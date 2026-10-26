/**
 * 截图：行内编辑（双击名称格）+ 点分类立即加载。
 */
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(WS + '/puppeteer-core');
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = 'http://127.0.0.1:8010';
const OUT = 'E:/AI/ERP软件/docs/验收截图';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const { access_token: token } = await login.json();

  const b = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 900 },
  });
  const p = await b.newPage();
  await p.goto(BASE, { waitUntil: 'networkidle2' });
  await p.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await p.reload({ waitUntil: 'networkidle2' });
  await p.waitForSelector('.nav-group-title');
  await p.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(400);
  await p.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '客户档案');
    if (it) it.click();
  });
  await sleep(1800);

  // 点一个分类（验证右侧立刻加载）
  await p.evaluate(() => {
    const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes('国家电网'));
    if (el) el.click();
  });
  await sleep(800);

  // 双击第一行的名称格（合成 dblclick，与真实双击等价）
  await p.evaluate(() => {
    const tr = document.querySelector('tbody tr');
    if (!tr) return;
    const td = tr.children[2];
    td.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
  });
  await sleep(400);
  await p.screenshot({ path: OUT + '/v156_行内编辑_双击改名.png' });
  console.log('shot ok');
  await b.close();
})();
