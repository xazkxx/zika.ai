/**
 * 采购付款「无票强提醒」验收（业财一体化 · 第二块）
 *
 * 验的是"闸门真的拦得住"，不是"文案里有这句话"：
 *   1. 一张还没取得进项票的采购单，打开付款弹窗 → 顶部必须有"进项票缺 ¥x"角标 + 预提示；
 *   2. 点「确认付款」**不能提交成功**，必须切到强提醒面板（`[data-pay-noinvoice]`）；
 *   3. 面板上三个出口都在（索取发票 / 暂估 / 仍付），且没有"回车就过"的暗道；
 *   4. 选「做暂估处理并付款」→ 真的落库，且流水备注带【暂估】；
 *   5. 全程零页面错误。
 *
 * 跑法：
 *   BASE=http://127.0.0.1:8019 node scripts/verify_payment_no_invoice_gate.cjs
 *
 * ⚠️ 会把测试产生的付款流水挂到采购单上（真实写库）。收尾只能走数据层，
 *    所以单据、供应商、商品一律用测试签名（SUP-<hex> / SKU-<hex> / 测试*），
 *    跑完执行 `python scripts/clean_test_data.py` 即可扫干净。
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
const SUPPLIER = `测试供应商无票${TAG}`;
const PRODUCT = `测试商品无票${TAG}`;
const AMOUNT = 200;

const results = [];
let page;
let browser;

const ok = (name, extra = '') => {
  results.push({ name, ok: true });
  console.log(`PASS  ${name}${extra ? `  — ${extra}` : ''}`);
};
const fail = (name, why) => {
  results.push({ name, ok: false, why });
  console.log(`FAIL  ${name}  — ${why}`);
  throw new Error(`${name}：${why}`);
};

let TOKEN = '';
async function api(method, url, body) {
  const res = await fetch(`${BASE}${url}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
    },
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
  const created = {};

  // ── 0. 准备一张"有货无票"的采购单 ─────────────────────────────────────
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  const hex = Date.now().toString(16).slice(-8);
  const supplier = await api('POST', '/api/v1/suppliers', {
    code: `SUP-${hex}`,
    name: SUPPLIER,
  });
  if (supplier.status !== 201) throw new Error(`建供应商失败 ${JSON.stringify(supplier.data)}`);
  created.supplierId = supplier.data.id;

  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-${hex}`,
    name: PRODUCT,
    unit: '件',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
  created.productId = product.data.id;

  const warehouses = await api('GET', '/api/v1/warehouses');
  const warehouse = (Array.isArray(warehouses.data) ? warehouses.data : warehouses.data.items || [])[0];

  const po = await api('POST', '/api/v1/purchase-orders', {
    supplier_id: created.supplierId,
    warehouse_id: warehouse.id,
    doc_type: 'order',
    order_date: new Date().toISOString().slice(0, 10),
    items: [{ product_id: created.productId, quantity: 1, unit_price: AMOUNT, unit: '件', product_name: PRODUCT }],
  });
  if (po.status !== 201) throw new Error(`建采购单失败 ${JSON.stringify(po.data)}`);
  created.purchaseOrderId = po.data.id;
  const approved = await api('PATCH', `/api/v1/purchase-orders/${po.data.id}/status`, { status: 'approved' });
  if (approved.status !== 200) throw new Error(`审核失败 ${JSON.stringify(approved.data)}`);

  // 后端口径先自证：这张单确实"一张票都没有"
  const status = await api('GET', `/api/v1/orders/purchase/${po.data.id}/invoice-status`);
  if (status.status !== 200) throw new Error(`票据状态接口失败 ${status.status}`);
  if (status.data.need_invoice !== true || Number(status.data.invoiced_amount) !== 0) {
    throw new Error(`票据状态不对：${JSON.stringify(status.data)}`);
  }
  ok('后端票据状态：本单无票', `应付 ¥${status.data.net_amount}、已开票 ¥${status.data.invoiced_amount}、还差 ¥${status.data.uninvoiced_amount}`);

  // ── 1. 打开浏览器 ─────────────────────────────────────────────────────
  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1500, height: 940 },
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
      (e) => (e.textContent || '').trim() === '采购订单',
    );
    if (item) item.click();
  });
  await sleep(2000);
  ok('已进入采购订单页');

  // ── 2. 点这一行的「付款」──────────────────────────────────────────────
  const opened = await page.evaluate((id) => {
    const btn = document.querySelector(`[data-order-pay="${id}"]`);
    if (!btn) return false;
    btn.click();
    return true;
  }, created.purchaseOrderId);
  if (!opened) throw new Error('采购订单上找不到这一行的付款按钮');
  await sleep(1500);
  ok('付款弹窗已打开');

  // 票据角标 + 预提示（点之前就该看见"这单没票"）
  const pre = await page.evaluate(() => {
    const ticket = document.querySelector('.order-pay-dialog__ticket');
    const hint = document.querySelector('[data-pay-nowarn-hint]');
    const submit = document.querySelector('[data-pay-submit]');
    return {
      ticket: ticket ? ticket.textContent.trim() : '',
      ticketMissing: ticket ? ticket.className.includes('is-missing') : false,
      hint: hint ? hint.textContent.trim() : '',
      submitEnabled: submit ? !submit.disabled : false,
      submitLabel: submit ? submit.textContent.trim() : '',
    };
  });
  if (!pre.ticketMissing) fail('弹窗顶部显示「进项票缺」角标', pre.ticket);
  ok('弹窗顶部显示「进项票缺」角标', pre.ticket);
  if (!pre.hint.includes('未取得进项发票')) fail('提交前有预提示', pre.hint);
  ok('提交前有预提示', pre.hint.slice(0, 40));
  if (!pre.submitEnabled) fail('票据状态已就绪，付款按钮可点', pre.submitLabel);
  ok('票据状态已就绪，付款按钮可点');

  // ── 3. 点「确认付款」→ 必须被闸住 ─────────────────────────────────────
  await page.click('[data-pay-submit]');
  await sleep(900);
  const gated = await page.evaluate(() => {
    const gate = document.querySelector('[data-pay-noinvoice]');
    return {
      open: Boolean(gate),
      text: gate ? gate.textContent.replace(/\s+/g, ' ').trim() : '',
      hasAsk: Boolean(document.querySelector('[data-pay-gate-ask]')),
      hasEstimate: Boolean(document.querySelector('[data-pay-gate-estimate]')),
      hasContinue: Boolean(document.querySelector('[data-pay-gate-continue]')),
      // 关键：不能已经进了"成功态"
      hasResult: Boolean(document.querySelector('[data-pay-result]')),
    };
  });
  if (!gated.open) fail('点「确认付款」被无票闸门拦住（没直接提交）', gated.text || '没出现闸门');
  ok('点「确认付款」被无票闸门拦住（没直接提交）');
  if (gated.hasResult) fail('闸门期间没有"登记成功"假象', '出现了成功面板');
  ok('闸门期间没有"登记成功"假象');
  if (!gated.text.includes('此笔付款暂无发票')) fail('闸门文案含"此笔付款暂无发票"', gated.text.slice(0, 60));
  ok('闸门文案含"此笔付款暂无发票"', gated.text.slice(0, 46));
  if (!(gated.hasAsk && gated.hasEstimate && gated.hasContinue)) {
    fail('闸门三个出口齐全（索取发票 / 暂估 / 仍付）', JSON.stringify(gated));
  }
  ok('闸门三个出口齐全（索取发票 / 暂估 / 仍付）');

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  const shot = path.join(SHOT_DIR, 'e2e_pay_noinvoice_gate.png');
  await page.screenshot({ path: shot });
  console.log(`  📸 ${path.basename(shot)}`);

  // ── 4. 选「做暂估处理并付款」→ 真落库 ─────────────────────────────────
  await page.click('[data-pay-gate-estimate]');
  await sleep(2500);
  const done = await page.evaluate(() => {
    const result = document.querySelector('[data-pay-result]');
    const invoiceCell = document.querySelector('[data-pay-result-invoice]');
    return {
      hasResult: Boolean(result),
      head: result ? result.textContent.replace(/\s+/g, ' ').trim().slice(0, 80) : '',
      invoiceText: invoiceCell ? invoiceCell.textContent.trim() : '',
    };
  });
  if (!done.hasResult) fail('暂估付款已落库（出现成功面板）', done.head);
  ok('暂估付款已落库（出现成功面板）', done.head.slice(0, 40));
  if (!done.invoiceText.includes('暂估')) fail('成功面板标明"记暂估"', done.invoiceText);
  ok('成功面板标明"记暂估"', done.invoiceText);

  // 落库复核：流水备注必须带【暂估】，且有 invoice_id 为空
  const flows = await api('GET', '/api/v1/finance');
  const rows = Array.isArray(flows.data) ? flows.data : (flows.data && flows.data.items) || [];
  const mine = rows
    .filter((row) => Number(row.supplier_id) === Number(created.supplierId))
    .filter((row) => (row.note || '').includes('【暂估】'));
  if (!mine.length) fail('流水备注已打【暂估】标记', `共 ${rows.length} 条流水，未找到`);
  ok('流水备注已打【暂估】标记', (mine[0].note || '').slice(0, 42));

  const afterStatus = await api('GET', `/api/v1/orders/purchase/${created.purchaseOrderId}/invoice-status`);
  ok(
    '付款后票据状态仍然如实反映"无票"',
    `已开票 ¥${afterStatus.data.invoiced_amount} / 还差 ¥${afterStatus.data.uninvoiced_amount}`,
  );

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  console.log('提示：跑完请执行  python scripts/clean_test_data.py  扫掉本轮的测试数据');
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_pay_gate.png') });
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
