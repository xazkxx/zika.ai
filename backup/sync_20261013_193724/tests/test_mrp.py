"""MRP 运算（第 3 批 · 生产类第 2 个模块）回归测试。

MRP 不是单据，是**计算引擎**：把"要生产多少成品"按 BOM 逐层展开成"需要多少
原材料"，再拿现存量一减，得出每种物料的**净需求（缺料）**。

运算本身不写任何单据、不动库存财务 —— 测试同时验证这一点。

测试数据遵守 scripts/clean_test_data.py 的规则：商品名含「测试商品」、
商品编码用 SKU-<组>-<8位hex>，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _new_product(name: str, price: float = 10.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-MRP-{uuid.uuid4().hex[:8]}",
            "name": name,
            "purchase_price": price,
            "sale_price": price * 2,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "MRP测试仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-MRP-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _new_bom(parent_id: int, component_id: int, quantity: int = 1) -> int:
    resp = client.post(
        "/api/v1/production-boms",
        json={
            "product_id": parent_id,
            "component_product_id": component_id,
            "quantity": quantity,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_stock(product_id: int, warehouse_id: int, qty: int) -> None:
    resp = client.post(
        "/api/v1/inventory",
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "transaction_type": "inbound",
            "quantity": qty,
            "unit_price": 1.0,
        },
    )
    assert resp.status_code == 201, resp.text


def _row_of(result: dict, product_id: int) -> dict | None:
    return next((row for row in result["rows"] if row["product_id"] == product_id), None)


# ---------- 单层 BOM ----------


def test_mrp_single_level_explosion():
    """成品 A 由 原料 X×3 组成，库存不足时算出净需求。"""
    product = _new_product("MRP测试商品成品", 100.0)
    material = _new_product("MRP测试商品原料", 4.0)
    wh = _new_warehouse()
    bom_id = _new_bom(product, material, 3)
    try:
        _seed_stock(material, wh, 20)  # 有 20，需要 30，缺 10

        resp = client.get(
            "/api/v1/mrp/requirements", params={"product_id": product, "quantity": 10}
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()

        assert result["levels"] == 2
        top = _row_of(result, product)
        assert top is not None and top["is_product"] is True
        assert top["level"] == 0
        assert top["gross_quantity"] == 10
        assert top["net_quantity"] == 0, "顶层成品是产出，不做缺料判定"

        mat = _row_of(result, material)
        assert mat is not None
        assert mat["level"] == 1
        assert mat["gross_quantity"] == 30, "毛需求 = 成品数 × 单位用量"
        assert mat["on_hand"] == 20
        assert mat["net_quantity"] == 10, "净需求 = 毛需求 - 现存量"
        assert mat["status"] == "partial"
        assert mat["amount"] == 40.0, "缺料金额 = 净需求 × 参考进价"

        assert result["summary"]["shortage_lines"] == 1
        assert result["summary"]["shortage_quantity"] == 10
        assert result["summary"]["shortage_amount"] == 40.0
    finally:
        client.delete(f"/api/v1/production-boms/{bom_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product}")
        client.delete(f"/api/v1/products/{material}")


def test_mrp_sufficient_stock_has_no_shortage():
    product = _new_product("MRP测试商品成品", 100.0)
    material = _new_product("MRP测试商品原料", 4.0)
    wh = _new_warehouse()
    bom_id = _new_bom(product, material, 2)
    try:
        _seed_stock(material, wh, 100)  # 需要 20，远够

        result = client.get(
            "/api/v1/mrp/requirements", params={"product_id": product, "quantity": 10}
        ).json()
        mat = _row_of(result, material)
        assert mat["net_quantity"] == 0
        assert mat["status"] == "sufficient"
        assert result["summary"]["shortage_lines"] == 0
    finally:
        client.delete(f"/api/v1/production-boms/{bom_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product}")
        client.delete(f"/api/v1/products/{material}")


# ---------- 多层 BOM ----------


def test_mrp_multi_level_explosion():
    """成品 A ← 半成品 B×2 + 原料 D×1；半成品 B ← 原料 C×3。

    A×10 展开后：B 毛需求 20、D 毛需求 10、C 毛需求 60（B 再放大 3 倍）。
    """
    a = _new_product("MRP测试商品成品A", 100.0)
    b = _new_product("MRP测试商品半成品B", 30.0)
    c = _new_product("MRP测试商品原料C", 5.0)
    d = _new_product("MRP测试商品原料D", 2.0)
    wh = _new_warehouse()
    bom_a = _new_bom(a, b, 2)
    bom_a2 = _new_bom(a, d, 1)
    bom_b = _new_bom(b, c, 3)
    try:
        _seed_stock(b, wh, 5)  # B 有 5，需要 20 → 缺 15
        _seed_stock(d, wh, 100)  # D 足够

        result = client.get(
            "/api/v1/mrp/requirements", params={"product_id": a, "quantity": 10}
        ).json()

        assert result["levels"] == 3, "A(0) → B/D(1) → C(2)"
        row_b = _row_of(result, b)
        row_c = _row_of(result, c)
        row_d = _row_of(result, d)

        assert row_b["level"] == 1 and row_b["gross_quantity"] == 20
        assert row_b["net_quantity"] == 15
        assert row_d["level"] == 1 and row_d["gross_quantity"] == 10 and row_d["net_quantity"] == 0
        assert row_c["level"] == 2, "C 在第二层"
        assert row_c["gross_quantity"] == 60, "C 毛需求 = B 毛需求 20 × 3"
        assert row_c["net_quantity"] == 60, "C 没库存，全缺"

        assert result["summary"]["material_lines"] == 3
        assert result["summary"]["shortage_lines"] == 2
    finally:
        for bid in (bom_a, bom_a2, bom_b):
            client.delete(f"/api/v1/production-boms/{bid}")
        _drop_warehouse(wh)
        for pid in (a, b, c, d):
            client.delete(f"/api/v1/products/{pid}")


def test_mrp_missing_product_and_warehouse():
    missing_product = client.get(
        "/api/v1/mrp/requirements", params={"product_id": 99999999, "quantity": 1}
    )
    assert missing_product.status_code == 404

    product = _new_product("MRP测试商品成品", 10.0)
    try:
        bad_wh = client.get(
            "/api/v1/mrp/requirements",
            params={"product_id": product, "quantity": 1, "warehouse_id": 99999999},
        )
        assert bad_wh.status_code == 404
    finally:
        client.delete(f"/api/v1/products/{product}")


# ---------- 批量运算与按计划运算 ----------


def test_mrp_run_multiple_products_and_empty_rejected():
    a = _new_product("MRP测试商品成品A", 100.0)
    b = _new_product("MRP测试商品成品B", 80.0)
    ma = _new_product("MRP测试商品原料A", 5.0)
    bom_a = _new_bom(a, ma, 2)
    try:
        resp = client.post(
            "/api/v1/mrp/run",
            json={"items": [{"product_id": a, "quantity": 5}, {"product_id": b, "quantity": 2}]},
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["summary"]["demand_lines"] == 2
        assert _row_of(result, a)["gross_quantity"] == 5
        assert _row_of(result, ma)["gross_quantity"] == 10

        empty = client.post("/api/v1/mrp/run", json={"items": []})
        assert empty.status_code == 400, empty.text
    finally:
        client.delete(f"/api/v1/production-boms/{bom_a}")
        for pid in (a, b, ma):
            client.delete(f"/api/v1/products/{pid}")


def test_mrp_by_production_plan():
    product = _new_product("MRP测试商品成品", 100.0)
    material = _new_product("MRP测试商品原料", 6.0)
    bom_id = _new_bom(product, material, 4)
    plan_id = None
    try:
        plan_id = client.post(
            "/api/v1/production-plans",
            json={
                "items": [{"product_id": product, "quantity": 5}],
                "note": "生产计划测试",
            },
        ).json()["id"]

        resp = client.get(f"/api/v1/production-plans/{plan_id}/mrp")
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["plan_no"].startswith("SCJH")
        assert _row_of(result, material)["gross_quantity"] == 20

        empty_plan = client.post(
            "/api/v1/production-plans", json={"note": "生产计划测试"}
        ).json()["id"]
        try:
            no_demand = client.get(f"/api/v1/production-plans/{empty_plan}/mrp")
            assert no_demand.status_code == 400
        finally:
            client.delete(f"/api/v1/production-plans/{empty_plan}")

        missing = client.get("/api/v1/production-plans/99999999/mrp")
        assert missing.status_code == 404
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/production-boms/{bom_id}")
        client.delete(f"/api/v1/products/{product}")
        client.delete(f"/api/v1/products/{material}")
