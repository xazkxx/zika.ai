from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinishedGoodsReceipt(Base):
    """成品入库单（对齐浩技云「生产管理 → 成品入库」）。

    融合改造要点：

    1. 成品入库是生产链路的**收口环节**：车间把生产好的成品交回仓库，
       成品现存量**增加**（inbound 流水，related_type="production_in"）。

    2. 与领料/退料/调拨不同，成品入库**同时写财务成本流水**
       （transaction_type="cost"，direction="in"，金额=本次入库成本）——
       因为这一步是"在制品 → 产成品"的价值结转，落账才有意义。
       它用 `cost` 类型，不影响应收应付余额（只进成本口径的报表）。

    3. 可关联生产计划（`plan_id`）：计划 → 领料 → 退料 → 成品入库 形成
       完整闭环，每张单都能顺着计划号反查。
    """

    __tablename__ = "finished_goods_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    receipt_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 关联来源（可空）——
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    plan_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 成品入库仓
    receipt_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    workshop: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 生产车间
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 交库人 / 验收人
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 入库成本口径

    # draft 草稿 / submitted 已入库 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinishedGoodsReceiptItem(Base):
    """入库明细：一行 = 一种要交库的成品。"""

    __tablename__ = "finished_goods_receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    finished_goods_receipt_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 单位成本
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 成品入库单状态字典
FINISHED_GOODS_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已入库",
    "cancelled": "已取消",
}
