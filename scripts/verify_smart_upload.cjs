/**
 * 「多文件智能识别上传」真浏览器验收 —— 2026-10-23
 *
 * 验九件事：
 *   1. 点「新增客户」→ 弹窗**最顶部**有识别区（几何：它在客户名称输入框上方）；
 *   2. 两种模式（识别并填表 / 仅上传作为附件）都在；
 *   3. 传一张营业执照 PNG（真 OCR）→ 弹「识别完成，请核对信息」；
 *   4. 核对框里的值带 `<mark>` 高亮，且**此时表单还是空的**（先核对、后回填）；
 *   5. 点「应用到表单」→ 名称/税号/地址/联系人/电话 逐项落到输入框；
 *   6. 传 Word 报价单 → 核对框里出现商品明细行；
 *   7. 「仅上传作为附件」：切模式后提示"保存后自动归档"，保存客户 → 附件真的挂上了（接口复核）；
 *   8. 识别区不把弹窗撑宽（面板右边缘 ≤ 弹窗右边缘）；
 *   9. 收尾把本轮造的客户、附件删干净。
 *
 * 跑法：BASE=http://127.0.0.1:8022 node scripts/verify_smart_upload.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || process.env.ERP_BASE || 'http://127.0.0.1:8022';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const FIXTURES = 'E:/AI/ERP软件/docs/验收样本';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const TAG = Date.now().toString().slice(-6);

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

/** 菜单可能折叠：先直接找，找不到再只展开"看起来折叠着"的分组 */
async function openMenu(name) {
  const direct = await page.evaluate((n) => {
    const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
    if (!item) return false;
    item.click();
    return true;
  }, name);
  if (direct) return true;
  const groups = await page.$$('.nav-group-title');
  for (const group of groups) {
    await group.click();
    await sleep(300);
    const hit = await page.evaluate((n) => {
      const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
      if (!item) return false;
      item.click();
      return true;
    }, name);
    if (hit) return true;
  }
  return false;
}

async function fillFormField(key, value) {
  await page.evaluate(
    (field, text) => {
      const input = document.querySelector(`[data-partner-field="${field}"]`);
      if (!input) return;
      const setter = Object.getOwnPropertyDescriptor(
        input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
        'value',
      ).set;
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    },
    key,
    value,
  );
}

