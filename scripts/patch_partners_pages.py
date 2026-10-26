#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
patch_partners_pages.py —— 把客户 / 供应商档案页压回「薄壳」

背景
----
`pages/CustomersPage.jsx` / `pages/SuppliersPage.jsx` 由
`scripts/extract_pages.py` **整文件生成**（各 1035 行，其中 940 行是 ctx 解构）。
第三步把整页 UI 搬进了 `components/partners/PartnersBoard.jsx`，
页面文件只需要「取 ctx 里那 6 个值 → 传给组件」。

本脚本做的事：**无论生成器写了什么，都把它压回薄壳**。
   · `--apply`  真写
   · 不带参数   只体检（报告当前是薄壳 / 是生成原文）
   · `--check`  有任一页不是薄壳就退出码 1（给构建前用）

设计说明
--------
· 目标内容完全确定 → 整体重写最稳，天然幂等（与 `patch_products_board.py` 同思路）。
· ⚠️ 薄壳里有 JS 模板字符串 `${row.id}`，所以下面**不能用** `.format()` /
  f-string 处理骨架文本，直接用普通字符串常量（`$` 与 `{}` 都是字面量）。
· ⚠️ `pages/*.jsx` 统一 CRLF（生成器这么写）。写入前把 LF 转成 CRLF，
  写完双核对 CRLF / 裸 LF 计数 —— 否则会造出「整文件被改写」的假 diff。

用法
----
    python scripts/patch_partners_pages.py --apply
    python scripts/patch_partners_pages.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "frontend" / "src" / "pages"

# --------------------------------------------------------------------------- 壳

_SHELL_HEAD = """// 自动提取自 App.jsx（selectedTab='{tab}'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/partners/PartnersBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文，需执行：
//        python scripts/patch_partners_pages.py --apply
//    把它压回下面这几行（脚本幂等，已压过则空操作）。
//
//   历史手工修改（内容已全部搬到 PartnersBoard）：
//     ① ResizableLayout 包裹 + 单面板整行（gridColumn: '1 / -1'）
//     ② 第三步：ErpCard × 2 + ErpTree 分组树 + ErpTable 声明式列
import PartnersBoard from '../components/partners/PartnersBoard.jsx';

export default function {component}({{ ctx }}) {{
  return (
    <PartnersBoard
      kind="{kind}"
      rows={{ctx.{rows}}}
      search={{ctx.{search}}}
      onSearch={{ctx.{set_search}}}
      focus={{ctx.archiveFocus}}
      onClearFocus={{() => ctx.setArchiveFocus(null)}}
      onAdd={{() => ctx.{set_modal}(true)}}
      onDelete={{(row) =>
        ctx.setConfirmDelete({{
          id: row.id,
          endpoint: {{`/{endpoint}/${{row.id}}`}},
          label: {{`{label} ${{row.name}}`}},
          kind: '{kind}',
        }})
      }}
    />
  );
}}
"""

SHELLS = {
    "CustomersPage.jsx": _SHELL_HEAD.format(
        tab="customers",
        component="CustomersPage",
        kind="customer",
        rows="customers",
        search="customerSearch",
        set_search="setCustomerSearch",
        set_modal="setCustomerModalOpen",
        endpoint="customers",
        label="客户",
    ),
    "SuppliersPage.jsx": _SHELL_HEAD.format(
        tab="suppliers",
        component="SuppliersPage",
        kind="supplier",
        rows="suppliers",
        search="supplierSearch",
        set_search="setSupplierSearch",
        set_modal="setSupplierModalOpen",
        endpoint="suppliers",
        label="供应商",
    ),
}

MARKER = "import PartnersBoard from '../components/partners/PartnersBoard.jsx';"


def read_text(path: Path) -> str:
    # ⚠️ Path.read_text() 在 Python 3.12 不接受 newline 参数（3.13 才有）
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def is_shell(text: str, component: str) -> bool:
    """判定是否已是薄壳：有 import，且恰好一个 export default function。"""
    return MARKER in text and text.count(f"export default function {component}") == 1


def main() -> int:
    parser = argparse.ArgumentParser(description="把客户/供应商档案页压回薄壳")
    parser.add_argument("--apply", action="store_true", help="真写文件")
    parser.add_argument("--check", action="store_true", help="有页面不是薄壳则退出码 1")
    args = parser.parse_args()

    problems = 0

    for filename, shell_lf in SHELLS.items():
        path = PAGES / filename
        component = filename.replace(".jsx", "")

        if not path.exists():
            print(f"❌ 找不到 {path}")
            problems += 1
            continue

        raw = read_text(path)
        crlf = raw.count("\r\n")
        lf_only = raw.count("\n") - crlf

        if is_shell(raw, component):
            print(f"✅ {filename} 已是薄壳（{len(raw)} 字符，CRLF {crlf} / 裸 LF {lf_only}）")
            continue

        lines = raw.count("\n") + (0 if raw.endswith("\n") else 1)
        print(f"ℹ️  {filename} 是生成原文：{len(raw)} 字符 / {lines} 行（CRLF {crlf} / 裸 LF {lf_only}）")

        if args.check:
            print("   ❌ 不是薄壳 → 先跑 --apply")
            problems += 1
            continue

        if not args.apply:
            print(f"   （干跑）加 --apply 才会写入。目标长度 {len(shell_lf)} 字符")
            continue

        target = shell_lf.replace("\n", "\r\n")
        write_text(path, target)

        after = read_text(path)
        after_crlf = after.count("\r\n")
        after_lf = after.count("\n") - after_crlf
        ok = is_shell(after, component) and after_lf == 0
        print(f"   {'✅' if ok else '❌'} 已写入：{len(after)} 字符，CRLF {after_crlf} / 裸 LF {after_lf}")
        if not ok:
            problems += 1

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
