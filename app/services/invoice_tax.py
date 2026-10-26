"""进项税额口径（2026-10-26）—— 「本月已认证进项税额」的唯一算法。

## 为什么单独一个模块

这个数字同时出现在两处：发票汇总接口（`/invoices/summary` 的 `input_tax`）
和执行驾驶舱 KPI（`/dashboard/executive`）。两处各写一遍 `if` 的话，迟早在
「按哪个时间取月」「算不算电子专票」「红字要不要减」上出现分歧 ——
这类分歧在财务眼里就是**两个界面报出两个数**，而且谁都说不清该信哪个。

## 口径（写死在这里，改口径只改这一处）

1. **只算进项**：`direction == 'input'`。销项是对方抵扣，我方没有认证/抵扣动作；
   历史数据里销项票被标过 `deducted` 的照旧留着，但不进任何进项口径。
2. **只算专票**：`is_special_invoice()`（含电子专票，见该函数的注释）。
3. **按认证时间取月**：`certified_at` 落在目标月份。财务问的是「这个月认证了多少」，
   这是申报动作口径；按开票日会把上月开出的票在本月再算一遍。
4. **红字票直接相加**：`tax_amount` 是负数，冲减自然发生，不做特殊处理 ——
   刻意"取绝对值"才是错的（那会把一张冲红票当成新增进项）。

⚠️ 关于时区：`certified_at` 带时区，落库是 UTC。按**服务器本地时区**折算成月，
   与「当前月份」用同一套折算，两边永远一致。跨月边界（本地时间 1 号 0 点前后）
   可能与本机时区设置有关 —— 这是"用哪个时区看月"的问题，不是算法分歧。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.invoice import (
    DEDUCTION_CERTIFIED,
    DEDUCTION_DEDUCTED,
    DEDUCTION_UNCERTIFIED,
    DIRECTION_INPUT,
    Invoice,
    is_special_invoice,
)


def month_key(value: object) -> str | None:
    """把 `datetime` / `date` / ISO 字符串统一成 `YYYY-MM`。取不出来就 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone()
        return value.strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    return text[:7] if len(text) >= 7 else None


def current_month_key() -> str:
    """当前月份（服务器本地时区），与 `month_key` 同一套折算。"""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m")


def counts_toward_input_tax(invoice: Invoice) -> bool:
    """这张票是否计入进项税额口径：进项 + 专票。"""
    return (invoice.direction or "") == DIRECTION_INPUT and is_special_invoice(invoice.invoice_type)


def input_tax_summary(invoices: list[Invoice], month: str | None = None) -> dict[str, object]:
    """按认证/抵扣状态分桶统计进项专票。

    `certified_this_month_*` 是 KPI「本月已认证进项税额」的来源：
    **按认证时间落月**，与之后有没有抵扣无关 —— 财务申报就是"本月认证的票本月抵"，
    哪怕因为留抵暂时没抵掉，认证这个动作也已经发生在本月。
    """
    target = month or current_month_key()
    stats = {
        "month": target,
        "certified_this_month_count": 0,
        "certified_this_month_tax": 0.0,
        "certified_this_month_amount": 0.0,
        "uncertified_count": 0,
        "uncertified_tax": 0.0,
        "certified_pending_count": 0,
        "certified_pending_tax": 0.0,
        "deducted_count": 0,
        "deducted_tax": 0.0,
    }

    for invoice in invoices:
        if not counts_toward_input_tax(invoice):
            continue
        tax = float(invoice.tax_amount or 0.0)
        amount = float(invoice.total_amount or 0.0)
        state = invoice.deduction_state

        if invoice.certified and month_key(invoice.certified_at) == target:
            stats["certified_this_month_count"] += 1
            stats["certified_this_month_tax"] += tax
            stats["certified_this_month_amount"] += amount

        if state == DEDUCTION_DEDUCTED:
            stats["deducted_count"] += 1
            stats["deducted_tax"] += tax
        elif state == DEDUCTION_CERTIFIED:
            stats["certified_pending_count"] += 1
            stats["certified_pending_tax"] += tax
        elif state == DEDUCTION_UNCERTIFIED:
            stats["uncertified_count"] += 1
            stats["uncertified_tax"] += tax

    for key in (
        "certified_this_month_tax",
        "certified_this_month_amount",
        "uncertified_tax",
        "certified_pending_tax",
        "deducted_tax",
    ):
        stats[key] = round(float(stats[key]), 2)
    return stats


def certified_tax_of_month(db: Session, month: str | None = None) -> float:
    """本月已认证进项税额（驾驶舱 KPI 用）。与 `/invoices/summary` 同一口径。"""
    rows = db.query(Invoice).filter(Invoice.direction == DIRECTION_INPUT, Invoice.certified.is_(True)).all()
    return float(input_tax_summary(rows, month)["certified_this_month_tax"])
