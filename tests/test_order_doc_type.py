"""采购/销售订单（doc_type=order）与一键转单回归测试（第 1 批 · 收尾）。

背景：订单和出入库单此前共用一张表且行为完全相同（立即写库存+财务），
浩技云样板里它们是两个页面。本次给 `purchase_orders / sales_orders` 加
`doc_type` 判别字段：
- order    = 订单：只确认订货意向，不动库存、不写财务、不产生欠款；
- inbound / outbound = 出入库单（历史数据默认值）：原有行为原样保留。

新增接口：
- POST /purchase-orders/{id}/to-inbound  订单→入库单（写库存+应付）
- POST /sales-orders/{id}/to-outbound    订单→开单（写库存+应收）
- PATCH /purchase-orders/{id}/status、DELETE /purchase-orders/{id}（采购侧补齐）
- 列表 ?doc_type= 过滤

测试数据遵守 scripts/clean_test_data.py 的编码签名
（SKU-/CUST-/SUP- + 8位hex），跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _purge_sales_flows(order_id: int) -> None:
    """硬清一张销售单的资金流水（journal_entry_lines → journal_entries → financial_transactions）。

    完结闸让测试单据真实带上了资金流水，而红冲有意不解锁删单——
    测试收尾只能像运维清理一样按顺序硬删。related_type 实测是
    sales_out（开单应收）/ receipt（收款登记），不是 'sales_order'。
    """
    import psycopg

    from app.core.config import settings

    conn = psycopg.connect(
        str(settings.database_url).replace("postgresql+psycopg://", "postgresql://", 1)
    )
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM journal_entry_lines WHERE entry_id IN (
                SELECT je.id FROM journal_entries je
                JOIN financial_transactions ft ON je.flow_id = ft.id
                WHERE ft.related_order_id = %s
                  AND ft.related_type IN ('sales_out', 'receipt'))
            """,
            (order_id,),
        )
        cur.execute(
            """DELETE FROM journal_entries WHERE flow_id IN (
                SELECT id FROM financial_transactions
                WHERE related_order_id = %s
                  AND related_type IN ('sales_out', 'receipt'))""",
            (order_id,),
        )
        cur.execute(
            "DELETE FROM financial_transactions WHERE related_order_id = %s"
            " AND related_type IN ('sales_out', 'receipt')",
            (order_id,),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试商品", "purchase_price": 5.0, "sale_price": 9.0},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUST-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试客户"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={"code": f"SUP-ODT-{uuid.uuid4().hex[:8]}", "name": "订单测试供应商"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _inventory_rows_for(related_type: str, related_order_id: int) -> list[dict]:
    resp = client.get("/api/v1/inventory")
    assert resp.status_code == 200, resp.text
    return [
        row
        for row in resp.json()
        if row.get("related_type") == related_type and row.get("related_order_id") == related_order_id
    ]


def _finance_rows_for(related_type: str, related_order_id: int) -> list[dict]:
    resp = client.get("/api/v1/finance")
    assert resp.status_code == 200, resp.text
    return [
        row
        for row in resp.json()
        if row.get("related_type") == related_type and row.get("related_order_id") == related_order_id
    ]


# ---------- 创建：订单 vs 出入库单 ----------


def test_create_purchase_order_does_not_touch_stock_or_finance():
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        resp = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 5.0}],
                "note": "订单测试-不进货",
            },
        )
        assert resp.status_code == 201, resp.text
        order = resp.json()
        # 单号前缀 CGD、性质 order
        assert order["order_no"].startswith("CGD"), order["order_no"]
        assert order["doc_type"] == "order"
        # 订单不产生欠款与付款
        assert order["current_debt"] == 0.0
        assert order["paid_amount"] == 0.0
        assert order["total_amount"] == 15.0
        # 不写库存流水、不写财务流水
        assert _inventory_rows_for("purchase_in", order["id"]) == []
        assert _finance_rows_for("purchase_in", order["id"]) == []
    finally:
        client.delete(f"/api/v1/purchase-orders/{order['id']}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_sales_order_does_not_touch_stock_or_finance():
    product_id = _new_product()
    customer_id = _new_customer()
    try:
        resp = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "order",
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 9.0}],
            },
        )
        assert resp.status_code == 201, resp.text
        order = resp.json()
        assert order["order_no"].startswith("XSD"), order["order_no"]
        assert order["doc_type"] == "order"
        assert order["current_debt"] == 0.0
        assert order["received_amount"] == 0.0
        assert _inventory_rows_for("sales_out", order["id"]) == []
        assert _finance_rows_for("sales_out", order["id"]) == []
    finally:
        client.delete(f"/api/v1/sales-orders/{order['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_legacy_create_defaults_to_inbound_and_outbound():
    """不传 doc_type 的旧调用方必须保持原行为：入库/出库 + 库存 + 财务。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    try:
        po = client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 5.0}],
            },
        )
        assert po.status_code == 201, po.text
        purchase = po.json()
        assert purchase["doc_type"] == "inbound"
        assert purchase["order_no"].startswith("CG"), purchase["order_no"]
        assert len(_inventory_rows_for("purchase_in", purchase["id"])) == 1
        assert len(_finance_rows_for("purchase_in", purchase["id"])) >= 1

        so = client.post(
            "/api/v1/sales-orders",
            json={
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 9.0}],
            },
        )
        assert so.status_code == 201, so.text
        sales = so.json()
        assert sales["doc_type"] == "outbound"
        assert sales["order_no"].startswith("XS"), sales["order_no"]
        assert len(_inventory_rows_for("sales_out", sales["id"])) == 1

        # 列表 doc_type 过滤
        orders = client.get("/api/v1/purchase-orders", params={"doc_type": "order"}).json()
        assert all(row["doc_type"] == "order" for row in orders)
    finally:
        client.delete(f"/api/v1/purchase-orders/{purchase['id']}")
        client.delete(f"/api/v1/sales-orders/{sales['id']}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_invalid_doc_type_rejected():
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    try:
        assert (
            client.post(
                "/api/v1/purchase-orders",
                json={"doc_type": "nonsense", "supplier_id": supplier_id, "items": []},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/v1/sales-orders",
                json={"doc_type": "nonsense", "customer_id": customer_id, "items": []},
            ).status_code
            == 400
        )
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/customers/{customer_id}")


# ---------- 一键转单 ----------


def test_purchase_order_to_inbound_full_chain():
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        order = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 6, "unit_price": 5.0}],
                "note": "转单链路测试",
            },
        ).json()

        # 2026-10-18 新增闸口：未审核的订单不能转单（下面 approve 后才放行）
        blocked = client.post(f"/api/v1/purchase-orders/{order['id']}/to-inbound")
        assert blocked.status_code == 409, blocked.text
        assert "审核" in blocked.json()["detail"], blocked.text
        approved = client.patch(
            f"/api/v1/purchase-orders/{order['id']}/status", json={"status": "approved"}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved", approved.text

        resp = client.post(f"/api/v1/purchase-orders/{order['id']}/to-inbound")
        assert resp.status_code == 200, resp.text
        inbound = resp.json()
        # 生成的是入库单：CG 前缀、回指来源订单、复制明细
        assert inbound["doc_type"] == "inbound"
        assert inbound["order_no"].startswith("CG"), inbound["order_no"]
        assert inbound["source_order_id"] == order["id"]
        assert inbound["items"][0]["quantity"] == 6
        assert inbound["total_amount"] == 30.0
        # 库存与应付流水都挂在**入库单**上
        assert len(_inventory_rows_for("purchase_in", inbound["id"])) == 1
        assert len(_finance_rows_for("purchase_in", inbound["id"])) >= 1
        # 订单本身仍不产生流水
        assert _inventory_rows_for("purchase_in", order["id"]) == []

        # 订单状态置 completed，重复转单 409
        detail = client.get("/api/v1/purchase-orders", params={"doc_type": "order"}).json()
        target = next(row for row in detail if row["id"] == order["id"])
        assert target["status"] == "completed"
        again = client.post(f"/api/v1/purchase-orders/{order['id']}/to-inbound")
        assert again.status_code == 409, again.text

        # 已转单订单不能直接删
        blocked = client.delete(f"/api/v1/purchase-orders/{order['id']}")
        assert blocked.status_code == 409, blocked.text

        # 非订单类型不能转单
        assert client.post(f"/api/v1/purchase-orders/{inbound['id']}/to-inbound").status_code == 400

        # 收拾现场：先删入库单（冲销流水），再删订单
        assert client.delete(f"/api/v1/purchase-orders/{inbound['id']}").status_code == 204
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204
        # 冲销后流水清零
        assert _inventory_rows_for("purchase_in", inbound["id"]) == []
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_sales_order_to_outbound_full_chain():
    product_id = _new_product()
    customer_id = _new_customer()
    try:
        order = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "order",
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 9.0}],
            },
        ).json()

        # 同一条闸口：销售订单也必须先审核
        blocked = client.post(f"/api/v1/sales-orders/{order['id']}/to-outbound")
        assert blocked.status_code == 409, blocked.text
        assert "审核" in blocked.json()["detail"], blocked.text
        approved = client.patch(
            f"/api/v1/sales-orders/{order['id']}/status", json={"status": "approved"}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved", approved.text

        resp = client.post(f"/api/v1/sales-orders/{order['id']}/to-outbound")
        assert resp.status_code == 200, resp.text
        outbound = resp.json()
        assert outbound["doc_type"] == "outbound"
        assert outbound["order_no"].startswith("XS"), outbound["order_no"]
        assert outbound["source_order_id"] == order["id"]
        assert outbound["total_amount"] == 27.0
        assert len(_inventory_rows_for("sales_out", outbound["id"])) == 1
        assert len(_finance_rows_for("sales_out", outbound["id"])) >= 1
        assert _inventory_rows_for("sales_out", order["id"]) == []

        assert client.post(f"/api/v1/sales-orders/{order['id']}/to-outbound").status_code == 409
        assert client.delete(f"/api/v1/sales-orders/{order['id']}").status_code == 409

        assert client.delete(f"/api/v1/sales-orders/{outbound['id']}").status_code == 204
        assert client.delete(f"/api/v1/sales-orders/{order['id']}").status_code == 204
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_purchase_order_status_and_plain_order_delete():
    """未转单的订单可以直接删；补齐的 PATCH status 可用。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    try:
        order = client.post(
            "/api/v1/purchase-orders",
            json={
                "doc_type": "order",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 5.0}],
            },
        ).json()
        patched = client.patch(
            f"/api/v1/purchase-orders/{order['id']}/status", json={"status": "cancelled"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["status"] == "cancelled"
        # P0-5：删除 = 作废，幂等返回 204（旧契约"再删 404"已不再适用）
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204
        assert client.delete(f"/api/v1/purchase-orders/{order['id']}").status_code == 204
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 状态机（2026-10-18） ----------


def test_order_status_machine_rejects_illegal_values():
    """PATCH status 不再是"什么都能写"：未知码 400、跳级 409、终态锁死。"""
    product_id = _new_product()
    customer_id = _new_customer()
    try:
        order = client.post(
            "/api/v1/sales-orders",
            json={
                "doc_type": "order",
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 5.0}],
            },
        ).json()
        base = f"/api/v1/sales-orders/{order['id']}/status"

        # ① 未知状态码 → 400（改造前任何字符串都能写进库）
        bad = client.patch(base, json={"status": "已审核"})
        assert bad.status_code == 400, bad.text
        assert "draft" in bad.json()["detail"], bad.text

        # ② 空状态 → 400（改造前默认塞 submitted，等于静默放行）
        assert client.patch(base, json={}).status_code == 400

        # ③ 跳级：待审核（老值 submitted 归一）直接到已完成 → 409
        assert order["status"] == "submitted", order["status"]
        skip = client.patch(base, json={"status": "completed"})
        assert skip.status_code == 409, skip.text
        assert "待审核" in skip.json()["detail"], skip.text

        # ④ 正常审核：submitted(=pending) → approved
        ok = client.patch(base, json={"status": "approved"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved"

        # ⑤ 幂等：同一状态再点一次不报错
        again = client.patch(base, json={"status": "approved"})
        assert again.status_code == 200, again.text
        assert again.json()["status"] == "approved"

        # ⑥ 审核后不能退回草稿（approved 只允许 completed / pending / cancelled）
        back = client.patch(base, json={"status": "draft"})
        assert back.status_code == 409, back.text

        # ⑦ 终态锁死：cancelled 之后连审核都不行
        assert client.patch(base, json={"status": "cancelled"}).status_code == 200
        locked = client.patch(base, json={"status": "approved"})
        assert locked.status_code == 409, locked.text
        assert "终态" in locked.json()["detail"], locked.text

        assert client.delete(f"/api/v1/sales-orders/{order['id']}").status_code == 204
    finally:
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_spot_outbound_keeps_direct_flow():
    """现货开单（doc_type=outbound）没有审核环节：submitted → completed 必须仍然可用。

    2026-10-20 完结闸：completed 现在还要求"收齐款 + 开齐票"——
    什么都没做直接完结会 409（not_settled，含应收余额/未开票金额）。
    钱票两清后 submitted → completed 照常放行；完结后单据带着资金流水，
    删除会被 has_payment_flow 拦下（红冲有意不解锁删单），清流水才能删。
    """
    product_id = _new_product()
    customer_id = _new_customer()
    invoice = None  # 断言中途失败时 finally 也要能安全引用
    try:
        outbound = client.post(
            "/api/v1/sales-orders",
            json={
                "customer_id": customer_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 5.0}],
            },
        ).json()
        assert outbound["doc_type"] == "outbound"
        assert outbound["status"] == "submitted"

        # 完结闸：没钱没票不许完结
        resp = client.patch(
            f"/api/v1/sales-orders/{outbound['id']}/status", json={"status": "completed"}
        )
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "not_settled"
        assert float(detail["outstanding_amount"]) == 5.0
        assert float(detail["uninvoiced_amount"]) == 5.0

        # 钱票两清
        receipt = client.post(
            "/api/v1/finance/receipt",
            json={"party_id": customer_id, "order_id": outbound["id"], "amount": 5},
        )
        assert receipt.status_code in (200, 201), receipt.text
        invoice = client.post(
            "/api/v1/invoices",
            json={
                "invoice_no": f"INV-ODT-{uuid.uuid4().hex[:8]}",
                "invoice_type": "普票",
                "total_amount": 5,
                "direction": "output",
                "customer_id": customer_id,
                "related_order_id": outbound["id"],
            },
        )
        assert invoice.status_code == 201, invoice.text

        resp = client.patch(
            f"/api/v1/sales-orders/{outbound['id']}/status", json={"status": "completed"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "completed"

        # 现货单不接受审核态（没有这道流程）→ 400 而不是静默写入
        rejected = client.patch(
            f"/api/v1/sales-orders/{outbound['id']}/status", json={"status": "approved"}
        )
        assert rejected.status_code == 400, rejected.text

        # 已完结单据带资金流水 → 删除被拦（红冲不解锁删单）
        blocked = client.delete(f"/api/v1/sales-orders/{outbound['id']}")
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "has_payment_flow"

        # 测试收尾：硬清本单流水后才能删（与生产清理路径一致）
        _purge_sales_flows(outbound["id"])
        assert client.delete(f"/api/v1/sales-orders/{outbound['id']}").status_code == 204
    finally:
        # 自己造的发票自己删：发票表没有指向客户的级联，删客户不会带走它。
        # 漏这一步的后果实测过 —— 正式库累积了 8 张 INV-ODT-* ¥5.00 的假票。
        if invoice is not None and invoice.status_code == 201:
            client.delete(f"/api/v1/invoices/{invoice.json()['id']}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")
