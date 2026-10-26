/* ==========================================================================
 * ERP 经营看板 · 统一出口（纯 JavaScript，无任何 TypeScript 语法）
 * ---------------------------------------------------------------------------
 * 用法（本项目没配 @ 别名，用相对路径）：
 *   // src/pages/ 下的页面
 *   import { Dashboard } from '../components/dashboard';
 *
 *   // src/App.jsx
 *   import { Dashboard } from './components/dashboard';
 *
 *   <Dashboard />
 *
 * 也可以单独用某个子组件（记得外层套一个 .erpdash 容器，
 * 否则 CSS 变量取不到值）：
 *   import { KpiCards, TrendChart } from '../components/dashboard';
 *
 * 数据结构说明见 ./dashboardApi.js 顶部的 JSDoc。
 * ========================================================================== */

export { default as Dashboard } from './Dashboard';
export { default as KpiCards } from './KpiCards';
export { default as TrendChart } from './TrendChart';

export { fetchDashboard, MOCK_DASHBOARD, RANGE_OPTIONS } from './dashboardApi';
export {
  fmtInt,
  fmtByUnit,
  formatDateTime,
  buildPath,
  buildAreaPath,
  niceScale,
  xTickEvery,
} from './dashboardUtils';

export { default } from './Dashboard';
