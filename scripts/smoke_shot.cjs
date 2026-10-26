/* 登录流程截图：登录页 → 登录后主界面。用于给用户可视化确认登录可用。 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const puppeteer = require('C:/Users/admi/node_modules/puppeteer-core');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const PORT = 9222;
const URL = 'http://127.0.0.1:8010';
const UD = 'C:/tmp/edge-shot';
const OUT = 'D:/ERP软件/_smoke_shots';
try { fs.rmSync(UD, { recursive: true, force: true }); } catch (_) {}
fs.mkdirSync(OUT, { recursive: true });

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
  const child = spawn(EDGE, ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=' + PORT, '--user-data-dir=' + UD, 'about:blank'], { stdio: 'ignore' });
  try {
    if (!(await waitEdge())) throw new Error('Edge 未能启动');
    const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: { width: 1400, height: 900 } });
    const page = await browser.newPage();
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise((r) => setTimeout(r, 2500));
    await page.screenshot({ path: OUT + '/login.png' });

    // 受控 input：用原生 setter 赋值（避免浏览器 autofill 残留 + 追加输入导致值翻倍）
    await page.evaluate(() => {
      const setVal = (el, val) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const inputs = [...document.querySelectorAll('input')];
      const pwd = inputs.find((el) => el.type === 'password');
      const acct = inputs.find((el) => el.type === 'text' || el.type === 'email');
      if (acct) setVal(acct, 'admin');
      if (pwd) setVal(pwd, 'Admin123');
    });
    await page.evaluate(() => {
      const b = document.querySelector('.auth-submit') || [...document.querySelectorAll('button')].find((x) => (x.textContent || '').trim() === '登录' || x.type === 'submit');
      if (b) b.click();
    });
    await page.waitForFunction(() => /工作台|基础资料|采购管理|仪表盘/.test(document.getElementById('root') ? document.getElementById('root').innerText : ''), { timeout: 20000 });
    await new Promise((r) => setTimeout(r, 2500));
    await page.screenshot({ path: OUT + '/dashboard.png' });
    await browser.disconnect();
    console.log('OK ' + OUT);
  } catch (e) {
    console.log('SHOT_ERR ' + e.message);
  } finally {
    try { child.kill('SIGKILL'); } catch (_) {}
  }
})();
