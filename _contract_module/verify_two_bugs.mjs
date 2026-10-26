// 封神前两处 Bug 的验证台（真浏览器 + CDP 下载落盘读字节）
//
//   Bug 1  「已核对」按钮：已 reviewed 时必须 disabled + 变灰 + 文案「已完成核对」，
//          点击不发 /ocr/review 请求；即便被强制点亮，也只给一句回执不乱发请求。
//   Bug 2  Word 导出：落盘文件必须是真 docx（PK\x03\x04，>1KB，名字带 .docx）；
//          当服务端返回 JSON 报错（200 + {"detail":…}）时，**绝不能存成 .docx**，
//          必须报错并提示原因。
//
// 用法：node _contract_module/verify_two_bugs.mjs
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire('C:/Users/admi/.workbuddy/binaries/node/workspace/noop.js');
const puppeteer = require('puppeteer-core');

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const CHROME = 'C:/Users/admi/.agent-browser/browsers/chrome-155.0.8059.79/chrome.exe';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DL = path.join(ROOT, '_contract_module', '_dl_verify');
const STAMP = String(Date.now()).slice(-6);
const NO_UX = `HT-BUG1-${STAMP}`;
const NO_WD = `HT-BUG2-${STAMP}`;

const GREEN = [];
const RED = [];
const check = (label, ok, extra = '') => {
  (ok ? GREEN : RED).push(ok ? label : `${label}${extra ? ' —— ' + extra : ''}`);
  console.log(`  ${ok ? '✅' : '❌'} ${label}${ok || !extra ? '' : ' —— ' + extra}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(p, token, init = {}) {
  const res = await fetch(`${BASE}/api/v1${p}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  return { status: res.status, body };
}

fs.rmSync(DL, { recursive: true, force: true });
fs.mkdirSync(DL, { recursive: true });

const login = await fetchJson('/auth/login', null, {
  method: 'POST',
  body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
});
const token = login.body?.access_token || '';
check('X0 admin 登录', login.status === 200 && Boolean(token), `HTTP ${login.status}`);

const payload = (no, title) => ({
  contract_type: 'sales',
  direction: 'out',
  contract_no: no,
  title,
  party_name: '封神前验证客户',
  sign_date: '2026-10-19',
  total_amount: 1000,
  status: 'draft',
  items: [
    { product_name: '验证商品A', quantity: 2, unit_price: 300, amount: 600 },
    { product_name: '验证商品B', quantity: 1, unit_price: 400, amount: 400 },
  ],
});

const cUx = await fetchJson('/contracts', token, {
  method: 'POST',
  body: JSON.stringify(payload(NO_UX, 'Bug1 已核对按钮验证')),
});
const cWord = await fetchJson('/contracts', token, {
  method: 'POST',
  body: JSON.stringify(payload(NO_WD, 'Bug2 Word 导出验证')),
});
const uxId = cUx.body?.id || 0;
const wordId = cWord.body?.id || 0;
check('X0b 建好两张验证合同', cUx.status === 201 && cWord.status === 201, `${cUx.status}/${cWord.status}`);

// C1 推进到 reviewed + active（不跑 OCR 引擎：先挂小 PDF，再 PATCH ocr_json，最后 review）
const SMALL_PDF = path.join(
  ROOT,
  '.venv/Lib/site-packages/matplotlib/mpl-data/images/matplotlib.pdf',
);
if (uxId) {
  const form = new FormData();
  form.append(
    'file',
    new Blob([fs.readFileSync(SMALL_PDF)], { type: 'application/pdf' }),
    'tiny.pdf',
  );
  await fetch(`${BASE}/api/v1/contracts/${uxId}/source`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  await fetchJson(`/contracts/${uxId}/ocr`, token, {
    method: 'PATCH',
    body: JSON.stringify({ ocr_json: '{"fields":{}}', ocr_status: 'parsed' }),
  });
  const rev = await fetchJson(`/contracts/${uxId}/ocr/review`, token, {
    method: 'POST',
    body: JSON.stringify({ confirm_empty: true }),
  });
  const act = await fetchJson(`/contracts/${uxId}/status`, token, {
    method: 'PATCH',
    body: JSON.stringify({ status: 'active' }),
  });
  check(
    'X0c 合同已是「已人工核对 + 生效」',
    rev.status === 200 && act.status === 200,
    `review=${rev.status} status=${act.status}`,
  );
}

let browser;
const consoleErrors = [];
const reviewPosts = [];
try {
  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    protocolTimeout: 900000,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/not wrapped in act|ReactDOM|React DevTools/.test(t)) return;
    consoleErrors.push(t);
  });
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on('request', (req) => {
    if (req.url().includes('/ocr/review')) reviewPosts.push(req.url());
  });

  // 负向用例要用：只对 /exports/word/ 这一个 URL 返回 200 + JSON 报错
  // blob 下载在无头 Chrome 里不一定真落盘 → 直接盯 `<a download>` 的 click，
  // 这才是"有没有把内容存成文件"的直接证据（反证 C 组第一次就是被文件数骗过的）。
  await page.evaluateOnNewDocument(() => {
    window.__savedNames = [];
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function patchedClick() {
      if (String(this.href || '').startsWith('blob:')) {
        window.__savedNames.push(this.download || '');
      }
      return origClick.apply(this, arguments);
    };
  });

  await page.evaluateOnNewDocument(() => {
    const orig = window.fetch;
    window.fetch = function patched(input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (window.__fakeWordError && url.includes('/exports/word/')) {
        return Promise.resolve(
          new Response('{"detail":"模拟后端报错：模板缺失"}', {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }
      return orig.apply(this, arguments);
    };
  });

  const cdp = await page.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: DL,
    eventsEnabled: true,
  });

  await page.evaluateOnNewDocument((tok) => {
    localStorage.setItem('erp_token', tok);
    localStorage.setItem('erp_user', JSON.stringify({ username: 'admin', role: 'admin' }));
  }, token);
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle2', timeout: 45000 });
  await page.waitForSelector('.side-nav', { timeout: 20000 });

  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title').forEach((el) => {
      if (!el.closest('.nav-group')?.classList.contains('open')) el.click();
    });
  });
  await sleep(600);
  await page.evaluate(() => {
    Array.from(document.querySelectorAll('.nav-item'))
      .find((el) => el.textContent.trim() === '合同台账')
      ?.click();
  });
  await page.waitForSelector('.cledger', { timeout: 20000 });
  await sleep(1200);

  const openByNo = async (no) => {
    const hit = await page.evaluate((target) => {
      const row = Array.from(document.querySelectorAll('tbody tr')).find((tr) =>
        tr.textContent.includes(target),
      );
      const btn = Array.from(row?.querySelectorAll('button') || []).find(
        (b) => b.textContent.trim() === '详情',
      );
      btn?.click();
      return Boolean(btn);
    }, no);
    if (!hit) return false;
    await page.waitForSelector('.modal-header h3', { timeout: 15000 });
    await sleep(700);
    return true;
  };

  // ================= Bug 1 =================
  check('B1a 打开「已核对」合同的详情', await openByNo(NO_UX), NO_UX);
  const st = await page.evaluate(() => {
    const b = document.querySelector('[data-ocr-review]');
    if (!b) return null;
    const cs = getComputedStyle(b);
    return {
      text: b.textContent.trim(),
      disabled: b.disabled,
      reviewed: b.getAttribute('data-ocr-reviewed'),
      aria: b.getAttribute('aria-disabled'),
      bg: cs.backgroundColor,
      color: cs.color,
      cursor: cs.cursor,
      title: b.getAttribute('title') || '',
    };
  });
  check('B1b 按钮还在（不是凭空消失）', Boolean(st), JSON.stringify(st));
  check('B1c 文案已变成「已完成核对」', Boolean(st) && st.text.includes('已完成核对'), st?.text);
  check('B1d 处于 disabled', Boolean(st) && st.disabled === true, String(st?.disabled));
  check('B1e data-ocr-reviewed=1 / aria-disabled=true', st?.reviewed === '1' && st?.aria === 'true', JSON.stringify([st?.reviewed, st?.aria]));
  check(
    'B1f 视觉上不再是纯蓝（灰底 + not-allowed）',
    Boolean(st) && st.bg !== 'rgb(37, 99, 235)' && st.cursor === 'not-allowed',
    `${st?.bg} / ${st?.cursor}`,
  );
  check('B1g 悬停提示说清了为什么不能点', Boolean(st) && /无需再点|重新识别/.test(st.title), st?.title);

  const beforePosts = reviewPosts.length;
  await page.evaluate(() => document.querySelector('[data-ocr-review]')?.click());
  await sleep(800);
  check('B1h 点它不会发 /ocr/review 请求', reviewPosts.length === beforePosts, `${beforePosts} → ${reviewPosts.length}`);

  // 双重守卫：把 disabled 强制点亮再点，应该只给回执、依然不发请求
  const guard = await page.evaluate(() => {
    const b = document.querySelector('[data-ocr-review]');
    if (!b) return { ok: false };
    b.disabled = false;
    b.click();
    return { ok: true };
  });
  await sleep(700);
  const notice = await page.evaluate(
    () => document.querySelector('.cledger__notice')?.textContent.trim() || '',
  );
  const doneHint = await page.evaluate(
    () => document.querySelector('[data-ocr-done-hint]')?.textContent.trim() || '',
  );
  check(
    'B1i 详情里有一句常驻说明（不是一闪而过的 toast）',
    Boolean(guard.ok) && /已人工核对完成/.test(doneHint) && /重新识别/.test(doneHint),
    doneHint,
  );
  check('B1j 强制点亮后也没有真的重复核对', reviewPosts.length === beforePosts, `${beforePosts} → ${reviewPosts.length}`);

  await page.evaluate(() => document.querySelector('.modal-backdrop .close-btn')?.click());
  await sleep(600);

  // ================= Bug 2 · 正向：真下载 =================
  const clickWord = async (attr) => {
    const ok = await page.evaluate((sel) => {
      const row = Array.from(document.querySelectorAll('tbody tr')).find((tr) =>
        tr.textContent.includes(sel.no),
      );
      const btn = row?.querySelector(sel.q);
      btn?.click();
      return Boolean(btn);
    }, { no: NO_WD, q: `[data-word-export="${attr}"]` });
    return ok;
  };

  const before = fs.readdirSync(DL).filter((f) => !f.endsWith('.crdownload'));
  check('B2a 列表里点到 Word 按钮', await clickWord('contract'));
  let files = before;
  for (let i = 0; i < 25; i += 1) {
    await sleep(800);
    files = fs.readdirSync(DL).filter((f) => !f.endsWith('.crdownload'));
    if (files.length > before.length) break;
  }
  const added = files.filter((f) => !before.includes(f));
  const savedNames = await page.evaluate(() => window.__savedNames || []);
  check('B2b 确实触发了保存（<a download> 被点）', savedNames.length === 1, JSON.stringify(savedNames));
  check('B2b2 保存时的文件名带 .docx', savedNames[0]?.toLowerCase().endsWith('.docx'), savedNames[0]);
  check('B2b3 浏览器也真的落了盘', added.length === 1, JSON.stringify(files));

  if (added.length) {
    const p = path.join(DL, added[0]);
    const buf = fs.readFileSync(p);
    check(`B2c 文件名带 .docx（${added[0]}）`, added[0].toLowerCase().endsWith('.docx'), added[0]);
    check(`B2d 大小合理（${buf.length} B > 1KB）`, buf.length > 1024, String(buf.length));
    check(
      `B2e 魔数是 PK\\x03\\x04（真 docx/zip）：${buf.subarray(0, 4).toString('hex')}`,
      buf[0] === 0x50 && buf[1] === 0x4b && buf[2] === 0x03 && buf[3] === 0x04,
      buf.subarray(0, 4).toString('hex'),
    );
    check('B2f 不是 JSON 报错文本', buf.subarray(0, 1).toString() !== '{', buf.subarray(0, 30).toString('utf8'));
    // docx 里必须有 word/document.xml（只校验 zip 里是否有该条目名）
    check('B2g 包内含 word/document.xml', buf.includes(Buffer.from('word/document.xml')));
  } else {
    ['B2c', 'B2d', 'B2e', 'B2f', 'B2g'].forEach((k) => check(`${k} 无文件可校验`, false));
  }

  // ================= Bug 2 · 反向：服务端返回 200 + JSON =================
  // ⚠️ 这里连 .crdownload 一起数、并且轮询等满 8 秒：
  //    Chrome 先写 xxx.docx.crdownload 再改名，2.5 秒一刀切会漏判（反证 C 组第一次就是这么骗过自己的）。
  const listAll = () => fs.readdirSync(DL);
  const filesBeforeFake = listAll();
  await page.evaluate(() => {
    window.__fakeWordError = true;
  });
  check('B2h 负向用例：点到 Word 按钮', await clickWord('contract'));
  let filesAfterFake = filesBeforeFake;
  for (let i = 0; i < 16; i += 1) {
    await sleep(500);
    filesAfterFake = listAll();
    if (filesAfterFake.length > filesBeforeFake.length) {
      await sleep(1200); // 让它改名完，别把 .crdownload 当证据
      filesAfterFake = listAll();
      break;
    }
  }
  const savedAfterFake = await page.evaluate(() => (window.__savedNames || []).length);
  check(
    'B2i JSON 报错**没有**被存成 .docx（没有触发任何保存）',
    savedAfterFake === 1 && filesAfterFake.length === filesBeforeFake.length,
    `saved=${savedAfterFake}（应为 1，即正向那次）, files ${filesBeforeFake.length} → ${filesAfterFake.length}`,
  );
  const fakeNotice = await page.evaluate(
    () => document.querySelector('.cledger__notice')?.textContent.trim() || '',
  );
  check('B2j 界面明确报了「导出失败」并带出原因', /导出失败/.test(fakeNotice) && /模板缺失/.test(fakeNotice), fakeNotice);

  check('X9 全程无 JS 报错', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '));
} catch (err) {
  check('X-异常 浏览器流程跑通', false, `${err.name}: ${err.message}`);
} finally {
  if (browser) await browser.close();
  // 清理夹具
  for (const id of [uxId, wordId]) {
    if (id) await fetchJson(`/contracts/${id}`, token, { method: 'DELETE' });
  }
}

console.log('\n' + '='.repeat(68));
console.log(`合计 ${GREEN.length + RED.length} 项，通过 ${GREEN.length} 项，失败 ${RED.length} 项`);
RED.forEach((r) => console.log(`  ✗ ${r}`));
process.exitCode = RED.length ? 1 : 0;
