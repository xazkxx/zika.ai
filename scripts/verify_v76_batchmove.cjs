/**
 * v76 批量移动白屏 Bug 修复验收（真浏览器 · puppeteer-core + chrome.exe）
 *
 * 覆盖用户提出的三条：
 *   A. 前端交互拦截 —— 未选目标分类时「确定」按钮 disabled，给红字提示，**不发请求**
 *   B. 前端错误解析 —— 422 数组 detail 不能白屏；把 detail 强行设成数组也要能活
 *   C. 后端防呆 —— 分类为空/缺失返回中文 400，不是 Pydantic 原始对象
 *
 * 白屏判据（本脚本核心）：
 *   ① 页面主容器仍在（.app-shell / .sidebar 之一）；
 *   ② console 里没有 "Objects are not valid as a React child"；
 *   ③ 没有 pageerror；
 *   ④ 错误文案是**一行中文**，不是 "[object Object]" / 逗号拼接的英文。
 *
 * 运行：node scripts/verify_v76_batchmove.cjs
 */

const fs = require('fs');
const path = require('path');

// puppeteer-core 装在托管 node 工作区里（不是 frontend/node_modules）
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
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
  const data = await res.json();
  return data.access_token;
}

/**
 * 导航到商品页。
 * ⚠️ .nav-group-title 是 toggle：已展开时再点会**收起** → 必须先看 .nav-item 在不在。
 */
async function gotoProducts(page) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    const ps = document.querySelectorAll('p');
    for (const p of ps) {
      if (p.textContent.trim() === '商品档案') { p.closest('div')?.querySelector('button')?.click(); return; }
    }
  }).catch(() => {});
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const b = btns.find((x) => x.textContent.replace(/\s/g, '') === '登录');
    if (b) b.click();
  }).catch(() => {});
  await sleep(1500);
}

