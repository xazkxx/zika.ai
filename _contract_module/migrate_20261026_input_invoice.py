"""迁移：给 invoices 补 `supplier_id` / `certified` / `certified_at`，并回填历史数据。

为什么需要（2026-10-26 进项发票专项）
------------------------------------
1. **进项发票挂不上供应商**：`invoices` 只有 `seller_name` / `seller_tax_no` 纯文本，
   而 `customer_id` 只覆盖销项。后果是 `services/invoice_match` 的候选打分里
   "往来单位按档案 id 命中"那一档对进项**永远不成立**，同类金额的候选分不出高下，
   自动把票挂到采购入库单的成功率天然偏低。
2. **认证与抵扣被压成一个 bool**：`deducted` 只能表达"抵了/没抵"，
   「已认证待抵扣」这个月底最该盯的状态无处安放，财务只能另记 Excel。

本脚本做四件事（全部幂等，可重复执行）
------------------------------------
1. 每个 schema 的 `invoices` 表补三列（可空 / NOT NULL DEFAULT FALSE / 可空）
2. 建索引 `ix_invoices_supplier_id`（`_add_missing_columns` 只补列不建索引）
3. 回填 `supplier_id`：**税号唯一命中 → 名称归一化全等**，歧义一律留空
   —— 口径与 `erp_invoice._resolve_customer_id` / `invoice_match._resolve_supplier` 一致，
   绝不模糊匹配（挂错供应商比不挂更糟：会把票算进别人的应付/对账）。
4. 回填 `certified`：历史 `deducted = true` 的进项票 → `certified = true`，
   `certified_at` 取 `coalesce(certified_at, deducted_at, now())`
   —— 能抵扣必然已认证，这是唯一不需要问人的推断。

用法
----
    # 只看会发生什么（默认就是预演，不写库）
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261026_input_invoice.py
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261026_input_invoice.py --dry-run

    # 真正执行
    .venv\\Scripts\\python.exe _contract_module\\migrate_20261026_input_invoice.py --apply

⚠️ 刻意**不 import app.main / app.models**：前者会在模块级跑 `create_app()` 顺手对
   真实账套走 DDL，后者牵连 `app.db.base` 建引擎。本脚本只用 psycopg 直连，
   改哪张表、改哪些行，输出里逐条可见。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from dotenv import load_dotenv

# 锚到项目根再找 .env：本脚本可能被从任意 CWD 调用（IDE 任务、计划任务），
# 裸 load_dotenv() 是按**调用方脚本目录**找文件的，换个目录就静默读不到配置，
# 症状是 connect 报 "no password supplied"。
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DSN = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
if not DSN:
    raise SystemExit("DATABASE_URL 未配置：请在项目根 .env 里填写（脚本内不要写死密码）")

COLUMNS: tuple[tuple[str, str], ...] = (
    ("supplier_id", "INTEGER"),
    # NOT NULL + DEFAULT：老库补列时既有行必须立即可读，
    # 不能留 NULL 让 bool 三态化（None 既不是"已认证"也不是"未认证"）。
    ("certified", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("certified_at", "TIMESTAMP WITH TIME ZONE"),
)
INDEXES: tuple[tuple[str, str], ...] = (("ix_invoices_supplier_id", "supplier_id"),)

# 与 erp_invoice.py::_normalize_party_name / models.invoice._normalize_name 同一套规则。
# 三处必须一致，否则"迁移时匹配得上、新增发票时匹配不上"。
_STRIP_CHARS = " \t\r\n　()（）[]【】"


def normalize_party_name(value: str | None) -> str:
    text = str(value or "")
    for ch in _STRIP_CHARS:
        text = text.replace(ch, "")
    return text


def normalize_tax_no(value: str | None) -> str:
    """只留字母数字并大写（与 `models.invoice._normalize_tax_no` 一致）。"""
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def is_special_invoice(invoice_type: str | None) -> bool:
    """镜像 `models.invoice.is_special_invoice`：含「专票」二字即专票（含电子专票）。"""
    return "专票" in str(invoice_type or "")


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


def build_supplier_index(cur, schema: str) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """供应商档案 → 两张查找表：税号 → [id...]、归一化名称 → [id...]。

    ⚠️ 键值一律是**列表**：同一税号在供应商档案里挂多条记录是真实存在的
       （客户侧本项目实测过 #705 / #709 / #714 同税号）。这种时候无法定位到唯一
       供应商，回填必须放弃 —— 挑错的供应商会把这张票算进别人的应付对账。
    """
    cur.execute(f'select id, name, tax_no from "{schema}".suppliers order by id')
    by_tax: dict[str, list[int]] = {}
    by_name: dict[str, list[int]] = {}
    for sid, name, tax_no in cur.fetchall():
        tax = normalize_tax_no(tax_no)
        if tax:
            by_tax.setdefault(tax, []).append(sid)
        norm = normalize_party_name(name)
        if norm:
            by_name.setdefault(norm, []).append(sid)
    return by_tax, by_name


def migrate_columns(cur, schema: str) -> dict[str, int]:
    stats = {"added_columns": 0, "added_indexes": 0}
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
        cur.execute(f'CREATE INDEX IF NOT EXISTS {index_name} ON "{schema}".invoices ({column})')
        stats["added_indexes"] += 1
    return stats


def backfill_supplier_id(cur, schema: str) -> dict[str, int]:
    """进项发票挂供应商：税号唯一命中 → 名称归一化全等，歧义留空。"""
    stats = {"backfilled": 0, "unmatched": 0, "ambiguous": 0, "skipped": 0}
    if not table_exists(cur, schema, "suppliers"):
        print("  · 没有 suppliers 表，跳过进项挂供应商")
        return stats

    by_tax, by_name = build_supplier_index(cur, schema)
    cur.execute(
        f"""select id, seller_name, counterparty_name, seller_tax_no, supplier_id
            from "{schema}".invoices where direction = 'input' order by id"""
    )
    rows = cur.fetchall()
    if not rows:
        print("  · 没有进项发票，跳过挂供应商")
        return stats

    for invoice_id, seller_name, counterparty, seller_tax_no, current in rows:
        if current:
            stats["skipped"] += 1
            continue
        shown = seller_name or counterparty
        supplier_id: int | None = None
        source = ""

        tax = normalize_tax_no(seller_tax_no)
        candidates = (by_tax.get(tax) or []) if tax else []
        if len(candidates) == 1:
            supplier_id, source = candidates[0], "税号"
        elif len(candidates) > 1:
            stats["ambiguous"] += 1
            print(
                f"    ! 发票 #{invoice_id}《{shown}》税号命中 {len(candidates)} 个供应商"
                f"（{', '.join('#' + str(c) for c in candidates)}），无法确定归属，留空待人工指定"
            )
            continue

        if supplier_id is None:
            norm = normalize_party_name(shown)
            candidates = (by_name.get(norm) or []) if norm else []
            if len(candidates) == 1:
                supplier_id, source = candidates[0], "名称"
            elif len(candidates) > 1:
                stats["ambiguous"] += 1
                print(
                    f"    ! 发票 #{invoice_id}《{shown}》名称命中 {len(candidates)} 个供应商"
                    f"（{', '.join('#' + str(c) for c in candidates)}），无法确定归属，留空待人工指定"
                )
                continue

        if supplier_id is None:
            stats["unmatched"] += 1
            print(f"    - 发票 #{invoice_id}《{shown}》对不上供应商档案，留空待人工挂")
            continue

        print(f"    → 发票 #{invoice_id}《{shown}》按{source}挂到供应商 #{supplier_id}")
        cur.execute(f'update "{schema}".invoices set supplier_id=%s where id=%s', (supplier_id, invoice_id))
        stats["backfilled"] += 1

    print(
        f"  · 进项发票 {len(rows)} 张（已挂 {stats['skipped']} 张），本次回填 {stats['backfilled']} 张，"
        f"对不上 {stats['unmatched']} 张，歧义 {stats['ambiguous']} 张"
    )
    return stats


def backfill_certified(cur, schema: str) -> dict[str, int]:
    """历史已抵扣的进项票补上认证标记 —— 能抵扣必然已认证。"""
    stats = {"certified": 0, "general_with_deduction": 0}
    cur.execute(
        f"""select id, invoice_type, deducted_at, certified_at
            from "{schema}".invoices
            where direction = 'input' and deducted = true and certified = false
            order by id"""
    )
    rows = cur.fetchall()
    if not rows:
        print("  · 没有待补认证标记的进项发票")
        return stats

    for invoice_id, invoice_type, deducted_at, certified_at in rows:
        when = certified_at or deducted_at
        where = "原抵扣时间" if when else "当前时间"
        if is_special_invoice(invoice_type):
            print(f"    → 发票 #{invoice_id}（{invoice_type}）已抵扣 → 补认证标记，认证时间取{where}")
        else:
            # 普票标了已抵扣属于历史脏数据（政策上不可抵扣）。本脚本**只补标记、不改抵扣**：
            # 抹掉 deducted 会让历史统计数字突然变化，那属于业务决定，不该由迁移脚本替人拍板。
            stats["general_with_deduction"] += 1
            print(
                f"    ! 发票 #{invoice_id}（{invoice_type}）是普票却标着已抵扣（历史脏数据），"
                f"仅补认证标记，抵扣状态原样保留"
            )
        cur.execute(
            f"""update "{schema}".invoices
                set certified = true,
                    certified_at = coalesce(certified_at, deducted_at, now())
                where id = %s""",
            (invoice_id,),
        )
        stats["certified"] += 1

    extra = (
        f"（其中普票异常 {stats['general_with_deduction']} 张，未改抵扣状态）"
        if stats["general_with_deduction"]
        else ""
    )
    print(f"  · 补认证标记 {stats['certified']} 张{extra}")
    return stats


def migrate_schema(cur, schema: str) -> dict[str, int]:
    empty = {
        "added_columns": 0,
        "added_indexes": 0,
        "backfilled": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "certified": 0,
    }
    if not table_exists(cur, schema, "invoices"):
        print("  · 没有 invoices 表，跳过")
        return empty

    stats = dict(empty)
    stats.update(migrate_columns(cur, schema))
    supplier = backfill_supplier_id(cur, schema)
    stats["backfilled"] = supplier["backfilled"]
    stats["unmatched"] = supplier["unmatched"]
    stats["ambiguous"] = supplier["ambiguous"]
    stats["certified"] = backfill_certified(cur, schema)["certified"]
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="给 invoices 补 supplier_id / certified 并回填历史发票")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只预演）")
    parser.add_argument("--dry-run", action="store_true", help="显式预演（默认行为，写出来只是自证）")
    args = parser.parse_args()
    apply = args.apply and not args.dry_run

    mode = "执行（写库）" if apply else "预演（不写库）"
    print("=" * 78)
    print(f"invoices 进项发票字段迁移 —— {mode}")
    print(f"目标库：{DSN.split('@')[-1]}")
    print("=" * 78)

    total = {
        "added_columns": 0,
        "added_indexes": 0,
        "backfilled": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "certified": 0,
    }
    with psycopg.connect(DSN, connect_timeout=5) as conn:
        # 预演也走一个**真事务**：DDL 与 UPDATE 都真的执行，结束时 rollback。
        # 比"只打印计划"更接近真实执行，也更早暴露"加了列但 SQL 写错"这类问题
        # （PG 的 DDL 是事务性的，回滚不留痕）。与 migrate_20261018 同一套路。
        conn.autocommit = False
        with conn.cursor() as cur:
            schemas = list_schemas(cur)
            print(f"发现 {len(schemas)} 个 schema：{', '.join(schemas)}\n")
            for schema in schemas:
                print(f"【{schema}】")
                stats = migrate_schema(cur, schema)
                for key in total:
                    total[key] += stats[key]
                print()
        if apply:
            conn.commit()
        else:
            conn.rollback()

    print("=" * 78)
    print(
        f"合计：新增列 {total['added_columns']} · 新增索引 {total['added_indexes']} · "
        f"回填供应商 {total['backfilled']} 张 · 对不上 {total['unmatched']} 张 · "
        f"歧义 {total['ambiguous']} 张 · 补认证 {total['certified']} 张"
    )
    if apply:
        print("已执行（可重复执行，第二次应为全 0）。")
    elif any(total.values()):
        print("以上是预演结果，已全部回滚，未写库。确认无误后加 --apply 执行。")
    else:
        print("所有 schema 都已是目标状态，无需变更。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


