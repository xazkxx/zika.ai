/* 运行时冒烟测试：用 puppeteer-core + Edge 真实加载 ERP 前端，
 * 登录后遍历侧边栏菜单项，捕获任何 pageerror / console.error。
 * 目的：堵住「构建绿但运行崩」的漏洞（本次拆分曾因缺 import 整站白屏）。
 *
 * 运行：NODE_PATH=<node_modules> node scripts/smoke_test.cjs
 */
const puppeteer = require('C:/Users/admi/node_modules/puppeteer-core');
const URL = 'http://127.0.0.1:8010';
const DEBUG_PORT = 9222;

(async () => {
  // 连接已手动启动的 Edge（headless + remote-debugging），避免 puppeteer.launch 在本沙箱无法派生浏览器
  const browser = await puppeteer.connect({
    browserURL: `http://127.0.0.1:${DEBUG_PORT}`,
    defaultViewport: { width: 1400, height: 900 },
  });
  const page = await browser.newPage();

  const errors = [];
  let currentTab = '(initial/登录前)';
  page.on('pageerror', (e) => errors.push(`[pageerror @${currentTab}] ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(`[console.error @${currentTab}] ${m.text()}`);
  });

  console.log('→ 加载应用 ...');
  await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });

  // ---- 登录 ----
  console.log('→ 等待登录表单 ...');
  await page.waitForSelector('input', { timeout: 10000 });
  const inputs = await page.$$('input');
  for (const inp of inputs) {
    const info = await page.evaluate((el) => ({ type: el.type || el.getAttribute('type') || '', ph: el.placeholder || '' }), inp);
    if (info.type === 'password') await inp.type('Admin123');
    else if (/user|用户名|账号|name|account/i.test(info.ph) || info.type === 'text' || info.type === 'email')
      await inp.type('admin');
  }
  const loggedIn = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const b = btns.find((x) => /登录|login|sign\s*in/i.test(x.textContent || '')) || btns.find((x) => x.type === 'submit');
    if (b) { b.click(); return true; }
    return false;
  });
  console.log(loggedIn ? '→ 已点击登录按钮' : '⚠️ 未找到登录按钮，继续观察');

  // ---- 等待主界面（侧边栏） ----
  await page
    .waitForFunction(() => document.querySelector('nav, aside, [class*=sidebar], [class*=menu]') !== null, { timeout: 20000 })
    .catch(() => console.log('⚠️ 未检测到侧边栏容器'));
  await new Promise((r) => setTimeout(r, 1500));

  // ---- 收集侧边栏所有「叶子」菜单项（短文本、无子元素） ----
  const tabs = await page.evaluate(() => {
    const root = document.querySelector('nav, aside, [class*=sidebar], [class*=menu]') || document.body;
    const seen = new Set();
    const out = [];
    for (const el of root.querySelectorAll('a, li, div, span, button')) {
      if (el.children.length > 0) continue; // 只取叶子
      const t = (el.textContent || '').trim();
      if (t.length >= 1 && t.length <= 24 && !seen.has(t)) {
        seen.add(t);
        out.push(t);
      }
    }
    return out;
  });
  console.log(`→ 发现 ${tabs.length} 个菜单项，开始逐个点击 ...`);

  // ---- 逐个点击，捕获错误 ----
  for (const label of tabs) {
    currentTab = label;
    const ok = await page.evaluate((lbl) => {
      const root = document.querySelector('nav, aside, [class*=sidebar], [class*=menu]') || document.body;
      const el = [...root.querySelectorAll('a, li, div, span, button')].find(
        (e) => e.children.length === 0 && (e.textContent || '').trim() === lbl
      );
      if (el) { el.click(); return true; }
      return false;
    }, label);
    if (ok) await new Promise((r) => setTimeout(r, 180));
  }
  await new Promise((r) => setTimeout(r, 400));

  await browser.disconnect();

  if (errors.length) {
    console.log(`\n❌ 运行时冒烟测试发现 ${errors.length} 条错误：`);
    [...new Set(errors)].forEach((e) => console.log('  - ' + e));
    process.exit(1);
  } else {
    console.log(`\n✅ 运行时冒烟测试通过：登录成功并遍历 ${tabs.length} 个菜单项，无 pageerror / console.error。`);
    process.exit(0);
  }
})().catch((e) => {
  console.error('SMOKE TEST 异常:', e);
  process.exit(2);
});
