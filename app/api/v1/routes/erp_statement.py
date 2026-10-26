"""增强版对账单（第 13 批 · 第二阶段 · 模块 4 的路由层）。

## 与普通"应收应付明细表"的区别

一张对账单回答的是**对账区间内的四件事**，不是简单列流水：

    未开票金额        = 合同金额 − 已开票
    剩余未收 / 未付    = max(0, 合同金额 − 已收/已付 − 预收已核销)   ← 2026-10-22 加下限 0
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
| 发票 `invoices` | `invoiced_amount` | 销项按 `customer_id`（App 内新建）**或** `counterparty_name` = 对方名称（历史导入）；进项按名称 + `direction` 同向 + `issue_date ∈ 区间` |
| 收付款 `financial_transactions` | `received_amount` | `transaction_type ∈ (receipt, payment)` + `customer_id`/`supplier_id` + `occurred_at ∈ 区间` |

历史导入的发票只有 `counterparty_name`（没有 id），App 内手工新建的销项发票反过来只有
`customer_id` —— 两套都要认，否则"自己开的票"进不了自己的对账单。
名称匹配本身有歧义，所以**生成的是草稿**，必须人工核一遍再确认。
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _next_doc_no, _paginate
from app.db.session import get_db
from app.models.contract import CONTRACT_DIRECTIONS, Contract, normalize_direction
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.invoice import Invoice
from app.models.product import Product
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.statement import (
    STATEMENT_INVOICE_STATUS,
    STATEMENT_SOURCE_TYPES,
    STATEMENT_STATUS,
    Statement,
    StatementItem,
    compute_totals,
    derive_item_amounts,
    infer_invoice_status,
)
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
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

    # —— ② 发票（两套匹配口径 + 两套方向词表，缺一不可）——
    #   · 方向词表不一致：对账单方向是 `out` / `in`，发票方向是 `output` / `input`
    #     （见 `app/models/invoice.py::DIRECTION_OUTPUT`）。早期这里直接
    #     `Invoice.direction == direction`，**永远为假** → 任何客户的对账单
    #     「本期已开票」都是 ¥0，期末应收凭空少一个开票额（E2E 实拍：全额开票全额收款，
    #     期末却显示 −120，看着像客户多付了）。
    #   · 匹配键也是两套：历史导入/OCR 的发票只有 `counterparty_name`；
    #     App 内手工新建的销项发票只写 `buyer_name` + `customer_id`。
    #     同一文件的"四流穿透"底稿（`_ledger_preview`）早就是双口径，
    #     生成路径没跟上才出现"底稿有票、对账单没票"。
    if payload.get("include_invoices", True):
        inv_direction = "output" if direction == "out" else "input"
        invoice_query = db.query(Invoice).filter(
            Invoice.direction == inv_direction,
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
        name_cond = func.trim(Invoice.counterparty_name) == party_name if party_name else None
        if direction == "out":
            # 三个键任一命中即可：id（新数据）/ counterparty_name（历史导入）/
            # buyer_name（第 14 批前后都存在的买家抬头，兜住"没自动挂到客户"的漏网票）。
            conds = [Invoice.customer_id == party_id]
            if party_name:
                conds.append(func.trim(Invoice.buyer_name) == party_name)
            if name_cond is not None:
                conds.append(name_cond)
            invoice_query = invoice_query.filter(or_(*conds))
        elif name_cond is not None:
            # 进项发票目前没有 supplier_id 字段（模型注释里写明"将来可加"），只能按名称
            invoice_query = invoice_query.filter(name_cond)
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


# ===========================================================================
# 搜索预览 / 确认生成（2026-10-22）—— 把"生成"拆成"看"和"写"两步
# ===========================================================================
# 起因：原来只有一个「生成草稿」按钮，点下去**当场就占掉一个 DZ 单号并入库**。
# 用户的直觉却是"先搜一下看看这期有什么" —— 于是每试一次账期就多一张废草稿，
# 台账里全是没用的单号。现在拆成：
#   GET  /statements/preview-pool   只读：把区间内单据、发票、收付款拉出来给你核对
#   POST /statements/generate-selected  真正落库（可以只生成勾选的那几张单）
#
# ⚠️ 路由顺序：这两条**必须**声明在 `/statements/{statement_id}` 之前 ——
#    `{statement_id}: int` 会抢先匹配 "preview-pool" 然后 422（本项目踩过同款坑）。


@router.get("/statements/preview-pool", summary="搜索预览：只读聚合，不落库、不占对账单号")
def preview_pool(
    party_type: str = Query("customer", description="customer / supplier / all"),
    party_id: int | None = Query(None, description="往来单位 id；party_type=all 时可省略"),
    period_start: str = Query(..., description="账期开始 YYYY-MM-DD"),
    period_end: str = Query(..., description="账期结束 YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """把这一期该单位的所有业务事实摊开，**一个字节都不写库**。

    返回结构与 `/statements/{id}/preview` 一致（columns / rows / totals），
    这样前端不用为"预览态"再写一套表格 —— 同一张四流超宽表既能看已存对账单，
    也能看"还没生成的这一段"。
    """
    if party_type not in ("customer", "supplier", "all"):
        raise HTTPException(status_code=400, detail="party_type 只能是 customer / supplier / all")
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="缺少对账区间")
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="账期开始不能晚于结束")

    # —— 全部往来单位：应收 + 应付一起摊开（2026-10-22）——
    # 先按"这期到底谁有结算单据"筛一遍，只对有单的往来单位跑聚合 ——
    # 91 家客户/供应商逐个聚合会白跑几百条查询。
    if party_type == "all":
        return _preview_pool_all(db, period_start=period_start, period_end=period_end)

    if party_id in (None, ""):
        # 应收/应付视角下的「全部客户 / 全部供应商」：只跑这一个方向
        return _preview_pool_all(db, period_start=period_start, period_end=period_end,
                                 only=party_type)
    model = Customer if party_type == "customer" else Supplier
    party = db.get(model, int(party_id))
    if party is None:
        raise HTTPException(status_code=404, detail="对方单位档案不存在")

    data = _build_fusion_rows(
        db,
        party_type=party_type,
        party_id=int(party_id),
        party_name=getattr(party, "name", "") or "",
        period_start=period_start,
        period_end=period_end,
    )
    # 可勾选的"单据"：每张单的小计行一条（勾选粒度 = 单据，不是商品行）
    documents = [
        {
            "key": f"order:{row.get('source_id')}",
            "source_id": row.get("source_id"),
            "source_no": row.get("source_no"),
            "business_date": row.get("business_date"),
            "amount": row.get("amount"),
            "invoiced_amount": row.get("invoiced_amount"),
            "paid_amount": row.get("paid_amount"),
            "remaining_debt": row.get("remaining_debt"),
            "party_type": party_type,
            "party_name": getattr(party, "name", "") or "",
        }
        for row in (data.get("rows") or [])
        if row.get("row_kind") == "summary" and row.get("source_id")
    ]
    return {
        **data,
        "available": True,
        "party_type": party_type,
        "party_id": int(party_id),
        "party_name": getattr(party, "name", "") or "",
        "period": {"from": period_start, "to": period_end},
        "documents": documents,
        "doc_count": len(documents),
    }


def _preview_pool_all(
    db: Session, *, period_start: str, period_end: str, only: str | None = None
) -> dict[str, object]:
    """「全部往来单位」的只读预览：应收 + 应付合并成一张表。

    勾选键换成带方向前缀的形式（`sales:<id>` / `purchase:<id>`）——
    销售单和采购单是两张表，id 会撞，只用 `order:<id>` 分不清是哪一边。
    """
    customers = {row.id: row for row in db.query(Customer).all()}
    suppliers = {row.id: row for row in db.query(Supplier).all()}

    def _parties_with_docs(model, party_col, doc_type, names):
        rows = (
            db.query(party_col)
            .filter(
                model.doc_type == doc_type,
                model.status != "cancelled",
                model.order_date >= period_start,
                model.order_date <= period_end,
            )
            .distinct()
            .all()
        )
        return [pid for (pid,) in rows if pid in names]

    targets: list[tuple[str, int]] = []
    if only in (None, "customer"):
        targets += [
            ("customer", pid)
            for pid in _parties_with_docs(SalesOrder, SalesOrder.customer_id, "outbound", customers)
        ]
    if only in (None, "supplier"):
        targets += [
            ("supplier", pid)
            for pid in _parties_with_docs(PurchaseOrder, PurchaseOrder.supplier_id, "inbound", suppliers)
        ]

    merged_rows: list[dict[str, object]] = []
    documents: list[dict[str, object]] = []
    sums = {"amount_sum": 0.0, "invoiced_sum": 0.0, "paid_sum": 0.0, "remaining_sum": 0.0, "doc_count": 0}
    columns = _preview_columns()

    for ptype, pid in targets:
        party = customers.get(pid) if ptype == "customer" else suppliers.get(pid)
        party_name = getattr(party, "name", "") or ""
        data = _build_fusion_rows(
            db,
            party_type=ptype,
            party_id=int(pid),
            party_name=party_name,
            period_start=period_start,
            period_end=period_end,
        )
        prefix = "sales" if ptype == "customer" else "purchase"
        for row in data.get("rows") or []:
            # 每行都带上往来单位与方向，合并后仍能分清是"谁的单"
            row["party_name"] = party_name
            row["party_type"] = ptype
            if row.get("row_kind") == "summary" and row.get("source_id"):
                key = f"{prefix}:{row['source_id']}"
                row["doc_key"] = key
                documents.append(
                    {
                        "key": key,
                        "source_id": row.get("source_id"),
                        "source_no": row.get("source_no"),
                        "business_date": row.get("business_date"),
                        "amount": row.get("amount"),
                        "invoiced_amount": row.get("invoiced_amount"),
                        "paid_amount": row.get("paid_amount"),
                        "remaining_debt": row.get("remaining_debt"),
                        "party_type": ptype,
                        "party_name": party_name,
                    }
                )
            merged_rows.append(row)
        totals = data.get("totals") or {}
        sums["amount_sum"] += float(totals.get("amount_sum") or 0)
        sums["invoiced_sum"] += float(totals.get("invoiced_sum") or 0)
        sums["paid_sum"] += float(totals.get("paid_sum") or 0)
        sums["remaining_sum"] += float(totals.get("remaining_sum") or 0)

    # 重排行号（合并后行号必须连续，否则前端 key 撞、表格错行）
    for index, row in enumerate(merged_rows, start=1):
        row["line_no"] = index
    sums["doc_count"] = len(documents)

    return {
        "columns": columns,
        "rows": merged_rows,
        "totals": {key: f"{value:.2f}" if key != "doc_count" else value for key, value in sums.items()}
        | {"row_count": len(merged_rows), "self_purchase_sum": "0.00"},
        "available": True,
        "party_type": only or "all",
        "party_id": None,
        "party_name": "全部客户" if only == "customer" else ("全部供应商" if only == "supplier" else "全部往来单位"),
        "period": {"from": period_start, "to": period_end},
        "documents": documents,
        "doc_count": len(documents),
        "party_count": len(targets),
    }


@router.post("/statements/generate-selected", summary="确认生成：只把勾选的单据落库成正式对账单")
def generate_selected(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """按"勾选的单据"生成正式对账单（**这一支才会写库、才会占 DZ 单号**）。

    与 `POST /statements/generate` 的区别（后者保持原样，不动老调用方）：
      · 老接口把整期压成「合同 / 发票 / 收款」三类汇总行；
      · 这支按**每张单据一行**生成明细，勾哪张就进哪张 —— 和"核对打勾"的心智一致。

    为什么明细行要逐单：对账时客户是拿"这一单"跟你对的。
    压成三类汇总后，"哪张单开了票、哪张还没收钱"就全靠猜。
    """
    # party_type 允许 "all"：批量生成时每个勾选项自带方向（sales:/purchase: 前缀），
    # 这里的 party_type 只作为 `order:` 前缀键的默认方向。
    party_type = str(payload.get("party_type") or "customer")
    if party_type not in ("customer", "supplier", "all"):
        raise HTTPException(status_code=400, detail="party_type 只能是 customer / supplier / all")
    if party_type == "all":
        party_type = "customer"  # 仅用于解析裸 order: 键的默认方向
    direction = normalize_direction(direction=payload.get("direction") or (
        "out" if party_type == "customer" else "in"
    ))
    period_start = str(payload.get("period_start") or "").strip()
    period_end = str(payload.get("period_end") or "").strip()
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="缺少对账区间")
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="账期开始不能晚于结束")

    # party_id 现在是**可选**的：批量生成时每个勾选项自带往来单位，
    # 再要求先选一个"默认往来单位"纯属多余（2026-10-22「全部往来单位」模式）。
    raw_party = payload.get("party_id")
    party_id = None
    if raw_party not in (None, ""):
        try:
            party_id = int(raw_party)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="party_id 必须是整数") from exc

    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise HTTPException(status_code=400, detail="请先勾选至少一张单据再生成")

    # —— 解析勾选键 → 归属的往来单位 ——
    # 三种键前缀：`order:<id>`（按入参 party_type 判方向，兼容单客户预览）、
    # `sales:<id>` / `purchase:<id>`（"全部往来单位"预览用的混合键，自带方向）。
    # 为什么要分组：一次勾了多个客户/供应商，应当**各生成各的对账单**，
    # 而不是硬塞进一张（对账单是给某一个往来单位看的凭证，混户等于作废）。
    groups: dict[tuple[str, int], list] = {}
    for key in raw_keys:
        text_key = str(key)
        if ":" not in text_key:
            raise HTTPException(status_code=400, detail=f"无法识别的勾选项：{text_key}")
        prefix, raw_id = text_key.split(":", 1)
        if prefix == "order":
            type_for_key = party_type
        elif prefix == "sales":
            type_for_key = "customer"
        elif prefix == "purchase":
            type_for_key = "supplier"
        else:
            raise HTTPException(status_code=400, detail=f"无法识别的勾选项：{text_key}")
        try:
            order_id = int(raw_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"无法识别的勾选项：{text_key}") from exc

        key_model = SalesOrder if type_for_key == "customer" else PurchaseOrder
        order = db.get(key_model, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"勾选的单据不存在（{text_key}），可能已被删除")
        owner_id = int(
            getattr(order, "customer_id" if type_for_key == "customer" else "supplier_id") or 0
        )
        if not owner_id:
            raise HTTPException(status_code=409, detail=f"单据 {order.order_no} 没有往来单位，无法对账")
        groups.setdefault((type_for_key, owner_id), []).append(order)

    statements: list[dict[str, object]] = []
    total_lines = 0
    for (group_type, group_party_id), orders in groups.items():
        is_sales_group = group_type == "customer"
        group_model = Customer if is_sales_group else Supplier
        group_party = db.get(group_model, group_party_id)
        if group_party is None:
            raise HTTPException(status_code=404, detail="对方单位档案不存在")
        order_ids = [int(order.id) for order in orders]
        item_model = SalesOrderItem if is_sales_group else PurchaseOrderItem
        item_fk = item_model.sales_order_id if is_sales_group else item_model.purchase_order_id
        invoiced_map = {
            int(row_id): round(float(total or 0), 2)
            for row_id, total in (
                db.query(Invoice.related_order_id, func.coalesce(func.sum(Invoice.total_amount), 0))
                .filter(
                    Invoice.direction == ("output" if is_sales_group else "input"),
                    Invoice.related_order_id.in_(order_ids),
                )
                .group_by(Invoice.related_order_id)
                .all()
            )
        }
        item_counts = {
            int(row_id): int(count or 0)
            for row_id, count in (
                db.query(item_fk, func.count())
                .filter(item_fk.in_(order_ids))
                .group_by(item_fk)
                .all()
            )
        }

        lines: list[dict[str, object]] = []
        for order in orders:
            invoiced = invoiced_map.get(int(order.id), 0.0)
            net = float((order.receivable_amount if is_sales_group else order.payable_amount) or 0) - float(
                order.discount_amount or 0
            )
            received = float((order.received_amount if is_sales_group else order.paid_amount) or 0)
            lines.append(
                {
                    "business_date": order.order_date,
                    # 取值必须落在 schema 允许集合里（contract/order/inbound/outbound/
                    # invoice/receipt/payment/opening）—— 写 "sales_order" 会被 validator 拒掉。
                    "source_type": "outbound" if is_sales_group else "inbound",
                    "source_id": order.id,
                    "source_no": order.order_no,
                    "contract_id": None,
                    "contract_no": _contract_no_of(order),
                    "summary": f"{order.order_no}（{item_counts.get(int(order.id), 0)} 行明细）",
                    "contract_amount": round(net, 2),
                    "invoiced_amount": round(invoiced, 2),
                    "received_amount": round(received, 2),
                    "prepaid_received": 0,
                    "prepaid_applied": 0,
                    "invoice_count": 0,
                }
            )

        # 期初：多客户批量生成时，手填的期初只对"唯一那一组"有意义，其余取档案期初
        group_opening = getattr(group_party, "init_receivable" if is_sales_group else "init_payable", 0) or 0
        if len(groups) == 1 and payload.get("opening_balance") not in (None, ""):
            group_opening = payload.get("opening_balance")

        item_schemas = []
        for index, line in enumerate(lines, start=1):
            line["line_no"] = index
            item_schemas.append(StatementItemCreate(**line))

        statement = Statement(
            statement_no=_next_doc_no(db, Statement, "DZ", field="statement_no"),
            direction="out" if is_sales_group else "in",
            party_type=group_type,
            party_id=group_party_id,
            party_name=getattr(group_party, "name", "") or "",
            party_tax_no=getattr(group_party, "tax_no", None),
            period_start=period_start,
            period_end=period_end,
            statement_date=datetime.now().strftime("%Y-%m-%d"),
            currency=str(payload.get("currency") or "CNY"),
            opening_balance=group_opening or 0,
            status="draft",
            note=payload.get("note"),
            created_by=payload.get("created_by"),
        )
        db.add(statement)
        db.flush()

        rows = [
            _item_from_payload(statement.id, item.model_dump(), index)
            for index, item in enumerate(item_schemas, start=1)
        ]
        db.add_all(rows)
        _apply_totals(statement, rows)
        db.commit()
        db.refresh(statement)
        total_lines += len(rows)
        statements.append(_statement_payload(statement, _statement_items(db, statement.id)))

    message = (
        f"已生成对账单 {statements[0]['statement_no']}（{total_lines} 张单据）"
        if len(statements) == 1
        else f"已按 {len(statements)} 个往来单位各生成一张对账单，共 {total_lines} 张单据"
    )
    return {
        # 单组时把完整对账单平铺到顶层（老调用方/脚本照旧读 statement_no、items）
        **(statements[0] if len(statements) == 1 else {}),
        "statements": statements,
        "generated_lines": total_lines,
        "message": message,
    }


@router.get("/statements/{statement_id}", response_model=StatementRead)
def get_statement(statement_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    row = _statement_or_404(db, statement_id)
    return _statement_payload(row, _statement_items(db, statement_id))


# ===========================================================================
# 对账单大融合（2026-10-21 第二步）：明细级四流穿透预览（row_kind 架构）
# ===========================================================================
# 与旧版（只给往来账底稿）的关系：往来账底稿 ledger / 两口径差额 diff **原样保留**，
# 新增的是 columns + rows —— 一行 = 一条业务事实：
#   · detail  业务明细行（一张单的每个商品一行，数量/单价/金额在此）
#   · invoice 开票行（一张发票一行，实时 join invoices，不存第二份）
#   · recv / pay  收付款行（一笔流水一行，实时 join financial_transactions）
#   · summary 小计行（每个单据一行小计 + 全表合计）
# 前端超宽表按返回的 columns 渲染（元数据驱动），加列不用改前端。

_PREVIEW_INVOICE_STATUS: dict[str, str] = {"none": "未开票", "partial": "部分开票", "full": "已开票"}


def _c(field: str, label: str, group: str, width: int, *, frozen: bool = False,
       align: str = "left", kind: str = "text", mono: bool = False) -> dict[str, object]:
    """一列的元数据。`mono=True` 给"要逐位核对"的编码类字段（单号/票号/流水号）。"""
    return {"field": field, "label": label, "group": group, "width": width,
            "frozen": frozen, "align": align, "kind": kind, "mono": mono}


def _preview_columns() -> list[dict[str, object]]:
    """列元数据：前端超宽表的唯一渲染依据（分组顺序 = 显示顺序）。"""
    return [
        # —— 基础信息 ——
        _c("business_date", "业务日期", "基础信息", 105, frozen=True),
        _c("source_no", "单据号", "基础信息", 145, frozen=True, mono=True),
        # 2026-10-22：用户要的 12 列里缺的两列 —— 合同编号从单据备注「由合同 X 生成」里取
        _c("contract_no", "合同编号", "基础信息", 145, mono=True),
        _c("party_name", "客户/供应商", "基础信息", 170, frozen=True),
        _c("project_name", "工程项目", "基础信息", 150),
        _c("warehouse_name", "仓库", "基础信息", 90),
        _c("product_name", "商品名称", "基础信息", 150),
        _c("standards", "规格", "基础信息", 95),
        _c("model", "型号", "基础信息", 95),
        _c("unit", "单位", "基础信息", 55),
        _c("quantity", "数量", "基础信息", 65, align="right", kind="qty"),
        _c("unit_price", "单价", "基础信息", 85, align="right", kind="money"),
        _c("amount", "金额", "基础信息", 105, align="right", kind="money"),
        # —— 物流签收流 ——
        _c("delivery_date", "送货日期", "物流签收流", 100),
        _c("shipped_at", "发货时间", "物流签收流", 135),
        _c("sign_status", "签收状态", "物流签收流", 110),
        _c("signed_by", "签收人", "物流签收流", 85),
        _c("signed_at", "签收时间", "物流签收流", 135),
        _c("confirmed_at", "客户确认时间", "物流签收流", 135),
        _c("e_sign_status", "电子签", "物流签收流", 75),
        # —— 发票流 ——
        _c("invoice_status", "开票状态", "发票流", 85),
        _c("invoiced_at", "开票时间", "发票流", 100),
        _c("invoiced_amount", "开票金额", "发票流", 105, align="right", kind="money"),
        _c("invoice_no", "发票号码", "发票流", 175, mono=True),
        _c("uninvoiced_amount", "欠票金额", "发票流", 105, align="right", kind="money"),
        # —— 资金流 ——
        _c("flow_no", "收款流水号", "资金流", 130, mono=True),
        _c("paid_at", "收付款时间", "资金流", 110),
        _c("paid_amount", "收付款金额", "资金流", 110, align="right", kind="money"),
        _c("remaining_debt", "剩余欠款", "资金流", 105, align="right", kind="money"),
        _c("payment_method", "收款方式", "资金流", 100),
        # —— 历史专属（陕送票）——
        _c("history_received", "陕送付给的收款", "历史专属", 130, align="right", kind="money"),
        _c("self_purchase_paid", "已付自采金额", "历史专属", 120, align="right", kind="money"),
        _c("self_purchase_supplier", "自采供应商", "历史专属", 140),
        _c("supply_price", "供货价格", "历史专属", 90, align="right", kind="money"),
        _c("doc_note", "单据备注", "历史专属", 150),
        _c("line_note", "行备注", "历史专属", 140),
        _c("contact", "联系人", "历史专属", 90),
    ]


def _m2(value) -> str:
    """金额出参：两位小数字符串（Money 口径，绝不让裸 Decimal/float 进 JSON）。"""
    return str((Decimal(str(value)) if value is not None else Decimal("0")).quantize(Decimal("0.01")))


def _m4(value) -> str:
    """单价出参：四位小数字符串（费率口径，不截断）。"""
    return str((Decimal(str(value)) if value is not None else Decimal("0")).quantize(Decimal("0.0001")))


# 合同转单时把合同号写进单据备注（erp_sales.py: note = "由合同 X 生成"）。
# 这是单据与合同之间**唯一**的可追溯线索（sales_orders 没有 contract_id 列），
# 所以只能从这里取；取不到就显示空，绝不按"同名合同"乱猜。
_CONTRACT_NOTE_RE = re.compile(r"由合同\s*([^\s，,。；;]+)\s*生成")


def _contract_no_of(order) -> str | None:
    note = str(getattr(order, "note", "") or "")
    hit = _CONTRACT_NOTE_RE.search(note)
    return hit.group(1) if hit else None


def _sign_status_of(order) -> str:
    """签收状态：把三个时间戳压成一个能一眼看懂的状态词。

    刻意不新增数据库字段 —— 状态是**时间戳的派生物**，
    存两份必然出现"已签收但 signed_at 是空"的自相矛盾行。
    """
    if getattr(order, "signed_at", None):
        return "已签收"
    if getattr(order, "shipped_at", None):
        return "已发货·待签收"
    if getattr(order, "delivery_date", None):
        return "待发货"
    return "未发货"


# 收款方式写在流水备注里（前端拼的「…｜方式：银行转账｜…」），
# 因为 financial_transactions 没有 method 列。这里把它读回来当列显示。
_FLOW_METHOD_RE = re.compile(r"方式[:：]\s*([^｜|]+)")


def _method_of_flow(flow, fallback: str | None = None) -> str | None:
    note = str(getattr(flow, "note", "") or "")
    hit = _FLOW_METHOD_RE.search(note)
    if hit:
        return hit.group(1).strip()
    return fallback


def _dt(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _empty_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "line_no": 0, "row_kind": "detail", "source_id": None,
        "business_date": None, "source_no": None, "party_name": None,
        "project_name": None, "warehouse_name": None,
        "product_name": None, "standards": None, "model": None, "unit": None,
        "quantity": None, "unit_price": None, "amount": None,
        "contract_no": None, "sign_status": None, "flow_no": None,
        "delivery_date": None, "shipped_at": None, "signed_by": None,
        "signed_at": None, "confirmed_at": None, "e_sign_status": None,
        "invoice_status": None, "invoiced_at": None, "invoiced_amount": None,
        "invoice_no": None, "uninvoiced_amount": None,
        "paid_at": None, "paid_amount": None, "remaining_debt": None,
        "payment_method": None,
        "history_received": None, "self_purchase_paid": None,
        "self_purchase_supplier": None, "supply_price": None,
        "doc_note": None, "line_note": None, "contact": None,
    }
    row.update(overrides)
    return row


def _build_fusion_rows(
    db: Session,
    *,
    party_type: str,
    party_id: int,
    party_name: str,
    period_start: str,
    period_end: str,
) -> dict[str, object]:
    """按单据聚合四流。发票/资金**实时 join**，绝不存第二份。"""
    is_sales = party_type == "customer"
    doc_model = SalesOrder if is_sales else PurchaseOrder
    item_model = SalesOrderItem if is_sales else PurchaseOrderItem
    item_fk = "sales_order_id" if is_sales else "purchase_order_id"
    doc_order_field = doc_model.order_date

    warehouse_names = {w.id: w.name for w in db.query(Warehouse).all()}
    project_names = {pr.id: pr.name for pr in db.query(Project).all()}
    supplier_names = {sp.id: sp.name for sp in db.query(Supplier).all()}

    # —— ① 区间内的单据（作废的不进对账）——
    #
    # ⚠️ 只认**结算单据**：销售侧 `doc_type='outbound'`（出库单）、采购侧 `'inbound'`（入库单）。
    # 为什么必须过滤：`to-outbound` / `to-inbound` 会把订单复制成出库/入库单，
    # 两张单属于同一个客户、同一天、金额相同 —— 不过滤就是**一笔生意在对账单上算两遍**
    # （2026-10-22 实测：一张 100 元的单，预览出来 doc_count=2、金额 200）。
    # 而"订单"本身不产生应收应付（order 的 receivable_amount 不参与结算），
    # 所以它压根不该出现在对账底稿里。
    settle_doc_type = "outbound" if is_sales else "inbound"
    orders = (
        db.query(doc_model)
        .filter(
            getattr(doc_model, "customer_id" if is_sales else "supplier_id") == party_id,
            doc_model.doc_type == settle_doc_type,
            doc_order_field >= period_start,
            doc_order_field <= period_end,
            doc_model.status != "cancelled",
        )
        .order_by(doc_order_field, doc_model.id)
        .all()
    )
    order_ids = [o.id for o in orders]

    # —— ② 发票（挂单的按单分组；未挂单的兜底成独立行）——
    inv_direction = "output" if is_sales else "input"
    inv_q = db.query(Invoice).filter(
        Invoice.direction == inv_direction,
        Invoice.issue_date >= period_start,
        Invoice.issue_date <= period_end,
    )
    if is_sales:
        inv_q = inv_q.filter(
            or_(Invoice.customer_id == party_id, Invoice.counterparty_name == party_name)
        )
    else:
        inv_q = inv_q.filter(Invoice.counterparty_name == party_name)
    invoices = inv_q.all()
    invoice_by_order: dict[int, list[Invoice]] = {}
    loose_invoices: list[Invoice] = []
    for inv in invoices:
        if inv.related_order_id and inv.related_order_id in order_ids:
            invoice_by_order.setdefault(inv.related_order_id, []).append(inv)
        else:
            loose_invoices.append(inv)

    # —— ③ 收付款流水（挂单的按单分组；未挂单的兜底成独立行）——
    flow_type = "receipt" if is_sales else "payment"
    party_col = (
        FinancialTransaction.customer_id if is_sales else FinancialTransaction.supplier_id
    )
    flows = (
        db.query(FinancialTransaction)
        .filter(
            party_col == party_id,
            FinancialTransaction.transaction_type == flow_type,
            FinancialTransaction.occurred_at >= period_start,
            FinancialTransaction.occurred_at <= period_end,
        )
        .order_by(FinancialTransaction.occurred_at, FinancialTransaction.id)
        .all()
    )
    flow_by_order: dict[int, list[FinancialTransaction]] = {}
    loose_flows: list[FinancialTransaction] = []
    for flow in flows:
        if flow.related_order_id and flow.related_order_id in order_ids:
            flow_by_order.setdefault(flow.related_order_id, []).append(flow)
        else:
            loose_flows.append(flow)

    # —— ④ 组行 ——
    rows: list[dict[str, object]] = []
    totals = {
        "amount_sum": Decimal("0"), "invoiced_sum": Decimal("0"),
        "paid_sum": Decimal("0"), "remaining_sum": Decimal("0"),
        "self_purchase_sum": Decimal("0"), "doc_count": 0,
    }

    def _invoice_label(n: int, total: Decimal, net: Decimal) -> str:
        if n == 0:
            return "none"
        if total >= net - Decimal("0.005"):
            return "full"
        return "partial"

    for order in orders:
        items = (
            db.query(item_model)
            .filter(getattr(item_model, item_fk) == order.id)
            .order_by(item_model.id)
            .all()
        )
        order_invoices = invoice_by_order.get(order.id, [])
        order_flows = flow_by_order.get(order.id, [])
        invoiced_total = sum((inv.total_amount or Decimal("0") for inv in order_invoices), Decimal("0"))
        paid_total = sum((fl.amount or Decimal("0") for fl in order_flows), Decimal("0"))
        net = (order.receivable_amount if is_sales else order.payable_amount) - (order.discount_amount or Decimal("0"))
        invoice_nos = "、".join(inv.invoice_no for inv in order_invoices if inv.invoice_no)
        invoice_dates = [inv.issue_date for inv in order_invoices if inv.issue_date]
        warehouse_name = warehouse_names.get(order.warehouse_id)
        project_name = project_names.get(order.project_id)
        supplier_name = (
            supplier_names.get(order.self_purchase_supplier_id)
            if getattr(order, "self_purchase_supplier_id", None) else None
        )
        head_common = {
            "source_id": order.id,
            "business_date": order.order_date,
            "source_no": order.order_no,
            "party_name": party_name,
            "project_name": project_name,
            "warehouse_name": warehouse_name,
            "contract_no": _contract_no_of(order),
            "sign_status": _sign_status_of(order),
            "delivery_date": order.delivery_date,
            "shipped_at": _dt(getattr(order, "shipped_at", None)),
            "signed_by": getattr(order, "signed_by", None),
            "signed_at": _dt(getattr(order, "signed_at", None)),
            "confirmed_at": _dt(getattr(order, "confirmed_at", None)),
            "payment_method": order.payment_method,
            "doc_note": order.note,
            "contact": " ".join(x for x in [order.contact, order.contact_phone] if x),
            "self_purchase_paid": _m2(getattr(order, "self_purchase_paid", 0) or 0)
            if hasattr(order, "self_purchase_paid") else None,
            "self_purchase_supplier": supplier_name,
        }

        if items:
            for index, item in enumerate(items):
                row = _empty_row(**head_common)
                row["row_kind"] = "detail"
                row["product_name"] = item.product_name
                row["standards"] = item.standards
                row["model"] = getattr(item, "model", None)
                row["unit"] = item.unit
                row["quantity"] = str(int(item.quantity or 0))
                row["unit_price"] = _m4(item.unit_price)
                row["amount"] = _m2(item.amount)
                row["supply_price"] = (
                    _m4(item.supply_price) if getattr(item, "supply_price", None) is not None else None
                )
                row["line_note"] = item.note
                # 单据级聚合字段只放在第一行（发票/资金另有独立行，不挤在明细里）
                if index == 0:
                    row["invoice_status"] = _invoice_label(len(order_invoices), invoiced_total, net)
                    row["invoiced_at"] = min(invoice_dates) if invoice_dates else None
                    row["invoiced_amount"] = _m2(invoiced_total) if order_invoices else _m2(0)
                    row["invoice_no"] = invoice_nos or None
                    row["uninvoiced_amount"] = _m2(max(Decimal("0"), net - invoiced_total))
                    row["paid_amount"] = _m2(order.received_amount if is_sales else order.paid_amount)
                    row["remaining_debt"] = _m2(order.current_debt)
                    row["history_received"] = _m2(order.received_amount) if is_sales else None
                rows.append(row)
        else:
            row = _empty_row(**head_common)
            row["invoice_status"] = _invoice_label(len(order_invoices), invoiced_total, net)
            row["invoiced_amount"] = _m2(invoiced_total)
            row["uninvoiced_amount"] = _m2(max(Decimal("0"), net - invoiced_total))
            row["paid_amount"] = _m2(order.received_amount if is_sales else order.paid_amount)
            row["remaining_debt"] = _m2(order.current_debt)
            row["history_received"] = _m2(order.received_amount) if is_sales else None
            rows.append(row)

        # 开票行：一张发票一行
        for inv in order_invoices:
            row = _empty_row(**head_common)
            row["row_kind"] = "invoice"
            row["business_date"] = inv.issue_date or order.order_date
            row["invoiced_at"] = inv.issue_date
            row["invoiced_amount"] = _m2(inv.total_amount)
            row["invoice_no"] = inv.invoice_no
            row["invoice_status"] = "full"
            rows.append(row)

        # 收付款行：一笔流水一行
        for flow in order_flows:
            row = _empty_row(**head_common)
            row["row_kind"] = "recv" if is_sales else "pay"
            row["business_date"] = flow.occurred_at
            row["paid_at"] = flow.occurred_at
            row["paid_amount"] = _m2(flow.amount)
            # 流水号：新流水由 _write_finance 自动生成；历史流水可能为空 → 退回 #id
            row["flow_no"] = getattr(flow, "flow_no", None) or f"#{flow.id}"
            # 这一笔**实际用的**收款方式（写在流水备注里），不是单据上预设的那个
            row["payment_method"] = _method_of_flow(flow, order.payment_method)
            row["doc_note"] = flow.note or order.note
            rows.append(row)

        # 单据小计行
        sub = _empty_row(**head_common)
        sub["row_kind"] = "summary"
        sub["product_name"] = f"◤ {order.order_no} 小计（{len(items)} 行明细）"
        sub["quantity"] = str(sum(int(i.quantity or 0) for i in items))
        sub["amount"] = _m2(order.receivable_amount if is_sales else order.payable_amount)
        sub["invoiced_amount"] = _m2(invoiced_total)
        sub["uninvoiced_amount"] = _m2(max(Decimal("0"), net - invoiced_total))
        sub["paid_amount"] = _m2(paid_total)
        sub["remaining_debt"] = _m2(order.current_debt)
        rows.append(sub)

        totals["amount_sum"] += order.receivable_amount if is_sales else order.payable_amount
        totals["invoiced_sum"] += invoiced_total
        totals["paid_sum"] += paid_total
        totals["remaining_sum"] += order.current_debt or Decimal("0")
        totals["self_purchase_sum"] += Decimal(str(getattr(order, "self_purchase_paid", 0) or 0))
        totals["doc_count"] += 1

    # 未挂单的发票 / 流水：兜底成独立行（对账时"钱在账上、单找不到"最需要看见它们）
    for inv in loose_invoices:
        row = _empty_row()
        row["row_kind"] = "invoice"
        row["business_date"] = inv.issue_date
        row["party_name"] = party_name
        row["product_name"] = "（未关联单据的发票）"
        row["invoiced_at"] = inv.issue_date
        row["invoiced_amount"] = _m2(inv.total_amount)
        row["invoice_no"] = inv.invoice_no
        row["invoice_status"] = "full"
        row["doc_note"] = "⚠️ 这张发票没有挂到任何单据，请核对"
        rows.append(row)
        totals["invoiced_sum"] += inv.total_amount or Decimal("0")
    for flow in loose_flows:
        row = _empty_row()
        row["row_kind"] = "recv" if is_sales else "pay"
        row["business_date"] = flow.occurred_at
        row["party_name"] = party_name
        row["product_name"] = "（未关联单据的收付款）"
        row["paid_at"] = flow.occurred_at
        row["paid_amount"] = _m2(flow.amount)
        row["flow_no"] = getattr(flow, "flow_no", None) or f"#{flow.id}"
        row["payment_method"] = _method_of_flow(flow)
        row["doc_note"] = flow.note or "⚠️ 这笔流水没有挂到任何单据（预收/预付或旧数据），请核对"
        rows.append(row)
        totals["paid_sum"] += flow.amount or Decimal("0")

    # 全表合计行
    grand = _empty_row()
    grand["row_kind"] = "summary"
    grand["product_name"] = f"◢ 全表合计（{totals['doc_count']} 张单据）"
    grand["amount"] = _m2(totals["amount_sum"])
    grand["invoiced_amount"] = _m2(totals["invoiced_sum"])
    grand["paid_amount"] = _m2(totals["paid_sum"])
    grand["remaining_debt"] = _m2(totals["remaining_sum"])
    grand["self_purchase_paid"] = _m2(totals["self_purchase_sum"])
    rows.append(grand)

    # 行号（渲染顺序 = 业务顺序）
    for i, row in enumerate(rows, start=1):
        row["line_no"] = i

    return {
        "columns": _preview_columns(),
        "rows": rows,
        "totals": {
            "amount_sum": _m2(totals["amount_sum"]),
            "invoiced_sum": _m2(totals["invoiced_sum"]),
            "paid_sum": _m2(totals["paid_sum"]),
            "remaining_sum": _m2(totals["remaining_sum"]),
            "self_purchase_sum": _m2(totals["self_purchase_sum"]),
            "doc_count": totals["doc_count"],
            "row_count": len(rows),
        },
    }


@router.get(
    "/statements/{statement_id}/preview",
    summary="对账单详情内嵌预览：四流穿透超宽表 + 往来账底稿双口径",
)
def preview_statement(statement_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """对账单预览（2026-10-21 大融合版）。

    三层结构，一次请求全给：
      1. columns + rows —— 明细级四流穿透超宽表（detail/invoice/recv/pay/summary 五种行）；
      2. ledger + statement_side + diff —— 往来账「期初→逐笔→期末」与对账单口径的差额
         （沿用 finance_reconciliation 唯一实现，**不自动调平**的原则不变）；
      3. totals —— 合计数。

    数据来源：业务单据实时聚合（sales_orders/purchase_orders + invoices +
    financial_transactions），对账单本身只是"报表壳"，不存四流的第二份。
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
        return {**empty, "reason": "这张对账单没有关联往来单位档案（可能是手工建的），无法取数。"}

    fusion = _build_fusion_rows(
        db,
        party_type=party_type,
        party_id=int(row.party_id),
        party_name=row.party_name or "",
        period_start=row.period_start or "1900-01-01",
        period_end=row.period_end or "2999-12-31",
    )

    # 往来账底稿（保留：两口径差额是业务事实）
    from app.api.v1.routes.erp_finance import finance_reconciliation

    try:
        ledger = finance_reconciliation(
            party_type,
            int(row.party_id),
            from_date=row.period_start,
            to_date=row.period_end,
            db=db,
        )
        summary = ledger.get("summary") or {}
        ledger_closing = round(float(summary.get("closing_balance") or 0), 2)
        statement_closing = round(float(row.receivable_balance or 0), 2)
        diff = round(statement_closing - ledger_closing, 2)
        ledger_block = {
            "opening_balance": round(float(summary.get("opening_balance") or 0), 2),
            "increase_total": round(float(summary.get("increase_total") or 0), 2),
            "decrease_total": round(float(summary.get("decrease_total") or 0), 2),
            "closing_balance": ledger_closing,
            "closing_balance_upper": summary.get("closing_balance_upper"),
            "rows": ledger.get("rows") or [],
        }
    except Exception as exc:  # noqa: BLE001 —— 底稿失败不影响四流穿透表
        ledger_block = {"error": f"取往来账底稿失败：{exc}"}
        ledger_closing = 0.0
        statement_closing = round(float(row.receivable_balance or 0), 2)
        diff = round(statement_closing - ledger_closing, 2)

    return {
        "statement_id": row.id,
        "statement_no": row.statement_no,
        "available": True,
        "party_type": party_type,
        "party_id": row.party_id,
        "party_name": row.party_name,
        "period": {"from": row.period_start, "to": row.period_end},
        "columns": fusion["columns"],
        "rows": fusion["rows"],
        "totals": fusion["totals"],
        "ledger": ledger_block,
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
    # ① 先按公式重算**每一行**的计算字段，再②汇总表头。
    #    只做②不做①的后果（2026-10-22 实测）：表头「剩余未收」按新口径变成 0，
    #    明细行还留着旧的 −1676 —— 打印稿上两处数字打架，比不改还糟。
    for item in items:
        derived = derive_item_amounts(item)
        item.uninvoiced_amount = derived["uninvoiced_amount"]
        item.outstanding_amount = derived["outstanding_amount"]
        item.invoice_status = infer_invoice_status(
            item.contract_amount, item.invoiced_amount
        )
    db.flush()
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
