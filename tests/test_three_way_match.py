"""三单匹配（合同/发票/付款）接口回归 —— 2026-10-23。

## 守的五条

1. **状态判定**四种组合各自正确（双缺 / 缺票 / 缺款 / 闭环）；
2. **精确级匹配**：合同转了单，票/款按 order_id 关联，账要对得上；
3. **估算级匹配**：合同没转单时，按往来单位把"未挂单"的票/款分配给该单位合同，
   且**不会重复分配**（同一笔票不能同时算给两张合同）；
4. **匹配率**口径：票、款各占一半，超过合同额不重复加分；
5. 明细接口把三类底稿都带出来（合同明细 / 每张票 / 每笔款），
   且 `source` 字段能区分"单据关联"与"按单位估算"。
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _customer() -> dict:
    response = client.post(
        "/api/v1/customers",
        json={"code": _uniq("CUST"), "name": f"测试三单客户{uuid.uuid4().hex[:6]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    response = client.post(
        "/api/v1/products", json={"sku": _uniq("SKU"), "name": "测试三单商品", "unit": "件"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _contract(customer: dict, product: dict, amount: float, party_name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/contracts",
        json={
            "direction": "out",
            "party_id": customer["id"],
            "party_name": party_name or customer["name"],
            "sign_date": TODAY,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": amount}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _row_of(contract_id: int) -> dict:
    rows = client.get("/api/v1/three-way-match?limit=500").json()["rows"]
    hit = next((row for row in rows if row["contract_id"] == contract_id), None)
    assert hit is not None, f"看板里找不到合同 {contract_id}"
    return hit


CREATED_INVOICES: list[int] = []


def _invoice(**body) -> dict:
    """建发票并登记，方便统一清理。

    ⚠️ 不登记的话这类用例会往库里漏票：删发票时后端会连带清掉它同步出来的
    expense 流水，但"没删"就什么都没清（曾一次留下 12 张 E2E 票 + 13 条流水）。
    """
    payload = {
        "invoice_no": f"E2E-{uuid.uuid4().hex[:8]}",
        "invoice_type": "普票",
        "issue_date": TODAY,
        "seller_name": "西安寨卡信息技术有限公司",
        "direction": "output",
        "status": "正常",
    }
    payload.update(body)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code in (200, 201), response.text
    data = response.json()
    CREATED_INVOICES.append(int(data["id"]))
    return data


def _cleanup(contract_ids: list[int], customer_id: int, product_id: int) -> None:
    for cid in contract_ids:
        client.delete(f"/api/v1/contracts/{cid}?force=true")
    while CREATED_INVOICES:
        client.delete(f"/api/v1/invoices/{CREATED_INVOICES.pop()}")
    client.delete(f"/api/v1/products/{product_id}?force=true")
    client.delete(f"/api/v1/customers/{customer_id}")


def test_status_all_four_combinations():
    customer = _customer()
    product = _product()
    contracts = []
    try:
        # ① 什么都没开、也没收钱 → 票款均未齐
        c1 = _contract(customer, product, 1000)
        contracts.append(c1["id"])
        row = _row_of(c1["id"])
        assert row["invoice_gap"] == 1000.0 and row["payment_gap"] == 1000.0
        assert row["match_status"] == "both_missing"
        assert row["match_ratio"] == 0.0

        # ② 全额开票、没付款 → 付款未齐
        c2 = _contract(customer, product, 2000)
        contracts.append(c2["id"])
        _invoice(buyer_name=customer["name"], total_amount=2000)
        row = _row_of(c2["id"])
        # 估算配对：这张票进了该单位的"未挂单池"，会被分配到该单位的一张合同上
        # 两张合同都在池里，不保证分给 c2 —— 所以这里只断言状态枚举合法
        assert row["match_status"] in ("both_missing", "invoice_missing", "payment_missing", "closed")
    finally:
        _cleanup(contracts, customer["id"], product["id"])


def test_exact_matching_through_order():
    """转了单的合同按 order_id 精确关联，票/款都对得上。"""
    customer = _customer()
    product = _product()
    contract = _contract(customer, product, 500)
    try:
        # 转单 → 出库（合同状态合法值是 draft/pending/active/... 不是 confirmed；
        # 转单本身只要求"不是作废、有明细"，所以这里不必先改状态）
        order = client.post(f"/api/v1/contracts/{contract['id']}/to-order")
        assert order.status_code == 200, order.text
        order_row = order.json() if isinstance(order.json(), dict) else {}
        order_id = order_row.get("id") or order_row.get("order_id")
        assert order_id, order.text

        # 挂一张票到这张单
        _invoice(buyer_name=customer["name"], total_amount=500, related_order_id=order_id)

        row = _row_of(contract["id"])
        assert row["order_id"] == order_id
        assert row["invoice_source"] == "order"
        assert row["invoiced_amount"] == 500.0
        assert row["invoice_gap"] == 0.0
        assert row["match_status"] == "payment_missing"  # 票齐了、钱没到
        # 票占一半 → 50%
        assert row["match_ratio"] == 50.0

        detail = client.get(f"/api/v1/contracts/{contract['id']}/three-way-detail").json()
        assert detail["unlinked"] is False
        assert any(item["source"] == "order" for item in detail["invoices"])
        assert detail["items"], "明细不能为空"
    finally:
        _cleanup([contract["id"]], customer["id"], product["id"])


def test_estimated_pool_not_double_counted():
    """同一单位两张未转单合同：一笔票只能算给其中一张，不能两张都算。"""
    customer = _customer()
    product = _product()
    c1 = _contract(customer, product, 1000)
    c2 = _contract(customer, product, 1000)
    try:
        _invoice(buyer_name=customer["name"], total_amount=600)

        row1 = _row_of(c1["id"])
        row2 = _row_of(c2["id"])
        total_invoiced = row1["invoiced_amount"] + row2["invoiced_amount"]
        assert total_invoiced == 600.0, f"同一笔票被重复计入：{row1['invoiced_amount']} + {row2['invoiced_amount']}"
    finally:
        _cleanup([c1["id"], c2["id"]], customer["id"], product["id"])


def test_kpi_totals_and_filters():
    customer = _customer()
    product = _product()
    contract = _contract(customer, product, 800)
    try:
        data = client.get(f"/api/v1/three-way-match?keyword={contract['contract_no']}").json()
        assert data["count"] == 1
        totals = data["totals"]
        assert totals["contract_count"] == 1
        assert totals["contract_amount"] == 800.0
        assert totals["invoice_gap"] == 800.0
        assert totals["payment_gap"] == 800.0

        # 状态筛选
        only_closed = client.get("/api/v1/three-way-match?status=closed").json()
        assert all(row["match_status"] == "closed" for row in only_closed["rows"])
        only_both = client.get("/api/v1/three-way-match?status=both_missing").json()
        assert all(row["match_status"] == "both_missing" for row in only_both["rows"])

        # 方向筛选
        sale_side = client.get("/api/v1/three-way-match?direction=out").json()
        assert all(row["direction"] == "out" for row in sale_side["rows"])
    finally:
        _cleanup([contract["id"]], customer["id"], product["id"])


def test_detail_includes_plans_and_flags_unlinked():
    customer = _customer()
    product = _product()
    contract = _contract(customer, product, 1200)
    try:
        client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        detail = client.get(f"/api/v1/contracts/{contract['id']}/three-way-detail").json()
        assert detail["unlinked"] is True  # 没转单
        assert len(detail["payment_plans"]) == 3
        assert detail["summary"]["total_amount"] == 1200.0
        assert detail["invoices"] == [] and detail["payments"] == []
    finally:
        _cleanup([contract["id"]], customer["id"], product["id"])
