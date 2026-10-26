"""业财一体化 · 发票自动挂单 & 付款挂票 回归测试（2026-10-22）。

## 这批测试在守什么

1. **自动挂单只在"唯一强证据"时发生**
   金额一致 + 未开票余量够 + 候选唯一 —— 三个条件缺一个就只能返回候选让人点。
   放宽任何一条，代价都是"票挂到别人单上"，而挂错会直接骗过完结闸。

2. **绝不覆盖人工**
   已有 `related_order_id` 的发票再跑一次自动匹配，必须是 `skipped` 且值不变。

3. **红字票、待判定票不猜**
   冲红票必须和它冲的那张蓝票挂同一张单 —— 只有开票人知道是哪张。

4. **挂错要能撤**
   `link-order` 传 `order_id=null` 就是解挂（否则一张错票会长期污染完结闸）。

5. **付款挂票（先款后票）**
   付款登记带 `invoice_id` → 票挂到单上、流水记 `invoice_id`；
   销项票挂付款必须 400（方向不对的票挂上去比不挂更糟）。

6. **口径与完结闸一致**
   `invoice-status` 的 `uninvoiced_amount` 必须能准确预测"点完结会不会被拦"，
   所以它和 `erp_sales.py` 的 `not_settled` 用同一条 SQL（`order_invoiced_amount`）。
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _invoice_row(invoice_id: int) -> dict:
    """按 id 从发票列表取一行。

    ⚠️ 项目里**没有** `GET /invoices/{id}` 这条路由（只有列表、PATCH、文件、二维码），
    所以验证"到底写没写进库"只能从列表里捞。别顺手去加那条路由：
    `/invoices/summary`、`/invoices/parse` 这些同前缀的固定路径会被 `{invoice_id}: int`
    抢先匹配，直接 422 —— 这是本项目踩过的坑。
    """
    rows = client.get("/api/v1/invoices").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    hit = [row for row in rows if int(row["id"]) == int(invoice_id)]
    assert hit, f"发票 {invoice_id} 不在列表里"
    return hit[0]


def _warehouse() -> dict:
    rows = client.get("/api/v1/warehouses").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    assert rows, "库里至少要有一个仓库"
    return rows[0]


def _customer() -> dict:
    payload = {"code": _uniq("CUST"), "name": f"测试客户业财{uuid.uuid4().hex[:6]}"}
    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _supplier() -> dict:
    payload = {"code": _uniq("SUP"), "name": f"测试供应商业财{uuid.uuid4().hex[:6]}"}
    response = client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    payload = {"sku": _uniq("SKU"), "name": "测试商品业财", "unit": "件", "standards": "标准"}
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _opening(product_id: int, warehouse_id: int, qty: int = 500) -> None:
    """给足库存：转出库单会扣库存，没有期初的话单据数额是对的但库存会变负数。"""
    response = client.put(
        "/api/v1/opening-stock",
        json={"items": [{"warehouse_id": warehouse_id, "product_id": product_id, "quantity": qty, "unit_price": 10}]},
    )
    assert response.status_code == 200, response.text


def _outbound(customer_id: int, product_id: int, amount: float) -> dict:
    """建销售订单 → 审核 → 转出库单。走完整链路，别直接塞 doc_type='outbound'。"""
    warehouse = _warehouse()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": amount, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/sales-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    outbound = client.post(f"/api/v1/sales-orders/{order_id}/to-outbound")
    assert outbound.status_code == 200, outbound.text
    return outbound.json()


def _inbound(supplier_id: int, product_id: int, amount: float) -> dict:
    warehouse = _warehouse()
    order = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": amount, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/purchase-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    inbound = client.post(f"/api/v1/purchase-orders/{order_id}/to-inbound")
    assert inbound.status_code == 200, inbound.text
    return inbound.json()


def _output_invoice(buyer_name: str, amount: float, **extra) -> dict:
    payload = {
        "invoice_no": _uniq("INV"),
        "invoice_type": "普票",
        "issue_date": TODAY,
        "buyer_name": buyer_name,
        "seller_name": "西安寨卡信息技术有限公司",
        "total_amount": amount,
        "direction": "output",
        "status": "正常",
    }
    payload.update(extra)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _input_invoice(seller_name: str, amount: float, **extra) -> dict:
    payload = {
        "invoice_no": _uniq("INV"),
        "invoice_type": "普票",
        "issue_date": TODAY,
        "buyer_name": "西安寨卡信息技术有限公司",
        "seller_name": seller_name,
        "total_amount": amount,
        "direction": "input",
        "status": "正常",
    }
    payload.update(extra)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code in (200, 201), response.text
    return response.json()


# ---------------------------------------------------------------------------
# 1. 唯一强证据 → 自动挂上
# ---------------------------------------------------------------------------
def test_invoice_auto_attaches_when_unique_amount_match():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    outbound = _outbound(customer["id"], product["id"], 100.0)

    invoice = _output_invoice(customer["name"], 100.0, customer_id=customer["id"])

    match = invoice.get("match") or {}
    assert match.get("status") == "matched", match
    assert int(match.get("order_id") or 0) == int(outbound["id"])
    # 真写进库了，不是只在回包里说说
    assert int(_invoice_row(invoice["id"])["related_order_id"]) == int(outbound["id"])


# ---------------------------------------------------------------------------
# 2. 两张同额单 → 必须人工选，不许瞎挂
# ---------------------------------------------------------------------------
def test_invoice_does_not_auto_attach_when_two_candidates_tie():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    first = _outbound(customer["id"], product["id"], 88.0)
    second = _outbound(customer["id"], product["id"], 88.0)

    invoice = _output_invoice(customer["name"], 88.0, customer_id=customer["id"])

    match = invoice.get("match") or {}
    assert match.get("status") == "ambiguous", match
    assert match.get("order_id") in (None, 0)
    candidate_ids = {int(item["order_id"]) for item in match.get("candidates") or []}
    assert {first["id"], second["id"]} <= candidate_ids
    assert not invoice.get("related_order_id"), "歧义时绝不许自动落库"


# ---------------------------------------------------------------------------
# 3. 已有挂单 → 跳过，不覆盖
# ---------------------------------------------------------------------------
def test_auto_match_never_overwrites_existing_link():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    first = _outbound(customer["id"], product["id"], 50.0)
    second = _outbound(customer["id"], product["id"], 50.0)

    invoice = _output_invoice(customer["name"], 50.0, customer_id=customer["id"])
    # 先人工挂到第二张（模拟"用户明确指定"）
    linked = client.post(f"/api/v1/invoices/{invoice['id']}/link-order", json={"order_id": second["id"]})
    assert linked.status_code == 200, linked.text

    again = client.post(f"/api/v1/invoices/{invoice['id']}/auto-match").json()
    assert again.get("status") == "skipped", again
    detail = _invoice_row(invoice["id"])
    assert int(detail["related_order_id"]) == int(second["id"])
    assert int(detail["related_order_id"]) != int(first["id"])


# ---------------------------------------------------------------------------
# 4. 红字票不猜
# ---------------------------------------------------------------------------
def test_red_invoice_is_never_auto_matched():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    _outbound(customer["id"], product["id"], 30.0)

    invoice = _output_invoice(
        customer["name"], 30.0, customer_id=customer["id"], invoice_flag="red"
    )
    match = invoice.get("match") or {}
    assert match.get("status") == "skipped", match
    assert "红字" in (match.get("reason") or "")
    assert not invoice.get("related_order_id")


# ---------------------------------------------------------------------------
# 5. 人工挂单 + 解挂 + 跨对方拦截
# ---------------------------------------------------------------------------
def test_manual_link_and_unlink():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    outbound = _outbound(customer["id"], product["id"], 66.0)
    invoice = _output_invoice(customer["name"], 66.0, customer_id=customer["id"])

    # 先解挂（本来可能是自动挂上的），再挂回去，再解挂
    cleared = client.post(f"/api/v1/invoices/{invoice['id']}/link-order", json={"order_id": None})
    assert cleared.status_code == 200, cleared.text
    assert _invoice_row(invoice["id"])["related_order_id"] is None

    relinked = client.post(f"/api/v1/invoices/{invoice['id']}/link-order", json={"order_id": outbound["id"]})
    assert relinked.status_code == 200, relinked.text
    assert int(relinked.json()["order_id"]) == int(outbound["id"])

    # 挂到别家客户的单上必须 409 —— 这种错挂会直接算错别人的对账单
    other = _customer()
    other_outbound = _outbound(other["id"], product["id"], 66.0)
    bad = client.post(f"/api/v1/invoices/{invoice['id']}/link-order", json={"order_id": other_outbound["id"]})
    assert bad.status_code == 409, bad.text


# ---------------------------------------------------------------------------
# 6. 票据状态口径 = 完结闸口径
# ---------------------------------------------------------------------------
def test_invoice_status_predicts_settlement_gate():
    customer = _customer()
    product = _product()
    _opening(product["id"], _warehouse()["id"])
    outbound = _outbound(customer["id"], product["id"], 120.0)

    before = client.get(f"/api/v1/orders/sales/{outbound['id']}/invoice-status").json()
    assert before["status"] == "none"
    assert before["need_invoice"] is True
    assert round(before["uninvoiced_amount"], 2) == 120.0

    _output_invoice(customer["name"], 120.0, customer_id=customer["id"])

    after = client.get(f"/api/v1/orders/sales/{outbound['id']}/invoice-status").json()
    assert after["status"] == "full"
    assert after["need_invoice"] is False
    assert round(after["uninvoiced_amount"], 2) == 0.0
    assert after["invoice_count"] == 1


# ---------------------------------------------------------------------------
# 7. 付款挂进项票（先款后票）
# ---------------------------------------------------------------------------
def test_payment_can_carry_input_invoice():
    supplier = _supplier()
    product = _product()
    inbound = _inbound(supplier["id"], product["id"], 160.0)
    invoice = _input_invoice(supplier["name"], 160.0)

    # 这张票金额与入库单一致 → 建票时就已经自动挂上了（那是第 1 条用例在管的事）。
    # 这里要测的是"票已识别但还没挂单，付款时把它挂上"，所以先手动解挂。
    assert int(_invoice_row(invoice["id"])["related_order_id"]) == int(inbound["id"]), "本应被自动挂上"
    unlinked = client.post(f"/api/v1/invoices/{invoice['id']}/link-order", json={"order_id": None})
    assert unlinked.status_code == 200, unlinked.text

    status_before = client.get(f"/api/v1/orders/purchase/{inbound['id']}/invoice-status").json()
    assert status_before["need_invoice"] is True

    payment = client.post(
        "/api/v1/finance/payment",
        json={
            "party_id": supplier["id"],
            "order_id": inbound["id"],
            "amount": 160.0,
            "occurred_at": TODAY,
            "note": "先款后票：付款时把票挂上",
            "invoice_id": invoice["id"],
        },
    )
    assert payment.status_code == 201, payment.text
    body = payment.json()
    assert body["has_invoice"] is True
    assert body["invoice_id"] == invoice["id"]
    assert body["estimate"] is False

    # 票被顺手挂到了这张入库单上 → 未开票金额当场归零
    status_after = client.get(f"/api/v1/orders/purchase/{inbound['id']}/invoice-status").json()
    assert status_after["status"] == "full"
    assert int(status_after["invoices"][0]["id"]) == int(invoice["id"])


def test_payment_marks_estimate_and_no_invoice():
    supplier = _supplier()
    product = _product()
    inbound = _inbound(supplier["id"], product["id"], 90.0)

    estimated = client.post(
        "/api/v1/finance/payment",
        json={
            "party_id": supplier["id"],
            "order_id": inbound["id"],
            "amount": 90.0,
            "occurred_at": TODAY,
            "note": "无票先付",
            "estimate": True,
        },
    ).json()
    assert estimated["has_invoice"] is False
    assert estimated["estimate"] is True

    flows = client.get("/api/v1/finance").json()
    flows = flows if isinstance(flows, list) else flows.get("items") or []
    mine = [row for row in flows if row["id"] == estimated["id"]][0]
    assert "【暂估】" in (mine.get("note") or "")


def test_payment_rejects_output_invoice():
    supplier = _supplier()
    product = _product()
    inbound = _inbound(supplier["id"], product["id"], 40.0)
    customer = _customer()
    wrong = _output_invoice(customer["name"], 40.0, customer_id=customer["id"])

    response = client.post(
        "/api/v1/finance/payment",
        json={
            "party_id": supplier["id"],
            "order_id": inbound["id"],
            "amount": 40.0,
            "occurred_at": TODAY,
            "invoice_id": wrong["id"],
        },
    )
    assert response.status_code == 400, response.text
    assert "进项" in response.text
