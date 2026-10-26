/**
 * 临时诊断：拦截批量移动请求，打印真实 URL / 响应 / 状态
 * node scripts/_dbg_batchmove.cjs
 */
const fs = require('fs');
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = [
  'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
const API = `${BASE}/api/v1`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const res0 = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const token = (await res0.json()).access_token;
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'], defaultViewport: { width: 1600, height: 1000 } });
  const page = await browser.newPage();
  page.on('request', (r) => {
    if (/product/i.test(r.url()) && r.method() !== 'GET') {
      console.log('[REQ]', r.method(), r.url());
      console.log('      body:', String(r.postData() || '').slice(0, 300));
    }
  });
  page.on('response', async (r) => {
    if (/batch-category|\/products\/[^/]+$/.test(new URL(r.url()).pathname) && r.request().method() !== 'GET') {
      let body = '';
      try { body = (await r.text()).slice(0, 400); } catch (e) { body = `<no body: ${e.message}>`; }
      console.log('[RES]', r.status(), r.url());
      console.log('      ', body);
    }
  });
  page.on('console', (m) => { if (m.type() === 'error') console.log('[CONSOLE-ERR]', m.text().slice(0, 300)); });
  page.on('pageerror', (e) => console.log('[PAGEERR]', e.message));

  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await sleep(2500);
  await page.evaluate(() => {
    const has = [...document.querySelectorAll('.nav-item')].some((e) => /商品档案/.test(e.textContent));
    if (has) return;
    const t = [...document.querySelectorAll('.nav-group-title')].find((x) => /基础资料|资料|档案/.test(x.textContent));
    if (t) t.click();
  });
  await sleep(600);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find((e) => /商品档案/.test(e.textContent));
    if (item) item.click();
  });
  await sleep(2500);
  await page.evaluate(() => {
    const roots = [...document.querySelectorAll('.category-tree *')];
    const all = roots.find((e) => /^全部/.test(e.textContent.trim()) && e.children.length === 0);
    if (all) all.click();
  });
  await sleep(1800);

  const checkedIds = await page.evaluate(() => {
    const boxes = [...document.querySelectorAll('tbody input[type="checkbox"]')];
    boxes.slice(0, 2).forEach((b) => b.click());
    return boxes.length;
  });
  await sleep(400);
  await page.evaluate(() => document.querySelector('[data-product-batch-move]').click());
  await sleep(700);

  const picked = await page.evaluate(async () => {
    const host = document.querySelector('[data-erp-tree-select="product-batch-move"]');
    host.querySelector('.tsel-trigger').click();
    await new Promise((r) => setTimeout(r, 400));
    let rows = [...document.querySelectorAll('.tsel-row[data-tsel-key]')];
    let leaf = rows.find((r) => r.dataset.tselLeaf === '1');
    if (!leaf) {
      rows.find((r) => r.dataset.tselLeaf === '0').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 450));
      leaf = [...document.querySelectorAll('.tsel-row[data-tsel-key]')].find((r) => r.dataset.tselLeaf === '1');
    }
    if (!leaf) return 'no leaf';
    leaf.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 300));
    const trig = host.querySelector('.tsel-trigger');
    const btn = document.querySelector('[data-batch-move-submit]');
    return { picked: leaf.textContent.trim(), triggerText: trig.textContent.trim(), disabled: btn.disabled };
  });
  console.log('picked =', JSON.stringify(picked));
  console.log('--- 点击提交 ---');
  await page.evaluate(() => document.querySelector('[data-batch-move-submit]').click());
  await sleep(3000);
  const after = await page.evaluate(() => {
    const n = document.querySelector('.notice-box');
    return { notice: n ? n.textContent.trim() : '', dialog: Boolean(document.querySelector('[data-batch-move-dialog]')) };
  });
  console.log('after =', JSON.stringify(after));
  await browser.close();
})();
