# -*- coding: utf-8 -*-
"""第二阶段 P2-1：销售退货「反审核/作废」落账联动 + 合同 PATCH 支持换对方单位。

背景：`PATCH /sales-returns/{id}/status` 改造前只改状态字面量 ——
把一张「已退货」退回草稿后，库存流水与应收冲减**还在账上**，
单据看着是草稿、账上却已经动了，这是最危险的一类不一致。
本脚本把「已退货(submitted)」定为唯一落账态：
  · 从 submitted 走出去 → 撤销库存 + 撤销应收流水
  · 走进 submitted        → 重放库存 + 重写应收流水
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "api" / "v1" / "routes" / "erp_sales.py"

raw = TARGET.read_bytes().decode("utf-8")
text = raw.replace("\r\n", "\n")
original = text

# ---------------------------------------------------------------- 1. 状态接口
OLD_STATUS = '''@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)
def update_sales_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))
'''

NEW_STATUS = '''@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)
def update_sales_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """改销售退货状态，并**同步账实**。

    落账口径（唯一）：`submitted`（已退货）是这张单真正动过库存与应收的态。
      · 从 submitted 走出去（反审核→草稿 / 作废）→ 撤销库存入库 + 撤销应收冲减
      · 走进 submitted（草稿→审核）→ 重放库存入库 + 重写应收冲减

    改造前这里只写 `item.status`，于是「已退货」退回草稿后单据显示草稿、
    库存和应收却仍然按退货记过账 —— 单据与账本永久对不上。
    """
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")

    previous = item.status
    if previous == status_value:
        return _sales_return_payload(item, _sales_return_items(db, item.id))

    item.status = status_value
    rows = _sales_return_items(db, item.id)

    if previous == "submitted" and status_value != "submitted":
        # 反审核 / 作废：把这张单造成的库存与应收动作整笔撤回
        _revert_stock(db, "sales_return", item.id)
        _revert_finance(db, "sales_return", item.id)
    elif status_value == "submitted" and previous != "submitted":
        # 草稿重新审核：按当前明细重新落账
        _sales_return_apply_stock(db, item, rows)
        total = float(item.total_amount or 0.0)
        if total > 0:
            _write_finance(
                db,
                transaction_type="receivable",
                direction="in",
                amount=-total,
                related_type="sales_return",
                related_order_id=item.id,
                doc_no=item.return_no,
                customer_id=item.customer_id,
                warehouse_id=item.warehouse_id,
                occurred_at=item.return_date,
                note=f"销售退货 {item.return_no} 冲减应收",
            )

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))
'''

assert text.count(OLD_STATUS) == 1, f"状态接口锚点命中 {text.count(OLD_STATUS)} 次"
text = text.replace(OLD_STATUS, NEW_STATUS)

# ------------------------------------------------- 2. 明细替换时同步应收流水
OLD_ITEMS_TAIL = '''        # ⚠️ 明细变了，库存流水必须跟着重写：先冲销旧的，再按新明细写。
        #    不重写的话，改一次退货单，单据与现存量就永久对不上
        #    （与 3b 修的「采购退货 PATCH 不同步库存」是同一个洞）。
        _revert_stock(db, "sales_return", item.id)
        _sales_return_apply_stock(db, item, rows)
'''

NEW_ITEMS_TAIL = '''        # ⚠️ 明细变了，库存流水必须跟着重写：先冲销旧的，再按新明细写。
        #    不重写的话，改一次退货单，单据与现存量就永久对不上
        #    （与 3b 修的「采购退货 PATCH 不同步库存」是同一个洞）。
        _revert_stock(db, "sales_return", item.id)
        _sales_return_apply_stock(db, item, rows)

        # 金额跟着变了，应收冲减流水也必须重写 —— 否则库存按新明细动、
        # 应收仍按旧金额挂着（单据 ¥500、账上冲 ¥800）。只有已落账的单才需要。
        if item.status == "submitted":
            _revert_finance(db, "sales_return", item.id)
            new_total = float(item.total_amount or 0.0)
            if new_total > 0:
                _write_finance(
                    db,
                    transaction_type="receivable",
                    direction="in",
                    amount=-new_total,
                    related_type="sales_return",
                    related_order_id=item.id,
                    doc_no=item.return_no,
                    customer_id=item.customer_id,
                    warehouse_id=item.warehouse_id,
                    occurred_at=item.return_date,
                    note=f"销售退货 {item.return_no} 冲减应收",
                )
'''

assert text.count(OLD_ITEMS_TAIL) == 1, "明细替换锚点未命中"
text = text.replace(OLD_ITEMS_TAIL, NEW_ITEMS_TAIL)

# --------------------------------- 3. 合同 PATCH：允许改对方单位（草稿编辑要用）
OLD_CONTRACT_NUM = '''    number_fields = ["tax_rate", "penalty_rate", "inspection_days", "objection_days", "copies", "warehouse_id"]
'''
NEW_CONTRACT_NUM = '''    number_fields = [
        "tax_rate", "penalty_rate", "inspection_days", "objection_days", "copies", "warehouse_id",
        # 草稿编辑要能换对方单位；只改 party_id 不改 party_name 会串名字，
        # 所以 create 侧的 party_name 快照由下面的通用 text_fields 一起覆盖。
        "party_id",
    ]
'''
assert text.count(OLD_CONTRACT_NUM) == 1
text = text.replace(OLD_CONTRACT_NUM, NEW_CONTRACT_NUM)

# --------------------------------- 4. 确认需要导入的辅助函数都在（避免 UnboundLocal）
needles = ["_revert_finance", "_revert_stock", "_write_finance"]
for needle in needles:
    assert needle in text.split("async def")[0] or needle in text, needle

assert "_revert_finance" in text

TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK: erp_sales.py 已更新")
print("LF->CRLF 还原：", TARGET.read_bytes().count(b"\r\n"), "行")
