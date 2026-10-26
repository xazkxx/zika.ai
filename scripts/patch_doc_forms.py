#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「单据表单」的手工补丁重新打到 extract_pages.py 生成的页面文件上。

背景
----
`scripts/extract_pages.py` 每次重跑，都会用 App.jsx 里的 JSX **整块覆盖**
`frontend/src/pages/*.jsx`。而 2026-10-17 这几轮做的改动，是直接改在生成物上的：

  ① `import { itemRowError } from '../lib/orderLines';`（半填红字用）
  ② `<form ... data-doc-form="…">` —— 单据表单的作用域锚点，CSS 全靠它
  ③ 明细行尾部 `<p className="line-invalid" role="alert">{…}</p>` —— 半填红字
  ④ `ctx` 解构里的 `unitOptionsFor` —— 单位下拉的选项来源
  ⑤ 数量后面的「单位」`<select>` —— 按箱/盒录入，payload 带 unit
  ⑥ 商品选择 `<select>` → `<SearchSelect>`（2026-10-17 第三批），含它的 import

重跑生成器之后这几处会**静默消失**：表单样式退回旧版、红字校验不再出现、
单位下拉整列不见，但 `npm run build` 照样成功、页面也不报错 —— 只能靠肉眼发现。
所以必须能用一条命令把它们重新打上。

用法
----
    python scripts/patch_doc_forms.py            # 体检（默认只报告，不改文件）
    python scripts/patch_doc_forms.py --apply    # 打补丁
    python scripts/patch_doc_forms.py --check     # 有缺失就退出码 1（可挂 CI / 构建前）

设计约束
--------
* **幂等**：已经打过的不会重复打，连跑两次第二遍是「全部补丁在位」。
* **不猜**：找不到插入锚点就报错退出，绝不"大概插在这儿"。生成物结构变了，
  宁可让人来看一眼，也不要写出一份能构建但布局错乱的 JSX。
* **跟随换行符**：这几个页面是 CRLF，写入的每一行也必须是 CRLF；用
  `open(..., newline='')` 读写，避免 Python 把 `\\n` 翻成 `\\r\\n` 造出整文件假 diff。
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = os.path.join(ROOT, "frontend", "src", "pages")

IMPORT_LINE = "import { itemRowError } from '../lib/orderLines';"

# 商品搜索下拉的 import（2026-10-17 第三批）。相对路径是 `../components/...`，
# 因为页面文件都在 `src/pages/` 下。
SEARCH_IMPORT_LINE = "import SearchSelect from '../components/search-select/SearchSelect.jsx';"

# 明细行里的红字 <p>：24 空格缩进，正好落在 .form-row 内部（CSS grid-column:1/-1 横跨整行）
ROW_MARKUP = (
    "                        {/* 半填行红字：空行时内容为空串，CSS 用 :empty 直接隐藏 */}\n"
    "                        <p className=\"line-invalid\" role=\"alert\">{itemRowError(row, index)}</p>"
)

# 单位下拉：插在「数量」那个 </label> 之后、「单价」之前
# ⚠️ 这里的 JSX 花括号是**单层**的：本模板只做 `__HANDLER__` 的 str.replace，
#    不走 str.format —— 写成双花括号会原样落进 JSX，把 `{row.unit}` 变成 `{{…}}`
#    对象字面量（构建直接炸）。踩过一次，别再"顺手"写成 {{ }}。
UNIT_SELECT = """                        <label>
                          单位
                          <select
                            value={row.unit || unitOptionsFor(row.product_id)[0]?.name || ''}
                            onChange={__HANDLER__(index, 'unit')}
                            disabled={!row.product_id}
                          >
                            {unitOptionsFor(row.product_id).length === 0 && (
                              <option value="">{row.product_id ? '该商品未设单位' : '先选商品'}</option>
                            )}
                            {unitOptionsFor(row.product_id).map((option) => (
                              <option key={option.name} value={option.name}>{option.name}</option>
                            ))}
                          </select>
                        </label>
"""

# 商品选择：原生 <select> → SearchSelect
#
# 为什么必须替换：`products` 现在 261 条，原生下拉要一路滚；用户明确要求
# 按「商品名称 / SKU / 助记码」模糊检索。SearchSelect 全程本地 filter，不发请求。
#
# ⚠️ 两个坑：
#   ① `value` 要 `String(row.product_id ?? '')` —— SearchSelect 内部按字符串比 key，
#      传 null/undefined 会让"已选中"判定失效（下拉里看不出当前选了谁）。
#   ② 这里**不加 `allowClear={false}`**：明细行清空商品正是要走 onChange('')，
#      让上层的 makeOrderItemHandler 顺手把 unit/unit_price 复位。
#   ③ 花括号同样是单层 —— 理由见上面 UNIT_SELECT 的注释。
PRODUCT_SELECT_OLD = """                          <select value={row.product_id} onChange={__HANDLER__(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>"""

