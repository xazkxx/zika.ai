"""第 2 步回归测试：单据结算链 / 欠款链 / 单号生成 + 财务 × 全模块关联。

对应用户需求：
- 单据要能算清「应付(应收) → 优惠 → 实付(实收)」与「本次欠款 → 前次欠款 → 累欠货款」
- 财务模块要和所有模块保持关联（单据审核自动记账，人工只登记收付款）
"""

import uuid

from fastapi.testclient import TestClient

from app.api.v1.routes.erp import amount_to_chinese
from app.main import app

client = TestClient(app)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_customer(**extra):
    payload = {"code": _uniq("CUST"), "name": f"往来测试客户{extra.pop('tag', '')}"}
    payload.update(extra)
    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _make_supplier(**extra):
    payload = {"code": _uniq("SUP"), "name": f"往来测试供应商{extra.pop('tag', '')}"}
    payload.update(extra)
    response = client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _make_product(**extra):
    payload = {"sku": _uniq("SKU"), "name": "往来测试商品", "unit": "件", "standards": "标准"}
    payload.update(extra)
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- 单号自动生成 ----------


def test_purchase_order_no_auto_generated():
    supplier = _make_supplier()
    product = _make_product()
    response = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 10.0}],
        },
    )
    assert response.status_code == 201, response.text
    order_no = response.json()["order_no"]
    assert order_no.startswith("CG"), order_no
    assert len(order_no) == 13, order_no  # CG + 8 位日期 + 3 位流水


def test_sales_order_no_auto_generated_and_unique():
    customer = _make_customer()
    product = _make_product()
    body = {
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 10.0}],
    }
    first = client.post("/api/v1/sales-orders", json=body)
    second = client.post("/api/v1/sales-orders", json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["order_no"] != second.json()["order_no"]
    assert first.json()["order_no"].startswith("XS")


def test_order_rejects_unknown_party():
    product = _make_product()
    response = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": 99999999,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 1.0}],
        },
    )
    assert response.status_code == 404


# ---------- 结算链 ----------


def test_purchase_settlement_chain():
    supplier = _make_supplier()
    product = _make_product()
    response = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "warehouse_id": None,
            "businesser": "采购员甲",
            "delivery_date": "2026-10-15",
            "payment_method": "月结30天",
            "items": [
                {"product_id": product["id"], "quantity": 10, "unit_price": 100.0},
                {"product_id": product["id"], "quantity": 5, "unit_price": 20.0},
            ],
            "discount_amount": 100.0,
            "paid_amount": 500.0,
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()

    # 明细合计 10*100 + 5*20 = 1100
    assert data["total_amount"] == 1100.0
    assert data["payable_amount"] == 1100.0
    assert data["discount_amount"] == 100.0
    assert data["paid_amount"] == 500.0
    # 本次欠款 = 1100 - 100 - 500 = 500
    assert data["current_debt"] == 500.0
    assert data["prev_debt"] == 0.0
    assert data["total_debt"] == 500.0
    assert data["businesser"] == "采购员甲"
    assert data["delivery_date"] == "2026-10-15"
    assert data["payment_method"] == "月结30天"
    # 明细快照自动补齐，打印单据不必回查商品
    assert data["items"][0]["product_name"] == "往来测试商品"
    assert data["items"][0]["unit"] == "件"


def test_sales_settlement_chain_defaults_to_full_credit():
    """不填实收金额 = 全额挂账（会计上宁可高估应收，不可高估已收）。"""
    customer = _make_customer()
    product = _make_product()
    response = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 4, "unit_price": 250.0}],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["receivable_amount"] == 1000.0
    assert data["received_amount"] == 0.0
    assert data["current_debt"] == 1000.0
    assert data["total_debt"] == 1000.0


def test_debt_chain_carries_across_orders():
    """第二张单的"前次欠款"应等于第一张单的"累欠货款"。"""
    customer = _make_customer()
    product = _make_product()

    first = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 5, "unit_price": 100.0}],
        },
    ).json()
    assert first["prev_debt"] == 0.0 and first["total_debt"] == 500.0

    second = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 100.0}],
        },
    ).json()
    assert second["prev_debt"] == 500.0
    assert second["current_debt"] == 300.0
    assert second["total_debt"] == 800.0


