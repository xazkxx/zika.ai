"""C1 版本化迁移机制的单元测试（2026-10-27）。

钉住三件事：
  1. `apply_pending` 按 id 升序跑「还没跑过」的迁移，并写进 `erp_migrations` 记录；
  2. 幂等：已跑过的迁移再来一次是 no-op（不会重复执行）；
  3. 事务性：迁移抛异常时整条回滚 —— 不会出现「表建了一半、记录却没写」或反过来。

用一次性高 id（90 万段）避免与将来真实迁移撞号，跑完清理 marker 表与记录。
"""

import uuid

from sqlalchemy import inspect, text

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
from app.db.migrations import MIGRATIONS, _TRACKING_TABLE, apply_pending
from app.db.session import engine
from app.main import app  # noqa: F401 —— 确保 create_app 已跑、目标表存在（与全量测试同口径）


def _probe_id() -> int:
    # 90 万段：真实迁移从 1 开始，这里刻意远离，保证永不撞号
    return 900000 + (uuid.uuid4().int % 10000)


def test_apply_pending_runs_and_records_once():
    marker = f"_migration_probe_{uuid.uuid4().hex[:8]}"
    mid = _probe_id()

    def upgrade(conn):
        conn.execute(text(f"CREATE TABLE IF NOT EXISTS {marker} (id INTEGER)"))

    entry = (mid, "test probe", upgrade)
    MIGRATIONS.append(entry)

    try:
        applied = apply_pending(engine)
        assert applied == [mid], "新迁移应该被应用一次"

        # 幂等：已跑过，再来一次是 no-op
        assert apply_pending(engine) == []

        with engine.begin() as conn:
            assert inspect(conn).has_table(marker), "marker 表应该存在"
            rows = conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id = :id"), {"id": mid}
            ).fetchall()
            assert len(rows) == 1, "迁移记录应该写一条"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {marker}"))
            conn.execute(text(f"DELETE FROM {_TRACKING_TABLE} WHERE id = :id"), {"id": mid})
        MIGRATIONS.remove(entry)


def test_apply_pending_rolls_back_on_failure():
    marker = f"_migration_boom_{uuid.uuid4().hex[:8]}"
    mid = _probe_id()

    def boom(conn):
        conn.execute(text(f"CREATE TABLE IF NOT EXISTS {marker} (id INTEGER)"))
        raise RuntimeError("boom")

    entry = (mid, "test boom", boom)
    MIGRATIONS.append(entry)

    try:
        raised = False
        try:
            apply_pending(engine)
        except RuntimeError as exc:
            raised = True
            assert str(exc) == "boom"
        assert raised, "迁移抛异常应该向上传播"

        # 事务回滚：marker 表没留下、记录也没写
        with engine.begin() as conn:
            assert not inspect(conn).has_table(marker), "异常后 marker 表应该被回滚"
            rows = conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id = :id"), {"id": mid}
            ).fetchall()
            assert rows == [], "异常后不应写入迁移记录"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {marker}"))
        MIGRATIONS.remove(entry)


def test_invoice_migration_registered_and_idempotent():
    """第一条真实迁移（id=1）：新库应用/记录，已应用过不重复。"""
    assert 1 in {mid for mid, _, _ in MIGRATIONS}, "注册表里应有 id=1 的发票迁移"

    # 先应用一次，确保记录表存在（首次可能是 no-op，因为 create_all/补列已把列建好）
    apply_pending(engine)
    # 清掉 id=1 的记录，模拟「这个库还没跑过第一条」
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {_TRACKING_TABLE} WHERE id = 1"))

    applied = apply_pending(engine)
    assert 1 in applied, "清掉记录后 id=1 应被重新应用"
    assert apply_pending(engine) == [], "已应用过，第二次不应重复"

    # 无论新库（create_all 建好列）还是老库（迁移补列建好列），这些列都必须在
    with engine.begin() as conn:
        cols = {column["name"] for column in inspect(conn).get_columns("invoices")}

    assert set(INVOICE_COLUMNS) <= cols


def test_migration_adds_columns_to_legacy_table():
    """老库缺列路径：真实 ALTER 能补齐 INVOICE_COLUMNS 全部列，且第二次为空。"""
    from app.db.migrations import _add_columns_if_missing

    probe = "_c1_probe_legacy_invoices"
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {probe}"))
            conn.execute(text(f"CREATE TABLE {probe} (id INTEGER PRIMARY KEY, invoice_no VARCHAR(64))"))
            added = _add_columns_if_missing(conn, probe, INVOICE_COLUMNS)
        assert set(added) == set(INVOICE_COLUMNS), "老库缺全部列，应一次补齐"

        with engine.begin() as conn:
            assert _add_columns_if_missing(conn, probe, INVOICE_COLUMNS) == [], "已补齐，再补应为空"
            cols = {column["name"] for column in inspect(conn).get_columns(probe)}
        assert set(INVOICE_COLUMNS) <= cols
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {probe}"))


