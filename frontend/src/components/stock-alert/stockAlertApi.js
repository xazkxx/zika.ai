/* ==========================================================================
 * 数据层：Mock 数据 + 接口入口
 * ---------------------------------------------------------------------------
 * 纯 JavaScript + JSDoc，无任何 TypeScript 文件。
 *
 * 【KPI 结构】同 ERP 看板的约定，保持一致
 *   { key, label, value, unit, delta, trend, note, polarity, color, spark }
 *   trend    : 'up' | 'down' | 'flat'   只看数值方向，决定 涨红/跌绿
 *   polarity : 'normal' | 'inverse'     inverse = 涨了是坏事，会标「需关注」
 *
 * 【图表结构】双轴
 *   {
 *     leftTitle, leftUnit,      左轴标题/单位（数量类）
 *     rightTitle, rightUnit,    右轴标题/单位（百分比）
 *     labels: string[],
 *     series: [{ name, type, axis, color, data }]
 *   }
 *   type : 'area' 面积主线 | 'line' 实线 | 'dashed' 虚线
 *   axis : 'left' | 'right'
 *
 * 【预警明细结构】—— 这里写的是「后端只需要给的原始字段」
 *   { id, sku, name, warehouse, stock, safetyStock, dailyOut, suggest }
 *   派生字段（gap 缺口 / daysLeft 可用天数 / level 紧急度）由 alertRules.js 前端算，
 *   后端不用返回。判定口径见 alertRules.js 顶部注释。
 *
 * 【接口】✅ 已指向真实地址 /api/v1/erp/stock-alert
 * ========================================================================== */

/**
 * @typedef {'up' | 'down' | 'flat'} Trend
 * @typedef {'normal' | 'inverse'} Polarity
 * @typedef {'area' | 'line' | 'dashed'} SeriesType
 * @typedef {'left' | 'right'} AxisSide
 * @typedef {'urgent' | 'warn' | 'normal'} AlertLevel
 * @typedef {'30d' | '7d'} RangeKey
 * @typedef {'all' | AlertLevel} AlertFilter
 */

/**
 * @typedef {Object} KpiItem
 * @property {string} key
 * @property {string} label
 * @property {number} value
 * @property {string} unit
 * @property {number} delta
 * @property {Trend} trend
 * @property {string} note
 * @property {Polarity} polarity
 * @property {string} color
 * @property {number[]} spark
 */

/**
 * @typedef {Object} ChartSeries
 * @property {string} name
 * @property {SeriesType} type
 * @property {AxisSide} axis
 * @property {string} color
 * @property {number[]} data
 */

/**
 * @typedef {Object} ChartConfig
 * @property {string} leftTitle
 * @property {string} leftUnit
 * @property {string} rightTitle
 * @property {string} rightUnit
 * @property {string[]} labels
 * @property {ChartSeries[]} series
 */

/**
 * 后端返回的原始预警明细（不含派生字段）
 * @typedef {Object} RawAlertItem
 * @property {string} id
 * @property {string} sku
 * @property {string} name
 * @property {string} warehouse
 * @property {number} stock          当前库存
 * @property {number} safetyStock    安全库存
 * @property {number} dailyOut       日均出库（件/天）—— 用来算可用天数；0 表示不动销
 * @property {number} suggest        建议补货量
 */

/**
 * 前端补全后的预警明细（视图模型）
 * @typedef {RawAlertItem & {
 *   gap: number,          缺口 = safetyStock - stock
 *   daysLeft: number,     预计可用天数 = stock / dailyOut，算不出时是 Infinity
 *   level: AlertLevel,    紧急度，按 daysLeft 分档
 * }} AlertItem
 */

/**
 * @typedef {Object} StockAlertData
 * @property {KpiItem[]} kpis
 * @property {ChartConfig} chart
 * @property {RawAlertItem[]} alerts
 * @property {string} updatedAt
 */

