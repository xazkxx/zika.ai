"""迁移：给 invoices 加 `customer_id` / `contract_id` 两列，并尽量回填客户。

为什么需要（2026-10-18 诊断结论见 REPORT-DIAG-TASK12.md）
--------------------------------------------------------
对账单原来只能拿 `invoices.counterparty_name` 跟客户名**逐字相等**去匹配，
而发票上是"陕西送变电工程有限公司"、客户档案里是"陕西送变电第一分公司"，
字符串永远对不上 → 一张发票都进不了对账单。给发票落一个 `customer_id`
才是根治办法，名字只作为展示。

本脚本做三件事（全部幂等，可重复执行）
------------------------------------
1. 每个 schema 的 `invoices` 表补 `customer_id` / `contract_id`（可空 INTEGER）
2. 建两个索引（`_add_missing_columns` 只补列不建索引，索引必须在这里建）
3. 回填 `customer_id`：**税号优先**，其次"名称归一化后完全相等"
   —— 绝不做模糊匹配，宁可留空让人工挂（挂错客户比不挂更糟）

用法
----
    # 只看会发生什么（默认，不写库）
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261018_invoice_links.py

    # 真正执行
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261018_invoice_links.py --apply

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

DSN = os.getenv("DATABASE_URL", "postgresql+psycopg://erp:erp123456@127.0.0.1:5432/erp").replace(
    "postgresql+psycopg://", "postgresql://"
)

COLUMNS: tuple[tuple[str, str], ...] = (
    ("customer_id", "INTEGER"),
    ("contract_id", "INTEGER"),
)
INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_invoices_customer_id", "customer_id"),
    ("ix_invoices_contract_id", "contract_id"),
)

# 与 erp_invoice.py::_normalize_party_name 保持同一套规则（去空格与括号）。
# 两处必须一致，否则"迁移时匹配得上、新增发票时匹配不上"。
_STRIP_CHARS = " \t\r\n　()（）[]【】"


def normalize_party_name(value: str | None) -> str:
    text = str(value or "")
    for ch in _STRIP_CHARS:
        text = text.replace(ch, "")
    return text


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


def build_customer_index(cur, schema: str) -> tuple[dict[str, list[int]], dict[str, int]]:
    """客户档案 → 两张查找表：税号 → [id...]、归一化名称 → id。

    ⚠️ 税号是**列表**：同一个法人常常在客户档案里有多条记录（本项目实测：
       #705《西安东750千伏变电站330千伏送出工程（包2）》与 #714《陕西送变电第一分公司》
       **税号完全相同**）。这种时候税号无法定位到唯一客户，回填必须放弃而不是挑一个
       —— 挑错客户会把发票算进别人的对账单。
    """
    cur.execute(f'select id, name, tax_no from "{schema}".customers order by id')
    by_tax: dict[str, list[int]] = {}
    by_name: dict[str, int] = {}
    for cid, name, tax_no in cur.fetchall():
        tax = str(tax_no or "").strip()
        if tax:
            by_tax.setdefault(tax, []).append(cid)
        norm = normalize_party_name(name)
        if norm and norm not in by_name:
            by_name[norm] = cid
    return by_tax, by_name


def migrate_schema(cur, schema: str, apply: bool) -> dict[str, int]:
    stats = {"added_columns": 0, "added_indexes": 0, "backfilled": 0, "unmatched": 0, "ambiguous": 0}
    if not table_exists(cur, schema, "invoices"):
        print(f"  · 没有 invoices 表，跳过")
        return stats

    have = existing_columns(cur, schema, "invoices")
    for column, definition in COLUMNS:
        if column in have:
            print(f"  · 列 {column} 已存在")
            continue
        print(f"  + ALTER TABLE {schema}.invoices ADD COLUMN {column} {definition}")
        # 预演也真的执行（事务最后 rollback）—— 见 main() 里的说明
        cur.execute(f'ALTER TABLE "{schema}".invoices ADD COLUMN IF NOT EXISTS {column} {definition}')
        stats["added_columns"] += 1

    indexes = existing_indexes(cur, schema, "invoices")
    for index_name, column in INDEXES:
        if index_name in indexes:
            print(f"  · 索引 {index_name} 已存在")
            continue
        print(f"  + CREATE INDEX {index_name} ON {schema}.invoices ({column})")
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS {index_name} ON "{schema}".invoices ({column})'
        )
        stats["added_indexes"] += 1

    by_tax, by_name = build_customer_index(cur, schema)
    cur.execute(
        f"""select id, direction, counterparty_name, buyer_name, buyer_tax_no, customer_id
            from "{schema}".invoices order by id"""
    )
    rows = cur.fetchall()
    for invoice_id, direction, counterparty, buyer_name, buyer_tax_no, current in rows:
        if current:
            continue
        if direction != "output":
            # 进项发票挂的是供应商，本批没有 supplier_id 列 —— 不猜
            continue
        shown = buyer_name or counterparty

        # ① 名称归一化后完全相等：最具体，优先
        norm = normalize_party_name(shown)
        customer_id = by_name.get(norm) if norm else None
        source = "名称"

        # ② 名称对不上才看税号，且**必须唯一**
        if customer_id is None:
            candidates = by_tax.get(str(buyer_tax_no or "").strip()) or []
            if len(candidates) == 1:
                customer_id, source = candidates[0], "税号"
            elif len(candidates) > 1:
                stats["ambiguous"] += 1
                print(
                    f"    ! 发票 #{invoice_id}《{shown}》税号命中 {len(candidates)} 个客户"
                    f"（{', '.join('#' + str(c) for c in candidates)}），无法确定归属，留空待人工指定"
                )
                continue

        if customer_id is None:
            stats["unmatched"] += 1
            print(f"    - 发票 #{invoice_id}《{shown}》对不上客户档案，留空待人工挂")
            continue
        print(f"    → 发票 #{invoice_id}《{shown}》按{source}挂到客户 #{customer_id}")
        cur.execute(
            f'update "{schema}".invoices set customer_id=%s where id=%s', (customer_id, invoice_id)
        )
        stats["backfilled"] += 1

    if rows:
        total = len(rows)
        output = sum(1 for row in rows if row[1] == "output")
        print(
            f"  · 发票 {total} 张（销项 {output} 张），本次回填 {stats['backfilled']} 张，"
            f"销项对不上 {stats['unmatched']} 张，税号歧义 {stats['ambiguous']} 张"
        )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="给 invoices 加 customer_id / contract_id 并回填客户")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只打印计划）")
    args = parser.parse_args()

    mode = "执行" if args.apply else "预演（不写库）"
    print("=" * 78)
    print(f"invoices 关联字段迁移 —— {mode}")
    print(f"目标库：{DSN.split('@')[-1]}")
    print("=" * 78)

    with psycopg.connect(DSN, connect_timeout=5) as conn:
        # 预演也走一个**真事务**：DDL 真的执行、后面的 SELECT 才能看到新列，
        # 结束时 rollback 掉 —— 比"跳过 DDL 只打印计划"更接近真实执行，
        # 也更早暴露"加了列但 SQL 写错"这类问题（PG 的 DDL 是事务性的）。
        conn.autocommit = False
        with conn.cursor() as cur:
            schemas = list_schemas(cur)
            print(f"发现 {len(schemas)} 个 schema：{', '.join(schemas)}\n")
            total = {"added_columns": 0, "added_indexes": 0, "backfilled": 0, "unmatched": 0, "ambiguous": 0}
            for schema in schemas:
                print(f"【{schema}】")
                stats = migrate_schema(cur, schema, args.apply)
                for key in total:
                    total[key] += stats[key]
                print()
        if args.apply:
            conn.commit()
        else:
            conn.rollback()

    print("=" * 78)
    print(
        f"合计：新增列 {total['added_columns']} · 新增索引 {total['added_indexes']} · "
        f"回填发票 {total['backfilled']} 张 · 销项对不上 {total['unmatched']} 张 · "
        f"税号歧义 {total['ambiguous']} 张"
    )
    if not args.apply and (total["added_columns"] or total["added_indexes"] or total["backfilled"]):
        print("以上是预演结果，未写库。确认无误后加 --apply 执行。")
    elif args.apply:
        print("已执行（可重复执行，第二次应为全 0）。")
    else:
        print("所有 schema 都已是目标状态，无需变更。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
