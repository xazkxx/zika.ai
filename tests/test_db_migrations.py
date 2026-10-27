"""C1 版本化迁移机制的单元测试（2026-10-27）。

钉住三件事：
  1. `apply_pending` 按 id 升序跑「还没跑过」的迁移，并写进 `erp_migrations` 记录；
  2. 幂等：已跑过的迁移再来一次是 no-op（不会重复执行）；
  3. 事务性：迁移抛异常时整条回滚 —— 不会出现「表建了一半、记录却没写」或反过来。

用一次性高 id（90 万段）避免与将来真实迁移撞号，跑完清理 marker 表与记录。
"""

import uuid

from sqlalchemy import inspect, text

from app.db.migrations import MIGRATIONS, _TRACKING_TABLE, apply_pending
from app.db.session import engine
# 提前把 app.main 拉起来：迁移条目 1 会延迟导入 INVOICE_ADDITIONS，
# 若在 apply_pending 事务里才首次 import app.main，会重入 create_app/apply_pending
# 造成二次插入 UNIQUE 冲突。生产路径（create_app 内部调用）不存在此问题，仅测试需提前导入。
from app.main import app  # noqa: F401


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

    # 无论新库（create_all 建好列）还是老库（补列建好列），这 14 列都必须在
    with engine.begin() as conn:
        cols = {column["name"] for column in inspect(conn).get_columns("invoices")}
    from app.main import INVOICE_ADDITIONS

    assert set(INVOICE_ADDITIONS) <= cols


def test_migration_adds_columns_to_legacy_table():
    """老库缺列路径：真实 ALTER 能补齐 INVOICE_ADDITIONS 全部列，且第二次为空。"""
    from app.db.migrations import _add_columns_if_missing
    from app.main import INVOICE_ADDITIONS

    probe = "_c1_probe_legacy_invoices"
    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {probe}"))
            conn.execute(text(f"CREATE TABLE {probe} (id INTEGER PRIMARY KEY, invoice_no VARCHAR(64))"))
            added = _add_columns_if_missing(conn, probe, INVOICE_ADDITIONS)
        assert set(added) == set(INVOICE_ADDITIONS), "老库缺全部列，应一次补齐"

        with engine.begin() as conn:
            assert _add_columns_if_missing(conn, probe, INVOICE_ADDITIONS) == [], "已补齐，再补应为空"
            cols = {column["name"] for column in inspect(conn).get_columns(probe)}
        assert set(INVOICE_ADDITIONS) <= cols
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {probe}"))
