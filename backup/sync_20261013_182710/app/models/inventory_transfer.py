from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventoryTransfer(Base):
    """库存调拨单（对齐浩技云「库存管理 → 调拨管理」）。

    融合改造要点：

    1. 调拨是**同一企业内部的库存位置转移**：货物从调出仓库搬到调入仓库，
       总量不变、资产总额不变。因此它**不写财务流水**（既不产生应收应付，
       也不产生成本），只写库存流水 —— 这是行业标准做法，DOC_TYPES 里的
       `inv_transfer` 仅用于库存流水溯源与变动查询归类。

    2. 一份调拨单会为每条明细生成**两条方向相反的库存流水**：
       调出仓库 outbound（减）、调入仓库 inbound（加）。两条流水共用
       `related_type="inv_transfer"` + `related_order_id`=本单 id，所以删单时
       `_revert_stock` 一次把两条都冲掉，调入仓与调出仓同时复原。

    3. 调出仓库与调入仓库必须不同（后端校验），否则就是原地打转。

    4. 商品在明细里存**快照**（名称/规格/单位）：调拨单是历史凭证，
       商品改名后重印必须还是当初调拨的那份。
    """

    __tablename__ = "inventory_transfers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transfer_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 单据头 ——
    from_warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)  # 调出仓库（库存减少）
    to_warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)  # 调入仓库（库存增加）
    transfer_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 调拨日期
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 经办人
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 调拨原因
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计：调拨不涉金额，用总数量做合计与打印 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # draft 草稿 / submitted 已调拨 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryTransferItem(Base):
    """库存调拨明细（调拨商品清单，只记数量，不涉金额）。"""

    __tablename__ = "inventory_transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    inventory_transfer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 成本单价（仅打印参考）
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 调拨单状态字典 —— 前端下拉与后端校验共用
TRANSFER_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已调拨",
    "cancelled": "已取消",
}
