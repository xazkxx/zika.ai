from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchaseReturn(Base):
    """采购退货单（对齐浩技云「采购管理 → 退货管理」）。

    融合改造要点：

    1. 采购退货是**真实单据**，与采购入库方向相反：把货退回给供应商，
       库存减少（outbound 流水）、应付冲减（purchase_return 财务流水）。
       因此**独立成表**，不塞进 purchase_orders —— 入库与退货的库存/财务
       方向完全相反，共表会让「删单冲销 / 现存量聚合 / 对账单」全乱掉。

    2. 与采购入库单的关联靠 `source_order_id`（退货时可选填来源入库单），
       便于溯源；不强制，允许直接手工录退货。

    3. 供应商信息在**创建时快照**（名称/联系人/电话/地址），与档案解耦：
       退货单是历史凭证，供应商改信息不能把旧退货单一起改掉。

    4. 财务口径：退货审核后自动写 `purchase_return` 应付流水（方向 out、
       金额为负即可冲减，或直接记一笔负数应付）。人工不允许手录。
    """

    __tablename__ = "purchase_returns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    return_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # —— 供应商快照（创建时带出，与档案解耦）——
    supplier_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 退货仓库
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 退货日期
    return_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 退货原因
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 退款方式
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 溯源：可选的来源入库单/采购单 ——
    source_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 金额 ——
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_chinese: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 金额大写（冗余，便于打印）

    # draft 草稿 / submitted 已退货 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseReturnItem(Base):
    """采购退货明细（退回商品清单）。

    与采购/销售明细一样存**商品快照**：退货单发出后就是历史凭证，
    商品改名改价后重印必须还是当初退回去的那份。
    """

    __tablename__ = "purchase_return_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    purchase_return_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 采购退货状态字典 —— 前端下拉与后端校验共用
PURCHASE_RETURN_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已退货",
    "cancelled": "已取消",
}
