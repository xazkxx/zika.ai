"""销售管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

销售开单 / 销售订单 / 报价单 / 购销合同 / 销售退货。
"""

from __future__ import annotations

from app.core.company_info import load_company
from app.db.session import get_db
from app.models.contract import CONTRACT_STATUS, CONTRACT_TEMPLATES, CONTRACT_TYPES, Contract, ContractItem
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.product import Product
from app.models.quotation import (
    QUOTATION_PAYMENT_METHODS,
    QUOTATION_STATUS,
    QUOTATION_TRANSPORT_METHODS,
    Quotation,
    QuotationItem,
)
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.sales_return import SALES_RETURN_STATUS, SalesReturn, SalesReturnItem
from app.models.supplier import Supplier
from app.schemas import (
    ContractCreate,
    ContractRead,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    QuotationCreate,
    QuotationRead,
    SalesOrderCreate,
    SalesOrderItemCreate,
    SalesOrderRead,
    SalesReturnCreate,
    SalesReturnRead,
)
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _A2_DEFAULTS,
    _A2_DEFAULT_COPIES,
    _A2_DEFAULT_INSPECTION_DAYS,
    _A2_DEFAULT_OBJECTION_DAYS,
    _A2_DEFAULT_PENALTY_RATE,
    _apply_stock,
    _contract_items,
    _next_doc_no,
    _paginate,
    _prev_debt_total,
    _quotation_items,
    _resolve_item_snapshot,
    _resolve_warehouse_id,
    _revert_finance,
    _revert_stock,
    _s,
    _sales_return_items,
    _write_finance,
    amount_to_chinese,
)

router = APIRouter(prefix="", tags=["erp"])




