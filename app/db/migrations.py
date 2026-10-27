"""C1：版本化迁移注册表 + 迁移记录表（2026-10-27）。

为什么需要它
------------
这个项目的 schema 迁移长期**三套并行、各管一段**：

  1. `app/main.py` 里 17 组 `*_ADDITIONS` 内联 DDL + `ensure_schema_in` /
     `ensure_contract_module`（启动时幂等补列 / 转列 / 建索引）；
  2. 独立迁移脚本（`scripts/apply_phase1_migrations.py`、`migrate_*.py`、`backfill_*.py`…）；
  3. `scripts/` 80+ 一次性补丁（`_patch_*`、`phase2_patch_*`、`fix_*`…）。

三套各自为政的后果：不知道「这个库到底跑过哪些迁移」、同一列可能被两套机制各补一次、
一次性补丁散落在 scripts/ 里既难审计也难回滚。

新机制（最小实现，不引入 Alembic）
----------------------------------
每个迁移是一个 `(id, name, upgrade)` 三元组，登记进 `MIGRATIONS`，按 id 升序执行。
执行记录落进 `erp_migrations` 表（public 与各账套 schema 各一份），启动时只跑
「还没跑过的」—— 幂等由「已跑过就跳过」保证，不要求每段 SQL 自己幂等。

约束（写进 C1 纪律）
--------------------
C1 完成前**不删** main.py 的 `*_ADDITIONS` / `ensure_schema_in` / `ensure_contract_module`：
旧机制继续兜底，新机制先接管「新增迁移」，验证通过后再逐步把旧条目搬进注册表、最后才删旧机制。
"""

from __future__ import annotations

from sqlalchemy import Float, Numeric, inspect, text
from sqlalchemy.engine import Engine

from app.db.migration_columns import (
    COMPANY_COLUMNS,
    CONTRACT_COLUMNS,
    CUSTOMER_COLUMNS,
    FINANCE_COLUMNS,
    INVENTORY_COLUMNS,
    INVOICE_COLUMNS,
    PRODUCT_COLUMNS,
    PURCHASE_ITEM_COLUMNS,
    PURCHASE_ORDER_COLUMNS,
    PURCHASE_RETURN_ITEM_COLUMNS,
    QUOTATION_COLUMNS,
    SALES_ITEM_COLUMNS,
    SALES_ORDER_COLUMNS,
    SALES_RETURN_ITEM_COLUMNS,
    SUPPLIER_COLUMNS,
    USER_COLUMNS,
)

# —— C1-5：从 main.py 搬来的转列工具（金额 double→numeric(12,2) / 单价→numeric(14,4)）——
# 搬到这里后，`migrations.py` 是 schema 迁移的唯一实现处；main.py 不再保留迁移代码。
MONEY_COLUMNS_TO_NUMERIC: dict[str, tuple[str, ...]] = {
    "contracts": ("total_amount",),
    "contract_items": ("unit_price", "amount"),
    "quotations": ("total_amount",),
    "quotation_items": ("unit_price", "amount"),
}

PRICE_COLUMNS_TO_WIDE_NUMERIC: dict[str, tuple[str, ...]] = {
    "contract_items": ("unit_price",),
    "quotation_items": ("unit_price",),
}


def _ensure_numeric_money(conn, table: str, columns: tuple[str, ...]) -> list[str]:
    """把金额列从 `double precision` 幂等转成 `numeric(12, 2)`，返回**本次真正转换**的列。

    · 已经是 `numeric` 的直接跳过 —— 这是可重复执行的关键（启动时每次都跑）。
    · `USING round(col::numeric, 2)`：保留两位，不写 COALESCE ——
      可空列上的 NULL 必须保持 NULL（`round(NULL)` 仍是 NULL），
      把它抹成 0 会让"金额未填"和"金额为零"变成同一件事，对账单上分不清。
    · 表/列不存在（老库还没建、或某账套缺表）→ 静默跳过，不阻断启动。
    """
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return []
    existing = {column["name"]: column["type"] for column in inspector.get_columns(table)}
    converted: list[str] = []
    for column in columns:
        column_type = existing.get(column)
        if column_type is None:
            continue
        # ⚠️ 必须是 `isinstance(x, Float)` 而不是 `isinstance(x, Numeric)`：
        #    SQLAlchemy 的类层次是 `Float(Numeric)`、`DOUBLE_PRECISION(Float)` ——
        #    拿 Numeric 判"已经是定点数"会把 double precision 当成 numeric 放过。
        if isinstance(column_type, Numeric) and not isinstance(column_type, Float):
            continue
        conn.execute(
            text(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE NUMERIC(12, 2) USING round({column}::numeric, 2)"
            )
        )
        converted.append(column)
    return converted


