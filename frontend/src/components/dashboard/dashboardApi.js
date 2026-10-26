/* ==========================================================================
 * 数据层：Mock 数据 + 接口入口
 * ---------------------------------------------------------------------------
 * 原来是 types.ts，现在按你的要求合并进 JS：类型说明全部用 JSDoc 表达，
 * 不产生任何 TypeScript 文件，也不会影响构建。
 *
 * 【KPI 结构】
 *   {
 *     key, label, value, unit, delta, trend, note, polarity, color, spark
 *   }
 *   trend    : 'up' | 'down' | 'flat'   只看数值方向，决定 涨红/跌绿
 *   polarity : 'normal' | 'inverse'     业务语义。inverse = 涨了是坏事
 *              （待处理订单 / 库存预警 / 应收账款），上涨会额外标「需关注」
 *
 *   注意：色值永远跟随数值方向（涨红跌绿），业务好坏只由状态标区分。
 *        不要为了"好看"把预警指标的上涨画成绿色，会误导值班判断。
 *
 * 【图表结构】
 *   { unit, labels, series: [{ name, type, axis, color, data }] }
 *   type : 'area' 面积主线 | 'line' 虚线
 *   axis : 'left' | 'right'   双轴：左右各一套独立刻度
 *
 * 【接口】GET /api/erp/dashboard?range=7d|30d  ->  DashboardData
 * ========================================================================== */

/**
 * 数值方向
 * @typedef {'up' | 'down' | 'flat'} Trend
 */

/**
 * 业务语义
 * @typedef {'normal' | 'inverse'} Polarity
 */

/**
 * 图形类型 / 双轴归属 / 时间区间
 * @typedef {'area' | 'line'} SeriesType
 * @typedef {'left' | 'right'} AxisSide
 * @typedef {'7d' | '30d'} RangeKey
 */

/**
 * 单个 KPI 指标
 * @typedef {Object} KpiItem
 * @property {string} key 唯一 key，同时作为 data-key 输出
 * @property {string} label 指标名
 * @property {number} value 指标值
 * @property {string} unit 单位，'%' 走两位小数、其余走千分位整数
 * @property {number} delta 环比变化，正负号自带（-6 表示下降 6%）
 * @property {Trend} trend
 * @property {string} note 对比口径说明，如「较昨日」
 * @property {Polarity} polarity
 * @property {string} color 卡片主色，同时用于圆点和迷你趋势线
 * @property {number[]} spark 迷你趋势线的原始点，长度不限
 */

/**
 * 一条曲线
 * @typedef {Object} ChartSeries
 * @property {string} name
 * @property {SeriesType} type
 * @property {AxisSide} axis
 * @property {string} color
 * @property {number[]} data 长度必须与 ChartConfig.labels 一致
 */

/**
 * 图表配置
 * @typedef {Object} ChartConfig
 * @property {string} unit
 * @property {string[]} labels
 * @property {ChartSeries[]} series
 */

/**
 * 看板接口返回体
 * @typedef {Object} DashboardData
 * @property {KpiItem[]} kpis
 * @property {ChartConfig} chart
 * @property {string} updatedAt ISO 8601，如 2026-10-15T15:28:00+08:00
 */

/**
 * 时间区间选项
 * @typedef {Object} RangeOption
 * @property {RangeKey} value
 * @property {string} label
 */

/** @type {KpiItem[]} */
const MOCK_KPIS = [
  {
    key: 'sales',
    label: '今日销售额',
    value: 386420,
    unit: '元',
    delta: 12.4,
    trend: 'up',
    note: '较昨日',
    polarity: 'normal',
    color: '#3370ff',
    spark: [28, 33, 30, 41, 38, 45, 52],
  },
  {
    key: 'pendingOrders',
    label: '待处理订单',
    value: 128,
    unit: '单',
    delta: 18.5,
    trend: 'up',
    note: '较昨日',
    polarity: 'inverse',
    color: '#f59e0b',
    spark: [62, 58, 66, 71, 68, 78, 86],
  },
  {
    key: 'lowStock',
    label: '库存预警商品',
    value: 47,
    unit: '件',
    delta: -6.0,
    trend: 'down',
    note: '较昨日',
    polarity: 'inverse',
    color: '#e5484d',
    spark: [58, 61, 55, 52, 50, 48, 47],
  },
  {
    key: 'receivable',
    label: '应收账款',
    value: 2845600,
    unit: '元',
    delta: 3.2,
    trend: 'up',
    note: '较上月',
    polarity: 'inverse',
    color: '#7b61ff',
    spark: [70, 72, 71, 74, 76, 78, 80],
  },
];

