# -*- coding: utf-8 -*-
"""修掉「草稿创建也落账」：POST /sales-returns 改造前无条件加库存 + 冲应收，
于是 status='draft' 建出来的单子上写着草稿，账上却已经动过了。
改为与 PATCH/状态接口同一个收口函数，按状态决定是否落账。"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "routes" / "erp_sales.py"
text = TARGET.read_bytes().decode("utf-8").replace("\r\n", "\n")

OLD = '''    # —— 库存联动：退货增加现存量（inbound）——
    _sales_return_apply_stock(db, item, rows)

    # —— 财务联动：退货冲减应收。金额记负数（方向 in），对账时自然抵减 ——
    if total > 0:
        _write_finance(
            db,
            transaction_type="receivable",
            direction="in",
            amount=-total,
            related_type="sales_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            customer_id=payload.customer_id,
            warehouse_id=item.warehouse_id,
            occurred_at=return_date,
            note=f"销售退货 {item.return_no} 冲减应收",
        )
'''

NEW = '''    # —— 账实联动：只有「已退货(submitted)」才加库存 + 冲应收 ——
    #    改造前这里无条件落账，于是 status='draft' 建出来的单子
    #    写着草稿、账上却已经加了库存冲了应收，草稿再改明细又是另一笔账。
    #    收口到 _sync_sales_return_ledger，和 PATCH / 状态接口共用同一套判定。
    _sync_sales_return_ledger(
        db, item, rows, posted_before=False, content_changed=False
    )
'''

assert text.count(OLD) == 1, text.count(OLD)
text = text.replace(OLD, NEW)
TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK 草稿创建不再落账")
