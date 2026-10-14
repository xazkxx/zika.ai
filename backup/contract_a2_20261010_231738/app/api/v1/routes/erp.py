from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Annotated
from urllib import request
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.bom import BillOfMaterial
from app.models.customer import Customer
from app.models.finance import DOC_TYPES, FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.invoice import Invoice
from app.models.product import Product
from app.models.production import ProductionOrder
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.services import excel_io
from app.services.pdf_render import render_document_pdf
from app.schemas import (
    BillOfMaterialCreate,
    BillOfMaterialRead,
    CustomerCreate,
    CustomerRead,
    FinancialTransactionCreate,
    FinancialTransactionRead,
    InvoiceCreate,
    InvoiceUpdate,
    InventoryTransactionCreate,
    InventoryTransactionRead,
    ProductCreate,
    ProductRead,
    ProductionOrderCreate,
    ProductionOrderRead,
    ProjectCreate,
    ProjectRead,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    SalesOrderCreate,
    SalesOrderRead,
    SupplierCreate,
    SupplierRead,
    WarehouseCreate,
    WarehouseRead,
)

router = APIRouter(prefix="", tags=["erp"])


def _paginate(query, skip: int = 0, limit: int | None = None):
    """统一列表分页：limit 不传或 <= 0 时返回全部记录，不做任何截断。

    此前各列表接口默认 limit=100/500，导致「库里有 384 个商品，界面只显示 100 个」
    这类静默丢数据的问题。现在默认全量返回；调用方仍可显式传 skip/limit 做分页。
    """
    if skip and skip > 0:
        query = query.offset(skip)
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return query


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


# ============================================================================
# 融合改造：单据公共逻辑（单号生成 / 结算链 / 欠款链 / 财务自动记账）
# ============================================================================


def _next_doc_no(db: Session, model, prefix: str) -> str:
    """按 前缀 + 日期 + 3 位流水 生成单号，例如 CG20261010001。

    取当天同前缀的最大单号 +1；若当天还没有单子则从 001 开始。
    """
    today = datetime.now().strftime("%Y%m%d")
    pattern = f"{prefix}{today}%"
    last = (
        db.query(model.order_no)
        .filter(model.order_no.like(pattern))
        .order_by(model.order_no.desc())
        .first()
    )
    seq = 1
    if last and last[0]:
        tail = last[0][len(prefix) + 8 :]
        if tail.isdigit():
            seq = int(tail) + 1
    return f"{prefix}{today}{seq:03d}"


def _prev_debt_total(db: Session, model, fk_field, fk_value: int) -> float:
    """取同一往来对象上一张单据的"累欠货款"，作为本单的"前次欠款"。"""
    last = db.query(model).filter(fk_field == fk_value).order_by(model.id.desc()).first()
    return float(last.total_debt or 0.0) if last is not None else 0.0


def _normalize_period(value: str | None, fallback_date: str | None = None) -> str:
    """把 YYYY-MM-DD 归一成会计期间 YYYY-MM。"""
    raw = (value or fallback_date or "").strip()
    if len(raw) >= 7:
        return raw[:7]
    return datetime.now().strftime("%Y-%m")


