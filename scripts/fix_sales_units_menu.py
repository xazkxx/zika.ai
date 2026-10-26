#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""「销售出库（多单位）」菜单不出现 —— 一键排查 / 修复。

用法（在项目根目录，用项目自己的 venv）:

    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py           # 只体检，不动任何文件
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --fix     # 体检 + 打补丁 + 回填菜单表
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --fix --yes   # 同上，跳过确认
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --grant-roles  # 把该菜单补进 6 个内置业务角色
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --revoke-roles # 反向：从这 6 个角色里摘掉
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --revoke-roles --roles purchase,finance,staff
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --align-manager # manager 差集补齐到代码派生列表
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --grant-roles --roles warehouse --menu stock-alert
    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --grant-roles --roles finance  --menu general-ledger

`--grant-roles` / `--revoke-roles` 只动 `roles.permissions` 的 JSON，幂等、可来回跑；
它和 `--fix` 互不依赖（`--fix` 修的是"菜单节点存不存在"，这里修的是"角色看不看得见"）。

它检查的 6 件事（顺序即排查顺序）:

  1. app/core/permissions.py  —— PERMISSION_CATALOG 里到底有没有 sales-units
  2. frontend/src/App.jsx     —— 三处挂载点（import / menuGroups / 分发区）在不在
  3. public.menus             —— 表里有没有这个节点（**按 page_key 查，绝不按 id 查**）
  4. public.roles             —— admin 是不是 all=true（这决定了"要不要授权表"）
  5. 后端 /system/me/permissions —— 在线则真登录一次，看下发的 menus 与 menu_tree
  6. frontend/dist            —— 打出来的包里有不有这个菜单键

⚠️ 为什么第 3 项绝不按 id 查:
   `tests/test_menu_admin.py` 会 `POST /menus/reset`，菜单 id 每次全换
   （2385→2718→2803→2889→2892 …）。写死 id 的排查脚本，第一次能查到、
   跑完测试就永远查不到，是最坑的一类假阴性。

设计原则: 只补不改、可重复跑。补丁用「唯一锚点 + 断言 count==1」定位，
不用硬编码行号（行号会漂），锚点不唯一就报错退出、绝不猜。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)              # `app.core.config` 里 .env 是相对路径，必须先 chdir
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:           # pragma: no cover - 老控制台
    pass

PAGE_KEY = "sales-units"
LABEL = "销售出库（多单位）"
# 内置业务角色（admin 不在此列 —— 它 all=true，天然有全部菜单）
ROLE_CODES = ["manager", "sales", "purchase", "warehouse", "finance", "staff"]
PERMISSIONS_PY = ROOT / "app" / "core" / "permissions.py"
APP_JSX = ROOT / "frontend" / "src" / "App.jsx"

OK, BAD, WARN, SKIP = "[ OK ]", "[ !! ]", "[ ?? ]", "[ -- ]"
problems: list[str] = []
warnings: list[str] = []


def say(tag: str, msg: str) -> None:
    print(f"{tag} {msg}")


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
# 文件读写：**必须保留原换行符**
#   Path.read_text() 会把字节原样解出来，但 Path.write_text() 默认把 \n 翻成 \r\n，
#   对 LF 文件会造成「整文件被改写」的假 diff。所以统一 open(newline='')。
# ---------------------------------------------------------------------------
def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def eol_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(f"{path.name}.bak_{stamp}")
    shutil.copy2(path, dst)
    return dst


def insert_after(text: str, anchor: str, new_line: str, what: str) -> str:
    """在唯一锚点行之后插入一行（沿用文件自身换行符）。锚点不唯一 → 抛错不动手。"""
    count = text.count(anchor)
    if count != 1:
        raise RuntimeError(f"锚点不唯一（命中 {count} 次），拒绝盲改：{what}\n  锚点: {anchor!r}")
    eol = eol_of(text)
    # ⚠️ 多行插入块里的 \n 必须跟着目标文件的换行符走，否则往 CRLF 文件里混进 LF 行，
    #    git diff 会显示成「整段被改写」，而且下次用别的工具改更容易出问题。
    new_line = new_line.replace("\r\n", "\n").replace("\n", eol)
    return text.replace(anchor, anchor + eol + new_line, 1)


