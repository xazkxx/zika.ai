"""销售退货单（对齐浩技云「销售管理 → 销售退货」）回归测试（第 2 批 · 第 3 个单据表）。

销售退货是销售开单（出库）的**反向**单据：客户把货退回来，库存增加（inbound 流水）、
应收冲减（sales_return 财务流水，金额记负数、方向 in）。独立成表。

测试数据遵守 scripts/clean_test_data.py 的规则：退货单号用 `TEST-XSTH` 前缀、
备注含「销售退货测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _return_no() -> str:
    return f"TEST-XSTH{uuid.uuid4().hex[:8].upper()}"


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-SRET-{uuid.uuid4().hex[:8]}",
            "name": "销售退货测试商品",
            "purchase_price": 5.0,
            "sale_price": 12.5,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={
            "code": f"CUS-SRET-{uuid.uuid4().hex[:8]}",
            "name": "销售退货测试客户",
            "address": "西安市高新区测试路 8 号",
            "contact": "王经理",
            "contact_phone": "13300000000",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    """退货款来源需要一个供应商来垫底入库。"""
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-SRET-{uuid.uuid4().hex[:8]}", "name": "销售退货测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse() -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-{uuid.uuid4().hex[:8]}", "name": "销售退货主仓"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    """删测试仓库：用 force 强删，否则被库存流水引用时删不掉，会在库里堆积。"""
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _stock_for(product_id: int, warehouse_id: int) -> int:
    """该商品在指定仓库的现存量。"""
    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    rows = data.get("rows", [])
    for row in rows:
        if row.get("warehouse_id") == warehouse_id:
            return int(row.get("quantity") or 0)
    return 0


def _seed_stock(product_id: int, supplier_id: int, warehouse_id: int, qty: int = 10) -> int:
    """用一笔采购入库垫底库存，返回入库单 id。"""
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


# ---------- 创建与金额 ----------


def test_create_return_auto_no_snapshot_and_totals():
    product_id = _new_product()
    customer_id = _new_customer()
    warehouse_id = _new_warehouse()
    return_id = None
    try:
        resp = client.post(
            "/api/v1/sales-returns",
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "businesser": "销售员",
                "return_reason": "客户拒收",
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 12.5}],
                "note": "销售退货测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        return_id = r["id"]
        assert r["return_no"].startswith("XSTH"), r["return_no"]
        assert r["status"] == "submitted"
        assert r["total_amount"] == 37.5
        assert r["amount_chinese"], "金额大写不能为空"
        assert len(r["items"]) == 1
        assert r["items"][0]["amount"] == 37.5
        assert r["items"][0]["product_name"] == "销售退货测试商品"
        assert r["customer_name"] == "销售退货测试客户"
        assert r["contact"] == "王经理"
        assert r["contact_phone"] == "13300000000"
        assert r["return_date"], "退货日期缺省应自动填当天"
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_return_duplicate_no_rejected():
    customer_id = _new_customer()
    return_no = _return_no()
    ids = []
    try:
        first = client.post(
            "/api/v1/sales-returns",
            json={"return_no": return_no, "customer_id": customer_id, "note": "销售退货测试"},
        )
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post(
            "/api/v1/sales-returns",
            json={"return_no": return_no, "customer_id": customer_id, "note": "销售退货测试"},
        )
        assert dup.status_code == 400, dup.text
    finally:
        for rid in ids:
            client.delete(f"/api/v1/sales-returns/{rid}")
        client.delete(f"/api/v1/customers/{customer_id}")


def test_create_return_customer_not_found():
    resp = client.post(
        "/api/v1/sales-returns",
        json={"customer_id": 99999999, "note": "销售退货测试"},
    )
    assert resp.status_code == 404, resp.text


def test_create_return_invalid_status():
    customer_id = _new_customer()
    try:
        resp = client.post(
            "/api/v1/sales-returns",
            json={"customer_id": customer_id, "status": "nonsense", "note": "销售退货测试"},
        )
        assert resp.status_code == 400, resp.text
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")


# ---------- 库存 / 财务联动 ----------


def test_return_increases_stock_and_writes_negative_receivable():
    product_id = _new_product()
    customer_id = _new_customer()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    return_id = None
    inbound_id = None
    try:
        # 先入库 10 件垫底
        inbound_id = _seed_stock(product_id, supplier_id, warehouse_id, 10)
        assert _stock_for(product_id, warehouse_id) == 10

        # 出库 8 件（客户买走）
        outbound = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "outbound",
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 8, "unit_price": 12.5}],
            },
        )
        assert outbound.status_code == 201, outbound.text
        outbound_id = outbound.json()["id"]
        assert _stock_for(product_id, warehouse_id) == 2

        # 退 3 件回来
        resp = client.post(
            "/api/v1/sales-returns",
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 12.5}],
                "note": "销售退货测试",
            },
        )
        assert resp.status_code == 201, resp.text
        return_id = resp.json()["id"]

        # 库存 2 → 5
        assert _stock_for(product_id, warehouse_id) == 5

        # 财务：产生一条 sales_return、金额为负的应收流水
        fin = client.get("/api/v1/finance").json()
        matched = [
            row for row in fin
            if row.get("related_type") == "sales_return" and row.get("related_order_id") == return_id
        ]
        assert len(matched) == 1
        assert matched[0]["amount"] == -37.5
        assert matched[0]["direction"] == "in"
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        if "outbound_id" in dir():
            client.delete(f"/api/v1/sales-orders/{outbound_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_return_reverts_stock_and_finance():
    product_id = _new_product()
    customer_id = _new_customer()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    return_id = None
    inbound_id = None
    outbound_id = None
    try:
        inbound_id = _seed_stock(product_id, supplier_id, warehouse_id, 10)
        outbound = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "outbound",
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 8, "unit_price": 12.5}],
            },
        ).json()
        outbound_id = outbound["id"]
        assert _stock_for(product_id, warehouse_id) == 2

        ret = client.post(
            "/api/v1/sales-returns",
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 12.5}],
                "note": "销售退货测试",
            },
        ).json()
        return_id = ret["id"]
        assert _stock_for(product_id, warehouse_id) == 5

        # 删退货单：库存 5 → 2，应收冲减流水被删除
        assert client.delete(f"/api/v1/sales-returns/{return_id}").status_code == 204
        return_id = None
        assert _stock_for(product_id, warehouse_id) == 2

        fin = client.get("/api/v1/finance").json()
        assert not any(
            row.get("related_type") == "sales_return" for row in fin
        ), "删单后销售退货财务流水应被冲销"

        # 销售出库的应收流水仍应保留
        assert any(
            row.get("related_type") == "sales_out" and row.get("related_order_id") == outbound_id
            for row in fin
        )
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        if outbound_id:
            client.delete(f"/api/v1/sales-orders/{outbound_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 筛选 ----------


def test_return_list_and_filters():
    customer_id = _new_customer()
    return_no = _return_no()
    return_id = None
    try:
        created = client.post(
            "/api/v1/sales-returns",
            json={"return_no": return_no, "customer_id": customer_id, "businesser": "关键字业务员", "note": "销售退货测试"},
        ).json()
        return_id = created["id"]

        listed = client.get("/api/v1/sales-returns")
        assert listed.status_code == 200
        assert any(row["id"] == return_id for row in listed.json())

        by_no = client.get("/api/v1/sales-returns", params={"keyword": return_no}).json()
        assert [row["id"] for row in by_no] == [return_id]

        by_customer = client.get("/api/v1/sales-returns", params={"customer_id": customer_id}).json()
        assert any(row["id"] == return_id for row in by_customer)

        by_status = client.get("/api/v1/sales-returns", params={"status": "submitted"}).json()
        assert all(row["status"] == "submitted" for row in by_status)
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


# ---------- 编辑 / 状态 / meta ----------


def test_update_return_replaces_items_and_recomputes():
    product_id = _new_product()
    customer_id = _new_customer()
    return_id = None
    try:
        r = client.post(
            "/api/v1/sales-returns",
            json={
                "return_no": _return_no(),
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
                "note": "销售退货测试",
            },
        ).json()
        return_id = r["id"]

        patched = client.patch(
            f"/api/v1/sales-returns/{return_id}",
            json={
                "return_reason": "改后退货原因",
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 8.0}],
            },
        )
        assert patched.status_code == 200, patched.text
        row = patched.json()
        assert row["return_reason"] == "改后退货原因"
        assert row["total_amount"] == 32.0
        assert len(row["items"]) == 1
        assert row["items"][0]["amount"] == 32.0
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_return_status_patch_and_invalid_value():
    customer_id = _new_customer()
    return_id = None
    try:
        r = client.post(
            "/api/v1/sales-returns",
            json={"return_no": _return_no(), "customer_id": customer_id, "note": "销售退货测试"},
        ).json()
        return_id = r["id"]

        ok = client.patch(f"/api/v1/sales-returns/{return_id}/status", json={"status": "cancelled"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "cancelled"

        bad = client.patch(f"/api/v1/sales-returns/{return_id}/status", json={"status": "nonsense"})
        assert bad.status_code == 400, bad.text
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


def test_return_meta_dictionaries():
    meta = client.get("/api/v1/sales-returns/meta")
    assert meta.status_code == 200, meta.text
    data = meta.json()
    assert {item["code"] for item in data["statuses"]} == {"draft", "submitted", "cancelled"}


# ---------- 打印 ----------


def test_return_print_pdf():
    product_id = _new_product()
    customer_id = _new_customer()
    return_id = None
    try:
        r = client.post(
            "/api/v1/sales-returns",
            json={
                "return_no": _return_no(),
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 6.0}],
                "note": "销售退货测试",
            },
        ).json()
        return_id = r["id"]

        pdf = client.get(f"/api/v1/print/sales-return/{return_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/sales-return/99999999")
        assert missing.status_code == 404
    finally:
        if return_id:
            client.delete(f"/api/v1/sales-returns/{return_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")
