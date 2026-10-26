"""按 id 精确清理 E2E 全流程自测产生的数据（2026-10-22）。

## 为什么需要它

`verify_full_business_flow.cjs` 走的单据**收过款**，而 `/sales-orders/{id}` 的删除
接口有保护：_"已登记过收款/付款的单据禁止删除"_（409）。所以脚本里的 API 清理只能删一半，
剩下的必须从数据层按 id 删。

## 安全边界

只删清单文件里**明确记录过的 id**（`erp_e2e_created.json`），不做"按名字批量删"：

  · 先删流水（financial_transactions / inventory_transactions）
  · 再删明细（sales_order_items / purchase_order_items）
  · 再删单据（sales_orders / purchase_orders）
  · 再删对账单 / 发票
  · 再删期初（opening_stock）
  · 最后删商品 / 客户

跑法：
    python scripts/clean_e2e_data.py --dry-run      # 只报告命中多少行
    python scripts/clean_e2e_data.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402

MANIFEST = Path("C:/Users/admi/AppData/Local/Temp/erp_e2e_created.json")

# (表, 列, 清单里的键, 追加条件)  —— 顺序即删除顺序（先子后父）
#
# ⚠️ 期初库存**不是一张表**：它是 inventory_transactions 里 related_type='opening'
#    的一行，且 related_order_id 为 NULL。所以上面按单号删流水的那两步删不到它，
#    必须按 product_id 单独清 —— 否则商品删了、流水还留着，
#    库存流水页会冒出一条"查不到商品"的孤儿记录（真实踩过）。
STEPS = [
    ("financial_transactions", "related_order_id", ["outboundId", "salesOrderId", "purchaseInboundId", "purchaseOrderId"], ""),
    ("inventory_transactions", "related_order_id", ["outboundId", "salesOrderId", "purchaseInboundId", "purchaseOrderId"], ""),
    ("sales_order_items", "sales_order_id", ["outboundId", "salesOrderId"], ""),
    ("purchase_order_items", "purchase_order_id", ["purchaseInboundId", "purchaseOrderId"], ""),
    ("sales_orders", "id", ["outboundId", "salesOrderId"], ""),
    ("purchase_orders", "id", ["purchaseInboundId", "purchaseOrderId"], ""),
    ("invoices", "id", ["invoiceId"], ""),
    ("statements", "id", ["statementId"], ""),
    # 期初（related_type='opening'）—— 必须在删商品之前
    ("inventory_transactions", "product_id", ["productId"], "related_type = 'opening'"),
    ("inventory_transactions", "product_id", ["productId"], ""),
    ("products", "id", ["productId"], ""),
    ("customers", "id", ["customerId"], ""),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="按 id 清理 E2E 测试数据")
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只看）")
    ap.add_argument("--dry-run", action="store_true", help="与默认行为相同：只报告命中行数")
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    mf = Path(args.manifest)
    if not mf.exists():
        print(f"❌ 找不到清单 {mf}（先跑 verify_full_business_flow.cjs）")
        return 1
    data = json.loads(mf.read_text(encoding="utf-8"))
    print(f"清单：客户「{data.get('customerName')}」/ 商品「{data.get('productName')}」")

    total = 0
    with engine.begin() as conn:
        for table, column, keys, extra in STEPS:
            ids = sorted({int(data[k]) for k in keys if data.get(k)})
            if not ids:
                continue
            # 表不存在就跳过（不同版本可能没有某张表）
            exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
            if not exists:
                print(f"  - {table} 不存在，跳过")
                continue
            sql = f"DELETE FROM {table} WHERE {column} = ANY(:ids)"
            if extra:
                sql += f" AND {extra}"
            n = conn.execute(text(sql), {"ids": ids}).rowcount
            total += n or 0
            suffix = f"（{extra}）" if extra else ""
            print(f"  {'删' if apply else '将删'} {table}.{column} in {ids}{suffix} → {n} 行")

        if not apply:
            conn.rollback()
            print(f"\n（只读模式：共命中 {total} 行，未删除；加 --apply 才真删）")
            return 0

    # 复核：客户 / 商品 / 孤儿流水（商品没了但流水还在 = 脏数据）
    with engine.connect() as conn:
        left_c = conn.execute(text("SELECT COUNT(*) FROM customers WHERE id = :i"), {"i": data.get("customerId") or 0}).scalar()
        left_p = conn.execute(text("SELECT COUNT(*) FROM products WHERE id = :i"), {"i": data.get("productId") or 0}).scalar()
        orphan = conn.execute(
            text("SELECT COUNT(*) FROM inventory_transactions WHERE product_id = :i"),
            {"i": data.get("productId") or 0},
        ).scalar()
    print(f"\n复核：客户残留 {left_c} 行 / 商品残留 {left_p} 行 / 孤儿库存流水 {orphan} 行；共删除 {total} 行")
    return 0 if left_c == 0 and left_p == 0 and orphan == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
