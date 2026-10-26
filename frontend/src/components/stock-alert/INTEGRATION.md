# 库存预警看板 · 集成指南

> 纯 JavaScript（`.jsx`）+ 零第三方依赖，手写 SVG，无 ECharts / Chart.js。
> 已在你的真实工具链（Vite 5.4.21 + @vitejs/plugin-react 4.7.0 + React 18.3.1）上跑通生产构建。
>
> **当前状态：第三步已完成 —— 接口已指向 `/api/v1/erp/stock-alert`，后端已实现并跑通。**
> （后端文件：`app/api/v1/routes/erp_stock_alert.py`，见第十二节）

---

## 一、文件清单（9 + 1 个文件，全部已放进你的项目）

```
E:\AI\ERP软件\frontend\src\
├── components\stock-alert\          ← 组件目录
│   ├── index.js                     统一出口（桶文件）
│   ├── StockAlertDashboard.jsx      容器：唯一的请求方 + 状态管理
│   ├── KpiCards.jsx                 顶部 4 张卡片
│   ├── StockTrendChart.jsx          中间：出入库趋势（双轴手写 SVG）
│   ├── AlertList.jsx                底部：缺货预警商品明细（9 列 + 4 个筛选页签）
│   ├── alertRules.js                ★ 紧急度判定规则（改阈值只改这个文件）
│   ├── stockAlertApi.js             ★ 接口层（已接真实地址）
│   ├── stockAlertUtils.js           纯函数（格式化 / 路径 / 刻度）
│   └── stockAlert.css               样式（全部 erpstock- 前缀）
└── pages\
    └── StockAlertPage.jsx           页面壳（按你现有 45 个页面的写法）
```

**职责划分（重要）**：

| 文件 | 管什么 | 你要改哪个 |
|---|---|---|
| `stockAlertApi.js` | 发请求、字段映射 | 后端字段名和约定不一样时 |
| `alertRules.js` | 可用天数公式、紧急度阈值、排序 | **调整判定规则时** |
| `AlertList.jsx` 等 | 纯展示，不含任何业务判断 | 一般不用动 |

---

## 二、第二步：接口怎么改（**已经改好了**）

`stockAlertApi.js` 里现在是这个：

```js
/** 真实接口地址（和 src/lib/appLib.js 里的 API_BASE = '/api/v1' 对齐） */
export const STOCK_ALERT_ENDPOINT = '/api/v1/erp/stock-alert';

export async function fetchStockAlert(range = '30d', { signal } = {}) {
  const res = await fetch(`${STOCK_ALERT_ENDPOINT}?range=${encodeURIComponent(range)}`, { signal });
  if (!res.ok) throw new Error(`接口异常：${res.status} ${res.statusText}`);
  const json = await res.json();

  return {
    kpis: json.kpis ?? [],
    chart: json.chart ?? json.chartData ?? null,   // 两种命名都认
    alerts: json.alerts ?? json.list ?? [],        // 两种命名都认
    updatedAt: json.updatedAt ?? '',
  };
}
```

也就是：**你后端叫 `chart` / `chartData`、`alerts` / `list` 都行，前端不用改。**
`signal` 已经透传给了 `fetch`，`<StrictMode>` 下取消重复请求靠它。

### 请求参数

| 参数 | 取值 | 说明 |
|---|---|---|
| `range` | `30d` \| `7d` | `30d` 时图表要 30 个点，`7d` 时 7 个点 |

> 注意：`7d` 的数据**不是** `30d` 的最后 7 条截取，是两个独立的时间窗口，请各算一遍。
> 想省事的话，让 `7d` 直接返回第 24~30 天的数据，前端也能画。

### 后端还没上线时怎么先看界面

`StockAlertDashboard.jsx` 顶部有一个开关：

```js
const USE_MOCK = false;   // ← 改成 true 就走本地假数据，完全不发请求
```

改完刷新就能看界面。**上线前记得改回 `false`。**
（生产构建时 `USE_MOCK = false` 是字面量，Rollup 会把整个 mock 分支摇掉，**不占体积**。）

---

## 三、后端需要返回的 JSON 结构

完整响应示例（照这个写就行）：