def _write_finance(
    db: Session,
    *,
    transaction_type: str,
    amount: float,
    related_type: str | None = None,
    related_order_id: int | None = None,
    doc_no: str | None = None,
    direction: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    project_id: int | None = None,
    occurred_at: str | None = None,
    note: str | None = None,
) -> FinancialTransaction:
    """业务单据审核后由系统自动写财务流水，人工不允许绕过。"""
    day = (occurred_at or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    record = FinancialTransaction(
        transaction_type=transaction_type,
        related_type=related_type,
        related_order_id=related_order_id,
        doc_no=doc_no,
        direction=direction,
        customer_id=customer_id,
        supplier_id=supplier_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        project_id=project_id,
        amount=float(amount or 0.0),
        occurred_at=day,
        period=_normalize_period(day),
        note=note,
    )
    db.add(record)
    return record


# ============================================================================
# 融合改造：库存联动（开单自动加减库存 / 删单冲销 / 现存量 / 上下限预警）
#
# 四条规矩：
#   1. 库存由业务单据驱动，不靠人工记账 —— 采购单入库、销售单出库。
#   2. 每条流水都带 related_type + related_order_id，删单时按这两个字段冲销。
#   3. 单据没填仓库时回退到默认启用仓库；系统里一个仓库都没有就不写流水，
#      保留"还没建仓库也能开单"的兼容性。
#   4. 允许负库存：库存不足不阻断开单（线下生意常有先卖后进货），
#      但现存量与预警会明确标出来，不让它悄悄发生。
# ============================================================================

INBOUND_TYPES = {"inbound", "in", "purchase", "采购入库", "盘盈", "报溢", "调拨入"}
OUTBOUND_TYPES = {"outbound", "out", "sales", "销售出库", "盘亏", "报损", "调拨出"}


def _stock_delta(transaction_type: str, quantity: int) -> int:
    """把一条流水的「类型 + 数量」折算成对现存量的增减。"""
    qty = int(quantity or 0)
    kind = (transaction_type or "").strip().lower()
    if kind in INBOUND_TYPES:
        return abs(qty)
    if kind in OUTBOUND_TYPES:
        return -abs(qty)
    # 未识别的类型按「有符号数量」处理，兼容历史数据
    return qty


def _default_warehouse(db: Session) -> Warehouse | None:
    """默认仓库：优先启用中的，其次任意一个。单据未指定仓库时用它兜底。"""
    active = (
        db.query(Warehouse)
        .filter(Warehouse.is_active.is_(True))
        .order_by(Warehouse.id)
        .first()
    )
    return active or db.query(Warehouse).order_by(Warehouse.id).first()


def _resolve_warehouse_id(db: Session, given: int | None) -> int | None:
    """确定这张单进出哪个仓库。返回 None 表示系统里还没有仓库可用。"""
    if given:
        return int(given)
    fallback = _default_warehouse(db)
    return fallback.id if fallback is not None else None


def _apply_stock(
    db: Session,
    *,
    product_id: int,
    warehouse_id: int | None,
    quantity: int,
    transaction_type: str,
    unit_price: float = 0.0,
    related_type: str | None = None,
    related_order_id: int | None = None,
    doc_no: str | None = None,
    note: str | None = None,
) -> InventoryTransaction | None:
    """写一条库存流水。没有仓库或数量为 0 时跳过（返回 None）。"""
    qty = int(quantity or 0)
    if warehouse_id is None or qty == 0:
        return None
    record = InventoryTransaction(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=transaction_type,
        quantity=qty,
        unit_price=float(unit_price or 0.0),
        related_type=related_type,
        related_order_id=related_order_id,
        doc_no=doc_no,
        note=note,
    )
    db.add(record)
    return record


def _revert_stock(db: Session, related_type: str, related_order_id: int) -> int:
    """删单时冲销该单产生的全部库存流水，返回冲销条数。"""
    rows = (
        db.query(InventoryTransaction)
        .filter(
            InventoryTransaction.related_type == related_type,
            InventoryTransaction.related_order_id == related_order_id,
        )
        .all()
    )
    for row in rows:
        db.delete(row)
    return len(rows)


def _net_stock_map(db: Session) -> dict[tuple[int, int], int]:
    """全库净库存：(product_id, warehouse_id) -> 现存量。"""
    result: dict[tuple[int, int], int] = {}
    for row in db.query(InventoryTransaction).all():
        key = (row.product_id, row.warehouse_id)
        result[key] = result.get(key, 0) + _stock_delta(row.transaction_type, row.quantity)
    return result


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


def _build_purchase_payload(item: PurchaseOrder, rows: list[PurchaseOrderItem]) -> PurchaseOrderRead:
    return PurchaseOrderRead(
        id=item.id,
        order_no=item.order_no,
        supplier_id=item.supplier_id,
        status=item.status,
        total_amount=item.total_amount,
        created_at=item.created_at,
        warehouse_id=item.warehouse_id,
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


def _build_sales_payload(item: SalesOrder, rows: list[SalesOrderItem]) -> SalesOrderRead:
    return SalesOrderRead(
        id=item.id,
        order_no=item.order_no,
        customer_id=item.customer_id,
        status=item.status,
        total_amount=item.total_amount,
        created_at=item.created_at,
        warehouse_id=item.warehouse_id,
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


def _resolve_item_snapshot(db: Session, line) -> tuple[str | None, str | None, str | None]:
    """明细行缺快照时，从商品档案补齐名称/规格/单位。"""
    if line.product_name and line.unit:
        return line.product_name, line.standards, line.unit
    product = db.get(Product, line.product_id)
    if product is None:
        return line.product_name, line.standards, line.unit
    return (
        line.product_name or product.name,
        line.standards if line.standards is not None else product.standards,
        line.unit or product.unit,
    )


# RapidOCR 引擎单例：模型加载较慢，进程内只加载一次
_rapid_engine = None


def _get_rapid_engine():
    global _rapid_engine
    if _rapid_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_engine = RapidOCR()
    return _rapid_engine


def _classify_invoice_record(item: dict[str, object]) -> str:
    note_text = f"{item.get('note') or ''} {item.get('customer_name') or ''} {item.get('status') or ''}".lower()
    if any(keyword in note_text for keyword in ["采购", "办公", "耗材", "设备", "供应商", "原材料", "材料"]):
        return "采购"
    if any(keyword in note_text for keyword in ["销售", "收入", "客户", "服务", "订单"]):
        return "销售"
    if any(keyword in note_text for keyword in ["交通", "差旅", "出差", "机票", "酒店"]):
        return "差旅"
    if any(keyword in note_text for keyword in ["税", "增值税", "手续费", "银行", "利息"]):
        return "税费"
    return "其他"


def _extract_party(merged: str, start_label: str, end_labels: tuple[str, ...]) -> tuple[str | None, str | None]:
    """截取 购买方/销售方 段落，提取名称与纳税人识别号。"""
    start = merged.find(start_label)
    if start < 0:
        return None, None
    segment = merged[start + len(start_label):]
    for end_label in end_labels:
        idx = segment.find(end_label)
        if idx >= 0:
            segment = segment[:idx]
            break
    name_match = re.search(r"名\s*称[:：]\s*([^\n]{2,40})", segment)
    tax_match = re.search(r"(?:纳税人识别号|税号|统一社会信用代码)[:：]?\s*([0-9A-Za-z]{15,20})", segment)
    name = name_match.group(1).strip() if name_match else None
    tax_no = tax_match.group(1).strip() if tax_match else None
    return name, tax_no


def _split_glued_number(token: str) -> tuple[float, float, float] | None:
    """把被 OCR 粘连的数字串（如 250.00100.00）拆成 数量/单价/金额。"""
    for i in range(1, len(token)):
        for j in range(i + 1, len(token)):
            qty_text, price_text, amount_text = token[:i], token[i:j], token[j:]
            if not all(re.fullmatch(r"\d+(?:\.\d{1,2})?", part) for part in (qty_text, price_text, amount_text)):
                continue
            qty, price, amount = float(qty_text), float(price_text), float(amount_text)
            if amount > 0 and abs(qty * price - amount) <= max(0.05, amount * 0.005):
                return qty, price, amount
    return None


def _parse_item_line(line: str) -> dict[str, object] | None:
    """解析一行明细：品名 + 数量 + 单价 + 金额。

    兼容两种 OCR 输出：
    1. 空格分隔列：*品名* 2 50.00 100.00（数字列前必须有空格，从行尾往前验证）
    2. 数字粘连：*品名*打印纸A4250.00100.00（逐个数字位尝试拆分）
    两种都要求 数量×单价≈金额 成立，避免误判普通行。
    """
    # 空格分隔格式：行末至少一个空格 + 数字列
    spaced = re.search(r"^(.*?)\s+((?:\d[\d,.]*%?)(?:\s+\d[\d,.]*%?)*)\s*$", line)
    if spaced:
        name_raw = spaced.group(1)
        tokens = spaced.group(2).split()
        numeric = [token.replace(",", "") for token in tokens if not token.endswith("%")]
        parsed: tuple[float, float, float] | None = None
        if len(numeric) == 1:
            parsed = _split_glued_number(numeric[0])
        elif len(numeric) >= 3:
            try:
                values = [float(token) for token in numeric]
            except ValueError:
                values = []
            # 从行尾往前找第一个满足 数量×单价≈金额 的相邻三元组
            for idx in range(len(values) - 1, 1, -1):
                qty, price, amount = values[idx - 2], values[idx - 1], values[idx]
                if amount > 0 and abs(qty * price - amount) <= max(0.05, amount * 0.005):
                    parsed = (qty, price, amount)
                    break
        if parsed is None:
            return None
        qty, price, amount = parsed
    else:
        # 数字粘连格式：从每个数字位开始尝试拆分，直到校验成立
        parsed = None
        name_raw = ""
        for digit in re.finditer(r"\d", line):
            split = _split_glued_number(line[digit.start():])
            if split:
                parsed = split
                name_raw = line[:digit.start()]
                break
        if parsed is None:
            return None
        qty, price, amount = parsed

    # 去掉增值税发票明细的 *分类* 前缀（如 *办公用品*打印纸）
    name = re.sub(r"^\*[^*]*\*", "", name_raw).strip(" *\t")
    if not name or len(name) > 40:
        return None

    return {
        "item_name": name,
        "quantity": qty,
        "unit_price": round(price, 2),
        "amount": round(amount, 2),
    }


def _extract_invoice_items(lines: list[str], total_amount: float) -> list[dict[str, object]]:
    """识别明细行，明细合计与发票总额一致才算解析成功。"""
    items: list[dict[str, object]] = []
    for line in lines:
        parsed = _parse_item_line(line)
        if parsed:
            items.append(parsed)
    if items and abs(sum(item["amount"] for item in items) - total_amount) <= max(0.05, total_amount * 0.005):
        return items
    return []


def _infer_invoice_type(text: str) -> str:
    """从发票文本判断类型：专用发票 → 专票，普通发票 → 普票，否则未知。

    数电票文本形如"电子发票（增值税专用发票）"或"电子发票（增值税普通发票）"，
    只写"电子发票"无法判断专普，归为未知。
    """
    if re.search(r"增值税专用发票|专用发票|专用票", text):
        return "专票"
    if re.search(r"增值税普通发票|普通发票|普通票", text):
        return "普票"
    return "未知"


def _extract_dzp_fields(lines: list[str]) -> dict[str, object]:
    """数电票兜底提取：版面是"标签集中在上半部、数值按顺序排在下半部"，
    常规"标签+值"正则匹配不到，这里按数值出现顺序提取。

    典型值序列：发票号 → 开票日期 → 销售方名称 → 销售方税号 →
    购买方名称 → 购买方税号 → 不含税合计¥x → 税额¥y → 价税合计¥z
    """
    # 过滤标签碎片行（购/买/方 等单字行），保留数值行
    fragment_words = {"购", "买", "方", "信", "息", "销", "售", "合", "计", "备", "注"}
    useful: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line in fragment_words:
            continue
        useful.append(line)

    result: dict[str, object] = {}

    # 发票号：首个 8~20 位纯数字行（明细区的小数带小数点会自然排除）
    for line in useful:
        if re.fullmatch(r"\d{8,20}", line):
            result["invoice_no"] = line
            break

    # 日期：XXXX年XX月XX日
    for line in useful:
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", line)
        if match:
            result["date"] = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            break

    # 名称-税号对：税号（15~20 位字母数字）紧邻的前一行含中文即为名称。
    # 数电票值序列里先销售方后购买方：第一对=销售方，第二对=购买方
    parties: list[tuple[str, str]] = []
    for index in range(1, len(useful)):
        line = useful[index]
        if not re.fullmatch(r"[0-9A-Z]{15,20}", line):
            continue
        # 已识别为发票号的行不是税号；"开票人"行是标签不是公司名
        if line == result.get("invoice_no") or "开票人" in useful[index - 1]:
            continue
        prev = re.sub(r"^(?:名称|项目名称|购买方名称|销售方名称)\s*[:：]?\s*", "", useful[index - 1])
        if re.search(r"[一-鿿]", prev):
            parties.append((prev, line))
    if len(parties) >= 1:
        result["seller_name"], result["seller_tax_no"] = parties[0]
    if len(parties) >= 2:
        result["buyer_name"], result["buyer_tax_no"] = parties[1]

    # 金额：¥/￥ 开头的行，最后三个依次是 不含税合计 / 税额 / 价税合计
    money: list[float] = []
    for line in useful:
        match = re.match(r"^[¥￥]\s*([0-9,]+\.?\d*)", line)
        if match:
            money.append(float(match.group(1).replace(",", "")))
    if len(money) >= 3:
        result["excl_tax_amount"] = round(money[-3], 2)
        result["tax_amount"] = round(money[-2], 2)
        result["total_amount"] = round(money[-1], 2)

    # 税率：首个 "n%" 行
    for line in useful:
        match = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)%", line)
        if match:
            result["tax_rate"] = float(match.group(1))
            break

    return result


def _extract_invoice_summary(lines: list[str]) -> dict[str, object]:
    merged = "\n".join(lines)
    # 清洗版：去掉所有空白（空格/换行/制表符），并把全角数字/冒号/括号/￥ 转半角，
    # 让"金\n额"、全角冒号、全半角混用这类 PDF/OCR 干扰都能匹配到
    clean = re.sub(r"\s+", "", merged).translate(
        str.maketrans("０１２３４５６７８９：（）￥", "0123456789:()¥")
    )
    # 发票号（清洗后 "Invoice No" 会变成 "InvoiceNo"，两种写法都兼容）
    invoice_match = re.search(
        r"(?:发票号码|发票编号|票号|InvoiceNo\.?|№|No\.)\s*[:：]?\s*([0-9A-Za-z-]{6,24})",
        clean,
        re.I,
    )
    # 日期（"开票日期/开具日期/发票日期"任一关键词 + 8 位数字或带连字符日期）
    date_match = re.search(
        r"(?:开票日期|开具日期|发票日期|日期|Date)\s*[:：]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{8})",
        clean,
        re.I,
    )
    # 金额：优先取"（小写）"后的数字（发票常写"价税合计(大写)￥123.45(小写)￥123.45"，
    # 大写写的是汉字数字无法直接转浮点）；否则取金额关键词后的第一个数字
    amount_match = re.search(r"[\(（]小写[\)）]\s*[:：]?\s*[¥￥]?\s*([0-9,]+\.?[0-9]*)", clean)
    if amount_match is None:
        amount_match = re.search(
            r"(?:价税合计|金额合计|合计金额|总金额|Amount|Total|￥|¥)\s*[:：]?\s*([0-9,]+\.?[0-9]*)",
            clean,
            re.I,
        )

    invoice_no = invoice_match.group(1).strip() if invoice_match else f"INV-{uuid4().hex[:8].upper()}"
    invoice_date = date_match.group(1).strip() if date_match else None
    total_amount = float(str(amount_match.group(1)).replace(",", "")) if amount_match else 0.0

    buyer_name, buyer_tax_no = _extract_party(merged, "购买方", ("销售方", "价税合计", "密码区"))
    seller_name, seller_tax_no = _extract_party(merged, "销售方", ("价税合计", "备注", "收款人", "开票人", "复核"))

    # 发票类型：专用发票 → 专票，普通发票 → 普票
    invoice_type = _infer_invoice_type(merged)

    # 发票代码
    invoice_code = None
    code_match = re.search(r"发票代码\s*[:：]?\s*([0-9A-Za-z-]{8,24})", merged)
    if code_match:
        invoice_code = code_match.group(1).strip()

    # 税额：只匹配以"税额/税金"开头的行（避免误吞"价税合计"“不含税额”）
    tax_amount = None
    tax_match = re.search(r"^税(?:额|金)(?:合计)?\s*[:：]?\s*([0-9,]+\.?\d*)", merged, re.M)
    if tax_match:
        tax_amount = round(float(tax_match.group(1).replace(",", "")), 2)

    # 税率
    tax_rate = None
    rate_match = re.search(r"(?:税率|征收率)\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)\s*%", merged)
    if rate_match:
        tax_rate = float(rate_match.group(1))

    # 不含税额：优先用 合计-税额；缺税额时按税率反推
    excl_tax_amount = None
    if tax_amount is not None:
        excl_tax_amount = round(total_amount - tax_amount, 2)
    elif tax_rate is not None and total_amount > 0:
        excl_tax_amount = round(total_amount / (1 + tax_rate / 100), 2)
        tax_amount = round(total_amount - excl_tax_amount, 2)

    items = _extract_invoice_items(lines, total_amount)

    # 数电票兜底：标签与数值分离的版面常规正则匹配不到，
    # 按数值出现顺序提取，只补当前仍缺失的字段（不覆盖已有结果）
    dzp = _extract_dzp_fields(lines)
    if invoice_no.startswith("INV-"):
        invoice_no = dzp.get("invoice_no") or invoice_no
    if invoice_date is None:
        invoice_date = dzp.get("date") or date.today().isoformat()
    if total_amount == 0.0 and dzp.get("total_amount"):
        total_amount = float(dzp["total_amount"])
    if buyer_name is None:
        buyer_name = dzp.get("buyer_name")
    if buyer_tax_no is None:
        buyer_tax_no = dzp.get("buyer_tax_no")
    if seller_name is None:
        seller_name = dzp.get("seller_name")
    if seller_tax_no is None:
        seller_tax_no = dzp.get("seller_tax_no")
    if tax_amount is None:
        tax_amount = dzp.get("tax_amount")
    if tax_rate is None:
        tax_rate = dzp.get("tax_rate")
    if excl_tax_amount is None:
        excl_tax_amount = dzp.get("excl_tax_amount")
        if excl_tax_amount is None and tax_amount is not None and total_amount > 0:
            excl_tax_amount = round(total_amount - float(tax_amount), 2)

    return {
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "total_amount": round(total_amount, 2),
        "invoice_type": invoice_type,
        "invoice_code": invoice_code,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "excl_tax_amount": excl_tax_amount,
        "buyer_name": buyer_name,
        "buyer_tax_no": buyer_tax_no,
        "seller_name": seller_name,
        "seller_tax_no": seller_tax_no,
        "raw_text": merged,
        "items": items
        or ([
            {
                "invoice_no": invoice_no,
                "item_name": "发票扫描结果",
                "quantity": 1,
                "unit_price": round(total_amount, 2),
                "amount": round(total_amount, 2),
            }
        ] if total_amount else []),
    }


def _decode_qrcode(payload: bytes) -> str | None:
    """用 OpenCV 识别图片中的二维码（免 pyzbar 额外依赖）。"""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    detector = cv2.QRCodeDetector()
    text, _, _ = detector.detectAndDecode(image)
    return text.strip() if text else None


def _extract_qr_fields(text: str) -> dict[str, object]:
    """从二维码内容提取发票号/金额/日期。

    兼容两种常见格式：
    1. 数电票查验 URL（http...?fphm=...&je=...&kprq=...）
    2. 老式税控二维码（逗号分隔：01,10,发票代码,发票号码,金额,开票日期,...）
    """
    invoice_no: str | None = None
    total_amount: float | None = None
    date_text: str | None = None

    if text.lower().startswith(("http://", "https://")):
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(text).query)
        for key in ("fphm", "invoiceNo", "invoice_no", "fpnumber", "number"):
            if params.get(key):
                invoice_no = str(params[key][0]).strip()
                break
        for key in ("je", "amount", "total", "totalAmount", "money"):
            if params.get(key):
                try:
                    total_amount = float(str(params[key][0]).replace(",", ""))
                    break
                except ValueError:
                    pass
        for key in ("kprq", "date", "issueDate", "invoiceDate"):
            if params.get(key):
                date_text = str(params[key][0]).strip()
                break
        # 无查询参数的数电票直链（如陕西 dppt 平台）：.../v/2_发票号_日期时间+校验码
        if invoice_no is None or date_text is None:
            path_match = re.search(r"[_/](\d{8,20})_(\d{8})\d{6}", text)
            if path_match:
                if invoice_no is None:
                    invoice_no = path_match.group(1)
                if date_text is None:
                    date_text = path_match.group(2)
    else:
        # 注意：不能过滤空段！税控码如 "01,31,,发票号,金额,日期,,校验码" 中
        # 空段（发票代码位置）有含义，过滤后第 4/5/6 段会整体错位
        parts = [part.strip() for part in text.split(",")]
        # 老式税控二维码固定结构：第 4 段=发票号码，第 5 段=金额，第 6 段=开票日期
        if len(parts) >= 6 and re.fullmatch(r"\d{8,20}", parts[3]):
            invoice_no = parts[3]
            try:
                total_amount = float(parts[4])
            except ValueError:
                pass
            date_text = parts[5]
        else:
            # 启发式兜底：长数字串=发票号、带小数的数字=金额、8 位数字=日期
            numbers = [part for part in parts if re.fullmatch(r"\d{8,20}", part)]
            if numbers:
                # 发票号一般是段里最长的数字（20 位数电票号），8 位串多为日期
                invoice_no = max(numbers, key=len)
            for part in parts:
                if total_amount is None and re.fullmatch(r"\d+(?:\.\d{1,2})?", part) and "." in part:
                    total_amount = float(part)
                elif date_text is None and re.fullmatch(r"\d{8}", part):
                    date_text = part

    # 日期统一成 YYYY-MM-DD（8 位数字如 20260924 → 2026-09-24）
    normalized_date: str | None = None
    if date_text:
        digits = re.sub(r"\D", "", date_text)
        if re.fullmatch(r"\d{8}", digits):
            normalized_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
        else:
            normalized_date = date_text

    return {
        "invoice_no": invoice_no,
        "total_amount": total_amount,
        "date": normalized_date,
    }


def _pdf_page_pngs(payload: bytes, dpi: int = 200, zoom: float | None = None) -> list[bytes]:
    """把 PDF 每页渲染成 PNG 图片字节（供二维码检测和 OCR 使用）。

    zoom 非空时用 fitz.Matrix(zoom, zoom) 放大渲染（扫描件 OCR 用 3 倍 ≈ 300 DPI，
    小字更清晰识别率更高）；否则按 dpi 渲染（二维码检测 200 DPI 已够且更快）。
    """
    import fitz

    pages: list[bytes] = []
    with fitz.open(stream=payload, filetype="pdf") as doc:
        for page in doc:
            if zoom is not None:
                pages.append(page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png"))
            else:
                pages.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    return pages


def _pdf_text_layer(payload: bytes) -> str:
    """提取 PDF 内嵌文本层（原生 PDF 发票可直接读到文字）。"""
    import fitz

    with fitz.open(stream=payload, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _ocr_image_bytes(payload: bytes) -> tuple[str, list[str]]:
    """对单张图片字节做 OCR，返回 (引擎名, 文本行列表)。"""
    temp_dir = Path(tempfile.gettempdir()) / "erp_invoice_ocr"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / f"{uuid4()}.png"
    target_path.write_bytes(payload)

    lines: list[str] = []
    try:
        ocr_result, _ = _get_rapid_engine()(str(target_path))
        if ocr_result:
            for item in ocr_result:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                    text = str(item[1]).strip()
                    if text:
                        lines.append(text)
            if lines:
                return "rapidocr", lines
    except Exception:
        pass

    try:
        from paddleocr import PaddleOCR

        paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        paddle_result = paddle_ocr.ocr(str(target_path), cls=True)
        if paddle_result:
            for line in paddle_result[0]:
                if isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                    text = str(line[1][0]).strip()
                    if text:
                        lines.append(text)
                elif isinstance(line, str):
                    lines.append(line)
            if lines:
                return "paddleocr", lines
    except Exception:
        pass

    return "fallback", lines


def _parse_invoice_pipeline(payload: bytes, filename: str) -> dict[str, object]:
    """统一混合解析流水线：第一关二维码 → 第二关 PDF 文本层 → 第三关 OCR 兜底。"""
    extension = Path(filename).suffix.lower()
    is_pdf = extension == ".pdf"
    provider = "fallback"
    summary: dict[str, object] | None = None
    qr_fields: dict[str, object] | None = None

    # ---- 第一关：二维码拦截（最高优先级）----
    try:
        qr_text: str | None = None
        if is_pdf:
            for page_png in _pdf_page_pngs(payload):
                qr_text = _decode_qrcode(page_png)
                if qr_text:
                    break
            # 200 DPI 扫不到时放大 3 倍重扫，小二维码也能命中
            if not qr_text:
                for page_png in _pdf_page_pngs(payload, zoom=3):
                    qr_text = _decode_qrcode(page_png)
                    if qr_text:
                        break
        else:
            qr_text = _decode_qrcode(payload)
        if qr_text:
            qr_fields = _extract_qr_fields(qr_text)
            fields = qr_fields
            # 发票号和金额都提取到才拦截；只有发票号没有金额时交给后续关卡，
            # 避免金额为 0 的脏数据进入发票汇总
            if fields.get("invoice_no") and fields.get("total_amount"):
                provider = "qrcode"
                total = fields["total_amount"]
                total = round(float(total), 2) if total is not None else 0.0
                invoice_no = str(fields["invoice_no"] or f"INV-{uuid4().hex[:8].upper()}")
                summary = {
                    "invoice_no": invoice_no,
                    "invoice_date": fields["date"] or date.today().isoformat(),
                    "total_amount": total,
                    "invoice_type": "未知",
                    "invoice_code": None,
                    "tax_rate": None,
                    "tax_amount": None,
                    "excl_tax_amount": None,
                    "buyer_name": None,
                    "buyer_tax_no": None,
                    "seller_name": None,
                    "seller_tax_no": None,
                    "raw_text": qr_text,
                    "items": [
                        {
                            "invoice_no": invoice_no,
                            "item_name": "二维码解析结果",
                            "quantity": 1,
                            "unit_price": total,
                            "amount": total,
                        }
                    ]
                    if total
                    else [],
                }
                # 二维码里没有发票类型：PDF 顺带读文本层判断专票/普票
                if is_pdf:
                    try:
                        summary["invoice_type"] = _infer_invoice_type(_pdf_text_layer(payload))
                    except Exception:
                        pass
                # 二维码里没有税率/税额/明细/买卖双方：从文本层或 OCR 补充这些字段
                # （发票号/金额/日期仍以二维码为准，绝不覆盖）
                try:
                    extra_lines: list[str] = []
                    if is_pdf:
                        text = _pdf_text_layer(payload)
                        if len(text.strip()) > 20:
                            extra_lines = [line.strip() for line in text.splitlines() if line.strip()]
                        else:
                            for page_png in _pdf_page_pngs(payload, zoom=3):
                                _, page_lines = _ocr_image_bytes(page_png)
                                extra_lines.extend(page_lines)
                    else:
                        _, extra_lines = _ocr_image_bytes(payload)
                    if extra_lines:
                        extra = _extract_invoice_summary(extra_lines)
                        if summary["invoice_type"] in (None, "未知"):
                            summary["invoice_type"] = extra.get("invoice_type") or "未知"
                        for key in (
                            "invoice_code",
                            "tax_rate",
                            "tax_amount",
                            "buyer_name",
                            "buyer_tax_no",
                            "seller_name",
                            "seller_tax_no",
                        ):
                            if summary.get(key) is None:
                                summary[key] = extra.get(key)
                        # 不含税额：用二维码金额与补充的税额/税率重算，保证口径一致
                        if summary["tax_amount"] is not None:
                            summary["excl_tax_amount"] = round(
                                float(summary["total_amount"]) - float(summary["tax_amount"]), 2
                            )
                        elif summary["tax_rate"] is not None and summary["total_amount"]:
                            summary["excl_tax_amount"] = round(
                                float(summary["total_amount"]) / (1 + float(summary["tax_rate"]) / 100), 2
                            )
                        # 明细：文本层/OCR 提取到的替换二维码占位，发票号统一用二维码的
                        if extra.get("items"):
                            enriched = [{**line, "invoice_no": summary["invoice_no"]} for line in extra["items"]]
                            # 只有单条占位明细（未提取到真实明细）时，金额统一用二维码金额
                            if len(enriched) == 1 and "扫描结果" in str(enriched[0].get("item_name", "")):
                                enriched[0]["unit_price"] = summary["total_amount"]
                                enriched[0]["amount"] = summary["total_amount"]
                            summary["items"] = enriched
                except Exception:
                    pass
    except Exception:
        pass

    # ---- 第二关：PDF 文本层提取（原生 PDF）----
    # 智能分流：文本层字符数 > 20 才是原生 PDF，直接走正则；
    # 提取不到文字（或字数极少）视为扫描件，交给第三关 OCR
    if summary is None and is_pdf:
        try:
            text = _pdf_text_layer(payload)
            if len(text.strip()) > 20:
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                candidate = _extract_invoice_summary(lines)
                # 真实提取到发票号（非占位）或金额才算成功，否则交给下一关
                if not str(candidate["invoice_no"]).startswith("INV-") or candidate["total_amount"]:
                    provider = "pdf_text"
                    summary = candidate
        except Exception:
            pass

    # ---- 第三关：OCR 兜底（普通图片 / 扫描件 PDF）----
    # 扫描件 PDF 用 3 倍放大渲染（Matrix(3,3) ≈ 300 DPI）再送 OCR
    if summary is None:
        try:
            ocr_lines: list[str] = []
            engine = "fallback"
            if is_pdf:
                for page_png in _pdf_page_pngs(payload, zoom=3):
                    page_engine, page_lines = _ocr_image_bytes(page_png)
                    ocr_lines.extend(page_lines)
                    if page_engine != "fallback":
                        engine = page_engine
            else:
                engine, ocr_lines = _ocr_image_bytes(payload)
            provider = engine
            if ocr_lines:
                summary = _extract_invoice_summary(ocr_lines)
        except Exception:
            pass

    if summary is None:
        summary = {
            "invoice_no": f"INV-{uuid4().hex[:8].upper()}",
            "invoice_date": date.today().isoformat(),
            "total_amount": 0.0,
            "invoice_type": "未知",
            "invoice_code": None,
            "tax_rate": None,
            "tax_amount": None,
            "excl_tax_amount": None,
            "buyer_name": None,
            "buyer_tax_no": None,
            "seller_name": None,
            "seller_tax_no": None,
            "raw_text": f"发票文件：{filename}",
            "items": [],
        }

    # 二维码是机器编码数据，优先级高于 OCR 文字提取：第一关没拦截时，
    # 二维码里有值的字段无条件覆盖 OCR/文本层结果（包括 OCR 读错的发票号）
    if qr_fields and provider != "qrcode":
        if qr_fields.get("invoice_no"):
            summary["invoice_no"] = qr_fields["invoice_no"]
        if qr_fields.get("total_amount"):
            summary["total_amount"] = round(float(qr_fields["total_amount"]), 2)
        if qr_fields.get("date"):
            summary["invoice_date"] = qr_fields["date"]

    summary["provider"] = provider
    summary["filename"] = filename
    summary["file_type"] = extension
    # 统一字段名 date（与 invoice_date 同义），便于调用方直接取用
    summary["date"] = summary["invoice_date"]
    return summary


@router.post("/invoices/parse")
async def parse_invoice_file(file: UploadFile = File(...)) -> dict[str, object]:
    """统一发票解析接口：支持图片（png/jpg/jpeg）与 PDF，走二维码→文本层→OCR 流水线。"""
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    filename = file.filename or "invoice"
    return _parse_invoice_pipeline(payload, filename)


@router.post("/invoices/ocr")
async def local_invoice_ocr(file: UploadFile = File(...)) -> dict[str, object]:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_name = file.filename or "invoice.png"
    extension = Path(file_name).suffix.lower()
    temp_dir = Path(tempfile.gettempdir()) / "erp_invoice_ocr"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / f"{uuid4()}-{file_name}"
    target_path.write_bytes(payload)

    provider = "fallback"
    lines: list[str] = []

    # 首选：RapidOCR（纯本地、免额外引擎、内置中文模型）
    try:
        ocr_result, _ = _get_rapid_engine()(str(target_path))
        if ocr_result:
            provider = "rapidocr"
            for item in ocr_result:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                    text = str(item[1]).strip()
                    if text:
                        lines.append(text)
    except Exception:
        lines = []

    # 备选：PaddleOCR（需另装 paddlepaddle 引擎）
    if not lines:
        try:
            from paddleocr import PaddleOCR

            paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            paddle_result = paddle_ocr.ocr(str(target_path), cls=True)
            if paddle_result:
                provider = "paddleocr"
                for line in paddle_result[0]:
                    if isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                        text = str(line[1][0]).strip()
                        if text:
                            lines.append(text)
                    elif isinstance(line, str):
                        lines.append(line)
        except Exception:
            pass

    if not lines:
        lines = [f"发票文件：{file_name}", "未能识别出文字：请确认图片清晰、内容为印刷体，并检查本地 OCR 引擎依赖。"]

    summary = _extract_invoice_summary(lines)
    summary["provider"] = provider
    summary["filename"] = file_name
    summary["file_type"] = extension
    return summary


def _invoice_to_dict(item: Invoice) -> dict[str, object]:
    return {
        "id": item.id,
        "invoice_no": item.invoice_no,
        "invoice_type": item.invoice_type,
        "issue_date": item.issue_date,
        "counterparty_name": item.counterparty_name,
        "invoice_code": item.invoice_code,
        "total_amount": float(item.total_amount or 0),
        "tax_rate": item.tax_rate,
        "tax_amount": item.tax_amount,
        "excl_tax_amount": item.excl_tax_amount,
        "deducted": bool(item.deducted),
        "category": item.category,
        "status": item.status,
        "buyer_name": item.buyer_name,
        "buyer_tax_no": item.buyer_tax_no,
        "seller_name": item.seller_name,
        "seller_tax_no": item.seller_tax_no,
        "items": item.items,
        "raw_text": item.raw_text,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    """保存发票。按发票号码去重：重复上传时删除旧记录，用新解析结果替换。"""
    existing = db.query(Invoice).filter(Invoice.invoice_no == payload.invoice_no).first()
    if existing is not None:
        db.delete(existing)
        db.commit()
    item = Invoice(
        invoice_no=payload.invoice_no,
        invoice_type=payload.invoice_type,
        issue_date=payload.issue_date,
        counterparty_name=payload.counterparty_name,
        invoice_code=payload.invoice_code,
        total_amount=payload.total_amount,
        tax_rate=payload.tax_rate,
        tax_amount=payload.tax_amount,
        excl_tax_amount=payload.excl_tax_amount,
        deducted=payload.deducted,
        category=payload.category,
        status=payload.status,
        buyer_name=payload.buyer_name,
        buyer_tax_no=payload.buyer_tax_no,
        seller_name=payload.seller_name,
        seller_tax_no=payload.seller_tax_no,
        items_json=json.dumps(payload.items, ensure_ascii=False) if payload.items else None,
        raw_text=payload.raw_text,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _invoice_to_dict(item)


@router.get("/invoices")
def list_invoices(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[dict[str, object]]:
    items = _paginate(db.query(Invoice).order_by(Invoice.issue_date.desc(), Invoice.id.desc()), skip, limit).all()
    return [_invoice_to_dict(item) for item in items]


@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: InvoiceUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return _invoice_to_dict(item)


@router.delete("/invoices/batch", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoices_batch(payload: dict[str, object], db: Session = Depends(get_db)) -> Response:
    """批量删除发票：body 传 {"ids": [1, 2, 3]}。"""
    ids = [int(i) for i in (payload.get("ids") or [])]
    if not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    db.query(Invoice).filter(Invoice.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invoices/summary")
def invoices_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """发票汇总：类别对比、专票抵扣、普票/专票月度金额，供汇总页图表与分组表使用。"""
    items = db.query(Invoice).order_by(Invoice.issue_date.asc(), Invoice.id.asc()).all()
    total_amount = sum(float(item.total_amount or 0) for item in items)
    total_tax = sum(float(item.tax_amount or 0) for item in items)
    by_type: dict[str, dict[str, object]] = {}
    monthly: dict[str, dict[str, dict[str, object]]] = {}
    deducted_count = 0
    deducted_amount = 0.0
    undeducted_count = 0
    undeducted_amount = 0.0

    for item in items:
        invoice_type = item.invoice_type or "未知"
        amount = float(item.total_amount or 0)
        entry = by_type.setdefault(invoice_type, {"type": invoice_type, "count": 0, "amount": 0.0})
        entry["count"] = int(entry["count"]) + 1
        entry["amount"] = float(entry["amount"]) + amount

        month = (item.issue_date or "")[:7]
        if len(month) == 7:
            month_entry = monthly.setdefault(month, {})
            type_entry = month_entry.setdefault(invoice_type, {"count": 0, "amount": 0.0, "tax": 0.0})
            type_entry["count"] = int(type_entry["count"]) + 1
            type_entry["amount"] = float(type_entry["amount"]) + amount
            type_entry["tax"] = float(type_entry["tax"]) + float(item.tax_amount or 0)

        if invoice_type == "专票":
            if item.deducted:
                deducted_count += 1
                deducted_amount += amount
            else:
                undeducted_count += 1
                undeducted_amount += amount

    return {
        "total_count": len(items),
        "total_amount": round(total_amount, 2),
        "total_tax": round(total_tax, 2),
        "by_type": sorted(by_type.values(), key=lambda x: float(x["amount"]), reverse=True),
        "deduction": {
            "deducted_count": deducted_count,
            "deducted_amount": round(deducted_amount, 2),
            "undeducted_count": undeducted_count,
            "undeducted_amount": round(undeducted_amount, 2),
        },
        "monthly": {month: data for month, data in sorted(monthly.items())},
    }


@router.post("/invoices/sync-finance")
def sync_invoices_to_finance(db: Session = Depends(get_db)) -> dict[str, object]:
    """发票 → 财务关联：每张发票生成一条支出流水（按发票号码幂等去重）。"""
    items = db.query(Invoice).order_by(Invoice.id.asc()).all()
    existing_notes = [
        str(note)
        for (note,) in db.query(FinancialTransaction.note).filter(FinancialTransaction.note.isnot(None)).all()
    ]
    created = 0
    synced_amount = 0.0
    for item in items:
        marker = f"发票 {item.invoice_no}"
        if any(marker in note for note in existing_notes):
            continue
        counterparty = item.counterparty_name or item.seller_name or "对方单位"
        tax_text = f" 税额¥{float(item.tax_amount or 0):,.2f}" if item.tax_amount else ""
        db.add(
            FinancialTransaction(
                transaction_type="expense",
                amount=float(item.total_amount or 0),
                note=f"{marker} | {counterparty} | {item.invoice_type} | 税率{item.tax_rate or '—'}%{tax_text}",
            )
        )
        created += 1
        synced_amount += float(item.total_amount or 0)
    db.commit()
    return {
        "created": created,
        "synced_amount": round(synced_amount, 2),
        "message": f"已同步 {created} 张发票到财务，金额合计 ¥{synced_amount:,.2f}",
    }


def _local_invoice_analysis(summary: dict[str, object]) -> str:
    """无 DeepSeek Key 时的本地规则分析兜底。"""
    lines_out: list[str] = []
    total = float(summary.get("total_amount") or 0)
    total_tax = float(summary.get("total_tax") or 0)
    lines_out.append(f"本期共 {summary.get('total_count', 0)} 张发票，价税合计 ¥{total:,.2f}，税额 ¥{total_tax:,.2f}。")
    by_type = {str(item.get("type")): item for item in summary.get("by_type") or []}
    for type_name in ("专票", "普票", "未知"):
        entry = by_type.get(type_name)
        if entry:
            pct = (float(entry.get("amount") or 0) / total * 100) if total else 0
            lines_out.append(f"{type_name} {entry.get('count', 0)} 张、金额 ¥{float(entry.get('amount') or 0):,.2f}（占比 {pct:.1f}%）。")
    deduction = summary.get("deduction") or {}
    if deduction.get("undeducted_count"):
        lines_out.append(f"⚠ 有 {deduction['undeducted_count']} 张专票共 ¥{float(deduction['undeducted_amount'] or 0):,.2f} 尚未抵扣，建议及时认证抵扣。")
    monthly = summary.get("monthly") or {}
    months = sorted(monthly.keys())
    if len(months) >= 2:
        last_month, prev_month = months[-1], months[-2]
        last_amount = sum(float(v.get("amount") or 0) for v in monthly[last_month].values())
        prev_amount = sum(float(v.get("amount") or 0) for v in monthly[prev_month].values())
        if prev_amount > 0:
            change = (last_amount - prev_amount) / prev_amount * 100
            direction = "上升" if change >= 0 else "下降"
            lines_out.append(f"月度趋势：{last_month} 较 {prev_month} 金额{abs(change):.1f}%{direction}。")
    lines_out.append("建议：定期核对未抵扣专票，普票占比过高时关注采购类目结构。")
    return "\n".join(lines_out)


@router.post("/invoices/agent-analysis")
def invoice_agent_analysis(payload: dict[str, object] | None = None) -> dict[str, object]:
    """智能体分析：DeepSeek 对发票汇总做趋势/异常/税务分析；未配置 Key 时本地规则兜底。"""
    payload = payload or {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是企业财务智能体。根据发票汇总数据输出分析，分四段：1)总体概况 2)趋势分析 3)异常与风险 4)税务建议（抵扣提醒）。用简洁中文，每段用标题开头。注意：total_amount 是价税合计（已含税），total_tax 已包含在其中，两者不要相加。",
                },
                {
                    "role": "user",
                    "content": f"发票汇总数据：{json.dumps(summary, ensure_ascii=False)}",
                },
            ],
            "temperature": 0.3,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=60) as response:
                raw = response.read().decode("utf-8")
                content = json.loads(raw)
            message = content.get("choices", [{}])[0].get("message", {}).get("content") or ""
            if message.strip():
                return {"provider": "deepseek", "analysis": message.strip()}
        except Exception:
            pass

    return {"provider": "local", "analysis": _local_invoice_analysis(summary)}


@router.post("/invoices/analyze")
def analyze_invoices(payload: dict[str, object]) -> dict[str, object]:
    raw_invoices = payload.get("invoices") or []
    if not isinstance(raw_invoices, list):
        raise HTTPException(status_code=400, detail="invoices must be a list")

    normalized: list[dict[str, object]] = []
    total_amount = 0.0
    category_totals: dict[str, float] = {}

    for index, item in enumerate(raw_invoices):
        if not isinstance(item, dict):
            continue
        amount_value = item.get("amount") or item.get("total") or item.get("invoice_amount") or 0
        amount = float(amount_value or 0)
        customer_name = item.get("customer_name") or item.get("customer") or item.get("company") or "未知客户"
        note = item.get("note") or item.get("remark") or ""
        category = item.get("category") or _classify_invoice_record(item)
        record = {
            "id": item.get("id") or item.get("invoice_no") or f"INV-{index + 1}",
            "invoice_no": item.get("invoice_no") or item.get("id") or f"INV-{index + 1}",
            "customer_name": str(customer_name),
            "amount": amount,
            "date": item.get("date") or item.get("invoice_date") or item.get("issue_date") or "—",
            "status": item.get("status") or item.get("payment_status") or "已确认",
            "category": str(category),
            "note": str(note),
        }
        normalized.append(record)
        total_amount += amount
        category_totals[str(category)] = category_totals.get(str(category), 0.0) + amount

    summary = {
        "total_amount": float(total_amount),
        "count": len(normalized),
        "by_category": {category: float(amount) for category, amount in sorted(category_totals.items())},
    }

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        prompt = json.dumps(normalized, ensure_ascii=False)
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是发票智能分类助手。请把发票按采购、销售、差旅、税费、其他分类，并输出 JSON：{'items':[...], 'summary': {'total_amount':..., 'count':..., 'by_category': {...}}}。", 
                },
                {
                    "role": "user",
                    "content": f"请分析以下发票列表并返回分类结果：{prompt}",
                },
            ],
            "temperature": 0.1,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=30) as response:
                raw = response.read().decode("utf-8")
                content = json.loads(raw)
            choice = content.get("choices", [{}])[0]
            message = choice.get("message", {}).get("content") or ""
            cleaned = message.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            parsed_response = json.loads(cleaned)
            if isinstance(parsed_response.get("items"), list):
                return {
                    "provider": "deepseek",
                    "items": parsed_response["items"],
                    "summary": parsed_response.get("summary", summary),
                }
        except Exception:
            pass

    return {
        "provider": "local",
        "items": normalized,
        "summary": summary,
    }


