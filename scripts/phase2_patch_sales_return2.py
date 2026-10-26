# -*- coding: utf-8 -*-
"""第二阶段 P2-1（第二步）：销售退货 PATCH 与状态接口统一「账实同步」。

第一版补丁把状态写在前面、明细写在后面，两个入口各自 sync，组合起来会重账：
`{status:'draft', items:[...]}` 这种一次带两样的请求，库存会被回滚后再加一遍。
本脚本改成**一个收口函数** `_sync_sales_return_ledger`，按四个组合算一次净动作：
    posted_before × posted_after × content_changed → 只在需要时 revert / apply
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app" / "api" / "v1" / "routes" / "erp_sales.py"

raw = TARGET.read_bytes().decode("utf-8")
text = raw.replace("\r\n", "\n")

PATCH_START = '@router.patch("/sales-returns/{return_id}", response_model=SalesReturnRead)'
STATUS_START = '@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)'
DELETE_START = '@router.delete("/sales-returns/{return_id}", status_code=status.HTTP_204_NO_CONTENT)'

for marker in (PATCH_START, STATUS_START, DELETE_START):
    assert text.count(marker) == 1, marker

i_patch = text.index(PATCH_START)
i_status = text.index(STATUS_START)
i_delete = text.index(DELETE_START)
# 两条注解之间夹着上一段的收尾空行，保留两行分隔
head = text[:i_patch]
mid = text[i_patch:i_status]
tail_doc = mid[: mid.index("def update_sales_return(")]
tail_blank = tail_doc[tail_doc.rstrip("\n").rfind("\n") + 1 :] or "\n\n"

NEW_PATCH = '''@router.patch("/sales-returns/{return_id}", response_model=SalesReturnRead)
def update_sales_return(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")

    posted_before = item.status == "submitted"

    text_fields = [
        "customer_name", "contact", "contact_phone", "address", "businesser",
        "return_date", "return_reason", "payment_method", "note",
        "source_order_no",
    ]
    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    for int_field in ("warehouse_id", "source_order_id", "customer_id"):
        if int_field in payload:
            raw_value = payload.get(int_field)
            setattr(item, int_field, int(raw_value) if raw_value not in ("", None) else None)

    # ⚠️ 状态先存起来，等明细处理完再一次性收口（见下面的 _sync_sales_return_ledger）。
    #    边改边落账会出现"回滚一次、再加一次"的重账。
    target_status = item.status
    if payload.get("status"):
        if str(payload["status"]) not in SALES_RETURN_STATUS:
            raise HTTPException(status_code=400, detail="销售退货状态非法")
        target_status = str(payload["status"])

    rows = _sales_return_items(db, item.id)
    content_changed = False
    # 传了明细就整单替换并重算金额/大写
    if isinstance(payload.get("items"), list):
        content_changed = True
        # ⚠️ 替换之前先把**这张单原来的同商品单价**记下来。
        #    PATCH 走的是**裸 dict**（不像 POST 有 Pydantic 挡在前面），
        #    `line_data.get("unit_price")` 缺失就是 None；不兜底就等于静默按 0 记账 ——
        #    金额/应收/财务流水全变 0，而库存照样动，三个数字永久对不上。
        previous_prices: dict[int, float] = {}
        for old in db.query(SalesReturnItem).filter(
            SalesReturnItem.sales_return_id == item.id
        ).all():
            old_price = float(old.unit_price or 0.0)
            if old.product_id is not None and old_price > 0:
                previous_prices.setdefault(int(old.product_id), old_price)

        db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == item.id).delete()
        rows = []
        total = 0.0
        for index, line in enumerate(payload["items"]):
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            pid = int(product_id) if product_id else None
            product = db.get(Product, pid) if pid else None
            unit = line_data.get("unit") or (product.unit if product else None)
            # 和 POST 一样：**按 unit 现场解析**换算率，绝不信客户端传的 factor
            factor = _resolve_unit_factor(db, pid, unit)
            quantity = _sales_return_quantity(line_data.get("quantity"), index)
            # 单价缺失 → 回查这张单原来的同商品单价；查不到（新加的行）→ 400
            unit_price = _sales_return_unit_price(
                line_data.get("unit_price"),
                index,
                product=product,
                factor=factor,
                fallback=previous_prices.get(pid) if pid else None,
            )
            row = SalesReturnItem(
                sales_return_id=item.id,
                product_id=pid,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=unit,
                quantity=quantity,
                # 3c：漏写这一列 = PATCH 一次就把换算率悄悄打回 1，库存按 1 倍扣
                unit_factor=factor,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)
        db.flush()

    item.status = target_status
    _sync_sales_return_ledger(
        db, item, rows, posted_before=posted_before, content_changed=content_changed
    )

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))



'''

NEW_STATUS = '''@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)
def update_sales_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """改销售退货状态，并**同步账实**（收口在 `_sync_sales_return_ledger`）。"""
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")

    posted_before = item.status == "submitted"
    item.status = status_value
    rows = _sales_return_items(db, item.id)
    _sync_sales_return_ledger(
        db, item, rows, posted_before=posted_before, content_changed=False
    )

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))



'''

HELPER = '''def _sync_sales_return_ledger(
    db: Session,
    item: SalesReturn,
    rows: list[SalesReturnItem],
    *,
    posted_before: bool,
    content_changed: bool,
) -> None:
    """把这张退货单的库存流水与应收冲减，对齐到**当前**状态与明细。

    落账口径（唯一）：`submitted`（已退货）才是真正动过库存与应收的态。
    改造前状态接口只写 `item.status`，于是「已退货」退回草稿后单据显示草稿、
    库存和应收却仍按退货记过账 —— 单据与账本永久对不上。

    四个组合的净动作（只在必要时动手，避免"回滚一次、再加一次"的重账）：
        posted_before × posted_after × changed → revert / apply
    """
    posted_after = item.status == "submitted"
    need_revert = posted_before and (content_changed or not posted_after)
    need_apply = posted_after and (content_changed or not posted_before)

    if need_revert:
        _revert_stock(db, "sales_return", item.id)
        _revert_finance(db, "sales_return", item.id)
        db.flush()

    if need_apply:
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


'''

new_text = head + HELPER + NEW_PATCH + NEW_STATUS + text[i_delete:]
TARGET.write_bytes(new_text.replace("\n", "\r\n").encode("utf-8"))
print("OK 已重写销售退货 PATCH / 状态接口 / 收口函数")
