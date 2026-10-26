/* ==========================================================================
 * 紧急度判定规则
 * ---------------------------------------------------------------------------
 * 这个文件把「库存预警」的业务口径单独摘出来，只有纯函数、零 React 依赖。
 *
 * 🔧 要改判定规则，只改本文件的 ALERT_THRESHOLDS 一个常量即可，
 *    换料时不用碰组件，也不用碰接口层。
 *
 * 当前口径（用户确认）：
 *    预计可用天数 = 当前库存 / 日均出库
 *    可用天数  <  3 天  →  紧急 urgent
 *    3 ≤ 天数 ≤ 7 天   →  预警 warn
 *    可用天数  >  7 天  →  正常 normal
 *
 * 【缺货判定 —— 不在本文件，在后端】
 *    「哪些商品算缺货、要不要进明细表」是**接口层的口径**，由
 *    `app/api/v1/routes/erp_stock_alert.py` 的 `_is_shortage()` 唯一定义：
 *      设了库存下限（stock_lower > 0）→ 现存量**严格低于**下限才算缺货；
 *      没设下限（NULL / 0）          → 退回「现存量 <= 0」，卖光了才算缺货。
 *    KPI 的「缺货商品」数、它的 7 天迷你趋势、明细表的入选条件都调那一个函数。
 *    本文件只管**拿到明细之后**怎么算紧急度，所以不要在这里再写一遍缺货判断 ——
 *    两处各写一份，改口径时必然漏掉一处。
 *
 * 【边界约定，接后端时注意】
 *   - 天数正好等于 3  →  预警（不是紧急）
 *   - 天数正好等于 7  →  预警
 *   - 日均出库为 0 或缺失 → 天数为 Infinity → 判为「正常」，
 *     表格里显示「—」。不动销的商品不构成缺货风险。
 *   - **库存为负（欠货）→ 天数按 0 算 → 紧急**。这一档不能漏：
 *     系统允许负库存开单，负库存就是已经欠出去了。
 *   - level 字段由前端算，后端不用返回（返回了也会被重算覆盖）。
 * ========================================================================== */

/** 紧急度枚举，按严重程度从高到低 */
export const ALERT_LEVELS = ['urgent', 'warn', 'normal'];

/**
 * 🔧 判定阈值（单位：天）—— 改这里就能调整分档规则
 * @type {{ urgentBelow: number, warnBelow: number }}
 */
export const ALERT_THRESHOLDS = {
  /** 可用天数 < 该值 → 紧急 */
  urgentBelow: 3,
  /** 可用天数 ≤ 该值 → 预警；> 该值 → 正常 */
  warnBelow: 7,
};

/** 每个档位的展示信息（文案 + 排序权重），组件只读这里，不硬编码中文 */
export const LEVEL_META = {
  urgent: { label: '紧急', order: 0 },
  warn: { label: '预警', order: 1 },
  normal: { label: '正常', order: 2 },
};

/** 底部明细表的筛选页签 —— 和 ALERT_LEVELS 一一对应，避免两处各写一份 */
export const FILTER_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'urgent', label: '紧急' },
  { value: 'warn', label: '预警' },
  { value: 'normal', label: '正常' },
];

/**
 * 预计可用天数 = 当前库存 / 日均出库
 *
 * 两种"算不出来"必须分开，混成一个会把最该报警的行判成正常：
 *
 *   - 负库存 → 0 天。本系统允许负库存开单（先卖后进货），负库存意味着货已经欠出去
 *     了，是最紧急的一档，绝不能归进「正常」。
 *   - 日均出库 <= 0 → Infinity。真的算不出来（不动销），不构成缺货风险，显示「—」。
 *
 * @param {number} stock     当前库存
 * @param {number} dailyOut  日均出库
 * @returns {number} 天数；不动销时返回 Infinity
 */
export function daysOfSupply(stock, dailyOut) {
  const s = Number(stock);
  const d = Number(dailyOut);
  if (!Number.isFinite(s)) return Infinity;
  if (s < 0) return 0;
  if (!Number.isFinite(d) || d <= 0) return Infinity;
  return s / d;
}

/**
 * 按可用天数判档
 *
 * 阈值读 ALERT_THRESHOLDS；Infinity（算不出天数）归入「正常」。
 *
 * @param {number} days
 * @returns {'urgent' | 'warn' | 'normal'}
 */
export function levelFromDays(days) {
  if (!Number.isFinite(days)) return 'normal';
  if (days < ALERT_THRESHOLDS.urgentBelow) return 'urgent';
  if (days <= ALERT_THRESHOLDS.warnBelow) return 'warn';
  return 'normal';
}

/**
 * 把接口返回的原始明细补全成"视图模型"
 *
 * 原始字段（后端给）：id / sku / name / warehouse / stock / safetyStock / dailyOut / suggest
 * 派生字段（前端算）：gap 缺口 / daysLeft 可用天数 / level 紧急度
 *
 * @param {import('./stockAlertApi').RawAlertItem} item
 * @returns {import('./stockAlertApi').AlertItem}
 */
export function enrichAlert(item) {
  const stock = Number(item.stock) || 0;
  const safetyStock = Number(item.safetyStock) || 0;
  const daysLeft = daysOfSupply(stock, item.dailyOut);
  return {
    ...item,
    stock,
    safetyStock,
    gap: safetyStock - stock,
    daysLeft,
    level: levelFromDays(daysLeft),
  };
}

/**
 * 批量补全 + 排序
 *
 * 排序即补货优先级：可用天数少的排前面；天数相同再看缺口大小。
 * 后端返回什么顺序都不影响展示，这里统一重排。
 *
 * @param {import('./stockAlertApi').RawAlertItem[] | null | undefined} list
 * @returns {import('./stockAlertApi').AlertItem[]}
 */
export function enrichAlerts(list) {
  return (list || [])
    .map(enrichAlert)
    .sort((a, b) => {
      if (a.daysLeft !== b.daysLeft) return a.daysLeft - b.daysLeft;
      return b.gap - a.gap;
    });
}

/**
 * 按档位计数，供顶部汇总和筛选页签用
 *
 * @param {import('./stockAlertApi').AlertItem[] | null | undefined} list 已 enrich 的列表
 * @returns {{ all: number, urgent: number, warn: number, normal: number }}
 */
export function countByLevel(list) {
  const out = { all: 0, urgent: 0, warn: 0, normal: 0 };
  (list || []).forEach((it) => {
    out.all += 1;
    if (out[it.level] !== undefined) out[it.level] += 1;
  });
  return out;
}
