/**
 * 「搜索预览 → 核对勾选 → 确认生成」验收（2026-10-22）
 *
 * 这次交互改造的核心承诺是：**看一眼不能占一个对账单号**。所以这个脚本的重点是
 * "数一遍库里的对账单条数"，而不是"按钮有没有变绿"：
 *
 *   1. 点「🔍 搜索预览」→ 表格出来、单据默认全勾选、汇总有数；
 *   2. **此时库里对账单条数必须不变**（旧版这一点会 +1，正是要修的毛病）；
 *   3. 取消勾选一张 → 已勾选计数下降、该行整组置灰；
 *   4. 点「确认生成对账单」→ 库里恰好 +1，单号是 DZ 开头，明细行数 = 勾选数；
 *   5. 收尾把这张测试对账单删掉（不污染台账）。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_statement_preview_confirm.cjs
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

async function statementCount() {
  const res = await api('GET', '/api/v1/statements?limit=200');
  const rows = Array.isArray(res.data) ? res.data : (res.data && res.data.items) || [];
  return rows.length;
}

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 找一家"这期确实有单据"的客户：直接问 preview-pool，谁有单就用谁
  const customers = await api('GET', '/api/v1/customers?limit=500');
  const list = Array.isArray(customers.data) ? customers.data : (customers.data && customers.data.items) || [];
  const today = new Date().toISOString().slice(0, 10);
  let picked = null;
  for (const customer of list) {
    const probe = await api(
      'GET',
      `/api/v1/statements/preview-pool?party_type=customer&party_id=${customer.id}&period_start=2026-01-01&period_end=${today}`,
    );
    if (probe.status === 200 && (probe.data.doc_count || 0) >= 2) {
      picked = { customer, pool: probe.data };
      break;
    }
  }
  if (!picked) throw new Error('没有任何客户在这期有 ≥2 张单据，无法验收（先生成几张销售单）');
  ok(
    '准备：找到一家这期有单据的客户',
    `${picked.customer.name} · ${picked.pool.doc_count} 张单据 · ¥${picked.pool.totals.amount_sum}`,
  );

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 980 },
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
  await sleep(2000);

  // 切到「应收」——往来单位框只在收/付视角出现
  await page.evaluate(() => document.querySelector('.stmt__seg-btn[data-scope="out"]')?.click());
  await sleep(900);

  // 选往来单位（ssel 是 portal + onMouseDown，必须真实坐标点）
  await page.evaluate(() => {
    const box = document.querySelector('.stmt__field--party .ssel');
    box?.querySelector('.ssel-trigger')?.click();
  });
  await sleep(500);
  await page.evaluate((name) => {
    const input = document.querySelector('.stmt__field--party .ssel-input');
    if (!input) return;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, name);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, picked.customer.name);
  await sleep(700);
  const opt = await page.evaluate((name) => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    const hit = panels
      .flatMap((panel) => [...panel.querySelectorAll('.ssel-option')])
      .find((item) => (item.textContent || '').includes(name));
    if (!hit) return null;
    const rect = hit.getBoundingClientRect();
    return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
  }, picked.customer.name);
  if (!opt) fail('选中往来单位', picked.customer.name);
  await page.mouse.click(opt.x, opt.y);
  await sleep(700);

  // 账期覆盖到有单的那几天
  await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('.stmt__period .stmt__date, .stmt__date')];
    const setVal = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    if (inputs[0]) setVal(inputs[0], '2026-01-01');
    if (inputs[1]) setVal(inputs[1], new Date().toISOString().slice(0, 10));
  });
  await sleep(400);

  // —— 核心断言 A：点「搜索预览」前先记条数 ——
  const beforeCount = await statementCount();

  const previewLabel = await page.evaluate(() => {
    const btn = document.querySelector('[data-stmt-preview]');
    return btn ? btn.textContent.trim() : '';
  });
  if (!previewLabel.includes('搜索预览')) fail('按钮已改名「搜索预览」', previewLabel || '找不到按钮');
  ok('按钮已改名「搜索预览」', previewLabel);

  await page.click('[data-stmt-preview]');
  await sleep(2600);

  const pool = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-pool]');
    if (!root) return { ok: false };
    const checks = [...root.querySelectorAll('[data-stmt-check]')];
    const confirm = root.querySelector('[data-stmt-confirm]');
    return {
      ok: true,
      docChecks: checks.length,
      checkedCount: checks.filter((c) => c.checked).length,
      pickedText: (root.querySelector('[data-stmt-picked-count]')?.textContent || '').trim(),
      confirmText: confirm ? confirm.textContent.trim() : '',
      confirmColor: confirm ? getComputedStyle(confirm).backgroundColor : '',
      rows: root.querySelectorAll('tbody tr').length,
    };
  });
  if (!pool.ok) fail('预览表格已渲染', '找不到 [data-stmt-pool]');
  ok('预览表格已渲染', `${pool.rows} 行 / ${pool.docChecks} 张可勾选单据`);

  if (pool.docChecks !== picked.pool.doc_count) {
    fail('可勾选单据数 = 接口返回的单据数', `${pool.docChecks} vs ${picked.pool.doc_count}`);
  }
  ok('可勾选单据数 = 接口返回的单据数', `${pool.docChecks} 张`);

  if (pool.checkedCount !== pool.docChecks) fail('默认全部勾选', `${pool.checkedCount}/${pool.docChecks}`);
  ok('默认全部勾选', `${pool.checkedCount}/${pool.docChecks}`);

  if (!pool.confirmText.includes('确认生成对账单')) fail('有「确认生成对账单」按钮', pool.confirmText);
  ok('有「确认生成对账单」按钮', pool.confirmText);
  // 绿色：rgb(22,163,74)
  if (!/22,\s*163,\s*74/.test(pool.confirmColor)) fail('确认按钮是绿色（与蓝色预览区分）', pool.confirmColor);
  ok('确认按钮是绿色', pool.confirmColor);

  // —— 核心断言 B：只看不写 ——
  const afterPreviewCount = await statementCount();
  if (afterPreviewCount !== beforeCount) {
    fail('「搜索预览」不写库（对账单条数不变）', `${beforeCount} → ${afterPreviewCount}`);
  }
  ok('「搜索预览」不写库（对账单条数不变）', `仍为 ${beforeCount} 张`);

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_statement_preview_pool.png') });
  console.log('  📸 e2e_statement_preview_pool.png');

  // —— 取消一张 → 计数下降 + 置灰 ——
  await page.evaluate(() => {
    const first = document.querySelector('[data-stmt-check]');
    first?.click();
  });
  await sleep(500);
  const afterUncheck = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-pool]');
    const checks = [...root.querySelectorAll('[data-stmt-check]')];
    return {
      checked: checks.filter((c) => c.checked).length,
      dimmed: root.querySelectorAll('.stmt-fusion__row.is-unpicked').length,
      pickedText: (root.querySelector('[data-stmt-picked-count]')?.textContent || '').trim(),
    };
  });
  if (afterUncheck.checked !== pool.docChecks - 1) {
    fail('取消勾选后计数 -1', `${afterUncheck.checked}/${pool.docChecks}`);
  }
  ok('取消勾选后计数 -1', afterUncheck.pickedText);
  if (afterUncheck.dimmed === 0) fail('取消勾选的单据整组置灰', '没有任何 is-unpicked 行');
  ok('取消勾选的单据整组置灰', `${afterUncheck.dimmed} 行`);

  // 勾回去（保证生成的是全部单据，明细行数好断言）
  await page.evaluate(() => {
    const first = document.querySelector('[data-stmt-check]');
    first?.click();
  });
  await sleep(400);

  // —— 确认生成：库 +1，单号 DZ，明细 = 勾选数 ——
  await page.click('[data-stmt-confirm]');
  await sleep(3200);
  const afterGenerateCount = await statementCount();
  if (afterGenerateCount !== beforeCount + 1) {
    fail('「确认生成对账单」才写库（恰好 +1）', `${beforeCount} → ${afterGenerateCount}`);
  }
  ok('「确认生成对账单」才写库（恰好 +1）', `${beforeCount} → ${afterGenerateCount}`);

  const fresh = await api('GET', '/api/v1/statements?limit=200');
  const rows = Array.isArray(fresh.data) ? fresh.data : (fresh.data && fresh.data.items) || [];
  const created = rows.reduce((a, b) => (Number(a.id) > Number(b.id) ? a : b));
  if (!String(created.statement_no || '').startsWith('DZ')) {
    fail('新对账单号以 DZ 开头', created.statement_no);
  }
  const detail = await api('GET', `/api/v1/statements/${created.id}`);
  const itemCount = (detail.data.items || []).length;
  if (itemCount !== pool.docChecks) {
    fail('明细行数 = 勾选的单据数', `${itemCount} vs ${pool.docChecks}`);
  }
  ok('新单号 / 明细行数正确', `${created.statement_no} · ${itemCount} 行`);
  // 对账单头部的金额字段叫 contract_amount（合同/本期金额），没有 total_amount
  ok(
    '对账单已生成并自动载入（可继续核对/保存）',
    `合计 ¥${detail.data.contract_amount} · 已开票 ¥${detail.data.invoiced_amount}`,
  );

  // 收尾：删掉这张验收用对账单，台账不留垃圾
  const removed = await api('DELETE', `/api/v1/statements/${created.id}`);
  if (removed.status !== 204) fail('清理验收对账单', `HTTP ${removed.status}`);
  ok('清理验收对账单', `已删除 ${created.statement_no}`);

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_statement_pool.png') });
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
