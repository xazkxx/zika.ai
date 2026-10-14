"""仓库档案管理接口回归测试（第 1 批 · 基础资料 → 仓库档案）。

背景：`warehouses` 表与 `/warehouses` 的增删改查早已存在（库存模块的底座），
但菜单一直挂 `todo` 待建、也没有删除与引用检查。本次补齐后：
- 前端有了「仓库档案」页（列表 + 新增 / 编辑 / 删除）；
- 后端补 `DELETE /warehouses/{id}`、`DELETE /warehouses/batch`、
  `GET /warehouses/{id}/references`，口径与客户 / 供应商 / 商品三张档案完全一致：
  被业务数据引用时返回 409，带 `force=true` 才允许强删。

测试数据遵守 `scripts/clean_test_data.py` 的仓库清理签名
（编码 `WH-<8位hex>`，名称以「主仓库 / 一号仓 / 停用仓 / 主仓」开头），
跑完由 conftest 自动清理，不污染正式库。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _uniq_code() -> str:
    return f"WH-{uuid.uuid4().hex[:8]}"


def _new_warehouse(name: str = "主仓库-测试", **overrides) -> dict:
    payload = {"code": _uniq_code(), "name": name}
    payload.update(overrides)
    resp = client.post("/api/v1/warehouses", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-WH-{uuid.uuid4().hex[:8]}", "name": "仓库引用测试客户"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-WH-{uuid.uuid4().hex[:8]}", "name": "仓库引用测试商品"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_sales_order(customer_id: int, product_id: int, warehouse_id: int) -> int:
    resp = client.post(
        "/api/v1/sales-orders",
        json={
            "order_no": f"TEST-WH-{uuid.uuid4().hex[:8]}",
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------- 增删改查 ----------


def test_warehouse_lifecycle_crud():
    code = _uniq_code()
    created = client.post(
        "/api/v1/warehouses",
        json={
            "code": code,
            "name": "主仓库-生命周期",
            "location": "A区01号位",
            "manager": "张三",
            "phone": "13800000000",
            "note": "回归测试",
        },
    )
    assert created.status_code == 201, created.text
    warehouse_id = created.json()["id"]
    assert created.json()["is_active"] is True

    # 列表里能看到新建的仓库
    listed = client.get("/api/v1/warehouses", params={"limit": 500})
    assert listed.status_code == 200, listed.text
    assert any(row["id"] == warehouse_id for row in listed.json())

    # 编辑：改名 / 换货位 / 停用
    patched = client.patch(
        f"/api/v1/warehouses/{warehouse_id}",
        json={
            "code": code,
            "name": "主仓库-改名后",
            "location": "B区02号位",
            "manager": "李四",
            "phone": "13900000000",
            "is_active": False,
            "note": "已停用",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "主仓库-改名后"
    assert body["location"] == "B区02号位"
    assert body["is_active"] is False

    # 编码撞到别的仓库 → 400
    other = _new_warehouse("一号仓-占位")
    dup = client.patch(
        f"/api/v1/warehouses/{warehouse_id}",
        json={"code": other["code"], "name": "主仓库-改名后"},
    )
    assert dup.status_code == 400, dup.text
    assert "already exists" in dup.json()["detail"]

    # 未启用的仓库不应出现在 only_active 列表
    active_only = client.get("/api/v1/warehouses", params={"only_active": True, "limit": 500})
    assert active_only.status_code == 200
    assert all(row["id"] != warehouse_id for row in active_only.json())

    # 删除：204；再删 404
    assert client.delete(f"/api/v1/warehouses/{warehouse_id}").status_code == 204
    assert client.delete(f"/api/v1/warehouses/{warehouse_id}").status_code == 404
    assert client.delete(f"/api/v1/warehouses/{other['id']}").status_code == 204


def test_warehouse_missing_ids_return_404():
    assert client.delete("/api/v1/warehouses/99999999").status_code == 404
    assert client.get("/api/v1/warehouses/99999999/references").status_code == 404
    assert (
        client.patch(
            "/api/v1/warehouses/99999999", json={"code": "WH-00000000", "name": "不存在"}
        ).status_code
        == 404
    )


# ---------- 引用检查与删除保护 ----------


def test_warehouse_references_empty_when_unused():
    warehouse = _new_warehouse("主仓库-无引用")
    refs = client.get(f"/api/v1/warehouses/{warehouse['id']}/references")
    assert refs.status_code == 200, refs.text
    assert refs.json()["references"] == []
    assert client.delete(f"/api/v1/warehouses/{warehouse['id']}").status_code == 204


def test_warehouse_delete_blocked_then_forced():
    """仓库被销售单引用时删除要拦下（409），force=true 才允许强删。"""
    warehouse = _new_warehouse("主仓库-被引用")
    warehouse_id = warehouse["id"]
    customer_id = _new_customer()
    product_id = _new_product()
    order_id = _new_sales_order(customer_id, product_id, warehouse_id)

    # 引用清单里应点名销售单
    refs = client.get(f"/api/v1/warehouses/{warehouse_id}/references")
    assert refs.status_code == 200, refs.text
    sources = {row["source"] for row in refs.json()["references"]}
    assert "销售单" in sources, refs.text

    # 直接删 → 409，提示里点名销售单
    blocked = client.delete(f"/api/v1/warehouses/{warehouse_id}")
    assert blocked.status_code == 409, blocked.text
    assert "销售单" in blocked.json()["detail"]

    # 档案仍在
    assert client.get(f"/api/v1/warehouses/{warehouse_id}").status_code == 200

    # force=true 强删 → 204，且不动单据
    forced = client.delete(f"/api/v1/warehouses/{warehouse_id}?force=true")
    assert forced.status_code == 204, forced.text
    assert client.delete(f"/api/v1/warehouses/{warehouse_id}").status_code == 404

    # 收拾现场：单据仍在，测试自己删掉
    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204
    client.delete(f"/api/v1/customers/{customer_id}")
    client.delete(f"/api/v1/products/{product_id}")


def test_warehouse_batch_delete_splits_deleted_and_blocked():
    free_id = _new_warehouse("主仓库-批量可删")["id"]
    locked_id = _new_warehouse("主仓库-批量受限")["id"]
    customer_id = _new_customer()
    product_id = _new_product()
    order_id = _new_sales_order(customer_id, product_id, locked_id)

    resp = client.request(
        "DELETE",
        "/api/v1/warehouses/batch",
        json={"ids": [free_id, locked_id, 99999999]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] == 1
    assert body["blocked_count"] == 1
    assert body["not_found"] == [99999999]
    assert body["deleted"][0]["id"] == free_id
    assert body["blocked"][0]["id"] == locked_id

    # 被引用的那个还在
    assert client.get(f"/api/v1/warehouses/{locked_id}/references").status_code == 200

    # 批量强删可一次清掉
    resp2 = client.request(
        "DELETE", "/api/v1/warehouses/batch?force=true", json={"ids": [locked_id]}
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["deleted_count"] == 1

    # 请求体格式错误要给出 400，而不是 500
    assert (
        client.request("DELETE", "/api/v1/warehouses/batch", json={"ids": "not-a-list"}).status_code
        == 400
    )

    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204
    client.delete(f"/api/v1/customers/{customer_id}")
    client.delete(f"/api/v1/products/{product_id}")
