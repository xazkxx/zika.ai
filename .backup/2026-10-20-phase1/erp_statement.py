"""增强版对账单（第 13 批 · 第二阶段 · 模块 4 的路由层）。

## 与普通"应收应付明细表"的区别

一张对账单回答的是**对账区间内的四件事**，不是简单列流水：

    未开票金额        = 合同金额 − 已开票
    剩余未收 / 未付    = 合同金额 − 已收/已付 − 预收已核销
    应收账款余额      = 期初应收 + 本期已开票 − 本期已收 − 预收已核销
    预收账款余额      = 本期预收 − 预收已核销

`剩余未收/付` 与 `应收余额` **不是同一个数**：前者只针对本期合同，后者含期初与往期。

## 三条硬规则

1. **头部合计是冗余快照**（`statements` 表里就是 10 个 numeric 列），
   不在查询时实时算。对账单一经发出是法律凭证，事后补一张发票不能让
   去年 12 月那张对账单自己变数。重算只能走 **显式** `POST /statements/{id}/recalc`。
2. **公式只有一份实现**：全部调用 `app/models/statement.py` 里的
   `compute_totals()` / `derive_item_amounts()` / `infer_invoice_status()`
   （Decimal 计算）。这里不写第二份 `round(float(...))`。
3. **已确认 / 已发送的对账单不能改明细**：`status` 一旦离开 `draft`，
   明细与合计都锁死，只能"作废重开"。否则两份打印稿会不一致，而对账单正是
   用来"证明双方账目一致"的东西。

## 自动生成（`POST /statements/generate`）

按「往来单位 + 对账区间」把三类数据汇总成一张草稿：

| 来源 | 落到哪一列 | 判据 |
|---|---|---|
| 合同 `contracts` | `contract_amount` | `party_type` + `party_id` + `direction` + `sign_date ∈ 区间` |
| 发票 `invoices` | `invoiced_amount` | `counterparty_name` = 对方名称 + `direction` 同向 + `issue_date ∈ 区间` |
| 收付款 `financial_transactions` | `received_amount` | `transaction_type ∈ (receipt, payment)` + `customer_id`/`supplier_id` + `occurred_at ∈ 区间` |

发票没有 `customer_id`（第 11 批之前导入的数据只有 `counterparty_name`），
所以只能按名称匹配 —— 因此**生成的是草稿**，必须人工核一遍再确认。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _next_doc_no, _paginate
from app.db.session import get_db
from app.models.contract import CONTRACT_DIRECTIONS, Contract, normalize_direction
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.invoice import Invoice
from app.models.statement import (
    STATEMENT_INVOICE_STATUS,
    STATEMENT_SOURCE_TYPES,
    STATEMENT_STATUS,
    Statement,
    StatementItem,
    compute_totals,
)
from app.models.supplier import Supplier
from app.schemas import (
    StatementCreate,
    StatementItemCreate,
    StatementItemRead,
    StatementRead,
)

router = APIRouter(prefix="", tags=["erp"])


# ===========================================================================
# 内部辅助
# ===========================================================================


def _statement_or_404(db: Session, statement_id: int) -> Statement:
    row = db.get(Statement, statement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="对账单不存在")
    return row


def _statement_items(db: Session, statement_id: int) -> list[StatementItem]:
    return (
        db.query(StatementItem)
        .filter(StatementItem.statement_id == statement_id)
        .order_by(StatementItem.line_no, StatementItem.id)
        .all()
    )


def _item_payload(row: StatementItem) -> dict[str, object]:
    return {
        "id": row.id,
        "statement_id": row.statement_id,
        "line_no": row.line_no,
        "business_date": row.business_date,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "contract_id": row.contract_id,
        "contract_no": row.contract_no,
        "summary": row.summary,
        "contract_amount": row.contract_amount,
        "invoiced_amount": row.invoiced_amount,
        "uninvoiced_amount": row.uninvoiced_amount,
        "received_amount": row.received_amount,
        "prepaid_received": row.prepaid_received,
        "prepaid_applied": row.prepaid_applied,
        "outstanding_amount": row.outstanding_amount,
        "invoice_status": row.invoice_status,
        "invoice_count": row.invoice_count,
        "note": row.note,
        "created_at": row.created_at,
    }


def _statement_payload(row: Statement, items: list[StatementItem]) -> dict[str, object]:
    data = {column.name: getattr(row, column.name) for column in Statement.__table__.columns}
    data["items"] = [_item_payload(item) for item in items]
    return data


def _assert_editable(row: Statement) -> None:
    """非草稿态不许改明细/合计。理由见模块头第 3 条。"""
    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"对账单 {row.statement_no} 已是「{STATEMENT_STATUS.get(row.status, row.status)}」状态，"
                "不能再修改明细或重算。如需调整，请作废后重新生成。"
            ),
        )


def _apply_totals(row: Statement, items: list[StatementItem]) -> dict[str, object]:
    """把明细汇总写进头部金额（**唯一口径**：`compute_totals`）。

    ⚠️ 刻意**不回写 `opening_balance`**：它是**入参**（来自客户/供应商期初或用户手填），
    不是算出来的合计。`compute_totals()` 的返回值里带着它只是为了方便调用方，
    照着全量 setattr 就会把"期初"变成"上一次计算用的期初" —— 一旦别处传了 0，
    库里存的期初就被悄悄抹成 0 了（反证 C 真的踩到：重算之后应收余额少了整整一个期初）。
    """
    totals = compute_totals(items, opening_balance=row.opening_balance or 0)
    for field, value in totals.items():
        if field == "opening_balance":
            continue
        setattr(row, field, value)
    row.item_count = len(items)
    return totals


def _item_from_payload(statement_id: int, data: dict[str, object], line_no: int) -> StatementItem:
    """明细行落库：计算字段用 schema 已校验过的值（它调的也是模型里的同一份公式）。"""
    return StatementItem(
        statement_id=statement_id,
        line_no=int(data.get("line_no") or line_no),
        business_date=data.get("business_date"),
        source_type=data.get("source_type"),
        source_id=int(data["source_id"]) if data.get("source_id") not in (None, "") else None,
        source_no=data.get("source_no"),
        contract_id=int(data["contract_id"]) if data.get("contract_id") not in (None, "") else None,
        contract_no=data.get("contract_no"),
        summary=data.get("summary"),
        contract_amount=data.get("contract_amount") or 0,
        invoiced_amount=data.get("invoiced_amount") or 0,
        uninvoiced_amount=data.get("uninvoiced_amount") or 0,
        received_amount=data.get("received_amount") or 0,
        prepaid_received=data.get("prepaid_received") or 0,
        prepaid_applied=data.get("prepaid_applied") or 0,
        outstanding_amount=data.get("outstanding_amount") or 0,
        invoice_status=data.get("invoice_status") or "none",
        invoice_count=int(data.get("invoice_count") or 0),
        note=data.get("note"),
    )


# ===========================================================================
# 字典 / 列表（**注意：字面量路径必须写在 `/{statement_id}` 之前**）
# ===========================================================================


@router.get("/statements/meta")
def statement_meta() -> dict[str, object]:
    return {
        "directions": [
            {"code": code, "label": label} for code, label in CONTRACT_DIRECTIONS.items()
        ],
        "party_types": [
            {"code": "customer", "label": "客户（应收）"},
            {"code": "supplier", "label": "供应商（应付）"},
        ],
        "invoice_statuses": [
            {"code": code, "label": label} for code, label in STATEMENT_INVOICE_STATUS.items()
        ],
        "statuses": [{"code": code, "label": label} for code, label in STATEMENT_STATUS.items()],
        "currencies": ["CNY"],
        # 明细行的来源类型 —— 用模型里的字典，别在这里再抄一份
        "source_types": [
            {"code": code, "label": label} for code, label in STATEMENT_SOURCE_TYPES.items()
        ],
    }


@router.get("/statements")
def list_statements(
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
    party_type: str | None = Query(None),
    party_id: int | None = Query(None),
    status_value: str | None = Query(None, alias="status"),
    period_from: str | None = Query(None, description="按 period_end >= 过滤，YYYY-MM-DD"),
    period_to: str | None = Query(None, description="按 period_start <= 过滤，YYYY-MM-DD"),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[StatementRead]:
    query = db.query(Statement).order_by(Statement.id.desc())
    # `direction` 三态：不传 / 传 "all" = 不过滤（台账全景）；传 out / in = 只看该方向。
    # ⚠️ 必须先判 "all" 再 normalize —— normalize_direction("all") 会**静默回落到 out**，
    #    那样"全部"就变成了"只有应收"，页面上看起来像丢了数据。
    scope = str(direction or "").strip().lower()
    if scope and scope not in ("all", "全部"):
        query = query.filter(Statement.direction == normalize_direction(direction=scope))
    if party_type:
        query = query.filter(Statement.party_type == party_type)
    if party_id:
        query = query.filter(Statement.party_id == party_id)
    if status_value:
        query = query.filter(Statement.status == status_value)
    if period_from:
        query = query.filter(Statement.period_end >= period_from)
    if period_to:
        query = query.filter(Statement.period_start <= period_to)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Statement.statement_no.ilike(like),
                Statement.party_name.ilike(like),
                Statement.note.ilike(like),
            )
        )
    rows = _paginate(query, skip, limit).all()
    return [_statement_payload(row, _statement_items(db, row.id)) for row in rows]


@router.post("/statements/generate", summary="按往来单位 + 期间自动生成对账单草稿")
def generate_statement(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """把「合同 + 发票 + 收付款」汇总成一张**草稿**。

    入参（都能省，省了就用默认）：
        {
          "direction": "out",            # out 应收 / in 应付
          "party_type": "customer",      # customer / supplier（与 direction 必须自洽）
          "party_id": 3,
          "period_start": "2026-01-01",
          "period_end": "2026-12-31",
          "opening_balance": 0,          # 不传则取客户/供应商的期初
          "include_contracts": true,
          "include_invoices": true,
          "include_payments": true
        }
    """
    direction = normalize_direction(direction=payload.get("direction") or "out")
    party_type = str(payload.get("party_type") or ("customer" if direction == "out" else "supplier"))
    if direction == "out" and party_type != "customer":
        raise HTTPException(status_code=400, detail="应收（out）对账单的往来单位必须是客户")
    if direction == "in" and party_type != "supplier":
        raise HTTPException(status_code=400, detail="应付（in）对账单的往来单位必须是供应商")

    party_id = payload.get("party_id")
    if party_id in (None, ""):
        raise HTTPException(status_code=400, detail="缺少 party_id（要对哪个客户/供应商）")
    try:
        party_id = int(party_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="party_id 必须是整数") from exc

    period_start = str(payload.get("period_start") or "").strip()
    period_end = str(payload.get("period_end") or "").strip()
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="缺少对账区间（period_start / period_end）")
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="对账区间的开始日期不能晚于结束日期")

    model = Customer if party_type == "customer" else Supplier
    party = db.get(model, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="对方单位档案不存在")

    party_name = getattr(party, "name", None) or ""
    party_tax_no = getattr(party, "tax_no", None)
    opening = payload.get("opening_balance")
    if opening in (None, ""):
        opening = getattr(party, "init_receivable" if party_type == "customer" else "init_payable", 0) or 0

    lines: list[dict[str, object]] = []

    # —— ① 合同 ——
    if payload.get("include_contracts", True):
        contracts = (
            db.query(Contract)
            .filter(
                Contract.party_type == party_type,
                Contract.party_id == party_id,
                Contract.direction == direction,
                Contract.sign_date >= period_start,
                Contract.sign_date <= period_end,
                Contract.status != "void",
            )
            .order_by(Contract.sign_date, Contract.id)
            .all()
        )
        for contract in contracts:
            lines.append(
                {
                    "business_date": contract.sign_date,
                    "source_type": "contract",
                    "source_id": contract.id,
                    "source_no": contract.contract_no,
                    "contract_id": contract.id,
                    "contract_no": contract.contract_no,
                    "summary": contract.title or f"合同 {contract.contract_no}",
                    "contract_amount": contract.total_amount or 0,
                    "invoiced_amount": 0,
                    "received_amount": 0,
                    "prepaid_received": 0,
                    "prepaid_applied": 0,
                    "invoice_count": 0,
                }
            )

    # —— ② 发票（只有 counterparty_name，没有 party_id → 按名称匹配）——
    if payload.get("include_invoices", True):
        invoice_query = db.query(Invoice).filter(
            Invoice.direction == direction,
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
        if party_name:
            invoice_query = invoice_query.filter(Invoice.counterparty_name == party_name)
        invoices = invoice_query.all()
        invoice_total = sum(float(row.total_amount or 0) for row in invoices)
        if invoices:
            lines.append(
                {
                    "business_date": period_end,
                    "source_type": "invoice",
                    "source_id": None,
                    "source_no": None,
                    "contract_id": None,
                    "contract_no": None,
                    "summary": f"本期{'销项' if direction == 'out' else '进项'}发票 {len(invoices)} 张（未逐张匹配到合同）",
                    "contract_amount": 0,
                    "invoiced_amount": round(invoice_total, 2),
                    "received_amount": 0,
                    "prepaid_received": 0,
                    "prepaid_applied": 0,
                    "invoice_count": len(invoices),
                }
            )

    # —— ③ 收付款 ——
    if payload.get("include_payments", True):
        party_column = (
            FinancialTransaction.customer_id
            if party_type == "customer"
            else FinancialTransaction.supplier_id
        )
        flows = (
            db.query(FinancialTransaction)
            .filter(
                party_column == party_id,
                FinancialTransaction.transaction_type.in_(("receipt", "payment")),
                FinancialTransaction.occurred_at >= period_start,
                FinancialTransaction.occurred_at <= period_end,
            )
            .all()
        )
        flow_total = sum(float(row.amount or 0) for row in flows)
        if flows:
            lines.append(
                {
                    "business_date": period_end,
                    "source_type": "receipt" if party_type == "customer" else "payment",
                    "source_id": None,
                    "source_no": None,
                    "contract_id": None,
                    "contract_no": None,
                    "summary": f"本期{'收款' if party_type == 'customer' else '付款'} {len(flows)} 笔",
                    "contract_amount": 0,
                    "invoiced_amount": 0,
                    "received_amount": round(flow_total, 2),
                    "prepaid_received": 0,
                    "prepaid_applied": 0,
                    "invoice_count": 0,
                }
            )

    if not lines:
        raise HTTPException(
            status_code=404,
            detail=(
                f"该区间内没有找到「{party_name}」的合同 / 发票 / 收付款记录，"
                "对账单没有可列的内容。请检查对账区间，或手工新建后逐行录入。"
            ),
        )

    # 逐行补算 uninvoiced / outstanding / invoice_status（Schema 的 _derive 是同一份公式）
    item_schemas = []
    for index, line in enumerate(lines, start=1):
        line["line_no"] = index
        item_schemas.append(StatementItemCreate(**line))

    statement = Statement(
        statement_no=_next_doc_no(db, Statement, "DZ", field="statement_no"),
        direction=direction,
        party_type=party_type,
        party_id=party_id,
        party_name=party_name,
        party_tax_no=party_tax_no,
        period_start=period_start,
        period_end=period_end,
        statement_date=datetime.now().strftime("%Y-%m-%d"),
        currency=str(payload.get("currency") or "CNY"),
        opening_balance=opening or 0,
        status="draft",
        note=payload.get("note"),
        created_by=payload.get("created_by"),
    )
    db.add(statement)
    db.flush()

    rows = [_item_from_payload(statement.id, item.model_dump(), index)
            for index, item in enumerate(item_schemas, start=1)]
    db.add_all(rows)
    _apply_totals(statement, rows)
    db.commit()
    db.refresh(statement)

    return {
        **_statement_payload(statement, _statement_items(db, statement.id)),
        "generated_lines": len(rows),
        "message": f"已生成对账单草稿 {statement.statement_no}（{len(rows)} 行），请人工核对后确认",
    }


@router.get("/statements/{statement_id}", response_model=StatementRead)
def get_statement(statement_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    row = _statement_or_404(db, statement_id)
    return _statement_payload(row, _statement_items(db, statement_id))


@router.get(
    "/statements/{statement_id}/preview",
    summary="对账单详情内嵌预览：往来账「期初 → 逐笔 → 期末」",
)
def preview_statement(statement_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """把这张对账单涉及的往来账底稿摊开给用户看。

    ## 为什么要有这个接口

    对账单是**开票口径**（期末 = 期初 + 已开票 − 已收 − 预收核销），
    往来账是**流水口径**（期末 = 期初 + 本期增加 − 本期减少）。
    对账员真正要干的活是"把这两个数对上"。以前这两块在页面上完全分离：
    对账单页看不到底稿，往来对账页看不到单据 —— 中间靠人脑接。

    所以这里**只做一件事**：把同一往来单位、同一期间的往来账摊开，
    连同两个口径的期末余额与差额一起返回。**不自动调平**（差额是业务事实，
    不是可以四舍五入掉的误差）。

    ## 复用而非重写

    `finance_reconciliation()` 已经是「期初 → 逐笔 → 期末」的唯一实现
    （打印中心 B1/B2 模板也用它）。这里直接调用，不写第二份累加逻辑 ——
    否则哪天口径变了，预览会和打印稿对不上。
    """
    row = _statement_or_404(db, statement_id)
    party_type = "supplier" if (row.party_type or "").strip().lower() == "supplier" else "customer"

    empty = {
        "statement_id": row.id,
        "statement_no": row.statement_no,
        "available": False,
        "party_type": party_type,
        "party_id": row.party_id,
        "party_name": row.party_name,
    }
    if not row.party_id:
        return {**empty, "reason": "这张对账单没有关联往来单位档案（可能是手工建的），无法取往来账底稿。"}

    # 局部 import：`erp_finance` 在模块级 import 会拖进整个财务域，
    # 而这条路径只在打开详情预览时才走。（同 erp_print.py 的做法）
    from app.api.v1.routes.erp_finance import finance_reconciliation

    try:
        ledger = finance_reconciliation(
            party_type,
            int(row.party_id),
            from_date=row.period_start,
            to_date=row.period_end,
            db=db,
        )
    except HTTPException as exc:
        return {**empty, "reason": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001 —— 预览是辅助信息，绝不能把它变成"打不开详情"
        return {**empty, "reason": f"取往来账底稿失败：{exc}"}

    summary = ledger.get("summary") or {}
    ledger_closing = round(float(summary.get("closing_balance") or 0), 2)
    statement_closing = round(float(row.receivable_balance or 0), 2)
    diff = round(statement_closing - ledger_closing, 2)

    return {
        "statement_id": row.id,
        "statement_no": row.statement_no,
        "available": True,
        "party_type": party_type,
        "party_id": row.party_id,
        "party_name": ledger.get("party", {}).get("name") or row.party_name,
        "period": {"from": row.period_start, "to": row.period_end},
        "ledger": {
            "opening_balance": round(float(summary.get("opening_balance") or 0), 2),
            "increase_total": round(float(summary.get("increase_total") or 0), 2),
            "decrease_total": round(float(summary.get("decrease_total") or 0), 2),
            "closing_balance": ledger_closing,
            "closing_balance_upper": summary.get("closing_balance_upper"),
            "rows": ledger.get("rows") or [],
        },
        "statement_side": {
            "opening_balance": round(float(row.opening_balance or 0), 2),
            "invoiced_amount": round(float(row.invoiced_amount or 0), 2),
            "received_amount": round(float(row.received_amount or 0), 2),
            "prepaid_applied": round(float(row.prepaid_applied or 0), 2),
            "receivable_balance": statement_closing,
        },
        "diff": diff,
        "diff_reason": (
            "两个口径完全一致。"
            if abs(diff) < 0.005
            else "对账单按开票口径、往来账按收付款流水口径，差额本身是业务事实（如未开票已收、发票未入账），请人工核对，系统不自动调平。"
        ),
    }


# ===========================================================================
# 创建 / 修改 / 重算 / 状态 / 删除
# ===========================================================================


@router.post("/statements", response_model=StatementRead, status_code=status.HTTP_201_CREATED)
def create_statement(payload: StatementCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    """手工新建一张对账单。

    头部合计**不收客户端传的值**：Schema 里根本没有这些字段，
    全部由 `compute_totals()` 从明细算出来（见 DESIGN-PHASE1.md §5.3）。
    """
    statement_no = (payload.statement_no or "").strip() or _next_doc_no(
        db, Statement, "DZ", field="statement_no"
    )
    if db.query(Statement).filter(Statement.statement_no == statement_no).first():
        raise HTTPException(status_code=400, detail="对账单号已存在")

    row = Statement(
        statement_no=statement_no,
        direction=payload.direction,
        party_type=payload.party_type,
        party_id=payload.party_id,
        party_name=payload.party_name,
        party_tax_no=payload.party_tax_no,
        period_start=payload.period_start,
        period_end=payload.period_end,
        statement_date=payload.statement_date or datetime.now().strftime("%Y-%m-%d"),
        currency=payload.currency or "CNY",
        opening_balance=payload.opening_balance or 0,
        status=payload.status or "draft",
        note=payload.note,
        created_by=payload.created_by,
    )
    db.add(row)
    db.flush()

    items = [
        _item_from_payload(row.id, item.model_dump(), index)
        for index, item in enumerate(payload.items, start=1)
    ]
    db.add_all(items)
    _apply_totals(row, items)
    db.commit()
    db.refresh(row)
    return _statement_payload(row, _statement_items(db, row.id))


@router.patch("/statements/{statement_id}", response_model=StatementRead)
def update_statement(
    statement_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """改表头信息；传了 `items` 就整单替换明细并重算合计。

    ⚠️ 非草稿态只允许改 `note`（备注不影响金额与凭证效力）。
    """
    row = _statement_or_404(db, statement_id)
    wants_items = isinstance(payload.get("items"), list)
    if wants_items or payload.get("opening_balance") is not None:
        _assert_editable(row)

    for field in ("party_name", "party_tax_no", "period_start", "period_end", "statement_date", "note"):
        if field in payload:
            setattr(row, field, payload.get(field))

    if "opening_balance" in payload:
        raw = payload.get("opening_balance")
        row.opening_balance = 0 if raw in ("", None) else float(raw)

    items = _statement_items(db, row.id)
    if wants_items:
        # ⚠️ 批量 DELETE 绕过了 session；`Statement.items` 是 lazy="selectin"，
        #    集合里还挂着刚被删掉的对象。不 expire 的话，commit 时 delete-orphan
        #    会再删一遍（0 行匹配）并抛 SAWarning。
        db.query(StatementItem).filter(StatementItem.statement_id == row.id).delete(
            synchronize_session=False
        )
        db.expire(row, ["items"])
        items = []
        for index, line in enumerate(payload["items"], start=1):
            line_data = line if isinstance(line, dict) else {}
            # 走一遍 schema：算 uninvoiced / outstanding / invoice_status
            checked = StatementItemCreate(**line_data)
            items.append(_item_from_payload(row.id, checked.model_dump(), index))
        db.add_all(items)

    _apply_totals(row, items)
    db.commit()
    db.refresh(row)
    return _statement_payload(row, _statement_items(db, row.id))


@router.post("/statements/{statement_id}/recalc", summary="重算对账单合计")
def recalc_statement(statement_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """按当前明细重算头部 10 个金额。

    这是**唯一**能让一张已发出对账单数字变化的入口 —— 刻意做成显式动作，
    而不是每次读取都实时算（见模块头第 1 条）。
    """
    row = _statement_or_404(db, statement_id)
    _assert_editable(row)

    items = _statement_items(db, row.id)
    totals = _apply_totals(row, items)
    db.commit()
    db.refresh(row)
    return {
        "statement_id": row.id,
        "statement_no": row.statement_no,
        "item_count": row.item_count,
        "totals": {key: float(value) for key, value in totals.items()},
        "message": f"已按 {len(items)} 行明细重算",
    }


@router.patch("/statements/{statement_id}/status", response_model=StatementRead)
def update_statement_status(
    statement_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """状态流转：draft → confirmed → sent；任意态 → void（作废）。"""
    row = _statement_or_404(db, statement_id)
    target = str(payload.get("status") or "").strip().lower()
    if target not in STATEMENT_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"状态只能是 {' / '.join(STATEMENT_STATUS)}",
        )
    if row.status == target:
        return _statement_payload(row, _statement_items(db, row.id))
    if row.status == "void" and target != "void":
        raise HTTPException(status_code=409, detail="已作废的对账单不能改回其他状态，请重新生成")

    row.status = target
    if target == "confirmed":
        row.confirmed_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _statement_payload(row, _statement_items(db, row.id))


@router.delete("/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_statement(statement_id: int, db: Session = Depends(get_db)) -> Response:
    """删除对账单（明细跟着走，`ON DELETE CASCADE`）。

    **已确认/已发送的不许删**：那是已经发给对方的凭证，删了以后双方对不上，
    正确做法是置为作废（保留痕迹）。
    """
    row = _statement_or_404(db, statement_id)
    if row.status in ("confirmed", "sent"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"对账单 {row.statement_no} 已{'确认' if row.status == 'confirmed' else '发送'}，"
                "不能删除。请改为置为「作废」，以保留对账痕迹。"
            ),
        )
    db.query(StatementItem).filter(StatementItem.statement_id == statement_id).delete(
        synchronize_session=False
    )
    # 同上：先把集合从 session 里摘掉，再删本体，避免 delete-orphan 二次删除
    db.expire(row, ["items"])
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# 明细行：增 / 改 / 删（都只在草稿态可用）
# ===========================================================================


@router.post("/statements/{statement_id}/items", response_model=StatementItemRead,
             status_code=status.HTTP_201_CREATED)
def add_statement_item(
    statement_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    row = _statement_or_404(db, statement_id)
    _assert_editable(row)

    checked = StatementItemCreate(**payload)
    line_no = int(checked.line_no or 0) or (len(_statement_items(db, row.id)) + 1)
    item = _item_from_payload(row.id, checked.model_dump(), line_no)
    db.add(item)
    db.flush()
    _apply_totals(row, _statement_items(db, row.id))
    db.commit()
    db.refresh(item)
    return _item_payload(item)


@router.patch("/statements/{statement_id}/items/{item_id}", response_model=StatementItemRead)
def update_statement_item(
    statement_id: int, item_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    row = _statement_or_404(db, statement_id)
    _assert_editable(row)
    item = db.get(StatementItem, item_id)
    if item is None or item.statement_id != statement_id:
        raise HTTPException(status_code=404, detail="明细行不存在（或不属于这张对账单）")

    merged = _item_payload(item)
    merged.update(payload)
    checked = StatementItemCreate(**merged)
    for field, value in checked.model_dump().items():
        if field in ("line_no", "business_date", "source_type", "source_id", "source_no",
                     "contract_id", "contract_no", "summary", "contract_amount",
                     "invoiced_amount", "uninvoiced_amount", "received_amount",
                     "prepaid_received", "prepaid_applied", "outstanding_amount",
                     "invoice_status", "invoice_count", "note"):
            setattr(item, field, value)

    db.flush()
    _apply_totals(row, _statement_items(db, row.id))
    db.commit()
    db.refresh(item)
    return _item_payload(item)


@router.delete("/statements/{statement_id}/items/{item_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_statement_item(
    statement_id: int, item_id: int, db: Session = Depends(get_db)
) -> Response:
    row = _statement_or_404(db, statement_id)
    _assert_editable(row)
    item = db.get(StatementItem, item_id)
    if item is None or item.statement_id != statement_id:
        raise HTTPException(status_code=404, detail="明细行不存在（或不属于这张对账单）")
    db.delete(item)
    db.flush()
    _apply_totals(row, _statement_items(db, row.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
