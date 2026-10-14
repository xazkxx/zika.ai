"""报表中心 —— 16 张聚合报表（第 4 批）。

与前面三批的根本区别：**报表不建表、不写库**。它站在已有单据之上做只读聚合，
所以这一批的风险不在"写坏数据"，而在"算错数"。

## 一、为什么独立成模块，而不是塞进 erp.py

erp.py 已经 9300+ 行（它是"所有业务单据"的家）。报表是**另一种东西**：
没有单据生命周期、没有库存/财务联动、没有打印与 Excel 注册表，只有"读 + 算"。
放进 erp.py 只会让那个文件更难维护，而且报表天然需要自己的引擎（分桶、维表、
交叉表），与单据代码没有共享点。所以单开一个 router，挂在 `/reports` 下。

## 二、一个引擎，四种形态

16 张报表听起来很多，拆开看只有四种"形状"：

| 形态 | 报表 | 说明 |
|---|---|---|
| `crosstab` 交叉表 | 商品/客户分类/商品分类 的 日/月/季/年 报（12 张）+ 销售员报表 | 行 = 维度实体，列 = 期间桶 |
| `detail` 明细表 | 商品销售明细表 | 原始单据行，不聚合 |
| `flow` 收发存 | 商品出入统计 | 期初 + 入库 − 出库 = 期末 |
| `overview` 大盘 | 老板报表 | 收入/成本/毛利/应收/应付/库存 + Top 榜 |

前 12 张只差两个参数（`dimension` × `period`），所以**共用一个聚合引擎**：
先在库端按日期取一次事实数据，再在 Python 端按"维度 × 期间桶"分桶。
一次查询喂 12 张报表，不做 12 次全表扫。

## 三、口径（写在这里，免得以后各处算法漂移）

1. **只算真实出库的开单**：`sales_orders.doc_type == "outbound"`。
   `doc_type == "order"` 是"只订货没发货"，不该进销售报表（这与库存/财务口径一致）。
2. **销售退货冲减**：退货行按**负数**并入销售事实，得到的是**净销售**。
   看单张报表时不会突然发现"卖了 100 又退了 30 却仍显示 100"。
3. **毛利 = 净销售额 − 成本**，成本按商品档案的**当前采购价**估算
   （项目没有批次成本核算，这是刻意保留的简化，报表里会注明）。
4. **日期一律取单据自身的业务日期**（`order_date` / `return_date`），
   取不到才退到 `created_at`——录入时间和发生时间是两回事。
5. **纯只读**：本模块不写任何表。测试用"跑报表前后库存/财务流水条数不变"锁死。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.sales_return import SalesReturn, SalesReturnItem
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse

router = APIRouter(prefix="/reports", tags=["reports"])

# —— 出入库类型判定（与 erp.py 的 INBOUND_TYPES / OUTBOUND_TYPES 保持同一口径）——
INBOUND_TYPES = {"inbound", "in", "purchase", "采购入库", "盘盈", "报溢", "调拨入"}
OUTBOUND_TYPES = {"outbound", "out", "sales", "销售出库", "盘亏", "报损", "调拨出"}

PERIODS = {
    "day": "日报",
    "month": "月报",
    "quarter": "季报",
    "year": "年报",
}

DIMENSIONS = {
    "product": "商品",
    "customer": "客户",
    "category": "商品分类",
    "salesman": "销售员",
}

# 交叉表的最大列数：超过就拒绝，而不是悄悄截断（截断的报表比报错更危险）
MAX_BUCKETS = 62


# ============================================================
# 报表目录：16 张报表的唯一事实来源
# 前端菜单、接口分发、导出列名全部读这里，不另存一份。
# ============================================================
REPORT_CATALOG: list[dict[str, object]] = [
    # —— 商品销售 日/月/季/年（4 张）——
    {"key": "product-sales-day", "name": "商品销售日报", "group": "商品销售", "shape": "crosstab", "dimension": "product", "period": "day", "desc": "按天统计各商品的销量与销售额"},
    {"key": "product-sales-month", "name": "商品销售月报", "group": "商品销售", "shape": "crosstab", "dimension": "product", "period": "month", "desc": "按月统计各商品的销量与销售额"},
    {"key": "product-sales-quarter", "name": "商品销售季报", "group": "商品销售", "shape": "crosstab", "dimension": "product", "period": "quarter", "desc": "按季统计各商品的销量与销售额"},
    {"key": "product-sales-year", "name": "商品销售年报", "group": "商品销售", "shape": "crosstab", "dimension": "product", "period": "year", "desc": "按年统计各商品的销量与销售额"},
    # —— 客户分类 日/月/季/年（4 张）——
    {"key": "customer-sales-day", "name": "客户分类日报", "group": "客户销售", "shape": "crosstab", "dimension": "customer", "period": "day", "desc": "按天统计各客户的销量与销售额"},
    {"key": "customer-sales-month", "name": "客户分类月报", "group": "客户销售", "shape": "crosstab", "dimension": "customer", "period": "month", "desc": "按月统计各客户的销量与销售额"},
    {"key": "customer-sales-quarter", "name": "客户分类季报", "group": "客户销售", "shape": "crosstab", "dimension": "customer", "period": "quarter", "desc": "按季统计各客户的销量与销售额"},
    {"key": "customer-sales-year", "name": "客户分类年报", "group": "客户销售", "shape": "crosstab", "dimension": "customer", "period": "year", "desc": "按年统计各客户的销量与销售额"},
    # —— 商品分类 日/月/季/年（4 张）——
    {"key": "category-sales-day", "name": "商品分类日报", "group": "分类销售", "shape": "crosstab", "dimension": "category", "period": "day", "desc": "按天统计各商品分类的销量与销售额"},
    {"key": "category-sales-month", "name": "商品分类月报", "group": "分类销售", "shape": "crosstab", "dimension": "category", "period": "month", "desc": "按月统计各商品分类的销量与销售额"},
    {"key": "category-sales-quarter", "name": "商品分类季报", "group": "分类销售", "shape": "crosstab", "dimension": "category", "period": "quarter", "desc": "按季统计各商品分类的销量与销售额"},
    {"key": "category-sales-year", "name": "商品分类年报", "group": "分类销售", "shape": "crosstab", "dimension": "category", "period": "year", "desc": "按年统计各商品分类的销量与销售额"},
    # —— 其余 4 张 ——
    {"key": "inventory-flow", "name": "商品出入统计", "group": "库存报表", "shape": "flow", "dimension": "product", "period": "month", "desc": "按商品统计期初、本期入库、本期出库与期末结存"},
    {"key": "salesman", "name": "销售员报表", "group": "业绩考核", "shape": "crosstab", "dimension": "salesman", "period": "month", "desc": "按业务员统计销售量、销售额与毛利贡献"},
    {"key": "product-sales-detail", "name": "商品销售明细表", "group": "商品销售", "shape": "detail", "dimension": "product", "period": "day", "desc": "逐笔列出销售单据的商品行，可追溯单号与客户"},
    {"key": "boss", "name": "老板报表", "group": "经营看板", "shape": "overview", "dimension": "", "period": "month", "desc": "收入、成本、毛利、应收应付、库存与 Top 榜一屏总览"},
]

REPORT_BY_KEY: dict[str, dict[str, object]] = {str(item["key"]): item for item in REPORT_CATALOG}


# ============================================================
# 期间分桶
# ============================================================
def _today() -> str:
    return date.today().isoformat()


def _parse_day(value: str) -> date:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"日期格式应为 YYYY-MM-DD：{value}")


def _bucket_of(day: str, period: str) -> str:
    """把一个 YYYY-MM-DD 归入期间桶。"""
    if period == "month":
        return day[:7]
    if period == "quarter":
        return f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}"
    if period == "year":
        return day[:4]
    return day[:10]


def _bucket_sequence(start: date, end: date, period: str) -> list[str]:
    """列出区间内的全部期间桶（含空桶，报表要能看出"这段时间没卖"）。"""
    buckets: list[str] = []
    if period == "year":
        for year in range(start.year, end.year + 1):
            buckets.append(str(year))
    elif period == "quarter":
        y, q = start.year, (start.month - 1) // 3 + 1
        while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
            buckets.append(f"{y}-Q{q}")
            q += 1
            if q > 4:
                y, q = y + 1, 1
    elif period == "month":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            buckets.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                y, m = y + 1, 1
    else:
        cursor = start
        while cursor <= end:
            buckets.append(cursor.isoformat())
            cursor += timedelta(days=1)
    return buckets


def _default_range(period: str) -> tuple[str, str]:
    """各粒度的默认区间：够看趋势，又不至于把列撑爆。"""
    end = date.today()
    if period == "day":
        return (end - timedelta(days=29)).isoformat(), end.isoformat()
    if period == "month":
        start = (end.replace(day=1) - timedelta(days=335)).replace(day=1)
        return start.isoformat(), end.isoformat()
    if period == "quarter":
        return (end - timedelta(days=365 * 2 - 30)).isoformat(), end.isoformat()
    if period == "year":
        return date(end.year - 4, 1, 1).isoformat(), end.isoformat()
    return (end - timedelta(days=364)).isoformat(), end.isoformat()


# ============================================================
# 事实数据：销售（含退货冲减）
# ============================================================
@dataclass
class _Fact:
    """销售事实行：一行 = 一张销售单里的一行商品（退货并入为负数）。"""

    day: str
    doc_no: str
    party_id: int | None
    party_name: str
    product_id: int | None
    product_name: str
    standards: str
    unit: str
    category: str
    salesman: str
    quantity: float
    amount: float
    cost: float
    note: str = ""


def _money(value) -> float:
    return round(float(value or 0.0), 2)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _load_products(db: Session) -> dict[int, Product]:
    return {item.id: item for item in db.query(Product).all()}


def _load_customers(db: Session) -> dict[int, Customer]:
    return {item.id: item for item in db.query(Customer).all()}


def _sales_facts(db: Session, date_from: str, date_to: str) -> list[_Fact]:
    """取区间内的销售事实（开单出库 − 销售退货）。

    doc_type 只认 `outbound`：`order` 是"只订货没发货"，与库存/财务口径保持一致。
    """
    products = _load_products(db)
    customers = _load_customers(db)
    facts: list[_Fact] = []

    rows = (
        db.query(SalesOrderItem, SalesOrder)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(SalesOrder.doc_type == "outbound")
        .filter(SalesOrder.order_date >= date_from)
        .filter(SalesOrder.order_date <= date_to)
        .all()
    )
    for line, order in rows:
        product = products.get(line.product_id) if line.product_id is not None else None
        customer = customers.get(order.customer_id)
        quantity = float(line.quantity or 0)
        cost_price = float(getattr(product, "purchase_price", 0.0) or 0.0)
        facts.append(
            _Fact(
                day=_text(order.order_date)[:10] or _date_of(order.created_at),
                doc_no=_text(order.order_no),
                party_id=order.customer_id,
                party_name=_text(customer.name) if customer else f"客户-{order.customer_id}",
                product_id=line.product_id,
                product_name=_text(line.product_name) or _text(getattr(product, "name", "")) or f"商品-{line.product_id}",
                standards=_text(line.standards) or _text(getattr(product, "standards", "")),
                unit=_text(line.unit) or _text(getattr(product, "unit", "")),
                category=_text(getattr(product, "category", "")) or "未分类",
                salesman=_text(order.businesser) or _text(getattr(customer, "businesser", "")) or "未分配",
                quantity=quantity,
                amount=float(line.amount or 0.0),
                cost=quantity * cost_price,
                note="",
            )
        )

    # 销售退货：负数并入，报表口径 = 净销售
    returns = (
        db.query(SalesReturnItem, SalesReturn)
        .join(SalesReturn, SalesReturn.id == SalesReturnItem.sales_return_id)
        .filter(SalesReturn.return_date >= date_from)
        .filter(SalesReturn.return_date <= date_to)
        .all()
    )
    for line, record in returns:
        product = products.get(line.product_id) if line.product_id is not None else None
        customer = customers.get(record.customer_id)
        quantity = float(line.quantity or 0)
        cost_price = float(getattr(product, "purchase_price", 0.0) or 0.0)
        facts.append(
            _Fact(
                day=_text(record.return_date)[:10] or _date_of(record.created_at),
                doc_no=_text(record.return_no),
                party_id=record.customer_id,
                party_name=_text(record.customer_name) or (_text(customer.name) if customer else f"客户-{record.customer_id}"),
                product_id=line.product_id,
                product_name=_text(line.product_name) or _text(getattr(product, "name", "")) or f"商品-{line.product_id}",
                standards=_text(line.standards) or _text(getattr(product, "standards", "")),
                unit=_text(line.unit) or _text(getattr(product, "unit", "")),
                category=_text(getattr(product, "category", "")) or "未分类",
                salesman=_text(record.businesser) or _text(getattr(customer, "businesser", "")) or "未分配",
                quantity=-quantity,
                amount=-float(line.amount or 0.0),
                cost=-quantity * cost_price,
                note="退货冲减",
            )
        )
    return facts


def _date_of(created_at) -> str:
    if created_at is None:
        return ""
    if isinstance(created_at, datetime):
        return created_at.date().isoformat()
    return str(created_at)[:10]


# ============================================================
# 形态一：交叉表（12 张期间报表 + 销售员报表）
# ============================================================
def _dimension_key(fact: _Fact, dimension: str) -> tuple[str, str, dict[str, object]]:
    """返回 (分组键, 显示名, 附加维度信息)。"""
    if dimension == "customer":
        return (
            f"c{fact.party_id}",
            fact.party_name or "散客",
            {"party_id": fact.party_id},
        )
    if dimension == "category":
        return (f"g{fact.category}", fact.category or "未分类", {"category": fact.category})
    if dimension == "salesman":
        return (f"s{fact.salesman}", fact.salesman or "未分配", {"salesman": fact.salesman})
    # product（默认）
    return (
        f"p{fact.product_id}",
        fact.product_name or "未知商品",
        {
            "product_id": fact.product_id,
            "standards": fact.standards,
            "unit": fact.unit,
            "category": fact.category,
        },
    )


def build_crosstab(
    db: Session,
    *,
    dimension: str,
    period: str,
    date_from: str,
    date_to: str,
    limit: int | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    buckets = _bucket_sequence(_parse_day(date_from), _parse_day(date_to), period)
    if len(buckets) > MAX_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"区间过大：{period} 粒度会产生 {len(buckets)} 列（上限 {MAX_BUCKETS}）。请缩小日期范围，或改用更粗的粒度。",
        )
    bucket_index = {bucket: position for position, bucket in enumerate(buckets)}

    facts = _sales_facts(db, date_from, date_to)
    keyword = (keyword or "").strip()

    groups: dict[str, dict[str, object]] = {}
    for fact in facts:
        key, name, extra = _dimension_key(fact, dimension)
        if keyword and keyword not in name:
            continue
        bucket = _bucket_of(fact.day, period)
        position = bucket_index.get(bucket)
        if position is None:
            continue
        group = groups.get(key)
        if group is None:
            group = {
                "key": key,
                "name": name,
                "extra": extra,
                "cells": [[0.0, 0.0] for _ in buckets],  # [数量, 金额]
                "quantity": 0.0,
                "amount": 0.0,
                "cost": 0.0,
                "orders": 0,
            }
            groups[key] = group
        cell = group["cells"][position]
        cell[0] += fact.quantity
        cell[1] += fact.amount
        group["quantity"] += fact.quantity
        group["amount"] += fact.amount
        group["cost"] += fact.cost

    # 单数：按 (维度, 单号) 去重
    order_keys: set[tuple[str, str]] = set()
    for fact in facts:
        key, name, _extra = _dimension_key(fact, dimension)
        if keyword and keyword not in name:
            continue
        if fact.doc_no:
            order_keys.add((key, fact.doc_no))
    doc_count: dict[str, int] = {}
    for key, _doc in order_keys:
        doc_count[key] = doc_count.get(key, 0) + 1

    rows: list[dict[str, object]] = []
    grand_amount = sum(float(group["amount"]) for group in groups.values()) or 0.0
    for group in groups.values():
        group["orders"] = doc_count.get(str(group["key"]), 0)
        amount = float(group["amount"])
        cost = float(group["cost"])
        rows.append(
            {
                "key": group["key"],
                "name": group["name"],
                "extra": group["extra"],
                "cells": [
                    {"quantity": _money(cell[0]), "amount": _money(cell[1])}
                    for cell in group["cells"]  # type: ignore[index]
                ],
                "quantity": _money(group["quantity"]),
                "amount": _money(amount),
                "cost": _money(cost),
                "gross_profit": _money(amount - cost),
                "margin": round((amount - cost) / amount * 100, 2) if amount else 0.0,
                "orders": int(group["orders"]),
                "share": round(amount / grand_amount * 100, 2) if grand_amount else 0.0,
            }
        )
    rows.sort(key=lambda row: float(row["amount"]), reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]

    total_quantity = sum(float(row["quantity"]) for row in rows)
    total_amount = sum(float(row["amount"]) for row in rows)
    total_cost = sum(float(row["cost"]) for row in rows)

    series = []
    for position, bucket in enumerate(buckets):
        value = 0.0
        for group in groups.values():
            value += float(group["cells"][position][1])  # type: ignore[index]
        series.append({"label": bucket, "value": _money(value)})

    return {
        "shape": "crosstab",
        "buckets": buckets,
        "rows": rows,
        "series": series,
        "summary": {
            "row_count": len(rows),
            "bucket_count": len(buckets),
            "total_quantity": _money(total_quantity),
            "total_amount": _money(total_amount),
            "total_cost": _money(total_cost),
            "gross_profit": _money(total_amount - total_cost),
            "margin": round((total_amount - total_cost) / total_amount * 100, 2) if total_amount else 0.0,
        },
        "notes": [
            "口径：净销售 = 开单出库 − 销售退货（退货按负数并入）。",
            "只统计「开单管理」出库单；只订货未发货的销售订单不计入。",
            "成本按商品档案当前采购价估算，毛利为估算值。",
        ],
    }


# ============================================================
# 形态二：明细表（商品销售明细表）
# ============================================================
def build_sales_detail(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    limit: int | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    facts = _sales_facts(db, date_from, date_to)
    keyword = (keyword or "").strip()
    if keyword:
        facts = [
            fact
            for fact in facts
            if keyword in fact.product_name or keyword in fact.party_name or keyword in fact.doc_no
        ]
    facts.sort(key=lambda fact: (fact.day, fact.doc_no), reverse=True)

    total_quantity = sum(fact.quantity for fact in facts)
    total_amount = sum(fact.amount for fact in facts)
    total_cost = sum(fact.cost for fact in facts)

    rows = [
        {
            "day": fact.day,
            "doc_no": fact.doc_no,
            "party_name": fact.party_name,
            "product_name": fact.product_name,
            "standards": fact.standards,
            "unit": fact.unit,
            "category": fact.category,
            "salesman": fact.salesman,
            "quantity": _money(fact.quantity),
            "unit_price": _money(abs(fact.amount / fact.quantity) if fact.quantity else 0.0),
            "amount": _money(fact.amount),
            "gross_profit": _money(fact.amount - fact.cost),
            "note": fact.note,
        }
        for fact in (facts[:limit] if limit and limit > 0 else facts)
    ]

    daily: dict[str, float] = {}
    for fact in facts:
        daily[fact.day] = daily.get(fact.day, 0.0) + fact.amount

    return {
        "shape": "detail",
        "rows": rows,
        "series": [
            {"label": day, "value": _money(value)}
            for day, value in sorted(daily.items())
        ],
        "summary": {
            "row_count": len(rows),
            "total_rows": len(facts),
            "total_quantity": _money(total_quantity),
            "total_amount": _money(total_amount),
            "total_cost": _money(total_cost),
            "gross_profit": _money(total_amount - total_cost),
            "margin": round((total_amount - total_cost) / total_amount * 100, 2) if total_amount else 0.0,
        },
        "notes": ["逐行列示销售单据的商品行，退货行以负数出现并标注「退货冲减」。"],
    }


# ============================================================
# 形态三：收发存（商品出入统计）
# ============================================================
def _stock_delta(transaction_type: str, quantity) -> int:
    qty = int(quantity or 0)
    kind = _text(transaction_type).lower()
    if kind in INBOUND_TYPES:
        return abs(qty)
    if kind in OUTBOUND_TYPES:
        return -abs(qty)
    return qty


def build_inventory_flow(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    warehouse_id: int | None = None,
    limit: int | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    """商品出入统计：一行 = 商品（可按仓库拆），列出期初 / 本期入 / 本期出 / 期末。

    期初不是查出来的，是**倒推**的：期初 = 全部流水中日期 < 区间起点 的累计增减。
    期末直接等于"截止区间终点的累计"，两者天然自洽（期初 + 入 − 出 = 期末）。
    """
    products = _load_products(db)
    warehouses = {item.id: item for item in db.query(Warehouse).all()}
    start = date_from
    end = date_to

    query = db.query(InventoryTransaction)
    if warehouse_id:
        query = query.filter(InventoryTransaction.warehouse_id == warehouse_id)

    keyword = (keyword or "").strip()
    opening: dict[tuple[int, int], int] = {}
    inbound: dict[tuple[int, int], int] = {}
    outbound: dict[tuple[int, int], int] = {}
    in_amount: dict[tuple[int, int], float] = {}
    out_amount: dict[tuple[int, int], float] = {}

    for row in query.all():
        key = (row.product_id, row.warehouse_id)
        product = products.get(row.product_id)
        if keyword:
            name = _text(getattr(product, "name", ""))
            if keyword not in name and keyword not in _text(getattr(product, "sku", "")):
                continue
        day = _date_of(row.created_at)
        delta = _stock_delta(row.transaction_type, row.quantity)
        if day and day < start:
            opening[key] = opening.get(key, 0) + delta
            continue
        if day and day > end:
            # 区间之后发生的流水不该进本期，但也不该算期初 —— 直接忽略
            continue
        if delta >= 0:
            inbound[key] = inbound.get(key, 0) + delta
            in_amount[key] = in_amount.get(key, 0.0) + delta * float(row.unit_price or 0.0)
        else:
            outbound[key] = outbound.get(key, 0) + (-delta)
            out_amount[key] = out_amount.get(key, 0.0) + (-delta) * float(row.unit_price or 0.0)

    keys = set(opening) | set(inbound) | set(outbound)
    rows: list[dict[str, object]] = []
    for key in keys:
        product_id, warehouse = key
        product = products.get(product_id)
        begin = opening.get(key, 0)
        in_qty = inbound.get(key, 0)
        out_qty = outbound.get(key, 0)
        if not (begin or in_qty or out_qty):
            continue
        rows.append(
            {
                "key": f"{product_id}-{warehouse}",
                "product_id": product_id,
                "sku": _text(getattr(product, "sku", "")),
                "product_name": _text(getattr(product, "name", "")) or f"商品-{product_id}",
                "standards": _text(getattr(product, "standards", "")),
                "unit": _text(getattr(product, "unit", "")),
                "category": _text(getattr(product, "category", "")) or "未分类",
                "warehouse_id": warehouse,
                "warehouse_name": _text(getattr(warehouses.get(warehouse), "name", "")) or f"仓库-{warehouse}",
                "opening": begin,
                "inbound": in_qty,
                "outbound": out_qty,
                "closing": begin + in_qty - out_qty,
                "inbound_amount": _money(in_amount.get(key, 0.0)),
                "outbound_amount": _money(out_amount.get(key, 0.0)),
            }
        )
    rows.sort(key=lambda row: (int(row["inbound"]) + int(row["outbound"])), reverse=True)
    if limit and limit > 0:
        rows = rows[:limit]

    total_in = sum(int(row["inbound"]) for row in rows)
    total_out = sum(int(row["outbound"]) for row in rows)

    return {
        "shape": "flow",
        "rows": rows,
        "series": [
            {"label": "期初", "value": sum(int(row["opening"]) for row in rows)},
            {"label": "本期入库", "value": total_in},
            {"label": "本期出库", "value": total_out},
            {"label": "期末", "value": sum(int(row["closing"]) for row in rows)},
        ],
        "summary": {
            "row_count": len(rows),
            "opening": sum(int(row["opening"]) for row in rows),
            "inbound": total_in,
            "outbound": total_out,
            "closing": sum(int(row["closing"]) for row in rows),
            "inbound_amount": _money(sum(float(row["inbound_amount"]) for row in rows)),
            "outbound_amount": _money(sum(float(row["outbound_amount"]) for row in rows)),
        },
        "notes": [
            "期初 = 区间起点之前的全部库存流水累计；期末 = 期初 + 入库 − 出库，恒等成立。",
            "入库含采购入库、销售退货、生产领料退回、成品入库、调拨入、盘盈、报溢；出库为其反向。",
        ],
    }


# ============================================================
# 形态四：老板报表
# ============================================================
def build_boss(db: Session, *, date_from: str, date_to: str) -> dict[str, object]:
    """老板报表：一屏看完"赚了多少、欠了多少、压了多少货"。"""
    facts = _sales_facts(db, date_from, date_to)
    revenue = sum(fact.amount for fact in facts)
    cost = sum(fact.cost for fact in facts)
    gross = revenue - cost

    # 应收 / 应付：由财务流水实时算（receivable/payable 的累计未结）
    receivable = 0.0
    payable = 0.0
    for row in db.query(FinancialTransaction).all():
        kind = _text(row.transaction_type)
        if kind == "receivable":
            receivable += float(row.amount or 0.0)
        elif kind == "payable":
            payable += float(row.amount or 0.0)
        elif kind == "receipt":
            receivable -= float(row.amount or 0.0)
        elif kind == "payment":
            payable -= float(row.amount or 0.0)

    # 库存资金占用
    products = _load_products(db)
    stock_value = 0.0
    stock_quantity = 0
    for (product_id, _warehouse), quantity in _net_stock_map(db).items():
        stock_quantity += quantity
        product = products.get(product_id)
        stock_value += quantity * float(getattr(product, "purchase_price", 0.0) or 0.0)

    # 采购额（同期）
    purchase_total = 0.0
    for order in (
        db.query(PurchaseOrder)
        .filter(PurchaseOrder.doc_type == "inbound")
        .filter(PurchaseOrder.order_date >= date_from)
        .filter(PurchaseOrder.order_date <= date_to)
        .all()
    ):
        purchase_total += float(order.total_amount or 0.0)

    def _rank(dimension: str, top: int = 5) -> list[dict[str, object]]:
        groups: dict[str, dict[str, object]] = {}
        for fact in facts:
            key, name, _extra = _dimension_key(fact, dimension)
            group = groups.setdefault(key, {"name": name, "quantity": 0.0, "amount": 0.0, "cost": 0.0})
            group["quantity"] += fact.quantity
            group["amount"] += fact.amount
            group["cost"] += fact.cost
        ranked = [
            {
                "name": group["name"],
                "quantity": _money(group["quantity"]),
                "amount": _money(group["amount"]),
                "gross_profit": _money(float(group["amount"]) - float(group["cost"])),
            }
            for group in groups.values()
        ]
        ranked.sort(key=lambda row: float(row["amount"]), reverse=True)
        return ranked[:top]

    monthly: dict[str, float] = {}
    for fact in facts:
        bucket = _bucket_of(fact.day, "month")
        monthly[bucket] = monthly.get(bucket, 0.0) + fact.amount

    return {
        "shape": "overview",
        "metric_groups": [
            {
                "title": "经营成果",
                "metrics": [
                    {"label": "净销售额", "value": _money(revenue), "unit": "CNY"},
                    {"label": "销售成本", "value": _money(cost), "unit": "CNY"},
                    {"label": "毛利", "value": _money(gross), "unit": "CNY"},
                    {"label": "毛利率", "value": round(gross / revenue * 100, 2) if revenue else 0.0, "unit": "%"},
                    {"label": "采购额", "value": _money(purchase_total), "unit": "CNY"},
                ],
            },
            {
                "title": "资金占用",
                "metrics": [
                    {"label": "应收未收", "value": _money(receivable), "unit": "CNY"},
                    {"label": "应付未付", "value": _money(payable), "unit": "CNY"},
                    {"label": "库存资金", "value": _money(stock_value), "unit": "CNY"},
                    {"label": "库存数量", "value": int(stock_quantity), "unit": "件"},
                    {"label": "净资金缺口", "value": _money(receivable - payable), "unit": "CNY"},
                ],
            },
        ],
        "highlights": [
            {"title": "热销商品 Top5", "rows": _rank("product")},
            {"title": "销售员 Top5", "rows": _rank("salesman")},
            {"title": "客户 Top5", "rows": _rank("customer")},
            {"title": "商品分类 Top5", "rows": _rank("category")},
        ],
        "series": [{"label": label, "value": _money(value)} for label, value in sorted(monthly.items())],
        "summary": {
            "revenue": _money(revenue),
            "cost": _money(cost),
            "gross_profit": _money(gross),
            "margin": round(gross / revenue * 100, 2) if revenue else 0.0,
            "receivable": _money(receivable),
            "payable": _money(payable),
            "stock_value": _money(stock_value),
        },
        "notes": [
            "净销售额 = 开单出库 − 销售退货；成本按商品当前采购价估算。",
            "应收/应付由财务流水实时累计（应收应付 − 已收已付），与「应收账款 / 应付账款」页同一口径。",
        ],
    }


def _net_stock_map(db: Session) -> dict[tuple[int, int], int]:
    """全库净库存：(product_id, warehouse_id) -> 现存量。与 erp.py 口径一致。"""
    result: dict[tuple[int, int], int] = {}
    for row in db.query(InventoryTransaction).all():
        key = (row.product_id, row.warehouse_id)
        result[key] = result.get(key, 0) + _stock_delta(row.transaction_type, row.quantity)
    return result


# ============================================================
# 接口
# ============================================================
@router.get("/catalog")
def report_catalog() -> dict[str, object]:
    """报表目录：16 张报表的元数据 + 维度/粒度字典。前端菜单直接渲染这个。"""
    groups: list[dict[str, object]] = []
    for item in REPORT_CATALOG:
        group_name = str(item["group"])
        group = next((entry for entry in groups if entry["group"] == group_name), None)
        if group is None:
            group = {"group": group_name, "reports": []}
            groups.append(group)
        group["reports"].append(  # type: ignore[union-attr]
            {
                "key": item["key"],
                "name": item["name"],
                "shape": item["shape"],
                "dimension": item.get("dimension", ""),
                "period": item.get("period", ""),
                "desc": item["desc"],
            }
        )
    return {
        "total": len(REPORT_CATALOG),
        "groups": groups,
        "dimensions": DIMENSIONS,
        "periods": PERIODS,
    }


@router.get("/data/{report_key}")
def report_data(
    report_key: str,
    db: Session = Depends(get_db),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    dimension: str | None = Query(default=None),
    period: str | None = Query(default=None),
    warehouse_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int | None = Query(default=None),
) -> dict[str, object]:
    """统一取数入口：报表目录里的 16 个 key 全部走这里。"""
    meta = REPORT_BY_KEY.get(report_key)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"未知报表：{report_key}")

    shape = str(meta["shape"])
    # 粒度：只在交叉表里允许切换（明细/收发存/大盘没有"桶"的概念）
    active_period = (period or str(meta.get("period") or "month")).strip()
    if active_period not in PERIODS:
        raise HTTPException(status_code=400, detail=f"未知粒度：{active_period}")

    default_from, default_to = _default_range(active_period)
    start = (date_from or default_from)[:10]
    end = (date_to or default_to)[:10]
    if _parse_day(start) > _parse_day(end):
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")

    active_dimension = (dimension or str(meta.get("dimension") or "product")).strip()

    if shape == "crosstab":
        if active_dimension not in DIMENSIONS:
            raise HTTPException(status_code=400, detail=f"未知维度：{active_dimension}")
        payload = build_crosstab(
            db,
            dimension=active_dimension,
            period=active_period,
            date_from=start,
            date_to=end,
            limit=limit,
            keyword=keyword,
        )
    elif shape == "detail":
        payload = build_sales_detail(db, date_from=start, date_to=end, limit=limit, keyword=keyword)
    elif shape == "flow":
        payload = build_inventory_flow(
            db, date_from=start, date_to=end, warehouse_id=warehouse_id, limit=limit, keyword=keyword
        )
    elif shape == "overview":
        payload = build_boss(db, date_from=start, date_to=end)
    else:  # pragma: no cover - 目录里不会出现未知形态
        raise HTTPException(status_code=500, detail=f"报表形态未实现：{shape}")

    return {
        "report": {
            "key": meta["key"],
            "name": meta["name"],
            "group": meta["group"],
            "shape": shape,
            "desc": meta["desc"],
            "dimension": active_dimension if shape == "crosstab" else "",
            "period": active_period if shape == "crosstab" else "",
        },
        "range": {"date_from": start, "date_to": end},
        **payload,
    }


# 导出时的列定义：与前端表格保持一致
_EXPORT_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "crosstab": [("name", "名称")],
    "detail": [
        ("day", "日期"),
        ("doc_no", "单号"),
        ("party_name", "客户"),
        ("product_name", "商品"),
        ("standards", "规格"),
        ("unit", "单位"),
        ("quantity", "数量"),
        ("unit_price", "单价"),
        ("amount", "金额"),
        ("gross_profit", "毛利"),
        ("salesman", "业务员"),
        ("note", "备注"),
    ],
    "flow": [
        ("sku", "编码"),
        ("product_name", "商品"),
        ("standards", "规格"),
        ("warehouse_name", "仓库"),
        ("unit", "单位"),
        ("opening", "期初"),
        ("inbound", "本期入库"),
        ("outbound", "本期出库"),
        ("closing", "期末结存"),
    ],
}


@router.get("/export/{report_key}")
def export_report(
    report_key: str,
    db: Session = Depends(get_db),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    dimension: str | None = Query(default=None),
    period: str | None = Query(default=None),
    warehouse_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> Response:
    """把任意一张报表导成 CSV（带 UTF-8 BOM，Excel 直接双击不乱码）。"""
    payload = report_data(
        report_key,
        db=db,
        date_from=date_from,
        date_to=date_to,
        dimension=dimension,
        period=period,
        warehouse_id=warehouse_id,
        keyword=keyword,
        limit=None,
    )
    shape = str(payload["shape"])
    report = payload["report"]
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"{report['name']}（{payload['range']['date_from']} ~ {payload['range']['date_to']}）"])

    if shape == "crosstab":
        buckets = list(payload["buckets"])  # type: ignore[arg-type]
        header = ["名称"]
        for bucket in buckets:
            header += [f"{bucket} 数量", f"{bucket} 金额"]
        header += ["合计数量", "合计金额", "毛利", "毛利率%", "占比%", "单数"]
        writer.writerow(header)
        for row in payload["rows"]:  # type: ignore[union-attr]
            line = [row["name"]]
            for cell in row["cells"]:
                line += [cell["quantity"], cell["amount"]]
            line += [
                row["quantity"],
                row["amount"],
                row["gross_profit"],
                row["margin"],
                row["share"],
                row["orders"],
            ]
            writer.writerow(line)
        summary = payload["summary"]
        writer.writerow([])
        writer.writerow(["合计", "", "", summary["total_quantity"], summary["total_amount"], summary["gross_profit"]])
    elif shape in ("detail", "flow"):
        columns = _EXPORT_COLUMNS[shape]
        writer.writerow([label for _key, label in columns])
        for row in payload["rows"]:  # type: ignore[union-attr]
            writer.writerow([row.get(key, "") for key, _label in columns])
    else:  # overview（老板报表）
        for group in payload["metric_groups"]:  # type: ignore[union-attr]
            writer.writerow([group["title"]])
            writer.writerow([metric["label"] for metric in group["metrics"]])
            writer.writerow([metric["value"] for metric in group["metrics"]])
            writer.writerow([])
        for block in payload["highlights"]:  # type: ignore[union-attr]
            writer.writerow([block["title"]])
            writer.writerow(["名称", "数量", "金额", "毛利"])
            for row in block["rows"]:
                writer.writerow([row["name"], row["quantity"], row["amount"], row["gross_profit"]])
            writer.writerow([])

    for note in payload.get("notes") or []:
        writer.writerow([f"注：{note}"])

    filename = f"{report['key']}_{payload['range']['date_from']}_{payload['range']['date_to']}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
