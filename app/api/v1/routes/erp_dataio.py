"""导入导出 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

Excel 模板下载、批量导入、按 kind 导出。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.customer import Customer
from app.models.employee import Employee
from app.models.inventory import InventoryTransaction
from app.models.organization import Department
from app.models.product import Product
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.services import excel_io
from datetime import datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _attachment_response,
)

router = APIRouter(prefix="", tags=["erp"])




# ============================================================================
# 融合改造 第 3.5 步：Excel 导入导出（档案批量建账 / 数据迁移）
# ============================================================================

# 可导入导出的档案类别 → (模型, 去重键, 中文名)
_IMPORT_TARGETS: dict[str, tuple[type, list[str], str]] = {
    "products": (Product, ["sku"], "商品档案"),
    "customers": (Customer, ["code"], "客户档案"),
    "suppliers": (Supplier, ["code"], "供应商档案"),
    "warehouses": (Warehouse, ["code"], "仓库档案"),
    "employees": (Employee, ["code"], "员工档案"),
}



@router.get("/excel/kinds")
def list_excel_kinds() -> list[dict[str, object]]:
    """列出支持导入导出的数据类别，供前端渲染入口。"""
    out: list[dict[str, object]] = []
    for kind, cols in excel_io.COLUMNS.items():
        out.append(
            {
                "kind": kind,
                "label": excel_io.TITLES[kind].replace("导入模板", ""),
                "key_fields": [c["label"] for c in cols if c["field"] in excel_io.KEY_FIELDS[kind]],
                "required_fields": [c["label"] for c in cols if c.get("required")],
                "column_count": len(cols),
            }
        )
    return out



@router.get("/excel/templates/{kind}")
def download_excel_template(kind: str) -> Response:
    """下载导入模板（含表头、示例行、填写说明页）。"""
    if kind not in excel_io.COLUMNS:
        raise HTTPException(status_code=404, detail=f"不支持的数据类别：{kind}")
    data = excel_io.build_template(kind)
    filename = f"{excel_io.TITLES[kind]}.xlsx"
    return _attachment_response(data, filename, excel_io.xlsx_media_type())



def _export_records(db: Session, kind: str) -> list[dict[str, object]]:
    """取出某类别的全部数据（键与模板列一致）。"""
    specs = excel_io.COLUMNS[kind]
    if kind == "opening-stock":
        wh = {w.id: w.code for w in db.query(Warehouse).all()}
        pd = {p.id: p.sku for p in db.query(Product).all()}
        rows = (
            db.query(InventoryTransaction)
            .filter(InventoryTransaction.related_type == "opening")
            .order_by(InventoryTransaction.id)
            .all()
        )
        return [
            {
                "warehouse_code": wh.get(t.warehouse_id, ""),
                "sku": pd.get(t.product_id, ""),
                "quantity": t.quantity,
                "unit_price": t.unit_price,
                "note": t.note,
            }
            for t in rows
        ]
    model = _IMPORT_TARGETS[kind][0]
    fields = [c["field"] for c in specs]
    return [
        {f: getattr(obj, f, None) for f in fields}
        for obj in db.query(model).order_by(model.id).all()
    ]



@router.get("/excel/export/{kind}")
def export_excel(kind: str, db: Session = Depends(get_db)) -> Response:
    """导出某类别的全部数据为 xlsx（列与模板一致，可改完再导回来）。"""
    if kind not in excel_io.COLUMNS:
        raise HTTPException(status_code=404, detail=f"不支持的数据类别：{kind}")
    rows = _export_records(db, kind)
    data = excel_io.export_rows(kind, rows)
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{excel_io.TITLES[kind].replace('导入模板', '')}_{today}.xlsx"
    return _attachment_response(data, filename, excel_io.xlsx_media_type())



def _translate_import_payload(db: Session, kind: str, payload: dict[str, object]) -> dict[str, object]:
    """把 Excel 里"给人看的列"翻成模型字段。

    为什么必须有这一步：`_import_archive` 是拿到列名直接 `setattr` 的。
    列名一旦不等于字段名（比如「部门」填的是名字、库里存的是 id），
    SQLAlchemy 会**默默接受**这个不存在的属性 —— 数据静默丢掉，导入还报成功。
    所以凡是不等于字段名的列，都在这里显式翻译，翻不出来就抛错（变成该行的错误原因）。
    """
    payload = dict(payload)

    if kind == "employees":
        if "department_name" in payload:
            name = str(payload.pop("department_name") or "").strip()
            if name:
                dept = db.query(Department).filter(Department.name == name).first()
                if dept is None:
                    raise ValueError(f"部门「{name}」不存在，请先在「组织机构」里建好")
                payload["department_id"] = dept.id
            else:
                payload["department_id"] = None
        if "status" in payload:
            raw = str(payload.pop("status") or "").strip()
            # 表里填「在职/离职」，也认英文 code，避免手改回导时把人卡住
            mapping = {"在职": "active", "离职": "left", "active": "active", "left": "left"}
            if raw:
                if raw not in mapping:
                    raise ValueError(f"在职状态「{raw}」无法识别，请填「在职」或「离职」")
                payload["status"] = mapping[raw]

    return payload



def _import_archive(
    db: Session, kind: str, rows: list[dict[str, object]], mode: str
) -> dict[str, object]:
    """导入档案类数据（商品/客户/供应商/仓库）。每行独立保存点，单行失败不影响其他行。"""
    model, key_fields, _label = _IMPORT_TARGETS[kind]
    created = updated = skipped = 0
    errors: list[dict[str, object]] = []

    for record in rows:
        row_no = int(record.get("__row__") or 0)
        payload = {k: v for k, v in record.items() if k != "__row__" and v is not None}
        keys = {k: payload.get(k) for k in key_fields}
        action = ""
        try:
            payload = _translate_import_payload(db, kind, payload)
            with db.begin_nested():
                existing = None
                if all(v is not None for v in keys.values()):
                    existing = (
                        db.query(model)
                        .filter(*[getattr(model, k) == v for k, v in keys.items()])
                        .first()
                    )
                if existing is not None:
                    if mode == "skip":
                        action = "skipped"
                    else:
                        for k, v in payload.items():
                            setattr(existing, k, v)
                        action = "updated"
                else:
                    db.add(model(**payload))
                    action = "created"
        except Exception as exc:  # 单行失败：记录原因，继续下一行
            errors.append({"row": row_no, "message": _short_error(exc)})
            continue
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        else:
            skipped += 1

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}



def _import_opening_stock(
    db: Session, rows: list[dict[str, object]], mode: str
) -> dict[str, object]:
    """导入期初库存：写入 inventory_transactions（related_type=opening），重复导入幂等覆盖。"""
    created = updated = skipped = 0
    errors: list[dict[str, object]] = []
    wh_by_code = {w.code: w.id for w in db.query(Warehouse).all()}
    prod_by_sku = {p.sku: p.id for p in db.query(Product).all()}

    for record in rows:
        row_no = int(record.get("__row__") or 0)
        wcode = str(record.get("warehouse_code") or "")
        sku = str(record.get("sku") or "")
        action = ""
        try:
            if wcode not in wh_by_code:
                raise ValueError(f"仓库编码「{wcode}」不存在，请先在仓库档案里建好")
            if sku not in prod_by_sku:
                raise ValueError(f"商品编码「{sku}」不存在，请先在商品档案里建好")
            qty = int(record.get("quantity") or 0)
            if qty < 0:
                raise ValueError("期初数量不能为负数")
            price = float(record.get("unit_price") or 0.0)
            note = str(record.get("note") or "期初建账")
            wid, pid = wh_by_code[wcode], prod_by_sku[sku]

            with db.begin_nested():
                existing = (
                    db.query(InventoryTransaction)
                    .filter(
                        InventoryTransaction.warehouse_id == wid,
                        InventoryTransaction.product_id == pid,
                        InventoryTransaction.related_type == "opening",
                    )
                    .first()
                )
                if existing is not None:
                    if mode == "skip":
                        action = "skipped"
                    else:
                        existing.quantity = qty
                        existing.unit_price = price
                        existing.note = note
                        action = "updated"
                else:
                    db.add(
                        InventoryTransaction(
                            product_id=pid,
                            warehouse_id=wid,
                            transaction_type="inbound",
                            quantity=qty,
                            unit_price=price,
                            related_type="opening",
                            doc_no="OPENING",
                            note=note,
                        )
                    )
                    action = "created"
        except Exception as exc:
            errors.append({"row": row_no, "message": _short_error(exc)})
            continue
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        else:
            skipped += 1

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}



def _short_error(exc: Exception) -> str:
    """把异常压成一行可读文本（避免把整段堆栈塞进导入结果）。"""
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    if isinstance(exc, ValueError):
        return text
    return f"{text[:160]}"



@router.post("/excel/import/{kind}")
def import_excel(
    kind: str,
    file: UploadFile = File(...),
    mode: str = Query("upsert", description="upsert=存在则更新；skip=存在则跳过"),
    dry_run: bool = Query(False, description="true 时只校验不落库（预检）"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """上传 xlsx 导入。返回逐行结果，单行错误不影响其他行。"""
    if kind not in excel_io.COLUMNS:
        raise HTTPException(status_code=404, detail=f"不支持的数据类别：{kind}")
    if mode not in ("upsert", "skip"):
        raise HTTPException(status_code=400, detail="mode 只能是 upsert 或 skip")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传的文件是空的")

    try:
        rows, errors = excel_io.parse_rows(kind, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if kind == "opening-stock":
        result = _import_opening_stock(db, rows, mode)
    else:
        result = _import_archive(db, kind, rows, mode)

    if dry_run:
        db.rollback()  # 预检：全部丢弃
    else:
        db.commit()

    all_errors = (errors + list(result["errors"]))[:200]
    return {
        "kind": kind,
        "label": excel_io.TITLES[kind].replace("导入模板", ""),
        "mode": mode,
        "dry_run": dry_run,
        "parsed": len(rows),
        "created": result["created"],
        "updated": result["updated"],
        "skipped": result["skipped"],
        "failed": len(all_errors),
        "errors": all_errors,
    }
