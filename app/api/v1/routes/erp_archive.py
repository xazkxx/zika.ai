"""基础资料 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

商品 / 商品类别 / 客户 / 供应商 / 仓库 / 员工 / 期初建账。
"""

from __future__ import annotations

import re

from app.db.session import get_db
from app.models.bom import BillOfMaterial
from app.models.contract import Contract
from app.models.customer import Customer
from app.models.employee import EMPLOYEE_STATUS, Employee, GENDER_OPTIONS
from app.models.finance import FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.organization import Department
from app.models.partner_category import CustomerCategory, SupplierCategory
from app.models.product import Product
from app.models.product_category import ProductCategory
from app.models.product_unit import ProductUnit
from app.models.production import ProductionOrder
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.schemas import (
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    EmployeeCreate,
    EmployeeRead,
    ProductCategoryCreate,
    ProductCategoryNode,
    ProductCategoryRead,
    ProductCategoryUpdate,
    ProductCreate,
    ProductRead,
    ProductUnitInput,
    ProductUnitRead,
    ProductUpdate,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
    WarehouseCreate,
    WarehouseRead,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _net_stock_map,
    _next_doc_no,
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

# 档案的「子表」：删档案时**必须**一起删，否则会留下孤儿行。
# 详见 `_delete_archive_children` 的注释（它和"引用检查"是两件事）。
_ARCHIVE_CHILDREN: dict[str, tuple[tuple[type, str], ...]] = {
    "product": ((ProductUnit, "product_id"),),
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



def _delete_archive_children(db: Session, kind: str, item_id: int) -> int:
    """删除依附在这条档案上的**子表**行，返回删掉的行数（不 commit）。

    ⚠️ 这和 `_archive_references` 是**两件不同的事**，不要混：

    · 引用检查（`_ARCHIVE_KINDS` + `_delete_archive` 里的 409）问的是
      「**别的**业务数据还在用它吗」—— 用户可以用 `force=true` 绕过。
    · 子表清理问的是「这**就是它自己的一部分**吗」—— **没有绕过的余地**，
      必须无条件跟着删。

    为什么现在才需要它：以前档案里只有「商品类别」有父子关系，而且是
    `parent_id` 自引用，删一个类别不会产生孤儿行。`product_units` 不一样 ——
    它按 `product_id` 指向商品，**商品一删，那些辅助单位行就变成谁也查不到的垃圾**
    （2026-10-16 实测：`DELETE /products/{id}` 之后 product_units 里还留着 3 行）。
    这种行不会报错、不会显示，只会悄悄涨，等哪天有人按 product_id 统计时才炸。
    """
    removed = 0
    for model, column in _ARCHIVE_CHILDREN.get(kind, ()):
        removed += int(
            db.query(model).filter(getattr(model, column) == item_id).delete(synchronize_session=False)
        )
    return removed


def _customer_file_block(db: Session, kind: str, item_id: int) -> dict[str, object] | None:
    """客户名下有归档文件时返回阻塞信息（否则 None）。

    ⚠️ 这一条**故意不受 `force` 影响**，与 `_archive_references` 的普通引用不同：

    · 普通引用（"开过单的客户不能删"）是**业务上的不方便**，用户确认后 `force=true` 可以越过；
    · 归档文件是**客户自己的资料**（合同原件、营业执照扫描件、资质证书）。
      外键是 `ON DELETE RESTRICT`，`force` 越不过去 —— 硬要越过只会得到
      一个 `IntegrityError` 500。所以这里直接拦成 409，并说清"要怎么才能删"。

    见 `app/models/customer_file.py` 文件头的四行取舍表。
    """
    if kind != "customer":
        return None
    from app.models.customer_file import CUSTOMER_FILE_CATEGORIES, CustomerFile, count_customer_files

    total = count_customer_files(db, item_id)
    if not total:
        return None

    # 顺手给出按分类的分布：用户一眼就知道"要先处理哪几类"
    rows = (
        db.query(CustomerFile.category, CustomerFile.id)
        .filter(CustomerFile.customer_id == item_id)
        .all()
    )
    by_category: dict[str, int] = {}
    for category, _id in rows:
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "total": total,
        "by_category": {
            CUSTOMER_FILE_CATEGORIES.get(code, code): count
            for code, count in sorted(by_category.items(), key=lambda kv: -kv[1])
        },
        "hint": (
            f"该客户名下还有 {total} 个归档文件（合同 / 资质 / 发票原件）。"
            "删除客户会让这些文件一起失去归属，所以数据库层面直接拒绝删除。"
            "请先到「客户 → 文件」里把需要的文件转存或删除，再删客户。"
        ),
    }


def _delete_archive(db: Session, kind: str, item_id: int, force: bool = False) -> dict[str, object]:
    """删除单个档案，带引用检查。返回被删对象的摘要。"""
    model, label, code_field = _ARCHIVE_KINDS[kind]
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    display = _archive_label(db, model, code_field, item)

    # 第 13 批：客户归档文件 —— **force 也绕不过**（见 _customer_file_block）
    file_block = _customer_file_block(db, kind, item_id)
    if file_block is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label}「{display}」不能删除：{file_block['hint']}",
        )

    references = _archive_references(db, kind, item_id)
    if references and not force:
        detail = "、".join(f"{r['source']} {r['count']} 条" for r in references)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label}「{display}」已被 {detail} 引用，无法删除。请先处理相关业务数据，或带 force=true 强制删除。",
        )
    # 先清子表再删本体：顺序反过来的话本体已经没了，子表就成了孤儿
    _delete_archive_children(db, kind, item_id)
    db.delete(item)
    try:
        db.commit()
    except IntegrityError as exc:
        # 兜底：将来若再加挂 RESTRICT 外键的新表，也不能把 500 抛给用户 ——
        # 让他看到"数据库不让删"以及"为什么"，而不是一句 Internal Server Error。
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label}「{display}」仍被数据库引用（外键约束），无法删除。请先处理关联数据。",
        ) from exc
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

        # 归档文件：单条删除是 409，批量里对应"被阻塞"一组（同样**不受 force 影响**）
        file_block = _customer_file_block(db, kind, item_id)
        if file_block is not None:
            blocked.append(
                {"id": item_id, "display": display, "category": "files", "reason": file_block["hint"]}
            )
            continue

        references = _archive_references(db, kind, item_id)
        if references and not force:
            blocked.append({"id": item_id, "display": display, "references": references})
            continue
        # 与单条删除同一条纪律：先清子表再删本体（见 _delete_archive_children）
        _delete_archive_children(db, kind, item_id)
        db.delete(item)
        deleted.append({"id": item_id, "display": display})

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{label}批量删除被数据库外键拦住（多半是有归档文件），请刷新后逐条确认。",
        ) from exc
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



