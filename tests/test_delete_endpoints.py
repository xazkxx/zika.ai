"""删除接口测试。

覆盖两类：
  1. 业务单据删除：销售订单（连带明细）、BOM（连带子树）、发票。
  2. 主数据档案删除：商品 / 客户 / 供应商。
     —— 未被业务数据引用时直接删除；已被引用时返回 409，需 force=true 才强删；
        另提供 {id}/references 预览接口与 /batch 批量删除接口。

每个测试先创建临时数据、删除后不留残留（删除本身就是测试目标）。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _new_customer(prefix: str = "CUST-DEL") -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"{prefix}-{uuid.uuid4().hex[:8]}", "name": "删除测试客户"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-{uuid.uuid4().hex[:8]}", "name": "删除测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-DEL-{uuid.uuid4().hex[:8]}", "name": "删除测试商品"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_sales_order(customer_id: int, product_id: int) -> int:
    resp = client.post(
        "/api/v1/sales-orders",
        json={
            "order_no": f"TEST-DEL-{uuid.uuid4().hex[:8]}",
            "customer_id": customer_id,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_purchase_order(supplier_id: int, product_id: int) -> int:
    resp = client.post(
        "/api/v1/purchase-orders",
        json={
            "order_no": f"TEST-DEL-{uuid.uuid4().hex[:8]}",
            "supplier_id": supplier_id,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


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

    # 删除（P0-5 起 = 作废）：204，单据**不再物理消失**
    deleted = client.delete(f"/api/v1/sales-orders/{order_id}")
    assert deleted.status_code == 204

    # 重复删除：幂等 204，不会二次冲账（旧契约是 404，已随 P0-5 改变）
    again = client.delete(f"/api/v1/sales-orders/{order_id}")
    assert again.status_code == 204

    # 单据与明细都还在，只是状态落成 cancelled —— 这才是"可追责"的删除
    listed = client.get("/api/v1/sales-orders", params={"page_size": 500}).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    matched = [row for row in rows if row["id"] == order_id]
    assert matched, "P0-5：作废后单据必须仍然可查"
    assert matched[0]["status"] == "cancelled"
    assert matched[0]["items"], "P0-5：明细也必须保留（作废不是删明细）"


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


# ============================================================================
# 主数据档案删除：商品 / 客户 / 供应商
# ============================================================================


def test_delete_unreferenced_customer_supplier_product():
    """录错的档案（没有任何业务引用）应当可以直接删除。"""
    customer_id = _new_customer()
    supplier_id = _new_supplier()
    product_id = _new_product()

    for kind, item_id in [("customers", customer_id), ("suppliers", supplier_id), ("products", product_id)]:
        assert client.delete(f"/api/v1/{kind}/{item_id}").status_code == 204
        # 已删除，再删一次应 404
        assert client.delete(f"/api/v1/{kind}/{item_id}").status_code == 404


def test_delete_customer_blocked_then_forced():
    """客户被销售单引用时必须先拦下（409），force=true 才允许强删。"""
    customer_id = _new_customer()
    product_id = _new_product()
    order_id = _new_sales_order(customer_id, product_id)

    # 1) references 接口能查到引用明细
    refs = client.get(f"/api/v1/customers/{customer_id}/references")
    assert refs.status_code == 200, refs.text
    sources = {row["source"] for row in refs.json()["references"]}
    assert "销售单" in sources, refs.text

    # 2) 直接删 → 409，且提示里点名了销售单
    blocked = client.delete(f"/api/v1/customers/{customer_id}")
    assert blocked.status_code == 409, blocked.text
    assert "销售单" in blocked.json()["detail"]

    # 3) 档案仍在
    assert client.get(f"/api/v1/customers/{customer_id}/references").status_code == 200

    # 4) force=true 强删 → 204，且只删档案不动单据
    forced = client.delete(f"/api/v1/customers/{customer_id}?force=true")
    assert forced.status_code == 204, forced.text
    assert client.delete(f"/api/v1/customers/{customer_id}").status_code == 404

    # 收拾：单据仍存在，测试自己删掉，避免留残留
    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204


def test_delete_supplier_blocked_then_forced():
    """供应商被采购单引用时同样先 409。"""
    supplier_id = _new_supplier()
    product_id = _new_product()
    order_id = _new_purchase_order(supplier_id, product_id)

    blocked = client.delete(f"/api/v1/suppliers/{supplier_id}")
    assert blocked.status_code == 409, blocked.text
    assert "采购单" in blocked.json()["detail"]

    forced = client.delete(f"/api/v1/suppliers/{supplier_id}?force=true")
    assert forced.status_code == 204, forced.text
    assert client.delete(f"/api/v1/suppliers/{supplier_id}").status_code == 404

    # 采购单没有删除接口，交给 conftest 的孤儿清理收尾（供应商已不存在）
    assert order_id  # 保留引用，避免 linter 报未使用


def test_delete_product_blocked_when_referenced():
    """商品被销售单明细引用时也要拦下。"""
    customer_id = _new_customer()
    product_id = _new_product()
    order_id = _new_sales_order(customer_id, product_id)

    refs = client.get(f"/api/v1/products/{product_id}/references")
    assert refs.status_code == 200, refs.text
    sources = {row["source"] for row in refs.json()["references"]}
    assert "销售单明细" in sources, refs.text

    blocked = client.delete(f"/api/v1/products/{product_id}")
    assert blocked.status_code == 409, blocked.text
    assert "销售单明细" in blocked.json()["detail"]

    assert client.delete(f"/api/v1/products/{product_id}?force=true").status_code == 204
    # 商品删了，单据还在（明细里保存了商品名快照）
    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204


def test_archive_batch_delete_splits_deleted_and_blocked():
    """批量删除：能删的删掉，被引用的单独列出来，不因为一条受阻就整批失败。"""
    free_product = _new_product()
    customer_id = _new_customer()
    locked_product = _new_product()
    order_id = _new_sales_order(customer_id, locked_product)

    resp = client.request(
        "DELETE",
        "/api/v1/products/batch",
        json={"ids": [free_product, locked_product, 99999999]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] == 1
    assert body["blocked_count"] == 1
    assert body["not_found"] == [99999999]
    assert body["deleted"][0]["id"] == free_product
    assert body["blocked"][0]["id"] == locked_product

    # 被引用的那个还在
    assert client.get(f"/api/v1/products/{locked_product}/references").status_code == 200

    # 批量强删可以一次清掉
    resp2 = client.request(
        "DELETE", "/api/v1/products/batch?force=true", json={"ids": [locked_product]}
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["deleted_count"] == 1

    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204


def test_archive_batch_rejects_bad_payload():
    """批量删除的请求体格式错误要给出 400，而不是 500。"""
    assert client.request("DELETE", "/api/v1/products/batch", json={"ids": "not-a-list"}).status_code == 400
    assert client.request("DELETE", "/api/v1/customers/batch", json={"ids": ["abc"]}).status_code == 400


def test_archive_delete_nonexistent_ids():
    """不存在的档案：单个删返回 404，批量删归入 not_found。"""
    assert client.delete("/api/v1/products/99999999").status_code == 404
    assert client.delete("/api/v1/customers/99999999").status_code == 404
    assert client.delete("/api/v1/suppliers/99999999").status_code == 404
    assert client.get("/api/v1/products/99999999/references").status_code == 404

    resp = client.request("DELETE", "/api/v1/suppliers/batch", json={"ids": [99999999]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["not_found"] == [99999999]
    assert resp.json()["deleted_count"] == 0
