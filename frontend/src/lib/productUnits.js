/**
 * 商品辅助单位 —— 纯逻辑层（第三阶段 3a）
 *
 * 为什么单独一个文件：这几个函数是本阶段唯一有判断逻辑的地方（换算率合法性、
 * 重名、默认单位唯一、包装数镜像）。塞进 700 行的弹窗组件里就只能靠"打开浏览器
 * 点点看"，回归不了。拆出来之后
 *   node --test src/lib/productUnits.test.mjs
 * 秒级跑完，与 productCategory.js / productImage.js / alertRules.js 是同一套做法。
 *
 * 不依赖 React、不碰 window，标准 ESM 导出，不污染全局。
 *
 * ─────────────────────────────────────────────────────────────────────────
 * ⚠️ 换算方向（**唯一**的定义，改动前先看 `_product_units_step3/DESIGN.md`）
 *
 *     factor ＝ 「1 个本行单位 ＝ factor 个基本单位」
 *     基本单位数量 ＝ 录入数量 × factor          ← 只乘不除
 *
 * 为什么不能反过来存「1 基本单位 = 0.1 箱」：
 *   后端 `erp_common._apply_stock` 里是 `qty = int(quantity or 0)`，
 *   `qty == 0` 就直接 `return None` —— **一条库存流水都不写，而且不报错**。
 *   而 `int(3 × 0.1) = 0`：入库 3 箱，库存一根毛不动，界面还提示"成功"。
 *   所以 `factor` 恒为 ≥2 的整数，方向由数字本身钉死。
 *
 * ─────────────────────────────────────────────────────────────────────────
 * ⚠️ 本文件是**纯逻辑 + 纯校验**，不含任何数量计算。
 * 第三阶段 3a 的产物：辅助单位只被"维护"，不参与库存/金额的任何运算。
 * 真正开始按换算率乘数量是 3b（采购入库）。
 *
 * 数据形状说明：表单行（draft）与接口行**刻意保持同一套 snake_case 键**
 * （`unit_name` / `factor` / `price` / `sale_price` / `bar_code` / `is_default` /
 * `is_enabled` / `note`），只把数字变成字符串、把空值统一成 `''`。
 * 多一层键名翻译就多一个写错的机会，而这里没有收益。
 */

/** 换算率下界。1 没意义（与基本单位重复），<1 表示基本单位选错了。 */
export const UNIT_FACTOR_MIN = 2;
/** 换算率上界。防御性上限，防止误输入 99999999 把后续数量算成天文数字。 */
export const UNIT_FACTOR_MAX = 999999;
/** 一个商品最多几个辅助单位。与后端 `MAX_PRODUCT_UNITS` 必须一致。 */
export const MAX_UNITS_PER_PRODUCT = 50;

/** 去空白。**只 trim，不做任何其它清洗** —— 单位名以字典为准，允许中文。 */
export function normalizeUnitName(value) {
  return String(value ?? '').trim();
}

/**
 * 换算率是否合法：只接受 ≥2 的整数。
 *
 * ⚠️ 这里**不能用** `Number.isInteger(Number(value))`：
 *     `Number('')` 是 `0`、`Number('  ')` 是 `0`、`Number(null)` 是 `0` —— 空输入
 *     会被判成"合法且等于 0"，于是要么放过一个 0，要么把"没填"和"填了 0"
 *     混为一谈。所以先用正则确认是**纯数字串**，再判范围。
 *     顺带把 `2.5`（小数）、`1e3`（科学计数）、`-3`、`0x10` 全部挡在外面。
 */
export function factorIsValid(value) {
  const text = String(value ?? '').trim();
  if (!/^[0-9]+$/.test(text)) return false;
  const num = Number(text);
  return num >= UNIT_FACTOR_MIN && num <= UNIT_FACTOR_MAX;
}

/** 新增一行时的初始值：换算率预填 2（合法的最小值，逼用户看见并改它）。 */
export function makeEmptyUnitDraft() {
  return {
    unit_name: '',
    factor: String(UNIT_FACTOR_MIN),
    price: '',
    sale_price: '',
    bar_code: '',
    is_default: false,
    is_enabled: true,
    note: '',
  };
}

/**
 * 接口行 → 表单行。
 * 数字变字符串是为了受控输入框不会因为 `value={0}` 出现"删不干净"的手感问题。
 */
export function unitToDraft(row) {
  const source = row || {};
  const rawFactor = source.factor;
  return {
    unit_name: source.unit_name ?? '',
    factor:
      rawFactor === null || rawFactor === undefined || rawFactor === ''
        ? String(UNIT_FACTOR_MIN)
        : String(rawFactor),
    price: source.price ?? '',
    sale_price: source.sale_price ?? '',
    bar_code: source.bar_code ?? '',
    is_default: !!source.is_default,
    is_enabled: source.is_enabled === undefined ? true : !!source.is_enabled,
    note: source.note ?? '',
  };
}

export function unitsToDrafts(rows) {
  return (Array.isArray(rows) ? rows : []).map(unitToDraft);
}

/** 换算说明文案，如「1 箱 = 10 盒」。非法时明确显示 `?`，不猜。 */
export function describeFactor(factor, unitName, baseUnit) {
  const name = normalizeUnitName(unitName) || '（未命名）';
  const base = normalizeUnitName(baseUnit) || '（未填基本单位）';
  if (!factorIsValid(factor)) return `1 ${name} = ? ${base}`;
  return `1 ${name} = ${Number(String(factor).trim())} ${base}`;
}