# ---------- 财务 × 全模块关联 ----------


def test_order_creates_finance_records_automatically():
    supplier = _make_supplier()
    product = _make_product()
    order = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 300.0}],
            "paid_amount": 100.0,
        },
    ).json()

    records = client.get("/api/v1/finance", params={"limit": 500}).json()
    mine = [r for r in records if r["related_order_id"] == order["id"] and r["related_type"] == "purchase_in"]
    kinds = {r["transaction_type"] for r in mine}
    assert kinds == {"payable", "payment"}, kinds
    assert all(r["doc_no"] == order["order_no"] for r in mine)
    assert all(r["period"] for r in mine)
    payable = next(r for r in mine if r["transaction_type"] == "payable")
    assert payable["amount"] == 600.0
    assert payable["direction"] == "out"
    assert payable["related_type"] == "purchase_in"


def test_finance_rejects_unknown_related_type():
    response = client.post(
        "/api/v1/finance",
        json={"transaction_type": "expense", "amount": 10.0, "related_type": "不存在单据"},
    )
    assert response.status_code == 400


def test_finance_doc_types_dictionary():
    response = client.get("/api/v1/finance/doc-types")
    assert response.status_code == 200
    mapping = response.json()
    # 覆盖全部业务模块
    for key in ("purchase_in", "sales_out", "inv_check", "inv_scrap", "production_in", "project_cost", "invoice"):
        assert key in mapping


# ---------- 往来账 ----------


def test_ledger_and_reconciliation_for_customer():
    customer = _make_customer(init_receivable=200.0)
    product = _make_product()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 6, "unit_price": 100.0}],
        },
    ).json()

    ledger = client.get(
        "/api/v1/finance/ledger",
        params={"party_type": "customer", "party_id": customer["id"]},
    )
    assert ledger.status_code == 200, ledger.text
    data = ledger.json()
    assert data["opening_balance"] == 200.0
    assert data["increase_total"] == 600.0
    assert data["closing_balance"] == 800.0
    assert data["closing_balance_upper"].endswith("元整")

    recon = client.get(f"/api/v1/finance/reconciliation/customer/{customer['id']}")
    assert recon.status_code == 200
    body = recon.json()
    assert body["template"] == "B1"
    assert body["party"]["name"] == customer["name"]
    assert body["summary"]["closing_balance"] == 800.0
    assert any(row["doc_no"] == order["order_no"] for row in body["rows"])


def test_receivable_and_payable_summary():
    customer = _make_customer()
    product = _make_product()
    client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 400.0}],
        },
    )

    rows = client.get("/api/v1/finance/receivable").json()
    mine = next(r for r in rows if r["party_id"] == customer["id"])
    assert mine["balance"] == 800.0
    assert mine["party_name"] == customer["name"]
    assert mine["balance_upper"]


def test_aging_buckets_recent_document():
    customer = _make_customer()
    product = _make_product()
    client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 777.0}],
            "order_date": "2026-10-01",
        },
    )

    response = client.get("/api/v1/finance/aging", params={"party_type": "customer"})
    assert response.status_code == 200
    data = response.json()
    assert set(data["buckets"]) == {"0-30天", "31-60天", "61-90天", "90天以上"}
    assert data["total"] >= 777.0
    assert data["total_upper"]


# ---------- 收付款登记回写欠款链 ----------