def _ensure_wide_price(conn, table: str, columns: tuple[str, ...]) -> list[str]:
    """把单价列幂等放宽到 `numeric(14, 4)`，返回**本次真正改过**的列。

    单价是费率不是钱：`73.901 元/米` 被 (12,2) 存成 73.90，×580 就差 0.58 元。
    · 已经是 (14,4) 或更高小数位的 → 跳过（幂等的关键）。
    · `USING {col}::numeric(14,4)`：只改类型、不动值。
    · 表/列不存在 → 静默跳过，不阻断启动。
    """
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return []
    existing = {column["name"]: column["type"] for column in inspector.get_columns(table)}
    widened: list[str] = []
    for column in columns:
        column_type = existing.get(column)
        if column_type is None:
            continue
        scale = getattr(column_type, "scale", None)
        if not isinstance(column_type, Numeric) or isinstance(column_type, Float):
            continue
        if scale is not None and scale >= 4:
            continue
        conn.execute(
            text(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE NUMERIC(14, 4) USING {column}::numeric(14, 4)"
            )
        )
        widened.append(column)
    return widened


# 迁移注册表：只增不改。已发布过的条目改 id 或改内容会让老库状态错乱。
# 每条 = (id, name, upgrade)；upgrade(conn) 在当前 search_path 指向的 schema 内执行。
# 空的注册表 = 还没有任何「新机制」迁移 —— 这是 C1 的起点，后续批次往里追加。
MIGRATIONS: list[tuple[int, str, object]] = []

_TRACKING_TABLE = "erp_migrations"