```jsonc
{
  // ============ 1. 顶部 4 张 KPI 卡片 ============
  // 顺序就是显示顺序，固定 4 项
  "kpis": [
    {
      "key": "totalStock",          // 唯一标识，React key 用它，不能重复
      "label": "总库存",             // 卡片标题
      "value": 128460,              // 数值，前端按 unit 自动加千分位
      "unit": "件",                 // 单位；填 "%" 时保留 1 位小数
      "delta": 2.1,                 // 变化百分比，正负都行
      "trend": "up",                // "up" | "down" | "flat" —— 决定 涨红/跌绿
      "note": "较上周",              // 变化说明
      "polarity": "normal",         // "normal" | "inverse"
                                    //   inverse = 数字涨了是坏事 → 自动标「需关注」
      "color": "#3370ff",           // 卡片圆点 + 迷你趋势线颜色
      "spark": [58, 61, 60, 63, 66, 65, 68]   // 迷你趋势线，7 个点左右最好看
    },
    { "key": "inbound",  "label": "待入库",   "value": 36, "unit": "单", "delta": 12.5, "trend": "up",
      "note": "较昨日", "polarity": "inverse", "color": "#f59e0b", "spark": [24,26,31,28,33,34,36] },
    { "key": "outbound", "label": "待出库",   "value": 52, "unit": "单", "delta": -8.3, "trend": "down",
      "note": "较昨日", "polarity": "inverse", "color": "#7b61ff", "spark": [64,66,61,58,56,54,52] },
    { "key": "shortage", "label": "缺货商品", "value": 18, "unit": "种", "delta": 28.6, "trend": "up",
      "note": "较昨日", "polarity": "inverse", "color": "#e5484d", "spark": [9,10,12,11,14,16,18] }
  ],

  // ============ 2. 中间图表（双轴） ============
  // 叫 "chartData" 也行，前端两种命名都认
  "chart": {
    "leftTitle": "出入库量",        // 左轴标题（写在图表左上角）
    "leftUnit": "件",              // 左轴单位
    "rightTitle": "出库同比",       // 右轴标题（写在图表右上角）
    "rightUnit": "%",              // 右轴单位

    // X 轴标签。长度必须和每条 series 的 data 长度一致
    // range=30d 传 30 个、range=7d 传 7 个
    "labels": ["09-16", "09-17", "09-18", "…", "10-15"],

    // 三个序列：入库（面积）、出库（实线）、同比增速（虚线，挂右轴）
    "series": [
      {
        "name": "入库量",
        "type": "area",            // area 面积主线 | line 实线 | dashed 虚线
        "axis": "left",            // left 左轴 | right 右轴（左右轴各自独立算刻度）
        "color": "#3370ff",
        "data": [1180, 1240, 1310, "…", 1880]
      },
      {
        "name": "出库量",
        "type": "line",
        "axis": "left",
        "color": "#17a34a",
        "data": [1290, 1350, 1420, "…", 1930]
      },
      {
        "name": "同比增速",
        "type": "dashed",          // 自动画成虚线
        "axis": "right",           // 挂右轴，允许负值，0% 会画加粗基准线
        "color": "#f59e0b",
        "data": [8.4, 10.2, 12.1, "…", 21.4]
      }
    ]
  },

  // ============ 3. 底部缺货预警明细 ============
  // 叫 "list" 也行，前端两种命名都认
  // ⚠️ 只给下面这 8 个「原始字段」，缺口 / 可用天数 / 紧急度由前端算，不要返回
  "alerts": [
    {
      "id": "A03",              // 唯一标识，React key 用它
      "sku": "SKU-P270",        // 商品编码
      "name": "27 寸显示器 P27",  // 商品名称
      "warehouse": "广州仓",      // 仓库名（字符串，不是 id）
      "stock": 5,               // 当前库存
      "safetyStock": 40,        // 安全库存
      "dailyOut": 3,            // ★ 日均出库（件/天）—— 用来算可用天数
                                //   不动销的商品填 0，前端会显示「—」并判为正常
      "suggest": 60             // 建议补货量
    }
    // … 其余明细
  ],

  // ============ 4. 数据更新时间 ============
  "updatedAt": "2026-10-15T16:10:00+08:00"   // ISO 8601，显示在标题下方
}
```

### 后端不返回的三个字段（前端自己算）

| 字段 | 公式 | 算在哪 |
|---|---|---|
| `gap` 缺口 | `safetyStock - stock` | `alertRules.enrichAlert` |
| `daysLeft` 预计可用天数 | `stock / dailyOut`（`dailyOut<=0` 时算不出） | `alertRules.daysOfSupply` |
| `level` 紧急度 | 按 `daysLeft` 分档 | `alertRules.levelFromDays` |

**这样设计的好处**：改判定口径不用动后端、不用重新发接口。

### FastAPI 侧的响应模型（可直接抄）

