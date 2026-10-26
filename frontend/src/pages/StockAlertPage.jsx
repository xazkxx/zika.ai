/* ==========================================================================
 * 库存预警看板 · 页面壳
 * ---------------------------------------------------------------------------
 * 放到 E:\AI\ERP软件\frontend\src\pages\StockAlertPage.jsx
 *
 * 说明：这个页面不需要 ctx 里的任何东西（数据由组件自己请求），
 * 所以不接收参数也能跑。留着 props 占位是为了和你其他 45 个页面
 * 保持同一种写法，将来要接全局刷新 / 权限时直接从 ctx 里取。
 *
 * 如果你嫌多一个文件麻烦，也可以跳过它，
 * 直接在 App.jsx 里 import 组件本身 —— 见 INTEGRATION.md 的「方案 A」。
 * ========================================================================== */

import StockAlertDashboard from '../components/stock-alert';

/**
 * @param {{ ctx?: Record<string, unknown> }} _props
 */
// eslint-disable-next-line no-unused-vars
export default function StockAlertPage(_props) {
  return <StockAlertDashboard title="库存预警看板" />;
}
