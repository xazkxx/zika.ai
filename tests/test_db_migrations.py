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
