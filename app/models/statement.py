"""增强版对账单（第 13 批 · 模块 4，本模块最难的一张表）。

为什么必须拆成"头部 + 明细"两张表：

· **头部**是"这一期跟这个往来单位结了多少钱"的**汇总口径**，要直接打印给客户/供应商，
  所以必须能一次查出全部合计（含期初、应收余额、预收余额）。
· **明细**是"这笔钱是哪几份合同/哪几张发票/哪几笔收款构成的"，一行一个业务事实，
  带自己的业务日期与发票状态。

⚠️ 头部里的合计是**冗余快照**（denormalized），不是实时算的。理由：
对账单一旦发给对方就是**法律意义上的凭证**，事后不能因为单据被改而悄悄变数。
重算只能由"重新生成对账单"这个显式动作触发（第二阶段 `POST /statements/{id}/recalc`）。

金额口径（全部 Numeric(12,2)，禁止 float）：

    未开票金额   = 合同金额 − 已开票金额
    剩余未收/付  = max(0, 合同金额 − 已收/已付 − 预收已核销)  ← 2026-10-22 用户拍板加下限
    应收账款余额 = 期初应收 + 本期已开票 − 本期已收 − 预收已核销
    预收账款余额 = 本期预收 − 预收已核销

`remaining` 与 `receivable_balance` **不是同一个数**，别合并：
前者只针对"本期这几份合同"，后者是"这个客户在账上总体还欠我多少"（含期初与往期）。
把两者混成一个字段，财务对账时永远扯不清是"这份合同的差"还是"整个客户的差"。
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# 金额列统一精度：Numeric(12, 2) → 最大 9,999,999,999.99
MONEY = Numeric(12, 2)


class Statement(Base):
    """对账单头部（一客户/供应商 × 一个账期 = 一张对账单）。"""

    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    statement_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 方向与往来单位 ——
    # in  = 应付（我方采购，对方是供应商）
    # out = 应收（我方销售，对方是客户）
    direction: Mapped[str] = mapped_column(String(10), default="out", server_default="out", nullable=False)
    # customer / supplier —— 与 contracts.party_type 同口径
    party_type: Mapped[str] = mapped_column(String(20), default="customer", server_default="customer", nullable=False)
    # ⚠️ 多态引用（customer 或 supplier），**故意不加外键**：
    #    一个外键只能指向一张表。档案删了，对账单作为凭证必须还能打开 → 靠下面的快照字段兜底。
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    party_name: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 快照
    party_tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 快照（开票用）

    # —— 账期 ——
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)  # YYYY-MM-DD
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    statement_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 制单日期
    currency: Mapped[str] = mapped_column(String(10), default="CNY", server_default="CNY", nullable=False)

    # —— 汇总（快照，见文件头）——
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 期初应收/应付
    contract_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 合同金额合计
    invoiced_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 已开票金额
    uninvoiced_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 未开票金额
    received_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 已收/已付
    prepaid_received: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 本期预收/预付发生额
    prepaid_applied: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 预收已核销
    prepaid_balance: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 预收账款余额
    receivable_balance: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 应收账款余额
    outstanding_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)  # 剩余未收/未付

    item_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # draft 草稿 / confirmed 已确认 / sent 已发送对方 / void 作废
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=func.now(), nullable=True
    )

    # CASCADE：明细是头部的组成部分，没有独立存在的意义
    items = relationship(
        "StatementItem",
        back_populates="statement",
        cascade="all, delete-orphan",
        order_by="StatementItem.line_no",
        lazy="selectin",
    )

    __table_args__ = (
        # 账龄/对账列表最常用的过滤：某往来单位按账期倒序
        Index("ix_statements_party_period", "party_type", "party_id", "period_end"),
        Index("ix_statements_direction_status", "direction", "status"),
    )


class StatementItem(Base):
    """对账单明细（一行 = 一个业务事实：一份合同 / 一张发票 / 一笔收款）。"""

    __tablename__ = "statement_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # CASCADE：删头部自动删明细（这是**新表**，可以放心加外键）
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    # —— 业务日期（需求明确要求行级，不是账期级）——
    business_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # —— 溯源：这一行是从哪来的 ——
    # contract 合同 / order 订单 / inbound 入库 / outbound 出库
    # invoice 发票 / receipt 收款 / payment 付款 / opening 期初
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 关联合同：合同被删不该抹掉历史对账行 → SET NULL（快照字段仍在）
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contract_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 快照
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 摘要（打印在明细行上）

    # —— 金额（口径见文件头公式）——
    contract_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    invoiced_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    uninvoiced_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    received_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    # 本期预收/预付发生额：只有"单独收了一笔预收款"的行才有值，
    # 合同行留 0。头部 `prepaid_received` 是它的合计（compute_totals 汇总）。
    prepaid_received: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    prepaid_applied: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)
    outstanding_amount: Mapped[Decimal] = mapped_column(MONEY, default=0, server_default="0", nullable=False)

    # —— 发票状态（需求明确要求行级）——
    # none 未开 / partial 部分开 / full 已开
    invoice_status: Mapped[str] = mapped_column(String(10), default="none", server_default="none", nullable=False)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    statement = relationship("Statement", back_populates="items")


# ===========================================================================
# 字典与纯函数（第二阶段的路由直接复用，别在路由里重写一套）
# ===========================================================================
STATEMENT_DIRECTIONS: dict[str, str] = {
    "in": "应付（采购）",
    "out": "应收（销售）",
}

STATEMENT_STATUS: dict[str, str] = {
    "draft": "草稿",
    "confirmed": "已确认",
    "sent": "已发送",
    "void": "作废",
}

STATEMENT_INVOICE_STATUS: dict[str, str] = {
    "none": "未开票",
    "partial": "部分开票",
    "full": "已开票",
}

STATEMENT_SOURCE_TYPES: dict[str, str] = {
    "contract": "合同",
    "order": "订单",
    "inbound": "入库单",
    "outbound": "出库单",
    "invoice": "发票",
    "receipt": "收款",
    "payment": "付款",
    "opening": "期初",
}

ZERO = Decimal("0.00")


def _dec(value) -> Decimal:
    """任何输入 → 两位小数的 Decimal。空值/脏值一律按 0 处理。

    绝不用 float 中转：`Decimal(str(0.1 + 0.2))` 是 0.30000000000000004，
    对账单上就会印出这种数字。

    ⚠️ 舍入必须显式写 `ROUND_HALF_UP`（四舍五入）：Decimal 的**默认**是
    `ROUND_HALF_EVEN`（银行家舍入），100.005 会被舍成 100.00 ——
    国内对账/开票一律按四舍五入，差这一分钱客户会当场指出来。
    """
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _field(item, name: str):
    """从 ORM 对象**或 dict** 里取字段。

    ⚠️ 这里必须显式分流，不能只写 `getattr(item, name, None)`：
    对 dict 用 `getattr` 恒返回默认值 —— 函数会安静地算出一堆 0.00，
    调用方（Schema / 重算接口）拿到的"合计"全是零而不会报错。
    """
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def derive_item_amounts(item) -> dict[str, Decimal]:
    """按需求公式推导一行的「未开票」与「剩余未收/付」。

    入参可以是 StatementItem，也可以是 schema/字典（只要字段名一致）。
    返回 {'uninvoiced_amount', 'outstanding_amount'}，**只算不写**，
    由调用方决定是否落到对象上（生成阶段写、查询阶段随时可重算）。
    """
    contract = _dec(_field(item, "contract_amount"))
    invoiced = _dec(_field(item, "invoiced_amount"))
    received = _dec(_field(item, "received_amount"))
    prepaid = _dec(_field(item, "prepaid_applied"))
    return {
        # 未开票 = 合同金额 − 已开票
        "uninvoiced_amount": contract - invoiced,
        # 剩余未收/付 = max(0, 合同金额 − 已收/已付 − 预收已核销)
        #
        # ⚠️ 2026-10-22 用户拍板加下限 0（原来允许负数）。为什么要加：
        #   绝大多数业务是"订单 → 出库 → 开票 → 收款"，**根本没有合同**，
        #   合同额记 0，于是 0 − 已收 = "−120"，看着像客户多付了钱。
        #   多收的钱本来就不属于"剩余未收"，它体现在**预收余额**（prepaid_balance）里。
        #   注意：期末应收（receivable_balance）**不受影响** —— 它走的是
        #   `期初 + 已开票 − 已收 − 预收已核销`，那才是欠不欠钱的权威口径。
        "outstanding_amount": max(ZERO, contract - received - prepaid),
    }


def infer_invoice_status(contract_amount, invoiced_amount) -> str:
    """由金额推导发票状态，避免前端手填出错。"""
    contract = _dec(contract_amount)
    invoiced = _dec(invoiced_amount)
    if invoiced <= ZERO:
        return "none"
    if contract > ZERO and invoiced >= contract:
        return "full"
    return "partial"


def compute_totals(items, opening_balance=0) -> dict[str, Decimal]:
    """把明细行汇总成头部的 10 个金额。

    纯函数（不碰 DB），第二阶段 `POST /statements/{id}/recalc` 直接调它。
    **所有加减都在 Decimal 上做**，最后统一两位小数。
    """
    rows = list(items or [])
    contract = sum((_dec(_field(r, "contract_amount")) for r in rows), ZERO)
    invoiced = sum((_dec(_field(r, "invoiced_amount")) for r in rows), ZERO)
    received = sum((_dec(_field(r, "received_amount")) for r in rows), ZERO)
    prepaid_applied = sum((_dec(_field(r, "prepaid_applied")) for r in rows), ZERO)
    prepaid_received = sum((_dec(_field(r, "prepaid_received")) for r in rows), ZERO)

    opening = _dec(opening_balance)
    return {
        "opening_balance": opening,
        "contract_amount": contract,
        "invoiced_amount": invoiced,
        "uninvoiced_amount": contract - invoiced,
        "received_amount": received,
        "prepaid_received": prepaid_received,
        "prepaid_applied": prepaid_applied,
        # 预收账款余额 = 本期预收 − 预收已核销
        "prepaid_balance": prepaid_received - prepaid_applied,
        # 应收账款余额 = 期初 + 本期已开票 − 已收 − 预收已核销
        "receivable_balance": opening + invoiced - received - prepaid_applied,
        # 剩余未收/付 = **逐行** max(0, 合同金额 − 已收/已付 − 预收已核销) 再求和。
        # 必须先逐行夹到 0 再相加：先加后夹会让"某客户多收 100、另一单还欠 100"
        # 互相抵消成 0，合计与明细表就对不上了（打印稿上两处数字不一致最要命）。
        "outstanding_amount": sum(
            (
                max(
                    ZERO,
                    _dec(_field(row, "contract_amount"))
                    - _dec(_field(row, "received_amount"))
                    - _dec(_field(row, "prepaid_applied")),
                )
                for row in rows
            ),
            ZERO,
        ),
    }
