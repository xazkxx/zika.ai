"""财务管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

财务流水 / 应收应付 / 账龄 / 收付款 / 资金账户 / 转账 / 日常收支。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.bank import BANK_ACCOUNT_TYPES, BankAccount, BankTransfer, account_delta
from app.models.customer import Customer
from app.models.finance import DOC_TYPES, FinancialTransaction
from app.models.invoice import Invoice
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier
from app.schemas import FinancialTransactionCreate, FinancialTransactionRead
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _BALANCE_DECREASE,
    _BALANCE_INCREASE,
    _next_doc_no,
    _normalize_period,
    _paginate,
    _signed_amount,
    _write_finance,
    amount_to_chinese,
)

router = APIRouter(prefix="", tags=["erp"])




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

    # ── 业财一体化（2026-10-22）：付款挂进项发票 ──────────────────────────
    # 三件事在这里一次做完：
    #   ① 校验票的方向与归属（错票挂上去会骗过完结闸，必须拦在入口）；
    #   ② 把票挂到单据上（`related_order_id`），这样"未开票金额"当场就减少，
    #      不需要用户再跑一趟发票管理；
    #   ③ 在备注里留"暂估 / 无票"痕迹 —— 这是先款后票场景在账上唯一的证据。
    #
    # ⚠️ 这里**只记事实、不做拦截**：钱已经付了，系统再拦一次也变不出票来。
    #    真正的"强提醒"在前端（付款弹窗），后端负责把这笔钱的票属性记清楚。
    invoice_id = payload.get("invoice_id") or payload.get("input_invoice_id")
    estimate = bool(payload.get("estimate"))
    no_invoice = bool(payload.get("no_invoice"))
    linked_invoice = None
    if invoice_id not in (None, ""):
        linked_invoice = db.get(Invoice, int(invoice_id))
        if linked_invoice is None:
            raise HTTPException(status_code=404, detail="指定的进项发票不存在")
        if (linked_invoice.direction or "") != "input":
            raise HTTPException(status_code=400, detail="只有进项发票才能挂到付款流水上")
        if order_id and linked_invoice.related_order_id not in (None, int(order_id)):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"发票 {linked_invoice.invoice_no} 已挂在另一张单据上，"
                    "请先在该发票上解挂，再登记这笔付款"
                ),
            )
        # 票没挂单、这次又明确了是哪张采购单 → 顺手把票挂上去（付款即认票）
        if order_id and linked_invoice.related_order_id is None:
            linked_invoice.related_order_id = int(order_id)

    tags: list[str] = []
    if party_type == "supplier" and linked_invoice is None:
        if estimate:
            tags.append("【暂估】")
        elif no_invoice:
            tags.append("【无票付款】")
    if tags:
        note = "".join(tags) + note

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
        invoice_id=linked_invoice.id if linked_invoice is not None else None,
    )
    db.flush()

    # 记下这笔钱**实际冲抵到单据**的金额（预收/预付那部分不进单据）。
    # 红冲必须按它回退 received_amount / paid_amount —— 按 amount 回退会把单据冲成负数：
    # 单欠 1000、收了 1500，回退 1500 → received_amount = -500。
    record.applied_amount = round(applied, 2)

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
        # 业财一体化：这笔钱挂的票、以及"到底有没有票"，前端成功面板直接显示
        "invoice_id": record.invoice_id,
        "invoice_no": linked_invoice.invoice_no if linked_invoice is not None else None,
        "has_invoice": linked_invoice is not None,
        "estimate": bool(estimate and linked_invoice is None),
        "no_invoice": bool(no_invoice and linked_invoice is None),
    }



# ============================================================================
# 红冲（Reverse）—— 2026-10-19
#
# 为什么要有它：收款/付款是**真实资金记录**，登记错了不能删（删了这笔钱在账上就
# 凭空消失，也没有任何痕迹）。行业做法是"红字冲销"：再记一笔等额负数，两笔都留着，
# 合计归零，谁在什么时候冲的、为什么冲，全都查得到。
#
# 四条硬规矩：
#   1. 只红冲 receipt / payment（人工登记的真实资金）。
#      应收/应付（receivable/payable）是单据审核时自动生成的，要冲就红冲单据本身，
#      在这里单独冲会造出"单据还在、应收没了"的错账。
#   2. **一笔只能冲一次**：靠 reversal_of_id 反查 + 行锁（FOR UPDATE）双保险，
#      否则连点两下会冲两次，账变成 -1000。
#   3. 红冲生成的是**负数流水**（不是删原行、不是改金额），
#      所以 `sum(amount)` 天然归零，报表一行都不用改。
#   4. 挂单据的收款要**同步回退单据的 received_amount / paid_amount**，
#      并重算欠款链（prev_debt / current_debt / total_debt），否则单据还显示"已结清"。
# ============================================================================

REVERSIBLE_TYPES: dict[str, tuple[str, str]] = {
    # transaction_type -> (单据模型, 单据上的"已收/已付"字段)
    "receipt": ("SalesOrder", "received_amount"),
    "payment": ("PurchaseOrder", "paid_amount"),
}


def _reverse_flow(
    db: Session, flow_id: int, payload: dict[str, object], *, expect_type: str
) -> dict[str, object]:
    """红冲一笔收/付款，返回 {original, reversal, applied_amount, order}。"""
    # 行锁：两个人同时点红冲时，第二个请求会等第一个提交后再读到"已被冲销"
    original = (
        db.query(FinancialTransaction)
        .filter(FinancialTransaction.id == flow_id)
        .with_for_update()
        .first()
    )
    if original is None:
        raise HTTPException(status_code=404, detail="流水不存在")

    label = "收款" if expect_type == "receipt" else "付款"
    if original.transaction_type != expect_type:
        raise HTTPException(
            status_code=409,
            detail=f"流水 #{flow_id} 不是{label}，不能在这里红冲",
        )
    if original.reversal_of_id is not None:
        # 红字行本身不许再冲：冲红冲 = 又把原单加回去，账面看着对、业务已经乱了
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reversal_of_reversal",
                "message": f"流水 #{flow_id} 本身是一笔红冲（冲的是 #{original.reversal_of_id}），不能再红冲。",
                "hint": "要撤销这次红冲，请重新登记一笔正常的收付款，而不是再冲一次。",
            },
        )

    existing = (
        db.query(FinancialTransaction)
        .filter(FinancialTransaction.reversal_of_id == original.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "already_reversed",
                "message": f"流水 #{flow_id} 已于此前被红冲（红冲流水 #{existing.id}），不能重复红冲。",
                "hint": "一笔收付款只能冲一次。如果金额还需要调整，请重新登记一笔新的收付款。",
                "reversal_id": existing.id,
            },
        )

    amount = round(float(original.amount or 0.0), 2)
    if amount <= 0:
        # 走不到这里（红字行已在上面挡掉），留着防御脏数据
        raise HTTPException(status_code=409, detail=f"流水 #{flow_id} 金额不为正，无法红冲")

    reason = str(payload.get("reason") or "").strip()
    occurred_at = str(payload.get("occurred_at") or "")[:10] or datetime.now().strftime("%Y-%m-%d")

    # ---- 先把"要回退多少"算清楚（必须用 applied_amount，不能用总额）----
    model = None
    amount_field = ""
    order = None
    applied = 0.0
    party_id = original.customer_id or original.supplier_id
    if original.related_order_id:
        model_name, amount_field = REVERSIBLE_TYPES[expect_type]
        model = SalesOrder if model_name == "SalesOrder" else PurchaseOrder
        order = db.get(model, int(original.related_order_id))
        if order is not None:
            current = float(getattr(order, amount_field) or 0.0)
            if original.applied_amount is None:
                # 存量数据：老版本没记 applied_amount → 只能按"总额与当前已收的较小者"估，
                # 再夹一次 >= 0，宁可少退也不能把单据冲成负数。
                applied = round(min(amount, max(current, 0.0)), 2)
            else:
                applied = round(min(float(original.applied_amount), amount), 2)
            applied = round(min(applied, max(current, 0.0)), 2)

    note = f"红冲 #{original.id}（{label} ¥{amount:.2f}）"
    if reason:
        note = f"{note}：{reason}"

    reversal = FinancialTransaction(
        transaction_type=original.transaction_type,
        related_type=original.related_type,
        related_order_id=original.related_order_id,
        doc_no=original.doc_no,
        direction=original.direction,
        customer_id=original.customer_id,
        supplier_id=original.supplier_id,
        bank_account_id=original.bank_account_id,  # 同一账户，余额才会自己抵消
        product_id=original.product_id,
        warehouse_id=original.warehouse_id,
        project_id=original.project_id,
        category=original.category,
        handler=original.handler,
        amount=-amount,  # 负数：`sum(amount)` 自动归零，不用改任何报表口径
        currency=original.currency or "CNY",
        occurred_at=occurred_at,
        period=_normalize_period(occurred_at),
        note=note[:255],
        reversal_of_id=original.id,
        applied_amount=None,  # 红字行不再"冲抵单据"，回退发生在原行那一侧
    )
    db.add(reversal)
    db.flush()

    # 凭证：方向对调（见 services/ledger.py 的 post_reversal_entry 说明）
    from app.services.ledger import post_reversal_entry

    post_reversal_entry(db, reversal, original)

    # ---- 回退单据的已收/已付，并重算欠款链 ----
    if order is not None and applied > 0:
        current = float(getattr(order, amount_field) or 0.0)
        setattr(order, amount_field, round(max(0.0, current - applied), 2))
        fk_field = model.customer_id if model is SalesOrder else model.supplier_id
        if getattr(order, fk_field.key) is not None:
            _recalc_debt_chain(db, model, fk_field, getattr(order, fk_field.key), amount_field)

    db.commit()
    db.refresh(reversal)

    return {
        "original": {
            "id": original.id,
            "amount": amount,
            "transaction_type": original.transaction_type,
            "is_reversed": True,
            "reversed_flow_id": reversal.id,
        },
        "reversal": {
            "id": reversal.id,
            "amount": float(reversal.amount),
            "transaction_type": reversal.transaction_type,
            "occurred_at": reversal.occurred_at,
            "period": reversal.period,
            "note": reversal.note,
            "reversal_of_id": reversal.reversal_of_id,
        },
        "applied_amount": applied,
        "order": (
            None
            if order is None
            else {
                "id": order.id,
                "amount_field": amount_field,
                "amount": float(getattr(order, amount_field) or 0.0),
                "current_debt": float(getattr(order, "current_debt", 0.0) or 0.0),
            }
        ),
        "party_id": party_id,
    }


@router.post("/finance/receipt/{flow_id}/reverse", status_code=status.HTTP_201_CREATED)
def reverse_receipt(
    flow_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """红冲一笔收款（生成负数收款流水，并回退销售单的已收金额）。"""
    return _reverse_flow(db, flow_id, payload or {}, expect_type="receipt")


@router.post("/finance/payment/{flow_id}/reverse", status_code=status.HTTP_201_CREATED)
def reverse_payment(
    flow_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """红冲一笔付款（生成负数付款流水，并回退采购单的已付金额）。"""
    return _reverse_flow(db, flow_id, payload or {}, expect_type="payment")


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
    # 红冲状态：一次聚合查询拿到 {被冲的流水 id: 红字行 id}，再挂到 ORM 实例上。
    # 逐行 `exists` 会变成 N+1（500 条流水 = 500 次查询），这里必须批量。
    flipped = dict(
        db.query(FinancialTransaction.reversal_of_id, FinancialTransaction.id)
        .filter(FinancialTransaction.reversal_of_id.isnot(None))
        .all()
    )
    for item in items:
        item.is_reversed = item.id in flipped
        item.reversed_flow_id = flipped.get(item.id)
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
    # 资金账户必须真实存在：否则这条流水会挂在一个不存在的账户上，
    # 现金银行页看不到它、余额也算不到它 —— 等于凭空少了一笔钱。
    account_id = data.get("bank_account_id")
    if account_id is not None and db.get(BankAccount, int(account_id)) is None:
        raise HTTPException(status_code=400, detail="所选资金账户不存在")
    item = FinancialTransaction(**data)
    db.add(item)
    db.flush()  # 先拿 item.id，供凭证挂 flow_id 用
    # 自动过账：人工登记的收支（income/expense）同样进总账，走与单据一致的过账规则
    from app.services.ledger import post_journal_entry

    post_journal_entry(db, item)
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
    # ⚠️ 金额列迁到 numeric(14,2) 之后，SUM() 回来的是 Decimal；
    # 这里统一转成 float 再相加，否则 float - Decimal 会直接 TypeError（2026-10-21 修）。
    total_revenue = sum((float(item["total"] or 0) for item in by_customer), 0.0)

    return {
        "total_revenue": float(total_revenue),
        "total_expense": float(expense_rows),
        "net_profit": float(total_revenue) - float(expense_rows or 0),
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



# ============================================================================
# 现金银行（账户档案 + 账户流水 + 账户间转账）
# ============================================================================
# 余额口径见 app/models/bank.py 的说明：只有真实资金移动才算，
# 应收应付 / 成本结转 / 报损报溢不进账户余额。

BANK_ACCOUNT_PREFIX = "TR"  # 转账单号前缀（账户档案用编码，不需要流水号）



def _account_balances(db: Session) -> dict[int, float]:
    """各账户当前余额 = 期初 + Σ流水增减（只看挂了账户的流水）。"""
    opening = {row.id: float(row.init_balance or 0.0) for row in db.query(BankAccount).all()}
    result = dict(opening)
    rows = (
        db.query(FinancialTransaction)
        .filter(FinancialTransaction.bank_account_id.isnot(None))
        .all()
    )
    for row in rows:
        account_id = int(row.bank_account_id)
        if account_id not in result:
            continue  # 账户被删了但流水还挂着（历史数据）—— 不计入任何账户
        result[account_id] = result.get(account_id, 0.0) + account_delta(row.transaction_type, row.amount)
    return result



def _account_payload(row: BankAccount, balance: float, flow_count: int) -> dict[str, object]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "account_type": row.account_type or "bank",
        "account_type_label": BANK_ACCOUNT_TYPES.get(row.account_type or "bank", row.account_type or ""),
        "bank_name": row.bank_name,
        "account_no": row.account_no,
        "init_balance": float(row.init_balance or 0.0),
        "current_balance": round(balance, 2),
        "flow_count": flow_count,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "note": row.note,
    }



def _validate_account(db: Session, payload: dict, *, exclude_id: int | None = None) -> None:
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="账户编码不能为空")
    dup = db.query(BankAccount).filter(BankAccount.code == code)
    if exclude_id is not None:
        dup = dup.filter(BankAccount.id != exclude_id)
    if dup.first() is not None:
        raise HTTPException(status_code=400, detail=f"账户编码「{code}」已存在")
    if str(payload.get("account_type") or "bank") not in BANK_ACCOUNT_TYPES:
        raise HTTPException(status_code=400, detail=f"账户类型只能是：{'、'.join(BANK_ACCOUNT_TYPES)}")



@router.get("/bank-accounts")
def list_bank_accounts(
    include_inactive: bool = Query(False), db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    """账户列表（含当前余额与流水条数）。余额 = 期初 + Σ资金流水。"""
    query = db.query(BankAccount)
    if not include_inactive:
        query = query.filter(BankAccount.is_active.is_(True))
    rows = query.order_by(BankAccount.sort_order, BankAccount.id).all()

    counts: dict[int, int] = {}
    for account_id, count in (
        db.query(FinancialTransaction.bank_account_id, func.count(FinancialTransaction.id))
        .filter(FinancialTransaction.bank_account_id.isnot(None))
        .group_by(FinancialTransaction.bank_account_id)
        .all()
    ):
        counts[int(account_id)] = int(count)

    balances = _account_balances(db)
    return [
        _account_payload(row, balances.get(row.id, float(row.init_balance or 0.0)), counts.get(row.id, 0))
        for row in rows
    ]



@router.post("/bank-accounts", status_code=status.HTTP_201_CREATED)
def create_bank_account(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    data = {
        "code": str(payload.get("code") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "account_type": str(payload.get("account_type") or "bank"),
        "bank_name": payload.get("bank_name"),
        "account_no": payload.get("account_no"),
        "init_balance": float(payload.get("init_balance") or 0.0),
        "is_active": payload.get("is_active", True) is not False,
        "sort_order": int(payload.get("sort_order") or 0),
        "note": payload.get("note"),
    }
    if not data["name"]:
        raise HTTPException(status_code=400, detail="账户名称不能为空")
    _validate_account(db, data)
    row = BankAccount(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _account_payload(row, float(row.init_balance or 0.0), 0)



@router.patch("/bank-accounts/{account_id}")
def update_bank_account(
    account_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    row = db.get(BankAccount, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    data = {
        "code": str(payload.get("code", row.code) or "").strip(),
        "name": str(payload.get("name", row.name) or "").strip(),
        "account_type": str(payload.get("account_type", row.account_type) or "bank"),
    }
    if not data["name"]:
        raise HTTPException(status_code=400, detail="账户名称不能为空")
    _validate_account(db, data, exclude_id=account_id)

    row.code = data["code"]
    row.name = data["name"]
    row.account_type = data["account_type"]
    for field in ("bank_name", "account_no", "note"):
        if field in payload:
            setattr(row, field, payload.get(field))
    if payload.get("init_balance") is not None:
        row.init_balance = float(payload["init_balance"])
    if payload.get("is_active") is not None:
        row.is_active = bool(payload["is_active"])
    if payload.get("sort_order") is not None:
        row.sort_order = int(payload["sort_order"])
    db.commit()
    db.refresh(row)
    balances = _account_balances(db)
    count = db.query(FinancialTransaction).filter(FinancialTransaction.bank_account_id == account_id).count()
    return _account_payload(row, balances.get(account_id, float(row.init_balance or 0.0)), count)



@router.delete("/bank-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(account_id: int, db: Session = Depends(get_db)) -> Response:
    """删账户。**有流水或转账时禁删**（409）—— 删掉会让那些流水指向不存在的账户，
    余额页从此对不上，而且没有任何入口能修回来。停用它才是正确操作。"""
    row = db.get(BankAccount, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="账户不存在")
    flow_count = db.query(FinancialTransaction).filter(FinancialTransaction.bank_account_id == account_id).count()
    transfer_count = (
        db.query(BankTransfer)
        .filter((BankTransfer.from_account_id == account_id) | (BankTransfer.to_account_id == account_id))
        .count()
    )
    if flow_count or transfer_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"账户「{row.name}」已有 {flow_count} 条流水"
                + (f"、{transfer_count} 笔转账" if transfer_count else "")
                + "，不能删除。请改用「停用」。"
            ),
        )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/bank-accounts/{account_id}/ledger")
def bank_account_ledger(
    account_id: int,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """账户流水账：期初 → 逐笔 → 期末。与往来对账同一套呈现方式。

    期初 = 账户期初余额 + 区间起点之前的资金流水；期末 = 期初 + 区间内净额。
    """
    row = db.get(BankAccount, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    flows = (
        db.query(FinancialTransaction)
        .filter(FinancialTransaction.bank_account_id == account_id)
        .order_by(FinancialTransaction.occurred_at.asc(), FinancialTransaction.id.asc())
        .all()
    )
    opening = float(row.init_balance or 0.0)
    in_range: list[FinancialTransaction] = []
    for flow in flows:
        day = (flow.occurred_at or "")[:10]
        if from_date and day and day < from_date:
            opening += account_delta(flow.transaction_type, flow.amount)
        elif to_date and day and day > to_date:
            continue
        else:
            in_range.append(flow)

    increase = sum(
        account_delta(f.transaction_type, f.amount) for f in in_range if account_delta(f.transaction_type, f.amount) > 0
    )
    decrease = -sum(
        account_delta(f.transaction_type, f.amount) for f in in_range if account_delta(f.transaction_type, f.amount) < 0
    )
    closing = opening + increase - decrease

    return {
        "account": _account_payload(row, closing, len(flows)),
        "period": {"from_date": from_date, "to_date": to_date},
        "summary": {
            "opening_balance": round(opening, 2),
            "increase": round(increase, 2),
            "decrease": round(decrease, 2),
            "closing_balance": round(closing, 2),
        },
        "rows": [
            {
                "id": f.id,
                "occurred_at": f.occurred_at,
                "transaction_type": f.transaction_type,
                "type_label": DOC_TYPES.get(f.related_type or "", "") or f.transaction_type,
                "category": f.category,
                "amount": float(f.amount or 0.0),
                "delta": round(account_delta(f.transaction_type, f.amount), 2),
                "doc_no": f.doc_no,
                "customer_id": f.customer_id,
                "supplier_id": f.supplier_id,
                "handler": f.handler,
                "note": f.note,
            }
            for f in in_range
        ],
    }



@router.get("/bank-transfers")
def list_bank_transfers(
    skip: int = 0, limit: int | None = None, db: Session = Depends(get_db)
) -> list[dict[str, object]]:
    names = {row.id: row.name for row in db.query(BankAccount).all()}
    rows = _paginate(db.query(BankTransfer).order_by(BankTransfer.id.desc()), skip, limit).all()
    return [
        {
            "id": row.id,
            "transfer_no": row.transfer_no,
            "from_account_id": row.from_account_id,
            "from_account_name": names.get(row.from_account_id, f"账户-{row.from_account_id}"),
            "to_account_id": row.to_account_id,
            "to_account_name": names.get(row.to_account_id, f"账户-{row.to_account_id}"),
            "amount": float(row.amount or 0.0),
            "transfer_date": row.transfer_date,
            "handler": row.handler,
            "note": row.note,
            "created_at": row.created_at,
        }
        for row in rows
    ]



@router.post("/bank-transfers", status_code=status.HTTP_201_CREATED)
def create_bank_transfer(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """账户间转账：写一条转出、一条转入，两条共用 same related_order_id 便于整体冲销。"""
    try:
        from_id = int(payload.get("from_account_id") or 0)
        to_id = int(payload.get("to_account_id") or 0)
        amount = float(payload.get("amount") or 0.0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="账户或金额格式不对") from exc

    if from_id == to_id:
        raise HTTPException(status_code=400, detail="转出与转入不能是同一个账户")
    from_account = db.get(BankAccount, from_id)
    to_account = db.get(BankAccount, to_id)
    if from_account is None or to_account is None:
        raise HTTPException(status_code=400, detail="转出或转入账户不存在")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="转账金额必须大于 0")

    occurred_at = str(payload.get("transfer_date") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    row = BankTransfer(
        transfer_no=_next_doc_no(db, BankTransfer, BANK_ACCOUNT_PREFIX, field="transfer_no"),
        from_account_id=from_id,
        to_account_id=to_id,
        amount=amount,
        transfer_date=occurred_at,
        handler=payload.get("handler"),
        note=payload.get("note"),
    )
    db.add(row)
    db.flush()

    for account, account_type, direction, label in (
        (from_account, "transfer_out", "out", "转出"),
        (to_account, "transfer_in", "in", "转入"),
    ):
        db.add(
            FinancialTransaction(
                transaction_type=account_type,
                amount=amount,
                direction=direction,
                bank_account_id=account.id,
                related_type="bank_transfer",
                related_order_id=row.id,
                doc_no=row.transfer_no,
                category="账户转账",
                handler=row.handler,
                occurred_at=occurred_at,
                period=_normalize_period(occurred_at),
                note=f"{label}：{row.note}" if row.note else f"账户转账 {label}（{from_account.name} → {to_account.name}）",
            )
        )
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "transfer_no": row.transfer_no,
        "from_account_id": from_id,
        "from_account_name": from_account.name,
        "to_account_id": to_id,
        "to_account_name": to_account.name,
        "amount": amount,
        "transfer_date": occurred_at,
        "handler": row.handler,
        "note": row.note,
        "created_at": row.created_at,
    }



@router.delete("/bank-transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_transfer(transfer_id: int, db: Session = Depends(get_db)) -> Response:
    """删转账并连带删掉它的两条流水（与其它单据的"删单冲销"同一约定）。"""
    row = db.get(BankTransfer, transfer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="转账记录不存在")
    db.query(FinancialTransaction).filter(
        FinancialTransaction.related_type == "bank_transfer",
        FinancialTransaction.related_order_id == transfer_id,
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.delete("/finance/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finance_entry(entry_id: int, db: Session = Depends(get_db)) -> Response:
    """删一条**人工登记**的日常收支。

    死守两条：类型必须是 income / expense，且**没有来源单据**（related_type 为空）。
    单据自动写的流水（采购入库的应付、销售开单的应收、生产的成本……）
    必须跟着单据走 —— 单独删掉一条，账就和单据对不上了，而且没有任何痕迹。
    """
    row = db.get(FinancialTransaction, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="收支记录不存在")
    if row.transaction_type not in ("income", "expense"):
        raise HTTPException(status_code=409, detail="只有日常收入/支出可以在这里删除")
    if row.related_type:
        raise HTTPException(
            status_code=409,
            detail=f"这条流水由「{DOC_TYPES.get(row.related_type, row.related_type)}」自动生成，请到对应单据上删除",
        )
    db.delete(row)
    # 同生共死：删掉流水，把它的凭证（若已过账）一并删掉，避免孤儿凭证污染总账
    from app.services.ledger import delete_journal_entries_for_flow

    delete_journal_entries_for_flow(db, row.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/finance/entries")
def list_finance_entries(
    entry_type: str | None = Query(None, description="income / expense；不传则两者都返回"),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    bank_account_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """日常收支明细（只含 income / expense 两类），带收入支出合计。

    与 `/finance` 的区别：那条是**全量流水**（含单据自动写的应收应付/成本）；
    这条只服务"日常收支"这一个页面，因此只挑人工登记的收支。
    """
    query = db.query(FinancialTransaction).filter(
        FinancialTransaction.transaction_type.in_(["income", "expense"])
    )
    if entry_type:
        if entry_type not in ("income", "expense"):
            raise HTTPException(status_code=400, detail="entry_type 只能是 income 或 expense")
        query = query.filter(FinancialTransaction.transaction_type == entry_type)
    if from_date:
        query = query.filter(FinancialTransaction.occurred_at >= from_date)
    if to_date:
        query = query.filter(FinancialTransaction.occurred_at <= to_date)
    if bank_account_id is not None:
        query = query.filter(FinancialTransaction.bank_account_id == bank_account_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                FinancialTransaction.note.ilike(like),
                FinancialTransaction.category.ilike(like),
                FinancialTransaction.handler.ilike(like),
                FinancialTransaction.doc_no.ilike(like),
            )
        )

    total_income = 0.0
    total_expense = 0.0
    for row in query.all():
        if row.transaction_type == "income":
            total_income += float(row.amount or 0.0)
        else:
            total_expense += float(row.amount or 0.0)

    rows = _paginate(query.order_by(FinancialTransaction.id.desc()), skip, limit).all()
    accounts = {row.id: row.name for row in db.query(BankAccount).all()}
    return {
        "items": [
            {
                "id": row.id,
                "transaction_type": row.transaction_type,
                "occurred_at": row.occurred_at,
                "period": row.period,
                "category": row.category,
                "amount": float(row.amount or 0.0),
                "bank_account_id": row.bank_account_id,
                "bank_account_name": accounts.get(row.bank_account_id) if row.bank_account_id else None,
                "handler": row.handler,
                "note": row.note,
                "doc_no": row.doc_no,
                # 来源单据类型：**必须下发**。删除接口是按它拒绝删除的
                # （单据自动写的流水要跟着单据走），前端不拿到它就只能在界面上
                # 摆一个"点了必然报错"的删除按钮。顺便让界面能如实标出
                # 「这条是发票/入库单自动生成的」。
                "related_type": row.related_type,
                "related_type_label": DOC_TYPES.get(row.related_type or "", "") or None,
                "customer_id": row.customer_id,
                "supplier_id": row.supplier_id,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "summary": {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net": round(total_income - total_expense, 2),
        },
    }
