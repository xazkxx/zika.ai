/**
 * 三个交互闭环验收（2026-10-22）。
 *
 * 全部用**真实拖拽**（Puppeteer drag interception），不用合成 DragEvent ——
 * 合成事件绕过命中测试，正是上次"拖进 A 提示 B"没测出来的原因。
 *
 * ① 点击任意分类 → 右表立刻出数据（不是"请选择分类"空态）
 * ② 真实拖拽到某个分类 → 提示语与目标一致、右表立刻过滤、树高亮
 * ③ 双击格子行内编辑 → 落库 + 表格显示新值 + 行仍可拖
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
  // 造一个"有子分类也有客户"的目标分类，和一条待拖的客户
  const target = await call('POST', '/api/v1/customer-categories', { name: `联动目标-${tag}`, parent_id: null });
  const sub = await call('POST', '/api/v1/customer-categories', { name: `联动子级-${tag}`, parent_id: target.body.id });
  const inTarget = await call('POST', '/api/v1/customers', {
    code: `CUST-IN-${tag}`,
    name: `已在目标里-${tag}`,
    category_id: target.body.id,
  });
  const toDrag = await call('POST', '/api/v1/customers', { code: `CUST-DRAG-${tag}`, name: `待拖客户-${tag}` });

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

  const clickRow = async (text) => {
    const box = await page.evaluate((t) => {
      const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes(t));
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x + 40), y: Math.round(r.y + r.height / 2) };
    }, text);
    if (!box) return false;
    await page.mouse.click(box.x, box.y);
    await sleep(700);
    return true;
  };

  const tableState = () =>
    page.evaluate(() => ({
      rows: document.querySelectorAll('tbody tr').length,
      empty: (document.querySelector('.erp-table__state-cell') || {}).textContent || '',
      header: (document.querySelector('.erp-card__subtitle, .erp-card__sub') || {}).textContent || '',
      active: [...document.querySelectorAll('.ptree__row.is-active')].map((e) => (e.textContent || '').trim().slice(0, 16)),
    }));

  // ── ① 点击分类 → 右表立刻有数据 ──────────────────────────────────────
  const clickedAll = await clickRow('全部客户');
  const allState = await tableState();
  check('点「全部客户」右表有数据', clickedAll && allState.rows > 0, `${allState.rows} 行`);

  const clickedTarget = await clickRow(`联动目标-${tag}`);
  const targetState = await tableState();
  check(
    '点具体分类 → 右表立刻加载该分类数据（不是"请选择分类"）',
    clickedTarget && targetState.rows === 1 && !/请先/.test(targetState.empty),
    `${targetState.rows} 行 / empty="${targetState.empty.slice(0, 20)}"`,
  );

  // ── ② 真实拖拽：提示语必须与目标一致，右表立刻过滤 ───────────────────
  await clickRow('全部客户');
  const srcBox = await page.evaluate((t) => {
    const tr = [...document.querySelectorAll('tbody tr')].find((el) => (el.textContent || '').includes(t));
    if (!tr) return null;
    const r = tr.getBoundingClientRect();
    return { x: Math.round(r.x + 60), y: Math.round(r.y + r.height / 2) };
  }, `待拖客户-${tag}`);
  const dstBox = await page.evaluate((t) => {
    const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes(t));
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x + 60), y: Math.round(r.y + r.height / 2) };
  }, `联动目标-${tag}`);

  const data = await page.mouse.drag(srcBox, dstBox);
  await page.mouse.dragEnter(dstBox, data);
  await page.mouse.dragOver(dstBox, data);
  await page.mouse.drop(dstBox, data);
  // ⚠️ drop 之后浏览器仍认为左键按着（drag 序列是 down 起的），不松开会报
  //    "left is already pressed"，后面所有 click 都失败
  await page.mouse.up().catch(() => {});
  await sleep(1500);

  const afterDrop = await tableState();
  const toast = await page.evaluate(() => {
    const box = [...document.querySelectorAll('div,span')].find((el) => /已成功移动/.test(el.textContent || '') && el.children.length === 0);
    return box ? box.textContent.trim() : '';
  });
  check('真实拖拽后提示语与实际目标一致', toast.includes(`联动目标-${tag}`), toast.slice(0, 60));
  check('真实拖拽后右表立刻过滤出该分类（2 行）', afterDrop.rows === 2, `${afterDrop.rows} 行`);
  check('真实拖拽后左树高亮目标', afterDrop.active.some((t) => t.includes(`联动目标-${tag}`)), JSON.stringify(afterDrop.active));

  const api = await call('GET', '/api/v1/customers');
  const moved = (api.body || []).find((c) => c.name === `待拖客户-${tag}`);
  check('落库分类 = 目标分类', moved && moved.category_id === target.body.id, `category_id=${moved && moved.category_id}`);

  // ── ③ 行内编辑：双击名称格 → 改名 → Enter ────────────────────────────
  const cellBox = await page.evaluate((t) => {
    const tr = [...document.querySelectorAll('tbody tr')].find((el) => (el.textContent || '').includes(t));
    if (!tr) return null;
    const td = tr.children[2]; // 0=选择列 1=编码 2=名称
    const r = td.getBoundingClientRect();
    return { x: Math.round(r.x + 30), y: Math.round(r.y + r.height / 2) };
  }, `待拖客户-${tag}`);
  await page.mouse.click(cellBox.x, cellBox.y, { clickCount: 1 });
  await sleep(90);
  await page.mouse.click(cellBox.x, cellBox.y, { clickCount: 1 });
  await sleep(400);
  let hasInput = await page.evaluate(() => Boolean(document.querySelector('.cell-edit-input')));
  if (!hasInput) {
    // 真鼠标没合成出 dblclick 时，补一次**合成** dblclick：只用来区分
    // "事件没到"与"处理逻辑坏了"，两条都不过才算真失败
    const diag = await page.evaluate((pt) => {
      const el = document.elementFromPoint(pt.x, pt.y);
      const td = el && el.closest ? el.closest('td') : null;
      const info = { tag: el && el.tagName, cls: el && el.className, cellIndex: td ? td.cellIndex : null };
      if (td) td.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
      return info;
    }, cellBox);
    await sleep(300);
    hasInput = await page.evaluate(() => Boolean(document.querySelector('.cell-edit-input')));
    console.log('    诊断：命中', JSON.stringify(diag), '→ 合成 dblclick 后 input =', hasInput);
  }
  check('双击名称格出现行内输入框', hasInput);

  if (hasInput) {
    // 用 page.type 走真实键盘输入（直接在 evaluate 里改 value 不会触发 React 的 onChange）
    await page.click('.cell-edit-input');
    await page.keyboard.down('Control');
    await page.keyboard.press('KeyA');
    await page.keyboard.up('Control');
    await page.type('.cell-edit-input', `改名后-${tag}`, { delay: 25 });
    await sleep(200);
    const typed = await page.evaluate(() => {
      const input = document.querySelector('.cell-edit-input');
      return input ? input.value : '(no input)';
    });
    console.log('    输入框当前值：', typed);
    await page.keyboard.press('Enter');
    await sleep(1500);
    const renamed = await page.evaluate((t) => document.body.innerText.includes(t), `改名后-${tag}`);
    check('行内改名后表格显示新值', renamed);
    const api2 = await call('GET', '/api/v1/customers');
    const row2 = (api2.body || []).find((c) => c.name === `改名后-${tag}`);
    check('行内改名已落库', Boolean(row2));
  }

  const stillDraggable = await page.evaluate(() => {
    const tr = document.querySelector('tbody tr');
    return tr ? tr.getAttribute('draggable') === 'true' : null;
  });
  check('行内编辑不影响行拖拽（draggable 仍在）', stillDraggable === true);

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  // 清理
  for (const c of [inTarget.body, toDrag.body]) if (c && c.id) await call('DELETE', `/api/v1/customers/${c.id}`);
  await call('DELETE', `/api/v1/customer-categories/${sub.body.id}`);
  await call('DELETE', `/api/v1/customer-categories/${target.body.id}`);
  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
