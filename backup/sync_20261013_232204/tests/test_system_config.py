"""系统参数 与 数字字典（第 5 批第 2 轮）回归测试。

这一轮的核心风险不是"算错数"，而是**参数改了没反应**：
一个假参数会让用户以为配置生效了，比没有这个功能更糟。
所以本文件最重要的两条是：

1. `test_every_builtin_param_is_read` —— 逐个内置参数去源码里找读取点，
   找不到就失败。新增参数必须同时有落地代码，否则这条测试挡住。
2. `test_footer_text_reaches_the_pdf` —— 真把参数改掉，真打一张 PDF，
   从 PDF 里把文字抠出来验证页脚出现了。

其余覆盖：分组返回、批量保存、类型校验、内置项不可删、
字典 CRUD 与状态对 `lookups` 的影响、以及"业务接口对普通用户开放、
管理接口只对管理员开放"的鉴权边界。

测试数据命名遵守 scripts/clean_test_data.py 的签名：DICT-TEST-* / SKU-CFG-* / CUST-CFG-*。
"""

import re
import uuid
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.system_config import DEFAULT_DICTIONARIES, DEFAULT_PARAMS

client = TestClient(app)
ADMIN = {"username": "admin", "password": "Admin123"}
ROOT = Path(__file__).resolve().parent.parent


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _admin_headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _param_map(headers: dict[str, str]) -> dict[str, dict]:
    data = client.get("/api/v1/system/params", headers=headers).json()
    return {item["param_key"]: item for group in data["groups"] for item in group["items"]}


