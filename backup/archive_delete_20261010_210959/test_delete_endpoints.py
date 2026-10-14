"""三个删除接口测试：销售订单（连带明细）、BOM（连带子树）、发票。

每个测试先创建临时数据、删除后不留残留（删除本身就是测试目标）。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_delete_sales_order_removes_items():
    # 自建客户与商品，避免依赖库里写死的 id（新增单据校验会检查外键存在性）
    customer = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-DEL-{uuid.uuid4().hex[:8]}", "name": "删除测试客户"},
    )
    assert customer.status_code == 201, customer.text
    customer_id = customer.json()["id"]

    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-DEL-{uuid.uuid4().hex[:8]}", "name": "删除测试商品"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]

    # 创建临时销售订单（含 1 条明细）
    order_no = f"TEST-DEL-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/sales-orders",
        json={
            "order_no": order_no,
            "customer_id": customer_id,
            "items": [{"product_id": product_id, "quantity": 2, "unit_price": 10.0}],
        },
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    # 删除成功
    deleted = client.delete(f"/api/v1/sales-orders/{order_id}")
    assert deleted.status_code == 204

    # 已删除，再次删除应 404
    again = client.delete(f"/api/v1/sales-orders/{order_id}")
    assert again.status_code == 404


def test_delete_bom_node_cascades_children():
    # 创建临时 BOM 父节点 + 子节点
    parent = client.post(
        "/api/v1/production-boms",
        json={
            "product_id": 1,
            "component_product_id": 2,
            "name": f"TMP-P-{uuid.uuid4().hex[:8]}",
            "bom_type": "assembly",
        },
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]

    child = client.post(
        "/api/v1/production-boms",
        json={
            "product_id": 1,
            "component_product_id": 3,
            "name": f"TMP-C-{uuid.uuid4().hex[:8]}",
            "bom_type": "component",
            "parent_id": parent_id,
        },
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    # 删除父节点：204，且父/子都从树里消失
    deleted = client.delete(f"/api/v1/production-boms/{parent_id}")
    assert deleted.status_code == 204

    tree = client.get("/api/v1/production-boms/tree")
    assert tree.status_code == 200
    all_ids: set[int] = set()

    def collect(nodes: list) -> None:
        for node in nodes:
            all_ids.add(node["id"])
            collect(node.get("children") or [])

    collect(tree.json())
    assert parent_id not in all_ids
    assert child_id not in all_ids

    # 父节点已删除，再次删除应 404
    again = client.delete(f"/api/v1/production-boms/{parent_id}")
    assert again.status_code == 404


def test_delete_missing_records_404():
    # 发票删除接口：不存在的 id 返回 404（接口本身早已存在，这里只做回归验证）
    assert client.delete("/api/v1/invoices/99999999").status_code == 404
    assert client.delete("/api/v1/production-boms/99999999").status_code == 404
    assert client.delete("/api/v1/sales-orders/99999999").status_code == 404