PRODUCT_SELECT_NEW = """                          <SearchSelect
                            options={products}
                            value={String(row.product_id ?? '')}
                            onChange={__HANDLER__(index, 'product_id')}
                            placeholder="搜索商品名称 / SKU / 助记码"
                          />"""

# 剩余单据页各一行「指令」。
#
# ⚠️ 2026-10-17 第三步-B 全部四家洗完，本表**已清空**（保留结构以便将来新增单据页）：
#    · PurchasePage.jsx      → components/docs/PurchaseInboundBoard.jsx（第一家）
#    · SalesPage.jsx         → components/docs/SalesOutboundBoard.jsx（第二家）
#    · PurchaseOrderPage.jsx ┐
#    · SalesOrderPage.jsx    ┘ → components/docs/OrderBoard.jsx（第三、四家，CONFIG 收口）
#    四页都只剩一行转发，`data-doc-form`、SearchSelect、单位下拉、半填红字全部搬进了组件。
#    再往表里留任何一条，`--check` 都会永久报"缺 6 处"，`--apply` 还会去改薄壳。
#
#    清空之后靠下面 `scan_legacy_pages()` 兜底：只要 `pages/*.jsx` 里又出现
#    `data-doc-form="`，说明有页面被重新生成回了老结构（或有人把 JSX 搬回了 App.jsx），
#    `--check` 立刻变红 —— 空表不等于放行。
SPECS = []

# 只有 import、没有表单结构的生成页（同样会被 extract_pages.py 整块覆盖）
IMPORT_ONLY = []

# 生成物里固定存在的结构锚点（用于定位，不参与改写）
SUMMARY_ANCHOR = '                    <div className="order-items-summary">'
ROW_CLOSE_ANCHOR = "                      </div>"
CTX_TAIL_ANCHOR = "    warehouses"
GENERATED_HEADER = "// 自动提取自 App.jsx"


class PatchError(RuntimeError):
    pass


def eol_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def with_eol(block: str, eol: str) -> str:
    return block.replace("\r\n", "\n").replace("\n", eol)


def patch_import(text: str, eol: str, line: str = IMPORT_LINE) -> tuple[str, str]:
    """① 补 import（放在生成器那行注释下面，保持文件开头结构不变）。"""
    if line in text:
        return text, ""
    pos = text.find(GENERATED_HEADER)
    if pos == -1:
        raise PatchError("文件开头没有 `// 自动提取自 App.jsx` 注释，无法确定插入位置")
    line_end = text.find(eol, pos)
    if line_end == -1:
        raise PatchError("生成器注释所在行没有换行符，文件结构异常")
    insert_at = line_end + len(eol)
    return text[:insert_at] + line + eol + text[insert_at:], "补 import"


def patch_doc_form(text: str, spec: dict, eol: str) -> tuple[str, str]:
    """② 给 <form> 挂 data-doc-form 属性。"""
    attr = f'data-doc-form="{spec["doc_form"]}"'
    if attr in text:
        return text, ""
    needle = f'<form onSubmit={{{spec["submit"]}}} className="erp-form"'
    count = text.count(needle)
    if count != 1:
        raise PatchError(
            f'`<form onSubmit={{{spec["submit"]}}} className="erp-form"` 命中 {count} 次（应为 1 次）'
        )
    return text.replace(needle, f"{needle} {attr}", 1), "补 data-doc-form"


def patch_row_markup(text: str, eol: str) -> tuple[str, str]:
    """③ 在明细行 div 的收尾 </div> 之前插入红字 <p>。"""
    if 'className="line-invalid"' in text:
        return text, ""
    summary_at = text.find(SUMMARY_ANCHOR)
    if summary_at == -1:
        raise PatchError("找不到 `<div className=\"order-items-summary\">`，无法定位明细行区间")
    row_close_at = text.rfind(ROW_CLOSE_ANCHOR, 0, summary_at)
    if row_close_at == -1:
        raise PatchError("合计行之前找不到明细行的收尾 `</div>`")
    block = with_eol(ROW_MARKUP, eol) + eol
    return text[:row_close_at] + block + text[row_close_at:], "补红字 <p>"


