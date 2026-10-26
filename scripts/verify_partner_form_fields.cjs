/**
 * 客户/供应商「开票信息」字段验收 —— 2026-10-23
 *
 * 验七件事：
 *   1. 「新增客户」弹窗里**没有**「客户级别」，多了税号/开户行/银行账号/开票电话四列；
 *   2. 填好保存 → 接口里四个值都真的落库；
 *   3. 点「编辑」重新打开 → 四个值都回填（不是保存了但页面读不出来）；
 *   4. 用这个客户建一份合同 → 正文（简易版范本）抬头带出税号/开户行/账号，
 *      且电话取的是**开票电话**而不是手机；
 *   5. 「新增供应商」弹窗同样有四列，保存后接口可读；
 *   6. 收尾：合同、客户、供应商删干净。
 *
 * 跑法：BASE=http://127.0.0.1:8022 node scripts/verify_partner_form_fields.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || process.env.ERP_BASE || 'http://127.0.0.1:8022';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const TAG = Date.now().toString().slice(-6);
const TODAY = new Date().toISOString().slice(0, 10);
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

/** 提交后可能弹"相似名称"黄框（名称防呆）：点「仍然新建」继续。
 *  这个框是产品行为，不是 bug —— 上一轮验收残留的名字和本轮只差几个数字，正好会触发。 */
async function passNameGuard() {
  await sleep(400);
  const guard = await page.$('.name-guard-modal');
  if (!guard) return false;
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.name-guard-modal button')].find((b) =>
      (b.textContent || '').includes('仍然新建'),
    );
    if (btn) btn.click();
  });
  await sleep(600);
  return true;
}

async function openMenu(name) {
  const direct = await page.evaluate((n) => {
    const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
    if (!item) return false;
    item.click();
    return true;
  }, name);
  if (direct) {
    await sleep(1800);
    return true;
  }
  const groups = await page.$$('.nav-group-title');
  for (const group of groups) {
    await group.click();
    await sleep(250);
    const hit = await page.evaluate((n) => {
      const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
      if (!item) return false;
      item.click();
      return true;
    }, name);
    if (hit) {
      await sleep(1800);
      return true;
    }
  }
  return false;
}

/** 受控输入框：原生 setter + input 事件 */
async function setField(key, value) {
  await page.evaluate(
    (field, text) => {
      const input = document.querySelector(`[data-partner-field="${field}"]`);
      if (!input) return;
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    },
    key,
    value,
  );
  await sleep(80);
}

