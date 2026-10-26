"""客户 / 供应商分类树（**真实物理表**，每个账套各一棵）

## 为什么现在才建

改造前，客户档案的左侧树是「视图树」：按 `level`（客户级别）、`businesser`（业务员）
现场算出来；供应商按 `short_name` 的首字母算。那两棵树**拖不动、也建不了子级** ——
不是组件不行，而是底下根本没有层级数据可写。

这一版把层级落成真表，形状与 `product_categories` 保持一致（同一套前端树组件可以直接吃），
但有一处**刻意不同**，值得先说清楚：

| | 商品分类 | 客户 / 供应商分类 |
|---|---|---|
| 档案怎么挂 | `products.category` 存**节点名（字符串）** | `customers/suppliers.category_id` 存**节点 id** |
| 改名后果 | 历史商品的 `category` 变成孤儿字符串 | 档案自动跟着走，一处不用改 |

商品那边当初是为了「不迁移 262 个存量商品」才存名称；代价是**改个类别名就得批量刷商品**，
而且跨分支重名会有歧义。新表没有存量包袱，所以直接存 id —— 这是这次唯一想要"更好"的地方。

## 不建外键

全库只有 3 个外键，这是既有约定（见 `MEMORY.md`）。`category_id` 指向一张**账套内**的表，
不建 FK；改用三处应用层保证：

1. 写入前校验 id 存在（`erp_archive._assert_partner_category`）；
2. 删分类时先查有没有档案还挂在上面 → 409；
3. `GET` 时若发现档案指向不存在的 id（理论上不该有），前端按「未分类」处理，
   后端不因此 500。

## 同级重名：为什么是**两条**部分唯一索引

`UNIQUE (parent_id, name)` 在 PostgreSQL 里**挡不住两个顶级同名节点** ——
`NULL` 在唯一约束里被当作互不相等。而顶级恰恰是最容易重名的一层。

所以拆成两条**部分唯一索引**（partial unique index）：

- `parent_id IS NULL` 时只对 `name` 唯一 → 顶级不重名；
- `parent_id IS NOT NULL` 时对 `(parent_id, name)` 唯一 → 同级不重名。

路由层仍保留一次显式检查，只为了给出中文 400 提示（撞索引只会拿到一句英文
`duplicate key value violates unique constraint`，用户看不懂）。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _tree_table_args(table: str) -> tuple:
    """两张分类表共用的约束集合（索引名带表名前缀，避免与别的表撞名）。"""
    return (
        # 顶级不重名：UNIQUE(name) 只作用于 parent_id IS NULL 的行
        Index(
            f"ux_{table}_root_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        # 同级不重名：UNIQUE(parent_id, name) 只作用于非顶级行
        Index(
            f"ux_{table}_sibling_name",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
        # 空白名称在列表里就是一行"看不见的节点"，直接从库里堵掉；
        # 用 btrim 而不是 <> ''，否则 '   ' 能过。
        CheckConstraint("length(btrim(name)) > 0", name=f"ck_{table}_name_not_blank"),
    )


class CustomerCategory(Base):
    """客户分类（无限极）。

    `parent_id is None` = 顶级。层级深度**不设上限** —— 与 `product_categories`
    一致，深度由业务决定，代码里任何"最多 N 级"的假设都会在真实组织架构前失效。
    """

    __tablename__ = "customer_categories"
    __table_args__ = _tree_table_args("customer_categories")

    # ⚠️ 主键上刻意**不写** `index=True`：PG 的 PRIMARY KEY 自带 btree，
    #    再写一次会多出一个完全冗余的 `ix_customer_categories_id`
    #    （`product_categories` 那边就有这个冗余索引，新表不跟）。
    #    也别小看这点差异 —— 它决定了「脚本建的表」与「create_all 建的表」
    #    索引名集合是否一致，不一致就会在迁移报告里天天报"缺索引"。
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 同级排序。拖拽后由 `/move` 重排为 10、20、30…，留出空档方便手工插入
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupplierCategory(Base):
    """供应商分类（无限极）。结构与 `CustomerCategory` 完全一致，故不重复注释。"""

    __tablename__ = "supplier_categories"
    __table_args__ = _tree_table_args("supplier_categories")

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
