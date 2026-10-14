"""基础资料 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

商品 / 商品类别 / 客户 / 供应商 / 仓库 / 员工 / 期初建账。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.bom import BillOfMaterial
from app.models.contract import Contract
from app.models.customer import Customer
from app.models.employee import EMPLOYEE_STATUS, Employee, GENDER_OPTIONS
from app.models.finance import FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.organization import Department
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.production import ProductionOrder
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.schemas import (
    CustomerCreate,
    CustomerRead,
    EmployeeCreate,
    EmployeeRead,
    ProductCategoryCreate,
    ProductCategoryNode,
    ProductCategoryRead,
    ProductCategoryUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SupplierCreate,
    SupplierRead,
    WarehouseCreate,
    WarehouseRead,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _net_stock_map,
    _paginate,
    _signed_amount,
    _stock_delta,
)

router = APIRouter(prefix="", tags=["erp"])




# ============================================================================
# 档案删除：引用检查（商品 / 客户 / 供应商）
#
# 档案是主数据，单据是业务数据。删档案最大的风险是「单据指向一个不存在的对象」，
# 表现为单据列表里客户名变成空白、商品查不到。所以默认先做引用检查：
#   · 没被任何业务数据引用  → 直接删除（录错的档案就属于这一类）
#   · 已被引用              → 返回 409 并列出引用明细，由用户决定是否 force 强删
# force=true 时只删档案本身，不动业务单据——单据明细里存了名称/规格/单位快照，
# 历史单据的打印与金额不受影响，只是失去了与档案的关联。
# ============================================================================

# kind -> (模型, 中文名, 编码字段)
_ARCHIVE_KINDS: dict[str, tuple[type, str, str]] = {
    "product": (Product, "商品", "sku"),
    "customer": (Customer, "客户", "code"),
    "supplier": (Supplier, "供应商", "code"),
    "warehouse": (Warehouse, "仓库", "code"),
    "employee": (Employee, "员工", "code"),
}



def _archive_references(db: Session, kind: str, item_id: int) -> list[dict[str, object]]:
    """统计某档案被哪些业务数据引用，只返回数量大于 0 的项。"""
    checks: dict[str, list[tuple[str, type, str]]] = {
        "product": [
            ("采购单明细", PurchaseOrderItem, "product_id"),
            ("销售单明细", SalesOrderItem, "product_id"),
            ("库存流水", InventoryTransaction, "product_id"),
            ("生产BOM（母件）", BillOfMaterial, "product_id"),
            ("生产BOM（子件）", BillOfMaterial, "component_product_id"),
            ("生产工单", ProductionOrder, "product_id"),
            ("财务流水", FinancialTransaction, "product_id"),
        ],
        "customer": [
            ("销售单", SalesOrder, "customer_id"),
            ("财务流水", FinancialTransaction, "customer_id"),
        ],
        "supplier": [
            ("采购单", PurchaseOrder, "supplier_id"),
            ("财务流水", FinancialTransaction, "supplier_id"),
        ],
        "warehouse": [
            ("采购单", PurchaseOrder, "warehouse_id"),
            ("销售单", SalesOrder, "warehouse_id"),
            ("库存流水", InventoryTransaction, "warehouse_id"),
            ("财务流水", FinancialTransaction, "warehouse_id"),
            ("购销合同", Contract, "warehouse_id"),
        ],
        # 员工档案：目前没有业务表用外键引用它 —— 单据上的人名是**字符串快照**
        # （业务员、领料人、送货人），改了档案里的名字不会改动历史单据。
        # 所以这里暂时没有引用项可查；将来某张单据改挂 employee_id 时，在这里加一行。
        "employee": [],
    }
    result: list[dict[str, object]] = []
    for label, model, field_name in checks.get(kind, []):
        column = getattr(model, field_name)
        count = (
            db.query(func.count()).select_from(model).filter(column == item_id).scalar() or 0
        )
        if count:
            result.append({"source": label, "count": int(count)})
    return result



def _archive_label(db: Session, model: type, code_field: str, item) -> str:
    """给前端提示用的人类可读标签，例如「商品 矿泉水（SKU-001）」。"""
    code = getattr(item, code_field, None) or ""
    name = getattr(item, "name", None) or ""
    return f"{name}（{code}）" if code else str(name)



def _delete_archive(db: Session, kind: str, item_id: int, force: bool = False) -> dict[str, object]:
    """删除单个档案，带引用检查。返回被删对象的摘要。"""
    model, label, code_field = _ARCHIVE_KINDS[kind]
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    display = _archive_label(db, model, code_field, item)
    references = _archive_references(db, kind, item_id)
    if references and not force:
        detail = "、".join(f"{r['source']} {r['count']} 条" for r in references)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label}「{display}」已被 {detail} 引用，无法删除。请先处理相关业务数据，或带 force=true 强制删除。",
        )
    db.delete(item)
    db.commit()
    return {"id": item_id, "display": display, "forced": bool(references and force)}



def _delete_archive_batch(
    db: Session, kind: str, ids: list[int], force: bool = False
) -> dict[str, object]:
    """批量删除档案。逐条判定，返回成功 / 被引用阻塞 / 不存在三组结果。"""
    model, label, code_field = _ARCHIVE_KINDS[kind]
    deleted: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    not_found: list[int] = []

    for item_id in ids:
        item = db.get(model, item_id)
        if item is None:
            not_found.append(item_id)
            continue
        display = _archive_label(db, model, code_field, item)
        references = _archive_references(db, kind, item_id)
        if references and not force:
            blocked.append({"id": item_id, "display": display, "references": references})
            continue
        db.delete(item)
        deleted.append({"id": item_id, "display": display})

    db.commit()
    return {
        "kind": kind,
        "label": label,
        "deleted": deleted,
        "blocked": blocked,
        "not_found": not_found,
        "deleted_count": len(deleted),
        "blocked_count": len(blocked),
    }



def _parse_id_list(payload: dict[str, object]) -> list[int]:
    """从请求体里解析 ids，兼容 {"ids": [...]} 与裸数组两种写法。"""
    raw = payload.get("ids") if isinstance(payload, dict) else payload
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=400, detail="请求体格式错误，应为 {\"ids\": [1, 2, 3]}")
    ids: list[int] = []
    for value in raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"非法 id：{value!r}")
    return ids



@router.get("/customers")
def list_customers(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[CustomerRead]:
    items = _paginate(db.query(Customer).order_by(Customer.id.desc()), skip, limit).all()
    return items



@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    existing = db.query(Customer).filter(Customer.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Customer code already exists")
    item = Customer(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.get("/customers/{customer_id}/references")
def customer_references(customer_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """查客户被哪些业务数据引用，供前端在删除前给出提示。"""
    if db.get(Customer, customer_id) is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    return {
        "kind": "customer",
        "id": customer_id,
        "references": _archive_references(db, "customer", customer_id),
    }



@router.delete("/customers/batch")
def delete_customers_batch(
    payload: dict[str, object], force: bool = False, db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量删除客户。force=true 时忽略引用检查。"""
    return _delete_archive_batch(db, "customer", _parse_id_list(payload), force)



