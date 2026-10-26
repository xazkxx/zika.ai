"""采购管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

采购入库 / 采购订单 / 采购退货 / 供应商绩效与采购建议。
"""

from __future__ import annotations

from app.core.doc_status import assert_transition, is_approved, status_label
from app.db.session import get_db
from app.models.finance import FinancialTransaction
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.purchase_return import PURCHASE_RETURN_STATUS, PurchaseReturn, PurchaseReturnItem
from app.models.supplier import Supplier
from app.core.money import ZERO, line_amount, money
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
    _clean_order_lines,
    _next_doc_no,
    _paginate,
    _prev_debt_total,
    _purchase_return_items,
    _resolve_item_snapshot,
    _resolve_unit_factor,
    _resolve_warehouse_id,
    _assert_no_payment_flows,
    _assert_source_order_no_payment,
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
                # ⚠️ 手写 dict **最容易漏字段**，而漏了 unit_factor 不会报错 ——
                # Pydantic 会用默认值 1 填上，于是前端**永远看到 1**，比不显示更糟。
                "unit_factor": row.unit_factor,
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

    # 空行 / 半填行先过一遍：整行空白的部分静默丢弃，选了商品却没数量的直接 400。
    # 必须放在**取单号之前** —— 否则校验失败会白白消耗一个流水号。
    lines_in = _clean_order_lines(payload.items, "采购单")

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, PurchaseOrder, "CGD" if doc_type == "order" else "CG")
    if db.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="采购单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # ⚠️ 换算率解析必须在**落表头之前**做完 —— 和采购退货那边同一个道理：
    # 表头在下面明细循环之前就 `db.commit()` 了，若 400 发生在循环里，
    # 库里会留下一张「只有表头、没有明细」的空入库单。
    # 快照与换算率各只算一遍，循环里按下标取，避免重复查库。
    snapshots = [_resolve_item_snapshot(db, line) for line in lines_in]
    unit_factors = [
        _resolve_unit_factor(db, line.product_id, snapshot[2])
        for line, snapshot in zip(lines_in, snapshots)
    ]

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    # 采购订单不产生欠款（还没入库结算），欠款链字段保持 0
    prev_debt = (
        money(_prev_debt_total(db, PurchaseOrder, PurchaseOrder.supplier_id, payload.supplier_id))
        if doc_type == "inbound"
        else ZERO
    )

    item = PurchaseOrder(
        order_no=order_no,
        supplier_id=payload.supplier_id,
        status="draft",
        total_amount=ZERO,
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

    total = ZERO  # 金额累加必须从 Decimal 起步：0.0 + Decimal 会 TypeError
    rows: list[PurchaseOrderItem] = []
    for index, line in enumerate(lines_in):
        name, standards, unit = snapshots[index]
        row = PurchaseOrderItem(
            purchase_order_id=item.id,
            product_id=line.product_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            # 行金额统一走 line_amount：单价是 4 位"费率"，先用 2 位收口就是少钱
            amount=line_amount(line.unit_price, line.quantity),
            product_name=name,
            standards=standards,
            unit=unit,
            # 服务端解析出来的快照，不是客户端传的
            unit_factor=unit_factors[index],
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    # 结算链：应付 → 优惠 → 实付
    # 实付金额不填 = 0，即本单全额挂账；之后由「付款登记」逐笔冲减。
    # 会计上宁可高估应付、不可高估已付，这样对账单才有真实的往来发生额。
    gross = money(total)
    discount = money(payload.discount_amount)
    net = money(gross - discount)
    paid = money(payload.paid_amount)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = money(net - paid)

    item.total_amount = gross
    item.payable_amount = gross
    item.discount_amount = discount
    item.paid_amount = paid
    item.current_debt = current_debt
    item.prev_debt = prev_debt
    item.total_debt = money(prev_debt + current_debt)
    item.status = "submitted"

    # —— 采购订单（doc_type=order）：到此为止 ——
    # 订单只是"意向确认"，不动库存、不写财务、不产生欠款；
    # 真正的入库/结算由「转入库单」或手工开入库单完成。
    if doc_type == "order":
        item.paid_amount = ZERO
        item.current_debt = ZERO
        item.prev_debt = ZERO
        item.total_debt = ZERO
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
            # 换算在这里发生：流水 quantity = 录入数量 × factor，
            # unit_price 同步 ÷ factor 换成"每基本单位成本"。
            # 因为 (q×f)×(p÷f) = q×p，单据金额/应付/收发存入库金额**一分不变**。
            unit_factor=row.unit_factor,
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
    """改单据状态 —— 与销售侧同一套状态机（`app/core/doc_status.py`）。

    采购/销售/现货单共用同一份流转表，任何一边单独加状态都会让两套账口径分叉。
    """
    item = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    status_value = assert_transition(item.doc_type, item.status, payload.get("status"), item.order_no)
    if status_value != item.status:
        item.status = status_value
        db.commit()
        db.refresh(item)
    order_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == item.id).all()
    return _build_purchase_payload(item, order_items)


@router.patch("/purchase-orders/{order_id}/unsubmit", response_model=PurchaseOrderRead)
def unsubmit_purchase_order(order_id: int, db: Session = Depends(get_db)) -> PurchaseOrderRead:
    """反审核：submitted / approved → draft（2026-10-20 老系统 UX 升级）。

    与销售侧同一道闸口：**只要产生过库存/资金流水就不许退**。
    订单（doc_type=order）没动过账，pending/approved 都能退回草稿；
    入库单（doc_type=inbound）创建即写流水，必然被闸口拦下 → 走红冲/删单。
    """
    item = db.get(PurchaseOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if item.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail="已完结 / 已取消的单据不能反审核。已完结的单据要走「红冲」或删除。",
        )
    from app.models.inventory import InventoryTransaction

    flow_types = ("purchase_in", "payment")
    has_flows = db.query(InventoryTransaction.id).filter(
        InventoryTransaction.related_order_id == order_id,
        InventoryTransaction.related_type.in_(flow_types),
    ).first() or db.query(FinancialTransaction.id).filter(
        FinancialTransaction.related_order_id == order_id,
        FinancialTransaction.related_type.in_(flow_types),
    ).first()
    if has_flows is not None:
        raise HTTPException(
            status_code=409,
            detail="这张单已产生库存/资金流水（入库或付款），不能反审核。金额登错请走「红冲」或删除单据。",
        )
    item.status = "draft"
    db.commit()
    db.refresh(item)
    order_items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == item.id).all()
    return _build_purchase_payload(item, order_items)