def patch_ctx_unit(text: str, eol: str) -> tuple[str, str]:
    """④ 在 `} = ctx;` 之前补 unitOptionsFor 解构。

    ⚠️ 判"已打过"必须看**解构区**（`unitOptionsFor` 紧跟 `} = ctx;`），
    不能全文找 `unitOptionsFor` —— 单位下拉的 JSX 里也有这个词，
    全文判定会让"解构丢了但 select 还在"的文件假绿（那样页面必然崩）。
    """
    if f"    unitOptionsFor{eol}  }} = ctx;" in text:
        return text, ""
    anchor = f"{CTX_TAIL_ANCHOR}{eol}  }} = ctx;"
    if anchor not in text:
        raise PatchError("找不到 `warehouses` + `} = ctx;` 的结尾，ctx 解构结构可能变了")
    replacement = (
        f"{CTX_TAIL_ANCHOR},{eol}"
        f"    // 明细行「单位」下拉的选项（基础单位恒在，辅助单位异步补齐）{eol}"
        f"    unitOptionsFor{eol}  }} = ctx;"
    )
    return text.replace(anchor, replacement, 1), "补 unitOptionsFor 解构"


def patch_unit_select(text: str, spec: dict, eol: str) -> tuple[str, str]:
    """⑤ 在「数量」之后插入「单位」下拉。"""
    if "unitOptionsFor(row.product_id)" in text:
        return text, ""
    anchor = f"value={{row.quantity}} onChange={{{spec['handler']}(index, 'quantity')}} />"
    pos = text.find(anchor)
    if pos == -1:
        raise PatchError(f"找不到数量输入框（handler={spec['handler']}），无法定位插入点")
    close = text.find("</label>", pos)
    if close == -1:
        raise PatchError("数量输入框之后找不到 `</label>`")
    line_end = text.find(eol, close)
    if line_end == -1:
        raise PatchError("`</label>` 之后没有换行符，文件结构异常")
    insert_at = line_end + len(eol)
    block = with_eol(UNIT_SELECT.replace("__HANDLER__", spec["handler"]), eol)
    return text[:insert_at] + block + text[insert_at:], "补单位下拉"


def patch_product_search(text: str, spec: dict, eol: str) -> tuple[str, str]:
    """⑥ 把明细行的商品 `<select>` 换成 `<SearchSelect>`。

    ⚠️ 判定"已打过"用 `options={products}` —— 旧结构里这个词**不可能**出现
    （旧结构是 `{products.map(...)}`），所以不会像 `unitOptionsFor` 那样
    既在解构又在 JSX 里、全文搜就假绿。
    """
    if "options={products}" in text:
        return text, ""
    old = with_eol(PRODUCT_SELECT_OLD.replace("__HANDLER__", spec["handler"]), eol)
    count = text.count(old)
    if count != 1:
        raise PatchError(
            f"商品下拉锚点命中 {count} 次（应为 1 次）；handler={spec['handler']}，"
            "生成物结构可能变了"
        )
    new = with_eol(PRODUCT_SELECT_NEW.replace("__HANDLER__", spec["handler"]), eol)
    return text.replace(old, new, 1), "商品改 SearchSelect"


def strip_comment_lines(text: str) -> str:
    """丢掉整行注释（`//`、`*`、`/*` 开头）。

    只处理**整行**注释：真实 JSX 里那行 `<form …>` 绝不会以 `//` 开头，
    所以这个粗粒度剥法对我们要找的结构是安全的，也不需要引入真正 JS 词法器。
    """
    kept = []
    for line in text.splitlines():
        head = line.strip()
        if head.startswith("//") or head.startswith("*") or head.startswith("/*"):
            continue
        kept.append(line)
    return "\n".join(kept)


def scan_legacy_pages() -> list[tuple[str, str]]:
    """扫 `pages/*.jsx`，找出还带 `data-doc-form="` 的页面。

    SPECS 清空后这是**唯一还会变红的东西**，作用是防止"假绿"：
      · 有人把整页 JSX 搬回 App.jsx → 重跑 extract_pages.py → 老结构又出现；
      · 或者手动从备份还原了旧页面。
    这两种情况下补丁脚本无事可做（它只会往老结构里打补丁），但必须有人知道
    "这页已经退回重构前了"，所以直接报出来。
    """
    hits = []
    # ⚠️ 两步都必要：
    #    ① 先**丢掉整行注释** —— 薄壳的注释里为了解释"为什么不需要补丁"，会原样写出
    #       `<form data-doc-form="inbound">` 这种示例（PurchasePage.jsx:14 就是），
    #       只搜结构也会假红；
    #    ② 再锚定真正的 JSX 结构 `<form … data-doc-form="…">`，而不是裸字符串 ——
    #       四个薄壳的注释里都出现过这个词。第一次实测正是被 ① 咬了一口。
    pattern = re.compile(r"<form[^>]*data-doc-form=\"([^\"]+)\"", re.S)
    for path in sorted(glob.glob(os.path.join(PAGES_DIR, "*.jsx"))):
        text = strip_comment_lines(read_text(path))
        m = pattern.search(text)
        if m:
            hits.append((os.path.basename(path), m.group(1)))
    return hits