@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int, force: bool = False, db: Session = Depends(get_db)
) -> Response:
    _delete_archive(db, "customer", customer_id, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[SupplierRead]:
    items = _paginate(db.query(Supplier).order_by(Supplier.id.desc()), skip, limit).all()
    return items



@router.post("/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)) -> Supplier:
    existing = db.query(Supplier).filter(Supplier.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Supplier code already exists")
    item = Supplier(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.get("/suppliers/{supplier_id}/references")
def supplier_references(supplier_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """查供应商被哪些业务数据引用，供前端在删除前给出提示。"""
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return {
        "kind": "supplier",
        "id": supplier_id,
        "references": _archive_references(db, "supplier", supplier_id),
    }



@router.delete("/suppliers/batch")
def delete_suppliers_batch(
    payload: dict[str, object], force: bool = False, db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量删除供应商。force=true 时忽略引用检查。"""
    return _delete_archive_batch(db, "supplier", _parse_id_list(payload), force)



@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: int, force: bool = False, db: Session = Depends(get_db)
) -> Response:
    _delete_archive(db, "supplier", supplier_id, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/product-categories", response_model=list[ProductCategoryNode])
def list_product_categories(db: Session = Depends(get_db)) -> list[dict]:
    """商品类别树（多级）。返回嵌套 children，前端左侧类别树直接渲染。

    浩技云 5.0 左侧「商品类别」是棵树：顶级=客户/板块，二级=商品类别。
    之前系统里 category 只是扁平字符串，树没了 —— 这里把它补回来。
    """
    nodes = db.query(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.id).all()
    by_parent: dict[int | None, list[ProductCategory]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    def build(parent_id: int | None) -> list[dict]:
        result: list[dict] = []
        for n in by_parent.get(parent_id, []):
            node = {
                "id": n.id,
                "name": n.name,
                "parent_id": n.parent_id,
                "sort_order": n.sort_order,
                "note": n.note,
                "created_at": n.created_at,
                "children": build(n.id),
            }
            result.append(node)
        return result

    return build(None)



@router.post("/product-categories", response_model=ProductCategoryRead, status_code=status.HTTP_201_CREATED)
def create_product_category(payload: ProductCategoryCreate, db: Session = Depends(get_db)) -> ProductCategory:
    _assert_category_name_unique(db, payload.name, payload.parent_id)
    if payload.parent_id is not None and db.get(ProductCategory, payload.parent_id) is None:
        raise HTTPException(status_code=400, detail="上级类别不存在")
    item = ProductCategory(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.patch("/product-categories/{category_id}", response_model=ProductCategoryRead)
def update_product_category(
    category_id: int, payload: ProductCategoryUpdate, db: Session = Depends(get_db)
) -> ProductCategory:
    item = db.get(ProductCategory, category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="类别不存在")
    data = payload.model_dump(exclude_unset=True)
    # 改名或改上级后，同一父级下不能重名
    new_name = data.get("name", item.name)
    new_parent = data.get("parent_id", item.parent_id)
    if "name" in data or "parent_id" in data:
        _assert_category_name_unique(db, new_name, new_parent, exclude_id=item.id)
    if "parent_id" in data and data["parent_id"] is not None:
        if data["parent_id"] == item.id or _is_descendant(db, item.id, data["parent_id"]):
            raise HTTPException(status_code=400, detail="不能把类别挂到它自己或它的下级")
        if db.get(ProductCategory, data["parent_id"]) is None:
            raise HTTPException(status_code=400, detail="上级类别不存在")
    for field, value in data.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item



@router.delete("/product-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_category(category_id: int, db: Session = Depends(get_db)) -> Response:
    """删类别：有子类别或仍被商品引用时拒绝（前端据此提示先清理）。"""
    item = db.get(ProductCategory, category_id)
    if item is None:
        raise HTTPException(status_code=404, detail="类别不存在")
    child = db.query(ProductCategory).filter(ProductCategory.parent_id == category_id).first()
    if child is not None:
        raise HTTPException(status_code=409, detail="该类别下还有子类别，请先删除子类别")
    used = db.query(Product).filter(Product.category == item.name).first()
    if used is not None:
        raise HTTPException(status_code=409, detail=f"仍有商品属于「{item.name}」，请先改掉这些商品的类别")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _assert_category_name_unique(
    db: Session, name: str, parent_id: int | None, exclude_id: int | None = None
) -> None:
    """同一父级下类别名唯一（商品选类别按「名称」回写字符串，重名会歧义）。"""
    q = db.query(ProductCategory).filter(ProductCategory.name == name, ProductCategory.parent_id == parent_id)
    if exclude_id is not None:
        q = q.filter(ProductCategory.id != exclude_id)
    if q.first() is not None:
        raise HTTPException(status_code=400, detail="同一上级下已有同名类别")



def _is_descendant(db: Session, ancestor_id: int, node_id: int) -> bool:
    """判断 node_id 是否在 ancestor_id 的子孙里（防把类别挂到自己的下级形成环）。"""
    current = node_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        row = db.get(ProductCategory, current)
        current = row.parent_id if row else None
    return False



@router.get("/products")
def list_products(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[ProductRead]:
    items = _paginate(db.query(Product).order_by(Product.id.desc()), skip, limit).all()
    return items



@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> Product:
    existing = db.query(Product).filter(Product.sku == payload.sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product SKU already exists")
    item = Product(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)) -> Product:
    """改商品：只更新显式传入的字段，SKU 不可改。

    之前商品只有「新增 + 删除」，没有编辑 —— 浩技云商品档案里录错的
    助记码/条码/规格只能删了重建。补上这个接口后前端才有编辑入口。
    """
    item = db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item



@router.get("/products/{product_id}/references")
def product_references(product_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """查商品被哪些业务数据引用，供前端在删除前给出提示。"""
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return {
        "kind": "product",
        "id": product_id,
        "references": _archive_references(db, "product", product_id),
    }



@router.delete("/products/batch")
def delete_products_batch(
    payload: dict[str, object], force: bool = False, db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量删除商品。force=true 时忽略引用检查。"""
    return _delete_archive_batch(db, "product", _parse_id_list(payload), force)



@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int, force: bool = False, db: Session = Depends(get_db)
) -> Response:
    _delete_archive(db, "product", product_id, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/warehouses")
def list_warehouses(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int | None = None,
    only_active: bool = False,
) -> list[WarehouseRead]:
    query = db.query(Warehouse)
    if only_active:
        query = query.filter(Warehouse.is_active.is_(True))
    return _paginate(query.order_by(Warehouse.code), skip, limit).all()



@router.post("/warehouses", response_model=WarehouseRead, status_code=status.HTTP_201_CREATED)
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db)) -> Warehouse:
    existing = db.query(Warehouse).filter(Warehouse.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Warehouse code already exists")
    item = Warehouse(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.get("/warehouses/{warehouse_id}", response_model=WarehouseRead)
def get_warehouse(warehouse_id: int, db: Session = Depends(get_db)) -> Warehouse:
    item = db.get(Warehouse, warehouse_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return item



@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseRead)
def update_warehouse(
    warehouse_id: int, payload: WarehouseCreate, db: Session = Depends(get_db)
) -> Warehouse:
    item = db.get(Warehouse, warehouse_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    # 编码唯一性：允许改成自己，但不能撞别的仓库
    duplicate = (
        db.query(Warehouse)
        .filter(Warehouse.code == payload.code, Warehouse.id != warehouse_id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Warehouse code already exists")
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item



@router.get("/warehouses/{warehouse_id}/references")
def warehouse_references(warehouse_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """查仓库被哪些业务数据引用，供前端在删除前给出提示。"""
    if db.get(Warehouse, warehouse_id) is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    return {
        "kind": "warehouse",
        "id": warehouse_id,
        "references": _archive_references(db, "warehouse", warehouse_id),
    }



@router.delete("/warehouses/batch")
def delete_warehouses_batch(
    payload: dict[str, object], force: bool = False, db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量删除仓库。force=true 时忽略引用检查。"""
    return _delete_archive_batch(db, "warehouse", _parse_id_list(payload), force)



@router.delete("/warehouses/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_warehouse(
    warehouse_id: int, force: bool = False, db: Session = Depends(get_db)
) -> Response:
    _delete_archive(db, "warehouse", warehouse_id, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# ============================================================================
# 员工档案（基础资料收尾）
# ============================================================================
def _employee_payload(row: Employee, dept_names: dict[int, str]) -> dict[str, object]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "gender": row.gender,
        "department_id": row.department_id,
        "department_name": dept_names.get(row.department_id) if row.department_id else None,
        "position": row.position,
        "phone": row.phone,
        "id_card": row.id_card,
        "hire_date": row.hire_date,
        "leave_date": row.leave_date,
        "status": row.status or "active",
        "base_salary": row.base_salary,
        "bank_name": row.bank_name,
        "bank_account": row.bank_account,
        "emergency_contact": row.emergency_contact,
        "emergency_phone": row.emergency_phone,
        "note": row.note,
        "created_at": row.created_at,
    }



def _department_name_map(db: Session) -> dict[int, str]:
    return {row.id: row.name for row in db.query(Department).all()}



def _validate_employee(db: Session, payload: dict[str, object], *, exclude_id: int | None = None) -> None:
    """员工档案的写入校验。宁可 400 也不要写进一条"部门不存在"的脏数据。"""
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="工号不能为空")
    duplicate = db.query(Employee).filter(Employee.code == code)
    if exclude_id is not None:
        duplicate = duplicate.filter(Employee.id != exclude_id)
    if duplicate.first() is not None:
        raise HTTPException(status_code=400, detail=f"工号「{code}」已存在")

    status = str(payload.get("status") or "active")
    if status not in EMPLOYEE_STATUS:
        raise HTTPException(status_code=400, detail=f"在职状态只能是：{'、'.join(EMPLOYEE_STATUS)}")

    dept_id = payload.get("department_id")
    if dept_id not in (None, ""):
        if db.get(Department, int(dept_id)) is None:
            raise HTTPException(status_code=400, detail="所选部门不存在，请先在「组织机构」里建好")
    elif dept_id == "":
        payload["department_id"] = None

    gender = payload.get("gender")
    if gender not in (None, "") and str(gender) not in GENDER_OPTIONS:
        raise HTTPException(status_code=400, detail=f"性别只能是：{'、'.join(GENDER_OPTIONS)}")



@router.get("/employees/meta")
def employee_meta(db: Session = Depends(get_db)) -> dict[str, object]:
    """表单选项：在职状态 / 性别 / 部门（扁平列表，带层级缩进）。

    必须声明在 `/employees/{employee_id}` 之前，否则 "meta" 会先撞上那个路由。
    """
    depts = db.query(Department).order_by(Department.level, Department.sort_order, Department.id).all()
    return {
        "statuses": [{"value": key, "label": label} for key, label in EMPLOYEE_STATUS.items()],
        "genders": GENDER_OPTIONS,
        "departments": [
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "level": row.level or 0,
                "label": "　" * int(row.level or 0) + row.name,
            }
            for row in depts
        ],
    }



@router.get("/employees")
def list_employees(
    keyword: str | None = None,
    department_id: int | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """员工列表。keyword 同时匹配工号 / 姓名 / 手机 / 岗位。"""
    query = db.query(Employee)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Employee.code.ilike(like),
                Employee.name.ilike(like),
                Employee.phone.ilike(like),
                Employee.position.ilike(like),
            )
        )
    if department_id is not None:
        query = query.filter(Employee.department_id == department_id)
    if status:
        query = query.filter(Employee.status == status)

    rows = _paginate(query.order_by(Employee.id.desc()), skip, limit).all()
    dept_names = _department_name_map(db)
    return [_employee_payload(row, dept_names) for row in rows]



@router.get("/employees/{employee_id}", response_model=EmployeeRead)
def get_employee(employee_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    row = db.get(Employee, employee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    return _employee_payload(row, _department_name_map(db))



@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    data = payload.model_dump()
    data["code"] = str(data["code"]).strip()
    data["name"] = str(data["name"]).strip()
    _validate_employee(db, data)
    row = Employee(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _employee_payload(row, _department_name_map(db))



@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: int, payload: EmployeeCreate, db: Session = Depends(get_db)
) -> dict[str, object]:
    """整表更新（与仓库档案同一约定：前端表单始终提交完整对象）。"""
    row = db.get(Employee, employee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    data = payload.model_dump()
    data["code"] = str(data["code"]).strip()
    data["name"] = str(data["name"]).strip()
    _validate_employee(db, data, exclude_id=employee_id)
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _employee_payload(row, _department_name_map(db))



@router.get("/employees/{employee_id}/references")
def employee_references(employee_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """员工被哪些业务数据引用，供前端删除前提示。"""
    if db.get(Employee, employee_id) is None:
        raise HTTPException(status_code=404, detail="员工不存在")
    return {
        "kind": "employee",
        "id": employee_id,
        "references": _archive_references(db, "employee", employee_id),
    }



@router.delete("/employees/batch")
def delete_employees_batch(
    payload: dict[str, object], force: bool = False, db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量删除员工。force=true 时忽略引用检查。"""
    return _delete_archive_batch(db, "employee", _parse_id_list(payload), force)



@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(
    employee_id: int, force: bool = False, db: Session = Depends(get_db)
) -> Response:
    _delete_archive(db, "employee", employee_id, force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# ============================================================================
# 期初建账：库存期初 / 应收应付期初
# ============================================================================
# 期初库存**不单独建表**，就是 inventory_transactions 里 related_type='opening' 的流水。
# 这么做的直接好处：现存量、库存报表、成本计算全都自动把期初算进去
# （`_net_stock_map` 扫全表，不需要为"期初"再加一个分支）。
# 代价是这一批流水必须和业务流水区分干净 —— 下面每个写操作都死守
# `related_type == "opening"`，绝不允许碰到真实业务流水。
OPENING_RELATED_TYPE = "opening"



def _opening_stock_rows(db: Session) -> tuple[list[dict[str, object]], dict[str, object]]:
    """期初建账一览：每行 = 一个「仓库 × 商品」的期初，外加现存量与业务发生标记。"""
    products = {p.id: p for p in db.query(Product).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}

    net: dict[tuple[int, int], int] = {}
    business_keys: set[tuple[int, int]] = set()
    openings: list[InventoryTransaction] = []
    for row in db.query(InventoryTransaction).all():
        key = (row.product_id, row.warehouse_id)
        net[key] = net.get(key, 0) + _stock_delta(row.transaction_type, row.quantity)
        if row.related_type == OPENING_RELATED_TYPE:
            openings.append(row)
        else:
            business_keys.add(key)

    rows: list[dict[str, object]] = []
    for row in openings:
        key = (row.product_id, row.warehouse_id)
        product = products.get(row.product_id)
        warehouse = warehouses.get(row.warehouse_id)
        quantity = int(row.quantity or 0)
        price = float(row.unit_price or 0.0)
        rows.append(
            {
                "id": row.id,
                "warehouse_id": row.warehouse_id,
                "warehouse_name": getattr(warehouse, "name", None) or f"仓库-{row.warehouse_id}",
                "warehouse_code": getattr(warehouse, "code", None),
                "product_id": row.product_id,
                "sku": getattr(product, "sku", None),
                "product_name": getattr(product, "name", None) or f"商品-{row.product_id}",
                "standards": getattr(product, "standards", None),
                "unit": getattr(product, "unit", None),
                "quantity": quantity,
                "unit_price": price,
                "amount": round(quantity * price, 2),
                # 备注必须带出来：它是用户自己填的建账说明（"浩技云迁移 2026-10"之类），
                # 漏了它页面上那一列永远是空的，而且"载入改这一项"会把备注刷成默认值。
                "note": row.note or "",
                # 现存量：期初 + 之后所有出入库。改期初会让这个数字跟着跳。
                "current_stock": net.get(key, 0),
                # 该「仓库 × 商品」是否已经发生过真实业务流水。
                # 有了业务还改期初，等于凭空调整历史起点 —— 页面必须警示。
                "has_business": key in business_keys,
            }
        )
    rows.sort(key=lambda item: (item["warehouse_id"], item["product_id"]))
    summary = {
        "lines": len(rows),
        "total_quantity": sum(int(item["quantity"]) for item in rows),
        "total_amount": round(sum(float(item["amount"]) for item in rows), 2),
        "business_lines": sum(1 for item in rows if item["has_business"]),
    }
    return rows, summary



@router.get("/opening-stock")
def list_opening_stock(db: Session = Depends(get_db)) -> dict[str, object]:
    """期初库存一览（建账页的数据源）。"""
    rows, summary = _opening_stock_rows(db)
    return {"items": rows, "summary": summary}



@router.put("/opening-stock")
def save_opening_stock(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """批量保存期初库存（幂等 upsert，按「仓库 × 商品」去重）。

    - 数量与单价都是 0 → **删除**这条期初（"填成 0 就是没有"），不留一堆 0 行；
    - 已存在的期初只改数量 / 单价 / 备注，不新增流水（否则现存量会被叠加）。
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items 必须是数组")

    warehouses = {w.id: w for w in db.query(Warehouse).all()}
    products = {p.id: p for p in db.query(Product).all()}
    created = updated = removed = 0

    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 行格式不对")
        wid = int(raw.get("warehouse_id") or 0)
        pid = int(raw.get("product_id") or 0)
        if wid not in warehouses:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的仓库不存在")
        if pid not in products:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的商品不存在")
        try:
            quantity = int(raw.get("quantity") or 0)
            price = float(raw.get("unit_price") or 0.0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的数量或单价不是数字") from exc
        if quantity < 0:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的期初数量不能为负数")
        if price < 0:
            raise HTTPException(status_code=400, detail=f"第 {index} 行的成本单价不能为负数")

        existing = (
            db.query(InventoryTransaction)
            .filter(
                InventoryTransaction.warehouse_id == wid,
                InventoryTransaction.product_id == pid,
                InventoryTransaction.related_type == OPENING_RELATED_TYPE,
            )
            .first()
        )
        if quantity == 0 and price == 0:
            if existing is not None:
                db.delete(existing)
                removed += 1
            continue
        note = str(raw.get("note") or "期初建账")
        if existing is not None:
            existing.quantity = quantity
            existing.unit_price = price
            existing.note = note
            updated += 1
        else:
            db.add(
                InventoryTransaction(
                    product_id=pid,
                    warehouse_id=wid,
                    transaction_type="inbound",
                    quantity=quantity,
                    unit_price=price,
                    related_type=OPENING_RELATED_TYPE,
                    doc_no="OPENING",
                    note=note,
                )
            )
            created += 1

    db.commit()
    _, summary = _opening_stock_rows(db)
    return {
        "created": created,
        "updated": updated,
        "removed": removed,
        "summary": summary,
        "message": f"新增 {created} 项、更新 {updated} 项、清除 {removed} 项",
    }



@router.delete("/opening-stock/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opening_stock(transaction_id: int, db: Session = Depends(get_db)) -> Response:
    """删除一条期初。

    死守 `related_type == 'opening'`：这个 id 落在同一张流水表里，
    少一个判断就可能删掉一条真实出库 —— 那等于凭空改库存。
    """
    row = db.get(InventoryTransaction, transaction_id)
    if row is None or row.related_type != OPENING_RELATED_TYPE:
        raise HTTPException(status_code=404, detail="期初记录不存在")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/opening-stock/clear")
def clear_opening_stock(db: Session = Depends(get_db)) -> dict[str, object]:
    """清空全部期初库存（只删 related_type='opening' 的流水）。"""
    rows = (
        db.query(InventoryTransaction)
        .filter(InventoryTransaction.related_type == OPENING_RELATED_TYPE)
        .all()
    )
    for row in rows:
        db.delete(row)
    db.commit()
    return {"deleted": len(rows), "message": f"已清除 {len(rows)} 项期初库存"}



def _opening_balance_rows(db: Session) -> dict[str, object]:
    """期初应收 / 应付一览：期初金额 + 期间发生额 + 当前余额。

    当前余额复用往来账同一套口径（`_signed_amount`），
    这样建账页看到的数字与「往来对账」页完全一致。
    """
    moved: dict[tuple[str, int], float] = {}
    for row in db.query(FinancialTransaction).all():
        if row.customer_id is not None:
            key = ("customer", row.customer_id)
            moved[key] = moved.get(key, 0.0) + _signed_amount("customer", row)
        if row.supplier_id is not None:
            key = ("supplier", row.supplier_id)
            moved[key] = moved.get(key, 0.0) + _signed_amount("supplier", row)

    receivables = []
    for row in db.query(Customer).order_by(Customer.id).all():
        init = float(row.init_receivable or 0.0)
        occurred = round(moved.get(("customer", row.id), 0.0), 2)
        receivables.append(
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "init_amount": init,
                "init_invoice_debt": float(row.init_invoice_debt or 0.0),
                "occurred_amount": occurred,
                "current_balance": round(init + occurred, 2),
            }
        )

    payables = []
    for row in db.query(Supplier).order_by(Supplier.id).all():
        init = float(row.init_payable or 0.0)
        occurred = round(moved.get(("supplier", row.id), 0.0), 2)
        payables.append(
            {
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "init_amount": init,
                "init_invoice_debt": float(row.init_invoice_debt or 0.0),
                "occurred_amount": occurred,
                "current_balance": round(init + occurred, 2),
            }
        )

    return {
        "receivables": receivables,
        "payables": payables,
        "summary": {
            "customer_count": len(receivables),
            "receivable_total": round(sum(item["init_amount"] for item in receivables), 2),
            "supplier_count": len(payables),
            "payable_total": round(sum(item["init_amount"] for item in payables), 2),
        },
    }



@router.get("/opening-balances")
def list_opening_balances(db: Session = Depends(get_db)) -> dict[str, object]:
    """期初应收 / 应付一览（建账页的另外两个 Tab 的数据源）。"""
    return _opening_balance_rows(db)



@router.put("/opening-balances")
def save_opening_balances(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """批量写期初应收 / 应付。

    只动 `init_receivable` / `init_payable` / `init_invoice_debt` 三个字段，
    **不碰档案的其它字段** —— 建账归建账，改档案归改档案，两件事不混在一个接口里。
    允许负数：客户的预收款、给供应商的预付款，期初就是负的。
    """
    if not isinstance(payload.get("receivable"), list) and not isinstance(payload.get("payable"), list):
        raise HTTPException(status_code=400, detail="至少要给 receivable 或 payable 数组")

    def _amount(raw: dict[str, object], field: str, index: int, side: str) -> float:
        try:
            return round(float(raw.get(field) or 0.0), 2)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{side}第 {index} 行的金额不是数字") from exc

    customers = 0
    for index, raw in enumerate(payload.get("receivable") or [], start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"应收第 {index} 行格式不对")
        row = db.get(Customer, int(raw.get("id") or 0))
        if row is None:
            raise HTTPException(status_code=400, detail=f"应收第 {index} 行的客户不存在")
        row.init_receivable = _amount(raw, "init_amount", index, "应收")
        if "init_invoice_debt" in raw:
            row.init_invoice_debt = _amount(raw, "init_invoice_debt", index, "应收")
        customers += 1

    suppliers = 0
    for index, raw in enumerate(payload.get("payable") or [], start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"应付第 {index} 行格式不对")
        row = db.get(Supplier, int(raw.get("id") or 0))
        if row is None:
            raise HTTPException(status_code=400, detail=f"应付第 {index} 行的供应商不存在")
        row.init_payable = _amount(raw, "init_amount", index, "应付")
        if "init_invoice_debt" in raw:
            row.init_invoice_debt = _amount(raw, "init_invoice_debt", index, "应付")
        suppliers += 1

    db.commit()
    result = _opening_balance_rows(db)
    result["message"] = f"已保存 {customers} 个客户的期初应收、{suppliers} 个供应商的期初应付"
    return result
