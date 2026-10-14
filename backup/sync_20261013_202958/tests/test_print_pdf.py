"""打印接口测试：真实造单后请求 /print/*，断言返回合法 PDF 且内容正确。

覆盖：采购订单 / 采购入库单 / 销售开单 / 送货单 / 客户对账单（B1）/
供应商对账单（B2）/ 往来余额确认单（B3），以及 404 分支与 PDF 文本抽查。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def print_fixtures():
    tag = uuid.uuid4().hex[:8]
    wh = client.get("/api/v1/warehouses").json()
    wh_id = (
        wh[0]["id"]
        if wh
        else client.post("/api/v1/warehouses", json={"code": f"WH-{tag}", "name": f"主仓库临时{tag}"}).json()["id"]
    )
    sup = client.post("/api/v1/suppliers", json={"code": f"SUP-PRT-{tag}", "name": f"打印测试供应商{tag}"}).json()
    cus = client.post("/api/v1/customers", json={"code": f"CUST-PRT-{tag}", "name": f"打印测试客户{tag}"}).json()
    prod = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-PRT-{tag}", "name": "打印测试商品", "standards": "DN100 PN16", "unit": "个",
              "purchase_price": 156.5, "sale_price": 210.0},
    ).json()
    po = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": sup["id"], "warehouse_id": wh_id, "order_date": "2026-10-10",
            "businesser": "李明", "contact": "张伟", "contact_phone": "13800000000",
            "address": "西安市高新区纬二十六路 1 号", "payment_method": "月结30天",
            "items": [
                {"product_id": prod["id"], "quantity": 20, "unit_price": 156.5, "amount": 3130.0, "note": "含税含运"},
                {"product_id": prod["id"], "quantity": 15, "unit_price": 88.0, "amount": 1320.0},
            ],
        },
    ).json()
    so = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": cus["id"], "warehouse_id": wh_id, "order_date": "2026-10-10",
            "delivery_date": "2026-10-12", "businesser": "李明",
            "contact": "赵敏", "contact_phone": "13833334444", "address": "西安市雁塔区科技路 66 号",
            "items": [
                {"product_id": prod["id"], "quantity": 8, "unit_price": 210.0, "amount": 1680.0, "note": "急件"},
                {"product_id": prod["id"], "quantity": 5, "unit_price": 210.0, "amount": 1050.0},
            ],
        },
    ).json()
    client.post(
        "/api/v1/finance",
        json={"transaction_type": "income", "direction": "in", "amount": 2000.0,
              "customer_id": cus["id"], "occurred_at": "2026-09-01", "note": f"打印测试期初收款 {tag}"},
    )
    return {"tag": tag, "sup": sup, "cus": cus, "prod": prod, "po": po, "so": so}


def _assert_pdf(resp) -> None:
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/pdf")
    assert resp.content[:4] == b"%PDF"


def test_print_purchase_order_and_inbound(print_fixtures):
    po = print_fixtures["po"]
    for kind in ("purchase-order", "purchase-inbound"):
        _assert_pdf(client.get(f"/api/v1/print/{kind}/{po['id']}"))


def test_print_sales_order_and_delivery_note(print_fixtures):
    so = print_fixtures["so"]
    for kind in ("sales-order", "delivery-note"):
        _assert_pdf(client.get(f"/api/v1/print/{kind}/{so['id']}"))


def test_print_statement_customer_and_supplier(print_fixtures):
    _assert_pdf(client.get(f"/api/v1/print/statement/customer/{print_fixtures['cus']['id']}"))
    _assert_pdf(client.get(f"/api/v1/print/statement/supplier/{print_fixtures['sup']['id']}"))


def test_print_balance_confirm(print_fixtures):
    _assert_pdf(client.get(f"/api/v1/print/balance-confirm/customer/{print_fixtures['cus']['id']}"))


def test_print_pdf_text_content(print_fixtures):
    import pymupdf

    so = print_fixtures["so"]
    resp = client.get(f"/api/v1/print/sales-order/{so['id']}")
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    text = doc[0].get_text()
    assert "销售开单" in text
    assert so["order_no"] in text
    assert "打印测试商品" in text
    assert "大写" in text
    doc.close()

    resp = client.get(f"/api/v1/print/statement/customer/{print_fixtures['cus']['id']}")
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    text = doc[0].get_text()
    assert "客户对账单" in text
    assert "期初余额" in text and "期末余额" in text
    doc.close()


def test_print_unknown_type_and_missing_doc():
    assert client.get("/api/v1/print/no-such-type/1").status_code == 404
    assert client.get("/api/v1/print/sales-order/99999999").status_code == 404
    assert client.get("/api/v1/print/purchase-order/99999999").status_code == 404
    assert client.get("/api/v1/print/statement/customer/99999999").status_code == 404
    assert client.get("/api/v1/print/statement/badtype/1").status_code in (400, 404)
