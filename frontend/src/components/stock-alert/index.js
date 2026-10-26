/* ==========================================================================
 * 库存预警看板 · 统一出口（纯 JavaScript，无任何 TypeScript 语法）
 * ---------------------------------------------------------------------------
 * 用法（本项目没配 @ 别名，用相对路径）：
 *   // src/pages/ 下的页面
 *   import { StockAlertDashboard } from '../components/stock-alert';
 *
 *   // src/App.jsx
 *   import { StockAlertDashboard } from './components/stock-alert';
 *
 *   <StockAlertDashboard />
 *
 * 也可以单独用某个子组件（记得外层套一个 .erpstock 容器，
 * 否则 CSS 变量取不到值）：
 *   import { KpiCards, StockTrendChart, AlertList } from '../components/stock-alert';
 *
 * 数据结构说明见 ./stockAlertApi.js 顶部的 JSDoc。
 * ========================================================================== */

/* 子组件在桶里统一加 Stock 前缀：dashboard 桶也导出了 KpiCards，
   万一某个文件同时引两个桶，命名不会打架 */
export { default as StockAlertDashboard } from './StockAlertDashboard';
export { default as StockKpiCards } from './KpiCards';
export { default as StockTrendChart } from './StockTrendChart';
export { default as StockAlertList } from './AlertList';

export { fetchStockAlert, getStockAlertMock, STOCK_ALERT_ENDPOINT, MOCK_STOCK_ALERT, RANGE_OPTIONS } from './stockAlertApi';

/* 紧急度判定规则集中在这里 —— 改阈值只改这个文件 */
export {
  ALERT_LEVELS,
  ALERT_THRESHOLDS,
  LEVEL_META,
  FILTER_OPTIONS,
  daysOfSupply,
  levelFromDays,
  enrichAlert,
  enrichAlerts,
  countByLevel,
} from './alertRules';

export {
  fmtInt,
  fmtByUnit,
  fmtDays,
  formatDateTime,
  buildPath,
  buildAreaPath,
  niceScale,
  xTickEvery,
} from './stockAlertUtils';

export { default } from './StockAlertDashboard';
