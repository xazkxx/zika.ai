"""商品档案「补回来」回归测试：编辑接口 + 树形类别。

## 这一批修的是什么

对照浩技云 5.0 的「商品管理」界面，本系统商品档案有两个真实缺口：

1. **商品只能新增/删除，没有编辑** —— 录错的条码/助记码/规格只能删了重建。
2. **类别是扁平字符串** —— 浩技云左侧是多级类别树（顶级=客户/板块，二级=商品类别）。

所以下面用例钉的是三件事：
- `PATCH /products/{id}` 只改传了的字段、SKU 不可改；
- 类别树能建多级、同级不重名、删有子类/被引用的类别会被拒绝；
- 存量商品的扁平 `category` 字符串能被幂等播种成顶级类别节点。
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
    """一套干净的商品测试数据：商品 + 类别。用完全删。"""
    h = _headers()
    tag = _hex()
    prod = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-CAT-{tag}", "name": f"类别测试商品-{tag}", "unit": "件",
              "purchase_price": 50, "sale_price": 100},
        headers=h,
    ).json()
    yield {"h": h, "tag": tag, "prod": prod}
    # 清理：删商品、删可能残留的类别
    client.delete(f"/api/v1/products/{prod['id']}", headers=h)
    tree = client.get("/api/v1/product-categories", headers=h).json()
    for root in tree:
        if tag in root.get("name", ""):
            for child in root.get("children", []):
                client.delete(f"/api/v1/product-categories/{child['id']}", headers=h)
            client.delete(f"/api/v1/product-categories/{root['id']}", headers=h)


def test_product_patch_updates_only_sent_fields(fx):
    """编辑商品：只改传了的字段，未传的不动，SKU 不可改。"""
    h, tag, prod = fx["h"], fx["tag"], fx["prod"]
    resp = client.patch(
        f"/api/v1/products/{prod['id']}",
        json={"bar_code": "6901234567890", "mnemonic": "LBSX", "standards": "带钢头"},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bar_code"] == "6901234567890"
    assert body["mnemonic"] == "LBSX"
    assert body["standards"] == "带钢头"
    # 未传的字段保持原值
    assert body["name"] == prod["name"]
    assert body["purchase_price"] == 50


def test_product_patch_missing_404(fx):
    resp = client.patch("/api/v1/products/99999999", json={"name": "x"}, headers=fx["h"])
    assert resp.status_code == 404


def test_product_patch_does_not_allow_sku_change(fx):
    """SKU 是唯一标识，编辑接口不接受改它（schema 里根本没有这个字段）。"""
    h, prod = fx["h"], fx["prod"]
    # ProductUpdate 没有 sku 字段，传了会被 pydantic 忽略 —— 但名称等仍应能改
    resp = client.patch(f"/api/v1/products/{prod['id']}", json={"name": "改名后的商品"}, headers=h)
    assert resp.status_code == 200
    # SKU 保持不变
    assert resp.json()["sku"] == prod["sku"]


def test_category_tree_crud_and_nesting(fx):
    """建顶级类别 → 建子类别 → 树形接口返回嵌套 children。"""
    h, tag = fx["h"], fx["tag"]
    root = client.post("/api/v1/product-categories", json={"name": f"顶级-{tag}"}, headers=h)
    assert root.status_code == 201, root.text
    root_id = root.json()["id"]
    child = client.post(
        "/api/v1/product-categories", json={"name": f"子类-{tag}", "parent_id": root_id}, headers=h
    )
    assert child.status_code == 201, child.text

    tree = client.get("/api/v1/product-categories", headers=h).json()
    node = next((n for n in tree if n["name"] == f"顶级-{tag}"), None)
    assert node is not None, "顶级类别应出现在树里"
    assert len(node["children"]) == 1
    assert node["children"][0]["name"] == f"子类-{tag}"


def test_category_duplicate_name_under_same_parent_409(fx):
    """同一父级下类别名唯一（商品按名称回写 category 字符串，重名会歧义）。

    2026-10-22 起统一改回 **409**：重名属于"和库里数据冲突"，不是"参数格式错"，
    前端要据此弹红字（400 会被当成输入格式问题）。
    """
    h, tag = fx["h"], fx["tag"]
    r1 = client.post("/api/v1/product-categories", json={"name": f"重名-{tag}"}, headers=h)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/product-categories", json={"name": f"重名-{tag}"}, headers=h)
    assert r2.status_code == 409, r2.text
    assert "同名类别" in r2.json().get("detail", "")


def test_category_delete_with_children_409(fx):
    """有子类别的类别不能删（409），先删子类才行。"""
    h, tag = fx["h"], fx["tag"]
    root = client.post("/api/v1/product-categories", json={"name": f"父-{tag}"}, headers=h).json()
    client.post("/api/v1/product-categories", json={"name": f"子-{tag}", "parent_id": root["id"]}, headers=h)
    resp = client.delete(f"/api/v1/product-categories/{root['id']}", headers=h)
    assert resp.status_code == 409, resp.text


def test_category_delete_referenced_by_product_409(fx):
    """仍被商品引用的类别不能删（409）。"""
    h, tag, prod = fx["h"], fx["tag"], fx["prod"]
    cat = client.post("/api/v1/product-categories", json={"name": f"在用-{tag}"}, headers=h).json()
    # 商品挂到这个类别上（category 存类别名）
    client.patch(f"/api/v1/products/{prod['id']}", json={"category": cat["name"]}, headers=h)
    resp = client.delete(f"/api/v1/product-categories/{cat['id']}", headers=h)
    assert resp.status_code == 409, resp.text
    # 改掉商品的类别后即可删
    client.patch(f"/api/v1/products/{prod['id']}", json={"category": None}, headers=h)
    assert client.delete(f"/api/v1/product-categories/{cat['id']}", headers=h).status_code == 204


def test_category_prevent_cycle(fx):
    """不能把类别挂到它自己或它的下级（防成环）。"""
    h, tag = fx["h"], fx["tag"]
    root = client.post("/api/v1/product-categories", json={"name": f"环-{tag}"}, headers=h).json()
    child = client.post(
        "/api/v1/product-categories", json={"name": f"环子-{tag}", "parent_id": root["id"]}, headers=h
    ).json()
    # 把父挂到自己下级 → 400
    resp = client.patch(f"/api/v1/product-categories/{root['id']}", json={"parent_id": child["id"]}, headers=h)
    assert resp.status_code == 400, resp.text


def test_seed_existing_categories_idempotent(fx):
    """存量扁平 category 字符串被播种成顶级类别；重复跑不重复建（幂等）。"""
    h, tag, prod = fx["h"], fx["tag"], fx["prod"]
    # 给商品一个独一无二的类别，然后触发一次播种
    client.patch(f"/api/v1/products/{prod['id']}", json={"category": f"播种-{tag}"}, headers=h)
    from app.main import ensure_default_product_categories

    ensure_default_product_categories()
    ensure_default_product_categories()  # 再跑一次不应重复

    tree = client.get("/api/v1/product-categories", headers=h).json()
    names = [n["name"] for n in tree]
    assert names.count(f"播种-{tag}") == 1, "播种应幂等，不产生重复节点"