/** @type {Record<RangeKey, ChartConfig>} */
const MOCK_CHART = {
  '7d': {
    unit: '万元',
    labels: ['10-09', '10-10', '10-11', '10-12', '10-13', '10-14', '10-15'],
    series: [
      { name: '销售额', type: 'area', axis: 'left', color: '#3370ff', data: [116, 105, 92, 86, 128, 136, 142] },
      { name: '同比增速', type: 'line', axis: 'right', color: '#f59e0b', data: [14.2, 9.6, 5.3, 2.1, 19.2, 20.6, 21.8] },
    ],
  },
  '30d': {
    unit: '万元',
    labels: [
      '09-16', '09-17', '09-18', '09-19', '09-20', '09-21', '09-22', '09-23', '09-24', '09-25',
      '09-26', '09-27', '09-28', '09-29', '09-30', '10-01', '10-02', '10-03', '10-04', '10-05',
      '10-06', '10-07', '10-08', '10-09', '10-10', '10-11', '10-12', '10-13', '10-14', '10-15',
    ],
    series: [
      {
        name: '销售额', type: 'area', axis: 'left', color: '#3370ff',
        data: [
          88, 92, 96, 84, 76, 71, 95, 99, 103, 97,
          89, 78, 73, 101, 108, 62, 58, 54, 66, 74,
          112, 118, 124, 116, 105, 92, 86, 128, 136, 142,
        ],
      },
      {
        name: '同比增速', type: 'line', axis: 'right', color: '#f59e0b',
        data: [
          6.2, 8.4, 10.1, 4.3, -1.2, -4.6, 7.8, 9.5, 12.3, 8.9,
          3.1, -2.4, -5.1, 11.2, 14.6, -6.4, -7.8, -8.2, -5.4, -3.2,
          15.3, 17.8, 18.4, 14.2, 9.6, 5.3, 2.1, 19.2, 20.6, 21.8,
        ],
      },
    ],
  },
};

const MOCK_UPDATED_AT = '2026-10-15T15:28:00+08:00';

/**
 * @param {number} ms
 * @returns {Promise<void>}
 */
const delay = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * 看板数据入口
 * ---------------------------------------------------------------------------
 * 目前返回假数据。接后端时只改这一个函数，渲染层完全不用动：
 *
 *   export async function fetchDashboard(range = '7d', { signal } = {}) {
 *     const res = await fetch(`/api/erp/dashboard?range=${range}`, { signal });
 *     if (!res.ok) throw new Error(`接口异常：${res.status}`);
 *     return res.json();
 *   }
 *
 * @param {RangeKey} [range]
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<DashboardData>}
 */
export async function fetchDashboard(range = '7d', { signal } = {}) {
  // 模拟网络延迟，方便验证 loading 骨架屏；真实环境请删掉
  await delay(220);
  if (signal && signal.aborted) {
    const err = new Error('aborted');
    err.name = 'AbortError';
    throw err;
  }
  return {
    kpis: MOCK_KPIS,
    chart: MOCK_CHART[range] || MOCK_CHART['7d'],
    updatedAt: MOCK_UPDATED_AT,
  };
}

/** 导出原始 mock，方便写测试或做 Storybook */
export const MOCK_DASHBOARD = {
  kpis: MOCK_KPIS,
  chart: MOCK_CHART,
  updatedAt: MOCK_UPDATED_AT,
};

/** @type {RangeOption[]} */
export const RANGE_OPTIONS = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
];
