"""库存报损报溢单（对齐浩技云「库存管理 → 报损报溢」）回归测试。

报损与报溢是同一张表的两个方向，用 adjust_type 区分：

| adjust_type | 含义 | 库存方向 | 单号前缀 | 库存流水 related_type |
|---|---|---|---|---|
| scrap     | 报损 | 减少 outbound | BS | inv_scrap |
| overflow  | 报溢 | 增加 inbound  | BY | inv_overflow |

明细数量恒正，方向完全由单据头决定。与调拨、盘点同属**纯库存单据**：
只写库存流水、不写财务流水（反向断言锁死）。

测试数据遵守 scripts/clean_test_data.py 的规则：单号用 `TEST-BS` / `TEST-BY`
前缀、备注含「报损报溢测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SCRAP = "scrap"
OVERFLOW = "overflow"


def _adjust_no(kind: str = "BS") -> str:
    return f"TEST-{kind}{uuid.uuid4().hex[:8].upper()}"


def _new_product(name: str = "报损报溢测试商品", price: float = 8.0) -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-ADJ-{uuid.uuid4().hex[:8]}",
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
        json={"code": f"SUP-ADJ-{uuid.uuid4().hex[:8]}", "name": "报损报溢测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse(name: str = "报损主仓") -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-ADJ-{uuid.uuid4().hex[:8]}", "name": name},
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


def _adjust_rows(adjust_id: int, doc_type: str) -> list[dict]:
    log = client.get("/api/v1/inventory").json()
    return [
        row for row in log
        if row.get("related_type") == doc_type and row.get("related_order_id") == adjust_id
    ]


# ---------- 创建 ----------


def test_create_scrap_reduces_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)

        resp = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "handler": "仓管员",
                "reason": "包装破损报废",
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        adjust_id = r["id"]
        assert r["adjust_no"].startswith("BS"), r["adjust_no"]
        assert r["adjust_type"] == SCRAP
        assert r["status"] == "submitted"
        assert r["adjust_date"], "单据日期缺省应自动填当天"
        assert r["total_quantity"] == 3
        assert r["total_amount"] == 24.0
        assert r["items"][0]["product_name"] == "报损报溢测试商品"

        # 报损：库存减少
        assert _stock_for(product_id, wh) == 7
        rows = _adjust_rows(adjust_id, "inv_scrap")
        assert len(rows) == 1
        assert rows[0]["transaction_type"] == "outbound"

        # 纯库存单据：不写财务流水
        fin = client.get("/api/v1/finance").json()
        assert not any(
            row.get("related_type") in ("inv_scrap", "inv_overflow") for row in fin
        ), "报损报溢只调整现存量，不应写财务流水"
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_overflow_increases_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)

        resp = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": OVERFLOW,
                "warehouse_id": wh,
                "reason": "入库少记补登",
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        adjust_id = r["id"]
        assert r["adjust_no"].startswith("BY"), r["adjust_no"]
        assert r["adjust_type"] == OVERFLOW
        assert r["total_quantity"] == 4
        assert r["total_amount"] == 32.0

        # 报溢：库存增加
        assert _stock_for(product_id, wh) == 14
        rows = _adjust_rows(adjust_id, "inv_overflow")
        assert len(rows) == 1
        assert rows[0]["transaction_type"] == "inbound"
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_adjustment_duplicate_no_rejected():
    wh = _new_warehouse()
    adjust_no = _adjust_no()
    ids = []
    try:
        payload = {
            "adjust_no": adjust_no,
            "adjust_type": SCRAP,
            "warehouse_id": wh,
            "note": "报损报溢测试",
        }
        first = client.post("/api/v1/inventory-adjustments", json=payload)
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post("/api/v1/inventory-adjustments", json=payload)
        assert dup.status_code == 400, dup.text
    finally:
        for aid in ids:
            client.delete(f"/api/v1/inventory-adjustments/{aid}")
        _drop_warehouse(wh)


def test_create_adjustment_rejects_bad_type_and_missing_warehouse():
    wh = _new_warehouse()
    try:
        bad_type = client.post(
            "/api/v1/inventory-adjustments",
            json={"adjust_type": "nonsense", "warehouse_id": wh, "note": "报损报溢测试"},
        )
        assert bad_type.status_code == 400, bad_type.text

        missing = client.post(
            "/api/v1/inventory-adjustments",
            json={"adjust_type": SCRAP, "warehouse_id": 99999999, "note": "报损报溢测试"},
        )
        assert missing.status_code == 404, missing.text

        bad_status = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "status": "nonsense",
                "note": "报损报溢测试",
            },
        )
        assert bad_status.status_code == 400, bad_status.text
    finally:
        _drop_warehouse(wh)


def test_create_adjustment_negative_quantity_normalized():
    """明细数量恒正：业务传 -5 也按 5 记录，方向只看单据头。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        r = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": -5, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        ).json()
        adjust_id = r["id"]
        assert r["total_quantity"] == 5
        assert _stock_for(product_id, wh) == 5, "报损 5 件：10 → 5"
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 库存回滚与重放 ----------