```py
from pydantic import BaseModel

class KpiItem(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    delta: float
    trend: str          # up | down | flat
    note: str
    polarity: str       # normal | inverse
    color: str
    spark: list[float]

class ChartSeries(BaseModel):
    name: str
    type: str           # area | line | dashed
    axis: str           # left | right
    color: str
    data: list[float]

class ChartConfig(BaseModel):
    leftTitle: str
    leftUnit: str
    rightTitle: str
    rightUnit: str
    labels: list[str]
    series: list[ChartSeries]

class AlertItem(BaseModel):
    id: str
    sku: str
    name: str
    warehouse: str
    stock: float
    safetyStock: float
    dailyOut: float     # 日均出库，0 表示不动销
    suggest: float

class StockAlertResponse(BaseModel):
    kpis: list[KpiItem]
    chart: ChartConfig
    alerts: list[AlertItem]
    updatedAt: str

@router.get("/api/v1/erp/stock-alert", response_model=StockAlertResponse)
async def stock_alert(range: str = "30d"):
    ...
```

> 保持 pydantic 字段名和上面一致，前端就能直接吃，一行映射都不用写。
> 想用下划线命名（`safety_stock`）也行，在 `fetchStockAlert` 的 `return` 里加映射即可。

---

## 四、紧急度判定规则（本轮新增，重点）

全部集中在 **`alertRules.js`**，组件里没有任何硬编码阈值。

### 规则

```
预计可用天数 = 当前库存 / 日均出库

可用天数  <  3 天      →  紧急 urgent   （红色标签）
3 ≤ 天数 ≤ 7 天        →  预警 warn     （橙色标签）
可用天数  >  7 天      →  正常 normal   （绿色标签）
```

### 🔧 怎么改阈值

只改 `alertRules.js` 顶部这一个常量：

```js
export const ALERT_THRESHOLDS = {
  urgentBelow: 3,   // ← 改这里：可用天数小于几天算紧急
  warnBelow: 7,     // ← 改这里：小于等于几天算预警，超过就是正常
};
```

改完刷新即可，**组件、接口、后端都不用动**。

### 边界行为（已逐个写进测试钉死）

| 情况 | 判定 | 说明 |
|---|---|---|
| 天数正好 = 3 | **预警** | 不是紧急 |
| 天数正好 = 7 | **预警** | 不是正常 |
| 天数 2.99 | 紧急 | |
| 天数 7.01 | 正常 | |
| **库存为负（欠货）** | **紧急** | 后端也返回 `daysLeft = 0`。系统允许负库存开单，负库存 = 货已欠出去，**绝不能判成正常** |
| 库存 = 0 且动销 | 紧急 | 0 天 |
| 库存 = 0 且不动销 | 正常 | 天数算不出 → 显示「—」 |
| `dailyOut = 0`（不动销） | **正常** | 天数算不出 → 显示「—」→ 不误报 |
| `dailyOut` 缺失 / 负数 | 正常 | 同上 |

> ⚠️ 这里有个**本轮修掉的坑**：原来的 `daysOfSupply` 把「库存 < 0」和「日均出库 ≤ 0」
> 一起归成 `Infinity`，于是负库存的行被判成「正常」。真实数据一跑就露馅
> （`P1867W25 电扳手套筒 -6 件` 被判正常）。现在两者分开：负库存 → 0 天 → 紧急。

### 排序口径

明细表按 **预计可用天数从少到多** 排列（= 补货优先级），天数相同时缺口大的排前面，
「算不出天数」的排在最后。后端返回什么顺序都不影响，前端统一重排。

> 想改成别的排序，改 `alertRules.enrichAlerts` 里的 `sort` 回调一处即可。

---

## 五、底部明细表的 9 列

| 列 | 来源 | 说明 |
|---|---|---|
| 商品 | `name` + `sku` | 两行显示 |
| 仓库 | `warehouse` | |
| 当前库存 | `stock` | |
| 安全库存 | `safetyStock` | 灰色弱化 |
| 缺口 | `safetyStock - stock` **前端算** | 红底胶囊 |
| 日均出库 | `dailyOut` | 为 0 时显示「—」 |
| **预计可用天数** | `stock / dailyOut` **前端算** | ★ 按档位着色、字号提一档，整表最该被看到的一列 |
| 建议补货 | `suggest` | 加粗 |
| 紧急度 | 前端算 | 紧急 / 预警 / 正常 三色标签 |

筛选页签：**全部 18 / 紧急 6 / 预警 6 / 正常 6**（数量实时统计，不写死）。

---

## 六、四个改动点（App.jsx 3 行 + 后端 1 行）

