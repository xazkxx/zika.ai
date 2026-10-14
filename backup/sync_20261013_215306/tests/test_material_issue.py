"""生产领料单（第 3 批 · 生产类第 3 个单据表）回归测试。

领料 = 把原材料从仓库发到车间：原材料现存量**减少**（outbound 流水）。
与调拨/盘点/报损报溢一样是**纯库存单据** —— 只动库存、不写财务流水
（材料成本归集落在下游成品入库环节）。本文件用反向断言锁死这条口径。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-` 前缀、
备注含「生产领料测试」。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _issue_no() -> str:
    return f"TEST-SCLL{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "领料测试商品", price: float = 6.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-LL-{uuid.uuid4().hex[:8]}",
            "name": name,
            "purchase_price": price,
            "sale_price": price * 2,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-LL-{uuid.uuid4().hex[:8]}", "name": "领料测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "领料主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-LL-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _stock_for(product_id: int, warehouse_id: int) -> int:
    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    for row in data.get("rows", []):
        if row.get("warehouse_id") == warehouse_id:
            return int(row.get("quantity") or 0)
    return 0


def _seed_stock(product_id: int, supplier_id: int, warehouse_id: int, qty: int = 10) -> int:
    resp = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "items": [{"product_id": product_id, "quantity": qty, "unit_price": 6.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _issue_rows(issue_id: int) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "production_issue" and row.get("related_order_id") == issue_id
    ]


def _new_plan(product_id: int, warehouse_id: int | None = None, qty: int = 10) -> int:
    body = {
        "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": qty}],
        "note": "生产计划测试",
    }
    resp = client.post("/api/v1/production-plans", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------- 创建与单据头 ----------


def test_create_issue_auto_no_and_line_fields():
    product_id = _new_product()
    wh = _new_warehouse()
    issue_id = None
    try:
        resp = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": wh,
                "workshop": "装配车间",
                "handler": "领料员",
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "生产领料测试",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        issue_id = body["id"]
        assert body["issue_no"].startswith("SCLL"), body["issue_no"]
        assert body["status"] == "submitted"
        assert body["issue_date"], "领料日期缺省应自动填当天"
        line = body["items"][0]
        assert line["product_name"] == "领料测试商品"
        assert line["unit_price"] == 6.0, "材料成本缺省按商品进价带出"
        assert line["amount"] == 24.0
        assert body["total_quantity"] == 4
        assert body["total_amount"] == 24.0
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_issue_duplicate_no_rejected():
    product_id = _new_product()
    issue_no = _issue_no()
    ids = []
    try:
        payload = {
            "issue_no": issue_no,
            "items": [{"product_id": product_id, "quantity": 1}],
            "note": "生产领料测试",
        }
        first = client.post("/api/v1/material-issues", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/material-issues", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for iid in ids:
            client.delete(f"/api/v1/material-issues/{iid}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_issue_missing_warehouse_plan_and_bad_status():
    product_id = _new_product()
    try:
        missing_wh = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": 99999999,
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "生产领料测试",
            },
        )
        assert missing_wh.status_code == 404, missing_wh.text

        missing_plan = client.post(
            "/api/v1/material-issues",
            json={"plan_id": 99999999, "note": "生产领料测试"},
        )
        assert missing_plan.status_code == 404, missing_plan.text

        bad_status = client.post(
            "/api/v1/material-issues",
            json={"status": "nonsense", "note": "生产领料测试"},
        )
        assert bad_status.status_code == 400, bad_status.text
    finally:
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 库存联动 ----------


def test_issue_decreases_stock_and_writes_no_finance():
    """领料把原材料发给车间：库存减少，且不写任何财务流水。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    issue_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        assert _stock_for(product_id, wh) == 10

        fin_before = len(client.get("/api/v1/finance").json())
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "生产领料测试",
            },
        ).json()["id"]

        assert _stock_for(product_id, wh) == 6, "领料应把 4 件材料发出仓库"
        rows = _issue_rows(issue_id)
        assert len(rows) == 1
        assert rows[0]["transaction_type"] == "outbound"

        assert len(client.get("/api/v1/finance").json()) == fin_before, (
            "生产领料是纯库存单据，不应写财务流水"
        )
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_issue_reverts_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    issue_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 6}],
                "note": "生产领料测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 4

        assert client.delete(f"/api/v1/material-issues/{issue_id}").status_code == 204
        assert _stock_for(product_id, wh) == 10, "删领料单应把材料退回仓库"
        assert _issue_rows(issue_id) == []
        issue_id = None
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_issue_items_replays_stock():
    """改领料数量必须整体重放，否则会留下按旧数量发过的料（单边账）。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    issue_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "生产领料测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 6

        patched = client.patch(
            f"/api/v1/material-issues/{issue_id}",
            json={"items": [{"product_id": product_id, "quantity": 7}]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["total_quantity"] == 7
        assert _stock_for(product_id, wh) == 3, "应按新数量 7 重放，而不是叠加"
        assert len(_issue_rows(issue_id)) == 1, "流水应重放而不是累积"
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_issue_warehouse_replays_stock():
    """改领料仓库也要整体重放：旧仓库的料退回、新仓库重新发出。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh_a = _new_warehouse("领料仓A")
    wh_b = _new_warehouse("领料仓B")
    inbound_a = inbound_b = None
    issue_id = None
    try:
        inbound_a = _seed_stock(product_id, supplier_id, wh_a, 10)
        inbound_b = _seed_stock(product_id, supplier_id, wh_b, 10)

        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "warehouse_id": wh_a,
                "items": [{"product_id": product_id, "quantity": 3}],
                "note": "生产领料测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh_a) == 7
        assert _stock_for(product_id, wh_b) == 10

        assert client.patch(
            f"/api/v1/material-issues/{issue_id}", json={"warehouse_id": wh_b}
        ).status_code == 200
        assert _stock_for(product_id, wh_a) == 10, "旧仓的料应退回"
        assert _stock_for(product_id, wh_b) == 7, "新仓应重新发出"
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        for iid in (inbound_a, inbound_b):
            if iid:
                client.delete(f"/api/v1/purchase-orders/{iid}")
        _drop_warehouse(wh_a)
        _drop_warehouse(wh_b)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 领料底稿 ----------


