"""第 10 批（动态菜单管理）回归测试。

用户提的是「目前好像没有向下级创建菜单的能力」。改造把**菜单的展示结构**搬进了
数据库（`menus` 表），管理员可以在界面里自由增删层级。这一批最容易出问题的地方
不是"能不能建菜单"，而是**边界有没有守住** —— 所以测试的重点在下面四条：

1. `test_menu_page_key_must_be_a_real_page` —— 菜单项必须挂在**已有页面**上。
   放进来一个不存在的 key，用户点这个菜单只会看到一片空白，而且界面上没有任何
   报错（前端没有对应渲染分支）。这是整个功能的安全阀。
2. `test_menu_cannot_build_beyond_max_depth` / `..._leaf_cannot_have_children`
   —— 层级与"菜单项不能再挂下级"的约束。不守的话侧边栏的语义会含糊：
   点一个既有页面又有子节点的菜单，到底是跳页还是展开？
3. `test_menu_delete_guard_and_reset` —— 有子节点不许删（不做级联删除），
   以及"恢复默认"能把出厂树找回来。
4. `test_permission_model_is_not_touched` —— 权限模型**一行没动**：
   权限点仍然是那份固定的页面清单，角色拿到的还是页面 key 数组。
   菜单树只管"怎么展示"，不管"能不能看"。

另外还有两条防退化的断言：
- 内置菜单种子必须**原样复刻**改造前的两级结构，这样"换成动态菜单"对老用户观感零变化；
- 前端侧边栏必须真的用后端下发的菜单树（而不是又回去读内置常量）。
"""

import pytest
from fastapi.testclient import TestClient

from app.core.permissions import PERMISSION_CATALOG, all_menu_keys
from app.main import app
from app.models.menu import MAX_MENU_DEPTH, Menu, default_menu_specs

client = TestClient(app)
BASE = "/api/v1/system/menus"


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def admin():
    return _headers()


def _find(label: str) -> dict | None:
    """按名称在扁平列表里找一个节点。"""
    flat = client.get(BASE, headers=_headers()).json()["flat"]
    return next((row for row in flat if row["label"] == label), None)


@pytest.fixture()
def temp_nodes():
    """建一批临时菜单节点，收尾按"先叶子后分组"删干净。

    收尾顺序不能颠倒：有子节点的分组删不掉（接口 409）。
    """
    made: list[int] = []
    yield made
    for menu_id in reversed(made):
        client.delete(f"{BASE}/{menu_id}", headers=_headers())


# ============================================================
# 播种：默认树必须原样复刻改造前的两级结构
# ============================================================
def test_default_seed_mirrors_catalog():
    """种子 = PERMISSION_CATALOG 的两级复刻，条数必须严丝合缝。

    这条是"换成动态菜单对老用户观感零变化"的保证：默认树就是原来那份
    「分组 → 菜单项」，一个不多一个不少。
    """
    specs = default_menu_specs()
    groups = [spec for spec in specs if spec[0] is None]
    leaves = [spec for spec in specs if spec[0] is not None]

    assert len(groups) == len(PERMISSION_CATALOG)
    assert len(leaves) == len(all_menu_keys())
    # 每个叶子的 page_key 都与目录一一对应
    assert {spec[2] for spec in leaves} == set(all_menu_keys())
    # 每个叶子的父分组名都能在分组里找到（否则播种时会挂空）
    group_names = {spec[1] for spec in groups}
    assert all(spec[0] in group_names for spec in leaves)


def test_seeded_tree_matches_catalog_order(admin):
    """真实播种出来的树：顶层分组顺序与目录一致，页面齐全。"""
    data = client.get(BASE, headers=admin).json()
    assert data["total"] > 0, "菜单表没有播种"
    assert [node["label"] for node in data["tree"]] == [g["label"] for g in PERMISSION_CATALOG]

    tree_pages = set()
    for group in data["tree"]:
        for child in group["children"]:
            if child["page_key"]:
                tree_pages.add(child["page_key"])
    assert tree_pages == set(all_menu_keys())

    # 每个节点都带派生字段，前端直接渲染
    first = data["tree"][0]["children"][0]
    assert first["kind"] == "menu"
    assert first["kind_label"] == "菜单项"
    assert first["page_label"]
    assert data["tree"][0]["kind"] == "group"


