/**
 * 合同付款计划（多期次）UI 验收 —— 2026-10-23
 *
 * 验七件事（真浏览器、真上传、真落库）：
 *   1. 合同详情里有「付款计划」区块，空态有引导文案；
 *   2. 点「一键三期 30/40/30」→ 出现 3 行，汇总「已计划」= 合同总额；
 *   3. 在第 1 期「已付金额」里填 3000 并失焦 → 汇总「已付」与进度条同步到 30%；
 *   4. 上传回单 → 该行变成「查看回单」；
 *   5. 关掉弹窗后，列表该行的金额下面出现进度条与 30%（新增的进度展示）；
 *   6. 后端汇总与界面一致（接口复核，防止"界面好看但数不对"）；
 *   7. 验收数据全部清掉。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_contract_payment_plans.cjs
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

  const customer = await api('POST', '/api/v1/customers', {
    code: `CUST-PAY${TAG}`,
    name: `测试付款客户${TAG}`,
  });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);
  const product = await api('POST', '/api/v1/products', {
    sku: `SKU-PAY${TAG}`,
    name: `测试付款商品${TAG}`,
    unit: '件',
  });
  if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
  const contract = await api('POST', '/api/v1/contracts', {
    direction: 'out',
    party_id: customer.data.id,
    party_name: customer.data.name,
    sign_date: TODAY,
    items: [{ product_id: product.data.id, quantity: 10, unit_price: 1000 }],
  });
  if (contract.status !== 201) throw new Error(`建合同失败 ${JSON.stringify(contract.data)}`);
  const CID = contract.data.id;
  const TOTAL = Number(contract.data.total_amount);
  ok('准备：一张 ¥10,000 的合同', contract.data.contract_no);

  // 回单用的图片
  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  const receiptFile = path.join(SHOT_DIR, `tmp_receipt_${TAG}.png`);
  const made = spawn(
    'E:/AI/ERP软件/.venv/Scripts/python.exe',
    [
      '-c',
      [
        'from PIL import Image, ImageDraw',
        "img = Image.new('RGB', (600, 320), 'white')",
        "ImageDraw.Draw(img).text((40, 40), 'PAYMENT RECEIPT')",
        `img.save(r'${receiptFile.replace(/\\/g, '\\\\')}')`,
      ].join('\n'),
    ],
  );
  if (!fs.existsSync(receiptFile)) fail('准备：回单图片', made.stderr || '生成失败');

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
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(400);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find(
      (e) => (e.textContent || '').trim() === '购销合同',
    );
    if (item) item.click();
  });
  await sleep(2600);

  // —— 1. 打开详情，找到付款计划区块 ——
  await page.evaluate((no) => {
    const tr = [...document.querySelectorAll('.contract-list-table tbody tr')].find((r) =>
      (r.textContent || '').includes(no),
    );
    if (tr) tr.click();
  }, contract.data.contract_no);
  await sleep(1400);

  const block = await page.evaluate(() => {
    const root = document.querySelector('[data-contract-payment-plans]');
    if (!root) return { ok: false };
    return {
      ok: true,
      empty: (root.textContent || '').includes('还没有付款计划'),
      hasTemplateBtn: Boolean(root.querySelector('[data-payplan-template]')),
      rows: root.querySelectorAll('[data-payplan-row]').length,
    };
  });
  if (!block.ok) fail('详情里有「付款计划」区块', '找不到 [data-contract-payment-plans]');
  if (!block.hasTemplateBtn) fail('空态有「一键三期」按钮');
  ok('详情里有「付款计划」区块', block.empty ? '空态提示正常' : `已有 ${block.rows} 期`);

  // —— 2. 一键三期 ——
  await page.click('[data-payplan-template]');
  await sleep(2200);

  const afterTemplate = await page.evaluate(() => {
    const root = document.querySelector('[data-contract-payment-plans]');
    const rows = [...root.querySelectorAll('[data-payplan-row]')];
    const summary = root.querySelector('[data-payplan-summary]')?.textContent || '';
    return {
      rows: rows.length,
      ratios: rows.map((row) => row.children[3]?.textContent?.trim()),
      amounts: rows.map((row) => {
        const input = row.children[4]?.querySelector('input');
        return input ? input.value : '';
      }),
      summary,
    };
  });
  if (afterTemplate.rows !== 3) fail('一键三期生成 3 行', `${afterTemplate.rows} 行`);
  ok('一键三期生成 3 行', afterTemplate.ratios.join(' / '));
  if (!afterTemplate.summary.includes('10,000.00')) {
    fail('汇总「已计划」= 合同总额', afterTemplate.summary.slice(0, 80));
  }
  ok('汇总「已计划」= 合同总额 ¥10,000.00');

  // —— 3. 登记第 1 期已付 3000 ——
  const firstPlanId = await page.evaluate(() => {
    const row = document.querySelector('[data-payplan-row]');
    return row ? row.getAttribute('data-payplan-row') : null;
  });
  if (!firstPlanId) fail('拿到第 1 期的 id');

  await page.evaluate((planId) => {
    const input = document.querySelector(`[data-payplan-paid="${planId}"]`);
    if (!input) return;
    // ⚠️ 必须先 focus：元素没获得焦点时 `blur()` 不会派发 blur 事件，
    //    onBlur 上的保存逻辑就永远不会跑（真实用户是点进去再点走）。
  }, firstPlanId);
  await sleep(300);
  // 真实交互：聚焦 → 全选清空 → 输入 → 失焦
  // ⚠️ type=number 的三击全选不可靠（曾把 3000 输成 30000）；
  //    并且合成 click 不会移动焦点，必须显式 focus，再用 activeElement.blur() 触发 onBlur。
  await page.evaluate((planId) => {
    const input = document.querySelector(`[data-payplan-paid="${planId}"]`);
    if (!input) return;
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, '3000');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, firstPlanId);
  await sleep(200);
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await sleep(2200);

  const afterPaid = await page.evaluate((planId) => {
    const root = document.querySelector('[data-contract-payment-plans]');
    const summary = root.querySelector('[data-payplan-summary]');
    const bar = summary?.querySelector('.payplan__bar-fill');
    const row = document.querySelector(`[data-payplan-row="${planId}"]`);
    return {
      summaryText: summary?.textContent || '',
      barWidth: bar ? bar.style.width : '',
      shortfall: row ? row.children[6]?.textContent?.trim() : '',
      settled: row ? row.className.includes('is-settled') : false,
    };
  }, firstPlanId);

  if (!afterPaid.summaryText.includes('3,000.00')) {
    fail('登记后汇总「已付」= ¥3,000.00', afterPaid.summaryText.slice(0, 80));
  }
  if (!/30%/.test(afterPaid.barWidth)) {
    fail('进度条到 30%', `width=${afterPaid.barWidth}`);
  }
  ok('登记实付后汇总与进度条同步', `已付 ¥3,000 · 进度 ${afterPaid.barWidth}`);
  if (!afterPaid.settled) fail('该期被标记为已结清（左侧绿条）');
  ok('该期标记为已结清', afterPaid.shortfall || '');

  // —— 4. 上传回单 ——
  const receiptInput = await page.$(`[data-payplan-upload="${firstPlanId}"]`);
  if (!receiptInput) fail('该期有回单上传入口');
  await receiptInput.uploadFile(receiptFile);
  await sleep(2400);

  const afterReceipt = await page.evaluate((planId) => {
    const row = document.querySelector(`[data-payplan-row="${planId}"]`);
    return {
      hasView: Boolean(document.querySelector(`[data-payplan-receipt="${planId}"]`)),
      text: row ? row.children[7]?.textContent?.trim() : '',
    };
  }, firstPlanId);
  if (!afterReceipt.hasView) fail('回单上传后出现「查看回单」', afterReceipt.text);
  ok('回单上传成功并可查看', afterReceipt.text);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_payment_plan_modal.png') });
  console.log('  📸 e2e_contract_payment_plan_modal.png');

  // —— 6. 后端复核（界面好看但数不对，是最难查的那类 bug）——
  const server = await api('GET', `/api/v1/contracts/${CID}/payment-plans`);
  const summary = server.data.summary;
  if (Number(summary.paid_amount) !== 3000) fail('后端已付金额 = 3000', String(summary.paid_amount));
  if (Number(summary.progress) !== 30) fail('后端进度 = 30%', String(summary.progress));
  if (Number(summary.shortfall) !== TOTAL - 3000) {
    fail('后端未付缺口 = 7000', String(summary.shortfall));
  }
  ok('后端汇总与界面一致', `已付 ${summary.paid_amount} · ${summary.progress}% · 缺口 ${summary.shortfall}`);

  // —— 5. 关弹窗 → 列表进度 ——
  await page.evaluate(() => {
    const card = document.querySelector('[data-contract-detail-modal]');
    const btn = [...card.querySelectorAll('.modal-actions button')].find((b) =>
      /关闭/.test(b.textContent || ''),
    );
    if (btn) btn.click();
  });
  await sleep(900);

  const listProgress = await page.evaluate((id) => {
    const cell = document.querySelector(`[data-contract-progress="${id}"]`);
    if (!cell) return { ok: false };
    const bar = cell.querySelector('.contract-progress__bar i');
    return {
      ok: true,
      text: (cell.textContent || '').trim(),
      width: bar ? bar.style.width : '',
      inAmountCell: cell.closest('.contract-amount-cell') !== null,
    };
  }, CID);
  if (!listProgress.ok) fail('合同列表出现付款进度元素', '找不到 data-contract-progress');
  if (!listProgress.text.includes('30')) fail('列表进度显示 30%', listProgress.text);
  ok('合同列表金额下方显示进度', `${listProgress.text}（条宽 ${listProgress.width}）`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_payment_list.png') });
  console.log('  📸 e2e_contract_payment_list.png');

  // —— 7. 清理 ——
  await api('DELETE', `/api/v1/contracts/${CID}?force=true`);
  await api('DELETE', `/api/v1/products/${product.data.id}?force=true`);
  await api('DELETE', `/api/v1/customers/${customer.data.id}`);
  fs.rmSync(receiptFile, { force: true });
  ok('已清理验收数据');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_contract_payment.png') });
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

function spawn(cmd, args) {
  return require('child_process').spawnSync(cmd, args, { encoding: 'utf8' });
}
