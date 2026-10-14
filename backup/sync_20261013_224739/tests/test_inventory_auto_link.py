"""库存联动测试：开单自动加减库存、删单回滚、现存量查询、上下限预警。

改造前库存是「死」的 —— 开单不扣库存，现存量靠 alerts 里写死的 15/20 猜。
这里逐条验证新的联动链路：

  1. 采购单入库 → 现存量增加
  2. 销售单出库 → 现存量减少
  3. 库存不足不阻断开单（允许负库存），但被标为「缺货」
  4. 删除销售单 → 冲销出库流水，库存还原
  5. 多仓库互不串账
  6. 单据没填仓库时回退到默认仓库
  7. 现存量接口按仓库 / 商品筛选 + 汇总
  8. 上下限决定预警状态（低于下限 / 高于上限）
  9. 库存流水带得出源单号
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _new_warehouse() -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-{uuid.uuid4().hex[:8]}", "name": "主仓库-测试", "is_active": True},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_product(**overrides) -> int:
    payload = {"sku": f"SKU-INV-{uuid.uuid4().hex[:8]}", "name": "测试商品-库存"}
    payload.update(overrides)
    resp = client.post("/api/v1/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-{uuid.uuid4().hex[:8]}", "name": "测试供应商-库存"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-DEL-{uuid.uuid4().hex[:8]}", "name": "测试客户-库存"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _purchase(supplier_id: int, product_id: int, quantity: int, warehouse_id=None) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 10.0}],
    }
    if warehouse_id is not None:
        payload["warehouse_id"] = warehouse_id
    resp = client.post("/api/v1/purchase-orders", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sale(customer_id: int, product_id: int, quantity: int, warehouse_id=None) -> dict:
    payload = {
        "customer_id": customer_id,
        "items": [{"product_id": product_id, "quantity": quantity, "unit_price": 20.0}],
    }
    if warehouse_id is not None:
        payload["warehouse_id"] = warehouse_id
    resp = client.post("/api/v1/sales-orders", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stock_row(product_id: int, warehouse_id: int) -> dict:
    resp = client.get("/api/v1/inventory/stock", params={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    for row in resp.json()["rows"]:
        if row["warehouse_id"] == warehouse_id:
            return row
    raise AssertionError(f"现存量里没有 商品{product_id} × 仓库{warehouse_id}")


def test_purchase_order_increases_stock():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product(purchase_price=12.5)

    _purchase(supplier_id, product_id, 30, warehouse_id)

    row = _stock_row(product_id, warehouse_id)
    assert row["quantity"] == 30
    assert row["sku"] is not None
    assert row["product_name"] == "测试商品-库存"


def test_sales_order_decreases_stock():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    product_id = _new_product()

    _purchase(supplier_id, product_id, 30, warehouse_id)
    _sale(customer_id, product_id, 12, warehouse_id)

    assert _stock_row(product_id, warehouse_id)["quantity"] == 18


def test_negative_stock_is_allowed_but_flagged():
    """库存不足不阻断开单，但一定要标出来 —— 不能悄悄欠货。"""
    warehouse_id = _new_warehouse()
    customer_id = _new_customer()
    product_id = _new_product()

    resp = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "items": [{"product_id": product_id, "quantity": 5, "unit_price": 20.0}],
        },
    )
    assert resp.status_code == 201, "没有库存时开单不应被阻断"

    row = _stock_row(product_id, warehouse_id)
    assert row["quantity"] == -5
    assert row["status"] == "shortage"

    alerts = client.get("/api/v1/inventory/alerts").json()
    mine = [a for a in alerts if a["product_id"] == product_id]
    assert mine and mine[0]["status"] == "shortage"
    assert mine[0]["label"] == "缺货"


def test_delete_sales_order_reverts_stock():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    product_id = _new_product()

    _purchase(supplier_id, product_id, 30, warehouse_id)
    sale = _sale(customer_id, product_id, 8, warehouse_id)
    assert _stock_row(product_id, warehouse_id)["quantity"] == 22

    assert client.delete(f"/api/v1/sales-orders/{sale['id']}").status_code == 204

    # 单没了，货得还回来，否则库存永远对不上
    assert _stock_row(product_id, warehouse_id)["quantity"] == 30


def test_delete_sales_order_reverts_finance():
    """删销售开单要把产生的应收流水一并冲销，不能留下指向已删单据的孤儿。"""
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    product_id = _new_product()

    _purchase(supplier_id, product_id, 30, warehouse_id)
    sale = _sale(customer_id, product_id, 8, warehouse_id)

    def _rows():
        return [
            f for f in client.get("/api/v1/finance").json()
            if f.get("related_type") == "sales_out" and f.get("related_order_id") == sale["id"]
        ]

    assert _rows(), "销售开单应产生应收流水"

    assert client.delete(f"/api/v1/sales-orders/{sale['id']}").status_code == 204

    assert _rows() == [], "删销售开单后不应再有指向它的应收流水"


def test_delete_purchase_order_reverts_finance():
    """删采购入库单要把产生的应付流水一并冲销，不能留下指向已删单据的孤儿。"""
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product()

    order = _purchase(supplier_id, product_id, 20, warehouse_id)

    def _rows():
        return [
            f for f in client.get("/api/v1/finance").json()
            if f.get("related_type") == "purchase_in" and f.get("related_order_id") == order["id"]
        ]

    assert _rows(), "采购入库应产生应付流水"

    assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204

    assert _rows() == [], "删采购入库单后不应再有指向它的应付流水"


def test_multi_warehouse_isolation():
    w1 = _new_warehouse()
    w2 = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product()

    _purchase(supplier_id, product_id, 10, w1)
    _purchase(supplier_id, product_id, 25, w2)

    assert _stock_row(product_id, w1)["quantity"] == 10
    assert _stock_row(product_id, w2)["quantity"] == 25

    # 按仓库筛选只出该仓库的行
    filtered = client.get("/api/v1/inventory/stock", params={"warehouse_id": w1}).json()
    assert all(row["warehouse_id"] == w1 for row in filtered["rows"])
    assert sum(row["quantity"] for row in filtered["rows"]) >= 10


def test_stock_falls_back_to_default_warehouse():
    """单据没填仓库时，货不能凭空消失 —— 应落到默认仓库上并回填到单据。"""
    _new_warehouse()  # 保证系统里至少有一个启用仓库
    supplier_id = _new_supplier()
    product_id = _new_product()

    body = _purchase(supplier_id, product_id, 7)
    assert body["warehouse_id"] is not None, "单据上的仓库应被回填，否则流水与单据对不上"

    summary = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()["summary"]
    assert summary["total_quantity"] == 7


def test_stock_status_follows_product_limits():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product(stock_lower=10, stock_upper=100)

    _purchase(supplier_id, product_id, 5, warehouse_id)
    row = _stock_row(product_id, warehouse_id)
    assert row["status"] == "low_stock", "低于下限应报低库存"
    assert row["stock_lower"] == 10
    assert row["stock_upper"] == 100

    _purchase(supplier_id, product_id, 200, warehouse_id)
    row = _stock_row(product_id, warehouse_id)
    assert row["quantity"] == 205
    assert row["status"] == "overstock", "高于上限应报积压"

    alerts = {a["product_id"]: a for a in client.get("/api/v1/inventory/alerts").json()}
    assert alerts[product_id]["status"] == "overstock"

    # 积压的商品不该出现在补货建议里
    recs = client.get("/api/v1/purchase/recommendations").json()
    assert all(r["product_id"] != product_id for r in recs), "积压商品不该被建议继续采购"


def test_product_without_limits_is_not_nagged():
    """没设上下限的商品，库存为 0 不该被反复预警（只有负库存才报）。"""
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    product_id = _new_product()

    _purchase(supplier_id, product_id, 10, warehouse_id)
    _sale(customer_id, product_id, 10, warehouse_id)

    row = _stock_row(product_id, warehouse_id)
    assert row["quantity"] == 0
    assert row["status"] == "normal", "没设下限时库存为 0 属于正常，不打扰用户"

    alerts = [a for a in client.get("/api/v1/inventory/alerts").json() if a["product_id"] == product_id]
    assert alerts == []


def test_inventory_transaction_carries_source_doc():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product()

    body = _purchase(supplier_id, product_id, 4, warehouse_id)

    txns = client.get("/api/v1/inventory", params={"limit": 0}).json()
    mine = [t for t in txns if t["product_id"] == product_id and t["warehouse_id"] == warehouse_id]
    assert mine, "应该产生了库存流水"
    assert mine[0]["related_type"] == "purchase_in"
    assert mine[0]["related_order_id"] == body["id"]
    assert mine[0]["doc_no"] == body["order_no"], "流水要记得住来源单号，否则对账说不清"


def test_stock_summary_and_abnormal_filter():
    warehouse_id = _new_warehouse()
    supplier_id = _new_supplier()
    product_id = _new_product(stock_lower=100, purchase_price=2.0)

    _purchase(supplier_id, product_id, 3, warehouse_id)

    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    assert data["summary"]["total_quantity"] == 3
    assert data["summary"]["low_stock_count"] == 1
    assert data["summary"]["estimated_value"] == 6.0  # 3 × 2.0

    abnormal = client.get(
        "/api/v1/inventory/stock", params={"product_id": product_id, "only_abnormal": True}
    ).json()
    assert len(abnormal["rows"]) == 1
    assert abnormal["rows"][0]["status"] == "low_stock"

    overall = client.get("/api/v1/inventory/summary").json()
    assert overall["stock_lines"] >= 1
    assert "estimated_value" in overall
