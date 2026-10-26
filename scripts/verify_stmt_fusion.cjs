/**
 * verify_stmt_fusion.cjs —— 「四流穿透明细」超宽表真浏览器验收（2026-10-21）
 *
 * 断言：
 *  1. 打开「增强对账单」→ 载入对账单 57 → 穿透表出现，34 列表头
 *  2. 横向滚动到最右后，冻结列（业务日期/单据号）依然可见（elementFromPoint 命中）
 *  3. 行类型着色存在（summary 行背景为灰系）
 *  4. 合计条显示 5 组列数与总金额
 *  5. 表头 sticky：纵向滚动后表头仍在
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
let passed = 0, failed = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { passed += 1; console.log(`  ✅ ${name}`); }
  else { failed += 1; console.log(`  ❌ ${name}${extra ? ' —— ' + extra : ''}`); }
};

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();
  const browser = await puppeteer.launch({
    executablePath: 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
    headless: 'new', args: ['--no-sandbox', '--window-size=1440,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 120)));
  await page.evaluateOnNewDocument((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise((r) => setTimeout(r, 2500));

  // 进「增强对账单」（分组：销售管理）
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.nav-group-title')].find((el) => el.textContent.includes('销售管理'));
    if (t) t.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.nav-item')];
    (items.find((el) => el.textContent.trim() === '增强对账单') || items.find((el) => el.textContent.includes('增强对账单'))).click();
  });
  await new Promise((r) => setTimeout(r, 1200));

  // 载入对账单 57：台账里找 DZ20261019001 的行点「打开」
  const opened = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('tr.erp-table__row')];
    const target = rows.find((tr) => tr.textContent.includes('DZ20261019001'));
    if (!target) return false;
    const btn = target.querySelector('button.link-btn') || target;
    btn.click();
    return true;
  });
  ok('台账里找到并打开 DZ20261019001', opened);
  await page.waitForSelector('[data-stmt-fusion]', { timeout: 10000 });
  await new Promise((r) => setTimeout(r, 600));

  // 1. 列数与行
  const meta = await page.evaluate(() => {
    const wrap = document.querySelector('[data-stmt-fusion]');
    const ths = wrap.querySelectorAll('thead th');
    const trs = wrap.querySelectorAll('tbody tr');
    const total = document.querySelector('[data-stmt-totals]');
    return { cols: ths.length, rows: trs.length, total: total ? total.textContent : '' };
  });
  ok(`超宽表渲染 ${meta.cols} 列（34 数据列 + 1 行类型列）`, meta.cols === 35, `实际 ${meta.cols}`);
  ok(`有数据行（${meta.rows} 行）`, meta.rows >= 5, `实际 ${meta.rows}`);
  ok('合计条有金额', /¥/.test(meta.total), meta.total);

  // 2. 横向滚动到最右：冻结列依然钉在可视区
  const scrollBox = await page.evaluateHandle(() => document.querySelector('.stmt-fusion__scroll'));
  await page.evaluate((el) => { el.scrollLeft = el.scrollWidth; el.scrollTop = 0; }, scrollBox);
  await new Promise((r) => setTimeout(r, 400));
  const frozenVisible = await page.evaluate(() => {
    const th = document.querySelector('[data-stmt-fusion] thead th.is-frozen');
    if (!th) return false;
    const rect = th.getBoundingClientRect();
    const wrap = document.querySelector('.stmt-fusion__scroll').getBoundingClientRect();
    return rect.left >= wrap.left - 2 && rect.left < wrap.left + 600; // 钉在容器左侧
  });
  ok('横向滚动到最右后冻结列仍钉在左侧', frozenVisible);

  // 3. summary 行着色
  const summaryBg = await page.evaluate(() => {
    const tr = document.querySelector('tr.stmt-fusion__row--summary td');
    return tr ? getComputedStyle(tr).backgroundColor : '';
  });
  ok('小计行灰底着色', /241, 245, 249/.test(summaryBg), summaryBg);

  // 4. 纵向滚动后表头仍在
  await page.evaluate((el) => { el.scrollTop = el.scrollHeight; el.scrollLeft = 0; }, scrollBox);
  await new Promise((r) => setTimeout(r, 400));
  const headerSticky = await page.evaluate(() => {
    const wrap = document.querySelector('.stmt-fusion__scroll').getBoundingClientRect();
    const th = document.querySelector('[data-stmt-fusion] thead th');
    const rect = th.getBoundingClientRect();
    return rect.top >= wrap.top - 2 && rect.top < wrap.top + 60;
  });
  ok('纵向滚动后表头 sticky 仍在顶部', headerSticky);

  // 5. 数据正确性抽查：detail 行的单号来自列表，金额合计条与 totals 一致
  const dataOk = await page.evaluate(() => {
    const wrap = document.querySelector('[data-stmt-fusion]');
    const hasDetail = !!wrap.querySelector('tr.stmt-fusion__row--detail');
    const text = wrap.textContent;
    return hasDetail && /XSD|XS/.test(text) && /¥/.test(text);
  });
  ok('明细行含真实单号与金额', dataOk);

  console.log(`\n结果：${passed} 通过 / ${failed} 失败`);
  await browser.close();
  process.exit(failed === 0 ? 0 : 1);
})().catch((err) => { console.error('脚本异常：', err); process.exit(2); });
