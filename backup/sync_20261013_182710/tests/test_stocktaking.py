"""库存盘点单（对齐浩技云「库存管理 → 盘点管理」）回归测试（第 2 批 · 第 5 个单据表）。

盘点是**账实核对**：账面数由系统按现存量带出、实盘数由人录入，差额就是盈亏。
盈亏方向由明细行自己决定（diff > 0 盘盈 inbound、diff < 0 盘亏 outbound），
所以一张盘点单会同时写两类流水，共用 related_type="inv_check"，
删单时一次全冲、账实同时回到盘点前。

盘点与调拨同属**纯库存单据**：只调整现存量、不写财务流水。

测试数据遵守 scripts/clean_test_data.py 的规则：盘点单号用 `TEST-PD` 前缀、
备注含「盘点单测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _check_no() -> str:
    return f"TEST-PD{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "盘点测试商品", price: float = 6.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-PD-{uuid.uuid4().hex[:8]}",
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
        json={"code": f"SUP-PD-{uuid.uuid4().hex[:8]}", "name": "盘点测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "盘点主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-PD-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    """删测试仓库：用 force 强删，否则被库存流水引用时删不掉，会在库里堆积。"""
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _stock_for(product_id: int, warehouse_id: int) -> int:
    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    for row in data.get("rows", []):
        if row.get("warehouse_id") == warehouse_id:
            return int(row.get("quantity") or 0)
    return 0


def _seed_stock(product_id: int, supplier_id: int, warehouse_id: int, qty: int = 10) -> int:
    """用一笔采购入库给盘点仓垫底库存，返回入库单 id。"""
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


def _check_rows(check_id: int) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "inv_check" and row.get("related_order_id") == check_id
    ]


# ---------- 创建与单据头 ----------


def test_create_stocktaking_auto_no_and_line_fields():
    product_id = _new_product()
    wh = _new_warehouse()
    check_id = None
    try:
        resp = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "handler": "盘点员",
                "items": [{"product_id": product_id, "book_quantity": 10, "actual_quantity": 13}],
                "note": "盘点单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        check_id = r["id"]
        assert r["check_no"].startswith("PD"), r["check_no"]
        assert r["status"] == "submitted"
        assert r["check_date"], "盘点日期缺省应自动填当天"
        assert len(r["items"]) == 1
        line = r["items"][0]
        assert line["product_name"] == "盘点测试商品"
        assert line["book_quantity"] == 10
        assert line["actual_quantity"] == 13
        assert line["diff_quantity"] == 3, "盈亏应由后端统一算：实盘 - 账面"
        # 盘盈/盘亏分开记，不互相抵消
        assert r["total_profit"] == 3
        assert r["total_loss"] == 0
        assert r["profit_lines"] == 1
        assert r["loss_lines"] == 0
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_stocktaking_book_quantity_auto_filled():
    """不传账面数时按当前现存量带出（盘点底稿路径的核心保障）。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    check_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 12)
        resp = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "actual_quantity": 9}],
                "note": "盘点单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        check_id = r["id"]
        assert r["items"][0]["book_quantity"] == 12
        assert r["items"][0]["diff_quantity"] == -3
        assert r["total_loss"] == 3
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_stocktaking_unit_price_falls_back_to_product_cost():
    """明细不填成本单价时，按商品档案进价补齐，让盈亏金额也能算出来。"""
    product_id = _new_product("盘点成本价商品", 6.0)
    wh = _new_warehouse()
    check_id = None
    try:
        r = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "book_quantity": 0, "actual_quantity": 5}],
                "note": "盘点单测试",
            },
        ).json()
        check_id = r["id"]
        assert r["items"][0]["unit_price"] == 6.0
        assert r["items"][0]["amount"] == 30.0, "盘盈金额 = 盈亏数 × 商品进价"
        assert r["total_amount"] == 30.0
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_stocktaking_duplicate_no_rejected():
    wh = _new_warehouse()
    check_no = _check_no()
    ids = []
    try:
        payload = {"check_no": check_no, "warehouse_id": wh, "note": "盘点单测试"}
        first = client.post("/api/v1/stocktakings", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/stocktakings", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for cid in ids:
            client.delete(f"/api/v1/stocktakings/{cid}")
        _drop_warehouse(wh)


def test_create_stocktaking_missing_warehouse_and_bad_status():
    wh = _new_warehouse()
    try:
        missing = client.post(
            "/api/v1/stocktakings",
            json={"warehouse_id": 99999999, "note": "盘点单测试"},
        )
        assert missing.status_code == 404, missing.text

        bad = client.post(
            "/api/v1/stocktakings",
            json={"warehouse_id": wh, "status": "nonsense", "note": "盘点单测试"},
        )
        assert bad.status_code == 400, bad.text
    finally:
        _drop_warehouse(wh)


# ---------- 库存联动 ----------


def test_stocktaking_adjusts_stock_both_directions():
    """一张盘点单同时盘盈盘亏：盘盈加库存、盘亏减库存，两类流水各自记。"""
    p_up = _new_product("盘盈商品")
    p_down = _new_product("盘亏商品")
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_up = inbound_down = None
    check_id = None
    try:
        inbound_up = _seed_stock(p_up, supplier_id, wh, 10)
        inbound_down = _seed_stock(p_down, supplier_id, wh, 10)
        assert _stock_for(p_up, wh) == 10
        assert _stock_for(p_down, wh) == 10

        resp = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "items": [
                    {"product_id": p_up, "book_quantity": 10, "actual_quantity": 14},
                    {"product_id": p_down, "book_quantity": 10, "actual_quantity": 6},
                ],
                "note": "盘点单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        check_id = r["id"]
        assert r["total_profit"] == 4
        assert r["total_loss"] == 4
        assert r["profit_lines"] == 1
        assert r["loss_lines"] == 1

        # 账实核对后：盘盈商品 10 → 14，盘亏商品 10 → 6
        assert _stock_for(p_up, wh) == 14
        assert _stock_for(p_down, wh) == 6

        rows = _check_rows(check_id)
        assert len(rows) == 2
        types = sorted(row["transaction_type"] for row in rows)
        assert types == ["inbound", "outbound"]

        # 盘点属于纯库存单据，不产生任何财务流水
        fin = client.get("/api/v1/finance").json()
        assert not any(
            row.get("related_type") == "inv_check" for row in fin
        ), "库存盘点只调整现存量，不应写财务流水"
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        for iid in (inbound_up, inbound_down):
            if iid:
                client.delete(f"/api/v1/purchase-orders/{iid}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{p_up}")
        client.delete(f"/api/v1/products/{p_down}")


def test_delete_stocktaking_reverts_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    check_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        check_id = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "book_quantity": 10, "actual_quantity": 7}],
                "note": "盘点单测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 7

        assert client.delete(f"/api/v1/stocktakings/{check_id}").status_code == 204
        assert _stock_for(product_id, wh) == 10, "删盘点单应把盘亏的库存加回来"
        assert _check_rows(check_id) == []
        check_id = None

        assert _stock_for(product_id, wh) == 10, "采购入库的流水仍应保留"
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_stocktaking_replays_stock():
    """改实盘数必须整体重放，否则会留下按旧明细调整过的库存（单边账）。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    check_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        check_id = client.post(
            "/api/v1/stocktakings",
            json={
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "actual_quantity": 13}],
                "note": "盘点单测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 13

        # 实盘 13 → 8（盘点结果改了）：先冲销旧流水，再按新差异重放
        patched = client.patch(
            f"/api/v1/stocktakings/{check_id}",
            json={
                "handler": "改后盘点员",
                "items": [{"product_id": product_id, "book_quantity": 10, "actual_quantity": 8}],
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["handler"] == "改后盘点员"
        assert body["total_profit"] == 0
        assert body["total_loss"] == 2
        assert _stock_for(product_id, wh) == 8
        assert len(_check_rows(check_id)) == 1, "流水应重放而不是累积"
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 盘点底稿 ----------


def test_stocktaking_plan_returns_book_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 15)

        resp = client.get("/api/v1/stocktakings/plan", params={"warehouse_id": wh})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["warehouse_id"] == wh
        assert data["count"] >= 1
        row = next((r for r in data["rows"] if r["product_id"] == product_id), None)
        assert row is not None, "盘点底稿应带出该仓库的账面库存"
        assert row["book_quantity"] == 15

        missing = client.get("/api/v1/stocktakings/plan", params={"warehouse_id": 99999999})
        assert missing.status_code == 404
    finally:
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 状态 / meta / 详情 ----------


def test_stocktaking_list_and_filters():
    wh = _new_warehouse()
    check_no = _check_no()
    check_id = None
    try:
        check_id = client.post(
            "/api/v1/stocktakings",
            json={
                "check_no": check_no,
                "warehouse_id": wh,
                "handler": "关键字盘点员",
                "note": "盘点单测试",
            },
        ).json()["id"]

        listed = client.get("/api/v1/stocktakings").json()
        assert any(row["id"] == check_id for row in listed)

        by_no = client.get("/api/v1/stocktakings", params={"keyword": check_no}).json()
        assert [row["id"] for row in by_no] == [check_id]

        by_wh = client.get("/api/v1/stocktakings", params={"warehouse_id": wh}).json()
        assert any(row["id"] == check_id for row in by_wh)

        by_status = client.get("/api/v1/stocktakings", params={"status": "submitted"}).json()
        assert all(row["status"] == "submitted" for row in by_status)
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        _drop_warehouse(wh)


def test_stocktaking_status_patch_detail_and_meta():
    wh = _new_warehouse()
    check_id = None
    try:
        check_id = client.post(
            "/api/v1/stocktakings",
            json={"check_no": _check_no(), "warehouse_id": wh, "note": "盘点单测试"},
        ).json()["id"]

        detail = client.get(f"/api/v1/stocktakings/{check_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["check_no"].startswith("TEST-PD")

        ok = client.patch(f"/api/v1/stocktakings/{check_id}/status", json={"status": "cancelled"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "cancelled"

        bad = client.patch(f"/api/v1/stocktakings/{check_id}/status", json={"status": "nonsense"})
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/stocktakings/meta")
        assert meta.status_code == 200, meta.text
        assert {item["code"] for item in meta.json()["statuses"]} == {
            "draft", "submitted", "cancelled",
        }

        missing = client.get("/api/v1/stocktakings/99999999")
        assert missing.status_code == 404
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        _drop_warehouse(wh)


# ---------- 打印 ----------


def test_stocktaking_print_pdf():
    product_id = _new_product()
    wh = _new_warehouse()
    check_id = None
    try:
        check_id = client.post(
            "/api/v1/stocktakings",
            json={
                "check_no": _check_no(),
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "book_quantity": 5, "actual_quantity": 7}],
                "note": "盘点单测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/stocktaking/{check_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/stocktaking/99999999")
        assert missing.status_code == 404
    finally:
        if check_id:
            client.delete(f"/api/v1/stocktakings/{check_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")
