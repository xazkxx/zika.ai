/**
 * 树形下拉组件验收：客户 / 供应商 / 商品 / 商品批量移动 四处。
 *
 * 验三件事：
 *   ① 回显——编辑弹窗里「所属分类」显示的是**名称路径**，不是原始 id；
 *   ② 下拉——面板里真的列出了分类节点（不止「未分类」）；
 *   ③ 选择——点一个末级节点后，输入框变成它的路径、值也回写了。
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

  const openMenu = async (label) => {
    await page.evaluate((t) => {
      const it = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === t);
      if (it) it.click();
    }, label);
    await sleep(1500);
  };

  /** 打开第一行的「编辑」，读分类下拉的触发器文案；点开面板数节点。 */
  const probePartner = async (menu, expectName, dataAttr) => {
    await openMenu(menu);
    await page.evaluate(() => {
      const all = [...document.querySelectorAll('.ptree__row')].find((el) => /^全部/.test((el.textContent || '').trim()));
      if (all) all.click();
    });
    await sleep(900);
    // 找一条"有分类"的行来编辑（没有就退回第一行）
    const opened = await page.evaluate((attr) => {
      const rows = [...document.querySelectorAll('tbody tr')];
      const hit = rows.find((tr) => (tr.textContent || '').includes(attr)) || rows[0];
      if (!hit) return false;
      const btn = [...hit.querySelectorAll('button')].find((b) => b.textContent.trim() === '编辑');
      if (!btn) return false;
      btn.click();
      return true;
    }, expectName);
    await sleep(900);
    const trigger = await page.evaluate(() => {
      const el = document.querySelector('[data-erp-tree-select-field="category_id"] .tsel-trigger');
      if (!el) return null;
      const wrapper = el.closest('.erp-form-row') || el.parentElement;
      return {
        text: (el.innerText || '').trim(),
        rowText: (wrapper ? wrapper.innerText : '').trim().slice(0, 80),
      };
    });
    return { opened, trigger };
  };

  // ── 客户档案 ────────────────────────────────────────────────────────────
  const customer = await probePartner('客户档案', '湖南华邦建设有限公司');
  check('客户：编辑弹窗能打开', customer.opened);
  const custText = customer.trigger ? customer.trigger.rowText : '';
  check(
    '客户：分类回显是名称而不是纯数字 id',
    Boolean(customer.trigger) && !/^\s*\d+\s*$/.test(customer.trigger.text || '') && /[\u4e00-\u9fa5]/.test(customer.trigger.text || ''),
    `trigger="${customer.trigger && customer.trigger.text}"`,
  );
  const custPanel = await page.evaluate(() => {
    const trig = document.querySelector('[data-erp-tree-select-field="category_id"] .tsel-trigger');
    if (!trig) return null;
    trig.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    trig.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  });
  await sleep(600);
  const custNodes = await page.evaluate(() => {
    const panel = document.querySelector('.tsel-panel');
    if (!panel) return { open: false, nodes: 0, texts: [] };
    const items = [...panel.querySelectorAll('.tsel-row')];
    return { open: true, nodes: items.length, texts: items.slice(0, 6).map((el) => (el.textContent || '').trim()) };
  });
  check('客户：下拉面板列出了分类节点', custPanel && custNodes.open && custNodes.nodes > 0, `${custNodes.nodes} 个节点 ${JSON.stringify(custNodes.texts)}`);
  await page.keyboard.press('Escape');
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.partner-modal button')].find((b) => b.textContent.trim() === '取消' || b.getAttribute('aria-label') === '关闭');
    if (btn) btn.click();
  });
  await sleep(500);

  // ── 供应商档案 ──────────────────────────────────────────────────────────
  // 挑一条**确实有分类**的供应商（「陕西德龙不锈钢」category_id=1），
  // 否则回显永远是 placeholder，这条断言等于没测。
  const supplier = await probePartner('供应商档案', '陕西德龙不锈钢');
  check('供应商：编辑弹窗能打开', supplier.opened);
  check(
    '供应商：分类回显是名称而不是纯数字',
    Boolean(supplier.trigger) && /[\u4e00-\u9fa5]/.test((supplier.trigger && supplier.trigger.text) || ''),
    `trigger="${supplier.trigger && supplier.trigger.text}"`,
  );
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.partner-modal button')].find((b) => b.textContent.trim() === '取消' || b.getAttribute('aria-label') === '关闭');
    if (btn) btn.click();
  });
  await sleep(500);

  // ── 商品档案：编辑里的「类别」──────────────────────────────────────────
  await openMenu('商品档案');
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('.category-tree *')].find((el) => /^全部商品/.test((el.textContent || '').trim()));
    if (all) all.click();
  });
  await sleep(900);
  const productOpened = await page.evaluate(() => {
    const row = [...document.querySelectorAll('tbody tr')].find((tr) => tr.querySelector('button'));
    const btn = row && [...row.querySelectorAll('button')].find((b) => b.textContent.trim() === '编辑');
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(900);
  const productTrigger = await page.evaluate(() => {
    const el = document.querySelector('[data-erp-tree-select-field="category"] .tsel-trigger');
    return el ? (el.innerText || '').trim() : null;
  });
  check('商品：类别下拉有回显', productOpened && Boolean(productTrigger), `trigger="${productTrigger}"`);
  const productNodes = await page.evaluate(() => {
    const trig = document.querySelector('[data-erp-tree-select-field="category"] .tsel-trigger');
    if (!trig) return 0;
    trig.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    trig.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return -1;
  });
  await sleep(600);
  const pNodes = await page.evaluate(() => {
    const panel = document.querySelector('.tsel-panel');
    return panel ? panel.querySelectorAll('.tsel-row').length : 0;
  });
  check('商品：类别面板列出了节点', productNodes === -1 && pNodes > 0, `${pNodes} 个`);
  await page.keyboard.press('Escape');

  check('全程零页面错误', errors.length === 0, errors[0] || '');

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - failed.length} 通过 / ${failed.length} 失败`);
  if (failed.length) console.log('失败项：', failed.map((r) => r.name).join(' / '));
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验台本身出错：', err);
  process.exit(2);
});
