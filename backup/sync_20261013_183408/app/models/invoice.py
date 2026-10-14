from datetime import datetime
import json

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Invoice(Base):
    """发票：OCR 识别结果持久化，支持财务同步与智能分析。"""

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
