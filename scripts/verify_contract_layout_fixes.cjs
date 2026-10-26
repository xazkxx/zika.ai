/**
 * 购销合同页三处布局修复验收（2026-10-23）
 *
 * 全部用**几何测量**判定，不看截图猜：
 *   ① 列表操作列：三颗按钮必须都落在表格容器内（右边界不超出容器右边界），且不换行；
 *   ② 客户下拉：客户名的盒子要比编码盒子宽（名称占主位），面板不小于 360px；
 *   ③ 详情弹窗：宽度 ≥ 900px，明细表容器可横向滚动，各列宽度不被压到 60px 以下。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_contract_layout_fixes.cjs
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

  // 准备：一个名字很长的客户（专门用来触发"名称被挤压"）+ 5 行明细的合同
  const customer = await api('POST', '/api/v1/customers', {
    code: `CUS-${TAG}`,
    name: `陕北至关中第三通道750千伏输变电工程(包${TAG})甲供材料项目部有限公司`,
  });
  if (customer.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(customer.data)}`);

  const items = [];
  for (let i = 0; i < 5; i += 1) {
    const product = await api('POST', '/api/v1/products', {
      sku: `SKU-L${TAG}-${i}`,
      name: `测试线缆${TAG}-${i}`,
      unit: '米',
      standards: 'ZRC-YJV-8.7/15kV-3×240',
    });
    if (product.status !== 201) throw new Error(`建商品失败 ${JSON.stringify(product.data)}`);
    items.push({ product_id: product.data.id, quantity: 100 + i, unit_price: 88.5 + i });
  }
  const contract = await api('POST', '/api/v1/contracts', {
    direction: 'out',
    party_id: customer.data.id,
    party_name: customer.data.name,
    sign_date: TODAY,
    delivery_date: '2026-11-20',
    delivery_place: '西安市高新区工地现场A区',
    items,
  });
  if (contract.status !== 201) throw new Error(`建合同失败 ${JSON.stringify(contract.data)}`);
  ok('准备：长名称客户 + 5 行明细的合同', `${contract.data.contract_no}`);

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    // 视口可用 WIDTH 覆盖：默认按用户真实屏幕 1920 验"常态"，
    // 窄屏（1440/1280）另外跑一遍看降级是否可接受。
    defaultViewport: { width: Number(process.env.WIDTH || 1920), height: 1000 },
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

  // ============ ① 列表操作列不溢出 ============
  const list = await page.evaluate((no) => {
    const wrap = document.querySelector('.contract-list-scroll');
    const table = document.querySelector('.contract-list-table');
    if (!wrap || !table) return { ok: false };
    const wrapRect = wrap.getBoundingClientRect();
    const rows = [...table.querySelectorAll('tbody tr')];
    const row = rows.find((r) => (r.textContent || '').includes(no));
    if (!row) return { ok: false, reason: '找不到合同行' };
    const cell = row.querySelector('.contract-row-actions');
    const buttons = [...(cell ? cell.querySelectorAll('button') : [])].map((b) => {
      const r = b.getBoundingClientRect();
      return { text: (b.textContent || '').trim(), left: r.left, right: r.right, top: r.top, width: r.width };
    });
    const cellRect = cell ? cell.getBoundingClientRect() : null;
    return {
      ok: true,
      wrapRight: wrapRect.right,
      wrapLeft: wrapRect.left,
      scrollable: wrap.scrollWidth > wrap.clientWidth + 4,
      buttons,
      cellRight: cellRect ? cellRect.right : null,
      cellLeft: cellRect ? cellRect.left : null,
      display: cell ? getComputedStyle(cell).display : '',
      rowsInline: buttons.map((b) => `${b.text}:${Math.round(b.left)}-${Math.round(b.right)}`),
    };
  }, contract.data.contract_no);

  if (!list.ok) fail('列表页结构正确', list.reason || '找不到滚动容器/表格');
  ok('列表已套横向滚动容器', list.scrollable ? '内容超宽时可滚' : '当前无需滚动');

  if (list.display !== 'flex') fail('操作列是 flex 布局（按钮不换行）', list.display);
  ok('操作列是 flex 布局', list.display);

  if (list.buttons.length !== 3) fail('操作列有三颗按钮', `${list.buttons.length} 颗`);
  const overflow = list.buttons.filter((b) => b.right > list.wrapRight + 1);
  if (overflow.length) {
    fail(
      '按钮全部落在表格容器内（不飞出边框）',
      `溢出：${overflow.map((b) => `${b.text} 右边界 ${Math.round(b.right)} > 容器 ${Math.round(list.wrapRight)}`).join('；')}`,
    );
  }
  ok('按钮全部落在表格容器内（不飞出边框）', list.rowsInline.join(' | '));

  const sameRow = Math.max(...list.buttons.map((b) => b.top)) - Math.min(...list.buttons.map((b) => b.top));
  if (sameRow > 6) fail('三颗按钮在同一行（没被挤成两行）', `top 差 ${Math.round(sameRow)}px`);
  ok('三颗按钮在同一行', `top 差 ${Math.round(sameRow)}px`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_layout_list.png') });
  console.log('  📸 e2e_contract_layout_list.png');

  // ============ ② 客户下拉名称占主位 ============
  await page.evaluate(() => {
    const box = document.querySelector('.erp-form .ssel');
    box?.querySelector('.ssel-trigger')?.click();
  });
  await sleep(700);

  const dropdown = await page.evaluate(() => {
    const panel = document.querySelector('.ssel-panel');
    if (!panel) return { ok: false };
    const option = panel.querySelector('.ssel-option');
    if (!option) return { ok: false, reason: '面板里没有选项' };
    const label = option.querySelector('.ssel-option-label');
    const meta = option.querySelector('.ssel-option-meta');
    const labelRect = label ? label.getBoundingClientRect() : null;
    const metaRect = meta ? meta.getBoundingClientRect() : null;
    const optionRect = option.getBoundingClientRect();
    return {
      ok: true,
      panelWidth: panel.getBoundingClientRect().width,
      optionWidth: optionRect.width,
      labelWidth: labelRect ? labelRect.width : 0,
      metaWidth: metaRect ? metaRect.width : 0,
      labelFlexBasis: label ? getComputedStyle(label).flexBasis : '',
      text: (option.textContent || '').trim().slice(0, 40),
    };
  });
  if (!dropdown.ok) fail('客户下拉能打开', dropdown.reason || '没有 .ssel-panel');
  if (dropdown.panelWidth < 350) fail('下拉面板宽度 ≥ 350px', `${Math.round(dropdown.panelWidth)}px`);
  ok('下拉面板宽度足够', `${Math.round(dropdown.panelWidth)}px`);

  // 名称必须明显比编码宽（编码最多 32%）
  if (dropdown.metaWidth && dropdown.labelWidth < dropdown.metaWidth) {
    fail('客户名比客户编码宽（名称占主位）', `名称 ${Math.round(dropdown.labelWidth)}px / 编码 ${Math.round(dropdown.metaWidth)}px`);
  }
  const metaRatio = dropdown.optionWidth ? dropdown.metaWidth / dropdown.optionWidth : 0;
  if (metaRatio > 0.34) fail('编码最多占选项宽度的 32%', `实际 ${(metaRatio * 100).toFixed(0)}%`);
  ok('客户名占主位、编码被限宽', `名称 ${Math.round(dropdown.labelWidth)}px · 编码 ${Math.round(dropdown.metaWidth)}px（${(metaRatio * 100).toFixed(0)}%）`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_layout_dropdown.png') });
  console.log('  📸 e2e_contract_layout_dropdown.png');
  await page.keyboard.press('Escape');
  await sleep(400);

  // ============ ③ 详情弹窗加宽 + 明细表可横滑 ============
  await page.evaluate((no) => {
    const tr = [...document.querySelectorAll('.contract-list-table tbody tr')].find((r) =>
      (r.textContent || '').includes(no),
    );
    if (tr) tr.click();
  }, contract.data.contract_no);
  await sleep(1200);

  const modal = await page.evaluate(() => {
    const card = document.querySelector('[data-contract-detail-modal]');
    if (!card) return { ok: false };
    const cardRect = card.getBoundingClientRect();
    const wrap = card.querySelector('.contract-detail__table-wrap');
    const table = card.querySelector('.contract-detail-table');
    if (!wrap || !table) return { ok: false, reason: '弹窗里没有明细表' };
    const headCells = [...table.querySelectorAll('thead th')].map((th) => ({
      text: (th.textContent || '').trim(),
      width: Math.round(th.getBoundingClientRect().width),
      left: Math.round(th.getBoundingClientRect().left),
    }));
    const rowCells = [...(table.querySelector('tbody tr')?.children || [])].map((td) => ({
      width: Math.round(td.getBoundingClientRect().width),
      left: Math.round(td.getBoundingClientRect().left),
      right: Math.round(td.getBoundingClientRect().right),
    }));
    return {
      ok: true,
      modalWidth: cardRect.width,
      modalLeft: cardRect.left,
      modalRight: cardRect.right,
      viewportWidth: window.innerWidth,
      wrapScrollWidth: wrap.scrollWidth,
      wrapClientWidth: wrap.clientWidth,
      tableMinWidth: getComputedStyle(table).minWidth,
      headCells,
      rowCells,
      bodyScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
    };
  });
  if (!modal.ok) fail('合同详情弹窗能打开', modal.reason || '找不到弹窗');
  if (modal.modalWidth < 900) fail('详情弹窗宽度 ≥ 900px', `${Math.round(modal.modalWidth)}px`);
  ok('详情弹窗已加宽', `${Math.round(modal.modalWidth)}px（视口 ${modal.viewportWidth}）`);

  const narrowCols = modal.headCells.filter((c) => c.width < 60);
  if (narrowCols.length) {
    fail('各列宽度不被压到 60px 以下', narrowCols.map((c) => `${c.text}=${c.width}px`).join('、'));
  }
  ok('各列宽度正常', modal.headCells.map((c) => `${c.text}${c.width}`).join(' · '));

  // 表头与数据行逐列对齐（同一次修复的口径）
  const misaligned = modal.headCells.filter((head, index) => {
    const cell = modal.rowCells[index];
    return cell && Math.abs(head.left - cell.left) > 1;
  });
  if (misaligned.length) fail('表头与数据行逐列对齐', `${misaligned.length} 列错位`);
  ok('表头与数据行逐列对齐', `${modal.headCells.length} 列`);

  const bodyOverflow = modal.bodyScroll;
  if (bodyOverflow) fail('弹窗内容不撑破页面（不出现整页横向滚动条）', 'document 出现横向滚动');
  ok('弹窗内容不撑破页面', `表格容器 ${modal.wrapScrollWidth}/${modal.wrapClientWidth}${modal.wrapScrollWidth > modal.wrapClientWidth ? '（可横滑）' : ''}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_contract_layout_modal.png') });
  console.log('  📸 e2e_contract_layout_modal.png');

  // 收尾
  await api('DELETE', `/api/v1/contracts/${contract.data.id}?force=true`);
  for (const item of items) await api('DELETE', `/api/v1/products/${item.product_id}?force=true`);
  await api('DELETE', `/api/v1/customers/${customer.data.id}`);

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_contract_layout.png') });
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