def _ensure_tracking_table(conn) -> None:
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} ("
            "id INTEGER PRIMARY KEY, "
            "name VARCHAR(200) NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )


def _applied_ids(conn) -> set[int]:
    if not inspect(conn).has_table(_TRACKING_TABLE):
        return set()
    rows = conn.execute(text(f"SELECT id FROM {_TRACKING_TABLE}")).fetchall()
    return {int(row[0]) for row in rows}


def apply_pending(engine: Engine) -> list[int]:
    """按 id 升序跑还没跑过的迁移，返回本次新应用的 id 列表（空 = 无新迁移）。

    每个迁移与「记录它已跑」在同一事务里完成：upgrade 抛异常则整条回滚，
    不会出现「迁移跑了一半、记录却没写」或反过来 —— 这是版本化迁移的底线。

    调用方负责传**正确的 engine**：public 用默认 engine，账套 schema 用
    `tenant.ddl_engine_for(schema)`（search_path 不带 public，避免 `has_table`
    把 public 里的表误判成账套自己的表）。
    """
    if not MIGRATIONS:
        return []
    applied: list[int] = []
    with engine.begin() as conn:
        _ensure_tracking_table(conn)
        done = _applied_ids(conn)
        for mid, name, upgrade in sorted(MIGRATIONS, key=lambda m: m[0]):
            if mid in done:
                continue
            upgrade(conn)
            conn.execute(
                text(f"INSERT INTO {_TRACKING_TABLE} (id, name) VALUES (:id, :name)"),
                {"id": mid, "name": name},
            )
            applied.append(mid)
    return applied


# ===========================================================================
# 迁移条目（C1 起，这里逐条追加；id 只增不改）
# ===========================================================================
def _add_columns_if_missing(conn, table: str, additions: dict[str, str]) -> list[str]:
    """幂等补列：只给已存在、但缺这些列的表补，返回本次真正补上的列名。

    与 main.py `_add_missing_columns` 同口径（表不存在直接返回；逐列比对再 ALTER）。
    """
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return []
    existing = {column["name"] for column in inspector.get_columns(table)}
    added: list[str] = []
    for name, definition in additions.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            added.append(name)
    return added


def _migration_0001_invoice_attributes(conn) -> None:
    """C1-1/C1-3：发票业务属性 + 原件 + 挂档案（列定义见 migration_columns.INVOICE_COLUMNS）。"""
    _add_columns_if_missing(conn, "invoices", INVOICE_COLUMNS)


MIGRATIONS.append((1, "invoice business attributes & source file", _migration_0001_invoice_attributes))


def _migration_0002_product_attributes(conn) -> None:
    """C1-2a/C1-3：产品档案补列（含后追加的 tax_rate）。"""
    _add_columns_if_missing(conn, "products", PRODUCT_COLUMNS)


def _migration_0003_customer_attributes(conn) -> None:
    """C1-2a/C1-3：客户档案补列。"""
    _add_columns_if_missing(conn, "customers", CUSTOMER_COLUMNS)


def _migration_0004_supplier_attributes(conn) -> None:
    """C1-2a/C1-3：供应商档案补列。"""
    _add_columns_if_missing(conn, "suppliers", SUPPLIER_COLUMNS)


MIGRATIONS.extend(
    [
        (2, "product attributes", _migration_0002_product_attributes),
        (3, "customer attributes", _migration_0003_customer_attributes),
        (4, "supplier attributes", _migration_0004_supplier_attributes),
    ]
)


def _migration_0005_purchase_orders(conn) -> None:
    """C1-4A：采购单头补列（仓库绑定 / 结算链 / 欠款链）。"""
    _add_columns_if_missing(conn, "purchase_orders", PURCHASE_ORDER_COLUMNS)


def _migration_0006_sales_orders(conn) -> None:
    """C1-4A：销售单头补列。"""
    _add_columns_if_missing(conn, "sales_orders", SALES_ORDER_COLUMNS)


def _migration_0007_purchase_order_items(conn) -> None:
    """C1-4A：采购单明细补列（含 ORDER_ITEM 基础列）。"""
    _add_columns_if_missing(conn, "purchase_order_items", PURCHASE_ITEM_COLUMNS)


def _migration_0008_sales_order_items(conn) -> None:
    """C1-4A：销售单明细补列（含 ORDER_ITEM 基础列）。"""
    _add_columns_if_missing(conn, "sales_order_items", SALES_ITEM_COLUMNS)


def _migration_0009_purchase_return_items(conn) -> None:
    """C1-4A：采购退货明细补列。"""
    _add_columns_if_missing(conn, "purchase_return_items", PURCHASE_RETURN_ITEM_COLUMNS)


def _migration_0010_sales_return_items(conn) -> None:
    """C1-4A：销售退货明细补列。"""
    _add_columns_if_missing(conn, "sales_return_items", SALES_RETURN_ITEM_COLUMNS)


MIGRATIONS.extend(
    [
        (5, "purchase order header", _migration_0005_purchase_orders),
        (6, "sales order header", _migration_0006_sales_orders),
        (7, "purchase order items", _migration_0007_purchase_order_items),
        (8, "sales order items", _migration_0008_sales_order_items),
        (9, "purchase return items", _migration_0009_purchase_return_items),
        (10, "sales return items", _migration_0010_sales_return_items),
    ]
)


def _migration_0011_financial_transactions(conn) -> None:
    """C1-4B：资金流水补列（红冲 / 挂发票 / 流水号）。"""
    _add_columns_if_missing(conn, "financial_transactions", FINANCE_COLUMNS)


def _migration_0012_inventory_transactions(conn) -> None:
    """C1-4B：库存流水溯源补列。"""
    _add_columns_if_missing(conn, "inventory_transactions", INVENTORY_COLUMNS)


def _migration_0013_users(conn) -> None:
    """C1-4B：用户挂部门 / 角色 / 联系方式等补列。"""
    _add_columns_if_missing(conn, "users", USER_COLUMNS)


def _migration_0014_companies(conn) -> None:
    """C1-4B：账套抬头名称补列。"""
    _add_columns_if_missing(conn, "companies", COMPANY_COLUMNS)


MIGRATIONS.extend(
    [
        (11, "financial transactions", _migration_0011_financial_transactions),
        (12, "inventory transactions", _migration_0012_inventory_transactions),
        (13, "user profile columns", _migration_0013_users),
        (14, "company header", _migration_0014_companies),
    ]
)


def _migration_0015_contracts(conn) -> None:
    """C1-4C：合同主表补列（方向 / 原件 / 模板 / OCR）。"""
    _add_columns_if_missing(conn, "contracts", CONTRACT_COLUMNS)


def _migration_0016_quotations(conn) -> None:
    """C1-4C：报价单补列（关联合同）。"""
    _add_columns_if_missing(conn, "quotations", QUOTATION_COLUMNS)


def _migration_0017_contract_module_extras(conn) -> None:
    """C1-4C：合同模块的转列 / 纠偏 / 建索引（全部前置判断，老库安全）。

    - 金额列 `double -> numeric(12,2)`、单价列 -> `numeric(14,4)`：复用 main.py 的幂等
      转换函数（内部按列类型判断，已是 numeric 直接跳过；表/列不存在也跳过）。
    - `contracts.direction` 与 `contract_type` 对齐（只动自相矛盾的历史行）。
    - 两个索引 `CREATE INDEX IF NOT EXISTS`（索引名 per-schema，多账套不冲突）。
    """
    if not inspect(conn).has_table("contracts"):
        return
    for table, columns in MONEY_COLUMNS_TO_NUMERIC.items():
        _ensure_numeric_money(conn, table, columns)
    for table, columns in PRICE_COLUMNS_TO_WIDE_NUMERIC.items():
        _ensure_wide_price(conn, table, columns)
    conn.execute(
        text(
            "UPDATE contracts SET direction = 'in' "
            "WHERE contract_type = 'purchase' AND direction <> 'in'"
        )
    )
    conn.execute(
        text(
            "UPDATE contracts SET contract_type = 'purchase' "
            "WHERE direction = 'in' AND contract_type <> 'purchase'"
        )
    )
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_contracts_direction ON contracts (direction)"))
    if inspect(conn).has_table("quotations"):
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_quotations_contract_id ON quotations (contract_id)")
        )