@router.post("/agent/assistant")
def mobile_agent_assistant(payload: dict[str, object] | None = None) -> dict[str, object]:
    payload = payload or {}
    prompt = str(payload.get("prompt") or "请评估当前业务健康度")
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

    sales_total = float(context.get("sales_total") or context.get("sales") or 0)
    purchase_total = float(context.get("purchase_total") or context.get("purchase") or 0)
    finance_total = float(context.get("finance_total") or context.get("finance") or 0)
    customers = int(context.get("customers") or 0)
    products = int(context.get("products") or 0)

    gross_profit = sales_total - purchase_total
    gross_margin_rate = (gross_profit / sales_total * 100) if sales_total else 0.0
    operating_health = "健康" if gross_margin_rate >= 20 and finance_total >= 0 else "关注" if gross_margin_rate >= 8 else "风险"

    summary = {
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "finance_total": finance_total,
        "customers": customers,
        "products": products,
        "gross_profit": gross_profit,
        "gross_margin_rate": round(gross_margin_rate, 2),
    }

    answer = (
        f"当前业务健康度为{operating_health}。"
        f"销售额为¥{sales_total:,.0f}，采购额为¥{purchase_total:,.0f}，毛利为¥{gross_profit:,.0f}，"
        f"毛利率为{gross_margin_rate:.1f}%；当前客户数{customers}，产品数{products}。"
        f"建议：{('继续扩张优质客户并控制采购成本。' if operating_health == '健康' else '加速回款并压缩非必要支出。' if operating_health == '关注' else '立即审查现金流和风险客户，降低坏账概率。') }"
    )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key and prompt:
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是ERP本地智能体助手，输出简洁、实用、中文结论。",
                },
                {
                    "role": "user",
                    "content": f"用户提问：{prompt}\n\n当前业务数据：{json.dumps(summary, ensure_ascii=False)}",
                },
            ],
            "temperature": 0.2,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=30) as response:
                content = json.loads(response.read().decode("utf-8"))
            answer = content.get("choices", [{}])[0].get("message", {}).get("content") or answer
        except Exception:
            pass

    return {
        "answer": answer,
        "summary": summary,
        "risk_level": operating_health,
    }