# ---------------------------------------------------------------------------
# 1. permissions.py
# ---------------------------------------------------------------------------
def check_permissions_py() -> tuple[bool, str]:
    text = read_text(PERMISSIONS_PY)
    has_key = f'"{PAGE_KEY}"' in text
    # 顺带把销售组实际项数数出来：6 → 加完应为 7
    m = re.search(r'"group": "sales".*?"items": \[(.*?)\]', text, re.S)
    items = re.findall(r'"key":\s*"([^"]+)"', m.group(1)) if m else []

    if has_key:
        say(OK, f"permissions.py 已含 {PAGE_KEY}（销售组共 {len(items)} 项）")
    else:
        say(BAD, f"permissions.py **没有** {PAGE_KEY}（销售组只有 {len(items)} 项: {', '.join(items)}）")
        problems.append("permissions.py 缺 sales-units —— 这是菜单缺失的根因")
    return has_key, text


# ---------------------------------------------------------------------------
# 2. App.jsx 三处挂载点
# ---------------------------------------------------------------------------
def check_app_jsx() -> tuple[bool, str]:
    text = read_text(APP_JSX)
    lines = text.splitlines()

    # 换行符体检：App.jsx 是 CRLF。混进 LF 会被 git 显示成整文件改写。
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    say(OK if lf_only == 0 else BAD,
        f"App.jsx 换行符: CRLF {crlf} 行 / 裸 LF {lf_only} 行"
        + ("" if lf_only == 0 else "  ← ⚠️ 混合换行，需要归一"))
    if lf_only:
        problems.append(f"App.jsx 有 {lf_only} 行是裸 LF（应为 CRLF）")

    def find(pattern: str) -> list[tuple[int, str]]:
        rx = re.compile(pattern)
        return [(i + 1, ln) for i, ln in enumerate(lines) if rx.search(ln)]

    spots = {
        "① import": find(r"^\s*import\s+\{\s*SalesOrderUnitsBoard\s*\}"),
        "② menuGroups": find(r"key:\s*'sales-units'"),
        "③ 分发区": find(r"selectedTab\s*===\s*'sales-units'"),
    }
    all_ok = True
    for name, hits in spots.items():
        if hits:
            for ln, content in hits:
                say(OK, f"App.jsx {name} 命中 → 第 {ln} 行: {content.strip()}")
        else:
            all_ok = False
            say(BAD, f"App.jsx {name} **缺失**")
            problems.append(f"App.jsx {name} 缺失")

    # 顺手报告锚点当前行号，方便人工核对
    for label, pattern in (
        ("import 锚点", r"^import WarehousesPage"),
        ("menuGroups 锚点", r"key:\s*'sales-statement'"),
        ("分发区锚点", r"selectedTab === 'sales' && <SalesPage"),
    ):
        hits = find(pattern)
        if hits:
            say(OK, f"{label} 在第 {hits[0][0]} 行（补丁会插在它后面）")
    return all_ok, text


# ---------------------------------------------------------------------------
# 3/4. 数据库：public.menus 与 public.roles
# ---------------------------------------------------------------------------
def db_session():
    from app.db.session import SessionLocal

    return SessionLocal()