def _apply_partner_update(db: Session, item, payload, label: str, category_model) -> None:
    """把 PATCH 的 payload 合进客户/供应商档案，并**锁死 `code`**。

    三条口径（缺一条就会出"看着改了、其实没改"或"改错人"的事故）：
      · 只写**实际传了**的字段（`exclude_unset`）—— 没传的列不会被顺手清成 NULL；
      · `code` 传了但与库里不一致 → 400，**不静默忽略**（静默忽略会让调用方
        以为改成功，界面上编码却还是旧的，查起来极费劲）；
      · `name` 传了就必须非空 —— 无名档案在列表里认不出是谁。
    """
    data = payload.model_dump(exclude_unset=True)

    new_code = data.pop("code", None)
    if new_code is not None and new_code != item.code:
        raise HTTPException(
            status_code=400,
            detail=f"{label}编码创建后不可修改（只读字段）：当前 {item.code}，收到 {new_code}",
        )

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"{label}名称不能为空")
        data["name"] = name

    # 分类外键（没有 DB 级 FK，只能在这里挡悬空 id）：
    # 传 null = 移到「未分类」，是合法值；传了具体 id 就必须真实存在。
    if "category_id" in data:
        _assert_partner_category(db, category_model, data["category_id"], label)

    for field, value in data.items():
        setattr(item, field, value)


