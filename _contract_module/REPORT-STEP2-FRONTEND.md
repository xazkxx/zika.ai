# 第二步交付：订单页「单步审核」前后端打通（前端）

> 日期：2026-10-18 · 版本 v1.0.0 · 缓存 `erp-pwa-v37`
> 前置：第一步（后端状态机 + 发票加 `customer_id`/`contract_id`）已验收
> 本步范围：`OrderBoard.jsx` 审核/转单/收款按钮 + 状态徽标 + 菜单改名**未做**（下一步）+ 收款弹窗**未做**（下一步）

---

## 0. 一句话结论

订单页现在是一条**单步审核**的闭环：`提交后徽标=待审核` → `点审核 → 已审核` → `转开单/入库 → 已转单` → `收款/付款入口出现`。
未审核时转单按钮**禁用**（后端也 409 双保险），收款按钮当前给**明确占位提示**，弹窗下一步接。

---

## 1. 改了哪 5 个文件（行号可直接 grep）

| 文件 | 换行 | 行数 | 改动 |
|---|---|---|---|
| `frontend/src/lib/appLib.js` | CRLF | 822 | `:155-180` 新增订单专用状态表（**没动全局 `DOC_STATUS_LABELS`**） |
| `frontend/src/components/docs/OrderBoard.jsx` | LF | 601 | 7 处（见 §2） |
| `frontend/src/components/docs/docs.css` | LF | 314 | `:255` `:264-314` 徽标 + 操作列样式 |
| `frontend/src/App.jsx` | CRLF | 11251 | `:5096-5148` 审核实现 + `:9500-9501` `:9846` 注入 ctx |
| `frontend/public/sw.js` | LF | 177 | `:100` → `erp-pwa-v37` |

### 1.1 为什么另起一套状态表（关键决策）

`appLib.js:138` 的 `DOC_STATUS_LABELS` 被生产单、盘点、调拨、入库、出库等**十几个模块共用**。
在订单语境里 `submitted` 必须显示「待审核」，但在即时单语境里它必须是「已提交」。
→ 所以新增 `ORDER_STATUS_LABELS` / `ORDER_STATUS_GROUP` / `orderStatusLabel()` / `orderStatusGroup()`，
**只给订单页用**；全局表一个字没动。

```js
// appLib.js:155
export const ORDER_STATUS_LABELS = {
  draft: '草稿', pending: '待审核', submitted: '待审核', approved: '已审核',
  shipped: '已发货', completed: '已转单', cancelled: '已取消',
};
// appLib.js:166 —— 把库里的多个历史值归到"视觉分组"，前端只判分组不判原始码
export const ORDER_STATUS_GROUP = {
  draft:'pending', pending:'pending', submitted:'pending', approved:'approved',
  shipped:'shipped', completed:'completed', cancelled:'cancelled',
};
```

> `draft` 故意归到 `pending` 组，视觉上都是"还没审核"，但**审核按钮的显隐只用 `pending` 组** ——
> 也就是用户要求的「只有 submitted 状态下才显示审核按钮」。

---

## 2. `OrderBoard.jsx` 七处改动

| 行 | 内容 |
|---|---|
| `:48` | `import { orderStatusGroup, orderStatusLabel } from '../../lib/appLib';` |
| `:78-88` | `ORDER_CONFIG.purchase`：`approveKey` / `auditTitle` / `convertLockedTitle` / `payLabel:'付款'` / `payField:'paid_amount'` / `payTitle` |
| `:112-122` | `ORDER_CONFIG.sales` 对称：`approveKey:'approveSalesOrder'` / `payLabel:'收款'` / `payField:'received_amount'` |
| `:160` `:167` | `const approveOrder = ctx[cfg.approveKey];` / `const [auditingId, setAuditingId] = useState(null);`（解构里**移除** `DOC_STATUS_LABELS`） |
| `:322-326` | 状态列改徽标：`<span className={"status-badge order-status order-status--" + group} data-order-status>` |
| `:333-334` | 操作列宽 **248 → 352**（五个动作挤不进 248，会折成两行） |
| `:338-440` | 操作列按钮逻辑（下方 §3） |