def _set_params(headers: dict[str, str], mapping: dict[str, str]) -> None:
    resp = client.put(
        "/api/v1/system/params",
        json={"items": [{"param_key": key, "param_value": value} for key, value in mapping.items()]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def param_guard():
    """改动系统参数后自动还原，避免污染同一库里的其它测试。"""
    headers = _admin_headers()
    original = {key: row["param_value"] for key, row in _param_map(headers).items()}
    yield headers
    _set_params(headers, original)


# ============================================================
# 参数：目录与"不许有假参数"
# ============================================================
def test_every_builtin_param_is_read():
    """每个内置参数都必须能在代码里找到读取点 —— 不许有"改了没反应"的假参数。

    做法：在测试里硬编码"谁读它"，然后去源码里找那个读取痕迹。
    新增参数时必须同步在这里登记，否则这条测试会失败。
    """
    # param_key -> [(待搜索的源码文件, 必须出现的片段), ...]
    read_points: dict[str, list[tuple[str, str]]] = {
        "print.footer_text": [
            # 出口在 erp.py 的 _pdf_response，真正的读取在打印模板解析里（三层优先级）
            ("app/api/v1/routes/erp.py", "resolve_print_spec(db, doc_type, spec)"),
            ("app/models/print_template.py", 'get_param(db, "print.footer_text", "")'),
            ("app/services/pdf_render.py", 'spec.get("footer_text")'),
        ],
        "system.default_page": [
            ("app/api/v1/routes/system.py", "system.default_page"),
            ("frontend/src/App.jsx", "ui?.default_page"),
        ],
        "stock.warn_enabled": [
            ("app/api/v1/routes/system.py", "stock.warn_enabled"),
            ("frontend/src/App.jsx", "stock_warn_enabled"),
        ],
    }

    assert {str(spec["param_key"]) for spec in DEFAULT_PARAMS} == set(read_points), (
        "内置参数与读取点清单不一致：新增/删除了参数却没更新这条测试"
    )

    for key, points in read_points.items():
        for rel_path, needle in points:
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            assert needle in source, f"参数 {key} 声称的读取点没找到：{rel_path} 里的 {needle!r}"


def test_params_grouped_payload(param_guard):
    data = client.get("/api/v1/system/params", headers=param_guard).json()
    assert data["total"] >= len(DEFAULT_PARAMS)
    labels = [group["label"] for group in data["groups"]]
    assert "打印与单据" in labels and "系统与界面" in labels

    for group in data["groups"]:
        for item in group["items"]:
            assert item["param_key"] and item["label"]
            assert item["value_type"] in {"string", "bool", "int", "decimal"}
            assert "default_value" in item
    assert {entry["key"] for entry in data["value_types"]} == {"string", "bool", "int", "decimal"}


def test_param_validation_rejects_bad_values(param_guard):
    bad_bool = client.put(
        "/api/v1/system/params",
        json={"items": [{"param_key": "stock.warn_enabled", "param_value": "maybe"}]},
        headers=param_guard,
    )
    assert bad_bool.status_code == 400
    assert "true" in bad_bool.json()["detail"]

    unknown = client.put(
        "/api/v1/system/params",
        json={"items": [{"param_key": "no.such.key", "param_value": "1"}]},
        headers=param_guard,
    )
    assert unknown.status_code == 400
    assert "未知参数" in unknown.json()["detail"]


def test_builtin_param_cannot_be_deleted_but_custom_can(param_guard):
    rows = _param_map(param_guard)
    builtin_id = rows["print.footer_text"]["id"]
    resp = client.delete(f"/api/v1/system/params/{builtin_id}", headers=param_guard)
    assert resp.status_code == 409
    assert "内置参数" in resp.json()["detail"]

    created = client.post(
        "/api/v1/system/params",
        json={
            "param_key": f"test.custom.{_hex()}",
            "label": "测试自定义参数",
            "param_value": "hello",
            "param_group": "system",
            "value_type": "string",
        },
        headers=param_guard,
    )
    assert created.status_code == 201, created.text
    custom_id = created.json()["id"]
    assert created.json()["default_value"] == "", "自定义参数没有出厂默认值"

    assert client.delete(f"/api/v1/system/params/{custom_id}", headers=param_guard).status_code == 204
    assert client.delete(f"/api/v1/system/params/{custom_id}", headers=param_guard).status_code == 404


def test_footer_text_reaches_the_pdf(param_guard):
    """把参数改掉 → 打一张真单据 → 从 PDF 里把文字抠出来比对。"""
    # 造客户 + 商品 + 销售开单（doc_type=outbound 才会写库存，这里用订单即可）
    customer = client.post(
        "/api/v1/customers", json={"code": f"CUST-CFG-{_hex()}", "name": "页脚验证客户"}
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-CFG-{_hex()}", "name": "页脚验证商品", "sale_price": 10.0},
    ).json()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 10.0}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    marker = f"页脚验证-{_hex()}"

    # 清空时：PDF 里不应出现任何自定义页脚
    _set_params(param_guard, {"print.footer_text": ""})
    plain = client.get(f"/api/v1/print/sales-order/{order_id}")
    assert plain.status_code == 200, plain.text
    plain_text = fitz.open(stream=plain.content, filetype="pdf")[0].get_text()
    assert marker not in plain_text
    assert "第 1 页" in plain_text

    # 设置后：PDF 页脚出现该文字
    _set_params(param_guard, {"print.footer_text": marker})
    marked = client.get(f"/api/v1/print/sales-order/{order_id}")
    assert marked.status_code == 200, marked.text
    marked_text = fitz.open(stream=marked.content, filetype="pdf")[0].get_text()
    assert marker in marked_text, f"参数没进 PDF 页脚：{marked_text!r}"

    # 收尾：删掉造出来的单据与档案
    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code in (200, 204)
    assert client.delete(f"/api/v1/products/{product['id']}").status_code in (200, 204)
    assert client.delete(f"/api/v1/customers/{customer['id']}").status_code in (200, 204)


def test_default_page_and_warn_flag_are_delivered_to_frontend(param_guard):
    _set_params(param_guard, {"system.default_page": "reports", "stock.warn_enabled": "false"})
    data = client.get("/api/v1/system/me/permissions", headers=param_guard).json()
    assert data["ui"]["default_page"] == "reports"
    assert data["ui"]["stock_warn_enabled"] is False

    _set_params(param_guard, {"system.default_page": "overview", "stock.warn_enabled": "true"})
    data = client.get("/api/v1/system/me/permissions", headers=param_guard).json()
    assert data["ui"]["default_page"] == "overview"
    assert data["ui"]["stock_warn_enabled"] is True


def test_default_page_falls_back_when_menu_not_visible():
    """落地页必须落在该用户看得见的菜单里，否则登录后会弹到一个空页面。"""
    role = client.post(
        "/api/v1/system/roles",
        json={
            "code": f"TEST-ROLE-{_hex()}",
            "name": "测试角色-落地页",
            "permissions": {"all": False, "menus": ["products"]},
        },
        headers=_admin_headers(),
    ).json()
    username = f"TEST-USR-{_hex()}"
    user = client.post(
        "/api/v1/system/users",
        json={"username": username, "password": "Pass1234", "role_id": role["id"]},
        headers=_admin_headers(),
    ).json()

    try:
        _set_params(_admin_headers(), {"system.default_page": "reports"})  # 该角色看不到报表
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        data = client.get("/api/v1/system/me/permissions", headers=headers).json()
        assert data["ui"]["default_page"] == "products", "不可见的落地页必须退回该用户可见的菜单"
    finally:
        _set_params(_admin_headers(), {"system.default_page": "overview"})
        admin = _admin_headers()
        client.delete(f"/api/v1/system/users/{user['id']}", headers=admin)
        client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)


