"""报表中心（第 4 批 · 16 张聚合报表）回归测试。

报表是**只读**的：不建表、不写库存、不写财务。所以这一批的风险不在"写坏数据"，
而在"算错数"。本文件主要锁四件事：

1. **目录完整**：16 张报表、key 唯一、形态合法（前端菜单直接吃这个）。
2. **分桶正确**：日/月/季/年四种粒度的桶序列与归类规则。
3. **聚合正确**：维度（商品/客户/分类/销售员）分得对，退货按负数冲减，
   「只订货未发货」的销售订单不进报表。
4. **只读**：跑完全部 16 张报表，库存流水与财务流水的条数必须一条不变。

断言一律**按名字定位到自己造的那一行**，不比对全局合计 —— 正式库里本来就有
其他业务数据（含期初建账），比对全局会假失败。

测试数据遵守 scripts/clean_test_data.py 的编码签名：SKU-RPT-<hex> / CUST-RPT-<hex>。
"""

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api.v1.routes.reports import (
    MAX_BUCKETS,
    REPORT_CATALOG,
    _bucket_of,
    _bucket_sequence,
    _default_range,
)
from app.main import app

client = TestClient(app)


# ============================================================
# 造数据 / 清数据
# ============================================================
def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _new_product(name: str, *, price: float = 4.0, sale: float = 10.0, category: str = "报表测试分类") -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-RPT-{_hex()}",
            "name": name,
            "purchase_price": price,
            "sale_price": sale,
            "category": category,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_customer(name: str, *, businesser: str = "报表业务员") -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-RPT-{_hex()}", "name": name, "businesser": businesser},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse() -> int:
    resp = client.post("/api/v1/warehouses", json={"code": f"WH-{_hex()}", "name": "报表测试仓"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post("/api/v1/suppliers", json={"code": f"SUP-RPT-{_hex()}", "name": "报表测试供应商"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _sale(
    customer_id: int,
    product_id: int,
    quantity: int,
    unit_price: float,
    day: str,
    *,
    doc_type: str = "outbound",
    warehouse_id: int | None = None,
    businesser: str = "报表业务员",
) -> dict:
    resp = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "doc_type": doc_type,
            "warehouse_id": warehouse_id,
            "businesser": businesser,
            "order_date": day,
            "items": [{"product_id": product_id, "quantity": quantity, "unit_price": unit_price}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _return(customer_id: int, product_id: int, quantity: int, unit_price: float, day: str) -> dict:
    resp = client.post(
        "/api/v1/sales-returns",
        json={
            "return_no": f"TEST-XSTH{_hex().upper()}",
            "customer_id": customer_id,
            "return_date": day,
            "items": [
                {"product_id": product_id, "quantity": quantity, "unit_price": unit_price}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _report(key: str, **params) -> dict:
    resp = client.get(f"/api/v1/reports/data/{key}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row(rows: list[dict], name: str) -> dict | None:
    return next((row for row in rows if row.get("name") == name), None)


def _iso(offset_days: int) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


# ============================================================
# 一、目录与参数校验
# ============================================================
def test_catalog_has_16_reports_with_unique_keys():
    resp = client.get("/api/v1/reports/catalog")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["total"] == 16
    assert len(REPORT_CATALOG) == 16

    keys = [item["key"] for item in REPORT_CATALOG]
    assert len(set(keys)) == 16, "报表 key 必须唯一"

    flat = [item for group in payload["groups"] for item in group["reports"]]
    assert len(flat) == 16
    for item in flat:
        assert item["shape"] in {"crosstab", "detail", "flow", "overview"}, item
        assert item["name"] and item["desc"]

    # 12 张期间报表 = 3 维度 × 4 粒度
    crosstab = [item for item in REPORT_CATALOG if item["shape"] == "crosstab"]
    assert len(crosstab) == 13  # 12 张维度报表 + 销售员报表
    combos = {(item["dimension"], item["period"]) for item in crosstab if item["dimension"] != "salesman"}
    assert combos == {
        (dimension, period)
        for dimension in ("product", "customer", "category")
        for period in ("day", "month", "quarter", "year")
    }
    assert len(payload["dimensions"]) == 4
    assert len(payload["periods"]) == 4


def test_unknown_report_returns_404():
    resp = client.get("/api/v1/reports/data/not-a-report")
    assert resp.status_code == 404


def test_bad_date_range_returns_400():
    resp = client.get(
        "/api/v1/reports/data/product-sales-month",
        params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
    )
    assert resp.status_code == 400
    assert "开始日期" in resp.json()["detail"]


def test_too_many_buckets_is_rejected_not_truncated():
    """日粒度拉两年 = 700+ 列，必须报错，而不是悄悄截断出一张错报表。"""
    resp = client.get(
        "/api/v1/reports/data/product-sales-day",
        params={"date_from": "2024-01-01", "date_to": "2026-01-01"},
    )
    assert resp.status_code == 400
    assert str(MAX_BUCKETS) in resp.json()["detail"]


# ============================================================
# 二、分桶引擎
# ============================================================
def test_bucket_of_handles_all_four_periods():
    day = "2026-05-17"
    assert _bucket_of(day, "day") == "2026-05-17"
    assert _bucket_of(day, "month") == "2026-05"
    assert _bucket_of(day, "quarter") == "2026-Q2"
    assert _bucket_of(day, "year") == "2026"

    # 季度边界：1/4/7/10 月各起一个新季度
    assert _bucket_of("2026-01-01", "quarter") == "2026-Q1"
    assert _bucket_of("2026-03-31", "quarter") == "2026-Q1"
    assert _bucket_of("2026-04-01", "quarter") == "2026-Q2"
    assert _bucket_of("2026-07-01", "quarter") == "2026-Q3"
    assert _bucket_of("2026-12-31", "quarter") == "2026-Q4"


def test_bucket_sequence_spans_boundaries():
    start, end = date(2026, 11, 20), date(2027, 3, 2)

    assert _bucket_sequence(start, end, "month") == ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    assert _bucket_sequence(start, end, "quarter") == ["2026-Q4", "2027-Q1"]
    assert _bucket_sequence(start, end, "year") == ["2026", "2027"]
    days = _bucket_sequence(date(2026, 12, 30), date(2027, 1, 2), "day")
    assert days == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]


def test_default_range_stays_within_bucket_cap():
    """每种粒度的默认区间都必须能直接出报表（不触发列数上限）。"""
    for period in ("day", "month", "quarter", "year"):
        start, end = _default_range(period)
        buckets = _bucket_sequence(date.fromisoformat(start), date.fromisoformat(end), period)
        assert 1 <= len(buckets) <= MAX_BUCKETS, (period, len(buckets))


# ============================================================
# 三、交叉表：维度聚合
# ============================================================
def test_product_sales_month_aggregates_by_bucket():
    product_id = _new_product(f"报表商品月报A-{_hex()}")
    customer_id = _new_customer(f"报表客户月报A-{_hex()}")
    start, end = _iso(-40), _iso(0)
    try:
        # 两笔，落在不同月份：用区间内的两个日期
        first_day, second_day = _iso(-35), _iso(-3)
        _sale(customer_id, product_id, 10, 10.0, first_day)
        _sale(customer_id, product_id, 5, 10.0, second_day)

        payload = _report("product-sales-month", date_from=start, date_to=end)
        assert payload["shape"] == "crosstab"
        assert payload["report"]["dimension"] == "product"

        buckets = payload["buckets"]
        # 自己造的商品必须出现，数量/金额/毛利口径正确
        row = next(r for r in payload["rows"] if r["extra"].get("product_id") == product_id)
        assert row["quantity"] == 15
        assert row["amount"] == 150.0
        assert row["cost"] == 60.0  # 15 × 采购价 4.0
        assert row["gross_profit"] == 90.0
        assert row["margin"] == 60.0
        assert row["orders"] == 2

        # 两个桶各自的金额加起来 = 合计
        cell_amount = sum(cell["amount"] for cell in row["cells"])
        assert cell_amount == 150.0
        assert len(row["cells"]) == len(buckets)

        # 桶标签必须与请求的日期区间同构
        first_bucket = _bucket_of(first_day, "month")
        assert first_bucket in buckets
        position = buckets.index(first_bucket)
        assert row["cells"][position]["amount"] in (50.0, 100.0)
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_customer_and_category_dimensions_are_distinct():
    tag = _hex()
    product_id = _new_product(f"报表商品分类A-{tag}", category=f"报表分类-{tag}")
    customer_a = _new_customer(f"报表客户甲-{tag}")
    customer_b = _new_customer(f"报表客户乙-{tag}")
    start, end = _iso(-10), _iso(0)
    try:
        _sale(customer_a, product_id, 4, 10.0, _iso(-2))
        _sale(customer_b, product_id, 6, 10.0, _iso(-1))

        by_customer = _report("customer-sales-month", date_from=start, date_to=end)
        row_a = _row(by_customer["rows"], f"报表客户甲-{tag}")
        row_b = _row(by_customer["rows"], f"报表客户乙-{tag}")
        assert row_a and row_a["quantity"] == 4 and row_a["amount"] == 40.0
        assert row_b and row_b["quantity"] == 6 and row_b["amount"] == 60.0
        assert row_a["extra"]["party_id"] == customer_a

        by_category = _report("category-sales-month", date_from=start, date_to=end)
        row_c = _row(by_category["rows"], f"报表分类-{tag}")
        assert row_c and row_c["quantity"] == 10 and row_c["amount"] == 100.0
        # 分类维度下没有 product_id（是聚合出来的）
        assert "product_id" not in row_c["extra"]
    finally:
        for cid in (customer_a, customer_b):
            client.delete(f"/api/v1/customers/{cid}")
        client.delete(f"/api/v1/products/{product_id}")


def test_salesman_report_falls_back_to_customer_businesser():
    tag = _hex()
    product_id = _new_product(f"报表商品业务员-{tag}")
    customer_id = _new_customer(f"报表客户业务员-{tag}", businesser=f"业务员-{tag}")
    start, end = _iso(-10), _iso(0)
    try:
        resp = client.post(
            "/api/v1/sales-orders",
            json={
                "customer_id": customer_id,
                "order_date": _iso(-1),
                # 不传 order.businesser：报表应回退到客户档案的业务员
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 10.0}],
            },
        )
        assert resp.status_code == 201, resp.text

        payload = _report("salesman", date_from=start, date_to=end)
        row = _row(payload["rows"], f"业务员-{tag}")
        assert row and row["quantity"] == 3 and row["amount"] == 30.0
        assert row["share"] > 0
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_sales_return_is_netted_into_sales_reports():
    """退货按负数并入：卖 10 件退 3 件，报表必须显示净 7 件 / 净 ¥70。"""
    tag = _hex()
    product_id = _new_product(f"报表商品退货-{tag}")
    customer_id = _new_customer(f"报表客户退货-{tag}")
    start, end = _iso(-10), _iso(0)
    order = None
    ret = None
    try:
        order = _sale(customer_id, product_id, 10, 10.0, _iso(-5))
        ret = _return(customer_id, product_id, 3, 10.0, _iso(-2))

        payload = _report("product-sales-detail", date_from=start, date_to=end, keyword=f"报表商品退货-{tag}")
        assert payload["summary"]["total_quantity"] == 7
        assert payload["summary"]["total_amount"] == 70.0
        notes = [row["note"] for row in payload["rows"]]
        assert "退货冲减" in notes

        monthly = _report("product-sales-month", date_from=start, date_to=end)
        row = _row(monthly["rows"], f"报表商品退货-{tag}")
        assert row["quantity"] == 7
        assert row["amount"] == 70.0
    finally:
        if ret:
            client.delete(f"/api/v1/sales-returns/{ret['id']}")
        if order:
            client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_plain_sales_order_doc_type_is_excluded():
    """doc_type=order 是「只订货没发货」，不能进销售报表（与库存/财务同一口径）。"""
    tag = _hex()
    product_id = _new_product(f"报表商品订货-{tag}")
    customer_id = _new_customer(f"报表客户订货-{tag}")
    start, end = _iso(-10), _iso(0)
    order = None
    try:
        order = _sale(customer_id, product_id, 8, 10.0, _iso(-1), doc_type="order")

        payload = _report("product-sales-month", date_from=start, date_to=end, keyword=f"报表商品订货-{tag}")
        assert _row(payload["rows"], f"报表商品订货-{tag}") is None

        detail = _report("product-sales-detail", date_from=start, date_to=end, keyword=f"报表商品订货-{tag}")
        assert detail["rows"] == []
    finally:
        if order:
            client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_date_range_filter_excludes_other_periods():
    tag = _hex()
    product_id = _new_product(f"报表商品区间-{tag}")
    customer_id = _new_customer(f"报表客户区间-{tag}")
    order = None
    try:
        order = _sale(customer_id, product_id, 10, 10.0, "2020-03-15")

        inside = _report(
            "product-sales-month", date_from="2020-03-01", date_to="2020-03-31", keyword=f"报表商品区间-{tag}"
        )
        assert _row(inside["rows"], f"报表商品区间-{tag}") is not None

        outside = _report(
            "product-sales-month", date_from="2020-04-01", date_to="2020-04-30", keyword=f"报表商品区间-{tag}"
        )
        assert _row(outside["rows"], f"报表商品区间-{tag}") is None
    finally:
        if order:
            client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_dimension_and_period_can_be_overridden():
    """12 张报表共用一个引擎，因此粒度和维度都可以在页面上现切。"""
    payload = _report(
        "product-sales-month",
        date_from="2026-01-01",
        date_to="2026-12-31",
        dimension="category",
        period="quarter",
    )
    assert payload["report"]["dimension"] == "category"
    assert payload["report"]["period"] == "quarter"
    assert payload["buckets"] == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]

    bad = client.get(
        "/api/v1/reports/data/product-sales-month",
        params={"dimension": "warehouse"},
    )
    assert bad.status_code == 400


# ============================================================
# 四、收发存：期初 + 入 − 出 = 期末
# ============================================================
def test_inventory_flow_identity_holds():
    tag = _hex()
    product_id = _new_product(f"报表商品出入-{tag}")
    customer_id = _new_customer(f"报表客户出入-{tag}")
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    purchase = None
    order = None
    try:
        # 采购入库 30 → 销售出库 12 → 净 18
        resp = client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 30, "unit_price": 4.0}],
            },
        )
        assert resp.status_code == 201, resp.text
        purchase = resp.json()

        order = _sale(customer_id, product_id, 12, 10.0, _iso(-1), warehouse_id=warehouse_id)

        payload = _report(
            "inventory-flow",
            date_from="2000-01-01",
            date_to=_iso(1),
            warehouse_id=warehouse_id,
            keyword=f"报表商品出入-{tag}",
        )
        assert payload["shape"] == "flow"
        row = next(r for r in payload["rows"] if r["product_id"] == product_id)
        assert row["opening"] == 0
        assert row["inbound"] >= 30
        assert row["outbound"] >= 12
        # 恒等式：期初 + 入 − 出 = 期末
        assert row["closing"] == row["opening"] + row["inbound"] - row["outbound"]
        assert row["closing"] >= 18

        # 换个区间：把区间起点推到明天，今天发生的一切都变成期初
        future = _report(
            "inventory-flow",
            date_from=_iso(1),
            date_to=_iso(9),
            warehouse_id=warehouse_id,
            keyword=f"报表商品出入-{tag}",
        )
        future_row = next(r for r in future["rows"] if r["product_id"] == product_id)
        assert future_row["inbound"] == 0 and future_row["outbound"] == 0
        assert future_row["opening"] == future_row["closing"] == row["closing"]
    finally:
        if order:
            client.delete(f"/api/v1/sales-orders/{order['id']}")
        if purchase:
            client.delete(f"/api/v1/purchase-orders/{purchase['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


# ============================================================
# 五、老板报表
# ============================================================
def test_boss_report_has_all_blocks_and_consistent_margin():
    tag = _hex()
    product_id = _new_product(f"报表商品老板-{tag}", price=4.0, sale=10.0)
    customer_id = _new_customer(f"报表客户老板-{tag}")
    start, end = _iso(-10), _iso(0)
    order = None
    try:
        order = _sale(customer_id, product_id, 10, 10.0, _iso(-2))

        payload = _report("boss", date_from=start, date_to=end)
        assert payload["shape"] == "overview"

        titles = [group["title"] for group in payload["metric_groups"]]
        assert titles == ["经营成果", "资金占用"]

        summary = payload["summary"]
        # 自己造的这笔必须被算进去
        assert summary["revenue"] >= 100.0
        assert summary["cost"] >= 40.0
        assert summary["gross_profit"] == round(summary["revenue"] - summary["cost"], 2)
        assert summary["margin"] == round(summary["gross_profit"] / summary["revenue"] * 100, 2)
        assert summary["stock_value"] >= 0

        top_products = next(b for b in payload["highlights"] if b["title"] == "热销商品 Top5")
        assert len(top_products["rows"]) <= 5
        assert all(
            top_products["rows"][i]["amount"] >= top_products["rows"][i + 1]["amount"]
            for i in range(len(top_products["rows"]) - 1)
        ), "Top 榜必须按金额降序"
    finally:
        if order:
            client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ============================================================
# 六、CSV 导出（16 张全形态）
# ============================================================
def test_export_works_for_every_shape():
    cases = {
        "product-sales-month": "商品销售月报",
        "salesman": "销售员报表",
        "product-sales-detail": "商品销售明细表",
        "inventory-flow": "商品出入统计",
        "boss": "老板报表",
    }
    for key, title in cases.items():
        resp = client.get(f"/api/v1/reports/export/{key}", params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
        assert resp.status_code == 200, resp.text
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        assert resp.content.startswith("\ufeff".encode("utf-8")), "CSV 必须带 BOM，否则 Excel 打开中文乱码"
        body = resp.content.decode("utf-8-sig")
        assert body.splitlines()[0].startswith(title)


def test_export_unknown_report_404():
    resp = client.get("/api/v1/reports/export/nope")
    assert resp.status_code == 404


# ============================================================
# 七、只读性：报表不许碰库存与财务
# ============================================================
def test_reports_are_read_only():
    def counts() -> tuple[int, int]:
        from app.db.session import SessionLocal
        from app.models.finance import FinancialTransaction
        from app.models.inventory import InventoryTransaction

        db = SessionLocal()
        try:
            return (
                db.query(InventoryTransaction).count(),
                db.query(FinancialTransaction).count(),
            )
        finally:
            db.close()

    before = counts()
    for item in REPORT_CATALOG:
        # 不传日期：各报表用自己的默认区间（日报 30 天、月报 12 个月…），
        # 保证任何粒度都不会触发列数上限，走到真正的取数分支。
        assert client.get(f"/api/v1/reports/data/{item['key']}").status_code == 200
        assert client.get(f"/api/v1/reports/export/{item['key']}").status_code == 200
    after = counts()

    assert before == after, "报表是只读的：库存流水与财务流水条数必须一条不变"