@router.get("/mobile/dashboard")
def mobile_dashboard(db: Session = Depends(get_db)) -> dict[str, object]:
    dashboard_summary = summary(db)
    inventory_alerts = list_inventory_alerts(db)
    payment_alerts = finance_alerts(db)
    total_sales = float(dashboard_summary.get("sales_total") or 0.0)
    total_purchase = float(dashboard_summary.get("purchase_total") or 0.0)
    net_profit = total_sales - total_purchase
    risk_count = len(inventory_alerts) + len(payment_alerts)

    if net_profit >= 0 and risk_count <= 2:
        status = "healthy"
    elif risk_count <= 5:
        status = "warning"
    else:
        status = "risk"

    recommendations: list[str] = []
    if inventory_alerts:
        recommendations.append(
            f"库存预警 {len(inventory_alerts)} 项（缺货 / 低库存 / 积压），请检查补货与存货周转。"
        )
    if payment_alerts:
        recommendations.append(f"付款提醒 {len(payment_alerts)} 项，建议及时跟进供应商付款。")
    if net_profit < 0:
        recommendations.append("当前净利润为负，建议压缩非必要支出并提升回款效率。")
    if not recommendations:
        recommendations.append("当前业务状态稳定，建议继续维持现有经营节奏。")

    return {
        "status": status,
        "risk_count": risk_count,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "sales_total": total_sales,
            "purchase_total": total_purchase,
            "net_profit": net_profit,
            "customers": int(dashboard_summary.get("customers") or 0),
            "products": int(dashboard_summary.get("products") or 0),
            "inventory_alerts": len(inventory_alerts),
            "payment_alerts": len(payment_alerts),
        },
        "kpis": [
            {"label": "销售额", "value": total_sales, "unit": "CNY"},
            {"label": "采购额", "value": total_purchase, "unit": "CNY"},
            {"label": "净利润", "value": net_profit, "unit": "CNY"},
            {"label": "风险项", "value": risk_count, "unit": "items"},
        ],
        "recommendations": recommendations,
    }


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
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.get("/purchase-orders")
def list_purchase_orders(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[PurchaseOrderRead]:
    items = _paginate(db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()), skip, limit).all()
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

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, PurchaseOrder, "CG")
    if db.query(PurchaseOrder).filter(PurchaseOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="采购单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    prev_debt = round(_prev_debt_total(db, PurchaseOrder, PurchaseOrder.supplier_id, payload.supplier_id), 2)

    item = PurchaseOrder(
        order_no=order_no,
        supplier_id=payload.supplier_id,
        status="draft",
        total_amount=0.0,
        warehouse_id=payload.warehouse_id,
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


@router.get("/sales-orders")
def list_sales_orders(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[SalesOrderRead]:
    items = _paginate(db.query(SalesOrder).order_by(SalesOrder.id.desc()), skip, limit).all()
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

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, SalesOrder, "XS")
    if db.query(SalesOrder).filter(SalesOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="销售开单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    prev_debt = round(_prev_debt_total(db, SalesOrder, SalesOrder.customer_id, payload.customer_id), 2)

    item = SalesOrder(
        order_no=order_no,
        customer_id=payload.customer_id,
        status="draft",
        total_amount=0.0,
        warehouse_id=payload.warehouse_id,
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
    # 库存联动回滚：这张单产生的出库流水一并冲销，否则货扣了单没了，库存就再也对不上
    _revert_stock(db, "sales_out", order_id)
    # 先删订单明细，再删订单本身，避免留下孤儿明细
    db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.get("/purchase/recommendations")
def purchase_recommendations(db: Session = Depends(get_db)) -> list[dict[str, object]]:
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


_CN_NUM = "零壹贰叁肆伍陆柒捌玖"
_CN_UNITS = ["", "拾", "佰", "仟"]
_CN_BIG = ["", "万", "亿", "兆"]


def _four_to_chinese(n: int) -> str:
    """0-9999 转中文数字（内部零压缩）。"""
    s = ""
    zero = False
    for pos in range(3, -1, -1):
        d = (n // (10**pos)) % 10
        if d == 0:
            zero = True
        else:
            if zero and s:
                s += "零"
            zero = False
            s += _CN_NUM[d] + _CN_UNITS[pos]
    return s


def _integer_to_chinese(n: int) -> str:
    """整数转中文大写。"""
    if n == 0:
        return "零"
    sections = []
    while n > 0:
        sections.append(n % 10000)
        n //= 10000
    out = ""
    for idx in range(len(sections) - 1, -1, -1):
        sec = sections[idx]
        if sec == 0:
            if out and not out.endswith("零"):
                out += "零"
            continue
        if out and sec < 1000 and not out.endswith("零"):
            out += "零"
        out += _four_to_chinese(sec) + _CN_BIG[idx]
    return out.rstrip("零") or "零"


def amount_to_chinese(amount: float) -> str:
    """金额转财务大写，例如 42640.00 → 肆万贰仟陆佰肆拾元整。对账单与合同必备。"""
    total_fen = int(round(abs(float(amount or 0.0)) * 100))
    yuan, rem = divmod(total_fen, 100)
    jiao, fen = divmod(rem, 10)

    result = _integer_to_chinese(yuan) + "元"
    if jiao == 0 and fen == 0:
        result += "整"
    else:
        if jiao:
            result += _CN_NUM[jiao] + "角"
        elif fen:
            result += "零"
        if fen:
            result += _CN_NUM[fen] + "分"
    if float(amount or 0.0) < 0:
        result = "负" + result
    return result


# 往来账方向：不同业务类型对余额的影响
_BALANCE_INCREASE = {
    "customer": {"receivable", "income", "sales_return"},
    "supplier": {"payable", "expense", "purchase_return"},
}
_BALANCE_DECREASE = {
    "customer": {"receipt", "sales_out"},
    "supplier": {"payment", "purchase_in"},
}


def _party_opening_balance(db: Session, party_type: str, party_id: int) -> tuple[float, str]:
    """期初余额与往来对象名称：客户取期初应收，供应商取期初应付。"""
    if party_type == "customer":
        party = db.get(Customer, party_id)
        if party is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        return float(party.init_receivable or 0.0), party.name
    if party_type == "supplier":
        party = db.get(Supplier, party_id)
        if party is None:
            raise HTTPException(status_code=404, detail="Supplier not found")
        return float(party.init_payable or 0.0), party.name
    raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")


def _party_transactions(
    db: Session,
    party_type: str,
    party_id: int,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[FinancialTransaction]:
    field = FinancialTransaction.customer_id if party_type == "customer" else FinancialTransaction.supplier_id
    query = db.query(FinancialTransaction).filter(field == party_id)
    if from_date:
        query = query.filter(FinancialTransaction.occurred_at >= from_date)
    if to_date:
        query = query.filter(FinancialTransaction.occurred_at <= to_date)
    return query.order_by(FinancialTransaction.occurred_at.asc(), FinancialTransaction.id.asc()).all()


def _signed_amount(party_type: str, record: FinancialTransaction) -> float:
    """按往来账口径给出带符号金额：增加为正，减少为负。"""
    amount = float(record.amount or 0.0)
    if record.transaction_type in _BALANCE_INCREASE.get(party_type, set()):
        return amount
    if record.transaction_type in _BALANCE_DECREASE.get(party_type, set()):
        return -amount
    return 0.0


@router.get("/finance/ledger")
def finance_ledger(
    party_type: str,
    party_id: int,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """往来账明细：期初余额 → 逐笔发生 → 期末余额。对账单的数据源。"""
    opening, party_name = _party_opening_balance(db, party_type, party_id)
    records = _party_transactions(db, party_type, party_id, from_date, to_date)

    running = opening
    rows = []
    for record in records:
        delta = _signed_amount(party_type, record)
        running = round(running + delta, 2)
        rows.append(
            {
                "id": record.id,
                "date": record.occurred_at,
                "doc_no": record.doc_no,
                "related_type": record.related_type,
                "transaction_type": record.transaction_type,
                "summary": record.note,
                "increase": round(delta, 2) if delta > 0 else 0.0,
                "decrease": round(-delta, 2) if delta < 0 else 0.0,
                "balance": running,
            }
        )

    increase_total = round(sum(row["increase"] for row in rows), 2)
    decrease_total = round(sum(row["decrease"] for row in rows), 2)
    return {
        "party_type": party_type,
        "party_id": party_id,
        "party_name": party_name,
        "from_date": from_date,
        "to_date": to_date,
        "opening_balance": round(opening, 2),
        "increase_total": increase_total,
        "decrease_total": decrease_total,
        "closing_balance": round(opening + increase_total - decrease_total, 2),
        "closing_balance_upper": amount_to_chinese(opening + increase_total - decrease_total),
        "rows": rows,
    }


@router.get("/finance/receivable")
def finance_receivable(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """应收汇总：按客户算当前欠款。"""
    return _party_balance_summary(db, "customer")


@router.get("/finance/payable")
def finance_payable(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """应付汇总：按供应商算当前欠款。"""
    return _party_balance_summary(db, "supplier")


def _party_balance_summary(db: Session, party_type: str) -> list[dict[str, object]]:
    if party_type == "customer":
        parties = db.query(Customer).all()
        field = FinancialTransaction.customer_id
        opening_attr = "init_receivable"
    else:
        parties = db.query(Supplier).all()
        field = FinancialTransaction.supplier_id
        opening_attr = "init_payable"

    results = []
    for party in parties:
        opening = float(getattr(party, opening_attr) or 0.0)
        records = db.query(FinancialTransaction).filter(field == party.id).all()
        increase = sum(_signed_amount(party_type, r) for r in records if _signed_amount(party_type, r) > 0)
        decrease = sum(-_signed_amount(party_type, r) for r in records if _signed_amount(party_type, r) < 0)
        balance = round(opening + increase - decrease, 2)
        if balance == 0 and increase == 0 and decrease == 0:
            continue
        results.append(
            {
                "party_id": party.id,
                "party_code": party.code,
                "party_name": party.name,
                "contact": getattr(party, "contact", None) or party.phone,
                "phone": party.phone,
                "opening_balance": round(opening, 2),
                "increase_total": round(increase, 2),
                "decrease_total": round(decrease, 2),
                "balance": balance,
                "balance_upper": amount_to_chinese(balance),
            }
        )
    results.sort(key=lambda row: row["balance"], reverse=True)
    return results


@router.get("/finance/aging")
def finance_aging(party_type: str = "customer", db: Session = Depends(get_db)) -> dict[str, object]:
    """账龄分析：按 FIFO 把已收/已付款冲抵最早的单据，剩下的按账龄分桶。"""
    if party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")

    field = FinancialTransaction.customer_id if party_type == "customer" else FinancialTransaction.supplier_id
    increases = _BALANCE_INCREASE[party_type]
    decreases = _BALANCE_DECREASE[party_type]
    today = date.today()

    party_ids = [row[0] for row in db.query(field).filter(field.isnot(None)).distinct().all()]
    buckets = {"0-30天": 0.0, "31-60天": 0.0, "61-90天": 0.0, "90天以上": 0.0}
    details = []

    for party_id in party_ids:
        records = (
            db.query(FinancialTransaction)
            .filter(field == party_id)
            .order_by(FinancialTransaction.occurred_at.asc(), FinancialTransaction.id.asc())
            .all()
        )
        docs = [(r.occurred_at or "", float(r.amount or 0.0)) for r in records if r.transaction_type in increases]
        paid_total = sum(float(r.amount or 0.0) for r in records if r.transaction_type in decreases)

        remaining_paid = paid_total
        party_buckets = {"0-30天": 0.0, "31-60天": 0.0, "61-90天": 0.0, "90天以上": 0.0}
        for day, amount in docs:
            if remaining_paid >= amount:
                remaining_paid -= amount
                continue
            open_amount = round(amount - remaining_paid, 2)
            remaining_paid = 0.0
            try:
                age = (today - datetime.strptime(day[:10], "%Y-%m-%d").date()).days
            except (ValueError, TypeError):
                age = 0
            key = "0-30天" if age <= 30 else "31-60天" if age <= 60 else "61-90天" if age <= 90 else "90天以上"
            party_buckets[key] += open_amount

        party_total = round(sum(party_buckets.values()), 2)
        if party_total <= 0:
            continue
        for key, value in party_buckets.items():
            buckets[key] += value
        details.append({"party_id": party_id, "outstanding": party_total, **{k: round(v, 2) for k, v in party_buckets.items()}})

    details.sort(key=lambda row: row["outstanding"], reverse=True)
    return {
        "party_type": party_type,
        "as_of": today.strftime("%Y-%m-%d"),
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "total": round(sum(buckets.values()), 2),
        "total_upper": amount_to_chinese(sum(buckets.values())),
        "details": details,
    }


@router.get("/finance/reconciliation/{party_type}/{party_id}")
def finance_reconciliation(
    party_type: str,
    party_id: int,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """对账单数据：表头 + 明细 + 汇总，直接喂给 B1/B2/B3 模板。"""
    ledger = finance_ledger(party_type, party_id, from_date, to_date, db)
    party = db.get(Customer if party_type == "customer" else Supplier, party_id)
    return {
        "template": "B2" if party_type == "supplier" else "B1",
        "title": "供应商对账单" if party_type == "supplier" else "客户对账单",
        "period": {"from": from_date, "to": to_date},
        "party": {
            "type": party_type,
            "id": party_id,
            "name": party.name,
            "code": party.code,
            "address": party.address,
            "phone": party.phone,
            "contact": getattr(party, "contact", None),
            "contact_phone": getattr(party, "contact_phone", None) or getattr(party, "mobile", None),
            "tax_no": getattr(party, "tax_no", None),
            "bank_name": getattr(party, "bank_name", None),
            "bank_account": getattr(party, "bank_account", None),
        },
        "summary": {
            "opening_balance": ledger["opening_balance"],
            "increase_total": ledger["increase_total"],
            "decrease_total": ledger["decrease_total"],
            "closing_balance": ledger["closing_balance"],
            "closing_balance_upper": ledger["closing_balance_upper"],
        },
        "rows": ledger["rows"],
    }


# ============================================================================
# 融合改造：打印模板（后端 pymupdf 直出 PDF，嵌入中文字体）
# ============================================================================


def _s(v) -> str:
    """None 安全转字符串。"""
    return "" if v is None else str(v)


def _d(v) -> str:
    """日期字段取 YYYY-MM-DD，None 安全。"""
    return "" if v is None else str(v)[:10]


def _pdf_response(spec: dict, filename: str) -> Response:
    pdf = render_document_pdf(spec)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}.pdf"'},
    )


@router.get("/print/statement/{party_type}/{party_id}")
def print_statement(
    party_type: str,
    party_id: int,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """B1 客户对账单 / B2 供应商对账单（PDF）。"""
    if party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")
    data = finance_reconciliation(party_type, party_id, from_date, to_date, db)
    s = data["summary"]
    spec = {
        "title": data["title"],
        "doc_no": f"DZ{datetime.now().strftime('%Y%m%d')}-{party_id:04d}",
        "period": f"对账期间：{_s(from_date) or '（起始）'} 至 {_s(to_date) or datetime.now().strftime('%Y-%m-%d')}",
        "header_left": [
            ("单位名称", _s(data["party"]["name"])),
            ("单位编码", _s(data["party"]["code"])),
            ("地址", _s(data["party"]["address"])),
            ("联系电话", _s(data["party"]["contact_phone"]) or _s(data["party"]["phone"])),
        ],
        "header_right": [
            ("联系人", _s(data["party"]["contact"])),
            ("税号", _s(data["party"]["tax_no"])),
            ("开户银行", _s(data["party"]["bank_name"])),
            ("银行账号", _s(data["party"]["bank_account"])),
        ],
        "columns": [
            {"label": "日期", "width": 58, "align": "c"},
            {"label": "单据号", "width": 92, "align": "l"},
            {"label": "摘要", "width": 175, "align": "l"},
            {"label": "增加", "width": 62, "align": "r"},
            {"label": "减少", "width": 62, "align": "r"},
            {"label": "余额", "width": 66, "align": "r"},
        ],
        "rows": [
            [row["date"], _s(row["doc_no"]), _s(row["summary"]), row["increase"], row["decrease"], row["balance"]]
            for row in data["rows"]
        ],
        "summary": [
            ("期初余额", f"{float(s['opening_balance']):,.2f}"),
            ("本期增加", f"{float(s['increase_total']):,.2f}"),
            ("本期减少", f"{float(s['decrease_total']):,.2f}"),
            ("期末余额", f"{float(s['closing_balance']):,.2f}"),
        ],
        "notes": [
            f"期末余额（大写）：{s['closing_balance_upper']}",
            "说明：如对上述往来无异议，请盖章确认回传；如有异议，请于 5 个工作日内与我司联系核对。",
        ],
        "signatures": ["制单", "审核", ("客户" if party_type == "customer" else "供应商") + "确认（盖章）"],
    }
    return _pdf_response(spec, f"statement_{party_type}_{party_id}")


@router.get("/print/balance-confirm/{party_type}/{party_id}")
def print_balance_confirm(
    party_type: str,
    party_id: int,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """B3 往来余额确认单（PDF）。"""
    if party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")
    data = finance_reconciliation(party_type, party_id, from_date, to_date, db)
    s = data["summary"]
    to = _s(to_date) or datetime.now().strftime("%Y-%m-%d")
    spec = {
        "title": "往来余额确认单",
        "doc_no": f"QR{datetime.now().strftime('%Y%m%d')}-{party_id:04d}",
        "period": f"对账期间：{_s(from_date) or '（起始）'} 至 {to}",
        "header_left": [
            ("单位名称", _s(data["party"]["name"])),
            ("单位编码", _s(data["party"]["code"])),
            ("地址", _s(data["party"]["address"])),
        ],
        "header_right": [
            ("联系人", _s(data["party"]["contact"])),
            ("联系电话", _s(data["party"]["contact_phone"]) or _s(data["party"]["phone"])),
            ("确认日期", to),
        ],
        "paragraphs": [
            f"兹确认：截至 {to}，贵我双方业务往来款项余额如下表所示。经双方核对账目一致，请贵司核对后盖章确认回传。",
        ],
        "summary": [
            ("期初余额", f"{float(s['opening_balance']):,.2f}"),
            ("本期增加", f"{float(s['increase_total']):,.2f}"),
            ("本期减少", f"{float(s['decrease_total']):,.2f}"),
            ("期末余额", f"{float(s['closing_balance']):,.2f}"),
        ],
        "notes": [
            f"期末余额（大写）：{s['closing_balance_upper']}",
            "本确认单一式两份，双方各执一份；如有异议请于 5 个工作日内书面提出，逾期视为确认无误。",
        ],
        "signatures": ["我方（盖章）", ("客户" if party_type == "customer" else "供应商") + "（盖章）", "确认日期"],
    }
    return _pdf_response(spec, f"balance_confirm_{party_type}_{party_id}")


def _order_rows(rows: list, *, with_price: bool) -> list[list]:
    """明细快照 → 打印行。送货单不显示价格。"""
    out = []
    for i, r in enumerate(rows, start=1):
        line = [str(i), _s(r.product_name), _s(r.standards), _s(r.unit), r.quantity]
        if with_price:
            line += [r.unit_price, r.amount]
        line.append(_s(r.note))
        out.append(line)
    return out


def _purchase_print_spec(db: Session, order_id: int, *, inbound: bool) -> dict:
    item = db.get(PurchaseOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购单不存在")
    rows = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).all()
    supplier = db.get(Supplier, item.supplier_id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "采购入库单" if inbound else "采购订单",
        "doc_no": item.order_no,
        "header_left": [
            ("供应商", _s(supplier.name) if supplier else ""),
            ("联系人", _s(item.contact) or _s(supplier.contact) if supplier else ""),
            ("联系电话", _s(item.contact_phone) or (_s(supplier.phone) if supplier else "")),
            ("收货地址", _s(item.address)),
        ],
        "header_right": [
            ("单据日期", _s(item.order_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("付款方式", _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 132, "align": "l"},
            {"label": "规格", "width": 82, "align": "l"},
            {"label": "单位", "width": 38, "align": "c"},
            {"label": "数量", "width": 52, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 45, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"},
        "extra_rows": [
            ("优惠金额", f"{float(item.discount_amount or 0.0):,.2f}"),
            ("实付金额", f"{float(item.paid_amount or 0.0):,.2f}"),
            ("累计欠款", f"{float(item.total_debt or 0.0):,.2f}"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "仓管", "供应商签收"],
    }


def _sales_print_spec(db: Session, order_id: int, *, delivery: bool) -> dict:
    item = db.get(SalesOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售单不存在")
    rows = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).all()
    customer = db.get(Customer, item.customer_id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    spec: dict = {
        "title": "送货单" if delivery else "销售开单",
        "doc_no": item.order_no,
        "header_left": [
            ("客户名称", _s(customer.name) if customer else ""),
            ("联系人", _s(item.contact) or (_s(customer.contact) if customer else "")),
            ("联系电话", _s(item.contact_phone) or (_s(customer.phone) if customer else "")),
            ("送货地址" if delivery else "收货地址", _s(item.address)),
        ],
        "header_right": [
            ("单据日期", _s(item.order_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("送货日期" if delivery else "付款方式", _s(item.delivery_date) if delivery else _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 150, "align": "l"},
            {"label": "规格", "width": 95, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
        ],
        "rows": _order_rows(rows, with_price=not delivery),
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "司机/送货", "客户签收"],
    }
    if delivery:
        spec["columns"] += [
            {"label": "签收数量", "width": 70, "align": "c"},
            {"label": "备注", "width": 71, "align": "l"},
        ]
    else:
        spec["columns"] += [
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 65, "align": "r"},
            {"label": "备注", "width": 33, "align": "l"},
        ]
        spec["totals"] = {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"}
        spec["extra_rows"] = [
            ("优惠金额", f"{float(item.discount_amount or 0.0):,.2f}"),
            ("实收金额", f"{float(item.received_amount or 0.0):,.2f}"),
            ("累计欠款", f"{float(item.total_debt or 0.0):,.2f}"),
        ]
    return spec


_PRINT_KINDS = {
    "purchase-order": ("采购订单", _purchase_print_spec, {"inbound": False}),
    "purchase-inbound": ("采购入库单", _purchase_print_spec, {"inbound": True}),
    "sales-order": ("销售开单", _sales_print_spec, {"delivery": False}),
    "delivery-note": ("送货单", _sales_print_spec, {"delivery": True}),
}


@router.get("/print/{doc_type}/{doc_id}")
def print_order(doc_type: str, doc_id: int, db: Session = Depends(get_db)) -> Response:
    """单据打印：purchase-order / purchase-inbound / sales-order / delivery-note → PDF。"""
    entry = _PRINT_KINDS.get(doc_type)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知的打印类型：{doc_type}")
    _, builder, kwargs = entry
    spec = builder(db, doc_id, **kwargs)
    filename = str(spec.get("doc_no") or f"{doc_type}_{doc_id}").replace("/", "-") or f"{doc_type}_{doc_id}"
    return _pdf_response(spec, filename)


@router.post("/finance/receipt", status_code=status.HTTP_201_CREATED)
def create_receipt(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """收款登记：冲减客户应收。可指定具体销售单，指定后回写该单欠款链。"""
    return _register_payment(db, payload, party_type="customer", transaction_type="receipt")


@router.post("/finance/payment", status_code=status.HTTP_201_CREATED)
def create_payment(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """付款登记：冲减供应商应付。可指定具体采购单。"""
    return _register_payment(db, payload, party_type="supplier", transaction_type="payment")


def _register_payment(
    db: Session, payload: dict[str, object], *, party_type: str, transaction_type: str
) -> dict[str, object]:
    party_id = payload.get("party_id") or payload.get("customer_id") or payload.get("supplier_id")
    if party_id is None:
        raise HTTPException(status_code=400, detail="必须提供 party_id")
    party_id = int(party_id)
    amount = round(float(payload.get("amount") or 0.0), 2)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于 0")

    _, party_name = _party_opening_balance(db, party_type, party_id)
    occurred_at = str(payload.get("occurred_at") or datetime.now().strftime("%Y-%m-%d"))[:10]
    base_note = str(payload.get("note") or f"{'收款' if party_type == 'customer' else '付款'}登记：{party_name}")
    order_id = payload.get("order_id")

    # 指定了单据时，先算清这单还能冲抵多少：超出未付余额的部分算预收/预付，
    # 不硬挂到单据上，避免单据出现负的"累欠货款"。
    applied = amount
    target = None
    amount_field = ""
    fk_field = None
    model = None
    if order_id:
        model = SalesOrder if party_type == "customer" else PurchaseOrder
        amount_field = "received_amount" if party_type == "customer" else "paid_amount"
        fk_field = model.customer_id if party_type == "customer" else model.supplier_id
        target = db.get(model, int(order_id))
        if target is None:
            raise HTTPException(status_code=404, detail="单据不存在")
        net = round(float(target.total_amount or 0.0) - float(target.discount_amount or 0.0), 2)
        already = float(getattr(target, amount_field) or 0.0)
        outstanding = round(net - already, 2)
        applied = round(min(amount, outstanding), 2) if outstanding > 0 else 0.0

    prepaid = round(amount - applied, 2)
    note = base_note if prepaid <= 0 else f"{base_note}（其中 {prepaid:.2f} 为预收/预付）"

    record = _write_finance(
        db,
        transaction_type=transaction_type,
        direction="in" if party_type == "customer" else "out",
        amount=amount,
        related_type="receipt" if party_type == "customer" else "payment",
        related_order_id=int(order_id) if order_id else None,
        doc_no=str(payload.get("doc_no") or ""),
        customer_id=party_id if party_type == "customer" else None,
        supplier_id=party_id if party_type == "supplier" else None,
        occurred_at=occurred_at,
        note=note,
    )
    db.flush()

    if target is not None:
        setattr(target, amount_field, round(float(getattr(target, amount_field) or 0.0) + applied, 2))
        _recalc_debt_chain(db, model, fk_field, party_id, amount_field)

    db.commit()

    return {
        "id": record.id,
        "transaction_type": transaction_type,
        "party_type": party_type,
        "party_id": party_id,
        "amount": amount,
        "applied_amount": applied,
        "prepaid_amount": prepaid,
        "occurred_at": occurred_at,
        "order_id": int(order_id) if order_id else None,
    }


def _recalc_debt_chain(db: Session, model, fk_field, fk_value: int, amount_field: str) -> None:
    """按单据顺序重算「前次欠款 → 本次欠款 → 累欠货款」。"""
    orders = db.query(model).filter(fk_field == fk_value).order_by(model.id.asc()).all()
    running = 0.0
    for order in orders:
        gross = float(order.total_amount or 0.0)
        discount = float(order.discount_amount or 0.0)
        net = round(gross - discount, 2)
        paid = float(getattr(order, amount_field) or 0.0)
        current = round(net - paid, 2)
        order.prev_debt = running
        order.current_debt = current
        order.total_debt = round(running + current, 2)
        running = order.total_debt


@router.get("/finance/period-summary")
def finance_period_summary(period: str | None = Query(None), db: Session = Depends(get_db)) -> dict[str, object]:
    """按会计期间汇总经营数据，支撑利润表与月报。"""
    target = period or datetime.now().strftime("%Y-%m")
    records = db.query(FinancialTransaction).filter(FinancialTransaction.period == target).all()

    income = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type in ("receivable", "income")), 2)
    receipt = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type == "receipt"), 2)
    cost = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type in ("payable", "cost")), 2)
    payment = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type == "payment"), 2)
    expense = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type in ("expense", "scrap")), 2)
    other_income = round(sum(float(r.amount or 0.0) for r in records if r.transaction_type == "overflow"), 2)

    return {
        "period": target,
        "sales_amount": income,
        "receipt_amount": receipt,
        "cost_amount": cost,
        "payment_amount": payment,
        "expense_amount": expense,
        "other_income": other_income,
        "gross_profit": round(income - cost, 2),
        "net_profit": round(income + other_income - cost - expense, 2),
        "record_count": len(records),
    }


@router.get("/finance/doc-types")
def finance_doc_types() -> dict[str, str]:
    """返回财务可关联的单据类型字典，供前端下拉与校验使用。"""
    return DOC_TYPES


@router.get("/finance/alerts")
def finance_alerts(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    supplier_names = {item.id: item.name for item in db.query(Supplier).all()}
    alerts: list[dict[str, object]] = []

    for record in db.query(FinancialTransaction).filter(FinancialTransaction.transaction_type == "expense").all():
        if not record.supplier_id:
            continue
        supplier_name = supplier_names.get(record.supplier_id, "供应商")
        alerts.append(
            {
                "id": record.id,
                "type": "supplier_payment_alert",
                "supplier_id": record.supplier_id,
                "supplier_name": supplier_name,
                "amount": float(record.amount or 0.0),
                "risk_level": "warning" if float(record.amount or 0.0) >= 100 else "info",
                "message": f"{supplier_name}付款提醒：¥{float(record.amount or 0.0):,.0f}，建议尽快处理。",
            }
        )

    return alerts


@router.get("/finance")
def list_finance(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[FinancialTransactionRead]:
    items = _paginate(db.query(FinancialTransaction).order_by(FinancialTransaction.id.desc()), skip, limit).all()
    return items


@router.post("/finance", response_model=FinancialTransactionRead, status_code=status.HTTP_201_CREATED)
def create_finance_record(payload: FinancialTransactionCreate, db: Session = Depends(get_db)) -> FinancialTransaction:
    data = payload.model_dump()
    # 业务发生日期与会计期间：不传则按当天补齐，保证任何流水都能进期间报表
    data["occurred_at"] = (data.get("occurred_at") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    data["period"] = data.get("period") or _normalize_period(data["occurred_at"])
    # 方向：不传时按业务类型推导
    if not data.get("direction"):
        data["direction"] = "in" if data.get("transaction_type") in ("receivable", "receipt", "income", "overflow") else "out"
    # 单据类型校验：防止写入未登记的类型，破坏"财务与所有模块关联"的口径
    related_type = data.get("related_type")
    if related_type and related_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"未知的单据类型：{related_type}")
    item = FinancialTransaction(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/finance/analysis")
def finance_analysis(
    db: Session = Depends(get_db),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict[str, object]:
    query = db.query(
        Customer.id.label("customer_id"),
        Customer.name.label("customer_name"),
        func.coalesce(func.sum(FinancialTransaction.amount), 0).label("total"),
    ).outerjoin(FinancialTransaction, FinancialTransaction.customer_id == Customer.id)

    query = query.filter(FinancialTransaction.transaction_type == "income")
    if start_date:
        query = query.filter(func.date(FinancialTransaction.created_at) >= start_date)
    if end_date:
        query = query.filter(func.date(FinancialTransaction.created_at) <= end_date)
    revenue_rows = query.group_by(Customer.id, Customer.name).order_by(func.sum(FinancialTransaction.amount).desc()).all()

    expense_query = db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0).label("total")).filter(FinancialTransaction.transaction_type == "expense")
    if start_date:
        expense_query = expense_query.filter(func.date(FinancialTransaction.created_at) >= start_date)
    if end_date:
        expense_query = expense_query.filter(func.date(FinancialTransaction.created_at) <= end_date)
    expense_rows = expense_query.scalar() or 0

    # strftime 是 SQLite 专用函数，PG 要用 to_char，按方言选择（保持两库兼容）
    if db.get_bind().dialect.name == "postgresql":
        month_expr = func.to_char(FinancialTransaction.created_at, "YYYY-MM")
    else:
        month_expr = func.strftime("%Y-%m", FinancialTransaction.created_at)

    monthly_query = db.query(
        month_expr.label("month"),
        FinancialTransaction.transaction_type,
        func.coalesce(func.sum(FinancialTransaction.amount), 0).label("total"),
    )
    if start_date:
        monthly_query = monthly_query.filter(func.date(FinancialTransaction.created_at) >= start_date)
    if end_date:
        monthly_query = monthly_query.filter(func.date(FinancialTransaction.created_at) <= end_date)
    monthly_rows = monthly_query.group_by(month_expr, FinancialTransaction.transaction_type).order_by(month_expr.asc()).all()

    monthly_map: dict[str, dict[str, float | str]] = {}
    for month, transaction_type, total in monthly_rows:
        entry = monthly_map.setdefault(month, {"month": month, "income": 0.0, "expense": 0.0})
        if transaction_type == "income":
            entry["income"] = float(total or 0)
        elif transaction_type == "expense":
            entry["expense"] = float(total or 0)

    by_customer = [
        {
            "customer_id": row.customer_id,
            "customer_name": row.customer_name,
            "total": float(row.total or 0.0),
        }
        for row in revenue_rows
        if row.customer_id is not None
    ]
    total_revenue = sum(item["total"] for item in by_customer)

    return {
        "total_revenue": float(total_revenue),
        "total_expense": float(expense_rows),
        "net_profit": float(total_revenue - expense_rows),
        "by_customer": by_customer,
        "monthly_trend": [
            {
                "month": item["month"],
                "income": float(item.get("income") or 0.0),
                "expense": float(item.get("expense") or 0.0),
                "net": float((item.get("income") or 0.0) - (item.get("expense") or 0.0)),
            }
            for item in sorted(monthly_map.values(), key=lambda x: str(x["month"]))
        ],
    }


@router.get("/finance/decision-support")
def finance_decision_support(db: Session = Depends(get_db)) -> dict[str, object]:
    total_income = float(
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0)).filter(FinancialTransaction.transaction_type == "income").scalar() or 0.0
    )
    total_expense = float(
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0)).filter(FinancialTransaction.transaction_type == "expense").scalar() or 0.0
    )
    net_cash_flow = total_income - total_expense
    gross_margin_rate = ((net_cash_flow / total_income) * 100) if total_income else 0.0
    expense_ratio = ((total_expense / total_income) * 100) if total_income else 0.0

    if net_cash_flow >= 1000 and gross_margin_rate >= 20:
        risk_level = "healthy"
        status = {"liquidity": "充足", "trend": "增长", "cash_position": "稳健"}
    elif net_cash_flow >= 0:
        risk_level = "watch"
        status = {"liquidity": "一般", "trend": "稳定", "cash_position": "待关注"}
    else:
        risk_level = "risk"
        status = {"liquidity": "紧张", "trend": "下降", "cash_position": "高风险"}

    recommendations: list[str] = []
    if expense_ratio > 70:
        recommendations.append("压缩非必要支出，优先控制采购成本与日常运营成本。")
    if gross_margin_rate < 20:
        recommendations.append("提升产品毛利率，评估价格调整或采购议价空间。")
    if net_cash_flow < 0:
        recommendations.append("加速回款并延期非核心支出，降低短期现金流压力。")
    if not recommendations:
        recommendations.append("当前财务状况整体正常，建议继续保持收支平衡并维持风险监控。")

    summary = {
        "total_income": total_income,
        "total_expense": total_expense,
        "net_cash_flow": net_cash_flow,
        "gross_margin_rate": round(gross_margin_rate, 2),
        "expense_ratio": round(expense_ratio, 2),
    }

    return {
        "summary": summary,
        "status": status,
        "risk_level": risk_level,
        "recommendations": recommendations,
    }


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


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[ProjectRead]:
    items = _paginate(db.query(Project).order_by(Project.id.desc()), skip, limit).all()
    return items


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    existing = db.query(Project).filter(Project.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project code already exists")
    item = Project(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/dashboard/operations")
def dashboard_operations(db: Session = Depends(get_db)) -> dict[str, object]:
    production_orders = db.query(ProductionOrder).all()
    projects = db.query(Project).all()
    bom_items = db.query(BillOfMaterial).all()

    status_breakdown = {
        "planned": sum(1 for item in production_orders if item.status == "planned"),
        "in_progress": sum(1 for item in production_orders if item.status == "in_progress"),
        "completed": sum(1 for item in production_orders if item.status == "completed"),
    }
    high_priority_orders = [
        {
            "id": item.id,
            "order_no": item.order_no,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "priority": item.priority,
            "status": item.status,
        }
        for item in production_orders
        if item.priority == "high"
    ]
    project_summary = {
        "total": len(projects),
        "in_progress": sum(1 for item in projects if item.status == "in_progress"),
        "completed": sum(1 for item in projects if item.status == "completed"),
        "avg_progress": round(sum(item.progress for item in projects) / len(projects), 1) if projects else 0.0,
        "budget_total": round(sum(float(item.budget or 0.0) for item in projects), 2),
    }

    milestones = [
        {
            "project_name": item.name,
            "phase": "需求评审" if item.status == "planned" else "执行阶段" if item.status == "in_progress" else "验收交付",
            "deadline": item.deadline or (item.created_at.date().isoformat() if item.created_at else "2026-12-31"),
            "status": item.status,
            "progress": item.progress,
        }
        for item in projects[:6]
    ]

    total_production_cost = sum((item.quantity * 38.0) + (item.quantity * 12.0) for item in production_orders)
    labour_cost = sum(item.quantity * 12.0 for item in production_orders)
    material_cost = sum(item.quantity * 38.0 for item in production_orders)
    cost_summary = {
        "material_cost": round(material_cost, 2),
        "labor_cost": round(labour_cost, 2),
        "overhead_cost": round(total_production_cost * 0.1, 2),
        "total_cost": round(total_production_cost * 1.1, 2),
    }

    production_flow = []
    for item in production_orders[:10]:
        stage_names = ["需求确认", "BOM审核", "物料准备", "生产执行", "质检入库"]
        threshold = 0 if item.status == "planned" else 2 if item.status == "in_progress" else len(stage_names)
        steps = []
        for index, stage in enumerate(stage_names):
            steps.append(
                {
                    "name": stage,
                    "status": "done" if index < threshold else "active" if index == threshold and item.status != "completed" else "pending",
                }
            )
        if item.status == "completed":
            steps[-1]["status"] = "done"
        production_flow.append({
            "order_no": item.order_no,
            "status": item.status,
            "steps": steps,
        })

    bom_summary = {
        "total_items": len(bom_items),
        "total_quantity": sum(int(item.quantity) for item in bom_items),
        "total_cost": round(sum(float(item.unit_cost) * int(item.quantity) for item in bom_items), 2),
    }

    recommendations = []
    if status_breakdown["planned"]:
        recommendations.append(
            {
                "title": "优先完成计划排产",
                "description": "当前有多个计划中订单，建议先确认 BOM 与物料准备，避免后续停线。",
                "priority": "high",
            }
        )
    if high_priority_orders:
        recommendations.append(
            {
                "title": "高优先级订单前置",
                "description": "高优先级订单存在交付风险，建议提前排入当日产线并安排检验窗口。",
                "priority": "high",
            }
        )
    if bom_summary["total_items"]:
        recommendations.append(
            {
                "title": "BOM关联复核",
                "description": "已关联 BOM 明细，可重点检查关键部件用量和单位成本，避免成本失控。",
                "priority": "medium",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "title": "稳定生产节奏",
                "description": "当前生产状态平稳，建议维持现有排产与质检节奏，并关注交付拐点。",
                "priority": "low",
            }
        )

    work_orders = [
        {
            "id": item.id,
            "order_no": item.order_no,
            "product_id": item.product_id,
            "line_name": "A线" if item.id % 3 == 0 else "B线" if item.id % 3 == 1 else "C线",
            "quantity": item.quantity,
            "status": item.status,
            "planned_start": (item.created_at.date().isoformat() if item.created_at else "2026-09-01"),
            "planned_end": (item.created_at.date().isoformat() if item.created_at else "2026-09-02"),
        }
        for item in production_orders[:8]
    ]

    production_schedule = [
        {
            "date": "2026-09-24",
            "line_name": "A线",
            "order_no": work_order["order_no"],
            "duration_days": 2,
            "status": work_order["status"],
        }
        for work_order in work_orders[:3]
    ]

    bom_alerts = [
        {
            "component_id": item.component_product_id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_cost": round(float(item.unit_cost or 0.0), 2),
            "level": "warning" if item.quantity >= 3 else "info",
            "message": "关键部件用量较高，建议提前补料" if item.quantity >= 3 else "材料可持续供应",
        }
        for item in bom_items[:5]
    ]

    if not bom_alerts:
        bom_alerts.append(
            {
                "component_id": 0,
                "product_id": 0,
                "quantity": 0,
                "unit_cost": 0.0,
                "level": "info",
                "message": "暂无 BOM 缺料预警，当前物料状态正常",
            }
        )

    line_board = [
        {
            "line_name": "A线",
            "utilization": 82,
            "output": 320,
            "status": "正常",
            "pending_orders": 2,
        },
        {
            "line_name": "B线",
            "utilization": 68,
            "output": 260,
            "status": "待补料",
            "pending_orders": 1,
        },
        {
            "line_name": "C线",
            "utilization": 74,
            "output": 290,
            "status": "正常",
            "pending_orders": 3,
        },
    ]

    auto_schedule = [
        {
            "order_no": item.order_no,
            "line_name": "A线" if idx % 3 == 0 else "B线" if idx % 3 == 1 else "C线",
            "start_date": "2026-09-24",
            "end_date": "2026-09-26",
            "load_rate": 85 if item.priority == "high" else 70 if item.priority == "normal" else 55,
        }
        for idx, item in enumerate(production_orders[:5])
    ]

    inventory_alerts = list_inventory_alerts(db)
    purchase_recommendation_list = purchase_recommendations(db)
    supplier_performance_data = supplier_performance(db)
    payment_alerts = finance_alerts(db)

    work_report_summary = {
        "total_work_orders": len(work_orders),
        "completed_today": sum(1 for item in work_orders if item["status"] == "completed"),
        "progress_rate": round((sum(1 for item in work_orders if item["status"] == "completed") / len(work_orders)) * 100, 1) if work_orders else 0.0,
        "avg_output": 280,
        "oee": 86.4,
    }

    gantt = [
        {
            "id": item.id,
            "title": item.order_no,
            "start": item.created_at.date().isoformat() if item.created_at else "2026-09-01",
            "end": (item.created_at.date().isoformat() if item.created_at else "2026-09-01"),
            "progress": 25 if item.status == "planned" else 60 if item.status == "in_progress" else 100,
            "status": item.status,
        }
        for item in production_orders[:8]
    ]

    return {
        "production_orders": [
            {
                "id": item.id,
                "order_no": item.order_no,
                "product_id": item.product_id,
                "bom_id": item.bom_id,
                "quantity": item.quantity,
                "status": item.status,
                "priority": item.priority,
                "note": item.note,
            }
            for item in production_orders
        ],
        "project_summary": project_summary,
        "high_priority_orders": high_priority_orders,
        "status_breakdown": status_breakdown,
        "milestones": milestones,
        "cost_summary": cost_summary,
        "gantt": gantt,
        "production_flow": production_flow,
        "recommendations": recommendations,
        "bom_summary": bom_summary,
        "work_orders": work_orders,
        "production_schedule": production_schedule,
        "bom_alerts": bom_alerts,
        "line_board": line_board,
        "auto_schedule": auto_schedule,
        "inventory_alerts": inventory_alerts,
        "purchase_recommendations": purchase_recommendation_list,
        "supplier_performance": supplier_performance_data,
        "payment_alerts": payment_alerts,
        "work_report_summary": work_report_summary,
    }


@router.get("/dashboard/executive")
def executive_dashboard(db: Session = Depends(get_db)) -> dict[str, object]:
    summary_data = summary(db)
    operations_data = dashboard_operations(db)
    payment_alerts = finance_alerts(db)
    inventory_alerts = list_inventory_alerts(db)

    kpis = [
        {"label": "销售额", "value": float(summary_data.get("sales_total") or 0.0), "unit": "CNY"},
        {"label": "采购额", "value": float(summary_data.get("purchase_total") or 0.0), "unit": "CNY"},
        {"label": "净利润", "value": float((summary_data.get("sales_total") or 0.0) - (summary_data.get("purchase_total") or 0.0)), "unit": "CNY"},
        {"label": "生产订单", "value": int(len(operations_data.get("production_orders") or [])), "unit": "orders"},
        {"label": "库存预警", "value": int(len(inventory_alerts)), "unit": "items"},
        {"label": "付款提醒", "value": int(len(payment_alerts)), "unit": "alerts"},
    ]

    status = {
        "health": "healthy" if len(payment_alerts) <= 2 and len(inventory_alerts) <= 3 else "watch",
        "production": operations_data.get("work_report_summary", {}).get("progress_rate", 0),
        "margin": round((float(summary_data.get("sales_total") or 0.0) - float(summary_data.get("purchase_total") or 0.0)) / float(summary_data.get("sales_total") or 1.0) * 100, 2) if (summary_data.get("sales_total") or 0.0) else 0.0,
        "risk_count": int(len(payment_alerts) + len(inventory_alerts)),
    }

    alerts = [
        {"title": "库存风险", "message": f"当前库存预警 {len(inventory_alerts)} 项，建议关注补货与积压。", "severity": "warning" if inventory_alerts else "info"},
        {"title": "付款提醒", "message": f"当前需要跟进 {len(payment_alerts)} 个付款事项。", "severity": "warning" if payment_alerts else "info"},
        {"title": "生产进度", "message": f"工单完成率 {operations_data.get('work_report_summary', {}).get('progress_rate', 0)}%，整体运行正常。", "severity": "info"},
    ]

    return {"kpis": kpis, "status": status, "alerts": alerts}


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, float | int]:
    customer_count = db.query(Customer).count()
    supplier_count = db.query(Supplier).count()
    product_count = db.query(Product).count()
    sales_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(SalesOrder.total_amount), 0))
        .scalar()
        or 0
    )
    purchase_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(PurchaseOrder.total_amount), 0))
        .scalar()
        or 0
    )
    finance_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(FinancialTransaction.amount), 0))
        .scalar()
        or 0
    )
    return {
        "customers": customer_count,
        "suppliers": supplier_count,
        "products": product_count,
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "finance_total": finance_total,
    }


