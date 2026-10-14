"""购销合同（模板 A2 · 标准版）模块测试。

覆盖：新建（自动单号 / 明细金额 / 金额大写 / 条款默认兜底）、列表筛选、
详情、修改、状态流转、一键转单（销售合同→销售开单、采购合同→采购入库单，
并验证库存与财务联动）、重复转单 409、已转单合同删除 409 与 force 删除、
A2 合同 PDF 生成与文本抽查、字典接口与 404 分支。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def fx():
    tag = uuid.uuid4().hex[:8]
    wh = client.get("/api/v1/warehouses").json()
    wh_id = (
        wh[0]["id"]
        if wh
        else client.post("/api/v1/warehouses", json={"code": f"WH-{tag}", "name": f"主仓库临时{tag}"}).json()["id"]
    )
    cus = client.post(
        "/api/v1/customers",
        json={
            "code": f"CUST-CONTRACT-{tag}",
            "name": f"测试客户合同{tag}",
            "address": "西安市雁塔区科技路 66 号",
            "contact": "赵敏",
            "contact_phone": "13833334444",
            "tax_no": "91610113MA6U0000XX",
            "bank_name": "中国银行西安分行",
            "bank_account": "1020334455667",
        },
    ).json()
    sup = client.post(
        "/api/v1/suppliers",
        json={
            "code": f"SUP-CONTRACT-{tag}",
            "name": f"测试供应商合同{tag}",
            "address": "西安市高新区纬二十六路 1 号",
            "contact": "张伟",
            "mobile": "13800001111",
        },
    ).json()
    prod = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-CONTRACT-{tag}",
            "name": f"测试商品合同{tag}",
            "standards": "DN100 PN16",
            "unit": "个",
            "purchase_price": 156.5,
            "sale_price": 210.0,
        },
    ).json()

    sales_contract = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "contract_no": f"TEST-HT-S-{tag}",
            "party_id": cus["id"],
            "warehouse_id": wh_id,
            "sign_date": "2026-10-10",
            "sign_place": "西安市",
            "delivery_date": "2026-10-20",
            "delivery_place": "西安市雁塔区科技路 66 号",
            "items": [{"product_id": prod["id"], "quantity": 2, "unit_price": 210.0, "note": "急件"}],
        },
    ).json()
    purchase_contract = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "purchase",
            "contract_no": f"TEST-HT-P-{tag}",
            "party_id": sup["id"],
            "sign_date": "2026-10-11",
            "quality_standard": "GB/T 12224 国家标准",
            "inspection_days": 5,
            "copies": 4,
            "items": [
                {"product_id": prod["id"], "quantity": 20, "unit_price": 156.5},
                {"product_id": prod["id"], "quantity": 15, "unit_price": 88.0},
            ],
        },
    ).json()
    return {
        "tag": tag,
        "wh_id": wh_id,
        "cus": cus,
        "sup": sup,
        "prod": prod,
        "sales_contract": sales_contract,
        "purchase_contract": purchase_contract,
    }


def test_contract_meta(contracts_meta=None):
    meta = client.get("/api/v1/contracts/meta").json()
    assert any(t["code"] == "A2" for t in meta["templates"])
    assert {t["code"] for t in meta["types"]} == {"sales", "purchase"}
    assert {s["code"] for s in meta["statuses"]} == {"draft", "signed", "executing", "finished", "void"}
    assert "quality_standard" in meta["defaults"]
    assert meta["inspection_days"] == 7
    assert meta["penalty_rate"] == pytest.approx(0.0005)


def test_contract_create_auto_no_and_defaults(fx):
    """自动单号 + 明细快照 + 金额大写 + 条款默认兜底 —— 合同没填的变量要有行业常规表述。"""
    resp = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "party_id": fx["cus"]["id"],
            "items": [{"product_id": fx["prod"]["id"], "quantity": 2, "unit_price": 210.0}],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["contract_no"].startswith("HT")
    assert len(data["contract_no"]) == len("HT") + 8 + 3
    assert data["total_amount"] == pytest.approx(420.0)
    assert data["amount_chinese"] == "肆佰贰拾元整"
    assert data["title"] == "销售合同"
    assert data["status"] == "draft"
    assert len(data["items"]) == 1
    assert data["items"][0]["product_name"] == fx["prod"]["name"]
    assert data["items"][0]["standards"] == "DN100 PN16"
    assert data["items"][0]["unit"] == "个"
    assert data["items"][0]["amount"] == pytest.approx(420.0)
    # 对方档案自动带出
    assert data["party_name"] == fx["cus"]["name"]
    assert data["party_tax_no"] == "91610113MA6U0000XX"
    assert data["party_contact"] == "赵敏"
    # 条款变量兜底
    assert data["quality_standard"]
    assert data["payment_terms"]
    assert data["inspection_days"] == 7
    assert data["objection_days"] == 15
    assert data["penalty_rate"] == pytest.approx(0.0005)
    assert data["copies"] == 2
    assert data["sign_date"] == "2026-10-10"


def test_contract_type_and_party_validation(fx):
    # 编号重复必须拦住
    dup = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "contract_no": fx["sales_contract"]["contract_no"],
            "party_id": fx["cus"]["id"],
            "items": [{"product_id": fx["prod"]["id"], "quantity": 1, "unit_price": 1.0}],
        },
    )
    assert dup.status_code == 400
    # 非法类型
    bad = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "lease",
            "party_id": fx["cus"]["id"],
            "items": [{"product_id": fx["prod"]["id"], "quantity": 1, "unit_price": 1.0}],
        },
    )
    assert bad.status_code == 400
    # 对方档案不存在
    missing = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "party_id": 99999999,
            "items": [{"product_id": fx["prod"]["id"], "quantity": 1, "unit_price": 1.0}],
        },
    )
    assert missing.status_code == 404
    # 采购合同明细里的自定义条款要落库
    pc = fx["purchase_contract"]
    assert pc["contract_type"] == "purchase"
    assert pc["title"] == "采购合同"
    assert pc["quality_standard"] == "GB/T 12224 国家标准"
    assert pc["inspection_days"] == 5
    assert pc["copies"] == 4
    assert pc["total_amount"] == pytest.approx(20 * 156.5 + 15 * 88.0)


def test_contract_list_and_filters(fx):
    all_rows = client.get("/api/v1/contracts").json()
    assert len(all_rows) >= 2

    sales_rows = client.get("/api/v1/contracts", params={"contract_type": "sales"}).json()
    assert sales_rows and all(r["contract_type"] == "sales" for r in sales_rows)

    draft_rows = client.get("/api/v1/contracts", params={"status": "draft"}).json()
    assert all(r["status"] == "draft" for r in draft_rows)

    kw = client.get("/api/v1/contracts", params={"keyword": fx["tag"]}).json()
    assert len(kw) >= 2

    by_party = client.get("/api/v1/contracts", params={"party_id": fx["cus"]["id"]}).json()
    assert any(r["id"] == fx["sales_contract"]["id"] for r in by_party)

    by_sup = client.get("/api/v1/contracts", params={"party_id": fx["sup"]["id"]}).json()
    assert any(r["id"] == fx["purchase_contract"]["id"] for r in by_sup)


def test_contract_detail_and_update(fx):
    """详情 / 修改：用独立合同验证，避免污染后面打印测试依赖的基准数据。"""
    tmp = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "purchase",
            "contract_no": f"TEST-HT-ED-{fx['tag'][:4]}",
            "party_id": fx["sup"]["id"],
            "items": [{"product_id": fx["prod"]["id"], "quantity": 2, "unit_price": 210.0}],
        },
    ).json()
    cid = tmp["id"]
    assert client.get(f"/api/v1/contracts/{cid}").json()["id"] == cid
    assert client.get("/api/v1/contracts/99999999").status_code == 404

    resp = client.patch(
        f"/api/v1/contracts/{cid}",
        json={"status": "signed", "quality_standard": "双方确认的技术协议附件一", "sign_place": "西安高新区"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "signed"
    assert data["quality_standard"] == "双方确认的技术协议附件一"
    assert data["sign_place"] == "西安高新区"

    # 明细整单替换后金额与大写要跟着变
    resp = client.patch(
        f"/api/v1/contracts/{cid}",
        json={"items": [{"product_id": fx["prod"]["id"], "quantity": 3, "unit_price": 210.0}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_amount"] == pytest.approx(630.0)
    assert data["amount_chinese"] == "陆佰叁拾元整"
    assert len(data["items"]) == 1

    # 非法状态 / 不存在的合同
    assert client.patch(f"/api/v1/contracts/{cid}", json={"status": "unknown"}).status_code == 400
    assert client.patch(f"/api/v1/contracts/{cid}/status", json={"status": "nope"}).status_code == 400
    assert client.patch(f"/api/v1/contracts/{cid}/status", json={"status": "executing"}).status_code == 200
    assert client.patch("/api/v1/contracts/99999999/status", json={"status": "signed"}).status_code == 404


def test_contract_to_purchase_order(fx):
    """采购合同 → 采购入库单：入库联动库存、产生应付。"""
    cid = fx["purchase_contract"]["id"]

    def stock_qty():
        rows = client.get("/api/v1/inventory/stock", params={"product_id": fx["prod"]["id"]}).json()["rows"]
        return sum(row["quantity"] for row in rows)

    before_stock = stock_qty()
    resp = client.post(f"/api/v1/contracts/{cid}/to-order")
    assert resp.status_code == 200
    result = resp.json()
    assert result["order_type"] == "purchase_order"
    assert result["order_no"].startswith("CG")
    assert result["order_amount"] == pytest.approx(4450.0)

    # 合同回填单据号并进入执行中
    detail = client.get(f"/api/v1/contracts/{cid}").json()
    assert detail["order_id"] == result["order_id"]
    assert detail["order_no"] == result["order_no"]
    assert detail["status"] == "executing"

    # 库存联动：入库 35 件
    assert stock_qty() == before_stock + 35

    # 财务联动：产生应付，且能通过单据号溯源
    finance = client.get("/api/v1/finance").json()
    assert any(
        row.get("doc_no") == result["order_no"] and row.get("transaction_type") == "payable" for row in finance
    )

    # 重复转单必须拦住
    assert client.post(f"/api/v1/contracts/{cid}/to-order").status_code == 409


def test_contract_to_sales_order_and_delete_guard(fx):
    """销售合同 → 销售开单：出库联动库存、产生应收；已转单的合同不能直接删。"""
    cid = fx["sales_contract"]["id"]

    def stock_qty():
        rows = client.get("/api/v1/inventory/stock", params={"product_id": fx["prod"]["id"]}).json()["rows"]
        return sum(row["quantity"] for row in rows)

    before_stock = stock_qty()
    before_finance = len(client.get("/api/v1/finance").json())

    resp = client.post(f"/api/v1/contracts/{cid}/to-order")
    assert resp.status_code == 200
    result = resp.json()
    assert result["order_type"] == "sales_order"
    assert result["order_no"].startswith("XS")
    assert result["order_amount"] == pytest.approx(420.0)

    assert stock_qty() == before_stock - 2
    finance = client.get("/api/v1/finance").json()
    assert len(finance) > before_finance
    assert any(
        row.get("doc_no") == result["order_no"] and row.get("transaction_type") == "receivable" for row in finance
    )

    # 引用检查：能看到来源单据
    refs = client.get(f"/api/v1/contracts/{cid}/references").json()
    assert refs["references"] and refs["references"][0]["type"] == "order"
    assert refs["references"][0]["doc_no"] == result["order_no"]

    # 已转单：默认拒绝删除，force 才放行
    blocked = client.delete(f"/api/v1/contracts/{cid}")
    assert blocked.status_code == 409
    assert client.delete(f"/api/v1/contracts/{cid}", params={"force": "true"}).status_code == 204
    assert client.get(f"/api/v1/contracts/{cid}").status_code == 404
    assert client.delete("/api/v1/contracts/99999999").status_code == 404
    assert client.get("/api/v1/contracts/99999999/references").status_code == 404


def test_contract_delete_plain(fx):
    """未转单的合同可以直接删，明细一并清掉。"""
    plain = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "contract_no": f"TEST-HT-DEL-{fx['tag'][:4]}",
            "party_id": fx["cus"]["id"],
            "items": [{"product_id": fx["prod"]["id"], "quantity": 1, "unit_price": 10.0}],
        },
    ).json()
    assert client.get(f"/api/v1/contracts/{plain['id']}/references").json()["references"] == []
    assert client.delete(f"/api/v1/contracts/{plain['id']}").status_code == 204
    assert client.get(f"/api/v1/contracts/{plain['id']}").status_code == 404


def test_contract_to_order_requires_party(fx):
    """没有关联档案的合同（只有对方名称快照）不能转单 —— 单据必须要 customer_id/supplier_id。"""
    loose = client.post(
        "/api/v1/contracts",
        json={
            "contract_type": "sales",
            "contract_no": f"TEST-HT-NP-{fx['tag'][:4]}",
            "party_name": f"测试客户合同{fx['tag']}",
            "items": [{"product_id": fx["prod"]["id"], "quantity": 1, "unit_price": 10.0}],
        },
    ).json()
    resp = client.post(f"/api/v1/contracts/{loose['id']}/to-order")
    assert resp.status_code == 400
    assert "档案" in resp.json()["detail"]

    empty = client.post(
        "/api/v1/contracts",
        json={"contract_type": "sales", "contract_no": f"TEST-HT-EM-{fx['tag'][:4]}", "party_id": fx["cus"]["id"]},
    ).json()
    assert client.post(f"/api/v1/contracts/{empty['id']}/to-order").status_code == 400


def test_contract_print_a2_pdf(fx):
    """A2 标准版 PDF：抬头、甲乙方角色、条款框架、变量取值、合计大写都要对。"""
    import pymupdf

    cid = fx["purchase_contract"]["id"]
    resp = client.get(f"/api/v1/print/contract/{cid}")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/pdf")
    assert resp.content[:4] == b"%PDF"

    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    text = "".join(page.get_text() for page in doc)
    doc.close()

    assert "购销合同" in text
    assert fx["purchase_contract"]["contract_no"] in text
    assert "第一条 合同标的" in text
    assert "第十一条 其他约定" in text
    assert "甲方（需方）" in text and "乙方（供方）" in text
    # 采购合同：我方是需方（甲方），供应商是供方（乙方）
    assert fx["sup"]["name"] in text
    # 合同里填的质量标准要出现在条款正文
    assert "GB/T 12224 国家标准" in text
    # 验收期限 5 天取自合同字段
    assert "5 日内完成验收" in text
    assert "合计" in text

    assert client.get("/api/v1/print/contract/99999999").status_code == 404
    assert client.get("/api/v1/print/purchase-order/99999999").status_code == 404
