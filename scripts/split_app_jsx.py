#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端拆分脚本（Phase 0）：把 App.jsx 模块级「纯代码」外提到 src/lib/appLib.js。

安全约束（与后端 pytest 契约一致）：
- `menuGroups` 与 `pageActions` 两个常量 MUST 留在 App.jsx（test_system_config.py /
  test_topbar_actions.py 用正则逐行 grep App.jsx 校验它们与后端权限点一致）。
- App.jsx 头部 7 行 import + pdfjs worker 副作用 MUST 留在 App.jsx。
- 被移动的只是纯常量（empty*Form / *_STATUS_LABEL / LEDGER_ALIASES / OPENING_TABS ...）
  与纯函数（*Label / money / plain / formatLogTime / docTypeLabel ...），彼此无 React 依赖。

做法：
1. 定位 `function App()` 作为模块级 / 函数体的分界；
2. 用「字符级括号匹配（跳过字符串与注释）」精确切出 menuGroups、pageActions 两个块；
3. 其余模块级声明 → appLib.js（给顶层 const/function/let 加 export）；
4. App.jsx 重写为：原 import 行 + `import {…} from './lib/appLib'` + menuGroups 块
   + pageActions 块 + 原 App 函数体；
5. 重跑幂等（再次运行：若 App.jsx 已无多余模块级声明则跳过）。

运行：python scripts/split_app_jsx.py [--dry-run]
"""
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'frontend', 'src', 'App.jsx')
LIB = os.path.join(ROOT, 'frontend', 'src', 'lib', 'appLib.js')


def read_lines(p):
    with open(p, encoding='utf-8') as f:
        return f.read().split('\n')


def find_app_start(lines):
    for i, l in enumerate(lines):
        if re.match(r'^function App\(\)\s*\{', l):
            return i  # 0-indexed
    raise RuntimeError('找不到 function App()')


def scan_block(lines, start_idx, open_ch):
    """从 start_idx（该行以 open_ch 开头，如 '[' 或 '{'）开始，字符级括号匹配，
    返回块的结束行号（0-indexed，含闭合符所在行）。"""
    close_ch = {'[': ']', '{': '}', '(': ')'}[open_ch]
    depth = 0
    in_str = None
    i = start_idx
    # 先定位该行里第一个 open_ch 的位置
    line = lines[i]
    pos = line.find(open_ch)
    depth = 1
    j = pos + 1
    while i < len(lines):
        while j < len(line):
            c = line[j]
            if in_str:
                if c == '\\':
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
                j += 1
                continue
            if c in ('"', "'", '`'):
                in_str = c
                j += 1
                continue
            if c == '/' and j + 1 < len(line) and line[j + 1] == '/':
                break  # 行注释，跳过本行剩余
            if c == '/' and j + 1 < len(line) and line[j + 1] == '*':
                # 块注释
                k = j + 2
                while k < len(line) and not (line[k] == '*' and k + 1 < len(line) and line[k + 1] == '/'):
                    k += 1
                j = k + 2
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i
            j += 1
        i += 1
        if i >= len(lines):
            break
        line = lines[i]
        j = 0
    raise RuntimeError('括号未闭合')


def top_level_names(lines):
    names = []
    for l in lines:
        m = re.match(r'^(?:export\s+)?(const|let|var|function)\s+([A-Za-z_$][\w$]*)', l)
        if m:
            names.append(m.group(2))
    return names


def main():
    dry = '--dry-run' in sys.argv
    lines = read_lines(SRC)
    app_idx = find_app_start(lines)  # 0-indexed
    # head = lines[0:app_idx]  (即 1..996 行，1-indexed)
    head = lines[:app_idx]

    # 找到 menuGroups / pageActions 起始行（0-indexed）
    mg_start = pa_start = None
    for i, l in enumerate(head):
        if mg_start is None and re.match(r'^const menuGroups\s*=\s*\[', l):
            mg_start = i
        elif pa_start is None and re.match(r'^const pageActions\s*=\s*\{', l):
            pa_start = i
    if mg_start is None or pa_start is None:
        raise RuntimeError('找不到 menuGroups 或 pageActions')

    mg_end = scan_block(head, mg_start, '[')
    pa_end = scan_block(head, pa_start, '{')

    # 保留段（0-indexed 行集合）
    keep = set(range(0, 7))           # 原 import + worker 副作用
    keep |= set(range(mg_start, mg_end + 1))
    keep |= set(range(pa_start, pa_end + 1))

    # lib 段 = head 中不在 keep 的行
    lib_lines = [head[k] for k in range(len(head)) if k not in keep]

    # 给 lib 顶层声明加 export
    out_lib = []
    for l in lib_lines:
        m = re.match(r'^(const|let|var|function)\s+', l)
        if m and not l.startswith('export '):
            out_lib.append('export ' + l)
        else:
            out_lib.append(l)

    lib_names = top_level_names(out_lib)
    # 去重保序
    seen = set()
    uniq = []
    for n in lib_names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)

    import_line = f"import {{ {', '.join(uniq)} }} from './lib/appLib';"
    new_head = (
        [import_line]
        + lines[0:7]
        + head[mg_start:mg_end + 1]
        + head[pa_start:pa_end + 1]
    )
    new_app = new_head + lines[app_idx:]

    if dry:
        print(f'[dry-run] App 模块级总行数: {len(head)}')
        print(f'[dry-run] menuGroups 块: 行 {mg_start+1}-{mg_end+1}')
        print(f'[dry-run] pageActions 块: 行 {pa_start+1}-{pa_end+1}')
        print(f'[dry-run] 将外提 {len(lib_lines)} 行到 appLib.js，导出 {len(uniq)} 个名字')
        print(f'[dry-run] App.jsx 将从 {len(lines)} 行变为 {len(new_app)} 行')
        return

    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    with open(LIB, 'w', encoding='utf-8') as f:
        f.write('// 自动提取：App.jsx 模块级纯常量与纯函数（见 scripts/split_app_jsx.py）\n')
        f.write('// 这些定义彼此无 React 依赖，且不被 menuGroups / pageActions 反向依赖。\n\n')
        f.write('\n'.join(out_lib))
        f.write('\n')
    with open(SRC, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_app))
        f.write('\n')
    print(f'OK: 外提 {len(lib_lines)} 行 -> {os.path.relpath(LIB, ROOT)}')
    print(f'OK: App.jsx {len(lines)} 行 -> {len(new_app)} 行（含 menuGroups/pageActions/App 函数）')
    print(f'OK: 导出 {len(uniq)} 个名字')


if __name__ == '__main__':
    main()
