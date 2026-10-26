/**
 * 拖拽视觉截图：展开「未分类」+ 制造一次"正在拖到分类节点上"的高亮。
 * 只截图，不改数据（drop 前就结束）。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
const OUT = 'E:/AI/ERP软件/docs/验收截图';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();
  const H = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const tag = Date.now().toString().slice(-6);
  const cat = await fetch(`${BASE}/api/v1/customer-categories`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ name: `集团客户（拖拽示例）`, parent_id: null }),
  }).then((r) => r.json());

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 950 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
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
  await sleep(1600);
  // 展开未分类 + 全部客户
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部客户/.test((el.textContent || '').trim()));
    if (all) all.click();
    const t = document.querySelector('[data-uncat-toggle]');
    if (t) t.click();
  });
  await sleep(900);
  // 制造高亮：拖第一行到"集团客户（拖拽示例）"
  await page.evaluate(async () => {
    const row = document.querySelector('tbody tr.is-draggable-row');
    const target = [...document.querySelectorAll('.ptree__row')].find((el) => (el.textContent || '').includes('集团客户（拖拽示例）'));
    if (!row || !target) return;
    const dt = new DataTransfer();
    row.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
    target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    document.body.dataset.partnerDragging = '1';
  });
  await sleep(400);
  await page.screenshot({ path: path.join(OUT, 'v132_拖拽归档_高亮.png') });
  console.log('shot ok, category id =', cat.id);
  await browser.close();
  // 清掉示例分类（里面没有客户）
  await fetch(`${BASE}/api/v1/customer-categories/${cat.id}`, { method: 'DELETE', headers: H });
})();