/** @type {KpiItem[]} */
const MOCK_KPIS = [
  {
    key: 'totalStock',
    label: '总库存',
    value: 128460,
    unit: '件',
    delta: 2.1,
    trend: 'up',
    note: '较上周',
    polarity: 'normal',
    color: '#3370ff',
    spark: [58, 61, 60, 63, 66, 65, 68],
  },
  {
    key: 'inbound',
    label: '待入库',
    value: 36,
    unit: '单',
    delta: 12.5,
    trend: 'up',
    note: '较昨日',
    polarity: 'inverse',
    color: '#f59e0b',
    spark: [24, 26, 31, 28, 33, 34, 36],
  },
  {
    key: 'outbound',
    label: '待出库',
    value: 52,
    unit: '单',
    delta: -8.3,
    trend: 'down',
    note: '较昨日',
    polarity: 'inverse',
    color: '#7b61ff',
    spark: [64, 66, 61, 58, 56, 54, 52],
  },
  {
    key: 'shortage',
    label: '缺货商品',
    value: 18,
    unit: '种',
    delta: 28.6,
    trend: 'up',
    note: '较昨日',
    polarity: 'inverse',
    color: '#e5484d',
    spark: [9, 10, 12, 11, 14, 16, 18],
  },
];

const LABELS_30D = [
  '09-16', '09-17', '09-18', '09-19', '09-20', '09-21', '09-22', '09-23', '09-24', '09-25',
  '09-26', '09-27', '09-28', '09-29', '09-30', '10-01', '10-02', '10-03', '10-04', '10-05',
  '10-06', '10-07', '10-08', '10-09', '10-10', '10-11', '10-12', '10-13', '10-14', '10-15',
];

const INBOUND_30D = [
  1180, 1240, 1310, 1120, 980, 920, 1260,
  1330, 1420, 1290, 1150, 1010, 960, 1380, 1460,
  820, 760, 700, 880, 960, 1520, 1610, 1680,
  1540, 1390, 1220, 1130, 1720, 1810, 1880,
];

const OUTBOUND_30D = [
  1290, 1350, 1420, 1180, 1050, 990, 1370,
  1450, 1520, 1380, 1240, 1090, 1020, 1490, 1580,
  900, 830, 760, 940, 1030, 1650, 1740, 1820,
  1660, 1480, 1300, 1180, 1760, 1850, 1930,
];

// 出库量同比增速，跨正负区间（用来验证右轴的 0% 基准线）
const YOY_30D = [
  8.4, 10.2, 12.1, 5.3, -1.8, -5.2, 9.6,
  11.4, 13.8, 10.1, 4.7, -2.9, -6.4, 12.6, 15.2,
  -7.2, -8.4, -8.6, -6.8, -3.4, 16.8, 19.2, 20.4,
  15.6, 10.8, 6.2, 2.4, 18.6, 20.8, 21.4,
];

/** @type {Record<RangeKey, ChartConfig>} */
const MOCK_CHART = {
  '30d': {
    leftTitle: '出入库量',
    leftUnit: '件',
    rightTitle: '出库同比',
    rightUnit: '%',
    labels: LABELS_30D,
    series: [
      { name: '入库量', type: 'area', axis: 'left', color: '#3370ff', data: INBOUND_30D },
      { name: '出库量', type: 'line', axis: 'left', color: '#17a34a', data: OUTBOUND_30D },
      { name: '同比增速', type: 'dashed', axis: 'right', color: '#f59e0b', data: YOY_30D },
    ],
  },
  '7d': {
    leftTitle: '出入库量',
    leftUnit: '件',
    rightTitle: '出库同比',
    rightUnit: '%',
    labels: LABELS_30D.slice(-7),
    series: [
      { name: '入库量', type: 'area', axis: 'left', color: '#3370ff', data: INBOUND_30D.slice(-7) },
      { name: '出库量', type: 'line', axis: 'left', color: '#17a34a', data: OUTBOUND_30D.slice(-7) },
      { name: '同比增速', type: 'dashed', axis: 'right', color: '#f59e0b', data: YOY_30D.slice(-7) },
    ],
  },
};

