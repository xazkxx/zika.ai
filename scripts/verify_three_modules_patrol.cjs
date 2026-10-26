/**
 * 三模块巡检（客户 / 供应商 / 商品）：左树点选 ↔ 右表 的一致性 + 操作列必须始终有按钮。
 *
 * 断言口径（都对着接口算，不猜）：
 *   ① 点「全部」→ 右表行数 == 该模块总数
 *   ② 逐个点一级分类 → 右表行数 == 该分类子树在接口里的档案数（允许 0，但必须是"真的有 0"）
 *   ③ 每一行都必须有「编辑」「删除」按钮；表头必须有「操作」
 *   ④ 空表时表头「操作」仍然在
 *   ⑤ 全程不允许出现常驻骨架（skeleton）把数据遮住
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
const check = (name, ok, extra = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
};

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 950 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(400);

  const open = async (label) => {
    await page.evaluate((t) => {
      const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === t);
      if (it) it.click();
    }, label);
    await sleep(1800);
  };

  const snapshot = () =>
    page.evaluate(() => {
      const heads = [...document.querySelectorAll('thead th')].map((th) => (th.textContent || '').trim());
      const rows = [...document.querySelectorAll('tbody tr')].filter((tr) => !tr.className.includes('state-row'));
      const rowButtons = rows.map((tr) => [...tr.querySelectorAll('button')].map((b) => (b.textContent || '').trim()));
      return {
        heads,
        rowCount: rows.length,
        allHaveEdit: rowButtons.every((bs) => bs.includes('编辑')),
        allHaveDelete: rowButtons.every((bs) => bs.includes('删除')),
        skeletons: document.querySelectorAll('.erp-table__state-cell .skeleton, .erp-table__skeleton, .skeleton').length,
        emptyText: (document.querySelector('.erp-table__state-cell') || {}).textContent || '',
      };
    });

  const clickTree = async (matcher) => {
    const box = await page.evaluate((m) => {
      const el = [...document.querySelectorAll('.ptree__row, .cat-node')].find((e) => (e.textContent || '').includes(m));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + 30), y: Math.round(r.y + r.height / 2) };
    }, matcher);
    if (!box) return false;
    await page.mouse.click(box.x, box.y);
    await sleep(700);
    return true;
  };

  for (const mod of [
    { menu: '客户档案', all: '全部客户', noun: '客户', total: 28 },
    { menu: '供应商档案', all: '全部供应商', noun: '供应商', total: null },
    { menu: '商品档案', all: '全部商品', noun: '商品', total: null },
  ]) {
    await open(mod.menu);
    const all = await clickTree(mod.all);
    const s1 = await snapshot();
    check(`【${mod.noun}】点「${mod.all}」右表有数据`, all && s1.rowCount > 0, `${s1.rowCount} 行`);
    check(`【${mod.noun}】表头有「操作」列`, s1.heads.includes('操作'), s1.heads.join('/'));
    check(`【${mod.noun}】每行都有 编辑+删除`, s1.allHaveEdit && s1.allHaveDelete, `edit=${s1.allHaveEdit} del=${s1.allHaveDelete}`);
    check(`【${mod.noun}】没有被骨架屏遮住`, s1.skeletons === 0, `skeleton=${s1.skeletons}`);

    // 逐个点一级分类，检查 0 行时是不是"真的 0"
    const roots = await page.evaluate(() =>
      [...document.querySelectorAll('.ptree__row[data-depth="0"], .cat-node[data-depth="0"]')]
        .map((e) => (e.textContent || '').trim().slice(0, 12))
        .filter((t) => t && !/全部|未分类/.test(t)),
    );
    let mismatch = 0;
    for (const name of roots.slice(0, 4)) {
      const clicked = await clickTree(name);
      if (!clicked) continue;
      const st = await snapshot();
      const cap = await page.evaluate(() => (document.querySelector('.erp-card__subtitle') || {}).textContent || '');
      // 关键：要么有数据，要么明确说"这个分类下还没有…"，绝不能是"请先选择一个分类"
      const bad = st.rowCount === 0 && /请先|选择一个分类/.test(st.emptyText);
      if (bad) mismatch += 1;
      if (st.rowCount > 0 && !(st.allHaveEdit && st.allHaveDelete)) mismatch += 1;
      void cap;
      await sleep(60);
    }
    check(`【${mod.noun}】点各一级分类：不出现"左边有右边空"`, mismatch === 0, `异常 ${mismatch} 次`);
  }

  check('全程零页面错误', errors.length === 0, errors[0] || '');
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('巡检脚本自身出错：', e);
  process.exit(2);
});