(async () => {
  for (const file of ['license.png', 'namecard.png', 'quote.docx']) {
    if (!fs.existsSync(path.join(FIXTURES, file))) {
      fail('验收样本存在', `${file} 缺失，先跑 scripts/make_smart_upload_fixtures.py`);
    }
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

  // —— 1. 进客户档案，点新增 ——
  if (!(await openMenu('客户档案'))) fail('侧边栏有「客户档案」', '找不到菜单');
  await sleep(2000);
  const opened = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').trim().includes('新增客户'));
    if (!btn) return false;
    btn.click();
    return true;
  });
  if (!opened) fail('列表上有「新增客户」按钮', '没找到');
  await page.waitForSelector('[data-partner-modal="customer"]', { timeout: 10000 });
  await sleep(600);
  ok('打开「新增客户」弹窗');

  // —— 2. 识别区位置与模式 ——
  const layout = await page.evaluate(() => {
    const panel = document.querySelector('[data-smart-upload]');
    const modal = document.querySelector('[data-partner-modal="customer"]');
    const nameInput = document.querySelector('[data-partner-field="name"]');
    if (!panel || !modal || !nameInput) return { ok: false };
    const p = panel.getBoundingClientRect();
    const m = modal.getBoundingClientRect();
    const n = nameInput.getBoundingClientRect();
    const modes = [...panel.querySelectorAll('[data-su-mode]')].map((el) => ({
      key: el.getAttribute('data-su-mode'),
      label: (el.closest('label')?.textContent || '').trim(),
    }));
    return {
      ok: true,
      panelTop: Math.round(p.top),
      inputTop: Math.round(n.top),
      panelRight: Math.round(p.right),
      modalRight: Math.round(m.right),
      hasDrop: Boolean(panel.querySelector('[data-su-drop]')),
      modes,
      title: (panel.querySelector('.smart-upload__title')?.textContent || '').trim(),
    };
  });
  if (!layout.ok) fail('弹窗里有识别区', '找不到 [data-smart-upload]');
  if (layout.panelTop >= layout.inputTop) {
    fail('识别区在表单最顶部', `面板 top=${layout.panelTop} 不高于名称输入 top=${layout.inputTop}`);
  }
  if (!layout.hasDrop) fail('有拖拽/选择框', '缺少 [data-su-drop]');
  if (layout.modes.length !== 2) fail('两种模式都在', JSON.stringify(layout.modes));
  if (!layout.title.includes('智能识别上传')) fail('标题文案正确', layout.title);
  if (layout.panelRight > layout.modalRight + 1) {
    fail('识别区没把弹窗撑宽', `面板右 ${layout.panelRight} > 弹窗右 ${layout.modalRight}`);
  }
  ok('识别区在表单最顶部、宽度不溢出', `top ${layout.panelTop} < 名称 ${layout.inputTop}`);
  ok('两种模式都在', layout.modes.map((m) => m.label).join(' / '));

  // —— 3. 上传营业执照（真 OCR）——
  const formBefore = await page.evaluate(() =>
    (document.querySelector('[data-partner-field="name"]')?.value || '').trim(),
  );
  if (formBefore) fail('识别前表单是空的', formBefore);

  const input = await page.$('[data-su-input]');
  await input.uploadFile(path.join(FIXTURES, 'license.png'));
  // 首次 OCR 要加载模型，等久一点
  await page.waitForSelector('[data-su-result]', { timeout: 120000 });
  await sleep(300);
  ok('上传营业执照后弹出核对框');

  const receipt = await page.evaluate(() => {
    const modal = document.querySelector('[data-su-result]');
    const rows = [...modal.querySelectorAll('[data-su-field]')].map((tr) => ({
      key: tr.getAttribute('data-su-field'),
      label: (tr.querySelector('.smart-upload__label')?.textContent || '').trim(),
      value: (tr.querySelector('.smart-upload__mark')?.textContent || '').trim(),
      highlighted: Boolean(tr.querySelector('mark')),
    }));
    const nameNow = (document.querySelector('[data-partner-field="name"]')?.value || '').trim();
    return {
      rows,
      nameNow,
      title: (modal.querySelector('.smart-upload__dialog-head strong')?.textContent || '').trim(),
      warnings: modal.querySelectorAll('[data-su-warning] li').length,
    };
  });
  if (!receipt.title.includes('核对')) fail('核对框标题明确', receipt.title);
  if (!receipt.rows.length) fail('核对框里有识别结果', '0 行');
  if (!receipt.rows.every((row) => row.highlighted)) {
    fail('识别值全部高亮', JSON.stringify(receipt.rows.filter((row) => !row.highlighted)));
  }
  if (receipt.nameNow) fail('核对阶段还没回填表单', receipt.nameNow);
  ok('核对框把识别值高亮标出，表单此时仍为空', `${receipt.rows.length} 项`);

  const fieldMap = Object.fromEntries(receipt.rows.map((row) => [row.key, row.value]));
  if (!fieldMap.name || !fieldMap.name.includes('陕西送变电工程有限公司')) {
    fail('认出公司名称', JSON.stringify(fieldMap));
  }
  if (fieldMap.tax_no !== '91610103MA6TX8K23Q') fail('认出统一社会信用代码', String(fieldMap.tax_no));
  ok('关键字段认得对', `名称=${fieldMap.name} · 税号=${fieldMap.tax_no}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_upload_review.png') });
  console.log('  📸 e2e_smart_upload_review.png');

  // —— 4. 应用到表单 ——
  await page.click('[data-su-apply]');
  await sleep(700);
  const filled = await page.evaluate(() => {
    const read = (key) => (document.querySelector(`[data-partner-field="${key}"]`)?.value || '').trim();
    return { name: read('name'), phone: read('phone'), contact: read('contact'), address: read('address') };
  });
  if (!filled.name.includes('陕西送变电工程有限公司')) fail('名称已填进表单', filled.name);
  if (!filled.contact) fail('联系人已填进表单', JSON.stringify(filled));
  if (!filled.address) fail('地址已填进表单', JSON.stringify(filled));
  if (!filled.phone) fail('电话已填进表单', JSON.stringify(filled));
  ok('应用到表单后逐项落位', `名称/联系人/电话/地址 都已填`);

  // —— 5. Word 报价单 → 商品明细 ——
  await page.click('[data-su-input]').catch(() => {});
  const input2 = await page.$('[data-su-input]');
  await input2.uploadFile(path.join(FIXTURES, 'quote.docx'));
  await page.waitForSelector('[data-su-result]', { timeout: 60000 });
  await sleep(400);
  const itemsInfo = await page.evaluate(() => {
    const modal = document.querySelector('[data-su-result]');
    const box = modal.querySelector('.smart-upload__items');
    return {
      hasBox: Boolean(box),
      rows: box ? box.querySelectorAll('tbody tr').length : 0,
      first: box ? (box.querySelector('tbody tr td')?.textContent || '').trim() : '',
      names: [...modal.querySelectorAll('[data-su-field="name"] .smart-upload__mark')].map((n) =>
        (n.textContent || '').trim(),
      ),
    };
  });
  if (!itemsInfo.hasBox) fail('Word 报价单识别出商品明细区', '没有明细块');
  if (itemsInfo.rows < 1) fail('明细行 ≥ 1', String(itemsInfo.rows));
  ok('Word 报价单带出商品明细', `${itemsInfo.rows} 行，首行「${itemsInfo.first}」`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_upload_items.png') });
  console.log('  📸 e2e_smart_upload_items.png');

  await page.click('[data-su-cancel]');
  await sleep(400);

  // —— 6. 「仅上传作为附件」→ 保存后归档 ——
  await page.click('[data-su-mode="attach"]');
  await sleep(500);
  const attachHint = await page.evaluate(
    () => (document.querySelector('[data-su-hint]')?.textContent || '').trim(),
  );
  if (!attachHint.includes('归档')) fail('切到附件模式后有说明', attachHint || '（没有提示）');
  ok('切到「仅上传作为附件」有明确说明', attachHint);

  const attachName = `智能识别验收客户${TAG}`;
  await fillFormField('name', attachName);
  await sleep(200);
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('[data-partner-modal="customer"] button[type="submit"]')][0];
    if (btn) btn.click();
  });
  // 等弹窗关闭（保存成功）
  for (let i = 0; i < 40; i += 1) {
    const open = await page.$('[data-partner-modal="customer"]');
    if (!open) break;
    await sleep(300);
  }
  const modalGone = !(await page.$('[data-partner-modal="customer"]'));
  if (!modalGone) fail('保存后弹窗关闭', '弹窗还在（可能保存失败）');
  await sleep(1200);

  const list = await api('GET', '/api/v1/customers?limit=500');
  const rows = Array.isArray(list.data) ? list.data : list.data?.items || [];
  const created = rows.find((row) => row.name === attachName);
  if (!created) fail('客户已创建', `在列表里找不到「${attachName}」`);
  const filesRes = await api('GET', `/api/v1/customers/${created.id}/files`);
  const files = Array.isArray(filesRes.data) ? filesRes.data : filesRes.data?.items || [];
  if (files.length < 1) fail('附件已归档到该客户', `附件数 ${files.length}`);
  ok('「仅上传作为附件」在保存后真的归档了', `${files.length} 个附件 · 客户 ${created.code}`);

  const notice = await page.evaluate(() => {
    const node = document.querySelector('.notice, .toast, [data-notice]');
    return node ? (node.textContent || '').trim().slice(0, 60) : '';
  });
  if (notice) ok('页面给了保存/归档提示', notice);

  // —— 7. 收尾：删附件、删客户 ——
  for (const file of files) {
    await api('DELETE', `/api/v1/customer-files/${file.id}`);
  }
  const removed = await api('DELETE', `/api/v1/customers/${created.id}`);
  if (removed.status !== 204 && removed.status !== 200) {
    fail('清理验收客户', `HTTP ${removed.status}`);
  }
  const after = await api('GET', '/api/v1/customers?limit=500');
  const afterRows = Array.isArray(after.data) ? after.data : after.data?.items || [];
  if (afterRows.some((row) => row.name === attachName)) fail('客户已删除', attachName);
  ok('验收数据已清理干净');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_smart_upload.png') });
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