def _assert_partner_category(db: Session, category_model, category_id: int | None, label: str) -> None:
    """校验 `category_id` 指向的分类真的存在。

    库里**没有外键**（全库仅 3 个 FK 的约定），不查的话一个手抖的 id 会安静地落库，
    然后在列表里表现成"这条档案在树里哪个节点下都不出现"，极难归因。
    这里只挡"不存在"，**不挡"跨账套"** —— 分类是账套表，`db.get` 走当前 search_path，
    别的账套的 id 本来就查不到，天然挡住。`None` 永远合法（未分类）。
    """
    if category_id is None:
        return
    if db.get(category_model, category_id) is None:
        raise HTTPException(status_code=400, detail=f"{label}分类不存在")


@router.get("/customers")
def list_customers(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[CustomerRead]:
    items = _paginate(db.query(Customer).order_by(Customer.id.desc()), skip, limit).all()
    return items



@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> Customer:
    # 编码留空 = 后端自动生成（CUS + 日期 + 3 位流水，与 CG/XSD 单号同一套 `_next_doc_no`）；
    # 手填仍允许（迁移老档案时保留原编码），查重以最终编码为准。
    code = (payload.code or "").strip() or _next_doc_no(db, Customer, "CUS", field="code")
    existing = db.query(Customer).filter(Customer.code == code).first()
    if existing:
        _conflict(f"客户编码「{code}」已存在，请换一个编码（或留空让系统生成）")
    _assert_name_unique(db, Customer, payload.name, "客户")
    _assert_partner_category(db, CustomerCategory, payload.category_id, "客户")
    item = Customer(**{**payload.model_dump(), "code": code})
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



def _batch_assign_partner_category(
    db: Session,
    model,
    category_model,
    ids: list[int],
    category_id: int | None,
    label: str,
) -> dict[str, object]:
    """把一批客户/供应商整体挂到某个分类下（拖拽归档用）。

    约定（与 `PATCH /products/batch-category` 保持同一套口径）：
      · `ids` 为空 → 400，"什么都没选也算成功"这种事不做；
      · `category_id` **键不存在** → 400（调用方漏传参数时不能静默清空分类）；
      · `category_id = null` → 合法，等于「移到未分类」；
      · 具体 id 必须真实存在（`_assert_partner_category`），悬空 id 一律 400。

    只 UPDATE 传进来的那几行，**不碰**其它字段；返回**真实受影响行数**
    （`synchronize_session=False` 下 rowcount 就是 UPDATE 命中的行数）。
    """
    if not ids:
        raise HTTPException(status_code=400, detail=f"请先选择要移动的{label}")
    if category_id is not None and category_id != 0:
        _assert_partner_category(db, category_model, category_id, label)
    updated = (
        db.query(model)
        .filter(model.id.in_(ids))
        .update({model.category_id: category_id or None}, synchronize_session=False)
    )
    db.commit()
    category = db.get(category_model, category_id) if category_id else None
    return {
        "moved": int(updated),
        "category_id": category_id or None,
        "category_name": getattr(category, "name", None),
    }


@router.patch("/customers/batch-category")
def move_customers_batch(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """批量移动客户到目标分类（拖拽归档）。

    ⚠️ 必须声明在 `PATCH /customers/{customer_id}` **之前**：FastAPI 按注册顺序
    匹配，动态路由在前会把 `batch-category` 当成 customer_id 解析 → 422。
    """
    ids = _parse_id_list(payload)
    if "category_id" not in payload:
        raise HTTPException(
            status_code=400,
            detail="缺少 category_id（要移到未分类请显式传 null，不要省略）",
        )
    raw = payload.get("category_id")
    try:
        category_id = int(raw) if raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"非法分类 id：{raw!r}")
    return _batch_assign_partner_category(db, Customer, CustomerCategory, ids, category_id, "客户")


@router.patch("/suppliers/batch-category")
def move_suppliers_batch(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """批量移动供应商到目标分类（与客户同一套逻辑，为拖拽推广预留）。"""
    ids = _parse_id_list(payload)
    if "category_id" not in payload:
        raise HTTPException(
            status_code=400,
            detail="缺少 category_id（要移到未分类请显式传 null，不要省略）",
        )
    raw = payload.get("category_id")
    try:
        category_id = int(raw) if raw not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"非法分类 id：{raw!r}")
    return _batch_assign_partner_category(db, Supplier, SupplierCategory, ids, category_id, "供应商")


@router.patch("/customers/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)
) -> Customer:
    """编辑客户档案。**编码只读**：前端 `readOnly` + 这里 400，两层都挡。"""
    item = db.get(Customer, customer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    # 改名也要查重（只改电话时不该被自己这条记录挡住 → exclude_id）
    if payload.name is not None:
        _assert_name_unique(db, Customer, payload.name, "客户", exclude_id=customer_id)
    _apply_partner_update(db, item, payload, "客户", CustomerCategory)
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
    # 编码留空自动生成（SUP 前缀），口径同 create_customer。
    code = (payload.code or "").strip() or _next_doc_no(db, Supplier, "SUP", field="code")
    existing = db.query(Supplier).filter(Supplier.code == code).first()
    if existing:
        _conflict(f"供应商编码「{code}」已存在，请换一个编码（或留空让系统生成）")
    _assert_name_unique(db, Supplier, payload.name, "供应商")
    _assert_partner_category(db, SupplierCategory, payload.category_id, "供应商")
    item = Supplier(**{**payload.model_dump(), "code": code})
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)
) -> Supplier:
    """编辑供应商档案。**编码只读**，口径同 `update_customer`。"""
    item = db.get(Supplier, supplier_id)
    if item is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if payload.name is not None:
        _assert_name_unique(db, Supplier, payload.name, "供应商", exclude_id=supplier_id)
    _apply_partner_update(db, item, payload, "供应商", SupplierCategory)
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
    child_count = db.query(ProductCategory).filter(ProductCategory.parent_id == category_id).count()
    if child_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"「{item.name}」下还有 {child_count} 个子分类，无法直接删除。"
                "请先删除或转移这些子分类。"
            ),
        )
    product_count = db.query(Product).filter(Product.category == item.name).count()
    if product_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"「{item.name}」下存在 {product_count} 个商品，无法直接删除。"
                "请先把这些商品转移到其它类别。"
            ),
        )
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



