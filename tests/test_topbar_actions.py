"""第 9 批：顶栏操作「按页面驱动」的回归测试。

这一批修的是一个**全站级的观感缺陷**：顶栏曾把「新建报价 / 新增订单」
两个按钮**硬编码**在模板里，于是客户档案、现金银行、报表中心、操作日志……
全部约 50 个页面的右上角都挂着同一对与当前页无关的按钮。

改成按菜单 key 查 `pageActions` 表之后，有三件事必须钉住，否则会悄悄退化：

1. **硬编码不许回来** —— 直接对 `<header className="topbar">...</header>` 这一段
   断言里面不再出现那两个按钮文字。有人图省事再塞一对全局按钮就会被挡住。
2. **配置的 key 必须真实存在** —— `pageActions` 的键与 `to` 目标都得在 `menuGroups`
   里找得到。写错一个字母的后果是"按钮点了跳到一个空白页"，界面上完全看不出报错。
3. **样式口径统一** —— 主/次按钮的 padding 不许再分叉（此前主按钮不带 `small-btn`、
   次按钮带，并排放着明显不齐）。
"""

import re
from pathlib import Path

APP_JSX = Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
STYLES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "styles.css"


def _source() -> str:
    return APP_JSX.read_text(encoding="utf-8")


def _menu_block(source: str) -> str:
    start = source.index("const menuGroups = [")
    end = source.index("\n];", start)
    return source[start:end]


def _actions_block(source: str) -> str:
    start = source.index("const pageActions = {")
    # 顶层以「行首的 };」收尾
    end = source.index("\n};", start)
    return source[start:end]


def _menu_keys(source: str) -> set[str]:
    return set(re.findall(r"\{ key: '([a-z0-9-]+)', label:", _menu_block(source)))


def _action_entries(source: str) -> list[tuple[str, str, str]]:
    """解出 [(页面key, 目标key, variant), ...]。"""
    block = _actions_block(source)
    entries: list[tuple[str, str, str]] = []
    # 形如：  key: [ ... ]  或  'key': [ ... ]
    for match in re.finditer(r"^\s{2}'?([a-z0-9-]+)'?:\s*\[", block, re.MULTILINE):
        page = match.group(1)
        # 取该条目到下一个条目（或块尾）之间的片段
        rest = block[match.end():]
        nxt = re.search(r"^\s{2}'?[a-z0-9-]+'?:\s*\[", rest, re.MULTILINE)
        chunk = rest[: nxt.start()] if nxt else rest
        for one in re.finditer(
            r"\{ label: '([^']+)', to: '([a-z0-9-]+)', variant: '([a-z]+)' \}", chunk
        ):
            entries.append((page, one.group(2), one.group(3)))
    return entries


def test_topbar_has_no_hardcoded_global_buttons():
    """顶栏里不许再有写死的全局按钮。"""
    source = _source()
    start = source.index('<header className="topbar">')
    end = source.index("</header>", start)
    header = source[start:end]

    assert "currentActions" in header, "顶栏没有用 currentActions 驱动操作区"
    # 先剥掉注释再判断：注释里提到这些字样是说明文字，不是真的按钮文字节点。
    without_comments = re.sub(r"\{/\*.*?\*/\}", "", header, flags=re.DOTALL)
    for label in ("新建报价", "新增订单"):
        assert label not in without_comments, (
            f"顶栏又出现了硬编码按钮「{label}」—— 它会给全部页面都挂上无关按钮，"
            "请改到 pageActions 表里按页面配置"
        )


def test_page_actions_reference_real_pages():
    """pageActions 的键与跳转目标都必须是真的菜单项（写错就是"点了跳空白页"）。"""
    source = _source()
    keys = _menu_keys(source)
    entries = _action_entries(source)

    assert entries, "没能从 App.jsx 解出任何顶栏操作，正则需要跟着代码结构更新"

    used_pages = {page for page, _, _ in entries}
    missing_pages = sorted(used_pages - keys)
    assert not missing_pages, f"pageActions 里配了不存在的页面 key：{missing_pages}"

    targets = {to for _, to, _ in entries}
    missing_targets = sorted(targets - keys)
    assert not missing_targets, f"pageActions 里配了不存在的跳转目标：{missing_targets}"


def test_page_actions_shape_is_sane():
    """variant 只能是 primary / secondary，且单页操作不超过两个。"""
    source = _source()
    entries = _action_entries(source)

    for _, _, variant in entries:
        assert variant in ("primary", "secondary"), f"variant 取值非法：{variant}"

    per_page: dict[str, int] = {}
    for page, _, _ in entries:
        per_page[page] = per_page.get(page, 0) + 1
    too_many = {page: n for page, n in per_page.items() if n > 2}
    assert not too_many, f"单个页面的顶栏操作超过 2 个会显得杂乱：{too_many}"

    # 每页最多一个主操作（实心按钮），否则用户不知道哪个是主要动作
    heavy = {}
    for page, _, variant in entries:
        if variant == "primary":
            heavy[page] = heavy.get(page, 0) + 1
    dup = {page: n for page, n in heavy.items() if n > 1}
    assert not dup, f"同一页面出现了多个主操作：{dup}"


def test_documents_pages_have_their_own_actions_and_others_do_not():
    """两个具体断言：图六那两颗按钮该落在开单页；系统设置类页面一个入口都不配。"""
    source = _source()
    per_page: dict[str, list[str]] = {}
    for page, to, _ in _action_entries(source):
        per_page.setdefault(page, []).append(to)

    # 参考图里的「新建报价 / 新增订单」本来就属于开单管理，这里必须在
    assert set(per_page.get("sales", [])) == {"quotation", "sales-order"}, (
        "开单管理页的顶栏操作应正好是「新建报价 → quotation」与「新增订单 → sales-order」"
    )

    # 系统设置类页面**一个都不配**：侧边栏本来就能到，放到右上角只是重复，
    # 等于把"全站挂同一对按钮"的老毛病换个形式再犯一遍。
    system_pages = ("users", "settings", "params", "dictionaries", "print-templates", "logs")
    leaked = {page: per_page[page] for page in system_pages if page in per_page}
    assert not leaked, (
        f"系统设置类页面不该有顶栏操作（它们只是「能跳到哪」，不是「这个页面的下一步」）：{leaked}"
    )


def test_topbar_primary_and_secondary_buttons_share_padding():
    """主/次按钮在顶栏里必须同高：样式表要有统一的覆盖规则。"""
    css = STYLES.read_text(encoding="utf-8")
    assert ".topbar-actions .primary-btn" in css and ".topbar-actions .secondary-btn" in css, (
        "styles.css 缺少顶栏主/次按钮的统一 padding 规则（否则两个按钮高度不一致）"
    )
