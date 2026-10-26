/**
 * 用**真实拖拽**复现「拖进 A 却提示 B / 右侧不联动」。
 *
 * 之前的验收都是 `new DragEvent(...)` 直接 dispatch 到目标节点上 —— 那绕过了浏览器的
 * 命中测试，根本测不到"鼠标实际落在哪一行"。这里改用 Puppeteer 的拖拽拦截
 * （setDragInterception），让 Chrome 自己走原生 HTML5 DnD。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();
  const H = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const call = (m, u, b) =>
    fetch(`${BASE}${u}`, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined }).then(async (r) => ({
      status: r.status,
      body: await r.json().catch(() => ({})),
    }));

  const tag = Date.now().toString().slice(-6);
  const cust = await call('POST', '/api/v1/customers', { code: `CUST-DNDREAL-${tag}`, name: `真拖客户-${tag}` });
  console.log('造客户', cust.body.id);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 950 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
  await page.setDragInterception(true);
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(400);
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '客户档案');
    if (it) it.click();
  });
  await sleep(1800);
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);

  // 找到目标节点「国家电网公司」的真实屏幕坐标（取行中央，避开上下边缘）
  const pick = async (selector, byText) => {
    return page.evaluate(({ selector, byText }) => {
      const els = [...document.querySelectorAll(selector)];
      const el = byText ? els.find((e) => (e.textContent || '').includes(byText)) : els[0];
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), text: (el.textContent || '').trim().slice(0, 20) };
    }, { selector, byText });
  };

  const src = await pick('tbody tr', `真拖客户-${tag}`);
  const dst = await pick('.ptree__row', '国家电网公司');
  console.log('拖拽起点', src);
  console.log('拖拽终点', dst);

  const data = await page.mouse.drag(src, dst);
  await page.mouse.dragEnter(dst, data);
  await page.mouse.dragOver(dst, data);
  await page.mouse.drop(dst, data);
  await sleep(1600);

  const state = await page.evaluate(() => ({
    toast: (document.querySelector('.notice, .toast, [role="status"]') || {}).textContent || '',
    rows: document.querySelectorAll('tbody tr').length,
    empty: (document.querySelector('.erp-table__state-cell') || {}).textContent || '',
    header: (document.querySelector('.erp-card__sub, .partners-list__meta, .erp-card__title') || {}).textContent || '',
    treeActive: [...document.querySelectorAll('.ptree__row.is-active')].map((e) => (e.textContent || '').trim().slice(0, 20)),
    body: document.body.innerText.slice(0, 0),
  }));
  console.log('拖后状态', JSON.stringify(state, null, 1));

  // 服务端实际落到哪个分类
  const after = await call('GET', '/api/v1/customers');
  const row = (after.body || []).find((c) => c.name === `真拖客户-${tag}`);
  console.log('落库 category_id =', row && row.category_id, '（国家电网公司 id 应为 321）');
  console.log('errors', errors.slice(0, 3));

  if (row) await call('DELETE', `/api/v1/customers/${row.id}`);
  await browser.close();
})();