# ============================================================
# 数字字典
# ============================================================
def test_builtin_dictionaries_seeded():
    headers = _admin_headers()
    rows = client.get("/api/v1/system/dictionaries", headers=headers).json()
    by_type = {row["dict_type"]: row for row in rows}

    for spec in DEFAULT_DICTIONARIES:
        dict_type = str(spec["dict_type"])
        assert dict_type in by_type, f"内置字典 {dict_type} 未被播种"
        assert by_type[dict_type]["is_system"] is True
        assert by_type[dict_type]["item_count"] == len(spec["items"]), (
            f"{dict_type} 的字典项数量与内置清单不一致（可能是重复播种或有手工改动）"
        )


def test_lookups_returns_candidates_and_respects_state():
    """字典项停用、字典停用，都要立刻从业务候选里消失。"""
    headers = _admin_headers()
    dict_type = f"testdict{_hex()}"[:20]
    created = client.post(
        "/api/v1/system/dictionaries",
        json={"dict_type": dict_type, "dict_name": "测试字典"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    first = client.post(
        f"/api/v1/system/dictionaries/{dict_type}/items",
        json={"item_value": "甲", "item_label": "甲项"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/v1/system/dictionaries/{dict_type}/items",
        json={"item_value": "乙"},
        headers=headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["item_label"] == "乙", "不传显示名时应与项值相同"

    # 重复项值要挡住
    duplicated = client.post(
        f"/api/v1/system/dictionaries/{dict_type}/items",
        json={"item_value": "甲"},
        headers=headers,
    )
    assert duplicated.status_code == 400
    assert "已存在" in duplicated.json()["detail"]

    data = client.get(f"/api/v1/system/lookups?types={dict_type}", headers=headers).json()
    assert [item["value"] for item in data[dict_type]] == ["甲", "乙"]

    # 停用一项 → 候选里少一个
    assert client.patch(
        f"/api/v1/system/dictionary-items/{second.json()['id']}", json={"is_enabled": False}, headers=headers
    ).status_code == 200
    data = client.get(f"/api/v1/system/lookups?types={dict_type}", headers=headers).json()
    assert [item["value"] for item in data[dict_type]] == ["甲"]

    # 停用整个字典 → 候选为空（而不是报错）
    dict_id = created.json()["id"]
    assert client.patch(f"/api/v1/system/dictionaries/{dict_id}", json={"is_active": False}, headers=headers).status_code == 200
    data = client.get(f"/api/v1/system/lookups?types={dict_type}", headers=headers).json()
    assert data[dict_type] == []

    # 删字典：字典项一并清掉
    assert client.delete(f"/api/v1/system/dictionaries/{dict_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/system/lookups?types={dict_type}", headers=headers).json()[dict_type] == []


def test_system_dictionary_cannot_be_deleted():
    headers = _admin_headers()
    rows = client.get("/api/v1/system/dictionaries", headers=headers).json()
    target = next(row for row in rows if row["is_system"])
    resp = client.delete(f"/api/v1/system/dictionaries/{target['id']}", headers=headers)
    assert resp.status_code == 409
    assert "内置字典" in resp.json()["detail"]


def test_lookups_open_to_any_logged_in_user():
    """业务表单要拿候选，不该要求管理员权限；但管理接口仍然只对管理员开放。"""
    role = client.post(
        "/api/v1/system/roles",
        json={"code": f"TEST-ROLE-{_hex()}", "name": "测试角色-候选", "permissions": {"all": False, "menus": ["sales"]}},
        headers=_admin_headers(),
    ).json()
    username = f"TEST-USR-{_hex()}"
    user = client.post(
        "/api/v1/system/users",
        json={"username": username, "password": "Pass1234", "role_id": role["id"]},
        headers=_admin_headers(),
    ).json()

    try:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        assert client.get("/api/v1/system/lookups?types=payment_method", headers=headers).status_code == 200
        assert client.get("/api/v1/system/me/permissions", headers=headers).status_code == 200

        assert client.get("/api/v1/system/params", headers=headers).status_code == 403
        assert client.get("/api/v1/system/dictionaries", headers=headers).status_code == 403
        assert client.put(
            "/api/v1/system/params", json={"items": []}, headers=headers
        ).status_code == 403
    finally:
        admin = _admin_headers()
        client.delete(f"/api/v1/system/users/{user['id']}", headers=admin)
        client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)


def test_lookups_without_types_returns_all_active():
    headers = _admin_headers()
    data = client.get("/api/v1/system/lookups", headers=headers).json()
    for spec in DEFAULT_DICTIONARIES:
        assert str(spec["dict_type"]) in data


def test_dictionary_list_matches_frontend_read_paths():
    """内置字典都必须在 App.jsx 里有挂载点（datalist），否则等于白配。"""
    source = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    for spec in DEFAULT_DICTIONARIES:
        dict_type = str(spec["dict_type"])
        assert re.search(rf"lookupValues\('{re.escape(dict_type)}'\)", source), (
            f"字典 {dict_type} 没有在前端挂到任何输入框（datalist）上"
        )
