"""生产计划单（第 3 批 · 生产类第 1 个单据表）回归测试。

生产计划是**排产意图**而非业务发生：只说明"什么时候、在哪个车间仓、生产多少
什么产品"，既不写库存流水、也不写财务流水（与报价单同属前置单据）。

本文件把这条口径用**反向断言**锁死：创建计划前后，库存流水与财务流水的条数
必须完全不变。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-` 前缀、
备注含「生产计划测试」。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _plan_no() -> str:
    return f"TEST-SCJH{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "生产计划测试商品", price: float = 50.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-SCJH-{uuid.uuid4().hex[:8]}",
            "name": name,
            "purchase_price": price,
            "sale_price": price * 2,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "生产车间仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-SCJH-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


# ---------- 创建与单据头 ----------


def test_create_plan_auto_no_and_line_fields():
    product_id = _new_product()
    wh = _new_warehouse()
    plan_id = None
    try:
        resp = client.post(
            "/api/v1/production-plans",
            json={
                "warehouse_id": wh,
                "handler": "计划员",
                "items": [{"product_id": product_id, "quantity": 10}],
                "note": "生产计划测试",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        plan_id = body["id"]
        assert body["plan_no"].startswith("SCJH"), body["plan_no"]
        assert body["plan_type"] == "self"
        assert body["status"] == "planned"
        assert body["plan_date"], "计划日期缺省应自动填当天"
        assert len(body["items"]) == 1
        line = body["items"][0]
        assert line["product_name"] == "生产计划测试商品"
        assert line["unit_price"] == 50.0, "计划成本缺省按商品进价带出"
        assert line["amount"] == 500.0
        assert body["total_quantity"] == 10
        assert body["total_amount"] == 500.0
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_outsource_plan_uses_wwjh_prefix():
    product_id = _new_product()
    plan_id = None
    try:
        body = client.post(
            "/api/v1/production-plans",
            json={
                "plan_type": "outsource",
                "items": [{"product_id": product_id, "quantity": 3}],
                "note": "生产计划测试",
            },
        ).json()
        plan_id = body["id"]
        assert body["plan_type"] == "outsource"
        assert body["plan_no"].startswith("WWJH"), body["plan_no"]
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_plan_does_not_touch_stock_or_finance():
    """生产计划是前置单据：不写库存流水、不写财务流水。"""
    product_id = _new_product()
    wh = _new_warehouse()
    plan_id = None
    try:
        inv_before = len(client.get("/api/v1/inventory").json())
        fin_before = len(client.get("/api/v1/finance").json())

        plan_id = client.post(
            "/api/v1/production-plans",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 7}],
                "note": "生产计划测试",
            },
        ).json()["id"]

        assert len(client.get("/api/v1/inventory").json()) == inv_before, "计划不应写库存流水"
        assert len(client.get("/api/v1/finance").json()) == fin_before, "计划不应写财务流水"
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_plan_duplicate_no_rejected():
    product_id = _new_product()
    plan_no = _plan_no()
    ids = []
    try:
        payload = {
            "plan_no": plan_no,
            "items": [{"product_id": product_id, "quantity": 1}],
            "note": "生产计划测试",
        }
        first = client.post("/api/v1/production-plans", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/production-plans", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for pid in ids:
            client.delete(f"/api/v1/production-plans/{pid}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_plan_missing_warehouse_and_bad_status():
    product_id = _new_product()
    try:
        missing = client.post(
            "/api/v1/production-plans",
            json={
                "warehouse_id": 99999999,
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "生产计划测试",
            },
        )
        assert missing.status_code == 404, missing.text

        bad_status = client.post(
            "/api/v1/production-plans",
            json={"status": "nonsense", "note": "生产计划测试"},
        )
        assert bad_status.status_code == 400, bad_status.text

        bad_type = client.post(
            "/api/v1/production-plans",
            json={"plan_type": "nonsense", "note": "生产计划测试"},
        )
        assert bad_type.status_code == 400, bad_type.text
    finally:
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 修改与重算 ----------


def test_update_plan_replaces_items_and_recomputes():
    p1 = _new_product("生产计划测试商品", 50.0)
    p2 = _new_product("生产计划测试商品二", 20.0)
    plan_id = None
    try:
        plan_id = client.post(
            "/api/v1/production-plans",
            json={"items": [{"product_id": p1, "quantity": 10}], "note": "生产计划测试"},
        ).json()["id"]

        patched = client.patch(
            f"/api/v1/production-plans/{plan_id}",
            json={
                "handler": "改后计划员",
                "items": [
                    {"product_id": p1, "quantity": 4},
                    {"product_id": p2, "quantity": 5},
                ],
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["handler"] == "改后计划员"
        assert len(body["items"]) == 2, "明细应整单替换，不是追加"
        assert body["total_quantity"] == 9
        assert body["total_amount"] == 4 * 50.0 + 5 * 20.0
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{p1}")
        client.delete(f"/api/v1/products/{p2}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_plan_list_and_filters():
    product_id = _new_product()
    plan_no = _plan_no()
    plan_id = None
    try:
        plan_id = client.post(
            "/api/v1/production-plans",
            json={
                "plan_no": plan_no,
                "plan_type": "outsource",
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "生产计划测试",
            },
        ).json()["id"]

        listed = client.get("/api/v1/production-plans").json()
        assert any(row["id"] == plan_id for row in listed)

        by_no = client.get("/api/v1/production-plans", params={"keyword": plan_no}).json()
        assert [row["id"] for row in by_no] == [plan_id]

        by_type = client.get("/api/v1/production-plans", params={"plan_type": "outsource"}).json()
        assert all(row["plan_type"] == "outsource" for row in by_type)

        by_status = client.get("/api/v1/production-plans", params={"status": "planned"}).json()
        assert all(row["status"] == "planned" for row in by_status)
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_plan_status_patch_detail_and_meta():
    product_id = _new_product()
    plan_id = None
    try:
        plan_id = client.post(
            "/api/v1/production-plans",
            json={
                "plan_no": _plan_no(),
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "生产计划测试",
            },
        ).json()["id"]

        detail = client.get(f"/api/v1/production-plans/{plan_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["plan_no"].startswith("TEST-SCJH")

        ok = client.patch(f"/api/v1/production-plans/{plan_id}/status", json={"status": "released"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "released"

        bad = client.patch(
            f"/api/v1/production-plans/{plan_id}/status", json={"status": "nonsense"}
        )
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/production-plans/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "planned", "released", "closed", "cancelled",
        }
        assert {item["code"] for item in meta.json()["plan_types"]} == {"self", "outsource"}

        missing = client.get("/api/v1/production-plans/99999999")
        assert missing.status_code == 404
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_plan_removes_header_and_items():
    product_id = _new_product()
    plan_id = client.post(
        "/api/v1/production-plans",
        json={
            "plan_no": _plan_no(),
            "items": [{"product_id": product_id, "quantity": 1}],
            "note": "生产计划测试",
        },
    ).json()["id"]
    try:
        assert client.delete(f"/api/v1/production-plans/{plan_id}").status_code == 204
        assert client.get(f"/api/v1/production-plans/{plan_id}").status_code == 404
    finally:
        client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 打印 ----------


def test_plan_print_pdf():
    product_id = _new_product()
    plan_id = None
    try:
        plan_id = client.post(
            "/api/v1/production-plans",
            json={
                "plan_no": _plan_no(),
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "生产计划测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/production-plan/{plan_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/production-plan/99999999")
        assert missing.status_code == 404
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/products/{product_id}")
