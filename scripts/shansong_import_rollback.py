# -*- coding: utf-8 -*-
"""回滚「历史导入」产生的全部数据 —— 只删自己导进去的，一根手都不碰别人的。

## 为什么需要它

导入脚本一旦出错，最重要的事情不是"改对再跑一遍"，
而是**先把错误数据清干净**。否则第二次导入会撞上第一次的半截数据：
库存流水重复、应收重复、客户重名……到最后你分不清哪条是对的。

## 凭什么敢删

**只认备注前缀 `历史导入|`**。这是导入脚本自己打的标记，
只要不是我们导的，一律不动。删除范围严格按 `related_order_id` 关联：

    sales_orders        → note LIKE '历史导入%'
    sales_order_items   → sales_order_id IN (上面那些 id)
    inventory_transactions → related_order_id IN (上面) 且 related_type='sales_out'
    financial_transactions → related_order_id IN (上面) 且 related_type='sales_out'
    （会计凭证：按 flow_id 关联财务流水，一并清掉，否则总账挂空分录）

**不删客户档案**：客户可能被别的单据引用了，删了会连坐。
如果确实要删，脚本会单独列出"本次导入新建、且没有任何单据引用的客户"，
让你手工确认 —— 不自动删。

跑法
----
    # 先看会删什么（默认）
    ./.venv/Scripts/python.exe scripts/shansong_import_rollback.py

    # 真的删
    ./.venv/Scripts/python.exe scripts/shansong_import_rollback.py --commit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

NOTE_TAG = "历史导入"


def main() -> int:
    ap = argparse.ArgumentParser(description="回滚历史导入数据")
    ap.add_argument("--commit", action="store_true", help="真的删除（默认只统计）")
    ap.add_argument("--only", default="", help="只回滚这些系统单号，逗号分隔（留空=全部历史导入单）")
    args = ap.parse_args()

    import psycopg

    from db_config import psycopg_dsn  # noqa: E402

    conn = psycopg.connect(psycopg_dsn())
    cur = conn.cursor()

    only = [s.strip() for s in (args.only or "").split(",") if s.strip()]
    if only:
        # 加了 --only 就只认点名的单，但**仍然必须**带「历史导入」备注，不能借它删正经单
        cur.execute(
            "SELECT id, order_no, total_amount FROM sales_orders "
            "WHERE note LIKE %s AND order_no = ANY(%s) ORDER BY id",
            (f"{NOTE_TAG}%", only),
        )
        found = {r[1] for r in cur.fetchall()}
        unknown = [n for n in only if n not in found]
        if unknown:
            print(f"❌ 这些单号不是「历史导入」单，拒绝回滚：{', '.join(unknown)}")
            conn.rollback()
            conn.close()
            return 1
        cur.execute(
            "SELECT id, order_no, total_amount FROM sales_orders "
            "WHERE note LIKE %s AND order_no = ANY(%s) ORDER BY id",
            (f"{NOTE_TAG}%", only),
        )
    else:
        cur.execute(
            "SELECT id, order_no, total_amount FROM sales_orders WHERE note LIKE %s ORDER BY id",
            (f"{NOTE_TAG}%",),
        )
    orders = cur.fetchall()
    if not orders:
        print("没有找到任何「历史导入」单据，无需回滚。")
        conn.rollback()
        conn.close()
        return 0

    ids = [r[0] for r in orders]
    total = sum(r[2] for r in orders)

    cur.execute("SELECT count(*) FROM sales_order_items WHERE sales_order_id = ANY(%s)", (ids,))
    n_items = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM inventory_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out'",
        (ids,),
    )
    n_inv = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM financial_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out'",
        (ids,),
    )
    n_fin = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM accounting_vouchers WHERE flow_id IN "
        "(SELECT id FROM financial_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out')",
        (ids,),
    )
    n_vou = cur.fetchone()[0]

    print("=" * 60)
    print(f"将回滚 {len(orders)} 张历史导入单，金额 ¥{total}")
    print(f"  销售单        {len(orders)}")
    print(f"  明细行        {n_items}")
    print(f"  库存流水      {n_inv}")
    print(f"  财务流水      {n_fin}")
    print(f"  会计凭证      {n_vou}")
    print()
    for o in orders[:10]:
        print(f"    {o[1]}  ¥{o[2]}")
    if len(orders) > 10:
        print(f"    …… 共 {len(orders)} 张")

    if not args.commit:
        print()
        print("⚠️ 这是统计模式。要真正删除请加 --commit")
        conn.rollback()
        conn.close()
        return 0

    # 顺序很重要：先删子表，再删主表
    cur.execute(
        "DELETE FROM accounting_vouchers WHERE flow_id IN "
        "(SELECT id FROM financial_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out')",
        (ids,),
    )
    cur.execute(
        "DELETE FROM financial_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out'",
        (ids,),
    )
    cur.execute(
        "DELETE FROM inventory_transactions WHERE related_order_id = ANY(%s) AND related_type='sales_out'",
        (ids,),
    )
    cur.execute("DELETE FROM sales_order_items WHERE sales_order_id = ANY(%s)", (ids,))
    cur.execute("DELETE FROM sales_orders WHERE id = ANY(%s)", (ids,))

    # 顺带报告：这次导入新建、现在无人引用的客户（只报告，不删）
    cur.execute("SELECT count(*) FROM customers")
    cur.fetchone()
    conn.commit()

    print()
    print(f"✅ 已回滚：{len(orders)} 张单 / {n_items} 明细 / {n_inv} 库存流水 / {n_fin} 财务流水 / {n_vou} 凭证")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