def test_master_data_migrations_registered_and_applied():
    """C1-2a：产品/客户/供应商三组补列迁移已注册并已应用，列均在。"""
    assert {2, 3, 4} <= {mid for mid, _, _ in MIGRATIONS}

    apply_pending(engine)  # 幂等，确保已应用
    with engine.begin() as conn:
        applied = {
            row[0]
            for row in conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id IN (2, 3, 4)")
            ).fetchall()
        }
    assert applied == {2, 3, 4}

    for table, columns in (
        ("products", PRODUCT_COLUMNS),
        ("customers", CUSTOMER_COLUMNS),
        ("suppliers", SUPPLIER_COLUMNS),
    ):
        with engine.begin() as conn:
            cols = {column["name"] for column in inspect(conn).get_columns(table)}
        assert set(columns) <= cols, f"{table} 缺列：{set(columns) - cols}"


def test_order_migrations_registered_and_applied():
    """C1-4A：采购/销售单头与明细（含退货明细）迁移已注册并应用，列齐全。"""
    assert {5, 6, 7, 8, 9, 10} <= {mid for mid, _, _ in MIGRATIONS}

    apply_pending(engine)
    with engine.begin() as conn:
        applied = {
            row[0]
            for row in conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id IN (5, 6, 7, 8, 9, 10)")
            ).fetchall()
        }
    assert applied == {5, 6, 7, 8, 9, 10}

    for table, columns in (
        ("purchase_orders", PURCHASE_ORDER_COLUMNS),
        ("sales_orders", SALES_ORDER_COLUMNS),
        ("purchase_order_items", PURCHASE_ITEM_COLUMNS),
        ("sales_order_items", SALES_ITEM_COLUMNS),
        ("purchase_return_items", PURCHASE_RETURN_ITEM_COLUMNS),
        ("sales_return_items", SALES_RETURN_ITEM_COLUMNS),
    ):
        with engine.begin() as conn:
            cols = {column["name"] for column in inspect(conn).get_columns(table)}
        assert set(columns) <= cols, f"{table} 缺列：{set(columns) - cols}"


def test_finance_inventory_user_company_migrations():
    """C1-4B：财务/库存流水、用户、公司补列迁移已注册并应用。"""
    assert {11, 12, 13, 14} <= {mid for mid, _, _ in MIGRATIONS}

    apply_pending(engine)
    with engine.begin() as conn:
        applied = {
            row[0]
            for row in conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id IN (11, 12, 13, 14)")
            ).fetchall()
        }
    assert applied == {11, 12, 13, 14}

    for table, columns in (
        ("financial_transactions", FINANCE_COLUMNS),
        ("inventory_transactions", INVENTORY_COLUMNS),
        ("users", USER_COLUMNS),
        ("companies", COMPANY_COLUMNS),
    ):
        with engine.begin() as conn:
            cols = {column["name"] for column in inspect(conn).get_columns(table)}
        assert set(columns) <= cols, f"{table} 缺列：{set(columns) - cols}"


def test_contract_migrations_registered_and_applied():
    """C1-4C：合同/报价补列 + 转列/索引/纠偏迁移已注册并应用。"""
    assert {15, 16, 17, 18} <= {mid for mid, _, _ in MIGRATIONS}

    apply_pending(engine)
    with engine.begin() as conn:
        applied = {
            row[0]
            for row in conn.execute(
                text(f"SELECT id FROM {_TRACKING_TABLE} WHERE id IN (15, 16, 17, 18)")
            ).fetchall()
        }
    assert applied == {15, 16, 17, 18}

    for table, columns in (
        ("contracts", CONTRACT_COLUMNS),
        ("quotations", QUOTATION_COLUMNS),
    ):
        with engine.begin() as conn:
            cols = {column["name"] for column in inspect(conn).get_columns(table)}
        assert set(columns) <= cols, f"{table} 缺列：{set(columns) - cols}"

    # 金额列必须已是 numeric（转列迁移生效），两个索引必须存在
    with engine.begin() as conn:
        types = {column["name"]: column["type"] for column in inspect(conn).get_columns("contracts")}
        index_names = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename IN ('contracts', 'quotations')"
                )
            ).fetchall()
        }
    assert str(types["total_amount"]).upper().startswith("NUMERIC"), "contracts.total_amount 应已转 numeric"
    assert "ix_contracts_direction" in index_names
    assert "ix_quotations_contract_id" in index_names
