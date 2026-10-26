/**
 * 临时排障：客户档案「导出」点下去到底发生了什么。
 * 不写断言，只把现场打出来（截图 + DOM 摘要 + 控制台报错）。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();
  page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 300)));
  page.on('console', (m) => {
    if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 300));
  });

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');
  await sleep(600);
  await page.evaluate(() => document.querySelectorAll('.nav-group-title.collapsed').forEach((el) => el.click()));
  await sleep(600);

  const clicked = await page.evaluate(() => {
    const item = Array.from(document.querySelectorAll('.nav-group-items .nav-item')).find(
      (el) => el.textContent.trim().indexOf('客户档案') === 0,
    );
    if (!item) return 'no-menu';
    item.click();
    return 'ok';
  });
  console.log('菜单:', clicked);
  await sleep(1500);

  const info = await page.evaluate(() => {
    const btn = document.querySelector('[data-export-open]');
    return {
      exists: !!btn,
      disabled: btn ? btn.disabled : null,
      text: btn ? btn.textContent.trim() : '',
      rect: btn ? btn.getBoundingClientRect().toJSON() : null,
      overlayCount: document.querySelectorAll('.modal-overlay').length,
    };
  });
  console.log('按钮:', JSON.stringify(info));

  // 用 DOM click，绕过坐标/遮挡问题
  await page.evaluate(() => document.querySelector('[data-export-open]').click());
  await sleep(800);
  const after = await page.evaluate(() => ({
    dialog: !!document.querySelector('[data-export-dialog]'),
    overlay: document.querySelectorAll('.modal-overlay').length,
    cardClass: (document.querySelector('.modal-overlay .modal-card') || {}).className || '',
    bodyTail: document.body.textContent.replace(/\s+/g, ' ').slice(-160),
  }));
  console.log('点击后:', JSON.stringify(after));
  await page.screenshot({ path: path.resolve(__dirname, '..', 'docs', '验收截图', 'debug-export.png') });
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
