"""生产管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

BOM / 生产工单 / 生产计划 / MRP / 领料 / 退料 / 成品入库 / 委外加工。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.bom import BillOfMaterial
from app.models.finished_goods import FINISHED_GOODS_STATUS, FinishedGoodsReceipt, FinishedGoodsReceiptItem
from app.models.material_issue import MATERIAL_ISSUE_STATUS, MaterialIssue, MaterialIssueItem
from app.models.material_return import MATERIAL_RETURN_STATUS, MaterialReturn, MaterialReturnItem
from app.models.outsourcing import OUTSOURCING_STATUS, OutsourcingItem, OutsourcingOrder
from app.models.product import Product
from app.models.production import ProductionOrder
from app.models.production_plan import PLAN_TYPES, PRODUCTION_PLAN_STATUS, ProductionPlan, ProductionPlanItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.schemas import (
    BillOfMaterialCreate,
    BillOfMaterialRead,
    FinishedGoodsCreate,
    FinishedGoodsRead,
    MaterialIssueCreate,
    MaterialIssueRead,
    MaterialReturnCreate,
    MaterialReturnRead,
    OutsourcingCreate,
    OutsourcingRead,
    ProductionOrderCreate,
    ProductionOrderRead,
    ProductionPlanCreate,
    ProductionPlanRead,
)
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _apply_stock,
    _bom_children_map,
    _finished_goods_items,
    _material_issue_items,
    _material_return_items,
    _next_doc_no,
    _on_hand_by_product,
    _outsourcing_items,
    _paginate,
    _production_plan_items,
    _resolve_cost_price,
    _resolve_item_snapshot,
    _resolve_warehouse_id,
    _revert_finance,
    _revert_stock,
    _write_finance,
)

router = APIRouter(prefix="", tags=["erp"])




def _serialize_bom_node(node: BillOfMaterial) -> dict[str, object]:
    return {
        "id": node.id,
        "product_id": node.product_id,
        "component_product_id": node.component_product_id,
        "parent_id": node.parent_id,
        "name": node.name or f"BOM-{node.id}",
        "code": node.code,
        "quantity": node.quantity,
        "unit_cost": round(float(node.unit_cost or 0.0), 2),
        "bom_type": node.bom_type or "component",
        "level": node.level,
        "description": node.description or node.note,
        "children": [
            _serialize_bom_node(child)
            for child in sorted(node.children, key=lambda item: (item.level, item.id))
        ],
    }



@router.get("/production-boms/tree")
def list_bom_tree(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    roots = db.query(BillOfMaterial).filter(BillOfMaterial.parent_id.is_(None)).order_by(BillOfMaterial.level, BillOfMaterial.id).all()
    return [_serialize_bom_node(item) for item in roots]



@router.get("/production-boms")
def list_bom_items(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[BillOfMaterialRead]:
    items = _paginate(db.query(BillOfMaterial).order_by(BillOfMaterial.id.desc()), skip, limit).all()
    return items



@router.post("/production-boms", response_model=BillOfMaterialRead, status_code=status.HTTP_201_CREATED)
def create_bom_item(payload: BillOfMaterialCreate, db: Session = Depends(get_db)) -> BillOfMaterial:
    payload_data = payload.model_dump(exclude_none=True)
    if payload.parent_id is not None:
        parent = db.query(BillOfMaterial).filter(BillOfMaterial.id == payload.parent_id).first()
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent BOM node not found")
        payload_data["level"] = parent.level + 1
    else:
        payload_data.setdefault("level", payload.level)
    payload_data.setdefault("name", f"BOM-{payload.product_id}-{payload.component_product_id}")
    payload_data.setdefault("code", f"BOM-{payload.product_id}-{payload.component_product_id}")
    payload_data.setdefault("bom_type", "component")
    item = BillOfMaterial(**payload_data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.delete("/production-boms/{bom_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_production_bom(bom_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.query(BillOfMaterial).filter(BillOfMaterial.id == bom_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="BOM node not found")
    # BOM 是树形结构（parent_id 自引用），删除时连同子孙节点一起删，
    # 先自底向上收集全部子节点 id，避免外键约束冲突
    to_delete = {bom_id}
    while True:
        children = {
            row.id
            for row in db.query(BillOfMaterial.id)
            .filter(BillOfMaterial.parent_id.in_(to_delete))
            .all()
        }
        new_children = children - to_delete
        if not new_children:
            break
        to_delete |= new_children
    db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(to_delete)).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/production-orders")
def list_production_orders(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[ProductionOrderRead]:
    items = _paginate(db.query(ProductionOrder).order_by(ProductionOrder.id.desc()), skip, limit).all()
    return items



@router.post("/production-orders", response_model=ProductionOrderRead, status_code=status.HTTP_201_CREATED)
def create_production_order(payload: ProductionOrderCreate, db: Session = Depends(get_db)) -> ProductionOrder:
    existing = db.query(ProductionOrder).filter(ProductionOrder.order_no == payload.order_no).first()
    if existing:
        raise HTTPException(status_code=400, detail="Production order number already exists")
    item = ProductionOrder(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



def _production_plan_payload(item: ProductionPlan, rows: list[ProductionPlanItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "plan_no": item.plan_no,
        "plan_type": item.plan_type,
        "warehouse_id": item.warehouse_id,
        "plan_date": item.plan_date,
        "delivery_date": item.delivery_date,
        "handler": item.handler,
        "workshop": item.workshop,
        "source_order_id": item.source_order_id,
        "source_order_no": item.source_order_no,
        "status": item.status,
        "total_quantity": item.total_quantity,
        "total_amount": item.total_amount,
        "note": item.note,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "production_plan_id": row.production_plan_id,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "bom_id": row.bom_id,
                "note": row.note,
            }
            for row in rows
        ],
    }



def _normalize_plan_type(value: str | None) -> str:
    kind = (value or "").strip() or "self"
    if kind not in PLAN_TYPES:
        raise HTTPException(status_code=400, detail="生产计划类型非法（应为 self 自制 或 outsource 委外）")
    return kind



class _PlanLine:
    """把 PATCH 传来的 dict 明细包装成对象，复用 _resolve_item_snapshot 的快照补齐逻辑。"""

    def __init__(self, data: dict[str, object]) -> None:
        self.product_id = data.get("product_id")
        self.product_name = data.get("product_name")
        self.standards = data.get("standards")
        self.unit = data.get("unit")



@router.get("/production-plans/meta")
def production_plan_meta() -> dict[str, object]:
    """生产计划页字典：计划类型 + 状态。"""
    return {
        "plan_types": [
            {"code": code, "label": spec["label"]} for code, spec in PLAN_TYPES.items()
        ],
        "statuses": [
            {"code": code, "label": label} for code, label in PRODUCTION_PLAN_STATUS.items()
        ],
    }



@router.get("/production-plans")
def list_production_plans(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    plan_type: str | None = Query(None),
    warehouse_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(ProductionPlan).order_by(ProductionPlan.id.desc())
    if status_value:
        query = query.filter(ProductionPlan.status == status_value)
    if plan_type:
        query = query.filter(ProductionPlan.plan_type == plan_type)
    if warehouse_id:
        query = query.filter(ProductionPlan.warehouse_id == warehouse_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                ProductionPlan.plan_no.ilike(like),
                ProductionPlan.handler.ilike(like),
                ProductionPlan.workshop.ilike(like),
                ProductionPlan.source_order_no.ilike(like),
                ProductionPlan.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_production_plan_payload(item, _production_plan_items(db, item.id)) for item in items]



@router.get("/production-plans/{plan_id}", response_model=ProductionPlanRead)
def get_production_plan(plan_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    return _production_plan_payload(item, _production_plan_items(db, item.id))



@router.post(
    "/production-plans",
    response_model=ProductionPlanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_production_plan(
    payload: ProductionPlanCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    plan_type = _normalize_plan_type(payload.plan_type)

    if payload.warehouse_id:
        if db.get(Warehouse, int(payload.warehouse_id)) is None:
            raise HTTPException(status_code=404, detail="生产仓库不存在")

    if payload.status and payload.status not in PRODUCTION_PLAN_STATUS:
        raise HTTPException(status_code=400, detail="生产计划状态非法")

    prefix = PLAN_TYPES[plan_type]["prefix"]
    plan_no = (payload.plan_no or "").strip() or _next_doc_no(
        db, ProductionPlan, prefix, field="plan_no"
    )
    if db.query(ProductionPlan).filter(ProductionPlan.plan_no == plan_no).first():
        raise HTTPException(status_code=400, detail="生产计划单号已存在")

    item = ProductionPlan(
        plan_no=plan_no,
        plan_type=plan_type,
        warehouse_id=int(payload.warehouse_id) if payload.warehouse_id else None,
        plan_date=payload.plan_date or datetime.now().strftime("%Y-%m-%d"),
        delivery_date=payload.delivery_date,
        handler=payload.handler,
        workshop=payload.workshop,
        source_order_id=payload.source_order_id,
        source_order_no=payload.source_order_no,
        status=payload.status or "planned",
        note=payload.note,
        total_quantity=0.0,
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total_qty = 0.0
    total_amount = 0.0
    rows: list[ProductionPlanItem] = []
    for line in payload.items:
        name, standards, unit = _resolve_item_snapshot(db, line)
        quantity = float(line.quantity or 0.0)
        unit_price = _resolve_cost_price(db, line.product_id, line.unit_price)
        row = ProductionPlanItem(
            production_plan_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            bom_id=line.bom_id,
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
    # 生产计划是前置单据：不写库存、不写财务
    return _production_plan_payload(item, rows)



@router.patch("/production-plans/{plan_id}", response_model=ProductionPlanRead)
def update_production_plan(
    plan_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")

    for field in ("plan_date", "delivery_date", "handler", "workshop", "source_order_no", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="生产仓库不存在")
        item.warehouse_id = new_wh
    if payload.get("source_order_id") not in (None, ""):
        item.source_order_id = int(payload["source_order_id"])

    if payload.get("plan_type") not in (None, ""):
        item.plan_type = _normalize_plan_type(str(payload["plan_type"]))

    if payload.get("status"):
        if str(payload["status"]) not in PRODUCTION_PLAN_STATUS:
            raise HTTPException(status_code=400, detail="生产计划状态非法")
        item.status = str(payload["status"])

    rows = _production_plan_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(ProductionPlanItem).filter(
            ProductionPlanItem.production_plan_id == item.id
        ).delete(synchronize_session=False)
        rows = []
        total_qty = 0.0
        total_amount = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            name, standards, unit = _resolve_item_snapshot(db, _PlanLine(line_data))
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
            row = ProductionPlanItem(
                production_plan_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=name,
                standards=standards,
                unit=unit,
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                bom_id=line_data.get("bom_id"),
                note=line_data.get("note"),
            )
            total_qty += quantity
            total_amount += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_quantity = round(total_qty, 2)
        item.total_amount = round(total_amount, 2)

    db.commit()
    db.refresh(item)
    return _production_plan_payload(item, rows)



@router.patch("/production-plans/{plan_id}/status", response_model=ProductionPlanRead)
def update_production_plan_status(
    plan_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in PRODUCTION_PLAN_STATUS:
        raise HTTPException(status_code=400, detail="生产计划状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _production_plan_payload(item, _production_plan_items(db, item.id))



@router.delete("/production-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_production_plan(plan_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    # 计划是链路起点：已被下游单据引用时先拦一道，避免把上游删了下游悬空
    refs = []
    if db.query(MaterialIssue).filter(MaterialIssue.plan_id == plan_id).first():
        refs.append("生产领料单")
    if db.query(MaterialReturn).filter(MaterialReturn.plan_id == plan_id).first():
        refs.append("生产退料单")
    if db.query(FinishedGoodsReceipt).filter(FinishedGoodsReceipt.plan_id == plan_id).first():
        refs.append("成品入库单")
    if refs:
        raise HTTPException(
            status_code=409,
            detail=f"该生产计划已被{'、'.join(refs)}引用，请先删除下游单据再删计划",
        )
    # 生产计划没写库存、没写财务，删单只需清掉自身与明细
    db.query(ProductionPlanItem).filter(
        ProductionPlanItem.production_plan_id == plan_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _mrp_explode(
    db: Session,
    demands: list[tuple[int, float]],
    warehouse_id: int | None = None,
) -> dict[str, object]:
    """按 BOM 展开物料需求，返回分层结果 + 缺料汇总。"""
    children = _bom_children_map(db)
    products = {p.id: p for p in db.query(Product).all()}
    warehouse = db.get(Warehouse, warehouse_id) if warehouse_id else None

    gross: dict[int, float] = {}
    level_of: dict[int, int] = {}
    top_ids: list[int] = []

    def walk(pid: int, qty: float, level: int) -> None:
        if level > 12 or qty <= 0:
            return
        gross[pid] = gross.get(pid, 0.0) + qty
        if pid not in level_of or level < level_of[pid]:
            level_of[pid] = level
        if level == 0:
            top_ids.append(pid)
        for comp, per in children.get(pid, []):
            walk(comp, qty * per, level + 1)

    for pid, qty in demands:
        if pid is None:
            continue
        walk(int(pid), float(qty or 0.0), 0)

    on_hand = _on_hand_by_product(db, warehouse_id)
    top_set = set(top_ids)

    rows: list[dict[str, object]] = []
    for pid, gross_qty in gross.items():
        product = products.get(pid)
        is_product = pid in top_set and level_of.get(pid, 0) == 0
        available = float(on_hand.get(pid, 0))
        if is_product:
            # 顶层成品是要被"生产出来"的产出，不做缺料判定
            net = 0.0
            status = "product"
        else:
            net = max(0.0, float(gross_qty) - available)
            if net <= 0:
                status = "sufficient"
            elif available > 0:
                status = "partial"
            else:
                status = "shortage"
        price = float(getattr(product, "purchase_price", 0.0) or 0.0)
        rows.append(
            {
                "level": level_of.get(pid, 0),
                "product_id": pid,
                "product_name": getattr(product, "name", None) or f"商品-{pid}",
                "sku": getattr(product, "sku", None),
                "standards": getattr(product, "standards", None),
                "unit": getattr(product, "unit", None),
                "gross_quantity": round(float(gross_qty), 4),
                "on_hand": int(available),
                "net_quantity": round(net, 4),
                "unit_price": round(price, 2),
                "amount": round(net * price, 2),
                "status": status,
                "is_product": is_product,
            }
        )
    rows.sort(key=lambda r: (int(r["level"]), int(r["product_id"])))

    materials = [r for r in rows if not r["is_product"]]
    shortage = [r for r in materials if float(r["net_quantity"]) > 0]
    levels = (max(level_of.values()) + 1) if level_of else 0
    return {
        "warehouse_id": warehouse_id,
        "warehouse_name": getattr(warehouse, "name", None) if warehouse else None,
        "demands": [
            {
                "product_id": pid,
                "product_name": getattr(products.get(pid), "name", None) or f"商品-{pid}",
                "quantity": round(float(qty), 4),
            }
            for pid, qty in demands
            if pid is not None
        ],
        "levels": levels,
        "bom_ready": bool(children),
        "rows": rows,
        "materials": materials,
        "shortages": shortage,
        "summary": {
            "demand_lines": len([d for d in demands if d[0] is not None]),
            "product_lines": len(rows) - len(materials),
            "material_lines": len(materials),
            "shortage_lines": len(shortage),
            "shortage_quantity": round(sum(float(r["net_quantity"]) for r in shortage), 4),
            "shortage_amount": round(sum(float(r["amount"]) for r in shortage), 2),
        },
    }



def _parse_mrp_demands(payload: dict[str, object] | None) -> list[tuple[int, float]]:
    """把请求体里的明细统一解析成 [(product_id, quantity)]。"""
    demands: list[tuple[int, float]] = []
    data = payload or {}
    items = data.get("items")
    if isinstance(items, list):
        for line in items:
            line_data = line if isinstance(line, dict) else {}
            pid = line_data.get("product_id")
            if pid in (None, ""):
                continue
            demands.append((int(pid), float(line_data.get("quantity") or 0.0)))
    if not demands and data.get("product_id") not in (None, ""):
        demands.append((int(data["product_id"]), float(data.get("quantity") or 0.0)))
    return demands



@router.get("/mrp/requirements")
def mrp_requirements(
    product_id: int = Query(...),
    quantity: float = Query(1),
    warehouse_id: int | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """单成品物料需求试算。"""
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="成品不存在")
    if warehouse_id and db.get(Warehouse, warehouse_id) is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return _mrp_explode(db, [(product_id, quantity)], warehouse_id)



@router.post("/mrp/run")
def mrp_run(payload: dict[str, object] | None = None, db: Session = Depends(get_db)) -> dict[str, object]:
    """多成品批量 MRP 运算（body: {"items":[{"product_id":1,"quantity":10}], "warehouse_id":2}）。"""
    data = payload or {}
    demands = _parse_mrp_demands(data)
    if not demands:
        raise HTTPException(status_code=400, detail="至少需要一个物料需求（product_id + quantity）")
    warehouse_id = data.get("warehouse_id")
    warehouse_id = int(warehouse_id) if warehouse_id not in (None, "") else None
    if warehouse_id and db.get(Warehouse, warehouse_id) is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return _mrp_explode(db, demands, warehouse_id)



@router.get("/production-plans/{plan_id}/mrp")
def production_plan_mrp(plan_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """按生产计划整单运算：把计划的每个成品明细当作顶层需求。"""
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    rows = _production_plan_items(db, item.id)
    demands = [(row.product_id, float(row.quantity or 0.0)) for row in rows if row.product_id]
    if not demands:
        raise HTTPException(status_code=400, detail="该生产计划没有可运算的成品明细")
    result = _mrp_explode(db, demands, item.warehouse_id)
    result["plan_no"] = item.plan_no
    result["plan_type"] = item.plan_type
    return result



def _material_issue_payload(item: MaterialIssue, rows: list[MaterialIssueItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "issue_no": item.issue_no,
        "plan_id": item.plan_id,
        "plan_no": item.plan_no,
        "warehouse_id": item.warehouse_id,
        "issue_date": item.issue_date,
        "workshop": item.workshop,
        "handler": item.handler,
        "note": item.note,
        "status": item.status,
        "total_quantity": item.total_quantity,
        "total_amount": item.total_amount,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "material_issue_id": row.material_issue_id,
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



def _material_issue_apply_stock(
    db: Session, item: MaterialIssue, rows: list[MaterialIssueItem]
) -> None:
    """领料：原材料出库（outbound）。仓库为空时回退默认仓库。"""
    warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    for row in rows:
        qty = abs(float(row.quantity or 0.0))
        if qty == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="production_issue",
            related_order_id=item.id,
            doc_no=item.issue_no,
            note=f"生产领料 {item.issue_no}",
        )



def _line_to_dict(line) -> dict[str, object]:
    """明细行（Pydantic 对象或 dict）统一成 dict，供生产类单据复用。"""
    if isinstance(line, dict):
        return line
    if hasattr(line, "model_dump"):
        return line.model_dump()
    return {}



def _material_issue_lines(db: Session, raw_items: list) -> tuple[list[MaterialIssueItem], float, float]:
    """把明细请求（Pydantic / dict 列表）转成明细行，并算合计。"""
    rows: list[MaterialIssueItem] = []
    total_qty = 0.0
    total_amount = 0.0
    for line in raw_items:
        line_data = _line_to_dict(line)
        product_id = line_data.get("product_id")
        name, standards, unit = _resolve_item_snapshot(db, _PlanLine(line_data))
        quantity = abs(float(line_data.get("quantity") or 0.0))
        unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
        row = MaterialIssueItem(
            product_id=int(product_id) if product_id else None,
            product_name=name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line_data.get("note"),
        )
        total_qty += quantity
        total_amount += row.amount
        rows.append(row)
    return rows, round(total_qty, 2), round(total_amount, 2)



@router.get("/material-issues/meta")
def material_issue_meta() -> dict[str, object]:
    """生产领料页字典：状态。"""
    return {
        "statuses": [
            {"code": code, "label": label} for code, label in MATERIAL_ISSUE_STATUS.items()
        ]
    }



@router.get("/material-issues/suggestion")
def material_issue_suggestion(
    plan_id: int = Query(...), db: Session = Depends(get_db)
) -> dict[str, object]:
    """按生产计划带出领料底稿：BOM 展开后的物料需求（复用 MRP 引擎）。"""
    plan = db.get(ProductionPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    plan_rows = _production_plan_items(db, plan.id)
    demands = [(row.product_id, float(row.quantity or 0.0)) for row in plan_rows if row.product_id]
    if not demands:
        raise HTTPException(status_code=400, detail="该生产计划没有可展开的成品明细")
    result = _mrp_explode(db, demands, plan.warehouse_id)
    items = [
        {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "standards": row["standards"],
            "unit": row["unit"],
            # 领料默认按"毛需求"（生产这个量一共要用多少），人可再改
            "quantity": row["gross_quantity"],
            "unit_price": row["unit_price"],
            "on_hand": row["on_hand"],
            "net_quantity": row["net_quantity"],
        }
        for row in result["materials"]
    ]
    return {
        "plan_id": plan.id,
        "plan_no": plan.plan_no,
        "warehouse_id": plan.warehouse_id,
        "count": len(items),
        "items": items,
        "summary": result["summary"],
        "bom_ready": result["bom_ready"],
    }



@router.get("/material-issues")
def list_material_issues(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    plan_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(MaterialIssue).order_by(MaterialIssue.id.desc())
    if status_value:
        query = query.filter(MaterialIssue.status == status_value)
    if warehouse_id:
        query = query.filter(MaterialIssue.warehouse_id == warehouse_id)
    if plan_id:
        query = query.filter(MaterialIssue.plan_id == plan_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                MaterialIssue.issue_no.ilike(like),
                MaterialIssue.plan_no.ilike(like),
                MaterialIssue.workshop.ilike(like),
                MaterialIssue.handler.ilike(like),
                MaterialIssue.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_material_issue_payload(item, _material_issue_items(db, item.id)) for item in items]



@router.get("/material-issues/{issue_id}", response_model=MaterialIssueRead)
def get_material_issue(issue_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(MaterialIssue, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    return _material_issue_payload(item, _material_issue_items(db, item.id))



@router.post(
    "/material-issues",
    response_model=MaterialIssueRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material_issue(
    payload: MaterialIssueCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    if payload.warehouse_id and db.get(Warehouse, int(payload.warehouse_id)) is None:
        raise HTTPException(status_code=404, detail="领料仓库不存在")
    if payload.plan_id and db.get(ProductionPlan, int(payload.plan_id)) is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if payload.status and payload.status not in MATERIAL_ISSUE_STATUS:
        raise HTTPException(status_code=400, detail="生产领料单状态非法")

    issue_no = (payload.issue_no or "").strip() or _next_doc_no(
        db, MaterialIssue, "SCLL", field="issue_no"
    )
    if db.query(MaterialIssue).filter(MaterialIssue.issue_no == issue_no).first():
        raise HTTPException(status_code=400, detail="生产领料单号已存在")

    plan_no = payload.plan_no
    if payload.plan_id and not plan_no:
        plan = db.get(ProductionPlan, int(payload.plan_id))
        plan_no = plan.plan_no if plan else None

    item = MaterialIssue(
        issue_no=issue_no,
        plan_id=int(payload.plan_id) if payload.plan_id else None,
        plan_no=plan_no,
        warehouse_id=int(payload.warehouse_id) if payload.warehouse_id else None,
        issue_date=payload.issue_date or datetime.now().strftime("%Y-%m-%d"),
        workshop=payload.workshop,
        handler=payload.handler,
        note=payload.note,
        status=payload.status or "submitted",
        total_quantity=0.0,
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    rows, total_qty, total_amount = _material_issue_lines(db, payload.items)
    for row in rows:
        row.material_issue_id = item.id
    db.add_all(rows)
    item.total_quantity = total_qty
    item.total_amount = total_amount
    db.commit()
    db.refresh(item)

    # 库存联动：领料 = 原材料出库（纯库存单据，不写财务）
    _material_issue_apply_stock(db, item, rows)
    db.commit()
    db.refresh(item)
    return _material_issue_payload(item, rows)



@router.patch("/material-issues/{issue_id}", response_model=MaterialIssueRead)
def update_material_issue(
    issue_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(MaterialIssue, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")

    stock_touched = False

    for field in ("issue_date", "workshop", "handler", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="领料仓库不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    if payload.get("plan_id") not in (None, ""):
        plan = db.get(ProductionPlan, int(payload["plan_id"]))
        if plan is None:
            raise HTTPException(status_code=404, detail="生产计划不存在")
        item.plan_id = plan.id
        item.plan_no = plan.plan_no

    if payload.get("status"):
        if str(payload["status"]) not in MATERIAL_ISSUE_STATUS:
            raise HTTPException(status_code=400, detail="生产领料单状态非法")
        item.status = str(payload["status"])

    rows = _material_issue_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(MaterialIssueItem).filter(
            MaterialIssueItem.material_issue_id == item.id
        ).delete(synchronize_session=False)
        rows, total_qty, total_amount = _material_issue_lines(db, payload["items"])
        for row in rows:
            row.material_issue_id = item.id
        db.add_all(rows)
        item.total_quantity = total_qty
        item.total_amount = total_amount
        stock_touched = True

    if stock_touched:
        # 明细 / 仓库任一变化都要整体重放，否则残留按旧内容扣过的库存
        _revert_stock(db, "production_issue", item.id)
        _material_issue_apply_stock(db, item, rows)

    db.commit()
    db.refresh(item)
    return _material_issue_payload(item, rows)



@router.patch("/material-issues/{issue_id}/status", response_model=MaterialIssueRead)
def update_material_issue_status(
    issue_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(MaterialIssue, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in MATERIAL_ISSUE_STATUS:
        raise HTTPException(status_code=400, detail="生产领料单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _material_issue_payload(item, _material_issue_items(db, item.id))



@router.delete("/material-issues/{issue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material_issue(issue_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(MaterialIssue, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    # 删单回滚：冲销该单发出的全部 outbound 流水（材料自动回到仓库）
    _revert_stock(db, "production_issue", issue_id)
    db.query(MaterialIssueItem).filter(
        MaterialIssueItem.material_issue_id == issue_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _material_return_payload(item: MaterialReturn, rows: list[MaterialReturnItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "return_no": item.return_no,
        "plan_id": item.plan_id,
        "plan_no": item.plan_no,
        "warehouse_id": item.warehouse_id,
        "return_date": item.return_date,
        "workshop": item.workshop,
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
                "material_return_id": row.material_return_id,
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



def _material_return_apply_stock(
    db: Session, item: MaterialReturn, rows: list[MaterialReturnItem]
) -> None:
    """退料：原材料入库（inbound），与领料方向相反。"""
    warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    for row in rows:
        qty = abs(float(row.quantity or 0.0))
        if qty == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="production_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            note=f"生产退料 {item.return_no}",
        )



def _material_return_lines(db: Session, raw_items: list) -> tuple[list[MaterialReturnItem], float, float]:
    rows: list[MaterialReturnItem] = []
    total_qty = 0.0
    total_amount = 0.0
    for line in raw_items:
        line_data = _line_to_dict(line)
        product_id = line_data.get("product_id")
        name, standards, unit = _resolve_item_snapshot(db, _PlanLine(line_data))
        quantity = abs(float(line_data.get("quantity") or 0.0))
        unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
        row = MaterialReturnItem(
            product_id=int(product_id) if product_id else None,
            product_name=name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line_data.get("note"),
        )
        total_qty += quantity
        total_amount += row.amount
        rows.append(row)
    return rows, round(total_qty, 2), round(total_amount, 2)



@router.get("/material-returns/meta")
def material_return_meta() -> dict[str, object]:
    """生产退料页字典：状态。"""
    return {
        "statuses": [
            {"code": code, "label": label} for code, label in MATERIAL_RETURN_STATUS.items()
        ]
    }



@router.get("/material-returns")
def list_material_returns(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    plan_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(MaterialReturn).order_by(MaterialReturn.id.desc())
    if status_value:
        query = query.filter(MaterialReturn.status == status_value)
    if warehouse_id:
        query = query.filter(MaterialReturn.warehouse_id == warehouse_id)
    if plan_id:
        query = query.filter(MaterialReturn.plan_id == plan_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                MaterialReturn.return_no.ilike(like),
                MaterialReturn.plan_no.ilike(like),
                MaterialReturn.workshop.ilike(like),
                MaterialReturn.handler.ilike(like),
                MaterialReturn.reason.ilike(like),
                MaterialReturn.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_material_return_payload(item, _material_return_items(db, item.id)) for item in items]



@router.get("/material-returns/{return_id}", response_model=MaterialReturnRead)
def get_material_return(return_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(MaterialReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产退料单不存在")
    return _material_return_payload(item, _material_return_items(db, item.id))



@router.post(
    "/material-returns",
    response_model=MaterialReturnRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material_return(
    payload: MaterialReturnCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    if payload.warehouse_id and db.get(Warehouse, int(payload.warehouse_id)) is None:
        raise HTTPException(status_code=404, detail="退料仓库不存在")
    if payload.plan_id and db.get(ProductionPlan, int(payload.plan_id)) is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if payload.status and payload.status not in MATERIAL_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="生产退料单状态非法")

    return_no = (payload.return_no or "").strip() or _next_doc_no(
        db, MaterialReturn, "SCTL", field="return_no"
    )
    if db.query(MaterialReturn).filter(MaterialReturn.return_no == return_no).first():
        raise HTTPException(status_code=400, detail="生产退料单号已存在")

    plan_no = payload.plan_no
    if payload.plan_id and not plan_no:
        plan = db.get(ProductionPlan, int(payload.plan_id))
        plan_no = plan.plan_no if plan else None

    item = MaterialReturn(
        return_no=return_no,
        plan_id=int(payload.plan_id) if payload.plan_id else None,
        plan_no=plan_no,
        warehouse_id=int(payload.warehouse_id) if payload.warehouse_id else None,
        return_date=payload.return_date or datetime.now().strftime("%Y-%m-%d"),
        workshop=payload.workshop,
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

    rows, total_qty, total_amount = _material_return_lines(db, payload.items)
    for row in rows:
        row.material_return_id = item.id
    db.add_all(rows)
    item.total_quantity = total_qty
    item.total_amount = total_amount
    db.commit()
    db.refresh(item)

    # 库存联动：退料 = 原材料入库（纯库存单据，不写财务）
    _material_return_apply_stock(db, item, rows)
    db.commit()
    db.refresh(item)
    return _material_return_payload(item, rows)



@router.patch("/material-returns/{return_id}", response_model=MaterialReturnRead)
def update_material_return(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(MaterialReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产退料单不存在")

    stock_touched = False

    for field in ("return_date", "workshop", "handler", "reason", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="退料仓库不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    if payload.get("plan_id") not in (None, ""):
        plan = db.get(ProductionPlan, int(payload["plan_id"]))
        if plan is None:
            raise HTTPException(status_code=404, detail="生产计划不存在")
        item.plan_id = plan.id
        item.plan_no = plan.plan_no

    if payload.get("status"):
        if str(payload["status"]) not in MATERIAL_RETURN_STATUS:
            raise HTTPException(status_code=400, detail="生产退料单状态非法")
        item.status = str(payload["status"])

    rows = _material_return_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(MaterialReturnItem).filter(
            MaterialReturnItem.material_return_id == item.id
        ).delete(synchronize_session=False)
        rows, total_qty, total_amount = _material_return_lines(db, payload["items"])
        for row in rows:
            row.material_return_id = item.id
        db.add_all(rows)
        item.total_quantity = total_qty
        item.total_amount = total_amount
        stock_touched = True

    if stock_touched:
        _revert_stock(db, "production_return", item.id)
        _material_return_apply_stock(db, item, rows)

    db.commit()
    db.refresh(item)
    return _material_return_payload(item, rows)



@router.patch("/material-returns/{return_id}/status", response_model=MaterialReturnRead)
def update_material_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(MaterialReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产退料单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in MATERIAL_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="生产退料单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _material_return_payload(item, _material_return_items(db, item.id))



@router.delete("/material-returns/{return_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material_return(return_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(MaterialReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产退料单不存在")
    _revert_stock(db, "production_return", return_id)
    db.query(MaterialReturnItem).filter(
        MaterialReturnItem.material_return_id == return_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# ============================================================================
# 第 3 批 · 生产类之五：成品入库（生产链路的收口环节）
#
# 成品入库 = 车间把生产好的成品交回仓库：成品现存量**增加**（inbound）。
# 与领料/退料不同，这一步**同时写财务成本流水**（transaction_type="cost"、
# direction="in"），因为它是"在制品 → 产成品"的价值结转；用 cost 类型，
# 不影响应收应付余额，只进成本口径。
# ============================================================================


def _production_doc_lines(db: Session, raw_items: list, model_cls) -> tuple[list, float, float]:
    """生产类单据明细（Pydantic / dict 列表）→ 明细行 + 合计。成品入库复用。"""
    rows: list = []
    total_qty = 0.0
    total_amount = 0.0
    for line in raw_items:
        line_data = _line_to_dict(line)
        product_id = line_data.get("product_id")
        name, standards, unit = _resolve_item_snapshot(db, _PlanLine(line_data))
        quantity = abs(float(line_data.get("quantity") or 0.0))
        unit_price = _resolve_cost_price(db, product_id, line_data.get("unit_price"))
        row = model_cls(
            product_id=int(product_id) if product_id else None,
            product_name=name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line_data.get("note"),
        )
        total_qty += quantity
        total_amount += row.amount
        rows.append(row)
    return rows, round(total_qty, 2), round(total_amount, 2)



def _finished_goods_payload(
    item: FinishedGoodsReceipt, rows: list[FinishedGoodsReceiptItem]
) -> dict[str, object]:
    return {
        "id": item.id,
        "receipt_no": item.receipt_no,
        "plan_id": item.plan_id,
        "plan_no": item.plan_no,
        "warehouse_id": item.warehouse_id,
        "receipt_date": item.receipt_date,
        "workshop": item.workshop,
        "handler": item.handler,
        "note": item.note,
        "status": item.status,
        "total_quantity": item.total_quantity,
        "total_amount": item.total_amount,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "finished_goods_receipt_id": row.finished_goods_receipt_id,
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



def _finished_goods_apply_stock(
    db: Session, item: FinishedGoodsReceipt, rows: list[FinishedGoodsReceiptItem]
) -> None:
    """成品入库：成品现存量增加（inbound）。"""
    warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    for row in rows:
        qty = abs(float(row.quantity or 0.0))
        if qty == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="production_in",
            related_order_id=item.id,
            doc_no=item.receipt_no,
            note=f"成品入库 {item.receipt_no}",
        )



def _finished_goods_write_finance(db: Session, item: FinishedGoodsReceipt) -> None:
    """成品入库写成本流水（在制品 → 产成品的价值结转）。"""
    amount = round(float(item.total_amount or 0.0), 2)
    if amount <= 0:
        return
    _write_finance(
        db,
        transaction_type="cost",
        direction="in",
        amount=amount,
        related_type="production_in",
        related_order_id=item.id,
        doc_no=item.receipt_no,
        warehouse_id=item.warehouse_id,
        occurred_at=item.receipt_date,
        note=f"成品入库单 {item.receipt_no} 结转生产成本",
    )



@router.get("/finished-goods/meta")
def finished_goods_meta() -> dict[str, object]:
    """成品入库页字典：状态。"""
    return {
        "statuses": [
            {"code": code, "label": label} for code, label in FINISHED_GOODS_STATUS.items()
        ]
    }



@router.get("/finished-goods")
def list_finished_goods(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    warehouse_id: int | None = Query(None),
    plan_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(FinishedGoodsReceipt).order_by(FinishedGoodsReceipt.id.desc())
    if status_value:
        query = query.filter(FinishedGoodsReceipt.status == status_value)
    if warehouse_id:
        query = query.filter(FinishedGoodsReceipt.warehouse_id == warehouse_id)
    if plan_id:
        query = query.filter(FinishedGoodsReceipt.plan_id == plan_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                FinishedGoodsReceipt.receipt_no.ilike(like),
                FinishedGoodsReceipt.plan_no.ilike(like),
                FinishedGoodsReceipt.workshop.ilike(like),
                FinishedGoodsReceipt.handler.ilike(like),
                FinishedGoodsReceipt.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_finished_goods_payload(item, _finished_goods_items(db, item.id)) for item in items]



@router.get("/finished-goods/{receipt_id}", response_model=FinishedGoodsRead)
def get_finished_goods(receipt_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(FinishedGoodsReceipt, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="成品入库单不存在")
    return _finished_goods_payload(item, _finished_goods_items(db, item.id))



@router.post(
    "/finished-goods",
    response_model=FinishedGoodsRead,
    status_code=status.HTTP_201_CREATED,
)
def create_finished_goods(
    payload: FinishedGoodsCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    if payload.warehouse_id and db.get(Warehouse, int(payload.warehouse_id)) is None:
        raise HTTPException(status_code=404, detail="成品入库仓不存在")
    if payload.plan_id and db.get(ProductionPlan, int(payload.plan_id)) is None:
        raise HTTPException(status_code=404, detail="生产计划不存在")
    if payload.status and payload.status not in FINISHED_GOODS_STATUS:
        raise HTTPException(status_code=400, detail="成品入库单状态非法")

    receipt_no = (payload.receipt_no or "").strip() or _next_doc_no(
        db, FinishedGoodsReceipt, "CPRK", field="receipt_no"
    )
    if db.query(FinishedGoodsReceipt).filter(FinishedGoodsReceipt.receipt_no == receipt_no).first():
        raise HTTPException(status_code=400, detail="成品入库单号已存在")

    plan_no = payload.plan_no
    if payload.plan_id and not plan_no:
        plan = db.get(ProductionPlan, int(payload.plan_id))
        plan_no = plan.plan_no if plan else None

    item = FinishedGoodsReceipt(
        receipt_no=receipt_no,
        plan_id=int(payload.plan_id) if payload.plan_id else None,
        plan_no=plan_no,
        warehouse_id=int(payload.warehouse_id) if payload.warehouse_id else None,
        receipt_date=payload.receipt_date or datetime.now().strftime("%Y-%m-%d"),
        workshop=payload.workshop,
        handler=payload.handler,
        note=payload.note,
        status=payload.status or "submitted",
        total_quantity=0.0,
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    rows, total_qty, total_amount = _production_doc_lines(db, payload.items, FinishedGoodsReceiptItem)
    for row in rows:
        row.finished_goods_receipt_id = item.id
    db.add_all(rows)
    item.total_quantity = total_qty
    item.total_amount = total_amount
    db.commit()
    db.refresh(item)

    # 库存联动（成品入库）+ 财务联动（成本结转）
    _finished_goods_apply_stock(db, item, rows)
    _finished_goods_write_finance(db, item)
    db.commit()
    db.refresh(item)
    return _finished_goods_payload(item, rows)



@router.patch("/finished-goods/{receipt_id}", response_model=FinishedGoodsRead)
def update_finished_goods(
    receipt_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(FinishedGoodsReceipt, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="成品入库单不存在")

    stock_touched = False

    for field in ("receipt_date", "workshop", "handler", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="成品入库仓不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    if payload.get("plan_id") not in (None, ""):
        plan = db.get(ProductionPlan, int(payload["plan_id"]))
        if plan is None:
            raise HTTPException(status_code=404, detail="生产计划不存在")
        item.plan_id = plan.id
        item.plan_no = plan.plan_no

    if payload.get("status"):
        if str(payload["status"]) not in FINISHED_GOODS_STATUS:
            raise HTTPException(status_code=400, detail="成品入库单状态非法")
        item.status = str(payload["status"])

    rows = _finished_goods_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(FinishedGoodsReceiptItem).filter(
            FinishedGoodsReceiptItem.finished_goods_receipt_id == item.id
        ).delete(synchronize_session=False)
        rows, total_qty, total_amount = _production_doc_lines(
            db, payload["items"], FinishedGoodsReceiptItem
        )
        for row in rows:
            row.finished_goods_receipt_id = item.id
        db.add_all(rows)
        item.total_quantity = total_qty
        item.total_amount = total_amount
        stock_touched = True

    if stock_touched:
        _revert_stock(db, "production_in", item.id)
        _finished_goods_apply_stock(db, item, rows)
    # 金额可能变了：财务流水恒按最新内容重放（幂等）
    _revert_finance(db, "production_in", item.id)
    _finished_goods_write_finance(db, item)

    db.commit()
    db.refresh(item)
    return _finished_goods_payload(item, rows)



@router.patch("/finished-goods/{receipt_id}/status", response_model=FinishedGoodsRead)
def update_finished_goods_status(
    receipt_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(FinishedGoodsReceipt, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="成品入库单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in FINISHED_GOODS_STATUS:
        raise HTTPException(status_code=400, detail="成品入库单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _finished_goods_payload(item, _finished_goods_items(db, item.id))



@router.delete("/finished-goods/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finished_goods(receipt_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(FinishedGoodsReceipt, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="成品入库单不存在")
    # 库存与财务一起回滚：成品退回车间、成本流水抹掉
    _revert_stock(db, "production_in", receipt_id)
    _revert_finance(db, "production_in", receipt_id)
    db.query(FinishedGoodsReceiptItem).filter(
        FinishedGoodsReceiptItem.finished_goods_receipt_id == receipt_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _outsourcing_payload(item: OutsourcingOrder, rows: list[OutsourcingItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "order_no": item.order_no,
        "supplier_id": item.supplier_id,
        "warehouse_id": item.warehouse_id,
        "order_date": item.order_date,
        "handler": item.handler,
        "note": item.note,
        "status": item.status,
        "product_id": item.product_id,
        "product_name": item.product_name,
        "standards": item.standards,
        "unit": item.unit,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "process_fee": item.process_fee,
        "total_amount": item.total_amount,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "outsourcing_order_id": row.outsourcing_order_id,
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



def _outsourcing_apply_stock(db: Session, item: OutsourcingOrder, rows: list[OutsourcingItem]) -> None:
    """发料 outbound（材料）+ 收成品 inbound（成品），两类流水共用同一溯源。"""
    warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    for row in rows:
        qty = abs(float(row.quantity or 0.0))
        if qty == 0 or row.product_id is None:
            continue
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="outsourcing",
            related_order_id=item.id,
            doc_no=item.order_no,
            note=f"委外发料 {item.order_no}",
        )
    finished_qty = abs(float(item.quantity or 0.0))
    if item.product_id is not None and finished_qty > 0:
        _apply_stock(
            db,
            product_id=item.product_id,
            warehouse_id=warehouse_id,
            quantity=finished_qty,
            transaction_type="inbound",
            unit_price=item.unit_price,
            related_type="outsourcing",
            related_order_id=item.id,
            doc_no=item.order_no,
            note=f"委外收回 {item.order_no}",
        )



def _outsourcing_write_finance(db: Session, item: OutsourcingOrder) -> None:
    """加工费对外协厂产生应付。"""
    fee = round(float(item.process_fee or 0.0), 2)
    if fee <= 0:
        return
    _write_finance(
        db,
        transaction_type="payable",
        direction="out",
        amount=fee,
        related_type="outsourcing",
        related_order_id=item.id,
        doc_no=item.order_no,
        supplier_id=item.supplier_id,
        warehouse_id=item.warehouse_id,
        occurred_at=item.order_date,
        note=f"委外加工费 {item.order_no}",
    )



@router.get("/outsourcings/meta")
def outsourcing_meta() -> dict[str, object]:
    """委外加工页字典：状态。"""
    return {
        "statuses": [
            {"code": code, "label": label} for code, label in OUTSOURCING_STATUS.items()
        ]
    }



@router.get("/outsourcings")
def list_outsourcings(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(OutsourcingOrder).order_by(OutsourcingOrder.id.desc())
    if status_value:
        query = query.filter(OutsourcingOrder.status == status_value)
    if supplier_id:
        query = query.filter(OutsourcingOrder.supplier_id == supplier_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                OutsourcingOrder.order_no.ilike(like),
                OutsourcingOrder.product_name.ilike(like),
                OutsourcingOrder.handler.ilike(like),
                OutsourcingOrder.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_outsourcing_payload(item, _outsourcing_items(db, item.id)) for item in items]



@router.get("/outsourcings/{order_id}", response_model=OutsourcingRead)
def get_outsourcing(order_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(OutsourcingOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="委外加工单不存在")
    return _outsourcing_payload(item, _outsourcing_items(db, item.id))



@router.post(
    "/outsourcings",
    response_model=OutsourcingRead,
    status_code=status.HTTP_201_CREATED,
)
def create_outsourcing(
    payload: OutsourcingCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    if payload.supplier_id and db.get(Supplier, int(payload.supplier_id)) is None:
        raise HTTPException(status_code=404, detail="外协厂（供应商）不存在")
    if payload.warehouse_id and db.get(Warehouse, int(payload.warehouse_id)) is None:
        raise HTTPException(status_code=404, detail="发料/收料仓库不存在")
    if payload.status and payload.status not in OUTSOURCING_STATUS:
        raise HTTPException(status_code=400, detail="委外加工单状态非法")

    order_no = (payload.order_no or "").strip() or _next_doc_no(
        db, OutsourcingOrder, "WWJG", field="order_no"
    )
    if db.query(OutsourcingOrder).filter(OutsourcingOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="委外加工单号已存在")

    # 加工产出的成品快照
    product_name, standards, unit = _resolve_item_snapshot(db, _PlanLine({
        "product_id": payload.product_id,
        "product_name": payload.product_name,
        "standards": payload.standards,
        "unit": payload.unit,
    }))

    item = OutsourcingOrder(
        order_no=order_no,
        supplier_id=int(payload.supplier_id) if payload.supplier_id else None,
        warehouse_id=int(payload.warehouse_id) if payload.warehouse_id else None,
        order_date=payload.order_date or datetime.now().strftime("%Y-%m-%d"),
        handler=payload.handler,
        note=payload.note,
        status=payload.status or "submitted",
        product_id=int(payload.product_id) if payload.product_id else None,
        product_name=product_name,
        standards=standards,
        unit=unit,
        quantity=abs(float(payload.quantity or 0.0)),
        unit_price=_resolve_cost_price(db, payload.product_id, payload.unit_price),
        process_fee=round(float(payload.process_fee or 0.0), 2),
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    rows, _total_qty, total_amount = _production_doc_lines(db, payload.items, OutsourcingItem)
    for row in rows:
        row.outsourcing_order_id = item.id
    db.add_all(rows)
    item.total_amount = total_amount
    db.commit()
    db.refresh(item)

    # 库存联动（发料 + 收成品）+ 财务联动（加工费应付）
    _outsourcing_apply_stock(db, item, rows)
    _outsourcing_write_finance(db, item)
    db.commit()
    db.refresh(item)
    return _outsourcing_payload(item, rows)



@router.patch("/outsourcings/{order_id}", response_model=OutsourcingRead)
def update_outsourcing(
    order_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(OutsourcingOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="委外加工单不存在")

    stock_touched = False
    finance_touched = False

    for field in ("order_date", "handler", "note"):
        if field in payload:
            setattr(item, field, payload.get(field))

    if "supplier_id" in payload and payload.get("supplier_id") not in ("", None):
        new_sup = int(payload["supplier_id"])
        if db.get(Supplier, new_sup) is None:
            raise HTTPException(status_code=404, detail="外协厂（供应商）不存在")
        item.supplier_id = new_sup
        finance_touched = True

    if "warehouse_id" in payload and payload.get("warehouse_id") not in ("", None):
        new_wh = int(payload["warehouse_id"])
        if db.get(Warehouse, new_wh) is None:
            raise HTTPException(status_code=404, detail="发料/收料仓库不存在")
        item.warehouse_id = new_wh
        stock_touched = True

    if payload.get("process_fee") not in (None, ""):
        item.process_fee = round(float(payload["process_fee"] or 0.0), 2)
        finance_touched = True

    if payload.get("status"):
        if str(payload["status"]) not in OUTSOURCING_STATUS:
            raise HTTPException(status_code=400, detail="委外加工单状态非法")
        item.status = str(payload["status"])

    # 加工产出（成品）改了也要重放库存
    if payload.get("product_id") not in (None, "") or payload.get("quantity") not in (None, ""):
        if payload.get("product_id") not in (None, ""):
            item.product_id = int(payload["product_id"])
        name, standards, unit = _resolve_item_snapshot(db, _PlanLine({
            "product_id": item.product_id,
            "product_name": payload.get("product_name"),
            "standards": payload.get("standards"),
            "unit": payload.get("unit"),
        }))
        item.product_name = name
        item.standards = standards
        item.unit = unit
        if payload.get("quantity") not in (None, ""):
            item.quantity = abs(float(payload["quantity"] or 0.0))
        item.unit_price = _resolve_cost_price(db, item.product_id, payload.get("unit_price", item.unit_price))
        stock_touched = True

    rows = _outsourcing_items(db, item.id)
    if isinstance(payload.get("items"), list):
        db.query(OutsourcingItem).filter(
            OutsourcingItem.outsourcing_order_id == item.id
        ).delete(synchronize_session=False)
        rows, _total_qty, total_amount = _production_doc_lines(db, payload["items"], OutsourcingItem)
        for row in rows:
            row.outsourcing_order_id = item.id
        db.add_all(rows)
        item.total_amount = total_amount
        stock_touched = True

    if stock_touched:
        _revert_stock(db, "outsourcing", item.id)
        _outsourcing_apply_stock(db, item, rows)
    if finance_touched or stock_touched:
        _revert_finance(db, "outsourcing", item.id)
        _outsourcing_write_finance(db, item)

    db.commit()
    db.refresh(item)
    return _outsourcing_payload(item, rows)



@router.patch("/outsourcings/{order_id}/status", response_model=OutsourcingRead)
def update_outsourcing_status(
    order_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(OutsourcingOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="委外加工单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in OUTSOURCING_STATUS:
        raise HTTPException(status_code=400, detail="委外加工单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _outsourcing_payload(item, _outsourcing_items(db, item.id))



@router.delete("/outsourcings/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_outsourcing(order_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(OutsourcingOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="委外加工单不存在")
    # 库存一次性回滚（发料退回 + 收回成品扣回）并冲销加工费应付
    _revert_stock(db, "outsourcing", order_id)
    _revert_finance(db, "outsourcing", order_id)
    db.query(OutsourcingItem).filter(
        OutsourcingItem.outsourcing_order_id == order_id
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
