from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductionPlan(Base):
    """生产计划单（对齐浩技云「生产管理 → 生产计划」）。

    融合改造要点：

    1. 生产计划是**排产意图**，不是业务发生：它只说明"打算在什么时候、
       用哪个车间仓、生产多少件什么产品"，**既不写库存流水、也不写财务流水**。
       这与报价单同属"前置单据"，测试里用反向断言把这条锁死。

    2. 它是整条生产链路的起点：MRP 运算按计划展开物料需求 → 生产领料按计划
       领料 → 生产退料退回余料 → 成品入库把产出记回库存。所以计划单要能被
       下游单据按 `source_plan_id` 反查（避免重复领料 / 重复入库）。

    3. `plan_type` 区分自制 / 委外：自制走车间领料入库，委外把半成品发给
       外协厂加工（委外加工单另行登记）。字段一致，只有工序归属不同。

    4. 明细可挂 BOM（`bom_id`），MRP 与领料按它展开；不挂就按成品档案 + 手工
       明细走，保留"还没建 BOM 也能先排产"的兼容性。
    """

    __tablename__ = "production_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    plan_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # self 自制 / outsource 委外
    plan_type: Mapped[str] = mapped_column(String(20), default="self", nullable=False, index=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 生产车间仓 / 领料仓
    plan_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 计划日期
    delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 计划完工日期
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 计划员
    workshop: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 车间 / 产线

    # —— 关联来源（可空：允许手工排产）——
    source_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 关联销售订单
    source_order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 合计 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 计划成本口径

    # draft 草稿 / planned 已计划 / released 已下达 / closed 已关闭 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductionPlanItem(Base):
    """生产计划明细 = 一行一个要生产的成品（或半成品）。"""

    __tablename__ = "production_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    production_plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 计划生产数量
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 计划单位成本
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    bom_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 关联 BOM 根节点
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 生产计划状态字典 —— 前端下拉与后端校验共用
PRODUCTION_PLAN_STATUS: dict[str, str] = {
    "draft": "草稿",
    "planned": "已计划",
    "released": "已下达",
    "closed": "已关闭",
    "cancelled": "已取消",
}

# 计划类型字典 —— 值里带单号前缀与说明，业务代码不写 if
PLAN_TYPES: dict[str, dict[str, str]] = {
    "self": {"label": "自制", "prefix": "SCJH"},
    "outsource": {"label": "委外", "prefix": "WWJH"},
}
