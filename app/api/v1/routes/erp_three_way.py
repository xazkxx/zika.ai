"""三单匹配（合同 / 发票 / 付款）—— 2026-10-23。

## 这个看板回答什么问题

"这张合同，票开了没有？钱收了没有？差在哪一笔？"

财务月底最怕的不是"有缺口"，而是"知道有缺口但查不出差在哪"。
所以这里做两件事：
  1. **汇总**：逐合同算 已开票 / 未开票缺口 / 已付 / 未付缺口 / 匹配率；
  2. **可下钻**：抽屉里把该合同的明细、每一张发票、每一笔收付款按时间线列出来。

## 匹配是分级的（很重要，直接决定数字可不可信）

| 级别 | 规则 | 可信度 |
|---|---|---|
| 精确 | 合同 → 单据（contracts.order_id）→ 发票/流水（related_order_id） | 高：真的挂了单 |
| 估算 | 合同没转单时，取该往来单位**未挂任何单据**的发票/流水，按日期顺序分配给该单位未转单合同（按签订日期） | 中：能对上单位与金额，但具体归属于哪张合同是推断的 |

为什么必须有"估算"这一级：合同没转单时，erp 里压根没有 order_id 可链，
如果只做精确匹配，这类合同永远是"票 0 元、款 0 元"，看板一片红且毫无信息量。
估算的每一笔在抽屉里都标注了「按单位估算」，财务能一眼分辨 —— **不假装精确**。

## 口径

- 已开票：销项合同取 `output` 发票，进项合同取 `input` 发票；
- 已付：销项取 `receipt`（收款），进项取 `payment`（付款）；
  **应收/应付的记账行（receivable/payable）不算实付** —— 那是债权债务，不是钱。
- 缺口 = 合同总额 − 已开票 / 已付。允许为负（超开票/超付），负数在界面上标「超」。
- 匹配率 = (min(已开票, 合同额) + min(已付, 合同额)) / (2 × 合同额)：
  票、款两项各占一半；超出的部分不重复加分。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.contract import Contract, ContractItem
from app.models.finance import FinancialTransaction
from app.models.invoice import Invoice

router = APIRouter(tags=["three-way-match"])

# 实际收付款的流水类型（不含 receivable/payable 这类记账行）
FLOW_TYPES = ("receipt", "payment")


def _flow_method(note: str | None) -> str:
    """从流水备注里取付款方式。

    ⚠️ `FinancialTransaction` **没有** payment_method 列 —— 付款方式一直存在
    `note` 里（形如 "收款登记：XX 工程｜方式：微信"）。直接读属性会 AttributeError，
    而且只有"存在挂单流水"的数据才会触发（单跑测试造不出这种数据，全量跑才炸）。
    """
    text = str(note or "")
    if "方式：" in text:
        return text.split("方式：")[-1].strip()[:20]
    return ""


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _party_key(contract: Contract) -> str:
    """往来单位的归并键：优先 party_id（同名不同号才分得清），没 id 时退回名称。"""
    if contract.party_id:
        return f"{contract.party_type or 'customer'}:{int(contract.party_id)}"
    return f"{contract.party_type or 'customer'}:name:{(contract.party_name or '').strip()}"


def _status_of(invoice_gap: float, pay_gap: float) -> tuple[str, str]:
    """状态与颜色。判定顺序按需求：两项都缺 > 单项缺 > 闭环。"""
    inv_missing = invoice_gap > 0.005
    pay_missing = pay_gap > 0.005
    if inv_missing and pay_missing:
        return "both_missing", "票款均未齐"
    if inv_missing:
        return "invoice_missing", "发票未齐"
    if pay_missing:
        return "payment_missing", "付款未齐"
    return "closed", "已闭环"


def _load_invoice_map(db: Session, order_ids: list[int]) -> dict[int, list[dict]]:
    """单据 → 发票（精确级）。"""
    if not order_ids:
        return {}
    rows = (
        db.query(Invoice)
        .filter(Invoice.related_order_id.in_(order_ids))
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    )
    result: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        result[int(row.related_order_id)].append(
            {
                "id": row.id,
                "invoice_no": row.invoice_no,
                "issue_date": row.issue_date,
                "amount": _money(row.total_amount),
                "direction": row.direction,
                "status": row.status,
                "source": "order",
            }
        )
    return result


def _load_flow_map(db: Session, order_ids: list[int]) -> dict[int, list[dict]]:
    """单据 → 实收实付流水（精确级）。"""
    if not order_ids:
        return {}
    rows = (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.related_order_id.in_(order_ids),
            FinancialTransaction.transaction_type.in_(FLOW_TYPES),
        )
        .order_by(FinancialTransaction.occurred_at, FinancialTransaction.id)
        .all()
    )
    result: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        result[int(row.related_order_id)].append(
            {
                "id": row.id,
                "occurred_at": str(row.occurred_at or ""),
                "amount": _money(row.amount),
                "type": row.transaction_type,
                "method": _flow_method(row.note),
                "note": row.note,
                "source": "order",
            }
        )
    return result


def _load_loose_pools(db: Session) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """未挂任何单据的发票 / 收付款，按往来单位归堆（估算级用）。

    ⚠️ 只取 `related_order_id IS NULL` 的：已经挂到单据上的钱/票，
    如果再参与"估算分配"就是一笔钱算两次。
    """
    invoices: dict[str, list[dict]] = defaultdict(list)
    for row in (
        db.query(Invoice)
        .filter(Invoice.related_order_id.is_(None))
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    ):
        name = (row.counterparty_name or row.buyer_name or "").strip()
        key = (
            f"customer:{int(row.customer_id)}"
            if getattr(row, "customer_id", None)
            else f"customer:name:{name}"
        )
        if not getattr(row, "customer_id", None) and not name:
            continue
        invoices[key].append(
            {
                "id": row.id,
                "invoice_no": row.invoice_no,
                "issue_date": row.issue_date,
                "amount": _money(row.total_amount),
                "direction": row.direction,
                "status": row.status,
                "source": "party",
            }
        )
        # 进项发票没有 supplier_id，用名称同时挂一份到 supplier 键上
        if row.direction == "input" and name:
            seller_key = f"supplier:name:{name}"
            if seller_key != key:
                invoices[seller_key].append(invoices[key][-1])

    flows: dict[str, list[dict]] = defaultdict(list)
    for row in (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.related_order_id.is_(None),
            FinancialTransaction.transaction_type.in_(FLOW_TYPES),
        )
        .order_by(FinancialTransaction.occurred_at, FinancialTransaction.id)
        .all()
    ):
        key = None
        if row.transaction_type == "receipt" and getattr(row, "customer_id", None):
            key = f"customer:{int(row.customer_id)}"
        elif getattr(row, "supplier_id", None):
            key = f"supplier:{int(row.supplier_id)}"
        if key is None:
            continue
        flows[key].append(
            {
                "id": row.id,
                "occurred_at": str(row.occurred_at or ""),
                "amount": _money(row.amount),
                "type": row.transaction_type,
                "method": _flow_method(row.note),
                "note": row.note,
                "source": "party",
            }
        )
    return invoices, flows


def _allocate(pool: list[dict], contracts: list[Contract], key: str) -> dict[int, dict]:
    """把某单位"未挂单"的票/款按顺序分配给该单位未转单的合同。

    分配规则（刻意简单、可解释）：
      · 合同按签订日期升序，票/款按发生日期升序；
      · 每笔**整笔**给当前第一个仍有缺口的合同（不拆票 —— 拆了财务对不上号）；
      · 合同都满了就停止，剩下的不硬塞（宁可少算，不可凭空多算）。
    """
    result: dict[int, dict] = {}
    if not pool or not contracts:
        return result

    pending = sorted(contracts, key=lambda item: (item.sign_date or "", item.id))
    cursor = 0
    for contract in pending:
        total = _money(contract.total_amount)
        picked: list[dict] = []
        used = 0.0
        while cursor < len(pool) and used < total - 0.005:
            item = pool[cursor]
            picked.append(item)
            used += item["amount"]
            cursor += 1
        if picked:
            result[int(contract.id)] = {"items": picked, "amount": round(used, 2)}
    return result


def build_three_way_rows(db: Session, contracts: list[Contract]) -> list[dict]:
    """把一批合同算成三单匹配行（一次批量查询，不做 N+1）。"""
    order_ids = [int(item.order_id) for item in contracts if item.order_id]
    invoice_by_order = _load_invoice_map(db, order_ids)
    flow_by_order = _load_flow_map(db, order_ids)
    loose_invoices, loose_flows = _load_loose_pools(db)

    # 按往来单位分组，供估算级分配
    by_party: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        by_party[_party_key(contract)].append(contract)

    estimated_invoices: dict[int, dict] = {}
    estimated_flows: dict[int, dict] = {}
    for key, party_contracts in by_party.items():
        # 只有"没转单"的合同才需要估算 —— 已转单的按单据链算，绝不混用两套口径
        unlinked = [item for item in party_contracts if not item.order_id]
        if not unlinked:
            continue
        direction = "input" if (unlinked[0].direction or "out") == "in" else "output"
        pool_inv = [row for row in loose_invoices.get(key, []) if row["direction"] == direction]
        estimated_invoices.update(_allocate(pool_inv, unlinked, key))
        pool_flow = [row for row in loose_flows.get(key, [])]
        estimated_flows.update(_allocate(pool_flow, unlinked, key))

    rows: list[dict] = []
    for contract in contracts:
        total = _money(contract.total_amount)
        exact_inv = invoice_by_order.get(int(contract.order_id), []) if contract.order_id else []
        exact_flow = flow_by_order.get(int(contract.order_id), []) if contract.order_id else []
        est_inv = estimated_invoices.get(int(contract.id), {})
        est_flow = estimated_flows.get(int(contract.id), {})

        invoiced = round(sum(item["amount"] for item in exact_inv) + float(est_inv.get("amount", 0)), 2)
        paid = round(sum(item["amount"] for item in exact_flow) + float(est_flow.get("amount", 0)), 2)
        invoice_gap = round(total - invoiced, 2)
        pay_gap = round(total - paid, 2)
        status_code, status_label = _status_of(invoice_gap, pay_gap)

        # 匹配率：票、款各占 50%，超出合同额的部分不重复加分
        if total > 0:
            ratio = (min(invoiced, total) + min(paid, total)) / (2 * total) * 100
        else:
            ratio = 0.0

        rows.append(
            {
                "contract_id": int(contract.id),
                "contract_no": contract.contract_no,
                "title": contract.title,
                "party_name": contract.party_name,
                "direction": contract.direction or "out",
                "sign_date": contract.sign_date,
                "status": contract.status,
                "total_amount": total,
                "invoiced_amount": invoiced,
                "invoice_gap": invoice_gap,
                "paid_amount": paid,
                "payment_gap": pay_gap,
                "match_ratio": round(ratio, 2),
                "match_status": status_code,
                "match_label": status_label,
                # 口径透明：前端在合同号旁标「估算」小标签
                "invoice_source": "order" if exact_inv else ("party" if est_inv.get("items") else "none"),
                "payment_source": "order" if exact_flow else ("party" if est_flow.get("items") else "none"),
                "order_id": contract.order_id,
                "order_no": contract.order_no,
            }
        )
    return rows


def _totals(rows: list[dict]) -> dict:
    return {
        "contract_count": len(rows),
        "contract_amount": round(sum(row["total_amount"] for row in rows), 2),
        "invoiced_amount": round(sum(row["invoiced_amount"] for row in rows), 2),
        "invoice_gap": round(sum(row["invoice_gap"] for row in rows), 2),
        "paid_amount": round(sum(row["paid_amount"] for row in rows), 2),
        "payment_gap": round(sum(row["payment_gap"] for row in rows), 2),
        "closed_count": sum(1 for row in rows if row["match_status"] == "closed"),
        "both_missing": sum(1 for row in rows if row["match_status"] == "both_missing"),
    }


@router.get("/three-way-match", summary="三单匹配看板：合同 / 发票 / 付款 三方对账")
def three_way_match(
    keyword: str = Query("", description="合同号 / 名称 / 往来单位"),
    status: str = Query("", description="both_missing / invoice_missing / payment_missing / closed"),
    direction: str = Query("", description="out 应收侧 / in 应付侧"),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """一次返回行与 KPI。

    KPI 按**全部命中筛选的合同**汇总（不是当前页），否则"合同总额"会随翻页变化，
    财务对账时会被吓一跳。
    """
    query = db.query(Contract).filter(Contract.status != "void")
    if direction in ("out", "in"):
        query = query.filter(Contract.direction == direction)
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        query = query.filter(
            Contract.contract_no.ilike(like) | Contract.title.ilike(like) | Contract.party_name.ilike(like)
        )
    contracts = query.order_by(Contract.sign_date.desc(), Contract.id.desc()).all()
    rows = build_three_way_rows(db, contracts)

    if status:
        rows = [row for row in rows if row["match_status"] == status]

    totals = _totals(rows)
    page = rows[skip : skip + limit]
    return {
        "rows": page,
        "totals": totals,
        "count": len(rows),
        "skip": skip,
        "limit": limit,
        "generated_at": date.today().isoformat(),
    }


@router.get("/contracts/{contract_id}/three-way-detail", summary="三单匹配明细（抽屉用）")
def three_way_detail(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """一张合同的全部底稿：明细、每张票、每笔款、付款计划，缺口逐条对着看。"""
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    items = (
        db.query(ContractItem).filter(ContractItem.contract_id == contract_id).order_by(ContractItem.id).all()
    )
    row = build_three_way_rows(db, [contract])[0]

    order_ids = [int(contract.order_id)] if contract.order_id else []
    exact_inv = _load_invoice_map(db, order_ids).get(int(contract.order_id), []) if order_ids else []
    exact_flow = _load_flow_map(db, order_ids).get(int(contract.order_id), []) if order_ids else []

    loose_invoices, loose_flows = _load_loose_pools(db)
    key = _party_key(contract)
    direction = "input" if (contract.direction or "out") == "in" else "output"
    pool_inv = [item for item in loose_invoices.get(key, []) if item["direction"] == direction]
    est_inv = _allocate(pool_inv, [contract], key).get(int(contract.id), {}).get("items", [])
    est_flow = _allocate(loose_flows.get(key, []), [contract], key).get(int(contract.id), {}).get("items", [])

    # 付款计划作为"计划侧"参考（不是实际付款，不能混进已付）
    from app.models.contract_payment import ContractPaymentPlan

    plans = (
        db.query(ContractPaymentPlan)
        .filter(ContractPaymentPlan.contract_id == contract_id)
        .order_by(ContractPaymentPlan.period_no)
        .all()
    )

    return {
        "contract": {
            "id": contract.id,
            "contract_no": contract.contract_no,
            "title": contract.title,
            "party_name": contract.party_name,
            "direction": contract.direction or "out",
            "sign_date": contract.sign_date,
            "status": contract.status,
            "total_amount": _money(contract.total_amount),
            "payment_terms": contract.payment_terms,
            "order_no": contract.order_no,
        },
        "summary": row,
        "items": [
            {
                "id": item.id,
                "product_name": item.product_name,
                "standards": item.standards,
                "unit": item.unit,
                "quantity": _money(item.quantity),
                "unit_price": _money(item.unit_price),
                "amount": _money(item.amount),
            }
            for item in items
        ],
        # source: order=单据精确关联；party=按单位估算
        "invoices": exact_inv + est_inv,
        "payments": exact_flow + est_flow,
        "payment_plans": [
            {
                "period_no": plan.period_no,
                "name": plan.name,
                "plan_date": plan.plan_date,
                "plan_amount": _money(plan.plan_amount),
                "paid_amount": _money(plan.paid_amount),
                "has_receipt": bool(plan.receipt_path),
            }
            for plan in plans
        ],
        "unlinked": not contract.order_id,
    }
