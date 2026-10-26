"""客户/供应商「开票信息」字段的接口级回归（2026-10-23）。

## 这次改了什么

表单里的「客户级别 level」去掉，换成开票真正要用到的四列：
`tax_no / bank_name / bank_account / invoice_phone`。
其中 `tax_no`、`bank_name`、`bank_account` 库里本来就有（只是表单没放出来），
`invoice_phone` 是**新列**，靠 `main._add_missing_columns` 的幂等迁移补上。

## 守的四件事

1. 新列真的建出来了（客户 + 供应商两张表），且可空（老档案不受影响）；
2. 创建/更新接口能收这四个字段，存进去、读得出来；
3. **合同正文**能自动带出税号与开户行/账号（以前只在 `party_name` 为空时才反查，
   而表单里名称早就选好了 —— 结果打出来的合同抬头永远是空的）；
4. 合同抬头电话**优先取开票电话**，没填才退回业务电话。
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _columns(table: str) -> set[str]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("select column_name from information_schema.columns where table_name = :t"),
            {"t": table},
        ).all()
        return {row[0] for row in rows}
    finally:
        db.close()


@pytest.mark.parametrize("table", ["customers", "suppliers"])
def test_invoice_phone_column_exists(table):
    assert "invoice_phone" in _columns(table)


def test_customer_keeps_invoice_fields():
    body = {
        "code": _uniq("CUST"),
        "name": f"测试开票客户{uuid.uuid4().hex[:6]}",
        "tax_no": "91610103MA6TX8K23Q",
        "bank_name": "招商银行西安分行",
        "bank_account": "1298888666601",
        "invoice_phone": "029-88886666",
    }
    created = client.post("/api/v1/customers", json=body)
    assert created.status_code == 201, created.text
    row = created.json()
    try:
        assert row["tax_no"] == "91610103MA6TX8K23Q"
        assert row["bank_name"] == "招商银行西安分行"
        assert row["bank_account"] == "1298888666601"
        assert row["invoice_phone"] == "029-88886666"

        # 重新读一次（确认真的落库，不是回显请求体）。
        # ⚠️ 客户档案**没有** `GET /customers/{id}` 这个路由（只有列表 + PATCH/DELETE），
        #    所以要退回列表里找那一行 —— 直接 GET 详情会拿到 404 的 detail 字典，
        #    然后 KeyError 看起来像"字段没存上"，其实是路由不存在。
        rows = client.get("/api/v1/customers?limit=500").json()
        rows = rows if isinstance(rows, list) else rows.get("items") or []
        again = next((item for item in rows if item["id"] == row["id"]), None)
        assert again is not None, "新建的客户没出现在列表里"
        assert again["invoice_phone"] == "029-88886666"

        # PATCH 只改一个字段，不许把别的清空
        patched = client.patch(
            f"/api/v1/customers/{row['id']}",
            json={"invoice_phone": "029-11112222"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["invoice_phone"] == "029-11112222"
        assert patched.json()["tax_no"] == "91610103MA6TX8K23Q"
        assert patched.json()["bank_name"] == "招商银行西安分行"
    finally:
        client.delete(f"/api/v1/customers/{row['id']}")


def test_supplier_keeps_invoice_fields():
    created = client.post(
        "/api/v1/suppliers",
        json={
            "code": _uniq("SUP"),
            "name": f"测试开票供应商{uuid.uuid4().hex[:6]}",
            "tax_no": "9144030071526726X9",
            "bank_name": "建设银行深圳科技园支行",
            "bank_account": "755912345678901",
            "invoice_phone": "0755-26551234",
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    try:
        assert row["invoice_phone"] == "0755-26551234"
        assert row["bank_account"] == "755912345678901"
    finally:
        client.delete(f"/api/v1/suppliers/{row['id']}")


def test_contract_document_pulls_tax_and_bank_from_archive():
    """合同正文必须自动带出税号/开户行/账号；电话优先用开票电话。"""
    customer = client.post(
        "/api/v1/customers",
        json={
            "code": _uniq("CUST"),
            "name": f"测试合同抬头{uuid.uuid4().hex[:6]}",
            "tax_no": "91610103MA6TX8K23Q",
            "bank_name": "招商银行西安分行",
            "bank_account": "1298888666601",
            "phone": "13800138000",
            "invoice_phone": "029-88886666",
        },
    ).json()
    product = client.post(
        "/api/v1/products", json={"sku": _uniq("SKU"), "name": "合同抬头测试商品", "unit": "件"}
    ).json()
    contract = client.post(
        "/api/v1/contracts",
        json={
            "direction": "out",
            "party_id": customer["id"],
            # **故意带上 party_name**：这正是老逻辑失效的场景（名称非空就不反查）
            "party_name": customer["name"],
            "sign_date": TODAY,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}],
        },
    )
    assert contract.status_code == 201, contract.text
    contract_row = contract.json()
    try:
        preview = client.post(
            "/api/v1/contracts/document/preview", json={"contract_id": contract_row["id"]}
        )
        assert preview.status_code == 200, preview.text
        document = preview.json()["document"]
        buyer = document["parties"]["buyer"]
        assert buyer["tax_no"] == "91610103MA6TX8K23Q", buyer
        assert buyer["bank_name"] == "招商银行西安分行", buyer
        assert buyer["bank_account"] == "1298888666601", buyer
        assert buyer["phone"] == "029-88886666", buyer  # 开票电话优先于手机

        # 开票信息要出现在**落款签字块**里（简易版范本的结算条款写的是"款到发货"，
        # 开户行/账号挂在签字块，不在条文里 —— 断言要认这个结构，别拿条文去比）。
        signs = document.get("signatures") or []
        assert any(
            item.get("bank_name") == "招商银行西安分行"
            and item.get("bank_account") == "1298888666601"
            for item in signs
        ), signs
    finally:
        client.delete(f"/api/v1/contracts/{contract_row['id']}?force=true")
        client.delete(f"/api/v1/products/{product['id']}?force=true")
        client.delete(f"/api/v1/customers/{customer['id']}")