/**
 * @type {RawAlertItem[]}
 *
 * 刻意只给原始字段（没有 level）—— 紧急度由 alertRules.js 按可用天数算。
 * 这样以后调阈值不用动 mock，也顺带验证了派生逻辑真的生效。
 *
 * 这批数据按「可用天数 = stock / dailyOut」正好落在三个档：
 *   A03/A01/A02/A04/A06/A05   1.7 ~ 2.9 天  →  紧急
 *   A08/A07/A10/A11/A09/A12   4.0 ~ 6.0 天  →  预警
 *   其余 6 条                 8.3 ~ 8.9 天  →  正常
 * A18 的日均出库故意给 0（不动销），用来验证「算不出天数 → 显示 — → 判为正常」。
 */
const MOCK_ALERTS = [
  { id: 'A01', sku: 'SKU-M185', name: '无线鼠标 M185', warehouse: '上海主仓', stock: 12, safetyStock: 80, dailyOut: 6, suggest: 200 },
  { id: 'A02', sku: 'SKU-K380', name: '机械键盘 K380', warehouse: '上海主仓', stock: 24, safetyStock: 100, dailyOut: 9, suggest: 150 },
  { id: 'A03', sku: 'SKU-P270', name: '27 寸显示器 P27', warehouse: '广州仓', stock: 5, safetyStock: 40, dailyOut: 3, suggest: 60 },
  { id: 'A04', sku: 'SKU-DOCK', name: 'USB-C 扩展坞', warehouse: '广州仓', stock: 33, safetyStock: 90, dailyOut: 12, suggest: 120 },
  { id: 'A05', sku: 'SKU-H500', name: '降噪耳机 H500', warehouse: '深圳仓', stock: 41, safetyStock: 120, dailyOut: 14, suggest: 180 },
  { id: 'A06', sku: 'SKU-HD1T', name: '移动硬盘 1TB', warehouse: '深圳仓', stock: 58, safetyStock: 150, dailyOut: 20, suggest: 200 },
  { id: 'A07', sku: 'SKU-WCP1', name: '无线充电板', warehouse: '上海主仓', stock: 66, safetyStock: 140, dailyOut: 15, suggest: 150 },
  { id: 'A08', sku: 'SKU-S20', name: '蓝牙音箱 S20', warehouse: '广州仓', stock: 72, safetyStock: 130, dailyOut: 18, suggest: 100 },
  { id: 'A09', sku: 'SKU-C920', name: '高清摄像头 C920', warehouse: '深圳仓', stock: 88, safetyStock: 160, dailyOut: 16, suggest: 120 },
  { id: 'A10', sku: 'SKU-NET5', name: '网线 5 米', warehouse: '上海主仓', stock: 95, safetyStock: 150, dailyOut: 20, suggest: 80 },
  { id: 'A11', sku: 'SKU-TC10', name: 'Type-C 数据线', warehouse: '广州仓', stock: 110, safetyStock: 200, dailyOut: 22, suggest: 150 },
  { id: 'A12', sku: 'SKU-ARM1', name: '显示器支架', warehouse: '深圳仓', stock: 126, safetyStock: 180, dailyOut: 21, suggest: 80 },
  { id: 'A13', sku: 'SKU-MOU2', name: '有线鼠标 M100', warehouse: '上海主仓', stock: 134, safetyStock: 200, dailyOut: 15, suggest: 100 },
  { id: 'A14', sku: 'SKU-KB2', name: '薄膜键盘 K120', warehouse: '广州仓', stock: 141, safetyStock: 200, dailyOut: 17, suggest: 90 },
  { id: 'A15', sku: 'SKU-PAD1', name: '鼠标垫 大号', warehouse: '深圳仓', stock: 152, safetyStock: 210, dailyOut: 18, suggest: 80 },
  { id: 'A16', sku: 'SKU-SPK2', name: '桌面音箱 SP2', warehouse: '上海主仓', stock: 163, safetyStock: 220, dailyOut: 19, suggest: 80 },
  { id: 'A17', sku: 'SKU-HUB4', name: 'USB 集线器 4 口', warehouse: '广州仓', stock: 174, safetyStock: 230, dailyOut: 20, suggest: 70 },
  { id: 'A18', sku: 'SKU-STD1', name: '笔记本支架', warehouse: '深圳仓', stock: 185, safetyStock: 240, dailyOut: 0, suggest: 70 },
];

