"""采购/销售订单（doc_type=order）与一键转单回归测试（第 1 批 · 收尾）。

背景：订单和出入库单此前共用一张表且行为完全相同（立即写库存+财务），
浩技云样板里它们是两个页面。本次给 `purchase_orders / sales_orders` 加
`doc_type` 判别字段：
- order    = 订单：只确认订货意向，不动库存、不写财务、不产生欠款；
- inbound / outbound = 出入库单（历史数据默认值）：原有行为原样保留。

新增接口：
- POST /purchase-orders/{id}/to-inbound  订单→入库单（写库存+应付）
- POST /sales-orders/{id}/to-outbound    订单→开单（写库存+应收）
- PATCH /purchase-orders/{id}/status、DELETE /purchase-orders/{id}（采购侧补齐）
- 列表 ?doc_type= 过滤

测试数据遵守 scripts/clean_test_data.py 的编码签名
（SKU-/CUST-/SUP- + 8位hex），跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试商品", "purchase_price": 5.0, "sale_price": 9.0},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试客户"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _inventory_rows_for(related_type: str, related_order_id: int) -> list[dict]:
    resp = client.get("/api/v1/inventory")
    assert resp.status_code == 200, resp.text
    return [
        row
        for row in resp.json()
        if row.get("related_type") == related_type and row.get("related_order_id") == related_order_id
    ]


def _finance_rows_for(related_type: str, related_order_id: int) -> list[dict]:
    resp = client.get("/api/v1/finance")
    assert resp.status_code == 200, resp.text
    return [
        row
        for row in resp.json()
        if row.get("related_type") == related_type and row.get("related_order_id") == related_order_id
    ]


# ---------- 创建：订单 vs 出入库单 ----------


def test_create_purchase_order_does_not_touch_stock_or_finance():
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        resp = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 5.0}],
                "note": "订单测试-不进货",
            },
        )
        assert resp.status_code == 201, resp.text
        order = resp.json()
        # 单号前缀 CGD、性质 order
        assert order["order_no"].startswith("CGD"), order["order_no"]
        assert order["doc_type"] == "order"
        # 订单不产生欠款与付款
        assert order["current_debt"] == 0.0
        assert order["paid_amount"] == 0.0
        assert order["total_amount"] == 15.0
        # 不写库存流水、不写财务流水
        assert _inventory_rows_for("purchase_in", order["id"]) == []
        assert _finance_rows_for("purchase_in", order["id"]) == []
    finally:
        client.delete(f"/api/v1/purchase-orders/{order['id']}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_sales_order_does_not_touch_stock_or_finance():
    product_id = _new_product()
    customer_id = _new_customer()
    try:
        resp = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "order",
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 9.0}],
            },
        )
        assert resp.status_code == 201, resp.text
        order = resp.json()
        assert order["order_no"].startswith("XSD"), order["order_no"]
        assert order["doc_type"] == "order"
        assert order["current_debt"] == 0.0
        assert order["received_amount"] == 0.0
        assert _inventory_rows_for("sales_out", order["id"]) == []
        assert _finance_rows_for("sales_out", order["id"]) == []
    finally:
        client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_legacy_create_defaults_to_inbound_and_outbound():
    """不传 doc_type 的旧调用方必须保持原行为：入库/出库 + 库存 + 财务。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    try:
        po = client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 5.0}],
            },
        )
        assert po.status_code == 201, po.text
        purchase = po.json()
        assert purchase["doc_type"] == "inbound"
        assert purchase["order_no"].startswith("CG"), purchase["order_no"]
        assert len(_inventory_rows_for("purchase_in", purchase["id"])) == 1
        assert len(_finance_rows_for("purchase_in", purchase["id"])) >= 1

        so = client.post(
            "/api/v1/sales-orders",
            json={
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 9.0}],
            },
        )
        assert so.status_code == 201, so.text
        sales = so.json()
        assert sales["doc_type"] == "outbound"
        assert sales["order_no"].startswith("XS"), sales["order_no"]
        assert len(_inventory_rows_for("sales_out", sales["id"])) == 1

        # 列表 doc_type 过滤
        orders = client.get("/api/v1/purchase-orders", params={"doc_type": "order"}).json()
        assert all(row["doc_type"] == "order" for row in orders)
    finally:
        client.delete(f"/api/v1/purchase-orders/{purchase['id']}")
        client.delete(f"/api/v1/sales-orders/{sales['id']}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_invalid_doc_type_rejected():
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    try:
        assert (
            client.post(
                "/api/v1/purchase-orders",
                json={"doc_type": "nonsense", "supplier_id": supplier_id, "items": []},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/v1/sales-orders",
                json={"doc_type": "nonsense", "customer_id": customer_id, "items": []},
            ).status_code
            == 400
        )
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


# ---------- 一键转单 ----------


def test_purchase_order_to_inbound_full_chain():
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        order = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 6, "unit_price": 5.0}],
                "note": "转单链路测试",
            },
        ).json()

        resp = client.post(f"/api/v1/purchase-orders/{order['id']}/to-inbound")
        assert resp.status_code == 200, resp.text
        inbound = resp.json()
        # 生成的是入库单：CG 前缀、回指来源订单、复制明细
        assert inbound["doc_type"] == "inbound"
        assert inbound["order_no"].startswith("CG"), inbound["order_no"]
        assert inbound["source_order_id"] == order["id"]
        assert inbound["items"][0]["quantity"] == 6
        assert inbound["total_amount"] == 30.0
        # 库存与应付流水都挂在**入库单**上
        assert len(_inventory_rows_for("purchase_in", inbound["id"])) == 1
        assert len(_finance_rows_for("purchase_in", inbound["id"])) >= 1
        # 订单本身仍不产生流水
        assert _inventory_rows_for("purchase_in", order["id"]) == []

        # 订单状态置 completed，重复转单 409
        detail = client.get("/api/v1/purchase-orders", params={"doc_type": "order"}).json()
        target = next(row for row in detail if row["id"] == order["id"])
        assert target["status"] == "completed"
        again = client.post(f"/api/v1/purchase-orders/{order['id']}/to-inbound")
        assert again.status_code == 409, again.text

        # 已转单订单不能直接删
        blocked = client.delete(f"/api/v1/purchase-orders/{order['id']}")
        assert blocked.status_code == 409, blocked.text

        # 非订单类型不能转单
        assert client.post(f"/api/v1/purchase-orders/{inbound['id']}/to-inbound").status_code == 400

        # 收拾现场：先删入库单（冲销流水），再删订单
        assert client.delete(f"/api/v1/purchase-orders/{inbound['id']}").status_code == 204
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204
        # 冲销后流水清零
        assert _inventory_rows_for("purchase_in", inbound["id"]) == []
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_sales_order_to_outbound_full_chain():
    product_id = _new_product()
    customer_id = _new_customer()
    try:
        order = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "order",
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 9.0}],
            },
        ).json()

        resp = client.post(f"/api/v1/sales-orders/{order['id']}/to-outbound")
        assert resp.status_code == 200, resp.text
        outbound = resp.json()
        assert outbound["doc_type"] == "outbound"
        assert outbound["order_no"].startswith("XS"), outbound["order_no"]
        assert outbound["source_order_id"] == order["id"]
        assert outbound["total_amount"] == 27.0
        assert len(_inventory_rows_for("sales_out", outbound["id"])) == 1
        assert len(_finance_rows_for("sales_out", outbound["id"])) >= 1
        assert _inventory_rows_for("sales_out", order["id"]) == []

        assert client.post(f"/api/v1/sales-orders/{order['id']}/to-outbound").status_code == 409
        assert client.delete(f"/api/v1/sales-orders/{order['id']}").status_code == 409

        assert client.delete(f"/api/v1/sales-orders/{outbound['id']}").status_code == 204
        assert client.delete(f"/api/v1/sales-orders/{order['id']}").status_code == 204
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_purchase_order_status_and_plain_order_delete():
    """未转单的订单可以直接删；补齐的 PATCH status 可用。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        order = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 5.0}],
            },
        ).json()
        patched = client.patch(
            f"/api/v1/purchase-orders/{order['id']}/status", json={"status": "cancelled"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["status"] == "cancelled"
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 404
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")
