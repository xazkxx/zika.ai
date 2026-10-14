from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchaseOrder(Base):
    """采购单据。

    融合「浩技云进销存」后，单据不再只是"订单"，而是承担完整的
    结算链（应付 → 优惠 → 实付）与欠款链（本次欠款 → 前次欠款 → 累欠货款）。
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 单据头：仓库绑定与业务信息（融合改造新增，全部可空）——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 进货仓库
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 开单日期
    delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 送货日期
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 付款方式
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 联系人（下单时快照）
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 收货地址快照
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 结算链：应付 → 优惠 → 实付 ——
    payable_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 应付金额（明细合计）
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 优惠金额
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 实付金额
    is_invoiced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 是否开票

    # —— 欠款链：本次欠款 → 前次欠款 → 累欠货款 ——
    current_debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 本次欠款
    prev_debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 前次欠款
    total_debt: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 累欠货款


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 明细快照：打印单据时不需要再回查商品档案 ——
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 单位
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
