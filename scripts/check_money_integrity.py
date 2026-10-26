# -*- coding: utf-8 -*-
"""金额精度体检（只读）—— 迁移前后都能跑，用来证明"这笔账是算对的"。

六项检查，对应六类真实事故：

  1. 金额列出现 3 位小数      → 说明某处还在用浮点累加（或改型时被截断）
  2. 单价列超过 4 位小数      → double 的二进制尾巴：41.666666666664 这种
  3. 单头合计 ≠ 明细金额之和   → "合计单价 × 合计数量"的经典错，或漏算明细
  4. 借贷不平                 → journal_entry_lines 每张凭证 SUM(debit) ≠ SUM(credit)
  5. 凭证头 ≠ 凭证行           → journal_entries.total_debit 与明细对不上
  6. 发票挂着不存在的单        → related_order_id 指向已删除的销售/采购单

跑法：
    .venv/Scripts/python.exe scripts/check_money_integrity.py
    .venv/Scripts/python.exe scripts/check_money_integrity.py --schema co_03
退出码：0 = 全部 PASS；1 = 有异常（CI / 验收台可以直接用它当闸门）
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "ERP_DB_URL", "postgresql+psycopg://erp:erp123456@127.0.0.1:5432/erp"
)
SCHEMAS = ("public", "co_02", "co_03")

# 钱：两位小数。表 → 列
MONEY_COLUMNS = {
    "sales_orders": ["total_amount", "receivable_amount", "discount_amount",
                     "received_amount", "current_debt", "prev_debt", "total_debt"],
    "sales_order_items": ["amount"],
    "purchase_orders": ["total_amount", "payable_amount", "discount_amount",
                        "paid_amount", "current_debt", "prev_debt", "total_debt"],
    "purchase_order_items": ["amount"],
    "invoices": ["total_amount", "tax_amount", "excl_tax_amount"],
    "financial_transactions": ["amount", "applied_amount"],
    "journal_entries": ["total_debit", "total_credit"],
    "journal_entry_lines": ["debit", "credit"],
}

# 费率（单价 / 单位成本）：四位小数
RATE_COLUMNS = {
    "sales_order_items": ["unit_price"],
    "purchase_order_items": ["unit_price"],
    "inventory_transactions": ["unit_price"],
}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    RESULTS.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  — " + extra) if extra else ""))


def table_exists(conn, schema: str, table: str) -> bool:
    return bool(
        conn.execute(
            text(
                "select 1 from information_schema.tables "
                "where table_schema=:s and table_name=:t"
            ),
            {"s": schema, "t": table},
        ).first()
    )


def column_type(conn, schema: str, table: str, column: str) -> str | None:
    return conn.execute(
        text(
            "select data_type from information_schema.columns "
            "where table_schema=:s and table_name=:t and column_name=:c"
        ),
        {"s": schema, "t": table, "c": column},
    ).scalar()


def run(schemas):
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        for sch in schemas:
            print(f"\n══ {sch} ══")

            # ── 1. 金额超 2 位小数 ────────────────────────────────────
            bad_rows, detail = 0, []
            for tbl, cols in MONEY_COLUMNS.items():
                if not table_exists(conn, sch, tbl):
                    continue
                for col in cols:
                    if column_type(conn, sch, tbl, col) is None:
                        continue
                    n = conn.execute(
                        text(
                            f"select count(*) from {sch}.{tbl} "
                            f"where {col} is not null and {col}::numeric <> round({col}::numeric, 2)"
                        )
                    ).scalar() or 0
                    if n:
                        bad_rows += n
                        detail.append(f"{tbl}.{col}={n}")
            check(f"[{sch}] 1. 金额列都是两位小数", bad_rows == 0,
                  "、".join(detail) if detail else f"{len(MONEY_COLUMNS)} 张表")

            # ── 2. 单价超 4 位小数 ───────────────────────────────────
            bad_rows, detail = 0, []
            for tbl, cols in RATE_COLUMNS.items():
                if not table_exists(conn, sch, tbl):
                    continue
                for col in cols:
                    if column_type(conn, sch, tbl, col) is None:
                        continue
                    n = conn.execute(
                        text(
                            f"select count(*) from {sch}.{tbl} "
                            f"where {col} is not null and {col}::numeric <> round({col}::numeric, 4)"
                        )
                    ).scalar() or 0
                    if n:
                        bad_rows += n
                        detail.append(f"{tbl}.{col}={n}")
            # 迁移前这些是 double 的二进制尾巴，迁移后必须为 0 —— 所以"失败"是有信息量的
            check(f"[{sch}] 2. 单价列不超过四位小数", bad_rows == 0,
                  "、".join(detail) if detail else "干净")

            # ── 3. 单头合计 vs 明细之和 ──────────────────────────────
            for head, items, fk, amount_col, total_col in (
                ("sales_orders", "sales_order_items", "sales_order_id", "amount", "total_amount"),
                ("purchase_orders", "purchase_order_items", "purchase_order_id", "amount", "total_amount"),
            ):
                if not (table_exists(conn, sch, head) and table_exists(conn, sch, items)):
                    continue
                rows = conn.execute(
                    text(
                        f"""select o.id, o.{total_col}::numeric as head_total,
                                   coalesce(sum(i.{amount_col}::numeric), 0) as item_total
                              from {sch}.{head} o
                              join {sch}.{items} i on i.{fk} = o.id
                             group by o.id, o.{total_col}
                            having abs(o.{total_col}::numeric - coalesce(sum(i.{amount_col}::numeric), 0)) > 0.01"""
                    )
                ).fetchall()
                sample = "；".join(f"#{r[0]} 头={r[1]} 明细={r[2]}" for r in rows[:3])
                check(f"[{sch}] 3. {head} 单头合计 = 明细之和", not rows,
                      f"{len(rows)} 张不一致（{sample}）" if rows else "全部一致")

            # ── 4. 借贷平衡 ─────────────────────────────────────────
            if table_exists(conn, sch, "journal_entry_lines"):
                rows = conn.execute(
                    text(
                        f"""select entry_id, sum(debit::numeric), sum(credit::numeric)
                              from {sch}.journal_entry_lines
                             group by entry_id
                            having abs(sum(debit::numeric) - sum(credit::numeric)) > 0.005"""
                    )
                ).fetchall()
                sample = "；".join(f"凭证#{r[0]} 借={r[1]} 贷={r[2]}" for r in rows[:3])
                check(f"[{sch}] 4. 每张凭证借贷平衡", not rows,
                      f"{len(rows)} 张不平（{sample}）" if rows else "全部平衡")

            # ── 5. 凭证头 vs 凭证行 ──────────────────────────────────
            if table_exists(conn, sch, "journal_entry_lines") and table_exists(conn, sch, "journal_entries"):
                rows = conn.execute(
                    text(
                        f"""select e.id, e.total_debit::numeric,
                                   coalesce((select sum(l.debit::numeric) from {sch}.journal_entry_lines l
                                              where l.entry_id = e.id), 0)
                              from {sch}.journal_entries e
                             where abs(e.total_debit::numeric -
                                       coalesce((select sum(l.debit::numeric) from {sch}.journal_entry_lines l
                                                  where l.entry_id = e.id), 0)) > 0.005"""
                    )
                ).fetchall()
                check(f"[{sch}] 5. 凭证头合计 = 明细借方之和", not rows,
                      f"{len(rows)} 张不一致" if rows else "全部一致")

            # ── 6. 发票挂到不存在的单 ────────────────────────────────
            if table_exists(conn, sch, "invoices"):
                out_bad = conn.execute(
                    text(
                        f"""select count(*) from {sch}.invoices i
                             where i.related_order_id is not null and i.direction = 'output'
                               and not exists (select 1 from {sch}.sales_orders o where o.id = i.related_order_id)"""
                    )
                ).scalar() or 0
                in_bad = conn.execute(
                    text(
                        f"""select count(*) from {sch}.invoices i
                             where i.related_order_id is not null and i.direction = 'input'
                               and not exists (select 1 from {sch}.purchase_orders o where o.id = i.related_order_id)"""
                    )
                ).scalar() or 0
                check(f"[{sch}] 6. 发票挂的单据都还存在", out_bad == 0 and in_bad == 0,
                      f"销项 {out_bad} 张 / 进项 {in_bad} 张指向已删除单据"
                      if (out_bad or in_bad) else "全部有效")

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 64)
    print(f"体检结果：{passed}/{total} 项通过")
    if passed != total:
        print("异常项：")
        for name, ok, extra in RESULTS:
            if not ok:
                print(f"  · {name}" + (f"  — {extra}" if extra else ""))
    print("=" * 64)
    return 0 if passed == total else 1


def main():
    parser = argparse.ArgumentParser(description="金额精度体检（只读）")
    parser.add_argument("--schema", action="append", help="只查指定 schema，可重复")
    args = parser.parse_args()
    schemas = tuple(args.schema) if args.schema else SCHEMAS
    sys.exit(run(schemas))


if __name__ == "__main__":
    main()