def test_seeding_is_idempotent(admin):
    """重复播种不能翻倍 —— 重启一次菜单就变两套是最糟的故障。"""
    from app.main import ensure_default_menus

    before = client.get(BASE, headers=admin).json()["total"]
    ensure_default_menus()
    ensure_default_menus()
    after = client.get(BASE, headers=admin).json()["total"]
    assert before == after


# ============================================================
# ⭐ 安全阀：菜单项必须挂在真实页面上
# ============================================================
def test_menu_page_key_must_be_a_real_page(admin):
    """不存在的 page_key 一律 400。

    这是整件事的安全阀：菜单只是个"壳"，背后必须有前端的
    `selectedTab === 'xxx'` 渲染分支，否则用户点进去是空白页，
    而且**界面上不会有任何报错** —— 这类问题极难排查，所以在写入口就掐死。
    """
    resp = client.post(BASE, json={"label": "幽灵菜单", "page_key": "no-such-page"}, headers=admin)
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]
    assert "空白" in resp.json()["detail"], "报错要说清后果，否则用户不知道为什么不让填"

    # 合法的 page_key 能建（用临时节点，收尾删掉）
    created = client.post(BASE, json={"label": "临时-客户", "page_key": "customers"}, headers=admin)
    assert created.status_code == 201, created.text
    assert created.json()["page_key"] == "customers"
    assert created.json()["page_label"] == "客户档案"
    client.delete(f"{BASE}/{created.json()['id']}", headers=admin)

    # 可选页面清单要一并下发（前端下拉直接用）
    pages = client.get(BASE, headers=admin).json()["pages"]
    assert {page["key"] for page in pages} == set(all_menu_keys())
    assert all(page["label"] and page["group"] for page in pages)


# ============================================================
# ⭐ 层级与形状约束
# ============================================================
def test_menu_can_nest_three_levels(admin, temp_nodes):
    """分组 → 子分组 → 菜单项：三级必须能建出来（这就是用户要的"下级菜单"）。"""
    basic = _find("基础资料")
    assert basic and basic["kind"] == "group"

    sub = client.post(BASE, json={"label": "临时子组", "parent_id": basic["id"]}, headers=admin)
    assert sub.status_code == 201, sub.text
    assert sub.json()["kind"] == "group"
    assert sub.json()["depth"] == 2, "顶层分组下的子分组应该是第 2 层"
    temp_nodes.append(sub.json()["id"])

    leaf = client.post(
        BASE,
        json={"label": "临时客户入口", "parent_id": sub.json()["id"], "page_key": "customers"},
        headers=admin,
    )
    assert leaf.status_code == 201, leaf.text
    assert leaf.json()["kind"] == "menu"
    assert leaf.json()["depth"] == 3
    assert leaf.json()["page_label"] == "客户档案"
    temp_nodes.append(leaf.json()["id"])

    # 树里真的嵌进去了
    tree = client.get(BASE, headers=admin).json()["tree"]
    basic_node = next(node for node in tree if node["label"] == "基础资料")
    sub_node = next(node for node in basic_node["children"] if node["label"] == "临时子组")
    assert [child["label"] for child in sub_node["children"]] == ["临时客户入口"]


