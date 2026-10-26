# -*- coding: utf-8 -*-
"""拖拽归档：批量改客户/供应商分类的接口契约（2026-10-21，拖拽试点）。

用户诉求：右侧表格里的行（或多选）直接拖到左侧分类节点上，松手就归档。
前端只负责"拖"，真正落库的是 `PATCH /customers/batch-category`。
这个接口的边界必须钉死，否则一次手滑能把几百条档案的分类清空：

  · 空 ids        → 400（"什么都没选也算成功"是事故，不是便利）
  · 漏传 category_id → 400（与"显式传 null = 移到未分类"必须能区分开）
  · 悬空 id       → 400（库里没有外键，不查就会落一个哪儿都查不到的 category_id）
  · 显式 null     → 200，真的移到未分类
  · 返回 moved    → 真实 UPDATE 行数，不是"我准备更新几行"
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def admin():
    return _headers()


@pytest.fixture()
def fixture_data(admin):
    """一个客户分类 + 两个客户（都在未分类下），测完删干净。"""
    tag = uuid.uuid4().hex[:8]
    category = client.post(
        "/api/v1/customer-categories",
        json={"name": f"拖拽测试类-{tag}", "parent_id": None},
        headers=admin,
    )
    assert category.status_code in (200, 201), category.text
    category_id = category.json()["id"]

    ids = []
    for index in range(2):
        resp = client.post(
            "/api/v1/customers",
            json={"code": f"CUST-DND-{tag}{index}", "name": f"拖拽测试客户{index}-{tag}"},
            headers=admin,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])

    yield {"category_id": category_id, "ids": ids, "tag": tag}

    for customer_id in ids:
        client.delete(f"/api/v1/customers/{customer_id}", headers=admin)
    client.delete(f"/api/v1/customer-categories/{category_id}", headers=admin)


def test_批量归档把整批客户的分类改掉(admin, fixture_data):
    resp = client.patch(
        "/api/v1/customers/batch-category",
        json={"ids": fixture_data["ids"], "category_id": fixture_data["category_id"]},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved"] == 2, body
    assert body["category_id"] == fixture_data["category_id"]
    assert body["category_name"].startswith("拖拽测试类"), body

    # 落库真的改了（不是只回了个漂亮数字）
    rows = {
        row["id"]: row for row in client.get("/api/v1/customers", headers=admin).json()
    }
    for customer_id in fixture_data["ids"]:
        assert rows[customer_id]["category_id"] == fixture_data["category_id"]


def test_显式传_null_等于移到未分类(admin, fixture_data):
    client.patch(
        "/api/v1/customers/batch-category",
        json={"ids": fixture_data["ids"], "category_id": fixture_data["category_id"]},
        headers=admin,
    )
    resp = client.patch(
        "/api/v1/customers/batch-category",
        json={"ids": fixture_data["ids"], "category_id": None},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"] == 2
    assert resp.json()["category_id"] is None

    rows = {row["id"]: row for row in client.get("/api/v1/customers", headers=admin).json()}
    for customer_id in fixture_data["ids"]:
        assert rows[customer_id]["category_id"] is None


def test_漏传_category_id_必须拒绝而不是清空(admin, fixture_data):
    """这条是防"手滑清库"的总闸：漏参数≠移到未分类。"""
    resp = client.patch(
        "/api/v1/customers/batch-category",
        json={"ids": fixture_data["ids"]},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "category_id" in str(resp.json()["detail"])


def test_空_ids_返回_400(admin):
    resp = client.patch(
        "/api/v1/customers/batch-category", json={"ids": [], "category_id": None}, headers=admin
    )
    assert resp.status_code == 400, resp.text


def test_悬空分类_id_返回_400(admin, fixture_data):
    resp = client.patch(
        "/api/v1/customers/batch-category",
        json={"ids": fixture_data["ids"], "category_id": 99999999},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "分类不存在" in str(resp.json()["detail"])


def test_供应商同名接口也在(admin):
    """供应商留着同一套接口（拖拽推广时不用再动后端）。"""
    resp = client.patch(
        "/api/v1/suppliers/batch-category", json={"ids": [], "category_id": None}, headers=admin
    )
    # 空 ids 一样 400 —— 证明路由存在且走的是同一套校验（没被 /{supplier_id} 抢走）
    assert resp.status_code == 400, resp.text
    assert "供应商" in str(resp.json()["detail"])
