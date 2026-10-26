/**
 * 截图：编辑客户弹窗里「所属分类」的回显 + 展开后的树（修复后）。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
const OUT = 'E:/AI/ERP软件/docs/验收截图';
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
    args: ['--no-sandbox'],
    defaultViewport: { width: 1500, height: 950 },
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
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);
  // 编辑「湖南华邦建设有限公司」（分类=储能，就是用户截图里显示 330 的那条）
  await page.evaluate(() => {
    const row = [...document.querySelectorAll('tbody tr')].find((tr) => (tr.textContent || '').includes('湖南华邦建设'));
    if (!row) return;
    const btn = [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '编辑');
    if (btn) btn.click();
  });
  await sleep(900);
  // 展开树
  await page.evaluate(() => {
    const trig = document.querySelector('[data-erp-tree-select-field="category_id"] .tsel-trigger');
    if (!trig) return;
    trig.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    trig.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await sleep(700);
  // 展开各级，露出「储能」
  await page.evaluate(async () => {
    const panel = document.querySelector('.tsel-panel');
    if (!panel) return;
    const rows = () => [...panel.querySelectorAll('.tsel-row.is-branch')];
    for (let i = 0; i < 3; i += 1) {
      const target = rows().find((r) => /其他客户/.test(r.textContent || '')) || rows()[rows().length - 1];
      if (!target) break;
      const caret = target.querySelector('.tsel-row__caret');
      (caret || target).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 350));
    }
  });
  await sleep(600);
  await page.screenshot({ path: path.join(OUT, 'v134_客户分类树下拉_修复后.png') });
  console.log('shot ok');
  await browser.close();
})();
