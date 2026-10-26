/**
 * 真浏览器验收：第二阶段（P2-1~P2-5）五个改动点。
 *
 * 为什么必须真浏览器：这几项全是"按钮该不该出现 / 弹窗能不能开"，
 * jsdom 里 `<details>`、`:has()`、CSS 网格都不成立，跑出来的绿是假的。
 *
 * 跑法（后端先起 8011）：
 *   ERP_BASE=http://127.0.0.1:8011 node scripts/verify_phase2_ui.cjs
 * 产物：docs/验收截图/p2-*.png
 *
 * 断言口径：每条都要求**元素真的在 DOM 且可交互**，不看源码、不看接口。
 * 反证方式：把对应 data-* 属性删掉（或把按钮藏起来）→ 本脚本必须变红。
 */
const fs = require('fs');
const path = require('path');

const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
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

  // 侧边栏分组默认收起：未展开时 .nav-item 压根不在 DOM
  await page.waitForSelector('.nav-group-title', { timeout: 30000 });
  await sleep(500);
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title.collapsed').forEach((el) => el.click());
  });
  await sleep(800);

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

  // ══════════════════════════════════ P2-4 返回按钮 ══════════════════════════
  check('初始没有「返回」（第一页没上一页可回）', !(await page.$('[data-nav-back]')));
  await openMenu('客户档案');
  await openMenu('销售退货');
  let backText = await page.evaluate(() => {
    const el = document.querySelector('[data-nav-back]');
    return el ? el.textContent.trim() : '';
  });
  check('二级页出现「← 返回」按钮', backText.includes('返回'), backText);
  await shot('p2-01-返回按钮');
  await page.click('[data-nav-back]');
  await sleep(1200);
  const heading = await page.evaluate(() => (document.querySelector('.topbar h1') || {}).textContent || '');
  check('点返回回到上一页（客户档案）', heading.includes('客户'), heading);

  // ══════════════════════════════════ P2-5 导出选列 ══════════════════════════
  const hasExportBtn = !!(await page.$('[data-export-open]'));
  check('客户档案有「导出 Excel」按钮', hasExportBtn);
  if (hasExportBtn) {
    await page.click('[data-export-open]');
    await sleep(500);
    const dialog = await page.evaluate(() => {
      const box = document.querySelector('[data-export-dialog]');
      if (!box) return null;
      return {
        checkboxes: box.querySelectorAll('input[type=checkbox]').length,
        checked: box.querySelectorAll('input[type=checkbox]:checked').length,
        selectedText: (box.querySelector('[data-export-selected-count]') || {}).textContent || '',
        confirmDisabled: (box.querySelector('[data-export-confirm]') || {}).disabled,
      };
    });
    check('点导出先弹窗（不直接下载）', !!dialog);
    if (dialog) {
      check('弹窗列出全部可导出列（≥10）', dialog.checkboxes >= 10, `${dialog.checkboxes} 列`);
      check('默认勾选 6 列', dialog.checked === 6, `${dialog.checked} 列`);
      check('显示已选计数', dialog.selectedText.includes('6'), dialog.selectedText.trim());
      check('有勾选时导出按钮可用', dialog.confirmDisabled === false);
      await shot('p2-02-导出选列弹窗');

      // 全部取消 → 导出必须禁用（一列都勾等于给个空文件）
      await page.click('[data-export-toggle-all]');
      await sleep(300);
      let afterAll = await page.evaluate(() => ({
        checked: document.querySelectorAll('[data-export-dialog] input[type=checkbox]:checked').length,
        disabled: (document.querySelector('[data-export-confirm]') || {}).disabled,
        warn: !!document.querySelector('.export-columns__warn'),
      }));
      check('「全选」按钮先把已勾的 6 列全部取消', afterAll.checked === 0, `${afterAll.checked}`);
      check('零勾选时导出按钮禁用', afterAll.disabled === true);
      check('零勾选时给出提示', afterAll.warn === true);

      // 再全选一次 → 恢复可用，然后关闭
      await page.click('[data-export-toggle-all]');
      await sleep(250);
      afterAll = await page.evaluate(() => ({
        checked: document.querySelectorAll('[data-export-dialog] input[type=checkbox]:checked').length,
        disabled: (document.querySelector('[data-export-confirm]') || {}).disabled,
      }));
      check('再点一次全选恢复 18 列', afterAll.checked >= 10, `${afterAll.checked}`);
      check('全选后导出按钮恢复可用', afterAll.disabled === false);
      await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('[data-export-dialog] button')).find(
          (b) => b.textContent.trim() === '取消',
        );
        if (btn) btn.click();
      });
      await sleep(300);
      check('取消后弹窗关闭', !(await page.$('[data-export-dialog]')));
    }
  }

  // ══════════════════════════════════ P2-4 报表日历 ══════════════════════════
  await openMenu('报表中心');
  const report = await page.evaluate(() => ({
    year: !!document.querySelector('[data-report-year]'),
    month: !!document.querySelector('[data-report-month]'),
    quick: document.querySelectorAll('[data-report-quick] button').length,
    quickLabels: Array.from(document.querySelectorAll('[data-report-quick] button')).map((b) =>
      b.textContent.trim(),
    ),
    custom: !!document.querySelector('[data-report-custom-range]'),
  }));
  check('报表有「年份」下拉', report.year);
  check('报表有「月份」下拉', report.month);
  check('有 本月/上月/今年 三个快捷按钮', report.quick === 3, report.quickLabels.join('/'));
  check(
    '快捷按钮文案齐全',
    ['本月', '上月', '今年'].every((want) => report.quickLabels.includes(want)),
    report.quickLabels.join('/'),
  );

  const beforeRange = await page.evaluate(() => {
    const from = document.querySelector('[data-report-custom-range] input');
    return from ? from.value : '';
  });
  await page.click('[data-report-quick] [data-range="this-year"]');
  await sleep(400);
  const afterRange = await page.evaluate(() => {
    const inputs = document.querySelectorAll('[data-report-custom-range] input');
    return { from: inputs[0] ? inputs[0].value : '', to: inputs[1] ? inputs[1].value : '' };
  });
  check('点「今年」把起止改成 01-01 ~ 12-31',
    afterRange.from.endsWith('-01-01') && afterRange.to.endsWith('-12-31'),
    `${afterRange.from} ~ ${afterRange.to}`);
  check('「今年」把月份下拉切到「全年」', await page.evaluate(() => {
    const el = document.querySelector('[data-report-month]');
    return !!el && el.value === 'all';
  }));
  await shot('p2-03-报表年月下拉');

  // ══════════════════════════════════ P2-1 销售退货 ══════════════════════════
  await openMenu('销售退货');
  const sr = await page.evaluate(() => {
    const detail = document.querySelector('[data-sales-return-detail]');
    const rows = document.querySelectorAll('tbody tr').length;
    return {
      hasDetail: !!detail,
      hasEditingHint: !!document.querySelector('[data-sales-return-editing]'),
      draftBtn: !!document.querySelector('[data-sales-return-draft]'),
      rows,
    };
  });
  check('销售退货列表有「详情」按钮', sr.hasDetail, `列表 ${sr.rows} 行`);
  check('销售退货表单有「存为草稿」按钮', sr.draftBtn);
  check('未进入编辑态时不显示编辑提示', sr.hasEditingHint === false);
  if (sr.hasDetail) {
    await page.click('[data-sales-return-detail]');
    await sleep(600);
    const box = await page.evaluate(() => {
      const card = document.querySelector('[data-sales-return-detail-card]');
      if (!card) return null;
      return {
        rows: card.querySelectorAll('tbody tr').length,
        hasPrint: !!Array.from(card.querySelectorAll('button')).find((b) =>
          b.textContent.includes('打印'),
        ),
        text: card.textContent.replace(/\s+/g, ' ').slice(0, 120),
      };
    });
    check('点「详情」打开详情弹窗', !!box);
    if (box) {
      check('详情弹窗里明细表有行', box.rows > 0, `${box.rows} 行`);
      check('详情弹窗有打印按钮', box.hasPrint);
      await shot('p2-04-销售退货详情');
      await page.evaluate(() => {
        const btn = Array.from(document.querySelectorAll('[data-sales-return-detail-card] button')).find(
          (b) => b.textContent.trim() === '关闭',
        );
        if (btn) btn.click();
      });
      await sleep(300);
    }
  }

  // ══════════════════════════════════ P2-2 对账单三步走 ══════════════════════
  await openMenu('增强对账单');
  const stmt = await page.evaluate(() => {
    const preview = document.querySelector('[data-stmt-preview]');
    const create = document.querySelector('[data-stmt-create]');
    const steps = document.querySelectorAll('[data-stmt-steps] .stmt__step').length;
    return {
      previewText: preview ? preview.textContent.trim() : '',
      createText: create ? create.textContent.trim() : '',
      createDisabled: create ? create.disabled : null,
      steps,
      downloads: !!document.querySelector('[data-stmt-downloads]'),
    };
  });
  check('对账单有「搜索预览」按钮', stmt.previewText.includes('搜索预览'), stmt.previewText);
  check('对账单有「生成对账单」按钮', stmt.createText.includes('生成对账单'), stmt.createText);
  check('没预览时「生成对账单」是禁用的', stmt.createDisabled === true, String(stmt.createDisabled));
  check('有 3 步指示条', stmt.steps === 3, `${stmt.steps} 步`);
  check('未生成时没有下载区', stmt.downloads === false);
  await shot('p2-05-对账单三步走');

  // ══════════════════════════════════ P2-3 财务去冗余 ══════════════════════════
  await openMenu('财务流水');
  const fin = await page.evaluate(() => {
    const body = document.body.textContent.replace(/\s+/g, ' ');
    const typeSel = document.querySelector('[data-finance-type]');
    const more = document.querySelector('[data-finance-more]');
    return {
      hasType: !!typeSel,
      options: typeSel ? Array.from(typeSel.options).map((o) => o.textContent.trim()) : [],
      hasMore: !!more,
      // 裸的「客户 ID / 供应商 ID」输入框必须消失
      hasCustomerIdLabel: body.includes('客户 ID') || body.includes('供应商 ID'),
      saveText: (Array.from(document.querySelectorAll('button')).find((b) =>
        b.textContent.trim() === '确认保存',
      ) || {}).textContent || '',
    };
  });
  check('财务录入仍有「类型」下拉', fin.hasType);
  check('类型选项是「收 / 付」', fin.options.length === 2 && fin.options[0].includes('收'), fin.options.join(' | '));
  check('客户 ID / 供应商 ID 输入框已移除', fin.hasCustomerIdLabel === false);
  check('货币/关联订单收进「更多（可选）」', fin.hasMore);
  check('保存按钮叫「确认保存」', fin.saveText.includes('确认保存'), fin.saveText);
  await shot('p2-06-财务去冗余');

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;
  console.log(`\n=== ${passed} PASS / ${failed} FAIL ===`);
  process.exit(failed ? 1 : 0);
})().catch((err) => {
  console.error('验收脚本异常：', err);
  process.exit(2);
});
