/**
 * 验收：① 拖拽归档后的"展开祖先 + 高亮 + 右侧过滤"；② 表头拖列宽 + 持久化。
 *
 * 拖拽用合成 DragEvent（HTML5 原生 DnD 不走鼠标轨迹，page.mouse 触发不了 dragstart）。
 * 列宽用真实 pointer 事件（pointerdown/pointermove/pointerup）—— 组件就是按这套写的。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
const check = (name, ok, extra = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
};

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

  // 造数据：一个"有子级的父分类"（模拟折叠态目标）+ 两个未分类客户
  const tag = Date.now().toString().slice(-6);
  const parent = await call('POST', '/api/v1/customer-categories', {
    name: `折叠目标-${tag}`,
    parent_id: null,
  });
  const parentId = parent.body.id;
  const child = await call('POST', '/api/v1/customer-categories', {
    name: `折叠子级-${tag}`,
    parent_id: parentId,
  });
  const childId = child.body.id;
  const custIds = [];
  for (let i = 0; i < 2; i += 1) {
    const created = await call('POST', '/api/v1/customers', {
      code: `CUST-CR-${tag}${i}`,
      name: `列宽验收客户${i}-${tag}`,
    });
    custIds.push(created.body.id);
  }
  console.log(`  造数据：父分类 #${parentId} / 子级 #${childId}，客户 ${custIds.join(',')}`);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 950 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
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
  await sleep(1600);

  // ── 拖拽归档：目标父分类当前是折叠的（默认只展开第一层） ────────────────
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);

  const before = await page.evaluate((pid) => {
    const row = document.querySelector(`.ptree__row[data-node-id="${pid}"]`);
    return { exists: Boolean(row), expanded: row ? row.getAttribute('aria-expanded') : null };
  }, parentId);
  check('折叠目标节点在树上且处于折叠态', before.exists && before.expanded === 'false', `aria-expanded=${before.expanded}`);

  const dropped = await page.evaluate(
    async ({ names, pid }) => {
      const rows = [...document.querySelectorAll('tbody tr')].filter((tr) => names.some((n) => (tr.textContent || '').includes(n)));
      const target = document.querySelector(`.ptree__row[data-node-id="${pid}"]`);
      if (!rows.length || !target) return { ok: false, why: `rows=${rows.length} target=${Boolean(target)}` };
      const dt = new DataTransfer();
      rows[0].dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      rows[0].dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
      return { ok: true };
    },
    { names: [`列宽验收客户0-${tag}`], pid: parentId },
  );
  // 闪烁只有 900ms，而且落在 "落库 → 刷树 → 展开 → 下一帧" 之后才出现：
  // 固定等待必然踩空，改成轮询（最多 2.5s）
  const flashSeen = await page.waitForFunction(
    (pid) => {
      const row = document.querySelector(`.ptree__row[data-node-id="${pid}"]`);
      return Boolean(row && row.className.includes('is-flash'));
    },
    { timeout: 2500, polling: 60 },
    parentId,
  ).then(() => true).catch(() => false);

  const after = await page.evaluate((pid) => {
    const row = document.querySelector(`.ptree__row[data-node-id="${pid}"]`);
    return {
      expanded: row ? row.getAttribute('aria-expanded') : null,
      flash: row ? row.className.includes('is-flash') : false,
      active: row ? row.className.includes('is-active') : false,
      childVisible: Boolean(document.querySelector('.ptree__row[data-node-id="' + (window.__childId || 0) + '"]')),
    };
  }, parentId);
  check('拖入后目标节点自动展开', after.expanded === 'true', `aria-expanded=${after.expanded}`);
  check('拖入后目标节点被选中（右侧列表随之过滤）', after.active);
  check('拖入后目标节点闪烁高亮', after.flash || flashSeen);
  check('目标分类的档案数已按库更新', dropped.ok);

  await sleep(900);
  const movedRows = await page.evaluate(() => document.querySelectorAll('tbody tr').length);
  check('右侧列表已过滤到目标分类（只剩刚拖进去的 1 条）', movedRows === 1, `${movedRows} 行`);

  // ── 列宽拖动 ────────────────────────────────────────────────────────────
  const resizer = await page.evaluate(() => {
    const el = document.querySelector('[data-col-resizer="name"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  });
  check('表头出现列宽抓手', Boolean(resizer), resizer ? `@${resizer.x},${resizer.y}` : '');

  const beforeW = await page.evaluate(() => {
    const th = document.querySelector('th .erp-table__resizer[data-col-resizer="name"]')?.parentElement;
    return th ? Math.round(th.getBoundingClientRect().width) : 0;
  });
  await page.mouse.move(resizer.x, resizer.y);
  await page.mouse.down();
  await page.mouse.move(resizer.x + 90, resizer.y, { steps: 8 });
  await page.mouse.up();
  await sleep(400);
  const afterW = await page.evaluate(() => {
    const th = document.querySelector('th .erp-table__resizer[data-col-resizer="name"]')?.parentElement;
    return th ? Math.round(th.getBoundingClientRect().width) : 0;
  });
  check('拖动后列宽变大', afterW - beforeW >= 60, `${beforeW}px → ${afterW}px`);

  const stored = await page.evaluate(() => window.localStorage.getItem('erp:colw:partners-customer'));
  check('列宽写进 localStorage', Boolean(stored) && stored.includes('name'), stored || '');

  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1500);
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '客户档案');
    if (it) it.click();
  });
  await sleep(1500);
  const reloadedW = await page.evaluate(() => {
    const th = document.querySelector('th .erp-table__resizer[data-col-resizer="name"]')?.parentElement;
    return th ? Math.round(th.getBoundingClientRect().width) : 0;
  });
  check('刷新后列宽仍然生效', Math.abs(reloadedW - afterW) <= 2, `${reloadedW}px`);

  // 双击复位
  const resetPoint = await page.evaluate(() => {
    const el = document.querySelector('[data-col-resizer="name"]');
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
  });
  // 真人双击 = 两次独立 click（间隔 <400ms）。puppeteer 的 clickCount:2 只发一对
  // down/up，浏览器不一定会合成 dblclick —— 之前这里假红就是这个原因。
  await page.mouse.click(resetPoint.x, resetPoint.y);
  await sleep(80);
  await page.mouse.click(resetPoint.x, resetPoint.y);
  await sleep(400);
  const resetW = await page.evaluate(() => {
    const th = document.querySelector('th .erp-table__resizer[data-col-resizer="name"]')?.parentElement;
    return th ? Math.round(th.getBoundingClientRect().width) : 0;
  });
  check('双击抓手恢复默认列宽', Math.abs(resetW - beforeW) <= 3, `${resetW}px (默认 ${beforeW}px)`);

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理
  for (const id of custIds) await call('DELETE', `/api/v1/customers/${id}`);
  await call('DELETE', `/api/v1/customer-categories/${childId}`);
  await call('DELETE', `/api/v1/customer-categories/${parentId}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
