"""全单据 Word 导出（任务 E · 2026-10-19）

    GET /exports/word/kinds                 四种单据的清单（前端按钮/菜单用）
    GET /exports/word/{kind}/{doc_id}       下载 .docx（kind = contract/quotation/inbound/statement）

为什么另开一个模块而不是塞进 `erp_export.py`：那边是**台账 xlsx**（一行一条，
给会计二次加工）；这里是**能盖章的正式文件**。两者的路由前缀也不同
（`/exports/{kind}` 只有两段，本模块是四段，不存在被吃掉的顺序问题 ——
但仍按"字面段先注册"的惯例，`kinds` 写在 `{kind}` 之前）。

## 两个刻意的取舍

1. **默认返回二进制**（`_attachment_response`，带 RFC 5987 中文文件名）。
   同一条接口加 `?as_json=true` 会返回 base64 —— 自测脚本和"公司电脑装了下载
   拦截插件"的场景用它：Word 的 MIME 不会被浏览器阅读器接管，但下载被插件
   改写的情况真实存在，留一条纯 JSON 的旁路比事后排查便宜。
2. **导出是只读操作**：不写库、不改状态、不产生流水。所以不做权限细分，
   但**必须带 token**（`get_db` 按 token 定 schema，跨账套导出的数据就是事故）。
"""

from __future__ import annotations

import base64
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _attachment_response
from app.core.company_info import load_company
from app.db.session import get_db
from app.models.contract import Contract, ContractItem
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.quotation import Quotation, QuotationItem
from app.models.statement import Statement, StatementItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.services import word_export

