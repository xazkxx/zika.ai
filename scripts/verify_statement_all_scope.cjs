/**
 * 「增强对账单」三个视角 + 表头对齐 + 预览态按钮收敛 验收（2026-10-22 第二轮）
 *
 * 逐条对应用户指出的四个痛点：
 *   1. 「全部」视角必须有搜索区（含「全部往来单位」）与「🔍 搜索预览」；
 *   2. 预览表**表头与表体列严格对齐**（逐列比对 left/width，误差 ≤ 1px），且能横向滚动；
 *   3. 预览态**不许出现** 保存 / 重算 / 打印 PDF / 导出 Excel / 导出 Word；
 *   4. 支持「全部往来单位」批量预览，勾选后批量生成（每个往来单位一张），验收后自动删掉。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_statement_all_scope.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8019';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
let page;
let browser;
let TOKEN = '';

const ok = (name, extra = '') => {
  results.push({ name, ok: true });
  console.log(`PASS  ${name}${extra ? `  — ${extra}` : ''}`);
};
const fail = (name, why) => {
  results.push({ name, ok: false, why });
  console.log(`FAIL  ${name}  — ${why}`);
  throw new Error(`${name}：${why}`);
};

async function api(method, url, body) {
  const res = await fetch(`${BASE}${url}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  return { status: res.status, data };
}

async function statementIds() {
  const res = await api('GET', '/api/v1/statements?limit=200');
  const rows = Array.isArray(res.data) ? res.data : (res.data && res.data.items) || [];
  return rows.map((row) => Number(row.id));
}

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 先确认后端支持全量预览（不然界面点下去只会报错，验不到 UI）
  const today = new Date().toISOString().slice(0, 10);
  const probe = await api(
    'GET',
    `/api/v1/statements/preview-pool?party_type=all&period_start=2026-01-01&period_end=${today}`,
  );
  if (probe.status !== 200) throw new Error(`全量预览接口不可用：${probe.status}`);
  ok('后端支持「全部往来单位」只读预览', `${probe.data.party_count} 家 · ${probe.data.doc_count} 张单`);

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1660, height: 1000 },
    protocolTimeout: 180000,
  });
  page = await browser.newPage();
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 160)));
  await page.setCacheEnabled(false);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(400);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find(
      (e) => (e.textContent || '').trim() === '增强对账单',
    );
    if (item) item.click();
  });
  await sleep(2200);

  // 确保在「全部」视角
  await page.evaluate(() => document.querySelector('.stmt__seg-btn[data-scope="all"]')?.click());
  await sleep(900);

  // —— 痛点 1：全部视角必须有搜索区 ——
  const allScope = await page.evaluate(() => {
    const preview = document.querySelector('[data-stmt-preview]');
    const partyBox = document.querySelector('.stmt__field--party');
    return {
      hasPreview: Boolean(preview),
      hasParty: Boolean(partyBox),
      periodInputs: document.querySelectorAll('input[type="date"]').length,
    };
  });
  if (!allScope.hasPreview) fail('「全部」视角有「🔍 搜索预览」入口', '找不到按钮');
  ok('「全部」视角有「🔍 搜索预览」入口');
  if (!allScope.hasParty) fail('「全部」视角有往来单位选择区');
  ok('「全部」视角有往来单位选择区', `${allScope.periodInputs} 个日期框`);

  // —— 痛点 4：下拉里要有「全部往来单位」 ——
  await page.evaluate(() => {
    document.querySelector('.stmt__field--party .ssel-trigger')?.click();
  });
  await sleep(500);
  const optionsText = await page.evaluate(() => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    return panels.flatMap((panel) => [...panel.querySelectorAll('.ssel-option')]).map((item) => item.textContent.trim());
  });
  if (!optionsText.some((text) => text.includes('全部往来单位'))) {
    fail('往来单位下拉有「全部往来单位」', optionsText.slice(0, 3).join(' | '));
  }
  ok('往来单位下拉有「全部往来单位」', optionsText[0]);
  // 选它
  const allOpt = await page.evaluate(() => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    const hit = panels
      .flatMap((panel) => [...panel.querySelectorAll('.ssel-option')])
      .find((item) => item.textContent.includes('全部往来单位'));
    if (!hit) return null;
    const rect = hit.getBoundingClientRect();
    return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
  });
  if (!allOpt) fail('选中「全部往来单位」', '选项不在可视区');
  await page.mouse.click(allOpt.x, allOpt.y);
  await sleep(600);

  // 账期拉到全年
  await page.evaluate(() => {
    const set = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const a = document.querySelector('input[aria-label="对账期间开始"]');
    const b = document.querySelector('input[aria-label="对账期间结束"]');
    if (a) set(a, '2026-01-01');
    if (b) set(b, new Date().toISOString().slice(0, 10));
  });
  await sleep(300);

  const before = await statementIds();
  await page.click('[data-stmt-preview]');
  await sleep(3000);

  const pool = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-pool]');
    if (!root) return { ok: false };
    const checks = [...root.querySelectorAll('[data-stmt-check]')];
    return {
      ok: true,
      docChecks: checks.length,
      checked: checks.filter((c) => c.checked).length,
      rows: root.querySelectorAll('tbody tr').length,
      subtitle: (root.closest('.erp-card')?.querySelector('.erp-card__subtitle')?.textContent || '').trim(),
    };
  });
  if (!pool.ok) fail('「全部」视角能搜出预览表', '没有 [data-stmt-pool]');
  ok('「全部」视角能搜出预览表', `${pool.docChecks} 张单 · ${pool.rows} 行`);
  if (pool.checked !== pool.docChecks) fail('默认全选', `${pool.checked}/${pool.docChecks}`);
  ok('默认全选', `${pool.checked}/${pool.docChecks}`);

  // —— 痛点 3：预览态不许有 保存/重算/打印/导出 ——
  const cmdButtons = await page.evaluate(() => {
    const bar = document.querySelector('.stmt__cmd');
    return [...(bar ? bar.querySelectorAll('button') : [])].map((b) => (b.textContent || '').trim());
  });
  const forbidden = ['保存', '重算', '打印 PDF', '导出 Excel', '导出 Word'];
  const hitBad = forbidden.filter((label) => cmdButtons.some((text) => text === label));
  if (hitBad.length) fail('预览态隐藏"针对已生成对账单"的按钮', `仍可见：${hitBad.join('、')}`);
  ok('预览态隐藏保存/重算/打印/导出', `命令区只剩：${cmdButtons.join(' / ')}`);

  // —— 痛点 2：表头与表体严格对齐 ——
  const align = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-pool] [data-stmt-fusion]');
    if (!root) return { ok: false };
    const ths = [...root.querySelectorAll('thead th')];
    const tds = [...root.querySelectorAll('tbody tr')[0].children];
    const deltas = [];
    for (let i = 0; i < Math.min(ths.length, tds.length); i += 1) {
      const a = ths[i].getBoundingClientRect();
      const b = tds[i].getBoundingClientRect();
      deltas.push({ i, dLeft: Math.round(Math.abs(a.left - b.left)), dWidth: Math.round(Math.abs(a.width - b.width)) });
    }
    const scroll = root.querySelector('.stmt-fusion__scroll');
    return {
      ok: true,
      columns: ths.length,
      worstLeft: Math.max(...deltas.map((d) => d.dLeft)),
      worstWidth: Math.max(...deltas.map((d) => d.dWidth)),
      scrollable: scroll ? scroll.scrollWidth > scroll.clientWidth + 20 : false,
      scrollWidth: scroll ? scroll.scrollWidth : 0,
      clientWidth: scroll ? scroll.clientWidth : 0,
      tableLayout: getComputedStyle(root.querySelector('table')).tableLayout,
    };
  });
  if (!align.ok) fail('预览表可测量', '找不到表格');
  if (align.tableLayout !== 'fixed') fail('表格用固定布局（对齐的前提）', align.tableLayout);
  ok('表格用固定布局', align.tableLayout);
  if (align.worstLeft > 1 || align.worstWidth > 1) {
    fail('表头与表体逐列对齐（误差 ≤1px）', `最大偏差 left ${align.worstLeft}px / width ${align.worstWidth}px`);
  }
  ok('表头与表体逐列对齐（误差 ≤1px）', `${align.columns} 列全对齐`);
  if (!align.scrollable) fail('横向滚动可用', `${align.scrollWidth} vs ${align.clientWidth}`);
  ok('横向滚动可用', `${align.scrollWidth}px / ${align.clientWidth}px`);

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_statement_all_scope.png') });
  console.log('  📸 e2e_statement_all_scope.png');

  // —— 批量生成：勾了几个往来单位就该出几张 ——
  await page.click('[data-stmt-confirm]');
  await sleep(3600);
  const after = await statementIds();
  const created = after.filter((id) => !before.includes(id));
  if (!created.length) fail('批量生成落库', `对账单数量 ${before.length} → ${after.length}`);
  const parties = new Set();
  for (const id of created) {
    const detail = await api('GET', `/api/v1/statements/${id}`);
    parties.add(`${detail.data.party_type}:${detail.data.party_id}`);
  }
  if (parties.size !== created.length) {
    fail('每个往来单位各一张（不混户）', `${created.length} 张单却有 ${parties.size} 个往来单位`);
  }
  ok('批量生成：每个往来单位各一张', `${created.length} 张 / ${parties.size} 家`);

  for (const id of created) {
    await api('DELETE', `/api/v1/statements/${id}`);
  }
  ok('已清理验收生成的对账单', `${created.length} 张`);

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_statement_all_scope.png') });
  } catch {
    /* ignore */
  }
  try {
    if (browser) await browser.close();
  } catch {
    /* ignore */
  }
  process.exit(1);
});
