"""发票 → 业务单据 自动匹配（业财一体化 · 第一根钉子）。

## 为什么需要它

`invoices.related_order_id` 是"发票孤岛"接回业务流的**唯一锚点**：

- 出库单完结闸（`erp_sales.py` 的 `not_settled`）只按它统计"未开票金额"；
- 对账单的"四流穿透明细"（业务 → 签收 → 发票 → 资金）也只按它把票挂到单上。

以前全靠人在下拉里手工挑，现实结果是"库里一堆票、单据上一张都没挂"，
于是出库单永远结不了案、对账单上"已开票"永远为 0。

## 匹配策略：只自动落库"有把握的那部分"

模型注释里当初写着"不自动匹配"，理由是一票多单 / 一单多票猜不准 —— 这个判断今天仍然成立。
所以这里不是"尽量都挂上"，而是：

    只有**唯一强证据**成立时才自动写库，其余一律返回候选让人点。

自动落库的三个条件（缺一不可）：

1. **金额一致**：发票价税合计 == 单据净额（`total_amount - discount_amount`），容差 0.01；
2. **余量够**：该单未开票余额 ≥ 本票金额（不制造"超开票"，否则完结闸会被骗过）；
3. **唯一**：满足前两条的候选恰好 1 张。

其余情况返回 `ambiguous`（有候选、请人点）或 `none`（人工兜底）。

## 三条硬规矩

1. **绝不覆盖人工**：`related_order_id` 已有值 → 直接 `skipped`。
   要改只能在发票弹窗里手改，或在候选框里明确选一个。
2. **红字发票不自动挂**：冲红票必须和它冲的那张蓝票挂在同一张单上，
   而"是哪一张"只有开票人知道。金额是负数，任何按金额猜的做法都会挂错。
3. **方向决定目标表**，且只认"出库单 / 入库单"：
   销项 → `sales_orders.doc_type='outbound'`；进项 → `purchase_orders.doc_type='inbound'`。
   为什么不认"订单"：完结闸和钱票两清算的就是这两张单，挂到订单上等于挂了个不参与结算的壳。

## 税号优先、名称兜底（2026-10-22 起两边都支持）

客户档案本来就有 `tax_no`；供应商档案 2026-10-22 补了这一列（`app/db/migration_columns.py::SUPPLIER_COLUMNS`）。
现在**销项、进项都是"税号优先 → 名称归一化全等兜底"**：

- 税号是税局发的唯一标识，OCR 认它的准确率也高于名称；
- 名称只在"简称 vs 全称"这种必然发生的场景下兜底，且**只做全等**、不做包含
  （"XX公司"包含于"XX公司第一分公司"，按包含判会张冠李戴）；
- 税号命中多条档案（同税号挂多主体，库里真实存在）→ 视为歧义，退回名称，**不猜**。

## 唯一口径

`order_invoiced_amount()` 与完结闸（`erp_sales.py`）用的是同一条 SQL。
以后再加"对账单/报表"要统计已开票，一律调这个函数，不许另写一份。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.invoice import (
    DIRECTION_INPUT,
    DIRECTION_OUTPUT,
    Invoice,
    _normalize_name,
    _normalize_tax_no,
)
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier

# 金额容差：分位。库里全是 Numeric(14,2)，用 1 分钱做容差足够，也不至于把
# "差 1 块钱"的近似单当成同一笔。
MONEY_EPS = 0.01

# 单据日期窗口：发票通常滞后于业务 0~90 天，个别跨年补票留到 180 天；
# 提前开票（预开）给 60 天余量。窗口外的单不进候选 —— 不是"日期越近越可能是它"，
# 而是"太远的单基本可以排除"，否则一个两年前的同额单会来抢分。
WINDOW_BEFORE_DAYS = 180
WINDOW_AFTER_DAYS = 60

MAX_CANDIDATES = 8

# —— 打分权重（只影响排序，不决定是否自动落库）——
S_AMOUNT_EQUAL = 50  # 金额完全相等
S_ORDER_NO_IN_TEXT = 30  # OCR 原文里出现了单号
S_BALANCE_ENOUGH = 15  # 未开票余量足够
S_PARTY_ID_RESOLVED = 10  # 往来单位是按 id 命中的（不是靠名字猜的）
S_GAP_7 = 20
S_GAP_30 = 10
S_GAP_90 = 5

STATUS_MATCHED = "matched"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NONE = "none"
STATUS_SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# 唯一口径：某张单"已开票多少"
# ---------------------------------------------------------------------------
def order_invoiced_amount(db: Session, order_id: int) -> float:
    """该单据已挂发票的价税合计（红字票是负数，天然抵扣）。

    与 `erp_sales.py` 完结闸里的那段 SQL **逐字等价**；改这里必须同步那边，
    或者干脆把那边也改成调这个函数（本轮已改）。
    """
    total = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.related_order_id == order_id)
        .scalar()
    )
    return round(float(total or 0.0), 2)


def order_net_amount(order: SalesOrder | PurchaseOrder) -> float:
    """单据净额 = 总额 − 优惠（发票应当开的金额）。收付款登记也用这个口径。"""
    return round(
        float(order.total_amount or 0) - float(order.discount_amount or 0),
        2,
    )


def order_uninvoiced_amount(db: Session, order: SalesOrder | PurchaseOrder) -> float:
    """未开票金额 = max(总额 − 已开票, 0)。

    ⚠️ 这里用**总额**而不是净额，是为了和完结闸（`erp_sales.py` 的 `not_settled`）
    逐字对齐 —— 强提醒必须能准确预测"点完结会不会被拦"，两个口径差一个优惠额，
    用户就会看到"提醒说还差 100，完结却说得差 0"。

    取 0 下限：多开的票（分位差、含税差）不该让"未开票"变负数，
    否则完结闸的 `uninvoiced > 0` 判断会因为 −0.01 永远拦住用户。
    """
    return round(max(0.0, float(order.total_amount or 0) - order_invoiced_amount(db, order.id)), 2)


# ---------------------------------------------------------------------------
# 结构
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """一张候选单据。字段名刻意"人话"，因为要原样吐给前端弹窗。"""

    order_id: int
    order_no: str
    order_date: str
    party_id: int
    party_name: str
    net_amount: float
    invoiced_amount: float
    uninvoiced_amount: float
    amount_equal: bool
    balance_enough: bool
    date_gap: int | None
    score: int
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "order_no": self.order_no,
            "order_date": self.order_date,
            "party_id": self.party_id,
            "party_name": self.party_name,
            "net_amount": self.net_amount,
            "invoiced_amount": self.invoiced_amount,
            "uninvoiced_amount": self.uninvoiced_amount,
            "amount_equal": self.amount_equal,
            "balance_enough": self.balance_enough,
            "date_gap": self.date_gap,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass
class MatchOutcome:
    status: str
    invoice_id: int
    invoice_no: str
    direction: str
    order_id: int | None
    order_no: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    applied: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "invoice_id": self.invoice_id,
            "invoice_no": self.invoice_no,
            "direction": self.direction,
            "order_id": self.order_id,
            "order_no": self.order_no,
            "reason": self.reason,
            "applied": self.applied,
            "candidates": [item.as_dict() for item in self.candidates],
        }


# ---------------------------------------------------------------------------
# 往来单位解析
# ---------------------------------------------------------------------------
def _resolve_customer(db: Session, invoice: Invoice) -> tuple[int | None, str]:
    """销项：税号优先 → 名称归一化全等兜底。

    顺序为什么是税号在前：对方开票时把"西安XX科技有限公司"写成"西安XX科技"是常态，
    而税号是税局发的唯一标识。名称放前面会让一次简称把票挂到别人单上。
    税号命中多条（同税号挂多档案，库里真实存在）→ 视为歧义，退回名称，不猜。
    """
    if invoice.customer_id:
        row = db.get(Customer, int(invoice.customer_id))
        if row is not None:
            return row.id, row.name or ""

    tax = _normalize_tax_no(invoice.buyer_tax_no)
    if tax:
        rows = db.query(Customer).filter(Customer.tax_no.isnot(None)).all()
        hits = [row for row in rows if _normalize_tax_no(row.tax_no) == tax]
        if len(hits) == 1:
            return hits[0].id, hits[0].name or ""

    target = _normalize_name(invoice.buyer_name or invoice.counterparty_name)
    if target:
        for row in db.query(Customer).all():
            if _normalize_name(row.name) == target:
                return row.id, row.name or ""
    return None, ""


def _resolve_supplier(db: Session, invoice: Invoice) -> tuple[int | None, str]:
    """进项：税号优先 → 名称归一化全等兜底（口径与 `_resolve_customer` 一致）。

    2026-10-22 之前这里**只按名称**，因为 `suppliers` 没有税号列。
    现在补了列（见 `app/db/migration_columns.py::SUPPLIER_COLUMNS`），进项票终于也能按税号认人 ——
    这正是"陕西送变电"和"陕西送变电工程有限公司"能对上同一家的关键。
    """
    tax = _normalize_tax_no(invoice.seller_tax_no)
    if tax:
        rows = db.query(Supplier).filter(Supplier.tax_no.isnot(None)).all()
        hits = [row for row in rows if _normalize_tax_no(row.tax_no) == tax]
        if len(hits) == 1:
            return hits[0].id, hits[0].name or ""

    target = _normalize_name(invoice.seller_name or invoice.counterparty_name)
    if not target:
        return None, ""
    for row in db.query(Supplier).all():
        if _normalize_name(row.name) == target:
            return row.id, row.name or ""
    return None, ""


def _resolve_party(db: Session, invoice: Invoice) -> tuple[int | None, str, str]:
    if invoice.direction == DIRECTION_OUTPUT:
        party_id, name = _resolve_customer(db, invoice)
        return party_id, name, "客户"
    party_id, name = _resolve_supplier(db, invoice)
    return party_id, name, "供应商"


# ---------------------------------------------------------------------------
# 候选与打分
# ---------------------------------------------------------------------------
def _date_gap(order_date: str | None, issue_date: str | None) -> int | None:
    """单据日期与开票日差多少天。字符串 ISO 日期，解析不了就当未知（None）。"""
    try:
        left = datetime.strptime(str(order_date or "")[:10], "%Y-%m-%d").date()
        right = datetime.strptime(str(issue_date or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return abs((right - left).days)


def _window(issue_date: str | None) -> tuple[str, str] | None:
    try:
        base = datetime.strptime(str(issue_date or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    start = base - timedelta(days=WINDOW_BEFORE_DAYS)
    end = base + timedelta(days=WINDOW_AFTER_DAYS)
    return start.isoformat(), end.isoformat()


def _score(
    *,
    net: float,
    invoiced: float,
    uninvoiced: float,
    invoice_total: float,
    date_gap: int | None,
    order_no: str,
    raw_text: str,
    party_by_id: bool,
) -> tuple[int, bool, bool, list[str]]:
    score = 0
    reasons: list[str] = []

    amount_equal = abs(net - invoice_total) <= MONEY_EPS and net > 0
    if amount_equal:
        score += S_AMOUNT_EQUAL
        reasons.append(f"金额与单据净额一致（¥{net:,.2f}）")

    balance_enough = uninvoiced + MONEY_EPS >= invoice_total and uninvoiced > 0
    if balance_enough:
        score += S_BALANCE_ENOUGH
        reasons.append(f"未开票余量够（还有 ¥{uninvoiced:,.2f}）")

    if order_no and raw_text and order_no in raw_text:
        score += S_ORDER_NO_IN_TEXT
        reasons.append(f"发票原文里出现单号 {order_no}")

    if party_by_id:
        score += S_PARTY_ID_RESOLVED
        reasons.append("往来单位按档案 id 精确命中")

    if date_gap is not None:
        if date_gap <= 7:
            score += S_GAP_7
            reasons.append(f"开票日与单据日相差 {date_gap} 天")
        elif date_gap <= 30:
            score += S_GAP_30
            reasons.append(f"开票日与单据日相差 {date_gap} 天")
        elif date_gap <= 90:
            score += S_GAP_90
            reasons.append(f"开票日与单据日相差 {date_gap} 天")

    return score, amount_equal, balance_enough, reasons


def _collect_candidates(db: Session, invoice: Invoice, party_id: int, party_name: str) -> list[Candidate]:
    is_sales = invoice.direction == DIRECTION_OUTPUT
    model = SalesOrder if is_sales else PurchaseOrder
    doc_type = "outbound" if is_sales else "inbound"
    party_col = model.customer_id if is_sales else model.supplier_id
    invoice_total = round(float(invoice.total_amount or 0.0), 2)

    query = db.query(model).filter(
        party_col == party_id,
        model.doc_type == doc_type,
        model.status != "cancelled",
    )
    span = _window(invoice.issue_date)
    if span is not None:
        start, end = span
        query = query.filter(model.order_date >= start, model.order_date <= end)

    orders = query.order_by(model.order_date.desc(), model.id.desc()).limit(200).all()

    # 发票的 OK 号/单号线索：OCR 原文里出现单号是最硬的证据之一
    raw_text = invoice.raw_text or ""
    # customer_id / supplier_id 是否本来就是 id 命中（而不是靠名字猜出来的）。
    # 进项这一侧 2026-10-26 才有 supplier_id：在此之前 `party_by_id` 恒为 False，
    # 进项候选永远少这一档加分，金额相同的候选分不出高下。
    party_by_id = bool(invoice.customer_id) if is_sales else bool(invoice.supplier_id)

    candidates: list[Candidate] = []
    for order in orders:
        net = order_net_amount(order)
        invoiced = order_invoiced_amount(db, order.id)
        # 余量按**完结闸口径**（总额 − 已开票）算，见文件头「唯一口径」
        uninvoiced = round(max(0.0, float(order.total_amount or 0) - invoiced), 2)
        gap = _date_gap(order.order_date, invoice.issue_date)
        score, amount_equal, balance_enough, reasons = _score(
            net=net,
            invoiced=invoiced,
            uninvoiced=uninvoiced,
            invoice_total=invoice_total,
            date_gap=gap,
            order_no=order.order_no or "",
            raw_text=raw_text,
            party_by_id=party_by_id,
        )
        candidates.append(
            Candidate(
                order_id=order.id,
                order_no=order.order_no or "",
                order_date=order.order_date or "",
                party_id=party_id,
                party_name=party_name,
                net_amount=net,
                invoiced_amount=invoiced,
                uninvoiced_amount=uninvoiced,
                amount_equal=amount_equal,
                balance_enough=balance_enough,
                date_gap=gap,
                score=score,
                reasons=reasons,
            )
        )

    # 分高在前；同分时日期近的在前（稳定排序，便于人工核对）
    candidates.sort(key=lambda c: (-c.score, c.date_gap if c.date_gap is not None else 9999, -c.order_id))
    return candidates[:MAX_CANDIDATES]


# ---------------------------------------------------------------------------
# 对外：算一次匹配（不写库）
# ---------------------------------------------------------------------------
def match_invoice(db: Session, invoice: Invoice) -> MatchOutcome:
    """算一次匹配结果。**纯读**，不写库 —— 前端弹窗、批量预演都调它。"""
    base = MatchOutcome(
        status=STATUS_NONE,
        invoice_id=invoice.id,
        invoice_no=invoice.invoice_no or "",
        direction=invoice.direction or "",
        order_id=invoice.related_order_id,
    )

    if invoice.related_order_id:
        base.status = STATUS_SKIPPED
        base.reason = "这张发票已经挂过单据，不自动改（要换请人工指定）"
        return base

    if invoice.direction not in (DIRECTION_INPUT, DIRECTION_OUTPUT):
        base.status = STATUS_SKIPPED
        base.reason = "发票方向还没判定（待判定），先在发票上指定进项/销项再匹配"
        return base

    if (invoice.invoice_flag or "blue") == "red":
        base.status = STATUS_SKIPPED
        base.reason = "红字发票请手工指定冲红对象（要和它冲的那张蓝票挂在同一张单上）"
        return base

    invoice_total = round(float(invoice.total_amount or 0.0), 2)
    if invoice_total <= 0:
        base.status = STATUS_SKIPPED
        base.reason = "发票金额为 0，没有可匹配的依据"
        return base

    party_id, party_name, party_label = _resolve_party(db, invoice)
    if not party_id:
        base.status = STATUS_NONE
        base.reason = (
            f"发票上的{party_label}抬头没对上档案（"
            f"{'购买方' if invoice.direction == DIRECTION_OUTPUT else '销售方'}："
            f"{invoice.buyer_name if invoice.direction == DIRECTION_OUTPUT else invoice.seller_name or '空'}），"
            f"请先在{party_label}档案里补一条，或在发票上手工指定单据"
        )
        return base

    candidates = _collect_candidates(db, invoice, party_id, party_name)
    base.candidates = candidates

    if not candidates:
        base.status = STATUS_NONE
        base.reason = (
            f"「{party_name}」在开票日前后没有可挂的{'出库单' if invoice.direction == DIRECTION_OUTPUT else '入库单'}"
            f"（也可能单据日期为空、已作废，或都已完成开票）"
        )
        return base

    strong = [item for item in candidates if item.amount_equal and item.balance_enough]
    if len(strong) == 1:
        winner = strong[0]
        base.status = STATUS_MATCHED
        base.order_id = winner.order_id
        base.order_no = winner.order_no
        base.reason = f"唯一匹配：{winner.order_no}（金额一致且余量够）"
        # 把命中的那张排到最前，前端确认框第一行就是它
        base.candidates = [winner] + [item for item in candidates if item.order_id != winner.order_id]
        return base

    if len(strong) > 1:
        base.status = STATUS_AMBIGUOUS
        base.reason = f"有 {len(strong)} 张单据金额都对得上，必须人工指定"
        return base

    base.status = STATUS_AMBIGUOUS
    base.reason = "没有金额完全一致的单据，以下是按日期/单号线索排出的候选，请人工确认"
    return base


# ---------------------------------------------------------------------------
# 对外：自动落库 / 人工指定
# ---------------------------------------------------------------------------
def _sync_order_invoiced_flag(db: Session, order: SalesOrder | PurchaseOrder) -> None:
    """把单据的 `is_invoiced` 跟着发票合计算一遍（很多页面按它显示"已开票"角标）。"""
    if not hasattr(order, "is_invoiced"):
        return
    total = float(order.total_amount or 0)
    invoiced = order_invoiced_amount(db, order.id)
    order.is_invoiced = bool(total > 0 and invoiced + MONEY_EPS >= total)


def apply_match(db: Session, invoice: Invoice, order_id: int, *, source: str = "auto") -> MatchOutcome:
    """把发票挂到指定单据上（**唯一**写 `related_order_id` 的入口）。

    校验比"能不能挂"多两条，因为挂错会直接污染完结闸与对账单：
      · 单据必须存在、方向必须与发票一致（销项只能挂销售单）；
      · 单据的往来单位必须和发票的往来单位一致（跨对方的挂单 100% 是错的）。
    """
    is_sales = invoice.direction == DIRECTION_OUTPUT
    model = SalesOrder if is_sales else PurchaseOrder
    order = db.get(model, int(order_id))
    if order is None:
        raise ValueError("单据不存在")
    if (order.doc_type or "") != ("outbound" if is_sales else "inbound"):
        raise ValueError(
            f"只能挂到{'出库单' if is_sales else '入库单'}上，"
            f"这张是{'订单' if (order.doc_type or '') == 'order' else order.doc_type}"
        )

    party_id, party_name, party_label = _resolve_party(db, invoice)
    order_party = order.customer_id if is_sales else order.supplier_id
    if party_id and order_party and int(party_id) != int(order_party):
        raise ValueError(f"单据的{party_label}与发票不一致，不能挂在一起")

    invoice.related_order_id = int(order_id)
    _sync_order_invoiced_flag(db, order)
    db.commit()
    db.refresh(invoice)

    return MatchOutcome(
        status=STATUS_MATCHED,
        invoice_id=invoice.id,
        invoice_no=invoice.invoice_no or "",
        direction=invoice.direction or "",
        order_id=invoice.related_order_id,
        order_no=order.order_no or "",
        reason=("自动匹配成功" if source == "auto" else "已人工指定单据"),
        applied=True,
    )


def auto_attach(db: Session, invoice: Invoice) -> MatchOutcome:
    """新建/上传发票后调它：**只有唯一强证据时**才写库，否则原样返回候选。

    这是 `create_invoice` / `import_invoice` 的收尾动作，必须"调了也白调"：
    任何异常都不该让一张已经识别好的发票存不进去 —— 匹配是加分项，不是前置条件。
    """
    try:
        outcome = match_invoice(db, invoice)
        if outcome.status == STATUS_MATCHED and outcome.order_id:
            return apply_match(db, invoice, outcome.order_id, source="auto")
        return outcome
    except Exception as exc:  # noqa: BLE001 —— 匹配失败绝不拖垮开票主流程
        return MatchOutcome(
            status=STATUS_SKIPPED,
            invoice_id=invoice.id,
            invoice_no=invoice.invoice_no or "",
            direction=invoice.direction or "",
            order_id=invoice.related_order_id,
            reason=f"自动匹配跳过（{type(exc).__name__}: {exc}）",
        )
