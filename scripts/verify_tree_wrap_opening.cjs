/**
 * 三个问题的验收（2026-10-22 第五轮）：
 *   ① 商品分类：任意层级都有可点手柄；三级分类能拖到别的父级并落库
 *   ② 商品表：名称列允许换行（white-space: normal），行高不是写死的
 *   ③ 期初库存：点「改这一项」→ 表单回填 + 按钮变「保存修改」→ 保存后落库
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
  // 造一棵三级链：P → C → G（G 是要被拖走的那个）
  const P = await call('POST', '/api/v1/product-categories', { name: `验收父-${tag}`, parent_id: null });
  const C = await call('POST', '/api/v1/product-categories', { name: `验收子-${tag}`, parent_id: P.body.id });
  const G = await call('POST', '/api/v1/product-categories', { name: `验收孙-${tag}`, parent_id: C.body.id });
  const T = await call('POST', '/api/v1/product-categories', { name: `验收目标-${tag}`, parent_id: null });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1440, height: 900 },
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
  await sleep(2200);

  const caret = async (id) => {
    await page.evaluate((i) => {
      const c = document.querySelector(`.cat-node[data-node-id="${i}"] .cat-caret`);
      if (c) c.click();
    }, id);
    await sleep(550);
  };
  await caret(P.body.id);
  await caret(C.body.id);

  // ① 三级节点手柄：存在、常驻可见（opacity > 0）、在行内
  const grip = await page.evaluate((gid) => {
    const row = document.querySelector(`.cat-node[data-node-id="${gid}"]`);
    if (!row) return { found: false };
    const el = row.querySelector('.cat-grip');
    if (!el) return { found: true, grip: false };
    const rr = row.getBoundingClientRect();
    const gr = el.getBoundingClientRect();
    return {
      found: true,
      grip: true,
      opacity: Number(getComputedStyle(el).opacity),
      inside: gr.right <= rr.right + 1 && gr.width >= 10,
      depth: row.getAttribute('data-depth'),
    };
  }, G.body.id);
  check('三级分类渲染出来了', grip.found && grip.depth === '2', JSON.stringify(grip));
  check('三级分类有拖拽手柄', Boolean(grip.grip), '');
  check('手柄常驻可见（不是 opacity:0）', Number(grip.opacity) > 0, `opacity=${grip.opacity}`);
  check('手柄落在行内、尺寸正常', Boolean(grip.inside), '');

  // ② 拖 G → T（用鼠标按住手柄拖，pointer 事件引擎）
  const box = async (id) =>
    page.evaluate((i) => {
      const row = document.querySelector(`.cat-node[data-node-id="${i}"]`);
      if (!row) return null;
      const el = row.querySelector('.cat-grip') || row;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, id);
  const gBox = await box(G.body.id);
  const tBox = await box(T.body.id);
  if (gBox && tBox) {
    await page.mouse.move(gBox.x, gBox.y);
    await page.mouse.down();
    await page.mouse.move(gBox.x + 5, gBox.y, { steps: 3 });
    await page.mouse.move(tBox.x, tBox.y, { steps: 14 });
    await page.mouse.move(tBox.x, tBox.y + 1, { steps: 3 });
    await page.mouse.up();
  }
  await sleep(1800);
  const tree = await call('GET', '/api/v1/product-categories');
  const find = (list, id) => {
    for (const n of list || []) {
      if (Number(n.id) === Number(id)) return n;
      const hit = find(n.children, id);
      if (hit) return hit;
    }
    return null;
  };
  const movedG = find(tree.body, G.body.id);
  check('三级分类能拖到另一个父级并落库', movedG && Number(movedG.parent_id) === Number(T.body.id), `parent_id=${movedG && movedG.parent_id}`);

  // ③ 商品表：名称列允许换行
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.cat-node')].find((e) => (e.textContent || '').includes('五金'));
    if (el) el.click();
  });
  await sleep(900);
  const cells = await page.evaluate(() => {
    const tr = document.querySelector('tbody tr');
    if (!tr) return null;
    const wrapCells = [...tr.querySelectorAll('td.erp-table__cell--wrap')].map((td) => getComputedStyle(td).whiteSpace);
    return { wrapCount: wrapCells.length, allNormal: wrapCells.every((w) => w === 'normal') };
  });
  check('商品名称/类别列可换行（white-space: normal）', Boolean(cells && cells.wrapCount >= 2 && cells.allNormal), JSON.stringify(cells));

  // ④ 期初库存：改这一项 → 回填 + 按钮变「保存修改」→ 保存落库
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '商品期初库存');
    if (it) it.click();
  });
  await sleep(2200);
  const beforeRow = await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.textContent || '').includes('改这一项'));
    if (!btn) return null;
    const tr = btn.closest('tr');
    return { text: (tr.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 80) };
  });
  check('已建账期初列表存在「改这一项」', Boolean(beforeRow), beforeRow ? beforeRow.text.slice(0, 40) : '');

  if (beforeRow) {
    await page.evaluate(() => {
      [...document.querySelectorAll('button')].find((b) => (b.textContent || '').includes('改这一项')).click();
    });
    await sleep(1000);
    const editState = await page.evaluate(() => ({
      saveBtn: Boolean(document.querySelector('[data-opening-save-edit="1"]')),
      btnTexts: [...document.querySelectorAll('button')].map((b) => (b.textContent || '').trim()).filter((t) => /保存修改|加入清单|取消编辑/.test(t)),
      qty: (document.querySelector('input[type="number"]') || {}).value,
      highlighted: Boolean(document.querySelector('.opening-entry.is-editing')),
    }));
    check('点「改这一项」后按钮变「保存修改」', editState.saveBtn === true, JSON.stringify(editState.btnTexts));
    check('表单已回填数量', Boolean(editState.qty), `qty=${editState.qty}`);
    check('表单高亮提示用户看这里', editState.highlighted === true, '');

    // 改数量 → 保存修改 → 校验落库
    const newQty = String(Number(editState.qty || 0) + 1);
    await page.evaluate((q) => {
      const input = document.querySelector('.opening-entry input[type="number"]');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, q);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, newQty);
    await sleep(200);
    await page.click('[data-opening-save-edit="1"]');
    await sleep(1600);
    const api = await call('GET', '/api/v1/opening-stock');
    const hit = (api.body.items || []).find((x) => String(x.quantity) === newQty);
    check('「保存修改」直接落库（数量已更新）', Boolean(hit), `期望 ${newQty}，库里有 ${hit ? '该项' : '没找到'}`);
    // ⚠️ 这条断言改的是**真实期初数据**，测完必须原样退回，
    //    否则每跑一次验收，劳保手套的期初就 +1（第一次就踩了）。
    if (hit) {
      await call('PUT', '/api/v1/opening-stock', {
        items: [
          {
            warehouse_id: hit.warehouse_id,
            product_id: hit.product_id,
            quantity: Number(editState.qty || 0),
            unit_price: hit.unit_price,
            note: hit.note || '',
          },
        ],
      });
      const back = await call('GET', '/api/v1/opening-stock');
      const restored = (back.body.items || []).find(
        (x) => Number(x.product_id) === Number(hit.product_id) && Number(x.warehouse_id) === Number(hit.warehouse_id),
      );
      check('验收改动的期初已原样回滚', restored && Number(restored.quantity) === Number(editState.qty), `quantity=${restored && restored.quantity}`);
    }
  }

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理
  for (const id of [G.body.id, C.body.id, P.body.id, T.body.id].filter(Boolean)) {
    await call('PATCH', `/api/v1/product-categories/${id}`, { parent_id: null });
  }
  for (const id of [G.body.id, C.body.id, P.body.id, T.body.id].filter(Boolean)) {
    await call('DELETE', `/api/v1/product-categories/${id}`);
  }
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('验收脚本自身出错：', e);
  process.exit(2);
});
