"""打印接口测试：真实造单后请求 /print/*，断言返回合法 PDF 且内容正确。

覆盖：采购订单 / 采购入库单 / 销售开单 / 送货单 / 客户对账单（B1）/
供应商对账单（B2）/ 往来余额确认单（B3），以及 404 分支与 PDF 文本抽查。

另外钉住一条**踩过坑的响应头约定**（见 `test_all_print_endpoints_send_attachment`）：
单据 PDF 必须是 `Content-Disposition: attachment`，不能是 `inline`。
"""

import base64
import re
import uuid
from pathlib import Path

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


def test_print_endpoints_serve_both_transports(print_fixtures):
    """打印有两条通道，都必须能用。

    ⚠️ 这一条是踩了坑之后补的，别再改回去：

    `application/pdf` 的响应会被 Edge/Chrome 的**内置 PDF 阅读器接管**，
    于是浏览器里的 `fetch()` 拿到的是一个**空响应**（实测状态 204、body 为空），
    而 `response.ok` 对 2xx 依然为真 —— 前端会"成功"下载一个 0 字节的空 PDF，
    界面还提示已生成。这个缺陷从打印功能上线起潜伏了很久，
    因为以前只用 TestClient 验证接口（TestClient 不经过浏览器的渲染管线）。

    所以前端 `printPdf` 一律带 `Accept: application/json` 走 base64 通道：
    JSON 不会被任何浏览器接管，也能明确判断内容完整性。两条通道都保留：
    默认通道给外部脚本/curl 用（直接拿到 PDF 字节），JSON 通道给页面用。
    """
    order_id = print_fixtures["po"]["id"]
    url = f"/api/v1/print/purchase-order/{order_id}"

    # ① 默认通道：真 PDF 字节 + attachment
    binary = client.get(url)
    assert binary.status_code == 200
    assert binary.headers["content-type"].startswith("application/pdf")
    assert binary.headers["content-disposition"].startswith("attachment"), binary.headers["content-disposition"]
    assert binary.content[:4] == b"%PDF", "默认通道返回的不是 PDF"
    assert len(binary.content) > 3000

    # ② JSON 通道：base64 能解回同一份 PDF
    payload_resp = client.get(url, headers={"Accept": "application/json"})
    assert payload_resp.status_code == 200
    assert payload_resp.headers["content-type"].startswith("application/json")
    payload = payload_resp.json()
    assert payload["filename"].endswith(".pdf")
    assert payload["content_type"] == "application/pdf"
    raw = base64.b64decode(payload["content_base64"])
    assert raw[:4] == b"%PDF", "JSON 通道解出来的不是 PDF"
    assert len(raw) > 3000
    # 两条通道必须来自同一套渲染逻辑（长度允许因页脚/时间戳有微小差异，量级要一致）
    assert abs(len(raw) - len(binary.content)) < len(binary.content) * 0.2

    # ③ 对账单 / 余额确认单 / 合同 等其它出口也支持 JSON 通道
    statement = client.get(
        f"/api/v1/print/statement/customer/{print_fixtures['cus']['id']}",
        headers={"Accept": "application/json"},
    )
    assert statement.status_code == 200, statement.text
    assert statement.headers["content-type"].startswith("application/json")
    assert base64.b64decode(statement.json()["content_base64"])[:4] == b"%PDF"

    # ④ 模板预览保持二进制 PDF + inline（它是塞进 iframe 渲染的，不能改成 JSON）
    root = Path(__file__).resolve().parent.parent
    system_source = (root / "app" / "api" / "v1" / "routes" / "system.py").read_text(encoding="utf-8")
    assert 'inline; filename="template_' in system_source, "模板预览的 inline 被改掉了，iframe 会变成下载"