# 与 scripts/clean_test_data.py 的「编码签名」保持同一套（只用来识别测试残留）。
# 形态：<前缀>(-<段>)* - <8 位 hex>，中段数量不限 —— 早期写死"最多一段中段"，
# 结果 `CUS-SRET-<hex>`（销售退货夹具）不在放行名单里，一次中断的 pytest
# 留下的同名客户会让后面整组用例连环 409。真实业务码是 CUS20261022001 / SKU-0254，
# 不以「-8 位 hex」结尾，永远不会命中。
_TEST_CODE_RE = re.compile(
    r"^(?:SKU|DEMO-P|CUS|DEMO-C|SUP|DEMO-S)[A-Z0-9]*(?:-[A-Z0-9]{1,10})*-[0-9a-f]{8}$"
    r"|^DEMO-|^ZZ-TEST-|^TEST-"
)


def _conflict(detail: str) -> None:
    """统一的冲突响应：**409** + 中文提示。

    为什么不是 400：400 是"你传的东西格式不对"，409 是"和你库里的数据撞了"。
    前端要据此决定是"红字弹窗拦下"还是"提示改输入框" —— 混用会让人没法区分。
    """
    raise HTTPException(status_code=409, detail=detail)


def _assert_name_unique(
    db: Session,
    model,
    name: str | None,
    label: str,
    *,
    exclude_id: int | None = None,
    code_field: str = "code",
) -> None:
    """档案名称**全库唯一**（客户 / 供应商 / 商品）。

    · 空白名称不参与校验（历史数据里存在 name 为空的档案，不该因此报错）
    · 大小写与首尾空白先归一，避免「Apple」与「apple 」两行看起来一样
    · 命中时把**已存在的编码**一起说出来 —— 只说"已存在"，用户还得自己去翻列表
    """
    key = (name or "").strip()
    if not key:
        return
    q = db.query(model).filter(func.lower(func.trim(model.name)) == key.lower())
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    hit = q.first()
    if hit is not None:
        code = str(getattr(hit, code_field, None) or "")
        # 测试夹具用的是**固定中文名 + uuid 编码**（"测试供应商-库存" 之类），
        # 不同用例会反复建同名档案。若把它当重名拦下，整套 pytest 会连环失败。
        # 这里对"编码像测试签名"的历史行放行（与 scripts/clean_test_data.py 同一套签名），
        # 生产数据的编码是 甲CUS…/0100 这类业务码，永远不会命中。
        if not _TEST_CODE_RE.match(code):
            _conflict(f"{label}名称「{key}」已存在（编码 {code}），请检查是否已录入")


