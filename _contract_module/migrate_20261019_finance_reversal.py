"""迁移：给 financial_transactions 加红冲字段（2026-10-19）

为什么需要
----------
「红冲」要同时回答两个问题：
  1. 这笔流水有没有被冲过、被哪一笔冲的 → 需要 `reversal_of_id`（只在红字行上有值）
  2. 这笔收付款当时**实际冲抵到单据**多少 → 需要 `applied_amount`

第 2 点最容易漏：单欠 1000、客户给了 1500，其中 500 是预收、不进单据。
红冲时若按 1500 回退，订单的 `received_amount` 会变成 -500 —— 账面直接错。

本脚本做三件事（全部幂等，可重复执行）
------------------------------------
1. 每个 schema 的 `financial_transactions` 补 `reversal_of_id` / `applied_amount`
2. 建**唯一**索引 `uq_financial_transactions_reversal_of`（一笔只能被冲一次；
   PG 的唯一索引允许多个 NULL，所以不影响存量行）
3. 给存量「挂单据的收付款」回填 applied_amount —— 只回填**能确定**的：
   单据当前已收/已付 ≥ 本笔金额 时，按本笔全额计；否则留 NULL，
   由接口在红冲时按 `min(金额, 当前已收)` 保守估算（宁可少退，不能冲成负数）

用法
----
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261019_finance_reversal.py
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261019_finance_reversal.py --apply

⚠️ 刻意**不 import app.main**：那会在模块级跑 `create_app()`，顺手对三个真实账套
   走一遍 DDL。本脚本只用 psycopg 直连，改哪张表、改哪些行，输出里逐条可见。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from dotenv import load_dotenv

load_dotenv()

DSN = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
if not DSN:
    raise SystemExit("DATABASE_URL 未配置：请在项目根 .env 里填写（脚本内不要写死密码）")

COLUMNS: tuple[tuple[str, str], ...] = (
    ("reversal_of_id", "INTEGER"),
    ("applied_amount", "DOUBLE PRECISION"),
)

# 唯一索引：一笔原流水只能有一条红字行。
# PG 里 NULL 不参与唯一性比较，所以存量（全 NULL）不会撞。
UNIQUE_INDEX = "uq_financial_transactions_reversal_of"


def list_schemas(cur) -> list[str]:
    cur.execute(
        """
        select schema_name from information_schema.schemata
        where schema_name not in ('pg_catalog', 'information_schema', 'pg_toast')
          and schema_name not like 'pg_%'
        order by schema_name
        """
    )
    return [row[0] for row in cur.fetchall()]


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        "select 1 from information_schema.tables where table_schema=%s and table_name=%s",
        (schema, table),
    )
    return cur.fetchone() is not None


def existing_columns(cur, schema: str, table: str) -> set[str]:
    cur.execute(
        "select column_name from information_schema.columns where table_schema=%s and table_name=%s",
        (schema, table),
    )
    return {row[0] for row in cur.fetchall()}


def existing_indexes(cur, schema: str, table: str) -> set[str]:
    cur.execute("select indexname from pg_indexes where schemaname=%s and tablename=%s", (schema, table))
    return {row[0] for row in cur.fetchall()}


def migrate_schema(cur, schema: str) -> dict[str, int]:
    stats = {"added_columns": 0, "added_indexes": 0, "backfilled": 0, "skipped": 0}
    if not table_exists(cur, schema, "financial_transactions"):
        print("  · 没有 financial_transactions 表，跳过")
        return stats

    have = existing_columns(cur, schema, "financial_transactions")
    for column, definition in COLUMNS:
        if column in have:
            print(f"  · 列 {column} 已存在")
            continue
        print(f"  + ALTER TABLE {schema}.financial_transactions ADD COLUMN {column} {definition}")
        cur.execute(
            f'ALTER TABLE "{schema}".financial_transactions ADD COLUMN IF NOT EXISTS {column} {definition}'
        )
        stats["added_columns"] += 1

    indexes = existing_indexes(cur, schema, "financial_transactions")
    if UNIQUE_INDEX in indexes:
        print(f"  · 索引 {UNIQUE_INDEX} 已存在")
    else:
        print(f"  + CREATE UNIQUE INDEX {UNIQUE_INDEX} ON {schema}.financial_transactions (reversal_of_id)")
        cur.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX} '
            f'ON "{schema}".financial_transactions (reversal_of_id)'
        )
        stats["added_indexes"] += 1

    # ---- 回填 applied_amount（只回填能确定的）----
    cur.execute(
        f"""select f.id, f.amount, f.related_order_id
            from "{schema}".financial_transactions f
            where f.transaction_type in ('receipt','payment')
              and f.related_order_id is not null
              and f.applied_amount is null
              and f.reversal_of_id is null
            order by f.id"""
    )
    pending = cur.fetchall()
    for flow_id, amount, order_id in pending:
        amount = float(amount or 0)
        if amount <= 0:
            stats["skipped"] += 1
            continue
        cur.execute(
            f'select received_amount from "{schema}".sales_orders where id=%s', (order_id,)
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f'select paid_amount from "{schema}".purchase_orders where id=%s', (order_id,)
            )
            row = cur.fetchone()
        paid = float((row[0] if row else 0) or 0)
        if paid + 1e-6 < amount:
            # 单据上的已收付比这笔还少 → 当时多半有预收/预付，无法反推准确分摊
            stats["skipped"] += 1
            print(f"    ~ 流水 #{flow_id} 金额 {amount:.2f} > 单据当前已收付 {paid:.2f}，留空（接口按保守口径处理）")
            continue
        cur.execute(
            f'update "{schema}".financial_transactions set applied_amount=%s where id=%s',
            (round(amount, 2), flow_id),
        )
        stats["backfilled"] += 1
        print(f"    → 流水 #{flow_id} applied_amount = {amount:.2f}")

    cur.execute(
        f"""select count(*) from "{schema}".financial_transactions
            where reversal_of_id is not null"""
    )
    reversed_rows = cur.fetchone()[0]
    print(f"  · 存量红字行 {reversed_rows} 条；回填 applied_amount {stats['backfilled']} 条，"
          f"无法确定 {stats['skipped']} 条")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    args = parser.parse_args()

    print(f"DSN: {DSN}")
    print("模式:", "APPLY（会写库）" if args.apply else "预演（最后统一 rollback）")

    conn = psycopg.connect(DSN)
    cur = conn.cursor()
    total = {"added_columns": 0, "added_indexes": 0, "backfilled": 0, "skipped": 0}
    for schema in list_schemas(cur):
        if not table_exists(cur, schema, "financial_transactions"):
            continue
        print(f"\n[{schema}]")
        stats = migrate_schema(cur, schema)
        for key in total:
            total[key] += stats[key]

    if args.apply:
        conn.commit()
        print("\n已提交。")
    else:
        conn.rollback()
        print("\n预演结束，已回滚。加 --apply 真正执行。")
    print("合计:", total)
    conn.close()


if __name__ == "__main__":
    main()
