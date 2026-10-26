from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 以下为对齐「浩技云进销存」供应商档案补齐的字段，全部可空，不影响历史数据 ——
    short_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 供应商简称
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 联系人
    main_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 主要联系人
    mobile: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 手机号码
    postcode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 邮编
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 开户行
    bank_account: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 账号
    # 开票电话（2026-10-23）：口径同 `Customer.invoice_phone`。
    invoice_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    init_payable: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初应付
    init_invoice_debt: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初欠票
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 纳税人识别号（2026-10-22，业财一体化）。
    # 为什么必须补：进项发票只能靠"对方是谁"来匹配单据，而名称是最不可靠的键 ——
    # 对方开票时常把"陕西送变电工程有限公司"写成"陕西送变电"或"…第一分公司"，
    # 一字之差就匹配失败。税号是税局发的唯一标识，OCR 认出来的准确率也远高于名称。
    # 口径与 `Customer.tax_no` 完全一致（同长度、同可空），匹配时先比税号、再退回名称。
    tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 所属供应商分类（`supplier_categories.id`）。不建外键，口径同 `Customer.category_id`。
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