router = APIRouter(prefix="", tags=["erp"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_KINDS: list[dict[str, str]] = [
    {"kind": "contract", "label": "购销合同", "source": "合同台账"},
    {"kind": "quotation", "label": "报价单", "source": "报价单"},
    {"kind": "inbound", "label": "入库单", "source": "采购入库（订单也可导）"},
    {"kind": "statement", "label": "对账单", "source": "对账单"},
]


def _safe_filename(text: str, fallback: str) -> str:
    """文件名净化：去掉路径分隔符与 Windows 保留字符（中文保留）。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(text or "")).strip(" ._")
    return cleaned or fallback


@router.get("/exports/word/kinds", summary="可导出的单据类型（Word）")
def word_export_kinds() -> list[dict[str, str]]:
    return _KINDS


@router.post(
    "/exports/word/contract-document",
    summary="按内置范本生成合同正文 Word（表单草稿即可导，供确认修改）",
)
def export_contract_document_word(payload: dict, db: Session = Depends(get_db)):
    """业务流转第一步：**先 Word 确认，后 PDF 盖章**。

    请求体与 `/print/contract-document/pdf` 完全一致（合同表单 payload 或
    `{"contract_id": N}`），**不要求先保存合同**。排版走公文规范
    （宋体 12pt / 1.5 倍行距 / 首行缩进 / 两端对齐 / 细线表格 / 签章网格）。
    """
    from app.api.v1.routes.erp_print import _contract_document_payload
    from app.api.v1.routes.erp_common import resolve_contract_document_payload
    from app.services.contract_template import build_gongkuang_document
    from datetime import datetime as _dt

    data = _contract_document_payload(db, payload)
    data = resolve_contract_document_payload(db, data)
    document = build_gongkuang_document(data, data.get("items") or [])
    content = word_export.build_contract_document(document, load_company(db))
    if not content or not content.startswith(b"PK"):
        raise HTTPException(status_code=500, detail="Word 生成异常（内容为空或不是 docx 二进制）")
    raw_no = str(document.get("contract_no") or "").strip()
    if not raw_no or raw_no.startswith("（"):
        raw_no = f"draft_{_dt.now().strftime('%Y%m%d%H%M')}"
    filename = _safe_filename(f"合同正文-{raw_no}", "contract-draft") + ".docx"
    return _attachment_response(content, filename, DOCX_MEDIA_TYPE)


@router.get("/exports/word/{kind}/{doc_id}", summary="导出 Word（.docx）")
def export_word(
    kind: str,
    doc_id: int,
    db: Session = Depends(get_db),
    as_json: bool = Query(False, description="true 时返回 base64 JSON（下载被拦截时用）"),
):
    company = load_company(db)
    content, filename = _render(kind, doc_id, db, company)

    # 发出前最后一道自检：docx 是 zip 包，前 4 字节必然是 PK\x03\x04。
    # 生成为空/写坏时**宁可报 500 让人看见**，也不要把坏字节流当成文件发出去
    # —— 用户拿到一个打不开的 .docx，比看到一句报错难排查得多。
    if not content or len(content) < 4 or not content.startswith(b"PK"):
        raise HTTPException(
            status_code=500,
            detail="Word 生成异常（内容为空或不是 docx 二进制），请联系管理员",
        )

    if as_json:
        return {
            "filename": filename,
            "content_type": DOCX_MEDIA_TYPE,
            "size": len(content),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
    return _attachment_response(content, filename, DOCX_MEDIA_TYPE)


def _render(kind: str, doc_id: int, db: Session, company: dict) -> tuple[bytes, str]:
    """按 kind 取数并生成 docx。返回 (字节, 文件名)。"""
    key = (kind or "").strip().lower()

    if key == "contract":
        contract = db.get(Contract, doc_id)
        if contract is None:
            raise HTTPException(status_code=404, detail="合同不存在")
        items = (
            db.query(ContractItem)
            .filter(ContractItem.contract_id == doc_id)
            .order_by(ContractItem.id.asc())
            .all()
        )
        content = word_export.build_contract(contract, items, company)
        return content, _safe_filename(f"购销合同-{contract.contract_no}", f"contract-{doc_id}") + ".docx"

    if key == "quotation":
        quotation = db.get(Quotation, doc_id)
        if quotation is None:
            raise HTTPException(status_code=404, detail="报价单不存在")
        items = (
            db.query(QuotationItem)
            .filter(QuotationItem.quotation_id == doc_id)
            .order_by(QuotationItem.id.asc())
            .all()
        )
        content = word_export.build_quotation(quotation, items, company)
        return content, _safe_filename(f"报价单-{quotation.quote_no}", f"quotation-{doc_id}") + ".docx"

    if key == "inbound":
        order = db.get(PurchaseOrder, doc_id)
        if order is None:
            raise HTTPException(status_code=404, detail="单据不存在")
        items = (
            db.query(PurchaseOrderItem)
            .filter(PurchaseOrderItem.purchase_order_id == doc_id)
            .order_by(PurchaseOrderItem.id.asc())
            .all()
        )
        supplier = db.get(Supplier, order.supplier_id) if order.supplier_id else None
        warehouse = db.get(Warehouse, order.warehouse_id) if order.warehouse_id else None
        supplier_info = (
            {
                "name": supplier.name,
                "contact": getattr(supplier, "contact", "") or "",
                "phone": getattr(supplier, "phone", "") or "",
                "address": getattr(supplier, "address", "") or "",
            }
            if supplier
            else {}
        )
        content = word_export.build_inbound(
            order, items, company, supplier_info, warehouse.name if warehouse else ""
        )
        prefix = "采购订单" if str(order.doc_type or "") == "order" else "采购入库单"
        return content, _safe_filename(f"{prefix}-{order.order_no}", f"inbound-{doc_id}") + ".docx"

    if key == "statement":
        statement = db.get(Statement, doc_id)
        if statement is None:
            raise HTTPException(status_code=404, detail="对账单不存在")
        items = (
            db.query(StatementItem)
            .filter(StatementItem.statement_id == doc_id)
            .order_by(StatementItem.line_no.asc(), StatementItem.id.asc())
            .all()
        )
        content = word_export.build_statement(statement, items, company)
        return content, _safe_filename(f"对账单-{statement.statement_no}", f"statement-{doc_id}") + ".docx"

    raise HTTPException(
        status_code=400,
        detail="不支持导出这种单据（可选：contract / quotation / inbound / statement）",
    )