@router.post("/purchase-orders/{order_id}/to-inbound", response_model=PurchaseOrderRead)
def purchase_order_to_inbound(order_id: int, db: Session = Depends(get_db)) -> PurchaseOrderRead:
    """采购订单 → 采购入库单（一键转单）。

    生成一张新的入库单（doc_type=inbound，写库存流水与应付财务流水），
    复制订单的头信息与明细；订单本身置 completed 并保留可追溯。

    ⚠️ **必须审核通过才允许转单**（与销售侧同一道闸口，2026-10-18 定）。
    """
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.doc_type != "order":
        raise HTTPException(status_code=400, detail="只有采购订单才能转入库单")
    if order.status == "completed":
        raise HTTPException(status_code=409, detail="该订单已转入库单，不能重复转单")
    if not is_approved(order.doc_type, order.status):
        raise HTTPException(
            status_code=409,
            detail=f"订单 {order.order_no} 当前是「{status_label(order.status)}」，"
            "必须先审核通过（approved）才能转入库单",
        )

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
        paid_amount=ZERO,  # 结算在入库单上另行登记，转单时不带收款
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
    # 已登记过付款/收款的单据禁止删除（2026-10-18）—— 同销售侧，
    # 必须排在 _revert_stock / _revert_finance 之前（先动库存再报错会留下半截状态）
    _assert_no_payment_flows(db, order_id, item.order_no or f"#{order_id}")
    # 删入库单时，来源订单上也可能已登记付款（同销售侧，避免订单变成死锁单）
    if item.source_order_id:
        _assert_source_order_no_payment(db, db.get(PurchaseOrder, item.source_order_id), "采购入库单")
    # 库存联动回滚：这张单产生的入库流水一并冲销（订单没有流水，此处自然为空操作）
    _revert_stock(db, "purchase_in", order_id)
    # 财务联动回滚：只冲销"入库自己产生的"应付（related_type=purchase_in）。
    # 收付款（receipt/payment）不在这里删 —— 上面那道闸口已经拦下了。
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



