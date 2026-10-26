# 第三步交付：订单收/付款弹窗（把断了很久的资金链路接上）

> 日期：2026-10-18 · 缓存 `erp-pwa-v38`
> 前置：第一步（后端状态机 + 发票加字段）、第二步（订单页审核按钮）已验收
> 本步范围：**只做收款弹窗**（用户指定"先给弹窗，我构建后测试收款闭环"）
> **未做**：菜单改名「现货开单」、发票页「关联客户」下拉 —— 等本步验收后再动

---

## 0. 一句话结论

订单行点「收款/付款」→ 弹窗填金额/日期/方式/备注 → `POST /finance/receipt|payment`
→ 写一条 `financial_transactions`（含凭证）并冲减本单欠款 → 列表变「已结清」，
财务流水页能立刻看到这笔钱。

**这条链路正是任务 1 查出来的根因之一**：后端 `_register_payment`（`erp_finance.py:285`）
一直写着完整逻辑（冲单 + 超收拆预收 + 重算欠款链），但**前端零调用**，
所以库里从来没有 `receipt`/`payment`，对账单「本期已收」永远算不出来。

---

## 1. 文件清单

| 文件 | 换行 | 行数 | 说明 |
|---|---|---|---|
| `frontend/src/components/docs/OrderPaymentDialog.jsx` | LF | **301（新建）** | 弹窗本体，受控组件 |
| `frontend/src/components/docs/pay-dialog.css` | LF | **150（新建）** | 只写 `.order-pay-dialog*` 独占类名 |
| `frontend/src/App.jsx` | CRLF | 11380 | 状态 + 三个函数 + 挂载 + `refreshFinance` |
| `frontend/src/lib/appLib.js` | CRLF | 838 | `FINANCE_TYPE_LABEL` / `financeTypeLabel` |
| `frontend/src/pages/FinancePage.jsx` | CRLF | 1153 | 类型列中文化 + 进入即刷新 |
| `frontend/public/sw.js` | LF | 177 | `:100` → `erp-pwa-v38` |

### 1.1 为什么弹窗自己不发请求

与 `PartnerModal` / `sales-units` 同一套约定：**组件只渲染，不碰接口**。
好处是这套弹窗以后能直接被「财务流水」页的收款入口复用，只换 `onSubmit`。

---

## 2. 三个金额口径（和后端严格对齐）

```
净额   = total_amount - discount_amount
已登记 = received_amount（销售） / paid_amount（采购）
未收款 = max(净额 - 已登记, 0)        ← 弹窗默认填这个数
```

允许填**大于**未收款：后端 `_register_payment:318` 会把 `min(金额, 未收)` 冲单、
超出部分算**预收/预付**（不硬挂单，否则单据会出现负欠款）。
弹窗在提交前就用黄字提示"超出的 ¥X 会记为预收"，不让你以为是填错了。

> ⚠️ 千万别把"未收"简化成"净额" —— 反证 B 就是把这个算错，`F16` 立刻变红。

---

## 3. 弹窗字段

| 字段 | 控件 | 默认 | 落库去向 |
|---|---|---|---|
| 本次收款/付款金额 | `number step=0.01` | 待收金额（结清则空） | `amount` |
| 业务日期 | `date` | **今天**（本地时区，不用 `toISOString()`） | `occurred_at` |
| 方式 | `select`：现金/微信/支付宝/银行转账/承兑汇票/其他 | 单据的 `payment_method`，没有则「银行转账」 | **拼进 `note`** |
| 备注 | `textarea` | 空 | 拼进 `note` 末尾 |

**方式为什么写进备注**：`financial_transactions` 没有 `method` 列，
`_write_finance`（`erp_common.py:96`）也没有这个入参。要真按方式出报表，
得给流水表加列 + 透传 `bank_account_id` —— 那是独立一小步，本步不夹带。
备注最终形如：`收款登记：客户名｜方式：微信｜ZZFB-E2E-第一笔`。

---

## 4. `App.jsx` 改动（行号可直接 grep）

| 行 | 内容 |
|---|---|
| `:782-786` | `orderPayDialog` / `orderPayBusy` / `orderPayResult` / `orderPayError` 四个状态 |
| `:5150` | `openOrderPayment(row, kind)` —— 只记 `{kind, row}`，清掉上次结果 |
| `:5157-5166` | `closeOrderPayment()` —— **已有结果时必放行**（见 §6 踩坑 1） |
| `:5169` | `submitOrderPayment({amount, occurred_at, method, note})` —— 拼备注 + POST + 重拉列表 |
| `:8008` | `refreshFinance()` —— 重拉 `/finance?limit=500` |
| `:10666-10684` | `<OrderPaymentDialog …/>` 挂载点（与 `PartnerModal` 同级，两个订单页共用） |

POST 的关键片段：

```js
const response = await fetch(`${API_BASE}/finance/${isSales ? 'receipt' : 'payment'}`, {
  method: 'POST',
  body: JSON.stringify({
    party_id: partyId,          // 销售取 customer_id，采购取 supplier_id（缺了就报错，不猜）
    order_id: row.id,           // ★ 有它才会冲单；没有就只是记一笔"预收"
    amount, occurred_at,
    note: composedNote,
    doc_no: row.order_no || '',
  }),
});
```

成功后 `await refreshSalesOrderList()` / `refreshPurchaseOrderList()` ——
**不能只改这一行**：后端 `_recalc_debt_chain` 会把同一客户后面所有单据的
`prev_debt` / `current_debt` 全部重算。

---

## 5. 验证

### 5.1 E2E（真 Chrome，`verify_frontend_step3_payment.mjs`）→ **51 / 51 全绿**

造 3 张单（销售 A 300 / 销售 B 300 / 采购 C 176），三层断言：

