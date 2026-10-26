// 任务 H · 详情页两个 UX 盲区 · 界面台（2026-10-19）
//
// 用户原话：
//   ① "OCR 状态已经是「已人工核对」，但下方依然有一个「开始识别」按钮。如果用户误点，
//      可能会覆盖已核对的数据。请把这个按钮隐藏，或者改成「重新识别」，并在点击时
//      弹出二次确认。"
//   ② "当前合同是「草稿」，但我找遍了详情页，没看到「提交审核」或「转为生效」的按钮。"
//
// 断言：
//   H1  已核对的合同：按钮文案是「重新识别」，不是「开始识别」
//   H2  点它先弹确认框，文案说清"会覆盖已人工核对的数据"
//   H3  点「取消」→ 弹窗关、**没有发识别请求**、库里 ocr_status 仍是 reviewed
//   H4  点「继续重新识别」→ 真的开始识别（骨架屏出现），跑完 ocr_status 回到 parsed
//   H5  草稿合同详情底部有「确认生效」
//   H6  点它 → 状态变 active、按钮消失、列表徽章变成「生效」
//   H7  已生效的合同再打开详情，**没有**「确认生效」（不能一键把完成/作废拉回生效）
//
// 用法：node _contract_module/verify_taskH_detail_ux.mjs

import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire('C:/Users/admi/.workbuddy/binaries/node/workspace/noop.js');
const puppeteer = require('puppeteer-core');

const BASE = process.env.ERP_BASE || 'http://127.0.0.1:8011';
const CHROME = 'C:/Users/admi/.agent-browser/browsers/chrome-155.0.8059.79/chrome.exe';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VENV_PY = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
// 1 页 22KB、没有文本层 → 走真 OCR 但只需几秒（用大扫描件跑这里太浪费）
const SMALL_PDF = path.join(
  ROOT,
  '.venv',
  'Lib',
  'site-packages',
  'matplotlib',
  'mpl-data',
  'images',
  'matplotlib.pdf',
);

const STAMP = Date.now().toString().slice(-6);
const NO_DRAFT = `HT-UXH${STAMP}A`;
const NO_REVIEWED = `HT-UXH${STAMP}B`;

const GREEN = [];
const RED = [];
const check = (label, ok, extra = '') => {
  (ok ? GREEN : RED).push(ok ? label : `${label}${extra ? ' —— ' + extra : ''}`);
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

function pyJson(script, args = []) {
  const result = spawnSync(VENV_PY, ['-c', script, ...args], {
    encoding: 'utf8',
    cwd: ROOT,
    timeout: 60000,
  });
  try {
    return JSON.parse((result.stdout || '{}').trim().split('\n').pop() || '{}');
  } catch {
    return { error: (result.stderr || '').slice(0, 300) };
  }
}

const dbOcrStatus = (id) =>
  pyJson(
    `
import os, sys, json
from dotenv import load_dotenv
load_dotenv('.env')  # pyJson 的 cwd 就是项目根
import psycopg
con = psycopg.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://'))
cur = con.cursor()
cur.execute("set search_path to public")
cur.execute("select contract_no, status, ocr_status from contracts where id=%s", (int(sys.argv[1]),))
row = cur.fetchone()
print(json.dumps(None if not row else {"contract_no": row[0], "status": row[1], "ocr_status": row[2]},
                 ensure_ascii=False))
`,
    [String(id)],
  );

async function expandGroups(page) {
  await page.evaluate(() => {
    document.querySelectorAll('.nav-group-title').forEach((el) => {
      if (el.classList.contains('collapsed')) el.click();
    });
  });
  await sleep(250);
}

async function gotoTab(page, label) {
  await expandGroups(page);
  await page.evaluate((text) => {
    const item = Array.from(document.querySelectorAll('.nav-item')).find(
      (el) => el.textContent.trim() === text,
    );
    item?.click();
  }, label);
  await sleep(900);
}

/** 在列表里按合同号找到那一行，点「详情」 */
async function openDetailByNo(page, contractNo) {
  const clicked = await page.evaluate((no) => {
    const row = Array.from(document.querySelectorAll('tbody tr')).find((tr) =>
      tr.textContent.includes(no),
    );
    if (!row) return false;
    const btn =
      Array.from(row.querySelectorAll('button')).find((b) => b.textContent.trim() === '详情') ||
      row;
    btn.click();
    return true;
  }, contractNo);
  await sleep(700);
  return clicked;
}

const closeDetail = async (page) => {
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('.modal-actions button')).find(
      (b) => b.textContent.trim() === '关闭',
    );
    btn?.click();
  });
  await page
    .waitForFunction(() => !document.querySelector('[data-ocr-start]'), { timeout: 10000 })
    .catch(() => null);
  await sleep(300);
};

