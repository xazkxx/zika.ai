from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MaterialIssue(Base):
    """生产领料单（对齐浩技云「生产管理 → 生产领料」）。

    融合改造要点：

    1. 领料是**按生产计划把原材料从仓库发到车间**：原材料现存量**减少**
       （outbound 流水），是"材料出库"这个动作。它与调拨、盘点、报损报溢
       一样属于**纯库存单据** —— 只动库存、**不写财务流水**（材料的成本
       归集落在下游的成品入库环节，避免同一笔成本被记两次）。
       测试用反向断言锁死"不得产生 financial_transactions"。

    2. 可关联生产计划（`plan_id` + `plan_no` 快照）：这样一件计划领了多少料、
       退了多少料，都能顺着 `source` 反查，避免重复领料。

    3. 新增接口 `GET /material-issues/suggestion?plan_id=` 会按该计划的 BOM
       展开物料需求、扣减现存量后给出净需求清单，直接生成领料底稿 ——
       避免照着手写的领料单一样样敲（与盘点底稿同一思路，复用 MRP 引擎）。

    4. 明细改数量 / 改仓库时必须**整体重放库存**（先冲销再按新内容重放），
       否则会留下按旧明细扣过的库存（单边账）。
    """

    __tablename__ = "material_issues"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    issue_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 关联来源（可空：允许不挂计划的零星领料）——
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    plan_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 领料仓库（材料来源）
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    workshop: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 领料车间 / 用途
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 领料人
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 材料成本口径

    # draft 草稿 / submitted 已领料 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialIssueItem(Base):
    """领料明细：一行 = 一种要发出的原材料。"""

    __tablename__ = "material_issue_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    material_issue_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 生产领料单状态字典
MATERIAL_ISSUE_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已领料",
    "cancelled": "已取消",
}
