/* ==========================================================================
 * 纯函数工具：零 React 依赖、零副作用，可单独单测 / 复用到其他页面
 * ---------------------------------------------------------------------------
 * 类型说明统一用 JSDoc 表达，不引入任何 TypeScript 文件。
 * ========================================================================== */

/**
 * 二维点，绘图与几何计算共用
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
 * 按单位格式化：百分比保留 2 位小数，其余取整加千分位
 * @param {number} n
 * @param {string} unit
 * @returns {string}
 */
export const fmtByUnit = (n, unit) =>
  unit === '%' ? Number(n ?? 0).toFixed(2) : fmtInt(Math.round(n));

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
 * niceScale(0, 142, 4)     -> { min:0,   max:150, step:50, ticks:3 }
 * niceScale(-8.2, 21.8, 4) -> { min:-10, max:30,  step:10, ticks:4 }
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

  let step = candidates[candidates.length - 1];
  for (let i = 0; i < candidates.length; i += 1) {
    if (candidates[i] >= rawStep) { step = candidates[i]; break; }
  }

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
