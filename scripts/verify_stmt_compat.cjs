/**
 * verify_stmt_compat.cjs —— 增强对账单兼容性验收（2026-10-21 白屏修复）。
 *
 * 场景 A：新后端（8013）—— 四流穿透明细正常渲染，逐张点开不崩。
 * 场景 B（反证）：打补丁 window.fetch 模拟「旧后端结构」（available=true 但无 rows/columns/totals）
 *        —— 必须不白屏，且显示"重启 ERP 后端"指引。
 */
const path = require('path');
const puppeteer = require(path.join('C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core'));

const BASE = 'http://127.0.0.1:8013';
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const results = [];
const ok = (name, pass, detail = '') => {
  results.push({ name, pass });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function openPage(browser, token) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err).split('\n')[0]));
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await sleep(1200);
  await page.evaluate(() => document.querySelectorAll('.nav-group-title').forEach((el) => {
    if (el.getAttribute('aria-expanded') !== 'true') el.click();
  }));
  await sleep(400);
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.nav-item')].find((el) => el.textContent.trim().includes('增强对账单'));
    if (t) t.click();
  });
  await sleep(1500);
  return { page, errors };
}

(async () => {
  const loginRes = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const token = (await loginRes.json()).access_token;
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    defaultViewport: { width: 1440, height: 900 },
  });

  // ── 场景 A：新后端，逐张点开前 5 张 ─────────────────────────────────────
  {
    const { page, errors } = await openPage(browser, token);
    const rowTexts = await page.evaluate(() =>
      [...document.querySelectorAll('tr.erp-table__row')].slice(0, 5).map((tr) => tr.textContent.slice(0, 30)),
    );
    ok('A0 最近列表有行可点', rowTexts.length > 0, `rows=${rowTexts.length}`);
    for (let i = 0; i < Math.min(5, rowTexts.length); i += 1) {
      await page.evaluate((idx) => {
        [...document.querySelectorAll('tr.erp-table__row')][idx].click();
      }, i);
      await sleep(2200);
    }
    const fusionVisible = await page.evaluate(() => {
      const el = document.querySelector('.stmt-fusion');
      if (!el) return { present: false };
      const r = el.getBoundingClientRect();
      return { present: true, th: el.querySelectorAll('th').length, rows: el.querySelectorAll('tbody tr').length, visible: r.width > 0 && r.height > 0 };
    });
    ok('A1 新后端下四流穿透明细正常渲染', fusionVisible.present && fusionVisible.visible && fusionVisible.th >= 30,
      `th=${fusionVisible.th} rows=${fusionVisible.rows}`);
    ok('A2 逐张点开零页面错误', errors.length === 0, errors.slice(0, 2).join(' | '));
    await page.close();
  }

  // ── 场景 B（反证）：模拟旧后端结构 ──────────────────────────────────────
  {
    const { page, errors } = await openPage(browser, token);
    // 先正常点开第一张，再把 fetch 打补丁拦截 preview 返回旧结构，然后切另一张触发重新拉取
    await page.evaluate(() => { [...document.querySelectorAll('tr.erp-table__row')][0].click(); });
    await sleep(2000);
    await page.evaluate(() => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (url, ...rest) => {
        if (String(url).includes('/preview')) {
          // 旧后端结构：available=true、period、ledger、diff —— 没有 rows/columns/totals
          return Promise.resolve(new Response(JSON.stringify({
            statement_id: 1, statement_no: 'OLD', available: true,
            party_type: 'customer', party_name: '旧结构客户', party_id: 701,
            period: { from: '2026-06-01', to: '2026-06-30' },
            ledger: { opening_balance: 0, increase_total: 0, decrease_total: 0, closing_balance: 0, rows: [] },
            statement_side: {}, diff: 0,
          }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
        }
        return originalFetch(url, ...rest);
      };
    });
    // 切到第二张触发 preview 重拉（会命中补丁）
    await page.evaluate(() => {
      const rows = [...document.querySelectorAll('tr.erp-table__row')];
      (rows[1] || rows[0]).click();
    });
    await sleep(2200);
    const legacyState = await page.evaluate(() => {
      const hint = [...document.querySelectorAll('.stmt__preview-empty')].find((el) => el.textContent.includes('重启'));
      const boundary = document.querySelector('.error-boundary, [class*="error"]');
      const appAlive = Boolean(document.querySelector('.erp-table__row'));
      return { hintShown: Boolean(hint), appAlive };
    });
    ok('B1 旧后端结构不白屏（页面仍活着）', legacyState.appAlive);
    ok('B2 显示「重启 ERP 后端」明确指引', legacyState.hintShown);
    ok('B3 模拟旧结构下零页面错误', errors.length === 0, errors.slice(0, 2).join(' | '));
    await page.close();
  }

  await browser.close();
  const passed = results.filter((r) => r.pass).length;
  console.log(`\nPROBE TOTAL: ${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
})().catch((err) => { console.error('FATAL', err); process.exit(2); });