def _purchase_return_quantity(value: object, index: int) -> float:
    """校验退货明细的数量是整数，返回 float（该列类型本来就是 double precision）。

    `PurchaseReturnItem.quantity` 是 `double precision`（而采购 / 销售明细是 `integer`），
    写库存流水那一侧过去用的是 `int(...)` —— 于是「退 3.5 件」会**静默**变成扣 3，
    少的 0.5 既没有报错也没有日志。接了多单位换算之后更糟：
    `int(3.5) * 10 = 30`，而单据的意思是 35 —— 一次丢 5 件。

    库存的硬规则是「绝不存小数」，所以这里**不截断、也不四舍五入**，
    直接把不合法的数量挡在门外。
    """
    try:
        qty = float(value or 0.0)
    except (TypeError, ValueError):
        # PATCH 那条路的 payload 是**裸 dict**（不像 POST 有 Pydantic 挡在前面），
        # 所以 "abc" 这种脏值会走到这里 —— 不能让它冒成 500
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量不是合法数字",
        ) from None
    # is_integer() 对 inf / nan 都返回 False，所以这一句同时把它们挡掉了
    if not qty.is_integer():
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量必须是整数（库存按整数计量），当前填的是 {qty}",
        )
    # ⚠️ 只判"整数"是不够的：`float(None or 0.0)`、`float("" or 0.0)` 都是 0.0，
    # 而 0.0 是"合法整数" —— 实测（见 verify_patch0 的 [4]）PATCH 传 `quantity: null`
    # 会**静默**把这张退货单改成"退 0 件"：金额变 0，而且因为 `_apply_stock`
    # 对 qty==0 是直接 return None，它还会顺手把原来的库存流水冲销掉。
    # 退货单上一行"退 0 件"本来就没有任何业务含义，所以正整数才是唯一合法输入。
    if qty <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量必须大于 0",
        )
    return qty


def _purchase_return_unit_price(
    raw: object,
    index: int,
    *,
    product: Product | None,
    factor: int,
    fallback: float | None,
) -> float:
    """解析退货明细行的单价 —— **绝不允许把一个 0 写进单据**。

    ⚠️ 这是一个真实的财务口子：退货单的 `unit_price` 一旦被静默写成 0，
    金额、应付冲减、财务流水**全部变成 0**，而**库存照样扣** ——
    单据、库存、财务三个数字从此永久对不上，而且一声不响。
    （补丁验证台 `verify_patch0` 的 [8] 实测过：只传 quantity、不传 unit_price，
    HTTP 200，单据金额 0.0，库存流水 unit_price 0.0。）

    三处调用点传进来的 `raw` 来源不同，但"非正数"的形态是一样的：
      · POST：Pydantic 的 `unit_price: float = 0.0` —— **字段缺失就是 0.0**
      · POST 前端：`Number(row.unit_price) || 0` —— 用户把价格留空就是 0
      · PATCH：裸 dict 的 `.get("unit_price")` —— 缺失是 None
    所以这里**刻意不去区分**"显式填了 0"和"根本没填"：两者都是"没提供有效价格"，
    一律走兜底。退货单价为 0 在业务上没有正向含义，把它当默认值处理才对。

    兜底顺序由调用方通过 `fallback` 决定（None = 没有可继承的来源）：
      · PATCH：回查这张单**原来的同商品明细单价**（用户明确要求的口径）
      · POST ：没有原单可查，回落到 `products.purchase_price × factor`
        —— 档案进价是**基本单位**口径，必须乘 factor 才等于"每录入单位"的价；
        不乘的话「1 箱」会按「1 盒」的价记账，少 factor 倍（`DESIGN_3B` §7.2 的同类陷阱）

    兜底也拿不到 >0 的数就 **400**。宁可挡在门外，也不要往库里写一个 0。
    """
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        # PATCH 那条路是裸 dict，脏值会走到这里 —— 不能让它冒成 500
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货单价不是合法数字",
        ) from None
    if value > 0:
        return value
    if value < 0:
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货单价不能是负数（当前填的是 {value}）",
        )
    # 走兜底
    if fallback is not None and fallback > 0:
        return float(fallback)
    if product is not None:
        hint = f"商品「{product.name}」的档案里也没有进价"
    else:
        hint = "该商品档案不存在，无法回查进价"
    raise HTTPException(
        status_code=400,
        detail=(
            f"第 {index + 1} 行的退货单价必须大于 0（留空或填 0 都不允许）。"
            f"{hint}，请在明细里显式填写单价。"
        ),
    )


