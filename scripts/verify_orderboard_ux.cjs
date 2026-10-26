/**
 * verify_orderboard_ux.cjs —— 任务二C 真浏览器验收（2026-10-21 夜间冲刺）。
 *
 * 覆盖三件事：
 *   A. 紧凑表头折叠 / 展开
 *   B. 明细列配置弹窗（隐藏列 → localStorage 持久化 → 恢复默认；锁列保护）
 *   C. 选客户/供应商自动带出 联系人/电话/地址（只回填空字段）
 * 附带：提交一张销售订单验证 contact 三字段真的随单落库（后端闭环），收尾删单。
 *
 * 反证纪律：每个断言都有真实 UI 操作驱动；探索性点击用真实鼠标坐标；
 * 关键断言后打 PROBE 标记，结束统计红绿。
 */
const path = require('path');
const puppeteer = require(path.join('C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules/puppeteer-core'));

// 端口可用 ERP_BASE 覆盖：开发 8013 / E 运行版 8011 / 打包桌面版 8010
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8013';
const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';

const results = [];
const ok = (name, pass, detail = '') => {
  results.push({ name, pass });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 通用：点开某个 ErpSearchSelect（按行标签定位），可输入关键字，选中第一/指定项。 */
async function pickSearchSelect(page, rowLabelLike, keyword) {
  await page.evaluate((label) => {
    const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
    const row = rows.find((el) => {
      const t = (el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '';
      return t.includes(label);
    });
    const trig = (row || document).querySelector('.ssel-trigger');
    if (trig) trig.click();
  }, rowLabelLike);
  await sleep(350);
  const input = await page.$('.ssel-input');
  if (input) {
    await input.click();
    if (keyword) await input.type(keyword, { delay: 40 });
  }
  await sleep(500);
  let options = await page.$$('.ssel-option');
  if (options.length === 0) {
    // 触发区可能被上一次点击关掉了：再点一次
    await page.evaluate((label) => {
      const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
      const row = rows.find((el) => {
        const t = (el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '';
        return t.includes(label);
      });
      const trig = (row || document).querySelector('.ssel-trigger');
      if (trig) trig.click();
    }, rowLabelLike);
    await sleep(500);
    const input2 = await page.$('.ssel-input');
    if (input2 && keyword) { await input2.click(); await input2.type(keyword, { delay: 40 }); await sleep(400); }
    options = await page.$$('.ssel-option');
  }
  if (options.length === 0 && input) {
    // 关键字没命中：清空再选第一项
    await input.click({ clickCount: 3 });
    await page.keyboard.press('Backspace');
    await sleep(350);
    options = await page.$$('.ssel-option');
  }
  if (options.length === 0) return null;
  const picked = await page.evaluate((kw) => {
    const list = [...document.querySelectorAll('.ssel-option')];
    const target = (kw && list.find((el) => el.textContent.includes(kw))) || list[0];
    const r = target.getBoundingClientRect();
    return { text: target.textContent.trim().slice(0, 24), x: r.x + r.width / 2, y: r.y + r.height / 2 };
  }, keyword);
  await page.mouse.click(picked.x, picked.y);
  await sleep(400);
  return picked.text;
}

(async () => {
  // 登录拿 token
  const loginRes = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const token = (await loginRes.json()).access_token;
  if (!token) throw new Error('login failed');

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(String(err)));

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await sleep(1200);
  // 清掉历史列配置，保证从干净状态开始
  await page.evaluate(() => {
    localStorage.removeItem('erp:doccols:sales');
    localStorage.removeItem('erp:doccols:purchase');
  });
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1200);

  // 展开所有侧边栏分组（默认收起），再进「销售订单」
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title').forEach((el) => {
      if (el.getAttribute('aria-expanded') !== 'true') el.click();
    });
  });
  await sleep(400);
  const clickedSales = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.nav-item')];
    const target = items.find((el) => el.textContent.trim().includes('销售订单'));
    if (!target) return false;
    target.click();
    return true;
  });
  ok('A0 进入销售订单页', clickedSales);
  await sleep(900);

  // ── A. 折叠 / 展开 ──────────────────────────────────────────────────────
  const gridBefore = await page.$('[data-doc-form] .erp-form-grid');
  const collapseBtn = await page.$('[data-doc-form-collapse]');
  ok('A1 折叠按钮存在且表头初始展开', Boolean(gridBefore && collapseBtn));
  await collapseBtn.click();
  await sleep(300);
  const collapsedState = await page.evaluate(() => {
    const grid = document.querySelector('[data-doc-form] .erp-form-grid');
    const hint = document.querySelector('[data-doc-form-collapsed-hint]');
    return { gridGone: !grid, hintText: hint ? hint.textContent.trim() : null };
  });
  ok('A2 收起后表头消失、摘要行出现且提示尚未选择客户',
    collapsedState.gridGone && /尚未选择/.test(collapsedState.hintText || ''),
    collapsedState.hintText);
  await page.click('[data-doc-form-collapse]');
  await sleep(300);
  const gridBack = await page.$('[data-doc-form] .erp-form-grid');
  ok('A3 展开恢复表头', Boolean(gridBack));

  // ── C. 选客户自动带出（先测，避免列配置的 DOM 变化干扰）────────────────
  // 手填一个联系人，验证"只回填空字段"
  const contactInput = await page.evaluateHandle(() => {
    const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
    const row = rows.find((el) => (el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent.includes('联系人'));
    return row ? row.querySelector('input') : null;
  });
  await contactInput.asElement().type('李四');
  await sleep(100);
  // 选客户（ErpSearchSelect：点开 → 关键字 → 点选项）
  const partyPicked = await pickSearchSelect(page, '客户', '西安创奕');
  if (!partyPicked) console.log('  ⚠️ 客户下拉没弹出，C 段可能失败');
  await sleep(400);
  const carried = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
    const getVal = (labelText) => {
      const row = rows.find((el) => ((el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '').trim() === labelText);
      return row ? row.querySelector('input')?.value : null;
    };
    return {
      contact: getVal('联系人'),
      phone: getVal('联系电话'),
      address: getVal('送货地址'),
    };
  });
  ok('C1 选客户带出联系人（手填的「李四」不被覆盖）', carried.contact === '李四', `contact=${carried.contact}`);
  ok('C2 带出联系电话', carried.phone === '029-73734646', `phone=${carried.phone}`);
  ok('C3 带出送货地址', /长安区|文苑中路/.test(carried.address || ''), `address=${carried.address}`);

  // ── B. 列配置 ───────────────────────────────────────────────────────────
  await page.click('[data-doc-col-config]');
  await sleep(300);
  // 弹窗真的在最上层：elementFromPoint 命中弹窗内部
  const modalOnTop = await page.evaluate(() => {
    const header = [...document.querySelectorAll('.modal-header h3')].find((el) => el.textContent.includes('明细列配置'));
    if (!header) return false;
    const r = header.getBoundingClientRect();
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return Boolean(hit && header.closest('.modal-card').contains(hit));
  });
  ok('B1 列配置弹窗打开且在最上层（z-index 正确）', modalOnTop);
  // 取消勾选「单位」「单价」→ 完成
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.doc-colpick-list label')];
    for (const text of ['单位', '单价']) {
      const el = items.find((l) => l.textContent.trim() === text);
      if (el) el.querySelector('input').click();
    }
  });
  await sleep(150);
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.modal-actions button')];
    btns.find((b) => b.textContent.includes('完成')).click();
  });
  await sleep(300);
  const colState = await page.evaluate(() => {
    const heads = [...document.querySelectorAll('[data-doc-form] .doc-lines th')].map((th) => th.textContent.trim());
    const foot = document.querySelector('[data-doc-form] .doc-total-row');
    return {
      heads,
      hasUnit: heads.includes('单位'),
      hasPrice: heads.includes('单价'),
      colSpan: foot ? Number(foot.querySelector('.doc-total-row__label')?.getAttribute('colspan')) : null,
      cellCount: foot ? foot.children.length : 0,
      stored: localStorage.getItem('erp:doccols:sales'),
    };
  });
  ok('B2 隐藏「单位/单价」后表头不含这两列', !colState.hasUnit && !colState.hasPrice, colState.heads.join('|'));
  // 口径：合计行必须**正好铺满**当前可见列（colSpan + 其余单元格 = 表头列数），
  // 不再写死 v96 的 2/4 —— 列集合调整过，硬编码数字会把"正确"判成"错"。
  ok('B3 合计行铺满可见列（colSpan 自适应）',
    (colState.colSpan || 0) + (colState.cellCount - 1) === colState.heads.length,
    `colSpan=${colState.colSpan} cells=${colState.cellCount} heads=${colState.heads.length}`);
  ok('B4 localStorage 持久化', /unit/.test(colState.stored || '') && /unit_price/.test(colState.stored || ''), colState.stored);

  // 刷新后配置仍在
  await page.reload({ waitUntil: 'networkidle2' });
  await sleep(1200);
  const persisted = await page.evaluate(() => {
    const heads = [...document.querySelectorAll('[data-doc-form] .doc-lines th')].map((th) => th.textContent.trim());
    return { hasUnit: heads.includes('单位'), hasPrice: heads.includes('单价') };
  });
  ok('B5 刷新后隐藏配置仍然生效', !persisted.hasUnit && !persisted.hasPrice);

  // 锁列保护：再藏 数量+金额 → 只剩商品列（商品列不在可隐藏清单）→ 数据列只剩 0 个？
  // 商品列是数据列！可编辑数据列 = 商品。数量/金额/单位/单价全藏 → label 锁定的是最后一个可编辑列。
  // 实际锁定规则：数量/单位/单价/金额 中只剩一个可见时锁定。先重开配置验证。
  await page.click('[data-doc-col-config]');
  await sleep(300);
  await page.evaluate(() => {
    const items = [...document.querySelectorAll('.doc-colpick-list label')];
    for (const text of ['数量']) {
      const el = items.find((l) => l.textContent.trim() === text);
      if (el) el.querySelector('input').click();
    }
  });
  await sleep(150);
  const lockedProbe = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.doc-colpick-list label')];
    const amount = items.find((l) => l.textContent.trim() === '金额');
    return { amountLocked: amount ? amount.classList.contains('doc-colpick--locked') : null };
  });
  ok('B6 只剩「金额」一列时锁定不可再藏（防呆）', lockedProbe.amountLocked === true);
  // 恢复默认
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.modal-actions button')];
    btns.find((b) => b.textContent.includes('恢复默认')).click();
  });
  await sleep(200);
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.modal-actions button')];
    btns.find((b) => b.textContent.includes('完成')).click();
  });
  await sleep(300);
  const restored = await page.evaluate(() => {
    const heads = [...document.querySelectorAll('[data-doc-form] .doc-lines th')].map((th) => th.textContent.trim());
    return { hasUnit: heads.includes('单位'), count: heads.length, stored: localStorage.getItem('erp:doccols:sales') };
  });
  ok('B7 恢复默认：6 列齐全且 localStorage 清空', restored.hasUnit && restored.count === 6 && restored.stored === null,
    `th=${restored.count} stored=${restored.stored}`);

  // ── 提交闭环：三字段随单落库 ────────────────────────────────────────────
  // 明细第一行选商品（任意可用商品），数量单价默认
  // ⚠️ B 段做过 page.reload()（持久化验证），表单被重置了 ——
  // 提交前必须重新选一次客户，否则后端会以"请先选择客户"拒绝。
  const repickParty = await pickSearchSelect(page, '客户', '西安创奕');
  console.log('  重新选客户:', repickParty || '未选中');
  // 手填联系人（验证"只回填空字段"的快照仍然随单落库）
  await page.evaluate(() => {
    const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
    const row = rows.find((el) => ((el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '').includes('联系人'));
    const input = row && row.querySelector('input');
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '李四');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await sleep(200);

  // 明细第一行选商品：点开下拉取第一条真实商品（原来写死"网线"，
  // 库里早没有这个名字了，会点到"没有匹配项"导致后面提交被拦）
  const linePicked = await page.evaluate(() => {
    const trig = document.querySelector('[data-doc-form] .doc-lines tbody tr .doc-line-product .ssel-trigger');
    if (trig) { trig.click(); return true; }
    return false;
  });
  await sleep(400);
  const opt = await page.evaluate(() => {
    const first = [...document.querySelectorAll('.ssel-option')].find((el) => !/没有匹配/.test(el.textContent || ''));
    if (!first) return null;
    const r = first.getBoundingClientRect();
    return { text: first.textContent.trim().slice(0, 20), x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  if (opt) await page.mouse.click(opt.x, opt.y);
  await sleep(500);
  console.log('  明细商品:', linePicked && opt ? opt.text : '未选中');
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('[data-doc-form] button[type="submit"]')][0];
    btn.click();
  });
  await sleep(1800);
  const noticeAfterSubmit = await page.evaluate(() => (document.querySelector('.notice, [class*=notice]') || {}).textContent || '');
  console.log('  提交后提示:', String(noticeAfterSubmit).replace(/\s+/g, ' ').trim().slice(0, 90) || '(空)');
  // 查落库
  const createdOrder = await (async () => {
    const res = await fetch(`${BASE}/api/v1/sales-orders?limit=5`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    const list = Array.isArray(data) ? data : data.items || [];
    // ⚠️ 只认**本次刚提交**的那张（contact=李四），绝不拿"最新一张"当靶子 ——
    // 曾经因此把一条真实历史导入单当成测试单删掉了。
    return list.find((o) => o.contact === '李四') || null;
  })();
  ok('C4 提交后 contact 三字段随单落库', Boolean(
    createdOrder && createdOrder.contact === '李四' &&
    createdOrder.contact_phone === '029-73734646' && /长安区|文苑中路/.test(createdOrder.address || ''),
  ), createdOrder ? `#${createdOrder.id} ${createdOrder.order_no} contact=${createdOrder.contact}` : '未找到新单');
  // 收尾：删测试单
  if (createdOrder && createdOrder.contact === '李四') {
    const del = await fetch(`${BASE}/api/v1/sales-orders/${createdOrder.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    ok('C5 测试单已删除（系统保持干净）', del.status === 200 || del.status === 204, `status=${del.status}`);
  }

  // ── 采购订单页抽检 ──────────────────────────────────────────────────────
  // 导航到采购订单：先展开全部分组（刷新后分组默认收起，菜单项根本没渲染）
  await page.evaluate(() => {
    for (const t of document.querySelectorAll('button.nav-group-title')) { try { t.click(); } catch (_) {} }
  });
  await sleep(700);
  await page.evaluate(() => {
    const cands = [...document.querySelectorAll('a, li, button, [class*=nav-item]')];
    const target = cands.find((el) => (el.textContent || '').trim() === '采购订单' && !el.classList.contains('nav-group-title'));
    if (target) target.click();
  });
  await sleep(1500);
  const pageTitle = await page.evaluate(() => (document.querySelector('.main-panel h1, .main-panel h2') || {}).textContent || '');
  console.log('  当前页:', String(pageTitle).trim());
  const purchaseProbe = await page.$('[data-doc-form-collapse]') && await page.$('[data-doc-col-config]');
  ok('D1 采购订单页同款折叠+列配置入口', Boolean(purchaseProbe));
  // 选供应商带出：520 陈秀玲
  const purchaseLabels = await page.evaluate(() => [...document.querySelectorAll('[data-doc-form] .erp-form-row')]
    .map((el) => ((el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '').trim()));
  console.log('  采购页表单行:', purchaseLabels.join(' / '));
  // 关键字要与档案里的名称前缀一致（"深圳市凯歌电子有限公司"），
  // 之前写"深圳凯歌"匹配不到 —— 差一个"市"字，下拉里就没有这一项。
  const supPickedText = await pickSearchSelect(page, '供应商', '深圳市凯歌');
  console.log('  选中供应商:', supPickedText || '未选中');
  await sleep(300);
  const supPick = await page.evaluate(() => {
    const row = [...document.querySelectorAll('.ssel-option')].find((el) => el.textContent.includes('深圳市凯歌电子有限公司'));
    if (!row) return null;
    const r = row.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  if (supPick) await page.mouse.click(supPick.x, supPick.y);
  await sleep(400);
  const supCarried = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('[data-doc-form] .erp-form-row')];
    const getVal = (labelText) => {
      const row = rows.find((el) => ((el.querySelector('label') || el.querySelector('.erp-form-row__label'))?.textContent || '').trim() === labelText);
      return row ? row.querySelector('input')?.value : null;
    };
    return { contact: getVal('联系人'), address: getVal('收货地址') };
  });
  ok('D2 选供应商带出联系人/收货地址', supCarried.contact === '陈秀玲' && supCarried.address === '广东佛山',
    `contact=${supCarried.contact} address=${supCarried.address}`);

  // 零 pageerror
  ok('Z1 全程零页面错误', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '));

  await browser.close();
  const passed = results.filter((r) => r.pass).length;
  console.log(`\nPROBE TOTAL: ${passed}/${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
})().catch((err) => {
  console.error('FATAL', err);
  process.exit(2);
});
