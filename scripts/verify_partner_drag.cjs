/**
 * 拖拽归档验收（客户档案试点）。
 *
 * 为什么不用 page.mouse 拖：HTML5 原生 DnD 不走鼠标轨迹，puppeteer 的
 * mouse.move 触发不了 dragstart。这里用 DataTransfer + 合成 DragEvent，
 * React 的 onDragStart/onDragOver/onDrop 照常收到事件 —— 验的是"事件接线
 * 和落库"对不对，不是浏览器的拖拽引擎。
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

  // 造数据：一个分类 + 两个未分类客户
  const tag = Date.now().toString().slice(-6);
  const category = await call('POST', '/api/v1/customer-categories', {
    name: `拖拽验收类-${tag}`,
    parent_id: null,
  });
  const categoryId = category.body.id;
  const custIds = [];
  for (let i = 0; i < 4; i += 1) {
    const created = await call('POST', '/api/v1/customers', {
      code: `CUST-DNDUI-${tag}${i}`,
      name: `拖拽验收客户${i}-${tag}`,
    });
    custIds.push(created.body.id);
  }
  console.log(`  造数据：分类 #${categoryId}，客户 ${custIds.join(',')}`);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 950 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 300)));

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
  await sleep(1500);

  // 切到「按分类」视图（默认就是），确认树的分类节点在
  const hasCategoryNode = await page.evaluate(
    (name) => Boolean([...document.querySelectorAll('.ptree__row')].find((el) => (el.textContent || '').includes(name))),
    `拖拽验收类-${tag}`,
  );
  check('新分类出现在左侧树上', hasCategoryNode);

  // 未分类节点：先展开
  const toggleOk = await page.evaluate(() => {
    const btn = document.querySelector('[data-uncat-toggle]');
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(600);
  const leafInfo = await page.evaluate(() => ({
    leaves: document.querySelectorAll('.ptree__leaf').length,
    firstDraggable: (() => {
      const leaf = document.querySelector('.ptree__leaf');
      return leaf ? leaf.getAttribute('draggable') === 'true' : false;
    })(),
  }));
  check('「未分类」可以像文件夹一样展开', toggleOk && leafInfo.leaves > 0, `${leafInfo.leaves} 行`);
  check('展开后的行可拖', leafInfo.firstDraggable);

  // 用鼠标从「未分类」叶子行拖到分类节点（合成 DnD）
  const draggedFromLeaf = await page.evaluate(
    async ({ customerName, categoryName }) => {
      const leaf = [...document.querySelectorAll('.ptree__leaf')].find((el) => (el.textContent || '').includes(customerName));
      const target = [...document.querySelectorAll('.ptree__row')].find((el) => (el.textContent || '').includes(categoryName));
      if (!leaf || !target) return { ok: false, why: !leaf ? 'no-leaf' : 'no-target' };
      const dt = new DataTransfer();
      leaf.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const over = target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
      // 高亮由 React state 驱动，必须等一帧再读 DOM
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const highlighted = target.classList.contains('is-partner-drop');
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      leaf.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
      return { ok: true, highlighted, overDefaultPrevented: over === false };
    },
    { customerName: `拖拽验收客户0-${tag}`, categoryName: `拖拽验收类-${tag}` },
  );
  await sleep(1500);
  check('从「未分类」叶子行发起拖拽', draggedFromLeaf.ok, draggedFromLeaf.why || '');
  check('经过分类节点时节点高亮', Boolean(draggedFromLeaf.highlighted));
  check('节点接受放下（dragover 被 preventDefault）', Boolean(draggedFromLeaf.overDefaultPrevented));

  const movedNotice = await page.evaluate(() => {
    const el = document.querySelector('.notice-box, .notice, .toast, [role="status"]');
    return el ? el.textContent.trim().slice(0, 60) : '';
  });
  check('松手后有"已成功移动 N 个客户至 XX 分类"提示', /已成功移动 \d+ 个客户至/.test(movedNotice), movedNotice);

  const afterLeaf = await fetch(`${BASE}/api/v1/customers`, { headers: H }).then((r) => r.json());
  const leafCustomer = afterLeaf.find((c) => c.code === `CUST-DNDUI-${tag}0`);
  check('库里这条客户的分类真的改了', leafCustomer && leafCustomer.category_id === categoryId, `category_id=${leafCustomer && leafCustomer.category_id}`);

  // 表格行拖拽（多选两个 → 整批移动）
  await page.evaluate((name) => {
    const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === '客户档案');
    if (it) it.click();
  }, '');
  await sleep(1200);
  // 回到「全部客户」，让两个测试客户都在表里
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部客户/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(1000);

  const rowDrag = await page.evaluate(
    ({ names, categoryName }) => {
      const rows = [...document.querySelectorAll('tbody tr.is-draggable-row')];
      const hits = rows.filter((tr) => names.some((n) => (tr.textContent || '').includes(n)));
      if (hits.length < 1) return { ok: false, why: `只找到 ${hits.length} 行` };
      const target = [...document.querySelectorAll('.ptree__row')].find((el) => (el.textContent || '').includes(categoryName));
      if (!target) return { ok: false, why: 'no-target' };
      const dt = new DataTransfer();
      hits[0].dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const payload = dt.getData('application/x-erp-partners');
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      hits[0].dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
      return { ok: true, payload };
    },
    { names: [`拖拽验收客户1-${tag}`], categoryName: `拖拽验收类-${tag}` },
  );
  await sleep(1600);
  check('表格行可拖且带上档案 id', rowDrag.ok && /\d+/.test(rowDrag.payload || ''), rowDrag.why || `payload=${rowDrag.payload}`);

  const finalRows = await fetch(`${BASE}/api/v1/customers`, { headers: H }).then((r) => r.json());
  const second = finalRows.find((c) => c.code === `CUST-DNDUI-${tag}1`);
  check('表格行拖拽后同样落库', second && second.category_id === categoryId, `category_id=${second && second.category_id}`);

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // ── 多选批量拖：勾两行，拖其中一行 → 两行一起走 ────────────────────────
  // 2026-10-21：拖完会**自动把右表过滤到目标分类**（新交互），所以先把列表切回「全部」，
  // 否则那两行根本不在表里（这是产品行为变了，不是回归）。
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(1500);

  const batch = await page.evaluate(
    async ({ names, ids, categoryName }) => {
      const rows = [...document.querySelectorAll('tbody tr')];
      const picked = rows.filter((tr) => names.some((n) => (tr.textContent || '').includes(n)));
      if (picked.length < 2) return { ok: false, why: `只找到 ${picked.length} 行` };
      // 真实勾选：点每行的 checkbox（受控组件，click 就能让 selectedKeys 变）
      picked.forEach((tr) => {
        const box = tr.querySelector('input[type="checkbox"]');
        if (box && !box.checked) box.click();
      });
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const checked = picked.filter((tr) => tr.querySelector('input[type="checkbox"]')?.checked).length;
      const target = [...document.querySelectorAll('.ptree__row')].find((el) => (el.textContent || '').includes(categoryName));
      if (!target) return { ok: false, why: 'no-target' };
      const dt = new DataTransfer();
      picked[0].dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const payload = dt.getData('application/x-erp-partners');
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }));
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
      picked[0].dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
      return { ok: true, checked, payload, expect: ids };
    },
    {
      names: [`拖拽验收客户2-${tag}`, `拖拽验收客户3-${tag}`],
      ids: [custIds[2], custIds[3]],
      categoryName: `拖拽验收类-${tag}`,
    },
  );
  await sleep(1800);
  const batchPayload = batch.payload ? JSON.parse(batch.payload) : [];
  check(
    '多选两行后拖其中一行 → 带着 2 个 id',
    batch.ok && batch.checked === 2 && batchPayload.length === 2,
    batch.why || `checked=${batch.checked} payload=${batch.payload}`,
  );

  const afterBatch = await fetch(`${BASE}/api/v1/customers`, { headers: H }).then((r) => r.json());
  const batchMoved = [custIds[2], custIds[3]].every(
    (id) => (afterBatch.find((c) => c.id === id) || {}).category_id === categoryId,
  );
  check('批量拖拽后两行都落库', batchMoved);

  // 清理
  for (const id of custIds) await call('DELETE', `/api/v1/customers/${id}`);
  await call('DELETE', `/api/v1/customer-categories/${categoryId}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
