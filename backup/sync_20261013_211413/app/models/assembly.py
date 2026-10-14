"""组合拆卸单 —— 对齐浩技云「库存管理 → 组合拆卸」。

**它解决什么**：把若干子件打包成一个套装（组合），或把套装拆回单件（拆卸）。
典型场景是套装销售 —— 卖一套消防报警器，库存上要同时扣掉主板、天线、壳体……

**和调拨、BOM 的关系**

- 与**调拨**：都是"库存位置/形态变化、不产生应收应付"的内部作业，所以同样
  **不写财务流水**，只写库存流水。区别是调拨在同一商品上换仓库，
  组合拆卸在**不同商品**之间换形态（子件 ↔ 成品）。
- 与**BOM**：组合配方直接读 `production_boms`（母件 `product_id`、
  子件 `component_product_id`、单位用量 `quantity`）—— **不另建一套配方表**。
  BOM 本来就是干这个的，再存一份必然两边漂移。

**明细存快照**：单据落库时把子件的名称/规格/单位/用量固化成明细行。
理由是 BOM 会被改（今天用 4 颗螺丝，下个月改 6 颗），
但**历史单据重印必须还是当初那批料**。所以明细行不跟随 BOM 变动。

**只按一级展开**：组合一个成品时，只扣它 BOM 里的直接子件。
如果某个子件自己也是组合件，请对那个中间件单独开一张组合单 ——
自动多级展开会让"这一单到底动了什么库存"变得难以核对，
而库存单据的第一要求是可核对。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 单据类型：组合（子件 → 成品）/ 拆卸（成品 → 子件）
ASSEMBLY_TYPES: dict[str, str] = {
    "combo": "组合",
    "split": "拆卸",
}

# 单据状态：新建立即执行库存变动（与调拨、盘点同一约定），
# 取消＝删单并把流水冲销掉，不留"已作废但仍占库存"的中间态。
ASSEMBLY_STATUS: dict[str, str] = {
    "submitted": "已执行",
    "cancelled": "已取消",
}

# 单号前缀：组合 ZH / 拆卸 CX（与 CG 采购、XS 销售同一套规则：前缀+日期+3 位流水）
ASSEMBLY_PREFIX: dict[str, str] = {"combo": "ZH", "split": "CX"}


class AssemblyOrder(Base):
    """组合拆卸单头。一张单只针对**一个**成品（套装）。"""

    __tablename__ = "assembly_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    # combo=组合（成品增加）/ split=拆卸（成品减少），见 ASSEMBLY_TYPES
    doc_type: Mapped[str] = mapped_column(String(20), default="combo", nullable=False, index=True)

    # 进出仓库：组合拆卸都在同一个仓库内完成（形态转换，货不动仓）
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 成品（母件）
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 成品数量（几套）
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 子件合计数量：打印与列表上"这一单总共动了多少件货"，由明细汇总而来
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssemblyOrderItem(Base):
    """子件明细（快照）。组合时这些是要**扣减**的子件，拆卸时是要**增加**的子件。"""

    __tablename__ = "assembly_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assembly_order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 快照：BOM 改了不影响历史单据重印
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 总用量（已按成品数量折算：BOM 单位用量 × 成品数量；允许手工改成实际用量）
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
