# -*- coding: utf-8 -*-
"""合同页左侧表单「L 型断层」诊断：登录 → 打开合同页 → 截图 + 输出每个表单块的几何数据。"""
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
CHROME = r"C:\Users\admi\.agent-browser\browsers\chrome-156.0.8078.47\chrome.exe"

JS = """
() => {
  const panel = document.querySelector('section.contracts-form-panel');
  if (!panel) return { error: 'no panel' };
  const rows = [];
  const walk = (el, depth) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const label = (el.tagName + '.' + (el.className && el.className.toString().split(' ')[0] || '')).slice(0, 60);
    rows.push({
      d: depth, tag: label,
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      disp: cs.display, pos: cs.position,
      minH: cs.minHeight, height: cs.height,
      text: (el.childNodes[0] && el.childNodes[0].nodeType === 3 ? el.childNodes[0].textContent.trim().slice(0, 14) : ''),
    });
    if (depth < 4) {
      for (const c of el.children) walk(c, depth + 1);
    }
  };
  walk(panel, 0);
  return { rows };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=CHROME, headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1680,950"],
    )
    ctx = browser.new_context(viewport={"width": 1680, "height": 950})
    page = ctx.new_page()
    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)
    # 登录
    if page.locator("#auth-account").count():
        page.fill("#auth-account", "admin")
        page.fill("#auth-password", "Admin123")
        page.click(".auth-form button[type=submit]")
        page.wait_for_timeout(2500)
    # 侧栏：展开「销售管理」→ 点「购销合同」
    clicked = page.evaluate(
        """() => {
        const items = [...document.querySelectorAll('a,button,li,span,div')].filter(e => e.offsetParent);
        const hit = items.filter(e => (e.textContent || '').trim() === '销售管理');
        if (hit.length) { hit[hit.length - 1].click(); return '销售管理'; }
        return null;
    }"""
    )
    print("nav1:", clicked)
    page.wait_for_timeout(800)
    clicked = page.evaluate(
        """() => {
        const items = [...document.querySelectorAll('a,button,li,span,div')].filter(e => e.offsetParent);
        const hit = items.filter(e => (e.textContent || '').trim() === '购销合同');
        if (hit.length) { hit[hit.length - 1].click(); return '购销合同'; }
        return null;
    }"""
    )
    print("nav2:", clicked)
    page.wait_for_timeout(800)
    # 选中第一个 Word 模板，复现「选中模板后出现断层」的场景
    picked = page.evaluate(
        """() => {
        const sel = document.querySelector('[data-contract-template-select]');
        if (!sel) return 'no-select';
        const wordOpt = [...sel.options].find(o => o.value && /Word/.test(o.textContent));
        const opt = wordOpt || [...sel.options].find(o => o.value);
        if (!opt) return 'no-option';
        const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
        setter.call(sel, opt.value);
        sel.dispatchEvent(new Event('input', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        return opt.textContent.trim();
    }"""
    )
    print("picked:", picked)
    page.wait_for_timeout(2500)
    page.screenshot(path="scripts/_gap_full.png", full_page=False)
    data = page.evaluate(JS)
    with open("scripts/_gap_diag.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # 只打印可疑的高块（h > 80 且非 iframe/表格）
    for r in data.get("rows", []):
        if r["h"] > 90 and r["disp"] != "none":
            print(f"d{r['d']} y={r['y']:>5} h={r['h']:>4} w={r['w']:>4} {r['tag']:<58} {r['text']}")
    browser.close()
print("DONE")
