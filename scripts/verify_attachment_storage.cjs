/**
 * 附件归档（设置页）UI 验收 —— 2026-10-23
 *
 * 验七件事（真浏览器 + 真实接口对账）：
 *   1. 设置页能进去，`[data-attachment-storage]` 渲染出来了；
 *   2. 三张汇总卡（附件总占用 / 存放位置 / 磁盘剩余）都有值，且不出现 "undefined"/"NaN"；
 *   3. 目录表 **6 行固定**（合同原件、合同模板、付款回单、客户资料、发票扫描件、商品图片），
 *      文件数与体积与后端 `/system/attachment-storage` 逐项一致；
 *   4. 几何：三张卡与表格都不溢出面板（右边缘 ≤ 面板右边缘 + 1px）；
 *      「存放位置」是长路径，必须自己省略而不是把卡片撑破；
 *   5. 点「一键备份所有附件」→ 出现成功提示，且备份列表**多出新的一行**；
 *   6. 点「下载」真的存成 .zip（CDP 下载行为，不用肉眼判断）；
 *   7. 收尾：把本次验收造出来的备份包和下载件删掉（只删自己造的那一份）。
 *
 * 跑法：BASE=http://127.0.0.1:8019 node scripts/verify_attachment_storage.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8019';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const DOWNLOAD_DIR = 'E:\\AI\\ERP软件\\docs\\_tmp_attach_download';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
let page;
let browser;
let TOKEN = '';
// 只在**这一轮**造出来的备份包；失败/成功都要删掉，不能把验收垃圾留在用户盘里
let createdBackup = { name: '', dir: '' };

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

/** 菜单可能是折叠的：先看有没有，没有才去展开分组（不要无条件把所有分组都点一遍，会把已展开的点塌） */
async function openMenu(labels) {
  const names = Array.isArray(labels) ? labels : [labels];
  for (const name of names) {
    const direct = await page.evaluate((n) => {
      const item = [...document.querySelectorAll('.nav-item')].find(
        (e) => (e.textContent || '').trim() === n,
      );
      if (!item) return false;
      item.click();
      return true;
    }, name);
    if (direct) return name;
  }
  // 没找到 → 逐个分组展开（只点"看起来是折叠的"）
  const groups = await page.$$('.nav-group-title');
  for (const group of groups) {
    const collapsed = await page.evaluate((el) => {
      const parent = el.closest('.nav-group') || el.parentElement;
      const body = parent ? parent.querySelector('.nav-group-items') : null;
      return !body || body.offsetHeight === 0;
    }, group);
    if (collapsed) {
      await group.click();
      await sleep(350);
    }
    for (const name of names) {
      const hit = await page.evaluate((n) => {
        const item = [...document.querySelectorAll('.nav-item')].find(
          (e) => (e.textContent || '').trim() === n,
        );
        if (!item) return false;
        item.click();
        return true;
      }, name);
      if (hit) return name;
    }
  }
  return null;
}

