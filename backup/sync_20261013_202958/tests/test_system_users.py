"""系统管理（第 5 批 · 组织机构 / 角色 / 用户）回归测试。

这一批与业务单据完全解耦，所以风险点也不同：

1. **树的完整性**：部门是自引用树，改父级可能成环（A 的爹设成 A 的孙子）——
   必须挡住，否则前端递归渲染直接栈溢出。
2. **删除的边界**：有子部门 / 有人的部门、内置角色、有人的角色、最后一个管理员、
   当前登录的自己 —— 这些都不许删。每一条都对应一个真实的误操作。
3. **权限真正生效**：`/system/me/permissions` 是前端菜单过滤的唯一数据源，
   角色配了什么就必须返回什么；角色被停用时要**收紧**而不是放开。
4. **停用要停到底**：账号停用后既不能重新登录，已签发的旧 token 也不能继续用
   （这是本轮顺手修掉的既有缺陷，用测试钉住）。
5. **权限目录与前端菜单不许漂移**：后端 `PERMISSION_CATALOG` 与前端 `menuGroups`
   是同一份菜单的两处描述，最后一条测试用正则从 App.jsx 抽 key 做一致性断言。

测试数据命名遵守 scripts/clean_test_data.py 的签名：TEST-USR-* / TEST-ROLE-* / TEST-DEPT-*。
"""

import re
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.permissions import PERMISSION_CATALOG, all_menu_keys
from app.main import app

client = TestClient(app)

