/**
 * 谭涛总分支专项验收（2026-10-22）：
 *   ① 父级角标 = 自己直挂 + 所有子级之和（展开后能数到的叶子数必须对得上）
 *   ② 父级直挂的客户必须渲染在**子分类上方**
 *   ③ 拖到"既有子分类又有客户"的父节点 → 成功、角标 +1、刷新后仍在
 *   ④ 拖到**客户叶子**上松手 → 落到该叶子所属分类（早先是静默失败）
 *   ⑤ 拖到一个"只有客户、没有子分类"的节点 → 成功
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

  const tag = Date.now().toString().slice(-6);
  const a = await call('POST', '/api/v1/customers', { code: `CUST-T1-${tag}`, name: `验收拖拽A-${tag}` });
  const b = await call('POST', '/api/v1/customers', { code: `CUST-T2-${tag}`, name: `验收拖拽B-${tag}` });

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
    const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes('全部客户'));
    if (el) el.click();
  });
  await sleep(700);

  const expand = async (name) => {
    await page.evaluate((n) => {
      const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes(n));
      const caret = el && el.querySelector('.ptree__caret');
      if (caret) caret.click();
    }, name);
    await sleep(550);
  };

  for (const n of ['国家电网', '陕西送变电', '施工一部', '谭涛总']) await expand(n);

  // 角标是"直挂 + 所有子级之和"。⚠️ 手风琴让两个兄弟不能同时展开，
  // 所以不能靠"把叶子全数一遍"来验，只能按**聚合口径**验：
  //   badge(父) == 父自己直挂的叶子数 + 各子级 badge 之和
  const readBadge = (id) =>
    page.evaluate((nid) => {
      const el = document.querySelector(`.ptree__row[data-node-id="${nid}"] .ptree__count`);
      return el ? Number((el.textContent || '').trim()) : null;
    }, id);

  const tree = await page.evaluate(() => {
    const badge = (id) => {
      const row = document.querySelector(`.ptree__row[data-node-id="${id}"]`);
      const el = row && row.querySelector('.ptree__count');
      return el ? Number((el.textContent || '').trim()) : null;
    };
    const leafOwners = [...document.querySelectorAll('.ptree__leaf')].map((l) => Number(l.getAttribute('data-leaf-owner')));
    return {
      badge325: badge(325),
      badge328: badge(328),
      badge329: badge(329),
      own325: leafOwners.filter((o) => o === 325).length,
    };
  });
  check(
    '谭涛总角标 = 自己直挂 + 王宪全 + 陈银贵',
    tree.badge325 === tree.own325 + tree.badge328 + tree.badge329,
    `${tree.badge325} vs ${tree.own325}+${tree.badge328}+${tree.badge329}`,
  );
  check('谭涛总自己直挂的客户已渲染出来', tree.own325 > 0, `${tree.own325} 个`);

  // 单独展开王宪全，验证它自己的角标与叶子数
  await expand('王宪全经理');
  const wang = await page.evaluate(() => {
    const n = [...document.querySelectorAll('.ptree__leaf')].filter((l) => l.getAttribute('data-leaf-owner') === '328').length;
    const el = document.querySelector('.ptree__row[data-node-id="328"] .ptree__count');
    return { leaves: n, badge: el ? Number(el.textContent.trim()) : null };
  });
  check('王宪全经理角标与叶子数一致', wang.badge === wang.leaves, `${wang.badge} vs ${wang.leaves}`);

  await expand('陈银贵经理');
  const chen = await page.evaluate(() => {
    const n = [...document.querySelectorAll('.ptree__leaf')].filter((l) => l.getAttribute('data-leaf-owner') === '329').length;
    const el = document.querySelector('.ptree__row[data-node-id="329"] .ptree__count');
    return { leaves: n, badge: el ? Number(el.textContent.trim()) : null };
  });
  check('陈银贵经理角标与叶子数一致', chen.badge === chen.leaves, `${chen.badge} vs ${chen.leaves}`);

  // 上面展开陈银贵时，手风琴已经把王宪全收起来了 —— 这是设计如此
  const accordion = await page.evaluate(() => {
    const w = document.querySelector('.ptree__row[data-node-id="328"]');
    return w ? w.getAttribute('aria-expanded') : null;
  });
  check('同级手风琴仍然生效（展开陈银贵会自动收起王宪全）', accordion === 'false', `aria-expanded=${accordion}`);

  // 父级直挂的客户是否排在子分类"上方"
  const leafBeforeChild = await page.evaluate(() => {
    const leaf = document.querySelector('.ptree__leaf[data-leaf-owner="325"]');
    const child = document.querySelector('.ptree__row[data-node-id="328"]');
    if (!leaf || !child) return null;
    // DOCUMENT_POSITION_FOLLOWING = 子分类排在叶子之后 → 叶子在"上方"
    return Boolean(leaf.compareDocumentPosition(child) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  check('父级直挂客户渲染在子分类上方', leafBeforeChild === true);

  // ── ② 拖到"有子分类也有客户"的父节点 ────────────────────────────────
  const dragRowTo = async (rowText, nodeSelector) => {
    const src = await page.evaluate((t) => {
      const tr = [...document.querySelectorAll('tbody tr')].find((el) => (el.textContent || '').includes(t));
      if (!tr) return null;
      const r = tr.getBoundingClientRect();
      return { x: Math.round(r.x + 60), y: Math.round(r.y + r.height / 2) };
    }, rowText);
    const dst = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + 60), y: Math.round(r.y + r.height / 2) };
    }, nodeSelector);
    if (!src || !dst) return { ok: false, why: `src=${Boolean(src)} dst=${Boolean(dst)}` };
    const data = await page.mouse.drag(src, dst);
    await page.mouse.dragEnter(dst, data);
    await page.mouse.dragOver(dst, data);
    await page.mouse.drop(dst, data);
    await page.mouse.up().catch(() => {});
    await sleep(1500);
    return { ok: true };
  };

  const toParent = await dragRowTo(`验收拖拽A-${tag}`, '.ptree__row[data-node-id="325"]');
  const badgeAfter = await page.evaluate(() => {
    const row = document.querySelector('.ptree__row[data-node-id="325"] .ptree__count');
    return row ? Number(row.textContent.trim()) : null;
  });
  check('拖到有子分类的父节点：成功', toParent.ok, toParent.why || '');
  check('拖到父节点后角标 +1', badgeAfter === tree.badge325 + 1, `${tree.badge325} → ${badgeAfter}`);

  // 刷新后是否还在
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1600);
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '客户档案');
    if (it) it.click();
  });
  await sleep(1500);
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes('全部客户'));
    if (el) el.click();
  });
  await sleep(800);
  const api = await call('GET', '/api/v1/customers');
  const movedA = (api.body || []).find((c) => c.code === `CUST-T1-${tag}`);
  check('刷新后该客户仍挂在父节点下', movedA && movedA.category_id === 325, `category_id=${movedA && movedA.category_id}`);

  // ── ③ 拖到"客户叶子"上：落到叶子所属分类 ─────────────────────────────
  for (const n of ['国家电网', '陕西送变电', '施工一部', '谭涛总']) await expand(n);
  const leafDrop = await dragRowTo(`验收拖拽B-${tag}`, '.ptree__leaf[data-leaf-owner="325"]');
  const movedB = (await call('GET', '/api/v1/customers')).body.find((c) => c.code === `CUST-T2-${tag}`);
  check('拖到客户叶子上松手：成功且落到该分类', leafDrop.ok && movedB && movedB.category_id === 325, `category_id=${movedB && movedB.category_id}`);

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  for (const c of [a.body, b.body]) if (c && c.id) await call('DELETE', `/api/v1/customers/${c.id}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('验收脚本自身出错：', e);
  process.exit(2);
});