def _purchase_return_apply_stock(
    db: Session, item: PurchaseReturn, rows: list[PurchaseReturnItem]
) -> None:
    """把这张退货单的明细写成 outbound 库存流水（**先冲销旧的**）。

    退货是减少现存量，方向和采购入库相反。单据没填仓库时回退到默认仓库，
    并把结果回填到单据上，保证单据与流水指向同一个仓。

    ⚠️ 建单（`create_purchase_return`）和改单（`update_purchase_return`）**都**调它。
    以前改单那条路是「整单替换明细但完全不碰流水」，于是
    「建单退 3 件 → 改成退 5 件」会留下「单据说 5、流水还是 −3」——
    单据与库存永久对不上，而且没有任何报错。**先冲后写**才是一致的。
    """
    _revert_stock(db, "purchase_return", item.id)
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            # 不在这里 int() —— 取整交给 `_apply_stock` 统一做，
            # 数量必须先由 `_purchase_return_quantity` 校验成整数才走到这儿。
            quantity=row.quantity,
            transaction_type="outbound",
            unit_price=row.unit_price,
            # 与采购入库同一套换算（方向相反）：流水 −(数量×factor) 个基本单位
            unit_factor=row.unit_factor,
            related_type="purchase_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            note=f"采购退货 {item.return_no}",
        )



