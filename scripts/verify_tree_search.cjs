/**
 * 左侧树「全局模糊搜索」验收 —— 2026-10-23
 *
 * 验七件事（真浏览器 + 真数据）：
 *   1. 客户档案左树的搜索框，输入**联系人**「周广平」能命中挂在该分类下的客户；
 *   2. 命中客户的**父级分类链自动展开**，客户行露出来且黄底高亮（data-leaf-hit）；
 *   3. 没命中的分支整支隐藏（不留空壳文件夹）；
 *   4. 清空搜索（×）后回到**默认折叠**：客户行消失、树上只剩顶级分类；
 *   5. 供应商树同一套行为（搜供应商名）；
 *   6. 商品树的搜索框匹配**商品名** → 它所属分类露出来并高亮；
 *   7. 收尾把本轮造的分类/客户删干净。
 *
 * 跑法：BASE=http://127.0.0.1:8022 node scripts/verify_tree_search.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || process.env.ERP_BASE || 'http://127.0.0.1:8022';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const TAG = Date.now().toString().slice(-6);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
let page;
let browser;
let TOKEN = '';

const ok = (name, extra = '') => {
  results.push({ name, ok: true });
  console.log(`PASS  ${name}${extra ? `  — ${extra}` : ''}`);
};
const fail = (name, why) => {
  results.push({ name, ok: false, why });
  console.log(`FAIL  ${name}  — ${why}`);
  throw new Error(`${name}：${why}`);
};

async function api(method, url, body) {
  const res = await fetch(`${BASE}${url}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  return { status: res.status, data };
}

/** 菜单可能折叠：先直接找，找不到展开分组再找 */
async function openMenu(name) {
  const direct = await page.evaluate((n) => {
    const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
    if (!item) return false;
    item.click();
    return true;
  }, name);
  if (direct) {
    await sleep(1800);
    return true;
  }
  const groups = await page.$$('.nav-group-title');
  for (const group of groups) {
    await group.click();
    await sleep(250);
    const hit = await page.evaluate((n) => {
      const item = [...document.querySelectorAll('.nav-item')].find((e) => (e.textContent || '').trim() === n);
      if (!item) return false;
      item.click();
      return true;
    }, name);
    if (hit) {
      await sleep(1800);
      return true;
    }
  }
  return false;
}

/** 在搜索框里输入（受控 input，用原生 setter + input 事件最稳） */
async function typeSearch(selector, value) {
  await page.evaluate(
    (sel, text) => {
      const input = document.querySelector(sel);
      if (!input) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    },
    selector,
    value,
  );
  await sleep(700);
}