def test_menu_cannot_build_beyond_max_depth(admin, temp_nodes):
    """超过 MAX_MENU_DEPTH 层要被拒 —— 左侧导航是纵向空间，再深就点不中了。

    ⚠️ 2026-10-16 菜单树重构：上限从写死的 3 改成**可配置**（默认 8，环境变量
    `ERP_MAX_MENU_DEPTH` 覆盖）。所以这个用例不再断言"第 4 层被拒"，
    而是**按当前上限动态造一条链**再越界 —— 上限以后调了，用例照样有效。

    保留原有的"菜单项不能再挂下级"检查（那是另一条规则，报错文案不同）。
    """
    basic = _find("基础资料")  # 第 1 层

    # 1) 原有检查：挂在"菜单项"下面被挡，报错里要能看出是哪一条规则
    sub = client.post(BASE, json={"label": "临时深组", "parent_id": basic["id"]}, headers=admin).json()
    temp_nodes.append(sub["id"])
    leaf = client.post(
        BASE,
        json={"label": "临时深菜单", "parent_id": sub["id"], "page_key": "customers"},
        headers=admin,
    ).json()
    temp_nodes.append(leaf["id"])

    too_deep = client.post(
        BASE,
        json={"label": "临时第四层", "parent_id": leaf["id"], "page_key": "customers"},
        headers=admin,
    )
    assert too_deep.status_code == 409
    assert "菜单项" in too_deep.json()["detail"]

    # 2) 真正测深度上限：从第 2 层一直造到第 MAX_MENU_DEPTH 层（都建成分组才挂得下去）
    parent_id = basic["id"]
    for depth in range(2, MAX_MENU_DEPTH + 1):
        node = client.post(
            BASE, json={"label": f"临时深组{depth}", "parent_id": parent_id}, headers=admin
        )
        assert node.status_code == 201, f"第 {depth} 层本应在上限内，却被拒：{node.json()}"
        temp_nodes.append(node.json()["id"])
        parent_id = node.json()["id"]

    # 上限之外再加一层 → 400，且文案要说清上限是多少
    overflow = client.post(BASE, json={"label": "临时超深组", "parent_id": parent_id}, headers=admin)
    assert overflow.status_code == 400
    assert f"最多 {MAX_MENU_DEPTH} 层" in overflow.json()["detail"]

    # 3) 上限要"够用且可配置"：
    #    · ≥3 才能表达 分组 → 子分组 → 菜单项
    #    · 可配置性用源码级检查（不 reload 模块 —— 重新定义 SQLAlchemy 模型会让
    #      同一张表在 Base 上重复注册，直接搞崩整个测试会话）
    assert MAX_MENU_DEPTH >= 3
    import inspect
    import sys as _sys

    src = inspect.getsource(_sys.modules["app.models.menu"])
    assert "ERP_MAX_MENU_DEPTH" in src, "深度上限必须能由环境变量 ERP_MAX_MENU_DEPTH 覆盖"


def test_leaf_cannot_have_children(admin, temp_nodes):
    """菜单项（已挂页面）不能再挂下级。

    否则"点它是跳页还是展开"就含糊了 —— 侧边栏的交互必须无歧义。
    """
    leaf = client.post(BASE, json={"label": "临时叶子", "page_key": "products"}, headers=admin).json()
    temp_nodes.append(leaf["id"])

    child = client.post(BASE, json={"label": "临时叶子下级", "parent_id": leaf["id"]}, headers=admin)
    assert child.status_code == 409
    assert "菜单项" in child.json()["detail"]

    # 有子节点的分组反过来也不能被改成菜单项
    basic = _find("基础资料")
    flip = client.patch(f"{BASE}/{basic['id']}", json={"page_key": "customers"}, headers=admin)
    assert flip.status_code == 409
    assert "个子菜单" in flip.json()["detail"]


def test_menu_rejects_cycle_and_duplicate_label(admin, temp_nodes):
    """成环与同层重名都要挡住。"""
    basic = _find("基础资料")
    sub = client.post(BASE, json={"label": "临时环组", "parent_id": basic["id"]}, headers=admin).json()
    temp_nodes.append(sub["id"])
    inner = client.post(BASE, json={"label": "临时环内组", "parent_id": sub["id"]}, headers=admin).json()
    temp_nodes.append(inner["id"])

    # 把外层的分组挂到它自己的下级里 → 成环
    cycle = client.patch(f"{BASE}/{sub['id']}", json={"parent_id": inner["id"]}, headers=admin)
    assert cycle.status_code == 400
    assert "环" in cycle.json()["detail"]

    # 挂到自己身上
    self_parent = client.patch(f"{BASE}/{sub['id']}", json={"parent_id": sub["id"]}, headers=admin)
    assert self_parent.status_code == 400

    # 同层重名
    dup = client.post(BASE, json={"label": "临时环组", "parent_id": basic["id"]}, headers=admin)
    assert dup.status_code == 400
    assert "已经有叫" in dup.json()["detail"]

    # 上级不存在
    ghost = client.post(BASE, json={"label": "临时孤儿", "parent_id": 99999999}, headers=admin)
    assert ghost.status_code == 400
    assert "上级菜单不存在" in ghost.json()["detail"]


