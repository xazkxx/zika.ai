"""销售报价单（对齐浩技云「销售 → 报价单」）回归测试（第 2 批 · 首个单据表）。

报价单是**商务意向文件**：报价本身不产生应收、不扣库存，客户确认后靠
`POST /quotations/{id}/to-order` 转成销售订单（`doc_type='order'`），
再由订单走单据链路 —— 与购销合同同一条链路。

测试数据遵守 scripts/clean_test_data.py 的规则：报价单号用 `TEST-` 前缀、
备注含「报价单测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _quote_no() -> str:
    return f"TEST-BJ{uuid.uuid4().hex[:8].upper()}"


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-QTN-{uuid.uuid4().hex[:8]}",
            "name": "报价单测试商品",
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
            "code": f"CUST-QTN-{uuid.uuid4().hex[:8]}",
            "name": "报价单测试客户",
            "address": "西安市莲湖区测试路 1 号",
            "contact": "杨主任",
            "phone": "15300000000",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _flow_counts() -> tuple[int, int]:
    """(库存流水条数, 财务流水条数) —— 用于验证报价单不触碰库存与财务。"""
    inv = client.get("/api/v1/inventory")
    fin = client.get("/api/v1/finance")
    assert inv.status_code == 200 and fin.status_code == 200
    return len(inv.json()), len(fin.json())


# ---------- 创建与列表 ----------


def test_create_quotation_auto_no_and_totals():
    product_id = _new_product()
    customer_id = _new_customer()
    before = _flow_counts()
    quote_id = None
    try:
        resp = client.post(
            "/api/v1/quotations",
            json={
                "customer_id": customer_id,
                "businesser": "范先生",
                "payment_method": "银行转账",
                "transport_method": "货运",
                "items": [{"product_id": product_id, "quantity": 10, "unit_price": 12.5}],
                "note": "报价单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        q = resp.json()
        quote_id = q["id"]
        # 自动单号 BJ+日期+流水；默认草稿
        assert q["quote_no"].startswith("BJ"), q["quote_no"]
        assert q["status"] == "draft"
        assert q["total_quantity"] == 10.0
        assert q["total_amount"] == 125.0
        assert q["amount_chinese"], "金额大写不能为空"
        assert len(q["items"]) == 1
        assert q["items"][0]["amount"] == 125.0
        assert q["items"][0]["product_name"] == "报价单测试商品"
        assert q["quote_date"], "报价日期缺省应自动填当天"
        # 报价单不产生库存 / 财务流水
        assert _flow_counts() == before
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_quotation_snapshots_customer_profile():
    """选了客户要把档案里的名称/地址/联系人/电话带出（快照，与档案解耦）。"""
    customer_id = _new_customer()
    quote_id = None
    try:
        q = client.post(
            "/api/v1/quotations",
            json={"quote_no": _quote_no(), "customer_id": customer_id, "note": "报价单测试"},
        )
        assert q.status_code == 201, q.text
        row = q.json()
        quote_id = row["id"]
        assert row["customer_name"] == "报价单测试客户"
        assert row["customer_address"] == "西安市莲湖区测试路 1 号"
        assert row["contact"] == "杨主任"
        assert row["contact_phone"] == "15300000000"
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


def test_quotation_duplicate_no_rejected_and_empty_items_allowed():
    """单号重复 400；无明细也允许（浩技云历史导入数据只含单头）。"""
    customer_id = _new_customer()
    quote_no = _quote_no()
    ids = []
    try:
        first = client.post(
            "/api/v1/quotations",
            json={"quote_no": quote_no, "customer_id": customer_id, "note": "报价单测试"},
        )
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])
        assert first.json()["items"] == []
        assert first.json()["total_amount"] == 0.0

        dup = client.post(
            "/api/v1/quotations",
            json={"quote_no": quote_no, "customer_id": customer_id, "note": "报价单测试"},
        )
        assert dup.status_code == 400, dup.text
    finally:
        for qid in ids:
            client.delete(f"/api/v1/quotations/{qid}")
        client.delete(f"/api/v1/customers/{customer_id}")


def test_quotation_list_and_keyword_filter():
    customer_id = _new_customer()
    quote_no = _quote_no()
    quote_id = None
    try:
        created = client.post(
            "/api/v1/quotations",
            json={"quote_no": quote_no, "customer_id": customer_id, "businesser": "关键词业务员", "note": "报价单测试"},
        )
        quote_id = created.json()["id"]

        listed = client.get("/api/v1/quotations")
        assert listed.status_code == 200
        assert any(row["id"] == quote_id for row in listed.json())

        by_no = client.get("/api/v1/quotations", params={"keyword": quote_no}).json()
        assert [row["id"] for row in by_no] == [quote_id]

        by_customer = client.get("/api/v1/quotations", params={"customer_id": customer_id}).json()
        assert any(row["id"] == quote_id for row in by_customer)

        by_status = client.get("/api/v1/quotations", params={"status": "draft"}).json()
        assert all(row["status"] == "draft" for row in by_status)
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


# ---------- 编辑与状态 ----------


def test_update_quotation_replaces_items_and_recomputes():
    product_id = _new_product()
    customer_id = _new_customer()
    quote_id = None
    try:
        q = client.post(
            "/api/v1/quotations",
            json={
                "quote_no": _quote_no(),
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
                "note": "报价单测试",
            },
        ).json()
        quote_id = q["id"]

        patched = client.patch(
            f"/api/v1/quotations/{quote_id}",
            json={
                "businesser": "改后业务员",
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 8.0}],
            },
        )
        assert patched.status_code == 200, patched.text
        row = patched.json()
        assert row["businesser"] == "改后业务员"
        assert row["total_quantity"] == 4.0
        assert row["total_amount"] == 32.0
        assert len(row["items"]) == 1
        assert row["items"][0]["amount"] == 32.0
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_quotation_status_patch_and_invalid_value():
    customer_id = _new_customer()
    quote_id = None
    try:
        q = client.post(
            "/api/v1/quotations",
            json={"quote_no": _quote_no(), "customer_id": customer_id, "note": "报价单测试"},
        ).json()
        quote_id = q["id"]

        ok = client.patch(f"/api/v1/quotations/{quote_id}/status", json={"status": "quoted"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "quoted"

        bad = client.patch(f"/api/v1/quotations/{quote_id}/status", json={"status": "nonsense"})
        assert bad.status_code == 400, bad.text
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


def test_quotation_meta_dictionaries():
    meta = client.get("/api/v1/quotations/meta")
    assert meta.status_code == 200, meta.text
    data = meta.json()
    assert {item["code"] for item in data["statuses"]} == {"draft", "quoted", "accepted", "rejected", "void"}
    assert "银行转账" in data["payment_methods"]
    assert "货运" in data["transport_methods"]


# ---------- 一键转销售订单 ----------


def test_quotation_to_order_full_chain():
    product_id = _new_product()
    customer_id = _new_customer()
    quote_id = None
    try:
        q = client.post(
            "/api/v1/quotations",
            json={
                "quote_no": _quote_no(),
                "customer_id": customer_id,
                "businesser": "范先生",
                "items": [{"product_id": product_id, "quantity": 5, "unit_price": 8.0}],
                "note": "报价单测试",
            },
        ).json()
        quote_id = q["id"]

        resp = client.post(f"/api/v1/quotations/{quote_id}/to-order")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["order_type"] == "sales_order"
        order_id = data["order_id"]

        # 报价单回填订单号，状态推进到已接受
        detail = client.get(f"/api/v1/quotations/{quote_id}").json()
        assert detail["order_id"] == order_id
        assert detail["order_no"] == data["order_no"]
        assert detail["status"] == "accepted"

        # 生成的销售订单是 doc_type=order：只订货，不动库存、不写财务
        orders = client.get("/api/v1/sales-orders", params={"doc_type": "order"}).json()
        target = next(row for row in orders if row["id"] == order_id)
        assert target["doc_type"] == "order"
        assert target["customer_id"] == customer_id
        assert target["total_amount"] == 40.0
        assert target["note"] == f"由报价单 {detail['quote_no']} 生成"

        # 重复转单 409；已转单不允许直接删
        assert client.post(f"/api/v1/quotations/{quote_id}/to-order").status_code == 409
        assert client.delete(f"/api/v1/quotations/{quote_id}").status_code == 409
        # references 能看到关联订单
        refs = client.get(f"/api/v1/quotations/{quote_id}/references")
        assert refs.status_code == 200
        assert refs.json()["references"][0]["doc_no"] == data["order_no"]

        # 先删该销售订单，再 force 删报价单
        assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code == 204
        assert client.delete(f"/api/v1/quotations/{quote_id}", params={"force": True}).status_code == 204
        quote_id = None
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}", params={"force": True})
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_quotation_to_order_requires_items_and_customer():
    product_id = _new_product()
    customer_id = _new_customer()
    ids = []
    try:
        # 无明细 → 400
        no_items = client.post(
            "/api/v1/quotations",
            json={"quote_no": _quote_no(), "customer_id": customer_id, "note": "报价单测试"},
        ).json()
        ids.append(no_items["id"])
        assert client.post(f"/api/v1/quotations/{no_items['id']}/to-order").status_code == 400

        # 有明细但没关联客户 → 400
        no_customer = client.post(
            "/api/v1/quotations",
            json={
                "quote_no": _quote_no(),
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 1.0}],
                "note": "报价单测试",
            },
        ).json()
        ids.append(no_customer["id"])
        assert client.post(f"/api/v1/quotations/{no_customer['id']}/to-order").status_code == 400

        # 已作废的报价单不能转单
        voided = client.post(
            "/api/v1/quotations",
            json={
                "quote_no": _quote_no(),
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 1.0}],
                "note": "报价单测试",
            },
        ).json()
        ids.append(voided["id"])
        client.patch(f"/api/v1/quotations/{voided['id']}/status", json={"status": "void"})
        assert client.post(f"/api/v1/quotations/{voided['id']}/to-order").status_code == 400
    finally:
        for qid in ids:
            client.delete(f"/api/v1/quotations/{qid}", params={"force": True})
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_quotation_delete_cleans_items():
    product_id = _new_product()
    quote_id = None
    try:
        q = client.post(
            "/api/v1/quotations",
            json={
                "quote_no": _quote_no(),
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 3.0}],
                "note": "报价单测试",
            },
        ).json()
        quote_id = q["id"]
        assert client.delete(f"/api/v1/quotations/{quote_id}").status_code == 204
        assert client.get(f"/api/v1/quotations/{quote_id}").status_code == 404
        assert client.delete(f"/api/v1/quotations/{quote_id}").status_code == 404
        quote_id = None
    finally:
        if quote_id:
            client.delete(f"/api/v1/quotations/{quote_id}")
        client.delete(f"/api/v1/products/{product_id}")
