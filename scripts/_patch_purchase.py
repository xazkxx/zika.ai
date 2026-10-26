# -*- coding: utf-8 -*-
"""给 erp_purchase.py 打 Decimal 补丁（CRLF 文件：先 LF 化，改完还原）。"""
P = r"E:/AI/ERP软件/app/api/v1/routes/erp_purchase.py"
raw = open(P, "rb").read()
crlf = raw.count(b"\r\n")
s = raw.replace(b"\r\n", b"\n").decode("utf-8")

def rep(old, new, tag):
    global s
    assert s.count(old) == 1, f"{tag}: 命中 {s.count(old)} 次\n---\n{old[:300]}"
    s = s.replace(old, new)
    print("OK", tag)

# 1) import
rep(
    "from app.models.supplier import Supplier\n",
    "from app.models.supplier import Supplier\nfrom app.core.money import ZERO, line_amount, money\n",
    "import",
)

# 2) 前次欠款：_prev_debt_total 现在返回 Decimal，round() 不能作用于 Decimal
rep(
    """    prev_debt = (
        round(_prev_debt_total(db, PurchaseOrder, PurchaseOrder.supplier_id, payload.supplier_id), 2)
        if doc_type == "inbound"
        else 0.0
    )""",
    """    prev_debt = (
        money(_prev_debt_total(db, PurchaseOrder, PurchaseOrder.supplier_id, payload.supplier_id))
        if doc_type == "inbound"
        else ZERO
    )""",
    "prev_debt",
)

# 3) 建单时先落 0（numeric 列，给 Decimal 而不是 float）
rep(
    "        total_amount=0.0,\n        doc_type=doc_type,",
    "        total_amount=ZERO,\n        doc_type=doc_type,",
    "PurchaseOrder total_amount 初始值",
)

# 4) 明细累加：0.0 + Decimal 会 TypeError
rep(
    "    total = 0.0\n    rows: list[PurchaseOrderItem] = []",
    "    total = ZERO  # 金额累加必须从 Decimal 起步：0.0 + Decimal 会 TypeError\n    rows: list[PurchaseOrderItem] = []",
    "total 起点",
)

# 5) 行金额：单价是 4 位费率
rep(
    "            amount=line.quantity * line.unit_price,",
    "            # 行金额统一走 line_amount：单价是 4 位\"费率\"，先用 2 位收口就是少钱\n            amount=line_amount(line.unit_price, line.quantity),",
    "采购行金额",
)

# 6) 结算链
rep(
    """    gross = round(total, 2)
    discount = round(float(payload.discount_amount or 0.0), 2)
    net = round(gross - discount, 2)
    paid = round(float(payload.paid_amount or 0.0), 2)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = round(net - paid, 2)""",
    """    gross = money(total)
    discount = money(payload.discount_amount)
    net = money(gross - discount)
    paid = money(payload.paid_amount)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = money(net - paid)""",
    "结算链",
)

rep(
    "    item.total_debt = round(prev_debt + current_debt, 2)",
    "    item.total_debt = money(prev_debt + current_debt)",
    "total_debt",
)

# 7) 采购订单不动欠款：清零四行
rep(
    """    if doc_type == "order":
        item.paid_amount = 0.0
        item.current_debt = 0.0
        item.prev_debt = 0.0
        item.total_debt = 0.0""",
    """    if doc_type == "order":
        item.paid_amount = ZERO
        item.current_debt = ZERO
        item.prev_debt = ZERO
        item.total_debt = ZERO""",
    "订单清零",
)

# 8) 转单不带收款
rep(
    "        paid_amount=0.0,  # 结算在入库单上另行登记，转单时不带收款",
    "        paid_amount=ZERO,  # 结算在入库单上另行登记，转单时不带收款",
    "转单 paid_amount",
)

# 9) 采购退货（表仍是 double，但金额口径统一走 line_amount 的 ROUND_HALF_UP）
rep(
    "    total = 0.0\n    rows: list[PurchaseReturnItem] = []",
    "    total = ZERO\n    rows: list[PurchaseReturnItem] = []",
    "退货 total 起点(建单)",
)
rep(
    "            amount=round(quantity * unit_price, 2),\n            note=line.note,",
    "            amount=line_amount(unit_price, quantity),\n            note=line.note,",
    "退货行金额(建单)",
)
rep(
    "    item.total_amount = round(total, 2)\n    item.amount_chinese = amount_to_chinese(item.total_amount)\n    db.commit()\n    db.refresh(item)\n\n    # —— 库存联动：退货减少现存量（outbound）——",
    "    item.total_amount = money(total)\n    item.amount_chinese = amount_to_chinese(item.total_amount)\n    db.commit()\n    db.refresh(item)\n\n    # —— 库存联动：退货减少现存量（outbound）——",
    "退货单头金额(建单)",
)

rep(
    "        rows = []\n        total = 0.0\n",
    "        rows = []\n        total = ZERO\n",
    "退货 total 起点(改单)",
)
rep(
    "                amount=round(quantity * unit_price, 2),\n                note=line_data.get(\"note\"),",
    "                amount=line_amount(unit_price, quantity),\n                note=line_data.get(\"note\"),",
    "退货行金额(改单)",
)
rep(
    "        item.total_amount = round(total, 2)\n        item.amount_chinese = amount_to_chinese(item.total_amount)\n        items_replaced = True",
    "        item.total_amount = money(total)\n        item.amount_chinese = amount_to_chinese(item.total_amount)\n        items_replaced = True",
    "退货单头金额(改单)",
)

out = s.replace("\n", "\r\n").encode("utf-8")
open(P, "wb").write(out)
chk = open(P, "rb").read()
print("CRLF", chk.count(b"\r\n"), "LF", chk.count(b"\n"), "原CRLF", crlf)