def check_db_menus(db) -> None:
    from app.models import Menu, default_menu_specs

    total = db.query(Menu).count()
    specs = default_menu_specs()
    expect = len(specs)
    say(OK if total == expect else WARN, f"public.menus 共 {total} 个节点；default_menu_specs() = {expect} 个")
    if total != expect:
        warnings.append(
            f"public.menus({total}) 与 PERMISSION_CATALOG 派生出的 {expect} 个节点不一致 —— "
            "重启后端会跑 _backfill_builtin_menus 补齐（只补不改）"
        )

    # 销售管理分组：按 label 找，不按 id
    group = db.query(Menu).filter(Menu.label == "销售管理", Menu.page_key.is_(None)).first()
    if group is None:
        say(BAD, "public.menus 里找不到顶层分组「销售管理」")
        problems.append("public.menus 缺「销售管理」分组")
    else:
        kids = (
            db.query(Menu)
            .filter(Menu.parent_id == group.id)
            .order_by(Menu.sort_order, Menu.id)
            .all()
        )
        say(OK, f"「销售管理」= id {group.id}，子节点 {len(kids)} 个：")
        for k in kids:
            flag = "" if k.is_enabled else "   ← ⚠️ is_enabled=False（_visible_menu_tree 会过滤掉它）"
            print(f"        id={k.id:<6} sort={k.sort_order:<4} page_key={k.page_key or '(空)':<20} {k.label}{flag}")
            if not k.is_enabled:
                warnings.append(f"菜单「{k.label}」is_enabled=False，前端看不到")

    node = db.query(Menu).filter(Menu.page_key == PAGE_KEY).all()
    if node:
        for n in node:
            say(OK, f"{PAGE_KEY} 节点存在 → id={n.id} parent_id={n.parent_id} sort={n.sort_order} "
                    f"is_enabled={n.is_enabled} is_builtin={n.is_builtin} label={n.label}")
    else:
        say(BAD, f"public.menus 里**没有** page_key='{PAGE_KEY}' 的节点（按 id 猜是没用的，id 会变）")
        problems.append("public.menus 缺 sales-units 节点")

    # sort_order 撞号检查：同父级下是否已有同号
    if group is not None:
        target_sort = None
        for parent_label, label, page_key, sort_order in specs:
            if parent_label == "销售管理" and page_key == PAGE_KEY:
                target_sort = sort_order
        if target_sort is not None:
            clash = db.query(Menu).filter(Menu.parent_id == group.id, Menu.sort_order == target_sort).all()
            clash = [c for c in clash if c.page_key != PAGE_KEY]
            if clash:
                names = ", ".join(f"{c.label}(id={c.id})" for c in clash)
                say(WARN, f"sort_order={target_sort} 已被同组节点占用: {names}（显示顺序可能插在中间）")
            else:
                say(OK, f"补进来的节点会拿到 sort_order={target_sort}，同组无撞号（排在组末）")


def check_db_roles(db) -> None:
    from app.models import Role, User

    users = db.query(User).all()
    print(f"        users: " + ", ".join(f"{u.username}(role={u.role})" for u in users[:8]))
    for u in users:
        if u.username != "admin":
            continue
        role = db.query(Role).filter(Role.code == u.role).first()
        if role is None:
            say(BAD, f"admin 的角色 code={u.role} 在 roles 表里不存在 → 会退回 ['overview']")
            problems.append("admin 角色丢失")
            return
        try:
            parsed = json.loads(role.permissions or "{}")
        except Exception:
            parsed = {}
        if parsed.get("all") is True:
            say(OK, f"admin → 角色「{role.name}」all=true ⇒ menus = all_menu_keys() 全集，"
                    "**不需要任何权限表授权行**")
        else:
            say(WARN, f"admin → 角色「{role.name}」all=false，menus={parsed.get('menus')}；"
                      "若不含 sales-units 就要么改回 all=true，要么把 key 加进该角色")
            if PAGE_KEY not in (parsed.get("menus") or []):
                problems.append(f"admin 的角色是 all=false 且不含 {PAGE_KEY}")

    # 非管理员角色：以**代码里的 BUILTIN_ROLES 为期望值**判断，而不是一律要求含 PAGE_KEY
    #（purchase/finance/staff 是**明确不给** sales-units 的，对它们报 WARN 只是刷屏）
    from app.models.role import BUILTIN_ROLES, _MANAGER_MENUS

    expected: dict[str, list[str]] = {}
    for spec in BUILTIN_ROLES:
        spec_perm = spec["permissions"]
        if spec_perm["all"]:  # type: ignore[index]
            continue
        expected[str(spec["code"])] = list(spec_perm["menus"])  # type: ignore[index]
    expected["manager"] = list(_MANAGER_MENUS)  # manager 是派生出来的，代码里没有手抄列表

    for role in db.query(Role).all():
        try:
            parsed = json.loads(role.permissions or "{}")
        except Exception:
            say(BAD, f"角色「{role.name}」的 permissions 不是合法 JSON，无法判断")
            continue
        if parsed.get("all"):
            continue
        menus = parsed.get("menus") or []
        wants = expected.get(role.code)
        if wants is None:
            say(OK, f"自定义角色「{role.name}」(code={role.code}) {len(menus)} 项（不受代码约束）")
            continue
        missing = [k for k in wants if k not in menus]
        extra = [k for k in menus if k not in wants]
        if not missing and not extra:
            say(OK, f"角色「{role.name}」(code={role.code}) 与代码定义一致（{len(menus)} 项）")
        else:
            say(WARN, f"角色「{role.name}」(code={role.code}) 与代码定义不一致："
                      f"缺 {missing or '无'} / 多 {extra or '无'}（历史快照或管理员手改）")


