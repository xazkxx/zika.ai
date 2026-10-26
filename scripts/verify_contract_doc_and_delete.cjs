/**
 * 购销合同：删除二次确认 + 内置范本正文生成/导出（2026-10-22，2026-10-23 换成简易版）
 *
 * 注意页面归属（踩过一次）：
 *   · 「购销合同」→ `pages/ContractsPage.jsx`（左侧录入区 + 右侧列表，本次改这里）
 *   · 「合同台账」→ `components/contracts/ContractsLedger.jsx`（另一个页面，也补了删除）
 * 脚本走的是「购销合同」。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_contract_doc_and_delete.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8019';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const DOWN_DIR = path.join(SHOT_DIR, 'tmp_download');
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

/** ErpSearchSelect：点 trigger → 输入关键字 → 真实坐标点选项 */
async function pickFromSelect(scopeSelector, keyword) {
  const opened = await page.evaluate((sel) => {
    const box = document.querySelector(sel);
    const trigger = box && box.querySelector('.ssel-trigger');
    if (!trigger) return false;
    trigger.click();
    return true;
  }, scopeSelector);
  if (!opened) return false;
  await sleep(450);
  await page.evaluate(
    ({ sel, text }) => {
      const input = document.querySelector(`${sel} .ssel-input`);
      if (!input) return;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    },
    { sel: scopeSelector, text: keyword },
  );
  await sleep(650);
  const box = await page.evaluate((text) => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    const hit = panels
      .flatMap((panel) => [...panel.querySelectorAll('.ssel-option')])
      .find((item) => (item.textContent || '').includes(text));
    if (!hit) return null;
    const rect = hit.getBoundingClientRect();
    return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
  }, keyword);
  if (!box) return false;
  await page.mouse.click(box.x, box.y);
  await sleep(500);
  return true;
}

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  const customer = await api('POST', '/api/v1/customers', {
    code: `CUST-CD${TAG}`,
    name: `测试合同客户${TAG}`,
    tax_no: `91610103CD${TAG}`,
    address: '西安市雁塔区示例路 1 号',
  });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);

  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-CD${TAG}`,
    name: `测试电缆${TAG}`,
    unit: '米',
    standards: 'YJV-3x35',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);

  const created = await api('POST', '/api/v1/contracts', {
    direction: 'out',
    party_name: customer.data.name,
    party_tax_no: customer.data.tax_no,
    sign_date: TODAY,
    delivery_date: '2026-11-01',
    delivery_place: '工地现场',
    items: [{ product_id: product.data.id, quantity: 100, unit_price: 12.5 }],
  });
  if (created.status !== 201) throw new Error(`建合同失败 ${JSON.stringify(created.data)}`);
  const contract = created.data;
  ok('准备：客户 / 商品 / 一张合同', `${contract.contract_no} · ¥${contract.total_amount}`);

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1680, height: 1000 },
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
      (e) => (e.textContent || '').trim() === '购销合同',
    );
    if (item) item.click();
  });
  await sleep(2400);

  // ================= 1. 删除按钮 + 二次确认 =================
  const hasDelete = await page.evaluate(
    (id) => Boolean(document.querySelector(`[data-contract-delete="${id}"]`)),
    contract.id,
  );
  if (!hasDelete) fail('合同列表每行有「删除」按钮', '找不到 data-contract-delete');
  ok('合同列表每行有「删除」按钮');

  await page.evaluate((id) => document.querySelector(`[data-contract-delete="${id}"]`).click(), contract.id);
  await sleep(900);
  const confirmState = await page.evaluate(() => {
    const card = document.querySelector('.modal-backdrop .modal-card');
    const text = card ? card.textContent : '';
    return {
      visible: Boolean(card) && text.includes('删除确认'),
      hasCancel: /取消/.test(text),
      hasConfirm: /确认删除/.test(text),
      mentionsFile: /原件/.test(text),
    };
  });
  if (!confirmState.visible) fail('点删除弹出「删除确认」', '没看到确认框');
  if (!confirmState.hasCancel || !confirmState.hasConfirm) {
    fail('确认框同时有「取消」与「确认删除」', JSON.stringify(confirmState));
  }
  ok('点删除弹出二次确认', confirmState.mentionsFile ? '提示含原件一并删除' : '');

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_delete_confirm.png') });
  console.log('  📸 e2e_contract_delete_confirm.png');

  // 取消 → 合同还在
  await page.evaluate(() => {
    const card = document.querySelector('.modal-backdrop .modal-card');
    const btn = [...card.querySelectorAll('button')].find((b) => (b.textContent || '').includes('取消'));
    btn.click();
  });
  await sleep(800);
  if ((await api('GET', `/api/v1/contracts/${contract.id}`)).status !== 200) {
    fail('点「取消」后合同仍在', '合同被删了');
  }
  ok('点「取消」后合同仍在（没误删）');

  // 再点删除 → 确认 → 真删
  await page.evaluate((id) => document.querySelector(`[data-contract-delete="${id}"]`).click(), contract.id);
  await sleep(800);
  await page.evaluate(() => {
    const card = document.querySelector('.modal-backdrop .modal-card');
    const btn = [...card.querySelectorAll('button')].find((b) => (b.textContent || '').includes('确认删除'));
    btn.click();
  });
  await sleep(2200);
  if ((await api('GET', `/api/v1/contracts/${contract.id}`)).status !== 404) {
    fail('确认后合同真的删掉', '服务端还能查到');
  }
  ok('确认后合同真的删掉（服务端 404）');

  // ================= 2. 生成合同正文 =================
  const hasDocBtn = await page.evaluate(() => Boolean(document.querySelector('[data-contract-doc]')));
  if (!hasDocBtn) fail('录入区有「生成合同正文」按钮', '找不到 data-contract-doc');
  ok('录入区有「生成合同正文」按钮');

  const partyOk = await pickFromSelect('.erp-form .ssel', customer.data.name);
  if (!partyOk) fail('选中客户', customer.data.name);
  ok('选中客户', customer.data.name);

  const productOk = await pickFromSelect('.contract-item-row .ssel', product.data.name);
  if (!productOk) fail('选中商品', product.data.name);

  // 数量 / 单价
  await page.evaluate(() => {
    const set = (el, val) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const row = document.querySelector('.contract-item-row .ssel')?.closest('.contract-item-row');
    const inputs = row ? [...row.querySelectorAll('input[type="number"]')] : [];
    if (inputs[0]) set(inputs[0], '100');
    if (inputs[1]) set(inputs[1], '12.5');
  });
  await sleep(600);
  ok('填好明细（商品 / 数量 / 单价）');

  await page.click('[data-contract-doc]');
  await sleep(2800);

  const doc = await page.evaluate(() => {
    const root = document.querySelector('[data-contract-doc-preview]');
    if (!root) return { ok: false };
    const text = root.textContent || '';
    return {
      ok: true,
      // 2026-10-23：内置范本换成客户在用的《产品买卖合同（简易版）》
      title: text.includes('产品买卖合同（简易版）'),
      oldTitle: text.includes('工矿产品购销合同'),
      clauses: root.querySelectorAll('.cledger__doc-clauses section').length,
      headings: [...root.querySelectorAll('.cledger__doc-clauses h4')].map((h) => h.textContent.trim()),
      items: root.querySelectorAll('.cledger__doc-items tbody tr').length,
      buyer: text.includes('甲方'),
      seller: text.includes('乙方'),
      signs: root.querySelectorAll('.cledger__doc-sign > div').length,
      amount: (root.querySelector('.cledger__doc-items tfoot td:last-child')?.textContent || '').trim(),
      // 简易版措辞是「交货期限 / 交货地点」（详细版才是「交货时间」）
      mentionsDelivery: text.includes('交货期限') && text.includes('交货地点'),
    };
  });
  if (!doc.ok) fail('点「生成合同正文」弹出预览', '没有 [data-contract-doc-preview]');
  ok('点「生成合同正文」弹出预览');
  if (!doc.title) fail('标题是《产品买卖合同（简易版）》', doc.headings.join(' / '));
  if (doc.oldTitle) fail('不再挂着《工矿产品购销合同》的标题');
  if (doc.clauses !== 8) fail('条款正好 8 条', `实际 ${doc.clauses} 条`);
  ok('条款齐全（简易版 8 条）', doc.headings.join(' / '));
  if (doc.items < 1) fail('明细已带入正文', `${doc.items} 行`);
  ok('明细已带入正文', `${doc.items} 行 · 合计 ${doc.amount}`);
  if (doc.signs < 2) fail('甲乙双方签字栏', `${doc.signs} 个`);
  ok('甲乙双方签字栏齐全', `${doc.signs} 个`);
  if (!doc.mentionsDelivery) fail('第四条带出了交货期限与交货地点');

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_document.png') });
  console.log('  📸 e2e_contract_document.png');

  // ================= 3. 导出 PDF =================
  fs.rmSync(DOWN_DIR, { recursive: true, force: true });
  fs.mkdirSync(DOWN_DIR, { recursive: true });
  const cdp = await page.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: DOWN_DIR.replace(/\//g, '\\'),
  });
  await page.click('[data-contract-doc-pdf]');
  await sleep(3400);
  const pdfs = fs.readdirSync(DOWN_DIR).filter((name) => name.toLowerCase().endsWith('.pdf'));
  if (!pdfs.length) fail('导出 PDF 真落盘', `目录里只有：${fs.readdirSync(DOWN_DIR).join(',') || '空'}`);
  const pdfPath = path.join(DOWN_DIR, pdfs[0]);
  const head = fs.readFileSync(pdfPath).subarray(0, 4).toString('latin1');
  if (head !== '%PDF') fail('下载的是真 PDF', `文件头 ${head}`);
  ok('导出 PDF 真落盘', `${pdfs[0]} · ${(fs.statSync(pdfPath).size / 1024).toFixed(0)} KB`);

  // 收尾
  await api('DELETE', `/api/v1/customers/${customer.data.id}`);
  await api('DELETE', `/api/v1/products/${product.data.id}`);
  fs.rmSync(DOWN_DIR, { recursive: true, force: true });

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_contract_doc.png') });
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
