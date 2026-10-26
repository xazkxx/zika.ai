/**
 * 三个问题的验收（2026-10-22）：
 *   ① 窄屏（1024×768）双栏不塌成单列：左树 ≥180px、右表吃掉剩余
 *   ② 商品页：没选类别 → 空表 + 引导；选了类别 → 有数据
 *   ③ 库存页：KPI 不再把负数加进"在库合计"；负库存行红字 + 徽标；流水行可点开抽屉
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
    defaultViewport: { width: 1024, height: 768 }, // 故意用窄屏复现"挤成一团"
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.evaluate(() => localStorage.removeItem('erp:mgrid:left'));
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

  // ── ① 窄屏布局 ────────────────────────────────────────────────────────
  await open('商品档案');
  const layout = await page.evaluate(() => {
    const grid = document.querySelector('.mgrid--split');
    if (!grid) return null;
    const left = grid.children[0];
    const right = grid.children[grid.children.length - 1];
    return {
      cols: getComputedStyle(grid).gridTemplateColumns,
      leftW: left ? Math.round(left.getBoundingClientRect().width) : null,
      rightW: right ? Math.round(right.getBoundingClientRect().width) : null,
      gridW: Math.round(grid.getBoundingClientRect().width),
      cols2: getComputedStyle(grid).gridTemplateColumns.split(' ').length,
    };
  });
  check('1024 宽度下商品页仍是两栏（不塌成单列）', Boolean(layout && layout.cols2 === 3), layout && layout.cols);
  check('左树宽度正常（≥180px）', Boolean(layout && layout.leftW >= 180), `${layout && layout.leftW}px`);
  check('右栏占据剩余空间（≥320px）', Boolean(layout && layout.rightW >= 320), `${layout && layout.rightW}px`);

  // ── ② 商品页空态 ──────────────────────────────────────────────────────
  const emptyFirst = await page.evaluate(() => ({
    rows: document.querySelectorAll('tbody tr').length,
    text: (document.querySelector('.erp-table__state-cell') || {}).textContent || '',
  }));
  check('没选类别时商品列表为空（不是 262 行）', emptyFirst.rows <= 1, `${emptyFirst.rows} 行`);
  check('空态提示去左侧选类别', /选|类别|分类/.test(emptyFirst.text), emptyFirst.text.slice(0, 40));

  await page.evaluate(() => {
    const row = [...document.querySelectorAll('.cat-node')].find((e) => (e.textContent || '').includes('五金'));
    if (row) row.click();
  });
  await sleep(900);
  const afterPick = await page.evaluate(() => document.querySelectorAll('tbody tr').length);
  check('点类别后商品列表出数据', afterPick > 0, `${afterPick} 行`);

  // ── ③ 库存页 ──────────────────────────────────────────────────────────
  await open('库存管理');
  await sleep(800);
  const inv = await page.evaluate(() => {
    const kpis = [...document.querySelectorAll('.stock-kpi')].map((k) => (k.textContent || '').trim().replace(/\s+/g, ' '));
    const negRows = document.querySelectorAll('tr.stock-row--neg').length;
    const negBadges = document.querySelectorAll('.stock-neg-badge').length;
    const note = (document.querySelector('.stock-neg-note') || {}).textContent || '';
    const ledgerRows = document.querySelectorAll('tr.inv-ledger-row').length;
    return { kpis, negRows, negBadges, note: note.slice(0, 50), ledgerRows };
  });
  const kpiText = inv.kpis.join(' | ');
  check('KPI 不再显示负数总量', !/库存总量\s*-/.test(kpiText) && !/-[\d,]{3,}/.test(inv.kpis[0] || ''), kpiText.slice(0, 60));
  check('出现了「在库合计 / 负库存商品」两个口径', inv.kpis.length >= 6, `${inv.kpis.length} 个 KPI`);
  check('负库存行标红', inv.negRows > 0, `${inv.negRows} 行`);
  check('负库存行有徽标', inv.negBadges > 0, `${inv.negBadges} 个`);
  check('有负库存原因说明', /只有出库流水|期初库存/.test(inv.note), inv.note.slice(0, 30));
  check('库存流水行可点', inv.ledgerRows > 0, `${inv.ledgerRows} 行`);

  if (inv.ledgerRows > 0) {
    await page.evaluate(() => document.querySelector('tr.inv-ledger-row').click());
    await sleep(500);
    const drawer = await page.evaluate(() => {
      const el = document.querySelector('.inv-drawer');
      return el ? { open: true, text: (el.textContent || '').slice(0, 60) } : { open: false };
    });
    check('点流水行能打开详情抽屉', drawer.open, drawer.text || '');
    if (drawer.open) {
      await page.evaluate(() => document.querySelector('.inv-drawer__mask').click());
      await sleep(300);
    }
  }

  check('全程零页面错误', errors.length === 0, errors[0] || '');
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('验收脚本自身出错：', e);
  process.exit(2);
});
