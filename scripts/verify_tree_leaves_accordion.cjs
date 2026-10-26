/**
 * 三个闭环的验收（2026-10-21 第四轮）。
 *
 * ① 手风琴 + 客户叶子：展开分类 → 该分类下的客户平铺出现；再展开同级另一个
 *    一级节点 → 前一个连同子级/客户一起折叠。
 * ② 拖拽后右侧列表不能"假装为空"：拖完立刻能看到刚拖进去的那条，
 *    且批量条不再喊"已选中 N 项但不在当前筛选内"。
 * ③ 脏数据：确认「折叠目标-*」已被清掉（脚本只做只读检查）。
 */
const path = require('path');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
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

  // 造两个一级分类，各挂 1~2 个客户，用来测"手风琴"和"叶子平铺"
  const tag = Date.now().toString().slice(-6);
  const A = await call('POST', '/api/v1/customer-categories', { name: `手风琴A-${tag}`, parent_id: null });
  const A1 = await call('POST', '/api/v1/customer-categories', { name: `A子级-${tag}`, parent_id: A.body.id });
  const B = await call('POST', '/api/v1/customer-categories', { name: `手风琴B-${tag}`, parent_id: null });
  const ca = await call('POST', '/api/v1/customers', { code: `CUST-ACC-A-${tag}`, name: `A客户甲-${tag}`, category_id: A.body.id });
  const ca2 = await call('POST', '/api/v1/customers', { code: `CUST-ACC-A2-${tag}`, name: `A客户乙-${tag}`, category_id: A.body.id });
  const cb = await call('POST', '/api/v1/customers', { code: `CUST-ACC-B-${tag}`, name: `B客户丙-${tag}`, category_id: B.body.id });

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

  const isExpanded = (id) =>
    page.evaluate((nid) => {
      const row = document.querySelector(`.ptree__row[data-node-id="${nid}"]`);
      return row ? row.getAttribute('aria-expanded') === 'true' : null;
    }, id);

  const clickCaret = async (id) => {
    await page.evaluate((nid) => {
      const row = document.querySelector(`.ptree__row[data-node-id="${nid}"]`);
      const caret = row && row.querySelector('.ptree__caret');
      if (caret) caret.click();
    }, id);
    await sleep(550);
  };

  /** 确保展开（已展开就不动，避免点成折叠） */
  const ensureExpanded = async (id) => {
    if ((await isExpanded(id)) !== true) await clickCaret(id);
    await sleep(250);
  };

  // ── ① 叶子平铺 ─────────────────────────────────────────────────────────
  await ensureExpanded(A.body.id);
  const leaves = await page.evaluate(() => [...document.querySelectorAll('.ptree__leaf[data-partner-leaf]')].map((el) => el.textContent.trim()));
  check(
    '展开分类后，该分类下的客户平铺出现在树里',
    leaves.some((t) => t.includes('A客户甲')) && leaves.some((t) => t.includes('A客户乙')),
    JSON.stringify(leaves.slice(0, 6)),
  );

  // ── ② 手风琴：展开 B（同级）→ A 及其子级/客户自动折叠 ─────────────────
  await clickCaret(B.body.id);
  const after = await page.evaluate(({ aid, bid }) => {
    const a = document.querySelector(`.ptree__row[data-node-id="${aid}"]`);
    const b = document.querySelector(`.ptree__row[data-node-id="${bid}"]`);
    const leafA = document.querySelector('.ptree__leaf[data-partner-leaf]');
    return {
      aOpen: a ? a.getAttribute('aria-expanded') : null,
      bOpen: b ? b.getAttribute('aria-expanded') : null,
      leafCount: document.querySelectorAll('.ptree__leaf[data-partner-leaf]').length,
      leafTexts: [...document.querySelectorAll('.ptree__leaf[data-partner-leaf]')].map((el) => el.textContent.trim()),
    };
  }, { aid: A.body.id, bid: B.body.id });
  check('展开另一个一级节点后，前一个自动折叠', after.aOpen === 'false' && after.bOpen === 'true', `A=${after.aOpen} B=${after.bOpen}`);
  check('旧节点的客户叶子也一并收起', !after.leafTexts.some((t) => t.includes('A客户甲')), JSON.stringify(after.leafTexts.slice(0, 4)));
  check('新展开的节点显示自己的客户', after.leafTexts.some((t) => t.includes('B客户丙')));

  // ── ③ 拖拽后右侧列表立刻有数据（不能"假装为空"）──────────────────────
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);
  await ensureExpanded(A.body.id); // 展开 A，好把叶子拖出去

  const dragResult = await page.evaluate(async ({ leafText, targetId }) => {
    const leaf = [...document.querySelectorAll('.ptree__leaf[data-partner-leaf]')].find((el) => (el.textContent || '').includes(leafText));
    const target = document.querySelector(`.ptree__row[data-node-id="${targetId}"]`);
    if (!leaf || !target) return { ok: false, why: `leaf=${Boolean(leaf)} target=${Boolean(target)}` };
    const dt = new DataTransfer();
    leaf.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
    target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
    target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
    leaf.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    return { ok: true };
    // 拖 A 自己名下的客户（此刻可见）到 A 的子分类 A1。
    // 注意不能用 B 的客户：手风琴刚把 B 折叠了，它的叶子已经不在 DOM 里 —— 这是对的。
  }, { leafText: `A客户甲-${tag}`, targetId: A1.body.id });
  check('可以把「分类下的客户叶子」拖到另一个分类', dragResult.ok, dragResult.why || '');

  await sleep(1500);
  const listState = await page.evaluate(() => ({
    rows: document.querySelectorAll('tbody tr').length,
    texts: [...document.querySelectorAll('tbody tr')].map((tr) => (tr.textContent || '').trim().slice(0, 30)),
    bulkbar: (document.querySelector('.erp-table-bulkbar') || {}).textContent || '',
    empty: (document.querySelector('.erp-table__state-cell') || {}).textContent || '',
  }));
  check('拖完右侧列表立刻显示刚拖进去的那条', listState.rows === 1 && listState.texts[0].includes('A客户甲'), `${listState.rows} 行 / ${listState.texts[0] || ''}`);
  check('不再出现"已选中 N 项，但不在当前筛选内"', !/不在当前筛选内/.test(listState.bulkbar), listState.bulkbar.slice(0, 40));

  // ── ④ 脏数据已清理 ─────────────────────────────────────────────────────
  const cats = await call('GET', '/api/v1/customer-categories');
  const walk = (nodes) => nodes.flatMap((n) => [n.name, ...walk(n.children || [])]);
  const names = walk(cats.body || []);
  check('「折叠目标-*」测试脏数据已从库里删除', !names.some((n) => /^折叠(目标|子级)-/.test(n)), names.filter((n) => /折叠/.test(n)).join(',') || '干净');

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理本轮造的数据
  for (const cu of [ca.body, ca2.body, cb.body]) if (cu && cu.id) await call('DELETE', `/api/v1/customers/${cu.id}`);
  await call('DELETE', `/api/v1/customer-categories/${A1.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${A.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${B.body.id}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