(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const token = await login();
  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
  });

  const page = await browser.newPage();
  const pageErrors = [];
  const consoleErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message ? e.message : e)));
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });

  // 先到真实站点再写 token（about:blank 上 localStorage 会 SecurityError）
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await sleep(2500);

  // ── 导航到商品档案 ────────────────────────────────────────────
  await page.evaluate(() => {
    const want = /商品档案|商品/;
    const has = [...document.querySelectorAll('.nav-item')].some((e) => want.test(e.textContent));
    if (has) return;
    const titles = [...document.querySelectorAll('.nav-group-title')];
    const t = titles.find((x) => /基础资料|资料|档案/.test(x.textContent));
    if (t) t.click();
  });
  await sleep(600);
  await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find((e) => /商品档案/.test(e.textContent));
    if (item) item.click();
  });
  await sleep(2500);

  // 商品列表左树未选中 = 空态，必须先点「全部」
  await page.evaluate(() => {
    const roots = [...document.querySelectorAll('.category-tree *, .ptree__body *')];
    const all = roots.find((e) => /^全部/.test(e.textContent.trim()) && e.children.length === 0);
    if (all) all.click();
  });
  await sleep(1800);

  const rowCount = await page.evaluate(() => document.querySelectorAll('tr.erp-table__row').length);
  record('商品列表有行（左树已选「全部」）', rowCount > 0, `rows=${rowCount}`);

  // ── A. 勾选两个商品 → 打开批量移动 ────────────────────────────
  const checked = await page.evaluate(() => {
    const boxes = [...document.querySelectorAll('tbody input[type="checkbox"]')];
    if (!boxes.length) return 0;
    boxes.slice(0, 2).forEach((b) => b.click());
    return Math.min(2, boxes.length);
  });
  await sleep(500);
  record('能勾选商品', checked >= 2, `checked=${checked}`);

  const opened = await page.evaluate(() => {
    const btn = document.querySelector('[data-product-batch-move]');
    if (!btn || btn.disabled) return false;
    btn.click();
    return true;
  });
  await sleep(800);
  const dialogThere = await page.evaluate(() => Boolean(document.querySelector('[data-batch-move-dialog]')));
  record('「批量移动」按钮打开小窗', opened && dialogThere, `clicked=${opened} dialog=${dialogThere}`);

  // A1：未选分类时按钮 disabled
  const a1 = await page.evaluate(() => {
    const btn = document.querySelector('[data-batch-move-submit]');
    const tip = document.querySelector('[data-batch-move-tip]');
    return {
      hasBtn: Boolean(btn),
      disabled: btn ? btn.disabled : null,
      tipText: tip ? tip.textContent.trim() : '',
    };
  });
  record(
    'A1 未选分类时「移动」按钮禁用',
    a1.hasBtn && a1.disabled === true,
    `disabled=${a1.disabled}`,
  );
  record('A1b 未选分类时给红字提示', a1.tipText.length > 0, a1.tipText);

  // A2：点 disabled 按钮不能发请求（用 CDP 计数）
  await page.setRequestInterception(false).catch(() => {});
  const reqLog = [];
  page.on('request', (req) => {
    if (req.url().includes('/products/batch-category')) reqLog.push(req.method());
  });
  await page.evaluate(() => {
    const btn = document.querySelector('[data-batch-move-submit]');
    if (btn) { btn.click(); btn.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
  });
  await sleep(900);
  record('A2 按钮禁用时不发 batch-category 请求', reqLog.length === 0, `requests=${reqLog.length}`);

  // A3：键盘回车提交也要被拦
  await page.evaluate(() => {
    const form = document.querySelector('[data-batch-move-dialog] form');
    if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await sleep(900);
  const a3 = await page.evaluate(() => {
    const hint = document.querySelector('[data-batch-move-hint]');
    return { text: hint ? hint.textContent.trim() : '', pageAlive: Boolean(document.querySelector('.app-shell, .sidebar, .main-area')) };
  });
  record('A3 强行提交被拦下并给提示', a3.text.length > 0 && a3.pageAlive, a3.text);
  record('A3b 拦截后页面没白屏', a3.pageAlive, `alive=${a3.pageAlive}`);
  record('A3c 拦下后仍不发请求', reqLog.length === 0, `requests=${reqLog.length}`);

  // ── B. 错误解析：直接调 422 分支，确认不白屏 ─────────────────
  // 用 fetch 在页面上下文里发一个**必定 422** 的请求（ids 传对象），拿到 detail 数组
  const b = await page.evaluate(async (api) => {
    const t = localStorage.getItem('erp_token');
    const res = await fetch(`${api}/products/batch-category`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
      body: JSON.stringify({ ids: { bad: 1 }, category: 'x' }),
    });
    const body = await res.json().catch(() => ({}));
    return { status: res.status, detailType: Array.isArray(body.detail) ? 'array' : typeof body.detail, body };
  }, API);
  record(
    'B1 畸形 ids 触发友好 400（不是 Pydantic 422）',
    b.status === 400 && b.detailType === 'string',
    `status=${b.status} detail=${b.detailType}`,
  );

  /**
   * B2 —— 错误解析函数的**真反证点**。
   *
   * 只发真实请求是测不到解析函数的：本项目的接口现在全都 400+字符串，
   * 422 分支永远不走 → 解析函数写坏了脚本也是绿的（实测反证时踩到）。
   * 所以这里直接做一个会返回 422 数组的假 fetch，再点一次提交，
   * 看 ① 页面活没活 ② 横幅是不是一行中文而不是 "[object Object]"。
   */
  await page.evaluate(() => {
    const realFetch = window.fetch;
    window.__restoreFetch = () => { window.fetch = realFetch; };
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (url.includes('/products/batch-category')) {
        // 精确复刻 FastAPI 422 body
        return new Response(
          JSON.stringify({
            detail: [
              { type: 'int_parsing', loc: ['body', 'ids', 0], msg: 'Input should be a valid integer, unable to parse string as an integer', input: 'abc' },
            ],
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return realFetch(input, init);
    };
  });
  const b2 = await page.evaluate(async () => {
    const btn = document.querySelector('[data-batch-move-submit]');
    if (!btn || btn.disabled) return { ok: false, why: '按钮不可点，无法触发 422 路径' };
    btn.click();
    await new Promise((r) => setTimeout(r, 1200));
    const n = document.querySelector('.notice-box');
    const notice = n ? n.textContent.trim() : '';
    const alive = Boolean(document.querySelector('.app-shell, .sidebar, .main-area'));
    return { ok: true, notice, alive };
  });
  record('B2 422 数组 detail 不导致白屏', b2.ok && b2.alive === true, JSON.stringify(b2));
  record(
    'B3 422 数组 detail 渲染成一行中文（不是 [object Object]）',
    b2.ok && b2.notice.length > 0 && !/\[object Object\]|Objects are not valid/.test(b2.notice),
    b2.notice,
  );
  await page.evaluate(() => window.__restoreFetch && window.__restoreFetch());
  await sleep(400);

  // ── C. 正常路径：选一个分类 → 提交 → 成功 ───────────────────
  // 打开树面板，点第一个末级节点
  const picked = await page.evaluate(async () => {
    const trig = document.querySelector('[data-tsel-trigger="product-batch-move"], .tsel-trigger');
    if (!trig) return { ok: false, why: 'no trigger' };
    trig.click();
    await new Promise((r) => setTimeout(r, 400));
    // 面板 portal 到 body，必须 document 级查询
    const rows = [...document.querySelectorAll('.tsel-row[data-tsel-key]')];
    if (!rows.length) return { ok: false, why: 'no rows' };
    // 优先找末级；没有末级就先展开第一个父级
    let leaf = rows.find((r) => !r.classList.contains('is-parent') && r.dataset.tselLeaf !== 'false');
    if (!leaf) { rows[0].dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); await new Promise((r) => setTimeout(r, 400)); }
    const fresh = [...document.querySelectorAll('.tsel-row[data-tsel-key]')];
    leaf = fresh.find((r) => !r.classList.contains('is-parent') && r.dataset.tselLeaf !== 'false');
    if (!leaf) return { ok: false, why: 'no leaf after expand' };
    leaf.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
    const btn = document.querySelector('[data-batch-move-submit]');
    return { ok: true, label: leaf.textContent.trim(), enabled: btn ? !btn.disabled : false };
  });
  record('C1 选中末级分类后按钮可用', picked.ok && picked.enabled === true, JSON.stringify(picked));

  if (picked.ok && picked.enabled) {
    const before = reqLog.length;
    await page.evaluate(() => document.querySelector('[data-batch-move-submit]').click());
    await sleep(2500);
    const after = reqLog.length;
    const noticeText = await page.evaluate(() => {
      const n = document.querySelector('.notice-box');
      return n ? n.textContent.trim() : '';
    });
    const alive = await page.evaluate(() => Boolean(document.querySelector('.app-shell, .sidebar, .main-area')));
    record('C2 提交后真的发了 PATCH', after > before, `before=${before} after=${after}`);
    record('C3 成功后顶部横幅给了一行中文', /已把\s*\d+\s*个商品移到/.test(noticeText), noticeText);
    record('C4 成功后页面没白屏', alive, `alive=${alive}`);
    const dialogGone = await page.evaluate(() => !document.querySelector('[data-batch-move-dialog]'));
    record('C5 成功后小窗自动关闭', dialogGone, `gone=${dialogGone}`);
  }

  // ── D. 白屏总检查 ─────────────────────────────────────────────
  const badErrors = [...pageErrors, ...consoleErrors].filter((t) =>
    /Objects are not valid as a React child|Cannot read properties|is not a function|Maximum update depth/i.test(t));
  record('D1 全程无 React 渲染崩溃', badErrors.length === 0, badErrors.slice(0, 3).join(' | '));

  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_batchmove_final.png') }).catch(() => {});

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log('');
  console.log(`==== ${results.length - failed.length}/${results.length} 通过 ====`);
  if (failed.length) {
    console.log('失败项：');
    failed.forEach((f) => console.log(`  · ${f.name}  ${f.detail}`));
    process.exit(1);
  }
})().catch((err) => {
  console.error('验收脚本异常：', err);
  process.exit(2);
});
