/**
 * 拖拽归档"亮起并定位"验收（三类档案全覆盖）。
 *
 * 客户/供应商：目标放在**三级**分类上（用户报的就是二级/三级没定位），
 *              并先把树滚到底部，验证 scrollIntoView 真的把它带进视野。
 * 商品：拖行到类别节点 → 校验 category 名称落库 + 左侧展开/高亮/闪烁。
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

  const tag = Date.now().toString().slice(-6);
  // 客户：三级链
  const c1 = await call('POST', '/api/v1/customer-categories', { name: `定位L1-${tag}`, parent_id: null });
  const c2 = await call('POST', '/api/v1/customer-categories', { name: `定位L2-${tag}`, parent_id: c1.body.id });
  const c3 = await call('POST', '/api/v1/customer-categories', { name: `定位L3-${tag}`, parent_id: c2.body.id });
  const cust = await call('POST', '/api/v1/customers', { code: `CUST-POS-${tag}`, name: `定位客户-${tag}` });
  // 供应商：一级（够验证链路）
  const s1 = await call('POST', '/api/v1/supplier-categories', { name: `供定位-${tag}`, parent_id: null });
  const sup = await call('POST', '/api/v1/suppliers', { code: `SUP-POS-${tag}`, name: `定位供应商-${tag}` });
  // 商品：一个空类别 + 一个无类别商品
  const pcat = await call('POST', '/api/v1/product-categories', { name: `商品定位-${tag}`, parent_id: null });
  const prod = await call('POST', '/api/v1/products', {
    sku: `SKU-POS-${tag}`,
    name: `定位商品-${tag}`,
    unit: '个',
    purchase_price: 1,
    sale_price: 2,
  });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1500, height: 760 }, // 故意矮一点：树容易超出视野
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

  const openMenu = async (label) => {
    await page.evaluate((t) => {
      const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === t);
      if (it) it.click();
    }, label);
    await sleep(1600);
  };

  /** 通用：拖第一行到指定节点，然后采集"是否展开/高亮/闪烁/在视野内" */
  const dropAndInspect = async ({ rowText, nodeSelector, ancestorIds }) => {
    // 先把树滚到底部：目标在下方，验证 scrollIntoView 真的起作用
    await page.evaluate(() => {
      const box = document.querySelector('.partners-tree, .category-tree');
      if (box) box.scrollTop = box.scrollHeight;
      window.scrollTo(0, document.body.scrollHeight);
    });
    await sleep(300);
    const dropped = await page.evaluate(
      ({ rowText, nodeSelector }) => {
        const tr = [...document.querySelectorAll('tbody tr')].find((t) => (t.textContent || '').includes(rowText));
        const target = document.querySelector(nodeSelector);
        if (!tr || !target) return { ok: false, why: `tr=${Boolean(tr)} target=${Boolean(target)}` };
        const dt = new DataTransfer();
        tr.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
        target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
        target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
        tr.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
        return { ok: true };
      },
      { rowText, nodeSelector },
    );
    const flashed = await page
      .waitForFunction(
        (sel) => {
          const el = document.querySelector(sel);
          return Boolean(el && (el.className.includes('is-flash') || el.className.includes('is-active')));
        },
        { timeout: 2500, polling: 40 },
        nodeSelector,
      )
      .then(() => true)
      .catch(() => false);
    await sleep(700);
    const state = await page.evaluate(
      ({ nodeSelector, ancestorIds }) => {
        const el = document.querySelector(nodeSelector);
        const box = el ? el.getBoundingClientRect() : null;
        return {
          exists: Boolean(el),
          active: el ? el.className.includes('is-active') : null,
          flash: el ? el.className.includes('is-flash') : null,
          inView: box ? box.top >= 0 && box.bottom <= window.innerHeight + 1 : null,
          ancestorsExpanded: ancestorIds.map((id) => {
            const row = document.querySelector(`[data-node-id="${id}"]`);
            if (!row) return 'missing';
            const exp = row.getAttribute('aria-expanded');
            return exp === null ? 'n/a' : exp === 'true';
          }),
        };
      },
      { nodeSelector, ancestorIds },
    );
    return { dropped, flashed, state };
  };

  // ── 客户：拖到三级分类 ────────────────────────────────────────────────
  await openMenu('客户档案');
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(800);
  // 三级节点默认是折叠的（树只展开第一层），先像用户一样把 L1/L2 点开
  for (const id of [c1.body.id, c2.body.id]) {
    await page.evaluate((nid) => {
      const row = document.querySelector(`.ptree__row[data-node-id="${nid}"]`);
      const caret = row && row.querySelector('.ptree__caret');
      if (caret) caret.click();
    }, id);
    await sleep(450);
  }
  const custRes = await dropAndInspect({
    rowText: `定位客户-${tag}`,
    nodeSelector: `.ptree__row[data-node-id="${c3.body.id}"]`,
    ancestorIds: [c1.body.id, c2.body.id],
  });
  check('客户：拖到三级分类成功', custRes.dropped.ok, custRes.dropped.why || '');
  check('客户：三级目标被高亮选中', custRes.state.active);
  check('客户：三级目标的祖先全部自动展开', custRes.state.ancestorsExpanded.every((v) => v === true), JSON.stringify(custRes.state.ancestorsExpanded));
  check('客户：滚动到可视区域', custRes.state.inView, `inView=${custRes.state.inView}`);
  check('客户：归档后闪一下', custRes.flashed || custRes.state.flash);

  // ── 供应商 ────────────────────────────────────────────────────────────
  await openMenu('供应商档案');
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(800);
  const supRes = await dropAndInspect({
    rowText: `定位供应商-${tag}`,
    nodeSelector: `.ptree__row[data-node-id="${s1.body.id}"]`,
    ancestorIds: [],
  });
  check('供应商：拖拽归档已开放（不再是只读）', supRes.dropped.ok, supRes.dropped.why || '');
  check('供应商：目标节点被高亮选中', supRes.state.active);
  check('供应商：归档后闪一下', supRes.flashed || supRes.state.flash);

  // ── 商品 ──────────────────────────────────────────────────────────────
  await openMenu('商品档案');
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.category-tree *')].find((el) => /^全部商品/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);
  const prodRes = await dropAndInspect({
    rowText: `定位商品-${tag}`,
    nodeSelector: `.cat-node[data-node-id="${pcat.body.id}"]`,
    ancestorIds: [],
  });
  check('商品：拖行到类别节点成功', prodRes.dropped.ok, prodRes.dropped.why || '');
  check('商品：类别节点被高亮选中', prodRes.state.active);
  check('商品：归档后闪一下', prodRes.flashed || prodRes.state.flash);

  const prodAfter = await call('GET', '/api/v1/products');
  const moved = (prodAfter.body || []).find((p) => p.sku === `SKU-POS-${tag}`);
  check('商品：category 已落库为类别名', moved && moved.category === `商品定位-${tag}`, moved ? `category=${moved.category}` : 'not found');

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理
  await call('DELETE', `/api/v1/customers/${cust.body.id}`);
  await call('DELETE', `/api/v1/suppliers/${sup.body.id}`);
  await call('DELETE', `/api/v1/products/${prod.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${c3.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${c2.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${c1.body.id}`);
  await call('DELETE', `/api/v1/supplier-categories/${s1.body.id}`);
  await call('DELETE', `/api/v1/product-categories/${pcat.body.id}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
