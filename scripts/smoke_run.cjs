/* 自包含运行时冒烟测试（带网络/控制台全量诊断）。
 * 启动 Edge headless → connect → 加载 ERP → 登录 → 遍历菜单项 → 捕获错误。
 * 运行：NODE_PATH=<fe/node_modules> node scripts/smoke_run.cjs
 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');
const puppeteer = require('C:/Users/admi/node_modules/puppeteer-core');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
// 允许换端口跑（和 verify_*.cjs 保持同一套约定）：
//   BASE=http://127.0.0.1:8019 node scripts/smoke_run.cjs
// 默认仍是 8010（用户常驻实例），但调试/验收请用备用端口，别抢正在用的那个。
const PORT = Number(process.env.CDP_PORT || 9222);
const URL = process.env.BASE || 'http://127.0.0.1:8010';
const UD = 'C:/tmp/edge-smoke';
// 用全新 profile：既能验证登录流程，也能避免上次遗留的 token 导致直接跳过登录。
try { fs.rmSync(UD, { recursive: true, force: true }); } catch (_) {}

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => res(d)); }).on('error', rej);
  });
}
async function waitEdge(tries = 40) {
  for (let i = 0; i < tries; i++) {
    try { await get(`http://127.0.0.1:${PORT}/json/version`); return true; }
    catch (e) { await new Promise((r) => setTimeout(r, 500)); }
  }
  return false;
}

(async () => {
  const errors = [];
  const logs = [];
  let currentTab = '(登录前)';
  const child = spawn(
    EDGE,
    ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=' + PORT, '--user-data-dir=C:/tmp/edge-smoke', 'about:blank'],
    { stdio: 'ignore' }
  );
  let exitCode = 0;
  try {
    const ok = await waitEdge();
    if (!ok) throw new Error('Edge 未能启动');

    const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: { width: 1400, height: 900 } });
    const page = await browser.newPage();
    page.on('pageerror', (e) => errors.push(`[pageerror @${currentTab}] ${e.message}`));
    page.on('console', (m) => { logs.push(`[${m.type()}] ${m.text()}`); if (m.type() === 'error') errors.push(`[console.error @${currentTab}] ${m.text()}`); });
    page.on('requestfailed', (req) => errors.push(`[reqfail] ${req.url()} :: ${req.failure() && req.failure().errorText}`));
    page.on('response', (res) => { if (res.status() >= 400) errors.push(`[http ${res.status()}] ${res.url()}`); });

    console.log('→ 加载应用 ...');
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise((r) => setTimeout(r, 5000)); // 等 React 挂载 + 资源

    const snap = await page.evaluate(() => ({
      title: document.title,
      inp: document.querySelectorAll('input').length,
      btns: document.querySelectorAll('button').length,
      rootLen: (document.getElementById('root') ? document.getElementById('root').innerHTML.length : -1),
      rootHead: (document.getElementById('root') ? document.getElementById('root').innerHTML : 'NO #root').slice(0, 200),
      body: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 400),
    }));
    console.log('SNAP ' + JSON.stringify(snap));
    console.log('LOGS ' + JSON.stringify(logs.slice(0, 30)));

    // ---- 登录（若尚未登录；全新 profile 下应当走此分支）----
    const needLogin = await page.evaluate(() => {
      const root = document.getElementById('root');
      const txt = (root ? root.innerText : '') || '';
      return !/工作台|基础资料|采购管理|仪表盘|运营概览/.test(txt);
    });
    if (needLogin && snap.inp > 0) {
      // 受控 input：用原生 setter 赋值（避免浏览器 autofill 残留 + 追加输入导致值翻倍）
      const filled = await page.evaluate(() => {
        const setVal = (el, val) => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          setter.call(el, val);
          el.dispatchEvent(new Event('input', { bubbles: true }));
        };
        const inputs = [...document.querySelectorAll('input')];
        const pwd = inputs.find((el) => el.type === 'password');
        const acct = inputs.find((el) => el.type === 'text' || el.type === 'email');
        let n = 0;
        if (acct) { setVal(acct, 'admin'); n++; }
        if (pwd) { setVal(pwd, 'Admin123'); n++; }
        return n;
      });
      console.log(`→ 填入 ${filled} 个输入框，点击登录 ...`);
      const clicked = await page.evaluate(() => {
        const b = document.querySelector('.auth-submit') ||
          [...document.querySelectorAll('button')].find((x) => (x.textContent || '').trim() === '登录') ||
          document.querySelector('button[type="submit"]');
        if (b) { b.click(); return true; }
        return false;
      });
      console.log(clicked ? '→ 已点击登录按钮' : '⚠️ 未找到登录按钮');
      await page.waitForFunction(() => /工作台|基础资料|采购管理|仪表盘|运营概览/.test(document.getElementById('root') ? document.getElementById('root').innerText : ''), { timeout: 20000 })
        .then(() => console.log('→ 登录成功，已进入主界面'))
        .catch(() => console.log('⚠️ 登录后未检测到主界面'));
    } else {
      console.log('→ 已处于登录态，跳过登录');
    }
    await new Promise((r) => setTimeout(r, 1500));

    // ---- 遍历侧边栏菜单项 ----
    // 结构：nav.side-nav > div.nav-group > button.nav-group-title（分组，点击展开/折叠）
    // 展开后分组下才有子菜单项（a/li）。先展开全部分组，再收集并逐个点击。
    await page.evaluate(() => {
      for (const t of document.querySelectorAll('button.nav-group-title')) {
        try { t.click(); } catch (_) {}
      }
    });
    await new Promise((r) => setTimeout(r, 700));

    const tabs = await page.evaluate(() => {
      const nav = document.querySelector('nav.side-nav, aside.sidebar, nav, aside') || document.body;
      const seen = new Set();
      const out = [];
      // 菜单项：a 标签 / li / 有 item 类的元素 / 非分组标题的 button
      for (const el of nav.querySelectorAll('a, li, [class*=menu-item], [class*=nav-item]')) {
        const t = (el.textContent || '').trim();
        if (t && t.length <= 24 && !seen.has(t)) { seen.add(t); out.push(t); }
      }
      if (out.length === 0) {
        for (const el of nav.querySelectorAll('button')) {
          if (el.classList.contains('nav-group-title')) continue;
          const t = (el.textContent || '').trim();
          if (t && t.length <= 24 && t !== '退出登录' && !seen.has(t)) { seen.add(t); out.push(t); }
        }
      }
      return out;
    });
    console.log(`→ 发现 ${tabs.length} 个菜单项，开始逐个点击 ...`);

    const clickErrorsByTab = {};
    for (const label of tabs) {
      currentTab = label;
      const before = errors.length;
      const ok = await page.evaluate((lbl) => {
        const nav = document.querySelector('nav.side-nav, aside.sidebar, nav, aside') || document.body;
        const el = [...nav.querySelectorAll('a, li, [class*=menu-item], [class*=nav-item], button')]
          .find((e) => (e.textContent || '').trim() === lbl && !e.classList.contains('nav-group-title'));
        if (el) { el.click(); return true; }
        return false;
      }, label);
      if (ok) {
        await new Promise((r) => setTimeout(r, 260));
        const added = errors.length - before;
        if (added > 0) clickErrorsByTab[label] = added;
      }
    }
    await new Promise((r) => setTimeout(r, 400));
    console.log('TAB_ERRORS ' + JSON.stringify(clickErrorsByTab));

    await browser.disconnect();

    if (errors.length) {
      console.log(`\n❌ 运行时冒烟测试发现 ${errors.length} 条错误：`);
      [...new Set(errors)].forEach((e) => console.log('  - ' + e));
      exitCode = 1;
    } else {
      console.log(`\n✅ 运行时冒烟测试通过：登录并遍历 ${tabs.length} 个菜单项，无 pageerror / console.error。`);
    }
  } catch (e) {
    console.log('SMOKE 异常:', e.message);
    console.log('CAPTURED ERRORS:', JSON.stringify(errors, null, 2));
    exitCode = 2;
  } finally {
    try { child.kill('SIGKILL'); } catch (_) {}
  }
  process.exit(exitCode);
})();
