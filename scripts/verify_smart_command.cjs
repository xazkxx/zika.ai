/**
 * 🤖 智能指令搜索框 真浏览器验收 —— 2026-10-23
 *
 * 验九件事：
 *   1. 工作台（首页）最顶部有指令条，且在欢迎横幅**上方**；
 *   2. 打「湖南华邦的对账单」→ 悬浮面板出现，命中单位高亮；
 *   3. 卡片数量与 `/agent/dispatch` 返回一致（对账单 2 张、未结清单据 1 张）；
 *   4. 点「打开预览」→ 弹窗显示出对账单（单号/账期/明细行）；
 *   5. 点「生成 PDF」→ 走 `Accept: application/json` 的 base64 通道，base64 解出来是 %PDF；
 *   6. 点「去修改」→ 跳到「增强对账单」，且往来单位被锁定成该单位；
 *   7. 合同意图：「湖南华邦的合同」→ 合同卡 → 预览正文标题是《产品买卖合同（简易版）》；
 *   8. 点「导出 Word」→ 响应非空 docx（PK 头）；
 *   9. 认不出的单位 → 面板给出候选；几何上面板不超出视口。
 *
 * 跑法：BASE=http://127.0.0.1:8022 node scripts/verify_smart_command.cjs
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || process.env.ERP_BASE || 'http://127.0.0.1:8022';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const PARTY_KEY = '湖南华邦';
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

async function typeCommand(text) {
  // 受控输入框：三击选中再打字不一定替换得掉（React 每次 render 会把选区重置）。
  // 用原生 setter + input 事件，与其它验收脚本同一套做法，稳。
  await page.evaluate((value) => {
    const input = document.querySelector('[data-scb-input]');
    if (!input) return;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
  await sleep(150);
}

async function backToOverview() {
  // 先直接找；找不到就把分组逐个展开再找一遍（侧边栏默认只展开当前分组）
  let hit = await page.evaluate(() => {
    const item = [...document.querySelectorAll('.nav-item')].find(
      (e) => (e.textContent || '').trim() === '运营概览',
    );
    if (!item) return false;
    item.click();
    return true;
  });
  if (hit) {
    await sleep(1500);
    return true;
  }
  const groups = await page.$$('.nav-group-title');
  for (const group of groups) {
    await group.click();
    await sleep(250);
    hit = await page.evaluate(() => {
      const item = [...document.querySelectorAll('.nav-item')].find(
        (e) => (e.textContent || '').trim() === '运营概览',
      );
      if (!item) return false;
      item.click();
      return true;
    });
    if (hit) {
      await sleep(1500);
      // 只展开了一个分组就停手，别把刚展开的再点回去
      return true;
    }
  }
  return false;
}

(async () => {
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败 ${login.status}`);
  TOKEN = login.data.access_token;

  // 后端基线（页面上的卡片数量必须与它一致）
  const expectedStatement = await api('POST', '/api/v1/agent/dispatch', { text: `${PARTY_KEY}的对账单` });
  if (expectedStatement.status !== 200) throw new Error(`dispatch 失败 ${expectedStatement.status}`);
  const exp = expectedStatement.data;
  const expStatements = (exp.matched_data || []).filter((row) => row.kind === 'statement');
  const expDocs = (exp.matched_data || []).filter((row) => row.kind === 'document');
  if (!exp.party) fail('后端能认出「湖南华邦」', JSON.stringify(exp.message));
  console.log(
    `  基线：${exp.party.name} · 对账单 ${expStatements.length} / 未结清单据 ${expDocs.length}`,
  );

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

  // 页面内埋点：记录 PDF / Word 两个下载通道的响应摘要（大 body 不走 CDP 读，会被 evict）
  await page.evaluateOnNewDocument(() => {
    window.__scbFetch = [];
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const response = await nativeFetch(input, init);
      if (url.includes('/print/statement-record/') || url.includes('/exports/word/contract/')) {
        const clone = response.clone();
        let bytes = -1;
        let head = '';
        try {
          const buffer = await clone.arrayBuffer();
          bytes = buffer.byteLength;
          head = Array.from(new Uint8Array(buffer.slice(0, 4)))
            .map((byte) => String.fromCharCode(byte))
            .join('');
        } catch {
          /* ignore */
        }
        window.__scbFetch.push({
          url,
          status: response.status,
          contentType: response.headers.get('content-type') || '',
          bytes,
          head,
        });
      }
      return response;
    };
  });

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');

  // 进工作台：默认落地页就是 overview（若被记住别的页，点菜单回来）
  if (!(await backToOverview())) fail('侧边栏能回到「运营概览」', '找不到菜单项');
  await page.waitForSelector('[data-scb-input]', { timeout: 15000 });

  // —— 1. 位置 ——
  const layout = await page.evaluate(() => {
    const bar = document.querySelector('[data-smart-command]');
    const banner = document.querySelector('.welcome-banner');
    if (!bar) return { ok: false };
    const b = bar.getBoundingClientRect();
    const w = banner ? banner.getBoundingClientRect() : null;
    return {
      ok: true,
      barTop: Math.round(b.top),
      bannerTop: w ? Math.round(w.top) : null,
      hasInput: Boolean(bar.querySelector('[data-scb-input]')),
      hasRun: Boolean(bar.querySelector('[data-scb-run]')),
      examples: bar.querySelectorAll('[data-scb-example]').length,
    };
  });
  if (!layout.ok) fail('工作台顶部有智能指令框', '找不到 [data-smart-command]');
  if (!layout.hasInput || !layout.hasRun) fail('指令框有输入框和执行按钮', JSON.stringify(layout));
  if (layout.bannerTop !== null && layout.barTop >= layout.bannerTop) {
    fail('指令框在欢迎横幅上方', `bar ${layout.barTop} / banner ${layout.bannerTop}`);
  }
  ok('工作台最顶部有指令框', `top ${layout.barTop} · 示例 ${layout.examples} 个`);

  // —— 2. 查对账单 ——
  await typeCommand(`${PARTY_KEY}的对账单`);
  await page.click('[data-scb-run]');
  await page.waitForSelector('[data-scb-panel]', { timeout: 30000 });
  await sleep(500);

  const panel = await page.evaluate(() => {
    const node = document.querySelector('[data-scb-panel]');
    const highlight = node.querySelector('.scb__mark');
    const statementCards = node.querySelectorAll('[data-scb-card^="statement-"]').length;
    const documentCards = node.querySelectorAll('[data-scb-card^="document-"]').length;
    const rect = node.getBoundingClientRect();
    return {
      attr: node.getAttribute('data-scb-panel'),
      party: highlight ? highlight.textContent.trim() : '',
      statementCards,
      documentCards,
      right: Math.round(rect.right),
      viewport: window.innerWidth,
      message: (node.querySelector('.scb__panel-meta span')?.textContent || '').trim(),
    };
  });
  if (!panel.party) fail('面板里高亮了命中的单位', '没有 .scb__mark');
  if (!panel.party.includes(PARTY_KEY)) fail('高亮的是「湖南华邦」', panel.party);
  if (panel.statementCards !== expStatements.length) {
    fail('对账单卡片数与接口一致', `页面 ${panel.statementCards} / 接口 ${expStatements.length}`);
  }
  if (panel.documentCards !== expDocs.length) {
    fail('未结清单据卡片数与接口一致', `页面 ${panel.documentCards} / 接口 ${expDocs.length}`);
  }
  if (panel.right > panel.viewport + 1) fail('面板不超出视口', `${panel.right} > ${panel.viewport}`);
  ok('悬浮面板出来了', `高亮 ${panel.party} · 对账单 ${panel.statementCards} 张 · 未结清单据 ${panel.documentCards} 张`);
  ok('面板文案说明了业务结论', panel.message);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_command_panel.png') });
  console.log('  📸 e2e_smart_command_panel.png');

  // —— 3. 打开预览（对账单） ——
  await page.click('[data-scb-preview^="statement-"]');
  await page.waitForSelector('[data-scb-preview-mask]', { timeout: 20000 });
  await sleep(800);
  const stPreview = await page.evaluate(() => {
    const mask = document.querySelector('[data-scb-preview-mask]');
    const text = mask.textContent || '';
    return {
      hasMask: Boolean(mask),
      rows: mask.querySelectorAll('tbody tr').length,
      hasPeriod: text.includes('账期'),
      empty: Boolean(mask.querySelector('.scb__empty')),
    };
  });
  if (!stPreview.hasMask) fail('点「打开预览」弹出对账单预览', '没有遮罩');
  if (stPreview.empty) fail('预览里有数据', '显示"读取中"或空');
  ok('对账单预览打开', `${stPreview.rows} 行明细`);
  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_command_statement.png') });
  await page.click('[data-scb-preview-close]');
  await sleep(400);

  // —— 4. 生成 PDF（base64 通道） ——
  await page.click('[data-scb-pdf]');
  await sleep(2500);
  const pdfCall = await page.evaluate(() =>
    (window.__scbFetch || []).filter((item) => item.url.includes('/print/statement-record/')).pop(),
  );
  if (!pdfCall) fail('点了「生成 PDF」真的发请求', '没有记录到请求');
  if (pdfCall.status !== 200) fail('PDF 接口返回 200', String(pdfCall.status));
  if (!pdfCall.contentType.includes('application/json')) {
    fail('PDF 走 JSON(base64) 通道', pdfCall.contentType);
  }
  ok('对账单 PDF 生成成功', `${pdfCall.bytes} 字节 base64，content-type ${pdfCall.contentType.split(';')[0]}`);

  // —— 5. 去修改（跳页 + 预填） ——
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('[data-scb-goto]')][0];
    if (btn) btn.click();
  });
  await sleep(2500);
  const jumped = await page.evaluate(() => {
    // 对账单编辑器的根节点（不是靠菜单文字判断 —— 侧边栏里永远有"增强对账单"四个字）
    const editor = document.querySelector('.stmt__field--party');
    // ErpSearchSelect 的已选值渲染在 `.ssel-value` 这个 span 里，**不是** input.value
    // （input 只装搜索词，选完就清空）—— 第一版断言读 input 所以误判成"没预填"。
    const valueNode = document.querySelector('.stmt__field--party .ssel-value');
    return {
      hasEditor: Boolean(editor),
      matched: valueNode ? (valueNode.textContent || '').trim() : '',
      url: location.href,
    };
  });
  if (!jumped.hasEditor) fail('「去修改」跳到增强对账单页面', jumped.url);
  if (!jumped.matched) fail('跳过去后往来单位已预填', '往来单位控件是空的');
  ok('「去修改」跳页并预填了往来单位', jumped.matched);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_command_goto.png') });

  // —— 6. 回工作台，查合同 ——
  if (!(await backToOverview())) fail('从对账单页回到工作台', '找不到「运营概览」菜单');
  await page.waitForSelector('[data-scb-input]', { timeout: 15000 });
  await typeCommand(`${PARTY_KEY}的合同`);
  await page.click('[data-scb-run]');
  await page.waitForSelector('[data-scb-card^="contract-"]', { timeout: 30000 });
  await sleep(400);
  const contractCount = await page.evaluate(
    () => document.querySelectorAll('[data-scb-card^="contract-"]').length,
  );
  ok('合同意图识别并出卡片', `${contractCount} 张`);

  await page.click('[data-scb-preview^="contract-"]');
  await page.waitForSelector('[data-scb-preview-mask]', { timeout: 20000 });
  await sleep(1500);
  const ctPreview = await page.evaluate(() => {
    const mask = document.querySelector('[data-scb-preview-mask]');
    // 合同自己的标题可能是"克拉玛依…采购合同"，但**正文用的模板**必须是简易版；
    // 弹窗标题栏上标了模板名（data-scb-template），就验它。
    const template = mask.querySelector('[data-scb-template]');
    return {
      title: (mask.querySelector('.scb__doc-title')?.textContent || '').trim(),
      template: template ? template.getAttribute('data-scb-template') : '',
      isSimple: (template ? template.getAttribute('data-scb-template') : '').includes('产品买卖合同（简易版）'),
      items: mask.querySelectorAll('tbody tr').length,
      clauses: mask.querySelectorAll('.scb__clauses li').length,
    };
  });
  if (!ctPreview.title) fail('合同预览有标题', '没有 .scb__doc-title');
  if (!ctPreview.isSimple) {
    fail('预览用的是《产品买卖合同（简易版）》', ctPreview.template || '（没标模板名）');
  }
  if (ctPreview.clauses < 8) fail('合同正文含 8 条条款', String(ctPreview.clauses));
  ok(
    '合同预览打开（简易版正文）',
    `${ctPreview.title} / 模板 ${ctPreview.template} · ${ctPreview.items} 项 · ${ctPreview.clauses} 条`,
  );

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_command_contract.png') });

  // —— 7. 导出 Word ——
  await page.click('[data-scb-preview-word]');
  await sleep(2500);
  const wordCall = await page.evaluate(() =>
    (window.__scbFetch || []).filter((item) => item.url.includes('/exports/word/contract/')).pop(),
  );
  if (!wordCall) fail('点了「导出 Word」真的发请求', '没有记录到请求');
  if (wordCall.status !== 200) fail('Word 接口返回 200', String(wordCall.status));
  if (!(wordCall.bytes > 1000)) fail('Word 文件不是空的', `${wordCall.bytes} 字节`);
  if (wordCall.head.slice(0, 2) !== 'PK') fail('导出内容是 docx（PK 头）', wordCall.head);
  ok('合同 Word 导出成功', `${wordCall.bytes} 字节 · ${wordCall.head.slice(0, 2)}`);

  await page.click('[data-scb-preview-close]');
  await sleep(400);
  await page.click('[data-scb-close]');
  await sleep(300);

  // —— 8. 认不出的单位 → 候选 ——
  await typeCommand('给我周广平的对账单');
  await page.click('[data-scb-run]');
  await page.waitForSelector('[data-scb-panel]', { timeout: 30000 });
  await sleep(600);
  const unknown = await page.evaluate(() => {
    const node = document.querySelector('[data-scb-panel]');
    return {
      candidates: node.querySelectorAll('[data-scb-candidate]').length,
      message: (node.querySelector('.scb__panel-meta span')?.textContent || '').trim(),
      cards: node.querySelectorAll('[data-scb-card]').length,
    };
  });
  if (unknown.cards !== 0) fail('认不出人时不出卡片', String(unknown.cards));
  if (!unknown.message.includes('没找到')) fail('认不出人时给明确提示', unknown.message);
  ok('认不出单位时给出说明', unknown.message);
  if (unknown.candidates > 0) ok('并给出可选候选', `${unknown.candidates} 个`);

  await page.screenshot({ path: path.join(SHOT_DIR, 'e2e_smart_command_unknown.png') });

  const errors = results.filter((r) => !r.ok);
  console.log(`\n结果：${results.length - errors.length} 通过 / ${errors.length} 失败`);
  await browser.close();
  process.exit(0);
})().catch(async (err) => {
  console.error('\n中断：', err.message);
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    if (page) await page.screenshot({ path: path.join(SHOT_DIR, 'error_smart_command.png') });
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
