#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `<div className="management-grid"> … </div>` 换成 `<ResizableLayout> … </ResizableLayout>`。

为什么必须用脚本、不能用编辑器全局替换
------------------------------------
`<ResizableLayout>` 需要**成对**替换：开标签换成新组件，它自己那个（可能隔了 200 行、
中间还套着七八层 div 的）闭合 `</div>` 也要换。随便搜 `</div>` 替换一定会把结构写坏，
而且坏法千奇百怪（多半是语法直接炸，好发现；少数是嵌套错位，更难查）。

本脚本按 **`<div` / `</div>` 配平**找到真正的那一个闭合标签，并做两道校验：
  ① 闭合行 `strip()` 必须正好是 `</div>`
  ② 闭合行的缩进必须与开标签一致
任一条不满足就报错退出、不写文件 —— 宁可让人来看一眼，也不猜。

⚠️ 自闭合 `<div … />` 不参与配平（按同行的 `/>` 认出来扣掉）。
   全仓只有 App.jsx:8181 一处，且不在任何 management-grid 块内；
   但漏掉它会让后续所有块的配平整体偏移，所以还是老实处理。

用法
----
    python scripts/wrap_resizable_layout.py            # 体检（只报告）
    python scripts/wrap_resizable_layout.py --apply    # 真写
    python scripts/wrap_resizable_layout.py --check    # 有未替换的就退出码 1

幂等：已经含 `ResizableLayout` 的文件直接跳过。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend", "src")
PAGES = os.path.join(SRC, "pages")

OPEN_TAG = '<div className="management-grid">'
PAGE_IMPORT = "import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';"
APP_IMPORT = "import ResizableLayout from './components/resizable-layout/ResizableLayout.jsx';"

RE_DIV_OPEN = re.compile(r"<div\b")
RE_DIV_SELF = re.compile(r"<div\b[^>]*?/>")
RE_DIV_CLOSE = re.compile(r"</div\s*>")
RE_SECTION = re.compile(r"<section\b")


class PatchError(RuntimeError):
    pass


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def find_close(lines: list[str], open_index: int) -> int:
    """返回与 open_index 这行的 <div 配平的那个 </div> 所在行号（0 基）。"""
    depth = 0
    started = False
    for j in range(open_index, len(lines)):
        line = lines[j]
        opens = len(RE_DIV_OPEN.findall(line)) - len(RE_DIV_SELF.findall(line))
        closes = len(RE_DIV_CLOSE.findall(line))
        depth += opens - closes
        if opens:
            started = True
        if started and depth <= 0:
            return j
    raise PatchError(f"从第 {open_index + 1} 行往后找不到配平的 </div>")


def count_sections(lines: list[str], open_index: int, close_index: int) -> int:
    """粗算直接子面板数（<section 出现在块内且不在更深的 div 里）。"""
    depth = 0
    started = False
    total = 0
    for j in range(open_index, close_index + 1):
        line = lines[j]
        if RE_SECTION.search(line) and started and depth == 1:
            total += 1
        opens = len(RE_DIV_OPEN.findall(line)) - len(RE_DIV_SELF.findall(line))
        closes = len(RE_DIV_CLOSE.findall(line))
        depth += opens - closes
        if opens:
            started = True
    return total


def process(path: str, import_line: str, apply: bool) -> tuple[int, int, list[str]]:
    """返回 (发现处数, 本次写入的处数, 报告行)。

    ⚠️ 干跑时"写入处数"恒为 0 —— 否则 `--check` 会永远返回 0（形同虚设）。
        这个坑上一轮在 patch_doc_forms 里踩过：`--apply` 报告成功不等于真落地。
    """
    text = read_text(path)
    if "management-grid" not in text:
        return 0, 0, []
    if "ResizableLayout" in text:
        return text.count(OPEN_TAG), 0, ["  已是 ResizableLayout，跳过"]

    lines = text.split("\n")
    targets = [i for i, line in enumerate(lines) if OPEN_TAG in line]
    if not targets:
        return 0, 0, []

    # ⚠️ 本仓文件有 CRLF 也有 LF。`split("\n")` 之后 CRLF 的每行尾巴上还留着 "\r"，
    #    改行时必须把它原样带上 —— 否则这两行会变成裸 LF，造出"整文件被改写"的假 diff。
    def split_eol(raw: str) -> tuple[str, str]:
        return (raw[:-1], "\r") if raw.endswith("\r") else (raw, "")

    report = []
    replaced = 0
    # 从后往前改，避免前面的行号位移影响后面的定位
    for open_index in reversed(targets):
        raw, eol = split_eol(lines[open_index])
        indent = raw[: len(raw) - len(raw.lstrip())]
        close_index = find_close(lines, open_index)
        close_raw = lines[close_index]
        if close_raw.strip() != "</div>":
            raise PatchError(
                f"{os.path.basename(path)}:{close_index + 1} 配平到的行不是单独的 </div>："
                f"{close_raw.strip()[:80]!r}"
            )
        close_body, close_eol = split_eol(close_raw)
        close_indent = close_body[: len(close_body) - len(close_body.lstrip())]
        if close_indent != indent:
            raise PatchError(
                f"{os.path.basename(path)}:{close_index + 1} 缩进({len(close_indent)}) "
                f"与开标签第 {open_index + 1} 行({len(indent)}) 不一致，疑似配平错位"
            )
        sections = count_sections(lines, open_index, close_index)
        report.append(
            f"  L{open_index + 1} → L{close_index + 1}  子面板 {sections}"
            + ("" if sections == 2 else "  （非 2 个子元素 → 组件自动降级为普通网格）")
        )
        lines[open_index] = f"{indent}<ResizableLayout>{eol}"
        lines[close_index] = f"{close_indent}</ResizableLayout>{close_eol}"
        replaced += 1

    # 补 import（放在第 1 行之后：页面是"自动提取"注释，App.jsx 是第一条 import）
    if replaced and import_line not in text:
        eol_marker = "\r" if "\r\n" in text else ""
        lines.insert(1, import_line + eol_marker)

    if apply and replaced:
        write_text(path, "\n".join(lines))
    return len(targets), (replaced if apply else 0), report


def main() -> int:
    parser = argparse.ArgumentParser(description="给 management-grid 套上 ResizableLayout")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    targets = [(p, PAGE_IMPORT) for p in sorted(glob.glob(os.path.join(PAGES, "*.jsx")))]
    targets.append((os.path.join(SRC, "App.jsx"), APP_IMPORT))

    print("=" * 78)
    print("management-grid → ResizableLayout · " + ("打补丁" if args.apply else "体检"))
    print("=" * 78)

    total_found = total_done = total_left = 0
    for path, import_line in targets:
        if not os.path.exists(path):
            continue
        try:
            found, done, report = process(path, import_line, args.apply)
        except PatchError as err:
            print(f"  ❌ {os.path.basename(path)}: {err}")
            total_left += 1
            continue
        if not found:
            continue
        total_found += found
        total_done += done
        total_left += found - done
        state = "已齐" if found == done else f"{found} 处待替换"
        print(f"  {os.path.basename(path):24s} {state}")
        for line in report:
            print(line)

    print("-" * 78)
    print(f"共发现 {total_found} 处，已替换 {total_done} 处，待替换 {total_left} 处")
    if args.apply:
        print("已写入。请重跑一次确认「已齐」，然后 npm run build")
        return 0
    return 0 if total_left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
