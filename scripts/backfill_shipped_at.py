# -*- coding: utf-8 -*-
"""回填 sales_orders.shipped_at —— 对账单大融合（2026-10-21 任务一）。

口径：取这张单**最早一条出库流水**的 created_at（转单出库那一刻 = 发货那一刻）。
没有流水的单（纯订单 doc_type=order、未转单）保持 NULL —— 没发货就是没发货，
不许用默认值伪装。幂等：只回填 shipped_at IS NULL 的行，重跑无副作用。
"""

from sqlalchemy import text

from app.db.session import SessionLocal


def backfill(db) -> dict:
    rows = db.execute(
        text(
            """
            SELECT o.id,
                   (SELECT MIN(i.created_at)
                      FROM inventory_transactions i
                     WHERE i.related_order_id = o.id
                       AND i.transaction_type = 'outbound')
                      AS first_out
              FROM sales_orders o
             WHERE o.shipped_at IS NULL
               AND o.doc_type = 'outbound'
            """
        )
    ).all()
    filled = 0
    for order_id, first_out in rows:
        if first_out is not None:
            db.execute(
                text("UPDATE sales_orders SET shipped_at = :t WHERE id = :i"),
                {"t": first_out, "i": order_id},
            )
            filled += 1
    db.commit()
    return {"scanned": len(rows), "filled": filled}


if __name__ == "__main__":
    db = SessionLocal()
    try:
        out = backfill(db)
        print(f"扫描 {out['scanned']} 张待回填单据，回填 {out['filled']} 张（其余无出库流水，保持空）")
    finally:
        db.close()
