/**
 * v86 商品类别树拖拽 —— 真浏览器验收（puppeteer-core + chrome.exe）
 *
 * 用户原话（这一轮只要前端手感，右侧列表联动下一轮再测）：
 *   「请先做出前端拖拽交互，我验收手感后，再去测右侧商品列表联动。」
 * 所以本脚本只验"树本身"：
 *
 *   A. 爪手存在（每个树节点都有，拖拽能力没被漏掉）
 *   B. 鼠标拖到**行上沿** → 同级排到目标前面（真的发请求、库里顺序真的变）
 *   C. 鼠标拖到**行中间** → 变成目标的子类（parent_id 真的变）
 *   D. 拖进**自己的子孙** → 红字禁止、**一个请求都不发**（防死循环）
 *   E. 拖完那一下的 click 被吞掉（不会"拖完顺手把这一行选中"）
 *   F. 全程无 pageerror、无 "Objects are not valid as a React child"、页面不白屏
 *
 * ⚠️ 三层判据缺一不可（本项目踩过的假绿都在这里）：
 *   ① 只断言"发了请求"不够 —— 后端可能 400；
 *   ② 只断言"接口 200"不够 —— 顺序可能没变（假绿）；
 *   ③ 所以每一段都去**拉真实接口**核对 id 顺序 / parent_id。
 *
 * 运行：
 *   ERP_BASE=http://127.0.0.1:8013 node scripts/verify_v86_cattree_drag.cjs
 *   （8010 上是用户双击 bat 起的旧后端，没有 /move 路由 —— 别拿它验）
 */

const fs = require('fs');
const path = require('path');

const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
const API = `${BASE}/api/v1`;
const SHOT_DIR = path.join(__dirname, '..', 'artifacts');

const CHROME_CANDIDATES = [
  'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
];
const chromePath = CHROME_CANDIDATES.find((p) => fs.existsSync(p));
if (!chromePath) {
  console.error('找不到 chrome.exe / msedge.exe');
  process.exit(2);
}

