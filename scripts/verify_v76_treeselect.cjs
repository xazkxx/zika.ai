/**
 * verify_v76_treeselect.cjs —— ErpTreeSelect 真浏览器验收（客户档案）
 *
 * 为什么要真浏览器：jsdom 不算 CSS、测不到 portal 定位、也测不到
 * mousedown 与 label 转发点击的相互作用。这个组件的手感全在这些地方。
 *
 * 跑法：
 *   node scripts/verify_v76_treeselect.cjs
 * 前置：
 *   后端在 8011（临时验证端口）、前端已 build 到 dist（8011 托管 dist）
 *
 * 断言覆盖用户提的四条要求：
 *   ① 默认折叠：打开时只出现第一级节点
 *   ② 逐层展开：点父级只展开一层，不摊平；父级不选中
 *   ③ 搜索：输入关键字自动展开命中链路，只留命中及其祖先
 *   ④ 回显：选中末级后输入框显示完整路径
 */

const fs = require('fs');
const path = require('path');

/* 依赖装了在 WorkBuddy 的托管 workspace 里（不污染项目 node_modules），
   与 verify_v75_ui.cjs 等既有脚本保持同一写法 */
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = [
  'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const SHOT_DIR = path.resolve(__dirname, '../docs/验收截图');

let pass = 0;
let fail = 0;
const failures = [];

function check(name, ok, detail) {
  if (ok) {
    pass += 1;
    console.log(`  ✅ ${name}`);
  } else {
    fail += 1;
    failures.push(name + (detail ? ` —— ${detail}` : ''));
    console.log(`  ❌ ${name}${detail ? ` —— ${detail}` : ''}`);
  }
}

(async () => {
  if (!CHROME) {
    console.error('找不到 chrome.exe');
    process.exit(1);
  }
  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();

  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(String(err && err.message ? err.message : err)));

  // ⚠️ 必须先导航到同源页面，about:blank 上 localStorage 会被拒（SecurityError）
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle2' });

  // 登录拿 token，写进 localStorage（前端约定 erp_token）
  const token = await page.evaluate(async (base) => {
    const res = await fetch(`${base}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
    });
    const data = await res.json();
    return data.access_token || '';
  }, BASE);
  if (!token) {
    console.error('登录失败，拿不到 token');
    process.exit(1);
  }
  await page.evaluate((t) => localStorage.setItem('erp_token', t), token);
  await page.reload({ waitUntil: 'networkidle2' });

  // 打开客户档案菜单（侧边栏分组默认收起 → 先点「基础资料」组标题）
  // ⚠️ 未展开时 .nav-item 根本不在 DOM 里（MEMORY §2）
  const groupClicked = await page.evaluate(() => {
    const titles = [...document.querySelectorAll('.nav-group-title')];
    const target = titles.find((t) => /基础资料/.test(t.textContent || ''));
    if (!target) return false;
    target.click();
    return true;
  });
  check('能展开「基础资料」菜单组', groupClicked);
  await new Promise((r) => setTimeout(r, 600));

  const opened = await page.evaluate(() => {
    const items = [...document.querySelectorAll('.nav-item')];
    const target = items.find((el) => /客户档案/.test(el.textContent || ''));
    if (target) {
      target.click();
      return true;
    }
    return false;
  });
  check('能打开「客户档案」页面', opened);

  // 等列表真有行。⚠️ 档案列表左侧分类树未选中时列表是空态（提示"点左侧全部"），
  //    这是**设计不是 bug**（MEMORY §2）→ 必须先点「全部客户」
  await new Promise((r) => setTimeout(r, 900));
  const pickedAll = await page.evaluate(() => {
    const body = document.querySelector('.ptree__body');
    if (!body) return false;
    const leaf = [...body.querySelectorAll('*')].find(
      (el) => el.children.length === 0 && /^全部客户$/.test((el.textContent || '').trim()),
    );
    if (!leaf) return false;
    // 点它可点的祖先行（文本节点本身可能不绑事件）
    let target = leaf;
    for (let i = 0; i < 4 && target; i += 1) {
      if (target.getAttribute && (target.getAttribute('role') === 'button' || target.tagName === 'BUTTON' || target.className?.includes?.('ptree'))) break;
      target = target.parentElement;
    }
    (target || leaf).click();
    return true;
  });
  check('能点「全部客户」展开列表', pickedAll);
  await new Promise((r) => setTimeout(r, 1000));

  const hasRows = await page
    .waitForSelector('tr.erp-table__row', { timeout: 8000 })
    .then(() => true)
    .catch(() => false);
  check('客户列表渲染出行', hasRows);

  // 点「新增客户」打开弹窗
  const openModal = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const target = btns.find((b) => /新增客户|新增/.test(b.textContent || ''));
    if (target) {
      target.click();
      return target.textContent.trim();
    }
    return '';
  });
  await new Promise((r) => setTimeout(r, 700));
  check('能打开新增客户弹窗', Boolean(openModal), openModal);

  // 找到树形下拉触发器
  const triggerSel = '[data-erp-tree-select="partner-customer-category"] .tsel-trigger';
  const hasTrigger = await page
    .waitForSelector(triggerSel, { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  check('「所属分类」渲染成 ErpTreeSelect（不是旧平铺下拉）', hasTrigger);

  if (!hasTrigger) {
    await browser.close();
    console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
    process.exit(1);
  }

  // —— ① 默认折叠：打开只显示第一级 ——
  await page.click(triggerSel);
  await new Promise((r) => setTimeout(r, 350));

  const level1 = await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    if (!panel) return null;
    const rows = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')];
    return {
      total: rows.length,
      branches: rows.filter((r) => r.dataset.tselLeaf === '0').length,
      leaves: rows.filter((r) => r.dataset.tselLeaf === '1').length,
      labels: rows.map((r) => r.querySelector('.tsel-row__label')?.textContent || ''),
      hasSearch: Boolean(panel.querySelector('[data-tsel-search]')),
    };
  });
  check('面板能打开', Boolean(level1));
  check('默认只显示第一级（3 个顶级，无子节点）', level1 && level1.total === 3 && level1.leaves === 0, JSON.stringify(level1?.labels));
  check('面板内有搜索框', level1 && level1.hasSearch);

  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_树形下拉_默认折叠.png') });

  // —— ② 逐层展开：点「国家电网公司」只展开一层 ——
  const expandOnce = await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    const row = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')].find(
      (r) => /国家电网公司/.test(r.textContent || ''),
    );
    if (!row) return null;
    row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    return true;
  });
  await new Promise((r) => setTimeout(r, 300));

  const afterExpand = await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    const rows = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')];
    return {
      total: rows.length,
      labels: rows.map((r) => (r.querySelector('.tsel-row__label')?.textContent || '').trim()),
      // 第二级以下是否出现（即是否被"摊平"了）
      deepVisible: rows.some((r) => /施工一部|谭涛总|机具分公司/.test(r.textContent || '')),
      // 父级是否被误选中
      triggeredText: document.querySelector('[data-erp-tree-select="partner-customer-category"] .tsel-trigger__text')?.textContent || '',
    };
  });
  check('点父级只展开下一层（4 → 有子节点出现，但不是整棵摊平）', afterExpand.total > 3 && !afterExpand.deepVisible, JSON.stringify(afterExpand.labels));
  check('点父级不会选中（输入框仍是占位文案）', !/国家电网/.test(afterExpand.triggeredText), afterExpand.triggeredText);

  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_树形下拉_逐层展开.png') });

  // 二次展开到深层：国家电网 → 陕西送变电 → 施工一部。
  // ⚠️ 必须**逐级等** —— 上一级没展开时下一级根本不在 DOM 里，
  //    一次性循环两遍会点空（第一次跑就是这么假红的）。
  const clickBranchByLabel = async (pattern, waitMs = 350) => {
    const ok = await page.evaluate((src) => {
      const re = new RegExp(src);
      const panel = document.querySelector('[data-erp-tree-select-panel]');
      if (!panel) return false;
      const row = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')].find(
        (r) => r.dataset.tselLeaf === '0' && re.test(r.querySelector('.tsel-row__label')?.textContent || ''),
      );
      if (!row) return false;
      row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      return true;
    }, pattern.source);
    await new Promise((r) => setTimeout(r, waitMs));
    return ok;
  };

  const step1 = await clickBranchByLabel(/^陕西送变电工程公司$/);
  const step2 = await clickBranchByLabel(/^施工一部$/);
  const step3 = await clickBranchByLabel(/^谭涛总$/);

  const deepNow = await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    if (!panel) return [];
    // 带上缩进深度：paddingLeft = 10 + depth*18
    return [...panel.querySelectorAll('.tsel-row[data-tsel-key]')].map((r) => ({
      label: (r.querySelector('.tsel-row__label')?.textContent || '').trim(),
      depth: Math.round((parseInt(r.style.paddingLeft, 10) - 10) / 18),
      leaf: r.dataset.tselLeaf === '1',
    }));
  });
  const labels = deepNow.map((r) => r.label);
  const maxDepth = deepNow.reduce((m, r) => Math.max(m, r.depth), 0);

  check(
    '逐层点父级可深入到第 4 级（陕西送变电 → 施工一部 → 谭涛总）',
    step1 && step2 && step3 && labels.includes('谭涛总'),
    `${step1}/${step2}/${step3} :: ${JSON.stringify(labels)}`,
  );
  /* "没摊平"的正确判据：点开第 4 级「谭涛总」后，它自己的子级（第 5 级：王宪全/陈银贵）
     应该出现，但**不能**超过第 5 级 —— 第 6 级如果也自动出来了，就是"全摊开"。

     ⚠️ 这条断言反证时差点假绿：把组件改成"永久全展开"后，maxDepth 仍然是 4，
        因为树本身最深就到第 4 级。也就是说**只看深度证明不了折叠**。
        真正有区分度的判据是上面那条"默认只显示第一级"（行数 3 vs 15）。
        这里保留深度断言作为补充，但不再把它当主证据。 */
  check(
    '逐层展开只往下加一层（最深到第 5 级，没有超过实际树深）',
    maxDepth <= 4 && labels.includes('王宪全经理'),
    `maxDepth=${maxDepth} json=${JSON.stringify(deepNow.map((r) => `${r.depth}:${r.label}`))}`,
  );
  check(
    '第 5 级是叶子，没有被当成父级继续展开',
    deepNow.filter((r) => r.depth === 4).every((r) => r.leaf),
    JSON.stringify(deepNow.filter((r) => r.depth === 4)),
  );

  // —— ③ 搜索：输入「王宪全」应自动展开到第 6 级链路 ——
  await page.evaluate(() => {
    const input = document.querySelector('[data-erp-tree-select-panel] [data-tsel-search]');
    if (input) {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, '王宪全');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await new Promise((r) => setTimeout(r, 400));

  const searched = await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    const rows = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')];
    return {
      labels: rows.map((r) => (r.querySelector('.tsel-row__label')?.textContent || '').trim()),
      hasHit: rows.some((r) => /王宪全/.test(r.textContent || '')),
    };
  });
  check('搜索命中深层节点（王宪全经理，第 6 级）', searched.hasHit, JSON.stringify(searched.labels));
  check(
    '搜索自动展开祖先链路（国家电网→陕西送变电→施工一部→谭涛总 都在）',
    ['国家电网公司', '陕西送变电工程公司', '施工一部', '谭涛总'].every((l) => searched.labels.includes(l)),
    JSON.stringify(searched.labels),
  );
  check(
    '搜索会剪掉无关分支（不再出现「中铁一局集团」）',
    !searched.labels.some((l) => /中铁一局/.test(l)),
    JSON.stringify(searched.labels),
  );

  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_树形下拉_搜索.png') });

  // —— ④ 选中末级 → 回显完整路径 ——
  await page.evaluate(() => {
    const panel = document.querySelector('[data-erp-tree-select-panel]');
    const row = [...panel.querySelectorAll('.tsel-row[data-tsel-key]')].find(
      (r) => /王宪全/.test(r.textContent || '') && r.dataset.tselLeaf === '1',
    );
    if (row) row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 400));

  const echoed = await page.evaluate(() => {
    const el = document.querySelector('[data-erp-tree-select="partner-customer-category"] .tsel-trigger__text');
    const panelStillOpen = Boolean(document.querySelector('[data-erp-tree-select-panel]'));
    return { text: (el?.textContent || '').trim(), panelStillOpen };
  });
  check(
    '选中末级后输入框回显完整路径',
    /国家电网公司 \/ 陕西送变电工程公司 \/ 施工一部 \/ 谭涛总 \/ 王宪全经理/.test(echoed.text),
    echoed.text,
  );
  check('选中后面板自动关闭', echoed.panelStillOpen === false);

  await page.screenshot({ path: path.join(SHOT_DIR, 'v76_树形下拉_回显路径.png') });

  // 全程零 pageerror
  check('全程零 pageerror', pageErrors.length === 0, pageErrors.join(' | '));

  await browser.close();

  console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
  if (fail) {
    console.log('失败项：');
    failures.forEach((f) => console.log('  - ' + f));
    process.exit(1);
  }
})().catch((err) => {
  console.error('脚本异常', err);
  process.exit(1);
});
