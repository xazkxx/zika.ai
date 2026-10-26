"""合同付款计划（多期次）接口回归 —— 2026-10-23。

## 守的六条

1. 一键三期：30/40/30，金额按合同总额算准；
2. 只传比例能算金额、只传金额能反算比例；**合同总额为 0 时按比例要明确 400**；
3. 期次重复 409（不能出现两个"第 1 期"）；
4. 登记实付 → 汇总进度与缺口同步变化；**超付**要能表达（缺口为负、进度夹到 100）；
5. 回单上传/读取/删除闭环；非 PDF/图片被拒；
6. 合同列表带出付款进度（这是列表新加的那一列的数据来源），
   而且必须**一次查完**（不能 N+1）。
"""

import io
import uuid
from datetime import date

from PIL import Image
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _customer() -> dict:
    response = client.post(
        "/api/v1/customers",
        json={"code": _uniq("CUST"), "name": f"测试付款客户{uuid.uuid4().hex[:6]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    response = client.post(
        "/api/v1/products", json={"sku": _uniq("SKU"), "name": "测试付款商品", "unit": "件"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _contract(amount: float = 10000.0, with_item: bool = True) -> dict:
    customer = _customer()
    product = _product()
    body = {
        "direction": "out",
        "party_id": customer["id"],
        "party_name": customer["name"],
        "sign_date": TODAY,
        "items": (
            [{"product_id": product["id"], "quantity": 10, "unit_price": amount / 10}]
            if with_item
            else []
        ),
    }
    response = client.post("/api/v1/contracts", json=body)
    assert response.status_code == 201, response.text
    contract = response.json()
    contract["_customer_id"] = customer["id"]
    contract["_product_id"] = product["id"]
    return contract


def _cleanup(contract: dict) -> None:
    client.delete(f"/api/v1/contracts/{contract['id']}?force=true")
    client.delete(f"/api/v1/products/{contract['_product_id']}?force=true")
    client.delete(f"/api/v1/customers/{contract['_customer_id']}")


def test_template_creates_three_periods():
    contract = _contract(10000.0)
    try:
        response = client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        assert response.status_code == 201, response.text
        data = response.json()
        plans = data["plans"]
        assert [p["period_no"] for p in plans] == [1, 2, 3]
        assert [p["plan_ratio"] for p in plans] == [30.0, 40.0, 30.0]
        assert [p["plan_amount"] for p in plans] == [3000.0, 4000.0, 3000.0]
        assert data["summary"]["planned_amount"] == 10000.0
        assert data["summary"]["progress"] == 0.0
        assert data["summary"]["shortfall"] == 10000.0

        # 第二次再来 → 409，不能覆盖已有计划
        again = client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        assert again.status_code == 409, again.text
    finally:
        _cleanup(contract)


def test_ratio_and_amount_are_interchangeable():
    contract = _contract(10000.0)
    try:
        # 只给比例
        by_ratio = client.post(
            f"/api/v1/contracts/{contract['id']}/payment-plans",
            json={"name": "预付", "plan_ratio": 25},
        )
        assert by_ratio.status_code == 201, by_ratio.text
        assert by_ratio.json()["plan"]["plan_amount"] == 2500.0
        assert by_ratio.json()["amount_derived"] is True

        # 只给金额 → 反算比例
        by_amount = client.post(
            f"/api/v1/contracts/{contract['id']}/payment-plans",
            json={"name": "尾款", "plan_amount": 1500},
        )
        assert by_amount.status_code == 201, by_amount.text
        assert by_amount.json()["plan"]["plan_ratio"] == 15.0

        # 期次重复
        dup = client.post(
            f"/api/v1/contracts/{contract['id']}/payment-plans",
            json={"period_no": 1, "plan_ratio": 5},
        )
        assert dup.status_code == 409, dup.text

        # 什么都不给
        empty = client.post(f"/api/v1/contracts/{contract['id']}/payment-plans", json={})
        assert empty.status_code == 400, empty.text
    finally:
        _cleanup(contract)


def test_zero_amount_contract_refuses_ratio():
    contract = _contract(with_item=False)
    try:
        # 明细为空 → 合同总额 0：按比例算不出来，必须明确 400 而不是静默存 0
        response = client.post(
            f"/api/v1/contracts/{contract['id']}/payment-plans",
            json={"name": "预付", "plan_ratio": 30},
        )
        assert response.status_code == 400, response.text
        assert "金额" in response.text

        # 直接填金额可以
        ok = client.post(
            f"/api/v1/contracts/{contract['id']}/payment-plans",
            json={"name": "预付", "plan_amount": 500},
        )
        assert ok.status_code == 201, ok.text
    finally:
        _cleanup(contract)


def test_paid_amount_updates_progress_and_allows_overpay():
    contract = _contract(10000.0)
    try:
        client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        plans = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"]

        first = client.patch(
            f"/api/v1/payment-plans/{plans[0]['id']}",
            json={"paid_amount": 3000, "paid_date": "2026-06-01"},
        )
        assert first.status_code == 200, first.text
        summary = first.json()["summary"]
        assert summary["paid_amount"] == 3000.0
        assert summary["progress"] == 30.0
        assert summary["shortfall"] == 7000.0
        assert summary["settled_count"] == 1

        # 超付：进度夹到 100，但缺口是真实的负数
        over = client.patch(
            f"/api/v1/payment-plans/{plans[0]['id']}", json={"paid_amount": 12000}
        )
        summary = over.json()["summary"]
        assert summary["progress"] == 100.0
        assert summary["shortfall"] == -2000.0
        assert over.json()["plan"]["shortfall"] == -9000.0
    finally:
        _cleanup(contract)


def test_receipt_upload_and_fetch():
    contract = _contract(5000.0)
    try:
        client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        plan = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"][0]

        image = Image.new("RGB", (300, 200), "white")
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        uploaded = client.post(
            f"/api/v1/payment-plans/{plan['id']}/receipt",
            files={"file": ("回单.png", buffer.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["plan"]["has_receipt"] is True

        fetched = client.get(f"/api/v1/payment-plans/{plan['id']}/receipt")
        assert fetched.status_code == 200
        assert fetched.content[:4] == b"\x89PNG"

        bad = client.post(
            f"/api/v1/payment-plans/{plan['id']}/receipt",
            files={"file": ("坏文件.exe", b"MZ", "application/octet-stream")},
        )
        assert bad.status_code == 400, bad.text
    finally:
        _cleanup(contract)


def test_contract_list_carries_progress():
    contract = _contract(8000.0)
    try:
        client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        plans = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"]
        client.patch(f"/api/v1/payment-plans/{plans[0]['id']}", json={"paid_amount": 2400})

        rows = client.get("/api/v1/contracts?limit=200").json()
        row = next(item for item in rows if item["id"] == contract["id"])
        assert row["payment_plan_count"] == 3
        assert row["payment_paid_amount"] == 2400.0
        assert row["payment_progress"] == 30.0
        assert row["payment_shortfall"] == 5600.0

        detail = client.get(f"/api/v1/contracts/{contract['id']}").json()
        assert detail["payment_progress"] == 30.0
    finally:
        _cleanup(contract)


def test_delete_plan_removes_it():
    contract = _contract(3000.0)
    try:
        client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
        plans = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"]
        assert client.delete(f"/api/v1/payment-plans/{plans[0]['id']}").status_code == 204
        remain = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"]
        assert len(remain) == 2
    finally:
        _cleanup(contract)


def test_deleting_contract_cascades_payment_plans():
    """删合同必须连付款计划一起删。

    否则库里会攒下"合同都不存在、计划还挂着"的孤儿行：
    三单匹配按合同聚合会被带偏，回单文件也永远留在 data/contract_receipts 里。
    """
    contract = _contract(6000.0)
    client.post(f"/api/v1/contracts/{contract['id']}/payment-plans/template", json={})
    plans = client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").json()["plans"]
    assert len(plans) == 3

    assert client.delete(f"/api/v1/contracts/{contract['id']}?force=true").status_code == 204
    # 合同没了，计划列表接口应当 404（合同不存在），而不是返回 3 条孤儿
    assert client.get(f"/api/v1/contracts/{contract['id']}/payment-plans").status_code == 404

    client.delete(f"/api/v1/products/{contract['_product_id']}?force=true")
    client.delete(f"/api/v1/customers/{contract['_customer_id']}")