/** 把第 index 行设为唯一默认（radio 语义：其余全部取消）。 */
export function setDefaultUnit(drafts, index) {
  return (Array.isArray(drafts) ? drafts : []).map((draft, i) => ({
    ...draft,
    is_default: i === index,
  }));
}

/**
 * 「包装数」应该被同步成什么值（用户 2026-10-16 拍板 A）。
 *
 * 没有默认辅助单位 → `null`（置空）。**刻意不自动挑一行当默认**：
 * 猜错了就是静默错数据，留空让人一眼看见才有救。
 */
export function packQtyMirror(drafts) {
  const list = Array.isArray(drafts) ? drafts : [];
  const hit = list.find((draft) => draft && draft.is_default);
  if (!hit) return null;
  return factorIsValid(hit.factor) ? Number(String(hit.factor).trim()) : null;
}

/** 默认辅助单位的单位名（仅用于界面提示）。 */
export function defaultUnitName(drafts) {
  const list = Array.isArray(drafts) ? drafts : [];
  const hit = list.find((draft) => draft && draft.is_default);
  return hit ? normalizeUnitName(hit.unit_name) : '';
}

/**
 * 校验整张辅助单位表。返回 `{ ok, index, error }`。
 *
 * `index` 指向出错的行（-1 表示与具体行无关的错误），界面用它高亮那一行。
 *
 * 与后端 `_validate_product_units` **逐条对应**（含中文提示的措辞），
 * 两边都做是因为：前端做能立刻给出定位，后端做才拦得住绕过界面的调用。
 * 提交时前端拦一道，后端再拦一道 —— 任何一条单独失效都不会写进脏数据。
 */
export function validateUnits(drafts, baseUnit) {
  const list = Array.isArray(drafts) ? drafts : [];

  if (list.length > MAX_UNITS_PER_PRODUCT) {
    return { ok: false, index: -1, error: `一个商品最多 ${MAX_UNITS_PER_PRODUCT} 个辅助单位` };
  }
  if (list.length === 0) return { ok: true, index: -1, error: '' };

  const base = normalizeUnitName(baseUnit);
  if (!base) {
    return {
      ok: false,
      index: -1,
      error: '请先填上面的「单位」—— 辅助单位要相对基本单位换算，没有基本单位就无从谈起',
    };
  }

  // 基本单位先进集合：这样"辅助单位名 == 基本单位名"会被当成重名拦下，
  // 而且提示语能分辨出是跟基本单位撞了还是跟兄弟行撞了。
  const seenNames = new Set([base]);
  const seenBarcodes = new Set();
  let defaultCount = 0;

  for (let i = 0; i < list.length; i += 1) {
    const draft = list[i] || {};
    const name = normalizeUnitName(draft.unit_name);

    if (!name) {
      return { ok: false, index: i, error: `第 ${i + 1} 行的辅助单位名称不能为空` };
    }
    if (seenNames.has(name)) {
      if (name === base) {
        return {
          ok: false,
          index: i,
          error: `第 ${i + 1} 行的「${name}」和本商品的基本单位重名了 —— 辅助单位必须比基本单位大`,
        };
      }
      return { ok: false, index: i, error: `第 ${i + 1} 行的「${name}」和上面的辅助单位重复了` };
    }
    seenNames.add(name);

    if (!factorIsValid(draft.factor)) {
      return {
        ok: false,
        index: i,
        error:
          `第 ${i + 1} 行「${name}」的换算率要填 ≥${UNIT_FACTOR_MIN} 的整数` +
          `（1 个${name}等于几个${base}）`,
      };
    }

    const barcode = String(draft.bar_code ?? '').trim();
    if (barcode) {
      if (seenBarcodes.has(barcode)) {
        return { ok: false, index: i, error: `第 ${i + 1} 行的条码「${barcode}」和上面重复了` };
      }
      seenBarcodes.add(barcode);
    }

    if (draft.is_default) defaultCount += 1;
  }

  if (defaultCount > 1) {
    return { ok: false, index: -1, error: '只能把一个辅助单位设为默认' };
  }

  return { ok: true, index: -1, error: '' };
}

const numberOrNull = (value) => {
  const text = String(value ?? '').trim();
  if (text === '') return null;
  const num = Number(text);
  return Number.isFinite(num) ? num : null;
};

const textOrNull = (value) => {
  const text = String(value ?? '').trim();
  return text === '' ? null : text;
};

/**
 * 表单行 → 接口载荷（对应后端 `schemas.ProductUnitInput`）。
 *
 * 空串一律转 `null`：后端 `price: Optional[float]` 收到 `''` 会直接 422，
 * 而用户在界面上"清空一个价格框"得到的正是 `''`。
 */
export function serializeUnits(drafts) {
  return (Array.isArray(drafts) ? drafts : []).map((draft) => ({
    unit_name: normalizeUnitName(draft.unit_name),
    factor: Number(String(draft.factor ?? '').trim()),
    price: numberOrNull(draft.price),
    sale_price: numberOrNull(draft.sale_price),
    bar_code: textOrNull(draft.bar_code),
    is_default: !!draft.is_default,
    is_enabled: draft.is_enabled === undefined ? true : !!draft.is_enabled,
    note: textOrNull(draft.note),
  }));
}
