"""进项发票（供应商 + 认证抵扣）回归测试 —— 2026-10-26。

## 这一批到底在守什么

进项票以前只有 `seller_name` 文本，没有供应商档案、没有"认证"这个动作，
于是三件事长期是错的：

1. **挂不上单**：`services/invoice_match` 对进项永远拿不到"按档案 id 命中"那一档，
   同金额候选分不出高下，自动挂入库单长期命中率偏低；
2. **没有认证状态**：`deducted` 一个 bool 装不下「已认证待抵扣」—— 那是月底最需要
   盯的真实状态（认证了、还没在申报表里抵）；
3. **进项税额无口径**：驾驶舱没有「本月已认证进项税额」，财务只能拿 Excel 另记一本账。

## 被钉住的约束（每条都对应一个曾经会静默出错的地方）

- 建票时给 `certified` 与 PATCH 走**同一套**校验，且 `certified_at` 只由服务器落；
- 方向切到进项时清掉 `customer_id`，反之清 `supplier_id` —— 两个 id 同时有值会让
  应收、应付两套对账**都认领同一张票**；
- 不传 `supplier_id` 时按**税号唯一命中**自动匹配（名称写成简称也要能挂上）；
- 状态机单向：未认证 → 已认证待抵扣 → 已抵扣；已抵扣时撤销认证 400；
  取消抵扣**保留认证**；抵扣时自动补认证；
- 销项票 / 普票不许认证抵扣（400）；
- 进项挂单要求单据供应商与发票销售方一致，否则应付对账串户；
- 列表筛选 `supplier_id / certified / deduction_state` 与派生状态口径一致；
- `/invoices/summary` 的 `input_tax` 与 `/dashboard/executive` 的「本月已认证进项税额」
  必须是**同一个数**（共用 `app/services/invoice_tax.py`）。

测试数据遵守 `scripts/clean_test_data.py` 的编码签名（SKU-/SUP- + 8 位 hex，
发票号 `E2E-INV-`），并在本模块结束时主动删除创建的发票与采购单。
"""

import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()

CREATED_INVOICES: list[int] = []
CREATED_ORDERS: list[int] = []


@pytest.fixture(scope="module", autouse=True)
def _purge_created_rows():
    """模块跑完把票和采购单删掉。

    发票号虽然是 `E2E-INV-` 前缀（清理脚本也认），但那个脚本只在整轮 pytest
    结束时兜底；单跑本文件时它不会触发，所以这里自己收尾，避免把票漏在库里。
    """
    yield
    for invoice_id in CREATED_INVOICES:
        client.delete(f"/api/v1/invoices/{invoice_id}")
    for order_id in CREATED_ORDERS:
        client.delete(f"/api/v1/purchase-orders/{order_id}")