def test_delete_adjustment_reverts_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        adjust_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 6

        assert client.delete(f"/api/v1/inventory-adjustments/{adjust_id}").status_code == 204
        assert _stock_for(product_id, wh) == 10, "删报损单应把减掉的库存加回来"
        assert _adjust_rows(adjust_id, "inv_scrap") == []
        assert _adjust_rows(adjust_id, "inv_overflow") == []
        adjust_id = None
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_adjustment_quantity_replays_stock():
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 20)
        adjust_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 17

        patched = client.patch(
            f"/api/v1/inventory-adjustments/{adjust_id}",
            json={
                "reason": "改后原因",
                "items": [{"product_id": product_id, "quantity": 9, "unit_price": 8.0}],
            },
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert body["reason"] == "改后原因"
        assert body["total_quantity"] == 9
        assert body["total_amount"] == 72.0
        assert _stock_for(product_id, wh) == 11
        assert len(_adjust_rows(adjust_id, "inv_scrap")) == 1, "流水应重放而不是累积"
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_adjustment_type_flips_direction():
    """报损改报溢 = 方向翻转：旧流水冲销、按新方向重放，只剩 1 条。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    wh = _new_warehouse()
    inbound_id = None
    adjust_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, wh, 10)
        adjust_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 8.0}],
                "note": "报损报溢测试",
            },
        ).json()["id"]
        assert _stock_for(product_id, wh) == 8

        flipped = client.patch(
            f"/api/v1/inventory-adjustments/{adjust_id}",
            json={"adjust_type": OVERFLOW},
        )
        assert flipped.status_code == 200, flipped.text
        assert flipped.json()["adjust_type"] == OVERFLOW

        # 10 - 2（旧报损冲销回来） + 2（新报溢）= 12
        assert _stock_for(product_id, wh) == 12
        assert _adjust_rows(adjust_id, "inv_scrap") == []
        assert len(_adjust_rows(adjust_id, "inv_overflow")) == 1

        bad = client.patch(
            f"/api/v1/inventory-adjustments/{adjust_id}",
            json={"adjust_type": "nonsense"},
        )
        assert bad.status_code == 400, bad.text
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 状态 / meta / 详情 / 打印 ----------


def test_adjustment_list_filters_by_type_and_status():
    wh = _new_warehouse()
    scrap_no = _adjust_no("BS")
    overflow_no = _adjust_no("BY")
    ids = []
    try:
        scrap_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_no": scrap_no,
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "note": "报损报溢测试",
            },
        ).json()["id"]
        ids.append(scrap_id)
        overflow_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_no": overflow_no,
                "adjust_type": OVERFLOW,
                "warehouse_id": wh,
                "note": "报损报溢测试",
            },
        ).json()["id"]
        ids.append(overflow_id)

        by_no = client.get("/api/v1/inventory-adjustments", params={"keyword": scrap_no}).json()
        assert [row["id"] for row in by_no] == [scrap_id]

        scraps = client.get("/api/v1/inventory-adjustments", params={"adjust_type": SCRAP}).json()
        assert all(row["adjust_type"] == SCRAP for row in scraps)
        assert any(row["id"] == scrap_id for row in scraps)
        assert not any(row["id"] == overflow_id for row in scraps)

        by_status = client.get(
            "/api/v1/inventory-adjustments", params={"status": "submitted"}
        ).json()
        assert all(row["status"] == "submitted" for row in by_status)
    finally:
        for aid in ids:
            client.delete(f"/api/v1/inventory-adjustments/{aid}")
        _drop_warehouse(wh)


def test_adjustment_status_patch_detail_and_meta():
    wh = _new_warehouse()
    adjust_id = None
    try:
        adjust_id = client.post(
            "/api/v1/inventory-adjustments",
            json={
                "adjust_no": _adjust_no(),
                "adjust_type": SCRAP,
                "warehouse_id": wh,
                "note": "报损报溢测试",
            },
        ).json()["id"]

        detail = client.get(f"/api/v1/inventory-adjustments/{adjust_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["adjust_no"].startswith("TEST-BS")

        ok = client.patch(
            f"/api/v1/inventory-adjustments/{adjust_id}/status", json={"status": "cancelled"}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "cancelled"

        bad = client.patch(
            f"/api/v1/inventory-adjustments/{adjust_id}/status", json={"status": "nonsense"}
        )
        assert bad.status_code == 400, bad.text

        meta = client.get("/api/v1/inventory-adjustments/meta")
        assert meta.status_code == 200, meta.text
        data = meta.json()
        types = {item["code"]: item for item in data["types"]}
        assert set(types) == {SCRAP, OVERFLOW}
        assert types[SCRAP]["direction"] == "outbound"
        assert types[OVERFLOW]["direction"] == "inbound"
        assert {item["code"] for item in data["statuses"]} == {"draft", "submitted", "cancelled"}

        missing = client.get("/api/v1/inventory-adjustments/99999999")
        assert missing.status_code == 404
    finally:
        if adjust_id:
            client.delete(f"/api/v1/inventory-adjustments/{adjust_id}")
        _drop_warehouse(wh)


def test_adjustment_print_pdf_both_kinds():
    product_id = _new_product()
    wh = _new_warehouse()
    ids = []
    try:
        for kind, doc_type in ((SCRAP, "inventory-scrap"), (OVERFLOW, "inventory-overflow")):
            adjust_id = client.post(
                "/api/v1/inventory-adjustments",
                json={
                    "adjust_no": _adjust_no("BS" if kind == SCRAP else "BY"),
                    "adjust_type": kind,
                    "warehouse_id": wh,
                    "items": [{"product_id": product_id, "quantity": 2, "unit_price": 8.0}],
                    "note": "报损报溢测试",
                },
            ).json()["id"]
            ids.append(adjust_id)

            pdf = client.get(f"/api/v1/print/{doc_type}/{adjust_id}")
            assert pdf.status_code == 200, pdf.text
            assert pdf.headers["content-type"] == "application/pdf"
            assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/inventory-scrap/99999999")
        assert missing.status_code == 404
    finally:
        for aid in ids:
            client.delete(f"/api/v1/inventory-adjustments/{aid}")
        _drop_warehouse(wh)
        client.delete(f"/api/v1/products/{product_id}")
