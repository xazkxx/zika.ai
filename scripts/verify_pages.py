#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
页面抽取后的静态校验：确认每个页面用到的标识符都在 { appCtx 键 ∪ 页面本地声明 ∪ 全局/HTML } 内。
目的：抓出「depth-1 扫描漏掉的函数顶层声明」——这类漏网之鱼会导致页面运行时 ReferenceError。
"""
import re
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'frontend', 'src', 'App.jsx')
PAGES_DIR = os.path.join(ROOT, 'frontend', 'src', 'pages')

GLOBALS = {
    # JS 关键字 / 字面量
    'return', 'if', 'for', 'while', 'const', 'let', 'var', 'function', 'else', 'switch',
    'case', 'break', 'continue', 'new', 'typeof', 'instanceof', 'in', 'of', 'do', 'try',
    'catch', 'finally', 'throw', 'await', 'async', 'yield', 'null', 'true', 'false',
    'undefined', 'NaN', 'this', 'void', 'delete', 'class', 'extends', 'super', 'import',
    'export', 'from', 'as', 'default', 'get', 'set',
    # JS 运行时
    'React', 'useState', 'useEffect', 'useMemo', 'useCallback', 'useRef', 'useContext',
    'useReducer', 'useLayoutEffect', 'Fragment', 'Component', 'createContext', 'createElement',
    'cloneElement', 'Children', 'console', 'window', 'document', 'Math', 'Date', 'JSON',
    'Object', 'Array', 'String', 'Number', 'Boolean', 'Symbol', 'Map', 'Set', 'WeakMap',
    'WeakSet', 'Promise', 'RegExp', 'Error', 'TypeError', 'setTimeout', 'setInterval',
    'clearTimeout', 'clearInterval', 'parseInt', 'parseFloat', 'isNaN', 'isFinite',
    'localStorage', 'sessionStorage', 'navigator', 'fetch', 'URL', 'URLSearchParams',
    'Event', 'CustomEvent', 'Blob', 'File', 'FileReader', 'Image', 'location', 'history',
    'alert', 'confirm', 'prompt', 'requestAnimationFrame', 'cancelAnimationFrame',
    # 常用方法名（作为成员调用被当作标识符出现）
    'map', 'filter', 'find', 'findIndex', 'some', 'every', 'reduce', 'forEach', 'slice',
    'splice', 'push', 'pop', 'shift', 'unshift', 'join', 'split', 'trim', 'replace',
    'includes', 'indexOf', 'lastIndexOf', 'keys', 'values', 'entries', 'startsWith',
    'endsWith', 'toUpperCase', 'toLowerCase', 'toFixed', 'toLocaleString', 'parse',
    'stringify', 'assign', 'hasOwnProperty', 'getItem', 'setItem', 'removeItem',
    'preventDefault', 'stopPropagation', 'then', 'catch', 'finally', 'resolve', 'reject',
    'length', 'value', 'target', 'currentTarget', 'key', 'id', 'name', 'type', 'state',
    'props', 'children', 'ref', 'className', 'style', 'onClick', 'onChange', 'onSubmit',
    'onBlur', 'onFocus', 'onKeyPress', 'onKeyDown', 'onKeyUp', 'onMouseEnter', 'onMouseLeave',
    'placeholder', 'disabled', 'checked', 'readOnly', 'defaultValue', 'href', 'src', 'alt',
    'title', 'role', 'aria', 'tabIndex', 'htmlFor', 'autoFocus', 'required', 'multiple',
    'min', 'max', 'step', 'pattern', 'rows', 'cols', 'width', 'height',
}

HTML_TAGS = {
    'div', 'span', 'button', 'input', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'section', 'header', 'footer', 'main', 'nav', 'ul', 'ol', 'li', 'form', 'label',
    'select', 'option', 'optgroup', 'textarea', 'p', 'strong', 'em', 'i', 'b', 'u', 's',
    'small', 'sub', 'sup', 'dl', 'dt', 'dd', 'fieldset', 'legend', 'canvas', 'video', 'audio',
    'source', 'track', 'iframe', 'link', 'meta', 'title', 'head', 'body', 'html', 'br', 'hr',
    'code', 'pre', 'blockquote', 'abbr', 'cite', 'q', 'time', 'mark', 'ruby', 'rt', 'rp',
    'picture', 'img', 'figure', 'figcaption', 'details', 'summary', 'dialog', 'menu', 'menuitem',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'article', 'aside', 'address', 'data', 'output',
    'progress', 'meter', 'svg', 'path', 'g', 'circle', 'rect', 'line', 'polygon', 'polyline',
    'ellipse', 'text', 'defs', 'use', 'symbol', 'linearGradient', 'stop', 'foreignObject',
}

# 常见 JSX 属性名（camelCase），避免误报
JSX_ATTRS = {
    'className', 'style', 'onClick', 'onChange', 'onSubmit', 'onBlur', 'onFocus',
    'onKeyDown', 'onKeyUp', 'onKeyPress', 'onMouseEnter', 'onMouseLeave', 'onMouseOver',
    'onMouseOut', 'placeholder', 'disabled', 'checked', 'readOnly', 'defaultValue',
    'href', 'src', 'alt', 'title', 'role', 'tabIndex', 'htmlFor', 'autoFocus', 'required',
    'multiple', 'min', 'max', 'step', 'pattern', 'rows', 'cols', 'width', 'height',
    'value', 'type', 'name', 'id', 'key', 'target', 'rel', 'viewBox', 'fill', 'stroke',
    'strokeWidth', 'strokeLinecap', 'strokeLinejoin', 'd', 'x1', 'y1', 'x2', 'y2',
    'cx', 'cy', 'r', 'rx', 'ry', 'points', 'transform', 'gradientUnits', 'offset',
    'stopColor', 'stopOpacity', 'xmlns', 'preserveAspectRatio', 'encoding', 'method',
    'action', 'autoComplete', 'spellCheck', 'contentEditable', 'draggable', 'onDragStart',
    'onDrop', 'onDragOver', 'colSpan', 'rowSpan', 'scope', 'controls', 'autoPlay', 'loop',
    'muted', 'poster', 'preload', 'crossOrigin', 'loading', 'referrerPolicy', 'sizes',
    'srcSet', 'async', 'defer', 'hidden', 'open', 'selected', 'default', 'indeterminate',
}


def parse_appctx_keys(src_lines):
    keys = set()
    in_block = False
    for l in src_lines:
        if 'const appCtx = {' in l:
            in_block = True
            # 可能同行有键
        if in_block:
            if '}' in l and 'appCtx' not in l:
                in_block = False
            for m in re.findall(r'([A-Za-z_$][\w$]*)', l):
                keys.add(m)
            if '};' in l:
                break
    # 去掉明显非标识符（如 }）
    keys.discard('}')
    return keys


def page_local_names(text):
    names = set()
    # 主解构: const { ... } = ctx;
    m = re.search(r'const\s*\{([^}]*)\}\s*=\s*ctx', text)
    if m:
        for tok in re.findall(r'([A-Za-z_$][\w$]*)', m.group(1)):
            names.add(tok)
    # 其他本地声明
    for mm in re.finditer(r'\b(?:const|let|var|function)\b\s+([^\n;=({]*?)(?:=|\(|\{|;)', text):
        for tok in re.findall(r'([A-Za-z_$][\w$]*)', mm.group(1)):
            if tok not in {'const', 'let', 'var', 'function'}:
                names.add(tok)
    return names


def main():
    src_lines = open(SRC, encoding='utf-8').read().split('\n')
    appctx = parse_appctx_keys(src_lines)
    print(f'appCtx 键数: {len(appctx)}')

    problems = 0
    for fn in sorted(os.listdir(PAGES_DIR)):
        if not fn.endswith('.jsx'):
            continue
        path = os.path.join(PAGES_DIR, fn)
        text = open(path, encoding='utf-8').read()
        locals_ = page_local_names(text)
        used = set(re.findall(r'[A-Za-z_$][\w$]*', text))
        missing = (used - appctx - locals_ - GLOBALS - HTML_TAGS - JSX_ATTRS)
        # 过滤纯数字/单字符噪声
        missing = {m for m in missing if len(m) > 1}
        if missing:
            problems += 1
            print(f'\n[!] {fn} 可能缺少标识符: {sorted(missing)[:40]}')
        else:
            print(f'[ok] {fn}')
    if problems == 0:
        print('\n✓ 全部页面：用到的标识符均能在 appCtx / 本地 / 全局 中找到')
    else:
        print(f'\n共 {problems} 个页面存在疑似缺失（请人工复核，多为 JSX 属性或第三方 API 误报）')


if __name__ == '__main__':
    main()