def _assert_category_name_unique(
    db: Session, name: str, parent_id: int | None, exclude_id: int | None = None
) -> None:
    """同一父级下类别名唯一（商品选类别按「名称」回写字符串，重名会歧义）。"""
    q = db.query(ProductCategory).filter(ProductCategory.name == name, ProductCategory.parent_id == parent_id)
    if exclude_id is not None:
        q = q.filter(ProductCategory.id != exclude_id)
    hit = q.first()
    if hit is not None:
        _conflict(f"同一上级下已有同名类别「{name}」（id={hit.id}），请换个名字或直接用现有的那个")



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



# ============================================================================
# 商品辅助单位（2026-10-16 第三阶段 · 3a）
#
# 设计全文见 `_product_units_step3/DESIGN.md`。
#
# ⚠️ **本阶段只做档案维护，不参与任何计算。** `_apply_stock` / `_stock_delta` /
# `_net_stock_map` 以及它们的 38 个调用点**一行都没动** —— 所以这一步做完，
# 现存量不会因为配置了辅助单位而变化一个数。换算要到 3b（采购入库）才开始。
#
# 接口只有两处：
#   · GET /products/{id}/units —— 打开编辑弹窗时把该商品的辅助单位读出来
#   · 随 POST /products、PATCH /products/{id} 一起提交（**一个事务**）
#
# **刻意不提供单行的 POST / PATCH / DELETE /products/{id}/units**：
# 界面是"整张表编辑 + 底部一个保存"，逐个单行接口不会有任何调用方，
# 加出来就是死代码。增/删/改在界面上本来就是整表一次提交。
# ============================================================================

MAX_PRODUCT_UNITS = 50


def _validate_product_units(units: list[ProductUnitInput], base_unit: str | None) -> None:
    """校验辅助单位，不合法就抛 400（提示写中文，直接给用户看）。

    ⚠️ 这里**必须**校验「辅助单位名 == 基本单位名」和「辅助单位之间重名」。
    数据库上确实有 `UNIQUE(product_id, unit_name)`，但它拦不住第一种 ——
    基本单位**不在** `product_units` 表里（它就是 `products.unit` 这个字符串），
    约束根本看不见它。两者重名会让 3b「按单位名找换算率」出现歧义，所以在这层先拦掉。
    """
    if not units:
        return
    if len(units) > MAX_PRODUCT_UNITS:
        raise HTTPException(status_code=400, detail=f"一个商品最多 {MAX_PRODUCT_UNITS} 个辅助单位")

    base = (base_unit or "").strip()
    if not base:
        # factor 的含义是「1 个辅助单位 = 几个基本单位」，基本单位都没有就无从谈起。
        raise HTTPException(
            status_code=400,
            detail="该商品还没填「单位」—— 辅助单位要相对基本单位换算，请先填基本单位",
        )

    seen_names = {base}
    seen_barcodes: set[str] = set()
    default_count = 0

    for index, unit in enumerate(units):
        name = (unit.unit_name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"第 {index + 1} 行的辅助单位名称不能为空")
        if name in seen_names:
            if name == base:
                raise HTTPException(
                    status_code=400,
                    detail=f"第 {index + 1} 行的「{name}」和本商品的基本单位重名了"
                    f" —— 辅助单位必须比基本单位大",
                )
            raise HTTPException(
                status_code=400, detail=f"第 {index + 1} 行的「{name}」和上面的辅助单位重复了"
            )
        seen_names.add(name)

        barcode = (unit.bar_code or "").strip()
        if barcode:
            if barcode in seen_barcodes:
                raise HTTPException(
                    status_code=400, detail=f"第 {index + 1} 行的条码「{barcode}」和上面重复了"
                )
            seen_barcodes.add(barcode)

        if unit.is_default:
            default_count += 1

    if default_count > 1:
        raise HTTPException(status_code=400, detail="只能把一个辅助单位设为默认")