def _hex(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def _supplier(name: str | None = None, tax_no: str | None = None) -> dict:
    payload = {"code": f"SUP-INV-{_hex()}", "name": name or f"测试供应商进项{_hex(6)}"}
    if tax_no is not None:
        payload["tax_no"] = tax_no
    response = client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    response = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-INV-{_hex()}", "name": "测试进项商品", "unit": "件"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _purchase_order(supplier_id: int, product_id: int) -> dict:
    """建一张 doc_type=order 的采购单。

    刻意用「订单」而不是「入库单」：订单不动库存、不产生应付，用例只验证
    `_validate_related_order` 的供应商一致性，不该顺带污染库存与财务流水。
    """
    response = client.post(
        "/api/v1/purchase-orders",
        json={
            "doc_type": "order",
            "supplier_id": supplier_id,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": 100.0}],
            "note": "测试进项发票挂单",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    CREATED_ORDERS.append(int(data["id"]))
    return data


def _invoice(**body) -> dict:
    payload = {
        "invoice_no": f"E2E-INV-{_hex()}",
        "invoice_type": "专票",
        "issue_date": TODAY,
        "direction": "input",
        "status": "已确认",
        "total_amount": 1130.0,
        "excl_tax_amount": 1000.0,
        "tax_amount": 130.0,
        "tax_rate": 13,
    }
    payload.update(body)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    CREATED_INVOICES.append(int(data["id"]))
    return data


def _items(query: str) -> list[dict]:
    response = client.get(f"/api/v1/invoices{query}")
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ---------- 1. 供应商档案 + 认证落库 ----------


def test_create_input_invoice_binds_supplier_and_certifies():
    """建票时直接给「已认证」：档案挂上、另一侧清空、时间戳由服务器落。"""
    supplier = _supplier()
    data = _invoice(supplier_id=supplier["id"], certified=True)

    assert data["supplier_id"] == supplier["id"]
    # 进项票不能同时挂客户：否则应收、应付两套对账都认领这张票
    assert data["customer_id"] is None
    assert data["certified"] is True
    assert data["deducted"] is False
    assert data["certified_at"], "认证时间必须由服务器落，不能为空"
    assert data["deduction_state"] == "certified"
    assert data["deduction_state_label"] == "已认证待抵扣"


def test_create_input_invoice_matches_supplier_by_tax_no():
    """不传 supplier_id 时按税号自动挂供应商 —— 名称是简称也要能挂上。"""
    tax_no = f"9161{_hex(10).upper()}"
    supplier = _supplier(tax_no=tax_no)
    # 票面写成小写 + 带空格，模拟 OCR 出来的税号格式
    spelled = f"{tax_no[:4].lower()} {tax_no[4:10]} {tax_no[10:]}"
    data = _invoice(seller_name="简称供应商（与档案全称不同）", seller_tax_no=spelled)

    assert data["supplier_id"] == supplier["id"], "税号唯一命中时必须挂上，不能靠名称猜"


# ---------- 2. 只有进项专票能认证 / 抵扣 ----------


def test_output_invoice_cannot_be_certified_or_deducted():
    response = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": f"E2E-INV-{_hex()}",
            "invoice_type": "专票",
            "issue_date": TODAY,
            "direction": "output",
            "certified": True,
        },
    )
    assert response.status_code == 400, response.text
    assert "销项" in response.json()["detail"]

    data = _invoice(direction="output")
    rejected = client.patch(f"/api/v1/invoices/{data['id']}", json={"deducted": True})
    assert rejected.status_code == 400, rejected.text
    assert "销项" in rejected.json()["detail"]
    # 销项票不该被挂上供应商档案
    assert data["supplier_id"] is None


def test_normal_invoice_cannot_be_certified():
    """普票政策上不可抵扣：标了就会凭空多出一块进项税额，必须当场 400。"""
    data = _invoice(invoice_type="普票", tax_amount=0.0)
    response = client.patch(f"/api/v1/invoices/{data['id']}", json={"certified": True})
    assert response.status_code == 400, response.text
    assert "专用发票" in response.json()["detail"]


# ---------- 3. 认证 / 抵扣状态机 ----------


def test_deduct_auto_certifies_with_timestamps():
    """抵扣时自动补认证：先抵扣后认证在税上根本不成立，不能让用户点两次。"""
    data = _invoice()
    response = client.patch(f"/api/v1/invoices/{data['id']}", json={"deducted": True})
    assert response.status_code == 200, response.text
    updated = response.json()

    assert updated["deducted"] is True
    assert updated["certified"] is True, "抵扣必须自动补认证"
    assert updated["certified_at"] and updated["deducted_at"]
    assert updated["deduction_state"] == "deducted"


def test_undeduct_keeps_certification_but_revoking_certification_is_blocked():
    """已抵扣时不许撤销认证；取消抵扣后认证保留，此后才允许撤销认证。"""
    data = _invoice(certified=True)

    while_deducted_block = client.patch(f"/api/v1/invoices/{data['id']}", json={"deducted": True})
    assert while_deducted_block.status_code == 200, while_deducted_block.text
    certified_at = while_deducted_block.json()["certified_at"]

    rejected = client.patch(f"/api/v1/invoices/{data['id']}", json={"certified": False})
    assert rejected.status_code == 400, rejected.text
    assert "先取消抵扣" in rejected.json()["detail"]

    undeducted = client.patch(f"/api/v1/invoices/{data['id']}", json={"deducted": False})
    assert undeducted.status_code == 200, undeducted.text
    body = undeducted.json()
    assert body["deducted"] is False
    assert body["deducted_at"] is None, "取消抵扣必须清掉抵扣时间"
    assert body["certified"] is True, "取消抵扣不能顺手把认证也撤了（票确实认证过）"
    assert body["certified_at"] == certified_at
    assert body["deduction_state"] == "certified"

    revoked = client.patch(f"/api/v1/invoices/{data['id']}", json={"certified": False})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["certified_at"] is None
    assert revoked.json()["deduction_state"] == "uncertified"


# ---------- 4. 进项挂单的供应商一致性 ----------


def test_input_invoice_cannot_link_another_suppliers_order():
    """把 A 供应商的票挂到 B 供应商的单上，应付对账会串户 —— 必须 400。"""
    owner = _supplier()
    other = _supplier()
    product = _product()
    order = _purchase_order(owner["id"], product["id"])

    response = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": f"E2E-INV-{_hex()}",
            "invoice_type": "专票",
            "issue_date": TODAY,
            "direction": "input",
            "supplier_id": other["id"],
            "related_order_id": order["id"],
        },
    )
    assert response.status_code == 400, response.text
    assert "供应商" in response.json()["detail"]

    data = _invoice(supplier_id=owner["id"], related_order_id=order["id"])
    assert data["related_order_id"] == order["id"]

    # 单号只有 PATCH 类响应才下发（列表接口不下发），顺便验证
    # `_order_no_map` 的「按方向分表」没有错位 —— 同一个 id 在两张表里可能撞号。
    echoed = client.patch(f"/api/v1/invoices/{data['id']}", json={"handler": "测试经办"})
    assert echoed.status_code == 200, echoed.text
    assert echoed.json()["related_order_no"] == order["order_no"]


