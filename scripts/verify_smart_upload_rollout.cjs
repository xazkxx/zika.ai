/**
 * 智能识别上传「铺开到供应商 + 商品」验收 —— 2026-10-23
 *
 * 验六件事（真浏览器 + 真 Word 报价单）：
 *   1. 「新增供应商」弹窗顶部有识别区；
 *   2. 传报价单 Word → 核对框认出名称/税号/地址/电话 → 应用后逐项落进表单；
 *   3. 保存后接口能读到这些值；收尾删掉；
 *   4. 「新增商品（新增产品）」弹窗顶部也有识别区；
 *   5. 传同一份报价单 → 核对框里出现**商品明细**，点第 2 行「用这一行」→
 *      名称/规格/单位/销售价按那一行填进商品表单；
 *   6. 商品保存成功后接口能读到；收尾删掉。
 *
 * 跑法：BASE=http://127.0.0.1:8022 node scripts/verify_smart_upload_rollout.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || process.env.ERP_BASE || 'http://127.0.0.1:8022';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const FIXTURES = 'E:/AI/ERP软件/docs/验收样本';
const TAG = Date.now().toString().slice(-6);
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

async function clickButtonByText(text) {
  return page.evaluate((label) => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim().includes(label));
    if (!btn) return false;
    btn.click();
    return true;
  }, text);
}

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

(async () => {
  const quote = path.join(FIXTURES, 'quote.docx');
  if (!fs.existsSync(quote)) {
    fail('验收样本存在', `${quote} 缺失，先跑 scripts/make_smart_upload_fixtures.py`);
  }

  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1920, height: 1000 },
    protocolTimeout: 240000,
  });
  page = await browser.newPage();
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 160)));
  await page.setCacheEnabled(false);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');

  // ======================= 供应商 =======================
  if (!(await openMenu('供应商档案'))) fail('打开「供应商档案」', '找不到菜单');
  if (!(await clickButtonByText('新增供应商'))) fail('点「新增供应商」', '找不到按钮');
  await page.waitForSelector('[data-partner-modal="supplier"]', { timeout: 10000 });
  await sleep(400);

  const hasPanel = await page.$('[data-partner-modal="supplier"] [data-smart-upload]');
  if (!hasPanel) fail('供应商弹窗有识别区', '找不到 [data-smart-upload]');
  ok('供应商弹窗顶部有智能识别区');

  const input = await page.$('[data-partner-modal="supplier"] [data-su-input]');
  await input.uploadFile(quote);
  await page.waitForSelector('[data-su-result]', { timeout: 60000 });
  await sleep(400);
  const supFields = await page.evaluate(() => {
    const modal = document.querySelector('[data-su-result]');
    return Object.fromEntries(
      [...modal.querySelectorAll('[data-su-field]')].map((tr) => [
        tr.getAttribute('data-su-field'),
        (tr.querySelector('.smart-upload__mark')?.textContent || '').trim(),
      ]),
    );
  });
  if (!supFields.name || !supFields.name.includes('凯歌')) {
    fail('供应商识别出名称', JSON.stringify(supFields));
  }
  if (supFields.tax_no !== '9144030071526726X9') fail('供应商识别出税号', String(supFields.tax_no));
  ok('供应商识别结果正确', `名称=${supFields.name} · 税号=${supFields.tax_no}`);

  await page.click('[data-su-apply]');
  await sleep(700);
  const supForm = await page.evaluate(() => {
    const read = (key) => document.querySelector(`[data-partner-modal="supplier"] [data-partner-field="${key}"]`)?.value || '';
    return {
      name: read('name'),
      tax_no: read('tax_no'),
      address: read('address'),
      phone: read('phone'),
    };
  });
  if (!supForm.name.includes('凯歌')) fail('供应商名称已回填', JSON.stringify(supForm));
  if (supForm.tax_no !== '9144030071526726X9') fail('供应商税号已回填', JSON.stringify(supForm));
  ok('供应商表单已被回填', `${supForm.name} · ${supForm.address || '（无地址）'}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_upload_supplier.png') });
  console.log('  📸 e2e_smart_upload_supplier.png');

  // 加上唯一后缀再保存，避免与已有供应商重名
  await page.evaluate((suffix) => {
    const input = document.querySelector('[data-partner-modal="supplier"] [data-partner-field="name"]');
    if (!input) return;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, `${input.value}${suffix}`);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, `-${TAG}`);
  const supName = await page.evaluate(
    () => document.querySelector('[data-partner-modal="supplier"] [data-partner-field="name"]')?.value || '',
  );

  await page.evaluate(() => {
    const btn = document.querySelector('[data-partner-modal="supplier"] button[type="submit"]');
    if (btn) btn.click();
  });
  await passNameGuard();
  for (let i = 0; i < 40; i += 1) {
    if (!(await page.$('[data-partner-modal="supplier"]'))) break;
    await sleep(300);
  }
  if (await page.$('[data-partner-modal="supplier"]')) fail('供应商保存成功', '弹窗还在');
  await sleep(600);

  const supList = await api('GET', '/api/v1/suppliers?limit=500');
  const supRows = Array.isArray(supList.data) ? supList.data : supList.data?.items || [];
  const savedSup = supRows.find((row) => row.name === supName);
  if (!savedSup) fail('供应商已入库', supName);
  if (savedSup.tax_no !== '9144030071526726X9') fail('供应商税号落库', String(savedSup.tax_no));
  ok('供应商保存并落库', `#${savedSup.id} ${savedSup.name}`);

  // ======================= 商品 =======================
  if (!(await openMenu('商品档案'))) fail('打开「商品档案」', '找不到菜单');
  if (!(await clickButtonByText('新增产品'))) fail('点「新增产品」', '找不到按钮');
  await page.waitForSelector('.modal-card.modal-wide', { timeout: 10000 });
  await sleep(500);

  const productPanel = await page.$('[data-smart-upload="product"]');
  if (!productPanel) fail('商品弹窗有识别区', '找不到 [data-smart-upload="product"]');
  ok('商品弹窗顶部有智能识别区');

  const pInput = await page.$('[data-smart-upload="product"] [data-su-input]');
  await pInput.uploadFile(quote);
  await page.waitForSelector('[data-su-result]', { timeout: 60000 });
  await sleep(400);

  const itemInfo = await page.evaluate(() => {
    const modal = document.querySelector('[data-su-result]');
    const rows = [...modal.querySelectorAll('tbody tr')].map((tr) => ({
      cells: [...tr.children].map((td) => (td.textContent || '').trim()),
      hasPick: Boolean(tr.querySelector('[data-su-item]')),
    }));
    return { rows, pickCount: modal.querySelectorAll('[data-su-item]').length };
  });
  if (itemInfo.pickCount < 2) fail('明细里每行都有「用这一行」', JSON.stringify(itemInfo.rows));
  ok('商品识别出明细行且可逐行取用', `${itemInfo.pickCount} 行可点`);

  // 点第 2 行（配电箱 XL-21 / 台 / 1800）
  await page.click('[data-su-item="1"]');
  await sleep(700);
  const prodForm = await page.evaluate(() => {
    // 商品弹窗用自己的 `data-product-field` 锚点（PartnerModal 才用 data-partner-field）
    const read = (key) => document.querySelector(`[data-product-field="${key}"]`)?.value || '';
    return {
      name: read('name'),
      standards: read('standards'),
      unit: read('unit'),
      sale_price: read('sale_price'),
    };
  });
  if (prodForm.name !== '配电箱') fail('商品名称取自选中行', JSON.stringify(prodForm));
  if (prodForm.standards !== 'XL-21') fail('商品规格取自选中行', JSON.stringify(prodForm));
  if (prodForm.unit !== '台') fail('商品单位取自选中行', JSON.stringify(prodForm));
  if (Number(prodForm.sale_price) !== 1800) fail('商品销售价取自选中行', JSON.stringify(prodForm));
  ok('「用这一行」把商品字段填对了', `${prodForm.name} / ${prodForm.standards} / ${prodForm.unit} / ¥${prodForm.sale_price}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_upload_product.png') });
  console.log('  📸 e2e_smart_upload_product.png');

  // 补 SKU 再保存
  const sku = `SKU-SU${TAG}`;
  await page.evaluate((value) => {
    const input = document.querySelector('[data-product-field="sku"]');
    if (!input) return;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, sku);
  await page.evaluate(() => {
    const form = document.querySelector('.modal-card.modal-wide form');
    if (form) form.requestSubmit();
  });
  for (let i = 0; i < 40; i += 1) {
    if (!(await page.$('.modal-card.modal-wide'))) break;
    await sleep(300);
  }
  await sleep(800);

  const prodList = await api('GET', '/api/v1/products?limit=500');
  const prodRows = Array.isArray(prodList.data) ? prodList.data : prodList.data?.items || [];
  const savedProd = prodRows.find((row) => row.sku === sku);
  if (!savedProd) fail('商品已入库', sku);
  if (savedProd.name !== '配电箱') fail('商品名称落库', String(savedProd.name));
  if (Number(savedProd.sale_price) !== 1800) fail('商品销售价落库', String(savedProd.sale_price));
  ok('商品保存并落库', `#${savedProd.id} ${savedProd.name} · ${savedProd.standards}`);

  // ======================= 收尾 =======================
  await api('DELETE', `/api/v1/products/${savedProd.id}?force=true`);
  await api('DELETE', `/api/v1/suppliers/${savedSup.id}`);
  const afterP = await api('GET', '/api/v1/products?limit=500');
  const afterPRows = Array.isArray(afterP.data) ? afterP.data : afterP.data?.items || [];
  if (afterPRows.some((row) => row.sku === sku)) fail('验收商品已删除', sku);
  ok('验收数据已清理干净');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_smart_upload_rollout.png') });
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
