"""成品入库单（第 3 批 · 生产类第 5 个单据表）回归测试。

成品入库是生产链路的**收口环节**：车间把生产好的成品交回仓库，
成品现存量**增加**（inbound）。

与领料/退料（纯库存单据）不同，成品入库**同时写财务成本流水**
（transaction_type="cost"、direction="in"）—— 它是"在制品 → 产成品"的
价值结转，用 cost 类型（不影响应收应付余额，只进成本口径报表）。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-` 前缀、
备注含「成品入库测试」。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _receipt_no() -> str:
    return f"TEST-CPRK{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "成品测试商品", price: float = 8.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-FG-{uuid.uuid4().hex[:8]}",
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
        json={"code": f"SUP-FG-{uuid.uuid4().hex[:8]}", "name": "成品入库测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "成品主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-FG-{uuid.uuid4().hex[:8]}", "name": name},
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
            "items": [{"product_id": product_id, "quantity": qty, "unit_price": 8.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _stock_rows(receipt_id: int) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "production_in" and row.get("related_order_id") == receipt_id
    ]


def _fin_rows(receipt_id: int) -> list[dict]:
    rows = client.get("/api/v1/finance").json()
    return [
        row for row in rows
        if row.get("related_type") == "production_in" and row.get("related_order_id") == receipt_id
    ]


# ---------- 创建与单据头 ----------


def test_create_receipt_auto_no_and_line_fields():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_id = None
    try:
        resp = client.post(
            "/api/v1/finished-goods",
            json={
                "warehouse_id": wh,
                "workshop": "总装车间",
                "handler": "交库员",
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "成品入库测试",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        receipt_id = body["id"]
        assert body["receipt_no"].startswith("CPRK"), body["receipt_no"]
        assert body["status"] == "submitted"
        assert body["receipt_date"], "入库日期缺省应自动填当天"
        line = body["items"][0]
        assert line["product_name"] == "成品测试商品"
        assert line["unit_price"] == 8.0, "未填单位成本时应从商品进价带出"
        assert line["amount"] == 40.0
        assert body["total_quantity"] == 5
        assert body["total_amount"] == 40.0
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_receipt_duplicate_no_rejected():
    product_id = _new_product()
    receipt_no = _receipt_no()
    ids = []
    try:
        payload = {
            "receipt_no": receipt_no,
            "items": [{"product_id": product_id, "quantity": 1}],
            "note": "成品入库测试",
        }
        first = client.post("/api/v1/finished-goods", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/finished-goods", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for rid in ids:
            client.delete(f"/api/v1/finished-goods/{rid}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_receipt_missing_warehouse_and_bad_status():
    product_id = _new_product()
    try:
        missing = client.post(
            "/api/v1/finished-goods",
            json={
                "warehouse_id": 99999999,
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "成品入库测试",
            },
        )
        assert missing.status_code == 404, missing.text

        bad = client.post(
            "/api/v1/finished-goods",
            json={"status": "nonsense", "note": "成品入库测试"},
        )
        assert bad.status_code == 400, bad.text
    finally:
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 库存 + 财务双向联动 ----------


def test_receipt_increases_stock_and_writes_cost_finance():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_id = None
    try:
        fin_before = len(client.get("/api/v1/finance").json())
        receipt_id = client.post(
            "/api/v1/finished-goods",
            json={
                "warehouse_id": wh,
                "workshop": "总装车间",
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "成品入库测试",
            },
        ).json()["id"]

        assert _stock_for(product_id, wh) == 5, "成品入库应把 5 件成品入库"
        stock_rows = _stock_rows(receipt_id)
        assert len(stock_rows) == 1
        assert stock_rows[0]["transaction_type"] == "inbound"

        fin_rows = _fin_rows(receipt_id)
        assert len(fin_rows) == 1, "成品入库应结转到财务成本流水"
        assert fin_rows[0]["transaction_type"] == "cost"
        assert fin_rows[0]["direction"] == "in"
        assert fin_rows[0]["amount"] == 40.0
        assert len(client.get("/api/v1/finance").json()) == fin_before + 1
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_receipt_reverts_stock_and_finance():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_id = None
    try:
        receipt_id = client.post(
            "/api/v1/finished-goods",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 6}],
                "note": "成品入库测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 6
        assert len(_fin_rows(receipt_id)) == 1

        assert client.delete(f"/api/v1/finished-goods/{receipt_id}").status_code == 204
        assert _stock_for(product_id, wh) == 0, "删成品入库单应把成品扣回车间"
        assert _stock_rows(receipt_id) == [], "库存流水应一并冲销"
        assert _fin_rows(receipt_id) == [], "财务成本流水应一并冲销"
        receipt_id = None
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_update_receipt_items_replays_stock_and_finance():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_id = None
    try:
        receipt_id = client.post(
            "/api/v1/finished-goods",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "成品入库测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 5

        patched = client.patch(
            f"/api/v1/finished-goods/{receipt_id}",
            json={"items": [{"product_id": product_id, "quantity": 2}]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["total_quantity"] == 2
        assert _stock_for(product_id, wh) == 2, "应按新数量 2 重放，而不是叠加"
        assert len(_stock_rows(receipt_id)) == 1, "库存流水应重放而不是累积"

        fin_rows = _fin_rows(receipt_id)
        assert len(fin_rows) == 1, "财务流水应重放而不是累积"
        assert fin_rows[0]["amount"] == 16.0, "成本金额应随明细金额更新"
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 关联生产计划 ----------


def test_receipt_links_production_plan():
    product_id = _new_product()
    wh = _new_warehouse()
    plan_id = None
    receipt_id = None
    try:
        plan = client.post(
            "/api/v1/production-plans",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "成品入库测试",
            },
        )
        assert plan.status_code == 201, plan.text
        plan_id = plan.json()["id"]
        plan_no = plan.json()["plan_no"]

        receipt = client.post(
            "/api/v1/finished-goods",
            json={
                "plan_id": plan_id,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 5}],
                "note": "成品入库测试",
            },
        )
        assert receipt.status_code == 201, receipt.text
        receipt_id = receipt.json()["id"]
        assert receipt.json()["plan_id"] == plan_id
        assert receipt.json()["plan_no"] == plan_no, "未传计划号时应从计划单带出"

        # 计划被下游引用后不允许删除
        blocked = client.delete(f"/api/v1/production-plans/{plan_id}")
        assert blocked.status_code == 409, blocked.text
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        if plan_id:
            client.delete(f"/api/v1/production-plans/{plan_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_receipt_list_status_detail_and_meta():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_no = _receipt_no()
    receipt_id = None
    try:
        receipt_id = client.post(
            "/api/v1/finished-goods",
            json={
                "receipt_no": receipt_no,
                "warehouse_id": wh,
                "workshop": "关键字车间",
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "成品入库测试",
            },
        ).json()["id"]

        by_no = client.get("/api/v1/finished-goods", params={"keyword": receipt_no}).json()
        assert [row["id"] for row in by_no] == [receipt_id]

        by_ws = client.get("/api/v1/finished-goods", params={"keyword": "关键字车间"}).json()
        assert any(row["id"] == receipt_id for row in by_ws)

        by_wh = client.get("/api/v1/finished-goods", params={"warehouse_id": wh}).json()
        assert any(row["id"] == receipt_id for row in by_wh)

        detail = client.get(f"/api/v1/finished-goods/{receipt_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["receipt_no"].startswith("TEST-CPRK")

        ok = client.patch(f"/api/v1/finished-goods/{receipt_id}/status", json={"status": "draft"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "draft"

        bad = client.patch(f"/api/v1/finished-goods/{receipt_id}/status", json={"status": "x"})
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/finished-goods/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "submitted", "cancelled",
        }

        assert client.get("/api/v1/finished-goods/99999999").status_code == 404
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 打印 ----------


def test_receipt_print_pdf():
    product_id = _new_product()
    wh = _new_warehouse()
    receipt_id = None
    try:
        receipt_id = client.post(
            "/api/v1/finished-goods",
            json={
                "receipt_no": _receipt_no(),
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "成品入库测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/finished-goods/{receipt_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        assert client.get("/api/v1/print/finished-goods/99999999").status_code == 404
    finally:
        if receipt_id:
            client.delete(f"/api/v1/finished-goods/{receipt_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")
