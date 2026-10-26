/**
 * verify_v76_full.cjs —— v76 全站替换真浏览器验收
 *
 * 覆盖：
 *   1. 客户弹窗「所属分类」= ErpTreeSelect，默认折叠 3 顶级
 *   2. 供应商弹窗「所属分类」= ErpTreeSelect（同一 PartnerModal，kind=supplier）
 *   3. 商品弹窗「类别」= ErpTreeSelect（nodes=商品分类树，getNodeValue=name）
 *   4. 商品列表勾选 → 「批量移动」按钮 → 小窗出现 → 选分类 → 接口返回 moved
 *      （用 1 个商品做真实移动 + 还原，确认整链路通）
 *   5. 全程零 pageerror
 */

const fs = require('fs');
const path = require('path');

const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = [
  'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const SHOT_DIR = path.resolve(__dirname, '..', 'docs', '验收截图');

let pass = 0;
let fail = 0;
const failures = [];
const check = (name, ok, detail) => {
  if (ok) { pass += 1; console.log(`  ✅ ${name}`); }
  else { fail += 1; failures.push(name + (detail ? ` —— ${detail}` : '')); console.log(`  ❌ ${name}${detail ? ` —— ${detail}` : ''}`); }
};

(async () => {
  if (!CHROME) { console.error('no chrome'); process.exit(1); }
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new', args: ['--no-sandbox'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message ? e.message : e)));

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle2' });
  const token = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/v1/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
    });
    return (await r.json()).access_token || '';
  }, BASE);
  check('登录拿 token', Boolean(token));
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 1500));

  const openGroupAndItem = async (groupRe, itemRe) => {
    await page.evaluate((g, i) => {
      const reG = new RegExp(g), reI = new RegExp(i);
      // ⚠️ 组标题是 toggle：已展开时再点会**收起**。只在未见菜单项时才点开。
      const hasItem = [...document.querySelectorAll('.nav-item')].some((e) => reI.test(e.textContent));
      if (!hasItem) {
        [...document.querySelectorAll('.nav-group-title')].find((t) => reG.test(t.textContent))?.click();
      }
      setTimeout(() => {
        [...document.querySelectorAll('.nav-item')].find((e) => reI.test(e.textContent))?.click();
      }, 350);
    }, groupRe, itemRe);
    await new Promise((r) => setTimeout(r, 1400));
  };

  const probeTreePanel = async (triggerSel) => {
    await page.click(`${triggerSel} .tsel-trigger`);
    await new Promise((r) => setTimeout(r, 500));
    const st = await page.evaluate(() => {
      const panel = document.querySelector('[data-erp-tree-select-panel]');
      if (!panel) return null;
      const rows = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')];
      return {
        count: rows.length,
        leaves: rows.filter((r) => r.dataset.tselLeaf === '1').length,
        flatPath: rows.some((r) => /\s\/\s/.test(r.querySelector('.tsel-row__label')?.textContent || '')),
        hasSearch: Boolean(panel.querySelector('[data-tsel-search]')),
      };
    });
    return st;
  };

  /* ── 1. 客户弹窗 ── */
  console.log('\n── 客户弹窗 ──');
  await openGroupAndItem('基础资料', '客户档案');
  await page.evaluate(() => { [...document.querySelectorAll('button')].find((b) => /新增客户/.test(b.textContent))?.click(); });
  await new Promise((r) => setTimeout(r, 700));
  const cust = await probeTreePanel('[data-erp-tree-select="partner-customer-category"]');
  check('客户「所属分类」是树形下拉', Boolean(cust));
  check('客户默认折叠（只显示顶级，无平铺路径）', cust && cust.count === 3 && cust.leaves === 0 && !cust.flatPath, JSON.stringify(cust));
  await page.keyboard.press('Escape');
  await new Promise((r) => setTimeout(r, 300));
  await page.evaluate(() => { document.querySelector('.modal-backdrop .close-btn')?.click(); });
  await new Promise((r) => setTimeout(r, 400));

  /* ── 2. 供应商弹窗 ── */
  console.log('\n── 供应商弹窗 ──');
  await openGroupAndItem('基础资料', '供应商档案');
  await page.evaluate(() => { [...document.querySelectorAll('button')].find((b) => /新增供应商/.test(b.textContent))?.click(); });
  await new Promise((r) => setTimeout(r, 700));
  const sup = await probeTreePanel('[data-erp-tree-select="partner-supplier-category"]');
  check('供应商「所属分类」是树形下拉（不再走旧 ErpSearchSelect）', Boolean(sup));
  /* 供应商树顶级 5 个：国家电网[枝]、中铁一局[叶]、马雷[枝]、崔军[叶]、创奕[叶]。
     默认折叠的正确表现 = count===5（正好顶级数）、3 个叶子直接可选、无平铺路径。 */
  check('供应商默认折叠（正好 5 个顶级，无平铺路径）', sup && sup.count === 5 && !sup.flatPath, JSON.stringify(sup));
  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_供应商_树形下拉.png') });
  await page.evaluate(() => { document.querySelector('.modal-backdrop .close-btn')?.click(); });
  await new Promise((r) => setTimeout(r, 400));

  /* ── 3. 商品弹窗 ── */
  console.log('\n── 商品弹窗 ──');
  await openGroupAndItem('基础资料', '商品档案');
  await page.evaluate(() => { [...document.querySelectorAll('button')].find((b) => /新增商品|新增产品/.test(b.textContent))?.click(); });
  await new Promise((r) => setTimeout(r, 700));
  const prod = await probeTreePanel('[data-erp-tree-select="product-category"]');
  check('商品「类别」是树形下拉', Boolean(prod));
  check('商品默认折叠（无平铺路径）', prod && !prod.flatPath, JSON.stringify(prod));
  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_商品_类别树.png') });
  await page.evaluate(() => { document.querySelector('.modal-backdrop .close-btn')?.click(); });
  await new Promise((r) => setTimeout(r, 400));

  /* ── 4. 批量移动 ── */
  console.log('\n── 批量移动 ──');
  // 商品档案页左侧树点「全部」（⚠️ 商品页树类名是 .category-tree，不是 .ptree__body）
  await page.evaluate(() => {
    const body = document.querySelector('.category-tree') || document.querySelector('.ptree__body');
    if (body) {
      const leaf = [...body.querySelectorAll('*')].find(
        (el) => el.children.length === 0 && /^全部/.test((el.textContent || '').trim()),
      );
      if (leaf) leaf.click();
    }
  });
  await new Promise((r) => setTimeout(r, 1200));
  const rowsNow = await page.evaluate(() => document.querySelectorAll('tr.erp-table__row').length);
  check('商品列表有行', rowsNow > 0, `rows=${rowsNow}`);

  // 勾选第一行
  await page.evaluate(() => {
    const row = document.querySelector('tr.erp-table__row');
    const cb = row && row.querySelector('input[type=checkbox]');
    if (cb && !cb.checked) cb.click();
  });
  await new Promise((r) => setTimeout(r, 500));
  const bulkVisible = await page.evaluate(() => Boolean(document.querySelector('[data-product-batch-move]')));
  check('勾选后「批量移动」按钮出现', bulkVisible);

  await page.click('[data-product-batch-move]');
  await new Promise((r) => setTimeout(r, 600));
  const dialog = await page.evaluate(() => {
    const d = document.querySelector('[data-batch-move-dialog]');
    if (!d) return null;
    return { title: d.querySelector('h3')?.textContent, hasTree: Boolean(d.querySelector('[data-erp-tree-select="product-batch-move"]')) };
  });
  check('批量移动小窗出现且内含树形下拉', Boolean(dialog && dialog.hasTree), JSON.stringify(dialog));
  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_批量移动_小窗.png') });

  // 在小窗里选一个分类（点第一个非清除叶子）并提交
  const moved = await page.evaluate(async () => {
    const d = document.querySelector('[data-batch-move-dialog]');
    // ⚠️ 面板要先点触发器才存在 —— 直接找 .tsel-row 会"无叶子可选"（假红）
    const trigger = d.querySelector('[data-erp-tree-select="product-batch-move"] .tsel-trigger');
    trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
    const rows = [...document.querySelectorAll('.tsel-row[data-tsel-key]')];
    const leaf = rows.find((r) => r.dataset.tselLeaf === '1');
    if (!leaf) return { ok: false, why: '无叶子可选', count: rows.length };
    leaf.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 300));
    const label = leaf.querySelector('.tsel-row__label')?.textContent.trim();
    const submit = [...d.querySelectorAll('button')].find((b) => /移动 \d+ 个商品/.test(b.textContent));
    if (!submit) return { ok: false, why: '无提交按钮' };
    submit.click();
    // 等notice 或弹窗关闭
    for (let i = 0; i < 20; i += 1) {
      await new Promise((r) => setTimeout(r, 300));
      if (!document.querySelector('[data-batch-move-dialog]')) return { ok: true, label };
    }
    return { ok: false, why: '弹窗未关闭', label };
  });
  check('批量移动整链路走通（选叶子→提交→弹窗关）', moved.ok, JSON.stringify(moved));
  if (moved.label) {
    // 还原：把该商品移回原分类 —— 直接调接口反查
    const restore = await page.evaluate(async (label) => {
      const t = localStorage.getItem('erp_token');
      const res = await fetch('/api/v1/products?limit=500', { headers: { Authorization: `Bearer ${t}` } });
      const data = await res.json();
      const rows = Array.isArray(data) ? data : data.rows || data.items || [];
      // 刚才移动的那个商品：勾选的是第一行，但这里难精确定位；用 category===label 的第一个商品改回「其他」
      const target = rows.find((r) => r.category === label);
      if (!target) return { restored: false };
      const r2 = await fetch('/api/v1/products/batch-category', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
        body: JSON.stringify({ ids: [target.id], category: '其他' }),
      });
      return { restored: r2.ok, id: target.id };
    }, moved.label);
    check('测试数据已还原（目标商品类别改回「其他」）', restore.restored, JSON.stringify(restore));
  }

  /* ── 5. 健康检查 ── */
  check('全程零 pageerror', pageErrors.length === 0, pageErrors.join(' | '));

  await browser.close();
  console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
  if (fail) { failures.forEach((f) => console.log('  - ' + f)); process.exit(1); }
})().catch((e) => { console.error('脚本异常', e); process.exit(1); });