def _purchase_return_apply_finance(db: Session, item: PurchaseReturn, total: float) -> None:
    """把退货单的「应付冲减」写成财务流水（**先冲销旧的**）。

    金额记负数（方向 out），对账时自然抵减采购产生的应付。

    ⚠️ 和 `_purchase_return_apply_stock` 是同一类问题的两半：
    改了明细却只重算库存、不重算财务，会留下
    「单据说退 5 件（−500）、库存 −5、财务还是 −300」——
    比两样都不改**更难查**，因为三个数字互不相等，谁对谁错说不清。
    所以派生数据要么一起重算，要么一起不动。
    """
    _revert_finance(db, "purchase_return", item.id)
    if total > 0:
        _write_finance(
            db,
            transaction_type="payable",
            direction="out",
            amount=-total,
            related_type="purchase_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            supplier_id=item.supplier_id,
            warehouse_id=item.warehouse_id,
            occurred_at=item.return_date,
            note=f"采购退货 {item.return_no} 冲减应付",
        )



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
                "unit_factor": row.unit_factor,
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

    # ⚠️ 明细校验必须在**落表头之前**做完。
    # 表头在下面明细循环之前就 `db.commit()` 了，所以如果等循环里才抛 400，
    # 库里会留下一张「只有表头、没有明细」的空退货单 —— 用户看到报错以为没成功，
    # 列表里却多了一张金额为 0 的单。
    # 换算率解析同样会 400（单位查不到 / 已停用），所以一并提前算。
    snapshots = [_resolve_item_snapshot(db, line) for line in payload.items]
    quantities = [
        _purchase_return_quantity(line.quantity, index)
        for index, line in enumerate(payload.items)
    ]
    unit_factors = [
        _resolve_unit_factor(db, line.product_id, snapshot[2])
        for line, snapshot in zip(payload.items, snapshots)
    ]
    # ⚠️ 单价校验也必须在**落表头之前**做完（单价缺失会 400）。
    # 建退货单没有"原单"可回查，所以兜底用**档案进价 × 换算率**：
    # 档案进价是基本单位口径，乘 factor 才是"每录入单位"的价。
    products = [
        db.get(Product, line.product_id) if line.product_id else None
        for line in payload.items
    ]
    unit_prices = [
        _purchase_return_unit_price(
            line.unit_price,
            index,
            product=products[index],
            factor=unit_factors[index],
            fallback=(
                float(products[index].purchase_price or 0.0) * unit_factors[index]
                if products[index] is not None
                else None
            ),
        )
        for index, line in enumerate(payload.items)
    ]

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

    total = ZERO
    rows: list[PurchaseReturnItem] = []
    for index, line in enumerate(payload.items):
        name, standards, unit = snapshots[index]
        quantity = quantities[index]
        unit_price = unit_prices[index]
        row = PurchaseReturnItem(
            purchase_return_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            unit_factor=unit_factors[index],
            quantity=quantity,
            unit_price=unit_price,
            amount=line_amount(unit_price, quantity),
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    item.total_amount = money(total)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)

    # —— 库存联动：退货减少现存量（outbound）——
    _purchase_return_apply_stock(db, item, rows)

    # —— 财务联动：退货冲减应付。金额记负数（方向 out），对账时自然抵减 ——
    _purchase_return_apply_finance(db, item, total)

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
    items_replaced = False
    if isinstance(payload.get("items"), list):
        # ⚠️ 整单替换是"先删后建"，所以**必须先把原明细的单价抄下来** ——
        # 调用方（例如只改数量的脚本）不传 unit_price 时要拿它兜底。
        # 不抄的话就会静默把整张单的金额冲成 0（库存照扣、应付不再冲减），
        # 详见 `_purchase_return_unit_price` 的 docstring。
        previous_prices: dict[int, float] = {}
        for old in db.query(PurchaseReturnItem).filter(
            PurchaseReturnItem.purchase_return_id == item.id
        ).all():
            old_price = float(old.unit_price or 0.0)
            if old.product_id is not None and old_price > 0:
                # setdefault：同一商品在旧单里出现多次时，取第一次（与明细顺序一致）
                previous_prices.setdefault(int(old.product_id), old_price)
        db.query(PurchaseReturnItem).filter(PurchaseReturnItem.purchase_return_id == item.id).delete()
        rows = []
        total = ZERO
        for index, line in enumerate(payload["items"]):
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            pid = int(product_id) if product_id else None
            product = db.get(Product, pid) if pid else None
            quantity = _purchase_return_quantity(line_data.get("quantity"), index)
            unit = line_data.get("unit") or (product.unit if product else None)
            # 走 PATCH 时是**裸 dict**，和 POST 一样按 unit 现场解析，不信客户端传 factor
            factor = _resolve_unit_factor(db, pid, unit)
            # 单价缺失 → 回查这张单原来的同商品单价；查不到（新加的行）→ 400
            unit_price = _purchase_return_unit_price(
                line_data.get("unit_price"),
                index,
                product=product,
                factor=factor,
                fallback=previous_prices.get(pid) if pid else None,
            )
            row = PurchaseReturnItem(
                purchase_return_id=item.id,
                product_id=pid,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=unit,
                unit_factor=factor,
                quantity=quantity,
                unit_price=unit_price,
                amount=line_amount(unit_price, quantity),
                note=line_data.get("note"),
            )
            total += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_amount = money(total)
        item.amount_chinese = amount_to_chinese(item.total_amount)
        items_replaced = True

    # —— 库存联动：改单必须**重写**流水（不是"不动"）——
    # 以前这里是「整单替换明细但完全不碰流水」，于是
    # 「建单退 3 件 → 改成退 5 件」会留下「单据说 5、流水还是 −3」：
    # 单据与库存永久对不上，而且没有任何报错。
    # 明细或仓库**任一**被改动过都要重算 —— 只换明细不换仓、或只换仓不换明细，
    # 都会让流水指向一个和单据不一致的口径。
    if items_replaced or "warehouse_id" in payload:
        _purchase_return_apply_stock(db, item, rows)

    # —— 财务联动：和库存同样的道理。改了明细/供应商/仓库/退货日期，
    #    应付冲减的金额与归属就都变了，必须一起重算 ——
    if items_replaced or any(
        key in payload for key in ("supplier_id", "warehouse_id", "return_date")
    ):
        _purchase_return_apply_finance(db, item, item.total_amount)

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
