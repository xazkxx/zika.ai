/**
 * 销售出库 · 多单位换算 —— 纯逻辑层（第三阶段 3c）
 *
 * ## 和后端的分工（这条界必须守住）
 *
 * **换算率永远由服务端从 `unit` 重新解析**（`erp_common._resolve_unit_factor`）。
 * 前端这里算出来的 `factor` **只用于界面展示和录入校验**，一个字节都不会发给后端 ——
 * 请求体里从来就没有 `unit_factor` 这个字段（`SalesOrderItemCreate` 里也没有）。
 * 客户端要是能自己说"我这 3 箱是 3000 盒"，库存就凭空放大 1000 倍。
 *
 * 所以本文件的价值是：
 *   ① 选"箱"时立刻让用户看见"实际出库 36 盒"，而不是等保存完再去库存页找答案；
 *   ② 在提交前把「选了个不存在的单位」「数量不是整数」这类错误拦在本地，
 *      省掉一次 400 往返；后端那一道闸当然还在，两道都不失效才写不进脏数据。
 *
 * ## 换算方向（与 `lib/productUnits.js` / `DESIGN.md` 同一套定义，不要另立一套）
 *
 *     factor ＝ 「1 个录入单位 ＝ factor 个基本单位」
 *     基本单位数量 ＝ 录入数量 × factor            ← 只乘不除
 *     最小单位成本 ＝ 录入单价 ÷ factor
 *
 * 不复用 `productUnits.js` 的 `factorIsValid` 之类是刻意的：那边是**维护态**的
 * 校验（上限 999999、最多 50 行），这里是**开单态**的取值语义，两者会各自演化。
 * 但方向的定义必须一致，所以上面那段话两处都抄了一遍。
 *
 * 不依赖 React、不碰 window，标准 ESM 导出，不污染全局。
 */

/** 基本单位（= 最小单位）的换算率恒为 1。 */
export const BASE_UNIT_FACTOR = 1;

/** 数量必须是正整数：后端 `SalesOrderItemCreate.quantity` 是 `int`。 */
export const MAX_LINE_QUANTITY = 9999999;

// 空行判定与其它单据页共用同一套口径（2026-10-17 空行边界测试）
// 带 .js 后缀：Vite 两种写法都认，但原生 node ESM 只认完整路径 —— 这样这个模块
// 能被单测脚本直接 import，不必先过一遍打包。
import { isBlankItemRow } from './orderLines.js';

const normalizeUnitName = (value) => String(value ?? '').trim();

/**
 * 纯数字串 → 整数。**刻意不用 `Number.isInteger(Number(v))`**：
 * `Number('')` / `Number('  ')` / `Number(null)` 全是 `0`，会把"没填"和"填了 0"
 * 混为一谈，也会把空输入判成合法。
 */
const intOf = (value) => {
  const text = String(value ?? '').trim();
  if (!/^-?[0-9]+$/.test(text)) return null;
  return Number(text);
};

const numberOrNull = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

/**
 * 新增一行的初始值。单位留空 = 还没选，逼用户看见这个下拉框。
 *
 * `price_auto` 是**纯界面标记，永远不会发给后端**（`serializeSalesItems`
 * 是按名字逐个挑字段拼载荷的，这个键会被丢掉）。它存在的唯一理由：
 *
 *   选了「箱」→ 单价自动预填 180 → 用户改成 666 → 再换回「盒」
 *
 * 最后那一步**必须保住 666**（用户手填的就是他要的），但
 * 「箱 180 → 大箱」这种情况又**必须**把 180 换成 700（不换就是 7 倍错价）。
 * 两者在值上分不出来 —— 预填的 180 和手填的 180 长得一模一样。
 * 所以额外记一个「这个值是我们替用户猜的，还是他自己写的」。
 */
export function makeEmptySalesLine() {
  return {
    product_id: '',
    unit: '',
    quantity: '1',
    unit_price: '',
    note: '',
    /** true = 单价是系统预填的（换单位时可以覆盖）；false = 用户手填的（绝不覆盖） */
    price_auto: true,
  };
}