@router.get("/reports/daily-export")
def export_daily_report(db: Session = Depends(get_db)) -> Response:
    today = date.today().isoformat()
    summary_data = summary(db)
    operations_data = dashboard_operations(db)
    work_report_summary = operations_data.get("work_report_summary") or {}

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "report_date",
        "sales_total",
        "purchase_total",
        "finance_total",
        "customers",
        "suppliers",
        "products",
        "production_orders",
        "completed_orders",
        "avg_progress",
        "material_cost",
        "labor_cost",
        "total_cost",
        "progress_rate",
        "oee",
    ])
    writer.writerow([
        today,
        float(summary_data.get("sales_total") or 0.0),
        float(summary_data.get("purchase_total") or 0.0),
        float(summary_data.get("finance_total") or 0.0),
        int(summary_data.get("customers") or 0),
        int(summary_data.get("suppliers") or 0),
        int(summary_data.get("products") or 0),
        int(len(operations_data.get("production_orders") or [])),
        int(work_report_summary.get("completed_today") or 0),
        float(operations_data.get("project_summary", {}).get("avg_progress") or 0.0),
        float(operations_data.get("cost_summary", {}).get("material_cost") or 0.0),
        float(operations_data.get("cost_summary", {}).get("labor_cost") or 0.0),
        float(operations_data.get("cost_summary", {}).get("total_cost") or 0.0),
        float(work_report_summary.get("progress_rate") or 0.0),
        float(work_report_summary.get("oee") or 0.0),
    ])

    csv_content = buffer.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="erp_daily_report_{today}.csv"'},
    )


# ============================================================================
# 融合改造 第 3.5 步：Excel 导入导出（档案批量建账 / 数据迁移）
# ============================================================================

# 可导入导出的档案类别 → (模型, 去重键, 中文名)
_IMPORT_TARGETS: dict[str, tuple[type, list[str], str]] = {
    "products": (Product, ["sku"], "商品档案"),
    "customers": (Customer, ["code"], "客户档案"),
    "suppliers": (Supplier, ["code"], "供应商档案"),
    "warehouses": (Warehouse, ["code"], "仓库档案"),
}


def _attachment_response(content: bytes, filename: str, media_type: str) -> Response:
    """带中文文件名的下载响应（ASCII 兜底 + RFC 5987，避免 header 编码错误）。"""
    from urllib.parse import quote

    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "download"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


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