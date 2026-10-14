from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutsourcingOrder(Base):
    """委外加工单（对齐浩技云「生产管理 → 委外加工」）。

    融合改造要点：

    1. 委外加工 = **把材料发给外协厂加工，加工完再收回成品**，一张单同时
       包含两个方向：
         - 发出材料：`outsourcing_items` 明细，原材料现存量**减少**（outbound）
         - 收回成品：单据头的 product_id + quantity，成品现存量**增加**（inbound）
       两类流水共用 `related_type="outsourcing"` + 本单 id，删单时一次全冲。

    2. 与自制不同，委外要**付加工费**：单据头记 `process_fee`（加工费总额），
       审核后自动产生**应付**（transaction_type="payable"，挂外协厂 supplier_id），
       所以委外加工是**同时动库存与财务**的单据。

    3. 一张单收一种成品（product_id + quantity），发出材料可以多行 —— 这符合
       "一个加工件在一家外协厂加工"的常见场景，单据结构清晰不臃肿。
    """

    __tablename__ = "outsourcing_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 外协厂与仓库 ——
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 外协加工商
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 发料 / 收料仓

    # —— 单据头 ——
    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 加工产出（成品）——
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 收回的成品
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 收回数量
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 成品单位成本

    # —— 加工费（对外协厂的应付）——
    process_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 加工费总额
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 发出材料成本合计

    # draft 草稿 / submitted 已收发 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutsourcingItem(Base):
    """委外发出材料明细：一行 = 一种发给外协厂的原材料（出库）。"""

    __tablename__ = "outsourcing_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    outsourcing_order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 委外加工单状态字典
OUTSOURCING_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已收发",
    "cancelled": "已取消",
}
