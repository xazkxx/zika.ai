"""`POST /system/menus/reorder`（拖拽落库）回归测试 —— 2026-10-16 菜单树重构

这个接口是拖拽的唯一写入口，一次请求会改一整批节点的父子关系与顺序，
所以边界比普通 CRUD 更要紧。本文件重点守三件事：

1. **漏传 parent_id 必须 422，绝不能静默把节点搬到顶层。**
   这条不是理论洁癖 —— 实测真发生过：一次还原请求漏了 parent_id，
   7 个子菜单当场被顶到顶层（顶层 11 → 18 个），而接口返回的是 200。
   静默错误比报错可怕，所以 `MenuReorderItem.parent_id` 现在没有默认值。

2. **四类非法移动都要被挡**：成环 / 挂到菜单项下 / 上级是自己 / 节点不存在。
   挡不住的后果是侧边栏语义含糊或菜单凭空消失，都是最难排查的那类问题。

3. **跑完不能留下任何痕迹。** 本文件用一个 module 级 autouse fixture 在收尾比对
   菜单快照 —— 有用例忘记还原就会以 teardown error 暴露出来。

⚠️ 刻意**不调用** `POST /menus/reset`：那个接口会清空并重新播种菜单表，
   ID 会全部换新（实测把 2385–2449 换成了 2718–2782）。测试要用 reset 才能跑通，
   说明它本身就不该这么写。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BASE = "/api/v1/system/menus"
REORDER = f"{BASE}/reorder"


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def admin():
    return _headers()


def _flat() -> list[dict]:
    resp = client.get(BASE, headers=_headers())
    assert resp.status_code == 200, resp.text
    return resp.json()["flat"]


def _find(label: str) -> dict | None:
    return next((row for row in _flat() if row["label"] == label), None)


def _children(parent_id: int | None) -> list[dict]:
    """某个父级下的直接子节点，已按 (sort_order, id) 排好。"""
    kids = [row for row in _flat() if row["parent_id"] == parent_id]
    return sorted(kids, key=lambda r: (r["sort_order"], r["id"]))


def _snapshot() -> list[tuple]:
    """菜单结构快照：只取会决定"树长什么样"的四个字段。"""
    return sorted(
        (row["id"], row["parent_id"], row["sort_order"], row["label"]) for row in _flat()
    )


@pytest.fixture(scope="module", autouse=True)
def _guard_menu_unchanged():
    """整个模块跑完后，菜单结构必须与跑之前逐字节一致。"""
    before = _snapshot()
    yield
    after = _snapshot()
    assert after == before, (
        "本文件跑完后菜单结构变了，说明有用例没把改动还原。\n"
        f"多出/变动的行: {sorted(set(after) ^ set(before))[:5]}"
    )


@pytest.fixture()
def temp_menu_nodes():
    """建临时菜单节点，收尾按"先叶子后分组"删干净（有子节点的分组删不掉）。"""
    made: list[int] = []
    yield made
    for menu_id in reversed(made):
        client.delete(f"{BASE}/{menu_id}", headers=_headers())


# ============================================================================
# 1. 漏传 parent_id —— 本文件存在的首要理由
# ============================================================================
def test_missing_parent_id_is_rejected_not_silently_moved(admin):
    """漏传 parent_id 必须 422，且**菜单结构一个字节都不能变**。

    场景还原：把「客户档案」移到顶层，但 items 里漏写 parent_id。
    （锚点原为「导入导出」，它已在 v72 菜单瘦身里下架，2026-10-21 改用「客户档案」。）
    旧行为（危险）：接口返回 200，节点被静默搬到顶层。
    新行为：422 明确拒收，并说清该怎么写。
    """
    node = _find("客户档案")
    assert node is not None, "测试库应存在「客户档案」菜单"
    parent_before = node["parent_id"]
    assert parent_before is not None, "前置条件：它本来在某个分组下"

    before = _snapshot()
    resp = client.post(REORDER, json={"items": [{"id": node["id"], "sort_order": 10}]}, headers=admin)

    assert resp.status_code == 422, f"漏传 parent_id 必须被拒，实际 {resp.status_code}: {resp.text}"
    detail = str(resp.json().get("detail", ""))
    assert "parent_id" in detail, f"报错里要提到 parent_id，实际: {detail}"
    assert "null" in detail, f"报错要告诉调用方顶层写 null，实际: {detail}"

    # 关键：结构没被改动（旧 bug 就是这里悄悄变了）
    assert _snapshot() == before, "被拒的请求绝不能改动菜单结构"
    assert _find("客户档案")["parent_id"] == parent_before


def test_explicit_null_parent_id_is_accepted(admin):
    """显式写 parent_id: null 是合法的（顶层节点），不能跟着一起被拒。

    前端 collectPayload 一直是显式传值（顶层时就是 null），这条守住它不被误伤。
    """
    node = _find("客户档案")
    assert node is not None
    assert node["parent_id"] is not None

    # 先把它记下来，测完放回去
    back = [row for row in _children(node["parent_id"])]
    payload = {
        "items": [
            {"id": row["id"], "parent_id": row["parent_id"], "sort_order": row["sort_order"]}
            for row in back
        ]
    }
    # 顶层节点全部带上（parent_id 显式为 None）→ 序列化成 JSON 就是 null
    tops = _children(None)
    payload["items"] += [
        {"id": row["id"], "parent_id": None, "sort_order": row["sort_order"]} for row in tops
    ]

    resp = client.post(REORDER, json=payload, headers=admin)
    assert resp.status_code == 200, f"显式 null 应当被接受，实际 {resp.status_code}: {resp.text}"
    assert _find("客户档案")["parent_id"] is not None, "它不应该跑到顶层去"


def test_missing_parent_id_error_points_at_offending_item(admin):
    """一批里只有第 2 项漏传 —— 报错要能定位到具体哪一项。"""
    tops = _children(None)
    assert len(tops) >= 1
    resp = client.post(
        REORDER,
        json={
            "items": [
                {"id": tops[0]["id"], "parent_id": None, "sort_order": 10},
                {"id": tops[0]["id"], "sort_order": 20},  # ← 这一项漏了 parent_id
            ]
        },
        headers=admin,
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    locs = [tuple(err.get("loc", ())) for err in detail]
    assert any("items" in loc and 1 in loc for loc in locs), f"应定位到 items[1]，实际: {locs}"


# ============================================================================
# 2. 正常移动
# ============================================================================
def test_reorder_siblings_renumbers_contiguously(admin):
    """同级重排：把第 1 个子项挪到最后，序号要重排成连续的 10/20/30…"""
    group = _find("基础资料")
    assert group is not None
    kids = _children(group["id"])
    assert len(kids) >= 3, "测试库的「基础资料」下应有多个子项"

    original = [{"id": r["id"], "parent_id": r["parent_id"], "sort_order": r["sort_order"]} for r in kids]

    # 把第一个挪到末尾：完整兄弟组一起发（前端 collectPayload 就是这么发的）
    reordered = kids[1:] + kids[:1]
    resp = client.post(
        REORDER,
        json={
            "items": [
                {"id": r["id"], "parent_id": group["id"], "sort_order": (i + 1) * 10}
                for i, r in enumerate(reordered)
            ]
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    after = _children(group["id"])
    assert [r["id"] for r in after] == [r["id"] for r in reordered], "顺序应与提交的一致"
    assert [r["sort_order"] for r in after] == [(i + 1) * 10 for i in range(len(after))], "序号应连续无空洞"

    # 还原
    assert client.post(REORDER, json={"items": original}, headers=admin).status_code == 200


def test_move_between_groups_renumbers_both_parents(admin, temp_menu_nodes):
    """跨组移动：旧父级与新父级的序号都要重排（旧位置不能留空洞）。"""
    source = _find("基础资料")
    target = _find("系统设置")
    assert source and target

    old_kids = _children(source["id"])
    old_last = old_kids[-1]

    resp = client.post(
        REORDER,
        json={"items": [{"id": old_last["id"], "parent_id": target["id"], "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    # 旧父级：剩下的子项序号重新连续
    left = _children(source["id"])
    assert [r["sort_order"] for r in left] == [(i + 1) * 10 for i in range(len(left))]
    assert old_last["id"] not in [r["id"] for r in left]

    # 新父级：它排在第一位
    moved = _children(target["id"])
    assert moved[0]["id"] == old_last["id"]

    # 还原：搬回去 + 两侧序号复原
    restore = [{"id": r["id"], "parent_id": source["id"], "sort_order": (i + 1) * 10} for i, r in enumerate(old_kids)]
    restore += [
        {"id": r["id"], "parent_id": target["id"], "sort_order": (i + 1) * 10}
        for i, r in enumerate([x for x in _children(target["id"]) if x["id"] != old_last["id"]])
    ]
    assert client.post(REORDER, json={"items": restore}, headers=admin).status_code == 200


def test_empty_items_is_a_noop(admin):
    """空 items 是合法的无操作（前端 probeReorderApi 靠它探测接口是否存在）。"""
    before = _snapshot()
    resp = client.post(REORDER, json={"items": []}, headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "tree" in body and "flat" in body, "应返回与 GET /menus 同构的结构"
    assert _snapshot() == before


# ============================================================================
# 3. 非法移动
# ============================================================================
def test_cannot_move_group_into_its_own_descendant(admin):
    """成环必须被拒（把分组挂到它自己的后代里）。"""
    group = _find("基础资料")
    kids = _children(group["id"])
    assert kids, "需要至少一个子节点才能构造成环"

    before = _snapshot()
    resp = client.post(
        REORDER,
        json={"items": [{"id": group["id"], "parent_id": kids[0]["id"], "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "环" in resp.json()["detail"]
    assert _snapshot() == before, "被拒的请求不能改动结构"


def test_cannot_move_into_a_menu_leaf(admin):
    """「菜单项」不能有下级 —— 否则"点它是跳页还是展开"就含糊了。"""
    leaf = next((row for row in _flat() if row["page_key"] and row["parent_id"] is not None), None)
    assert leaf is not None
    other = _find("系统设置")
    victim = _children(other["id"])[0]

    before = _snapshot()
    resp = client.post(
        REORDER,
        json={"items": [{"id": victim["id"], "parent_id": leaf["id"], "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 409, resp.text
    assert "菜单项" in resp.json()["detail"]
    assert _snapshot() == before


def test_cannot_be_its_own_parent(admin):
    group = _find("基础资料")
    before = _snapshot()
    resp = client.post(
        REORDER,
        json={"items": [{"id": group["id"], "parent_id": group["id"], "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "自己" in resp.json()["detail"]
    assert _snapshot() == before


def test_unknown_node_and_parent_are_rejected(admin):
    group = _find("基础资料")

    resp = client.post(
        REORDER,
        json={"items": [{"id": 99999999, "parent_id": group["id"], "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 404, resp.text
    assert "不存在" in resp.json()["detail"]

    victim = _children(group["id"])[0]
    before = _snapshot()
    resp = client.post(
        REORDER,
        json={"items": [{"id": victim["id"], "parent_id": 99999999, "sort_order": 10}]},
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "上级菜单" in resp.json()["detail"]
    assert _snapshot() == before


def test_duplicate_node_in_items_is_rejected(admin):
    group = _find("基础资料")
    victim = _children(group["id"])[0]
    before = _snapshot()
    resp = client.post(
        REORDER,
        json={
            "items": [
                {"id": victim["id"], "parent_id": group["id"], "sort_order": 10},
                {"id": victim["id"], "parent_id": None, "sort_order": 20},
            ]
        },
        headers=admin,
    )
    assert resp.status_code == 400, resp.text
    assert "两次" in resp.json()["detail"]
    assert _snapshot() == before


# ============================================================================
# 4. 权限
# ============================================================================
def test_reorder_requires_admin_token():
    """无 token 必须 401（不能像老的业务端点那样裸奔）。"""
    resp = client.post(REORDER, json={"items": []})
    assert resp.status_code == 401, f"无 token 应当 401，实际 {resp.status_code}"
