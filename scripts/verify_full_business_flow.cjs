/**
 * 全流程业务闭环自测（v185 打包版）—— 真实浏览器 + 真实后端
 *
 * 覆盖《测试操作向导》1~18 步：
 *   基础资料（UI 弹窗，含 409 红字与相似名黄框）→ 期初 → 采购链 → 销售链
 *   → 收款 → 反审核拦截 → 未结清拦截 → 发票挂单（UI 下拉）→ 完结 → 对账单生成/导出
 *
 * 设计取舍（写清楚免得被当成"没按 UI 点"）：
 *   · **建客户 / 建商品走 UI 弹窗** —— 这两步正是防呆规则所在，必须真点。
 *   · 单据链（订单→审核→转单→收款）走 API：UI 上这些表单有二十多个字段和联动下拉，
 *     逐格点会让脚本脆到每次改样式就红；这些规则本身在服务端，前端只是入口。
 *     每一步的**业务结果**都会回读接口 + 打开库存页核对，结果不对一样算失败。
 *   · 反审核 / 完结 / 发票挂单 / 对账单导出走 UI 或按 UI 等价的接口，并在报告里注明。
 *
 * 用法：
 *   BASE=http://127.0.0.1:8019 node scripts/verify_full_business_flow.cjs
 *   失败会截图 docs/验收截图/error_step_<N>.png
 */
const path = require('path');
const fs = require('fs');
const WS = 'C:/Users/admi/.workbuddy/binaries/node/workspace/node_modules';
const puppeteer = require(path.join(WS, 'puppeteer-core'));

const CHROME = 'C:/Users/admi/AppData/Local/Google/Chrome/Application/chrome.exe';
const BASE = process.env.BASE || 'http://127.0.0.1:8019';
const SHOT_DIR = 'E:/AI/ERP软件/docs/验收截图';
const DOWNLOAD_DIR = 'C:\\Users\\admi\\AppData\\Local\\Temp\\erp_e2e_dl';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const TAG = Date.now().toString().slice(-5);
const CUSTOMER = `测试客户-甲${TAG}`;
const PRODUCT = `测试商品-劳保鞋${TAG}`;
const UNIT_PRICE_PURCHASE = 80; // 每箱采购价
const UNIT_PRICE_SALE = 120; // 每箱售价
const OPENING_QTY = 100; // 双

const results = [];
let page;
let browser;

function pass(name, extra = '') {
  results.push({ name, ok: true, extra });
  console.log(`PASS: ${name}${extra ? `  — ${extra}` : ''}`);
}
function fail(name, reason) {
  results.push({ name, ok: false, extra: reason });
  console.log(`FAIL: ${name}  — ${reason}`);
}
function assert(cond, name, extra = '') {
  if (cond) pass(name, extra);
  else throw new Error(`断言失败：${name}${extra ? `（${extra}）` : ''}`);
}

async function shot(step) {
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    const file = path.join(SHOT_DIR, `error_step_${step}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`  已截图：${file}`);
  } catch (err) {
    console.log(`  截图失败：${err.message}`);
  }
}

/** 关键节点的成功快照：交付时给客户看的是这些，不是黑屏的报错图 */
async function shotOk(step, tag) {
  try {
    if (!fs.existsSync(SHOT_DIR)) fs.mkdirSync(SHOT_DIR, { recursive: true });
    const file = path.join(SHOT_DIR, `e2e_step${String(step).padStart(2, '0')}-${tag}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`  📸 ${path.basename(file)}`);
  } catch (err) {
    console.log(`  截图失败：${err.message}`);
  }
}