> **2026-10-15 更新**：改动 2️⃣ 3️⃣ **已经替你改好了**（见下表的实际行号），
> 改动 1️⃣ 按你的要求留到下一步。**改动 4️⃣ 是踩坑后才发现的，漏掉它侧边栏不会显示 —— 见第七节。**

| # | 文件 | 行号（改后实际值） | 状态 |
|---|---|---|---|
| 1️⃣ | `frontend/src/App.jsx` | 第 **10789** 行之后 | ⏳ 待做（下一步） |
| 2️⃣ | `frontend/src/App.jsx` | 第 **47** 行 | ✅ 已改 |
| 3️⃣ | `frontend/src/App.jsx` | 第 **111** 行 | ✅ 已改 |
| 4️⃣ | `app/core/permissions.py` | 第 **72** 行 | ✅ 已改 |

> 行号会随改动漂移。想自己核对的话，直接搜关键词：
> `StockAlertPage` / `'stock-alert'` / `库存预警`。

### 改动 1️⃣（第 10789 行之后）：页面分发 ⏳ 下一步

第 **10789** 行是：

```jsx
            {selectedTab === 'inventory' && <InventoryPage ctx={appCtx} />}
```

在它下面（空行之后）插入：

```jsx
            {selectedTab === 'stock-alert' && <StockAlertPage ctx={appCtx} />}
```

> ⚠️ 这一行没加之前，点菜单进去是**空白主面板**（顶栏标题正常显示「库存预警」）。
> 这是预期状态，不是 bug。

### 改动 2️⃣（第 47 行）：顶部 import ✅ 已改

```jsx
import StaffPage from './pages/StaffPage';
import StockAlertPage from './pages/StockAlertPage';        // ← 新增（按你的字母序排在这里）
import StocktakingPage from './pages/StocktakingPage';     // ← 原来的第 47 行，现在往后挪了一行
```

### 改动 3️⃣（第 111 行）：「库存管理」分组加菜单项 ✅ 已改

```jsx
      { key: 'loss-overflow', label: '报损报溢' },          // 原来的第 109 行，现在在第 110 行
      { key: 'stock-alert', label: '库存预警' },             // ← 新增
    ],
  },
```

> 菜单项的 `key` 必须和改动 1️⃣ 里的 `selectedTab === 'stock-alert'` 完全一致。

### 改动 4️⃣（第 72 行）：后端权限目录 ✅ 已改（漏了这行侧边栏不显示）

`app/core/permissions.py`，`PERMISSION_CATALOG` 的「库存管理」分组里（原第 71 行之后）：

```py
            {"key": "assembly", "label": "组合拆卸"},
            {"key": "loss-overflow", "label": "报损报溢"},
            {"key": "stock-alert", "label": "库存预警"},     # ← 新增
        ],
    },
```

改完**重启一次后端**，主启动的「缺则补」迁移会自动往 `menus` 表补上对应的菜单行。
为什么必须改它、以及它引发的第二个坑，见下一节。

---

## 七、⚠️ 侧边栏不显示新菜单：一条链上有三道闸，缺一道都静默失效

这一节是踩过坑之后写的，**照做就能一次通**。

### 三道闸分别在哪儿

| # | 位置 | 作用 | 不改的后果 |
|---|---|---|---|
| ① | `App.jsx` 第 **111** 行 `menuGroups` | 前端菜单**兜底**定义 + 顶栏标题 | 顶栏标题空、后端菜单树拿不到时无兜底 |
| ② | `app/core/permissions.py` 的 `PERMISSION_CATALOG` | 页面权限点的**唯一合法来源** | 菜单管理里选不到这个页面；角色勾不上；一致性测试挂 |
| ③ | 数据库 `menus` 表 | 侧边栏的**实际展示结构** | 侧边栏不显示（`visibleGroups` 直接 return `menuTree`，内置 menuGroups 被整体忽略） |

`App.jsx` 第 **8455** 行的优先级就是这么来的：

```js
const visibleGroups = useMemo(() => {
  if (Array.isArray(menuTree) && menuTree.length > 0) return menuTree;   // ← 后端菜单树优先
  ...                                                                    // ← 拿不到才用内置 menuGroups
}, [menuTree, myPermissions]);
```

**实测**：本机 `menus` 表有 64 行 → 后端菜单树一直是非空的 → 内置 `menuGroups` 从来没被用过。
所以「只改前端菜单项」在这套系统里**永远不会出现**在侧边栏上。

### ②→③ 是自动的：主启动的「缺则补」迁移