ADMIN = {"username": "admin", "password": "Admin123"}


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _admin_headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _new_department(name: str, parent_id: int | None = None) -> dict:
    resp = client.post(
        "/api/v1/system/departments",
        json={"code": f"TEST-DEPT-{_hex()}", "name": name, "parent_id": parent_id},
        headers=_admin_headers(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _new_role(name: str, *, menus: list[str] | None = None, all_flag: bool = False) -> dict:
    resp = client.post(
        "/api/v1/system/roles",
        json={
            "code": f"TEST-ROLE-{_hex()}",
            "name": name,
            "permissions": {"all": all_flag, "menus": menus or ["overview"]},
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _new_user(username: str, *, role_id: int | None = None, department_id: int | None = None,
              password: str = "Pass1234") -> dict:
    resp = client.post(
        "/api/v1/system/users",
        json={
            "username": username,
            "password": password,
            "role_id": role_id,
            "department_id": department_id,
            "full_name": f"测试用户 {username}",
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ============================================================
# 权限目录
# ============================================================
def test_permission_catalog_shape():
    """目录结构：分组有序、key 全局唯一、每组都有标签。"""
    assert PERMISSION_CATALOG, "权限目录不能为空"

    keys = all_menu_keys()
    assert len(keys) == len(set(keys)), "权限点 key 必须全局唯一"

    for group in PERMISSION_CATALOG:
        assert group["label"], "分组必须有中文标签"
        assert group["items"], f"分组 {group['group']} 不能是空组"
        for item in group["items"]:
            assert item["key"] and item["label"]


def test_permission_catalog_matches_frontend_menu():
    """后端权限目录必须与前端 menuGroups 逐项对齐（含顺序）。

    两边漂移是**静默故障**：角色勾了菜单但界面没有、或界面有菜单但角色勾不上，
    界面上完全看不出报错。所以把 App.jsx 当数据源解析一次，钉死在测试里。
    """
    app_jsx = Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    source = app_jsx.read_text(encoding="utf-8")

    start = source.index("const menuGroups = [")
    end = source.index("\n];", start)
    block = source[start:end]

    # menuGroups 里的叶子项写成单行：{ key: 'x', label: 'y' } / { key: 'x', label: 'y', todo: true }
    item_pattern = re.compile(r"\{ key: '([a-z0-9-]+)', label: '([^']+)'(?:, todo: true)? \}")
    frontend_items = item_pattern.findall(block)
    assert frontend_items, "没能从 App.jsx 解出任何菜单项，正则需要跟着代码结构更新"

    frontend_keys = [key for key, _ in frontend_items]
    assert frontend_keys == all_menu_keys(), (
        "前端 menuGroups 与后端 PERMISSION_CATALOG 漂移了：\n"
        f"  仅前端有：{sorted(set(frontend_keys) - set(all_menu_keys()))}\n"
        f"  仅后端有：{sorted(set(all_menu_keys()) - set(frontend_keys))}"
    )

    # 分组标签顺序也要一致，否则角色权限树的排列会和左侧菜单对不上
    group_pattern = re.compile(r"label: '([^']+)',\n\s*origin:")
    frontend_groups = group_pattern.findall(block)
    assert frontend_groups == [group["label"] for group in PERMISSION_CATALOG]


def test_system_meta_payload():
    headers = _admin_headers()
    resp = client.get("/api/v1/system/meta", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_menus"] == len(all_menu_keys())
    assert data["permission_catalog"] == PERMISSION_CATALOG
    assert isinstance(data["departments"], list) and data["departments"]

    codes = {role["code"] for role in data["roles"]}
    for builtin in ("admin", "manager", "sales", "purchase", "warehouse", "finance", "staff"):
        assert builtin in codes, f"内置角色 {builtin} 未被播种"

    admin_role = next(role for role in data["roles"] if role["code"] == "admin")
    assert admin_role["permissions"]["all"] is True
    assert admin_role["is_builtin"] is True


# ============================================================
# 当前用户权限（前端菜单过滤的唯一数据源）
# ============================================================
def test_my_permissions_admin_gets_everything():
    resp = client.get("/api/v1/system/me/permissions", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["all"] is True
    assert sorted(data["menus"]) == sorted(all_menu_keys())


def test_my_permissions_follows_role_config():
    role = _new_role("测试角色-只读商品", menus=["overview", "products"])
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username, role_id=role["id"])

    login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    data = client.get("/api/v1/system/me/permissions", headers=headers).json()
    assert data["all"] is False
    assert sorted(data["menus"]) == ["overview", "products"]
    assert data["role_name"] == role["name"]

    # 非管理员进不了系统管理接口
    assert client.get("/api/v1/system/meta", headers=headers).status_code == 403
    assert client.get("/api/v1/system/users", headers=headers).status_code == 403

    admin = _admin_headers()
    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204


def test_my_permissions_denies_when_role_disabled():
    """角色被停用：必须收紧到最小菜单，绝不能放行全集。"""
    role = _new_role("测试角色-待停用", menus=["overview", "products", "sales"])
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username, role_id=role["id"])
    admin = _admin_headers()

    assert client.patch(f"/api/v1/system/roles/{role['id']}", json={"is_active": False}, headers=admin).status_code == 200

    login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    data = client.get("/api/v1/system/me/permissions", headers=headers).json()

    assert data["all"] is False
    assert data["menus"] == ["overview"], "角色停用后只应保留工作台，而不是原配置或全集"

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204


# ============================================================
# 组织机构
# ============================================================
def test_department_tree_levels_and_delete_guard():
    admin = _admin_headers()
    parent = _new_department("测试部门-总部")
    assert parent["level"] == 0

    child = _new_department("测试部门-分店", parent_id=parent["id"])
    assert child["level"] == 1
    assert child["parent_id"] == parent["id"]

    grandchild = _new_department("测试部门-柜台", parent_id=child["id"])
    assert grandchild["level"] == 2

    tree = client.get("/api/v1/system/departments", headers=admin).json()

    def find(nodes: list[dict], dept_id: int) -> dict | None:
        for node in nodes:
            if node["id"] == dept_id:
                return node
            found = find(node["children"], dept_id)
            if found:
                return found
        return None

    node = find(tree, parent["id"])
    assert node is not None, "新建的部门必须出现在树里"
    assert find(node["children"], child["id"]) is not None
    assert find(node["children"], grandchild["id"]) is not None

    # 有子部门 → 409
    blocked = client.delete(f"/api/v1/system/departments/{parent['id']}", headers=admin)
    assert blocked.status_code == 409
    assert "子部门" in blocked.json()["detail"]

    # 自底向上删干净
    for dept_id in (grandchild["id"], child["id"], parent["id"]):
        assert client.delete(f"/api/v1/system/departments/{dept_id}", headers=admin).status_code == 204


def test_department_cannot_move_under_its_own_descendant():
    """把 A 的上级设成 A 的子孙 → 树成环，必须 400。"""
    admin = _admin_headers()
    a = _new_department("测试部门-环A")
    b = _new_department("测试部门-环B", parent_id=a["id"])

    resp = client.patch(f"/api/v1/system/departments/{a['id']}", json={"parent_id": b["id"]}, headers=admin)
    assert resp.status_code == 400
    assert "循环" in resp.json()["detail"]

    # 自己当自己的上级也拦掉
    resp = client.patch(f"/api/v1/system/departments/{a['id']}", json={"parent_id": a["id"]}, headers=admin)
    assert resp.status_code == 400

    assert client.delete(f"/api/v1/system/departments/{b['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/departments/{a['id']}", headers=admin).status_code == 204


def test_department_with_users_cannot_be_deleted():
    admin = _admin_headers()
    dept = _new_department("测试部门-有人")
    user = _new_user(f"TEST-USR-{_hex()}", department_id=dept["id"])

    resp = client.delete(f"/api/v1/system/departments/{dept['id']}", headers=admin)
    assert resp.status_code == 409
    assert "用户" in resp.json()["detail"]

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/departments/{dept['id']}", headers=admin).status_code == 204


def test_department_code_must_be_unique():
    admin = _admin_headers()
    dept = _new_department("测试部门-编码")
    resp = client.post(
        "/api/v1/system/departments",
        json={"code": dept["code"], "name": "测试部门-重码"},
        headers=admin,
    )
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]
    assert client.delete(f"/api/v1/system/departments/{dept['id']}", headers=admin).status_code == 204


# ============================================================
# 角色
# ============================================================
def test_builtin_role_cannot_be_deleted():
    admin = _admin_headers()
    for code in ("admin", "manager", "sales"):
        role = next(r for r in client.get("/api/v1/system/roles", headers=admin).json() if r["code"] == code)
        assert role["is_builtin"] is True
        resp = client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)
        assert resp.status_code == 409
        assert "内置角色" in resp.json()["detail"]


def test_role_permissions_are_normalized():
    """写入权限时：未知菜单键被丢掉、重复键去重、all 强制成 bool。"""
    admin = _admin_headers()
    resp = client.post(
        "/api/v1/system/roles",
        json={
            "code": f"TEST-ROLE-{_hex()}",
            "name": "测试角色-归一",
            "permissions": {"all": "yes", "menus": ["products", "products", "不存在的菜单", "sales"]},
        },
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    assert role["permissions"] == {"all": True, "menus": ["products", "sales"]}

    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204


def test_role_in_use_cannot_be_deleted():
    admin = _admin_headers()
    role = _new_role("测试角色-在用")
    user = _new_user(f"TEST-USR-{_hex()}", role_id=role["id"])

    resp = client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)
    assert resp.status_code == 409
    assert "用户" in resp.json()["detail"]

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204


def test_role_update_permissions_takes_effect():
    admin = _admin_headers()
    role = _new_role("测试角色-改权限", menus=["overview"])
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username, role_id=role["id"])

    resp = client.patch(
        f"/api/v1/system/roles/{role['id']}",
        json={"permissions": {"all": False, "menus": ["overview", "products", "reports"]}},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["permissions"]["menus"] == ["overview", "products", "reports"]

    login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert sorted(client.get("/api/v1/system/me/permissions", headers=headers).json()["menus"]) == [
        "overview", "products", "reports",
    ]

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204


# ============================================================
# 用户
# ============================================================
def test_user_create_login_and_password_hash_never_exposed():
    admin = _admin_headers()
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username, role_id=None)

    assert user["role"] == "staff", "不指定角色时退回默认的 staff"

    payload = client.get("/api/v1/system/users", headers=admin).json()
    row = next(item for item in payload if item["username"] == username)
    assert "hashed_password" not in row and "password" not in row, "接口不得返回任何口令字段"

    assert client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "wrong-pass"}).status_code == 401

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204


def test_user_password_reset_and_disabled_login():
    admin = _admin_headers()
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username)

    resp = client.post(
        f"/api/v1/system/users/{user['id']}/password", json={"new_password": "NewPass456"}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    # 旧密码作废、新密码可用
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "NewPass456"}).status_code == 200

    # 停用：不能登录，且**已签发的旧 token 立即失效**
    token = client.post("/api/v1/auth/login", json={"username": username, "password": "NewPass456"}).json()["access_token"]
    old_headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/system/me/permissions", headers=old_headers).status_code == 200

    assert client.post(f"/api/v1/system/users/{user['id']}/toggle", headers=admin).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "NewPass456"}).status_code == 403
    assert client.get("/api/v1/system/me/permissions", headers=old_headers).status_code == 403

    # 重新启用后可登录
    assert client.post(f"/api/v1/system/users/{user['id']}/toggle", headers=admin).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "NewPass456"}).status_code == 200

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204


