from datetime import datetime
from decimal import Decimal
import json

from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Invoice(Base):
    """发票：OCR 识别结果持久化，支持财务同步与智能分析。

    第 11 批补了三类字段（原来只有"识别结果"，没有"业务属性"和"原件"）：
    - **进销项** `direction`：进项 = 别人开给我们、销项 = 我们开给别人。
      靠**本公司税号**与发票的销售方/购买方税号比对判定（见 `detect_direction`）。
    - **红蓝字** `invoice_flag`：蓝字 = 正常发票，红字 = 冲红（负数）发票。
    - **原件** `source_*`：上传的 PDF/图片落盘后的相对路径与元信息。
      **在此之前原文件一个字节都不落盘**，"导出原始发票 PDF"就是靠这几个字段实现的。
    """

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    invoice_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    invoice_type: Mapped[str] = mapped_column(String(10), default="普票", nullable=False)  # 专票 / 普票 / 未知
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 对方单位名称
    invoice_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 发票代码
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 价税合计
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 税率 %
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)  # 税额
    excl_tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)  # 不含税额
    deducted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 专票是否已抵扣
    # 认证抵扣时间（2026-10-24）：由 update_invoice 在 deducted False→True 时自动落
    # 服务器时间，取消抵扣时清空。审计口径："这张专票是什么时候抵的"必须能回答。
    deducted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # —— 认证（2026-10-26）：进项专票的税局"勾选确认" ——
    # 为什么认证必须独立于抵扣：这是两个动作、两个时间点。
    #   「已认证待抵扣」是月底最需要盯的真实状态 —— 认证了但还没在申报表里抵扣，
    #   可能跨月、可能因为留抵暂不抵。压成一个 bool 后这个状态无处安放，
    #   财务只能靠 Excel 另记一本账。
    # 状态机（`update_invoice` 里强制）：
    #   未认证 --认证--> 已认证 --抵扣--> 已抵扣
    #   已抵扣时撤销认证 → 拒绝（税上不存在"没认证就抵扣"）；取消抵扣 → 认证保留。
    certified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 认证时间：**服务器**写入，前端传什么都不认。
    # KPI「本月已认证进项税额」按它的月份统计 —— 财务问的是"这个月认证了多少"，
    # 那是申报动作口径，不是开票日口径（按开票日会把上月票重复算进本月）。
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    buyer_tax_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    seller_tax_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    items_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 产品明细 JSON
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # OCR 原始文字

    # —— 第 11 批：业务属性 ——
    # input=进项 / output=销项 / unknown=待判定（本公司抬头没填时就是它）
    direction: Mapped[str] = mapped_column(String(10), default="unknown", nullable=False, index=True)
    # blue=蓝字（正常）/ red=红字（冲红）
    invoice_flag: Mapped[str] = mapped_column(String(10), default="blue", nullable=False)
    # manual=手工开票 / api=对接开票（税局数电平台）。⚠️ 只做状态留存，本批不做真对接
    issue_mode: Mapped[str] = mapped_column(String(10), default="manual", nullable=False)
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 关联档案（第 14 批，2026-10-18）：靠名字匹配发票是灾难 ——
    # 发票只有 `counterparty_name` 文本，而客户档案里同一家公司常有多个签约主体
    # （"XX公司""XX第一分公司""XX-某项目部"），字符串永远对不上。
    # 对账单曾经因此**一张发票都匹配不到**（见 REPORT-DIAG-TASK12.md）。
    # 现在落成 id：销项发票挂客户（customer_id），进项发票挂供应商（supplier_id）。
    # 各列都可空 —— 历史发票允许先不挂，由回填脚本按名字/税号尽力匹配。
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    contract_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 2026-10-26：进项发票挂供应商档案（镜像 customer_id）。
    # 在此之前进项只有 `seller_name` / `seller_tax_no` 纯文本，后果是
    # `services/invoice_match` 的候选打分对进项**永远拿不到**"按档案 id 命中"那一档，
    # 同类金额的候选分不出高下，自动挂入库单的成功率天然偏低。
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # —— 四流合一（2026-10-19）：发票挂到**具体单据** ——
    # 这是把"发票孤岛"接回业务流的唯一锚点。方向决定它指向哪张表：
    #   direction='output'（销项）→ sales_orders.id
    #   direction='input' （进项）→ purchase_orders.id
    #
    # ⚠️ 刻意不建外键、也**不自动匹配**：发票与单据的对应关系存在"一票多单（合并开票）"
    #    和"一单多票（分批开票）"两种真实情况，靠金额/名称去猜必然出错。
    #    这一列先只承载"1 张发票 → 1 张主单"，需要分摊时由对账聚合层按金额拆，
    #    不让主数据承担它表达不了的关系。
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # —— 第 11 批：原始文件（相对 storage_root 的路径，存绝对路径换盘就失效）——
    source_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_mime: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def items(self) -> list[dict]:
        """把 items_json 解析回明细列表，供序列化使用。"""
        if not self.items_json:
            return []
        try:
            return json.loads(self.items_json)
        except (TypeError, ValueError):
            return []

    @property
    def deduction_state(self) -> str:
        """认证/抵扣派生状态：`uncertified` / `certified` / `deducted`。

        放在模型上而不是各处各算一遍：列表、详情、summary 三处都要用，
        三处各写一次 `if deducted else if certified` 迟早在某一处写反
        （比如把"已认证"当成"已抵扣"报给财务，直接影响申报）。
        """
        if self.deducted:
            return DEDUCTION_DEDUCTED
        if self.certified:
            return DEDUCTION_CERTIFIED
        return DEDUCTION_UNCERTIFIED


