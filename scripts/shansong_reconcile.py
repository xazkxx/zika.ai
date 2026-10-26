# -*- coding: utf-8 -*-
"""历史数据导入 —— **对账脚本**（只读，不改库）。

输出四件事：
  1. 源 Excel 口径：原始明细行数 / 原始总额 / 去重后行数 / 去重后总额（差值=重复录入）；
  2. 系统口径：历史导入单据张数 / 单据总额 / 应收合计 / 出库流水行数；
  3. **按源单号逐张比对**：每张源单在 Excel 里的金额 vs 系统里对应单据的金额之和，
     差额不为 0 的直接列出来（拆单后仍应逐张相等，因为拆单只改分配对象、不改总额）；
  4. 结论：PASS / 有差异（附差异清单）。

跑法：
    ./.venv/Scripts/python.exe scripts/shansong_reconcile.py
    ./.venv/Scripts/python.exe scripts/shansong_reconcile.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from shansong_import_plan import plan as build_plan  # noqa: E402

NOTE_TAG = "历史导入"


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def main() -> int:
    ap = argparse.ArgumentParser(description="陕送票历史数据导入对账")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    args = ap.parse_args()

    from app.db.session import SessionLocal
    from app.models.finance import FinancialTransaction
    from app.models.sales_order import SalesOrder, SalesOrderItem
    from app.models.inventory import InventoryTransaction

    p = build_plan()

    # ── ① 源 Excel 口径 ────────────────────────────────────────────────
    raw_rows = p["raw_rows"]
    raw_total = _d(p["total_amount"])
    recs = p["records"]
    ok_recs = [r for r in recs if r["status"] == "ok"]
    kept_total = sum((_d(r["amount"]) for r in ok_recs), Decimal("0"))
    # dropped_rows 是**行数**（plan 里存的是计数，不是明细）
    dropped_count = int(p.get("dropped_rows") or 0)
    dropped_total = raw_total - kept_total

    # 按源单号汇总 Excel 金额（只统计可建单的 ok 行）
    excel_by_doc: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    rows_by_doc: dict[str, int] = defaultdict(int)
    for r in ok_recs:
        excel_by_doc[r["doc_no"]] += _d(r["amount"])
        rows_by_doc[r["doc_no"]] += 1

    db = SessionLocal()
    try:
        orders = (
            db.query(SalesOrder)
            .filter(SalesOrder.note.like(f"{NOTE_TAG}%"))
            .order_by(SalesOrder.id)
            .all()
        )
        sys_by_doc: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        orders_by_doc: dict[str, int] = defaultdict(int)
        for o in orders:
            src = party = None
            for part in str(o.note or "").split("|"):
                if part.startswith("源单号="):
                    src = part.split("=", 1)[1]
                elif part.startswith("工程="):
                    party = part.split("=", 1)[1]
            if not src:
                continue
            sys_by_doc[src] += _d(o.total_amount)
            orders_by_doc[src] += 1

        sys_total = sum((_d(o.total_amount) for o in orders), Decimal("0"))
        order_ids = [o.id for o in orders]
        item_count = (
            db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id.in_(order_ids)).count()
            if order_ids
            else 0
        )
        # 已确认的人工冲销（备注里带"重复行冲销"的红字应收）：这部分是**源表多算**，
        # 系统比 Excel 少是**正确**的，必须从差异里摘出来单独交代。
        adj_rows = (
            db.query(FinancialTransaction)
            .filter(
                FinancialTransaction.related_type == "sales_out",
                FinancialTransaction.related_order_id.in_(order_ids),
                FinancialTransaction.note.like("%重复行冲销%"),
            )
            .all()
            if order_ids
            else []
        )
        adjust_by_order: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for x in adj_rows:
            adjust_by_order[x.related_order_id] += abs(_d(x.amount))
        adjust_total = sum((v for v in adjust_by_order.values()), Decimal("0"))
        order_by_id = {o.id: o for o in orders}
        adjust_by_doc: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for oid, amt in adjust_by_order.items():
            o = order_by_id.get(oid)
            if not o:
                continue
            for part in str(o.note or "").split("|"):
                if part.startswith("源单号="):
                    adjust_by_doc[part.split("=", 1)[1]] += amt

        ar_total = Decimal("0")
        if order_ids:
            ar_rows = (
                db.query(FinancialTransaction)
                .filter(
                    FinancialTransaction.related_type == "sales_out",
                    FinancialTransaction.related_order_id.in_(order_ids),
                    FinancialTransaction.transaction_type == "receivable",
                )
                .all()
            )
            ar_total = sum((_d(x.amount) for x in ar_rows), Decimal("0"))
        stock_rows = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.related_type == "sales_out",
                InventoryTransaction.related_order_id.in_(order_ids),
            )
            .count()
            if order_ids
            else 0
        )
        submitted = sum(1 for o in orders if o.status == "submitted")
    finally:
        db.close()

    # ── ③ 逐张比对 ─────────────────────────────────────────────────────
    diffs = []
    rounding = []
    explained = []
    for doc in sorted(set(excel_by_doc) | set(sys_by_doc)):
        # Excel 里是"金额=数量×单价"的浮点值（如 1458.468），系统按分位入库（1458.47）。
        # 所以比对必须**先各自四舍五入到分**，否则每张单都能报出 0.002 的"差异"。
        e = excel_by_doc.get(doc, Decimal("0")).quantize(Decimal("0.01"))
        s = sys_by_doc.get(doc, Decimal("0")).quantize(Decimal("0.01"))
        # 这张源单若有已确认的重复行冲销，期望值就是 Excel − 冲销额。
        # 残差同样按"分位容差"判（Excel 是浮点积、系统按分入库，天然差几分钱）。
        adj = adjust_by_doc.get(doc, Decimal("0")).quantize(Decimal("0.01"))
        residual = (e - adj) - s
        if residual == 0:
            if adj:
                explained.append({"源单号": doc, "冲销额": str(adj), "Excel": str(e), "系统": str(s)})
            continue
        if abs(residual) <= Decimal("0.05"):
            if adj:
                explained.append(
                    {"源单号": doc, "冲销额": str(adj), "Excel": str(e), "系统": str(s), "残差": str(residual)}
                )
            else:
                rounding.append({"源单号": doc, "Excel": str(e), "系统": str(s), "差额": str(residual)})
            continue
        if True:
            diffs.append(
                {
                    "源单号": doc,
                    "Excel金额": str(e),
                    "系统金额": str(s),
                    "差额": str(e - s),
                    "系统单据数": orders_by_doc.get(doc, 0),
                    "Excel行数": rows_by_doc.get(doc, 0),
                }
            )

    covered = len({d for d in excel_by_doc if d in sys_by_doc})
    result = {
        "excel": {
            "原始行数": raw_rows,
            "原始总额": str(raw_total),
            "可建单行数": len(ok_recs),
            "可建单总额": str(kept_total),
            "去重丢弃金额": str(dropped_total),
            "去重丢弃行数": dropped_count,
            "源单号数": len(excel_by_doc),
        },
        "system": {
            "历史导入单据数": len(orders),
            "已提交单据数": submitted,
            "单据总额": str(sys_total),
            "明细行数": item_count,
            "应收合计": str(ar_total),
            "出库流水行数": stock_rows,
            "覆盖源单号数": covered,
        },
        "rounding": {"分位差异单数": len(rounding), "清单": rounding[:10]},
        "explained": {"已冲销单数": len(explained), "冲销合计": str(adjust_total), "清单": explained},
        "diff": {
            "差异单数": len(diffs),
            "差异总额": str(sum((_d(d["差额"]) for d in diffs), Decimal("0"))),
            "清单": diffs[:20],
        },
        "verdict": "PASS" if not diffs else "DIFF",
    }

    print("=" * 70)
    print("【源 Excel 口径】")
    print(f"  原始明细 {raw_rows} 行 / 总额 ¥{raw_total}")
    print(f"  可建单明细 {len(ok_recs)} 行 / 总额 ¥{kept_total}")
    print(f"  去重丢弃 {dropped_count} 行 / 金额 ¥{dropped_total}")
    print(f"  源单号 {len(excel_by_doc)} 个")
    print()
    print("【系统口径】")
    print(f"  历史导入单据 {len(orders)} 张（已提交 {submitted}）")
    print(f"  单据总额 ¥{sys_total}")
    print(f"  明细行 {item_count} 行")
    print(f"  应收合计 ¥{ar_total}")
    print(f"  出库流水 {stock_rows} 行")
    print(f"  覆盖源单号 {covered}/{len(excel_by_doc)}")
    print()
    print("【已确认冲销】")
    if explained:
        for d in explained:
            print(f"  {d['源单号']}  冲销 ¥{d['冲销额']}（Excel ¥{d['Excel']} → 系统 ¥{d['系统']}，源表重复行）")
        print(f"  小计 ¥{adjust_total}")
    else:
        print("  无")
    print()
    print("【逐张比对】")
    if rounding:
        print(f"  ℹ️ {len(rounding)} 张存在**分位四舍五入**差异（≤¥0.05，属正常）")
        for d in rounding[:5]:
            print(f"    {d['源单号']}  Excel ¥{d['Excel']}  系统 ¥{d['系统']}  差 ¥{d['差额']}")
    if not diffs:
        print("  ✅ 每张源单在系统里的金额与 Excel 一致（按分位对齐）")
    else:
        print(f"  ❌ {len(diffs)} 张有差异：")
        for d in diffs:
            print(
                f"    {d['源单号']}  Excel ¥{d['Excel金额']}  系统 ¥{d['系统金额']}"
                f"  差额 ¥{d['差额']}（系统 {d['系统单据数']} 张 / Excel {d['Excel行数']} 行）"
            )
    print()
    print(f"结论：{result['verdict']}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"（结果已写入 {args.json}）")
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
