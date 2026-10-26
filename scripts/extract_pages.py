#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端拆分脚本（Phase 1+）：把 App.jsx 主 return 里的页面 JSX 块抽成独立页面组件。

核心思路（对 React 安全、不重写任何 JSX）：
- 在 App 内构造 `appCtx` 对象，打包「App 函数顶层（depth==1）的全部标识符」
  （import 名 + 函数体内所有 const/let/var/function/destructuring 声明名）。
  只收 depth==1 的声明，避免把 handler/useEffect 内部的局部变量误打包（否则
  `const appCtx = { 那些名 }` 会在运行时 ReferenceError）。
- 每个 `{selectedTab === '<key>' && ( ...JSX... )}` 块被逐字抽出，生成
  `src/pages/<Name>Page.jsx`：组件通过 `ctx` prop 解构拿到所需变量
  （React 钩子、lib 纯函数、App 状态/处理函数全部来自 ctx，页面零 import，避免重复声明）。
- App 内只替换内部 `&& (...)` 为 `&& <Name ctx={appCtx} />`，外层 `{ }` 原样保留。
- 数据加载 effect / 状态仍留在 App，页面只渲染 → 数据流不变。

安全性：
- 页面解构名 = (App 顶层标识符) 去掉 (该块内局部声明)，保证页面用到的 App 级变量都在 ctx 中；
  局部声明留在页面内不会与解构重名。
- 所有 JSX 逐字搬运，不改逻辑。
- 幂等：已抽出的 key 会被跳过。

运行：
  python scripts/extract_pages.py [--dry-run] [--keys k1,k2,k3]
  （不传 --keys 则处理内置 BATCH 列表）
