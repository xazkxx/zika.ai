"""搜索预览 / 确认生成 的接口级回归（2026-10-22）。

## 守的是什么

界面上把「生成草稿」拆成两步（预览 → 确认生成），最容易退化的就是这个承诺：

> **看一眼不能占一个对账单号。**

前端脚本验的是"按钮和计数"，这里从接口层钉住同一件事 ——
`preview-pool` 调 100 次，`statements` 表也必须一条不多。
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


def _customer() -> dict:
    response = client.post(
        "/api/v1/customers", json={"code": _uniq("CUST"), "name": f"测试客户预览{uuid.uuid4().hex[:6]}"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _product() -> dict:
    response = client.post(
        "/api/v1/products", json={"sku": _uniq("SKU"), "name": "测试商品预览", "unit": "件"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _outbound(customer_id: int, product_id: int, amount: float) -> dict:
    warehouse = _warehouse()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse["id"],
            "doc_type": "order",
            "order_date": TODAY,
            "items": [{"product_id": product_id, "quantity": 1, "unit_price": amount, "unit": "件"}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert client.patch(f"/api/v1/sales-orders/{order_id}/status", json={"status": "approved"}).status_code == 200
    out = client.post(f"/api/v1/sales-orders/{order_id}/to-outbound")
    assert out.status_code == 200, out.text
    return out.json()


def _statement_total() -> int:
    rows = client.get("/api/v1/statements?limit=200").json()
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    return len(rows)


def _pool(customer_id: int, start: str = "2026-01-01", end: str = TODAY) -> dict:
    return client.get(
        "/api/v1/statements/preview-pool",
        params={
            "party_type": "customer",
            "party_id": customer_id,
            "period_start": start,
            "period_end": end,
        },
    ).json()


def test_preview_pool_never_writes_anything():
    """预览是纯读：调两次，对账单条数必须一模一样。"""
    customer = _customer()
    product = _product()
    _outbound(customer["id"], product["id"], 100.0)

    before = _statement_total()
    first = _pool(customer["id"])
    second = _pool(customer["id"])

    assert first["doc_count"] == 1, first
    assert second["doc_count"] == 1, second
    assert len(first["rows"]) == len(second["rows"])
    assert _statement_total() == before, "预览居然写库了"


def test_preview_pool_returns_doc_keys_and_totals():
    customer = _customer()
    product = _product()
    outbound = _outbound(customer["id"], product["id"], 88.0)

    data = _pool(customer["id"])
    assert data["documents"][0]["key"] == f"order:{outbound['id']}"
    assert float(data["totals"]["amount_sum"]) == 88.0
    # 与已存对账单的预览同构：列元数据 + 四流行
    assert len(data["columns"]) >= 35
    assert any(row["row_kind"] == "summary" for row in data["rows"])


def test_generate_selected_only_writes_picked_documents():
    """勾两张里的其中一张 → 对账单只应该有 1 行，且金额只算那一张。"""
    customer = _customer()
    product = _product()
    first = _outbound(customer["id"], product["id"], 60.0)
    _outbound(customer["id"], product["id"], 40.0)

    data = _pool(customer["id"])
    assert data["doc_count"] == 2

    created = client.post(
        "/api/v1/statements/generate-selected",
        json={
            "party_type": "customer",
            "party_id": customer["id"],
            "period_start": "2026-01-01",
            "period_end": TODAY,
            "keys": [f"order:{first['id']}"],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["statement_no"].startswith("DZ")
    items = body["items"]
    assert len(items) == 1, items
    assert items[0]["source_no"] == first["order_no"]
    assert float(body["contract_amount"]) == 60.0


def test_generate_selected_rejects_empty_keys():
    customer = _customer()
    product = _product()
    _outbound(customer["id"], product["id"], 10.0)

    empty = client.post(
        "/api/v1/statements/generate-selected",
        json={
            "party_type": "customer",
            "party_id": customer["id"],
            "period_start": "2026-01-01",
            "period_end": TODAY,
            "keys": [],
        },
    )
    assert empty.status_code == 400, empty.text


def test_batch_keys_split_into_one_statement_per_party():
    """勾了不同往来单位的单据 → **各生成一张**，绝不混户。

    2026-10-22 的「全部往来单位」预览就是按这个约定工作的：
    一次勾 3 个客户的单，应该得到 3 张对账单（每张只含该客户自己的单）。
    早期实现里"串户"是 409 直接拒绝，现在升级成"自动分组"，更符合财务直觉。
    """
    first = _customer()
    second = _customer()
    product = _product()
    mine = _outbound(first["id"], product["id"], 30.0)
    other = _outbound(second["id"], product["id"], 40.0)

    before = _statement_total()
    created = client.post(
        "/api/v1/statements/generate-selected",
        json={
            "party_type": "all",
            "period_start": "2026-01-01",
            "period_end": TODAY,
            "keys": [f"sales:{mine['id']}", f"sales:{other['id']}"],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert len(body["statements"]) == 2, body["statements"]
    assert {row["party_name"] for row in body["statements"]} == {first["name"], second["name"]}
    # 每张只含自己那一张单
    for row in body["statements"]:
        detail = client.get(f"/api/v1/statements/{row['id']}").json()
        assert len(detail["items"]) == 1
    assert _statement_total() == before + 2


def test_outstanding_amount_never_goes_negative():
    """剩余未收 = max(0, 合同 − 已收 − 预收核销)（2026-10-22 用户拍板加下限 0）。

    背景：绝大多数业务是"订单 → 出库 → 开票 → 收款"，**没有合同**，合同额记 0。
    旧公式 0 − 已收 会算出 "−120"，看着像客户多付了钱。
    多收的钱本来就该体现在「预收余额」，不该把"剩余未收"顶成负数。
    期末应收（receivable_balance）不受影响 —— 那才是欠不欠钱的权威口径。
    """
    customer = _customer()
    product = _product()
    outbound = _outbound(customer["id"], product["id"], 100.0)
    # 全额收款（不含合同）→ 生成一张逐单明细的对账单
    paid = client.post(
        "/api/v1/finance/receipt",
        json={"party_id": customer["id"], "order_id": outbound["id"], "amount": 100.0, "occurred_at": TODAY},
    )
    assert paid.status_code == 201, paid.text

    created = client.post(
        "/api/v1/statements/generate-selected",
        json={
            "party_type": "customer",
            "period_start": "2026-01-01",
            "period_end": TODAY,
            "keys": [f"order:{outbound['id']}"],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()

    # 这一行"合同额=单据净额、已收=全额"，剩余未收应当是 0，绝不是负数
    assert float(body["outstanding_amount"]) == 0.0
    for item in body["items"]:
        assert float(item["outstanding_amount"]) >= 0.0, item

    # 期末应收按"期初 + 已开票 − 已收"算：没开票但收了钱 → 负数（这是对的，多收要退/预收）
    assert float(body["receivable_balance"]) < 0.0

    client.delete(f"/api/v1/statements/{body['id']}")