/* ── HTTP 工具（绕开本机代理） ─────────────────────────────────────────── */
let TOKEN = '';
async function api(method, url, body) {
  const res = await fetch(`${BASE}${url}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) },
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

/* ── 浏览器小工具 ──────────────────────────────────────────────────────── */
const clickText = (text, scope = 'button') =>
  page.evaluate(
    (t, sel) => {
      const el = [...document.querySelectorAll(sel)].find((e) => (e.textContent || '').trim() === t);
      if (el) {
        el.click();
        return true;
      }
      return false;
    },
    text,
    scope,
  );

const openMenu = async (labels) => {
  // 自愈式：先直接找；找不到再点开分组标题重试。
  // ⚠️ 不能无脑"点开所有分组"—— 分组本来就是展开的时候，那一下反而把它们**全部折叠**，
  //    菜单项直接从 DOM 里消失（2026-10-22 就是这样假红在 STEP16 的：页面停在库存管理）。
  // 参数可以是单个名称或一组候选：菜单名在「系统设置 → 菜单管理」里是可以改的
  // （「发票管理」就被改成了「开票管理」），脚本钉死一个名字必然某天假红。
  const wanted = Array.isArray(labels) ? labels : [labels];
  const clickItem = () =>
    page.evaluate((names) => {
      const items = [...document.querySelectorAll('.nav-item')];
      for (const name of names) {
        const hit = items.find((e) => (e.textContent || '').trim() === name);
        if (hit) {
          hit.click();
          return true;
        }
      }
      return false;
    }, wanted);

  let found = await clickItem();
  if (!found) {
    await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
    await sleep(700);
    found = await clickItem();
  }
  await sleep(1800);
  return found;
};

/** 在弹窗里按 label 文字找输入框并填值（React 受控组件要派发 input 事件） */
async function fillModalField(labelRe, value) {
  return page.evaluate(
    (re, val) => {
      const modal = document.querySelector('.modal-card');
      if (!modal) return 'no-modal';
      const labels = [...modal.querySelectorAll('label')];
      const target = labels.find((l) => new RegExp(re).test(l.textContent || ''));
      if (!target) return 'no-label';
      const input = target.querySelector('input, textarea');
      if (!input) return 'no-input';
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, String(val));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return 'ok';
    },
    labelRe,
    value,
  );
}


/** 提交后若命中"相似名称"黄框，点「仍然新建」继续（这条路径本身就是被测特性） */
async function confirmSimilarGuardIfAny() {
  await sleep(700);
  const open = await page.evaluate(() => Boolean(document.querySelector('.name-guard-modal')));
  if (!open) return false;
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('.name-guard-modal button')].find((b) =>
      (b.textContent || '').includes('仍然新建'),
    );
    if (btn) btn.click();
  });
  await sleep(1400);
  return true;
}

async function submitTopModalForm() {
  return page.evaluate(() => {
    const modal = document.querySelector('.modal-card');
    if (!modal) return 'no-modal';
    const form = modal.querySelector('form');
    if (!form) return 'no-form';
    form.requestSubmit();
    return 'ok';
  });
}

/* ── 主流程 ────────────────────────────────────────────────────────────── */
(async () => {
  const startedAt = Date.now();
  const created = {}; // 记录 id 供清理
  const customerName = CUSTOMER;

  /* 0. 登录 + 打开浏览器 */
  const login = await api('POST', '/api/v1/auth/login', { username: 'admin', password: 'Admin123' });
  if (login.status !== 200) throw new Error(`登录失败：${login.status}`);
  TOKEN = login.data.access_token;

  const shops = await api('GET', '/api/v1/warehouses');
  const warehouse = (Array.isArray(shops.data) ? shops.data : shops.data.items || [])[0];
  assert(Boolean(warehouse), 'STEP0 找到默认仓库', `id=${warehouse && warehouse.id}`);

  const sup = await api('GET', '/api/v1/suppliers');
  const supplier = (Array.isArray(sup.data) ? sup.data : sup.data.items || [])[0];
  assert(Boolean(supplier), 'STEP0 找到默认供应商', supplier && supplier.name);

  browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1500, height: 940 },
    protocolTimeout: 180000,
  });
  page = await browser.newPage();
  page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 200)));
  // 记录发票 PATCH 的响应体：列表接口不返回 related_order_id，只能从这里确认是否真写进去
  const invoicePatches = [];
  page.on('response', async (resp) => {
    try {
      if (/\/api\/v1\/invoices\/\d+$/.test(resp.url()) && resp.request().method() === 'PATCH') {
        invoicePatches.push({ status: resp.status(), body: await resp.json() });
      }
    } catch {
      /* ignore */
    }
  });
  await page.setCacheEnabled(false);

  // 下载目录（Word 导出是前端生成的 blob）
  if (!fs.existsSync(DOWNLOAD_DIR)) fs.mkdirSync(DOWNLOAD_DIR, { recursive: true });
  const cdp = await page.target().createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DOWNLOAD_DIR });

  await page.goto(BASE, { waitUntil: 'networkidle2' });
  await page.evaluate((t) => localStorage.setItem('erp_token', t), TOKEN);
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('.nav-group-title');
  await page.evaluate(() => [...document.querySelectorAll('.nav-group-title')].forEach((e) => e.click()));
  await sleep(500);

  const ver = await api('GET', '/version.json');
  pass('STEP0 后端就绪', `${BASE} ${ver.data.cache || ''} ${ver.data.build || ''}`);

  let step = 1;
  try {
    /* ── 1. 建客户（UI） ─────────────────────────────────────────────── */
    step = 1;
    await openMenu('客户档案');
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('.ptree__row')].find((e) => (e.textContent || '').includes('全部客户'));
      if (el) el.click();
    });
    await sleep(800);
    await clickText('新增客户');
    await sleep(700);
    const f1 = await fillModalField('名称', CUSTOMER);
    assert(f1 === 'ok', 'STEP1 客户弹窗可填写', f1);
    await submitTopModalForm();
    const custGuard = await confirmSimilarGuardIfAny();
    if (custGuard) pass('STEP1 相似名确认框出现并已确认继续');
    await sleep(1200);
    const cust = (await api('GET', '/api/v1/customers')).data;
    const custRow = (Array.isArray(cust) ? cust : cust.items || []).find((c) => c.name === CUSTOMER);
    assert(Boolean(custRow), 'STEP1 客户创建成功（UI）', custRow && custRow.code);
    created.customerId = custRow.id;

    /* ── 2. 409 红字拦截（UI） ───────────────────────────────────────── */
    step = 2;
    await clickText('新增客户');
    await sleep(600);
    await fillModalField('名称', CUSTOMER);
    await submitTopModalForm();
    await sleep(900);
    const dupState = await page.evaluate(() => {
      const box = document.querySelector('.notice-box');
      return {
        text: box ? box.textContent.trim() : '',
        danger: box ? box.className.includes('danger') : false,
        modalOpen: Boolean(document.querySelector('.modal-card form')),
      };
    });
    assert(dupState.danger && /已存在/.test(dupState.text), 'STEP2 同名客户被红字拦截（409）', dupState.text.slice(0, 50));
    assert(dupState.modalOpen, 'STEP2 拦截后弹窗保持打开（不丢用户输入）');

    /* 相似名黄框（顺带验证第 2 步的软提醒） */
    await fillModalField('名称', CUSTOMER.slice(0, 5) + '二部');
    await submitTopModalForm();
    await sleep(900);
    const simOpen = await page.evaluate(() => Boolean(document.querySelector('.name-guard-modal')));
    assert(simOpen, 'STEP2b 相似名称弹出黄色确认框');
    await shotOk(2, '同名拦截红字与相似名黄框');
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.name-guard-modal button')].find((b) =>
        (b.textContent || '').includes('返回修改'),
      );
      if (btn) btn.click();
    });
    await sleep(300);
    await page.evaluate(() => {
      const btn = document.querySelector('.modal-card .close-btn');
      if (btn) btn.click();
    });
    await sleep(400);

    /* ── 3. 建商品（UI，带换算单位箱=10） ────────────────────────────── */
    step = 3;
    await openMenu('商品档案');
    // 商品页的按钮文案是「新增产品」（不是"新增商品"）—— 先按文案点，点不到再按 data 属性兜底
    let openedProduct = await clickText('新增产品');
    if (!openedProduct) {
      openedProduct = await page.evaluate(() => {
        const btn = [...document.querySelectorAll('button')].find((b) => /新增产品|新增商品/.test(b.textContent || ''));
        if (btn) {
          btn.click();
          return true;
        }
        return false;
      });
    }
    assert(openedProduct, 'STEP3 打开新增商品弹窗');
    await sleep(900);
    const f3a = await fillModalField('名称', PRODUCT);
    const f3b = await fillModalField('单位', '双');
    assert(f3a === 'ok' && f3b === 'ok', 'STEP3 商品弹窗可填写', `${f3a}/${f3b}`);
    // SKU 必填：单独按 label 找
    await page.evaluate((sku) => {
      const modal = document.querySelector('.modal-card');
      const labels = [...modal.querySelectorAll('label')];
      const target = labels.find((l) => /SKU|编码|编号/.test(l.textContent || ''));
      const input = target && target.querySelector('input');
      if (input) {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, sku);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }, `SKU-E2E-${TAG}`);
    // 辅助单位：点「＋ 添加辅助单位」→ 在 .punit-row 里填「箱 / 10」
    await page.evaluate(() => {
      const modal = document.querySelector('.modal-card');
      const btn = [...modal.querySelectorAll('button')].find((b) => /添加辅助单位/.test(b.textContent || ''));
      if (btn) btn.click();
    });
    await sleep(500);
    const unitFilled = await page.evaluate(() => {
      const modal = document.querySelector('.modal-card');
      const nameInput = modal.querySelector('.punit-row input[aria-label*="辅助单位名称"], .punit-cell-name input');
      const factorInput = modal.querySelector('.punit-cell-factor input');
      if (!nameInput || !factorInput) return 'no-unit-row';
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(nameInput, '箱');
      nameInput.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(factorInput, '10');
      factorInput.dispatchEvent(new Event('input', { bubbles: true }));
      return 'ok';
    });
    assert(unitFilled === 'ok', 'STEP3 辅助单位行可填写（箱=10）', unitFilled);
    await sleep(300);
    await submitTopModalForm();
    const prodGuard = await confirmSimilarGuardIfAny();
    if (prodGuard) pass('STEP3 相似名确认框出现并已确认继续（「劳保鞋」包含匹配）');
    await sleep(1500);
    const prods = (await api('GET', '/api/v1/products')).data;
    const prodRow = (Array.isArray(prods) ? prods : prods.items || []).find((p) => p.name === PRODUCT);
    assert(Boolean(prodRow), 'STEP3 商品创建成功（UI）', prodRow && prodRow.sku);
    created.productId = prodRow.id;
    const units = await api('GET', `/api/v1/products/${prodRow.id}/units`).catch(() => ({ data: null }));
    const unitList = Array.isArray(units.data) ? units.data : (units.data && units.data.items) || [];
    // 辅助单位接口可能不存在 → 不硬失败，但记录
    if (unitList.length) {
      const box = unitList.find((u) => u.unit_name === '箱' && Number(u.factor) === 10);
      assert(Boolean(box), 'STEP3 辅助单位「箱=10」已保存', JSON.stringify(unitList.map((u) => `${u.unit_name}×${u.factor}`)));
    } else {
      pass('STEP3 辅助单位接口未暴露（跳过数量校验）', '后续用「箱」下单会验证换算是否生效');
    }

    /* ── 4. 期初 100 双（API） ──────────────────────────────────────── */
    step = 4;
    const opening = await api('PUT', '/api/v1/opening-stock', {
      items: [{ warehouse_id: warehouse.id, product_id: prodRow.id, quantity: OPENING_QTY, unit_price: 60 }],
    });
    assert(opening.status === 200, 'STEP4 期初库存写入成功', JSON.stringify(opening.data).slice(0, 60));
    const stock1 = await api('GET', `/api/v1/inventory/stock?product_id=${prodRow.id}`);
    const q1 = (stock1.data.rows || []).reduce((s, r) => s + Number(r.quantity || 0), 0);
    assert(q1 === OPENING_QTY, 'STEP4 现存量 = 100 双', String(q1));

    /* ── 5. 采购订单（API） ─────────────────────────────────────────── */
    step = 5;
    const po = await api('POST', '/api/v1/purchase-orders', {
      supplier_id: supplier.id,
      warehouse_id: warehouse.id,
      doc_type: 'order',
      order_date: new Date().toISOString().slice(0, 10),
      items: [
        { product_id: prodRow.id, quantity: 2, unit_price: UNIT_PRICE_PURCHASE, unit: '箱', product_name: PRODUCT },
      ],
    });
    assert(po.status === 201, 'STEP5 采购订单创建（2 箱）', `status=${po.status}`);
    created.purchaseOrderId = po.data.id;

    /* ── 6. 未审核不能转单（负向断言） ─────────────────────────────── */
    step = 6;
    const earlyConvert = await api('POST', `/api/v1/purchase-orders/${po.data.id}/to-inbound`);
    assert(earlyConvert.status === 409, 'STEP6 未审核转单被拒（409）', String(earlyConvert.status));

    /* ── 7. 审核 → 转单 ─────────────────────────────────────────────── */
    step = 7;
    const approved = await api('PATCH', `/api/v1/purchase-orders/${po.data.id}/status`, { status: 'approved' });
    assert(approved.status === 200, 'STEP7 采购订单审核通过', approved.data && approved.data.status);
    const inbound = await api('POST', `/api/v1/purchase-orders/${po.data.id}/to-inbound`);
    assert(inbound.status === 200, 'STEP7 转采购入库单成功', inbound.data && inbound.data.order_no);
    created.purchaseInboundId = inbound.data.id;
    assert((inbound.data.status || '') === 'submitted', 'STEP7 入库单直接落账（已提交）', inbound.data.status);

    /* ── 8. 库存 +20 双 ─────────────────────────────────────────────── */
    step = 8;
    const stock2 = await api('GET', `/api/v1/inventory/stock?product_id=${prodRow.id}`);
    const q2 = (stock2.data.rows || []).reduce((s, r) => s + Number(r.quantity || 0), 0);
    assert(q2 === OPENING_QTY + 20, 'STEP8 入库后库存 = 120 双（2箱×10）', String(q2));

    /* ── 9. 应付款产生 ──────────────────────────────────────────────── */
    step = 9;
    // 应付款：按供应商取「应付汇总」（没有 /finance/transactions 这个路由，
    // 按单号筛是在 /finance/ledger 里做的；用汇总口径更稳）
    const payable = await api('GET', '/api/v1/finance/payable');
    const payRows = Array.isArray(payable.data) ? payable.data : (payable.data && payable.data.items) || [];
    const supRow = payRows.find((r) => Number(r.party_id ?? r.id) === Number(supplier.id));
    const paySum = Number((supRow && (supRow.balance ?? supRow.amount ?? supRow.debt)) || 0);
    assert(paySum >= 2 * UNIT_PRICE_PURCHASE - 0.01, 'STEP9 应付余额增加', `¥${paySum}`);

    /* ── 10. 销售订单 → 审核 → 转单 ─────────────────────────────────── */
    step = 10;
    const so = await api('POST', '/api/v1/sales-orders', {
      customer_id: custRow.id,
      warehouse_id: warehouse.id,
      doc_type: 'order',
      order_date: new Date().toISOString().slice(0, 10),
      items: [
        { product_id: prodRow.id, quantity: 1, unit_price: UNIT_PRICE_SALE, unit: '箱', product_name: PRODUCT },
      ],
    });
    assert(so.status === 201, 'STEP10 销售订单创建（1 箱）', `status=${so.status}`);
    created.salesOrderId = so.data.id;
    const soApproved = await api('PATCH', `/api/v1/sales-orders/${so.data.id}/status`, { status: 'approved' });
    assert(soApproved.status === 200, 'STEP10 销售订单审核通过');
    const outbound = await api('POST', `/api/v1/sales-orders/${so.data.id}/to-outbound`);
    assert(outbound.status === 200, 'STEP10 转销售出库单成功', outbound.data && outbound.data.order_no);
    created.outboundId = outbound.data.id;

    /* ── 11. 库存 −10 双 ───────────────────────────────────────────── */
    step = 11;
    const stock3 = await api('GET', `/api/v1/inventory/stock?product_id=${prodRow.id}`);
    const q3 = (stock3.data.rows || []).reduce((s, r) => s + Number(r.quantity || 0), 0);
    assert(q3 === OPENING_QTY + 10, 'STEP11 出库后库存 = 110 双', String(q3));

    /* 再用人眼看一遍：打开库存页搜这个商品，页面上的数字必须是 110。
       （接口对、页面错是老毛病，只信接口等于放过渲染层） */
    await openMenu('库存管理');
    await sleep(1200);
    const uiStock = await page.evaluate(async (name) => {
      const input = [...document.querySelectorAll('input')].find((i) =>
        /搜索现存量/.test(i.getAttribute('placeholder') || ''),
      );
      if (!input) return { ok: false, reason: 'no-input' };
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, name);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return { ok: true };
    }, PRODUCT);
    await sleep(1800);
    const uiStockText = uiStock.ok ? await page.evaluate(() => document.body.innerText || '') : '';
    assert(
      uiStock.ok && uiStockText.includes(PRODUCT) && /110/.test(uiStockText),
      'STEP11 库存页面上也显示 110',
      uiStock.ok ? '' : uiStock.reason,
    );
    await shotOk(11, '库存页-测试商品110双');

    /* ── 12. 部分收款 ──────────────────────────────────────────────── */
    step = 12;
    const half = await api('POST', '/api/v1/finance/receipt', {
      party_id: custRow.id,
      amount: UNIT_PRICE_SALE / 2,
      order_id: outbound.data.id,
      occurred_at: new Date().toISOString().slice(0, 10),
      note: 'E2E 部分收款',
    });
    assert(half.status === 201, 'STEP12 部分收款登记成功', `¥${UNIT_PRICE_SALE / 2}`);
    const afterPay = await api('GET', '/api/v1/sales-orders');
    const obRow = (Array.isArray(afterPay.data) ? afterPay.data : afterPay.data.items || []).find(
      (o) => o.id === outbound.data.id,
    );
    assert(Number(obRow.received_amount) > 0, 'STEP12 出库单已收金额回写', `已收 ${obRow.received_amount}`);

    /* ── 13. 反审核拦截 ────────────────────────────────────────────── */
    step = 13;
    const unsubmit = await api('PATCH', `/api/v1/sales-orders/${outbound.data.id}/status`, { status: 'draft' });
    assert(unsubmit.status === 409, 'STEP13 出库单反审核被拦截（409）', JSON.stringify(unsubmit.data).slice(0, 60));

    /* ── 14. 未结清不能完结 ────────────────────────────────────────── */
    step = 14;
    const complete1 = await api('PATCH', `/api/v1/sales-orders/${outbound.data.id}/status`, { status: 'completed' });
    const detail1 = complete1.data && complete1.data.detail;
    assert(complete1.status === 409, 'STEP14 未结清完结被拦截（409）', String(complete1.status));
    const msg1 = typeof detail1 === 'object' ? detail1.message : String(detail1 || '');
    assert(/未收|未开票|not_settled/.test(msg1), 'STEP14 拦截原因是钱票未清', msg1.slice(0, 40));

    /* ── 15. 收齐尾款 ──────────────────────────────────────────────── */
    step = 15;
    const rest = await api('POST', '/api/v1/finance/receipt', {
      party_id: custRow.id,
      amount: UNIT_PRICE_SALE / 2,
      order_id: outbound.data.id,
      occurred_at: new Date().toISOString().slice(0, 10),
      note: 'E2E 尾款',
    });
    assert(rest.status === 201, 'STEP15 尾款收齐');
    const afterRest = await api('GET', '/api/v1/sales-orders');
    const obRow2 = (Array.isArray(afterRest.data) ? afterRest.data : afterRest.data.items || []).find(
      (o) => o.id === outbound.data.id,
    );
    assert(Number(obRow2.current_debt) < 0.01, 'STEP15 欠款清零', `欠款 ${obRow2.current_debt}`);

    /* ── 16. 发票：新建 + UI 下拉挂单 ──────────────────────────────── */
    step = 16;
    const inv = await api('POST', '/api/v1/invoices', {
      invoice_no: `E2E-INV-${TAG}`,
      invoice_type: '普票',
      issue_date: new Date().toISOString().slice(0, 10),
      buyer_name: custRow.name,
      seller_name: '西安寨卡信息技术有限公司',
      total_amount: UNIT_PRICE_SALE,
      direction: 'output',
      status: '正常',
    });
    assert(inv.status === 201 || inv.status === 200, 'STEP16 新建销项发票', `status=${inv.status}`);
    const invList = (await api('GET', '/api/v1/invoices')).data;
    const invRow = (invList.items || invList).find((x) => x.invoice_no === `E2E-INV-${TAG}`);
    assert(Boolean(invRow), 'STEP16 发票出现在列表', invRow && `#${invRow.id}`);
    created.invoiceId = invRow.id;

    /* ⚠️ 必须先刷新页面：出库单是刚用 API 建的，而页面的 `salesOrders` 是**打开时**拉的，
       不刷新的话下拉里根本没有这张新单 —— 只会匹配到同号的旧单（E2E 实拍：挂到了 7827）。
       号码会复用：删掉的单释放了流水号，下一次建单还是同一个号。 */
    await page.reload({ waitUntil: 'networkidle2' });
    await sleep(1500);
    // UI：发票管理 → 编辑 → 关联出库单下拉 → 保存（openMenu 自己会按需展开分组）
    await openMenu(['发票管理', '开票管理']);
    const opened = await page.evaluate((no) => {
      const tr = [...document.querySelectorAll('tbody tr')].find((r) => (r.textContent || '').includes(no));
      if (!tr) return false;
      const btn = [...tr.querySelectorAll('button')].find((b) => /编辑/.test(b.textContent || ''));
      if (!btn) return false;
      btn.click();
      return true;
    }, `E2E-INV-${TAG}`);
    assert(opened, 'STEP16 打开发票编辑弹窗（UI）');
    await sleep(800);
    const hasPicker = await page.evaluate(() =>
      [...document.querySelectorAll('.modal-card label')].some((l) => /关联出库单/.test(l.textContent || '')),
    );
    assert(hasPicker, 'STEP16 弹窗里有「关联出库单（销项）」下拉');
    // 点开下拉并选第一条出库单
    /* ErpSearchSelect 的真实结构（看源码 `ssel-*`）：
       `.ssel-trigger` 点开 → 面板是 **portal 到 body** 的 `.ssel-panel`，
       选项在 `.ssel-option` 里。点 label 可能触发两次 toggle（label 自身也会激活），
       所以这里做成"打开→找选项→找不到就再开一次"的幂等重试。
       另外**不靠打字过滤**：面板里第一屏就有我们刚建的单，直接按单号匹配更稳。 */
    const orderNo = outbound.data.order_no;
    const openPicker = async () => {
      await page.evaluate(() => {
        const label = [...document.querySelectorAll('.modal-card label')].find((l) => /关联出库单/.test(l.textContent || ''));
        const trigger = label && label.querySelector('.ssel-trigger');
        if (trigger) trigger.click();
      });
      await sleep(600);
    };
    let chosen = '（未打开）';
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const opts = await page.evaluate(() =>
        [...document.querySelectorAll('.ssel-panel .ssel-option')].map((o) => (o.textContent || '').replace(/\s+/g, ' ').trim()),
      );
      if (!opts.length) {
        await openPicker();
        continue;
      }
      // ⚠️ 选项是用 **onMouseDown** 提交的（组件为了抢在 blur 之前），
      //    所以合成 `click()` 不会选中 —— 必须走真实鼠标坐标。
      const box = await page.evaluate((no) => {
        const opts = [...document.querySelectorAll('.ssel-panel .ssel-option')];
        const hit = opts.find((o) => (o.textContent || '').includes(no)) || opts[0];
        if (!hit) return null;
        const r = hit.getBoundingClientRect();
        return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), text: (hit.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 48) };
      }, orderNo);
      if (!box) break;
      await page.mouse.click(box.x, box.y);
      chosen = box.text;
      break;
    }
    await sleep(400);
    await sleep(400);
    await submitTopModalForm();
    await sleep(1200);
    // 列表接口**不返回** related_order_id（只在内部算未开票金额时用），
    // 所以用写接口的回包来确认；真正的功能证明在 STEP17 的"完结成功"。
    const patched = invoicePatches.filter((x) => x.status === 200).pop();
    const patchedRel = patched && patched.body ? patched.body.related_order_id : undefined;
    assert(
      Number(patchedRel) === Number(outbound.data.id),
      'STEP16 发票已挂到该出库单',
      `PATCH 回包 related_order_id=${patchedRel} 期望=${outbound.data.id}（选中：${chosen}）`,
    );

    /* ── 17. 完结成功 ──────────────────────────────────────────────── */
    step = 17;
    const complete2 = await api('PATCH', `/api/v1/sales-orders/${outbound.data.id}/status`, { status: 'completed' });
    assert(complete2.status === 200, 'STEP17 钱票两清后完结成功', complete2.data && complete2.data.status);
    assert((complete2.data.status || '') === 'completed', 'STEP17 单据状态 = 已完成');

    /* ── 18. 对账单：生成 + 导出 ───────────────────────────────────── */
    step = 18;
    await openMenu('增强对账单');
    await sleep(1500);

    /* 第 18 步按向导走完整 UI：切视角 → 选往来单位 → 填期间 → 生成草稿 → 导出 Word。
       （之前想"API 生成 + UI 载入"，但「载入已存对账单」列表只给当前 scope 的，
        跨 scope 拿不到刚建的那张；直接走生成路径反而更贴近用户操作。）

       ⚠️ 三个被踩过的坑，写在这里免得下次重犯：
       1. 「增强对账单」默认落在 scope=all（台账视角），这一屏**没有**往来单位输入框，
          只有一个提示条"要新开一张，先切到「应收」或「应付」"。不点页签就永远选不到客户。
       2. 不能写 `document.querySelector('.ssel')` —— 右侧「载入已存对账单」也是 ssel，
          DOM 顺序还更靠前，抓错了就会"下拉打开但候选为空"。必须限定 `.stmt__field--party`。
       3. `.ssel-option` 用 onMouseDown 提交，合成的 click() 无效，只能走真实坐标点击。 */
    // ① 切到「应收」视角
    const switched = await page.evaluate(() => {
      const tab = document.querySelector('.stmt__seg-btn[data-scope="out"]');
      if (!tab) return false;
      tab.click();
      return true;
    });
    assert(switched, 'STEP18 切到「应收」视角（往来单位框只在收/付视角出现）');
    await sleep(900);

    // ② 往来单位：点开 `.stmt__field--party` 里的 ssel，按客户名筛，真实坐标选
    const partyOpened = await page.evaluate(() => {
      const box = document.querySelector('.stmt__field--party .ssel');
      const trigger = box && box.querySelector('.ssel-trigger');
      if (!trigger) return false;
      trigger.click();
      return true;
    });
    assert(partyOpened, 'STEP18 打开往来单位下拉');
    await sleep(500);
    await page.evaluate((name) => {
      const input = document.querySelector('.stmt__field--party .ssel-input');
      if (!input) return;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(input, name);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, customerName);
    await sleep(700);
    const partyBox = await page.evaluate((name) => {
      const panels = [...document.querySelectorAll('.ssel-panel')];
      const opts = panels.flatMap((p) => [...p.querySelectorAll('.ssel-option')]);
      const hit = opts.find((o) => (o.textContent || '').includes(name));
      if (!hit) return null;
      const r = hit.getBoundingClientRect();
      return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
    }, customerName);
    assert(Boolean(partyBox), 'STEP18 选中往来单位', customerName);
    await page.mouse.click(partyBox.x, partyBox.y);
    await sleep(600);
    const partyShown = await page.evaluate(() => {
      const box = document.querySelector('.stmt__field--party');
      return box ? (box.textContent || '').trim() : '';
    });
    assert(partyShown.includes(customerName), 'STEP18 往来单位已回显', partyShown.slice(0, 40));

    // ② 期间
    await page.evaluate(({ from, to }) => {
      const set = (el, v) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      };
      const a = document.querySelector('input[aria-label="对账期间开始"]');
      const b = document.querySelector('input[aria-label="对账期间结束"]');
      if (a) set(a, from);
      if (b) set(b, to);
    }, { from: new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10), to: new Date().toISOString().slice(0, 10) });
    await sleep(300);

    // ③ 搜索预览 → 确认生成（2026-10-22 拆成两步：先看后写）
    //    旧版只有一个「生成草稿」，点一下当场占掉一个 DZ 单号；
    //    现在「🔍 搜索预览」只读，必须再点「确认生成对账单」才落库。
    const previewClicked = await page.evaluate(() => {
      const btn = document.querySelector('[data-stmt-preview]');
      if (!btn) return false;
      btn.click();
      return true;
    });
    assert(previewClicked, 'STEP18 点击「🔍 搜索预览」（只读预览）');
    await sleep(2600);

    const beforeGen = await api('GET', '/api/v1/statements');
    const beforeList = Array.isArray(beforeGen.data) ? beforeGen.data : (beforeGen.data && beforeGen.data.items) || [];
    assert(
      !beforeList.some((row) => row.party_name === customerName),
      'STEP18 预览不写库（此时服务端还查不到这家客户的对账单）',
    );

    const confirmBtn = await page.$('[data-stmt-confirm]');
    assert(Boolean(confirmBtn), 'STEP18 预览后出现「确认生成对账单」按钮');
    await page.click('[data-stmt-confirm]');
    await sleep(3000);
    const stRows = await api('GET', '/api/v1/statements');
    const stList = Array.isArray(stRows.data) ? stRows.data : (stRows.data && stRows.data.items) || [];
    const madeStmt = stList.find((x) => x.party_name === customerName);
    const stId = madeStmt ? madeStmt.id : null;
    assert(Boolean(stId), 'STEP18 生成对账单草稿（服务端可查）', madeStmt && madeStmt.statement_no);
    created.statementId = stId;
    const prev = await api('GET', `/api/v1/statements/${stId}/preview`);
    const rows = (prev.data && prev.data.rows) || [];
    assert(rows.length > 0, 'STEP18 对账单预览有明细', `${rows.length} 行`);

    /* 业务口径断言：全额开票（¥120）+ 全额收款（¥120）→ 本期已开票 120、期末应收 0。
       这一条是 2026-10-22 修掉的真实 bug 的护栏：
       生成接口原来用 `Invoice.direction == direction`（output vs out），永远不成立，
       于是"本期已开票"恒为 0，期末应收变成 −120（看着像客户多付了钱）。 */
    const stDetail = await api('GET', `/api/v1/statements/${stId}`);
    const detail = stDetail.data || {};
    const invoiced = Number(detail.invoiced_amount || 0);
    const receivable = Number(detail.receivable_balance || 0);
    assert(Math.abs(invoiced - UNIT_PRICE_SALE) < 0.01, 'STEP18 本期已开票 = ¥120（发票进了对账单）', `¥${invoiced}`);
    assert(Math.abs(receivable) < 0.01, 'STEP18 期末应收 = ¥0（开票与收款两清）', `¥${receivable}`);

    // 生成后前端必须无红字（生成失败只在 banner 里提示，不抛异常）
    const stmtErr = await page.evaluate(() => {
      const box = document.querySelector('.stmt__alert--error');
      return box ? (box.textContent || '').trim() : '';
    });
    assert(!stmtErr, 'STEP18 生成过程无报错横幅', stmtErr.slice(0, 60));

    // ④ 导出 Word（前端生成 blob → 浏览器下载）。未载入对账单时这个按钮是 disabled，
    //    所以下载是否真的落地本身就是"生成 + 导出"两步都成功的证据。
    // ⚠️ 不能用「跑前跑后目录差集」判断：对账单号在同一天是稳定的（DZ2026xxxx0001），
    //    重跑时文件名一模一样，Chrome 会**原地覆盖**，差集恒为空 → 假红。
    //    改成导出前把这个专用下载目录清空，跑完只看"有没有 docx"。
    if (fs.existsSync(DOWNLOAD_DIR)) {
      for (const f of fs.readdirSync(DOWNLOAD_DIR)) {
        try {
          fs.unlinkSync(path.join(DOWNLOAD_DIR, f));
        } catch {
          /* 被占用就算了 */
        }
      }
    }
    const exportEnabled = await page.evaluate(() => {
      const btn = document.querySelector('[data-word-export="statement"]');
      return Boolean(btn) && !btn.disabled;
    });
    assert(exportEnabled, 'STEP18 「导出 Word」按钮已可用（对账单已载入）');
    const exported = await clickText('导出 Word');
    assert(exported, 'STEP18 点击「导出 Word」');
    await sleep(6000);
    const fresh = (fs.existsSync(DOWNLOAD_DIR) ? fs.readdirSync(DOWNLOAD_DIR) : []).filter(
      (f) => !f.endsWith('.crdownload'),
    );
    const docx = fresh.find((f) => /\.docx$/i.test(f));
    const docxSize = docx ? fs.statSync(path.join(DOWNLOAD_DIR, docx)).size : 0;
    if (!docx) {
      const why = await page.evaluate(() => {
        const box = document.querySelector('.stmt__alert--error');
        return box ? (box.textContent || '').trim() : '（页面无报错横幅，可能是浏览器下载被拦）';
      });
      throw new Error(`断言失败：STEP18 导出 Word 文件已落地且非空（${why}）`);
    }
    assert(docxSize > 1024, 'STEP18 导出 Word 文件已落地且非空', `${docx} · ${docxSize} B`);
    await shotOk(18, '对账单已生成并导出Word');

    /* 汇总 */
    const passed = results.filter((r) => r.ok).length;
    const failed = results.filter((r) => !r.ok);
    console.log(`\n===== 结果：${passed} 通过 / ${failed.length} 失败，用时 ${((Date.now() - startedAt) / 1000).toFixed(1)}s =====`);
    if (failed.length) failed.forEach((f) => console.log(`  FAIL ${f.name} — ${f.extra}`));
  } catch (err) {
    console.error(`\nERROR at STEP ${step}: ${err.message}`);
    console.error(err.stack);
    await shot(step);
    throw err;
  } finally {
    /* ── 清理：按 ID 删单据/流水，再交给 clean_test_data.py 兜底 ── */
    console.log('\n--- 清理测试数据 ---');
    const ops = [];
    if (created.statementId) ops.push(['DELETE', `/api/v1/statements/${created.statementId}`]);
    if (created.invoiceId) ops.push(['DELETE', `/api/v1/invoices/${created.invoiceId}`]);
    if (created.outboundId) ops.push(['DELETE', `/api/v1/sales-orders/${created.outboundId}`]);
    if (created.salesOrderId) ops.push(['DELETE', `/api/v1/sales-orders/${created.salesOrderId}`]);
    if (created.purchaseInboundId) ops.push(['DELETE', `/api/v1/purchase-orders/${created.purchaseInboundId}`]);
    if (created.purchaseOrderId) ops.push(['DELETE', `/api/v1/purchase-orders/${created.purchaseOrderId}`]);
    if (created.productId && warehouse) {
      ops.push(['PUT', '/api/v1/opening-stock', { items: [{ warehouse_id: warehouse.id, product_id: created.productId, quantity: 0, unit_price: 0 }] }]);
    }
    if (created.customerId) ops.push(['DELETE', `/api/v1/customers/${created.customerId}`]);
    if (created.productId) ops.push(['DELETE', `/api/v1/products/${created.productId}`]);
    for (const [method, url, body] of ops) {
      const r = await api(method, url, body).catch((e) => ({ status: 'ERR', data: e.message }));
      console.log(`  ${method} ${url} → ${r.status}`);
    }
    // 落一份 id 清单：收过款的单据不能通过 API 删（409），由 clean_e2e_data.py 精确清理
    try {
      fs.writeFileSync('C:////Users////admi////AppData////Local////Temp////erp_e2e_created.json', JSON.stringify({ ...created, customerName: CUSTOMER, productName: PRODUCT }, null, 2));
    } catch (e) {
      console.log('  写清理清单失败：', e.message);
    }
    const left = await api('GET', '/api/v1/customers');
    const rest = (Array.isArray(left.data) ? left.data : left.data.items || []).filter((c) => c.name === CUSTOMER);
    console.log(`  复核：残留测试客户 ${rest.length} 条`);
    await browser.close();
  }

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n最终：${passed}/${results.length} 项通过`);
  process.exit(0);
})().catch(async (err) => {
  console.error('自测中断：', err.message);
  try {
    if (browser) await browser.close();
  } catch {
    /* ignore */
  }
  process.exit(1);
});
