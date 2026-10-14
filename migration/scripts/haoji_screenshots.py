# -*- coding: utf-8 -*-
"""浩技云进销存 — 全页面批量截图
用法:
    python haoji_screenshots.py           # 解析菜单并逐页截图
    python haoji_screenshots.py --list    # 只打印菜单树，不截图

输出: ./screenshots/  序号_分组_菜单名.png
      并在同目录生成 _menu.json / _index.md
"""
import sys, os, re, json, time, argparse
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from haoji_login import new_session, BASE

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
VIEWPORT = {'width': 1680, 'height': 1000}

# 菜单之外但值得截图的固定页面: (分组, 名称, 相对URL)
EXTRA_PAGES = [
    ('00_登录与首页', '登录页', None),            # None = 未登录状态截登录页
    ('00_登录与首页', '主框架-首页', 'loginController.do?login'),
    ('00_登录与首页', '主页内容', 'loginController.do?fineuiHome'),
    ('99_系统', '系统参数-单据设置', 'emkSysParamController.do?billSet'),
]


def parse_menu(html):
    """解析主框架页 -> [(分组, 名称, url), ...] 保序"""
    items = []
    # 分组: <li class='menu-item'> ... <span class="menu-text">分组</span> ... <ul ...> ... </ul>
    group_re = re.compile(
        r"<a href[^>]*>\s*<i[^>]*></i>\s*<span class=\"menu-text\">(.*?)</span>.*?"
        r"<ul[^>]*>(.*?)</ul>", re.S)
    link_re = re.compile(r'href="([A-Za-z]+\.do\?[A-Za-z0-9_]+)"[^>]*>.*?<span>(.*?)</span>', re.S)
    for gm in group_re.finditer(html):
        gname = re.sub(r'<[^>]+>', '', gm.group(1)).strip()
        for lm in link_re.finditer(gm.group(2)):
            url, name = lm.group(1), re.sub(r'<[^>]+>', '', lm.group(2)).strip()
            items.append((gname, name, url))
    return items


def sanitize(s):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', s).strip('_')


# 截图前清理: 移除 EasyUI messager 错误弹窗及其遮罩（页面本体内容保留）
CLEANUP_JS = """() => {
    let n = 0;
    document.querySelectorAll('.messager-body').forEach(e => {
        const win = e.closest('.panel.window') || e.closest('.window');
        if (win) { win.remove(); n++; }
    });
    if (n) document.querySelectorAll('.window-shadow, .window-mask').forEach(e => e.remove());
    return n;
}"""


