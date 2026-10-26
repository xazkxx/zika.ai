"""全单据导出（第 13 批 · 第三阶段）—— 合同 / 报价单 / 对账单 台账 Excel。

为什么不塞进 `/excel/*`（`erp_dataio.py`）：
那边的 `GET /excel/kinds` 是「导入导出」面板的数据源，每一项都配着
「下载模板 / 导入」两个按钮，且 `_IMPORT_TARGETS` 里必须有对应模型。
单据是**只出不进**的（合同靠单据本身生成，不靠 Excel 导），塞进去会让
那个面板出现一个点了"导入"就 404 的类别。所以单独一组接口：

    GET /exports/kinds          导出类别清单（前端按钮用）
    GET /exports/{kind}         下载 xlsx（kind = contracts / quotations / statements）

日期过滤按各类别的业务日期字段（合同 `sign_date`、报价单 `quote_date`、
对账单 `period_end`），都是 `YYYY-MM-DD` 字符串，直接字符串比较即可 ——
不要在这里 `::date` 强转：空串会炸，而业务上"没填签订日期"的草稿合同
本来就应该在"不过滤"时出现。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _attachment_response
from app.db.session import get_db
from app.models.contract import (
    CONTRACT_DIRECTIONS,
    CONTRACT_OCR_STATUS,
    CONTRACT_STATUS,
    CONTRACT_TYPES,
    Contract,
    ContractItem,
    normalize_contract_type,
    normalize_direction,
)
from app.models.quotation import QUOTATION_STATUS, Quotation, QuotationItem
from app.models.statement import (
    STATEMENT_DIRECTIONS,
    STATEMENT_INVOICE_STATUS,
    STATEMENT_SOURCE_TYPES,
    STATEMENT_STATUS,
    Statement,
    StatementItem,
)
from app.services import doc_export
from app.services.excel_io import xlsx_media_type

router = APIRouter(prefix="", tags=["erp"])

_PARTY_TYPE_LABELS = {"customer": "客户", "supplier": "供应商"}


def _s(value) -> str:
    return "" if value is None else str(value)


def _label(mapping: dict[str, str], key, fallback: str = "") -> str:
    if key is None or key == "":
        return fallback
    return mapping.get(str(key), str(key))


# ---------------------------------------------------------------------------
# 各类别取数：返回 (主表行, 明细行)
# ---------------------------------------------------------------------------

def _load_contracts(
    db: Session, *, from_date: str | None, to_date: str | None, direction: str | None, status: str | None
) -> tuple[list[dict], list[dict]]:
    q = db.query(Contract)
    if direction:
        want = normalize_direction(direction)
        # 双保险：老数据 direction 可能是默认 out 而 contract_type=purchase，
        # 只按 direction 过滤会把这批合同整体漏掉（导出的台账"少了十几份合同"）
        q = q.filter(
            or_(Contract.direction == want, Contract.contract_type == normalize_contract_type(want))
        )
    if status:
        q = q.filter(Contract.status == status)
    if from_date:
        q = q.filter(Contract.sign_date >= from_date)
    if to_date:
        q = q.filter(Contract.sign_date <= to_date)
    rows = q.order_by(Contract.id.desc()).all()
    if not rows:
        return [], []

    ids = [c.id for c in rows]
    items: list[ContractItem] = (
        db.query(ContractItem)
        .filter(ContractItem.contract_id.in_(ids))
        .order_by(ContractItem.contract_id, ContractItem.id)
        .all()
    )
    grouped: dict[int, list[ContractItem]] = {}
    for it in items:
        grouped.setdefault(it.contract_id, []).append(it)

    headers: list[dict] = []
    for c in rows:
        headers.append(
            {
                "contract_no": _s(c.contract_no),
                "direction_label": _label(CONTRACT_DIRECTIONS, normalize_direction(c.direction, c.contract_type)),
                "type_label": _label(CONTRACT_TYPES, normalize_contract_type(c.direction, c.contract_type)),
                "title": _s(c.title),
                "party_type_label": _label(_PARTY_TYPE_LABELS, c.party_type),
                "party_name": _s(c.party_name),
                "party_contact": _s(c.party_contact),
                "party_phone": _s(c.party_phone),
                "sign_date": _s(c.sign_date),
                "valid_from": _s(c.valid_from),
                "valid_to": _s(c.valid_to),
                "total_amount": c.total_amount,
                "tax_rate": c.tax_rate,
                "tax_included_label": "含税" if c.is_tax_included else "不含税",
                "status_label": _label(CONTRACT_STATUS, c.status),
                "ocr_label": _label(CONTRACT_OCR_STATUS, c.ocr_status),
                "source_file_name": _s(c.source_file_name),
                "order_no": _s(c.order_no),
                "payment_terms": _s(c.payment_terms),
                "note": _s(c.note),
                "created_at": c.created_at,
                "_id": c.id,
            }
        )

    details: list[dict] = []
    for c in rows:
        for idx, it in enumerate(grouped.get(c.id, []), start=1):
            details.append(
                {
                    "contract_no": _s(c.contract_no),
                    "line_no": idx,
                    "product_name": _s(it.product_name),
                    "standards": _s(it.standards),
                    "unit": _s(it.unit),
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "amount": it.amount,
                    "note": _s(it.note),
                }
            )
    return headers, details


def _load_quotations(
    db: Session, *, from_date: str | None, to_date: str | None, direction: str | None, status: str | None
) -> tuple[list[dict], list[dict]]:
    # 报价单只有"给客户报价"一个方向（status 才是它的状态），direction 参数对它是空操作
    q = db.query(Quotation)
    if status:
        q = q.filter(Quotation.status == status)
    if from_date:
        q = q.filter(Quotation.quote_date >= from_date)
    if to_date:
        q = q.filter(Quotation.quote_date <= to_date)
    rows = q.order_by(Quotation.id.desc()).all()
    if not rows:
        return [], []

    ids = [r.id for r in rows]
    items: list[QuotationItem] = (
        db.query(QuotationItem)
        .filter(QuotationItem.quotation_id.in_(ids))
        .order_by(QuotationItem.quotation_id, QuotationItem.id)
        .all()
    )
    grouped: dict[int, list[QuotationItem]] = {}
    for it in items:
        grouped.setdefault(it.quotation_id, []).append(it)

    # 关联合同编号：报价单只存了 contract_id（存量表故意不加外键），
    # 这里一次性查出来补成编号，"合同编号"列才对人有意义
    contract_ids = [r.contract_id for r in rows if r.contract_id]
    contract_no: dict[int, str] = {}
    if contract_ids:
        contract_no = {
            c.id: _s(c.contract_no)
            for c in db.query(Contract).filter(Contract.id.in_(contract_ids)).all()
        }

    headers: list[dict] = []
    for r in rows:
        headers.append(
            {
                "quote_no": _s(r.quote_no),
                "customer_name": _s(r.customer_name),
                "contact": _s(r.contact),
                "contact_phone": _s(r.contact_phone),
                "customer_address": _s(r.customer_address),
                "quote_date": _s(r.quote_date),
                "valid_until": _s(r.valid_until),
                "businesser": _s(r.businesser),
                "payment_method": _s(r.payment_method),
                "transport_method": _s(r.transport_method),
                "delivery_place": _s(r.delivery_place),
                "total_quantity": r.total_quantity,
                "total_amount": r.total_amount,
                "status_label": _label(QUOTATION_STATUS, r.status),
                "contract_no": contract_no.get(r.contract_id or 0, ""),
                "order_no": _s(r.order_no),
                "note": _s(r.note),
                "created_at": r.created_at,
                "_id": r.id,
            }
        )

    details: list[dict] = []
    for r in rows:
        for idx, it in enumerate(grouped.get(r.id, []), start=1):
            details.append(
                {
                    "quote_no": _s(r.quote_no),
                    "line_no": idx,
                    "product_name": _s(it.product_name),
                    "standards": _s(it.standards),
                    "unit": _s(it.unit),
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "amount": it.amount,
                    "note": _s(it.note),
                }
            )
    return headers, details


def _load_statements(
    db: Session, *, from_date: str | None, to_date: str | None, direction: str | None, status: str | None
) -> tuple[list[dict], list[dict]]:
    q = db.query(Statement)
    if direction:
        q = q.filter(Statement.direction == normalize_direction(direction))
    if status:
        q = q.filter(Statement.status == status)
    if from_date:
        q = q.filter(Statement.period_end >= from_date)
    if to_date:
        q = q.filter(Statement.period_end <= to_date)
    rows = q.order_by(Statement.id.desc()).all()
    if not rows:
        return [], []

    # 头部合计是冗余快照 → 直接读库里的值，**绝不在导出时重算**
    # （发出的对账单是法律凭证，导出/打印必须与当时确认的数一致）
    headers: list[dict] = []
    for r in rows:
        headers.append(
            {
                "statement_no": _s(r.statement_no),
                "direction_label": _label(STATEMENT_DIRECTIONS, r.direction),
                "party_type_label": _label(_PARTY_TYPE_LABELS, r.party_type),
                "party_name": _s(r.party_name),
                "party_tax_no": _s(r.party_tax_no),
                "period_start": _s(r.period_start),
                "period_end": _s(r.period_end),
                "statement_date": _s(r.statement_date),
                "opening_balance": r.opening_balance,
                "contract_amount": r.contract_amount,
                "invoiced_amount": r.invoiced_amount,
                "uninvoiced_amount": r.uninvoiced_amount,
                "received_amount": r.received_amount,
                "prepaid_received": r.prepaid_received,
                "prepaid_applied": r.prepaid_applied,
                "prepaid_balance": r.prepaid_balance,
                "receivable_balance": r.receivable_balance,
                "outstanding_amount": r.outstanding_amount,
                "item_count": r.item_count,
                "status_label": _label(STATEMENT_STATUS, r.status),
                "confirmed_at": r.confirmed_at,
                "note": _s(r.note),
                "_id": r.id,
            }
        )

    details: list[dict] = []
    for r in rows:
        for it in r.items:
            details.append(
                {
                    "statement_no": _s(r.statement_no),
                    "line_no": it.line_no,
                    "business_date": _s(it.business_date),
                    "source_type_label": _label(STATEMENT_SOURCE_TYPES, it.source_type),
                    "source_no": _s(it.source_no),
                    "contract_no": _s(it.contract_no),
                    "summary": _s(it.summary),
                    "contract_amount": it.contract_amount,
                    "invoiced_amount": it.invoiced_amount,
                    "uninvoiced_amount": it.uninvoiced_amount,
                    "received_amount": it.received_amount,
                    "prepaid_received": it.prepaid_received,
                    "prepaid_applied": it.prepaid_applied,
                    "outstanding_amount": it.outstanding_amount,
                    "invoice_status_label": _label(STATEMENT_INVOICE_STATUS, it.invoice_status),
                    "invoice_count": it.invoice_count,
                    "note": _s(it.note),
                }
            )
    return headers, details


_LOADERS = {
    "contracts": _load_contracts,
    "quotations": _load_quotations,
    "statements": _load_statements,
}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.get("/exports/kinds")
def list_export_kinds() -> list[dict[str, object]]:
    """列出支持导出的单据类别（只出不进，与 /excel/kinds 是两套）。"""
    return doc_export.kinds()


@router.get("/exports/{kind}")
def export_documents(
    kind: str,
    from_date: str | None = Query(None, description="起始日期 YYYY-MM-DD（按各类别业务日期）"),
    to_date: str | None = Query(None, description="截止日期 YYYY-MM-DD"),
    direction: str | None = Query(None, description="in / out（仅合同、对账单有效）"),
    status: str | None = Query(None, description="单据状态原值，如 draft / confirmed"),
    db: Session = Depends(get_db),
) -> Response:
    """导出单据台账 xlsx（主表 + 明细两张工作表）。"""
    if kind not in doc_export.DOC_KINDS:
        raise HTTPException(status_code=404, detail=f"不支持的单据导出类别：{kind}")
    if direction and direction not in ("in", "out"):
        raise HTTPException(status_code=400, detail="direction 只能是 in 或 out")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=400, detail="起始日期不能晚于截止日期")

    headers, details = _LOADERS[kind](
        db, from_date=from_date, to_date=to_date, direction=direction, status=status
    )

    # 过滤条件写进副标题：会计拿到文件要能看出"这张表是筛过的"
    conds: list[str] = []
    if from_date or to_date:
        conds.append(f"日期 {from_date or '（起）'} ~ {to_date or '（止）'}")
    if direction:
        conds.append(f"方向 {direction}")
    if status:
        conds.append(f"状态 {status}")
    subtitle = "筛选：" + "，".join(conds) if conds else ""

    for row in headers:
        row.pop("_id", None)

    data = doc_export.build(kind, headers, details, subtitle=subtitle)
    return _attachment_response(data, doc_export.filename(kind), xlsx_media_type())
