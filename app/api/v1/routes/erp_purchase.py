"""采购管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

采购入库 / 采购订单 / 采购退货 / 供应商绩效与采购建议。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.finance import FinancialTransaction
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.purchase_return import PURCHASE_RETURN_STATUS, PurchaseReturn, PurchaseReturnItem
from app.models.supplier import Supplier
from app.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderRead,
    PurchaseReturnCreate,
    PurchaseReturnRead,
)
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _apply_stock,
    _next_doc_no,
    _paginate,
    _prev_debt_total,
    _purchase_return_items,
    _resolve_item_snapshot,
    _resolve_warehouse_id,
    _revert_finance,
    _revert_stock,
    _write_finance,
    amount_to_chinese,
)

router = APIRouter(prefix="", tags=["erp"])




def _build_purchase_payload(item: PurchaseOrder, rows: list[PurchaseOrderItem]) -> PurchaseOrderRead:
    return PurchaseOrderRead(
        id=item.id,
        order_no=item.order_no,
        supplier_id=item.supplier_id,
        status=item.status,
        total_amount=item.total_amount,
        doc_type=item.doc_type or "inbound",
        source_order_id=item.source_order_id,
        created_at=item.created_at,
        warehouse_id=item.warehouse_id,
        # 手写映射**最容易漏字段**：加了 project_id 却没加在这里，
        # 结果是数据存进去了、接口却返回 None（前端显示不出单据属于哪个项目）
        project_id=item.project_id,
        businesser=item.businesser,
        order_date=item.order_date,
        delivery_date=item.delivery_date,
        payment_method=item.payment_method,
        contact=item.contact,
        contact_phone=item.contact_phone,
        address=item.address,
        note=item.note,
        discount_amount=item.discount_amount,
        paid_amount=item.paid_amount,
        is_invoiced=item.is_invoiced,
        payable_amount=item.payable_amount,
        current_debt=item.current_debt,
        prev_debt=item.prev_debt,
        total_debt=item.total_debt,
        items=[
            {
                "id": row.id,
                "purchase_order_id": row.purchase_order_id,
                "product_id": row.product_id,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "note": row.note,
            }
            for row in rows
        ],
    )



@router.get("/purchase-orders")
def list_purchase_orders(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int | None = None,
    doc_type: str | None = None,
    supplier_id: int | None = None,
) -> list[PurchaseOrderRead]:
    query = db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    # doc_type 过滤：order=采购订单页；inbound=采购入库页；不传=全量（兼容旧调用方）
    if doc_type:
        query = query.filter(PurchaseOrder.doc_type == doc_type)
    if supplier_id:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)
    items = _paginate(query, skip, limit).all()
    result = []
    for item in items:
        order_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == item.id).all()
        result.append(_build_purchase_payload(item, order_items))
    return result



@router.post("/purchase-orders", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
def create_purchase_order(payload: PurchaseOrderCreate, db: Session = Depends(get_db)) -> PurchaseOrderRead:
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # 单据性质：order=采购订单（只订货）；inbound=采购入库单（默认，真实入库+财务+库存）
    doc_type = (payload.doc_type or "inbound").strip()
    if doc_type not in ("order", "inbound"):
        raise HTTPException(status_code=400, detail="doc_type 仅支持 order / inbound")

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, PurchaseOrder, "CGD" if doc_type == "order" else "CG")
    if db.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="采购单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    # 采购订单不产生欠款（还没入库结算），欠款链字段保持 0
    prev_debt = (
        round(_prev_debt_total(db, PurchaseOrder, PurchaseOrder.supplier_id, payload.supplier_id), 2)
        if doc_type == "inbound"
        else 0.0
    )

    item = PurchaseOrder(
        order_no=order_no,
        supplier_id=payload.supplier_id,
        status="draft",
        total_amount=0.0,
        doc_type=doc_type,
        warehouse_id=payload.warehouse_id,
        project_id=payload.project_id,
        businesser=payload.businesser or supplier.contact,
        order_date=order_date,
        delivery_date=payload.delivery_date,
        payment_method=payload.payment_method,
        contact=payload.contact or supplier.main_contact or supplier.contact,
        contact_phone=payload.contact_phone or supplier.mobile or supplier.phone,
        address=payload.address or supplier.address,
        note=payload.note,
        is_invoiced=payload.is_invoiced,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[PurchaseOrderItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = PurchaseOrderItem(
            purchase_order_id=item.id,
            product_id=line.product_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            amount=line.quantity * line.unit_price,
            product_name=name,
            standards=standards,
            unit=unit,
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    # 结算链：应付 → 优惠 → 实付
    # 实付金额不填 = 0，即本单全额挂账；之后由「付款登记」逐笔冲减。
    # 会计上宁可高估应付、不可高估已付，这样对账单才有真实的往来发生额。
    gross = round(total, 2)
    discount = round(float(payload.discount_amount or 0.0), 2)
    net = round(gross - discount, 2)
    paid = round(float(payload.paid_amount or 0.0), 2)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = round(net - paid, 2)

    item.total_amount = gross
    item.payable_amount = gross
    item.discount_amount = discount
    item.paid_amount = paid
    item.current_debt = current_debt
    item.prev_debt = prev_debt
    item.total_debt = round(prev_debt + current_debt, 2)
    item.status = "submitted"

    # —— 采购订单（doc_type=order）：到此为止 ——
    # 订单只是"意向确认"，不动库存、不写财务、不产生欠款；
    # 真正的入库/结算由「转入库单」或手工开入库单完成。
    if doc_type == "order":
        item.paid_amount = 0.0
        item.current_debt = 0.0
        item.prev_debt = 0.0
        item.total_debt = 0.0
        db.commit()
        db.refresh(item)
        return _build_purchase_payload(item, rows)

    # 财务联动：单据审核即产生应付，人工无需再录
    if gross > 0:
        _write_finance(
            db,
            transaction_type="payable",
            direction="out",
            amount=gross,
            related_type="purchase_in",
            related_order_id=item.id,
            doc_no=item.order_no,
            supplier_id=payload.supplier_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"采购入库单 {item.order_no} 产生应付",
        )
    if paid > 0:
        _write_finance(
            db,
            transaction_type="payment",
            direction="out",
            amount=paid,
            related_type="purchase_in",
            related_order_id=item.id,
            doc_no=item.order_no,
            supplier_id=payload.supplier_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"采购入库单 {item.order_no} 付款",
        )

    # 库存联动：采购入库即增加现存量，每条明细一条流水。
    # 单据没填仓库时回退到默认仓库，并把结果回填到单据上，保证单据与流水指向同一个仓。
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=row.quantity,
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="purchase_in",
            related_order_id=item.id,
            doc_no=item.order_no,
            note=f"采购入库 {item.order_no}",
        )

    db.commit()
    db.refresh(item)
    return _build_purchase_payload(item, rows)



@router.patch("/purchase-orders/{order_id}/status")
def update_purchase_order_status(order_id: int, payload: dict[str, object], db: Session = Depends(get_db)) -> PurchaseOrderRead:
    item = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    status_value = str(payload.get("status") or "submitted").strip()
    if not status_value:
        raise HTTPException(status_code=400, detail="status is required")

    item.status = status_value
    db.commit()
    db.refresh(item)
    order_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == item.id).all()
    return _build_purchase_payload(item, order_items)



@router.post("/purchase-orders/{order_id}/to-inbound", response_model=PurchaseOrderRead)
def purchase_order_to_inbound(order_id: int, db: Session = Depends(get_db)) -> PurchaseOrderRead:
    """采购订单 → 采购入库单（一键转单）。

    生成一张新的入库单（doc_type=inbound，写库存流水与应付财务流水），
    复制订单的头信息与明细；订单本身置 completed 并保留可追溯。
    """
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.doc_type != "order":
        raise HTTPException(status_code=400, detail="只有采购订单才能转入库单")
    if order.status == "completed":
        raise HTTPException(status_code=409, detail="该订单已转入库单，不能重复转单")

    order_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order.id).all()
    payload = PurchaseOrderCreate(
        supplier_id=order.supplier_id,
        items=[
            PurchaseOrderItemCreate(
                product_id=row.product_id,
                quantity=row.quantity,
                unit_price=row.unit_price,
                product_name=row.product_name,
                standards=row.standards,
                unit=row.unit,
                note=row.note,
            )
            for row in order_items
        ],
        warehouse_id=order.warehouse_id,
        # 转单必须把项目一起带过去：订单上挂了项目、转出来的出库/入库单没挂，
        # 项目成本/收入就永远归集不到（闭环核查抓到的真实断点）
        project_id=order.project_id,
        businesser=order.businesser,
        order_date=order.order_date,
        delivery_date=order.delivery_date,
        payment_method=order.payment_method,
        contact=order.contact,
        contact_phone=order.contact_phone,
        address=order.address,
        note=order.note,
        discount_amount=order.discount_amount,
        paid_amount=0.0,  # 结算在入库单上另行登记，转单时不带收款
        is_invoiced=order.is_invoiced,
    )
    inbound = create_purchase_order(payload, db)

    # 回填：入库单回指来源订单，订单置 completed
    inbound_row = db.query(PurchaseOrder).filter(PurchaseOrder.id == inbound.id).first()
    inbound_row.source_order_id = order.id
    order.status = "completed"
    db.commit()
    db.refresh(inbound_row)
    order_items2 = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == inbound_row.id).all()
    return _build_purchase_payload(inbound_row, order_items2)



@router.delete("/purchase-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(order_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    # 已转入库单的订单不允许直接删（入库单还引用着它），先删入库单再回来删订单；
    # 用 source_order_id 反查比看 status 更准——入库单删掉后订单自然就能删了
    if (
        item.doc_type == "order"
        and db.query(PurchaseOrder).filter(PurchaseOrder.source_order_id == order_id).first() is not None
    ):
        raise HTTPException(status_code=409, detail="该订单已转入库单，请先删除对应的入库单")
    # 库存联动回滚：这张单产生的入库流水一并冲销（订单没有流水，此处自然为空操作）
    _revert_stock(db, "purchase_in", order_id)
    # 财务联动回滚：入库产生的应付 / 付款流水一并冲销，避免留下指向已删单据的孤儿
    _revert_finance(db, "purchase_in", order_id)
    db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/purchase/recommendations")
def purchase_recommendations(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    from app.api.v1.routes.erp_inventory import list_inventory_alerts
    product_names = {item.id: item.name for item in db.query(Product).all()}
    supplier_names = {item.id: item.name for item in db.query(Supplier).all()}
    inventory_alerts = list_inventory_alerts(db)

    recommendations: list[dict[str, object]] = []
    for alert in inventory_alerts:
        # 积压的商品不需要补货，跳过
        if alert["status"] == "overstock":
            continue
        product_id = int(alert["product_id"])
        available_quantity = int(alert["available_quantity"])
        lower = alert.get("stock_lower")
        base = int(lower) if lower is not None else 20
        # 补到下限之上，并再留一份下限作为安全库存
        qty_to_buy = max(1, (base - available_quantity) + base)
        priority = "high" if available_quantity <= 0 else "medium"
        recommendations.append(
            {
                "product_id": product_id,
                "product_name": product_names.get(product_id, f"产品-{product_id}"),
                "supplier_name": supplier_names.get(1, "主供应商") if supplier_names else "主供应商",
                "recommended_quantity": qty_to_buy,
                "priority": priority,
                "reason": "已缺货，建议立即补货以避免断供" if priority == "high" else f"低于库存下限 {base}，建议安排补货",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "product_id": 0,
                "product_name": "暂无补货需求",
                "supplier_name": "—",
                "recommended_quantity": 0,
                "priority": "low",
                "reason": "当前库存状态正常，无需立即补货。",
            }
        )

    return recommendations



@router.get("/supplier/performance")
def supplier_performance(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    supplier_names = {item.id: item.name for item in db.query(Supplier).all()}
    result: list[dict[str, object]] = []

    for supplier in db.query(Supplier).all():
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == supplier.id).all()
        total_amount = sum(float(order.total_amount or 0.0) for order in orders)
        on_time_count = sum(1 for order in orders if order.status in {"submitted", "received", "completed"})
        on_time_rate = round((on_time_count / len(orders) * 100), 1) if orders else 100.0

        result.append(
            {
                "supplier_id": supplier.id,
                "supplier_name": supplier_names.get(supplier.id, supplier.name),
                "order_count": len(orders),
                "total_amount": float(total_amount),
                "on_time_rate": float(on_time_rate),
                "risk_level": "healthy" if on_time_rate >= 80 else "watch" if on_time_rate >= 60 else "risk",
            }
        )

    return sorted(result, key=lambda item: float(item["total_amount"]), reverse=True)



def _purchase_return_payload(item: PurchaseReturn, rows: list[PurchaseReturnItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "return_no": item.return_no,
        "supplier_id": item.supplier_id,
        "supplier_name": item.supplier_name,
        "contact": item.contact,
        "contact_phone": item.contact_phone,
        "address": item.address,
        "warehouse_id": item.warehouse_id,
        "businesser": item.businesser,
        "return_date": item.return_date,
        "return_reason": item.return_reason,
        "payment_method": item.payment_method,
        "note": item.note,
        "source_order_id": item.source_order_id,
        "source_order_no": item.source_order_no,
        "status": item.status,
        "total_amount": item.total_amount,
        "amount_chinese": item.amount_chinese,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "purchase_return_id": row.purchase_return_id,
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



@router.get("/purchase-returns/meta")
def purchase_return_meta() -> dict[str, object]:
    """采购退货页字典：状态。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in PURCHASE_RETURN_STATUS.items()],
    }