const readTree = () =>
  page.evaluate(() => {
    const rows = [...document.querySelectorAll('.ptree__row')].map((el) => ({
      label: (el.textContent || '').trim(),
      hit: el.classList.contains('is-hit'),
    }));
    const leaves = [...document.querySelectorAll('[data-partner-leaf]')].map((el) => ({
      name: (el.querySelector('.ptree__leaf-name')?.textContent || '').trim(),
      hit: el.getAttribute('data-leaf-hit') === '1',
      highlighted: el.classList.contains('is-hit'),
      contact: (el.querySelector('.ptree__leaf-meta')?.textContent || '').trim(),
    }));
    return { rows, leaves };
  });

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // —— 造数：父级分类 → 子级分类 → 客户（联系人周广平）；另造一个无关分支 ——
  const parent = await api('POST', '/api/v1/customer-categories', { name: `验收搜索父级${TAG}` });
  if (parent.status !== 201) throw new Error(`建父分类失败 ${JSON.stringify(parent.data)}`);
  const child = await api('POST', '/api/v1/customer-categories', {
    name: `验收搜索子级${TAG}`,
    parent_id: parent.data.id,
  });
  if (child.status !== 201) throw new Error(`建子分类失败 ${JSON.stringify(child.data)}`);
  const other = await api('POST', '/api/v1/customer-categories', { name: `验收无关分类${TAG}` });
  if (other.status !== 201) throw new Error(`建无关分类失败 ${JSON.stringify(other.data)}`);

  const target = await api('POST', '/api/v1/customers', {
    code: `CUS-SRCH${TAG}`,
    name: `验收搜索客户${TAG}`,
    contact: '周广平',
    category_id: child.data.id,
  });
  if (target.status !== 201) throw new Error(`建客户失败 ${JSON.stringify(target.data)}`);
  const noise = await api('POST', '/api/v1/customers', {
    code: `CUS-NOISE${TAG}`,
    name: `验收无关客户${TAG}`,
    contact: '李四',
    category_id: other.data.id,
  });
  if (noise.status !== 201) throw new Error(`建无关客户失败 ${JSON.stringify(noise.data)}`);
  console.log(`  造数完成：父级 #${parent.data.id} / 子级 #${child.data.id} / 无关 #${other.data.id}`);

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox'],
    defaultViewport: { width: 1920, height: 1000 },
    protocolTimeout: 180000,
  });
  page = await browser.newPage();
  page.on('pageerror', (err) => console.log('  [pageerror]', String(err).slice(0, 160)));
  await page.setCacheEnabled(false);
  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');

  // —— 1. 客户档案：搜联系人 ——
  if (!(await openMenu('客户档案'))) fail('打开「客户档案」', '找不到菜单');
  await page.waitForSelector('[data-ptree-search]', { timeout: 15000 });

  const before = await readTree();
  if (before.leaves.some((leaf) => leaf.name.includes(`验收搜索客户${TAG}`))) {
    fail('搜索前客户叶子不显示（分类是折叠的）', JSON.stringify(before.leaves.slice(0, 3)));
  }
  ok('初始状态：树是折叠的，客户行不显示', `${before.rows.length} 个分类行`);

  await typeSearch('[data-ptree-search]', '周广平');
  await sleep(600);
  const hitState = await readTree();
  const hitLeaf = hitState.leaves.find((leaf) => leaf.name.includes(`验收搜索客户${TAG}`));
  if (!hitLeaf) {
    fail('按联系人「周广平」能搜到客户', JSON.stringify(hitState.leaves.slice(0, 5)));
  }
  if (!hitLeaf.highlighted) fail('命中的客户行是黄底高亮', JSON.stringify(hitLeaf));
  ok('搜「周广平」命中客户并高亮', `${hitLeaf.name} · 联系人 ${hitLeaf.contact || '（无）'}`);

  const labels = hitState.rows.map((row) => row.label).join(' | ');
  if (!labels.includes(`验收搜索父级${TAG}`) || !labels.includes(`验收搜索子级${TAG}`)) {
    fail('父级链路自动展开', labels.slice(0, 200));
  }
  if (labels.includes(`验收无关分类${TAG}`)) {
    fail('没命中的分类被隐藏（不留空壳）', labels.slice(0, 200));
  }
  ok('父级链路自动展开，无关分支已隐藏', `${hitState.rows.length} 个分类行可见`);

  const hitsBar = await page.evaluate(() => {
    const node = document.querySelector('[data-ptree-hits]');
    return node ? (node.textContent || '').trim() : '';
  });
  if (!hitsBar.includes('找到')) fail('命中条显示数量', hitsBar || '（没有命中条）');
  ok('命中条有统计', hitsBar.slice(0, 60));

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_tree_search_hit.png') });
  console.log('  📸 e2e_tree_search_hit.png');

  // —— 2. 清空 → 回到默认折叠 ——
  await page.click('.ptree__search-clear');
  await sleep(800);
  const afterClear = await readTree();
  if (afterClear.leaves.some((leaf) => leaf.name.includes(`验收搜索客户${TAG}`))) {
    fail('清空后客户行消失（回到折叠）', JSON.stringify(afterClear.leaves.slice(0, 3)));
  }
  const stillOpen = afterClear.rows.filter((row) => row.label.includes(`验收搜索子级${TAG}`));
  if (stillOpen.length) fail('清空后子树也收回（只剩顶级）', JSON.stringify(stillOpen));
  ok('清空搜索 → 恢复默认折叠', `${afterClear.rows.length} 个分类行，无客户行`);

  // —— 3. 供应商树 ——
  if (!(await openMenu('供应商档案'))) fail('打开「供应商档案」', '找不到菜单');
  await page.waitForSelector('[data-ptree-search]', { timeout: 15000 });
  await typeSearch('[data-ptree-search]', '河北万方');
  await sleep(700);
  const supState = await readTree();
  const supLeaf = supState.leaves.find((leaf) => leaf.name.includes('万方'));
  if (!supLeaf) fail('供应商树也能搜到具体供应商', JSON.stringify(supState.leaves.slice(0, 5)));
  if (!supLeaf.highlighted) fail('供应商命中行高亮', JSON.stringify(supLeaf));
  ok('供应商树同一套搜索生效', supLeaf.name);
  await page.click('.ptree__search-clear');
  await sleep(600);

  // —— 4. 商品树：搜商品名 → 分类露出来 ——
  if (!(await openMenu('商品档案'))) fail('打开「商品档案」', '找不到菜单');
  await page.waitForSelector('[data-cat-search]', { timeout: 15000 });
  const productName = await page.evaluate(() => {
    const input = document.querySelector('[data-cat-search]');
    return input ? input.getAttribute('placeholder') : '';
  });
  if (!productName) fail('商品树有搜索框', '找不到 [data-cat-search]');

  await typeSearch('[data-cat-search]', '帆布手套');
  await sleep(800);
  const catState = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('.cat-node')].map((el) => ({
      name: (el.querySelector('.cat-name')?.textContent || '').trim(),
      hit: el.classList.contains('is-hit'),
      hasProductHit: Boolean(el.querySelector('.cat-hit-note')),
    }));
    return {
      nodes,
      hits: (document.querySelector('[data-cat-hits]')?.textContent || '').trim(),
      empty: Boolean(document.querySelector('[data-cat-empty]')),
    };
  });
  if (catState.empty) fail('商品名能匹配到分类', '显示"没有匹配"');
  const hitCat = catState.nodes.find((node) => node.hit && node.hasProductHit);
  if (!hitCat) fail('命中分类带"商品命中"标记', JSON.stringify(catState.nodes.slice(0, 6)));
  ok('商品树搜商品名 → 分类高亮', `${hitCat.name} · ${catState.hits.slice(0, 40)}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_tree_search_product.png') });

  await page.click('[data-cat-search-clear]');
  await sleep(700);
  const catCleared = await page.evaluate(() => ({
    hits: Boolean(document.querySelector('[data-cat-hits]')),
    hitNodes: document.querySelectorAll('.cat-node.is-hit').length,
  }));
  if (catCleared.hits || catCleared.hitNodes) {
    fail('商品树清空后回到常态', JSON.stringify(catCleared));
  }
  ok('商品树清空后高亮与命中条都撤掉');

  // —— 5. 收尾 ——
  await api('DELETE', `/api/v1/customers/${target.data.id}`);
  await api('DELETE', `/api/v1/customers/${noise.data.id}`);
  for (const cat of [child.data.id, other.data.id, parent.data.id]) {
    await api('DELETE', `/api/v1/customer-categories/${cat}`);
  }
  const remain = await api('GET', '/api/v1/customer-categories');
  const flat = JSON.stringify(remain.data || []);
  if (flat.includes(`验收搜索`)) fail('验收分类已删除', '残留');
  ok('验收数据已清理干净');

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_tree_search.png') });
  } catch {
    /* ignore */
  }
  try {
    if (browser) await browser.close();
  } catch {
    /* ignore */
  }
  process.exit(1);
});