def _migration_0018_journal_entries_flow_id(conn) -> None:
    """C1-4C：总账凭证 flow_id（凭证 ↔ 流水同生共死）。"""
    _add_columns_if_missing(conn, "journal_entries", {"flow_id": "INTEGER"})


MIGRATIONS.extend(
    [
        (15, "contract header", _migration_0015_contracts),
        (16, "quotation link", _migration_0016_quotations),
        (17, "contract module extras (numeric/index/direction)", _migration_0017_contract_module_extras),
        (18, "journal entry flow_id", _migration_0018_journal_entries_flow_id),
    ]
)


def _migration_0019_production_orders_bom_id(conn) -> None:
    """C1-5：生产单挂 BOM（bom_id）。"""
    _add_columns_if_missing(conn, "production_orders", {"bom_id": "INTEGER"})


def _migration_0020_production_boms(conn) -> None:
    """C1-5：BOM 清单层级补列（parent / code / 类型 / 层级 / 说明）。"""
    _add_columns_if_missing(
        conn,
        "production_boms",
        {
            "parent_id": "INTEGER",
            "name": "VARCHAR(150)",
            "code": "VARCHAR(80)",
            "bom_type": "VARCHAR(50) DEFAULT 'component'",
            "level": "INTEGER NOT NULL DEFAULT 0",
            "description": "VARCHAR(255)",
        },
    )


def _migration_0021_users_role(conn) -> None:
    """C1-5：用户角色列（NOT NULL DEFAULT 'staff' + 历史行回填），幂等。"""
    inspector = inspect(conn)
    if not inspector.has_table("users"):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" in columns:
        return
    conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'staff'"))
    conn.execute(text("UPDATE users SET role = 'staff' WHERE role IS NULL"))


MIGRATIONS.extend(
    [
        (19, "production order bom_id", _migration_0019_production_orders_bom_id),
        (20, "production bom hierarchy", _migration_0020_production_boms),
        (21, "users role column", _migration_0021_users_role),
    ]
)
