/**
 * 单据明细行的「空行 / 半填」判定 —— 纯函数，无副作用、不依赖 React。
 *
 * ⚠️ 为什么不能只看 `product_id` 就判断空行：
 *    `emptyOrderItem`（lib/appLib.js:94）把数量预填成 `'1'`、单价预填成 `'0'`。
 *    于是「没选商品」和「整行没动过」不是一回事：
 *      ① 用户压根没动这行（数量还是 1、单价还是 0）→ 空行，**静默丢弃**；
 *      ② 用户填了数量/单价却没选商品 → **半填，必须红字拦截**。
 *    如果直接把 ② 当成空行丢掉，用户会以为"我明明填了数量"，单据却少一行；
 *    如果直接把 ① 当成半填报错，默认那几行空行就会拦住保存 —— 这正是
 *    2026-10-17 那次边界测试要修的问题。
 *
 * ⚠️ 反过来的口径同样要小心：「选了商品但数量为空」不能按 0 入账。
 *    后端 `_apply_stock` 对 qty==0 是直接 return，会变成
 *    "单据开出来了、库存一分没动"的幽灵单 —— 比报错更难查。
 */

/** 空明细行的预填值：数量 1、单价 0（见 lib/appLib.js 的 emptyOrderItem）。 */
export const DEFAULT_ITEM_QUANTITY = 1;
export const DEFAULT_ITEM_PRICE = 0;

function textOf(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function numberOf(value) {
  const text = textOf(value);
  if (text === '') return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 这一行是不是「整行没动过」。
 * 只有「没选商品」且「数量、单价都还是预填值」才算空行。
 */
export function isBlankItemRow(row) {
  if (!row) return true;
  if (textOf(row.product_id)) return false;
  const quantity = numberOf(row.quantity);
  const price = numberOf(row.unit_price);
  const quantityUntouched = quantity === null || quantity === DEFAULT_ITEM_QUANTITY;
  const priceUntouched = price === null || price === DEFAULT_ITEM_PRICE;
  return quantityUntouched && priceUntouched;
}

/**
 * 单行校验：合法或整行空着返回 ''；否则返回给用户看的红字。
 * `index` 是数组下标，提示里用 1 起始的行号。
 */
export function itemRowError(row, index) {
  const lineNo = Number(index) + 1;
  if (isBlankItemRow(row)) return '';

  if (!textOf(row.product_id)) {
    return `第 ${lineNo} 行填了数量或单价，但还没选商品`;
  }

  const quantity = numberOf(row.quantity);
  if (quantity === null) return `第 ${lineNo} 行的数量不能为空`;
  if (quantity <= 0) return `第 ${lineNo} 行的数量要大于 0`;
  if (!Number.isInteger(quantity)) return `第 ${lineNo} 行的数量要填整数（库存不存小数）`;

  const price = numberOf(row.unit_price);
  if (price !== null && price < 0) return `第 ${lineNo} 行的单价不能是负数`;

  return '';
}

/**
 * 整表体检。
 *   issues — 每一条半填/非法明细（含行号），前端逐行显示红字用；
 *   usable — 真正可以提交的行（已剔除空行）；
 *   ok     — 没有任何 issue 且至少有一行可用；
 *   empty  — 整张表都是空行（用户一行都没填）。
 */
export function inspectItemRows(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const issues = [];
  const usable = [];

  list.forEach((row, index) => {
    const message = itemRowError(row, index);
    if (message) {
      issues.push({ index, message });
      return;
    }
    // 空行（没选商品且没动过）既不报错也不提交
    if (!textOf(row && row.product_id)) return;
    usable.push(row);
  });

  return { issues, usable, ok: issues.length === 0 && usable.length > 0, empty: usable.length === 0 && issues.length === 0 };
}
