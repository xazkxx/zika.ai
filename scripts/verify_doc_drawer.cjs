/**
 * verify_doc_drawer.cjs —— 「销售出库单详情」右侧抽屉真浏览器验收（2026-10-20）
 *
 * 断言（每一条在旧的"居中弹窗"实现上都会红，天然反证）：
 *   1. 点列表行 → 抽屉出现，且 elementFromPoint 命中抽屉内部（防"DOM 在、看不见"）
 *   2. 抽屉开着时直接点另一行 → 抽屉单号切换（旧弹窗有遮罩挡着，点不到行，必红）
 *   3. Esc → 抽屉关闭
 *   4. 旧的详情 .modal-overlay 不再出现（详情不再走居中弹窗）
 *   5. 收款/开票等操作弹窗不受影响（不在此验，回归由既有基线兜）
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
let passed = 0;
let failed = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { passed += 1; console.log(`  ✅ ${name}`); }
  else { failed += 1; console.log(`  ❌ ${name}${extra ? ' —— ' + extra : ''}`); }
};

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  if (!login.ok) throw new Error(`登录失败 HTTP ${login.status}`);
  const { access_token: token } = await login.json();

  const browser = await puppeteer.launch({
    executablePath: 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--window-size=1440,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 120)));
  await page.evaluateOnNewDocument((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise((r) => setTimeout(r, 2500));

  // 侧边栏分组默认收起 → 先点分组标题，再点「开单管理」
  await page.evaluate(() => {
    const titles = [...document.querySelectorAll('.nav-group-title')];
    const sales = titles.find((el) => el.textContent.includes('销售管理'));
    if (sales) sales.click();
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.nav-item')];
    const target = items.find((el) => el.textContent.trim() === '开单管理')
      || items.find((el) => el.textContent.includes('开单管理'));
    if (target) target.click();
  });
  await new Promise((r) => setTimeout(r, 1500));

  // 等列表出真实数据行（≥1 张单）
  await page.waitForFunction(
    () => document.querySelectorAll('tr.erp-table__row').length > 0,
    { timeout: 15000 },
  );
  await new Promise((r) => setTimeout(r, 800));

  const rowNos = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('tr.erp-table__row')]
      .filter((tr) => /\d{4}-\d{2}-\d{2}/.test(tr.textContent) || /XS\d+/.test(tr.textContent));
    return rows.map((tr) => (tr.textContent.match(/XS\d+/) || [])[0]).filter(Boolean);
  });
  console.log(`列表行单号：${rowNos.slice(0, 5).join(' , ')}（共 ${rowNos.length}）`);
  ok('列表有 ≥2 张单可切换', rowNos.length >= 2, `只识别到 ${rowNos.length}`);

  // ── 断言 1：点第一行 → 抽屉出现且真的可见 ──
  await page.evaluate((no) => {
    const rows = [...document.querySelectorAll('tr.erp-table__row')];
    const target = rows.find((tr) => tr.textContent.includes(no));
    target.click();
  }, rowNos[0]);
  await page.waitForSelector('[data-doc-drawer="sales-outbound"]', { timeout: 5000 });
  const hit = await page.evaluate(() => {
    const drawer = document.querySelector('[data-doc-drawer="sales-outbound"]');
    const rect = drawer.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = Math.min(rect.top + 200, window.innerHeight - 10);
    const el = document.elementFromPoint(cx, cy);
    return { inDrawer: drawer.contains(el) || el === drawer, orderNo: (drawer.textContent.match(/XS\d+/) || [])[0] };
  });
  ok('抽屉出现且置顶可见（elementFromPoint 命中抽屉内部）', hit.inDrawer);
  ok('抽屉显示的是所点单据', hit.orderNo === rowNos[0], `抽屉=${hit.orderNo} 期望=${rowNos[0]}`);

  // ── 断言 2：抽屉开着直接点另一行 → 单号切换（核心新能力，旧弹窗必红）──
  await page.evaluate((no) => {
    const rows = [...document.querySelectorAll('tr.erp-table__row')];
    const target = rows.find((tr) => tr.textContent.includes(no));
    target.scrollIntoView({ block: 'center' });
    target.click();
  }, rowNos[1]);
  await new Promise((r) => setTimeout(r, 600));
  const switched = await page.evaluate(() => {
    const drawer = document.querySelector('[data-doc-drawer="sales-outbound"]');
    return drawer ? (drawer.textContent.match(/XS\d+/) || [])[0] : null;
  });
  ok('抽屉开着点另一行 → 详情直接切换', switched === rowNos[1], `抽屉=${switched} 期望=${rowNos[1]}`);

  // ── 断言 3：Esc 关闭 ──
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 500));
  const afterEsc = await page.evaluate(() => !!document.querySelector('[data-doc-drawer="sales-outbound"]'));
  ok('Esc 关闭抽屉', !afterEsc);

  // ── 断言 4：详情不再用居中弹窗（重新开一次确认 DOM 结构）──
  await page.evaluate((no) => {
    const rows = [...document.querySelectorAll('tr.erp-table__row')];
    rows.find((tr) => tr.textContent.includes(no)).click();
  }, rowNos[0]);
  await new Promise((r) => setTimeout(r, 500));
  const structure = await page.evaluate(() => {
    const drawer = document.querySelector('[data-doc-drawer="sales-outbound"]');
    const oldOverlay = [...document.querySelectorAll('.modal-overlay')]
      .some((el) => el.querySelector('.doc-detail'));
    return { hasDrawer: !!drawer, oldOverlay };
  });
  ok('详情 DOM 是抽屉而非居中弹窗', structure.hasDrawer && !structure.oldOverlay,
    `hasDrawer=${structure.hasDrawer} oldOverlay=${structure.oldOverlay}`);

  console.log(`\n结果：${passed} 通过 / ${failed} 失败`);
  await browser.close();
  process.exit(failed === 0 ? 0 : 1);
})().catch((err) => {
  console.error('脚本异常：', err);
  process.exit(2);
});
