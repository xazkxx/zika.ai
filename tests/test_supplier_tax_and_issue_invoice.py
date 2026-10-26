"""供应商税号 + 销售单「一键开票」回归测试（2026-10-22 · 业财一体化第二批）。

## 为什么要单独钉住这两件事

### 1. 供应商税号：进项票匹配的命门
以前进项票**只能按名称**找供应商。现实里对方开票写的是简称：
「陕西送变电」≠「陕西送变电工程有限公司」→ 匹配失败 → 票挂不上单 → 完结闸永远拦着。
补了 `suppliers.tax_no` 之后，匹配顺序变成 **税号优先 → 名称兜底**。
这条链只要有一环写错（模型没列、schema 丢字段、匹配没读税号），
表现都是"票来了但挂不上"，而且**不报错**，只能靠用例守住。

### 2. 一键开票：先销后票的闭环
四个必须成立的约束：
  · 金额取**未开票余额**，明细取**单据明细**，`related_order_id` 当场挂上；
  · 允许分次开票，但**不能超额**（超额会骗过完结闸的"已开票"口径）；
  · 开齐后再开 → 409（防重复开票）；
  · 不填票号给占位号 `KP-<单号>`，填了真实票号撞号 → 409（不许顶掉别人的票）。
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _warehouse() -> dict:
    rows = client.get("/api/v1/warehouses").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    return rows[0]


def _product() -> dict:
    response = client.post(
        "/api/v1/products",
        json={"sku": _uniq("SKU"), "name": "测试商品开票", "unit": "件", "standards": "标准"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _customer() -> dict:
    response = client.post(
        "/api/v1/customers",
        json={"code": _uniq("CUST"), "name": f"测试客户开票{uuid.uuid4().hex[:6]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _supplier(name: str | None = None, tax_no: str | None = None) -> dict:
    payload = {"code": _uniq("SUP"), "name": name or f"测试供应商税号{uuid.uuid4().hex[:6]}"}
    if tax_no is not None:
        payload["tax_no"] = tax_no
    response = client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _opening(product_id: int, qty: int = 500) -> None:
    response = client.put(
        "/api/v1/opening-stock",
        json={
            "items": [
                {"warehouse_id": _warehouse()["id"], "product_id": product_id, "quantity": qty, "unit_price": 10}
            ]
        },
    )
    assert response.status_code == 200, response.text


def _outbound(customer_id: int, product_id: int, amount: float, qty: int = 1) -> dict:
    warehouse = _warehouse()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product_id, "quantity": qty, "unit_price": amount, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/sales-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    out = client.post(f"/api/v1/sales-orders/{order_id}/to-outbound")
    assert out.status_code == 200, out.text
    return out.json()


def _invoice_rows() -> list[dict]:
    rows = client.get("/api/v1/invoices").json()
    return rows if isinstance(rows, list) else rows.get("items") or []


# ===========================================================================
# 一、供应商税号
# ===========================================================================
def test_supplier_tax_no_roundtrip():
    """税号能建、能改、能在列表里读回来（schema/模型/路由三处只要有一处漏就不通）。"""
    tax = f"9161{uuid.uuid4().hex[:14].upper()}"
    created = _supplier(tax_no=tax)
    assert created["tax_no"] == tax

    new_tax = f"9161{uuid.uuid4().hex[:14].upper()}"
    patched = client.patch(f"/api/v1/suppliers/{created['id']}", json={"tax_no": new_tax})
    assert patched.status_code == 200, patched.text
    assert patched.json()["tax_no"] == new_tax

    rows = client.get("/api/v1/suppliers").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    hit = [row for row in rows if row["id"] == created["id"]][0]
    assert hit["tax_no"] == new_tax


def test_input_invoice_matches_supplier_by_tax_no_when_name_differs():
    """**核心场景**：发票上写的是简称，靠税号仍能匹配到供应商 → 自动挂到入库单。"""
    tax = f"9161{uuid.uuid4().hex[:14].upper()}"
    supplier = _supplier(name=f"测试供应商全称{uuid.uuid4().hex[:6]}", tax_no=tax)
    product = _product()

    # 入库单：供应商是"全称"，金额 300
    order = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "warehouse_id": _warehouse()["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 300, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/purchase-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    inbound = client.post(f"/api/v1/purchase-orders/{order_id}/to-inbound")
    assert inbound.status_code == 200, inbound.text

    # 发票：销售方只写"简称"（和档案名称完全不一致），但税号一致
    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "专票",
            "issue_date": TODAY,
            "buyer_name": "西安寨卡信息技术有限公司",
            "seller_name": "测试供应商简称",
            "seller_tax_no": tax,
            "total_amount": 300.0,
            "direction": "input",
            "status": "正常",
        },
    )
    assert invoice.status_code in (200, 201), invoice.text
    body = invoice.json()
    assert (body.get("match") or {}).get("status") == "matched", body.get("match")
    assert int((body.get("match") or {}).get("order_id") or 0) == int(inbound.json()["id"])


def test_input_invoice_falls_back_to_name_when_tax_no_missing():
    """兜底不能丢：老供应商没登记税号，仍按名称全等匹配得上。"""
    supplier = _supplier()
    product = _product()
    order = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "warehouse_id": _warehouse()["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 88, "unit": "件"}],
        },
    )
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/purchase-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    inbound = client.post(f"/api/v1/purchase-orders/{order_id}/to-inbound")
    assert inbound.status_code == 200, inbound.text

    invoice = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "普票",
            "issue_date": TODAY,
            "buyer_name": "西安寨卡信息技术有限公司",
            "seller_name": supplier["name"],
            "total_amount": 88.0,
            "direction": "input",
            "status": "正常",
        },
    )
    body = invoice.json()
    assert (body.get("match") or {}).get("status") == "matched", body.get("match")


def test_invoice_patch_can_edit_tax_no_and_invoice_no():
    """发票弹窗里改税号/票号必须真的生效（以前 schema 没这两列，改了静默丢弃）。"""
    created = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "普票",
            "issue_date": TODAY,
            "total_amount": 10.0,
            "direction": "output",
            "status": "正常",
        },
    ).json()

    new_no = _uniq("INV")
    new_tax = f"9161{uuid.uuid4().hex[:14].upper()}"
    patched = client.patch(
        f"/api/v1/invoices/{created['id']}",
        json={"invoice_no": new_no, "buyer_tax_no": new_tax, "seller_tax_no": new_tax},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["invoice_no"] == new_no
    assert patched.json()["buyer_tax_no"] == new_tax
    assert patched.json()["seller_tax_no"] == new_tax


def test_invoice_patch_rejects_duplicate_invoice_no():
    first = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "普票",
            "issue_date": TODAY,
            "total_amount": 10.0,
            "direction": "output",
        },
    ).json()
    second = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "普票",
            "issue_date": TODAY,
            "total_amount": 10.0,
            "direction": "output",
        },
    ).json()

    clash = client.patch(f"/api/v1/invoices/{second['id']}", json={"invoice_no": first["invoice_no"]})
    assert clash.status_code == 409, clash.text
    assert "已" in clash.text


# ===========================================================================
# 二、一键开票
# ===========================================================================
def test_issue_invoice_creates_invoice_with_items_and_links_order():
    customer = _customer()
    product = _product()
    _opening(product["id"])
    # 单据总额 = 单价 × 数量 = 60 × 2 = 120（`_outbound` 传的是单价）
    outbound = _outbound(customer["id"], product["id"], 60.0, qty=2)

    issued = client.post(f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={})
    assert issued.status_code == 201, issued.text
    body = issued.json()
    invoice = body["invoice"]

    # ① 挂单 —— 完结闸只认这个字段
    assert int(invoice["related_order_id"]) == int(outbound["id"])
    # ② 金额 = 未开票余额
    assert round(float(invoice["total_amount"]), 2) == 120.0
    # ③ 明细来自单据（2 件 × 60）
    assert len(invoice["items"]) == 1, invoice["items"]
    assert invoice["items"][0]["item_name"] == product["name"]
    assert float(invoice["items"][0]["quantity"]) == 2.0
    # ④ 没给票号 → 占位号（可后补），并明确告知
    assert body["pending_no"] is True
    assert invoice["invoice_no"].startswith("KP-")

    # ⑤ 完结闸口径当场归零：这才是"先销后票"闭环的证据
    status = client.get(f"/api/v1/orders/sales/{outbound['id']}/invoice-status").json()
    assert status["status"] == "full"
    assert round(status["uninvoiced_amount"], 2) == 0.0


def test_issue_invoice_allows_partial_then_blocks_when_full():
    customer = _customer()
    product = _product()
    _opening(product["id"])
    outbound = _outbound(customer["id"], product["id"], 100.0)

    first = client.post(
        f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={"total_amount": 40}
    )
    assert first.status_code == 201, first.text
    assert round(float(first.json()["uninvoiced_amount"]), 2) == 60.0

    # 超额必须拦：否则完结闸的"已开票"会大于单据金额，单据静默变成"超额开票"
    over = client.post(
        f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={"total_amount": 999}
    )
    assert over.status_code == 400, over.text

    second = client.post(f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={})
    assert second.status_code == 201, second.text
    assert round(float(second.json()["uninvoiced_amount"]), 2) == 0.0

    # 开齐了再开 → 409（防重复开票；也防止"一张单开出三张同额票"）
    again = client.post(f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={})
    assert again.status_code == 409, again.text
    assert "已开齐" in again.text


def test_issue_invoice_rejects_duplicate_real_invoice_no():
    customer = _customer()
    product = _product()
    _opening(product["id"])
    outbound = _outbound(customer["id"], product["id"], 30.0)

    existing = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": _uniq("INV"),
            "invoice_type": "普票",
            "issue_date": TODAY,
            "total_amount": 1.0,
            "direction": "output",
        },
    ).json()

    clash = client.post(
        f"/api/v1/sales-orders/{outbound['id']}/issue-invoice",
        json={"invoice_no": existing["invoice_no"]},
    )
    assert clash.status_code == 409, clash.text


def test_issue_invoice_rejects_cancelled_order():
    customer = _customer()
    product = _product()
    _opening(product["id"])
    outbound = _outbound(customer["id"], product["id"], 20.0)
    # 出库单不能直接退回草稿；作废走 cancelled
    cancelled = client.patch(
        f"/api/v1/sales-orders/{outbound['id']}/status", json={"status": "cancelled"}
    )
    assert cancelled.status_code == 200, cancelled.text

    response = client.post(f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={})
    assert response.status_code == 409, response.text
    assert "作废" in response.text


# ===========================================================================
# 三、完结闸四字段（2026-10-22 恢复，之前静默丢失）
# ===========================================================================
def _outbound_row(order_id: int) -> dict:
    """从列表里按 id 取一行（前端「标记为已完结 / 一键开票」读的就是这份数据）。"""
    rows = client.get("/api/v1/sales-orders?doc_type=outbound").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    hit = [row for row in rows if int(row["id"]) == int(order_id)]
    assert hit, f"出库单 {order_id} 不在列表里"
    return hit[0]


def test_list_exposes_settlement_fields():
    """列表必须返回 settled / invoiced / outstanding / uninvoiced。

    这四个字段曾经在重构里丢掉，前端 `canComplete = Boolean(settled)` 恒为 false，
    于是「标记为已完结」按钮**永远是灰的**，而页面一声不响 —— 静默断链。
    """
    customer = _customer()
    product = _product()
    _opening(product["id"])
    outbound = _outbound(customer["id"], product["id"], 100.0)

    row = _outbound_row(outbound["id"])
    assert row["uninvoiced_amount"] == 100.0, row
    assert row["outstanding_amount"] == 100.0, row
    assert row["invoiced_amount"] == 0.0, row
    assert row["settled"] is False


def test_settled_requires_both_money_and_invoice():
    """钱票两清才算完结：只开票不收款、只收款不开票，都必须 settled=false。"""
    customer = _customer()
    product = _product()
    _opening(product["id"])
    outbound = _outbound(customer["id"], product["id"], 90.0)

    # ① 只开票 → 未开票归零，但还欠钱
    client.post(f"/api/v1/sales-orders/{outbound['id']}/issue-invoice", json={})
    row = _outbound_row(outbound["id"])
    assert row["uninvoiced_amount"] == 0.0
    assert row["outstanding_amount"] == 90.0
    assert row["settled"] is False

    # ② 再收齐 → 两个口径都归零，才可以完结
    paid = client.post(
        "/api/v1/finance/receipt",
        json={
            "party_id": customer["id"],
            "order_id": outbound["id"],
            "amount": 90.0,
            "occurred_at": TODAY,
        },
    )
    assert paid.status_code == 201, paid.text
    row = _outbound_row(outbound["id"])
    assert row["outstanding_amount"] == 0.0
    assert row["uninvoiced_amount"] == 0.0
    assert row["settled"] is True

    # ③ 服务端确实放行完结（前端按钮的依据与现实一致，不是"亮了却被 409"）
    done = client.patch(f"/api/v1/sales-orders/{outbound['id']}/status", json={"status": "completed"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
