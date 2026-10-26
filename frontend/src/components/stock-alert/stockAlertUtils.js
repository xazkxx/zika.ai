/* ==========================================================================
 * 纯函数工具：零 React 依赖、零副作用
 * ---------------------------------------------------------------------------
 * 类型说明统一用 JSDoc 表达，不引入任何 TypeScript 文件。
 * ========================================================================== */

/**
 * 二维点
 * @typedef {Object} Pt
 * @property {number} x
 * @property {number} y
 */

/**
 * 带原始值的点，用于悬浮命中
 * @typedef {Pt & { v: number }} ValuePt
 */

/**
 * 一套轴刻度的区间描述
 * @typedef {Object} Scale
 * @property {number} min
 * @property {number} max
 * @property {number} step
 * @property {number} ticks 区间个数（刻度线数量 = ticks + 1）
 */

/**
 * 千分位整数
 * @param {number} [n]
 * @returns {string}
 */
export const fmtInt = (n) => Number(n || 0).toLocaleString('zh-CN');

/**
 * 按单位格式化：百分比保留 1 位小数，其余取整加千分位
 * @param {number} n
 * @param {string} unit
 * @returns {string}
 */
export const fmtByUnit = (n, unit) => {
  if (unit === '%') return `${Number(n ?? 0).toFixed(1)}%`;
  return fmtInt(Math.round(n));
};

/**
 * 天数格式化：保留 1 位小数；算不出（Infinity / NaN）时返回破折号
 *
 * 日均出库为 0 时可用天数是 Infinity，直接显示 "Infinity 天" 会很难看，
 * 统一交给这里处理。
 *
 * @param {number} days
 * @returns {string}
 */
export const fmtDays = (days) => (Number.isFinite(days) ? Number(days).toFixed(1) : '—');

/**
 * 2026-10-15T15:28:00+08:00 -> 2026-10-15 15:28
 * @param {string} [input]
 * @returns {string}
 */
export function formatDateTime(input) {
  const d = input ? new Date(input) : new Date();
  if (Number.isNaN(d.getTime())) return '';
  /** @param {number} n */
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * [{x,y}] -> "M0 0L10 10"
 * @param {Pt[]} points
 * @returns {string}
 */
export function buildPath(points) {
  return points
    .map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');
}

/**
 * 折线闭合到底边，用来铺渐变面积
 * @param {Pt[]} points
 * @param {number} baseY
 * @returns {string}
 */
export function buildAreaPath(points, baseY) {
  if (!points.length) return '';
  const last = points[points.length - 1];
  const first = points[0];
  return `${buildPath(points)} L${last.x.toFixed(1)} ${baseY} L${first.x.toFixed(1)} ${baseY} Z`;
}

/**
 * 求「好看」的刻度区间，支持负值（右轴同比增速要用到）
 *
 * 候选步长会在 [1,2,2.5,5,10]×10^n 里挑，并允许「略小于理想步长」的候选
 * （容差 15%）。否则理想步长 502 撞上候选 500 会跳到 1000，
 * 白白浪费一大截轴高。
 *
 * niceScale(0, 1880, 4)    -> { min:0,   max:2000, step:500, ticks:4 }
 * niceScale(-8.6, 21.4, 4) -> { min:-10, max:30,   step:10,  ticks:4 }
 *
 * @param {number} min
 * @param {number} max
 * @param {number} [targetTicks]
 * @returns {Scale}
 */
export function niceScale(min, max, targetTicks = 4) {
  let lo = min;
  let hi = max;
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 10; }
  if (hi === lo) hi = lo + 1;

  const rawStep = (hi - lo) / targetTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const candidates = [1, 2, 2.5, 5, 10].map((n) => n * mag);

  const usable = candidates.filter((c) => c >= rawStep * 0.85);
  const step = usable.length ? usable[0] : candidates[candidates.length - 1];

  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  return { min: niceMin, max: niceMax, step, ticks: Math.round((niceMax - niceMin) / step) };
}

/**
 * X 轴标签抽稀步长：>12 个点时每 2 天显示一个，保持界面清爽
 * @param {number} labelCount
 * @returns {number}
 */
export const xTickEvery = (labelCount) => (labelCount > 12 ? 2 : 1);
