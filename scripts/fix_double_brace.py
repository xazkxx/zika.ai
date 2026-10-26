#!/usr/bin/env python3
# 一次性修复：上一版 extract_pages.py 的页面模板把 `}} = ctx;` 写成了双右花括号
# （模板结尾是普通字符串而非 f-string，导致 `}}` 被当作两个字面量 `}`）。
# 这里把所有 pages/*.jsx 里的 `}} = ctx;` 还原成合法的 `} = ctx;`。
# 用法：python scripts/fix_double_brace.py [--dry-run]
import os, sys, glob

PAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "pages")
PAGES_DIR = os.path.abspath(PAGES_DIR)
dry = "--dry-run" in sys.argv

bad = "}} = ctx;"
good = "} = ctx;"

total_files = 0
fixed_files = 0
total_repl = 0
for path in sorted(glob.glob(os.path.join(PAGES_DIR, "*.jsx"))):
    total_files += 1
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if bad in src:
        n = src.count(bad)
        total_repl += n
        fixed_files += 1
        if not dry:
            src = src.replace(bad, good)
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
        print(f"  [{'DRY' if dry else 'FIX'}] {os.path.basename(path)}: {n} 处")
    else:
        # 已经是正确的单花括号，跳过
        pass

print(f"\n扫描 {total_files} 个页面文件，需修复 {fixed_files} 个，共 {total_repl} 处 `}} = ctx;`。")
if dry:
    print("（dry-run，未写入）")
else:
    print("已修复完成。")
