"""项目模块回归测试（补齐"能新建、然后就断了"的那一段）。

## 这一批修的是什么

在此之前项目模块只有 `GET /projects`（列表）与 `POST /projects`（新建）：

- **改不了** —— 建完之后进度永远停在 0、状态永远停在"计划中"；
- **删不了**；
- **看不到成本** —— `financial_transactions.project_id` 这个字段一直存在，
  但**16 处写财务的地方没有任何一处传它**，项目维度形同虚设。

所以下面这些用例钉的是三件事：项目能维护、成本真能归集、**转单时不丢项目**。
最后一条是最容易漏的：销售订单挂了项目，转出来的出库单如果不带 project_id，
项目收入就永远归集不到 —— 而且**不报错**，只是数字是 0。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ADMIN = {"username": "admin", "password": "Admin123"}


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _hex() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def fx():
    """一套干净的项目测试数据：仓库 / 商品 / 客户 / 项目。用完全删。"""
    h = _headers()
    tag = _hex()
    wh = client.post("/api/v1/warehouses", json={"code": f"WH-{tag}", "name": f"项目测试仓-{tag}"}, headers=h).json()
    prod = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-PRJ-{tag}", "name": "项目测试商品", "unit": "件",
              "purchase_price": 50, "sale_price": 100, "tax_rate": 13},
        headers=h,
    ).json()
    cust = client.post("/api/v1/customers", json={"code": f"CUST-PRJ-{tag}", "name": f"项目测试客户-{tag}"}, headers=h).json()
    prj = client.post(
        "/api/v1/projects",
        json={"code": f"PRJ-{tag}", "name": f"项目测试-{tag}", "manager": "测试员",
              "status": "in_progress", "progress": 10, "budget": 10000},
        headers=h,
    ).json()
    yield {"h": h, "tag": tag, "wh": wh, "prod": prod, "cust": cust, "prj": prj}

    # 清理：先删单据与流水（否则项目删不掉），再删项目与档案
    from app.db.session import SessionLocal
    from app.models.finance import FinancialTransaction
    from app.models.project import Project
    from app.models.sales_order import SalesOrder, SalesOrderItem

    db = SessionLocal()
    try:
        order_ids = [r[0] for r in db.query(SalesOrder.id).filter(SalesOrder.project_id == prj["id"]).all()]
        if order_ids:
            db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id.in_(order_ids)).delete(synchronize_session=False)
            db.query(SalesOrder).filter(SalesOrder.id.in_(order_ids)).delete(synchronize_session=False)
        db.query(FinancialTransaction).filter(FinancialTransaction.project_id == prj["id"]).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == prj["id"]).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    for path in (f"/api/v1/products/{prod['id']}", f"/api/v1/customers/{cust['id']}", f"/api/v1/warehouses/{wh['id']}"):
        client.delete(path, headers=h)


# ============================================================
# 1. 项目能改（在此之前只有新建与列表）
# ============================================================
def test_project_can_be_updated(fx):
    h, prj = fx["h"], fx["prj"]
    resp = client.patch(f"/api/v1/projects/{prj['id']}", json={"progress": 65, "status": "delayed"}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["progress"] == 65
    assert body["status"] == "delayed"

    # 只传一部分字段时，其它字段不能被清掉
    again = client.patch(f"/api/v1/projects/{prj['id']}", json={"manager": "换个人"}, headers=h)
    assert again.status_code == 200
    assert again.json()["manager"] == "换个人"
    assert again.json()["progress"] == 65, "改负责人把手改进度冲掉了"
    assert again.json()["budget"] == 10000, "改负责人把预算冲掉了"


def test_project_status_and_progress_are_validated(fx):
    h, prj = fx["h"], fx["prj"]
    bad_status = client.patch(f"/api/v1/projects/{prj['id']}", json={"status": "随便写的"}, headers=h)
    assert bad_status.status_code == 400, bad_status.text

    bad_progress = client.patch(f"/api/v1/projects/{prj['id']}", json={"progress": 130}, headers=h)
    assert bad_progress.status_code == 400
    assert "0~100" in bad_progress.json()["detail"]


def test_project_status_matches_the_frontend_options():
    """状态字典必须覆盖前端下拉里的每一个取值。

    少一个的后果很具体：用户在下拉里选了"延期"，一保存就 400，
    而错误信息是"状态只能是 …"，用户根本看不出到底哪个能选。
    """
    from pathlib import Path

    from app.models.project import PROJECT_STATUS

    source = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    for key in PROJECT_STATUS:
        assert f"{key}:" in source, f"前端缺少状态 {key} 的显示名（会显示成英文 key）"
    for key in ("planned", "in_progress", "delayed", "completed"):
        assert key in PROJECT_STATUS, f"前端下拉用过 {key}，后端字典里没有"


def test_update_missing_project_returns_404():
    assert client.patch("/api/v1/projects/99999999", json={"progress": 1}, headers=_headers()).status_code == 404


# ============================================================
# 2. ⭐ 项目成本归集：单据产生的钱要能自动归到项目上
# ============================================================
def test_project_cost_aggregates_from_documents(fx):
    """★ 销售单挂上项目 → 出库产生的应收必须归集为项目收入。

    这条链上有两个容易断的地方，本用例把它们一起钉住：
      1. 出库单写应收时有没有带 project_id；
      2. **订单转出库单时有没有把项目带过去** —— 这条最容易漏，
         漏了不报错，只是项目收入永远是 0。
    """
    h, prj, cust, wh, prod = fx["h"], fx["prj"], fx["cust"], fx["wh"], fx["prod"]

    order = client.post(
        "/api/v1/sales-orders",
        json={"customer_id": cust["id"], "warehouse_id": wh["id"], "project_id": prj["id"],
              "doc_type": "order", "order_date": "2026-10-11",
              "items": [{"product_id": prod["id"], "quantity": 10, "unit_price": 100}]},
        headers=h,
    )
    assert order.status_code == 201, order.text
    assert order.json()["project_id"] == prj["id"], "销售订单没把项目存下来"

    outbound = client.post(f"/api/v1/sales-orders/{order.json()['id']}/to-outbound", headers=h)
    assert outbound.status_code == 200, outbound.text
    assert outbound.json()["project_id"] == prj["id"], (
        "★ 转单把项目丢了 —— 项目收入会永远归集不到，而且不报错"
    )

    # 再挂一笔项目费用
    exp = client.post(
        "/api/v1/finance",
        json={"transaction_type": "expense", "amount": 123.45, "category": "差旅费",
              "occurred_at": "2026-10-12", "note": "项目差旅", "project_id": prj["id"]},
        headers=h,
    )
    assert exp.status_code == 201, exp.text

    resp = client.get(f"/api/v1/projects/{prj['id']}/cost", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    summary = body["summary"]
    assert summary["income"] == 1000.0, f"项目收入应为 1000，实际 {summary['income']}"
    assert summary["expense"] == 123.45, summary
    assert summary["gross_profit"] == round(1000.0 - 123.45, 2), summary
    assert summary["flow_count"] >= 2

    sources = {row["related_type"] for row in body["by_source"]}
    assert "sales_out" in sources, f"归集口径里没有销售出库：{sources}"
    assert "expense" in sources
    client.delete(f"/api/v1/finance/{exp.json()['id']}", headers=h) if False else None


def test_project_cost_without_income_has_no_margin_rate(fx):
    """没有收入时毛利率要返回 None，不能返回 0 —— 0 会让人以为"不赚钱"，
    而实际是"还没开始卖"。"""
    h, prj = fx["h"], fx["prj"]
    body = client.get(f"/api/v1/projects/{prj['id']}/cost", headers=h).json()
    assert body["summary"]["income"] == 0
    # 没有收入时毛利率返回 None 而不是 0 —— 0 会让人以为"不赚钱"，
    # 实际是"还没开始卖"，两者对老板的决策含义完全不同
    assert body["summary"]["gross_margin_rate"] is None
    # 有预算、一分没花 → 0% 是**有意义**的（说明预算还没动），不该是 None
    assert body["summary"]["budget_usage_rate"] == 0.0


def test_project_cost_missing_project_returns_404():
    assert client.get("/api/v1/projects/99999999/cost", headers=_headers()).status_code == 404


# ============================================================
# 3. 删除保护：挂了单据/流水的项目不能删
# ============================================================
def test_project_with_flows_cannot_be_deleted(fx):
    """删掉项目，挂在上面的成本就变成"悬在空气里的数字"，报表再也归集不回来。

    正确做法是把状态改成"已关闭"，所以这里要挡住删除并说清原因。
    """
    h, prj = fx["h"], fx["prj"]
    exp = client.post(
        "/api/v1/finance",
        json={"transaction_type": "expense", "amount": 50, "occurred_at": "2026-10-12",
              "note": "挂项目的费用", "project_id": prj["id"]},
        headers=h,
    )
    assert exp.status_code == 201, exp.text

    resp = client.delete(f"/api/v1/projects/{prj['id']}", headers=h)
    assert resp.status_code == 409, resp.text
    assert "不能删除" in resp.json()["detail"]
    assert "已关闭" in resp.json()["detail"], "要告诉用户正确的替代做法"


def test_clean_project_can_be_deleted():
    h = _headers()
    prj = client.post(
        "/api/v1/projects",
        json={"code": f"PRJ-DEL-{_hex()}", "name": "待删项目"},
        headers=h,
    ).json()
    assert client.delete(f"/api/v1/projects/{prj['id']}", headers=h).status_code == 204
    assert client.delete(f"/api/v1/projects/{prj['id']}", headers=h).status_code == 404
