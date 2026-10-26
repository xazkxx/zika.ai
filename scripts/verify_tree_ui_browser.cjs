/**
 * 真浏览器验收：五页「左树 → 右表」联动。
 *
 * 为什么还要跑这个（jsdom 已经 17+16 项全绿）：
 *   jsdom 不算布局、不跑 CSS、也不走真实登录与菜单——而"手感"恰恰只在这些地方体现。
 *   这个脚本做三件事：真实登录 → 点菜单进页面 → 截图 + 断言 DOM。
 *
 * 跑法：node scripts/verify_tree_ui_browser.cjs
 * 产物：docs/验收截图/*.png（可直接发给同事看）
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
  console.log('登录成功，token 长度', token.length);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
    protocolTimeout: 120000,
  });
  const page = await browser.newPage();

  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2', timeout: 60000 });
  // 侧边栏真实结构（别再想当然写 .nav-item 就能等到）：
  //   div.nav-group > button.nav-group-title（默认 collapsed）+ div.nav-group-items > button.nav-item
  // 分组收起时 .nav-group-items 根本不在 DOM 里，所以 .nav-item 数量是 0，必须先展开分组。
  await page.waitForSelector('.nav-group-title', { timeout: 30000 });
  await sleep(600);

  const expandAllGroups = () =>
    page.evaluate(() => {
      const titles = Array.from(document.querySelectorAll('.nav-group-title.collapsed'));
      titles.forEach((el) => el.click());
      return titles.length;
    });

  const openMenu = async (label) => {
    for (let pass = 0; pass < 5; pass += 1) {
      const clicked = await page.evaluate((want) => {
        const item = Array.from(document.querySelectorAll('.nav-group-items .nav-item')).find(
          (el) => el.textContent.trim().indexOf(want) === 0,
        );
        if (!item) return false;
        item.click();
        return true;
      }, label);
      if (clicked) {
        await sleep(1000);
        return true;
      }
      const opened = await expandAllGroups();
      if (!opened) break;
      await sleep(400);
    }
    return false;
  };

  // 注意：ErpTable 的「空态/加载中」是一个占满整行的 <tr><td class="erp-table__state-cell">，
  // 直接数 tbody tr 会把空态算成 1 行数据 → 必须排掉，否则"空表"永远数成 1。
  const snapshot = () =>
    page.evaluate(() => {
      const body = document.body;
      const empty = document.querySelector('.erp-empty');
      const emptyText = empty ? empty.textContent.replace(/\s+/g, ' ').trim() : '';
      const rows = Array.from(document.querySelectorAll('tbody tr')).filter(
        (tr) => !tr.querySelector('.erp-table__state-cell'),
      ).length;
      const catNodes = document.querySelectorAll('.cat-node').length;
      const erpRows = document.querySelectorAll('.erp-tree__row').length;
      const stateCell = document.querySelector('.erp-table__state-cell');
      const stateText = stateCell ? stateCell.textContent.replace(/\s+/g, ' ').trim() : '';
      const title = (document.querySelector('.erp-card__title, .erp-card h3, .erp-card h2') || {}).textContent || '';
      return {
        emptyText,
        stateText,
        rows,
        catNodes,
        erpRows,
        title: title.trim(),
        hasPrompt: body.textContent.includes('请在左侧选择一个分类'),
      };
    });

  const shot = async (name) => {
    const file = path.join(SHOT_DIR, `${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    return file;
  };

  // ── 1) 客户档案 ──
  let ok = await openMenu('客户档案');
  check('菜单：客户档案可打开', ok);
  let s = await snapshot();
  check('客户页：初始右表为空', s.rows === 0, `tbody tr=${s.rows}`);
  check('客户页：显示「请在左侧选择一个分类」', s.hasPrompt, s.emptyText.slice(0, 40));
  check('客户页：左树只露一级（未展开）', s.catNodes <= 12, `可见节点=${s.catNodes}`);
  await shot('01-客户档案-初始空态');

  // 点「全部客户」→ 出数据
  await page.evaluate(() => {
    const row = Array.from(document.querySelectorAll('.ptree__row')).find((el) =>
      el.textContent.includes('全部客户'),
    );
    if (row) row.click();
  });
  await sleep(900);
  s = await snapshot();
  check('客户页：点「全部客户」后出数据', s.rows > 0, `tbody tr=${s.rows}`);
  await shot('02-客户档案-点了全部');

  // 搜索：只展开一条路径
  await page.type('[data-ptree-search="1"]', '华', { delay: 40 });
  await sleep(800);
  const searchState = await page.evaluate(() => ({
    hits: (document.querySelector('[data-ptree-hits="1"]') || {}).textContent || '',
    visibleRows: document.querySelectorAll('.ptree__row').length,
    marks: document.querySelectorAll('.ptree__mark').length,
  }));
  check(
    '客户页：搜索命中有统计且命中词高亮',
    searchState.hits.includes('找到') && searchState.marks > 0,
    searchState.hits.replace(/\s+/g, ' ').trim().slice(0, 30),
  );
  check('客户页：搜索结果只铺一条路径（行数 ≤ 8）', searchState.visibleRows <= 8, `可见行=${searchState.visibleRows}`);
  await shot('03-客户档案-搜索只展开一条路径');
  await page.keyboard.press('Escape');
  await sleep(300);

  // ── 2) 商品档案 ──
  ok = await openMenu('商品档案');
  check('菜单：商品档案可打开', ok);
  s = await snapshot();
  check('商品页：初始右表为空', s.rows === 0, `tbody tr=${s.rows}`);
  check('商品页：显示「请在左侧选择一个分类」', s.hasPrompt);
  await shot('04-商品档案-初始空态');

  await page.evaluate(() => {
    const row = Array.from(document.querySelectorAll('.cat-node')).find((el) =>
      el.textContent.includes('全部商品'),
    );
    if (row) row.click();
  });
  await sleep(900);
  s = await snapshot();
  check('商品页：点「全部商品」后出数据', s.rows > 0, `tbody tr=${s.rows}`);
  await shot('05-商品档案-点了全部');

  // ── 3) 仓库档案 ──
  ok = await openMenu('仓库档案');
  check('菜单：仓库档案可打开', ok);
  s = await snapshot();
  check('仓库页：初始右表为空', s.rows === 0, `tbody tr=${s.rows}`);
  check('仓库页：左树有「全部仓库」入口', s.erpRows >= 1, `树行=${s.erpRows}`);
  await shot('06-仓库档案-初始空态');

  await page.evaluate(() => {
    const row = Array.from(document.querySelectorAll('.erp-tree__row')).find((el) =>
      el.textContent.includes('全部仓库'),
    );
    if (row) row.click();
  });
  await sleep(700);
  s = await snapshot();
  check('仓库页：点「全部仓库」后出数据', s.rows > 0, `tbody tr=${s.rows}`);
  await shot('07-仓库档案-点了全部');

  // ── 4) 员工档案 ──
  ok = await openMenu('员工档案');
  check('菜单：员工档案可打开', ok);
  s = await snapshot();
  check('员工页：初始右表为空', s.rows === 0, `tbody tr=${s.rows}`);
  check('员工页：显示「请在左侧选择一个分类」', s.hasPrompt);
  await shot('08-员工档案-初始空态');

  await page.evaluate(() => {
    const row = Array.from(document.querySelectorAll('.erp-tree__row')).find((el) =>
      el.textContent.includes('全部员工'),
    );
    if (row) row.click();
  });
  await sleep(1200);
  s = await snapshot();
  // 这台机器的员工表就是空的（后端 /employees 返回 0 条），所以这里不能假设"一定出数据"。
  // 真正的判据是：点完之后提示语必须从"请在左侧选择一个分类"切走 —— 说明联动真的跑通了。
  check(
    '员工页：点「全部员工」后联动生效（出数据或转为「还没有员工」）',
    s.rows > 0 || (!s.hasPrompt && s.stateText.includes('还没有员工')),
    `tbody tr=${s.rows} 提示=${s.stateText.slice(0, 20)}`,
  );
  await shot('09-员工档案-点了全部');

  // ── 5) 供应商档案 ──
  ok = await openMenu('供应商档案');
  check('菜单：供应商档案可打开', ok);
  s = await snapshot();
  check('供应商页：初始右表为空', s.rows === 0, `tbody tr=${s.rows}`);
  await shot('10-供应商档案-初始空态');

  await browser.close();

  const failed = results.filter((item) => !item.ok);
  console.log(`\n汇总：${results.length - failed.length}/${results.length} 通过`);
  console.log('截图目录：', SHOT_DIR);
  process.exit(failed.length ? 1 : 0);
})().catch(async (err) => {
  console.error('验证台自身出错：', err);
  process.exit(2);
});