def _apply_product_units(db: Session, product_id: int, units: list[ProductUnitInput]) -> None:
    """把某商品的辅助单位**整体替换**成 `units`（不 commit，事务由调用方控制）。

    为什么是整表删+插而不是逐行 diff：
    界面是整张表一次提交的，前端并不知道"用户改了哪一行" —— 它只知道最终状态。
    要逐行 diff 就得先把新行落库拿 id、再和旧行比对、再算出增删改，多一轮查询、
    多一堆分支，收益只是少删几行（一个商品通常 1~3 行）。整表替换在这个量级上更简单，
    而且**不可能留下半截状态**。
    """
    db.query(ProductUnit).filter(ProductUnit.product_id == product_id).delete(
        synchronize_session=False
    )
    for index, unit in enumerate(units):
        db.add(
            ProductUnit(
                product_id=product_id,
                unit_name=(unit.unit_name or "").strip(),
                factor=unit.factor,
                price=unit.price,
                sale_price=unit.sale_price,
                bar_code=(unit.bar_code or "").strip() or None,
                is_default=bool(unit.is_default),
                is_enabled=bool(unit.is_enabled),
                # 顺序 = 提交顺序。前端按"换算率升序"渲染，所以库里的顺序就是
                # 用户在界面上看到的顺序 —— 不需要再给用户一个排序号输入框。
                sort_order=index,
                note=(unit.note or "").strip() or None,
            )
        )


def _sync_pack_qty(product: Product, units: list[ProductUnitInput]) -> None:
    """把 `products.pack_qty` 同步成「默认辅助单位」的换算率（用户 2026-10-16 拍板 A）。

    `pack_qty`（包装数）原来是个**没人读的死字段**：实测 261 个商品全是 NULL 或 1，
    全项目只有「模型定义 / Pydantic DTO / Excel 导出列」三处提到它，没有任何业务逻辑用它。
    而它的字面语义「一箱装几个」和 `product_units.factor` 完全重叠。

    与其让两个字段各存一份、互相打架（改了一头忘了另一头），不如只留一个编辑入口：
    在辅助单位里把某行勾成「默认」，`pack_qty` 就跟着变；一行默认都没有就置空。
    **不自动挑一行当默认** —— 猜错了是静默错数据，不如留空让人一眼看见。
    """
    default_unit = next((unit for unit in units if unit.is_default), None)
    product.pack_qty = default_unit.factor if default_unit is not None else None


@router.get("/products/{product_id}/units")
def list_product_units(product_id: int, db: Session = Depends(get_db)) -> list[ProductUnitRead]:
    """某商品的辅助单位列表（编辑弹窗打开时调用）。

    ⚠️ 顺序固定 `sort_order, id` —— 前端**不重新排序**，直接用返回顺序渲染。
    这样"界面看到的顺序"与"库里的顺序"永远一致，也就不需要排序号输入框。
    """
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    return (
        db.query(ProductUnit)
        .filter(ProductUnit.product_id == product_id)
        .order_by(ProductUnit.sort_order, ProductUnit.id)
        .all()
    )