`app/main.py` 的 `ensure_default_menus()` 里有一段**每次启动都跑、幂等**的迁移：

> 按 `PERMISSION_CATALOG` 生成内置菜单规格，只补**完全不存在**的 `(父节点, page_key)` 组合。
> 管理员加过、改过、删过的节点一律不碰 —— **绝不覆盖、绝不复活被删的**。

所以只要 ② 改了，**重启一次后端**，③ 就会自动补上（实测补出来的行：
`库存预警 / page_key=stock-alert / sort_order=70 / is_builtin=True`，落在「库存管理」下、报损报溢之后）。

`menus` 是**全局表**（住在 `public`，连接 `search_path = <账套>,public`），三个账套共用，补一次全都有。

### ⚠️ 千万别做「前端降级显示」

有一种看起来很贴心的写法：内置 `menuGroups` 里有、菜单树里没有的项，前端给它补回去。
**不要这么做** —— 那等于把管理员删掉的菜单复活，直接违背上面那句「绝不复活被删的」。
菜单树上没有就是不该有，这是设计，不是 bug。

### 🔴 第二个陷阱：`selectedTab` 有守卫，会让你以为组件坏了

`App.jsx` 第 **8490～8504** 行还有一个 effect：

```js
// 权限收紧后当前页可能已经不可见 …… 都自动落到第一个可见页。
collect(visibleGroups);                                  // 收集菜单树里所有 page_key
if (pages.size && !pages.has(selectedTab)) {
  setSelectedTab([...pages][0]);                         // ← 不在其中就被弹走
}
```

**所以「把 `useState` 默认值改成 `'stock-alert'` 刷新看看」这个办法，
在③没补上之前必然失败**：首帧菜单树还是空的、走内置兜底所以画面能出来，
等鉴权接口一返回，`selectedTab` 就被弹回 `overview` —— 表现是"页面闪一下就跳走了"，
极容易被误判成"组件有 bug"。

👉 **正确顺序：先改 ② → 重启后端 → 再动前端。** 顺序反了会白折腾一轮。

### 🅰️ 测试阶段：临时挂载法

> 🔴 **2026-10-15 实测：这个办法在这套系统里行不通，别用它。**
> `App.jsx` 第 **744** 行在**每次刷新**（token 校验通过）都会调
> `loadMyPermissions(authToken, true)`，其中 `applyLanding=true` 会执行
> `setSelectedTab(data.ui.default_page)` —— 而系统参数 `system.default_page` 现在是
> **`overview`**（`system_params` 表实测值）。所以 `useState` 的默认值活不过一次刷新，
> 表现就是"改了没反应、刷新还是运营概览"。这是落地页设计，不是 bug。
>
> 想让看板成为落地页，去「系统设置 → 参数设置」把 `system.default_page` 改成 `stock-alert`
> （后端会校验它必须在该用户可见菜单内，现在已经满足）。**这会影响该账套所有人的落地页**，
> 测完记得改回 `overview`。
>
> 日常测试请直接用下面的「点菜单」，最真实。

改 `App.jsx` 第 **453** 行：

```jsx
  const [selectedTab, setSelectedTab] = useState('stock-alert');
  //                                                 ^^^^^^^^^^^^^ 原来是 'overview'
```

### 🅰️′ 推荐测试路径：点菜单（改动 1️⃣ 之后就该这么测）

1. 刷新页面（或重启前端）
2. 左侧分组默认是**折叠**的 —— 点开「库存管理」
3. 点「库存预警」→ 应该直接进看板，顶栏标题「库存预警」

如果这一步正常，说明 ①②③④ 四处全部接通。

### 🅱️ 常驻入口

②③ 就绪后，「菜单管理」页的下拉里就会出现「库存预警」这个页面，可以自由挂到任意分组/层级下
（也可以在重启时让「缺则补」迁移自动挂到「库存管理」下）。

### 🅲 普通角色看不到？那是权限，不是 bug

`menus`（页面权限）是**角色里存的固定数组**，不会自动补新键。实测本机：

| 角色 | all | 菜单数 | 含库存预警 |
|---|---|---|---|
| admin 系统管理员 | ✅ true | — | ✅（`all` 直接放行全集） |
| manager 经营主管 | false | 45 | ❌ 要去「用户角色」勾 |
| warehouse 仓管员 | false | 12 | ❌ 同上 |

新页面跟库存预警最相关，建议给 `warehouse` / `manager` 勾上。
勾选框来自 `PERMISSION_CATALOG`，所以 ② 改完后那个格子才会出现。

