/**
 * 项目资金试算 —— 前端数据层（v1.81.0，2026-10-26）
 *
 * 三条约定（照抄后端 `app/services/project_calc.py`，一处都不能自作聪明）：
 *   1. 金额**全程当字符串**处理，只有显示时才转数字。后端返回的就是两位小数字符串，
 *      前端再 `Number()` 一次已经够用；但**绝不**在状态里存浮点累加结果，
 *      否则页面上会出现 1863025.4800000002 这种"差一分"的鬼数字。
 *   2. 草稿只进 localStorage，键名带版本号（换结构就换键，老草稿自然失效，
 *      不做迁移 —— 测算数据丢了重填一遍的成本，远低于"迁移写错"的成本）。
 *   3. 示例数据 = 《电线采购销售税额试算表_v6》的 5 个产品行，加总**正好**
 *      2,617,568.02 / 1,756,297.77，与 Excel 合计列逐分一致。
 *      所以打开页面不做任何操作，看到的就是 Excel 的那两批合计。
 */

export const DRAFT_KEY = 'erp.projectCalc.draft.v1';

/** 空行模板：新加一行时用它，`cost_qty` 留空表示"跟销售数量一样" */
export const emptyLine = () => ({
  product_name: '',
  unit: '米',
  qty: '',
  cost_qty: '',
  sale_price: '',
  cost_price: '',
  has_invoice: true,
});

/**
 * Excel v6 的 5 个产品行（原表第 1+2 批合计口径）。
 * 校验：销售 2,617,568.02 / 成本 1,756,297.77 / 毛利 762,186.06 / 净利 716,815.41
 */
export const SAMPLE_LINES = [
  { product_name: '4x35', unit: '米', qty: '3119', cost_qty: '3119', sale_price: '233.00', cost_price: '156.23', has_invoice: true },
  { product_name: '4x70', unit: '米', qty: '2766', cost_qty: '2766', sale_price: '463.10', cost_price: '310.80', has_invoice: true },
  { product_name: '4x50', unit: '米', qty: '306', cost_qty: '306', sale_price: '319.85', cost_price: '214.66', has_invoice: true },
  { product_name: '3x16', unit: '米', qty: '580', cost_qty: '580', sale_price: '73.901', cost_price: '49.60', has_invoice: true },
  { product_name: '3x25', unit: '米', qty: '4654', cost_qty: '4654', sale_price: '100.81', cost_price: '67.66', has_invoice: true },
];

export const DEFAULT_SETTINGS = {
  vat_rate: '0.13',
  surcharge_half: true,
  city_rate: '0.07',
  edu_rate: '0.03',
  ledu_rate: '0.02',
  water_rate: '0.00045',
  stamp_rate: '0.0003',
  income_rate: '0.05',
  capital_daily_rate: '0.0002',
  pay_days: 30,
  collect_days: 60,
  prepay: '0',
  prepay_supplier: '0',
  include_income_tax_in_advance: false,
};

export const SETTING_LABELS = {
  vat_rate: '增值税率',
  city_rate: '城建税',
  edu_rate: '教育费附加',
  ledu_rate: '地方教育附加',
  water_rate: '水利基金',
  stamp_rate: '印花税',
  income_rate: '企业所得税',
  capital_daily_rate: '日资金成本',
};

export const num = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

/** `1,234,567.89`；传字符串也不会抖（先 Number 再 toLocaleString） */
export const money = (value) =>
  `¥${num(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** KPI 用：≥1 万折成"万"，老板一眼看量级；悬浮再看精确值 */
export const moneyWan = (value) => {
  const amount = num(value);
  if (Math.abs(amount) >= 10000) return `¥${(amount / 10000).toFixed(2)} 万`;
  return money(amount);
};

/** 比率（后端给的是 0.3094 这种小数形式）→ `30.94%` */
export const percent = (ratio, digits = 2) => `${(num(ratio) * 100).toFixed(digits)}%`;

/** 表单里的费率是小数（0.00045）→ 显示成 `0.045%` */
export const rateText = (ratio, digits = 4) => {
  const text = (num(ratio) * 100).toFixed(digits);
  return `${text.replace(/0+$/, '').replace(/\.$/, '')}%`;
};

/** 这一行自己算出来的含税金额（表格里显示用，和兜底值无关） */
export const lineAmount = (line) => num(line.qty) * num(line.sale_price);
export const lineCostAmount = (line) => {
  const qty = line.cost_qty === '' || line.cost_qty === null || line.cost_qty === undefined ? line.qty : line.cost_qty;
  return num(qty) * num(line.cost_price);
};

/** 只保留非空行再发请求：空行会让"未取得专票"之类的提示数错 */
export const toPayloadLines = (lines) =>
  lines
    .filter((line) => [line.product_name, line.qty, line.sale_price, line.cost_qty, line.cost_price].some((v) => String(v || '').trim() !== ''))
    .map((line) => ({
      product_name: line.product_name || '',
      unit: line.unit || '',
      qty: String(line.qty === '' ? 0 : line.qty),
      cost_qty: line.cost_qty === '' || line.cost_qty === null || line.cost_qty === undefined ? null : String(line.cost_qty),
      sale_price: String(line.sale_price === '' ? 0 : line.sale_price),
      cost_price: String(line.cost_price === '' ? 0 : line.cost_price),
      has_invoice: Boolean(line.has_invoice),
    }));

export function loadDraft() {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const draft = JSON.parse(raw);
    if (!draft || !Array.isArray(draft.lines)) return null;
    return {
      label: typeof draft.label === 'string' ? draft.label : '',
      lines: draft.lines,
      settings: { ...DEFAULT_SETTINGS, ...(draft.settings || {}) },
      savedAt: draft.savedAt || '',
    };
  } catch {
    // localStorage 被禁用 / JSON 坏了：当没草稿，不能让整页白屏
    return null;
  }
}

export function saveDraft(draft) {
  try {
    window.localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ ...draft, savedAt: new Date().toISOString() }),
    );
    return true;
  } catch {
    return false;
  }
}

export function clearDraft() {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* 忽略：隐私模式下本来就没有存储 */
  }
}
