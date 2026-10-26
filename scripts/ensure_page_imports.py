#!/usr/bin/env python3
# 补齐前端拆分后缺失的页面 import：
# extract_pages.py 把内联 JSX 块替换为 `<XxxPage ctx={appCtx} />` 引用，
# 但遗漏了在 App.jsx 顶部写 `import XxxPage from './pages/XxxPage';`。
# 没有这行，所有页面组件都是 undefined，运行时每个 tab 都会崩。
#
# 本脚本：扫描 App.jsx 里所有 `<XxxPage ctx={appCtx} />` 引用，
# 为每个引用生成 import 并插入到 App.jsx 顶部「最后一个 import 语句」之后。
# 幂等：已存在的导入不会重复添加。
#
# 用法：python scripts/ensure_page_imports.py [--dry-run]
import os, re, sys

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "src"))
APP = os.path.join(SRC_DIR, "App.jsx")
PAGES_DIR = os.path.join(SRC_DIR, "pages")
dry = "--dry-run" in sys.argv

# 1) 收集 App.jsx 里所有 `<XxxPage ctx={appCtx} />` 形式的引用名
with open(APP, "r", encoding="utf-8") as f:
    app_src = f.read()
ref_names = set(re.findall(r"<(\w+)\s+ctx=\{appCtx\}", app_src))
# 过滤掉明显不是页面的（理论上都是 Page）
ref_names = {n for n in ref_names if n.endswith("Page")}
print(f"App.jsx 中引用的页面组件数: {len(ref_names)}")

# 2) 校验每个引用都有对应文件
missing = []
for name in sorted(ref_names):
    if not os.path.exists(os.path.join(PAGES_DIR, f"{name}.jsx")):
        missing.append(name)
if missing:
    print(f"⚠️ 以下引用在 pages/ 找不到对应文件: {missing}")

# 3) 构造 import 行
import_lines = [f"import {name} from './pages/{name}';" for name in sorted(ref_names)]
import_block = "\n".join(import_lines)

# 4) 幂等插入：若已存在 `from './pages/` 则跳过对应行
existing = set(re.findall(r"import\s+(\w+)\s+from\s+'\./pages/(\w+)'", app_src))
# existing: set of (binding, module) — 我们只要 module 名
existing_mods = {m for (_, m) in existing}
to_add = [ln for ln in import_lines if ln.split("'")[1].split("/")[-1] not in existing_mods]
print(f"已有页面导入: {len(existing_mods)}，待新增: {len(to_add)}")

if not to_add:
    print("✅ 所有页面 import 已就位，无需改动。")
    sys.exit(0)

app_lines = app_src.split("\n")
# 找到最后一个 `^import ` 行号
last_import_idx = -1
for i, ln in enumerate(app_lines):
    if re.match(r"^\s*import\s", ln):
        last_import_idx = i
if last_import_idx < 0:
    # 没有 import？插到最前面
    last_import_idx = -1

new_block = "\n".join(to_add)
if dry:
    print(f"\n[DRY] 将在第 {last_import_idx+1} 行后插入:\n{new_block}")
    sys.exit(0)

# 插入（在最后一个 import 行之后）
insert_at = last_import_idx + 1
app_lines.insert(insert_at, new_block)
with open(APP, "w", encoding="utf-8") as f:
    f.write("\n".join(app_lines))

print(f"✅ 已插入 {len(to_add)} 条页面 import（共 {len(import_lines)} 条，跳过已存在的）。")
print(f"插入位置：App.jsx 第 {insert_at} 行之后。")
