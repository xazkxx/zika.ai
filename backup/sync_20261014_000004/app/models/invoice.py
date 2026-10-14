from datetime import datetime
import json

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
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
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 价税合计
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 税率 %
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 税额
    excl_tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 不含税额
    deducted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 专票是否已抵扣
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