/**
 * 某个商品可选的单位列表。基本单位**永远排第一**，其余按换算率升序。
 *
 * `is_enabled === false` 的辅助单位会被剔除 —— 因为后端
 * `_resolve_unit_factor` 只认 `is_enabled = true` 的行，放出来只会让用户
 * 选一个必然 400 的选项。
 *
 * `includeUnit` 是给「编辑一张旧单」用的：那行可能选的是一个后来被停用的单位，
 * 直接剔除会让下拉框显示成"请选择单位"，用户一旦保存就静默换了单位。
 * 传进来就把这一项以 `disabledOption: true` 补在末尾，界面标"(已停用)"。
 */
export function buildUnitOptions(product, unitRows, includeUnit = '') {
  const base = normalizeUnitName(product && product.unit);
  const options = [];

  if (base) {
    options.push({
      name: base,
      factor: BASE_UNIT_FACTOR,
      isBase: true,
      disabledOption: false,
      salePrice: numberOrNull(product && product.sale_price),
      purchasePrice: numberOrNull(product && product.purchase_price),
    });
  }

  // ⚠️ 两个集合不能合并成一个：`sourceNames` 是"档案里出现过这个名字"，
  //    `emitted` 是"真的进了下拉框"。被停用剔掉的名字只进前者。
  //    合并的话，一个已停用的「托」会挡掉下面 `includeUnit` 的补录 ——
  //    改一张老单时那行就变成"请选择单位"，用户一保存就把单位悄悄换掉了。
  const sourceNames = new Set(base ? [base] : []);
  const emitted = new Set(base ? [base] : []);
  const extras = [];
  for (const row of Array.isArray(unitRows) ? unitRows : []) {
    if (!row) continue;
    const name = normalizeUnitName(row.unit_name);
    if (!name || sourceNames.has(name)) continue;
    sourceNames.add(name);
    const factor = intOf(row.factor);
    // `factor < 2` 的行是脏数据（DB 有 CHECK(factor>=2)）；宁可不显示，
    // 也不要显示一个换算后会算错的选项。
    if (factor === null || factor < 2) continue;
    if (row.is_enabled === false) continue;
    emitted.add(name);
    extras.push({
      name,
      factor,
      isBase: false,
      disabledOption: false,
      salePrice: numberOrNull(row.sale_price),
      purchasePrice: numberOrNull(row.price),
    });
  }
  extras.sort((a, b) => (a.factor === b.factor ? a.name.localeCompare(b.name) : a.factor - b.factor));

  const wanted = normalizeUnitName(includeUnit);
  if (wanted && !emitted.has(wanted)) {
    options.push({
      name: wanted,
      factor: BASE_UNIT_FACTOR,
      isBase: false,
      disabledOption: true,
      salePrice: null,
      purchasePrice: null,
    });
  }

  return options.concat(extras);
}

/** 取某个单位名对应的换算率。查不到 → 1（= 不换算，与后端"查不到就 400"不同，见文件头）。 */
export function resolveFactorFor(options, unitName) {
  const name = normalizeUnitName(unitName);
  if (!name) return BASE_UNIT_FACTOR;
  const hit = (Array.isArray(options) ? options : []).find((option) => option && option.name === name);
  return hit ? hit.factor : BASE_UNIT_FACTOR;
}

/**
 * 实际出库数量（最小单位）＝ 录入数量 × factor。
 * 任何一个算不出来就返回 `null`（界面显示 `—`），**绝不返回 0** ——
 * 0 会被误读成"这一行不出库"。
 */
export function baseQuantity(quantity, factor) {
  const qty = intOf(quantity);
  const mult = intOf(factor);
  if (qty === null || mult === null) return null;
  return qty * mult;
}

/** 每最小单位的成本 ＝ 录入单价 ÷ factor。后端写进流水就是这个数。 */
export function baseUnitCost(unitPrice, factor) {
  const price = numberOrNull(unitPrice);
  const mult = intOf(factor);
  if (price === null || mult === null || mult < 1) return null;
  return price / mult;
}

/** 行金额。**录入口径**：录入数量 × 录入单价（后端 `amount` 就是这个）。 */
export function lineAmount(quantity, unitPrice) {
  const qty = intOf(quantity);
  const price = numberOrNull(unitPrice);
  if (qty === null || price === null) return 0;
  return qty * price;
}

