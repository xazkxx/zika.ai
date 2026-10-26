// 任务 E · 全单据 Word 导出 · 界面层验证台（2026-10-19）
//
// 前面 `verify_taskE_word_export.py` 已经证明了「接口能吐出合格的 docx」。
// 这个台子只回答一件事：**用户在界面上点得着吗、点完真的落地成文件吗。**
//
//   U1  合同台账列表每行有「Word」按钮，点完磁盘上多出一个 .docx
//   U2  合同详情抽屉里也有「导出 Word」，且不是灰的
//   U3  报价单页每行有「Word」按钮，点完落盘
//   U4  采购入库页每行有「Word」按钮，点完落盘
//   U5  增强对账单载入一张真单后「导出 Word」可点，点完落盘
//   U6  四个下载文件都是合法 docx（python-docx 能打开、有正文、文件名带单号）
//   U7  全程没有控制台报错
//   U8  浏览器载入的 bundle = 本次 dist 构建（防止"改了没发布"）
//
// 用法：node _contract_module/verify_taskE_word_ui.mjs
//
// ⚠️ 三个坑（都是踩过的）：
//   ① 侧边栏分组默认收起 → `.nav-item` 不在 DOM，必须先点 `.nav-group-title` 展开；
//   ② 下载得用 CDP `Page.setDownloadBehavior`，不能靠 page.on('response') —— 那是 blob；
//   ③ `fork()` 跑不了 .py（ERR_UNKNOWN_FILE_EXTENSION）→ 用 `spawnSync(venv_python, [script])`。

import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire('C:/Users/admi/.workbuddy/binaries/node/workspace/noop.js');
const puppeteer = require('puppeteer-core');

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const CHROME = 'C:/Users/admi/.agent-browser/browsers/chrome-155.0.8059.79/chrome.exe';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VENV_PY = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
const DOWNLOAD_DIR = path.join(os.tmpdir(), `erp-word-ui-${Date.now()}`);

const GREEN = [];
const RED = [];
const check = (label, condition, extra = '') => {
  (condition ? GREEN : RED).push(condition ? label : `${label}${extra ? ' —— ' + extra : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(p, token, init = {}) {
  const response = await fetch(`${BASE}/api/v1${p}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  return { status: response.status, body };
}

/** 等下载目录里出现一个没见过的 *.docx，返回 {name,size} 或 null。 */
async function waitForDownload(seen, timeout = 25000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const now = fs.existsSync(DOWNLOAD_DIR) ? fs.readdirSync(DOWNLOAD_DIR) : [];
    const fresh = now.filter((name) => name.toLowerCase().endsWith('.docx') && !seen.has(name));
    // Chrome 下载完成才改名/落定，所以还要确认大小稳定
    for (const name of fresh) {
      const full = path.join(DOWNLOAD_DIR, name);
      try {
        const first = fs.statSync(full).size;
        await sleep(400);
        const second = fs.statSync(full).size;
        if (first === second && second > 8000) return { name, size: second };
      } catch {
        /* 还在写，下一轮再看 */
      }
    }
    await sleep(300);
  }
  return null;
}

function currentDownloads() {
  return new Set(fs.existsSync(DOWNLOAD_DIR) ? fs.readdirSync(DOWNLOAD_DIR) : []);
}

/** 展开所有收起的侧边栏分组（`.nav-item` 不在 DOM 时点不到）。 */
async function expandGroups(page) {
  await page.evaluate(() => {
    document
      .querySelectorAll('.nav-group-title')
      .forEach((el) => {
        if (el.classList.contains('collapsed')) el.click();
      });
  });
  await sleep(250);
}

async function gotoTab(page, label) {
  await expandGroups(page);
  const clicked = await page.evaluate((text) => {
    const item = Array.from(document.querySelectorAll('.nav-item')).find(
      (el) => el.textContent.trim() === text,
    );
    if (!item) return false;
    item.click();
    return true;
  }, label);
  await sleep(900);
  return clicked;
}

/** 点一个按钮并等下载。返回 {ok, file, detail}。 */
async function clickAndDownload(page, selector, timeout = 25000) {
  const seen = currentDownloads();
  const before = seen.size;
  const clicked = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return 'missing';
    if (el.disabled) return 'disabled';
    el.click();
    return 'ok';
  }, selector);
  if (clicked !== 'ok') return { ok: false, detail: `按钮状态 ${clicked}` };
  const file = await waitForDownload(seen, timeout);
  return {
    ok: Boolean(file),
    file,
    detail: file ? `${file.name} ${file.size} 字节` : `25 秒内没落盘（下载前后文件数 ${before} → ${currentDownloads().size}）`,
  };
}