def test_issue_suggestion_from_plan():
    """按生产计划带出领料底稿：BOM 展开展出的物料需求（毛需求）。"""
    product = _new_product("领料测试成品", 100.0)
    material = _new_product("领料测试原料", 5.0)
    wh = _new_warehouse()
    bom_id = client.post(
        "/api/v1/production-boms",
        json={"product_id": product, "component_product_id": material, "quantity": 3},
    ).json()["id"]
    plan_id = None
    try:
        plan_id = _new_plan(product, wh, 10)

        resp = client.get("/api/v1/material-issues/suggestion", params={"plan_id": plan_id})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["plan_no"].startswith("SCJH")
        row = next((r for r in data["items"] if r["product_id"] == material), None)
        assert row is not None, "领料底稿应带出 BOM 展开的原料"
        assert row["quantity"] == 30, "领料数量默认按毛需求（10 × 3）"

        missing = client.get("/api/v1/material-issues/suggestion", params={"plan_id": 99999999})
        assert missing.status_code == 404
    finally:
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        client.delete(f"/api/v1/production-boms/{bom_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product}")
        client.delete(f"/api/v1/products/{material}")


def test_plan_with_downstream_issue_cannot_be_deleted():
    product_id = _new_product()
    wh = _new_warehouse()
    plan_id = None
    issue_id = None
    try:
        plan_id = _new_plan(product_id, wh, 5)
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "plan_id": plan_id,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "生产领料测试",
            },
        ).json()["id"]

        blocked = client.delete(f"/api/v1/production-plans/{plan_id}")
        assert blocked.status_code == 409, blocked.text

        client.delete(f"/api/v1/material-issues/{issue_id}")
        issue_id = None
        assert client.delete(f"/api/v1/production-plans/{plan_id}").status_code == 204
        plan_id = None
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_issue_list_status_detail_and_meta():
    product_id = _new_product()
    wh = _new_warehouse()
    issue_no = _issue_no()
    issue_id = None
    try:
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "issue_no": issue_no,
                "warehouse_id": wh,
                "workshop": "关键字车间",
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "生产领料测试",
            },
        ).json()["id"]

        by_no = client.get("/api/v1/material-issues", params={"keyword": issue_no}).json()
        assert [row["id"] for row in by_no] == [issue_id]

        by_wh = client.get("/api/v1/material-issues", params={"warehouse_id": wh}).json()
        assert any(row["id"] == issue_id for row in by_wh)

        by_workshop = client.get("/api/v1/material-issues", params={"keyword": "关键字车间"}).json()
        assert any(row["id"] == issue_id for row in by_workshop)

        detail = client.get(f"/api/v1/material-issues/{issue_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["issue_no"].startswith("TEST-SCLL")

        ok = client.patch(f"/api/v1/material-issues/{issue_id}/status", json={"status": "cancelled"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "cancelled"

        bad = client.patch(f"/api/v1/material-issues/{issue_id}/status", json={"status": "x"})
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/material-issues/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "submitted", "cancelled",
        }

        assert client.get("/api/v1/material-issues/99999999").status_code == 404
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 打印 ----------


def test_issue_print_pdf():
    product_id = _new_product()
    wh = _new_warehouse()
    issue_id = None
    try:
        issue_id = client.post(
            "/api/v1/material-issues",
            json={
                "issue_no": _issue_no(),
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "生产领料测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/material-issue/{issue_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        assert client.get("/api/v1/print/material-issue/99999999").status_code == 404
    finally:
        if issue_id:
            client.delete(f"/api/v1/material-issues/{issue_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")
