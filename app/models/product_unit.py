"""商品辅助单位 —— 一个商品可以有多个「比基本单位更大」的计量单位。

设计全文见 `_product_units_step3/DESIGN.md`。一句话：

    factor ＝ 「1 个本行单位 ＝ factor 个基本单位」
    基本单位数量 ＝ 录入数量 × factor            ← 只乘不除

## 为什么 `CHECK (factor >= 2)` 是这个设计的安全阀

它在**数据库层**一次性保证了两件事，前端和后端都写不错：

1. **换算方向不可能写反。**
   方向反了（存「1 箱 = 0.1 盒」）的后果不是"差一点"，而是**整笔静默消失**：
   `erp_common._apply_stock` 里是 `qty = int(quantity or 0)`，`qty == 0` 就直接
   `return None` —— 一条库存流水都不写，而且**不报错、不记日志**。
   实测 `int(3 × 0.1) = 0`：入库 3 箱、库存不动、界面提示"成功"。

2. **「基本单位必然是最小单位」这条规则免费成立。**
   因为每个辅助单位都被强制 ≥2 倍，所以不可能存在比基本单位还小的单位。

## 基本单位为什么不在本表里占一行

`products.unit`（VARCHAR(50)）**本身就是基本单位**。给基本单位也在本表插一行
（`factor=1, is_base=true`）会带来两个真相来源，且要给 261×3 个存量商品各插一行。
现在这样是：零迁移、零冗余、不可能不一致。

所以本表**只放辅助单位**。列出某商品全部可选单位 ＝ `[products.unit] + 本表启用行`。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductUnit(Base):
    __tablename__ = "product_units"

    # ⚠️ 这两个 CHECK 是**幂等建表**时唯一能拦住脏数据的地方：
    #    pydantic 的 `ge=2` 只管 API 入口，将来若有人直接写 SQL / 写脚本批量导入，
    #    就只剩这两条约束了。所以两边都留着，不要以为重复。
    __table_args__ = (
        CheckConstraint("factor >= 2", name="ck_product_units_factor_ge_2"),
        CheckConstraint("btrim(unit_name) <> ''", name="ck_product_units_name_not_blank"),
        # 同一商品下单位名唯一（"盒"下面不能有两个"箱"）
        Index("uq_product_units_product_unit", "product_id", "unit_name", unique=True),
        # 箱码唯一，但**允许多行都没条码** —— 所以必须是带 WHERE 的部分索引，
        # 普通 UNIQUE(product_id, bar_code) 在 PostgreSQL 下同样允许多个 NULL，
        # 但写明 WHERE 更贴口径（读表结构的人一眼知道"可空"）。
        Index(
            "uq_product_units_product_barcode",
            "product_id",
            "bar_code",
            unique=True,
            postgresql_where=text("bar_code IS NOT NULL"),
        ),
        Index("ix_product_units_product", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 指向 products.id。**刻意不加外键** —— 全库只有 3 个外键，本项目约定靠应用层保证。
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # 单位名，取值对齐全局字典 product_unit（箱/包/盒/打/托盘…）。
    # 与 products.unit、purchase_order_items.unit 同为 VARCHAR(50)，口径一致。
    unit_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 换算率：1 个本行单位 = factor 个基本单位。见模块 docstring。
    factor: Mapped[int] = mapped_column(Integer, nullable=False)
    # 该辅助单位自己的进价 / 售价（用户 2026-10-16 拍板：要带独立进价/售价）。
    # 3a 阶段**只存不用** —— 没有任何计算读它，3b/3c 接单据时才会用到。
    # 类型跟 products.purchase_price 一致（Float），不引 NUMERIC 造成口径分裂。
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bar_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 「默认辅助单位」（用户 2026-10-16 拍板 A）：它的 factor 会被同步写进
    # products.pack_qty，让那个原本没人读的死字段有一个唯一编辑入口。
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 停用而非删除：删了会切断历史单据的追溯（虽然 3a 还没有单据引用它）。
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