def _build_sales_payload(item: SalesOrder, rows: list[SalesOrderItem]) -> SalesOrderRead:
    return SalesOrderRead(
        id=item.id,
        order_no=item.order_no,
        customer_id=item.customer_id,
        status=item.status,
        total_amount=item.total_amount,
        doc_type=item.doc_type or "outbound",
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
        received_amount=item.received_amount,
        is_invoiced=item.is_invoiced,
        receivable_amount=item.receivable_amount,
        current_debt=item.current_debt,
        prev_debt=item.prev_debt,
        total_debt=item.total_debt,
        items=[
            {
                "id": row.id,
                "sales_order_id": row.sales_order_id,
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



@router.get("/sales-orders")
def list_sales_orders(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int | None = None,
    doc_type: str | None = None,
    customer_id: int | None = None,
) -> list[SalesOrderRead]:
    query = db.query(SalesOrder).order_by(SalesOrder.id.desc())
    # doc_type 过滤：order=销售订单页；outbound=开单管理页；不传=全量（兼容旧调用方）
    if doc_type:
        query = query.filter(SalesOrder.doc_type == doc_type)
    if customer_id:
        query = query.filter(SalesOrder.customer_id == customer_id)
    items = _paginate(query, skip, limit).all()
    result = []
    for item in items:
        order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == item.id).all()
        result.append(_build_sales_payload(item, order_items))
    return result



@router.post("/sales-orders", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: SalesOrderCreate, db: Session = Depends(get_db)) -> SalesOrderRead:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    # 单据性质：order=销售订单（只订货）；outbound=销售开单（默认，真实出库+财务+库存）
    doc_type = (payload.doc_type or "outbound").strip()
    if doc_type not in ("order", "outbound"):
        raise HTTPException(status_code=400, detail="doc_type 仅支持 order / outbound")

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, SalesOrder, "XSD" if doc_type == "order" else "XS")
    if db.query(SalesOrder).filter(SalesOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="销售开单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    # 销售订单不产生欠款（还没出货结算），欠款链字段保持 0
    prev_debt = (
        round(_prev_debt_total(db, SalesOrder, SalesOrder.customer_id, payload.customer_id), 2)
        if doc_type == "outbound"
        else 0.0
    )

    item = SalesOrder(
        order_no=order_no,
        customer_id=payload.customer_id,
        status="draft",
        total_amount=0.0,
        doc_type=doc_type,
        warehouse_id=payload.warehouse_id,
        project_id=payload.project_id,
        businesser=payload.businesser or customer.businesser,
        order_date=order_date,
        delivery_date=payload.delivery_date,
        payment_method=payload.payment_method,
        contact=payload.contact or customer.contact,
        contact_phone=payload.contact_phone or customer.contact_phone or customer.phone,
        address=payload.address or customer.address,
        note=payload.note,
        is_invoiced=payload.is_invoiced,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[SalesOrderItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = SalesOrderItem(
            sales_order_id=item.id,
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

    # 结算链：应收 → 优惠 → 实收
    # 实收金额不填 = 0，即本单全额挂账；之后由「收款登记」逐笔冲减。
    gross = round(total, 2)
    discount = round(float(payload.discount_amount or 0.0), 2)
    net = round(gross - discount, 2)
    received = round(float(payload.received_amount or 0.0), 2)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = round(net - received, 2)

    item.total_amount = gross
    item.receivable_amount = gross
    item.discount_amount = discount
    item.received_amount = received
    item.current_debt = current_debt
    item.prev_debt = prev_debt
    item.total_debt = round(prev_debt + current_debt, 2)
    item.status = "submitted"

    # —— 销售订单（doc_type=order）：到此为止 ——
    # 订单只是"意向确认"，不动库存、不写财务、不产生欠款；
    # 真正的出库/结算由「转开单」或手工开销售单完成。
    if doc_type == "order":
        item.received_amount = 0.0
        item.current_debt = 0.0
        item.prev_debt = 0.0
        item.total_debt = 0.0
        db.commit()
        db.refresh(item)
        return _build_sales_payload(item, rows)

    # 财务联动：单据审核即产生应收，人工无需再录
    if gross > 0:
        _write_finance(
            db,
            transaction_type="receivable",
            direction="in",
            amount=gross,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            customer_id=payload.customer_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"销售开单 {item.order_no} 产生应收",
        )
    if received > 0:
        _write_finance(
            db,
            transaction_type="receipt",
            direction="in",
            amount=received,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            customer_id=payload.customer_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"销售开单 {item.order_no} 收款",
        )

    # 库存联动：销售出库即减少现存量，每条明细一条流水。
    # 库存不足不阻断开单（允许负库存），但现存量与预警会把它标出来。
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=row.quantity,
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            note=f"销售出库 {item.order_no}",
        )

    db.commit()
    db.refresh(item)
    return _build_sales_payload(item, rows)



@router.patch("/sales-orders/{order_id}/status")
def update_sales_order_status(order_id: int, payload: dict[str, object], db: Session = Depends(get_db)) -> SalesOrderRead:
    item = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Sales order not found")

    status_value = str(payload.get("status") or "submitted").strip()
    if not status_value:
        raise HTTPException(status_code=400, detail="status is required")

    item.status = status_value
    db.commit()
    db.refresh(item)
    order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == item.id).all()
    return _build_sales_payload(item, order_items)



@router.delete("/sales-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_order(order_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Sales order not found")
    # 已转开单的订单不允许直接删（开单还引用着它），先删开单再回来删订单；
    # 用 source_order_id 反查比看 status 更准——开单删掉后订单自然就能删了
    if (
        item.doc_type == "order"
        and db.query(SalesOrder).filter(SalesOrder.source_order_id == order_id).first() is not None
    ):
        raise HTTPException(status_code=409, detail="该订单已转开单，请先删除对应的开单")
    # 库存联动回滚：这张单产生的出库流水一并冲销，否则货扣了单没了，库存就再也对不上
    _revert_stock(db, "sales_out", order_id)
    # 财务联动回滚：开单产生的应收 / 收款流水一并冲销，避免留下指向已删单据的孤儿
    _revert_finance(db, "sales_out", order_id)
    # 先删订单明细，再删订单本身，避免留下孤儿明细
    db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/sales-orders/{order_id}/to-outbound", response_model=SalesOrderRead)
def sales_order_to_outbound(order_id: int, db: Session = Depends(get_db)) -> SalesOrderRead:
    """销售订单 → 销售开单（一键转单）。

    生成一张新的开单（doc_type=outbound，写库存流水与应收财务流水），
    复制订单的头信息与明细；订单本身置 completed 并保留可追溯。
    """
    order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Sales order not found")
    if order.doc_type != "order":
        raise HTTPException(status_code=400, detail="只有销售订单才能转开单")
    if order.status == "completed":
        raise HTTPException(status_code=409, detail="该订单已转开单，不能重复转单")

    order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order.id).all()
    payload = SalesOrderCreate(
        customer_id=order.customer_id,
        items=[
            SalesOrderItemCreate(
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
        received_amount=0.0,  # 结算在开单上另行登记，转单时不带收款
        is_invoiced=order.is_invoiced,
    )
    outbound = create_sales_order(payload, db)

    # 回填：开单回指来源订单，订单置 completed
    outbound_row = db.query(SalesOrder).filter(SalesOrder.id == outbound.id).first()
    outbound_row.source_order_id = order.id
    order.status = "completed"
    db.commit()
    db.refresh(outbound_row)
    order_items2 = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == outbound_row.id).all()
    return _build_sales_payload(outbound_row, order_items2)



def _quotation_payload(item: Quotation, rows: list[QuotationItem]) -> dict[str, object]:
    data = {column.name: getattr(item, column.name) for column in Quotation.__table__.columns}
    data["items"] = [
        {
            "id": row.id,
            "quotation_id": row.quotation_id,
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
    ]
    return data



def _contract_payload(item: Contract, rows: list[ContractItem]) -> dict[str, object]:
    data = {column.name: getattr(item, column.name) for column in Contract.__table__.columns}
    data["items"] = [
        {
            "id": row.id,
            "contract_id": row.contract_id,
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
    ]
    return data



@router.get("/contracts/meta")
def contract_meta() -> dict[str, object]:
    """合同页面的字典：模板版本 / 合同类型 / 状态 / 条款默认值。"""
    return {
        "templates": [{"code": code, "label": label} for code, label in CONTRACT_TEMPLATES.items()],
        "types": [{"code": code, "label": label} for code, label in CONTRACT_TYPES.items()],
        "statuses": [{"code": code, "label": label} for code, label in CONTRACT_STATUS.items()],
        "defaults": dict(_A2_DEFAULTS),
        "default_own": load_company(),
        "inspection_days": _A2_DEFAULT_INSPECTION_DAYS,
        "objection_days": _A2_DEFAULT_OBJECTION_DAYS,
        "penalty_rate": _A2_DEFAULT_PENALTY_RATE,
        "copies": _A2_DEFAULT_COPIES,
    }



@router.get("/contracts")
def list_contracts(
    db: Session = Depends(get_db),
    contract_type: str | None = Query(None),
    status_value: str | None = Query(None, alias="status"),
    party_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[ContractRead]:
    query = db.query(Contract).order_by(Contract.id.desc())
    if contract_type:
        query = query.filter(Contract.contract_type == contract_type)
    if status_value:
        query = query.filter(Contract.status == status_value)
    if party_id:
        query = query.filter(Contract.party_id == party_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Contract.contract_no.ilike(like),
                Contract.title.ilike(like),
                Contract.party_name.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_contract_payload(item, _contract_items(db, item.id)) for item in items]



@router.get("/contracts/{contract_id}", response_model=ContractRead)
def get_contract(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return _contract_payload(item, _contract_items(db, item.id))



@router.post("/contracts", response_model=ContractRead, status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.contract_type not in CONTRACT_TYPES:
        raise HTTPException(status_code=400, detail="contract_type 只能是 sales 或 purchase")

    contract_no = (payload.contract_no or "").strip() or _next_doc_no(db, Contract, "HT", field="contract_no")
    if db.query(Contract).filter(Contract.contract_no == contract_no).first():
        raise HTTPException(status_code=400, detail="合同编号已存在")

    # 对方单位：能从档案带出的自动带出，其余留白由用户填
    party_type = payload.party_type or ("customer" if payload.contract_type == "sales" else "supplier")
    party = None
    if payload.party_id:
        model = Customer if party_type == "customer" else Supplier
        party = db.get(model, payload.party_id)
        if party is None:
            raise HTTPException(status_code=404, detail="对方单位档案不存在")

    data: dict[str, object] = payload.model_dump(exclude={"items", "status"})
    data["contract_no"] = contract_no
    data["contract_type"] = payload.contract_type
    data["party_type"] = party_type
    data["status"] = payload.status or "draft"
    data["title"] = (payload.title or "").strip() or CONTRACT_TYPES[payload.contract_type]
    data["sign_date"] = payload.sign_date or datetime.now().strftime("%Y-%m-%d")

    if party is not None:
        data["party_name"] = payload.party_name or party.name
        data["party_address"] = payload.party_address or getattr(party, "address", None)
        data["party_bank_name"] = payload.party_bank_name or getattr(party, "bank_name", None)
        data["party_bank_account"] = payload.party_bank_account or getattr(party, "bank_account", None)
        data["party_tax_no"] = payload.party_tax_no or getattr(party, "tax_no", None)
        if party_type == "customer":
            data["party_contact"] = payload.party_contact or party.contact
            data["party_phone"] = payload.party_phone or party.contact_phone or party.phone
        else:
            data["party_contact"] = payload.party_contact or party.main_contact or party.contact
            data["party_phone"] = payload.party_phone or party.mobile or party.phone

    # 我方主体 / 条款变量：没填的用默认值兜底，保证打印出来是完整合同
    for key, value in {**load_company(), **_A2_DEFAULTS}.items():
        if not data.get(key):
            data[key] = value
    if not data.get("inspection_days"):
        data["inspection_days"] = _A2_DEFAULT_INSPECTION_DAYS
    if not data.get("objection_days"):
        data["objection_days"] = _A2_DEFAULT_OBJECTION_DAYS
    if not data.get("penalty_rate"):
        data["penalty_rate"] = _A2_DEFAULT_PENALTY_RATE
    if not data.get("copies"):
        data["copies"] = _A2_DEFAULT_COPIES

    item = Contract(**data)
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[ContractItem] = []
    for line in payload.items:
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = ContractItem(
            contract_id=item.id,
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
    return _contract_payload(item, rows)



@router.patch("/contracts/{contract_id}", response_model=ContractRead)
def update_contract(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")

    text_fields = [
        "title", "party_name", "party_tax_no", "party_legal_person", "party_address",
        "party_contact", "party_phone", "party_bank_name", "party_bank_account",
        "own_name", "own_tax_no", "own_legal_person", "own_address", "own_contact",
        "own_phone", "own_bank_name", "own_bank_account",
        "sign_date", "sign_place", "valid_from", "valid_to",
        "payment_terms", "invoice_requirement", "quality_standard", "package_standard",
        "delivery_date", "delivery_place", "delivery_method", "freight_bearer",
        "warranty_terms", "dispute_resolution", "service_address", "other_terms", "note",
    ]
    number_fields = ["tax_rate", "penalty_rate", "inspection_days", "objection_days", "copies", "warehouse_id"]

    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    for field in number_fields:
        if field in payload:
            raw = payload.get(field)
            if raw in ("", None):
                setattr(item, field, None)
            else:
                try:
                    setattr(item, field, float(raw) if field in ("tax_rate", "penalty_rate") else int(raw))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=f"{field} 取值非法") from exc
    if "is_tax_included" in payload:
        item.is_tax_included = bool(payload.get("is_tax_included"))
    if payload.get("status"):
        if str(payload["status"]) not in CONTRACT_STATUS:
            raise HTTPException(status_code=400, detail="合同状态非法")
        item.status = str(payload["status"])

    rows = _contract_items(db, item.id)
    # 传了明细就整单替换（合同明细是标的物清单，逐行改容易改乱）
    if isinstance(payload.get("items"), list):
        db.query(ContractItem).filter(ContractItem.contract_id == item.id).delete()
        rows = []
        total = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = ContractItem(
                contract_id=item.id,
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
    return _contract_payload(item, rows)



@router.patch("/contracts/{contract_id}/status", response_model=ContractRead)
def update_contract_status(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in CONTRACT_STATUS:
        raise HTTPException(status_code=400, detail="合同状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _contract_payload(item, _contract_items(db, item.id))



@router.get("/contracts/{contract_id}/references")
def contract_references(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """删除前的引用检查：已转单的合同不能直接删，否则单据溯源断链。"""
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    refs: list[dict[str, object]] = []
    if item.order_id:
        refs.append({
            "type": "order",
            "label": f"已生成{'销售开单' if item.contract_type == 'sales' else '采购入库单'}",
            "doc_no": _s(item.order_no),
            "count": 1,
        })
    return {"contract_id": contract_id, "contract_no": item.contract_no, "references": refs}



@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: int, force: bool = Query(False), db: Session = Depends(get_db)
) -> Response:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    if item.order_id and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"合同 {item.contract_no} 已生成单据 {item.order_no}，删除会断开单据溯源",
                "references": [{"type": "order", "doc_no": item.order_no}],
                "hint": "如需保留单据，请改为把合同状态置为「已作废」；确要删除可加 force=true",
            },
        )
    db.query(ContractItem).filter(ContractItem.contract_id == contract_id).delete()
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/contracts/{contract_id}/to-order")
def contract_to_order(
    contract_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """一键转单：销售合同 → 销售开单；采购合同 → 采购入库单。

    这是合同与财务 / 库存的**唯一**连接点 —— 合同本身不入账，
    转成单据后由单据产生应收应付并联动库存。
    """
    from app.api.v1.routes.erp_purchase import create_purchase_order
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    if item.order_id:
        raise HTTPException(status_code=409, detail=f"该合同已生成单据 {item.order_no}，不能重复转单")
    if item.status == "void":
        raise HTTPException(status_code=400, detail="已作废的合同不能转单")

    rows = _contract_items(db, item.id)
    if not rows:
        raise HTTPException(status_code=400, detail="合同没有明细，无法转单")
    if not item.party_id:
        raise HTTPException(status_code=400, detail="合同未关联客户 / 供应商档案，无法转单")

    payload = payload or {}
    note = f"由合同 {item.contract_no} 生成"
    if item.contract_type == "sales":
        order_payload = SalesOrderCreate(
            customer_id=item.party_id,
            items=[
                SalesOrderItemCreate(
                    product_id=row.product_id or 0,
                    quantity=int(row.quantity or 0),
                    unit_price=float(row.unit_price or 0.0),
                    product_name=row.product_name,
                    standards=row.standards,
                    unit=row.unit,
                    note=row.note,
                )
                for row in rows
            ],
            warehouse_id=item.warehouse_id,
            order_date=item.sign_date,
            delivery_date=item.delivery_date,
            contact=item.party_contact,
            contact_phone=item.party_phone,
            address=item.party_address,
            note=note,
        )
        order = create_sales_order(order_payload, db)
        order_type, order_label = "sales_order", "销售开单"
    else:
        order_payload = PurchaseOrderCreate(
            supplier_id=item.party_id,
            items=[
                PurchaseOrderItemCreate(
                    product_id=row.product_id or 0,
                    quantity=int(row.quantity or 0),
                    unit_price=float(row.unit_price or 0.0),
                    product_name=row.product_name,
                    standards=row.standards,
                    unit=row.unit,
                    note=row.note,
                )
                for row in rows
            ],
            warehouse_id=item.warehouse_id,
            order_date=item.sign_date,
            delivery_date=item.delivery_date,
            contact=item.party_contact,
            contact_phone=item.party_phone,
            address=item.party_address,
            note=note,
        )
        order = create_purchase_order(order_payload, db)
        order_type, order_label = "purchase_order", "采购入库单"

    item.order_id = order.id
    item.order_no = order.order_no
    if item.status in ("draft", "signed"):
        item.status = "executing"
    db.commit()
    db.refresh(item)

    return {
        "contract_id": item.id,
        "contract_no": item.contract_no,
        "order_type": order_type,
        "order_label": order_label,
        "order_id": order.id,
        "order_no": order.order_no,
        "order_amount": float(order.total_amount or 0.0),
        "message": f"已按合同 {item.contract_no} 生成{order_label} {order.order_no}",
    }



# —————————————————————— 销售报价单（对齐浩技云「销售 → 报价单」）——————————————————————


@router.get("/quotations/meta")
def quotation_meta() -> dict[str, object]:
    """报价单页面字典：状态 / 常用付款方式 / 常用运输方式。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in QUOTATION_STATUS.items()],
        "payment_methods": list(QUOTATION_PAYMENT_METHODS),
        "transport_methods": list(QUOTATION_TRANSPORT_METHODS),
    }



@router.get("/quotations")
def list_quotations(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    customer_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[QuotationRead]:
    query = db.query(Quotation).order_by(Quotation.id.desc())
    if status_value:
        query = query.filter(Quotation.status == status_value)
    if customer_id:
        query = query.filter(Quotation.customer_id == customer_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Quotation.quote_no.ilike(like),
                Quotation.customer_name.ilike(like),
                Quotation.businesser.ilike(like),
                Quotation.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_quotation_payload(item, _quotation_items(db, item.id)) for item in items]



@router.get("/quotations/{quotation_id}", response_model=QuotationRead)
def get_quotation(quotation_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    return _quotation_payload(item, _quotation_items(db, item.id))



@router.post("/quotations", response_model=QuotationRead, status_code=status.HTTP_201_CREATED)
def create_quotation(payload: QuotationCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.status and payload.status not in QUOTATION_STATUS:
        raise HTTPException(status_code=400, detail="报价单状态非法")

    quote_no = (payload.quote_no or "").strip() or _next_doc_no(db, Quotation, "BJ", field="quote_no")
    if db.query(Quotation).filter(Quotation.quote_no == quote_no).first():
        raise HTTPException(status_code=400, detail="报价单号已存在")

    data: dict[str, object] = payload.model_dump(exclude={"items", "status"})
    data["quote_no"] = quote_no
    data["status"] = payload.status or "draft"
    data["quote_date"] = payload.quote_date or datetime.now().strftime("%Y-%m-%d")

    # 客户快照：能从档案带出的自动带出，其余留白由用户填（报价单是发给客户的历史凭证，
    # 不能让客户档案改地址把旧报价一起改掉）
    if payload.customer_id:
        customer = db.get(Customer, payload.customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户档案不存在")
        data["customer_name"] = payload.customer_name or customer.name
        data["customer_address"] = payload.customer_address or getattr(customer, "address", None)
        data["contact"] = payload.contact or getattr(customer, "contact", None)
        data["contact_phone"] = (
            payload.contact_phone
            or getattr(customer, "contact_phone", None)
            or getattr(customer, "phone", None)
        )

    item = Quotation(**data)
    db.add(item)
    db.commit()
    db.refresh(item)

    total_amount = 0.0
    total_quantity = 0.0
    rows: list[QuotationItem] = []
    for line in payload.items:
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = QuotationItem(
            quotation_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total_amount += row.amount
        total_quantity += quantity
        rows.append(row)
    db.add_all(rows)

    item.total_amount = round(total_amount, 2)
    item.total_quantity = round(total_quantity, 2)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)
    return _quotation_payload(item, rows)



@router.patch("/quotations/{quotation_id}", response_model=QuotationRead)
def update_quotation(
    quotation_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")

    text_fields = [
        "customer_name", "customer_address", "contact", "contact_phone", "fax",
        "quote_date", "valid_until", "businesser", "payment_method",
        "transport_method", "delivery_place", "note",
    ]
    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    if "warehouse_id" in payload:
        raw = payload.get("warehouse_id")
        item.warehouse_id = int(raw) if raw not in ("", None) else None
    if "customer_id" in payload:
        raw = payload.get("customer_id")
        item.customer_id = int(raw) if raw not in ("", None) else None
    if payload.get("status"):
        if str(payload["status"]) not in QUOTATION_STATUS:
            raise HTTPException(status_code=400, detail="报价单状态非法")
        item.status = str(payload["status"])

    rows = _quotation_items(db, item.id)
    # 传了明细就整单替换（明细是报价商品清单，逐行改容易改乱）
    if isinstance(payload.get("items"), list):
        db.query(QuotationItem).filter(QuotationItem.quotation_id == item.id).delete()
        rows = []
        total_amount = 0.0
        total_quantity = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = QuotationItem(
                quotation_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total_amount += row.amount
            total_quantity += quantity
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total_amount, 2)
        item.total_quantity = round(total_quantity, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)

    db.commit()
    db.refresh(item)
    return _quotation_payload(item, rows)



@router.patch("/quotations/{quotation_id}/status", response_model=QuotationRead)
def update_quotation_status(
    quotation_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in QUOTATION_STATUS:
        raise HTTPException(status_code=400, detail="报价单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _quotation_payload(item, _quotation_items(db, item.id))



@router.get("/quotations/{quotation_id}/references")
def quotation_references(quotation_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """删除前的引用检查：已转单的报价单不能直接删，否则订单溯源断链。"""
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    refs: list[dict[str, object]] = []
    if item.order_id:
        refs.append({
            "type": "order",
            "label": "已生成销售订单",
            "doc_no": _s(item.order_no),
            "count": 1,
        })
    return {"quotation_id": quotation_id, "quote_no": item.quote_no, "references": refs}



@router.delete("/quotations/{quotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quotation(
    quotation_id: int, force: bool = Query(False), db: Session = Depends(get_db)
) -> Response:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    if item.order_id and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"报价单 {item.quote_no} 已生成销售订单 {item.order_no}，删除会断开订单溯源",
                "references": [{"type": "order", "doc_no": item.order_no}],
                "hint": "如需保留订单，请改为把报价单状态置为「已作废」；确要删除可加 force=true",
            },
        )
    db.query(QuotationItem).filter(QuotationItem.quotation_id == quotation_id).delete()
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/quotations/{quotation_id}/to-order")
def quotation_to_order(
    quotation_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """一键转单：报价单 → 销售订单（`doc_type='order'`）。

    与购销合同同一条链路 —— 报价单本身不产生应收、不动库存，
    转成销售订单后由订单去转开单，才联动库存与财务。
    """
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    if item.order_id:
        raise HTTPException(status_code=409, detail=f"该报价单已生成销售订单 {item.order_no}，不能重复转单")
    if item.status == "void":
        raise HTTPException(status_code=400, detail="已作废的报价单不能转单")

    rows = _quotation_items(db, item.id)
    if not rows:
        raise HTTPException(status_code=400, detail="报价单没有明细，无法转单")
    if not item.customer_id:
        raise HTTPException(status_code=400, detail="报价单未关联客户档案，无法转单")

    order_payload = SalesOrderCreate(
        customer_id=item.customer_id,
        doc_type="order",
        items=[
            SalesOrderItemCreate(
                product_id=row.product_id or 0,
                quantity=int(row.quantity or 0),
                unit_price=float(row.unit_price or 0.0),
                product_name=row.product_name,
                standards=row.standards,
                unit=row.unit,
                note=row.note,
            )
            for row in rows
        ],
        warehouse_id=item.warehouse_id,
        order_date=item.quote_date,
        contact=item.contact,
        contact_phone=item.contact_phone,
        address=item.customer_address,
        payment_method=item.payment_method,
        note=f"由报价单 {item.quote_no} 生成",
    )
    order = create_sales_order(order_payload, db)

    item.order_id = order.id
    item.order_no = order.order_no
    if item.status in ("draft", "quoted"):
        item.status = "accepted"
    db.commit()
    db.refresh(item)

    return {
        "quotation_id": item.id,
        "quote_no": item.quote_no,
        "order_type": "sales_order",
        "order_label": "销售订单",
        "order_id": order.id,
        "order_no": order.order_no,
        "order_amount": float(order.total_amount or 0.0),
        "message": f"已按报价单 {item.quote_no} 生成销售订单 {order.order_no}",
    }



def _sales_return_payload(item: SalesReturn, rows: list[SalesReturnItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "return_no": item.return_no,
        "customer_id": item.customer_id,
        "customer_name": item.customer_name,
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
                "sales_return_id": row.sales_return_id,
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



@router.get("/sales-returns/meta")
def sales_return_meta() -> dict[str, object]:
    """销售退货页字典：状态。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in SALES_RETURN_STATUS.items()],
    }



@router.get("/sales-returns")
def list_sales_returns(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    customer_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(SalesReturn).order_by(SalesReturn.id.desc())
    if status_value:
        query = query.filter(SalesReturn.status == status_value)
    if customer_id:
        query = query.filter(SalesReturn.customer_id == customer_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                SalesReturn.return_no.ilike(like),
                SalesReturn.customer_name.ilike(like),
                SalesReturn.businesser.ilike(like),
                SalesReturn.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_sales_return_payload(item, _sales_return_items(db, item.id)) for item in items]



@router.get("/sales-returns/{return_id}", response_model=SalesReturnRead)
def get_sales_return(return_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    return _sales_return_payload(item, _sales_return_items(db, item.id))



@router.post("/sales-returns", response_model=SalesReturnRead, status_code=status.HTTP_201_CREATED)
def create_sales_return(payload: SalesReturnCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户档案不存在")

    if payload.status and payload.status not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")

    return_no = (payload.return_no or "").strip() or _next_doc_no(db, SalesReturn, "XSTH", field="return_no")
    if db.query(SalesReturn).filter(SalesReturn.return_no == return_no).first():
        raise HTTPException(status_code=400, detail="销售退货单号已存在")

    return_date = payload.return_date or datetime.now().strftime("%Y-%m-%d")

    item = SalesReturn(
        return_no=return_no,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name or customer.name,
        contact=payload.contact or customer.contact,
        contact_phone=payload.contact_phone or customer.contact_phone or customer.phone,
        address=payload.address or customer.address,
        warehouse_id=payload.warehouse_id,
        businesser=payload.businesser or customer.businesser,
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
    rows: list[SalesReturnItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        row = SalesReturnItem(
            sales_return_id=item.id,
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

    # —— 库存联动：退货增加现存量（inbound）——
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=int(row.quantity or 0),
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="sales_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            note=f"销售退货 {item.return_no}",
        )

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

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, rows)



@router.patch("/sales-returns/{return_id}", response_model=SalesReturnRead)
def update_sales_return(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")

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
            raw = payload.get(int_field)
            setattr(item, int_field, int(raw) if raw not in ("", None) else None)
    if payload.get("status"):
        if str(payload["status"]) not in SALES_RETURN_STATUS:
            raise HTTPException(status_code=400, detail="销售退货状态非法")
        item.status = str(payload["status"])

    rows = _sales_return_items(db, item.id)
    # 传了明细就整单替换并重算金额/大写
    if isinstance(payload.get("items"), list):
        db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == item.id).delete()
        rows = []
        total = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = SalesReturnItem(
                sales_return_id=item.id,
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
    return _sales_return_payload(item, rows)



@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)
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



@router.delete("/sales-returns/{return_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_return(return_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    # 库存联动回滚：冲销这张退货单产生的 inbound 流水（退货入库的动作撤销，库存减回去）
    _revert_stock(db, "sales_return", return_id)
    # 财务联动回滚：冲销这张单产生的应收冲减流水
    db.query(FinancialTransaction).filter(
        FinancialTransaction.related_type == "sales_return",
        FinancialTransaction.related_order_id == return_id,
    ).delete(synchronize_session=False)
    db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == return_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