def run(apply: bool) -> int:
    rows = []
    missing_total = 0
    changed_total = 0

    for spec in SPECS:
        path = os.path.join(PAGES_DIR, spec["file"])
        if not os.path.exists(path):
            rows.append((spec["file"], ["文件不存在"], 0))
            missing_total += 1
            continue

        original = read_text(path)
        eol = eol_of(original)
        text = original
        done, missing = [], []

        steps = (
            ("import", lambda t: patch_import(t, eol)),
            ("import-search", lambda t: patch_import(t, eol, SEARCH_IMPORT_LINE)),
            ("data-doc-form", lambda t: patch_doc_form(t, spec, eol)),
            ("line-invalid", lambda t: patch_row_markup(t, eol)),
            ("ctx-unit", lambda t: patch_ctx_unit(t, eol)),
            ("unit-select", lambda t: patch_unit_select(t, spec, eol)),
            ("product-search", lambda t: patch_product_search(t, spec, eol)),
        )
        for label, fn in steps:
            try:
                text, action = fn(text)
            except PatchError as err:
                missing.append(f"{label}: {err}")
                continue
            if action:
                missing.append(f"{label}: 缺失——{action}")
            else:
                done.append(label)

        missing_total += len(missing)
        if apply and text != original:
            write_text(path, text)
            changed_total += 1
        rows.append((spec["file"], missing, 1 if text != original else 0))

    # 只有 import 的生成页
    for spec in IMPORT_ONLY:
        path = os.path.join(PAGES_DIR, spec["file"])
        if not os.path.exists(path):
            rows.append((spec["file"], ["文件不存在"], 0))
            missing_total += 1
            continue
        original = read_text(path)
        eol = eol_of(original)
        try:
            text, action = patch_import(original, eol, spec["import"])
        except PatchError as err:
            rows.append((spec["file"], [f"import: {err}"], 0))
            missing_total += 1
            continue
        missing = [f"import: 缺失——{action}"] if action else []
        missing_total += len(missing)
        if apply and text != original:
            write_text(path, text)
            changed_total += 1
        rows.append((spec["file"], missing, 1 if text != original else 0))

    print("=" * 78)
    print("单据表单手工补丁 · " + ("打补丁" if apply else "体检"))
    print("=" * 78)
    for name, missing, touched in rows:
        state = "已齐" if not missing else f"缺 {len(missing)} 处"
        flag = "（本次已写入）" if (apply and touched) else ""
        print(f"  {name:24s} {state}{flag}")
        for item in missing:
            print(f"      - {item}")

    print("-" * 78)

    # ——— 反向守卫：SPECS 清空后，这是唯一还会变红的检查 ———
    legacy = scan_legacy_pages()
    if legacy:
        print("⚠️ 发现仍带 data-doc-form 的页面（已退回重构前的老结构）：")
        for name, value in legacy:
            print(f"  {name:24s} data-doc-form=\"{value}\"")
        print("   若是有意搬回 App.jsx，请把该页重新登记进上面的 SPECS；")
        print("   若是误还原，从 _ui_kit_step3/_backup/ 取回薄壳版本。")
        print("   （这类问题**不能**用 --apply 修，必须人工决定走哪条路。）")
        return 1

    if missing_total == 0:
        print("✅ 全部补丁在位" + ("（SPECS 已清空：四个单据页均为薄壳）" if not SPECS else ""))
        return 0
    if apply:
        print(f"已写入 {changed_total} 个文件；请重跑本脚本确认「已齐」")
        return 0
    print(f"共缺 {missing_total} 处。执行 `python scripts/patch_doc_forms.py --apply` 补上")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="给 extract_pages.py 生成的单据页补回手工改动")
    parser.add_argument("--apply", action="store_true", help="真的写入文件")
    parser.add_argument("--check", action="store_true", help="有缺失就返回退出码 1")
    args = parser.parse_args()
    return run(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