# ---------- 5. 列表筛选 ----------


def test_list_filters_by_supplier_and_deduction_state():
    supplier = _supplier()
    certified = _invoice(supplier_id=supplier["id"], certified=True)
    pending = _invoice(supplier_id=supplier["id"])

    by_supplier = _items(f"?supplier_id={supplier['id']}")
    ids = {row["id"] for row in by_supplier}
    assert {certified["id"], pending["id"]} <= ids
    assert all(row["supplier_id"] == supplier["id"] for row in by_supplier)

    only_certified = {row["id"] for row in _items(f"?supplier_id={supplier['id']}&certified=yes")}
    assert certified["id"] in only_certified
    assert pending["id"] not in only_certified

    by_state = {row["id"] for row in _items(f"?supplier_id={supplier['id']}&deduction_state=certified")}
    assert certified["id"] in by_state
    assert pending["id"] not in by_state

    uncertified_ids = {row["id"] for row in _items(f"?supplier_id={supplier['id']}&deduction_state=uncertified")}
    assert pending["id"] in uncertified_ids
    assert certified["id"] not in uncertified_ids

    bad = client.get("/api/v1/invoices?certified=maybe")
    assert bad.status_code == 400, bad.text


# ---------- 6. 进项税额口径：两个界面必须是同一个数 ----------


def test_summary_and_dashboard_share_certified_input_tax():
    supplier = _supplier()
    baseline = client.get("/api/v1/dashboard/executive").json()
    baseline_value = next(
        float(kpi["value"]) for kpi in baseline["kpis"] if kpi["label"] == "本月已认证进项税额"
    )

    tax = 247.5
    data = _invoice(supplier_id=supplier["id"], certified=True, tax_amount=tax, total_amount=2147.5)
    assert data["certified"] is True

    summary = client.get("/api/v1/invoices/summary").json()
    input_tax = summary["input_tax"]
    # 按**认证时间**落月，不是开票日：财务问的是"这个月认证了多少"
    assert input_tax["month"] == datetime.now().strftime("%Y-%m")
    assert input_tax["certified_this_month_tax"] >= tax
    # 已认证待抵扣单独一桶，不能混进"已抵扣"
    assert input_tax["certified_pending_count"] >= 1

    after = client.get("/api/v1/dashboard/executive").json()
    after_value = next(
        float(kpi["value"]) for kpi in after["kpis"] if kpi["label"] == "本月已认证进项税额"
    )
    assert round(after_value - baseline_value, 2) == tax, "驾驶舱 KPI 与发票汇总必须同一口径"
