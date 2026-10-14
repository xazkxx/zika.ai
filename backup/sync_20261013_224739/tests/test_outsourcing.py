"""委外加工单（第 3 批 · 生产类第 6 个单据表，生产类收官）回归测试。

委外加工 = 把材料发给外协厂加工、加工完收回成品，一张单两个方向：
  - 发出材料：outsourcing_items 明细，原材料现存量**减少**（outbound）
  - 收回成品：单据头 product_id + quantity，成品现存量**增加**（inbound）
两类流水共用 related_type="outsourcing" + 本单 id，删单时一次全冲。

与自制不同，委外要**付加工费**：单据头记 process_fee，审核后自动产生
**应付**（transaction_type="payable" 挂外协厂）—— 所以委外加工是
**同时动库存与财务**的单据。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-` 前缀、
备注含「委外加工测试」。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _order_no() -> str:
    return f"TEST-WWJG{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "委外测试商品", price: float = 5.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-WW-{uuid.uuid4().hex[:8]}",
            "name": name,
            "purchase_price": price,
            "sale_price": price * 2,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier(name: str = "外协加工厂") -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-WW-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "委外主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-WW-{uuid.uuid4().hex[:8]}", "name": name},
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
            "items": [{"product_id": product_id, "quantity": qty, "unit_price": 5.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _stock_rows(order_id: int) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "outsourcing" and row.get("related_order_id") == order_id
    ]


def _fin_rows(order_id: int) -> list[dict]:
    rows = client.get("/api/v1/finance").json()
    return [
        row for row in rows
        if row.get("related_type") == "outsourcing" and row.get("related_order_id") == order_id
    ]


# ---------- 创建与单据头 ----------


def test_create_order_auto_no_and_fields():
    finished = _new_product("委外成品", 12.0)
    material = _new_product("委外材料", 5.0)
    supplier = _new_supplier()
    wh = _new_warehouse()
    order_id = None
    try:
        resp = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": supplier,
                "warehouse_id": wh,
                "handler": "委外员",
                "product_id": finished,
                "quantity": 5,
                "process_fee": 100.0,
                "items": [{"product_id": material, "quantity": 8}],
                "note": "委外加工测试",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        order_id = body["id"]
        assert body["order_no"].startswith("WWJG"), body["order_no"]
        assert body["status"] == "submitted"
        assert body["order_date"], "委外日期缺省应自动填当天"
        assert body["product_name"] == "委外成品"
        assert body["quantity"] == 5
        assert body["process_fee"] == 100.0
        line = body["items"][0]
        assert line["product_name"] == "委外材料"
        assert line["unit_price"] == 5.0
        assert line["amount"] == 40.0
        assert body["total_amount"] == 40.0, "发出材料成本合计"
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier}")
        client.delete(f"/api/v1/products/{material}")
        client.delete(f"/api/v1/products/{finished}")


def test_create_order_duplicate_no_rejected():
    material = _new_product("委外材料", 5.0)
    order_no = _order_no()
    ids = []
    try:
        payload = {
            "order_no": order_no,
            "items": [{"product_id": material, "quantity": 1}],
            "note": "委外加工测试",
        }
        first = client.post("/api/v1/outsourcings", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/outsourcings", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for oid in ids:
            client.delete(f"/api/v1/outsourcings/{oid}")
        client.delete(f"/api/v1/products/{material}")


def test_create_order_missing_supplier_and_bad_status():
    material = _new_product("委外材料", 5.0)
    try:
        missing = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": 99999999,
                "items": [{"product_id": material, "quantity": 1}],
                "note": "委外加工测试",
            },
        )
        assert missing.status_code == 404, missing.text

        bad = client.post(
            "/api/v1/outsourcings",
            json={"status": "nonsense", "note": "委外加工测试"},
        )
        assert bad.status_code == 400, bad.text
    finally:
        client.delete(f"/api/v1/products/{material}")


# ---------- 库存（发料 + 收成品）+ 财务（加工费应付）----------


def test_order_moves_stock_both_ways_and_writes_payable():
    finished = _new_product("委外成品", 12.0)
    material = _new_product("委外材料", 5.0)
    supplier = _new_supplier()
    wh = _new_warehouse()
    seed_id = None
    order_id = None
    try:
        seed_id = _seed_stock(material, supplier, wh, 10)
        fin_before = len(client.get("/api/v1/finance").json())

        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": supplier,
                "warehouse_id": wh,
                "product_id": finished,
                "quantity": 5,
                "process_fee": 100.0,
                "items": [{"product_id": material, "quantity": 4}],
                "note": "委外加工测试",
            },
        ).json()["id"]

        assert _stock_for(material, wh) == 6, "发料应把 4 件材料发给外协厂"
        assert _stock_for(finished, wh) == 5, "收回应把 5 件成品入库"

        rows = _stock_rows(order_id)
        assert len(rows) == 2, "一张单应有发料 + 收成品两条流水"
        kinds = sorted(row["transaction_type"] for row in rows)
        assert kinds == ["inbound", "outbound"]

        fin_rows = _fin_rows(order_id)
        assert len(fin_rows) == 1, "加工费应产生一笔应付"
        assert fin_rows[0]["transaction_type"] == "payable"
        assert fin_rows[0]["direction"] == "out"
        assert fin_rows[0]["amount"] == 100.0
        assert fin_rows[0]["supplier_id"] == supplier, "应付应挂到外协厂"
        assert len(client.get("/api/v1/finance").json()) == fin_before + 1
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        if seed_id:
            client.delete(f"/api/v1/purchase-orders/{seed_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier}")
        client.delete(f"/api/v1/products/{material}")
        client.delete(f"/api/v1/products/{finished}")


def test_delete_order_reverts_stock_and_finance():
    finished = _new_product("委外成品", 12.0)
    material = _new_product("委外材料", 5.0)
    supplier = _new_supplier()
    wh = _new_warehouse()
    seed_id = None
    order_id = None
    try:
        seed_id = _seed_stock(material, supplier, wh, 10)
        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": supplier,
                "warehouse_id": wh,
                "product_id": finished,
                "quantity": 5,
                "process_fee": 100.0,
                "items": [{"product_id": material, "quantity": 4}],
                "note": "委外加工测试",
            },
        ).json()["id"]
        assert _stock_for(material, wh) == 6
        assert _stock_for(finished, wh) == 5

        assert client.delete(f"/api/v1/outsourcings/{order_id}").status_code == 204
        assert _stock_for(material, wh) == 10, "删单应把发出的材料退回"
        assert _stock_for(finished, wh) == 0, "删单应把收回的成品扣回"
        assert _stock_rows(order_id) == [], "两类库存流水应一次全冲"
        assert _fin_rows(order_id) == [], "应付流水应一并冲销"
        order_id = None
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        if seed_id:
            client.delete(f"/api/v1/purchase-orders/{seed_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier}")
        client.delete(f"/api/v1/products/{material}")
        client.delete(f"/api/v1/products/{finished}")


def test_update_order_items_replays_stock_and_finance():
    finished = _new_product("委外成品", 12.0)
    material = _new_product("委外材料", 5.0)
    supplier = _new_supplier()
    wh = _new_warehouse()
    seed_id = None
    order_id = None
    try:
        seed_id = _seed_stock(material, supplier, wh, 10)
        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": supplier,
                "warehouse_id": wh,
                "product_id": finished,
                "quantity": 5,
                "process_fee": 100.0,
                "items": [{"product_id": material, "quantity": 4}],
                "note": "委外加工测试",
            },
        ).json()["id"]
        assert _stock_for(material, wh) == 6

        patched = client.patch(
            f"/api/v1/outsourcings/{order_id}",
            json={
                "quantity": 3,
                "process_fee": 60.0,
                "items": [{"product_id": material, "quantity": 2}],
            },
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["quantity"] == 3
        assert patched.json()["process_fee"] == 60.0
        assert _stock_for(material, wh) == 8, "应按新发料量 2 重放，而不是叠加"
        assert _stock_for(finished, wh) == 3, "应按新收回量 3 重放"
        assert len(_stock_rows(order_id)) == 2, "库存流水应重放而不是累积"

        fin_rows = _fin_rows(order_id)
        assert len(fin_rows) == 1, "应付流水应重放而不是累积"
        assert fin_rows[0]["amount"] == 60.0, "应付金额应随加工费更新"
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        if seed_id:
            client.delete(f"/api/v1/purchase-orders/{seed_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier}")
        client.delete(f"/api/v1/products/{material}")
        client.delete(f"/api/v1/products/{finished}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_order_list_status_detail_and_meta():
    material = _new_product("委外材料", 5.0)
    wh = _new_warehouse()
    order_no = _order_no()
    order_id = None
    try:
        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "order_no": order_no,
                "warehouse_id": wh,
                "handler": "关键字经办",
                "items": [{"product_id": material, "quantity": 2}],
                "note": "委外加工测试",
            },
        ).json()["id"]

        by_no = client.get("/api/v1/outsourcings", params={"keyword": order_no}).json()
        assert [row["id"] for row in by_no] == [order_id]

        by_handler = client.get("/api/v1/outsourcings", params={"keyword": "关键字经办"}).json()
        assert any(row["id"] == order_id for row in by_handler)

        detail = client.get(f"/api/v1/outsourcings/{order_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["order_no"].startswith("TEST-WWJG")

        ok = client.patch(f"/api/v1/outsourcings/{order_id}/status", json={"status": "draft"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "draft"

        bad = client.patch(f"/api/v1/outsourcings/{order_id}/status", json={"status": "x"})
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/outsourcings/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "submitted", "cancelled",
        }

        assert client.get("/api/v1/outsourcings/99999999").status_code == 404
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{material}")


def test_order_list_filter_by_supplier():
    material = _new_product("委外材料", 5.0)
    supplier = _new_supplier()
    order_id = None
    try:
        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "supplier_id": supplier,
                "items": [{"product_id": material, "quantity": 2}],
                "note": "委外加工测试",
            },
        ).json()["id"]

        by_sup = client.get("/api/v1/outsourcings", params={"supplier_id": supplier}).json()
        assert any(row["id"] == order_id for row in by_sup)
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        client.delete(f"/api/v1/suppliers/{supplier}")
        client.delete(f"/api/v1/products/{material}")


# ---------- 打印 ----------


def test_order_print_pdf():
    material = _new_product("委外材料", 5.0)
    wh = _new_warehouse()
    order_id = None
    try:
        order_id = client.post(
            "/api/v1/outsourcings",
            json={
                "order_no": _order_no(),
                "warehouse_id": wh,
                "items": [{"product_id": material, "quantity": 2}],
                "note": "委外加工测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/outsourcing/{order_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        assert client.get("/api/v1/print/outsourcing/99999999").status_code == 404
    finally:
        if order_id:
            client.delete(f"/api/v1/outsourcings/{order_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{material}")