def test_receipt_updates_order_and_recalculates_chain():
    customer = _make_customer()
    product = _make_product()

    first = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 5, "unit_price": 100.0}],
        },
    ).json()
    second = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 100.0}],
        },
    ).json()
    assert second["total_debt"] == 800.0

    receipt = client.post(
        "/api/v1/finance/receipt",
        json={"party_id": customer["id"], "amount": 200.0, "order_id": first["id"], "occurred_at": "2026-10-10"},
    )
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["transaction_type"] == "receipt"

    orders = {row["id"]: row for row in client.get("/api/v1/sales-orders", params={"limit": 500}).json()}
    assert orders[first["id"]]["received_amount"] == 200.0
    assert orders[first["id"]]["current_debt"] == 300.0
    assert orders[first["id"]]["total_debt"] == 300.0
    # 第二张单的前次欠款随之下降
    assert orders[second["id"]]["prev_debt"] == 300.0
    assert orders[second["id"]]["total_debt"] == 600.0

    ledger = client.get(
        "/api/v1/finance/ledger",
        params={"party_type": "customer", "party_id": customer["id"]},
    ).json()
    assert ledger["decrease_total"] == 200.0
    assert ledger["closing_balance"] == 600.0


def test_payment_flow_for_supplier():
    supplier = _make_supplier()
    product = _make_product()
    order = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "items": [{"product_id": product["id"], "quantity": 5, "unit_price": 200.0}],
        },
    ).json()
    assert order["total_debt"] == 1000.0

    payment = client.post(
        "/api/v1/finance/payment",
        json={"party_id": supplier["id"], "amount": 400.0, "order_id": order["id"]},
    )
    assert payment.status_code == 201, payment.text

    ledger = client.get(
        "/api/v1/finance/ledger",
        params={"party_type": "supplier", "party_id": supplier["id"]},
    ).json()
    assert ledger["opening_balance"] == 0.0
    assert ledger["increase_total"] == 1000.0
    assert ledger["decrease_total"] == 400.0
    assert ledger["closing_balance"] == 600.0

    recon = client.get(f"/api/v1/finance/reconciliation/supplier/{supplier['id']}").json()
    assert recon["template"] == "B2"
    assert recon["summary"]["closing_balance"] == 600.0


def test_receipt_rejects_bad_amount():
    customer = _make_customer()
    assert client.post("/api/v1/finance/receipt", json={"party_id": customer["id"], "amount": 0}).status_code == 400
    assert client.post("/api/v1/finance/receipt", json={"amount": 100.0}).status_code == 400


def test_overpayment_becomes_prepaid_and_never_negative_debt():
    """收款超过单据欠款时，超出部分算预收，单据不出现负的累欠货款。"""
    customer = _make_customer()
    product = _make_product()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 100.0}],
        },
    ).json()
    assert order["current_debt"] == 300.0

    response = client.post(
        "/api/v1/finance/receipt",
        json={"party_id": customer["id"], "amount": 500.0, "order_id": order["id"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["applied_amount"] == 300.0  # 只冲抵单据欠款
    assert body["prepaid_amount"] == 200.0  # 余下算预收

    refreshed = next(
        row for row in client.get("/api/v1/sales-orders", params={"limit": 500}).json() if row["id"] == order["id"]
    )
    assert refreshed["received_amount"] == 300.0
    assert refreshed["current_debt"] == 0.0
    assert refreshed["total_debt"] == 0.0  # 不允许负数

    # 往来账层面仍按实收 500 减少，余额为负说明客户有预存
    ledger = client.get(
        "/api/v1/finance/ledger",
        params={"party_type": "customer", "party_id": customer["id"]},
    ).json()
    assert ledger["decrease_total"] == 500.0
    assert ledger["closing_balance"] == -200.0


# ---------- 期间汇总与大写金额 ----------


def test_period_summary_reflects_orders():
    customer = _make_customer()
    product = _make_product()
    client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 10, "unit_price": 100.0}],
            "order_date": "2026-08-05",
        },
    )
    response = client.get("/api/v1/finance/period-summary", params={"period": "2026-08"})
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "2026-08"
    assert data["sales_amount"] >= 1000.0
    assert data["record_count"] >= 1


def test_amount_to_chinese():
    cases = {
        0: "零元整",
        10: "壹拾元整",
        105: "壹佰零伍元整",
        10000: "壹万元整",
        10001: "壹万零壹元整",
        1000000: "壹佰万元整",
        42640: "肆万贰仟陆佰肆拾元整",
        850.07: "捌佰伍拾元零柒分",
    }
    for value, expected in cases.items():
        assert amount_to_chinese(value) == expected, f"{value} -> {amount_to_chinese(value)}"
