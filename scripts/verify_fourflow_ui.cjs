/**
 * 真浏览器验收：四流合一 · 第二阶段第 2/4 步（发票挂单据 + 物流签收）。
 *
 * 只验"屏幕上看得见的东西"，一条数据都不改：
 *   1. 发票管理 → 某张销项票「编辑」→ 弹窗里有「关联单据」搜索选择器
 *   2. 点开选择器 → 候选里是**销售单号**（不是商品、不是空列表）
 *   3. 关掉弹窗 → 列表发票号码下面出现「未关联」小字（还没挂单的票看得见）
 *   4. 销售出库 → 点开一张出库单 → 详情里有「物流 / 签收」4 个输入框 + 签收状态角标
 *
 * 为什么全程不点保存：这是真实账套。字段写入由接口验收
 * （scripts/verify_fourflow_link.py，35 条）负责，这里只验"人能不能看到并操作"。
 *
 * 跑法（后端先起好）：
 *   ERP_BASE=http://127.0.0.1:8011 node scripts/verify_fourflow_ui.cjs
 * 产物：docs/验收截图/16~18-*.png
 */
const fs = require('fs');
const path = require('path');

const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8010';
const SHOT_DIR = path.resolve(__dirname, '..', 'docs', '验收截图');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, extra = '') => {
  results.push({ name, ok, extra });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
};

