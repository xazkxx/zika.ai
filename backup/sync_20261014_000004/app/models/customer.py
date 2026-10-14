from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 以下为对齐「浩技云进销存」客户档案补齐的字段，全部可空，不影响历史数据 ——
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 联系人
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 联系人电话
    tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 税号
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 开户行
    bank_account: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 开户账号
    level: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 客户级别
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 折扣
    credit_limit: Mapped[float | None] = mapped_column(Float, nullable=True)  # 信用额度
    init_receivable: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初应收
    init_invoice_debt: Mapped[float | None] = mapped_column(Float, nullable=True)  # 期初欠票
    relation_date: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 建立商业关系时间
    business_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务类型
    main_products: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 主营产品
    potential_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 潜在业务量/年
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