### 🅳 顶栏标题

`App.jsx` 第 **8686** 行 `currentPageLabel` 的取值顺序是
`菜单树节点名 → 内置 tabs 名 → '运营概览'`。
①②③ 都改了就显示后端的名字；只改了 ① 则显示内置的「库存预警」，不会崩。

---

## 八、可选：右上角快捷入口

`App.jsx` 第 **188** 行开始是 `pageActions`，想加跳转就加一段：

```js
  'stock-alert': [
    { label: '库存管理', to: 'inventory', variant: 'secondary' },
    { label: '采购订单', to: 'purchase-order', variant: 'primary' },
  ],
```

---

## 九、验证记录

### 1. 真实工具链生产构建 ✅

用你项目里的 Vite 5.4.21 + plugin-react 4.7.0 单独起体检工程编译：

```
✓ 45 modules transformed.
dist/assets/index-*.css   16.03 kB │ gzip:  3.01 kB
dist/assets/index-*.js   174.74 kB │ gzip: 54.07 kB
✓ built in 1.94s
```

零报错、零警告。

### 2. 体积（gzip）✅ 远低于 10 KB 上限

真实 Vite 做「加之前 / 加之后」对照构建，算**边际代价**：

| | raw | gzip |
|---|---|---|
| JS | 18.32 KB | **2.67 KB** |
| CSS | 9.25 KB | **1.07 KB** |
| **合计** | 27.57 KB | **3.74 KB** ✅ |

> **本地 mock 假数据已被 Rollup 完全摇掉**（`USE_MOCK = false` 是字面量，整个分支被 DCE），
> 上面这个数就是真实接口版的生产体积，不含任何假数据。

### 3. 渲染 + 交互 + 规则验证（jsdom 真实挂载）✅ **98 项断言全过**

覆盖：
- **紧急度规则**：可用天数公式、阈值边界（2.99 / 3 / 7 / 7.01）、**负库存 → 0 天 → 紧急**、
  库存 0 动销 / 不动销的分支、`dailyOut=0` 的降级、排序、计数
- **接口层**：URL 拼接、`range` 传参、非 2xx 抛错、`signal` 透传、`chartData`/`list` 命名兼容、漏字段降级
- **渲染**：骨架屏 → 数据 → KPI 格式与涨跌色 → 三档汇总 → 双轴刻度（含 −10% 负值与 0% 基准线）
  → X 轴抽稀 → 三系列绘制 → 图例显隐 → 悬浮提示
- **明细表**：9 列表头、18 行、按可用天数排序、首行数值全对、`dailyOut=0` 行显示「—」、
  三档标签 6/6/6、可用天数着色、4 个筛选页签计数与切换
- **时间范围切换**不闪屏
- **错误态**：错误条 + 重新加载

### 4. StrictMode 双跑 effect ✅ 16 项断言全过

不产生未处理的 promise rejection、不重复渲染、图表不会被第一次的 abort 干掉、
派生字段（可用天数 18 个）没被双跑污染。

### 5. CSS 作用域静态检查 ✅

没有 `:root` / `body` / `html` 选择器；每条规则起始选择器都以 `.erpstock` 开头；
类名、变量全部带 `erpstock` 前缀；三档 chip 样式齐全。

### 6. 集成接线验证（2026-10-15 新增）✅

- **`npm run build` 用你自己的 Vite 5.4.21 真跑**：`✓ 141 modules transformed`，零报错
  （只有既有的 chunk > 500 kB 提示，与本次无关）
- **菜单键一致性**：前端 `menuGroups` 54 项 vs 后端 `all_menu_keys()` 54 项，集合一致、顺序一致，
  `stock-alert` 两边都在「库存管理」末尾
