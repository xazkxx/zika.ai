/**
 * 对账单「四流超宽表」12 列 + 列宽拖拽验收（2026-10-22）
 *
 * 验四件事：
 *   1. 列的**内容**齐不齐：业务日期/送货/发货/签收状态/合同编号/单据号/
 *      开票状态/开票时间/发票号码/收款流水号/收款时间/收款方式/金额/已收/未收/已开票/未开票；
 *   2. 横向滚动能出来（表宽 > 可视宽），且冻结列真的钉住；
 *   3. 列宽**能用鼠标拖**（真实坐标），拖完宽度变了、并写进 localStorage；
 *   4. 双击抓手能复位。
 *
 * 只读：不建单、不改数据（打开一张已存在的对账单而已）。
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_statement_wide_table.cjs
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

  // 先找到一张"有明细"的对账单（没有明细的话四流表不会渲染）
  const statements = await api('GET', '/api/v1/statements?limit=50');
  const list = Array.isArray(statements.data) ? statements.data : (statements.data && statements.data.items) || [];
  if (!list.length) throw new Error('库里一张对账单都没有，先手工生成一张再跑');
  let target = null;
  for (const row of list) {
    const detail = await api('GET', `/api/v1/statements/${row.id}`);
    if ((detail.data.items || []).length > 0) {
      target = row;
      break;
    }
  }
  if (!target) throw new Error('没有一张带明细的对账单');

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

  // 增强对账单默认落在「全部」= 台账视角，点一行就载入
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find(
      (e) => (e.textContent || '').trim() === '增强对账单',
    );
    if (item) item.click();
  });
  await sleep(2000);

  const opened = await page.evaluate((no) => {
    const rows = [...document.querySelectorAll('tbody tr')];
    const row = rows.find((tr) => (tr.textContent || '').includes(no));
    if (!row) return false;
    row.click();
    return true;
  }, target.statement_no);
  if (!opened) fail('打开一张已存对账单', target.statement_no);
  await sleep(2500);

  const table = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-fusion]');
    if (!root) return { ok: false };
    const ths = [...root.querySelectorAll('thead th')].map((th) => th.getAttribute('data-col') || '');
    const labels = [...root.querySelectorAll('thead th')].map((th) => (th.textContent || '').trim());
    const scroll = root.querySelector('.stmt-fusion__scroll');
    return {
      ok: true,
      colCount: ths.length - 1, // 去掉最左边那条「行」
      ths,
      labels,
      scrollWidth: scroll ? scroll.scrollWidth : 0,
      clientWidth: scroll ? scroll.clientWidth : 0,
      rowCount: root.querySelectorAll('tbody tr').length,
    };
  });
  if (!table.ok) fail('四流超宽表已渲染', '找不到 [data-stmt-fusion]');
  ok('四流超宽表已渲染', `${table.colCount} 列 / ${table.rowCount} 行`);

  // —— 用户点名的 12 类信息，逐项确认列在 ——
  const required = [
    ['业务日期', 'business_date'],
    ['送货日期', 'delivery_date'],
    ['发货时间', 'shipped_at'],
    ['签收状态', 'sign_status'],
    ['合同编号', 'contract_no'],
    ['单据号', 'source_no'],
    ['开票状态', 'invoice_status'],
    ['开票时间', 'invoiced_at'],
    ['发票号码', 'invoice_no'],
    ['收款流水号', 'flow_no'],
    ['收付款时间', 'paid_at'],
    ['收款方式', 'payment_method'],
    ['金额', 'amount'],
    ['收付款金额', 'paid_amount'],
    ['剩余欠款', 'remaining_debt'],
    ['开票金额', 'invoiced_amount'],
    ['欠票金额', 'uninvoiced_amount'],
  ];
  const missing = required.filter(([, field]) => !table.ths.includes(field));
  if (missing.length) fail('12 类信息全部有对应列', `缺：${missing.map(([l]) => l).join('、')}`);
  ok('12 类信息全部有对应列', `${required.length} 项逐一对上`);

  if (!(table.scrollWidth > table.clientWidth + 40)) {
    fail('表宽超出可视区（需要横向滚动）', `scroll ${table.scrollWidth} vs client ${table.clientWidth}`);
  }
  ok('表宽超出可视区，横向滚动可用', `${table.scrollWidth}px / ${table.clientWidth}px`);

  // —— 冻结列：前 3 列必须各有不同的 left（旧实现全钉在同一个 left，会互相盖住）——
  const frozen = await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-fusion]');
    const ths = [...root.querySelectorAll('thead th.is-frozen')];
    return ths.map((th) => ({
      field: th.getAttribute('data-col'),
      left: Math.round(th.getBoundingClientRect().left),
      width: Math.round(th.getBoundingClientRect().width),
    }));
  });
  const lefts = frozen.map((f) => f.left);
  const uniqueLefts = new Set(lefts);
  if (frozen.length < 3) fail('冻结列数量', `只有 ${frozen.length} 列`);
  if (uniqueLefts.size !== frozen.length) fail('冻结列各自独立定位（不重叠）', JSON.stringify(frozen));
  ok('冻结列各自独立定位（不重叠）', frozen.map((f) => `${f.field}@${f.left}`).join(' '));

  // 超宽表在页面下方，先把它的表头滚进视口 —— 否则 getBoundingClientRect 落在
  // 视口外，elementFromPoint 拿到 null，鼠标事件直接丢进空气里（第一版就这么假红过）。
  await page.evaluate(() => {
    const root = document.querySelector('[data-stmt-fusion]');
    if (root) root.scrollIntoView({ block: 'center' });
  });
  await sleep(600);

  // —— 列宽拖拽（真实鼠标坐标）——
  const gripBox = await page.evaluate(() => {
    const grip = document.querySelector('[data-col-grip="contract_no"]');
    if (!grip) return null;
    const r = grip.getBoundingClientRect();
    const th = grip.closest('th');
    return {
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      width: Math.round(th.getBoundingClientRect().width),
    };
  });
  if (!gripBox) fail('合同编号列有拖拽抓手', '没找到 [data-col-grip="contract_no"]');
  ok('合同编号列有拖拽抓手', `当前宽 ${gripBox.width}px`);

  await page.mouse.move(gripBox.x, gripBox.y);
  await page.mouse.down();
  await page.mouse.move(gripBox.x + 70, gripBox.y, { steps: 8 });
  await page.mouse.up();
  await sleep(500);

  const afterDrag = await page.evaluate(() => {
    const th = document.querySelector('[data-col="contract_no"]');
    const saved = localStorage.getItem('erp:colw:stmt-fusion');
    return { width: th ? Math.round(th.getBoundingClientRect().width) : 0, saved };
  });
  if (afterDrag.width < gripBox.width + 40) {
    fail('拖拽后列宽真的变宽', `${gripBox.width} → ${afterDrag.width}`);
  }
  ok('拖拽后列宽真的变宽', `${gripBox.width} → ${afterDrag.width}px`);
  if (!afterDrag.saved || !afterDrag.saved.includes('contract_no')) {
    fail('列宽已写入 localStorage（刷新不丢）', String(afterDrag.saved));
  }
  ok('列宽已写入 localStorage（刷新不丢）', String(afterDrag.saved).slice(0, 48));

  // —— 双击复位 ——
  const grip2 = await page.evaluate(() => {
    const grip = document.querySelector('[data-col-grip="contract_no"]');
    const r = grip.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  });
  // ⚠️ 不能用 click({clickCount:2})：那只发一次 pointerdown（clickCount 只是事件属性），
  //    而复位是靠"自己数两次按下"（PointerEvent.detail 恒为 0，读不到点击次数）。
  //    真人双击 = 两次 down/up，这里照真人的节奏点两次。
  await page.mouse.click(grip2.x, grip2.y);
  await sleep(120);
  await page.mouse.click(grip2.x, grip2.y);
  await sleep(400);
  const afterReset = await page.evaluate(() => {
    const th = document.querySelector('[data-col="contract_no"]');
    const saved = localStorage.getItem('erp:colw:stmt-fusion') || '{}';
    return { width: th ? Math.round(th.getBoundingClientRect().width) : 0, saved };
  });
  if (Math.abs(afterReset.width - gripBox.width) > 6) {
    fail('双击抓手复位到默认宽度', `${afterReset.width} vs 默认 ${gripBox.width}`);
  }
  ok('双击抓手复位到默认宽度', `${afterReset.width}px`);
  if (afterReset.saved.includes('contract_no')) fail('复位后 localStorage 里该列已清除', afterReset.saved);
  ok('复位后 localStorage 里该列已清除');

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  const shot = path.join(SHOT_DIR, 'e2e_statement_wide_12cols.png');
  await page.screenshot({ path: shot, fullPage: false });
  console.log(`  📸 ${path.basename(shot)}`);

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_statement_wide.png') });
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