# ============================================================
# 删除守卫 / 隐藏 / 恢复默认
# ============================================================
def test_menu_delete_guard_and_reset(admin, temp_nodes):
    """有子节点不许删（不做级联），删叶子可以，恢复默认能重建出厂树。"""
    basic = _find("基础资料")
    sub = client.post(BASE, json={"label": "临时待删组", "parent_id": basic["id"]}, headers=admin).json()
    temp_nodes.append(sub["id"])
    leaf = client.post(
        BASE, json={"label": "临时待删项", "parent_id": sub["id"], "page_key": "customers"}, headers=admin
    ).json()
    temp_nodes.append(leaf["id"])

    blocked = client.delete(f"{BASE}/{sub['id']}", headers=admin)
    assert blocked.status_code == 409
    assert "个子菜单" in blocked.json()["detail"]

    assert client.delete(f"{BASE}/{leaf['id']}", headers=admin).status_code == 204
    temp_nodes.remove(leaf["id"])
    assert client.delete(f"{BASE}/{sub['id']}", headers=admin).status_code == 204
    temp_nodes.remove(sub["id"])

    assert client.delete(f"{BASE}/{sub['id']}", headers=admin).status_code == 404
    assert client.patch(f"{BASE}/99999999", json={"label": "x"}, headers=admin).status_code == 404


def test_hidden_menu_leaves_the_user_tree(admin, temp_nodes):
    """隐藏 = 从用户导航里消失；但如果它是某个分组下唯一的内容，那个分组也要消失。

    空分组留在侧边栏里只会让人以为坏了。
    """
    basic = _find("基础资料")
    sub = client.post(BASE, json={"label": "临时独苗组", "parent_id": basic["id"]}, headers=admin).json()
    temp_nodes.append(sub["id"])
    leaf = client.post(
        BASE, json={"label": "临时独苗项", "parent_id": sub["id"], "page_key": "customers"}, headers=admin
    ).json()
    temp_nodes.append(leaf["id"])

    def _visible(label: str) -> bool:
        tree = client.get("/api/v1/system/me/permissions", headers=_headers()).json()["menu_tree"]

        def walk(nodes):
            for node in nodes:
                if node["label"] == label:
                    return True
                if walk(node["children"]):
                    return True
            return False

        return walk(tree)

    assert _visible("临时独苗项")
    client.patch(f"{BASE}/{leaf['id']}", json={"is_enabled": False}, headers=admin)
    assert not _visible("临时独苗项"), "隐藏后不该再出现在用户导航里"
    assert not _visible("临时独苗组"), "里面没有可见内容的分组也要一起消失"

    client.patch(f"{BASE}/{leaf['id']}", json={"is_enabled": True}, headers=admin)
    assert _visible("临时独苗项") and _visible("临时独苗组")