# ---------------------------------------------------------------------------
# 5. 后端在线校验
# ---------------------------------------------------------------------------
def _http(method: str, url: str, payload: dict | None = None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    # ⚠️ 本机设了 HTTP_PROXY，urllib 连 localhost 也会走代理 → 必须绕开
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_backend() -> None:
    base = "http://127.0.0.1:8010/api/v1"
    try:
        health = _http("GET", f"{base.replace('/api/v1', '')}/openapi.json")
    except Exception as exc:
        say(SKIP, f"后端 8010 未响应（{type(exc).__name__}）—— 跳过在线校验，先启动后端")
        warnings.append("后端未运行，/system/me/permissions 没能验证")
        return
    paths = health.get("paths", {})
    say(OK, f"后端在线，共 {len(paths)} 条路由")

    try:
        login = _http("POST", f"{base}/auth/login", {"username": "admin", "password": "Admin123"})
    except Exception as exc:
        say(WARN, f"登录失败（{exc}）—— 跳过权限校验")
        return
    token = login.get("access_token") or login.get("token") or login.get("accessToken")
    if not token:
        say(WARN, f"登录返回里没有 token 字段: {list(login)}")
        return

    try:
        perm = _http("GET", f"{base}/system/me/permissions", token=token)
    except Exception as exc:
        say(WARN, f"读 /system/me/permissions 失败: {exc}")
        return

    menus = perm.get("menus") or []
    tree = perm.get("menu_tree") or []
    say(OK if PAGE_KEY in menus else BAD,
        f"/me/permissions: all={perm.get('all')} menus={len(menus)} 项，"
        f"{'含' if PAGE_KEY in menus else '**不含**'} {PAGE_KEY}，default_page={perm.get('ui', {}).get('default_page')}")
    if PAGE_KEY not in menus:
        problems.append("后端下发的 menus 不含 sales-units（permissions.py 没生效或进程没重启）")

    sales = next((n for n in tree if n.get("label") == "销售管理"), None)
    if sales is None:
        say(BAD, "menu_tree 里没有「销售管理」分组")
    else:
        kids = [c.get("page_key") for c in sales.get("children", [])]
        say(OK if PAGE_KEY in kids else BAD,
            f"menu_tree「销售管理」子节点 {len(kids)} 个: {kids}")
        if PAGE_KEY not in kids:
            problems.append("后端下发的 menu_tree 里没有 sales-units（public.menus 没回填）")


# ---------------------------------------------------------------------------
# 6. dist 产物
# ---------------------------------------------------------------------------
def check_dist() -> None:
    assets = ROOT / "frontend" / "dist" / "assets"
    if not assets.is_dir():
        say(SKIP, "frontend/dist 不存在 —— 还没 build")
        return
    hits = []
    for js in sorted(assets.glob("*.js")):
        try:
            blob = js.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if PAGE_KEY in blob:
            hits.append(js.name)
    if hits:
        say(OK, f"dist 产物里含 {PAGE_KEY}: {', '.join(hits)}")
    else:
        say(BAD, f"dist 产物里**没有** {PAGE_KEY} —— 说明 build 时 App.jsx 还没接上它")
        problems.append("dist 不含 sales-units（需要改完 App.jsx 重新 build）")


# ---------------------------------------------------------------------------
# 修复
# ---------------------------------------------------------------------------
def fix_permissions_py() -> None:
    text = read_text(PERMISSIONS_PY)
    if f'"{PAGE_KEY}"' in text:
        say(OK, "permissions.py 无需改动")
        return
    anchor = '            {"key": "sales-statement", "label": "销售对账单"},'
    new_line = f'            {{"key": "{PAGE_KEY}", "label": "{LABEL}"}},'
    new_text = insert_after(text, anchor, new_line, "permissions.py 销售组末尾插入")
    bak = backup(PERMISSIONS_PY)
    write_text(PERMISSIONS_PY, new_text)
    say(OK, f"permissions.py 已打补丁（备份: {bak.name}）")
    print(f"        + {new_line.strip()}")


def fix_app_jsx() -> None:
    text = read_text(APP_JSX)
    original = text
    edits: list[str] = []

    if not re.search(r"^\s*import\s+\{\s*SalesOrderUnitsBoard\s*\}", text, re.M):
        text = insert_after(
            text,
            "import WarehousesPage from './pages/WarehousesPage';",
            "import { SalesOrderUnitsBoard } from './components/sales-units';",
            "App.jsx 顶部 import",
        )
        edits.append("① 顶部 import")

    if not re.search(r"key:\s*'sales-units'", text):
        text = insert_after(
            text,
            "      { key: 'sales-statement', label: '销售对账单' },",
            f"      {{ key: '{PAGE_KEY}', label: '{LABEL}' }},",
            "App.jsx menuGroups 销售组",
        )
        edits.append("② menuGroups 销售组")

    if not re.search(r"selectedTab\s*===\s*'sales-units'", text):
        text = insert_after(
            text,
            "{selectedTab === 'sales' && <SalesPage ctx={appCtx} />}",
            "            {selectedTab === 'sales-units' && (\n"
            "              <SalesOrderUnitsBoard\n"
            "                apiBase={API_BASE}\n"
            "                authHeaders={authHeaders}\n"
            "                onNotice={setNotice}\n"
            "                onError={setError}\n"
            "              />\n"
            "            )}",
            "App.jsx 分发区",
        )
        edits.append("③ 分发区")

    if text == original:
        say(OK, "App.jsx 无需改动")
        return
    bak = backup(APP_JSX)
    write_text(APP_JSX, text)
    say(OK, f"App.jsx 已打补丁（备份: {bak.name}）: {'、'.join(edits)}")


def fix_db_menus(db) -> None:
    """等价复刻 app/main.py 的 _backfill_builtin_menus（幂等、只补不改）。

    刻意照抄同一套判据：分组按 label 去重、菜单项按 (parent_id, page_key) 去重，
    并且只认 is_builtin=True 的叶子 —— 这样脚本和启动时的行为不会漂移。
    """
    from app.models import Menu, default_menu_specs

    specs = default_menu_specs()

    group_ids: dict[str, int] = {}
    for row in db.query(Menu).filter(Menu.page_key.is_(None)).all():
        group_ids.setdefault(row.label, row.id)

    existing_items: set[tuple[int, str]] = {
        (r.parent_id, r.page_key)
        for r in db.query(Menu).filter(Menu.page_key.isnot(None), Menu.is_builtin.is_(True)).all()
        if r.parent_id is not None
    }

    added = 0
    for parent_label, label, page_key, sort_order in specs:
        if parent_label is not None:
            continue
        if label in group_ids:
            continue
        row = Menu(label=label, page_key=None, sort_order=sort_order, is_builtin=True)
        db.add(row)
        db.flush()
        group_ids[label] = row.id
        added += 1
        say(OK, f"补入分组「{label}」id={row.id}")

    for parent_label, label, page_key, sort_order in specs:
        if parent_label is None:
            continue
        parent_id = group_ids.get(parent_label)
        if parent_id is None:
            continue
        if (parent_id, page_key) in existing_items:
            continue
        db.add(Menu(parent_id=parent_id, label=label, page_key=page_key,
                    sort_order=sort_order, is_builtin=True))
        added += 1
        say(OK, f"补入菜单项「{label}」page_key={page_key} sort={sort_order}")

    # 额外兜底：节点在但被禁用 → 启用（_backfill 不做这一步，但它是「看不到」的常见原因）
    disabled = db.query(Menu).filter(Menu.page_key == PAGE_KEY, Menu.is_enabled.is_(False)).all()
    for row in disabled:
        row.is_enabled = True
        added += 1
        say(OK, f"启用被禁用的节点「{row.label}」(id={row.id})")

    db.commit()
    if added == 0:
        say(OK, "菜单表无需回填")
    else:
        say(OK, f"菜单表回填完成，共 {added} 处改动")


def set_roles(db, grant: bool, codes: list[str] | None = None, menu_key: str | None = None) -> None:
    """把指定菜单 key 幂等地补进 / 摘出目标角色的 `permissions.menus`。

    默认 key 是 `sales-units`（本脚本的主角），可用 `--menu <key>` 换成任意菜单，
    例如 `--grant-roles --roles warehouse --menu stock-alert`。

    为什么不靠 `ensure_default_roles` 自动生效：它是**只补不覆盖**（保护管理员手改），
    库里已存在的角色记录永远不会被代码里的 BUILTIN_ROLES 刷新 —— 所以**代码与数据两处都要动**。
    这里只动 JSON 的 menus 数组：追加/移除一个 key，不碰 `all` 标记、不重排其它 key。
    """
    from app.models import Role

    key = menu_key or PAGE_KEY
    changed = 0
    for code in (codes or ROLE_CODES):
        role = db.query(Role).filter(Role.code == code).first()
        if role is None:
            say(WARN, f"角色 code={code} 不存在，跳过")
            continue
        try:
            parsed = json.loads(role.permissions or "{}")
        except Exception:
            say(BAD, f"角色「{role.name}」的 permissions 不是合法 JSON，跳过（不敢盲改）")
            continue
        if parsed.get("all"):
            say(OK, f"角色「{role.name}」all=true，天然含全部菜单，跳过")
            continue
        menus = list(parsed.get("menus") or [])
        has = key in menus
        if grant and has:
            say(OK, f"角色「{role.name}」已有 {key}，无需改动")
            continue
        if not grant and not has:
            say(OK, f"角色「{role.name}」本来就没有 {key}，无需改动")
            continue
        if grant:
            menus.append(key)
        else:
            menus = [m for m in menus if m != key]
        parsed["menus"] = menus
        role.permissions = json.dumps(parsed, ensure_ascii=False)
        changed += 1
        say(OK, f"角色「{role.name}」(code={code}) {'加入' if grant else '移除'} {key}"
                f" → 现 {len(menus)} 个菜单")
    db.commit()
    say(OK, f"角色权限改动 {changed} 处")


def align_manager(db) -> None:
    """把 manager 的 `permissions.menus` **差集补齐**到代码的 `_MANAGER_MENUS`（只加不减）。

    manager 的语义是"全部业务菜单，不含系统设置"，代码里由
    `_MANAGER_MENUS = all_menu_keys() - system_menu_keys()` **动态派生** ——
    以后新增业务菜单它自动跟着有。

    但 `ensure_default_roles` 是"只补不覆盖"，已存在的库永远停在**播种当时的快照**，
    于是后来新增的菜单（`stock-alert`、`general-ledger`、`sales-units` …）不会自动到手。
    这里做差集补齐：只 append 缺的，**绝不删除**管理员可能手工加过的项。
    """
    from app.models import Role
    from app.models.role import _MANAGER_MENUS

    role = db.query(Role).filter(Role.code == "manager").first()
    if role is None:
        say(WARN, "角色 code=manager 不存在，跳过")
        return
    try:
        parsed = json.loads(role.permissions or "{}")
    except Exception:
        say(BAD, "manager 的 permissions 不是合法 JSON，跳过（不敢盲改）")
        return
    if parsed.get("all"):
        say(OK, "manager all=true，天然含全部菜单，跳过")
        return

    menus = list(parsed.get("menus") or [])
    missing = [k for k in _MANAGER_MENUS if k not in menus]
    if not missing:
        say(OK, f"manager 已与代码派生列表一致（{len(menus)} 项），无需改动")
    else:
        menus.extend(missing)
        parsed["menus"] = menus
        role.permissions = json.dumps(parsed, ensure_ascii=False)
        db.commit()
        say(OK, f"manager 补齐 {len(missing)} 项：{', '.join(missing)} → 现 {len(menus)} 个菜单")

    extra = [k for k in menus if k not in _MANAGER_MENUS]
    if extra:
        say(WARN, f"manager 另有 {len(extra)} 项不在代码派生列表里（可能是管理员手工加的，已原样保留）："
                  f"{', '.join(extra)}")


# ---------------------------------------------------------------------------
def main() -> int:
    do_fix = "--fix" in sys.argv
    assume_yes = "--yes" in sys.argv or "-y" in sys.argv

    print(f"项目根: {ROOT}")
    print(f"数据库: {getattr(__import__('app.core.config', fromlist=['settings']).settings, 'database_url', '?').split('@')[-1]}")

    rule("1. 后端权限目录 app/core/permissions.py")
    check_permissions_py()

    rule("2. 前端挂载点 frontend/src/App.jsx")
    check_app_jsx()

    rule("3. 菜单表 public.menus")
    db = db_session()
    try:
        check_db_menus(db)

        rule("4. 角色权限 public.roles（admin 是否需要单独授权）")
        check_db_roles(db)
    finally:
        pass

    rule("5. 后端在线校验 /system/me/permissions")
    check_backend()

    rule("6. 前端构建产物 frontend/dist")
    check_dist()

    want_grant = "--grant-roles" in sys.argv
    want_revoke = "--revoke-roles" in sys.argv
    if want_grant or want_revoke:
        codes = ROLE_CODES
        if "--roles" in sys.argv:
            idx = sys.argv.index("--roles")
            if idx + 1 < len(sys.argv):
                codes = [c.strip() for c in sys.argv[idx + 1].split(",") if c.strip()]
        menu_key = PAGE_KEY
        if "--menu" in sys.argv:
            idx = sys.argv.index("--menu")
            if idx + 1 < len(sys.argv):
                menu_key = sys.argv[idx + 1].strip()
        rule(f"7. 角色权限{'补齐' if want_grant else '撤回'}：{menu_key} → {', '.join(codes)}")
        set_roles(db, want_grant, codes, menu_key)
        rule("角色权限复核")
        check_db_roles(db)

    if "--align-manager" in sys.argv:
        rule("8. 经营主管权限对齐（差集补齐到代码派生列表）")
        align_manager(db)
        rule("角色权限复核")
        check_db_roles(db)

    rule("结论")
    if not problems:
        say(OK, "六项全绿。若界面仍不显示，按 README §6 的五层排查走一遍（大概率是浏览器缓存）")
    else:
        say(BAD, f"发现 {len(problems)} 个问题：")
        for i, p in enumerate(problems, 1):
            print(f"        {i}. {p}")
    if warnings:
        print()
        for w in warnings:
            say(WARN, w)

    if not do_fix:
        if problems:
            print()
            print("要自动修复请重跑并加 --fix：")
            print("    .venv\\Scripts\\python.exe scripts\\fix_sales_units_menu.py --fix")
        try:
            db.close()
        except Exception:
            pass
        return 1 if problems else 0

    rule("开始修复")
    if not assume_yes:
        try:
            input("将修改 permissions.py、App.jsx 并回填菜单表（已自动备份），回车继续，Ctrl+C 取消…")
        except EOFError:
            pass

    # permissions.py 先改：DB 回填要用新的 PERMISSION_CATALOG，而它已在进程里被 import 过，
    # 所以必须**重新加载模块**，否则 default_menu_specs() 还是旧的 65 个。
    fix_permissions_py()
    fix_app_jsx()

    import importlib

    import app.core.permissions as perms_mod

    # ⚠️ 只 reload permissions —— **绝不能 reload app.models.menu**：
    #    Menu 是 SQLAlchemy declarative 类，重载会二次注册 "menus" 表，
    #    直接抛 InvalidRequestError: Table 'menus' is already defined。
    #    好在 default_menu_specs() 里是**函数内延迟 import** PERMISSION_CATALOG，
    #    所以 reload 完 permissions，它下次调用自动拿到新的 66 项。
    importlib.reload(perms_mod)
    say(OK, f"重新加载 permissions → all_menu_keys() = {len(perms_mod.all_menu_keys())} 项，"
            f"含 {PAGE_KEY}: {PAGE_KEY in perms_mod.all_menu_keys()}")

    try:
        fix_db_menus(db)
    except Exception as exc:
        say(BAD, f"回填失败: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass

    rule("修复后复核")
    db2 = db_session()
    try:
        check_db_menus(db2)
    finally:
        db2.close()

    rule("接下来必须做两步（顺序不能反）")
    print("  1) 重启后端 —— permissions.py 改了，而它是**启动时** import 的模块级常量，")
    print("     不重启的话 /me/permissions 仍然按旧的 54 项下发（无 --reload）。")
    print("     先确认没有旧进程残留:  taskkill /F /IM pythonw.exe  taskkill /F /IM python.exe")
    print("     再双击「启动ERP.bat」。")
    print("  2) cd frontend && npm run build   —— App.jsx 改了，dist 还是旧的。")
    print("  3) 浏览器 Ctrl+Shift+R（或者 DevTools → Application → Clear storage）。")
    print()
    print("  验收: 左侧「销售管理 → 销售出库（多单位）」，点进去后录入")
    print("        3 箱 × 180 = 540，同时最小单位侧显示 36 盒 × 15 = 540。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print()
        say(BAD, str(exc))
        sys.exit(2)