@router.get("/purchase-returns")
def list_purchase_returns(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(PurchaseReturn).order_by(PurchaseReturn.id.desc())
    if status_value:
        query = query.filter(PurchaseReturn.status == status_value)
    if supplier_id:
        query = query.filter(PurchaseReturn.supplier_id == supplier_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                PurchaseReturn.return_no.ilike(like),
                PurchaseReturn.supplier_name.ilike(like),
                PurchaseReturn.businesser.ilike(like),
                PurchaseReturn.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_purchase_return_payload(item, _purchase_return_items(db, item.id)) for item in items]



@router.get("/purchase-returns/{return_id}", response_model=PurchaseReturnRead)
def get_purchase_return(return_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(PurchaseReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购退货单不存在")
    return _purchase_return_payload(item, _purchase_return_items(db, item.id))



@router.post("/purchase-returns", response_model=PurchaseReturnRead, status_code=status.HTTP_201_CREATED)
def create_purchase_return(payload: PurchaseReturnCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="供应商档案不存在")

    if payload.status and payload.status not in PURCHASE_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="采购退货状态非法")

    return_no = (payload.return_no or "").strip() or _next_doc_no(db, PurchaseReturn, "CGTH", field="return_no")
    if db.query(PurchaseReturn).filter(PurchaseReturn.return_no == return_no).first():
        raise HTTPException(status_code=400, detail="采购退货单号已存在")

    return_date = payload.return_date or datetime.now().strftime("%Y-%m-%d")

    item = PurchaseReturn(
        return_no=return_no,
        supplier_id=payload.supplier_id,
        supplier_name=payload.supplier_name or supplier.name,
        contact=payload.contact or supplier.main_contact or supplier.contact,
        contact_phone=payload.contact_phone or supplier.mobile or supplier.phone,
        address=payload.address or supplier.address,
        warehouse_id=payload.warehouse_id,
        businesser=payload.businesser or supplier.contact,
        return_date=return_date,
        return_reason=payload.return_reason,
        payment_method=payload.payment_method,
        note=payload.note,
        source_order_id=payload.source_order_id,
        source_order_no=payload.source_order_no,
        status=payload.status or "submitted",
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[PurchaseReturnItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        row = PurchaseReturnItem(
            purchase_return_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    item.total_amount = round(total, 2)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)

    # —— 库存联动：退货减少现存量（outbound）——
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=int(row.quantity or 0),
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="purchase_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            note=f"采购退货 {item.return_no}",
        )

    # —— 财务联动：退货冲减应付。金额记负数（方向 out），对账时自然抵减 ——
    if total > 0:
        _write_finance(
            db,
            transaction_type="payable",
            direction="out",
            amount=-total,
            related_type="purchase_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            supplier_id=payload.supplier_id,
            warehouse_id=item.warehouse_id,
            occurred_at=return_date,
            note=f"采购退货 {item.return_no} 冲减应付",
        )

    db.commit()
    db.refresh(item)
    return _purchase_return_payload(item, rows)



@router.patch("/purchase-returns/{return_id}", response_model=PurchaseReturnRead)
def update_purchase_return(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(PurchaseReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购退货单不存在")

    text_fields = [
        "supplier_name", "contact", "contact_phone", "address", "businesser",
        "return_date", "return_reason", "payment_method", "note",
        "source_order_no",
    ]
    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    for int_field in ("warehouse_id", "source_order_id", "supplier_id"):
        if int_field in payload:
            raw = payload.get(int_field)
            setattr(item, int_field, int(raw) if raw not in ("", None) else None)
    if payload.get("status"):
        if str(payload["status"]) not in PURCHASE_RETURN_STATUS:
            raise HTTPException(status_code=400, detail="采购退货状态非法")
        item.status = str(payload["status"])

    rows = _purchase_return_items(db, item.id)
    # 传了明细就整单替换并重算金额/大写
    if isinstance(payload.get("items"), list):
        db.query(PurchaseReturnItem).filter(PurchaseReturnItem.purchase_return_id == item.id).delete()
        rows = []
        total = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = PurchaseReturnItem(
                purchase_return_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)

    db.commit()
    db.refresh(item)
    return _purchase_return_payload(item, rows)



@router.patch("/purchase-returns/{return_id}/status", response_model=PurchaseReturnRead)
def update_purchase_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(PurchaseReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购退货单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in PURCHASE_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="采购退货状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _purchase_return_payload(item, _purchase_return_items(db, item.id))



@router.delete("/purchase-returns/{return_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_return(return_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(PurchaseReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购退货单不存在")
    # 库存联动回滚：冲销这张退货单产生的 outbound 流水（货退回的动作撤销，库存加回来）
    _revert_stock(db, "purchase_return", return_id)
    # 财务联动回滚：冲销这张单产生的应付冲减流水
    db.query(FinancialTransaction).filter(
        FinancialTransaction.related_type == "purchase_return",
        FinancialTransaction.related_order_id == return_id,
    ).delete(synchronize_session=False)
    db.query(PurchaseReturnItem).filter(PurchaseReturnItem.purchase_return_id == return_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