const MOCK_UPDATED_AT = '2026-10-15T16:10:00+08:00';

/** 真实接口地址（和 src/lib/appLib.js 里的 API_BASE = '/api/v1' 对齐） */
export const STOCK_ALERT_ENDPOINT = '/api/v1/erp/stock-alert';

/**
 * @param {number} ms
 * @returns {Promise<void>}
 */
const delay = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

/**
 * 库存预警看板数据入口 —— 真实 API
 * ---------------------------------------------------------------------------
 * 后端只需要保证返回四个字段，渲染层完全不用动：
 *
 *   kpis        KPI 卡片数组（4 项）
 *   chart       图表配置（含 labels + series）
 *   alerts      预警明细数组（只给原始字段）
 *   updatedAt   数据更新时间
 *
 * 字段名做了兼容：chart / chartData 都认，alerts / list 都认。
 * 所以你后端叫 chartData + list 也行，不用改这里。
 *
 * alerts 里只给原始字段即可，gap / daysLeft / level 由 alertRules.js 在前端算。
 *
 * 如果后端字段名和上面完全不一样（比如 kpiList / data），在下面的 return 里
 * 加一行映射就行，组件一个字都不用动。
 *
 * 【为什么要带 Authorization】本项目是多账套的：`get_db()` 按 token 里的账套
 * 把会话接到对应的 schema。不带 token 时后端只能落到**第一个账套** ——
 * 界面右上角切了账套，看板里的数却还是老账套的，属于最难排查的那类静默错账。
 * token 就放在 localStorage（与 App.jsx 的 authHeaders 同一个来源）。
 *
 * @param {RangeKey} [range]
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<StockAlertData>}
 */
export async function fetchStockAlert(range = '30d', { signal } = {}) {
  const token = localStorage.getItem('erp_token') || '';
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${STOCK_ALERT_ENDPOINT}?range=${encodeURIComponent(range)}`, {
    headers,
    signal,
  });
  if (!res.ok) throw new Error(`接口异常：${res.status} ${res.statusText}`);
  const json = await res.json();

  return {
    kpis: json.kpis ?? [],
    // 后端叫 chart 或 chartData 都行
    chart: json.chart ?? json.chartData ?? null,
    // 后端叫 alerts 或 list 都行
    alerts: json.alerts ?? json.list ?? [],
    updatedAt: json.updatedAt ?? '',
  };
}

/**
 * 离线兜底：拿不到后端数据时退回这份 mock。
 *
 * 接口还没上线、或者后端挂了想先看界面时，把 StockAlertDashboard.jsx 里的
 * USE_MOCK 改成 true 即可。线上不要用。
 *
 * 刻意保留 180ms 延迟：一来这样骨架屏 / loading 转圈在本地也能看到（否则
 * 同步返回会让加载态一闪而过，等于没法调），二来让 mock 和真实接口的行为一致。
 *
 * @param {RangeKey} [range]
 * @returns {Promise<StockAlertData>}
 */
export async function getStockAlertMock(range = '30d') {
  await delay(180);
  return {
    kpis: MOCK_KPIS,
    chart: MOCK_CHART[range] || MOCK_CHART['30d'],
    alerts: MOCK_ALERTS,
    updatedAt: MOCK_UPDATED_AT,
  };
}

/** 导出原始 mock，方便写测试 */
export const MOCK_STOCK_ALERT = {
  kpis: MOCK_KPIS,
  chart: MOCK_CHART,
  alerts: MOCK_ALERTS,
  updatedAt: MOCK_UPDATED_AT,
};

/** @type {{ value: RangeKey, label: string }[]} */
export const RANGE_OPTIONS = [
  { value: '30d', label: '近 30 天' },
  { value: '7d', label: '近 7 天' },
];