---

## 3. 操作列按钮逻辑（本步核心）

```jsx
// OrderBoard.jsx:342
const group = orderStatusGroup(row.status);
const converted = group === 'completed';   // 已转开单
const approved  = group === 'approved';    // 已审核
const needsAudit = group === 'pending';    // 待审核（submitted 或 pending）
const busy = convertingId === row.id;
const auditing = auditingId === row.id;

const settledAmount = Number(row[cfg.payField] || 0);          // received_amount / paid_amount
const payable = Number(row.total_amount || 0) - Number(row.discount_amount || 0);
// 分位容差：numeric(12,2) 别把 99.999999 判成未结清
const settled = payable > 0 && settledAmount >= payable - 0.005;
```

五个按钮的显隐：

```
打印   —— 永远显示
审核   —— needsAudit 才显示（data-order-audit）      → 点完回调 approveOrder(row)，按钮自己消失
转开单 —— converted ? 灰标「已转开单」 : 按钮
          按钮 disabled = busy || !approved（data-order-convert，title 分两套文案）
删除   —— 只在未转单时出现（已转单不可删，与后端一致）
收款/付款 —— (approved || converted) 才出现（data-order-pay，:424-440）
            已结清 → 灰标「已结清」（.order-paid-tag），否则按钮
```

几个刻意的取舍：

1. **未审核时转单按钮是 `disabled` 而不是"点了报 409"** —— 后端 `erp_sales.py:456` / `erp_purchase.py:334` 的闸口仍然在，前端只是不让用户白点一次。
2. **已转单不隐藏按钮，而是显示灰标「已转开单」** —— 按钮凭空消失看起来像 bug，显式说明更清楚。
3. **审核中/转单中状态独立**（`auditingId` / `convertingId`）—— 审核按钮点完不会连带把转单按钮也变成"转单中…"。
4. `useMemo` 依赖 `:446-457` 补全：`cfg, partners, printPdf, setConfirmDelete, convertingId, auditingId, convertOrder, approveOrder, openOrderPayment, kind`
   —— 少一个就会出现"审核完了按钮还在"的假象（渲染不更新）。

---

## 4. `App.jsx`：审核的落地点

