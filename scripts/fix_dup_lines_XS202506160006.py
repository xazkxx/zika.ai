# -*- coding: utf-8 -*-
"""冲销 XS202506160006（系统单 XS20250616001）里被重复录入的 3 行明细。

## 背景

源 Excel 里这 3 行**同工程、同商品、同数量、同单价**各出现两次（业务员复制粘贴多算）：

    E30浸胶手套-9码   2750 × 2.20 = 6,050.00
    黄边线手套        1800 × 1.10 = 1,980.00
    帆布手套（普）     216 × 2.20 =   475.20
    ────────────────────────────────────
    合计                             8,505.20

单据总额 18,990.94 → 冲销后应为 **10,485.74**。

## 为什么不是"删流水"

删掉出库流水等于**伪造历史**：账上看不出这里曾经多记过一笔。本脚本用**红字**处理，
三件事都留痕：

  ① 库存：给 3 行重复明细各写一条 `inbound`（回库）流水，数量与出库行一一对应；
  ② 应收：写一笔 `receivable / direction=in / amount=-8505.20` 的红字；
  ③ 单据：删掉 3 行明细，重算 total_amount / receivable_amount / current_debt，
     并在备注尾部追加 `|冲销=重复行3行-8505.20`。

## 安全

· 默认 dry-run，只有 `--commit` 才写库；
· 写之前校验：这 3 行确实是"同商品同数量同单价"的重复行、且单据未收款未开票；
· 任何一条不满足就整体中止（不写一半）。

跑法：
    ./.venv/Scripts/python.exe scripts/fix_dup_lines_XS202506160006.py            # 预演
    ./.venv/Scripts/python.exe scripts/fix_dup_lines_XS202506160006.py --commit   # 执行
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

SRC_NO = "XS202506160006"
MARK = "|冲销=重复行3行-8505.20"


def main() -> int:
    ap = argparse.ArgumentParser(description="冲销重复录入的 3 行明细")
    ap.add_argument("--commit", action="store_true", help="真正写库")
    args = ap.parse_args()

    from app.api.v1.routes.erp_common import _apply_stock, _write_finance, amount_to_chinese
    from app.core.money import money
    from app.db.session import SessionLocal
    from app.models.sales_order import SalesOrder, SalesOrderItem

    db = SessionLocal()
    try:
        order = (
            db.query(SalesOrder)
            .filter(SalesOrder.note.like(f"%源单号={SRC_NO}%"))
            .first()
        )
        if order is None:
            print(f"❌ 找不到源单号 {SRC_NO} 对应的系统单")
            return 1
        if MARK.strip("|") in str(order.note or ""):
            print("ℹ️ 这张单已经冲销过了，无需重复处理")
            return 0

        print(f"单据 {order.order_no}（id={order.id}）状态={order.status} 总额={order.total_amount}")
        print(f"已收={order.received_amount} 应收={order.receivable_amount} 欠款={order.current_debt}")

        # ── 前置校验：必须未收款、未开票，否则冲销会打乱已发生的钱票 ──
        if Decimal(str(order.received_amount or 0)) != 0:
            print(f"❌ 已收款 ¥{order.received_amount}，不能直接冲销（先处理收款单）")
            return 1
        from app.models.invoice import Invoice
        invoiced = (
            db.query(Invoice).filter(Invoice.related_order_id == order.id).count()
        )
        if invoiced:
            print(f"❌ 已开票 {invoiced} 张，不能直接冲销（先处理发票）")
            return 1

        items = (
            db.query(SalesOrderItem)
            .filter(SalesOrderItem.sales_order_id == order.id)
            .order_by(SalesOrderItem.id)
            .all()
        )
        # ── 找出重复行：按 (商品名, 数量, 单价) 分组，第 2 条起视为重复 ──
        seen: dict[tuple, SalesOrderItem] = {}
        dupes: list[SalesOrderItem] = []
        for it in items:
            key = (it.product_name, int(it.quantity), str(it.unit_price))
            if key in seen:
                dupes.append(it)
            else:
                seen[key] = it

        if len(dupes) != 3:
            print(f"❌ 预期 3 行重复明细，实际识别到 {len(dupes)} 行，中止（不改库）")
            for it in dupes:
                print(f"    id={it.id} {it.product_name} {it.quantity}×{it.unit_price}")
            return 1

        cut = sum((Decimal(str(it.amount)) for it in dupes), Decimal("0"))
        print()
        print("将冲销的重复明细：")
        for it in dupes:
            print(f"  id={it.id}  {it.product_name}  {it.quantity} × {it.unit_price} = ¥{it.amount}")
        print(f"合计冲销 ¥{cut}")

        new_total = money(Decimal(str(order.total_amount)) - cut)
        print(f"单据总额：{order.total_amount} → ¥{new_total}")
        print()

        if not args.commit:
            print("⚠️ 这是预演。要真正执行请加 --commit")
            return 0

        # ── ① 库存回库（红字）──
        for it in dupes:
            _apply_stock(
                db,
                product_id=it.product_id,
                warehouse_id=order.warehouse_id,
                quantity=int(it.quantity),
                transaction_type="inbound",
                unit_price=float(it.unit_price or 0),
                related_type="sales_out",
                related_order_id=order.id,
                doc_no=order.order_no,
                note=f"历史导入重复行冲销（回库）{order.order_no}",
            )
        # ── ② 应收红字 ──
        _write_finance(
            db,
            transaction_type="receivable",
            direction="in",
            amount=float(-cut),
            related_type="sales_out",
            related_order_id=order.id,
            doc_no=order.order_no,
            customer_id=order.customer_id,
            warehouse_id=order.warehouse_id,
            occurred_at=order.order_date,
            note=f"历史导入重复行冲销 {order.order_no}（-¥{cut}）",
        )
        # ── ③ 删行 + 重算单据 ──
        for it in dupes:
            db.delete(it)
        order.total_amount = new_total
        order.receivable_amount = new_total
        order.current_debt = money(new_total - Decimal(str(order.received_amount or 0)))
        order.amount_chinese = amount_to_chinese(new_total)
        order.note = (str(order.note or "") + MARK)[:255]
        db.commit()

        print("✅ 已冲销：库存回库 3 行、应收红字 1 笔、明细删除 3 行")
        print(f"   单据新总额 ¥{new_total}，应收 ¥{order.receivable_amount}，欠款 ¥{order.current_debt}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
