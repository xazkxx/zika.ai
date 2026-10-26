// 对账单编辑器的纯函数层（零 React 依赖）。
//
// ⚠️ 这里的金额公式是**后端 `app/models/statement.py::compute_totals()` 的镜像**。
//    前端算它只有一个目的：勾选/改数时**即时预览**，不为了落库。
//    落库一律由后端重算（`_apply_totals` / `POST /statements/{id}/recalc`）——
//    前端算的数永远只是"给人看的草稿值"，绝不提交。
//    两边公式若不一致，会出现"界面显示 100、存进去 98"这种最难查的问题，
//    所以四则运算必须逐字对齐（改这里请同步改模型）。

export const STATEMENT_STATUS_LABELS = {
  draft: '草稿',
  confirmed: '已确认',
  sent: '已发送',
  void: '作废',
};

export const INVOICE_STATUS_LABELS = {
  none: '未开票',
  partial: '部分开票',
  full: '已开票',
};

export const SOURCE_TYPE_LABELS = {
  contract: '合同',
  order: '订单',
  inbound: '入库单',
  outbound: '出库单',
  invoice: '发票',
  receipt: '收款',
  payment: '付款',
  opening: '期初',
};

/** 方向：out = 应收（我方销售，对方是客户）；in = 应付（我方采购，对方是供应商） */
export const DIRECTIONS = [
  { code: 'out', label: '应收对账（客户）', partyType: 'customer', partyLabel: '客户' },
  { code: 'in', label: '应付对账（供应商）', partyType: 'supplier', partyLabel: '供应商' },
];

export function directionOf(code) {
  return DIRECTIONS.find((item) => item.code === code) || DIRECTIONS[0];
}

export function statusLabel(code) {
  return STATEMENT_STATUS_LABELS[code] || code || '草稿';
}

export function invoiceStatusLabel(code) {
  return INVOICE_STATUS_LABELS[code] || code || '未开票';
}

export function sourceLabel(code) {
  return SOURCE_TYPE_LABELS[code] || code || '—';
}