- **菜单表**：`menus` 表 64 → 65 行，「库存管理」下顺序
  = 库存管理/变动查询/调拨管理/盘点管理/组合拆卸/报损报溢/**库存预警**（与前端完全一致）
- **守卫 effect 模拟**：`'stock-alert' in pages` → `True`（不会被弹走）；
  去掉该节点后会被 `setSelectedTab('overview')` 弹走 —— 这就是第七节描述的那个坑

复跑脚本：`buildcheck/check-stock-alert-wiring.py`（只读，不改任何东西）。

---

## 十、设计上刻意做的决定

| 决定 | 原因 |
|---|---|
| **紧急度在前端算，不让后端给** | 改口径不用动后端、不用重新发接口；后端也少一个可能算错的地方 |
| 悬浮交互全走 `ref` 改 DOM，**零 setState** | mousemove 不触发任何 React 渲染，30 天 × 3 条线拖动也不掉帧 |
| 切换时间范围时**不清空旧图** | 只加一个转圈，避免闪屏 |
| 图表容器从首次挂载就存在，骨架屏放在容器里 | 否则 `wrapRef` 首帧为 null，尺寸测量 effect 空跑一次后不再执行，图表永远画不出来 |
| 30 天时**不画数据点圆点** | 90 个圆点会糊成一片；≤15 个点时才显示 |
| 左轴固定从 0 起，右轴允许负值 | 数量类指标从 0 起才有可比性；同比增速会掉到 0 以下 |
| 明细表按可用天数排序而非后端顺序 | 采购关心的是「先补哪个」，可用天数升序就是补货优先级 |
| 「正常」档在汇总条里刻意弱化成灰色 | 汇总条要突出的是需要处理的，不是不需要处理的 |
| 全部 CSS 变量挂在 `.erpstock` 而不是 `:root` | 避免和现有主题变量撞名 |
| 容器**不设背景 / 内边距** | 底色交给你 `body` 的浅蓝渐变，内边距交给 `.main-panel` |
| 颜色：**涨红跌绿** | 国内习惯；业务好坏用标签表达，不靠颜色 |

---

## 十一、常见问题

**Q：页面报「数据加载失败：接口异常：404」？**
A：后端接口还没起。要么先起后端，要么把 `StockAlertDashboard.jsx` 的 `USE_MOCK` 改成 `true` 看界面。

**Q：明细表「预计可用天数」全是「—」？**
A：后端没给 `dailyOut`（日均出库）。检查这个字段有没有返回、是不是 0。

**Q：明细表行数很少，只有几行？**
A：进表规则见第十二节第 4 条第 3 点。绝大多数商品是「有库存 + 没设下限 + 窗口内没卖动」，
本来就不该报。想让某类商品参与预警，去**商品档案里填「库存下限」** —— 填了之后
只要击穿下限就会进表。

**Q：图表画不出来 / 只有坐标轴？**
A：`labels` 的长度必须和每条 `series[].data` 的长度完全一致。30d 要 30 个、7d 要 7 个。

**Q：接口返回了但界面空白，控制台没报错？**
A：大概率 `kpis` 返回的是 `null` 而不是数组。前端做了降级（`?? []`），但骨架屏判断依赖数组长度。

**Q：想加一列 / 改列名？**
A：改 `AlertList.jsx` 的 `<thead>` 和 `<tbody>` 两处；新列如果需要计算，在 `alertRules.enrichAlert` 里补派生字段。

**Q：想换主题色？**
A：只改 `stockAlert.css` 顶部 `.erpstock { --erpstock-brand: ...; --erpstock-up: ...; }` 那一组变量。

---

## 十二、第三步：后端接口（已实现并跑通）

### 1. 文件放哪（新增 1 个文件 + 改 2 行）

**新增**：`E:\AI\ERP软件\app\api\v1\routes\erp_stock_alert.py`

**改动**：`E:\AI\ERP软件\app\api\v1\routes\erp.py` —— 只加 2 行：

```py
# ① 顶部 import 区（第 26 行附近）
from app.api.v1.routes.erp_stock_alert import router as erp_stock_alert_router

# ② 底部注册区（第 39 行附近，放在最后即可）
router.include_router(erp_stock_alert_router)
```

**不用碰 `main.py`、不用碰 `app/api/v1/router.py`** —— `routes/erp.py` 是 ERP 各业务域的聚合入口，
`/api/v1` 前缀由 `main.py` 统一挂（`app.include_router(api_router, prefix="/api/v1")`），
所以路由里写 `"/erp/stock-alert"` 出来就是 `/api/v1/erp/stock-alert`。

### 2. 为什么**不能**直连 `E:\AI\ERP软件\erp.db`

这一条很关键，先说清楚：**你这套后端实际跑的是 PostgreSQL，不是 SQLite。**

| | 实际情况 |
|---|---|
| `.env` | `DATABASE_URL=postgresql+psycopg://erp:***@127.0.0.1:5432/erp` |
| `app/core/config.py` 第 19 行 | `database_url: str = "sqlite:///./erp.db"` —— 这只是**没有 .env 时的兜底默认值** |
| `E:\AI\ERP软件\erp.db` | 278 KB，最后修改时间停留在 9 月 24 日，**升级前的旧文件** |

而且本项目是**多账套**的：真正的 schema 由 token 里的账套决定，
`get_db(request)` 负责把会话接到对应 schema 上（`app/db/session.py` 的注释写得很明白：
「不要把 `SessionLocal` 用在业务路由里 —— 那会固定读第一个账套，在多账套下就是**串账**」）。

所以接口用的是 `Depends(get_db)`，和其余 200 多个业务路由完全一致：
**既能读到最新数据，也不会串账。直连 `erp.db` 两条都违反。**

### 3. 数据从哪来（全部是既有的表，没建新表）

| 指标 | 来源 | 口径 |
|---|---|---|
| 现存量 | `inventory_transactions` | 复用 `erp_common._stock_delta` 与 `_net_stock_map` 同一套算法，现存量不落库 |
| 日均出库 | `inventory_transactions` | 窗口内该「仓库 × 商品」的出库量 ÷ 窗口天数（30 或 7） |
| 安全库存 | `products.stock_lower`（库存下限） | 没设下限的商品不参与「击穿下限」判定 |
| 待入库 | `purchase_orders` | `doc_type='order'` 且状态未结束（未转成入库单）的单数 |
| 待出库 | `sales_orders` | `doc_type='order'` 且状态未结束的单数 |
| 缺货商品 | `inventory_transactions` | 全库合计现存量 ≤ 0 的商品**种数** |
| 出入库趋势 | `inventory_transactions` | 按日聚合；入库取 `INBOUND_TYPES`、出库取 `OUTBOUND_TYPES` |
| 同比增速 | `inventory_transactions` | 出库量 vs 去年同一天；见下面第 5 条 |

### 4. 三条业务口径（写在 `erp_stock_alert.py` 顶部，改只改那一段常量）

```py
ALERT_URGENT_BELOW = 3.0      # < 3 天 → 紧急  （必须与前端 alertRules.js 一致）
ALERT_WARN_BELOW = 7.0        # ≤ 7 天 → 预警
DEFAULT_DAILY_OUT = 1.0       # 🔧 窗口内没有出库记录时的默认日均出库
```

1. **除零安全**：`日均出库 ≤ 0` → 可用天数返回 `None`（不是抛异常），判「正常」。
   这是这里唯一能击穿接口的风险点，已经写成纯函数 `_days_of_supply` 并单独测过。
2. **负库存 → 0 天 → 紧急**。本系统允许负库存开单，负库存 = 货已欠出去，
   和「算不出天数」是两回事，绝不能混成一个 `Infinity`。（前端同步修了，见第四节）
3. **明细表进哪些行**：① 负库存 ② 击穿库存下限 ③ 现存量 ≤ 0 ④ **窗口内真有出库记录**
   且可用天数落到紧急/预警档。第 ④ 条特意要求"真有出库记录" ——
   否则拿默认值 1 件/天当分母，会把一堆躺着的呆滞库存全刷进表里。

### 5. ⚠️ 「出库同比」在数据不足时会自动降级

`同比` 需要去年同一天有出库数据。新账套几乎必然没有 —— 此时若照常画同比，
得到的是一条**恒为 0 的直线**，等于告诉老板"零增长"，那是假的。

所以后端做了检查：**去年同日有数据 → 画「出库同比」；没有 → 退回「7 日滚动环比」**，
`rightTitle` 和系列名一起改，界面文案不会说谎。等数据攒够一年，它会自动切回同比，前端一个字都不用动。

### 6. 怎么测

```bash
cd E:\AI\ERP软件
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# 另开一个窗口
curl "http://127.0.0.1:8000/api/v1/erp/stock-alert?range=30d"
```

或者直接在浏览器打开 Swagger：`http://127.0.0.1:8000/docs` → 搜 `stock-alert` → Try it out。

### 7. 实测结果（在你这台机器上、连你的真实数据库跑的）

```
GET /api/v1/erp/stock-alert?range=30d   200
  KPI: 总库存=32555件(+0% flat) | 待入库=0单(+0% flat)
       待出库=0单(+0% flat)   | 缺货商品=1种(+0% flat)
  chart: 30 个标签 09-16 … 10-15，三条序列长度都是 30，右轴标题 = 出库环比
  alerts: 1 行
    {"id":"P1867W25","sku":"0090-3","name":"电扳手套筒","warehouse":"主仓库",
     "stock":-6.0,"safetyStock":0.0,"dailyOut":0.2,"suggest":7.4,
     "gap":6.0,"daysLeft":0.0,"status":"urgent"}

GET /api/v1/erp/stock-alert?range=7d    200   7 个标签
GET /api/v1/erp/stock-alert?range=乱传的  200   自动回落到 30 天，不报错
```
