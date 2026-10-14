from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventoryAdjustment(Base):
    """库存报损报溢单（对齐浩技云「库存管理 → 报损报溢」）。

    融合改造要点：

    1. 报损与报溢是**同一张单据表的两个方向**，用 `adjust_type` 区分：
       - `scrap` 报损：货坏了 / 丢了 / 过期了，现存量**减少**（outbound）
       - `overflow` 报溢：盘出多余的货 / 入库少记了，现存量**增加**（inbound）
       两者字段完全对称，只有库存方向相反，所以合并成一张表 + 一个字典，
       而不是像采购/销售退货那样拆成两张表。

    2. 与调拨、盘点同属**纯库存单据**：只写库存流水、**不写财务流水**。
       `DOC_TYPES` 里的 `inv_scrap` / `inv_overflow` 只用于库存流水溯源与
       变动查询归类。测试用反向断言锁死"不得产生 financial_transactions"。

    3. 明细数量恒为正数（业务填「坏了 3 件」，不是「-3 件」），
       方向完全由单据头的 `adjust_type` 决定 —— 避免同一张单里正负混排。
    """

    __tablename__ = "inventory_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    adjust_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # scrap 报损（减库存）/ overflow 报溢（加库存）
    adjust_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)  # 发生仓库
    adjust_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 单据日期
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 经办人
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 报损报溢原因
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 成本口径金额

    # draft 草稿 / submitted 已生效 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryAdjustmentItem(Base):
    """报损报溢明细（数量恒正，方向看单据头的 adjust_type）。"""

    __tablename__ = "inventory_adjustment_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    inventory_adjustment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 报损报溢类型字典 —— 值里带库存方向，业务代码直接读 direction，不写 if 分支
ADJUST_TYPES: dict[str, dict[str, str]] = {
    "scrap": {"label": "报损", "direction": "outbound", "prefix": "BS", "doc_type": "inv_scrap"},
    "overflow": {"label": "报溢", "direction": "inbound", "prefix": "BY", "doc_type": "inv_overflow"},
}

# 报损报溢单状态字典
ADJUSTMENT_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已生效",
    "cancelled": "已取消",
}
