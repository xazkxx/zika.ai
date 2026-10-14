"""生产退料单（第 3 批 · 生产类第 4 个单据表）回归测试。

退料是领料的**反向**单据：车间余料退回仓库，原材料现存量**增加**（inbound）。
与领料一样是**纯库存单据** —— 只动库存、不写财务流水。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-` 前缀、
备注含「生产退料测试」。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _return_no() -> str:
    return f"TEST-SCTL{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "退料测试商品", price: float = 6.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-TL-{uuid.uuid4().hex[:8]}",
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
        json={"code": f"SUP-TL-{uuid.uuid4().hex[:8]}", "name": "退料测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "退料主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-TL-{uuid.uuid4().hex[:8]}", "name": name},
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


def _return_rows(return_id: int) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "production_return" and row.get("related_order_id") == return_id
    ]


# ---------- 创建与单据头 ----------


def test_create_return_auto_no_and_line_fields():
    product_id = _new_product()
    wh = _new_warehouse()
    return_id = None
    try:
        resp = client.post(
            "/api/v1/material-returns",
            json={
                "warehouse_id": wh,
                "workshop": "装配车间",
                "handler": "退料员",
                "reason": "余料退回",
                "items": [{"product_id": product_id, "quantity": 3}],
                "note": "生产退料测试",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return_id = body["id"]
        assert body["return_no"].startswith("SCTL"), body["return_no"]
        assert body["status"] == "submitted"
        assert body["return_date"], "退料日期缺省应自动填当天"
        line = body["items"][0]
        assert line["product_name"] == "退料测试商品"
        assert line["unit_price"] == 6.0
        assert line["amount"] == 18.0
        assert body["total_quantity"] == 3
        assert body["total_amount"] == 18.0
        assert body["reason"] == "余料退回"
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_return_duplicate_no_rejected():
    product_id = _new_product()
    return_no = _return_no()
    ids = []
    try:
        payload = {
            "return_no": return_no,
            "items": [{"product_id": product_id, "quantity": 1}],
            "note": "生产退料测试",
        }
        first = client.post("/api/v1/material-returns", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/material-returns", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for rid in ids:
            client.delete(f"/api/v1/material-returns/{rid}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_return_missing_warehouse_and_bad_status():
    product_id = _new_product()
    try:
        missing = client.post(
            "/api/v1/material-returns",
            json={
                "warehouse_id": 99999999,
                "items": [{"product_id": product_id, "quantity": 1}],
                "note": "生产退料测试",
            },
        )
        assert missing.status_code == 404, missing.text

        bad = client.post(
            "/api/v1/material-returns",
            json={"status": "nonsense", "note": "生产退料测试"},
        )
        assert bad.status_code == 400, bad.text
    finally:
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 库存联动（与领料相反）----------


def test_return_increases_stock_and_writes_no_finance():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)

        fin_before = len(client.get("/api/v1/finance").json())
        return_id = client.post(
            "/api/v1/material-returns",
            json={
                "warehouse_id": wh,
                "reason": "余料退回",
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "生产退料测试",
            },
        ).json()["id"]

        assert _stock_for(product_id, wh) == 14, "退料应把 4 件材料退回仓库"
        rows = _return_rows(return_id)
        assert len(rows) == 1
        assert rows[0]["transaction_type"] == "inbound"

        assert len(client.get("/api/v1/finance").json()) == fin_before, (
            "生产退料是纯库存单据，不应写财务流水"
        )
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_return_reverts_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        return_id = client.post(
            "/api/v1/material-returns",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 6}],
                "note": "生产退料测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 16

        assert client.delete(f"/api/v1/material-returns/{return_id}").status_code == 204
        assert _stock_for(product_id, wh) == 10, "删退料单应把退回的料再扣回去"
        assert _return_rows(return_id) == []
        return_id = None
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_return_items_replays_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        return_id = client.post(
            "/api/v1/material-returns",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "生产退料测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 14

        patched = client.patch(
            f"/api/v1/material-returns/{return_id}",
            json={"items": [{"product_id": product_id, "quantity": 2}]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["total_quantity"] == 2
        assert _stock_for(product_id, wh) == 12, "应按新数量 2 重放，而不是叠加"
        assert len(_return_rows(return_id)) == 1, "流水应重放而不是累积"
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_return_list_status_detail_and_meta():
    product_id = _new_product()
    wh = _new_warehouse()
    return_no = _return_no()
    return_id = None
    try:
        return_id = client.post(
            "/api/v1/material-returns",
            json={
                "return_no": return_no,
                "warehouse_id": wh,
                "workshop": "关键字车间",
                "reason": "关键字原因",
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "生产退料测试",
            },
        ).json()["id"]

        by_no = client.get("/api/v1/material-returns", params={"keyword": return_no}).json()
        assert [row["id"] for row in by_no] == [return_id]

        by_reason = client.get("/api/v1/material-returns", params={"keyword": "关键字原因"}).json()
        assert any(row["id"] == return_id for row in by_reason)

        by_wh = client.get("/api/v1/material-returns", params={"warehouse_id": wh}).json()
        assert any(row["id"] == return_id for row in by_wh)

        detail = client.get(f"/api/v1/material-returns/{return_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["return_no"].startswith("TEST-SCTL")

        ok = client.patch(f"/api/v1/material-returns/{return_id}/status", json={"status": "draft"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "draft"

        bad = client.patch(f"/api/v1/material-returns/{return_id}/status", json={"status": "x"})
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/material-returns/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "submitted", "cancelled",
        }

        assert client.get("/api/v1/material-returns/99999999").status_code == 404
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 打印 ----------


def test_return_print_pdf():
    product_id = _new_product()
    wh = _new_warehouse()
    return_id = None
    try:
        return_id = client.post(
            "/api/v1/material-returns",
            json={
                "return_no": _return_no(),
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "生产退料测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/material-return/{return_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        assert client.get("/api/v1/print/material-return/99999999").status_code == 404
    finally:
        if return_id:
            client.delete(f"/api/v1/material-returns/{return_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")
