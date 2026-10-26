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
    init_payable: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初应付
    init_invoice_debt: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初欠票
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 所属供应商分类（`supplier_categories.id`）。不建外键，口径同 `Customer.category_id`。
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
