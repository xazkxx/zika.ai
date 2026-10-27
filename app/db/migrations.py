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

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

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