def test_reset_restores_default_tree(admin, temp_nodes):
    """恢复默认：自定义节点清空，出厂树一条不少。"""
    basic = _find("基础资料")
    sub = client.post(BASE, json={"label": "临时将被重置", "parent_id": basic["id"]}, headers=admin).json()
    temp_nodes.append(sub["id"])
    assert client.get(BASE, headers=admin).json()["total"] == len(default_menu_specs()) + 1

    resp = client.post(f"{BASE}/reset", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == len(default_menu_specs())
    assert _find("临时将被重置") is None  # 已被重置清掉，temp_nodes 收尾删它会 404，无妨


# ============================================================
# 权限模型没被动过
# ============================================================
def test_permission_model_is_not_touched(admin):
    """权限点仍然是那份**固定的页面清单**，菜单树只管展示。

    这条是这次改造里最重要的架构边界：如果顺手让"菜单"变成权限点，
    角色权限就会绑在可变的菜单上 —— 管理员删个菜单，所有人的权限跟着漂。
    """
    catalog = client.get("/api/v1/system/permissions", headers=admin).json()
    catalog_keys = [
        str(item["key"]) for group in catalog["groups"] for item in group["items"]  # type: ignore[index]
    ]
    assert catalog_keys == all_menu_keys()
    # 权限目录与菜单表解耦：把菜单改名 / 隐藏，权限目录一个字都不变
    me = client.get("/api/v1/system/me/permissions", headers=admin).json()
    assert set(me["menus"]) == set(all_menu_keys())


# ============================================================
# 前后端挂载（防退化：不许又回去读内置常量）
# ============================================================
def test_frontend_renders_from_backend_menu_tree():
    """侧边栏必须真的用后端下发的菜单树，而不是又回去读内置的 menuGroups。"""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")

    # 数据源：优先 menuTree，兜底 menuGroups
    assert "if (Array.isArray(menuTree) && menuTree.length > 0) return menuTree;" in source
    # 递归渲染（三级）
    assert "const renderNavNodes = (nodes, depth = 0) => {" in source
    assert "{renderNavNodes(visibleGroups)}" in source
    # 菜单管理页 + 菜单项
    assert "selectedTab === 'menus'" in source
    assert "{ key: 'menus', label: '菜单管理' }" in source
    # 关键调用点
    for endpoint in ("/system/menus", "/system/menus/reset"):
        assert endpoint in source, f"前端没有调用 {endpoint}"
    for handler in ("refreshMenuAdmin", "submitMenu", "toggleMenuEnabled", "resetMenus"):
        assert handler in source, f"前端缺少处理函数 {handler}"


def test_menu_admin_page_has_no_topbar_actions():
    """菜单管理属于系统设置类页面，顶栏不该挂操作（收录标准见 pageActions 的注释）。"""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")
    start = source.index("const pageActions = {")
    block = source[start : source.index("\n};", start)]
    assert "\n  menus:" not in block


def test_permission_refresh_does_not_hijack_the_current_page():
    """刷新权限**不能**把用户弹回默认落地页。

    这是本批端到端抓出来的真 Bug：`/system/me/permissions` 除了权限还会下发
    `ui.default_page`，早先 `loadMyPermissions` 无条件跳过去 —— 于是任何
    "顺手刷一下权限"的地方（存菜单、存角色、改参数）都会把用户当场弹回首页。
    表现是"在菜单管理里点保存，页面像没反应一样跳走了"。

    修法：跳落地页改成显式开关 `applyLanding`，只有登录那一次传 true。
    后来端到端又抓出第二个时序坑：权限接口是**异步**的，用户完全可能在它返回之前
    就点了菜单 —— 于是刚点开的页面照样被落地页顶走（表现为"点库存预警闪回运营概览"）。
    补上的第二道闸是 `userNavigatedRef`：用户点过菜单之后，落地页一律作废。
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")

    # 默认必须是"不跳"
    assert "async function loadMyPermissions(token, applyLanding = false) {" in source

    # 落地页要过两道闸：applyLanding（只有登录那次）+ userNavigatedRef（用户没自己点过）
    assert (
        "if (applyLanding && landing && !userNavigatedRef.current) setSelectedTab(landing);"
        in source
    )

    # 闸门本体：点菜单时置位；否则这个条件恒为真，上面那行等于没加
    assert "const userNavigatedRef = useRef(false);" in source
    assert "userNavigatedRef.current = true;" in source

    # 全项目只有一个调用点可能跳落地页：启动/登录时的 `!canRestoreTab`。
    # 2026-10-21 起，登录与"带 token 刷新"共用同一处调用（loadCurrentUser），
    # 落地页是否生效由"有没有上次页面"决定 —— 所以合法形式是 `!canRestoreTab`，
    # 而不是写死的 `true`。其余调用一律不传第二参（applyLanding 默认 false）。
    assert (
        source.count("loadMyPermissions(authToken, !canRestoreTab)") == 1
    ), "启动/登录处应恰有一处按「能否恢复上次页面」决定落地页"
    # 其余调用点都必须是不带 applyLanding 的形式，否则"顺手刷权限"又会把人弹回首页。
    # 判据看"逗号"：带了第二参的调用全项目只允许上面那一处。
    assert (
        source.count("loadMyPermissions(authToken,") == 1
    ), "除启动处外不应再给 loadMyPermissions 传 applyLanding"
