/**
 * money.js —— 前端金额 / 费率的安全算术（全站唯一入口）。
 *
 * ## 为什么不能直接 toFixed(2) / Math.round(n * 100)
 *
 *   (1.005).toFixed(2)        === '1.00'   // 1.005 在内存里是 1.00499999999999989
 *   Math.round(1.005 * 100)   === 100      // 1.005*100 是 100.49999999999999
 *
 * 业务上这一分钱必须进位，所以正确姿势是"把小数点挪到数字串里"：
 *
 *   Number('1.005e2') === 100.5  → Math.round → 101 → /100 → 1.01  ✅
 *
 * ## 三条约定（与后端 app/core/money.py 对齐）
 *
 * 1. 钱 → 2 位（`round2`）；单价（费率）→ 4 位（`round4`）。**单价绝不用 round2**：
 *    73.901 × 580 = 42,862.58；抹成 73.90 就是 42,862.00，一单少 6 毛。
 * 2. 合计必须"逐行金额相加"（`sumAmounts`），不是"合计单价 × 合计数量"。
 * 3. 展示统一走 `money()`；参与计算一律先 `round2/round4`，别把 1.005 这类值一路带下去。
 *
 * ⚠️ 后端返回的 BigDecimal 在 JSON 里已经是 number（浏览器只认 double），
 *    所以"精度"这件事只能靠前端自己"用完即舍"，不能指望拿到的是精确值。
 */

/** 先放大 10 位消掉二进制噪声（1.00499999999999989 → 1.005）。
 *  直接 Math.round(n*1e2) 在 n=1.005 时会掉链子，先洗一遍再挪小数点就稳。 */
const clean = (n) => Number(n.toFixed(10));

/** 金额：2 位，四舍五入。 */
export function round2(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.round(Number(`${clean(n)}e2`)) / 100;
}

/** 单价 / 单位成本：4 位。**不要用 round2 处理单价。** */
export function round4(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.round(Number(`${clean(n)}e4`)) / 1e4;
}

/** 行金额 = 单价(4 位) × 数量 → 2 位。顺序不能反：先收 2 位再乘就是少钱的那个错。 */
export function lineAmount(unitPrice, quantity) {
  return round2(round4(unitPrice) * Number(quantity || 0));
}

/** 金额合计：逐行量化后相加。pick 默认取 row.amount，明细表各行字段不同名时传自定义。 */
export function sumAmounts(list, pick = (row) => row.amount) {
  const total = (Array.isArray(list) ? list : []).reduce((acc, row) => acc + round2(pick(row)), 0);
  return round2(total);
}

/** 价税合计 → { net: 不含税, tax: 税额 }。税率是百分比（13 = 13%）。 */
export function splitTax(total, taxRate) {
  const gross = round2(total);
  const rate = Number(taxRate);
  if (!Number.isFinite(rate) || rate <= 0) return { net: gross, tax: 0 };
  const net = round2(gross / (1 + rate / 100));
  return { net, tax: round2(gross - net) };
}

/** 展示：千分位 + 2 位；null/'' → '0.00'（列表里不要出现 NaN）。 */
export function money(value) {
  return round2(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** 展示：带 ¥ 前缀的 money()，负数把负号提到 ¥ 前面（¥-1,234.00 很难看）。 */
export function yuan(value) {
  const n = round2(value);
  return n < 0 ? `-¥${money(Math.abs(n))}` : `¥${money(n)}`;
}

/**
 * 展示：**单价 / 费率**。钱是 2 位，单价是 4 位 —— 这两者绝不能用同一个格式。
 *
 * `money(73.901)` 会显示成 `73.90` 或 `73.9`，用户当场就会以为"系统把我的价格改了"。
 * 这里给 2~4 位自适应：73.901 → "73.901"，73.9 → "73.90"，73 → "73.00"。
 *
 * ⚠️ 只用于**展示**。参与计算请用 `round4` / `lineAmount`，别拿格式化后的字符串去乘。
 */
export function rate(value) {
  return round4(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

/** 数量展示：整数不显示小数点，小数最多 4 位（0.5 米、1.25 吨这类）。 */
export function qty(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0';
  return Number.isInteger(n) ? String(n) : String(round4(n));
}