async function main() {
  check('H0 小体积 PDF 夹具在（1 页 22KB，真 OCR 只要几秒）', fs.existsSync(SMALL_PDF), SMALL_PDF);

  const login = await fetchJson('/auth/login', null, {
    method: 'POST',
    body: JSON.stringify({ username: 'admin', password: 'Admin123' }),
  });
  const token = login.body?.access_token || '';
  check('H0b admin 登录', login.status === 200 && Boolean(token), `HTTP ${login.status}`);

  const basePayload = (no, title) => ({
    contract_type: 'sales',
    direction: 'out',
    contract_no: no,
    title,
    party_name: 'UX 盲区验证客户',
    sign_date: '2026-10-19',
    total_amount: 100,
    status: 'draft',
    items: [{ product_name: '验证用商品', quantity: 1, unit_price: 100, amount: 100 }],
  });

  const draft = await fetchJson('/contracts', token, {
    method: 'POST',
    body: JSON.stringify(basePayload(NO_DRAFT, '详情页 UX 验证 · 草稿')),
  });
  const reviewed = await fetchJson('/contracts', token, {
    method: 'POST',
    body: JSON.stringify(basePayload(NO_REVIEWED, '详情页 UX 验证 · 已核对')),
  });
  check(
    'H0c 建好两张验证合同（草稿 / 已核对）',
    draft.status === 201 && reviewed.status === 201,
    `${draft.status}/${reviewed.status} ${JSON.stringify(draft.body).slice(0, 120)}`,
  );

  const draftId = draft.body?.id || 0;
  const reviewedId = reviewed.body?.id || 0;

  // 第二张：挂原件 → 写 ocr_json(parsed) → 走 review 置 reviewed（不跑引擎，秒级）
  if (reviewedId) {
    const form = new FormData();
    form.append('file', new Blob([fs.readFileSync(SMALL_PDF)], { type: 'application/pdf' }), 'tiny.pdf');
    const up = await fetch(`${BASE}/api/v1/contracts/${reviewedId}/source`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    check('H0d 已核对合同挂上原件', up.status === 200, `HTTP ${up.status}`);
    await fetchJson(`/contracts/${reviewedId}/ocr`, token, {
      method: 'PATCH',
      body: JSON.stringify({ ocr_json: '{"fields":{}}', ocr_status: 'parsed' }),
    });
    const rev = await fetchJson(`/contracts/${reviewedId}/ocr/review`, token, {
      method: 'POST',
      body: JSON.stringify({ confirm_empty: true }),
    });
    check('H0e 状态推进到 reviewed', rev.status === 200, `HTTP ${rev.status} ${JSON.stringify(rev.body).slice(0, 100)}`);
  }

  let browser;
  const consoleErrors = [];
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

    await page.evaluateOnNewDocument((tok) => {
      localStorage.setItem('erp_token', tok);
      localStorage.setItem('erp_user', JSON.stringify({ username: 'admin', role: 'admin' }));
    }, token);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle2', timeout: 45000 });
    await page.waitForSelector('.side-nav', { timeout: 20000 });
    await gotoTab(page, '合同台账');
    await page.waitForSelector('.cledger', { timeout: 20000 });

    // ================= ① 已核对 → 重新识别 + 二次确认 =================
    check('H1a 打开已核对合同的详情', await openDetailByNo(page, NO_REVIEWED), NO_REVIEWED);
    const ocrBtn = await page.evaluate(() => {
      const btn = document.querySelector('[data-ocr-start]');
      return {
        text: btn?.textContent.trim() || '',
        rerun: btn?.getAttribute('data-ocr-rerun') || '',
        badge: document.querySelector('.cledger__badge')?.textContent.trim() || '',
      };
    });
    check('H1 已核对时按钮文案是「重新识别」', ocrBtn.text.includes('重新识别'), ocrBtn.text);
    check('H1b 标记位 data-ocr-rerun=1（前端自己知道这是重跑）', ocrBtn.rerun === '1', ocrBtn.rerun);

    await page.evaluate(() => document.querySelector('[data-ocr-start]')?.click());
    const confirmOpen = await page
      .waitForSelector('[data-ocr-confirm-text]', { timeout: 6000 })
      .then(() => true)
      .catch(() => false);
    const confirmText = await page.evaluate(
      () => document.querySelector('[data-ocr-confirm-text]')?.textContent.trim() || '',
    );
    check('H2 点击后先弹二次确认（不是直接开跑）', confirmOpen);
    check(
      'H2b 文案说清"会覆盖已人工核对的数据"',
      confirmText.includes('已人工核对') && confirmText.includes('覆盖'),
      confirmText.slice(0, 80),
    );

    // 取消 → 什么都不该发生
    await page.evaluate(() => document.querySelector('[data-ocr-confirm-cancel]')?.click());
    await sleep(600);
    const afterCancel = await page.evaluate(() => ({
      modal: Boolean(document.querySelector('[data-ocr-confirm-text]')),
      running: Boolean(document.querySelector('[data-ocr-running]')),
    }));
    check('H3 点「取消」弹窗关闭、也没有开始识别', !afterCancel.modal && !afterCancel.running, JSON.stringify(afterCancel));
    check('H3b 库里 ocr_status 仍是 reviewed（没被悄悄重跑）', dbOcrStatus(reviewedId).ocr_status === 'reviewed', JSON.stringify(dbOcrStatus(reviewedId)));

    // 继续 → 真的开跑
    await page.evaluate(() => document.querySelector('[data-ocr-start]')?.click());
    await page.waitForSelector('[data-ocr-confirm-text]', { timeout: 6000 });
    await page.evaluate(() => document.querySelector('[data-ocr-confirm-ok]')?.click());
    const started = await page
      .waitForSelector('[data-ocr-running]', { timeout: 15000 })
      .then(() => true)
      .catch(() => false);
    check('H4 点「继续重新识别」后真的开始识别（出现识别中提示）', started);
    // 等识别结束（小 PDF 几秒；给 180 秒余量）
    const finished = await page
      .waitForFunction(() => !document.querySelector('[data-ocr-running]'), { timeout: 180000 })
      .then(() => true)
      .catch(() => false);
    await sleep(800);
    const statusAfter = dbOcrStatus(reviewedId).ocr_status;
    check(
      'H4b 识别跑完，ocr_status 从 reviewed 回到 parsed（说明"覆盖"是真的）',
      finished && statusAfter === 'parsed',
      `finished=${finished} status=${statusAfter}`,
    );
    await closeDetail(page);

    // ================= ② 草稿 → 确认生效 =================
    check('H5a 打开草稿合同的详情', await openDetailByNo(page, NO_DRAFT), NO_DRAFT);
    const activate = await page.evaluate(() => {
      const btn = document.querySelector('[data-contract-activate]');
      return {
        exists: Boolean(btn),
        text: btn?.textContent.trim() || '',
        // ⚠️ 必须限定在详情标题区：`.cledger__badge` 在**列表行**里也有，
        //    裸 querySelector 拿到的是背后那张表的第一枚徽章（踩过一次）
        badge: document.querySelector('.modal-header h3 .cledger__badge')?.textContent.trim() || '',
      };
    });
    check('H5 草稿合同底部有「确认生效」按钮', activate.exists && activate.text.includes('确认生效'), JSON.stringify(activate));

    await page.evaluate(() => document.querySelector('[data-contract-activate]')?.click());
    const gone = await page
      .waitForFunction(() => !document.querySelector('[data-contract-activate]'), { timeout: 20000 })
      .then(() => true)
      .catch(() => false);
    await sleep(500);
    const afterActivate = dbOcrStatus(draftId);
    const badgeNow = await page.evaluate(
      () => document.querySelector('.modal-header h3 .cledger__badge')?.textContent.trim() || '',
    );
    check('H6 点完状态变成 active（库里）', afterActivate.status === 'active', JSON.stringify(afterActivate));
    check('H6b 按钮消失（不能重复点）', gone);
    check('H6c 详情徽章变成「生效」', badgeNow.includes('生效'), badgeNow);

    // 列表徽章也应刷新
    await closeDetail(page);
    const listBadge = await page.evaluate((no) => {
      const row = Array.from(document.querySelectorAll('tbody tr')).find((tr) =>
        tr.textContent.includes(no),
      );
      return row?.textContent || '';
    }, NO_DRAFT);
    check('H6d 列表里这一行也显示「生效」', listBadge.includes('生效'), listBadge.slice(0, 80));

    // 已生效的合同不该再有「确认生效」
    await openDetailByNo(page, NO_DRAFT);
    const noActivate = await page.evaluate(() => !document.querySelector('[data-contract-activate]'));
    check('H7 已生效的合同再打开，没有「确认生效」（不会被一键拉回）', noActivate);
    await closeDetail(page);

    check('H8 全程无控制台报错', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '));
  } catch (err) {
    check('H-异常 浏览器流程跑通', false, `${err.name}: ${err.message}`);
  } finally {
    if (browser) await browser.close();
    for (const id of [draftId, reviewedId]) {
      if (id) await fetchJson(`/contracts/${id}`, token, { method: 'DELETE', body: JSON.stringify({}) });
    }
  }

  console.log('\n' + '='.repeat(68));
  console.log(`合计 ${GREEN.length + RED.length} 项，通过 ${GREEN.length} 项，失败 ${RED.length} 项`);
  for (const item of RED) console.log(`  ✗ ${item}`);
  process.exit(RED.length ? 1 : 0);
}

main();
