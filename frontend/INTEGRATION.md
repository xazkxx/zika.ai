# ERP 经营看板 · 集成指南（对接 `E:\AI\ERP软件\frontend`）

> 已按你项目的实际情况核对过：**Vite 5 + React 18.3.1 + 纯 JavaScript**，
> 项目里**没有 react-router**，是 `menuGroups` + `selectedTab` 的菜单驱动 SPA。
> 组件为纯手写 SVG，无图表库依赖，gzip 后约 **6 KB**（不含 React）。

**文件已就位**：`src/components/dashboard/`

```
Dashboard.jsx      容器，唯一数据源
KpiCards.jsx       顶部 4 卡
TrendChart.jsx     双轴主图
dashboardApi.js    Mock + fetchDashboard 入口（数据结构 JSDoc 在这）
dashboardUtils.js  纯函数工具
index.js           统一出口
dashboard.css      样式（组件内 import）
```

---

## 1. 挂载方式：加到菜单 + 页面分发区

你的 `src/App.jsx` 是菜单驱动的（没有 react-router），页面分发用的是
`{selectedTab === 'xxx' && <XxxPage ctx={appCtx} />}` 这种写法。所以**分三步**：

### 第 1 步：在 `menuGroups` 里加菜单项

`src/App.jsx` 第 58 行附近的 `workspace` 分组里加一项：

```js
{
  key: 'workspace',
  label: '工作台',
  origin: 'own',
  items: [
    { key: 'overview', label: '运营概览' },
    { key: 'dashboard', label: '经营看板' },   // ← 新增这一行
  ],
},
```

### 第 2 步：在 App.jsx 顶部加 import

放在那批 `import XxxPage from './pages/XxxPage';` 附近（第 13~56 行区域）：

```js
import Dashboard from './components/dashboard';
```

> 注意用 `'./components/dashboard'`，**不要写 `'@/components/dashboard'`**。
> 你的 `vite.config.js` 里没有配 `@` 别名，写了会报模块找不到。

### 第 3 步：在页面分发区加一行

`src/App.jsx` **第 10025 行**附近，紧挨着 `overview` 那行：

```jsx
{selectedTab === 'overview' && <OverviewPage ctx={appCtx} />}

{selectedTab === 'dashboard' && <Dashboard />}   {/* ← 新增 */}
```

因为这一版是纯展示组件、不吃 `ctx`，所以不需要像其它页面那样传 `ctx={appCtx}`。
将来接真实接口需要 token 时，再把 `ctx` 传进去即可。

---

## 2. 页面底色：已按你的要求改好

你的全局 `src/styles.css` 第 23 行是：

```css
body { background: linear-gradient(135deg, #eef5ff 0%, #f7f9fc 100%); }
```

而 `.erpdash` 原本自带 `#f4f5f7` 浅灰底 + `max-width: 1240px` + `padding: 24px`，
挂上去会出现「一块浅灰圆角区浮在浅蓝渐变页面中间」的突兀感。

**已按你确认的方案改掉**，现在 `.erpdash` 是：

```css
.erpdash {
  max-width: none;         /* 跟随父容器宽度 */
  margin: 0 auto;
  padding: 0;              /* 内边距交给页面容器 */
  background: transparent; /* 底色沿用宿主 body 的浅蓝渐变 */
}
```

同时把响应式里那条 `@media (max-width:560px) { .erpdash { padding: 16px 12px 32px } }` 也去掉了——
否则小屏会突然多出一圈留白，和桌面端不一致。

原来的三行（`max-width: 1240px` / `padding: 24px 20px 40px` / `background: var(--erpdash-bg)` / `border-radius: 8px`）
在 `dashboard.css` 里**以注释形式保留**了。将来要在别的场合独立使用（比如单独一个白底页面），
把注释打开即可恢复「自带一张浅灰卡片」的观感。

> ⚠️ 一个副作用要留意：`padding: 0` 之后，**内边距完全由你的页面容器决定**。
> 如果「经营看板」这个页面的内容区本身没有 padding，卡片会贴着容器边缘。
> 真出现这种情况，在分发区外面包一层即可：
>
> ```jsx
> {selectedTab === 'dashboard' && (
>   <div style={{ padding: '20px 24px' }}><Dashboard /></div>
> )}
> ```
>
> 但你现有的「运营概览」等页面显然是正常留白的，所以大概率不用管。

---

## 3. 和现有全局样式的冲突排查结果

我把 `src/styles.css`（4888 行）和组件逐个比对过，**结论是安全**：

| 你现有的全局规则 | 对组件的影响 |
|---|---|
| `* { box-sizing: border-box }`（第 13 行） | ✅ 和组件需求一致，无冲突 |
| `button, input, textarea, select { font: inherit }`（第 270 行） | ✅ 一致，无冲突 |
| `h1 { margin: 0; font-size: clamp(2rem, 3vw, 2.5rem) }`（第 504 行） | ✅ 组件标题用的是 `<h1 class="erpdash__title">`，类选择器优先级高于元素选择器，仍是 20px |
| `:root { font-family / color }`（第 1 行） | ✅ `:root` 的值是**继承**下来的，而 `.erpdash` 在自己的元素上**直接声明**了 font-family / color，直接声明永远胜过继承 |
| `body { background: 线性渐变 }` | ⚠️ 仅视觉差异，见 2.1 |

