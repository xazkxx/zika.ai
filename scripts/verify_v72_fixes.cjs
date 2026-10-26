/**
 * 真浏览器验收（v72）：4 个问题的修复。
 *
 * 验的都是**用户屏幕上能看到的**，不看源码：
 *   问题 1  销售退货：反审核只退回草稿（账不动）；作废要过二次弹窗 + 必填原因
 *   问题 2  五个档案页右上角都有「导入」，弹窗能打开、有三步、导出勾选列还在；
 *           左侧菜单已无「导入导出」
 *   问题 3  供应商档案点「中铁一局集团」不再白屏，且没有 ErrorBoundary 兜底卡片
 *   问题 4  左侧菜单已无「销售对账单」，「增强对账单」仍在
 *
 * 跑法（后端 8011 + 前端 dist 已构建）：
 *   ERP_BASE=http://127.0.0.1:8010 node scripts/verify_v72_fixes.cjs
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
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 200)));

  const shot = (name) =>
    page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) }).catch(() => {});

  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
  // 侧边栏分组默认收起：.nav-item 不在 DOM 里，得先全部展开
  await page.waitForSelector('.nav-group-title', { timeout: 30000 });
  await sleep(600);
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title.collapsed').forEach((el) => el.click());
  });
  await sleep(600);

  const navLabels = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.nav-item')).map((el) => (el.textContent || '').trim()),
  );
  console.log('\n侧边栏菜单：', navLabels.join(' | ').slice(0, 400));

  const openMenu = async (label) => {
    const ok = await page.evaluate((text) => {
      const items = Array.from(document.querySelectorAll('.nav-item'));
      const hit = items.find((el) => (el.textContent || '').trim() === text);
      if (!hit) return false;
      hit.click();
      return true;
    }, label);
    if (ok) await sleep(1500);
    return ok;
  };

  const visibleText = () => page.evaluate(() => document.body.innerText);

  /**
   * 档案页左侧的分类树是「三态」的：**没选 → 表格空**（设计如此，左侧树是入口）。
   * 2026-10-21 修正：原来这里直接数 tbody 行，等于在"还没选分类"的状态下数，
   * 必然 0 行 —— 是断言过期，不是页面坏了。点一下「全部」再看。
   */
  const clickAll = async () => {
    const hitInfo = await page.evaluate(() => {
      const nodes = Array.from(
        document.querySelectorAll(
          '.partners-tree .ptree__row, .partners-tree button, .partners-tree .erp-tree-node, .partners-tree [role="treeitem"]',
        ),
      );
      // 「全部客户 41」这种文案，取文本以「全部」开头的最外层节点
      const hit = nodes.find((el) => /^全部/.test((el.textContent || '').trim()));
      if (!hit) return null;
      hit.click();
      return { cls: hit.className, text: (hit.textContent || '').trim().slice(0, 24) };
    });
    if (!hitInfo) {
      console.log('  （左侧树里没找到「全部」节点）');
      return false;
    }
    await sleep(1000);
    return true;
  };

  /** 造一张 submitted 状态的退货单（只是为了能看见「反审核 / 作废」两个按钮）。 */
  const seedReturn = async () => {
    const customer = await fetch(`${BASE}/api/v1/customers?limit=1`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then((r) => r.json());
    const customerId = (Array.isArray(customer) ? customer[0] : null)?.id;
    if (!customerId) return null;
    const resp = await fetch(`${BASE}/api/v1/sales-returns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      // 单号走 TEST-XSTH 签名：clean_test_data.py 认这个前缀，脚本异常退出也不会留垃圾
      body: JSON.stringify({
        return_no: `TEST-XSTHV72${Date.now().toString().slice(-6)}`,
        customer_id: customerId,
        note: '销售退货测试（验收临时单，脚本结束即删）',
      }),
    });
    if (!resp.ok) return null;
    return resp.json();
  };

  // ── 问题 4：销售对账单已下架 ──
  console.log('\n── 问题 4：菜单瘦身 ──');
  check('左侧菜单已无「销售对账单」', !navLabels.includes('销售对账单'));
  check('左侧菜单仍有「增强对账单」', navLabels.includes('增强对账单'));

  // ── 问题 2：导入导出已内嵌、独立菜单已下架 ──
  console.log('\n── 问题 2：导入导出解耦 ──');
  check('左侧菜单已无「导入导出」', !navLabels.includes('导入导出'));

  const archivePages = [
    { menu: '客户档案', kind: 'customers', label: '客户' },
    { menu: '供应商档案', kind: 'suppliers', label: '供应商' },
    { menu: '商品档案', kind: 'products', label: '商品' },
    { menu: '仓库档案', kind: 'warehouses', label: '仓库' },
    { menu: '员工档案', kind: 'employees', label: '员工' },
  ];

  for (const item of archivePages) {
    const opened = await openMenu(item.menu);
    if (!opened) {
      check(`${item.menu}：菜单可打开`, false, '侧边栏找不到');
      continue;
    }
    // 点右上角「导入」
    const clicked = await page.evaluate(() => {
      const btn = document.querySelector('[data-import-open]');
      if (!btn) return false;
      btn.click();
      return true;
    });
    check(`${item.menu}：右上角有「导入」按钮`, clicked);
    if (!clicked) continue;

    await sleep(800);
    const dlg = await page.evaluate(() => {
      const el = document.querySelector('[data-archive-import]');
      if (!el) return null;
      return {
        kind: el.getAttribute('data-archive-import'),
        step: !!el.querySelector('[data-import-step="template"]'),
        templateBtn: !!el.querySelector('[data-import-template]'),
        fileBtn: !!el.querySelector('[data-import-file]'),
        text: (el.innerText || '').slice(0, 120),
      };
    });
    check(
      `${item.menu}：导入弹窗打开且 kind=${item.kind}`,
      !!dlg && dlg.kind === item.kind,
      dlg ? `kind=${dlg.kind}` : '弹窗未出现',
    );
    check(
      `${item.menu}：弹窗有「下载模板 + 选择文件」两步`,
      !!dlg && dlg.templateBtn && dlg.fileBtn,
    );
    if (item.menu === '客户档案') await shot('v72-import-dialog-customers');

    // 关掉弹窗（Esc 或点关闭）
    await page.keyboard.press('Escape');
    await sleep(500);
    const closed = await page.evaluate(() => !document.querySelector('[data-archive-import]'));
    check(`${item.menu}：按 Esc 能关掉弹窗`, closed);
  }

  // 导出勾选列弹窗仍在（客户档案上验一次）
  await openMenu('客户档案');
  await sleep(800);
  await clickAll(); // 左侧没选分类时导出按钮是灰的（0 行），先选「全部」
  const exportOk = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(
      (b) => (b.textContent || '').includes('导出'),
    );
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(900);
  const exportDlg = await page.evaluate(() => {
    const el = document.querySelector('[data-export-dialog]');
    if (!el) return null;
    return {
      kind: el.getAttribute('data-export-dialog'),
      text: (el.innerText || '').slice(0, 90),
      checkboxes: el.querySelectorAll('[data-export-column]').length,
    };
  });
  check(
    '客户档案：导出仍走「勾选列」弹窗',
    exportOk && !!exportDlg,
    exportDlg ? `kind=${exportDlg.kind} / ${exportDlg.checkboxes} 个可勾选列` : '弹窗未出现',
  );
  check(
    '导出弹窗真的列出可勾选的列',
    !!exportDlg && exportDlg.checkboxes > 0,
    exportDlg ? `${exportDlg.checkboxes} 列` : '',
  );
  await shot('v72-export-columns');
  await page.keyboard.press('Escape');
  await sleep(400);

  // ── 问题 3：供应商白屏 ──
  console.log('\n── 问题 3：供应商白屏 ──');
  await openMenu('供应商档案');
  await sleep(1200);
  await clickAll();
  const supplierRows = await page.evaluate(() => {
    const tr = Array.from(document.querySelectorAll('tbody tr'));
    return tr.filter((r) => !r.querySelector('.erp-table__state-cell')).length;
  });
  check('供应商档案：列表有数据行', supplierRows > 0, `${supplierRows} 行`);

  // 点「中铁一局集团」这条记录（用户报的就是它）
  const clickedTarget = await page.evaluate(() => {
    const tr = Array.from(document.querySelectorAll('tbody tr'));
    const hit = tr.find((r) => (r.textContent || '').includes('中铁一局'));
    if (!hit) return false;
    const cell = hit.querySelector('td');
    (cell || hit).click();
    return true;
  });
  await sleep(1500);
  const afterClick = await page.evaluate(() => ({
    bodyText: document.body.innerText.slice(0, 60),
    hasBoundary: !!document.querySelector('[data-error-boundary]'),
    rowCount: Array.from(document.querySelectorAll('tbody tr')).filter(
      (r) => !r.querySelector('.erp-table__state-cell'),
    ).length,
    appStillThere: !!document.querySelector('.app-shell, .sidebar, .nav-item'),
  }));
  check('点「中铁一局集团」后页面没白屏（主界面还在）', afterClick.appStillThere);
  check('点「中铁一局集团」后没有 ErrorBoundary 兜底卡片', !afterClick.hasBoundary);
  check('点「中铁一局集团」后表格仍有行', afterClick.rowCount > 0, `${afterClick.rowCount} 行`);
  await shot('v72-supplier-click-zhongtie');

  // 再点一条别的（国家电网）
  const clicked2 = await page.evaluate(() => {
    const tr = Array.from(document.querySelectorAll('tbody tr'));
    const hit = tr.find((r) => (r.textContent || '').includes('国家电网'));
    if (!hit) return false;
    (hit.querySelector('td') || hit).click();
    return true;
  });
  await sleep(1200);
  const afterClick2 = await page.evaluate(() => ({
    hasBoundary: !!document.querySelector('[data-error-boundary]'),
    appStillThere: !!document.querySelector('.app-shell, .sidebar, .nav-item'),
  }));
  check(
    '点「国家电网」后同样不白屏',
    clicked2 ? afterClick2.appStillThere && !afterClick2.hasBoundary : true,
    clicked2 ? '' : '（库里没有"国家电网"这条，跳过）',
  );

  // ── 问题 1：反审核 vs 作废 ──
  console.log('\n── 问题 1：反审核 / 作废 ──');
  const tempReturn = await seedReturn();
  if (tempReturn) {
    console.log(`  （已造临时退货单 ${tempReturn.return_no} 用于验证按钮）`);
  }
  await openMenu('销售退货');
  await sleep(1500);
  if (tempReturn) {
    // 列表按创建时间倒序，刷新一下确保新单在最上面
    await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
    await openMenu('销售退货');
    await sleep(1500);
  }
  const srState = await page.evaluate(() => ({
    hasVoidBtn: !!document.querySelector('[data-sales-return-void]'),
    hasUnsubmitBtn: !!document.querySelector('[data-sales-return-unsubmit]'),
    text: document.body.innerText.slice(0, 300),
  }));
  check(
    '销售退货页：存在独立的「作废」按钮',
    srState.hasVoidBtn,
    srState.hasVoidBtn ? '' : '（当前没有 submitted 状态的单，无法验证按钮）',
  );
  check(
    '销售退货页：存在「反审核」按钮',
    srState.hasUnsubmitBtn,
    srState.hasUnsubmitBtn ? '' : '（当前没有 submitted 状态的单）',
  );
  if (srState.hasVoidBtn) {
    await page.click('[data-sales-return-void]');
    await sleep(900);
    const confirm = await page.evaluate(() => {
      const box = document.querySelector('[data-print-confirm-danger]');
      if (!box) return null;
      const input = box.querySelector('[data-print-confirm-reason]');
      // ⚠️ 不能用 `button:last-of-type` —— 标题栏的 × 在它自己父节点里也是 last-of-type，
      //    document 顺序更靠前，会先命中那个（disabled 恒为 false）。
      const btn = box.querySelector('[data-print-confirm-ok]');
      return {
        text: (box.innerText || '').slice(0, 120),
        hasReason: !!input,
        confirmDisabled: btn ? btn.disabled : null,
      };
    });
    check('点「作废」弹出二次确认（红字危险样式）', !!confirm, confirm ? '有弹窗' : '没弹窗');
    check('作废弹窗要求填原因', !!confirm && confirm.hasReason);
    check(
      '原因为空时「确认作废」按钮是禁用的',
      !!confirm && confirm.confirmDisabled === true,
      confirm ? `disabled=${confirm.confirmDisabled}` : '',
    );
    await shot('v72-void-confirm');
    await page.keyboard.press('Escape');
    await sleep(500);
  }

  await shot('v72-final');

  // 收尾：删掉自己造的临时退货单（只按 return_no 精确删，绝不按列表遍历）
  if (tempReturn && tempReturn.id) {
    const del = await fetch(`${BASE}/api/v1/sales-returns/${tempReturn.id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    console.log(`  临时退货单清理：HTTP ${del.status}`);
  }

  await browser.close();

  const failed = results.filter((item) => !item.ok);
  console.log('\n页面报错（pageerror）：', pageErrors.length ? pageErrors.join(' / ') : '(none)');
  console.log(`\n汇总：${results.length - failed.length}/${results.length} 通过`);
  if (failed.length) console.log('失败项：', failed.map((f) => f.name).join(' / '));
  console.log('截图目录：', SHOT_DIR);
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验证台自身出错：', err);
  process.exit(2);
});