/**
 * 选中某个单位时应该预填的售价。没有就返回 `null`，由界面决定要不要回退到档案价。
 */
export function defaultUnitPrice(options, unitName) {
  const name = normalizeUnitName(unitName);
  const hit = (Array.isArray(options) ? options : []).find((option) => option && option.name === name);
  if (!hit) return null;
  if (hit.salePrice !== null && hit.salePrice !== undefined) return hit.salePrice;
  return null;
}

/**
 * 下拉换单位时**建议**填进去的售价（只在单价框还空着的时候用）。
 *
 * 取值优先级：
 *   ① 该辅助单位自己的售价（`product_units.sale_price`）—— 最准；
 *   ② 档案售价 × factor —— 辅助单位没单独定价时的合理推算
 *      （1 箱 12 盒、每盒 15 元 ⇒ 一箱 180 元）；
 *   ③ 都拿不到 → `null`，界面留空让人自己填，**绝不猜 0**
 *      （0 会被后端原样落库，变成一张金额为 0 的白送单）。
 *
 * ⚠️ 这只是"建议值"。调用方必须先确认单价框是空的才写进去 ——
 *    用户手填过的价格绝不能被换单位这个动作覆盖掉。
 */
export function suggestUnitPrice(options, unitName, product) {
  const direct = defaultUnitPrice(options, unitName);
  if (direct !== null) return direct;

  const basePrice = numberOrNull(product && product.sale_price);
  if (basePrice === null) return null;

  const factor = resolveFactorFor(options, unitName);
  if (factor < 1) return null;
  // 乘完仍然收敛到分，避免 15 × 12 变成 180.00000000000003
  return Math.round(basePrice * factor * 100) / 100;
}

/**
 * 换算说明文案，如「3 箱 = 36 盒」「36 盒」。
 * 算不出来时明确显示 `—`，不猜、不留空。
 */
export function describeConversion(quantity, factor, unitName, baseUnit) {
  const name = normalizeUnitName(unitName) || '—';
  const base = normalizeUnitName(baseUnit) || '—';
  const total = baseQuantity(quantity, factor);
  if (total === null) return '—';
  if (name === base) return `${total} ${base}`;
  return `${String(quantity).trim()} ${name} = ${total} ${base}`;
}

/**
 * 校验整张明细。返回 `{ ok, index, error }`，`index` 指到出错的行（-1 = 与行无关）。
 *
 * `optionsByProduct` 是 `Map<productId, options[]>`（或 `{ [id]: options }`），
 * 由调用方在商品/单位数据变化时建好，避免这里每行都去产品列表里线性找。
 */
