"""库存预警看板接口 —— `GET /api/v1/erp/stock-alert`

前端：`src/components/stock-alert/`（纯 JS + 手写 SVG，见该目录 INTEGRATION.md）

## 一、为什么用 `get_db()` 而不是直连 `erp.db`

本项目是**多账套**的：`.env` 里的 `DATABASE_URL` 指向的是数据库实例，
真正的库/schema 由 token 里的账套决定，`get_db(request)` 负责把会话接到对应的
schema 上（见 `app/db/session.py` 的说明）。直连 `erp.db` 或用 `SessionLocal`
都会固定读**第一个账套** —— 在多个账套下就是串账，而且 `erp.db` 是升级前的
旧文件，读出来的数是过期的。所以这里跟所有业务路由一样只依赖 `get_db()`。

## 二、口径（写在这里，免得以后各处算法漂移）

1. **现存量不落库**，由 `inventory_transactions` 实时汇总，与
   `erp_common._net_stock_map` 完全同一口径（同一个 `_stock_delta` 函数）。
2. **日均出库** = 窗口内该「仓库 × 商品」的出库量 ÷ 窗口天数。
   窗口内一条出库都没有 → 落到 `DEFAULT_DAILY_OUT`（默认 1 件/天）。
3. **预计可用天数** = 当前库存 ÷ 日均出库。**日均出库 <= 0 时返回 None**，
   绝不抛除零异常；口径是「算不出来 = 不动销 = 不构成缺货风险 = 正常」。
4. **紧急度**：< 3 天 紧急 / 3–7 天 预警 / > 7 天 正常。
   阈值常量与前端 `alertRules.js` 的 `ALERT_THRESHOLDS` 一一对应，改要两边一起改。
   钉死的边界：正好 3 天 → 预警；正好 7 天 → 预警。
5. **安全库存** 取商品档案的**库存下限** `products.stock_lower`。
   没设下限的商品不参与「击穿安全库存」这条判定（与现存量看板的既有口径一致），
   只在负库存或可用天数告急时才进明细表。
6. **纯只读**：本模块不写任何表。
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _default_warehouse, _stock_delta
from app.db.session import get_db
from app.models.inventory import InventoryTransaction
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.warehouse import Warehouse

router = APIRouter(prefix="", tags=["erp"])


# ============================================================================
# 常量：要调业务口径，只改这一段
# ============================================================================

# 出入库类型判定 —— 与 erp_common / reports 保持同一口径，不要另起一套
INBOUND_TYPES = {"inbound", "in", "purchase", "采购入库", "盘盈", "报溢", "调拨入"}
OUTBOUND_TYPES = {"outbound", "out", "sales", "销售出库", "盘亏", "报损", "调拨出"}

# 单据「已结束」状态：不在这个集合里的待办单据才算「待入库 / 待出库」。
# 采购单/销售单的生命周期：draft -> submitted -> completed（转单后）。
# 宁可把未知状态算成"待处理"（多提示一次），也不要漏掉真正没走完的单。
CLOSED_ORDER_STATUS = {"completed", "cancelled", "canceled", "closed", "void"}

# 🔧 紧急度阈值（天）—— 必须与前端 alertRules.js 的 ALERT_THRESHOLDS 一致
ALERT_URGENT_BELOW = 3.0
ALERT_WARN_BELOW = 7.0

# 🔧 窗口内没有任何出库记录时给的默认日均出库（件/天）
DEFAULT_DAILY_OUT = 1.0

# 图表 / 迷你趋势线参数
WINDOW_DAYS = {"7d": 7, "30d": 30}
DEFAULT_WINDOW = 30
SPARK_DAYS = 7

# 同比取「去年同一天」，按平年 365 天回推
YOY_OFFSET_DAYS = 365

KPI_COLORS = {
    "totalStock": "#3370ff",
    "inbound": "#f59e0b",
    "outbound": "#7b61ff",
    "shortage": "#e5484d",
}

SERIES_COLORS = {"inbound": "#3370ff", "outbound": "#17a34a", "growth": "#f59e0b"}


# ============================================================================
# Pydantic 模型（字段名必须与前端契约一致，不要改名）
# ============================================================================


class KpiItem(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    delta: float
    trend: str  # up | down | flat
    note: str
    polarity: str  # normal | inverse
    color: str
    spark: list[float]


class ChartSeries(BaseModel):
    name: str
    type: str  # area | line | dashed
    axis: str  # left | right
    color: str
    data: list[float]


class ChartConfig(BaseModel):
    leftTitle: str
    leftUnit: str
    rightTitle: str
    rightUnit: str
    labels: list[str]
    series: list[ChartSeries]


class AlertItem(BaseModel):
    """明细行。

    前 8 个字段是前端真正要的原始字段（缺口 / 可用天数 / 紧急度由前端算）。
    后 3 个是后端顺手也算的一份 —— 前端拿到后会自己重算并覆盖，不影响渲染；
    留着是为了接口自测、以及别的调用方（移动端 / 导出）拿来就能直接用。
    """

    id: str
    sku: str
    name: str
    warehouse: str
    stock: float
    safetyStock: float
    dailyOut: float
    suggest: float

    gap: float
    daysLeft: float | None
    status: str  # urgent | warn | normal


class StockAlertResponse(BaseModel):
    kpis: list[KpiItem]
    chart: ChartConfig
    alerts: list[AlertItem]
    updatedAt: str


# ============================================================================
# 纯函数：口径都在这里，方便单独测
# ============================================================================


def _days_of_supply(stock: float, daily_out: float) -> float | None:
    """预计可用天数 = 当前库存 / 日均出库。

    两种"算不出来"要分开处理，混成一个会把最该报警的行判成正常：

    * **负库存 → 0 天**。本系统是允许负库存开单的（先卖后进货），
      负库存意味着货已经欠出去了，是最紧急的一档，绝不能归进「正常」。
    * **日均出库 <= 0 → None**。真的算不出来（不动销），不构成缺货风险。

    不管哪条分支都**不抛除零异常** —— 这是这里唯一能击穿接口的风险点。
    """
    if stock is not None and float(stock) < 0:
        return 0.0
    if daily_out is None or daily_out <= 0:
        return None
    return float(stock) / float(daily_out)


def _status_from_days(days_left: float | None) -> str:
    """按可用天数分档。< 3 紧急；3 ~ 7 预警；> 7 正常；算不出天数归「正常」。"""
    if days_left is None:
        return "normal"
    if days_left < ALERT_URGENT_BELOW:
        return "urgent"
    if days_left <= ALERT_WARN_BELOW:
        return "warn"
    return "normal"


def _rate(current: float, previous: float) -> tuple[float, str]:
    """KPI 的变化率（%）。

    分母 <= 0 时**不编数字**，返回 0 / flat —— 从 0 涨到 100 算不出百分比，
    硬算成 +∞% 只会让人以为系统坏了。
    """
    if previous is None or previous <= 0:
        return 0.0, "flat"
    value = (float(current) - float(previous)) / float(previous) * 100
    if abs(value) < 0.05:
        return 0.0, "flat"
    return round(value, 1), ("up" if value > 0 else "down")


def _stock_lower(product: object) -> float | None:
    """读商品档案里的库存下限。

    `stock_lower` 是 NULL 或 0 都算**没设**（返回 None）——
    0 在下限语义里等于"不设限"，拿它去比大小会把「现存量 0」判成「低于下限」，
    于是一堆从没进过货的商品全被打成缺货。
    """
    raw = getattr(product, "stock_lower", None)
    if raw is None:
        return None
    value = float(raw)
    return value if value > 0 else None


def _is_shortage(stock: float, lower: float | None) -> bool:
    """缺货判定（用户 2026-10-15 确认口径）—— **全项目唯一的一份定义**。

    * 设了库存下限（`lower > 0`）→ 现存量**严格低于**下限才算缺货。
      正好等于下限**不算**（否则会冒出「缺口 0 / 建议补货 0」的空行）。
    * 没设下限（`lower is None`）→ 退回「现存量 <= 0」，卖光了才算缺货。

    KPI 的「缺货商品」数、它的 7 天迷你趋势、明细表的入选条件，三处都调这一个函数，
    免得各写各的之后三个数字互相对不上。
    """
    if lower is not None:
        return float(stock) < float(lower)
    return float(stock) <= 0.0


def _needs_attention(
    *,
    stock: int,
    safety: float,
    has_lower: bool,
    has_history: bool,
    status: str,
) -> bool:
    """哪一行要进明细表。

    命中任意一条即进：

    1. **缺货** —— 见 `_is_shortage`：设了下限就比下限（严格低于），没设就 `<= 0`。
       这一条同时覆盖了「已欠货（负库存）」「击穿下限」「卖光了」三种情况。
    2. **窗口内真有出库记录**，且可用天数已落到紧急 / 预警档。

    第 2 条特意要求 `has_history`：没有动销历史的商品，日均出库只能用默认值兜底，
    拿一个编出来的分母去判定"周转告急"，会把一堆躺着的呆滞库存刷进表里。
    真正库存告急的，第 1 条已经兜住了。

    ⚠️ 这里不再单独判 `stock < 0`：`_is_shortage` 的两条分支都能覆盖它
    （设了下限时必然低于下限；没设下限时 `<= 0` 包含负数），重复判断只会
    让以后改口径时漏改一处。
    """
    if _is_shortage(stock, safety if (has_lower and safety > 0) else None):
        return True
    if has_history and status in ("urgent", "warn"):
        return True
    return False


# ============================================================================
# 聚合：一次遍历把要用的量全部算出来，不做 N 次全表扫
# ============================================================================


def _summarize(db: Session, window_days: int, today: date) -> dict[str, object]:
    products = {p.id: p for p in db.query(Product).all()}
    warehouses = {w.id: w for w in db.query(Warehouse).all()}

    # 设了库存下限的商品（pid -> 下限）。这批商品**零流水也要参与缺货判定**：
    # 管理者既然给了它一个下限，就说明它是被盯着的商品，现存量 0 显然该报。
    # 没设下限的商品则不进这个集合 —— 它们只在"有库存流水"时才参与判定。
    managed: dict[int, float] = {}
    for product in products.values():
        lower = _stock_lower(product)
        if lower is not None:
            managed[product.id] = lower

    net: dict[tuple[int, int], int] = {}  # (商品, 仓库) -> 现存量
    delta_by_day: dict[str, int] = {}  # 日 -> 当日全库净变动
    per_product_day: dict[int, dict[str, int]] = {}  # 商品 -> {日: 净变动}
    in_by_day: dict[str, float] = {}  # 日 -> 入库量
    out_by_day: dict[str, float] = {}  # 日 -> 出库量
    window_out: dict[tuple[int, int], float] = {}  # 窗口内出库累计

    for row in db.query(InventoryTransaction).all():
        kind = (row.transaction_type or "").strip().lower()
        qty = int(row.quantity or 0)
        delta = _stock_delta(row.transaction_type, qty)

        key = (row.product_id, row.warehouse_id)
        net[key] = net.get(key, 0) + delta

        created = row.created_at
        if created is None:
            continue
        day_key = created.date().isoformat()
        days_ago = (today - created.date()).days
        if days_ago < 0:
            # 服务器时间与业务日期错位时，按"今天"算，不让它掉出窗口
            days_ago = 0

        delta_by_day[day_key] = delta_by_day.get(day_key, 0) + delta
        bucket = per_product_day.setdefault(row.product_id, {})
        bucket[day_key] = bucket.get(day_key, 0) + delta

        amount = float(abs(qty))
        if kind in INBOUND_TYPES:
            in_by_day[day_key] = in_by_day.get(day_key, 0.0) + amount
        elif kind in OUTBOUND_TYPES:
            out_by_day[day_key] = out_by_day.get(day_key, 0.0) + amount
            if days_ago < window_days:
                window_out[key] = window_out.get(key, 0.0) + amount

    # —— 任意一天的收盘总库存：对「当日净变动」做前缀和 ——
    day_keys = sorted(delta_by_day)
    prefix: list[int] = []
    running = 0
    for day_key in day_keys:
        running += delta_by_day[day_key]
        prefix.append(running)

    def stock_as_of(target: date) -> int:
        idx = bisect_right(day_keys, target.isoformat()) - 1
        return prefix[idx] if idx >= 0 else 0

    # —— 任意一天的缺货商品种数 ——
    # 把 (日, 商品, 变动) 排好序，用单调推进的游标累加，避免"每个日期都从头算一遍"。
    # ⚠️ 因此调用方必须**按日期升序**查询，别跳着传。
    flow = sorted(
        (day_key, pid, delta)
        for pid, daymap in per_product_day.items()
        for day_key, delta in daymap.items()
    )
    cursor = 0
    totals: dict[int, int] = {}

    def shortage_as_of(target: date) -> int:
        nonlocal cursor
        limit = target.isoformat()
        while cursor < len(flow) and flow[cursor][0] <= limit:
            _, pid, delta = flow[cursor]
            totals[pid] = totals.get(pid, 0) + delta
            cursor += 1
        hit = {
            pid
            for pid, value in totals.items()
            if _is_shortage(value, _stock_lower(products.get(pid)))
        }
        # 设了下限、却从没有任何流水的商品：现存量天然是 0，任一历史时点都算缺货。
        # 它们不在 totals 里（没流水），主集合扫不到，必须单独补 ——
        # 否则「设了下限但零库存」这种最该报警的情况反而漏掉。
        hit.update(
            pid
            for pid, lower in managed.items()
            if pid not in totals and _is_shortage(0.0, lower)
        )
        return len(hit)

    # —— 迷你趋势线要的 7 个日子（升序）——
    spark_days = [today - timedelta(days=SPARK_DAYS - 1 - i) for i in range(SPARK_DAYS)]

    shortage_prev = shortage_as_of(today - timedelta(days=SPARK_DAYS))
    shortage_spark = [float(shortage_as_of(day)) for day in spark_days]
    shortage_now = shortage_spark[-1] if shortage_spark else 0.0

    # —— 待入库 / 待出库：还没转成正式出入库单的订单一律算待处理 ——
    pending_in = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.doc_type == "order",
            PurchaseOrder.status.notin_(tuple(CLOSED_ORDER_STATUS)),
        )
        .all()
    )
    pending_out = (
        db.query(SalesOrder)
        .filter(
            SalesOrder.doc_type == "order",
            SalesOrder.status.notin_(tuple(CLOSED_ORDER_STATUS)),
        )
        .all()
    )

    def pending_spark(orders: list) -> list[float]:
        """按建单日累加：第 i 点 = 「建单日 <= 该日、至今仍是待处理」的单数。

        是近似（单据状态取的是当前值，中途转单的历史无法还原），
        但末点恒等于当前待处理总数，趋势方向是对的。
        """
        out: list[float] = []
        for day in spark_days:
            limit = day.isoformat()
            count = 0
            for order in orders:
                created = order.created_at
                if created is None or created.date().isoformat() <= limit:
                    count += 1
            out.append(float(count))
        return out

    total_stock = float(sum(net.values()))
    return {
        "products": products,
        "warehouses": warehouses,
        "net": net,
        # 设了库存下限的商品；零流水的那批靠它才进得了明细表
        "managed": managed,
        # 零流水商品挂哪个仓库：档案里没记过仓库，统一挂默认仓库
        "default_warehouse": _default_warehouse(db),
        "window_out": window_out,
        "in_by_day": in_by_day,
        "out_by_day": out_by_day,
        "stock_as_of": stock_as_of,
        "shortage_spark": shortage_spark,
        "shortage_now": shortage_now,
        "shortage_prev": float(shortage_prev),
        "pending_in": pending_in,
        "pending_out": pending_out,
        "pending_in_spark": pending_spark(pending_in),
        "pending_out_spark": pending_spark(pending_out),
        "total_stock": total_stock,
    }


# ============================================================================
# 组装三个区块
# ============================================================================


def _build_kpis(data: dict[str, object], today: date) -> list[KpiItem]:
    stock_as_of = data["stock_as_of"]
    total_stock = float(data["total_stock"])  # type: ignore[arg-type]
    prev_stock = float(stock_as_of(today - timedelta(days=SPARK_DAYS)))  # type: ignore[operator]

    in_spark = data["pending_in_spark"]  # type: ignore[assignment]
    out_spark = data["pending_out_spark"]  # type: ignore[assignment]
    shortage_spark = data["shortage_spark"]  # type: ignore[assignment]
    pending_in_count = float(len(data["pending_in"]))  # type: ignore[arg-type]
    pending_out_count = float(len(data["pending_out"]))  # type: ignore[arg-type]

    stock_spark = [
        float(stock_as_of(today - timedelta(days=SPARK_DAYS - 1 - i)))  # type: ignore[operator]
        for i in range(SPARK_DAYS)
    ]

    def card(
        key: str,
        label: str,
        value: float,
        unit: str,
        note: str,
        polarity: str,
        prev: float,
        spark: list[float],
    ) -> KpiItem:
        delta, trend = _rate(value, prev)
        return KpiItem(
            key=key,
            label=label,
            value=round(value, 2),
            unit=unit,
            delta=delta,
            trend=trend,
            note=note,
            polarity=polarity,
            color=KPI_COLORS[key],
            spark=spark,
        )

    return [
        card(
            "totalStock",
            "总库存",
            total_stock,
            "件",
            "较上周",
            "normal",
            prev_stock,
            stock_spark,
        ),
        card(
            "inbound",
            "待入库",
            pending_in_count,
            "单",
            "较昨日",
            "inverse",
            in_spark[-2] if len(in_spark) >= 2 else 0.0,
            in_spark,
        ),
        card(
            "outbound",
            "待出库",
            pending_out_count,
            "单",
            "较昨日",
            "inverse",
            out_spark[-2] if len(out_spark) >= 2 else 0.0,
            out_spark,
        ),
        card(
            "shortage",
            "缺货商品",
            float(data["shortage_now"]),  # type: ignore[arg-type]
            "种",
            "较上周",
            "inverse",
            float(data["shortage_prev"]),  # type: ignore[arg-type]
            shortage_spark,
        ),
    ]


def _build_alerts(data: dict[str, object], window_days: int) -> list[AlertItem]:
    products = data["products"]  # type: ignore[assignment]
    warehouses = data["warehouses"]  # type: ignore[assignment]
    net = data["net"]  # type: ignore[assignment]
    window_out = data["window_out"]  # type: ignore[assignment]
    managed: dict[int, float] = data.get("managed") or {}  # type: ignore[assignment]
    default_wh = data.get("default_warehouse")
    span = float(window_days)

    rows: list[AlertItem] = []
    for (pid, wid), stock in net.items():
        product = products.get(pid)
        warehouse = warehouses.get(wid)

        out_qty = float(window_out.get((pid, wid), 0.0))
        has_history = out_qty > 0
        daily_out = out_qty / span
        if daily_out <= 0:
            # 🔧 没有出库历史时的默认值。改成 0 会让这类商品全部落到「正常」。
            daily_out = DEFAULT_DAILY_OUT

        raw_lower = getattr(product, "stock_lower", None)
        has_lower = raw_lower is not None
        safety = float(raw_lower or 0)
        days_left = _days_of_supply(stock, daily_out)
        status = _status_from_days(days_left)

        if not _needs_attention(
            stock=stock,
            safety=safety,
            has_lower=has_lower,
            has_history=has_history,
            status=status,
        ):
            continue

        # 建议补货：补到「安全库存」与「够撑到预警线」里更高的那个目标
        target = max(safety, daily_out * ALERT_WARN_BELOW)
        suggest = max(target - float(stock), 0.0)

        rows.append(
            AlertItem(
                id=f"P{pid}W{wid}",
                sku=str(getattr(product, "sku", None) or ""),
                name=str(getattr(product, "name", None) or f"商品-{pid}"),
                warehouse=str(getattr(warehouse, "name", None) or f"仓库-{wid}"),
                stock=float(stock),
                safetyStock=round(safety, 2),
                dailyOut=round(daily_out, 2),
                suggest=round(suggest, 2),
                gap=round(safety - float(stock), 2),
                daysLeft=round(days_left, 2) if days_left is not None else None,
                status=status,
            )
        )

    # —— 设了库存下限、却从没有任何库存流水的商品 ——
    # 它们的现存量天然是 0，压根不在 `net` 里（没有 (商品,仓库) 组合），
    # 上面那个循环扫不到；但恰恰最该报：管理者已经明确给它设了下限。
    # 没设下限的商品**不在这里补** —— 否则 261 个商品里那 241 个从没进过货的
    # 呆滞档案会瞬间把明细表刷爆（实测会从 1 种跳到 242 种）。
    touched = {pid for pid, _wid in net}
    for pid, lower in managed.items():
        if pid in touched:
            continue
        product = products.get(pid)
        stock = 0.0
        daily_out = DEFAULT_DAILY_OUT
        days_left = _days_of_supply(stock, daily_out)
        status = _status_from_days(days_left)
        if not _needs_attention(
            stock=stock, safety=lower, has_lower=True, has_history=False, status=status
        ):
            continue
        target = max(lower, daily_out * ALERT_WARN_BELOW)
        rows.append(
            AlertItem(
                # 挂 W0：真实仓库 id 不可能是 0，天然不会和上面那批撞 id
                id=f"P{pid}W0",
                sku=str(getattr(product, "sku", None) or ""),
                name=str(getattr(product, "name", None) or f"商品-{pid}"),
                warehouse=str(getattr(default_wh, "name", None) or "—"),
                stock=stock,
                safetyStock=round(lower, 2),
                dailyOut=round(daily_out, 2),
                suggest=round(max(target - stock, 0.0), 2),
                gap=round(lower - stock, 2),
                daysLeft=round(days_left, 2) if days_left is not None else None,
                status=status,
            )
        )

    # 排序即补货优先级：可用天数少的在前（算不出天数的排最后），同档再看缺口大小。
    # 前端会按同一口径重排一遍，这里先排好是为了接口本身也自洽。
    rows.sort(key=lambda item: (item.daysLeft is None, item.daysLeft or 0.0, -item.gap))
    return rows


def _build_chart(
    data: dict[str, object], window_days: int, today: date
) -> ChartConfig:
    in_by_day = data["in_by_day"]  # type: ignore[assignment]
    out_by_day = data["out_by_day"]  # type: ignore[assignment]

    dates = [today - timedelta(days=window_days - 1 - i) for i in range(window_days)]
    labels = [day.strftime("%m-%d") for day in dates]

    def series_of(source: dict, day: date) -> float:
        return round(float(source.get(day.isoformat(), 0.0)), 2)

    inbound = [series_of(in_by_day, day) for day in dates]
    outbound = [series_of(out_by_day, day) for day in dates]

    # 同比优先：去年同一天有出货才算得出来。
    same_last_year = [day - timedelta(days=YOY_OFFSET_DAYS) for day in dates]
    has_yoy = any(series_of(out_by_day, day) > 0 for day in same_last_year)

    if has_yoy:
        growth = []
        for current, base in zip(outbound, same_last_year):
            base_qty = series_of(out_by_day, base)
            growth.append(
                round((current - base_qty) / base_qty * 100, 1) if base_qty > 0 else 0.0
            )
        right_title = "出库同比"
    else:
        # 新账套里根本没有去年同期的数据。此时若照常画同比，得到的是一条恒为 0 的
        # 直线，等于告诉用户"零增长"——那是假的。退回「7 日滚动环比」：
        # 口径真实、曲线平滑，标题也一起改，不让界面说谎。
        growth = []
        for index in range(len(dates)):
            current = sum(
                series_of(out_by_day, dates[index] - timedelta(days=k)) for k in range(0, 7)
            )
            previous = sum(
                series_of(out_by_day, dates[index] - timedelta(days=k)) for k in range(7, 14)
            )
            growth.append(round((current - previous) / previous * 100, 1) if previous > 0 else 0.0)
        right_title = "出库环比"

    return ChartConfig(
        leftTitle="出入库量",
        leftUnit="件",
        rightTitle=right_title,
        rightUnit="%",
        labels=labels,
        series=[
            ChartSeries(
                name="入库量",
                type="area",
                axis="left",
                color=SERIES_COLORS["inbound"],
                data=inbound,
            ),
            ChartSeries(
                name="出库量",
                type="line",
                axis="left",
                color=SERIES_COLORS["outbound"],
                data=outbound,
            ),
            ChartSeries(
                name="同比增速" if has_yoy else "环比增速",
                type="dashed",
                axis="right",
                color=SERIES_COLORS["growth"],
                data=growth,
            ),
        ],
    )


# ============================================================================
# 路由
# ============================================================================


@router.get("/erp/stock-alert", response_model=StockAlertResponse)
def stock_alert(
    range_value: str = Query("30d", alias="range", description="30d | 7d"),
    db: Session = Depends(get_db),
) -> StockAlertResponse:
    """库存预警看板：4 张 KPI + 出入库趋势 + 缺货明细，一次返回。"""
    window_days = WINDOW_DAYS.get(str(range_value).strip().lower(), DEFAULT_WINDOW)
    today = date.today()
    data = _summarize(db, window_days, today)

    return StockAlertResponse(
        kpis=_build_kpis(data, today),
        chart=_build_chart(data, window_days, today),
        alerts=_build_alerts(data, window_days),
        updatedAt=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
