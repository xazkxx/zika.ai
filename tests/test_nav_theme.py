"""左侧树状导航「多风格配色」的回归测试。

背景：侧边栏配色被做成 CSS 变量 + `[data-nav-theme=...]` 属性切换，主题清单写在
`App.jsx` 的 `NAV_THEMES`，主题定义写在 `styles.css`。**这是两处纯数据，最容易
各改一半**：清单里加了一套、CSS 里忘了加 → 点那个圆点什么都不变，界面上
完全看不出报错（正是本项目反复出现的"静默故障"）。

所以这里钉三件事：
1. **清单与 CSS 一一对应** —— `NAV_THEMES` 的 key 去掉 `default`，必须与
   CSS 里 `[data-nav-theme='xxx']` 的 key 集合完全相等（多一个少一个都算失败）。
2. **每个主题块都得真有颜色** —— 光有个空块不算数，必须至少定义了 `--nav-bg`。
3. **默认主题不写属性** —— `default` 是"改造前原样"，靠 `.app-shell` 上的默认变量，
   不写 `data-nav-theme`，否则老用户的观感就不是零变化了。
"""

import re
from pathlib import Path

APP_JSX = Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
STYLES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "styles.css"


def _jsx() -> str:
    return APP_JSX.read_text(encoding="utf-8")


def _css() -> str:
    return STYLES.read_text(encoding="utf-8")


def _nav_theme_block() -> str:
    source = _jsx()
    start = source.index("const NAV_THEMES = [")
    end = source.index("\n];", start)
    return source[start:end]


def _js_theme_keys() -> set[str]:
    return set(re.findall(r"\{ key: '([a-z]+)', label:", _nav_theme_block()))


def _css_theme_keys() -> set[str]:
    return set(re.findall(r"\[data-nav-theme='([a-z]+)'\]", _css()))


def test_nav_theme_keys_match_between_jsx_and_css():
    """JSX 的主题清单与 CSS 的主题块必须一一对应（default 除外）。"""
    js_keys = _js_theme_keys() - {"default"}
    css_keys = _css_theme_keys()
    assert js_keys, "App.jsx 里没解析到 NAV_THEMES（是否改名/换写法了？）"
    assert js_keys == css_keys, (
        f"主题清单与样式不一致：仅 JSX 有 {sorted(js_keys - css_keys)}，"
        f"仅 CSS 有 {sorted(css_keys - js_keys)}"
    )


def test_every_theme_block_actually_defines_a_color():
    """每个主题块都要真的定义颜色，不能只是空块。"""
    css = _css()
    for key in _css_theme_keys():
        # 取该主题块的正文（到下一个主题块或样式规则收尾）
        start = css.index(f"[data-nav-theme='{key}']")
        rest = css[start:]
        nxt = re.search(r"\[data-nav-theme='", rest[1:])
        chunk = rest[: nxt.start() + 1] if nxt else rest
        assert "--nav-bg" in chunk, f"主题 {key} 没有定义 --nav-bg，等于没换色"


def test_default_theme_writes_no_attribute():
    """默认主题不写 data-nav-theme —— 保持与改造前完全一致的观感。"""
    source = _jsx()
    assert "data-nav-theme={navTheme === 'default' ? undefined : navTheme}" in source, (
        "默认主题应该不写 data-nav-theme 属性"
    )


def test_theme_picker_is_rendered():
    """切换器 UI 存在，且绑定了选择事件。"""
    source = _jsx()
    assert "nav-theme-picker" in source, "侧边栏里没有主题切换器"
    assert "chooseNavTheme" in source, "主题切换没有绑定选择处理"
