"""前端构建标识 —— Python 侧和页面版本条读的是**同一份**数据。

页面上那行 `v52 · 2026-10-19 17:15 · 寨卡` 是 Vite 用 `define` 注入的编译期常量，
dist 里没有明文，Python 拿不到。所以 `vite.config.js` 在 build 结束时额外写一份
`frontend/dist/version.json`：

    开发态：<项目根>/frontend/dist/version.json
    打包态：<exe>/_internal/frontend/dist/version.json
            （erp.spec 的 datas 把 frontend/dist 整个打进去，这个文件跟着走）

这样"页面上写的版本"和"后端报的版本"永远一致，不会再出现
「用户说页面还是旧的，而后端坚持自己是最新的」这种对不上账的排查。

⚠️ 读不到就退回默认值，**绝不抛异常**：版本号读不到是小事，
   为此让后端起不来才是大事（这个教训来自 desktop_app 的静默崩溃）。
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

# 兜底值：键必须齐全，调用方拿 `info['cache']` 也不会 KeyError
_DEFAULT = {
    "app_version": "0.0.0",
    "cache": "v?",
    "build": "未构建",
    "build_at": "未构建",
    "brand": "",
    "commit": "nogit",
}


def version_json_path() -> Path:
    """version.json 的位置。打包后走 _MEIPASS，未打包走项目根。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "frontend" / "dist" / "version.json"
    return Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "version.json"


@lru_cache(maxsize=1)
def build_info() -> dict:
    """返回构建标识字典（只读，别改它）。"""
    info = dict(_DEFAULT)
    path = version_json_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return info
    if isinstance(raw, dict):
        for key in _DEFAULT:
            value = raw.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                info[key] = str(value)
    return info


def version_label() -> str:
    """拼成和页面一致的一段：`v52 · 2026-10-19 17:15 · 寨卡`。"""
    info = build_info()
    parts = [info["cache"], info["build_at"], info["brand"]]
    return " · ".join(part for part in parts if part)
