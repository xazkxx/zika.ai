"""单据状态的唯一权威定义与流转校验。

为什么单独一个模块
------------------
销售订单 / 现货开单 / 采购订单 / 采购入库单**共用同一张表**
（`sales_orders` / `purchase_orders`，靠 `doc_type` 区分），状态值集合相同，
但**流转规则不同**：订单要人工审核，现货单是即时单据（建单即生效）。
规则如果散在两个路由里各写一遍，必然漂移 —— 事实上改造前两边都是
`item.status = str(payload.get("status") or "submitted")`，**任何字符串都能写进去**，
"只有审核通过才能出库"这条业务规则在代码里根本不存在。

两类流程（2026-10-18 与用户确认）
--------------------------------
· 订单 `doc_type=order`       draft → pending → approved → completed
· 即时单 `doc_type=outbound`  draft → submitted → completed
  （`inbound` 与 `outbound` 同属即时单，不区分）

从任何非终态都可以转 `cancelled`。`completed` / `cancelled` 是终态，**不允许再改**。

历史值兼容
----------
改造前所有单据建出来都是 `submitted`（包括订单）。所以 `submitted` 在**订单**上
等价于 `pending`（待审核）；`normalize_status()` 负责这层转换，
**调用点不要各自写 if**，否则又会分叉。

注意：本模块只管"状态能不能改"，不管"改完要做什么"。转单副作用的守卫在
`erp_sales.py::sales_order_to_outbound` / `erp_purchase.py::purchase_order_to_inbound`。
"""

from __future__ import annotations

from fastapi import HTTPException

# 展示名：错误提示与日志用。前端的中文标签在 lib/appLib.js 的 ORDER_STATUS_LABELS，
# 两边对不上时以本文件的 key 为准（前端只负责显示，不负责判定）。
STATUS_LABELS: dict[str, str] = {
    "draft": "草稿",
    "pending": "待审核",
    "submitted": "已提交",  # 仅即时单使用；订单上的 submitted 会被归一成 pending
    "approved": "已审核",
    "completed": "已完成",
    "cancelled": "已取消",
}

# 合法状态码总表（写库只允许这几个值）
ALL_STATUSES: tuple[str, ...] = ("draft", "pending", "submitted", "approved", "completed", "cancelled")

# 订单可用的状态码（不含 submitted：新订单直接落 pending）
ORDER_STATUSES: tuple[str, ...] = ("draft", "pending", "approved", "completed", "cancelled")

# 即时单（现货开单 / 入库单）可用状态码（不含 pending / approved：它们没有审核环节）
DIRECT_STATUSES: tuple[str, ...] = ("draft", "submitted", "completed", "cancelled")

# 流转表：source → 允许的 target 集合
ORDER_FLOW: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending", "cancelled"}),
    # 制单后可以退回草稿（录错了重填），也可以直接审核或作废
    "pending": frozenset({"approved", "draft", "cancelled"}),
    # 审核后允许撤回（撤销审核回到待审核），一旦完成就锁死
    "approved": frozenset({"completed", "pending", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}

DIRECT_FLOW: dict[str, frozenset[str]] = {
    "draft": frozenset({"submitted", "completed", "cancelled"}),
    "submitted": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


def flow_name(doc_type: str | None) -> str:
    """把 doc_type 归到两类流程之一。未知 doc_type 按即时单处理（更宽松，不阻断老数据）。"""
    return "order" if str(doc_type or "").strip() == "order" else "direct"


def allowed_statuses(doc_type: str | None) -> tuple[str, ...]:
    return ORDER_STATUSES if flow_name(doc_type) == "order" else DIRECT_STATUSES


def status_label(status: str | None) -> str:
    code = str(status or "").strip()
    return STATUS_LABELS.get(code, code or "未知")


def normalize_status(doc_type: str | None, status: str | None) -> str:
    """校验并归一化一个状态码。

    · 未知码 → 400（把合法值列在 detail 里，前端可直接展示）
    · 订单上的 `submitted` → `pending`（历史值兼容）
    · 即时单上的 `pending` / `approved` → 400（这类单据没有审核环节）
    """
    code = str(status or "").strip().lower()
    if not code:
        raise HTTPException(
            status_code=400,
            detail="status 必填，可选：" + " / ".join(allowed_statuses(doc_type)),
        )
    if code not in ALL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 只能是 {' / '.join(allowed_statuses(doc_type))}（收到：{code}）",
        )
    if flow_name(doc_type) == "order":
        if code == "submitted":
            return "pending"
        if code not in ORDER_STATUSES:  # pragma: no cover - 由 ALL_STATUSES 兜住，留作防御
            raise HTTPException(status_code=400, detail=f"订单不支持状态 {code}")
        return code
    if code not in DIRECT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"现货单/出入库单没有「{STATUS_LABELS.get(code, code)}」这个状态，可选："
            + " / ".join(DIRECT_STATUSES),
        )
    return code


def assert_transition(doc_type: str | None, current: str | None, target: str | None, doc_no: str = "") -> str:
    """校验一次状态变更，返回**归一化后的目标状态**。

    同状态视为幂等空操作（前端双击、重复提交都不会报错）。
    非法流转抛 409，并在 detail 里写清"当前是什么、能改成什么"——
    这类错误用户一定会看到，英文错误码帮不上忙。
    """
    normalized_target = normalize_status(doc_type, target)
    normalized_current = normalize_status(doc_type, current) if str(current or "").strip() else "draft"

    if normalized_current == normalized_target:
        return normalized_target

    flow = ORDER_FLOW if flow_name(doc_type) == "order" else DIRECT_FLOW
    allowed = flow.get(normalized_current, frozenset())
    if normalized_target not in allowed:
        prefix = f"单据 {doc_no} " if doc_no else ""
        if not allowed:
            raise HTTPException(
                status_code=409,
                detail=f"{prefix}已处于终态「{status_label(normalized_current)}」，不能再改成"
                f"「{status_label(normalized_target)}」",
            )
        raise HTTPException(
            status_code=409,
            detail=f"{prefix}当前是「{status_label(normalized_current)}」，不能直接改成"
            f"「{status_label(normalized_target)}」。允许的下一步："
            + " / ".join(status_label(item) for item in sorted(allowed)),
        )
    return normalized_target


def is_approved(doc_type: str | None, status: str | None) -> bool:
    """转单前的统一判据：只有 `approved` 才算"审核通过"。

    历史 `submitted` 在订单上归一为 `pending` ⇒ **不算审核通过**，
    这是刻意的：老订单必须先点一次「审核」才能转单。
    """
    try:
        return normalize_status(doc_type, status) == "approved"
    except HTTPException:
        return False
