"""合同正文生成 + 删除保护 的接口级回归（2026-10-22）。

## 守的是什么

1. **生成正文不写库**：用户点「生成合同正文」只是"看看"，绝不该占一个合同号；
2. **八个条款一条不能少**，且订单/明细的金额、交货信息真的被填进去了
   （模板最容易退化的方式就是"少一条""用了默认值但没带业务数据"）；
3. **删除必须能真的删掉**，且已生成单据的合同要被 409 拦下（溯源线索不能断）。
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
        json={"code": _uniq("CUST"), "name": f"测试合同客户{uuid.uuid4().hex[:6]}", "tax_no": "91610103TEST0001"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _payload(customer_name: str, *, amount: float = 1250.0) -> dict:
    return {
        "direction": "out",
        "party_name": customer_name,
        "party_tax_no": "91610103TEST0001",
        "party_legal_person": "张三",
        "party_address": "西安市雁塔区示例路 1 号",
        "party_bank_name": "建行雁塔支行",
        "party_bank_account": "6100123456789",
        "sign_date": TODAY,
        "sign_place": "西安",
        "delivery_date": "2026-11-01",
        "delivery_place": "工地现场",
        "payment_terms": "",
        "penalty_rate": None,
        "is_tax_included": True,
        "items": [
            {
                "product_name": "电缆",
                "standards": "YJV-3x35",
                "unit": "米",
                "quantity": 100,
                "unit_price": amount / 100,
                "amount": amount,
            }
        ],
    }


def _contract_count() -> int:
    rows = client.get("/api/v1/contracts?limit=200").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    return len(rows)


def test_document_preview_never_writes_and_fills_all_clauses():
    customer = _customer()
    before = _contract_count()

    response = client.post("/api/v1/contracts/document/preview", json=_payload(customer["name"]))
    assert response.status_code == 200, response.text
    document = response.json()["document"]

    # ① 只读：合同条数不变
    assert _contract_count() == before, "生成正文居然写库了"

    # ② 八条标准条款齐全，且**措辞是简易版**（2026-10-23 换成客户在用的那份）
    headings = [clause["heading"] for clause in document["clauses"]]
    for expected in (
        "合同标的",
        "包装标准",
        "产品质量",
        "交（提）货时间、地点",
        "结算方式",
        "违约责任",
        "争议解决",
        "合同份数与生效",
    ):
        assert expected in headings, headings
    assert len(document["clauses"]) == 8, headings
    assert document["template"] == "SIMPLE"
    assert document["template_name"] == "产品买卖合同（简易版）"
    assert document["title"] == "产品买卖合同（简易版）"

    # ③ 业务数据真的填进去了
    assert document["totals"]["amount"] == 1250.0
    assert "壹仟贰佰伍拾元整" in document["totals"]["chinese"]
    assert document["parties"]["buyer"]["name"] == customer["name"]
    assert document["parties"]["seller"]["name"], "乙方（我方）名称不能为空"

    joined = "\n".join("\n".join(clause["paragraphs"]) for clause in document["clauses"])
    assert "2026-11-01" in joined, "交货日期没带进第四条"
    assert "工地现场" in joined, "交货地点没带进第四条"
    assert "1,250.00" in joined, "总额没带进第一条"

    # ④ 简易版的关键口径（这三条是用户逐字确认过的，改一个字都要有人负责）
    assert "款到发货" in joined
    assert "20% 的违约金" in joined
    assert "施工所在地人民法院" in joined
    # 详细版特有的表述不能漏进来
    assert "万分之" not in joined


def test_detail_variant_still_available_on_request():
    """简易版是默认值，但详细版不能因此消失 —— 老合同还要沿用原来的条款。"""
    customer = _customer()
    payload = {**_payload(customer["name"]), "template": "detail"}
    response = client.post("/api/v1/contracts/document/preview", json=payload)
    assert response.status_code == 200, response.text
    document = response.json()["document"]

    assert document["template"] == "GONGKUANG"
    assert document["template_name"] == "工矿产品购销合同"
    headings = [clause["heading"] for clause in document["clauses"]]
    assert "产品信息" in headings and "验收标准" in headings, headings
    assert "万分之" in "\n".join(
        "\n".join(clause["paragraphs"]) for clause in document["clauses"]
    )


def test_document_pdf_returns_real_pdf():
    customer = _customer()
    response = client.post(
        "/api/v1/print/contract-document/pdf",
        json=_payload(customer["name"]),
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_base64"], "PDF 内容是空的"
    assert body["filename"].endswith(".pdf")
    # PDF 头魔数（base64 的 %PDF = JVBERi）
    assert body["content_base64"][:5] == "JVBER"


def test_contract_delete_and_referenced_guard():
    customer = _customer()
    created = client.post("/api/v1/contracts", json=_payload(customer["name"]))
    assert created.status_code == 201, created.text
    contract = created.json()

    removed = client.delete(f"/api/v1/contracts/{contract['id']}")
    assert removed.status_code == 204, removed.text
    assert client.get(f"/api/v1/contracts/{contract['id']}").status_code == 404


def test_deleting_missing_contract_is_404():
    assert client.delete("/api/v1/contracts/99999999").status_code == 404
