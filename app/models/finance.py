from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinancialTransaction(Base):
    """财务流水 —— 业务事件驱动的记账中心。

    改造要点（「财务模块要和所有模块保持关联」）：
    1. 原有 related_order_id 是个裸整数，不知道指向哪张表；补 related_type 明确单据类型。
    2. 补 product_id / warehouse_id / project_id，让库存、生产、项目模块也能挂到财务。
    3. 补 direction（收/付方向）与 period（会计期间），支持按期间出报表。
    4. 补 occurred_at（业务发生日期），与 created_at（录入时间）区分。

    规矩：单据审核后由系统自动写流水，人工只能登记收付款与费用。
    """

    __tablename__ = "financial_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # 业务类型：receivable 应收 / payable 应付 / receipt 收款 / payment 付款 /
    #          cost 成本 / expense 费用 / income 收入 / scrap 报损 / overflow 报溢
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # 来源单据类型，取值见 DOC_TYPES（purchase_order / sales_order / inv_check ...）
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 来源单据号快照

    # 方向：in 流入（收/收入） / out 流出（付/成本/费用）
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)

    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 商品维度（库存/生产成本）
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 仓库维度（库存类）
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 项目维度（项目成本归集）

    # 资金账户维度（现金银行）：只有真正动了钱的流水才挂账户，见 app/models/bank.py 的口径说明
    bank_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 日常收支的类别（办公费 / 差旅费 / 利息收入…），候选来自数字字典 income_category / expense_category
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 经手人

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)

    occurred_at: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 业务发生日期 YYYY-MM-DD
    period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)  # 会计期间 YYYY-MM

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ---- 红冲（Reverse，2026-10-19）----------------------------------------
    # 只有**红字行**会填 reversal_of_id，指向被它冲掉的那条原始流水。
    # 反查"这条有没有被冲过"就靠它（`reversal_of_id == 本行 id` 存在 = 已冲销），
    # 不再另存一个 is_reversed 布尔 —— 两处状态一旦不同步，就会出现
    # 「显示已冲销、却还能再冲一次」这种自相矛盾的账。
    reversal_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 这笔收付款**实际冲抵到单据上**的金额（= min(收款额, 该单未付余额)）。
    # 预收/预付那部分不进单据，所以红冲时必须按它回退，不能按 amount：
    # 例：单欠 1000、收了 1500，applied=1000；若按 1500 回退，
    # 订单的 received_amount 会变成 -500（冲成了负数）。
    applied_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ---- 业财一体化（2026-10-22）：付款流水挂进项发票 ----------------------
    # 业务背景是"先款后票"：钱先付了，发票后到。这张表原来只有金额和单据，
    # 于是"付了钱但没有票"这件事在系统里**看不见** —— 既没法提醒去催票，
    # 也没法在汇算清缴时把"暂估"挑出来。
    #
    # `invoice_id` 就是那根挂票的钩子：付款登记时可以指定一张进项发票，
    # 挂上之后这张单的"未开票金额"立刻减少（完结闸、对账单同步生效）。
    # 可空：允许先付款后补票 —— 那正是"先款后票"的常态。
    invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 流水号（2026-10-22）。库里本来就有这一列（历史数据 7 行有值），但**模型里没映射**，
    # 于是新写的流水全是 NULL，对账单的「收款流水号」自然一片空白。
    # 现在补进模型并在 `_write_finance` 里自动生成：`FL<yyyymmdd><3位序号>`。
    # 对账时"这笔记账到底对应哪笔银行流水"就靠它来对。
    flow_no: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)


# 单据类型字典：财务流水 related_type 的合法取值。
# 「财务与所有模块关联」靠这张字典落地，将来新增模块时在这里登记即可。
DOC_TYPES: dict[str, str] = {
    "purchase_order": "采购订单",
    "purchase_in": "采购入库",
    "purchase_return": "采购退货",
    "sales_order": "销售订单",
    "sales_out": "销售开单",
    "sales_return": "销售退货",
    "receipt": "收款登记",
    "payment": "付款登记",
    "bank_transfer": "账户转账",
    "inv_check": "库存盘点",
    "inv_scrap": "报损",
    "inv_overflow": "报溢",
    "inv_transfer": "库存调拨",
    "production_order": "生产工单",
    "production_plan": "生产计划",
    "production_issue": "生产领料",
    "production_return": "生产退料",
    "production_in": "成品入库",
    "production_wage": "计件工资",
    "outsourcing": "委外加工",
    "project_cost": "项目费用",
    "invoice": "发票",
    "expense": "日常支出",
    "contract": "购销合同",
}
