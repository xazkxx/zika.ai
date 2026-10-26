#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
patch_products_board.py —— 把 pages/ProductsPage.jsx 压回「薄壳」

背景
----
`pages/ProductsPage.jsx` 由 `scripts/extract_pages.py` **整文件生成**，
重跑一次就会把整页 JSX 重新写回来（一千多行）。第二步示范重构把 UI
搬进了 `components/products/ProductsBoard.jsx`，页面文件只需要一行。

本脚本做的事只有一件：**无论生成器写了什么，都把它压回这一行**。
   · `--apply`  真写
   · 不带参数   只体检（报告当前是薄壳 / 是生成原文）
   · `--check`  不是薄壳就退出码 1（给 CI / 构建前用）

为什么整体重写而不是"替换某一段"
--------------------------------
生成器的输出可能随 App.jsx 变化（字段增删、缩进变化），按锚点切片很容易
在某个版本上切歪。目标内容是完全确定的，整体重写最稳，而且天然幂等。

用法
----
    python scripts/patch_products_board.py --apply
    python scripts/patch_products_board.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "frontend" / "src" / "pages" / "ProductsPage.jsx"

# 目标是确定内容：只保留 import 与一行渲染。
# ⚠️ 改这里等于改页面壳，改完记得同步本文件顶部的说明。
SHELL_LF = """// 自动提取自 App.jsx（selectedTab='products'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/products/ProductsBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文，需执行：
//        python scripts/patch_products_board.py --apply
//    把它压回下面这一行（脚本幂等，已压过则空操作）。
//
//   历史手工修改（内容已全部搬到 ProductsBoard）：
//     ① 分类树 <div className="category-tree">{renderCategoryNodes()}</div>
//     ② 产品列表首列「图片」缩略图
//     ③ 第二步示范重构：ErpCard × 2 + ErpTable + EmptyState
import ProductsBoard from '../components/products/ProductsBoard.jsx';

export default function ProductsPage({ ctx }) {
  return <ProductsBoard ctx={ctx} />;
}
"""

MARKER = "import ProductsBoard from '../components/products/ProductsBoard.jsx';"


def read_text(path: Path) -> str:
    # ⚠️ Path.read_text() 在 Python 3.12 不接受 newline 参数（3.13 才有）
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def is_shell(text: str) -> bool:
    """判定是否已经是薄壳：有 import、且只有一个 export default。"""
    return MARKER in text and text.count("export default function ProductsPage") == 1


def main() -> int:
    parser = argparse.ArgumentParser(description="把 ProductsPage.jsx 压回薄壳")
    parser.add_argument("--apply", action="store_true", help="真写文件")
    parser.add_argument("--check", action="store_true", help="不是薄壳则退出码 1")
    args = parser.parse_args()

    if not TARGET.exists():
        print(f"❌ 找不到 {TARGET}")
        return 1

    raw = read_text(TARGET)
    crlf = raw.count("\r\n")
    lf_only = raw.count("\n") - crlf

    if is_shell(raw):
        print(f"✅ 已经是薄壳（{len(raw)} 字符，CRLF {crlf} / 裸 LF {lf_only}）—— 无需改动")
        return 0

    lines = raw.count("\n") + (0 if raw.endswith("\n") else 1)
    print(f"ℹ️  当前是生成原文：{len(raw)} 字符 / {lines} 行（CRLF {crlf} / 裸 LF {lf_only}）")

    if args.check:
        print("❌ 不是薄壳 → 先跑 --apply")
        return 1

    if not args.apply:
        print("（干跑）加 --apply 才会写入。目标内容长度：%d 字符" % len(SHELL_LF))
        return 0

    # pages/*.jsx 统一是 CRLF（生成器这么写），这里跟着走，避免造出"整文件被改写"的假 diff
    target_text = SHELL_LF.replace("\n", "\r\n")
    write_text(TARGET, target_text)

    after = read_text(TARGET)
    after_crlf = after.count("\r\n")
    after_lf = after.count("\n") - after_crlf
    ok = is_shell(after) and after_lf == 0
    print(f"{'✅' if ok else '❌'} 已写入：{len(after)} 字符，CRLF {after_crlf} / 裸 LF {after_lf}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
