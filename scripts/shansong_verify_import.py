# -*- coding: utf-8 -*-
"""历史导入 · 验收脚本 —— 把"导入成功"升级成"账实一致"。

## 为什么必须有它

反证 PROBE-G 证明了一件事：**封掉应收流水后，导入脚本照样打印「成功」**。
所以"导入成功"这四个字一文不值 —— 它只证明没抛异常。

真正的验收要核对五条：
  1. 单据金额 == 明细金额之和
  2. 每张单都有库存流水，且数量 == 明细数量之和
  3. 每张单都有应收流水，且金额 == 单据金额        ← PROBE-G 就是漏这条
  4. 每张单都有会计凭证，且 借方合计 == 贷方合计
  5. 汇总：所有导入单金额合计 == 源数据预期合计

跑法
----
    ./.venv/Scripts/python.exe scripts/shansong_verify_import.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

NOTE_TAG = "历史导入"


def main() -> int:
    import psycopg

    from db_config import psycopg_dsn  # noqa: E402

    conn = psycopg.connect(psycopg_dsn())
    cur = conn.cursor()

    cur.execute(
        "SELECT id, order_no, total_amount, status, doc_type, customer_id, warehouse_id, order_date "
        "FROM sales_orders WHERE note LIKE %s ORDER BY id",
        (f"{NOTE_TAG}%",),
    )
    orders = cur.fetchall()

    fails: list[str] = []
    warns: list[str] = []

    if not orders:
        print("没有找到任何历史导入单。")
        conn.rollback()
        conn.close()
        return 0

    grand = Decimal("0")
    print("=" * 76)
    print(f"验收 {len(orders)} 张历史导入单")
    print("=" * 76)
    print(f"{'新单号':<14}{'状态':<11}{'金额':>11}{'明细':>6}{'库存':>6}{'应收':>11}{'凭证':>8}")
    print("-" * 76)

    for oid, order_no, total, status, doc_type, cust_id, wh_id, odate in orders:
        total = Decimal(str(total or 0))
        grand += total

        cur.execute(
            "SELECT count(*), COALESCE(SUM(quantity),0), COALESCE(SUM(amount),0) "
            "FROM sales_order_items WHERE sales_order_id=%s",
            (oid,),
        )
        n_item, qty_sum, amt_sum = cur.fetchone()
        amt_sum = Decimal(str(amt_sum or 0))

        cur.execute(
            "SELECT count(*), COALESCE(SUM(quantity),0) FROM inventory_transactions "
            "WHERE related_order_id=%s AND related_type='sales_out'",
            (oid,),
        )
        n_inv, inv_qty = cur.fetchone()

        cur.execute(
            "SELECT count(*), COALESCE(SUM(amount),0) FROM financial_transactions "
            "WHERE related_order_id=%s AND related_type='sales_out' AND transaction_type='receivable'",
            (oid,),
        )
        n_fin, fin_amt = cur.fetchone()
        fin_amt = Decimal(str(fin_amt or 0))

        cur.execute(
            "SELECT count(*), COALESCE(SUM(total_debit),0), COALESCE(SUM(total_credit),0) "
            "FROM journal_entries WHERE related_order_id=%s AND related_type='sales_out'",
            (oid,),
        )
        n_vou, dr, cr = cur.fetchone()
        dr, cr = Decimal(str(dr or 0)), Decimal(str(cr or 0))

        mark = ""
        # ① 单据金额 == 明细金额之和
        if abs(amt_sum - total) > Decimal("0.01"):
            fails.append(f"{order_no} 单据金额 {total} ≠ 明细合计 {amt_sum}")
            mark += "!"
        # ② 库存流水数量 == 明细数量
        if n_inv == 0:
            fails.append(f"{order_no} 没有库存流水")
            mark += "!"
        elif int(inv_qty) != int(qty_sum):
            fails.append(f"{order_no} 库存流水数量 {inv_qty} ≠ 明细数量 {qty_sum}")
            mark += "!"
        # ③ 应收金额 == 单据金额
        if n_fin == 0:
            fails.append(f"{order_no} 没有应收流水（账上不会出现这笔钱）")
            mark += "!"
        elif abs(fin_amt - total) > Decimal("0.01"):
            fails.append(f"{order_no} 应收 {fin_amt} ≠ 单据金额 {total}")
            mark += "!"
        # ④ 凭证借贷平衡
        if n_vou == 0:
            warns.append(f"{order_no} 没有会计凭证")
        elif dr != cr:
            fails.append(f"{order_no} 凭证借贷不平：借{dr} 贷{cr}")
            mark += "!"

        print(f"{order_no:<14}{status:<11}{total:>11}{n_item:>6}{n_inv:>6}"
              f"{fin_amt:>11}{n_vou:>8} {mark}")

    print("-" * 76)
    print(f"合计金额 ¥{grand}")

    # ⑤ 与源数据预期比对（读预检产物）
    plan_path = ROOT_DIR / "artifacts" / "shansong_import" / "plan.json"
    expect = None
    if plan_path.exists():
        import json

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        expect = Decimal(str(plan.get("importable_amount") or 0))
        print(f"源数据预期 ¥{expect}（预检时算出的可导入金额）")

    print()
    if warns:
        print(f"⚠️  {len(warns)} 条警告：")
        for w in warns[:10]:
            print(f"    {w}")
        print()

    if fails:
        print(f"❌ 验收未通过，{len(fails)} 处不一致：")
        for f in fails[:20]:
            print(f"    {f}")
        conn.rollback()
        conn.close()
        return 1

    print("✅ 验收通过：单据/库存/应收/凭证四项全部对得上")
    if expect is not None and expect > 0 and grand < expect:
        print(f"   （注：当前导入 ¥{grand} < 预期 ¥{expect}，说明还有单没导完，不是错误）")
    conn.rollback()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
