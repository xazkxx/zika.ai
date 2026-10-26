/**
 * 三单匹配看板 UI 验收 —— 2026-10-23
 *
 * 验七件事（真浏览器）：
 *   1. 侧边栏有「三单匹配」菜单，能进去；
 *   2. 顶部 6 个 KPI 都有数，缺口是红字；
 *   3. 主表有行，金额列与缺口列数值自洽（缺口 = 合同额 − 已开票/已付）；
 *   4. 状态灯文案与后端 match_status 一致（四种之一）；
 *   5. 点「查看」→ 右侧抽屉滑出，含合同明细表 + 时间线；
 *   6. 抽屉里的票据/款项条目带「单据关联 / 按单位估算」标记；
 *   7. 状态筛选能生效（选了「票款均未齐」就只剩这种）。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_three_way_match.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8019';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TAG = Date.now().toString().slice(-6);
const TODAY = new Date().toISOString().slice(0, 10);

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

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 准备：一张 1000 的合同（不转单），给该单位挂一张 400 的销项票 → 应判「票款均未齐」
  const customer = await api('POST', '/api/v1/customers', {
    code: `CUST-TWM${TAG}`,
    name: `测试三单客户${TAG}`,
  });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);
  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-TWM${TAG}`,
    name: `测试三单商品${TAG}`,
    unit: '件',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
  const contract = await api('POST', '/api/v1/contracts', {
    direction: 'out',
    party_id: customer.data.id,
    party_name: customer.data.name,
    sign_date: TODAY,
    items: [{ product_id: product.data.id, quantity: 1, unit_price: 1000 }],
  });
  if (contract.status !== 201) throw new Error(`建合同失败 ${JSON.stringify(contract.data)}`);
  const CID = contract.data.id;

  const invoice = await api('POST', '/api/v1/invoices', {
    invoice_no: `E2E-TWM-${TAG}`,
    invoice_type: '普票',
    issue_date: TODAY,
    buyer_name: customer.data.name,
    seller_name: '西安寨卡信息技术有限公司',
    total_amount: 400,
    direction: 'output',
    status: '正常',
  });
  if (![200, 201].includes(invoice.status)) throw new Error(`建发票失败 ${JSON.stringify(invoice.data)}`);
  ok('准备：合同 ¥1000 + 未挂单销项票 ¥400', contract.data.contract_no);

  const serverRow = (await api('GET', `/api/v1/three-way-match?keyword=${contract.data.contract_no}`)).data.rows[0];
  if (!serverRow) fail('后端能查到这张合同');
  if (serverRow.match_status !== 'both_missing') {
    fail('后端判定为「票款均未齐」', serverRow.match_status);
  }
  ok('后端判定状态', `${serverRow.match_label} · 票 ${serverRow.invoiced_amount} · 款 ${serverRow.paid_amount}`);

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1920, height: 1000 },
    protocolTimeout: 180000,
  });
  page = await browser.newPage();
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 160)));
  await page.setCacheEnabled(false);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');

  // —— 1. 菜单 ——
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(600);
  const menuFound = await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find(
      (e) => (e.textContent || '').trim() === '三单匹配',
    );
    if (!item) return false;
    item.click();
    return true;
  });
  if (!menuFound) fail('侧边栏有「三单匹配」菜单', '找不到该菜单项');
  await sleep(2600);
  ok('侧边栏有「三单匹配」菜单，可进入');

  // —— 2. KPI ——
  const kpi = await page.evaluate(() => {
    const root = document.querySelector('[data-three-way-page]');
    if (!root) return { ok: false };
    const read = (name) => {
      const node = root.querySelector(`[data-twm-kpi="${name}"]`);
      return node ? node.textContent.trim() : null;
    };
    const gapNode = root.querySelector('[data-twm-kpi="invoice-gap"]');
    const gapCard = gapNode ? gapNode.closest('.twm__kpi') : null;
    return {
      ok: true,
      count: read('count'),
      contract: read('contract'),
      invoiced: read('invoiced'),
      invoiceGap: read('invoice-gap'),
      paid: read('paid'),
      paymentGap: read('payment-gap'),
      gapColor: gapCard ? getComputedStyle(gapCard.querySelector('strong')).color : '',
    };
  });
  if (!kpi.ok) fail('进入三单匹配页面', '找不到 [data-three-way-page]');
  ['count', 'contract', 'invoiced', 'invoiceGap', 'paid', 'paymentGap'].forEach((key) => {
    if (kpi[key] === null || kpi[key] === '') fail(`KPI ${key} 有值`, String(kpi[key]));
  });
  ok('6 个 KPI 都有数', `合同 ${kpi.count} 张 · 总额 ${kpi.contract} · 已开票 ${kpi.invoiced} · 未开票缺口 ${kpi.invoiceGap}`);
  // 缺口红字：rgb(185, 28, 28)
  if (!/185,\s*28,\s*28/.test(kpi.gapColor)) fail('缺口数字是红字', kpi.gapColor);
  ok('未开票缺口是红字', kpi.gapColor);

  // —— 3. 主表 + 数值自洽 ——
  const table = await page.evaluate((cid) => {
    const rows = [...document.querySelectorAll('[data-twm-table] tbody tr')];
    const row = rows.find((r) => r.getAttribute('data-twm-row') === String(cid));
    if (!row) return { ok: false, rows: rows.length };
    const cells = [...row.children].map((td) => (td.textContent || '').trim());
    return { ok: true, rows: rows.length, cells };
  }, CID);
  if (!table.ok) fail('主表里有这张合同', `共 ${table.rows} 行`);
  ok('主表里有这张合同', `${table.rows} 行`);

  const num = (text) => Number(String(text).replace(/[^\d.-]/g, ''));
  const [noCell, , , amountCell, invoicedCell, invGapCell, paidCell, payGapCell] = table.cells;
  if (!noCell.includes(contract.data.contract_no)) fail('第一列是合同编号', noCell);
  if (Math.abs(num(amountCell) - 1000) > 0.01) fail('合同金额列 = 1000', amountCell);
  if (Math.abs(num(invoicedCell) - 400) > 0.01) fail('已开票列 = 400', invoicedCell);
  if (Math.abs(num(invGapCell) - 600) > 0.01) fail('开票缺口列 = 600', invGapCell);
  if (Math.abs(num(paidCell)) > 0.01) fail('已付列 = 0', paidCell);
  if (Math.abs(num(payGapCell) - 1000) > 0.01) fail('付款缺口列 = 1000', payGapCell);
  ok('金额与缺口自洽', `合同 ${amountCell} · 票 ${invoicedCell} · 缺口 ${invGapCell} · 款 ${paidCell}/${payGapCell}`);

  // 缺口用红字（td.is-gap）
  const gapRed = await page.evaluate((cid) => {
    const row = document.querySelector(`[data-twm-row="${cid}"]`);
    const cells = [...row.children];
    const color = getComputedStyle(cells[5]).color;
    return { cls: cells[5].className, color };
  }, CID);
  if (!/185,\s*28,\s*28/.test(gapRed.color)) fail('表格里的缺口是红字', gapRed.color);
  ok('表格缺口红字', gapRed.color);

  // —— 4. 状态灯 ——
  const statusCell = await page.evaluate((cid) => {
    const node = document.querySelector(`[data-twm-status-cell="${cid}"]`);
    return node ? { text: node.textContent.trim(), cls: node.className } : null;
  }, CID);
  if (!statusCell) fail('有状态灯');
  if (statusCell.text !== '票款均未齐') fail('状态文案 = 票款均未齐', statusCell.text);
  if (!statusCell.cls.includes('is-bad')) fail('双缺状态标红', statusCell.cls);
  ok('状态灯正确', `${statusCell.text}（红）`);

  // —— 5/6. 抽屉 ——
  await page.click(`[data-twm-view="${CID}"]`);
  await sleep(2000);

  const drawer = await page.evaluate(() => {
    const root = document.querySelector('[data-twm-drawer]');
    if (!root) return { ok: false };
    const text = root.textContent || '';
    return {
      ok: true,
      hasCards: root.querySelectorAll('.twm-drawer__cards > div').length,
      itemRows: root.querySelectorAll('.twm-drawer__table tbody tr').length,
      timelineItems: root.querySelectorAll('[data-twm-timeline] .twm-timeline__item').length,
      mentionsEstimate: text.includes('按单位估算'),
      mentionsUnlinked: text.includes('还没转成单据'),
      hasInvoice: text.includes('E2E-TWM-'),
    };
  });
  if (!drawer.ok) fail('点「查看」滑出明细抽屉', '没有 [data-twm-drawer]');
  ok('点「查看」滑出明细抽屉', `${drawer.hasCards} 张汇总卡`);
  if (drawer.itemRows < 1) fail('抽屉里有合同明细表', `${drawer.itemRows} 行`);
  ok('抽屉里有合同明细', `${drawer.itemRows} 行`);
  if (drawer.timelineItems < 1) fail('抽屉里有时间线条目', `${drawer.timelineItems} 条`);
  ok('抽屉里有时间线', `${drawer.timelineItems} 条`);
  if (!drawer.mentionsEstimate) fail('票/款标注了「按单位估算」');
  ok('票/款标注来源', '含「按单位估算」');
  if (!drawer.mentionsUnlinked) fail('未转单合同有提示');
  ok('未转单合同有明确提示');

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_three_way_drawer.png') });
  console.log('  📸 e2e_three_way_drawer.png');

  await page.click('[data-twm-drawer-close]');
  await sleep(700);

  // —— 7. 状态筛选 ——
  await page.select('[data-twm-status]', 'both_missing');
  await page.click('[data-twm-query]');
  await sleep(1800);
  const filtered = await page.evaluate(() => {
    const cells = [...document.querySelectorAll('[data-twm-status-cell]')].map((n) => n.textContent.trim());
    return { count: cells.length, labels: [...new Set(cells)] };
  });
  if (filtered.labels.some((label) => label !== '票款均未齐')) {
    fail('状态筛选生效', JSON.stringify(filtered.labels));
  }
  ok('状态筛选生效', `${filtered.count} 行，全部是「票款均未齐」`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_three_way_board.png') });
  console.log('  📸 e2e_three_way_board.png');

  // 清理
  await api('DELETE', `/api/v1/invoices/${invoice.data.id}`);
  await api('DELETE', `/api/v1/contracts/${CID}?force=true`);
  await api('DELETE', `/api/v1/products/${product.data.id}?force=true`);
  await api('DELETE', `/api/v1/customers/${customer.data.id}`);
  ok('已清理验收数据');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_three_way.png') });
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