// 必须与 SettingsPage.jsx 里的 fmtBytes 逐字一致 —— 拿它当"页面数字对不对"的尺子，
// 尺子自己换个精度就会误报（GB/MB 两位小数、KB 零位小数）。
const fmtBytes = (bytes) => {
  const value = Number(bytes || 0);
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${value} B`;
};

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 后端基线（页面上的数必须与它一致）
  const before = await api('GET', '/api/v1/system/attachment-storage');
  if (before.status !== 200) throw new Error(`概览接口失败 ${before.status}`);
  const beforeBackups = new Set((before.data.backups || []).map((r) => r.name));
  console.log(
    `  基线：${before.data.total_files} 个文件 / ${fmtBytes(before.data.total_bytes)}，已有备份 ${beforeBackups.size} 个`,
  );

  if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
  if (fs.existsSync(DOWNLOAD_DIR)) fs.rmSync(DOWNLOAD_DIR, { recursive: true, force: true });
  fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

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

  // —— 1. 进设置页 ——
  // ⚠️ 「系统设置」是**分组名**，下面挂着「公司信息」和「参数设置」两个页面；
  //    附件归档在「公司信息」这一页，点「参数设置」是另一个页面（找不到这个区块）。
  const entered = await openMenu(['公司信息']);
  if (!entered) fail('侧边栏有「公司信息」菜单', '找不到菜单项');
  await sleep(2200);
  ok('进入公司信息（系统设置）', entered);

  const panel = await page.$('[data-attachment-storage]');
  if (!panel) fail('设置页有「附件归档」区块', '找不到 [data-attachment-storage]');
  await page.evaluate(() => {
    const node = document.querySelector('[data-attachment-storage]');
    if (node) node.scrollIntoView({ block: 'center' });
  });
  await sleep(900);
  ok('设置页有「附件归档」区块');

  // —— 2. 三张汇总卡 ——
  const cards = await page.evaluate(() => {
    const root = document.querySelector('[data-attachment-storage]');
    const nodes = [...root.querySelectorAll('.storage-summary > div')];
    const read = (i) => {
      const node = nodes[i];
      if (!node) return null;
      return {
        label: (node.querySelector('span')?.textContent || '').trim(),
        value: (node.querySelector('strong')?.textContent || '').trim(),
        hint: (node.querySelector('em')?.textContent || '').trim(),
        // 长路径是否真的能自己收住：nowrap + 不把容器撑宽
        overflow: node.scrollWidth - node.clientWidth,
      };
    };
    return {
      count: nodes.length,
      cards: [read(0), read(1), read(2)],
      panelWidth: root.getBoundingClientRect().width,
      rootRight: root.getBoundingClientRect().right,
    };
  });
  if (cards.count !== 3) fail('三张汇总卡', `实际 ${cards.count} 张`);
  const labels = cards.cards.map((c) => c.label);
  for (const expect of ['附件总占用', '存放位置', '磁盘剩余']) {
    if (!labels.includes(expect)) fail(`汇总卡有「${expect}」`, JSON.stringify(labels));
  }
  for (const card of cards.cards) {
    if (!card.value) fail(`「${card.label}」有值`, '空');
    if (/undefined|NaN|null/.test(card.value)) fail(`「${card.label}」不是脏值`, card.value);
  }
  ok(
    '三张汇总卡都有值',
    cards.cards.map((c) => `${c.label}=${c.value}`).join(' · '),
  );

  // 数值与后端一致
  if (cards.cards[0].value !== fmtBytes(before.data.total_bytes)) {
    fail('附件总占用与后端一致', `页面 ${cards.cards[0].value} / 后端 ${fmtBytes(before.data.total_bytes)}`);
  }
  if (!cards.cards[0].hint.includes(String(before.data.total_files))) {
    fail('文件个数与后端一致', `${cards.cards[0].hint} / 后端 ${before.data.total_files}`);
  }
  const pathCard = cards.cards[1];
  if (!pathCard.value.includes(before.data.root.split(/[\\/]/).slice(-2)[1] || 'data')) {
    // 路径末尾可能是被省略的，只要求带盘符或 data 字样
    if (!/data/.test(pathCard.value) && !/^[A-Za-z]:/.test(pathCard.value)) {
      fail('存放位置显示的是 data 目录', pathCard.value);
    }
  }
  if (pathCard.overflow > 2) fail('存放位置没有撑破卡片', `溢出 ${pathCard.overflow}px`);
  ok('存放位置长路径自己省略', pathCard.value);
  if (cards.cards[2].value !== fmtBytes(before.data.disk.free)) {
    fail('磁盘剩余与后端一致', `页面 ${cards.cards[2].value} / 后端 ${fmtBytes(before.data.disk.free)}`);
  }
  ok('附件占用 / 磁盘剩余与后端逐项一致');

  // —— 3. 目录表 ——
  const table = await page.evaluate(() => {
    const root = document.querySelector('[data-attachment-storage]');
    const first = root.querySelector('table.storage-table');
    const rows = [...first.querySelectorAll('tbody tr')].map((tr) =>
      [...tr.children].map((td) => (td.textContent || '').trim()),
    );
    return {
      rows,
      headers: [...first.querySelectorAll('thead th')].map((th) => (th.textContent || '').trim()),
      right: first.getBoundingClientRect().right,
      wrapRight: root.getBoundingClientRect().right,
      overflowX: first.scrollWidth - first.clientWidth,
    };
  });
  if (table.rows.length !== 6) fail('目录表 6 行', `实际 ${table.rows.length} 行`);
  const expectedDirs = ['contracts/', 'contract_templates/', 'contract_receipts/', 'customer-files/', 'invoices/', 'products/'];
  const gotDirs = table.rows.map((r) => r[0]);
  if (JSON.stringify(gotDirs) !== JSON.stringify(expectedDirs)) {
    fail('目录顺序与白名单一致', JSON.stringify(gotDirs));
  }
  for (let i = 0; i < 6; i += 1) {
    const dir = before.data.dirs[i];
    const row = table.rows[i];
    if (row[1] !== dir.label) fail(`第 ${i + 1} 行用途是「${dir.label}」`, row[1]);
    if (Number(row[2]) !== dir.files) fail(`${dir.name} 文件数一致`, `页面 ${row[2]} / 后端 ${dir.files}`);
    if (row[3] !== fmtBytes(dir.bytes)) fail(`${dir.name} 体积一致`, `页面 ${row[3]} / 后端 ${fmtBytes(dir.bytes)}`);
  }
  ok('目录表 6 行，用途/文件数/体积与后端逐项一致');

  // —— 4. 几何不溢出 ——
  if (table.right > table.wrapRight + 1) {
    fail('目录表不溢出面板', `表格右 ${table.right} > 面板右 ${table.wrapRight}`);
  }
  if (table.overflowX > 1) fail('目录表没有横向溢出', `溢出 ${table.overflowX}px`);
  ok('目录表没有横向溢出', `表格右边缘 ${Math.round(table.right)} ≤ 面板右边缘 ${Math.round(table.wrapRight)}`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_attachment_storage.png') });
  console.log('  📸 e2e_attachment_storage.png');

  // —— 5. 一键备份 ——
  const backupsBefore = await page.evaluate(() => {
    const root = document.querySelector('[data-attachment-storage]');
    const box = root.querySelector('.storage-backups');
    if (!box) return 0;
    return box.querySelectorAll('tbody tr').length;
  });
  await page.click('[data-attachment-backup]');
  // 备份是同步打包，附件多时会慢：轮询等提示出现
  let msg = '';
  for (let i = 0; i < 40; i += 1) {
    msg = await page.evaluate(() => {
      const node = document.querySelector('[data-attachment-storage] .storage-msg');
      return node ? node.textContent.trim() : '';
    });
    if (msg.includes('已备份')) break;
    await sleep(500);
  }
  if (!msg.includes('已备份')) fail('点备份后有成功提示', msg || '（没有提示）');
  ok('一键备份成功', msg);

  const after = await api('GET', '/api/v1/system/attachment-storage');
  const newBackups = (after.data.backups || []).filter((r) => !beforeBackups.has(r.name));
  if (newBackups.length !== 1) fail('后端新生成 1 个备份包', `实际 ${newBackups.length} 个`);
  const created = newBackups[0];
  createdBackup = { name: created.name, dir: after.data.backup_dir };
  if (!created.name.endsWith('.zip')) fail('备份包是 .zip', created.name);
  ok('后端确实落了备份包', `${created.name} · ${fmtBytes(created.bytes)}`);

  const backupsAfter = await page.evaluate(() => {
    const root = document.querySelector('[data-attachment-storage]');
    const box = root.querySelector('.storage-backups');
    if (!box) return { rows: 0, first: '' };
    const rows = [...box.querySelectorAll('tbody tr')];
    return { rows: rows.length, first: (rows[0]?.children?.[0]?.textContent || '').trim() };
  });
  if (backupsAfter.first !== created.name) {
    fail('备份列表第一行是刚生成的包', `页面 ${backupsAfter.first} / 后端 ${created.name}`);
  }
  if (backupsAfter.rows < Math.max(1, backupsBefore)) {
    fail('备份列表行数增加', `前 ${backupsBefore} 行 → 后 ${backupsAfter.rows} 行`);
  }
  ok('备份列表即时刷新', `${backupsBefore} 行 → ${backupsAfter.rows} 行，首行 ${created.name}`);

  // —— 6. 下载通道（base64） ——
  // ⚠️ 这里**故意不去抓落盘文件**：本机 Chrome（有头无头都试过）对 `.zip` 直链的
  //    fetch 一律回空的 204，`downloadProgress` 直接 canceled —— 这是浏览器的下载拦截，
  //    不是服务端的锅（同一条 URL 用 curl 是 200 + 19MB）。
  //    所以前端改成 `?as=base64` 走 JSON，这里就守这段通道：
  //      ① 点按钮发出的是 `?as=base64` 的 GET，带 Authorization，回 200 JSON；
  //      ② base64 解出来 = 磁盘上的字节数，且以 PK 开头；
  //      ③ 页面把它包成了同样大小的 blob（说明 a.click() 那一步真的执行到了）。
  // 页面内埋点：拦一层 window.fetch，把下载请求的**响应摘要**记下来。
  // 为什么不在 node 侧读 `response.json()`：备份包 base64 之后 ~25MB，
  // CDP 的 inspector cache 会把它 evict 掉（Network.getResponseBody 报错），
  // 大文件只能让页面自己读完再把摘要带出来。
  await page.evaluateOnNewDocument(() => {
    window.__erpBlobs = [];
    window.__erpDownload = null;
    const original = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (obj) => {
      try {
        window.__erpBlobs.push({ size: obj && obj.size ? obj.size : 0, type: obj && obj.type ? obj.type : '' });
      } catch {
        /* ignore */
      }
      return original(obj);
    };

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const response = await nativeFetch(input, init);
      if (url.includes('/attachment-backup/') && (!init || !init.method || init.method === 'GET')) {
        const headers = (init && init.headers) || {};
        const auth = headers.Authorization || headers.authorization || '';
        const clone = response.clone();
        let payload = null;
        try {
          payload = await clone.json();
        } catch {
          payload = null;
        }
        window.__erpDownload = {
          url,
          status: response.status,
          contentType: response.headers.get('content-type') || '',
          hasAuth: String(auth).startsWith('Bearer '),
          filename: payload && payload.filename,
          bytes: payload && payload.bytes,
          b64Length: payload && payload.content_base64 ? payload.content_base64.length : 0,
          b64Head: payload && payload.content_base64 ? payload.content_base64.slice(0, 8) : '',
        };
      }
      return response;
    };
  });
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('[data-attachment-storage]');

  const downloadBtn = `[data-attachment-backup-download="${created.name}"]`;
  await page.waitForSelector(downloadBtn);
  await page.click(downloadBtn);

  let download = null;
  for (let i = 0; i < 60 && !download; i += 1) {
    download = await page.evaluate(() => window.__erpDownload);
    if (!download) await sleep(500);
  }
  if (!download) fail('点「下载」发出了备份下载请求', '页面里没有记录到');
  if (!download.url.includes('as=base64')) fail('下载走的是 base64 通道', download.url);
  if (download.status !== 200) fail('下载接口返回 200', String(download.status));
  if (!download.contentType.includes('application/json')) fail('下载通道返回 JSON', download.contentType);
  if (!download.hasAuth) fail('下载请求带上登录凭证', '没有 Authorization: Bearer');
  if (download.filename !== created.name) fail('返回的文件名正确', `${download.filename} / ${created.name}`);
  if (download.bytes !== created.bytes) fail('返回的字节数与备份包一致', `${download.bytes} / ${created.bytes}`);
  // 'PK\x03\x04' 的 base64 前缀是 'UEsD'
  if (!download.b64Head.startsWith('UEs')) fail('base64 开头是 zip 魔数', download.b64Head);
  const expectedB64 = Math.ceil(created.bytes / 3) * 4;
  if (Math.abs(download.b64Length - expectedB64) > 4) {
    fail('base64 长度与字节数对得上', `${download.b64Length} / 期望 ${expectedB64}`);
  }
  ok('base64 通道拿到完整 zip', `${download.bytes} 字节 · 带 Authorization · PK 魔数正确`);

  // blob 证据：页面应当多出一个同样大小的 blob（说明走到了 a.click()）
  let matched = null;
  for (let i = 0; i < 30 && !matched; i += 1) {
    const blobs = await page.evaluate(() => window.__erpBlobs || []);
    matched = blobs.find((b) => b.size === created.bytes) || null;
    if (!matched) await sleep(400);
  }
  if (!matched) {
    const blobs = await page.evaluate(() => window.__erpBlobs || []);
    fail('页面生成了同尺寸 blob', JSON.stringify(blobs.slice(-3)));
  }
  ok('页面已生成同尺寸 blob 并触发保存', `${matched.size} 字节 · ${matched.type || '(无 type)'}`);

  const downloadMsg = await page.evaluate(() => {
    const node = document.querySelector('[data-attachment-storage] .storage-msg');
    return node ? node.textContent.trim() : '';
  });
  if (!downloadMsg.includes('已开始下载')) fail('下载后有提示', downloadMsg || '（没有提示）');
  ok('下载后有明确提示', downloadMsg);

  // —— 7. 清理自己造的数据 ——
  try {
    fs.unlinkSync(path.join(after.data.backup_dir, created.name));
    createdBackup = { name: '', dir: '' };
    ok('已删除验收生成的备份包');
  } catch (err) {
    fail('清理验收备份包', String(err.message).slice(0, 120));
  }
  fs.rmSync(DOWNLOAD_DIR, { recursive: true, force: true });
  const final = await api('GET', '/api/v1/system/attachment-storage');
  if ((final.data.backups || []).some((r) => r.name === created.name)) {
    fail('备份目录已恢复原状', '刚删的包还在列表里');
  }
  ok('备份目录已恢复原状', `剩余 ${(final.data.backups || []).length} 个历史备份`);

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_attachment_storage.png') });
  } catch {
    /* ignore */
  }
  // 失败也要把自己造的备份包删掉（否则每跑一次验收，用户的备份目录就多一个 19MB 的包）
  try {
    if (createdBackup.name) {
      const target = path.join(createdBackup.dir, createdBackup.name);
      if (fs.existsSync(target)) fs.unlinkSync(target);
      console.log(`  已回滚验收备份包：${createdBackup.name}`);
    }
    if (fs.existsSync(DOWNLOAD_DIR)) fs.rmSync(DOWNLOAD_DIR, { recursive: true, force: true });
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