"""
import re
import os
import sys
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'frontend', 'src', 'App.jsx')
PAGES_DIR = os.path.join(ROOT, 'frontend', 'src', 'pages')

BATCH = [
    'customers', 'suppliers', 'products', 'warehouses', 'staff', 'opening-stock',
]

KEYWORDS = {'const', 'let', 'var', 'function', 'of', 'in', 'from', 'as',
            'return', 'if', 'for', 'while', 'else', 'switch', 'catch', 'new'}


def read_lines(p):
    with open(p, encoding='utf-8') as f:
        return f.read().split('\n')


def write_lines(p, lines):
    with open(p, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        f.write('\n')


def pascal(key):
    return ''.join(w.capitalize() for w in key.split('-'))


def collect_import_names(lines):
    names = set()
    for l in lines:
        m = re.match(r'\s*import\s+(.+?)\s+from\s+[\'"]', l)
        if not m:
            continue
        clause = m.group(1)
        for mm in re.finditer(r'([A-Za-z_$][\w$]*)\s*,?\s*(?:\{([^}]*)\})?', clause):
            dflt, named = mm.group(1), mm.group(2)
            if dflt and dflt not in ('*',):
                names.add(dflt)
            if named:
                for n in re.findall(r'([A-Za-z_$][\w$]*)', named):
                    names.add(n)
        for nm in re.finditer(r'\*\s+as\s+([A-Za-z_$][\w$]*)', clause):
            names.add(nm.group(1))
    return names


def decl_names_from(line, kw_start):
    """从 line[kw_start:]（以 const/let/var/function 开头）抽取声明名。"""
    rest = line[kw_start:]
    m = re.search(r'(?<![=!<>])=(?!=)|[\({;]', rest)
    left = rest[:m.start()] if m else rest
    left = re.sub(r'^(?:const|let|var|function)\s+', '', left).strip()
    out = []
    for tok in re.findall(r'[A-Za-z_$][\w$]*', left):
        if tok not in KEYWORDS:
            out.append(tok)
    return out


def collect_app_names(src_path):
    """调用 @babel/parser 精确收集 App 函数顶层标识符（比手写括号匹配可靠）。"""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collect_app_names.cjs')
    frontend_dir = os.path.join(ROOT, 'frontend')
    env = dict(os.environ)
    env['NODE_PATH'] = os.path.join(frontend_dir, 'node_modules')
    out = subprocess.check_output(
        ['node', script, src_path],
        cwd=frontend_dir, env=env, text=True
    )
    return set(json.loads(out))


def match_paren(lines, start_line, start_col):
    depth = 0
    in_str = None
    i, j = start_line, start_col
    while i < len(lines):
        line = lines[i]
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
            if c == '/' and j + 1 < len(line) and line[j + 1] == '/':
                break
            if c == '/' and j + 1 < len(line) and line[j + 1] == '*':
                k = j + 2
                while k < len(line) and not (line[k] == '*' and k + 1 < len(line) and line[k + 1] == '/'):
                    k += 1
                j = k + 2
                continue
            if c in ('"', "'", '`'):
                in_str = c
                j += 1
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return (i, j)
            j += 1
        i += 1
        j = 0
    raise RuntimeError(f'括号未匹配，起始 ({start_line},{start_col})')


def block_local_names(text):
    names = set()
    for m in re.finditer(r'\b(?:const|let|var|function)\b\s+([^\n;=({]*?)(?:=|\(|\{|;)', text):
        for tok in re.findall(r'[A-Za-z_$][\w$]*', m.group(1)):
            if tok not in KEYWORDS:
                names.add(tok)
    return names


def find_main_return(body_lines):
    best = None
    best_size = -1
    for i, l in enumerate(body_lines):
        for mm in re.finditer(r'return\s*\(', l):
            col = mm.end() - 1
            try:
                end = match_paren(body_lines, i, col)
            except RuntimeError:
                continue
            size = end[0] - i
            if size > best_size:
                best_size = size
                best = (i, col)
    return best


def main():
    dry = '--dry-run' in sys.argv
    keys = BATCH
    for a in sys.argv[1:]:
        if a.startswith('--keys='):
            keys = [k.strip() for k in a[8:].split(',') if k.strip()]

    lines = read_lines(SRC)
    if '--all' in sys.argv:
        # 自动发现当前 App.jsx 中所有 `selectedTab === 'X' && (` 块
        disc = set()
        for l in lines:
            for m in re.finditer(r"selectedTab\s*===\s*['\"]([^'\"]+)['\"]\s*&&\s*\(", l):
                disc.add(m.group(1))
        keys = sorted(disc)
    app_idx = None
    for i, l in enumerate(lines):
        if re.match(r'^function App\(\)\s*\{', l):
            app_idx = i
            break
    if app_idx is None:
        raise RuntimeError('找不到 function App()')

    import_names = collect_import_names(lines)
    body_lines = lines[app_idx + 1:]
    # 用 @babel/parser 精确收集（已含 import 本地名 + App 函数顶层声明）
    body_names = collect_app_names(SRC)
    all_names = (import_names | body_names)
    all_names.discard('appCtx')

    processed = []
    for key in keys:
        Name = pascal(key) + 'Page'
        block_start = None
        amp_col = None
        for i, l in enumerate(body_lines):
            m = re.search(r"selectedTab\s*===\s*['\"]" + re.escape(key) + r"['\"]\s*&&\s*\(", l)
            if m:
                amp_col = l.index('&&', m.start())
                # '(' 位置
                paren_col = m.end() - 1
                block_start = (i, paren_col)
                break
        if block_start is None:
            print(f'  [跳过] 未找到 key={key} 的渲染块')
            continue
        end = match_paren(body_lines, block_start[0], block_start[1])
        s_line, s_col = block_start[0], block_start[1] + 1
        e_line, e_col = end
        if s_line == e_line:
            content = body_lines[s_line][s_col:e_col]
        else:
            parts = [body_lines[s_line][s_col:]]
            for k in range(s_line + 1, e_line):
                parts.append(body_lines[k])
            parts.append(body_lines[e_line][:e_col])
            content = '\n'.join(parts)

        local = block_local_names(content)
        destructure = sorted(all_names - local)

        page_file = os.path.join(PAGES_DIR, f'{Name}.jsx')
        if dry:
            print(f'[dry-run] {key} -> {Name}.jsx  解构 {len(destructure)} 名, 块 {s_line+1}..{e_line+1} 行')
            continue

        os.makedirs(PAGES_DIR, exist_ok=True)
        page_code = (
            f"// 自动提取自 App.jsx（selectedTab='{key}'）— 见 scripts/extract_pages.py\n"
            f"export default function {Name}({{ ctx }}) {{\n"
            f"  const {{\n    " + ',\n    '.join(destructure) + "\n  }} = ctx;\n".replace("}} = ctx;", "} = ctx;")
            f"  return (\n{content}\n  );\n"
            f"}}\n"
        )
        with open(page_file, 'w', encoding='utf-8') as f:
            f.write(page_code)

        # 替换：保留外层 { 与 }，把 ` && ( ... )` 换成 ` && <Name ctx={{appCtx}} />`
        # 前缀 = 块起始行中 '&&' 之前的内容（含开头的 '{'）
        prefix = body_lines[s_line][:amp_col]
        # 后缀 = 匹配 ')' 行中 ')' 之后的内容（通常是 '}'）
        suffix = body_lines[e_line][e_col + 1:]
        repl = prefix + '&& <' + Name + ' ctx={appCtx} />' + suffix
        g_start = app_idx + 1 + s_line
        g_end = app_idx + 1 + e_line
        lines[g_start:g_end + 1] = [repl]
        # 重新加载 body（行号已变）
        body_lines = lines[app_idx + 1:]
        processed.append((key, Name, g_start + 1, g_end + 1))

    if dry:
        print(f'[dry-run] 顶层标识符共 {len(all_names)} 个')
        return

    # 注入 const appCtx = {...}：若已存在则替换（幂等），否则插到主 return 前
    ctx_obj = ',\n  '.join(sorted(all_names))
    appctx_code = (
        f"  // 自动注入：打包 App 作用域标识符给页面组件（见 scripts/extract_pages.py）\n"
        f"  const appCtx = {{\n  {ctx_obj}\n  }};"
    )
    existing = _find_existing_appctx(lines)
    if existing:
        s, e = existing
        lines[s:e + 1] = [appctx_code]
    else:
        ret = find_main_return(lines[app_idx + 1:])
        ret_line_global = app_idx + 1 + ret[0]
        lines.insert(ret_line_global, appctx_code)

    write_lines(SRC, lines)
    print(f'OK: 提取 {len(processed)} 个页面 -> {os.path.relpath(PAGES_DIR, ROOT)}')
    for k, n, s, e in processed:
        print(f'  {k} -> {n}.jsx  (App 中原块约 {s}-{e} 行)')


def _find_existing_appctx(lines):
    """若存在旧的 const appCtx = { ... } 块，返回 (起行, 止行)，否则 None。"""
    start = None
    for i, l in enumerate(lines):
        if re.match(r'\s*const appCtx = \{', l):
            start = i
            break
    if start is None:
        return None
    depth = 0
    in_str = None
    for j in range(start, len(lines)):
        line = lines[j]
        k = 0
        while k < len(line):
            c = line[k]
            if in_str:
                if c == '\\':
                    k += 2
                    continue
                if c == in_str:
                    in_str = None
                k += 1
                continue
            if c in ('"', "'", '`'):
                in_str = c
                k += 1
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return (start, j)
            k += 1
    return None


if __name__ == '__main__':
    main()