def test_user_cannot_delete_or_disable_self():
    admin = _admin_headers()
    admin_id = next(u["id"] for u in client.get("/api/v1/system/users", headers=admin).json() if u["username"] == "admin")

    resp = client.delete(f"/api/v1/system/users/{admin_id}", headers=admin)
    assert resp.status_code == 400
    assert "当前登录" in resp.json()["detail"]

    resp = client.post(f"/api/v1/system/users/{admin_id}/toggle", headers=admin)
    assert resp.status_code == 400

    resp = client.patch(f"/api/v1/system/users/{admin_id}", json={"role": "staff"}, headers=admin)
    assert resp.status_code == 400
    assert "管理员角色" in resp.json()["detail"]


def test_duplicate_username_rejected():
    admin = _admin_headers()
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username)

    resp = client.post(
        "/api/v1/system/users",
        json={"username": username, "password": "Pass1234"},
        headers=admin,
    )
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204


def test_user_filters_work():
    admin = _admin_headers()
    dept = _new_department("测试部门-筛选")
    role = _new_role("测试角色-筛选", menus=["overview"])
    username = f"TEST-USR-{_hex()}"
    user = _new_user(username, role_id=role["id"], department_id=dept["id"])

    rows = client.get("/api/v1/system/users", params={"keyword": username}, headers=admin).json()
    assert [row["username"] for row in rows] == [username]
    assert rows[0]["role_name"] == role["name"]
    assert rows[0]["department_name"] == dept["name"]

    rows = client.get("/api/v1/system/users", params={"department_id": dept["id"]}, headers=admin).json()
    assert username in [row["username"] for row in rows]

    rows = client.get("/api/v1/system/users", params={"role_id": role["id"]}, headers=admin).json()
    assert username in [row["username"] for row in rows]

    rows = client.get("/api/v1/system/users", params={"keyword": username, "is_active": False}, headers=admin).json()
    assert rows == []

    assert client.delete(f"/api/v1/system/users/{user['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/system/departments/{dept['id']}", headers=admin).status_code == 204


def test_system_endpoints_require_authentication():
    """未带 token：管理接口一律 401（不能因为"是本机"就放行）。"""
    assert client.get("/api/v1/system/meta").status_code == 401
    assert client.get("/api/v1/system/users").status_code == 401
    assert client.get("/api/v1/system/roles").status_code == 401
    assert client.get("/api/v1/system/me/permissions").status_code == 401
