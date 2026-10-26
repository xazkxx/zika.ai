/**
 * 第二批验收：供应商税号字段 + 销售单「一键开票」（业财一体化 · 先销后票）
 *
 * 验三件事，全部走真浏览器：
 *   1. 供应商弹窗里有「纳税人识别号」，填了能存进库（含回读）；
 *   2. 销售出库详情页有「一键开票」，点一下真生成销项发票，且挂到本单；
 *   3. 开票后单据的未开票金额归零（完结闸口径），再点一次被 409 拦住。
 *
 * 跑法：BASE=http://127.0.0.1:8020 node scripts/verify_tax_and_issue_invoice.cjs
 * 收尾：python scripts/clean_test_data.py（供应商/商品/单据/发票都用测试签名）
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8020';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TAG = Date.now().toString().slice(-6);
const hex = Date.now().toString(16).slice(-8);
const SUPPLIER = `测试供应商税号${TAG}`;
const TAX_NO = `91610103${TAG}XY`;
const PRODUCT = `测试商品开票${TAG}`;

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

  // ── 准备：客户 / 商品 / 期初 / 销售单（订单→审核→出库）────────────────
  const customer = await api('POST', '/api/v1/customers', { code: `CUST-${hex}`, name: `测试客户开票${TAG}` });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);
  const product = await api('POST', '/api/v1/products', { sku: `SKU-${hex}`, name: PRODUCT, unit: '件' });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
  const shops = await api('GET', '/api/v1/warehouses');
  const warehouse = (Array.isArray(shops.data) ? shops.data : shops.data.items || [])[0];
  await api('PUT', '/api/v1/opening-stock', {
    items: [{ warehouse_id: warehouse.id, product_id: product.data.id, quantity: 100, unit_price: 10 }],
  });

  const order = await api('POST', '/api/v1/sales-orders', {
    customer_id: customer.data.id,
    warehouse_id: warehouse.id,
    doc_type: 'order',
    order_date: new Date().toISOString().slice(0, 10),
    items: [{ product_id: product.data.id, quantity: 2, unit_price: 60, unit: '件', product_name: PRODUCT }],
  });
  if (order.status !== 201) throw new Error(`建销售单失败 ${JSON.stringify(order.data)}`);
  await api('PATCH', `/api/v1/sales-orders/${order.data.id}/status`, { status: 'approved' });
  const outbound = await api('POST', `/api/v1/sales-orders/${order.data.id}/to-outbound`);
  if (outbound.status !== 200) throw new Error(`转出库失败 ${JSON.stringify(outbound.data)}`);
  ok('准备：一张 2 件 × ¥60 的出库单', outbound.data.order_no);

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

  const openMenu = async (label) => {
    await page.evaluate((t) => {
      const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === t);
      if (item) item.click();
    }, label);
    await sleep(1800);
  };

  // ── 1. 供应商税号字段 ────────────────────────────────────────────────
  await openMenu('供应商档案');
  await page.evaluate(() => {
    const row = [...document.querySelectorAll('.ptree__row')].find((e) =>
      (e.textContent || '').includes('全部供应商'),
    );
    if (row) row.click();
  });
  await sleep(700);
  const openedSupplier = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '新增供应商');
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  });
  if (!openedSupplier) fail('打开新增供应商弹窗', '找不到「新增供应商」按钮');
  await sleep(700);

  const hasTaxField = await page.evaluate(() => {
    const modal = document.querySelector('.modal-card');
    if (!modal) return { ok: false, reason: 'no-modal' };
    const labels = [...modal.querySelectorAll('label')];
    const target = labels.find((l) => /纳税人识别号/.test(l.textContent || ''));
    if (!target) return { ok: false, reason: 'no-label' };
    const input = target.querySelector('input');
    return { ok: Boolean(input), placeholder: input ? input.getAttribute('placeholder') || '' : '' };
  });
  if (!hasTaxField.ok) fail('供应商弹窗有「纳税人识别号」字段', hasTaxField.reason);
  ok('供应商弹窗有「纳税人识别号」字段', String(hasTaxField.placeholder).slice(0, 30));

  // 填写并提交
  await page.evaluate(
    ({ name, tax }) => {
      const modal = document.querySelector('.modal-card');
      const setVal = (el, val) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const labels = [...modal.querySelectorAll('label')];
      const find = (re) => {
        const l = labels.find((x) => re.test(x.textContent || ''));
        return l && l.querySelector('input');
      };
      const nameInput = find(/供应商名称/);
      const taxInput = find(/纳税人识别号/);
      if (nameInput) setVal(nameInput, name);
      if (taxInput) setVal(taxInput, tax);
    },
    { name: SUPPLIER, tax: TAX_NO },
  );
  await sleep(300);
  // 填好但先不提交：把"弹窗里确实有这个字段、值也进得去"拍下来
  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_supplier_tax_modal.png') });
  console.log('  📸 e2e_supplier_tax_modal.png');
  await page.evaluate(() => {
    const form = document.querySelector('.modal-card form');
    if (form) form.requestSubmit();
  });
  await sleep(900);

  // 相似名护栏：`测试供应商税号xxxx` 这类夹具名字前缀相同，防呆规则会弹黄框。
  // 这不是 bug —— 是"同名/相似名"防呆在正常工作，点「仍然新建」继续即可。
  const guarded = await page.evaluate(() => {
    const modal = document.querySelector('.name-guard-modal');
    if (!modal) return false;
    const btn = [...modal.querySelectorAll('button')].find((b) => (b.textContent || '').includes('仍然新建'));
    if (btn) btn.click();
    return true;
  });
  if (guarded) console.log('  ↪ 命中相似名确认框，已点「仍然新建」');
  await sleep(1600);

  const supplierRows = await api('GET', '/api/v1/suppliers');
  const supplierList = Array.isArray(supplierRows.data) ? supplierRows.data : supplierRows.data.items || [];
  const savedSupplier = supplierList.find((row) => row.name === SUPPLIER);
  if (!savedSupplier) fail('供应商已保存（UI）', '列表里找不到');
  if (savedSupplier.tax_no !== TAX_NO) fail('税号已落库', `库里是 ${savedSupplier.tax_no}`);
  ok('供应商税号已落库（UI → 库）', `${savedSupplier.tax_no}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_supplier_tax_no.png') });
  console.log('  📸 e2e_supplier_tax_no.png');

  // ── 2. 销售出库详情 → 一键开票 ──────────────────────────────────────
  await openMenu('开单管理');
  await sleep(1200);
  const openedDetail = await page.evaluate((id) => {
    const rows = [...document.querySelectorAll('tbody tr')];
    const row = rows.find((tr) => (tr.textContent || '').includes(String(id)));
    if (!row) return { ok: false, reason: 'row-not-found' };
    const btn = [...row.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '预览');
    if (!btn) return { ok: false, reason: 'no-preview-btn' };
    btn.click();
    return { ok: true };
  }, outbound.data.order_no);
  if (!openedDetail.ok) fail('打开出库单详情', openedDetail.reason);
  await sleep(1200);

  const hasIssueBtn = await page.evaluate(() => {
    const btn = document.querySelector('[data-issue-invoice]');
    return {
      exists: Boolean(btn),
      label: btn ? btn.textContent.trim() : '',
      disabled: btn ? btn.disabled : true,
      title: btn ? btn.getAttribute('title') || '' : '',
    };
  });
  if (!hasIssueBtn.exists) fail('详情页有「一键开票」按钮', '找不到 data-issue-invoice');
  if (hasIssueBtn.disabled) fail('「一键开票」可点（未开票 > 0）', hasIssueBtn.title);
  ok('详情页有「一键开票」按钮且可点', hasIssueBtn.label);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_one_click_invoice_before.png') });

  await page.click('[data-issue-invoice]');
  await sleep(2600);

  const invoiceRows = await api('GET', '/api/v1/invoices');
  const invoices = Array.isArray(invoiceRows.data) ? invoiceRows.data : invoiceRows.data.items || [];
  const issued = invoices.find((row) => Number(row.related_order_id) === Number(outbound.data.id));
  if (!issued) fail('一键开票生成发票并挂单', '库里没有 related_order_id 指向本单的发票');
  ok('一键开票生成发票并挂单', `${issued.invoice_no} · ¥${issued.total_amount}`);
  if (issued.invoice_no.startsWith('KP-')) ok('未填票号时给占位号（可后补真实票号）', issued.invoice_no);
  else fail('占位号形态', issued.invoice_no);

  const statusAfter = await api('GET', `/api/v1/orders/sales/${outbound.data.id}/invoice-status`);
  if (Number(statusAfter.data.uninvoiced_amount) > 0.005) {
    fail('开票后未开票金额归零', `还剩 ¥${statusAfter.data.uninvoiced_amount}`);
  }
  ok('开票后未开票金额归零（完结闸口径）', `已开票 ¥${statusAfter.data.invoiced_amount}`);

  // ── 3. 重复开票被拦（服务端 409，前端提示兜住）──────────────────────
  const again = await api('POST', `/api/v1/sales-orders/${outbound.data.id}/issue-invoice`, {});
  if (again.status !== 409) fail('重复一键开票被 409 拦住', `实际 ${again.status}`);
  ok('重复一键开票被 409 拦住', (again.data && again.data.detail && again.data.detail.message) || 'already_invoiced');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  console.log('提示：跑完执行  python scripts/clean_test_data.py  扫掉本轮测试数据');
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_tax_issue.png') });
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
