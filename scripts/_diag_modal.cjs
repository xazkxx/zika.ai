/* 临时诊断：登录 → 打开一个弹窗 → 量弹窗与遮罩的实际位置（验证是否居中）。 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const puppeteer = require('C:/Users/admi/node_modules/puppeteer-core');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const PORT = 9222;
const URL = 'http://127.0.0.1:8010';
const UD = 'C:/tmp/edge-diag';
try { fs.rmSync(UD, { recursive: true, force: true }); } catch (_) {}

function get(u) { return new Promise((res, rej) => { http.get(u, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => res(d)); }).on('error', rej); }); }
async function waitEdge(t = 40) { for (let i = 0; i < t; i++) { try { await get(`http://127.0.0.1:${PORT}/json/version`); return true; } catch (e) { await new Promise((r) => setTimeout(r, 500)); } } return false; }

(async () => {
  const child = spawn(EDGE, ['--headless=new', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=' + PORT, '--user-data-dir=' + UD, 'about:blank'], { stdio: 'ignore' });
  try {
    await waitEdge();
    const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: { width: 1440, height: 900 } });
    const page = await browser.newPage();
    page.on('pageerror', (e) => console.log('[pageerror] ' + e.message));
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise((r) => setTimeout(r, 4000));
    await page.evaluate(() => {
      const setVal = (el, val) => {
        const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        s.call(el, val); el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const ins = [...document.querySelectorAll('input')];
      const pwd = ins.find((e) => e.type === 'password');
      const acct = ins.find((e) => e.type === 'text' || e.type === 'email');
      if (acct) setVal(acct, 'admin');
      if (pwd) setVal(pwd, 'Admin123');
      const b = document.querySelector('.auth-submit') || [...document.querySelectorAll('button')].find((x) => (x.textContent || '').trim() === '登录');
      if (b) b.click();
    });
    await new Promise((r) => setTimeout(r, 4000));

    // 展开全部分组 → 点「客户档案」
    await page.evaluate(() => { for (const t of document.querySelectorAll('button.nav-group-title')) { try { t.click(); } catch (_) {} } });
    await new Promise((r) => setTimeout(r, 600));
    const navOK = await page.evaluate(() => {
      const nav = document.querySelector('nav.side-nav, aside.sidebar, nav, aside') || document.body;
      const el = [...nav.querySelectorAll('a, li, [class*=menu-item], [class*=nav-item], button')].find((e) => (e.textContent || '').trim() === '客户档案');
      if (el) { el.click(); return true; } return false;
    });
    console.log('点击客户档案:', navOK);
    await new Promise((r) => setTimeout(r, 1500));

    const opened = await page.evaluate(() => {
      const b = [...document.querySelectorAll('button')].find((x) => (x.textContent || '').trim() === '新增客户');
      if (b) { b.click(); return true; } return false;
    });
    console.log('点开新增客户弹窗:', opened);
    await new Promise((r) => setTimeout(r, 900));

    const info = await page.evaluate(() => {
      const bd = document.querySelector('.modal-backdrop, .modal-overlay');
      const card = document.querySelector('.modal-card');
      if (!bd || !card) return { found: false, bd: !!bd, card: !!card };
      const r1 = bd.getBoundingClientRect();
      const r2 = card.getBoundingClientRect();
      const cs = getComputedStyle(bd);
      // 找出是否有祖先建立了 containing block（transform/filter/backdrop-filter/will-change/contain）
      const culprits = [];
      let p = bd.parentElement;
      while (p && p !== document.documentElement) {
        const s = getComputedStyle(p);
        if (s.transform !== 'none' || s.filter !== 'none' || s.backdropFilter !== 'none' || s.perspective !== 'none' || s.willChange !== 'auto' || s.contain !== 'none') {
          culprits.push({ tag: p.tagName, cls: p.className, transform: s.transform, filter: s.filter, backdrop: s.backdropFilter, willChange: s.willChange, contain: s.contain });
        }
        p = p.parentElement;
      }
      return {
        found: true,
        backdrop: { x: Math.round(r1.x), y: Math.round(r1.y), w: Math.round(r1.width), h: Math.round(r1.height), pos: cs.position, display: cs.display, jc: cs.justifyContent, ai: cs.alignItems },
        card: { x: Math.round(r2.x), y: Math.round(r2.y), w: Math.round(r2.width), h: Math.round(r2.height) },
        viewport: { w: window.innerWidth, h: window.innerHeight },
        cardCenterX: Math.round(r2.x + r2.width / 2),
        viewportCenterX: Math.round(window.innerWidth / 2),
        culprits,
      };
    });
    console.log(JSON.stringify(info, null, 2));
    await page.screenshot({ path: 'D:/ERP软件/_diag_modal.png' });
    await browser.disconnect();
  } catch (e) { console.log('异常:', e.message); }
  finally { try { child.kill('SIGKILL'); } catch (_) {} }
  process.exit(0);
})();
