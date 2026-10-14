"""库存管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

库存查询与流水 / 调拨 / 盘点 / 报损报溢 / 组合拆卸。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.assembly import ASSEMBLY_PREFIX, ASSEMBLY_STATUS, ASSEMBLY_TYPES, AssemblyOrder, AssemblyOrderItem
from app.models.inventory import InventoryTransaction
from app.models.inventory_adjustment import ADJUSTMENT_STATUS, ADJUST_TYPES, InventoryAdjustment, InventoryAdjustmentItem
from app.models.inventory_transfer import InventoryTransfer, InventoryTransferItem, TRANSFER_STATUS
from app.models.product import Product
from app.models.stocktaking import STOCKTAKING_STATUS, Stocktaking, StocktakingItem
from app.models.warehouse import Warehouse
from app.schemas import (
    AssemblyOrderCreate,
    AssemblyOrderRead,
    InventoryAdjustmentCreate,
    InventoryAdjustmentRead,
    InventoryTransactionCreate,
    InventoryTransactionRead,
    InventoryTransferCreate,
    InventoryTransferRead,
    StocktakingCreate,
    StocktakingRead,
)
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _adjust_items,
    _apply_stock,
    _bom_children_map,
    _default_warehouse,
    _net_stock_map,
    _next_doc_no,
    _on_hand_by_product,
    _paginate,
    _resolve_cost_price,
    _resolve_item_snapshot,
    _resolve_warehouse_id,
    _revert_stock,
    _stocktaking_items,
    _transfer_items,
)

router = APIRouter(prefix="", tags=["erp"])




def _stock_status(quantity: int, lower: int | None, upper: int | None) -> str:
    """按商品自带的库存上下限判定状态。

    没设下限的商品不会因为「库存为 0」被反复打扰 —— 只有真的欠货（负库存）
    才报缺货。要让某个商品参与预警，去它的档案里填库存下限即可。
    """
    if quantity < 0:
        return "shortage"
    if lower is not None and quantity <= int(lower):
        return "low_stock"
    if upper is not None and quantity >= int(upper):
        return "overstock"
    return "normal"



@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[InventoryTransactionRead]:
    items = _paginate(db.query(InventoryTransaction).order_by(InventoryTransaction.id.desc()), skip, limit).all()
    return items



def _stock_rows(
    db: Session,
    warehouse_id: int | None = None,
    product_id: int | None = None,
) -> list[dict[str, object]]:
    """聚合现存量明细：一行 = 一个「仓库 × 商品」组合。

    现存量不落库，永远由库存流水实时算出 —— 落库的话迟早会和流水对不上。
    """
    products = {p.id: p for p in db.query(Product).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}

    rows: list[dict[str, object]] = []
    for (pid, wid), quantity in _net_stock_map(db).items():
        if product_id is not None and pid != product_id:
            continue
        if warehouse_id is not None and wid != warehouse_id:
            continue
        product = products.get(pid)
        warehouse = warehouses.get(wid)
        lower = getattr(product, "stock_lower", None)
        upper = getattr(product, "stock_upper", None)
        rows.append(
            {
                "product_id": pid,
                "sku": getattr(product, "sku", None),
                "product_name": getattr(product, "name", None) or f"商品-{pid}",
                "standards": getattr(product, "standards", None),
                "unit": getattr(product, "unit", None),
                "warehouse_id": wid,
                "warehouse_name": getattr(warehouse, "name", None) or f"仓库-{wid}",
                "quantity": quantity,
                "stock_lower": lower,
                "stock_upper": upper,
                "status": _stock_status(quantity, lower, upper),
                "purchase_price": float(getattr(product, "purchase_price", 0.0) or 0.0),
            }
        )
    rows.sort(key=lambda row: (row["warehouse_id"], row["product_id"]))
    return rows



def _summarize_stock_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    """现存量汇总：行数、总量、成本口径库存额、各类预警数。"""
    counts = {"shortage": 0, "low_stock": 0, "overstock": 0, "normal": 0}
    total_quantity = 0
    estimated_value = 0.0
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        quantity = int(row["quantity"])
        total_quantity += quantity
        estimated_value += quantity * float(row["purchase_price"])
    return {
        "stock_lines": len(rows),
        "total_quantity": total_quantity,
        "estimated_value": round(estimated_value, 2),
        "shortage_count": counts["shortage"],
        "low_stock_count": counts["low_stock"],
        "overstock_count": counts["overstock"],
        "normal_count": counts["normal"],
        "alert_count": counts["shortage"] + counts["low_stock"] + counts["overstock"],
    }



@router.get("/inventory/stock")
def inventory_stock(
    warehouse_id: int | None = Query(None),
    product_id: int | None = Query(None),
    only_abnormal: bool = Query(False),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """现存量查询：仓库 × 商品的实时库存。

    only_abnormal=true 只返回低于下限 / 高于上限的行（现存量看板默认视图）。
    """
    rows = _stock_rows(db, warehouse_id, product_id)
    if only_abnormal:
        rows = [row for row in rows if row["status"] != "normal"]
    if keyword:
        needle = keyword.strip().lower()
        if needle:
            rows = [
                row
                for row in rows
                if needle in str(row["product_name"]).lower()
                or needle in str(row["sku"] or "").lower()
                or needle in str(row["warehouse_name"]).lower()
            ]
    return {"rows": rows, "summary": _summarize_stock_rows(rows)}



@router.get("/inventory/summary")
def inventory_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """库存总览：现存量口径的汇总数字，供首页看板使用。"""
    rows = _stock_rows(db)
    summary = _summarize_stock_rows(rows)
    summary["product_count"] = len({row["product_id"] for row in rows})
    summary["warehouse_count"] = len({row["warehouse_id"] for row in rows})
    return summary



@router.get("/inventory/alerts")
def list_inventory_alerts(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """库存预警：按商品自带的库存下限 / 上限判定。

    改造前这里写死了「低于 15 补货、高于 20 正常」，与实际商品完全脱节。
    现在每个商品在自己的档案里设定下限/上限，没设的商品不参与预警。
    """
    alerts: list[dict[str, object]] = []
    for row in _stock_rows(db):
        status = row["status"]
        if status == "normal":
            continue
        lower = row["stock_lower"]
        upper = row["stock_upper"]
        quantity = int(row["quantity"])

        if status == "shortage":
            label = "缺货"
            recommendation = f"现存量已为负，建议立即补货至 {lower} 以上"
        elif status == "low_stock":
            label = "低库存"
            recommendation = f"低于下限 {lower}，建议补货"
        else:
            label = "积压"
            recommendation = f"高于上限 {upper}，建议减少采购或促销消化"

        alerts.append(
            {
                # 兼容字段（首页看板在用）
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "warehouse_id": row["warehouse_id"],
                "available_quantity": quantity,
                "threshold": lower,
                "status": status,
                "recommendation": recommendation,
                # 补充字段
                "label": label,
                "sku": row["sku"],
                "unit": row["unit"],
                "warehouse_name": row["warehouse_name"],
                "stock_lower": lower,
                "stock_upper": upper,
            }
        )
    return alerts



@router.post("/inventory", response_model=InventoryTransactionRead, status_code=status.HTTP_201_CREATED)
def create_inventory_transaction(payload: InventoryTransactionCreate, db: Session = Depends(get_db)) -> InventoryTransaction:
    item = InventoryTransaction(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



def _transfer_payload(item: InventoryTransfer, rows: list[InventoryTransferItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "transfer_no": item.transfer_no,
        "from_warehouse_id": item.from_warehouse_id,
        "to_warehouse_id": item.to_warehouse_id,
        "transfer_date": item.transfer_date,
        "handler": item.handler,
        "reason": item.reason,
        "note": item.note,
        "status": item.status,
        "total_quantity": item.total_quantity,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "inventory_transfer_id": row.inventory_transfer_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "note": row.note,
            }
            for row in rows
        ],
    }



def _transfer_apply_stock(db: Session, item: InventoryTransfer, rows: list[InventoryTransferItem]) -> None:
    """把这张调拨单的库存动作写进流水：调出仓减、调入仓加。"""
    for row in rows:
        qty = int(row.quantity or 0)
        if qty == 0 or row.product_id is None:
            continue
        # 调出：outbound 流水（现存量减少）
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=item.from_warehouse_id,
            quantity=qty,
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="inv_transfer",
            related_order_id=item.id,
            doc_no=item.transfer_no,
            note=f"调拨出 {item.transfer_no}",
        )
        # 调入：inbound 流水（现存量增加）
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=item.to_warehouse_id,
            quantity=qty,
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="inv_transfer",
            related_order_id=item.id,
            doc_no=item.transfer_no,
            note=f"调拨入 {item.transfer_no}",
        )



def _validate_transfer_warehouses(db: Session, from_id: int | None, to_id: int | None) -> tuple[Warehouse, Warehouse]:
    if not from_id or not to_id:
        raise HTTPException(status_code=400, detail="调拨单必须同时指定调出仓库与调入仓库")
    if int(from_id) == int(to_id):
        raise HTTPException(status_code=400, detail="调出仓库与调入仓库不能相同")
    from_wh = db.get(Warehouse, int(from_id))
    if from_wh is None:
        raise HTTPException(status_code=404, detail="调出仓库不存在")
    to_wh = db.get(Warehouse, int(to_id))
    if to_wh is None:
        raise HTTPException(status_code=404, detail="调入仓库不存在")
    return from_wh, to_wh



@router.get("/inventory-transfers/meta")
def inventory_transfer_meta() -> dict[str, object]:
    """调拨页字典：状态。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in TRANSFER_STATUS.items()],
    }



