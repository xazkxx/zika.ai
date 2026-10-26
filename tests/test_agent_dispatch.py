"""智能指令派发（/agent/dispatch）的接口级回归（2026-10-23）。

## 守的四件事

1. **解析**：一句话要能拆出「意图 + 单位名」，且名字里不能带"给我/的对账单"这种残渣；
2. **认人**：全称、简称、联系人三种写法都能落到同一条档案上；认不出要说人话；
3. **取数**：对账单必须能列出"未结清单据"且金额自洽（单据额 − 已收 = 欠款），
   合同必须能列出该单位的合同 —— 并且这些都是**只读**的，调完不许多任何单据；
4. **跳转参数**：`goto.party` 必须是 `c:<id>` / `s:<id>` 这种页面状态能吃下的形状，
   否则前端"跳过去并预填"会静默失效（这条最容易前后端对不上）。

数据全部自己造：客户 + 商品 + 一张出库单（造出欠款）+ 一张合同，跑完删干净。
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TODAY = date.today().isoformat()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _auth() -> dict:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


HEADERS = _auth()


def _warehouse() -> dict:
    rows = client.get("/api/v1/warehouses").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    return rows[0]


def _customer(name: str | None = None, contact: str | None = None) -> dict:
    body = {"code": _uniq("CUST"), "name": name or f"指令测试客户{uuid.uuid4().hex[:6]}"}
    if contact:
        body["contact"] = contact
    response = client.post("/api/v1/customers", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    response = client.post("/api/v1/products", json={"sku": _uniq("SKU"), "name": "指令测试商品", "unit": "件"})
    assert response.status_code == 201, response.text
    return response.json()


def _outbound(customer_id: int, product_id: int, amount: float) -> dict:
    """一张已审核并已出库的销售单 —— 它才有"未结清"可言（order 未发货不进对账）。"""
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "warehouse_id": _warehouse()["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": amount, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/sales-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    outbound = client.post(f"/api/v1/sales-orders/{order_id}/to-outbound")
    assert outbound.status_code == 200, outbound.text
    return outbound.json()


def _contract(customer: dict, product: dict, amount: float = 5000.0) -> dict:
    response = client.post(
        "/api/v1/contracts",
        json={
            "direction": "out",
            "party_id": customer["id"],
            "party_name": customer["name"],
            "sign_date": TODAY,
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": amount}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _dispatch(text: str) -> dict:
    response = client.post("/api/v1/agent/dispatch", json={"text": text}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 解析（不需要数据库）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "intent_type", "party_query"),
    [
        ("给我周广平的对账单", "statement", "周广平"),
        ("给湖南华邦的对账单", "statement", "湖南华邦"),
        ("查一下西安明珠的合同", "contract", "西安明珠"),
        ("生成上海汉川机械厂的最新销售合同", "contract", "上海汉川机械厂"),
        ("和蒲白750的对账", "statement", "蒲白750"),
        ("西变公司的对账单", "statement", "西变公司"),
    ],
)
def test_parse_strips_noise_and_keeps_party(text, intent_type, party_query):
    from app.services.agent_command import parse_command

    parsed = parse_command(text)
    assert parsed["type"] == intent_type, parsed
    assert parsed["party_query"] == party_query, parsed
    assert parsed["parser"] == "rules"
    assert parsed["confidence"] >= 0.8


def test_parse_unknown_words():
    from app.services.agent_command import parse_command

    parsed = parse_command("你好")
    assert parsed["type"] == "unknown"
    assert parsed["confidence"] < 0.5


def test_dispatch_requires_auth():
    response = client.post("/api/v1/agent/dispatch", json={"text": "给我客户的对账单"})
    assert response.status_code in (401, 403), response.status_code


def test_dispatch_rejects_empty_text():
    response = client.post("/api/v1/agent/dispatch", json={"text": ""}, headers=HEADERS)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 认人 + 取数（真数据）
# ---------------------------------------------------------------------------
def test_dispatch_finds_contract_of_created_party():
    customer = _customer()
    product = _product()
    contract = _contract(customer, product, 5000.0)
    try:
        body = _dispatch(f"{customer['name']}的合同")
        assert body["type"] == "contract"
        assert body["party"]["id"] == customer["id"]
        assert body["party"]["matched_by"] == "exact"
        assert body["summary"]["contract_count"] >= 1
        ids = [row["id"] for row in body["matched_data"] if row["kind"] == "contract"]
        assert contract["id"] in ids
        hit = next(row for row in body["matched_data"] if row["id"] == contract["id"])
        assert hit["no"] == contract["contract_no"]
        assert abs(hit["amount"] - 5000.0) < 0.01
        # 跳转参数：前端要拿它去"购销合同"页预填关键字
        assert body["goto"]["page"] == "contracts"
        assert body["goto"]["keyword"] == customer["name"]
    finally:
        client.delete(f"/api/v1/contracts/{contract['id']}")
        client.delete(f"/api/v1/products/{product['id']}")
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_dispatch_lists_unsettled_documents_with_consistent_amounts():
    customer = _customer()
    product = _product()
    outbound = _outbound(customer["id"], product["id"], 1280.0)
    try:
        body = _dispatch(f"给{customer['name']}的对账单")
        assert body["type"] == "statement"
        assert body["party"]["id"] == customer["id"]
        docs = [row for row in body["matched_data"] if row["kind"] == "document"]
        assert docs, body["matched_data"]
        target = next((row for row in docs if row["no"] == outbound["order_no"]), None)
        assert target is not None, [row["no"] for row in docs]
        # 一分钱都没付过 → 欠款 = 单据金额；且三个数必须自洽
        assert abs(target["remaining"] - target["amount"]) < 0.01
        assert abs(target["amount"] - target["paid_amount"] - target["remaining"]) < 0.01
        assert target["status_label"] == "未结清"
        assert body["summary"]["outstanding_total"] >= target["remaining"] - 0.01
        # 跳转参数：对账单页吃 `c:<id>` + scope=out
        assert body["goto"]["page"] == "statements-editor"
        assert body["goto"]["party"] == f"c:{customer['id']}"
        assert body["goto"]["scope"] == "out"
        # 自动生成闭环（2026-10-25）：显式查对账单 + 名下零对账单 + 有未结清单据
        # → 后端静默落一张真草稿，卡片里带编号/金额/预览所需 id
        generated = body.get("generated")
        assert generated is not None, body["message"]
        assert str(generated["statement_no"]).startswith("DZ"), generated
        assert generated["id"] > 0
        assert generated["line_count"] >= 1
        # 草稿必须真的在库里（matched_data 里出现对账单卡片）
        statements = [row for row in body["matched_data"] if row["kind"] == "statement"]
        assert any(row["id"] == generated["id"] for row in statements), statements
        # 清理草稿，别让它挡住后面删客户
        assert client.delete(f"/api/v1/statements/{generated['id']}", headers=HEADERS).status_code == 204
    finally:
        client.delete(f"/api/v1/sales-orders/{outbound['id']}?force=true")
        client.delete(f"/api/v1/products/{product['id']}")
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_dispatch_matches_contact_name():
    """用户常说"{业务员/联系人}的对账单" —— 按联系人也要能落到档案上。"""
    tag = uuid.uuid4().hex[:4]
    customer = _customer(contact=f"周{tag}")
    try:
        body = _dispatch(f"给我周{tag}的对账单")
        assert body["party"] is not None, body["message"]
        assert body["party"]["id"] == customer["id"]
        assert body["party"]["matched_by"] == "contact"
    finally:
        client.delete(f"/api/v1/customers/{customer['id']}")


# ---------------------------------------------------------------------------
# 实时下拉 + 宽松解析（2026-10-24）
# ---------------------------------------------------------------------------
def test_agent_suggest_returns_matches():
    """GET /agent/suggest：输入半截话（拼音首字母 / 汉字前缀）也要实时认出人。"""
    from app.services.pinyin_initials import pinyin_initials

    pool = "甯胥庾逄逯郄郗郇郈綦毋亓官"
    tag = uuid.uuid4().hex
    contact = "".join(pool[int(tag[i * 2 : i * 2 + 2], 16) % len(pool)] for i in range(3))
    expected = pinyin_initials(contact)
    customer = _customer(contact=contact)
    try:
        response = client.get("/api/v1/agent/suggest", params={"q": expected}, headers=HEADERS)
        assert response.status_code == 200, response.text
        names = [row["name"] for row in response.json()["suggestions"]]
        assert customer["name"] in names, names

        # 汉字前缀（"周" → 周广平/周永红）同一条链路
        response2 = client.get("/api/v1/agent/suggest", params={"q": contact[0]}, headers=HEADERS)
        assert response2.status_code == 200, response2.text
        names2 = [row["name"] for row in response2.json()["suggestions"]]
        assert customer["name"] in names2, names2

        # 空查询不炸，回空列表
        response3 = client.get("/api/v1/agent/suggest", params={"q": ""}, headers=HEADERS)
        assert response3.status_code == 200
        assert response3.json()["suggestions"] == []
    finally:
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_dispatch_without_keyword_falls_back_to_statement():
    """只打名字、不带"对账单/合同"也要查（宽松解析），绝不能回"没听懂"。"""
    tag = uuid.uuid4().hex[:6]
    customer = _customer(name=f"宽松解析客户{tag}")
    try:
        body = _dispatch(customer["name"])
        assert body["type"] == "statement", body
        assert body["party"]["id"] == customer["id"]
        assert body["intent"]["fallback"] is True
        # 新建客户名下没单据 → 必须给"名下暂无"的人话 + empty 标记（前端渲染黄字）
        assert body["empty"] is True
        assert "名下暂无对账单" in body["message"], body["message"]
    finally:
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_agent_suggest_finds_category_nodes():
    """suggest 必须连**分类节点**一起搜（2026-10-24）。

    实测「周广平」这类名字常以客户分类/供应商分类节点存在（档案表里没有），
    只搜 customers/suppliers 会漏 —— zgp 拼音也要能命中分类名。
    """
    tag = uuid.uuid4().hex[:4]
    name = f"周广平测试组{tag}"
    created = client.post("/api/v1/customer-categories", json={"name": name}, headers=HEADERS)
    assert created.status_code == 201, created.text
    cat_id = created.json()["id"]
    try:
        # 字面命中
        resp = client.get("/api/v1/agent/suggest", params={"q": name}, headers=HEADERS)
        names = [row["name"] for row in resp.json()["suggestions"]]
        assert name in names, names
        # 拼音首字母命中（zgp → 周广平…，分类节点同样吃拼音通道）
        resp2 = client.get("/api/v1/agent/suggest", params={"q": "zgp"}, headers=HEADERS)
        names2 = [row["name"] for row in resp2.json()["suggestions"]]
        assert name in names2, names2
        # 类型标记正确（前端据此跳档案页而不是查对账单）
        hit = next(row for row in resp2.json()["suggestions"] if row["name"] == name)
        assert hit["type"] == "customer-category"
        assert hit["matched_by"] == "category"
    finally:
        client.delete(f"/api/v1/customer-categories/{cat_id}", headers=HEADERS)


def test_dispatch_reports_missing_party_in_plain_words():
    body = _dispatch("给不存在的单位XYZ的对账单")
    assert body["party"] is None
    assert body["matched_data"] == []
    assert "没找到" in body["message"]


# ---------------------------------------------------------------------------
# 拼音首字母（2026-10-23）：zgp → 周广平
# ---------------------------------------------------------------------------
def test_score_pinyin_initials_branches():
    """_score 的拼音分支：整串相等 > 包含；字面匹配永远优先；汉字查拼音=0 分。"""
    from app.services.agent_command import _score

    assert _score("周广平", "zgp") == (92, "pinyin-exact")
    assert _score("周广平", "zg") == (65, "pinyin-contains")
    assert _score("上海汉川机械厂", "shhcjx")[1] == "pinyin-contains"
    # 字面优先：同名时字面赢
    assert _score("周广平", "周广平") == (100, "exact")
    # 字面子串也优先于拼音（"zgp" 是 "ZGP金属" 的字面一部分）
    assert _score("ZGP金属", "zgp") == (60 + 18, "contains")
    # 汉字关键词不走拼音通道
    assert _score("周广平", "周广") == (60 + int(30 * 2 / 3), "contains")
    assert _score("周广平", "abc") == (0, "")


def test_dispatch_matches_contact_via_pinyin_initials():
    """「给我 zgp 的对账单」——联系人是"周广平"时按首字母也要能认出来。

    用生僻字拼联系人名，把与库里已有联系人（真有"周广平"）撞车的概率压到忽略不计。
    """
    from app.services.pinyin_initials import pinyin_initials

    pool = "甯胥庾逄逯郄郗郇郈綦毋亓官"
    tag = uuid.uuid4().hex
    contact = "".join(pool[int(tag[i * 2 : i * 2 + 2], 16) % len(pool)] for i in range(3))
    expected = pinyin_initials(contact)
    assert len(expected) == 3, (contact, expected)

    customer = _customer(contact=contact)
    try:
        body = _dispatch(f"给我{expected}的对账单")
        assert body["party"] is not None, body["message"]
        assert body["party"]["id"] == customer["id"], body["candidates"]
        assert body["party"]["matched_by"] == "contact-pinyin"
    finally:
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_dispatch_unknown_intent_asks_again():
    body = _dispatch("你好")
    assert body["type"] == "unknown"
    assert "没听懂" in body["message"]


def test_dispatch_auto_generation_is_idempotent():
    """自动生成只发生一次（2026-10-25）。

    「给我XX的对账单」第一查：静默落一张草稿；第二查：草稿已在库里，
    `generated` 消失、条数不涨。绝不能每次查询都白占一个 DZ 单号。
    顺带守"宽松兜底不生成"：只打名字（fallback 意图）永远不落单。
    """
    customer = _customer()
    product = _product()
    outbound = _outbound(customer["id"], product["id"], 660.0)
    try:
        # 只打名字 → 宽松兜底按对账单查，但绝不触发生成
        fallback_body = _dispatch(customer["name"])
        assert fallback_body["intent"]["fallback"] is True
        assert fallback_body.get("generated") is None, fallback_body["message"]

        # 显式意图第一查：生成
        first = _dispatch(f"给我{customer['name']}的对账单")
        assert first.get("generated") is not None, first["message"]
        draft_id = first["generated"]["id"]

        # 显式意图第二查：不重复生成
        second = _dispatch(f"给我{customer['name']}的对账单")
        assert second.get("generated") is None, second["message"]
        second_statements = [row for row in second["matched_data"] if row["kind"] == "statement"]
        assert len(second_statements) == 1, second_statements
        assert second_statements[0]["id"] == draft_id

        assert client.delete(f"/api/v1/statements/{draft_id}", headers=HEADERS).status_code == 204
    finally:
        client.delete(f"/api/v1/sales-orders/{outbound['id']}?force=true")
        client.delete(f"/api/v1/products/{product['id']}")
        client.delete(f"/api/v1/customers/{customer['id']}")


def test_dispatch_is_read_only():
    """dispatch 本体依旧只读：fallback 名字查询 / 合同查询 / 听不懂，一个单据都不许多。

    （自动生成草稿是显式对账单意图的专属行为，由上一条用例单独守。）
    """
    def counts() -> tuple[int, int]:
        orders = client.get("/api/v1/sales-orders?limit=500").json()
        orders = orders if isinstance(orders, list) else orders.get("items") or []
        statements = client.get("/api/v1/statements?limit=200").json()
        statements = statements if isinstance(statements, list) else statements.get("items") or []
        return len(orders), len(statements)

    before = counts()
    for text in ("湖南华邦", "蒲白750 的合同", "给你好"):
        _dispatch(text)
    assert counts() == before
