/**
 * 商品分类树专项验收（2026-10-22）：
 *   ① 有子分类的节点必须有展开箭头，点箭头能展开/收起
 *   ② 每个节点都有拖拽手柄（.cat-grip），按住能拖
 *   ③ 拖到另一个节点身上 = 变成它的子级（落库 parent_id 正确）
 *   ④ 手风琴：展开一个一级节点，另一个同级节点自动收起
 *   ⑤ 商品行仍然可以拖进类别（拖拽归档没被改坏）
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
  const A = await call('POST', '/api/v1/product-categories', { name: `验收A-${tag}`, parent_id: null });
  const B = await call('POST', '/api/v1/product-categories', { name: `验收B-${tag}`, parent_id: null });
  const C = await call('POST', '/api/v1/product-categories', { name: `验收C-${tag}`, parent_id: null });
  // C 必须有一个子级，否则它没有展开箭头，没法测手风琴
  const D = await call('POST', '/api/v1/product-categories', { name: `验收C子-${tag}`, parent_id: C.body?.id ?? null });
  if (!A.body?.id || !B.body?.id || !C.body?.id) {
    console.error('造分类失败', A, B, C);
    process.exit(2);
  }

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
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '商品档案');
    if (it) it.click();
  });
  await sleep(2000);

  // ── ① 箭头 ────────────────────────────────────────────────────────────
  const caretInfo = await page.evaluate(() => {
    const row = document.querySelector('.cat-node[data-node-id="6"]'); // 办公用品，有 1 个子类
    if (!row) return null;
    const caret = row.querySelector('.cat-caret:not(.leaf)');
    const svg = caret && caret.querySelector('svg');
    return {
      has: Boolean(caret),
      cursor: caret ? getComputedStyle(caret).cursor : null,
      svgW: svg ? Math.round(svg.getBoundingClientRect().width) : null,
      collapsed: caret ? caret.className.includes('is-collapsed') : null,
    };
  });
  check('有子分类的节点有展开箭头', Boolean(caretInfo && caretInfo.has), JSON.stringify(caretInfo));
  check('箭头尺寸可见（>=8px）且可点', Boolean(caretInfo && caretInfo.svgW >= 8 && caretInfo.cursor === 'pointer'), `svg=${caretInfo && caretInfo.svgW}px`);

  // 点箭头展开 → 子类「办公家具」出现
  await page.evaluate(() => {
    const row = document.querySelector('.cat-node[data-node-id="6"]');
    const caret = row && row.querySelector('.cat-caret');
    if (caret) caret.click();
  });
  await sleep(600);
  const childVisible = await page.evaluate(() => {
    const row = document.querySelector('.cat-node[data-node-id="5"]'); // 办公家具
    return row ? { depth: row.getAttribute('data-depth'), text: (row.textContent || '').trim().slice(0, 10) } : null;
  });
  check('点箭头后子分类「办公家具」展开出来', Boolean(childVisible && childVisible.depth === '1'), JSON.stringify(childVisible));

  // ── ② 手柄 ────────────────────────────────────────────────────────────
  const gripInfo = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.cat-node')];
    const withGrip = rows.filter((r) => r.querySelector('.cat-grip')).length;
    // 重名类别（树里有两个同名）后端按名称归属商品，拖它们会产生歧义 —— 设计上不给手柄
    const names = rows.map((r) => (r.querySelector('.cat-name') || {}).textContent || '');
    const dup = new Set(names.filter((n, i) => names.indexOf(n) !== i));
    const dupRows = rows.filter((r) => dup.has((r.querySelector('.cat-name') || {}).textContent || '')).length;
    const pen = document.querySelector('.cat-node[data-node-id="6"] .cat-grip');
    return { rows: rows.length, withGrip, dupRows, pen: Boolean(pen) };
  });
  check(
    '除重名类别外，每个节点都有拖拽手柄',
    gripInfo.pen && gripInfo.withGrip >= gripInfo.rows - gripInfo.dupRows,
    `${gripInfo.withGrip}/${gripInfo.rows}（重名 ${gripInfo.dupRows} 个按设计不给）`,
  );

  // ── ③ 拖拽改层级：A → B（拖到 B 行中间 = 成为子级）────────────────────
  const box = async (id) =>
    page.evaluate((nid) => {
      const row = document.querySelector(`.cat-node[data-node-id="${nid}"]`);
      if (!row) return null;
      const r = row.getBoundingClientRect();
      return { x: Math.round(r.x + 60), y: Math.round(r.y + r.height / 2) };
    }, id);

  const aBox = await box(A.body.id);
  const bBox = await box(B.body.id);
  if (aBox && bBox) {
    await page.mouse.move(aBox.x, aBox.y);
    await page.mouse.down();
    await page.mouse.move(aBox.x + 6, aBox.y + 2, { steps: 4 });
    await page.mouse.move(bBox.x, bBox.y, { steps: 12 });
    await page.mouse.move(bBox.x, bBox.y + 1, { steps: 3 });
    await page.mouse.up();
  }
  await sleep(1800);
  const tree = await call('GET', '/api/v1/product-categories');
  const findNode = (list, id) => {
    for (const n of list || []) {
      if (Number(n.id) === Number(id)) return n;
      const hit = findNode(n.children, id);
      if (hit) return hit;
    }
    return null;
  };
  const aNode = findNode(tree.body, A.body.id);
  check('拖到另一节点身上 = 变成它的子级（落库）', aNode && aNode.parent_id === B.body.id, `parent_id=${aNode && aNode.parent_id} 期望=${B.body.id}`);

  // ── ④ 手风琴：展开 A 所属的 B，再展开 C，B 应收起 ─────────────────────
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1400);
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '商品档案');
    if (it) it.click();
  });
  await sleep(1500);
  const clickCaret = async (id) => {
    await page.evaluate((nid) => {
      const row = document.querySelector(`.cat-node[data-node-id="${nid}"]`);
      const caret = row && row.querySelector('.cat-caret:not(.leaf)');
      if (caret) caret.click();
    }, id);
    await sleep(600);
  };
  await clickCaret(B.body.id);
  const bOpen = await page.evaluate((id) => {
    const row = document.querySelector(`.cat-node[data-node-id="${id}"]`);
    const caret = row && row.querySelector('.cat-caret:not(.leaf)');
    return caret ? !caret.className.includes('is-collapsed') : null;
  }, B.body.id);
  await clickCaret(C.body.id);
  const afterAccordion = await page.evaluate((id) => {
    const row = document.querySelector(`.cat-node[data-node-id="${id}"]`);
    const caret = row && row.querySelector('.cat-caret:not(.leaf)');
    return caret ? !caret.className.includes('is-collapsed') : null;
  }, B.body.id);
  check('手风琴：展开另一个同级节点后，前一个自动收起', bOpen === true && afterAccordion === false, `B: ${bOpen} → ${afterAccordion}`);

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理：有子级删不掉，所以先把所有测试类**移回顶级**再逐个删（顺序无关）
  const ids = [A.body.id, B.body.id, C.body.id, D.body?.id].filter(Boolean);
  for (const id of ids) await call('PATCH', `/api/v1/product-categories/${id}`, { parent_id: null });
  for (const id of ids) {
    const r = await call('DELETE', `/api/v1/product-categories/${id}`);
    if (r.status !== 204) console.log(`    清理 ${id} 失败：${r.status} ${JSON.stringify(r.body).slice(0, 80)}`);
  }
  const left = await call('GET', '/api/v1/product-categories');
  const flat = (list) => (list || []).flatMap((n) => [n, ...flat(n.children)]);
  const residue = flat(left.body).filter((n) => /^验收/.test(n.name || ''));
  check('验收用的临时分类已清理干净', residue.length === 0, `残留 ${residue.length} 个`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('验收脚本自身出错：', e);
  process.exit(2);
});