async function main() {
  fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });

  const login = await fetchJson('/auth/login', null, {
    method: 'POST',
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const token = login.body?.access_token || '';
  check('U0 admin 登录', login.status === 200 && Boolean(token), `HTTP ${login.status}`);

  // 合同台账现在是空的 → 现场建一张，跑完删掉（用户的数据一行不动）
  const created = await fetchJson('/contracts', token, {
    method: 'POST',
    body: JSON.stringify({
      direction: 'out',
      contract_type: 'sales',
      contract_no: 'HT-WORDUI-0001',
      title: 'Word 导出界面验证合同',
      party_name: '克拉玛依市城市建设投资发展有限责任公司',
      total_amount: 2617568.02,
      sign_date: '2026-10-19',
      status: 'draft',
      items: [
        {
          product_name: 'ZRC-YJY23-0.6/1kV-3x25',
          unit: '米',
          quantity: 4654,
          unit_price: 100.81,
        },
      ],
    }),
  });
  const contractId = created.body?.id || 0;
  check('U0b 造一张验证用合同', created.status === 201 || created.status === 200, `HTTP ${created.status} ${JSON.stringify(created.body).slice(0, 120)}`);

  let browser;
  const consoleErrors = [];
  const downloaded = [];

  try {
    browser = await puppeteer.launch({
      // 扫描件 OCR 单次要 200~320 秒，而 Puppeteer 默认 protocolTimeout=180s
      // —— 超了会抛 "Waiting for selector ... failed"：看着像识别没回填，其实是测试台自己把连接掐断了（2026-10-19 封版实测）
      protocolTimeout: 900000,
      executablePath: CHROME,
      headless: 'new',
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    const page = await browser.newPage();
    page.on('console', (msg) => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      if (/not wrapped in act|Warning: ReactDOM|Download the ReactDevTools/.test(text)) return;
      consoleErrors.push(text);
    });
    page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
    page.on('dialog', (dialog) => dialog.dismiss());

    const client = await page.target().createCDPSession();
    await client.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: DOWNLOAD_DIR });

    await page.evaluateOnNewDocument((tok) => {
      localStorage.setItem('erp_token', tok);
      localStorage.setItem('erp_user', JSON.stringify({ username: 'admin', role: 'admin' }));
    }, token);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle2', timeout: 45000 });
    await page.waitForSelector('.side-nav', { timeout: 20000 });

    // U8 产物一致性
    const distHtml = fs.readFileSync(path.join(ROOT, 'frontend', 'dist', 'index.html'), 'utf8');
    const distAsset = /assets\/index-[\w-]+\.js/.exec(distHtml)?.[0] || '';
    const loadedAsset = await page.evaluate(
      () =>
        Array.from(document.querySelectorAll('script[src]'))
          .map((el) => el.getAttribute('src'))
          .find((src) => /assets\/index-[\w-]+\.js/.test(src || '')) || '',
    );
    check(
      'U8 浏览器载入的 bundle = 本次 dist 构建',
      Boolean(distAsset) && loadedAsset.endsWith(distAsset.split('/').pop()),
      `${distAsset} vs ${loadedAsset}`,
    );

    // ---------- U1 合同台账（列表）----------
    const ok1 = await gotoTab(page, '合同台账');
    await page.waitForSelector('.cledger', { timeout: 20000 }).catch(() => {});
    await page.waitForSelector('tbody tr', { timeout: 20000 }).catch(() => {});
    await sleep(600);
    const wordBtns = await page.$$eval('[data-word-export="contract"]', (els) => els.length);
    check('U1 合同台账列表出现「Word」按钮', ok1 && wordBtns >= 1, `命中 ${wordBtns} 个`);
    const d1 = await clickAndDownload(page, '[data-word-export="contract"]');
    check('U1b 点「Word」→ 磁盘多出一个 .docx', d1.ok, d1.detail);
    if (d1.file) downloaded.push({ kind: '合同（列表）', ...d1.file });

    // ---------- U2 合同详情 ----------
    const detailOpened = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll('.cledger__row-actions button')).find(
        (el) => el.textContent.trim() === '详情',
      );
      if (!btn) return false;
      btn.click();
      return true;
    });
    await sleep(900);
    const detailProbe = await page.evaluate(() => {
      const el = document.querySelector('[data-word-export="contract-detail"]');
      return { exists: Boolean(el), disabled: el?.disabled ?? null, text: el?.textContent.trim() || '' };
    });
    check(
      'U2 合同详情里有「导出 Word」且可点',
      detailOpened && detailProbe.exists && detailProbe.disabled === false,
      JSON.stringify(detailProbe),
    );
    await page.keyboard.press('Escape');
    await sleep(400);

    // ---------- U3 报价单 ----------
    const ok3 = await gotoTab(page, '报价单');
    const qAppear = await page
      .waitForSelector('[data-word-export="quotation"]', { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    check('U3 报价单页出现「Word」按钮', ok3 && qAppear, '20 秒内没出现 [data-word-export="quotation"]');
    const d3 = await clickAndDownload(page, '[data-word-export="quotation"]');
    check('U3b 点「Word」→ 落盘', d3.ok, d3.detail);
    if (d3.file) downloaded.push({ kind: '报价单', ...d3.file });

    // ---------- U4 采购入库 ----------
    const ok4 = await gotoTab(page, '采购入库');
    const pAppear = await page
      .waitForSelector('[data-word-export="inbound"]', { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    check('U4 采购入库页出现「Word」按钮', ok4 && pAppear, '20 秒内没出现 [data-word-export="inbound"]');
    const d4 = await clickAndDownload(page, '[data-word-export="inbound"]');
    check('U4b 点「Word」→ 落盘', d4.ok, d4.detail);
    if (d4.file) downloaded.push({ kind: '入库单', ...d4.file });

    // ---------- U5 增强对账单 ----------
    const ok5 = await gotoTab(page, '增强对账单');
    const sAppear = await page
      .waitForSelector('[data-word-export="statement"]', { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    check('U5 增强对账单页出现「导出 Word」', ok5 && sAppear, '20 秒内没出现 [data-word-export="statement"]');

    // 没载入单据时按钮应该是灰的（防呆：不对着空气导出）
    const idleDisabled = await page.evaluate(
      () => document.querySelector('[data-word-export="statement"]')?.disabled ?? null,
    );
    check('U5b 没载入对账单时按钮是灰的', idleDisabled === true, String(idleDisabled));

    // 载入一张已存对账单：点开「载入已存对账单」下拉，选第一条
    await page.evaluate(() => {
      const box = document.querySelector('.stmt__field--recent div[role="combobox"]');
      box?.click();
    });
    await sleep(700);
    const picked = await page.evaluate(() => {
      // ⚠️ 下拉面板是 `createPortal` 到 body 的，不在 `.stmt__field--recent` 里面
      //    —— 用祖先选择器找 `[role="option"]` 会一个都找不到（第一版就栽在这）。
      const listbox = document.querySelector('[role="listbox"]');
      const opt = listbox?.querySelector('[role="option"]');
      if (!opt) return false;
      opt.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      return true;
    });
    await sleep(1400);
    const loadedDisabled = await page.evaluate(
      () => document.querySelector('[data-word-export="statement"]')?.disabled ?? null,
    );
    check('U5c 载入对账单后按钮可点', picked && loadedDisabled === false, `picked=${picked} disabled=${loadedDisabled}`);
    if (loadedDisabled === false) {
      const d5 = await clickAndDownload(page, '[data-word-export="statement"]');
      check('U5d 点「导出 Word」→ 落盘', d5.ok, d5.detail);
      if (d5.file) downloaded.push({ kind: '对账单', ...d5.file });
    } else {
      check('U5d 点「导出 Word」→ 落盘', false, '按钮仍不可点，跳过');
    }

    // ---------- U6 四份文件都是合法 docx ----------
    const probe = `
import sys, json
from docx import Document
out = []
for p in sys.argv[1:]:
    try:
        d = Document(p)
        text = "\\n".join([x.text for x in d.paragraphs])
        for t in d.tables:
            for r in t.rows:
                for c in r.cells:
                    text += "\\n" + c.text
        out.append({"path": p, "ok": len(text.strip()) > 50, "chars": len(text), "tables": len(d.tables)})
    except Exception as e:
        out.append({"path": p, "ok": False, "error": f"{type(e).__name__}: {e}"})
print(json.dumps(out, ensure_ascii=False))
`;
    const files = downloaded.map((d) => path.join(DOWNLOAD_DIR, d.name));
    const result = spawnSync(VENV_PY, ['-c', probe, ...files], {
      encoding: 'utf8',
      cwd: ROOT,
      timeout: 120000,
    });
    let parsed = [];
    try {
      parsed = JSON.parse((result.stdout || '[]').trim().split('\n').pop() || '[]');
    } catch {
      parsed = [];
    }
    const allOk = parsed.length === files.length && parsed.length >= 3 && parsed.every((row) => row.ok);
    check(
      `U6 下载的 ${files.length} 份文件都能被 Word 引擎打开且有正文`,
      allOk,
      JSON.stringify(parsed.map((row) => ({ ok: row.ok, chars: row.chars, err: row.error }))),
    );
    for (const row of parsed) {
      console.log(`    ${path.basename(row.path)}  正文 ${row.chars ?? 0} 字  表 ${row.tables ?? 0} 张`);
    }
    // 文件名要带单号（后端 RFC5987 中文名生效）
    const named = downloaded.filter((row) => /[\u4e00-\u9fa5]/.test(row.name) && /[A-Z]{2}/.test(row.name));
    check(
      'U6b 文件名是「单据名-单号.docx」形式（中文没被丢）',
      named.length === downloaded.length && downloaded.length >= 3,
      downloaded.map((row) => row.name).join(' | '),
    );

    check('U7 全程无控制台报错', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '));
  } catch (err) {
    check('U0c 浏览器流程跑通', false, `${err.name}: ${err.message}`);
  } finally {
    if (browser) await browser.close();
    if (contractId) {
      const removed = await fetchJson(`/contracts/${contractId}`, token, { method: 'DELETE' });
      check('U9 清理验证用合同', removed.status === 204 || removed.status === 200, `HTTP ${removed.status}`);
    }
    console.log(`\n下载目录：${DOWNLOAD_DIR}`);
  }

  console.log('\n' + '='.repeat(68));
  console.log(`合计 ${GREEN.length + RED.length} 项，通过 ${GREEN.length} 项，失败 ${RED.length} 项`);
  if (RED.length) {
    for (const item of RED) console.log(`  ✗ ${item}`);
  }
  process.exit(RED.length ? 1 : 0);
}

main();