```jsx
// App.jsx:5100 —— 采购/销售共用一份实现，只差 endpoint 与列表 setter
const approveOrderRow = async (kind, row) => {
  const prefix = kind === 'purchase' ? 'purchase-orders' : 'sales-orders';
  const response = await fetch(`${API_BASE}/${prefix}/${row.id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
    body: JSON.stringify({ status: 'approved' }),   // 只发 approved，合法性全交后端
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: '审核失败' }));
    // ⚠️ FastAPI 422 的 detail 是数组，直接拼进 Error 会变成 [object Object]
    throw new Error(typeof errorData.detail === 'string' ? errorData.detail : '审核失败');
  }
  const updated = await response.json();
  (kind === 'purchase' ? setPurchaseOrderList : setSalesOrderList)((prev) =>
    prev.map((item) => (item.id === row.id ? { ...item, ...updated } : item)),
  );
  setNotice(`${label} ${row.order_no} 已审核通过，现在可以${kind === 'purchase' ? '转入库单' : '转开单'}。`);
};
```

`openOrderPayment`（`:5138`）**当前是占位提示**，不是空函数：

```
收款登记：订单 XSD-20261018-001 应收 ¥300.00，已收 ¥0.00。收款弹窗将在下一步接入。
```

> 接弹窗时**只改这个函数的内部实现**，`OrderBoard.jsx` 一行都不用动 —— 这是本步留的接口。

---

## 5. 验证

### 5.1 销售侧 E2E（真 Chrome，`verify_frontend_step2_orders.mjs`）

`25 通过 / 0 失败`，含产物哈希断言（防 SW 缓存伪装）：

```
L1-L6  登录 / 建客户 / 建商品 / 建销售订单(201) / 初始 status=submitted
F1     浏览器加载的是本次构建产物（dist/index.html 现读 assets/index-*.js 比对）
F2-F6  进「销售订单」/ 行出现 / 徽标「待审核」/ 有审核按钮 / 转开单禁用
F7-F11 点审核 → 徽标「已审核」/ 审核按钮消失 / 转开单可点 / 有「已审核通过」提示 / 服务端 approved
F12-F16 转单 → 灰标「已转开单」/ 转单+删除消失 / 出现「收款」/ 服务端 completed / 服务端生成出库单
F17    点「收款」给出明确占位提示（不是静默无反应）
F18    控制台零异常
Z      清理残留 0
```

### 5.2 采购侧抽检（`verify_frontend_step2_purchase.mjs`）

`18 通过 / 0 失败`。**为什么单独跑**：`OrderBoard.jsx` 是共用组件，
最容易出的错是"两个 kind 接到同一个 endpoint"——界面全绿但库里打错单。

```
P4  建采购订单 201（⚠️ 必须显式 doc_type:'order'，采购单默认是 inbound）
P7-P10 行出现 / 徽标「待审核」/ 有审核按钮 / 「转入库单」禁用
P11-P15 审核后变「已审核」/ 按钮消失 / 转入库单可点 / 提示是采购口径 / 服务端 approved
P16 采购订单没有串到销售列表
P17 控制台零异常 · Z 清理残留 0
```

> **踩坑记录**：第一版脚本没传 `doc_type`，采购单被建成 `inbound`，
> 于是在采购订单页（过滤 `doc_type=order`）里找不到它 → 8 条红。
> 不是产品 bug，是测试造数漏了字段。

### 5.3 反证（改坏 → 必须变红）

同时注入两处：

| 反证 | 改动 | 预期变红 | 实测 |
|---|---|---|---|
| A | `const needsAudit = group === 'pending'` → `= true`（审核按钮永远显示） | F8 审核后按钮消失 | ✅ 红 |
| B | `disabled={busy \|\| !approved}` → `disabled={busy}`（未审核也能点转单） | F6 未审核时禁用 | ✅ 红 |

结果 `23 通过 / 2 失败`，**只有这两条红**，其余 23 条不受影响 → 证明断言确实在守这两处逻辑。
还原后 `grep PROBE` = 0，重新 `npm run build`，复跑 `25/25` 全绿。

### 5.4 后端回归

`pytest tests/test_order_doc_type.py -q` → **9 passed**（后端本步未改，跑一遍确认没被牵连）。

---

## 6. 构建 / 生效

```
npm run build  → ✓ built in 7.7s
dist/assets/index-DBefJHrY.js  2,422.33 kB │ gzip 566.32 kB
（上批 2,419.67 kB，+2.66 kB）
sw.js CACHE_VERSION = erp-pwa-v37（第 100 行）
```

生效步骤：**重启 8010（`启动ERP.bat`）+ Ctrl+F5**。SW 版本已 bump，旧壳会自动清掉。

---

## 7. 本步**没做**（下一步内容，已排好）

1. **`OrderPaymentDialog.jsx`** 收款/付款弹窗 → `POST /finance/receipt|payment` 带 `order_id`，把 `App.jsx:5138 openOrderPayment` 从占位改成真弹窗。
2. **菜单改名「现货开单」**，「销售出库（多单位）」并入多单位模式后下架独立菜单
   （`components/sales-units/SalesOrderUnitsBoard.jsx` 的 `handleStatus(order,'completed')` 与 `STATUS_LABELS` 要跟着改）。
3. **发票页加「关联客户」`ErpSearchSelect`** —— 12 张存量发票因 #705/#709/#714 共用税号全部留空，需要人工认领。
4. **`permissions.py` + `role.py` 菜单同步**（改名涉及菜单树，注意只能追加不能插中间）。
5. 之后才是**修对账单 generate 的四个断点**（发票方向 `out→output`、按 `customer_id` 取数、收付款加 `direction` 过滤、`include_orders`）。

---

## 8. 回滚

```
_contract_module/backup/20261018_step2_frontend/
  OrderBoard.jsx  docs.css  appLib.js  App.jsx  sw.js
  verify_frontend_step2_orders.mjs  verify_frontend_step2_purchase.mjs
```
逐字节覆盖回去 + `npm run build` 即可。后端未改，无需回滚。