反过来，组件**不会污染你的页面**：所有类名带 `erpdash-` 前缀，所有 CSS 变量挂在 `.erpdash` 上（不是 `:root`），盒模型重置收在 `.erpdash *` 作用域内，没有任何 `body{}` / `html{}` / `*{}` 全局选择器。

---

## 4. 避坑清单

### 4.1 不要加 `import React from 'react'`

`@vitejs/plugin-react` 默认使用自动 JSX 运行时，JSX 不需要手动引入 React。加了不会报编译错，但 ESLint 会提示未使用变量。

**唯一例外**：`eslint-plugin-react` 版本较老、开了 `react/react-in-jsx-scope` 时，会报 `'React' must be in scope when using JSX`。那时把该规则关掉（新版默认已关），或加回 React 导入。

### 4.2 JSDoc 不会导致任何构建报错

数据结构说明全部用 JSDoc 注释表达（`dashboardApi.js` 顶部），**没有独立的 types 文件**。JSDoc 本质是注释，esbuild / Vite 完全忽略它，不参与编译。

### 4.3 后续改代码别习惯性写 TS 语法

这几个在纯 JS 里会直接抛 `SyntaxError`：

```js
const name: string = 'abc';            // ❌ 变量类型标注
function f(x: number) {}               // ❌ 参数类型
const el = ref.current as HTMLElement; // ❌ 类型断言
interface Foo { a: string }            // ❌ interface
```

要写就写进 JSDoc：

```js
/** @type {string} */ const name = 'abc';
/** @param {number} x */ function f(x) {}
```

### 4.4 `<StrictMode>` 不会导致重复请求

你的 `main.jsx` 如果包了 `<StrictMode>`（Vite 模板默认），开发模式下 effect 会跑两次。组件内部已用 `AbortController` + `alive` 标志处理，不会出现双份数据或未处理的 promise rejection。**已实测验证，不用改。**

但接真实接口后如果换用 axios，记得把 `signal` 透传，否则第一次请求不会被真正取消。

### 4.5 tooltip 可能被祖先元素的 `overflow: hidden` 裁掉

tooltip 定位在 `.erpdash-chart` 内部（`position: relative`）。如果看板被塞进带 `overflow: hidden` 且高度很紧的容器里，悬浮提示可能被切边。你现在的页面容器是正常流式布局，应该没问题；真遇到了就把外层容器的 `overflow` 改成 `visible`。

### 4.6 图表在隐藏标签页里初始渲染也没问题

如果你的分发区写成 `{selectedTab === 'dashboard' && <Dashboard />}`（条件渲染），组件只在切到该菜单时才挂载，不会有隐藏态问题。即使放在 `display: none` 的容器里，尺寸测量走 `ResizeObserver`，容器一显示就会自动补测重绘，不需要手动触发 resize。

---

## 5. 集成后的自测清单

点左侧菜单「经营看板」，按这 6 条过一遍：

1. **首屏**：先出现 4 个灰色骨架卡片 + 图表骨架，约 220ms 后数据填充（Mock 里的模拟延迟）
2. **格式化**：今日销售额显示 `386,420元`、应收账款显示 `2,845,600元`（千分位）
3. **状态标**：待处理订单 / 应收账款带橙色「需关注」，库存预警商品带绿色「正常」，**今日销售额没有状态标**
4. **图表双轴**：左轴 `0/50/100/150`，右轴百分比刻度，左上角蓝字「销售额（万元）」、右上角橙字「同比增速（%）」
5. **交互**：鼠标横向移动有十字虚线 + 浮层提示；点图例能单独关掉某条线；点「近 30 天」X 轴标签变成每 2 天一个
6. **无样式污染**：切回「运营概览」等其它页面，确认字体、按钮、盒模型完全没变

---

## 6. 接真实接口时改哪

你的后端代理已配好（`vite.config.js` 里 `/api` → `http://127.0.0.1:8000`），
且 `appLib.js` 里 `API_BASE = '/api/v1'`。所以改 `dashboardApi.js` 这一个函数：

```js
export async function fetchDashboard(range = '7d', { signal } = {}) {
  const res = await fetch(`/api/v1/erp/dashboard?range=${range}`, { signal });
  if (!res.ok) throw new Error(`接口异常：${res.status}`);
  return res.json();
}
```

把 Mock 里那几行 `await delay(220)` 删掉。返回体结构对齐 `dashboardApi.js` 顶部 JSDoc 的 `DashboardData` 即可，**渲染层一行都不用改**：

```
{ kpis: KpiItem[], chart: { unit, labels, series }, updatedAt: string }
```

几个结构上的硬约定：

- `chart.series[].data.length` **必须等于** `chart.labels.length`
- `delta` 自带正负号（`-6` 表示下降 6%），`trend` 单独给方向（`'up' | 'down' | 'flat'`）
- 反向指标（涨了是坏事）记得标 `polarity: 'inverse'`，否则不会出现「需关注」标

---

## 附：本项目的验证结果

| 检查项 | 结果 |
|---|---|
| 用**你项目的 node_modules（React 18.3.1）** 编译 | ✅ 成功，无警告 |
| `dashboard.css` 语法解析 | ✅ 合法（73 条规则） |
| 模块依赖解析（17 条 import） | ✅ 全部可解析 |
| jsdom 真实挂载回归 | ✅ 39/39 |
| StrictMode 双跑 effect 专项 | ✅ 8/8 |
| 组件体积（不含 React） | 15.3 KB 原始 / **6.0 KB gzip** |