export function validateSalesLines(rows, optionsByProduct) {
  const list = Array.isArray(rows) ? rows : [];

  // 「整个表单还空着」判定：没有任何一行选了商品、也没有任何一行填了单价。
  // ⚠️ 不能用 `row.quantity` 参与判断 —— `makeEmptySalesLine()` 把数量预填成 `'1'`，
  //    于是每一行都"非空"，这条提示永远不会触发，用户点保存只会看到
  //    "第 1 行还没有选择商品"。那样虽不算错，但没告诉他"你整张表还没填"。
  const anyFilled = list.some(
    (row) => row && (row.product_id || numberOrNull(row.unit_price) !== null)
  );
  if (!anyFilled) {
    return { ok: false, index: -1, error: '请至少填写一行商品明细' };
  }

  for (let i = 0; i < list.length; i += 1) {
    const row = list[i] || {};
    // 整行空着（没选商品、数量还是预填的 1、单价没填）→ 直接跳过。
    // 2026-10-17 边界测试：默认/新增的空明细行不能拦住保存，
    // 只有"填了东西却没选商品"的半填行才该报错。
    if (isBlankItemRow(row)) continue;
    if (!row.product_id) {
      return { ok: false, index: i, error: `第 ${i + 1} 行还没有选择商品` };
    }

    const qty = intOf(row.quantity);
    if (qty === null) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的数量要填整数（库存不存小数）` };
    }
    if (qty <= 0) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的数量要大于 0` };
    }
    if (qty > MAX_LINE_QUANTITY) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的数量不能超过 ${MAX_LINE_QUANTITY}` };
    }

    const price = numberOrNull(row.unit_price);
    if (price === null) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的单价要填数字` };
    }
    if (price < 0) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的单价不能是负数` };
    }

    const options = lookupOptions(optionsByProduct, row.product_id);
    if (options === null) {
      return { ok: false, index: i, error: `第 ${i + 1} 行选中的商品不在商品列表里，请重新选择` };
    }

    const unit = normalizeUnitName(row.unit);
    if (unit) {
      const hit = options.find((option) => option.name === unit);
      // 下拉框里能选到的就一定是合法的；走到这里说明单位是外部塞进来的
      // （改单回填、导入），必须拦掉，否则后端 `_resolve_unit_factor` 直接 400。
      if (!hit) {
        return {
          ok: false,
          index: i,
          error: `第 ${i + 1} 行选中的商品没有单位「${unit}」，请重新选择单位`,
        };
      }
    }
  }

  // 兜底：所有行都被当成空行跳过了（例如只在单价里敲了个 0，商品一直没选）——
  // 不能放行，否则会发一个 items: [] 的空载荷给后端，报错要等一个来回。
  if (!list.some((row) => row && row.product_id)) {
    return { ok: false, index: -1, error: '请至少填写一行商品明细' };
  }

  return { ok: true, index: -1, error: '' };
}

/**
 * 表单行 → 接口载荷（对应后端 `SalesOrderItemCreate`）。
 *
 * ⚠️ **只发 `unit`，绝不发 `factor`** —— 后端连这个字段都没有。
 * `unit` 为空串时省略该键，让后端走"未指定单位 = 基本单位"的老路径。
 * `quantity` 必须是整数，`unit_price` 转成数字（后端是 `float`）。
 *
 * 载荷是**按名字逐个挑字段拼出来的**，不是把表单行整个发出去 ——
 * 于是行上的界面专属字段（`price_auto`）天然不会泄漏到请求体里。
 * 这也是为什么这里不能偷懒写 `{ ...row }`。
 */
export function serializeSalesItems(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => row && row.product_id)
    .map((row) => {
      const unit = normalizeUnitName(row.unit);
      const line = {
        product_id: Number(row.product_id),
        quantity: intOf(row.quantity) === null ? 0 : intOf(row.quantity),
        unit_price: numberOrNull(row.unit_price) === null ? 0 : numberOrNull(row.unit_price),
      };
      if (unit) line.unit = unit;
      line.note = row.note || null;
      return line;
    });
}

/** 汇总：行数 / 金额（录入口径）/ 各商品的最小单位出库量。 */
export function summarizeLines(rows, optionsByProduct) {
  const list = (Array.isArray(rows) ? rows : []).filter((row) => row && row.product_id);
  let amount = 0;
  const baseQtyByProduct = new Map();

  for (const row of list) {
    amount += lineAmount(row.quantity, row.unit_price);
    const options = lookupOptions(optionsByProduct, row.product_id);
    const factor = resolveFactorFor(options || [], row.unit);
    const total = baseQuantity(row.quantity, factor);
    if (total === null) continue;
    const key = String(row.product_id);
    baseQtyByProduct.set(key, (baseQtyByProduct.get(key) || 0) + total);
  }

  return { lineCount: list.length, amount: Math.round(amount * 100) / 100, baseQtyByProduct };
}

/** `Map` / 普通对象 / `null` 都能查 —— 调用方常常只有一个普通对象。 */
function lookupOptions(optionsByProduct, productId) {
  if (!optionsByProduct) return null;
  const key = String(productId);
  if (typeof optionsByProduct.get === 'function') {
    const hit = optionsByProduct.get(key);
    return Array.isArray(hit) ? hit : null;
  }
  const hit = optionsByProduct[key];
  return Array.isArray(hit) ? hit : null;
}

/**
 * 单位下拉的显示文案，如「箱（1箱=12盒）」。
 * 基本单位不带括号 —— 它不换算。
 */
export function unitOptionLabel(option, baseUnit) {
  if (!option) return '';
  const name = option.name;
  if (option.isBase) return `${name}（基本单位）`;
  const base = normalizeUnitName(baseUnit) || '基本单位';
  const suffix = option.disabledOption ? ' · 已停用' : '';
  return `${name}（1${name}=${option.factor}${base}）${suffix}`;
}