def fix_dialogs(s):
    """重截 _menu.json 里 title 含 404 的条目（这些页面内容正常但叠加了错误弹窗）"""
    import json
    from playwright.sync_api import sync_playwright

    idx_path = os.path.join(OUT_DIR, '_menu.json')
    log = json.load(open(idx_path, encoding='utf-8'))
    todo = [x for x in log if x.get('file') and '404' in (x.get('title') or '')]
    print(f'需要重截 {len(todo)} 个页面')
    if not todo:
        return

    cookie = s.cookies.get_dict().get('JSESSIONID')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True,
                                    args=['--disable-gpu', '--no-sandbox'])
        ctx = browser.new_context(viewport=VIEWPORT, locale='zh-CN')
        ctx.add_cookies([{'name': 'JSESSIONID', 'value': cookie,
                          'domain': 'www.janssa.com', 'path': '/'}])
        page = ctx.new_page()
        for it in todo:
            try:
                page.goto(it['url'], wait_until='load', timeout=45000)
                try:
                    page.wait_for_load_state('networkidle', timeout=6000)
                except Exception:
                    pass
                page.wait_for_timeout(1800)
                n = page.evaluate(CLEANUP_JS)
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT_DIR, it['file']))
                it['title'] = page.title()
                print(f"  [清理弹窗x{n}] {it['name']} -> {it['file']}")
            except Exception as e:
                print(f"  {it['name']} ERR {str(e)[:60]}")
        ctx.close()
        browser.close()

    json.dump(log, open(idx_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('完成')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='只打印菜单树')
    ap.add_argument('--with-forms', action='store_true', help='额外截取各模块的新增表单页(?goAdd)')
    ap.add_argument('--group', action='append', default=None,
                    help='只截指定分组(可多次传入), 如 --group 报表')
    ap.add_argument('--fix-dialogs', action='store_true',
                    help='重截 _menu.json 中标题含404(带错误弹窗)的页面')
    args = ap.parse_args()

    s = new_session()

    if args.fix_dialogs:
        fix_dialogs(s)
        return
    main_html = s.get(BASE + 'loginController.do?login', timeout=25).text
    menu = parse_menu(main_html)
    print(f'\n解析到 {len(menu)} 个菜单页面\n')
    cur = None
    for g, n, u in menu:
        if g != cur:
            print(f'【{g}】'); cur = g
        print(f'    {n:16s} {u}')
    if args.list:
        return

    if args.group:
        keys = tuple(args.group)
        menu = [x for x in menu if x[0] in keys]
        print(f'\n按分组过滤: {args.group} -> {len(menu)} 个页面')

    os.makedirs(OUT_DIR, exist_ok=True)
    cookie = s.cookies.get_dict().get('JSESSIONID')
    print(f'\nJSESSIONID = {cookie}')

    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PWTimeout

    pages = EXTRA_PAGES + [('01_' + g, n, u) for g, n, u in menu]

    if args.with_forms:
        # 每个 controller 额外尝试 ?goAdd 表单页
        seen_ctrl, forms = set(), []
        for g, n, u in menu:
            ctrl = u.split('.do?')[0]
            if ctrl in seen_ctrl:
                continue
            seen_ctrl.add(ctrl)
            forms.append(('9_' + g, n + '-新增表单', ctrl + '.do?goAdd'))
        pages += forms

    # 去重 URL
    seen, uniq = set(), []
    for g, n, u in pages:
        k = (n, u)
        if k in seen:
            continue
        seen.add(k); uniq.append((g, n, u))

    log = []
    idx = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True,
                                    args=['--disable-gpu', '--no-sandbox'])
        # --- 未登录状态: 截登录页 ---
        ctx0 = browser.new_context(viewport=VIEWPORT, locale='zh-CN')
        pg = ctx0.new_page()
        pg.goto(BASE + 'loginController.do?login', wait_until='load', timeout=40000)
        pg.wait_for_timeout(2500)
        p_login = os.path.join(OUT_DIR, '00_登录页.png')
        pg.screenshot(path=p_login)
        print('  [登录页] -> 00_登录页.png')
        log.append({'group': '00_登录与首页', 'name': '登录页', 'url': BASE + 'loginController.do?login',
                    'file': '00_登录页.png'})
        ctx0.close()

        # --- 已登录状态: 注入 cookie ---
        ctx = browser.new_context(viewport=VIEWPORT, locale='zh-CN')
        ctx.add_cookies([{'name': 'JSESSIONID', 'value': cookie,
                          'domain': 'www.janssa.com', 'path': '/'}])
        page = ctx.new_page()
        for g, n, u in uniq:
            if u is None:
                continue
            idx += 1
            fname = f'{idx:02d}_{sanitize(g)}_{sanitize(n)}.png'
            fpath = os.path.join(OUT_DIR, fname)
            url = BASE + u
            try:
                page.goto(url, wait_until='load', timeout=45000)
                try:
                    page.wait_for_load_state('networkidle', timeout=6000)
                except PWTimeout:
                    pass
                page.wait_for_timeout(1800)
                title = page.title()
                if 'Exception' in (title or ''):
                    print(f'  [{idx:02d}] {g} / {n}  -> 跳过(页面异常/{title})')
                    log.append({'group': g, 'name': n, 'url': url, 'file': None,
                                'error': f'page exception: {title}'})
                    continue
                page.evaluate(CLEANUP_JS)
                page.wait_for_timeout(300)
                page.screenshot(path=fpath)
                print(f'  [{idx:02d}] {g} / {n}  -> {fname}   ({title[:24]})')
                log.append({'group': g, 'name': n, 'url': url, 'file': fname, 'title': title})
            except Exception as e:
                print(f'  [{idx:02d}] {g} / {n}  ERR {str(e)[:70]}')
                log.append({'group': g, 'name': n, 'url': url, 'file': None, 'error': str(e)[:120]})
        ctx.close()
        browser.close()

    # 与已有 _menu.json 合并（补截时保留历史记录）
    idx_path = os.path.join(OUT_DIR, '_menu.json')
    old = []
    if os.path.exists(idx_path):
        try:
            old = json.load(open(idx_path, encoding='utf-8'))
        except Exception:
            old = []
    old_keys = {(x.get('name'), x.get('url')) for x in old}
    for it in log:
        if (it.get('name'), it.get('url')) not in old_keys:
            old.append(it)
    log = old

    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)

    # 生成索引 md
    lines = ['# 浩技云进销存 — 页面截图索引', '']
    cg = None
    for it in log:
        if it['group'] != cg:
            lines.append(f'\n## {it["group"]}\n')
            lines.append('| 页面 | 文件 | 地址 |')
            lines.append('|---|---|---|')
            cg = it['group']
        f = it.get('file') or f"(失败: {it.get('error','')})"
        lines.append(f'| {it["name"]} | {f} | {it["url"]} |')
    with open(os.path.join(OUT_DIR, '_index.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    ok = sum(1 for x in log if x.get('file'))
    print(f'\n完成: 成功 {ok} / 共 {len(log)}，输出目录 {OUT_DIR}')


if __name__ == '__main__':
    main()
