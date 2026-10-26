/**
 * 销售出库 · 多单位换算 —— 桶文件（第三阶段 3c）
 *
 * 用法（独立挂载，**不改 App.jsx 核心逻辑**）：
 *
 *   import { SalesOrderUnitsBoard } from './components/sales-units';
 *
 *   <SalesOrderUnitsBoard
 *     apiBase={API_BASE}                 // '/api/v1'
 *     authHeaders={authHeaders}          // () => ({ Authorization: 'Bearer …' })
 *     onNotice={setNotice}
 *     onError={setError}
 *   />
 *
 * 接进 `App.jsx` 的完整做法（共 3 处改动，行号以当时文件为准）：
 *   ① 顶部 import 一行；
 *   ② `menuGroups`/`pageActions` 里加一个菜单项，`pageKey` 例如 `sales-units`；
 *   ③ 分发区（~10790 行的 `{selectedTab === '…' && …}` 区）加一行
 *      `{selectedTab === 'sales-units' && <SalesOrderUnitsBoard … />}`。
 *
 * 之所以先做成独立组件：它只吃 4 个 props，不依赖 `ctx` 里那几十个
 * App.jsx 状态，所以可以**先在测试台里单独挂载跑通**再合并
 * （见 `_product_units_step3/verify_3c_frontend/`）。
 *
 * 业务说明见 `./SalesOrderUnitsBoard.jsx` 顶部；纯换算逻辑见 `src/lib/salesUnits.js`。
 */

export { default as SalesOrderUnitsBoard } from './SalesOrderUnitsBoard.jsx';
export { default as SalesOrderUnitsModal } from './SalesOrderUnitsModal.jsx';
export { default as UnitSelectCell } from './UnitSelectCell.jsx';
export { BaseQuantityCell } from './UnitSelectCell.jsx';

export { default } from './SalesOrderUnitsBoard.jsx';