```
L1-L9   登录 / 客户 / 供应商 / 商品 / 三张单 / 三张都审核
F1      产物哈希（防 SW 缓存伪装）
F2-F8   点「收款」开窗 / kind=sales / 标题登记收款 / 默认 300.00 / 日期=今天 / 方式 6 项 / 有备注
F9-F11  提交后成功态：冲减本单 100.00、预收 0.00
F12     点「完成」关窗
F13-F15 未结清仍有收款按钮 / 服务端 received_amount=100
F16     再次打开默认 200.00（减去已收）
F17-F19 结清后「已结清」灰标 + 按钮消失 + 服务端 300
F20-F22 超额 400：提前黄字提示、结果冲 300 预收 100、订单累计不超净额
F23-F28 采购侧 kind=purchase / 标题登记付款 / 默认 176.00 / 服务端 paid_amount=176
F29-F38 流水 4 条：A 两笔 receipt 且 direction=in、金额 100+200、挂 customer_id、
        业务日期=今天、备注含方式；B 那笔按 400 记且备注含预收；C 是 payment/out 且挂 supplier_id
F39-F40 财务流水页能看到这笔钱，类型显示「收款」不是 receipt
F41     控制台零异常
Z       订单/客户/供应商/商品清理（流水由 cleanup 脚本收尾）
```

### 5.2 反证（改坏 → 必须变红）

| 反证 | 改动 | 实测结果 |
|---|---|---|
| A | POST 不带 `order_id`（不冲单） | **17 条红**：F15/F17-F19/F21/F22/F28（金额不再冲减）+ F30-F38（流水按 `related_order_id` 全对不上） |
| B | 弹窗默认金额用净额（不减已收） | **F16 红**：第二次打开填 300.00 而不是 200.00 |

同时注入后 `32 通过 / 17 失败`，还原 `grep PROBE` = 0，重建复跑 **51/51**。

> F39/F40 本身也是"先红后绿"的：第一版跑出来就是这两条红（财务页拿的是登录时的
> 旧快照、类型列直接打印英文 `receipt`），修完才绿。这条红是真 bug，不是仪式。

### 5.3 后端回归

`pytest tests/test_order_doc_type.py tests/test_order_settlement_and_finance_link.py tests/test_finance_analysis.py` → **28 passed**。

---

## 6. 本步真正修掉的两个 bug（E2E 抓的，不是预想的）

**① 成功面板把「完成」按死**
`setOrderPayResult()` 在 `await refreshSalesOrderList()` **之前**执行，
所以成功面板渲染时 `orderPayBusy` 还是 `true`，而 `closeOrderPayment` 里
`if (orderPayBusy) return;` → 点「完成」毫无反应、弹窗关不掉（F12 红）。
修复：`if (orderPayBusy && !orderPayResult) return;` —— 钱已经落账了，没有理由再拦。
ESC / 背景点击 / × 按钮同步改成"有结果就放行"。

**② 财务流水页的钱是"旧账"**
`finance` 状态只在登录时拉一次，之后任何收付款都不会进这一页；
而且类型列 `<td>{row.transaction_type}</td>` 把 `receipt` 原样打出来。
修复：新增 `refreshFinance()` 并注入 ctx，`FinancePage` 挂载时调一次；
新增 `FINANCE_TYPE_LABEL` / `financeTypeLabel()`（和 `DOC_TYPE_LABEL` **不是一张表**：
那张是"来源单据"，这张是"业务类型"）。

---

## 7. 顺手发现（本步**没**改，建议排期）

1. **删单会留下孤儿收付款流水**：`DELETE /sales-orders/{id}` 只 `_revert_finance(db, "sales_out", id)`，
   `related_type='receipt'` 的收款流水不会被冲销，`related_order_id` 就指向了已删单据。
   本批 E2E 的数据是我用 SQL 清的（`cleanup_verify_step3_payment.py`），
   真实业务里删单前应该拦一手：**有收付款记录的单据不允许直接删**。
2. `/invoices/sync-finance` 把所有发票一律记 `expense`（任务 1 已记录），销项发票方向相反。
3. 「方式」目前只进备注，想按方式出报表需要流水表加列（见 §3）。

---

## 8. 生效方式

```
npm run build  → ✓ 8s，index 主包 2,428.83 kB / gzip 568.25（+6.5 kB，弹窗+样式）
sw.js CACHE_VERSION = erp-pwa-v38
```

**重启 8010（`启动ERP.bat`）+ Ctrl+F5**（后端本步没改，但重启最稳）。

验收动线：销售订单 → 已审核的单子点「收款」→ 填金额 → 确认 → 看行变「已结清」
→ 切「财务流水」应能立刻看到这笔（中文「收款」）。

---

## 9. 回滚

```
_contract_module/backup/20261018_step3_payment/
  OrderPaymentDialog.jsx  pay-dialog.css  App.jsx  appLib.js  FinancePage.jsx  sw.js
  verify_frontend_step3_payment.mjs  cleanup_verify_step3_payment.py
```

---

## 10. 下一步（等验收）

1. 菜单：「开单管理」→「现货开单」+ 下架「销售出库（多单位）」
   （`SalesOrderUnitsBoard.jsx` 的 `handleStatus(order,'completed')` 与 `STATUS_LABELS` 要跟着改；
   菜单项只能追加在组末，`sort_order = 下标×10`）。
2. 发票页「关联客户」`ErpSearchSelect` → 写 `customer_id` / `contract_id`，
   解决 12 张存量发票因税号歧义挂不上的问题。
3. 修对账单 `generate` 的四个断点（发票方向 `out→output`、按 `customer_id` 取数、
   收付款加 `direction` 过滤、`include_orders`）。