@router.get("/inventory-transfers")
def list_inventory_transfers(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(InventoryTransfer).order_by(InventoryTransfer.id.desc())
    if status_value:
        query = query.filter(InventoryTransfer.status == status_value)
    if warehouse_id:
        # 该仓库只要出现在「调出」或「调入」任一侧就算命中
        query = query.filter(
            or_(
                InventoryTransfer.from_warehouse_id == warehouse_id,
                InventoryTransfer.to_warehouse_id == warehouse_id,
            )
        )
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                InventoryTransfer.transfer_no.ilike(like),
                InventoryTransfer.handler.ilike(like),
                InventoryTransfer.reason.ilike(like),
                InventoryTransfer.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_transfer_payload(item, _transfer_items(db, item.id)) for item in items]



@router.get("/inventory-transfers/{transfer_id}", response_model=InventoryTransferRead)
def get_inventory_transfer(transfer_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(InventoryTransfer, transfer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    return _transfer_payload(item, _transfer_items(db, item.id))



@router.post("/inventory-transfers", response_model=InventoryTransferRead, status_code=status.HTTP_201_CREATED)
def create_inventory_transfer(
    payload: InventoryTransferCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    _validate_transfer_warehouses(db, payload.from_warehouse_id, payload.to_warehouse_id)

    if payload.status and payload.status not in TRANSFER_STATUS:
        raise HTTPException(status_code=400, detail="调拨单状态非法")

    transfer_no = (payload.transfer_no or "").strip() or _next_doc_no(
        db, InventoryTransfer, "DBD", field="transfer_no"
    )
    if db.query(InventoryTransfer).filter(InventoryTransfer.transfer_no == transfer_no).first():
        raise HTTPException(status_code=400, detail="调拨单号已存在")

    transfer_date = payload.transfer_date or datetime.now().strftime("%Y-%m-%d")

    item = InventoryTransfer(
        transfer_no=transfer_no,
        from_warehouse_id=int(payload.from_warehouse_id),
        to_warehouse_id=int(payload.to_warehouse_id),
        transfer_date=transfer_date,
        handler=payload.handler,
        reason=payload.reason,
        note=payload.note,
        status=payload.status or "submitted",
        total_quantity=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total_qty = 0.0
    rows: list[InventoryTransferItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        quantity = float(line.quantity or 0.0)
        row = InventoryTransferItem(
            inventory_transfer_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=float(line.unit_price or 0.0),
            note=line.note,
        )
        total_qty += quantity
        rows.append(row)
    db.add_all(rows)

    item.total_quantity = round(total_qty, 2)
    db.commit()
    db.refresh(item)

    # —— 库存联动：调出仓减、调入仓加（两条流水，共用 related_type）——
    _transfer_apply_stock(db, item, rows)
    db.commit()
    db.refresh(item)
    return _transfer_payload(item, rows)



@router.patch("/inventory-transfers/{transfer_id}", response_model=InventoryTransferRead)
def update_inventory_transfer(
    transfer_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(InventoryTransfer, transfer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")

    # 仓库或明细一旦变化，库存流水必须整体重放，否则会出现「调出减了但没加回来」
    stock_touched = False

    for field in ("transfer_date", "handler", "reason", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "from_warehouse_id" in payload or "to_warehouse_id" in payload:
        raw_from = payload.get("from_warehouse_id", item.from_warehouse_id)
        raw_to = payload.get("to_warehouse_id", item.to_warehouse_id)
        _validate_transfer_warehouses(db, raw_from, raw_to)
        item.from_warehouse_id = int(raw_from)
        item.to_warehouse_id = int(raw_to)
        stock_touched = True

    if payload.get("status"):
        if str(payload["status"]) not in TRANSFER_STATUS:
            raise HTTPException(status_code=400, detail="调拨单状态非法")
        item.status = str(payload["status"])

    rows = _transfer_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(InventoryTransferItem).filter(
            InventoryTransferItem.inventory_transfer_id == item.id
        ).delete()
        rows = []
        total_qty = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            row = InventoryTransferItem(
                inventory_transfer_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=float(line_data.get("unit_price") or 0.0),
                note=line_data.get("note"),
            )
            total_qty += quantity
            rows.append(row)
        db.add_all(rows)
        item.total_quantity = round(total_qty, 2)
        stock_touched = True

    if stock_touched:
        # 先冲销这张单原有的全部流水，再按最新内容重放
        _revert_stock(db, "inv_transfer", item.id)
        _transfer_apply_stock(db, item, rows)

    db.commit()
    db.refresh(item)
    return _transfer_payload(item, rows)



@router.patch("/inventory-transfers/{transfer_id}/status", response_model=InventoryTransferRead)
def update_inventory_transfer_status(
    transfer_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(InventoryTransfer, transfer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in TRANSFER_STATUS:
        raise HTTPException(status_code=400, detail="调拨单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _transfer_payload(item, _transfer_items(db, item.id))



@router.delete("/inventory-transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_transfer(transfer_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(InventoryTransfer, transfer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    # 库存联动回滚：冲销这张单的 outbound + inbound 两条流水，两侧仓库同时复原
    _revert_stock(db, "inv_transfer", transfer_id)
    db.query(InventoryTransferItem).filter(
        InventoryTransferItem.inventory_transfer_id == transfer_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _stocktaking_payload(item: Stocktaking, rows: list[StocktakingItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "check_no": item.check_no,
        "warehouse_id": item.warehouse_id,
        "check_date": item.check_date,
        "handler": item.handler,
        "scope": item.scope,
        "note": item.note,
        "status": item.status,
        "total_profit": item.total_profit,
        "total_loss": item.total_loss,
        "profit_lines": item.profit_lines,
        "loss_lines": item.loss_lines,
        "total_amount": item.total_amount,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "stocktaking_id": row.stocktaking_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "book_quantity": row.book_quantity,
                "actual_quantity": row.actual_quantity,
                "diff_quantity": row.diff_quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "note": row.note,
            }
            for row in rows
        ],
    }



def _stocktaking_totals(rows: list[StocktakingItem]) -> tuple[float, float, int, int, float]:
    """按明细算出 盘盈量 / 盘亏量 / 盘盈行数 / 盘亏行数 / 盈亏金额净额。"""
    profit = 0.0
    loss = 0.0
    profit_lines = 0
    loss_lines = 0
    amount = 0.0
    for row in rows:
        diff = float(row.diff_quantity or 0.0)
        if diff > 0:
            profit += diff
            profit_lines += 1
        elif diff < 0:
            loss += abs(diff)
            loss_lines += 1
        amount += diff * float(row.unit_price or 0.0)
    return round(profit, 2), round(loss, 2), profit_lines, loss_lines, round(amount, 2)



def _stocktaking_apply_stock(db: Session, item: Stocktaking, rows: list[StocktakingItem]) -> None:
    """把这张盘点单的盈亏写进库存流水：盘盈 inbound、盘亏 outbound。"""
    for row in rows:
        diff = int(round(float(row.diff_quantity or 0.0)))
        if diff == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=item.warehouse_id,
            quantity=abs(diff),
            transaction_type="inbound" if diff > 0 else "outbound",
            unit_price=row.unit_price,
            related_type="inv_check",
            related_order_id=item.id,
            doc_no=item.check_no,
            note=("盘盈 " if diff > 0 else "盘亏 ") + item.check_no,
        )



def _book_stock_of(db: Session, warehouse_id: int, product_id: int) -> float:
    """某个商品在某仓库的账面数（= 实时现存量）。"""
    return float(_net_stock_map(db).get((int(product_id), int(warehouse_id)), 0))



@router.get("/stocktakings/meta")
def stocktaking_meta() -> dict[str, object]:
    """盘点页字典：状态。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in STOCKTAKING_STATUS.items()],
    }



@router.get("/stocktakings/plan")
def stocktaking_plan(
    warehouse_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """盘点底稿：按仓库带出全部账面库存，前端据此生成明细行。

    这是盘点与其他单据最大的不同 —— 盘点不该让人一行行敲账面数，
    账面数是系统算出来的，人只负责填实盘数。
    """
    warehouse = db.get(Warehouse, int(warehouse_id))
    if warehouse is None:
        raise HTTPException(status_code=404, detail="盘点仓库不存在")
    rows = _stock_rows(db, warehouse_id=int(warehouse_id))
    return {
        "warehouse_id": int(warehouse_id),
        "warehouse_name": warehouse.name,
        "count": len(rows),
        "rows": [
            {
                "product_id": row["product_id"],
                "sku": row["sku"],
                "product_name": row["product_name"],
                "standards": row["standards"],
                "unit": row["unit"],
                "book_quantity": row["quantity"],
                "unit_price": row["purchase_price"],
            }
            for row in rows
        ],
    }



@router.get("/stocktakings")
def list_stocktakings(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(Stocktaking).order_by(Stocktaking.id.desc())
    if status_value:
        query = query.filter(Stocktaking.status == status_value)
    if warehouse_id:
        query = query.filter(Stocktaking.warehouse_id == warehouse_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Stocktaking.check_no.ilike(like),
                Stocktaking.handler.ilike(like),
                Stocktaking.scope.ilike(like),
                Stocktaking.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_stocktaking_payload(item, _stocktaking_items(db, item.id)) for item in items]



@router.get("/stocktakings/{check_id}", response_model=StocktakingRead)
def get_stocktaking(check_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Stocktaking, check_id)
    if item is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    return _stocktaking_payload(item, _stocktaking_items(db, item.id))



@router.post("/stocktakings", response_model=StocktakingRead, status_code=status.HTTP_201_CREATED)
def create_stocktaking(payload: StocktakingCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    warehouse = db.get(Warehouse, int(payload.warehouse_id))
    if warehouse is None:
        raise HTTPException(status_code=404, detail="盘点仓库不存在")

    if payload.status and payload.status not in STOCKTAKING_STATUS:
        raise HTTPException(status_code=400, detail="盘点单状态非法")

    check_no = (payload.check_no or "").strip() or _next_doc_no(
        db, Stocktaking, "PD", field="check_no"
    )
    if db.query(Stocktaking).filter(Stocktaking.check_no == check_no).first():
        raise HTTPException(status_code=400, detail="盘点单号已存在")

    check_date = payload.check_date or datetime.now().strftime("%Y-%m-%d")

    item = Stocktaking(
        check_no=check_no,
        warehouse_id=int(payload.warehouse_id),
        check_date=check_date,
        handler=payload.handler,
        scope=payload.scope,
        note=payload.note,
        status=payload.status or "submitted",
        total_profit=0.0,
        total_loss=0.0,
        profit_lines=0,
        loss_lines=0,
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    rows: list[StocktakingItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        actual = float(line.actual_quantity or 0.0)
        # 账面数：传了就用传的，没传就按当前现存量带出（盘点底稿路径）
        if line.book_quantity is None:
            book = _book_stock_of(db, item.warehouse_id, line.product_id) if line.product_id else 0.0
        else:
            book = float(line.book_quantity or 0.0)
        diff = round(actual - book, 2)
        unit_price = _resolve_cost_price(db, line.product_id, line.unit_price)
        rows.append(
            StocktakingItem(
                stocktaking_id=item.id,
                product_id=line.product_id,
                product_name=name or line.product_name,
                standards=standards,
                unit=unit,
                book_quantity=round(book, 2),
                actual_quantity=round(actual, 2),
                diff_quantity=diff,
                unit_price=unit_price,
                amount=round(diff * unit_price, 2),
                note=line.note,
            )
        )
    db.add_all(rows)

    profit, loss, profit_lines, loss_lines, amount = _stocktaking_totals(rows)
    item.total_profit = profit
    item.total_loss = loss
    item.profit_lines = profit_lines
    item.loss_lines = loss_lines
    item.total_amount = amount
    db.commit()
    db.refresh(item)

    # —— 库存联动：盈亏直接调整现存量（盘盈加、盘亏减）——
    _stocktaking_apply_stock(db, item, rows)
    db.commit()
    db.refresh(item)
    return _stocktaking_payload(item, rows)



@router.patch("/stocktakings/{check_id}", response_model=StocktakingRead)
def update_stocktaking(
    check_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Stocktaking, check_id)
    if item is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")

    # 明细或仓库一旦变化，库存流水必须整体重放，否则会留下按旧明细调整过的库存
    stock_touched = False

    for field in ("check_date", "handler", "scope", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="盘点仓库不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    if payload.get("status"):
        if str(payload["status"]) not in STOCKTAKING_STATUS:
            raise HTTPException(status_code=400, detail="盘点单状态非法")
        item.status = str(payload["status"])

    rows = _stocktaking_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(StocktakingItem).filter(
            StocktakingItem.stocktaking_id == item.id
        ).delete(synchronize_session=False)
        rows = []
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            actual = float(line_data.get("actual_quantity") or 0.0)
            raw_book = line_data.get("book_quantity")
            if raw_book in ("", None):
                book = (
                    _book_stock_of(db, item.warehouse_id, int(product_id))
                    if product_id
                    else 0.0
                )
            else:
                book = float(raw_book or 0.0)
            diff = round(actual - book, 2)
            unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
            rows.append(
                StocktakingItem(
                    stocktaking_id=item.id,
                    product_id=int(product_id) if product_id else None,
                    product_name=line_data.get("product_name") or (product.name if product else None),
                    standards=line_data.get("standards") or (product.standards if product else None),
                    unit=line_data.get("unit") or (product.unit if product else None),
                    book_quantity=round(book, 2),
                    actual_quantity=round(actual, 2),
                    diff_quantity=diff,
                    unit_price=unit_price,
                    amount=round(diff * unit_price, 2),
                    note=line_data.get("note"),
                )
            )
        db.add_all(rows)
        stock_touched = True

    profit, loss, profit_lines, loss_lines, amount = _stocktaking_totals(rows)
    item.total_profit = profit
    item.total_loss = loss
    item.profit_lines = profit_lines
    item.loss_lines = loss_lines
    item.total_amount = amount

    if stock_touched:
        # 先冲销这张单原有的全部盈亏流水，再按最新明细重放（盘点也有单边账风险）
        _revert_stock(db, "inv_check", item.id)
        _stocktaking_apply_stock(db, item, rows)

    db.commit()
    db.refresh(item)
    return _stocktaking_payload(item, rows)



@router.patch("/stocktakings/{check_id}/status", response_model=StocktakingRead)
def update_stocktaking_status(
    check_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Stocktaking, check_id)
    if item is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in STOCKTAKING_STATUS:
        raise HTTPException(status_code=400, detail="盘点单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _stocktaking_payload(item, _stocktaking_items(db, item.id))



@router.delete("/stocktakings/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stocktaking(check_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(Stocktaking, check_id)
    if item is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    # 库存联动回滚：盘盈与盘亏两类流水一起冲销，账实同时回到盘点前
    _revert_stock(db, "inv_check", check_id)
    db.query(StocktakingItem).filter(
        StocktakingItem.stocktaking_id == check_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _adjust_payload(item: InventoryAdjustment, rows: list[InventoryAdjustmentItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "adjust_no": item.adjust_no,
        "adjust_type": item.adjust_type,
        "warehouse_id": item.warehouse_id,
        "adjust_date": item.adjust_date,
        "handler": item.handler,
        "reason": item.reason,
        "note": item.note,
        "status": item.status,
        "total_quantity": item.total_quantity,
        "total_amount": item.total_amount,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "inventory_adjustment_id": row.inventory_adjustment_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "note": row.note,
            }
            for row in rows
        ],
    }



def _adjust_apply_stock(db: Session, item: InventoryAdjustment, rows: list[InventoryAdjustmentItem]) -> None:
    """按单据头的方向把明细写进库存流水（报损减、报溢加）。"""
    spec = ADJUST_TYPES[item.adjust_type]
    for row in rows:
        qty = int(round(float(row.quantity or 0.0)))
        if qty == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=item.warehouse_id,
            quantity=abs(qty),
            transaction_type=spec["direction"],
            unit_price=row.unit_price,
            related_type=spec["doc_type"],
            related_order_id=item.id,
            doc_no=item.adjust_no,
            note=f"{spec['label']} {item.adjust_no}",
        )



def _normalize_adjust_type(value: str | None) -> str:
    kind = (value or "").strip()
    if kind not in ADJUST_TYPES:
        raise HTTPException(status_code=400, detail="报损报溢类型非法（应为 scrap 或 overflow）")
    return kind



@router.get("/inventory-adjustments/meta")
def inventory_adjustment_meta() -> dict[str, object]:
    """报损报溢页字典：类型 + 状态。"""
    return {
        "types": [
            {"code": code, "label": spec["label"], "direction": spec["direction"]}
            for code, spec in ADJUST_TYPES.items()
        ],
        "statuses": [{"code": code, "label": label} for code, label in ADJUSTMENT_STATUS.items()],
    }



@router.get("/inventory-adjustments")
def list_inventory_adjustments(
    db: Session = Depends(get_db),
    adjust_type: str | None = Query(None),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(InventoryAdjustment).order_by(InventoryAdjustment.id.desc())
    if adjust_type:
        query = query.filter(InventoryAdjustment.adjust_type == adjust_type)
    if status_value:
        query = query.filter(InventoryAdjustment.status == status_value)
    if warehouse_id:
        query = query.filter(InventoryAdjustment.warehouse_id == warehouse_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                InventoryAdjustment.adjust_no.ilike(like),
                InventoryAdjustment.handler.ilike(like),
                InventoryAdjustment.reason.ilike(like),
                InventoryAdjustment.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_adjust_payload(item, _adjust_items(db, item.id)) for item in items]



@router.get("/inventory-adjustments/{adjust_id}", response_model=InventoryAdjustmentRead)
def get_inventory_adjustment(adjust_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(InventoryAdjustment, adjust_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报损报溢单不存在")
    return _adjust_payload(item, _adjust_items(db, item.id))



@router.post(
    "/inventory-adjustments",
    response_model=InventoryAdjustmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory_adjustment(
    payload: InventoryAdjustmentCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    adjust_type = _normalize_adjust_type(payload.adjust_type)
    spec = ADJUST_TYPES[adjust_type]

    warehouse = db.get(Warehouse, int(payload.warehouse_id))
    if warehouse is None:
        raise HTTPException(status_code=404, detail="发生仓库不存在")

    if payload.status and payload.status not in ADJUSTMENT_STATUS:
        raise HTTPException(status_code=400, detail="报损报溢单状态非法")

    # 单号前缀按类型区分：报损 BS、报溢 BY，两类单号各排各的号
    adjust_no = (payload.adjust_no or "").strip() or _next_doc_no(
        db, InventoryAdjustment, spec["prefix"], field="adjust_no"
    )
    if db.query(InventoryAdjustment).filter(InventoryAdjustment.adjust_no == adjust_no).first():
        raise HTTPException(status_code=400, detail="报损报溢单号已存在")

    adjust_date = payload.adjust_date or datetime.now().strftime("%Y-%m-%d")

    item = InventoryAdjustment(
        adjust_no=adjust_no,
        adjust_type=adjust_type,
        warehouse_id=int(payload.warehouse_id),
        adjust_date=adjust_date,
        handler=payload.handler,
        reason=payload.reason,
        note=payload.note,
        status=payload.status or "submitted",
        total_quantity=0.0,
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total_qty = 0.0
    total_amount = 0.0
    rows: list[InventoryAdjustmentItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        quantity = abs(float(line.quantity or 0.0))
        unit_price = _resolve_cost_price(db, line.product_id, line.unit_price)
        row = InventoryAdjustmentItem(
            inventory_adjustment_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total_qty += quantity
        total_amount += row.amount
        rows.append(row)
    db.add_all(rows)

    item.total_quantity = round(total_qty, 2)
    item.total_amount = round(total_amount, 2)
    db.commit()
    db.refresh(item)

    # —— 库存联动：报损减、报溢加（方向由单据头决定）——
    _adjust_apply_stock(db, item, rows)
    db.commit()
    db.refresh(item)
    return _adjust_payload(item, rows)



@router.patch("/inventory-adjustments/{adjust_id}", response_model=InventoryAdjustmentRead)
def update_inventory_adjustment(
    adjust_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(InventoryAdjustment, adjust_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报损报溢单不存在")

    stock_touched = False

    for field in ("adjust_date", "handler", "reason", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="发生仓库不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    # 改类型等于改方向：先冲销旧方向的流水，再按新方向重放
    if payload.get("adjust_type") not in (None, ""):
        new_type = _normalize_adjust_type(str(payload["adjust_type"]))
        if new_type != item.adjust_type:
            item.adjust_type = new_type
            stock_touched = True

    if payload.get("status"):
        if str(payload["status"]) not in ADJUSTMENT_STATUS:
            raise HTTPException(status_code=400, detail="报损报溢单状态非法")
        item.status = str(payload["status"])

    rows = _adjust_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(InventoryAdjustmentItem).filter(
            InventoryAdjustmentItem.inventory_adjustment_id == item.id
        ).delete(synchronize_session=False)
        rows = []
        total_qty = 0.0
        total_amount = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = abs(float(line_data.get("quantity") or 0.0))
            unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
            row = InventoryAdjustmentItem(
                inventory_adjustment_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total_qty += quantity
            total_amount += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_quantity = round(total_qty, 2)
        item.total_amount = round(total_amount, 2)
        stock_touched = True

    if stock_touched:
        # 类型/仓库/明细任一变化都要整体重放，否则会残留按旧内容调整过的库存
        _revert_stock(db, ADJUST_TYPES["scrap"]["doc_type"], item.id)
        _revert_stock(db, ADJUST_TYPES["overflow"]["doc_type"], item.id)
        _adjust_apply_stock(db, item, rows)

    db.commit()
    db.refresh(item)
    return _adjust_payload(item, rows)



@router.patch("/inventory-adjustments/{adjust_id}/status", response_model=InventoryAdjustmentRead)
def update_inventory_adjustment_status(
    adjust_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(InventoryAdjustment, adjust_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报损报溢单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in ADJUSTMENT_STATUS:
        raise HTTPException(status_code=400, detail="报损报溢单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _adjust_payload(item, _adjust_items(db, item.id))



@router.delete("/inventory-adjustments/{adjust_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_adjustment(adjust_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(InventoryAdjustment, adjust_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报损报溢单不存在")
    # 库存联动回滚：按这张单实际产生的方向冲销（两个 doc_type 都过一遍，幂等且安全）
    _revert_stock(db, ADJUST_TYPES["scrap"]["doc_type"], adjust_id)
    _revert_stock(db, ADJUST_TYPES["overflow"]["doc_type"], adjust_id)
    db.query(InventoryAdjustmentItem).filter(
        InventoryAdjustmentItem.inventory_adjustment_id == adjust_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# ============================================================================
# 组合拆卸（对齐浩技云「库存管理 → 组合拆卸」）
# ============================================================================
# 组合：子件出库、成品入库；拆卸：成品出库、子件入库。都在同一个仓库内完成。
# 组合配方**直接读 BOM**（`_bom_children_map`），不另建一套配方表 —— BOM 本来就是
# 表达"某成品由哪些子件按什么用量组成"的地方，再存一份必然两边漂移。


def _assembly_payload(
    db: Session, order: AssemblyOrder, items: list[AssemblyOrderItem]
) -> dict[str, object]:
    warehouse = db.get(Warehouse, order.warehouse_id) if order.warehouse_id else None
    return {
        "id": order.id,
        "order_no": order.order_no,
        "doc_type": order.doc_type or "combo",
        "doc_type_label": ASSEMBLY_TYPES.get(order.doc_type or "combo", order.doc_type or ""),
        "warehouse_id": order.warehouse_id,
        "warehouse_name": getattr(warehouse, "name", None),
        "product_id": order.product_id,
        "product_name": order.product_name,
        "standards": order.standards,
        "unit": order.unit,
        "quantity": int(order.quantity or 0),
        "total_quantity": float(order.total_quantity or 0.0),
        "order_date": order.order_date,
        "handler": order.handler,
        "note": order.note,
        "status": order.status or "submitted",
        "created_at": order.created_at,
        "items": [
            {
                "id": row.id,
                "assembly_order_id": row.assembly_order_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": float(row.quantity or 0.0),
                "unit_price": float(row.unit_price or 0.0),
                "note": row.note,
            }
            for row in items
        ],
    }



def _assembly_bom_lines(
    db: Session, product_id: int, quantity: int, warehouse_id: int | None = None
) -> list[dict[str, object]]:
    """按 BOM 展开成子件清单（一级），带上现存量与单价。

    `quantity` 传成品数量，返回的每行 `quantity` 是**总用量**（单位用量 × 成品数量）。
    """
    products = {p.id: p for p in db.query(Product).all()}
    on_hand = _on_hand_by_product(db, warehouse_id)
    lines: list[dict[str, object]] = []
    for child_id, per_unit in _bom_children_map(db).get(int(product_id), []):
        product = products.get(child_id)
        total = per_unit * max(1, int(quantity or 1))
        lines.append(
            {
                "product_id": child_id,
                "product_name": getattr(product, "name", None) or f"商品-{child_id}",
                "standards": getattr(product, "standards", None),
                "unit": getattr(product, "unit", None),
                "per_unit": per_unit,
                "quantity": total,
                "unit_price": float(getattr(product, "purchase_price", 0.0) or 0.0),
                "on_hand": on_hand.get(child_id, 0),
            }
        )
    return lines



def _assembly_warnings(
    db: Session,
    doc_type: str,
    product_id: int,
    quantity: int,
    items: list[dict[str, object]],
    warehouse_id: int | None,
) -> list[str]:
    """库存够不够，只提示不阻断 —— 与"允许负库存"的既定口径一致。

    组合要把子件扣掉、拆卸要把成品扣掉；不够就在返回里说清楚缺多少，
    由页面显示出来，而不是把单拦下来（现实中常出现"先开单后补货"）。
    """
    if warehouse_id is None:
        return []
    on_hand = _on_hand_by_product(db, warehouse_id)
    warehouse = db.get(Warehouse, warehouse_id)
    where = getattr(warehouse, "name", None) or f"仓库-{warehouse_id}"
    warnings: list[str] = []

    if doc_type == "split":
        have = on_hand.get(int(product_id), 0)
        if have < int(quantity):
            warnings.append(f"成品在「{where}」只有 {have}，本单要拆 {quantity}，将产生负库存")
    else:
        for row in items:
            pid = int(row["product_id"])
            have = on_hand.get(pid, 0)
            need = int(row["quantity"])
            if have < need:
                name = db.get(Product, pid)
                warnings.append(
                    f"子件「{getattr(name, 'name', pid)}」在「{where}」只有 {have}，本单要用 {need}，将产生负库存"
                )
    return warnings



@router.get("/assembly-orders/meta")
def assembly_meta(db: Session = Depends(get_db)) -> dict[str, object]:
    """单据类型 / 状态 / 默认仓库（供页面下拉）。"""
    default_warehouse = _default_warehouse(db)
    return {
        "doc_types": [{"value": key, "label": label} for key, label in ASSEMBLY_TYPES.items()],
        "statuses": [{"value": key, "label": label} for key, label in ASSEMBLY_STATUS.items()],
        "default_warehouse_id": getattr(default_warehouse, "id", None),
        "prefixes": ASSEMBLY_PREFIX,
    }



@router.get("/assembly-orders/bom-preview")
def assembly_bom_preview(
    product_id: int = Query(...),
    quantity: int = Query(1),
    doc_type: str = Query("combo"),
    warehouse_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """选完成品后拉出配方：子件清单（可再改数量）+ 现存量 + 缺口提示。

    必须声明在 `/assembly-orders/{order_id}` 之前，否则 "bom-preview" 会撞上路径参数。
    """
    if doc_type not in ASSEMBLY_TYPES:
        raise HTTPException(status_code=400, detail=f"单据类型只能是：{'、'.join(ASSEMBLY_TYPES)}")
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="成品不存在")
    if int(quantity or 0) <= 0:
        raise HTTPException(status_code=400, detail="成品数量必须大于 0")

    warehouse_id = _resolve_warehouse_id(db, warehouse_id)
    items = _assembly_bom_lines(db, product_id, int(quantity), warehouse_id)
    on_hand = _on_hand_by_product(db, warehouse_id)
    return {
        "doc_type": doc_type,
        "product": {
            "id": product.id,
            "name": product.name,
            "sku": product.sku,
            "standards": product.standards,
            "unit": product.unit,
            "on_hand": on_hand.get(product_id, 0),
        },
        "quantity": int(quantity),
        "warehouse_id": warehouse_id,
        # 没有配方时页面要明确提示，而不是给一份空清单让人以为"不用料"
        "has_bom": bool(items),
        "items": items,
        "warnings": _assembly_warnings(db, doc_type, product_id, int(quantity), items, warehouse_id),
    }



@router.get("/assembly-orders", response_model=list[AssemblyOrderRead])
def list_assembly_orders(
    doc_type: str | None = None,
    keyword: str | None = None,
    skip: int = 0,
    limit: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """组合拆卸单列表。keyword 同时匹配单号和成品名。"""
    query = db.query(AssemblyOrder)
    if doc_type:
        query = query.filter(AssemblyOrder.doc_type == doc_type)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(AssemblyOrder.order_no.ilike(like), AssemblyOrder.product_name.ilike(like)))
    orders = _paginate(query.order_by(AssemblyOrder.id.desc()), skip, limit).all()
    result = []
    for order in orders:
        items = (
            db.query(AssemblyOrderItem)
            .filter(AssemblyOrderItem.assembly_order_id == order.id)
            .order_by(AssemblyOrderItem.id)
            .all()
        )
        result.append(_assembly_payload(db, order, items))
    return result



@router.get("/assembly-orders/{order_id}", response_model=AssemblyOrderRead)
def get_assembly_order(order_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    order = db.get(AssemblyOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="组合拆卸单不存在")
    items = (
        db.query(AssemblyOrderItem)
        .filter(AssemblyOrderItem.assembly_order_id == order_id)
        .order_by(AssemblyOrderItem.id)
        .all()
    )
    return _assembly_payload(db, order, items)



@router.post("/assembly-orders", response_model=AssemblyOrderRead, status_code=status.HTTP_201_CREATED)
def create_assembly_order(
    payload: AssemblyOrderCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    """开一张组合 / 拆卸单，并立即执行库存变动。

    - 组合：成品入库 + 子件出库
    - 拆卸：成品出库 + 子件入库
    """
    doc_type = str(payload.doc_type or "combo")
    if doc_type not in ASSEMBLY_TYPES:
        raise HTTPException(status_code=400, detail=f"单据类型只能是：{'、'.join(ASSEMBLY_TYPES)}")

    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=400, detail="成品不存在，请先在商品档案里建好")
    quantity = int(payload.quantity or 0)
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="成品数量必须大于 0")

    raw_items = list(payload.items or [])
    if not raw_items:
        raise HTTPException(
            status_code=400,
            detail="子件清单不能为空。若该成品还没有配方，请先在「BOM 清单」里配置，或手工添加子件行。",
        )

    # 子件校验：必须存在、数量为正、不能是成品自己、不能重复
    resolved: list[dict[str, object]] = []
    seen: set[int] = set()
    for index, raw in enumerate(raw_items, start=1):
        child = db.get(Product, raw.product_id)
        if child is None:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的子件不存在")
        if int(raw.product_id) == int(payload.product_id):
            raise HTTPException(status_code=400, detail="子件不能是成品自己")
        if int(raw.product_id) in seen:
            raise HTTPException(
                status_code=400, detail=f"子件「{child.name}」在清单里出现了两次，请合并成一行"
            )
        seen.add(int(raw.product_id))
        if float(raw.quantity or 0) <= 0:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的用量必须大于 0")
        resolved.append(
            {
                "product_id": int(raw.product_id),
                "product_name": child.name,
                "standards": child.standards,
                "unit": child.unit,
                "quantity": float(raw.quantity),
                "unit_price": float(
                    raw.unit_price if raw.unit_price is not None else (child.purchase_price or 0.0)
                ),
                "note": raw.note,
            }
        )

    warehouse_id = _resolve_warehouse_id(db, payload.warehouse_id)
    if warehouse_id is None:
        raise HTTPException(status_code=400, detail="系统里还没有仓库，请先在仓库档案里建好")

    order = AssemblyOrder(
        order_no=_next_doc_no(db, AssemblyOrder, ASSEMBLY_PREFIX[doc_type], field="order_no"),
        doc_type=doc_type,
        warehouse_id=warehouse_id,
        product_id=int(payload.product_id),
        product_name=product.name,
        standards=product.standards,
        unit=product.unit,
        quantity=quantity,
        total_quantity=round(sum(float(row["quantity"]) for row in resolved), 2),
        order_date=payload.order_date or datetime.now().strftime("%Y-%m-%d"),
        handler=payload.handler,
        note=payload.note,
        status="submitted",
    )
    db.add(order)
    db.flush()  # 先拿到 id，库存流水要用它做 related_order_id

    # 库存联动：成品与子件方向相反，两条都用同一个 related_type + order_id，
    # 所以删单时 _revert_stock 一次把整单的流水都冲掉。
    product_sign = "inbound" if doc_type == "combo" else "outbound"
    item_sign = "outbound" if doc_type == "combo" else "inbound"
    direction = "组合" if doc_type == "combo" else "拆卸"

    _apply_stock(
        db,
        product_id=order.product_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
        transaction_type=product_sign,
        unit_price=float(product.purchase_price or 0.0),
        related_type="assembly",
        related_order_id=order.id,
        doc_no=order.order_no,
        note=f"{direction}成品（{ASSEMBLY_TYPES[doc_type]}单）",
    )
    for row in resolved:
        db.add(
            AssemblyOrderItem(
                assembly_order_id=order.id,
                product_id=row["product_id"],
                product_name=row["product_name"],
                standards=row["standards"],
                unit=row["unit"],
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                note=row["note"],
            )
        )
        _apply_stock(
            db,
            product_id=int(row["product_id"]),
            warehouse_id=warehouse_id,
            quantity=int(row["quantity"]),
            transaction_type=item_sign,
            unit_price=float(row["unit_price"] or 0.0),
            related_type="assembly",
            related_order_id=order.id,
            doc_no=order.order_no,
            note=f"{direction}子件（{ASSEMBLY_TYPES[doc_type]}单）",
        )

    db.commit()
    db.refresh(order)
    items = (
        db.query(AssemblyOrderItem)
        .filter(AssemblyOrderItem.assembly_order_id == order.id)
        .order_by(AssemblyOrderItem.id)
        .all()
    )
    result = _assembly_payload(db, order, items)
    # 库存不够照样能开单（允许负库存），但必须回报出来，别让用户开完才发现
    result["warnings"] = _assembly_warnings(db, doc_type, order.product_id, quantity, resolved, warehouse_id)
    return result



@router.delete("/assembly-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assembly_order(order_id: int, db: Session = Depends(get_db)) -> Response:
    """删单并冲销库存：成品与子件的变动一起复原。"""
    order = db.get(AssemblyOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="组合拆卸单不存在")
    _revert_stock(db, "assembly", order_id)
    db.query(AssemblyOrderItem).filter(AssemblyOrderItem.assembly_order_id == order_id).delete(
        synchronize_session=False
    )
    db.delete(order)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