const modalFields = () =>
  page.evaluate(() => {
    const modal = document.querySelector('[data-partner-modal]');
    if (!modal) return null;
    const labels = [...modal.querySelectorAll('label')].map((label) =>
      (label.textContent || '').trim().replace(/\s+/g, ''),
    );
    const keys = [...modal.querySelectorAll('[data-partner-field]')].map((el) =>
      el.getAttribute('data-partner-field'),
    );
    return { labels, keys, text: (modal.textContent || '').replace(/\s+/g, '') };
  });

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

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

  // —— 1. 客户弹窗字段 ——
  if (!(await openMenu('客户档案'))) fail('打开「客户档案」', '找不到菜单');
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim().includes('新增客户'));
    if (btn) btn.click();
  });
  await page.waitForSelector('[data-partner-modal="customer"]', { timeout: 10000 });
  await sleep(500);

  const custModal = await modalFields();
  if (!custModal) fail('客户弹窗打开', '没有 [data-partner-modal]');
  if (custModal.labels.some((label) => label.includes('客户级别'))) {
    fail('「客户级别」已移除', custModal.labels.join(' / '));
  }
  for (const key of ['tax_no', 'bank_name', 'bank_account', 'invoice_phone']) {
    if (!custModal.keys.includes(key)) fail(`客户弹窗有 ${key} 字段`, custModal.keys.join(','));
  }
  ok('客户弹窗：级别已删、四个开票字段都在', custModal.keys.join(' · '));

  // —— 2. 填 + 存 ——
  const custName = `验收开票客户${TAG}`;
  await setField('name', custName);
  await setField('tax_no', '91610103MA6TX8K23Q');
  await setField('bank_name', '招商银行西安分行');
  await setField('bank_account', '1298888666601');
  await setField('invoice_phone', '029-88886666');
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_partner_form_customer.png') });
  console.log('  📸 e2e_partner_form_customer.png');

  await page.evaluate(() => {
    const btn = document.querySelector('[data-partner-modal="customer"] button[type="submit"]');
    if (btn) btn.click();
  });
  await passNameGuard();
  for (let i = 0; i < 40; i += 1) {
    if (!(await page.$('[data-partner-modal="customer"]'))) break;
    await sleep(300);
  }
  if (await page.$('[data-partner-modal="customer"]')) fail('保存后弹窗关闭', '可能保存失败');
  await sleep(800);

  const list = await api('GET', '/api/v1/customers?limit=500');
  const rows = Array.isArray(list.data) ? list.data : list.data?.items || [];
  const saved = rows.find((row) => row.name === custName);
  if (!saved) fail('新客户已入库', '列表里找不到');
  const checks = {
    tax_no: '91610103MA6TX8K23Q',
    bank_name: '招商银行西安分行',
    bank_account: '1298888666601',
    invoice_phone: '029-88886666',
  };
  for (const [key, expected] of Object.entries(checks)) {
    if (saved[key] !== expected) fail(`${key} 已落库`, `${saved[key]} ≠ ${expected}`);
  }
  ok('四个开票字段都真的存进去了', `客户 #${saved.id}`);

  // —— 3. 编辑回填 ——
  // ⚠️ 客户档案页的右表默认是**空的**（首屏提示"请先在左侧选择一个分类"），
  //    刚保存的客户不会自动出现在右表里 —— 必须先点左侧「全部客户」。
  await page.evaluate(() => {
    const row = document.querySelector('.ptree__row--all');
    if (row) row.click();
  });
  await sleep(1500);

  await page.evaluate((name) => {
    const row = [...document.querySelectorAll('tr')].find((tr) => (tr.textContent || '').includes(name));
    if (!row) return;
    const btn = [...row.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '编辑');
    if (btn) btn.click();
  }, custName);
  await page.waitForSelector('[data-partner-modal="customer"]', { timeout: 8000 });
  await sleep(500);
  const filled = await page.evaluate(() => {
    const read = (key) => document.querySelector(`[data-partner-field="${key}"]`)?.value || '';
    return {
      tax_no: read('tax_no'),
      bank_name: read('bank_name'),
      bank_account: read('bank_account'),
      invoice_phone: read('invoice_phone'),
    };
  });
  for (const [key, expected] of Object.entries(checks)) {
    if (filled[key] !== expected) fail(`编辑态回填 ${key}`, `${filled[key]} ≠ ${expected}`);
  }
  ok('编辑弹窗把四个字段都回填了');
  await page.click('[data-partner-modal="customer"] .close-btn');
  await sleep(400);

  // —— 4. 合同正文自动带出 ——
  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-FIELD${TAG}`,
    name: `验收开票商品${TAG}`,
    unit: '件',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
  const contract = await api('POST', '/api/v1/contracts', {
    direction: 'out',
    party_id: saved.id,
    party_name: saved.name,
    sign_date: TODAY,
    items: [{ product_id: product.data.id, quantity: 1, unit_price: 100 }],
  });
  if (contract.status !== 201) throw new Error(`建合同失败 ${JSON.stringify(contract.data)}`);

  const preview = await api('POST', '/api/v1/contracts/document/preview', {
    contract_id: contract.data.id,
  });
  if (preview.status !== 200) throw new Error(`预览失败 ${JSON.stringify(preview.data)}`);
  const buyer = preview.data.document.parties.buyer;
  if (buyer.tax_no !== '91610103MA6TX8K23Q') fail('合同抬头带出税号', JSON.stringify(buyer));
  if (buyer.bank_name !== '招商银行西安分行') fail('合同抬头带出开户行', JSON.stringify(buyer));
  if (buyer.bank_account !== '1298888666601') fail('合同抬头带出银行账号', JSON.stringify(buyer));
  if (buyer.phone !== '029-88886666') fail('抬头电话取开票电话', JSON.stringify(buyer));
  ok('合同正文自动带出税号 / 开户行 / 账号', `${buyer.tax_no} · ${buyer.bank_name}`);

  await api('DELETE', `/api/v1/contracts/${contract.data.id}?force=true`);

  // —— 5. 供应商弹窗 ——
  if (!(await openMenu('供应商档案'))) fail('打开「供应商档案」', '找不到菜单');
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim().includes('新增供应商'));
    if (btn) btn.click();
  });
  await page.waitForSelector('[data-partner-modal="supplier"]', { timeout: 10000 });
  await sleep(500);
  const supModal = await modalFields();
  for (const key of ['tax_no', 'bank_name', 'bank_account', 'invoice_phone']) {
    if (!supModal.keys.includes(key)) fail(`供应商弹窗有 ${key} 字段`, supModal.keys.join(','));
  }
  ok('供应商弹窗同样有四个开票字段', supModal.keys.join(' · '));

  const supName = `验收开票供应商${TAG}`;
  await setField('name', supName);
  await setField('tax_no', '9144030071526726X9');
  await setField('bank_name', '建设银行深圳科技园支行');
  await setField('bank_account', '755912345678901');
  await setField('invoice_phone', '0755-26551234');
  await page.evaluate(() => {
    const btn = document.querySelector('[data-partner-modal="supplier"] button[type="submit"]');
    if (btn) btn.click();
  });
  await passNameGuard();
  for (let i = 0; i < 40; i += 1) {
    if (!(await page.$('[data-partner-modal="supplier"]'))) break;
    await sleep(300);
  }
  const supList = await api('GET', '/api/v1/suppliers?limit=500');
  const supRows = Array.isArray(supList.data) ? supList.data : supList.data?.items || [];
  const supSaved = supRows.find((row) => row.name === supName);
  if (!supSaved) fail('供应商已入库', '列表里找不到');
  if (supSaved.invoice_phone !== '0755-26551234') {
    fail('供应商开票电话已落库', String(supSaved.invoice_phone));
  }
  ok('供应商开票信息落库', `#${supSaved.id}`);

  // —— 6. 收尾 ——
  await api('DELETE', `/api/v1/customers/${saved.id}`);
  await api('DELETE', `/api/v1/suppliers/${supSaved.id}`);
  await api('DELETE', `/api/v1/products/${product.data.id}?force=true`);
  const afterC = await api('GET', '/api/v1/customers?limit=500');
  const afterRows = Array.isArray(afterC.data) ? afterC.data : afterC.data?.items || [];
  if (afterRows.some((row) => row.name === custName)) fail('验收客户已删除', custName);
  ok('验收数据已清理干净');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_partner_form.png') });
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
