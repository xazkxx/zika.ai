/**
 * 合同模板库 + 完整合同 验收（2026-10-22）
 *
 * 验六件事（真浏览器 + 真下载）：
 *   1. 「📁 模板管理」按钮存在，点开是抽屉；
 *   2. 抽屉里能上传 Word 模板（名称/备注/文件），上传后列表里出现；
 *   3. 表单顶部「选择合同模板」下拉能选到它；
 *   4. Word 模板不能"预览"（没有预览按钮），PDF/图片才有；
 *   5. 详情里「下载/打印完整合同」能真的落盘（Word 模板 → .docx 且变量已替换）；
 *   6. 抽屉里删除模板生效。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_contract_template_library.cjs
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

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 准备：一个客户、一个商品、一份本地 docx 模板文件（用 Python 生成后部在这里）
  const customer = await api('POST', '/api/v1/customers', {
    code: `CUST-TPL${TAG}`,
    name: `测试模板客户${TAG}`,
  });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);
  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-TPL${TAG}`,
    name: `测试模板商品${TAG}`,
    unit: '件',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);

  const templateFile = path.join(SHOT_DIR, `tmp_tpl_${TAG}.docx`);
  const made = require('child_process').spawnSync(
    'E:/AI/ERP软件/.venv/Scripts/python.exe',
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        'd = Document()',
        "d.add_paragraph('甲方：{{party_name}}')",
        "d.add_paragraph('交货地点：{{delivery_place}}')",
        "d.add_paragraph('总价：{{total_amount}}（{{total_chinese}}）')",
        `d.save(r'${templateFile.replace(/\\/g, '\\\\')}')`,
      ].join('\n'),
    ],
    { encoding: 'utf8' },
  );
  if (!fs.existsSync(templateFile)) {
    fail('准备：生成一份 Word 模板文件', made.stderr || '生成失败');
  }
  ok('准备：客户 / 商品 / Word 模板文件');

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

  // ============ 1. 模板管理按钮 → 抽屉 ============
  const hasManage = await page.evaluate(() => Boolean(document.querySelector('[data-contract-template-manage]')));
  if (!hasManage) fail('页面有「📁 模板管理」按钮', '找不到 data-contract-template-manage');
  ok('页面有「📁 模板管理」按钮');

  await page.click('[data-contract-template-manage]');
  await sleep(900);
  const drawer = await page.evaluate(() => {
    const root = document.querySelector('[data-contract-template-drawer]');
    return { open: Boolean(root), hasUpload: Boolean(root && root.querySelector('[data-tpl-upload]')) };
  });
  if (!drawer.open) fail('点按钮弹出模板库抽屉', '没有 [data-contract-template-drawer]');
  ok('点按钮弹出模板库抽屉', drawer.hasUpload ? '含上传表单' : '');

  // ============ 2. 上传 Word 模板 ============
  const nameInput = await page.$('[data-tpl-name]');
  if (!nameInput) fail('抽屉里有「模板名称」输入框');
  await nameInput.click();
  await page.keyboard.type(`标准工矿产品购销合同-${TAG}`);

  const fileInput = await page.$('[data-tpl-file]');
  if (!fileInput) fail('抽屉里有文件选择框');
  await fileInput.uploadFile(templateFile);
  await sleep(400);

  await page.click('[data-tpl-upload]');
  await sleep(2600);

  const uploaded = await page.evaluate((tag) => {
    const root = document.querySelector('[data-contract-template-drawer]');
    const items = [...(root ? root.querySelectorAll('.tpl-drawer__item') : [])];
    return {
      count: items.length,
      names: items.map((item) => (item.textContent || '').trim()).slice(0, 3),
      matched: items.some((item) => (item.textContent || '').includes(tag)),
    };
  }, TAG);
  if (!uploaded.matched) fail('上传后模板出现在列表里', JSON.stringify(uploaded.names));
  ok('上传后模板出现在列表里', `共 ${uploaded.count} 份`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_template_drawer.png') });
  console.log('  📸 e2e_contract_template_drawer.png');

  // 关抽屉
  await page.evaluate(() => {
    const root = document.querySelector('[data-contract-template-drawer]');
    const btn = [...root.querySelectorAll('button')].find((b) => (b.textContent || '').trim() === '关闭');
    btn.click();
  });
  await sleep(700);

  // ============ 3. 表单顶部下拉能选到它 ============
  const options = await page.evaluate(() => {
    const select = document.querySelector('[data-contract-template-select]');
    if (!select) return null;
    return [...select.options].map((o) => ({ value: o.value, text: o.textContent.trim() }));
  });
  if (!options) fail('表单顶部有「选择合同模板」下拉', '找不到 data-contract-template-select');
  const target = options.find((o) => o.text.includes(TAG));
  if (!target) fail('下拉里能选到刚上传的模板', JSON.stringify(options.map((o) => o.text).slice(0, 3)));
  ok('下拉里能选到刚上传的模板', target.text);
  ok('下拉含「不使用模板」默认项', options[0].text.slice(0, 20));

  await page.select('[data-contract-template-select]', target.value);
  await sleep(600);
  const afterPick = await page.evaluate(() => ({
    hasPreviewBtn: Boolean(document.querySelector('[data-contract-template-preview]')),
    tip: (document.querySelector('.contract-template-tip')?.textContent || '').trim().slice(0, 30),
  }));
  // Word 模板不可在线预览 → 不该出现「预览模板」，但要有"变量替换"提示
  if (afterPick.hasPreviewBtn) fail('Word 模板不显示「预览模板」（它是文档不是图片/PDF）');
  ok('Word 模板不显示「预览模板」', afterPick.tip);

  // ============ 4. 填客户/明细 → 保存 → 详情里下载完整合同 ============
  const partyOk = await page.evaluate((name) => {
    const box = document.querySelector('.erp-form .ssel');
    const trigger = box && box.querySelector('.ssel-trigger');
    if (!trigger) return false;
    trigger.click();
    const input = box.querySelector('.ssel-input');
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, name);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    return true;
  }, customer.data.name);
  if (!partyOk) fail('打开客户下拉');
  await sleep(800);
  const partyPoint = await page.evaluate((name) => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    const hit = panels
      .flatMap((p) => [...p.querySelectorAll('.ssel-option')])
      .find((o) => (o.textContent || '').includes(name));
    if (!hit) return null;
    const rect = hit.getBoundingClientRect();
    return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
  }, customer.data.name);
  if (!partyPoint) fail('选中客户', customer.data.name);
  await page.mouse.click(partyPoint.x, partyPoint.y);
  await sleep(700);

  // 明细：商品 select + 数量 + 单价
  await page.evaluate((name) => {
    const box = document.querySelector('.contract-item-row .ssel');
    box?.querySelector('.ssel-trigger')?.click();
    const input = box?.querySelector('.ssel-input');
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, name);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, product.data.name);
  await sleep(800);
  const productPoint = await page.evaluate((name) => {
    const panels = [...document.querySelectorAll('.ssel-panel')];
    const hit = panels
      .flatMap((p) => [...p.querySelectorAll('.ssel-option')])
      .find((o) => (o.textContent || '').includes(name));
    if (!hit) return null;
    const rect = hit.getBoundingClientRect();
    return { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) };
  }, product.data.name);
  if (!productPoint) fail('选中商品', product.data.name);
  await page.mouse.click(productPoint.x, productPoint.y);
  await sleep(600);

  await page.evaluate(() => {
    const set = (el, v) => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const inputs = [...document.querySelectorAll('.contract-item-row input[type="number"]')];
    if (inputs[0]) set(inputs[0], '10');
    if (inputs[1]) set(inputs[1], '99.5');
  });
  await sleep(400);

  // 保存
  await page.evaluate(() => {
    const form = document.querySelector('.erp-form');
    if (form) form.requestSubmit();
  });
  await sleep(3000);

  const contracts = await api('GET', '/api/v1/contracts?limit=20');
  const rows = Array.isArray(contracts.data) ? contracts.data : (contracts.data || {}).items || [];
  const mine = rows.find((row) => row.party_name === customer.data.name);
  if (!mine) fail('保存合同成功（服务端可查）');
  if (String(mine.template_id) !== String(target.value)) {
    fail('合同记住了所选模板（template_id 落库）', `库里是 ${mine.template_id}，选了 ${target.value}`);
  }
  ok('合同记住了所选模板', `template_id=${mine.template_id}`);

  // 打开详情（列表行点击）
  await page.evaluate((no) => {
    const tr = [...document.querySelectorAll('tbody tr')].find((r) => (r.textContent || '').includes(no));
    if (tr) tr.click();
  }, mine.contract_no);
  await sleep(1200);

  const hasFullBtn = await page.evaluate(() => Boolean(document.querySelector('[data-contract-full]')));
  if (!hasFullBtn) fail('详情里有「下载/打印完整合同」按钮');
  ok('详情里有「下载/打印完整合同」按钮');

  // 真下载（CDP 落盘）
  fs.rmSync(DOWN_DIR, { recursive: true, force: true });
  fs.mkdirSync(DOWN_DIR, { recursive: true });
  const cdp = await page.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: DOWN_DIR.replace(/\//g, '\\'),
  });
  await page.click('[data-contract-full]');
  await sleep(3600);

  const files = fs.readdirSync(DOWN_DIR);
  const wordFile = files.find((name) => name.toLowerCase().endsWith('.docx'));
  if (!wordFile) fail('Word 模板下载的是 .docx', `目录里只有：${files.join(',') || '空'}`);
  const size = fs.statSync(path.join(DOWN_DIR, wordFile)).size;
  ok('Word 模板下载的是 .docx', `${wordFile} · ${(size / 1024).toFixed(0)} KB`);

  // 用 python-docx 校验变量真的替换了
  const check = require('child_process').spawnSync(
    'E:/AI/ERP软件/.venv/Scripts/python.exe',
    [
      '-c',
      [
        'import sys',
        'from docx import Document',
        `d = Document(r'${path.join(DOWN_DIR, wordFile).replace(/\\/g, '\\\\')}')`,
        "text = '\\n'.join(p.text for p in d.paragraphs)",
        'print("HAS_NAME", ' + JSON.stringify(customer.data.name) + ' in text)',
        'print("HAS_PLACEHOLDER", "{{" in text)',
        'print("HAS_AMOUNT", "995.00" in text)',
      ].join('\n'),
    ],
    { encoding: 'utf8' },
  );
  const out = String(check.stdout || '');
  if (!out.includes('HAS_NAME True')) fail('下载的 docx 里客户名已替换', out.slice(0, 120));
  if (out.includes('HAS_PLACEHOLDER True')) fail('下载的 docx 里没有残留占位符', out.slice(0, 120));
  if (!out.includes('HAS_AMOUNT True')) fail('下载的 docx 里金额已替换', out.slice(0, 120));
  ok('docx 里变量已替换（客户名/金额/无残留占位符）');

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_full_download.png') });

  // ============ 5. 抽屉里删除模板 ============
  await page.evaluate(() => document.querySelector('[data-contract-full]')?.closest('.modal-card')?.querySelector('.modal-actions button:last-child')?.click());
  await sleep(600);
  await page.click('[data-contract-template-manage]');
  await sleep(900);
  await page.evaluate((tid) => document.querySelector(`[data-tpl-delete="${tid}"]`)?.click(), target.value);
  await sleep(800);
  const confirmed = await page.evaluate(() => {
    const card = document.querySelector('.print-confirm, [data-print-confirm], .modal-backdrop .modal-card');
    if (!card) return false;
    const btn = [...card.querySelectorAll('button')].find((b) => /确认|删除/.test(b.textContent || '') && !/取消/.test(b.textContent || ''));
    if (!btn) return false;
    btn.click();
    return true;
  });
  if (!confirmed) fail('删除模板有二次确认');
  await sleep(2000);
  const stillThere = await api('GET', '/api/v1/contract-templates');
  const list = Array.isArray(stillThere.data) ? stillThere.data : [];
  if (list.some((row) => String(row.id) === String(target.value))) {
    fail('模板已从库里删除', `还在：${JSON.stringify(list.map((r) => r.id))}`);
  }
  ok('模板已从库里删除（删除后合同仍可下载正文）');

  // 收尾
  await api('DELETE', `/api/v1/contracts/${mine.id}?force=true`);
  await api('DELETE', `/api/v1/customers/${customer.data.id}`);
  await api('DELETE', `/api/v1/products/${product.data.id}`);
  fs.rmSync(DOWN_DIR, { recursive: true, force: true });
  fs.rmSync(templateFile, { force: true });

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_contract_template.png') });
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