(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true });

  const login = await fetch(`${BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  if (!login.ok) throw new Error(`登录失败 HTTP ${login.status}`);
  const { access_token: token } = await login.json();

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();
  page.on('pageerror', (err) => console.log('  [页面报错]', String(err).slice(0, 200)));

  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });

  // 侧边栏分组默认收起：组没展开时 .nav-item 根本不在 DOM 里
  await page.waitForSelector('.nav-group-title', { timeout: 30000 });
  await sleep(500);
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title.collapsed').forEach((el) => el.click());
  });
  await sleep(700);

  const openMenu = async (label) => {
    const ok = await page.evaluate((want) => {
      const item = Array.from(document.querySelectorAll('.nav-group-items .nav-item')).find(
        (el) => el.textContent.trim().indexOf(want) === 0,
      );
      if (!item) return false;
      item.click();
      return true;
    }, label);
    if (ok) await sleep(1400);
    return ok;
  };

  const shot = async (name) => {
    await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`), fullPage: false });
  };

  // ══ 1. 发票管理 → 编辑弹窗 → 关联单据 ══════════════════════════
  console.log('\n── 发票 → 关联单据（界面） ──');
  const pageOpened = await openMenu(['发票管理', '开票管理']);
  check('1.1 侧边栏能进「发票管理 / 开票管理」', pageOpened);

  // 空态是占满整行的 <tr><td class="erp-table__state-cell">，必须排掉才算行数
  await page.waitForFunction(
    () => document.querySelectorAll('tbody tr').length > 0,
    { timeout: 30000 },
  );
  await sleep(800);

  const rowCount = await page.evaluate(
    () => Array.from(document.querySelectorAll('tbody tr')).filter((tr) => !tr.querySelector('.erp-table__state-cell')).length,
  );
  check('1.2 发票列表有数据行', rowCount > 0, `${rowCount} 行`);

  const emptyTagCount = await page.evaluate(
    () => document.querySelectorAll('.invoice-order-link.is-empty').length,
  );
  check('1.3 没挂单的票，号码下面有「未关联」标记', emptyTagCount > 0, `${emptyTagCount} 张`);

  const linkedTagCount = await page.evaluate(
    () => document.querySelectorAll('.invoice-order-link:not(.is-empty)').length,
  );
  console.log(`  · 已挂单标记：${linkedTagCount} 张（存量 4 张都是未挂，预期 0）`);

  // 点第一行的「编辑」
  const editClicked = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tbody tr')).filter((tr) => !tr.querySelector('.erp-table__state-cell'));
    for (const tr of rows) {
      const btn = Array.from(tr.querySelectorAll('button')).find((b) => b.textContent.trim() === '编辑');
      if (btn) { btn.click(); return true; }
    }
    return false;
  });
  check('1.4 能打开「编辑发票」弹窗', editClicked);

  await page.waitForSelector('.invoice-edit-form', { timeout: 15000 });
  await sleep(400);

  const fieldInfo = await page.evaluate(() => {
    const field = document.querySelector('.invoice-edit-form .order-link-field');
    const trigger = field && field.querySelector('.ssel-trigger');
    const hint = field && field.querySelector('.order-link-field__hint');
    const direction = (() => {
      const sel = Array.from(document.querySelectorAll('.invoice-edit-form select')).find((s) =>
        Array.from(s.options).some((o) => o.value === 'output' && o.textContent.includes('销项')),
      );
      return sel ? sel.value : '';
    })();
    return {
      hasField: Boolean(field),
      hasTrigger: Boolean(trigger),
      triggerText: trigger ? trigger.textContent.trim() : '',
      hintText: hint ? hint.textContent.trim() : '',
      label: field ? field.querySelector('span').textContent.trim() : '',
      direction,
      disabled: trigger ? trigger.closest('.ssel')?.getAttribute('data-disabled') === 'true' : null,
    };
  });

  check('1.5 弹窗里有「关联单据」区块', fieldInfo.hasField, fieldInfo.label);
  check('1.6 触发器是可搜索下拉（不是原生 select）', fieldInfo.hasTrigger, fieldInfo.triggerText);
  check('1.7 有说明文字（未关联的后果）', fieldInfo.hintText.length > 0, fieldInfo.hintText.slice(0, 40));
  if (fieldInfo.direction === 'unknown') {
    check('1.8 待判定的票：选择器禁用并给出提示', fieldInfo.disabled === true && fieldInfo.triggerText.includes('进销项'));
  } else {
    check('1.8 进销项已判定：选择器可用', fieldInfo.disabled === false, `direction=${fieldInfo.direction}`);
  }

  // 点开看候选
  await page.click('.invoice-edit-form .order-link-field .ssel-trigger');
  await sleep(600);
  const options = await page.evaluate(() => {
    const panel = document.querySelector('.ssel-panel');
    if (!panel) return { open: false, texts: [] };
    const texts = Array.from(panel.querySelectorAll('.ssel-option')).map((el) => el.textContent.trim());
    return { open: true, texts };
  });
  await shot('16-发票关联单据');
  check('1.9 点开后面板弹出', options.open);
  check('1.10 候选里有单据号（说明挂的是单据不是商品）',
    options.texts.some((t) => /[A-Z]{2,}\d|XS|CG/.test(t)),
    options.texts.slice(0, 3).join(' | ').slice(0, 120));
  check('1.11 候选不是空的', options.texts.length > 0, `${options.texts.length} 条`);

  // 关掉面板与弹窗（不保存 → 一行数据都不动）
  await page.keyboard.press('Escape');
  await sleep(300);
  const closed = await page.evaluate(() => {
    const cancel = Array.from(document.querySelectorAll('.invoice-edit-form button')).find((b) => b.textContent.trim() === '取消');
    if (cancel) { cancel.click(); return true; }
    return false;
  });
  await sleep(600);
  check('1.12 取消能关掉弹窗（不写库）', closed);

  // ══ 2. 销售出库 → 详情里的物流 / 签收 ═══════════════════════════
  console.log('\n── 销售出库 → 物流签收（界面） ──');
  const outboundOpened = await openMenu('销售出库');
  check('2.1 侧边栏能进「销售出库」', outboundOpened);
  await sleep(800);

  const rowClicked = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tbody tr')).filter((tr) => !tr.querySelector('.erp-table__state-cell'));
    if (!rows.length) return false;
    rows[0].click();
    return true;
  });
  check('2.2 能点开一张出库单详情', rowClicked);

  const hasSection = await page
    .waitForSelector('[data-logistics-section]', { timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  check('2.3 详情里有「物流 / 签收」区块', hasSection);

  const logistics = await page.evaluate(() => {
    const sec = document.querySelector('[data-logistics-section]');
    if (!sec) return null;
    const labels = Array.from(sec.querySelectorAll('.doc-logistics__grid label > span')).map((el) => el.textContent.trim());
    const inputs = Array.from(sec.querySelectorAll('.doc-logistics__grid input')).map((el) => el.type || 'text');
    const badge = sec.querySelector('.status-badge');
    return {
      labels,
      inputs,
      badge: badge ? badge.textContent.trim() : '',
      hasButton: Array.from(sec.querySelectorAll('button')).some((b) => /登记签收|更新物流/.test(b.textContent)),
      hint: (sec.querySelector('.doc-logistics__hint') || {}).textContent || '',
    };
  });
  check('2.4 四个输入框齐全（公司/单号/签收人/签收时间）',
    logistics && ['物流公司', '物流单号', '签收人', '签收时间'].every((t) => logistics.labels.includes(t)),
    logistics ? logistics.labels.join(' / ') : '');
  check('2.5 签收时间是 datetime-local（能选到分钟）',
    logistics && logistics.inputs.includes('datetime-local'), logistics ? logistics.inputs.join(',') : '');
  check('2.6 有「已签收 / 未签收」状态角标',
    logistics && ['已签收', '未签收'].includes(logistics.badge), logistics ? logistics.badge : '');
  check('2.7 有保存按钮', logistics && logistics.hasButton);

  await shot('17-销售出库物流签收');
  console.log('  · 备注：', logistics && logistics.hint.slice(0, 50));

  // 关掉详情弹窗
  await page.evaluate(() => {
    const overlay = document.querySelector('.modal-overlay');
    if (overlay) overlay.click();
  });
  await sleep(500);

  // ══ 3. 汇总 ══════════════════════════════════════════════════
  await browser.close();
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${'='.repeat(62)}\n结果：${passed}/${results.length} 条通过`);
  const failed = results.filter((r) => !r.ok).map((r) => r.name);
  if (failed.length) {
    console.log('失败项：\n' + failed.map((n) => '  · ' + n).join('\n'));
  }
  console.log('='.repeat(62));
  process.exit(passed === results.length ? 0 : 1);
})().catch((err) => {
  console.error('验收脚本异常：', err);
  process.exit(1);
});