# ===========================================================================
# 认证 / 抵扣（2026-10-26）
# ===========================================================================
# 认证 = 在税局平台"勾选确认"这张进项专票；抵扣 = 在当期申报表里把它抵掉。
# 顺序不可逆：没认证不能抵扣；但可以"认证了暂不抵扣"（留抵/跨期）。
DEDUCTION_UNCERTIFIED = "uncertified"
DEDUCTION_CERTIFIED = "certified"
DEDUCTION_DEDUCTED = "deducted"

DEDUCTION_STATE_LABELS = {
    DEDUCTION_UNCERTIFIED: "未认证",
    DEDUCTION_CERTIFIED: "已认证待抵扣",
    DEDUCTION_DEDUCTED: "已抵扣",
}


def is_special_invoice(invoice_type: str | None) -> bool:
    """票种是否为增值税**专用**发票（含电子专票）。

    ⚠️ 不要写 `invoice_type == "专票"`：编辑弹窗的票种下拉里就有「电子专票」，
    而 OCR 只产出「专票 / 普票 / 未知」。严格相等的后果是 —— 财务把票种改成
    「电子专票」后，行内的抵扣按钮和 summary 里的抵扣统计**同时消失**，
    而且不报任何错。判"专票"只认名称里含不含这两个字，与枚举写法解耦。
    """
    return "专票" in str(invoice_type or "")


# ===========================================================================
# 第 11 批：进销项判定
# ===========================================================================
# 进项 = 别人开给我们（我方是购买方）；销项 = 我们开给别人（我方是销售方）。
#
# 判据必须用**纳税人识别号**，不能用名称：名称会被 OCR 认错、会有简称与全称之别
# （实测库里就出现过同一个"陕西送变电工程有限公司"在一张票上是买方、
# 在另一张票上是卖方 —— 用名称去猜必然出错）。
#
# 税号比对不上时退一步用名称**完全相等**比对（去掉空白与括号后的全等），
# 不用"包含"—— "陕西送变电工程有限公司"包含于"陕西送变电工程有限公司第一分公司"
# 这种关系一旦按包含判定就会张冠李戴。
DIRECTION_INPUT = "input"
DIRECTION_OUTPUT = "output"
DIRECTION_UNKNOWN = "unknown"

DIRECTION_LABELS = {
    DIRECTION_INPUT: "进项",
    DIRECTION_OUTPUT: "销项",
    DIRECTION_UNKNOWN: "待判定",
}

INVOICE_FLAG_LABELS = {"blue": "蓝字", "red": "红字"}
ISSUE_MODE_LABELS = {"manual": "手工开票", "api": "对接开票"}

# —— 作废状态（P0-5，2026-10-26）——
# 发票以前是**物理删除**：删掉的票号、金额、税额、原件全部消失，
# 结果「进项税抵扣统计」少一张、对账单上多一笔无票收入，谁也说不清差在哪。
# 现在改成软作废：行保留、原件移入归档目录，`status` 落这个值。
INVOICE_VOIDED = "已作废"
INVOICE_STATUS_LABELS = {"草稿": "草稿", "已确认": "已确认", INVOICE_VOIDED: INVOICE_VOIDED}


def active_invoice_clause():
    """SQL 条件：**排除已作废发票**（`status` 为空的历史数据视为有效）。

    为什么用 `coalesce` 而不是 `status != '已作废'`：
    SQL 里 `NULL != '已作废'` 的结果是 NULL（不是 TRUE），
    直接写会把所有"没填过 status"的历史发票一起过滤掉 ——
    那是**静默丢数**，比多算一张作废票严重得多。
    """
    return func.coalesce(Invoice.status, "") != INVOICE_VOIDED


def _normalize_tax_no(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _normalize_name(value: str | None) -> str:
    text = str(value or "")
    for ch in " \t\r\n　()（）[]【】":
        text = text.replace(ch, "")
    return text


def detect_direction(
    *,
    own_tax_no: str | None,
    own_name: str | None,
    seller_tax_no: str | None,
    seller_name: str | None,
    buyer_tax_no: str | None,
    buyer_name: str | None,
) -> str:
    """判定这张发票是进项还是销项。判不出来返回 `unknown`（界面显示「待判定」）。

    **本公司抬头没填时一律返回 unknown** —— 宁可让用户看到"待判定"并去补公司信息，
    也不要凭"对方名称像不像供应商"去猜。猜错的进销项会直接算错税负统计，
    而且错了看不出来。
    """
    own_tax = _normalize_tax_no(own_tax_no)
    if own_tax:
        if _normalize_tax_no(seller_tax_no) == own_tax:
            return DIRECTION_OUTPUT  # 我方是销售方 → 我们开出去的
        if _normalize_tax_no(buyer_tax_no) == own_tax:
            return DIRECTION_INPUT  # 我方是购买方 → 别人开给我们的

    own = _normalize_name(own_name)
    if own:
        if _normalize_name(seller_name) == own:
            return DIRECTION_OUTPUT
        if _normalize_name(buyer_name) == own:
            return DIRECTION_INPUT

    return DIRECTION_UNKNOWN