/** 后端金额出参是 float，但也有可能是字符串（Decimal 序列化）→ 统一成数字 */
export function toNumber(value) {
  if (value === null || value === undefined || value === '') return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** 两位小数的四舍五入。**只用于显示与前端预览**，落库由后端 Decimal 负责 */
export function round2(value) {
  return Math.round((toNumber(value) + Number.EPSILON) * 100) / 100;
}

/** 千分位金额（不带币种符号）：1234.5 → "1,234.50" */
export function amount(value) {
  const n = round2(value);
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 带币种的金额：1234.5 → "¥1,234.50" */
export function money(value) {
  return `¥${amount(value)}`;
}

/** 正负号敏感金额：负数前面补负号（`amount()` 的 toLocaleString 对负数已带 `-`） */
export function signedAmount(value) {
  return amount(value);
}

// ---------------------------------------------------------------------------
// 日期
// ---------------------------------------------------------------------------

export function todayStr() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 默认账期 = 本年 1 月 1 日 ~ 今天。对账最常用的就是"年初到现在" */
export function defaultPeriod() {
  const year = new Date().getFullYear();
  return { start: `${year}-01-01`, end: todayStr() };
}

// ---------------------------------------------------------------------------
// 明细行
// ---------------------------------------------------------------------------

/** 行的稳定 key：库里来的用 `id`，内存态用 `idx-<位置>` */
export function itemKey(row, index) {
  if (row && row.id !== null && row.id !== undefined && row.id !== '') return `id:${row.id}`;
  return `idx:${index}`;
}

/**
 * 把后端明细转成编辑器内部行。
 * 金额一律转成**字符串**存进 row：输入框是受控的，`''` 要能表示"用户正在清空"，
 * 存数字会被 `Number('') === 0` 悄悄吃掉，用户永远删不干净那一格。
 */
export function normalizeItem(raw = {}, index = 0) {
  const contract = toNumber(raw.contract_amount);
  const invoiced = toNumber(raw.invoiced_amount);
  const received = toNumber(raw.received_amount);
  const prepaidReceived = toNumber(raw.prepaid_received);
  const prepaidApplied = toNumber(raw.prepaid_applied);
  return {
    id: raw.id ?? null,
    key: itemKey(raw, index),
    line_no: raw.line_no ?? index + 1,
    business_date: raw.business_date || '',
    source_type: raw.source_type || '',
    source_no: raw.source_no || '',
    contract_id: raw.contract_id ?? null,
    contract_no: raw.contract_no || '',
    summary: raw.summary || '',
    contract_amount: String(contract || ''),
    invoiced_amount: String(invoiced || ''),
    received_amount: String(received || ''),
    prepaid_received: String(prepaidReceived || ''),
    prepaid_applied: String(prepaidApplied || ''),
    invoice_count: Number(raw.invoice_count || 0),
    note: raw.note || '',
  };
}

/**
 * 派生一行的三个计算字段（与后端 `StatementItem` 的 `_derive` 同口径）：
 *   未开票 = 合同金额 − 已开票
 *   剩余未收 = 合同金额 − 已收 − 预收已核销
 *   发票状态 = 已开票 ≤ 0 → none；已开票 ≥ 合同金额 → full；否则 partial
 *
 * ⚠️ 合同金额为 0 的行（比如"本期收款 N 笔"这种汇总行）不要判成"已开票" ——
 *    `0 >= 0` 为真，会把一行纯收款标成"已开票"，对账时非常容易被误读。
 *    所以 full 的前提是**合同金额 > 0**。
 */
export function deriveRow(row) {
  const contract = toNumber(row.contract_amount);
  const invoiced = toNumber(row.invoiced_amount);
  const received = toNumber(row.received_amount);
  const applied = toNumber(row.prepaid_applied);
  const uninvoiced = round2(contract - invoiced);
  const outstanding = round2(contract - received - applied);
  let invoiceStatus = 'none';
  if (invoiced > 0) invoiceStatus = contract > 0 && invoiced >= contract ? 'full' : 'partial';
  return { uninvoiced, outstanding, invoiceStatus };
}

/**
 * 勾选行的合计 = 头部 6 张卡片的来源。公式逐字对齐 `compute_totals()`：
 *   未开票     = 合同金额 − 已开票
 *   预收余额   = 预收发生 − 预收已核销
 *   应收余额   = 期初 + 已开票 − 已收 − 预收已核销
 *   剩余未收   = 合同金额 − 已收 − 预收已核销
 */
export function computeTotals(rows, openingBalance = 0) {
  const list = rows || [];
  const sum = (field) => list.reduce((acc, row) => acc + toNumber(row[field]), 0);
  const contract = sum('contract_amount');
  const invoiced = sum('invoiced_amount');
  const received = sum('received_amount');
  const prepaidReceived = sum('prepaid_received');
  const prepaidApplied = sum('prepaid_applied');
  const opening = toNumber(openingBalance);
  return {
    opening_balance: round2(opening),
    contract_amount: round2(contract),
    invoiced_amount: round2(invoiced),
    uninvoiced_amount: round2(contract - invoiced),
    received_amount: round2(received),
    prepaid_received: round2(prepaidReceived),
    prepaid_applied: round2(prepaidApplied),
    prepaid_balance: round2(prepaidReceived - prepaidApplied),
    receivable_balance: round2(opening + invoiced - received - prepaidApplied),
    outstanding_amount: round2(contract - received - prepaidApplied),
    item_count: list.length,
  };
}

/** 头部 6 张卡片 / 底部合计条的统一取值口径 */
export function headerCards(totals, direction = 'out') {
  const receivable = direction === 'out';
  return [
    { key: 'opening_balance', label: '期初余额', value: totals.opening_balance, hint: '上期结转' },
    { key: 'contract_amount', label: '本期新增', value: totals.contract_amount, hint: '合同金额合计' },
    { key: 'invoiced_amount', label: '本期已开票', value: totals.invoiced_amount, hint: '勾选行合计' },
    { key: 'received_amount', label: receivable ? '本期已收' : '本期已付', value: totals.received_amount, hint: '勾选行合计' },
    { key: 'receivable_balance', label: receivable ? '期末应收' : '期末应付', value: totals.receivable_balance, hint: '期初+开票−已收' },
    { key: 'outstanding_amount', label: '剩余未收', value: totals.outstanding_amount, hint: '合同额−已收−核销' },
  ];
}

// ---------------------------------------------------------------------------
// 校验 / 请求参数
// ---------------------------------------------------------------------------

/**
 * 生成草稿的前置校验。
 * `ErpSearchSelect` 的触发器是 `div[role=combobox]`，原生 `required` 完全失效，
 * 所以这里必须自己拦（与合同台账同一条硬规则）。
 */
export function validateGenerate({ partyId, period }) {
  if (!String(partyId || '').trim()) return '请先选择往来单位（客户或供应商）';
  const start = String(period?.start || '').trim();
  const end = String(period?.end || '').trim();
  if (!start || !end) return '请填写完整的对账期间（开始日期与结束日期都要有）';
  if (start > end) return '对账期间的开始日期不能晚于结束日期';
  return null;
}

/** 保存时的校验：只有草稿能改；且至少要有一行勾选的明细 */
export function validateSave({ statement, checkedCount }) {
  if (!statement) return '还没有载入对账单，请先「生成草稿」或载入一张已有对账单';
  if (statement.status !== 'draft') {
    return `这张对账单已是「${statusLabel(statement.status)}」状态，不能再改明细（需调整请作废后重新生成）`;
  }
  if (checkedCount <= 0) return '至少要勾选一行明细，否则对账单是空的';
  return null;
}

/** 保存载荷：**只提交勾选的行**（未勾选 = 不纳入本单） */
export function buildSavePayload({ period, opening, note }, checkedRows) {
  return {
    period_start: period?.start || null,
    period_end: period?.end || null,
    opening_balance: round2(opening),
    note: note || null,
    items: (checkedRows || []).map((row, index) => ({
      line_no: index + 1,
      business_date: row.business_date || null,
      source_type: row.source_type || null,
      source_no: row.source_no || null,
      contract_id: row.contract_id ?? null,
      contract_no: row.contract_no || null,
      summary: row.summary || null,
      contract_amount: round2(row.contract_amount),
      invoiced_amount: round2(row.invoiced_amount),
      received_amount: round2(row.received_amount),
      prepaid_received: round2(row.prepaid_received),
      prepaid_applied: round2(row.prepaid_applied),
      invoice_count: Number(row.invoice_count || 0),
      note: row.note || null,
    })),
  };
}

/** 导出查询串：只带账期（对账单台账按 `period_end` 过滤） */
export function exportQuery({ period, direction }) {
  const params = new URLSearchParams();
  if (period?.start) params.set('from_date', period.start);
  if (period?.end) params.set('to_date', period.end);
  if (direction) params.set('direction', direction);
  return params.toString();
}

/** 打印走通用分发路由：`/print/{doc_type}/{doc_id}`，对账单的 doc_type 是 `statement-record` */
export function printPath(statementId) {
  return `/print/statement-record/${statementId}`;
}

/** 下拉里一行对账单怎么显示：单号 · 单位 · 账期（右侧灰字是状态） */
export function statementOptionLabel(row) {
  if (!row) return '';
  const period = [row.period_start, row.period_end].filter(Boolean).join('~');
  return [row.statement_no, row.party_name, period].filter(Boolean).join(' · ');
}

/**
 * 载入一张对账单后，默认勾选哪些行。
 * 默认**全选**：打开一张单据时用户的预期是"看到它的全部内容"，
 * 而不是"看到一堆没勾的框"。
 */
export function allRowKeys(rows) {
  // 优先用行自带的 `key`（`normalizeItem` 已经算好）：它来自 `id`，
  // 用户改了一格数字也不会变；只有内存新行才退到"按位置"。
  return (rows || []).map((row, index) => row.key || itemKey(row, index));
}
