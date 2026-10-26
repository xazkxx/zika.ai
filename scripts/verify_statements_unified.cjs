/**
 * 真浏览器验收：需求 3「财务对账单三入口归一」。
 *
 * 验的是四件事（都是用户在屏幕上能直接看到的）：
 *   1. 点「采购对账单」→ 落到对账单页、范围自动锁在「应付」
 *   2. 「销售对账单」菜单**已下架**（moved 2026-10-20：与增强对账单重叠，只留后者）
 *   3. 点「增强对账单」→ 落在「全部」，看到的是台账（能点开）
 *   4. 打开一张单 → 明细下方出现「往来账底稿（期初 → 逐笔 → 期末）」六张卡 + 流水表
 *
 * 跑法（后端必须先起好，8010 是生产实例；临时验证用 8011）：
 *   ERP_BASE=http://127.0.0.1:8011 node scripts/verify_statements_unified.cjs
 * 产物：docs/验收截图/11~15-*.png
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
  page.on('pageerror', (err) => console.log('  [页面报错]', String(err).slice(0, 160)));

  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
  // 侧边栏分组默认收起：.nav-group-items 不在 DOM 里，得先展开
  await page.waitForSelector('.nav-group-title', { timeout: 30000 });
  await sleep(500);
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title.collapsed').forEach((el) => el.click());
  });
  await sleep(600);

  const openMenu = async (label) => {
    const ok = await page.evaluate((want) => {
      const item = Array.from(document.querySelectorAll('.nav-group-items .nav-item')).find(
        (el) => el.textContent.trim().indexOf(want) === 0,
      );
      if (!item) return false;
      item.click();
      return true;
    }, label);
    if (ok) await sleep(1100);
    return ok;
  };

  const shot = async (name) => {
    await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`), fullPage: false });
  };

  /** 当前激活的范围 Tab / 单头标题 / 台账行数 / 预览卡 */
  const snapshot = () =>
    page.evaluate(() => {
      const activeTab = document.querySelector('.stmt__seg-btn.is-active');
      const scopeTitle = document.querySelector('[data-scope-title]');
      const noEl = document.querySelector('[data-statement-no]');
      const ledgerRows = Array.from(document.querySelectorAll('tbody tr')).filter(
        (tr) => !tr.querySelector('.erp-table__state-cell'),
      );
      const previewCards = document.querySelectorAll('[data-preview]');
      return {
        activeScope: activeTab ? activeTab.textContent.trim() : '',
        scopeTitle: scopeTitle ? scopeTitle.textContent.trim() : '',
        statementNo: noEl ? noEl.textContent.trim() : '',
        dataRows: ledgerRows.length,
        previewCards: previewCards.length,
        hasGenerate: !!Array.from(document.querySelectorAll('button')).find(
          (b) => b.textContent.trim() === '生成草稿',
        ),
        hasLedgerHint: !!document.querySelector('[data-scope-hint]'),
        diffReason: (document.querySelector('[data-diff-reason]') || {}).textContent || '',
        bodyText: document.body.textContent.replace(/\s+/g, ' '),
      };
    });

  // ── 1) 采购对账单 → 应付 ──
  let ok = await openMenu('采购对账单');
  check('菜单：采购对账单可打开', ok);
  let s = await snapshot();
  check('采购入口：范围锁在「应付」', s.activeScope === '应付', `激活=${s.activeScope}`);
  check('采购入口：标题显示应付对账单', s.scopeTitle.includes('应付'), s.scopeTitle);
  check('采购入口：有「生成草稿」入口（说明在编辑器，不是台账）', s.hasGenerate);
  await shot('11-采购对账单-应付');

  // ── 2) 全部 → 台账 ──
  await page.evaluate(() => {
    const btn = document.querySelector('.stmt__seg-btn[data-scope="all"]');
    if (btn) btn.click();
  });
  await sleep(900);
  s = await snapshot();
  check('切「全部」：显示台账说明', s.hasLedgerHint);
  check('切「全部」：台账里有对账单行', s.dataRows >= 1, `行数=${s.dataRows}`);
  check('切「全部」：没有「生成草稿」（全部模式不生成）', !s.hasGenerate);
  await shot('12-增强对账单-全部台账');

  // ── 3) 点台账第一行 → 打开单据 + 底稿预览 ──
  await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tbody tr')).filter(
      (tr) => !tr.querySelector('.erp-table__state-cell'),
    );
    if (rows[0]) rows[0].click();
  });
  await sleep(1600);
  s = await snapshot();
  check('台账点行：真的打开了单据', s.statementNo !== '' && s.statementNo !== '未生成', `单号=${s.statementNo}`);
  check('打开单据后：内嵌往来账预览六卡齐全', s.previewCards === 6, `卡数=${s.previewCards}`);
  check(
    '预览带差额口径说明',
    s.diffReason.includes('口径'),
    s.diffReason.slice(0, 28),
  );
  await shot('13-对账单详情-底稿预览');

  // ── 4) 销售对账单菜单已下架（2026-10-20 菜单瘦身）──
  // 「销售对账单」和「增强对账单」功能重叠，只保留后者。
  // 这里验的是"菜单真的不在侧边栏了"——不是简单地"点了没反应"，
  // 因为点了没反应和菜单不存在在 UI 上分不出来，必须查 DOM。
  const hasSalesStatement = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('.nav-item'));
    return items.some((el) => (el.textContent || '').includes('销售对账单'));
  });
  check('菜单：销售对账单已下架（侧边栏找不到）', !hasSalesStatement);
  const stillHasEnhanced = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll('.nav-item'));
    return items.some((el) => (el.textContent || '').includes('增强对账单'));
  });
  check('菜单：增强对账单仍在', stillHasEnhanced);

  // ── 5) 增强对账单 → 全部 ──
  ok = await openMenu('增强对账单');
  check('菜单：增强对账单可打开', ok);
  s = await snapshot();
  check('增强入口：范围落在「全部」', s.activeScope === '全部', `激活=${s.activeScope}`);
  check('增强入口：直接看到台账', s.hasLedgerHint && s.dataRows >= 1, `行数=${s.dataRows}`);
  await shot('15-增强对账单-默认全部');

  await browser.close();

  const failed = results.filter((item) => !item.ok);
  console.log(`\n汇总：${results.length - failed.length}/${results.length} 通过`);
  console.log('截图目录：', SHOT_DIR);
  process.exit(failed.length ? 1 : 0);
})().catch((err) => {
  console.error('验证台自身出错：', err);
  process.exit(2);
});