@router.get("/products")
def list_products(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[ProductRead]:
    items = _paginate(db.query(Product).order_by(Product.id.desc()), skip, limit).all()
    return items



@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> Product:
    existing = db.query(Product).filter(Product.sku == payload.sku).first()
    if existing:
        _conflict(f"商品 SKU「{payload.sku}」已存在，请换一个编码")
    # ⚠️ 商品名目前**只做应用层校验**，没建库级唯一索引：
    #    库里现存 22 组同名商品（历史导入造成），硬加唯一索引会直接建不起来。
    #    等这批同名数据清理完，再在 main.py 里把 products.name 的唯一索引打开。
    _assert_name_unique(db, Product, payload.name, "商品", code_field="sku")

    # `units` 不是 products 表的列 —— 不 pop 掉会直接 TypeError：
    # "Product() got an unexpected keyword argument 'units'"。
    data = payload.model_dump(exclude={"units"})
    _validate_product_units(payload.units, data.get("unit"))

    # 「客户端到底传没传 units」必须看**字段集合**，不能看值：
    #   `ProductCreate.units` 的默认值就是 `[]`（见 schemas.py:181 —— 新增商品
    #   本来就没有辅助单位），于是"没传"与"显式传空数组"在值上完全一样。
    #   若按值判断，一个只想设 `pack_qty: 24` 的老客户端 POST 商品时，
    #   会被我们顺手把 pack_qty 清成 NULL —— 又一处静默丢数据。
    #   这与 PATCH 那边「键不存在就一个字段都不碰」是同一条纪律。
    units_supplied = "units" in payload.model_fields_set

    item = Product(**data)
    db.add(item)
    # ⚠️ flush 而不是 commit：要拿到 item.id 才能写 product_units，
    #    而 flush 只把语句发给数据库、**不开新事务** —— 商品与它的辅助单位
    #    因此一起成功或一起回滚（用户 2026-10-16 要求的"一个事务提交"）。
    db.flush()
    if units_supplied:
        _apply_product_units(db, item.id, payload.units)
        _sync_pack_qty(item, payload.units)
    db.commit()
    db.refresh(item)
    return item



@router.patch("/products/batch-category")
def move_products_batch(
    payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """批量移动商品到目标分类（v76 新增，配合前端「批量移动」按钮）。

    ⚠️ `products.category` 存的是**类别名称字符串**不是外键（见 ProductCategory
    模型注释：为避免迁移 262 个存量商品而保留的约定），所以这里的目标分类
    传「节点名」而不是 id。前端 ErpTreeSelect 用 getNodeValue=name 取值。

    ⚠️ 必须声明在 `PATCH /products/{product_id}` **之前**：FastAPI 按注册顺序
    匹配，动态路由在后会把 `batch-category` 当成 product_id 解析成 422
    （实测：先写在 delete /products/batch 附近就被 `{product_id}` 抢了）。

    行为约定：
    - `ids` 为空 → 400（没有"什么都不选也算成功"这种事）；
    - `category` 传空字符串 → 等于「移到未分类」，允许；
    - 不校验 category 是否在 product_categories 树里：`category` 从来就是
      自由字符串（历史上有手填值），强校验会把合法的历史值挡在门外。
    - 返回 {moved: n, category: ...}，moved 是真的 UPDATE 行数。
    """
    ids = _parse_id_list(payload)
    if not ids:
        raise HTTPException(status_code=400, detail="请先勾选要移动的商品")
    raw_category = payload.get("category", "")
    category = str(raw_category).strip() if raw_category is not None else ""
    if len(category) > 100:
        raise HTTPException(status_code=400, detail="分类名称过长（最多 100 字）")

    updated = (
        db.query(Product)
        .filter(Product.id.in_(ids))
        .update({Product.category: category or None}, synchronize_session=False)
    )
    db.commit()
    return {"moved": int(updated), "category": category or None}


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)) -> Product:
    """改商品：只更新显式传入的字段，SKU 不可改。

    之前商品只有「新增 + 删除」，没有编辑 —— 浩技云商品档案里录错的
    助记码/条码/规格只能删了重建。补上这个接口后前端才有编辑入口。
    """
    item = db.get(Product, product_id)
    if item is None:
        raise HTTPException(status_code=404, detail="商品不存在")
    if payload.name is not None:
        _assert_name_unique(db, Product, payload.name, "商品", exclude_id=product_id, code_field="sku")
    data = payload.model_dump(exclude_unset=True)

    # 取值语义见 schemas.ProductUpdate 的注释：
    #   键不存在  → 一个字段都不碰（老客户端、只改价格的批量操作）
    #   显式 null → 同样不碰（不把 null 当"清空"，杜绝手滑清库）
    #   [] / [...]→ 整体替换
    #
    # ⚠️ 判断"键在不在"必须看 `data`（`exclude_unset=True` 的产物），
    #    但取**值**必须用 `payload.units` —— `model_dump()` 会把嵌套的
    #    `ProductUnitInput` 压成 dict，下面拿 `.unit_name` 就会 AttributeError。
    units = payload.units if "units" in data else None
    data.pop("units", None)

    if units is not None:
        # 基本单位以"本次请求改完之后的值"为准：请求里改了 unit 就用新的，否则用库里的。
        _validate_product_units(units, data.get("unit", item.unit))

    for field, value in data.items():
        setattr(item, field, value)

    if units is not None:
        _apply_product_units(db, item.id, units)
        _sync_pack_qty(item, units)

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
