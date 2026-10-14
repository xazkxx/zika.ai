from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MaterialReturn(Base):
    """生产退料单（对齐浩技云「生产管理 → 生产退料」）。

    融合改造要点：

    1. 退料是领料的**反向**单据：车间没用了的余料退回仓库，
       原材料现存量**增加**（inbound 流水）。与领料一样属于**纯库存单据**，
       只动库存、**不写财务流水**。

    2. 与领料完全镜像：头字段一一对应（关联计划 / 领料仓 / 车间 / 经办人），
       只是库存方向相反、单号前缀不同（退料 SCTL），并多一个「退料原因」。

    3. `related_type` 用 `production_return`（领料用 `production_issue`），
       这样变动查询里领料/退料能分开归类，一眼看出材料是发出去还是退回来。
    """

    __tablename__ = "material_returns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    return_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 关联来源（可空）——
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    plan_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 退料仓库（退回哪里）
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    workshop: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 退料车间
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 退料人
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 退料原因
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # draft 草稿 / submitted 已退料 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialReturnItem(Base):
    """退料明细：一行 = 一种退回仓库的原材料。"""

    __tablename__ = "material_return_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    material_return_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 生产退料单状态字典
MATERIAL_RETURN_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已退料",
    "cancelled": "已取消",
}
