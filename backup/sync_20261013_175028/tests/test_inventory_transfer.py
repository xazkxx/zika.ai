"""库存调拨单（对齐浩技云「库存管理 → 调拨管理」）回归测试（第 2 批 · 第 4 个单据表）。

调拨是同一企业内部的库存位置转移：货物从调出仓库搬到调入仓库，总量与资产总额
都不变，因此**只写库存流水、不写财务流水**。每条明细生成两条方向相反的流水
（调出 outbound / 调入 inbound），共用 related_type="inv_transfer"，
删单时一次把两条都冲掉、两侧仓库同时复原。

测试数据遵守 scripts/clean_test_data.py 的规则：调拨单号用 `TEST-DBD` 前缀、
备注含「调拨单测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _transfer_no() -> str:
    return f"TEST-DBD{uuid.uuid4().hex[:8].upper()}"


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-TRF-{uuid.uuid4().hex[:8]}",
            "name": "调拨测试商品",
            "purchase_price": 5.0,
            "sale_price": 12.5,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-TRF-{uuid.uuid4().hex[:8]}", "name": "调拨测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "调拨主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-{uuid.uuid4().hex[:8]}", "name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    """删测试仓库：用 force 强删，否则被库存流水引用时删不掉，会在库里堆积。"""
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _stock_for(product_id: int, warehouse_id: int) -> int:
    """该商品在指定仓库的现存量。"""
    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    for row in data.get("rows", []):
        if row.get("warehouse_id") == warehouse_id:
            return int(row.get("quantity") or 0)
    return 0


def _seed_stock(product_id: int, supplier_id: int, warehouse_id: int, qty: int = 10) -> int:
    """用一笔采购入库给调出仓垫底库存，返回入库单 id。"""
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


def _transfer_rows(transfer_id: int) -> list[dict]:
    """这张调拨单产生的库存流水。"""
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == "inv_transfer" and row.get("related_order_id") == transfer_id
    ]


# ---------- 创建与单据头 ----------


def test_create_transfer_auto_no_snapshot_and_total():
    product_id = _new_product()
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    transfer_id = None
    try:
        resp = client.post(
            "/api/v1/inventory-transfers",
            json={
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "handler": "仓管员",
                "reason": "门店补货",
                "items": [{"product_id": product_id, "quantity": 4}],
                "note": "调拨单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        transfer_id = r["id"]
        assert r["transfer_no"].startswith("DBD"), r["transfer_no"]
        assert r["status"] == "submitted"
        assert r["total_quantity"] == 4
        assert r["from_warehouse_id"] == from_wh
        assert r["to_warehouse_id"] == to_wh
        assert r["transfer_date"], "调拨日期缺省应自动填当天"
        assert len(r["items"]) == 1
        assert r["items"][0]["product_name"] == "调拨测试商品"
        assert r["items"][0]["quantity"] == 4
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)
        client.delete(f"/api/v1/products/{product_id}")


def test_create_transfer_duplicate_no_rejected():
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    transfer_no = _transfer_no()
    ids = []
    try:
        payload = {
            "transfer_no": transfer_no,
            "from_warehouse_id": from_wh,
            "to_warehouse_id": to_wh,
            "note": "调拨单测试",
        }
        first = client.post("/api/v1/inventory-transfers", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/inventory-transfers", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for tid in ids:
            client.delete(f"/api/v1/inventory-transfers/{tid}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)


def test_create_transfer_same_or_missing_warehouse_rejected():
    wh = _new_warehouse("调拨主仓")
    try:
        same = client.post(
            "/api/v1/inventory-transfers",
            json={"from_warehouse_id": wh, "to_warehouse_id": wh, "note": "调拨单测试"},
        )
        assert same.status_code == 400, same.text
        assert "不能相同" in same.json()["detail"]

        missing = client.post(
            "/api/v1/inventory-transfers",
            json={"from_warehouse_id": 99999999, "to_warehouse_id": wh, "note": "调拨单测试"},
        )
        assert missing.status_code == 404, missing.text
    finally:
        _drop_warehouse(wh)


def test_create_transfer_invalid_status():
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    try:
        resp = client.post(
            "/api/v1/inventory-transfers",
            json={
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "status": "nonsense",
                "note": "调拨单测试",
            },
        )
        assert resp.status_code == 400, resp.text
    finally:
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)


# ---------- 库存联动 ----------


def test_transfer_moves_stock_between_warehouses():
    product_id = _new_product()
    supplier_id = _new_supplier()
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    inbound_id = None
    transfer_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, from_wh, 10)
        assert _stock_for(product_id, from_wh) == 10
        assert _stock_for(product_id, to_wh) == 0

        resp = client.post(
            "/api/v1/inventory-transfers",
            json={
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "items": [{"product_id": product_id, "quantity": 6}],
                "note": "调拨单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        transfer_id = resp.json()["id"]

        # 调出仓 10 → 4，调入仓 0 → 6（总量守恒）
        assert _stock_for(product_id, from_wh) == 4
        assert _stock_for(product_id, to_wh) == 6

        # 一条 outbound + 一条 inbound，共用 related_type=inv_transfer
        rows = _transfer_rows(transfer_id)
        assert len(rows) == 2
        types = sorted(row["transaction_type"] for row in rows)
        assert types == ["inbound", "outbound"]
        assert {row["warehouse_id"] for row in rows} == {from_wh, to_wh}

        # 调拨不产生任何财务流水
        fin = client.get("/api/v1/finance").json()
        assert not any(
            row.get("related_type") == "inv_transfer" for row in fin
        ), "库存调拨属于内部位置转移，不应写财务流水"
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_transfer_reverts_both_warehouses():
    product_id = _new_product()
    supplier_id = _new_supplier()
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    inbound_id = None
    transfer_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, from_wh, 10)

        transfer_id = client.post(
            "/api/v1/inventory-transfers",
            json={
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "items": [{"product_id": product_id, "quantity": 6}],
                "note": "调拨单测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, from_wh) == 4
        assert _stock_for(product_id, to_wh) == 6

        # 删调拨单：两侧仓库同时复原
        assert client.delete(f"/api/v1/inventory-transfers/{transfer_id}").status_code == 204
        assert _stock_for(product_id, from_wh) == 10
        assert _stock_for(product_id, to_wh) == 0
        assert _transfer_rows(transfer_id) == []
        transfer_id = None

        # 采购入库的流水仍应保留
        assert _stock_for(product_id, from_wh) == 10
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_transfer_replays_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    inbound_id = None
    transfer_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, from_wh, 10)

        transfer_id = client.post(
            "/api/v1/inventory-transfers",
            json={
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "items": [{"product_id": product_id, "quantity": 3}],
                "note": "调拨单测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, from_wh) == 7
        assert _stock_for(product_id, to_wh) == 3

        # 把数量从 3 改成 8：旧流水冲销、按新数量重放
        patched = client.patch(
            f"/api/v1/inventory-transfers/{transfer_id}",
            json={"reason": "改后原因", "items": [{"product_id": product_id, "quantity": 8}]},
        )
        assert patched.status_code == 200, patched.text
        row = patched.json()
        assert row["reason"] == "改后原因"
        assert row["total_quantity"] == 8
        assert _stock_for(product_id, from_wh) == 2
        assert _stock_for(product_id, to_wh) == 8
        # 流水不重复累积：仍是 2 条
        assert len(_transfer_rows(transfer_id)) == 2
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 筛选 ----------


def test_transfer_list_and_filters():
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    transfer_no = _transfer_no()
    transfer_id = None
    try:
        created = client.post(
            "/api/v1/inventory-transfers",
            json={
                "transfer_no": transfer_no,
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "handler": "关键字经办人",
                "note": "调拨单测试",
            },
        ).json()
        transfer_id = created["id"]

        listed = client.get("/api/v1/inventory-transfers").json()
        assert any(row["id"] == transfer_id for row in listed)

        by_no = client.get("/api/v1/inventory-transfers", params={"keyword": transfer_no}).json()
        assert [row["id"] for row in by_no] == [transfer_id]

        by_wh = client.get("/api/v1/inventory-transfers", params={"warehouse_id": to_wh}).json()
        assert any(row["id"] == transfer_id for row in by_wh)

        by_status = client.get("/api/v1/inventory-transfers", params={"status": "submitted"}).json()
        assert all(row["status"] == "submitted" for row in by_status)
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)


# ---------- 状态 / meta / 详情 ----------


def test_transfer_status_patch_and_detail():
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    transfer_id = None
    try:
        transfer_id = client.post(
            "/api/v1/inventory-transfers",
            json={
                "transfer_no": _transfer_no(),
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "note": "调拨单测试",
            },
        ).json()["id"]

        detail = client.get(f"/api/v1/inventory-transfers/{transfer_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["transfer_no"].startswith("TEST-DBD")

        ok = client.patch(f"/api/v1/inventory-transfers/{transfer_id}/status", json={"status": "cancelled"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "cancelled"

        bad = client.patch(f"/api/v1/inventory-transfers/{transfer_id}/status", json={"status": "nonsense"})
        assert bad.status_code == 400, bad.text

        missing = client.get("/api/v1/inventory-transfers/99999999")
        assert missing.status_code == 404
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)


def test_transfer_meta_dictionaries():
    meta = client.get("/api/v1/inventory-transfers/meta")
    assert meta.status_code == 200, meta.text
    data = meta.json()
    assert {item["code"] for item in data["statuses"]} == {"draft", "submitted", "cancelled"}


# ---------- 打印 ----------


def test_transfer_print_pdf():
    product_id = _new_product()
    from_wh = _new_warehouse("调拨主仓")
    to_wh = _new_warehouse("调拨主仓二")
    transfer_id = None
    try:
        transfer_id = client.post(
            "/api/v1/inventory-transfers",
            json={
                "transfer_no": _transfer_no(),
                "from_warehouse_id": from_wh,
                "to_warehouse_id": to_wh,
                "items": [{"product_id": product_id, "quantity": 2}],
                "note": "调拨单测试",
            },
        ).json()["id"]

        pdf = client.get(f"/api/v1/print/inventory-transfer/{transfer_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/inventory-transfer/99999999")
        assert missing.status_code == 404
    finally:
        if transfer_id:
            client.delete(f"/api/v1/inventory-transfers/{transfer_id}")
        _drop_warehouse(from_wh)
        _drop_warehouse(to_wh)
        client.delete(f"/api/v1/products/{product_id}")