const results = [];
const record = (name, ok, detail = '') => {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function login() {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  if (!res.ok) throw new Error(`登录失败 ${res.status}`);
  return (await res.json()).access_token;
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

/** 拉整棵树（诊断/核实用，直接看服务端真相而不是页面 DOM） */
async function fetchTree(token) {
  const res = await fetch(`${API}/product-categories`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(`拉分类树失败 ${res.status}`);
  return res.json();
}

/** 建一批探针类别：一个父 + N 个子，全部带同一个 tag */
async function createChain(token, tag, count) {
  const post = async (body) => {
    const res = await fetch(`${API}/product-categories`, {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`建类别失败 ${res.status} ${await res.text()}`);
    return res.json();
  };
  const parent = await post({ name: `拖父-${tag}` });
  const kids = [];
  for (let i = 0; i < count; i += 1) {
    kids.push(await post({ name: `拖子${i}-${tag}`, parent_id: parent.id }));
  }
  return { parent, kids };
}

async function cleanup(token, tag) {
  const tree = await fetchTree(token);
  const kill = async (id) => {
    await fetch(`${API}/product-categories/${id}`, { method: 'DELETE', headers: authHeaders(token) });
  };
  for (const root of tree) {
    if (!String(root.name || '').includes(tag)) continue;
    for (const child of root.children || []) await kill(child.id);
    await kill(root.id);
  }
}

/** 树里某个父级下的子 id 顺序（服务端真相） */
function childrenOrder(tree, parentId) {
  const walk = (list) => {
    for (const node of list) {
      if (node.id === parentId) return (node.children || []).map((c) => c.id);
      const hit = walk(node.children || []);
      if (hit) return hit;
    }
    return null;
  };
  return walk(tree) || [];
}

function findNode(tree, id) {
  for (const node of tree) {
    if (node.id === id) return node;
    const hit = findNode(node.children || [], id);
    if (hit) return hit;
  }
  return null;
}

/**
 * 从抓手拖到目标行的某个**相对高度**。
 * @param {number} ratio 0.15 = 行上沿（before）/ 0.5 = 行中间（inside）/ 0.85 = 行下沿（after）
 */
async function drag(page, srcId, dstId, ratio) {
  const box = await page.evaluate((s, d, r) => {
    const srcRow = [...document.querySelectorAll('[data-node-id]')].find((e) => Number(e.dataset.nodeId) === s);
    const dstRow = [...document.querySelectorAll('[data-node-id]')].find((e) => Number(e.dataset.nodeId) === d);
    if (!srcRow || !dstRow) return null;
    const grip = srcRow.querySelector('[data-cat-grip="1"]');
    if (!grip) return null;
    const g = grip.getBoundingClientRect();
    const t = dstRow.getBoundingClientRect();
    return {
      sx: g.left + g.width / 2,
      sy: g.top + g.height / 2,
      dx: t.left + Math.min(60, t.width / 2),
      dy: t.top + t.height * r,
    };
  }, srcId, dstId, ratio);
  if (!box) return { ok: false, reason: '找不到抓手或目标行' };

  await page.mouse.move(box.sx, box.sy);
  await page.mouse.down();
  // 分几步移动：一步跳过去命中测试可能还没激活（鼠标要 >4px 才算拖）
  for (let i = 1; i <= 8; i += 1) {
    await page.mouse.move(
      box.sx + ((box.dx - box.sx) * i) / 8,
      box.sy + ((box.dy - box.sy) * i) / 8,
    );
    await sleep(35);
  }
  await sleep(120);
  const mid = await page.evaluate(() => {
    const ghost = document.querySelector('[data-cat-ghost="1"]');
    const hl = [...document.querySelectorAll('[data-node-id]')]
      .filter((e) => /is-drop-/.test(e.className))
      .map((e) => ({ id: Number(e.dataset.nodeId), cls: e.className }));
    return { ghost: Boolean(ghost), hl };
  });
  await page.mouse.up();
  await sleep(1400); // 松手 → 发请求 → 重拉树
  return { ok: true, mid, box };
}

(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const token = await login();
  const tag = Math.random().toString(16).slice(2, 8);
  let chain;

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
  });

  const page = await browser.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  const moveRequests = [];
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message ? e.message : e)));
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('request', (req) => {
    if (req.url().includes('/product-categories/') && req.url().endsWith('/move')) {
      moveRequests.push({ url: req.url(), method: req.method(), body: req.postData() });
    }
  });

  try {
    // ── 准备数据：一个父 + 3 个子（同级排序用），另一个父（改父级用）──────────
    chain = await createChain(token, tag, 3);
    const other = await (async () => {
      const res = await fetch(`${API}/product-categories`, {
        method: 'POST',
        headers: authHeaders(token),
        body: JSON.stringify({ name: `拖父B-${tag}` }),
      });
      return res.json();
    })();
    const [k0, k1, k2] = chain.kids.map((k) => k.id);

    // ── 进站点、注入 token ────────────────────────────────────
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
    await page.goto(BASE, { waitUntil: 'networkidle2' });
    await sleep(2200);

    // 侧边栏分组默认收起（.nav-item 不在 DOM）→ 先展开含「商品档案」的那组
    await page.evaluate(() => {
      const has = [...document.querySelectorAll('.nav-item')].some((e) => /商品档案/.test(e.textContent));
      if (has) return;
      const t = [...document.querySelectorAll('.nav-group-title')]
        .find((x) => /基础资料|资料|档案/.test(x.textContent));
      if (t) t.click();
    });
    await sleep(700);
    await page.evaluate(() => {
      const item = [...document.querySelectorAll('.nav-item')].find((e) => /商品档案/.test(e.textContent));
      if (item) item.click();
    });
    await sleep(2500);

    // 左树未选中时右侧是空态 —— 这是设计，先点「全部商品」
    await page.evaluate(() => {
      const all = [...document.querySelectorAll('.cat-root-group .cat-node')]
        .find((e) => /全部商品/.test(e.textContent));
      if (all) all.click();
    });
    await sleep(1500);

    // 展开我们建的父级，让子类出现在 DOM 里
    await page.evaluate((pid) => {
      const row = [...document.querySelectorAll('[data-node-id]')]
        .find((e) => Number(e.dataset.nodeId) === pid);
      const caret = row && row.querySelector('.cat-caret:not(.leaf)');
      if (caret && caret.classList.contains('is-collapsed')) caret.click();
    }, chain.parent.id);
    await sleep(900);

    const treeVisible = await page.evaluate(() => ({
      body: Boolean(document.querySelector('.category-tree-body')),
      rows: document.querySelectorAll('.category-tree-body [data-node-id]').length,
    }));
    record('A0 类别树渲染出节点（.category-tree-body 里有 [data-node-id]）',
      treeVisible.body && treeVisible.rows > 0, `rows=${treeVisible.rows}`);

    // ── A. 抓手存在性 ────────────────────────────────────────
    const grips = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.category-tree-body [data-node-id]')];
      const withGrip = rows.filter((r) => r.querySelector('[data-cat-grip="1"]'));
      return { rows: rows.length, withGrip: withGrip.length };
    });
    record('A1 每个树节点都有拖拽抓手 .cat-grip',
      grips.rows > 0 && grips.withGrip === grips.rows,
      `rows=${grips.rows} grips=${grips.withGrip}`);

    // 抓手是触屏唯一入口 —— 必须带 touch-action:none，否则手机上一拖就断
    const gripTouch = await page.evaluate(() => {
      const g = document.querySelector('[data-cat-grip="1"]');
      if (!g) return null;
      return getComputedStyle(g).touchAction;
    });
    record('A2 抓手 `touch-action:none`（触屏拖不被打断）', gripTouch === 'none', String(gripTouch));

    // ── B. 同级排序：k2 拖到 k0 上沿 → 顺序 [k2,k0,k1] ─────────
    const before = childrenOrder(await fetchTree(token), chain.parent.id);
    const bDrag = await drag(page, k2, k0, 0.15);
    record('B0 拖拽过程中出现跟手浮标 + 落点高亮',
      bDrag.ok && bDrag.mid && bDrag.mid.ghost && bDrag.mid.hl.length > 0,
      bDrag.ok ? `ghost=${bDrag.mid.ghost} hl=${JSON.stringify(bDrag.mid.hl)}` : bDrag.reason);

    const bReq = moveRequests.length;
    const after = childrenOrder(await fetchTree(token), chain.parent.id);
    record('B1 松手后发了 1 条 /move 请求', bReq === 1, `requests=${bReq} body=${bReq ? moveRequests[0].body : ''}`);
    record('B2 同级顺序真的变了（服务端真相）',
      JSON.stringify(after) === JSON.stringify([k2, k0, k1]),
      `before=${JSON.stringify(before)} after=${JSON.stringify(after)}`);

    // ── E. 拖完那一下的 click 要被吞掉（不能顺手选中某一行）─────
    // 拖动起点是 k2，松手后浏览器会在它上面补一个 click；被吞掉 → 选中态不变
    const activeAfterDrag = await page.evaluate(() =>
      [...document.querySelectorAll('.cat-node.is-active')].map((e) => e.textContent.trim()));
    record('E1 拖完不会顺手把某一行选中',
      !activeAfterDrag.some((t) => /拖子/.test(t)),
      `active=${JSON.stringify(activeAfterDrag)}`);

    // ── C. 改父级：k1 拖到 other 行中间 → k1.parent_id = other ──
    // other 是顶级行，可能需要滚动到可见区
    await page.evaluate((oid) => {
      const row = [...document.querySelectorAll('[data-node-id]')]
        .find((e) => Number(e.dataset.nodeId) === oid);
      if (row) row.scrollIntoView({ block: 'center' });
    }, other.id);
    await sleep(400);

    const cDrag = await drag(page, k1, other.id, 0.5);
    const treeC = await fetchTree(token);
    const k1Node = findNode(treeC, k1);
    record('C1 拖到行中间 = 变成它的子类（parent_id 真的改了）',
      cDrag.ok && k1Node && k1Node.parent_id === other.id,
      `k1.parent_id=${k1Node ? k1Node.parent_id : 'null'} 期望 ${other.id}`);
    record('C2 原父级下只剩 k2、k0',
      JSON.stringify(childrenOrder(treeC, chain.parent.id)) === JSON.stringify([k2, k0]),
      JSON.stringify(childrenOrder(treeC, chain.parent.id)));

    // ── D. 防环：把父级拖进自己的子级（k2 现在还在它下面）──────
    // 先确保父级展开、k2 可见
    await page.evaluate((pid) => {
      const row = [...document.querySelectorAll('[data-node-id]')]
        .find((e) => Number(e.dataset.nodeId) === pid);
      const caret = row && row.querySelector('.cat-caret:not(.leaf)');
      if (caret && caret.classList.contains('is-collapsed')) caret.click();
    }, chain.parent.id);
    await sleep(600);

    const reqBeforeD = moveRequests.length;
    const dDrag = await drag(page, chain.parent.id, k2, 0.5);
    await sleep(900);
    const dHl = dDrag.ok && dDrag.mid ? dDrag.mid.hl.find((h) => h.id === k2) : null;
    record('D1 拖进自己的子孙 → 该行标红禁止（is-drop-forbidden）',
      Boolean(dHl && /is-drop-forbidden/.test(dHl.cls)),
      dHl ? dHl.cls : 'no highlight');
    record('D2 非法拖拽一个请求都不发（防死循环）',
      moveRequests.length === reqBeforeD,
      `before=${reqBeforeD} after=${moveRequests.length}`);

    const treeD = await fetchTree(token);
    const parentNode = findNode(treeD, chain.parent.id);
    record('D3 库里的 parent_id 没被改（数据没成环）',
      parentNode && parentNode.parent_id === null,
      `parent.parent_id=${parentNode ? parentNode.parent_id : 'missing'}`);

    // ── F. 健康度 ───────────────────────────────────────────
    await page.screenshot({ path: path.join(SHOT_DIR, 'v86_cattree_drag.png') });
    const alive = await page.evaluate(() => ({
      shell: Boolean(document.querySelector('.app-shell, .sidebar, .main-area')),
      errCard: Boolean(document.querySelector('[data-error-boundary]')),
    }));
    record('F1 全程无 pageerror', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
    record('F2 无 "Objects are not valid as a React child"',
      !consoleErrors.some((t) => /Objects are not valid as a React child/.test(t)),
      consoleErrors.slice(0, 2).join(' | '));
    record('F3 页面没白屏、没出错误边界', alive.shell && !alive.errCard,
      `shell=${alive.shell} errCard=${alive.errCard}`);
  } catch (err) {
    record('脚本异常', false, String(err && err.stack ? err.stack : err));
  } finally {
    await browser.close().catch(() => {});
    try {
      if (chain) await cleanup(token, tag);
    } catch (_e) { /* 清理失败不影响结论 */ }
  }

  const failed = results.filter((r) => !r.ok);
  console.log('');
  console.log(`总计 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`);
  if (failed.length) {
    console.log('失败项：');
    failed.forEach((f) => console.log(`  · ${f.name}  ${f.detail}`));
  }
  process.exit(failed.length ? 1 : 0);
})();
