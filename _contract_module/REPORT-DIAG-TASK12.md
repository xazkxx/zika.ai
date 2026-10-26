# 任务 1 + 任务 2：对账单查不到数据的根因 / 重复流程梳理

> 2026-10-18 晚。只读诊断，未改任何业务代码。
> 诊断脚本：`_contract_module/diag_statement_data.py`、`diag_data_profile.py`、`diag_invoice_owner.py`（全部只读）。

---

## 一、结论速览（先看这 5 条）

1. **你选的客户名下，合同一条都没有**——三个账套（`public` / `co_02` / `co_03`）的 `contracts` 表**全库 0 条**，不是"状态不是已生效被拦"，是**从来没录进去过**。
2. 那个客户有 **1 张销售出库单**（29.64 元），但**对账单的 generate 根本不读销售单**，只读合同 / 发票 / 收付款。
3. 发票有 4 张，但 ① 名字是《陕西送变电工程有限公司》，**客户档案里没有这个名字**（只有三个"分公司/项目部"）；② 发票方向存的是 `output`，对账单查的是 `out`——**永远匹配不上（真 bug）**。
4. 资金流水里**从来没有 `receipt` / `payment` 这种"真收付款"**，只有 `receivable`（开单产生的应收）、`payable`、`expense`。而 ① 对账单只认 `receipt/payment`；② **前端根本没有"收款/付款"入口**（`POST /finance/receipt` 接口有，零调用方）。
5. 所以"没数据"不是一处坏，是**四条链路全断**。下面逐条给证据。

---

## 二、任务 1：为什么生成草稿说没数据

### 2.1 先确认是哪个客户

`customers` 表里名字带"送变电"的有 3 个（三个 schema 里 id 相同，是同一批主数据复制）：

| id | 名称 | 期初应收 |
| --- | --- | --- |
| 714 | 陕西送变电第一分公司 | 0.00 |
| 716 | 陕西送变电机具分公司 | 0.00 |
| 720 | 陕西送变电公司一分司-攀西特高压交流工程线路工程 | 0.00 |

三个都查了，**结果一样**。下面以 720 为例（它是唯一有业务单据的那个）。

### 2.2 四个数据源逐个核（2026-01-01 ~ 2026-10-18）

| 数据源 | generate 的取数条件 | 库里实际 | 判定 |
| --- | --- | --- | --- |
| 合同 | `party_type=customer` + `party_id` + `direction=out` + `sign_date∈区间` + `status≠void` | **0 条**（全库 0 条） | ❌ 无 |
| 发票 | `direction=out` + `issue_date∈区间` + `counterparty_name = 客户名`（**精确相等**） | 4 张，但名字是《陕西送变电工程有限公司》，且 `direction=output` | ❌ 双杀 |
| 收付款 | `customer_id` + `type∈(receipt,payment)` + `occurred_at∈区间` | 1 笔，但 `type=receivable`（开单产生应收，不是收款） | ❌ 被过滤 |
| 销售出库单 | **generate 压根不读这张表** | 1 张 `XS20261018001`，29.64，`doc_type=outbound`，`status=completed` | ⚠️ 数据在，但口径不含 |

于是 `erp_statement.py:399` 命中 `if not lines:` → 抛 404，前端提示就是那句"该区间内没有找到…的合同 / 发票 / 收付款记录"。

### 2.3 五个断点（其中 3 个是代码 bug，2 个是数据缺口）

**断点 ①（数据缺口）合同表是空的。**
`contracts` 在 `public` / `co_02` / `co_03` 三套账里**都是 0 条**。也就是说「购销合同」和「合同台账」两个页面都**从没成功保存过一张合同**。
> 顺带排除一种可能：不是"状态不是已生效"。`generate` 只排除 `void`，`draft` 也会被抓进去。

**断点 ②（真 bug）发票方向枚举对不上。**
- 发票模型：`input` / `output` / `unknown`（`app/models/invoice.py:83-85`）
- 对账单过滤：`Invoice.direction == "out"`（`erp_statement.py:335`）

`'output' != 'out'` → **一张都取不到**。这条不管你名字对不对，都是 0。

**断点 ③（真 bug + 数据缺口）发票按"名字完全相等"匹配往来单位。**
`erp_statement.py:339-340` 是 `Invoice.counterparty_name == party_name`。
库里 4 张发票的对方是《陕西送变电工程有限公司》（购买方同名、销售方是我方），而客户档案里只有"第一分公司 / 机具分公司 / 一分司-攀西…"。**父公司和分公司不是同一个客户**，字符串永远不相等。
发票表**没有 `customer_id`、也没有 `contract_id`**，所以只能靠名字——这是设计层面的断点。

**断点 ④（真 bug，最致命）收付款类型从来没被写入。**
全库资金流水类型分布：

| 账套 | 类型 | 笔数 | 金额 |
| --- | --- | --- | --- |
| public | expense | 6 | 21,937.48 |
| public | payable | 5 | 2,028.93 |
| public | receivable | 2 | −6,470.36 |
| co_02 | expense | 4 | 19,506.40 |
| co_03 | expense | 4 | 19,490.74 |
| co_03 | receivable | 1 | 4,181.50 |

**`receipt` / `payment` 一次都没出现过。** 原因很清楚：
- 后端有 `POST /finance/receipt`、`POST /finance/payment`（`erp_finance.py:271/278`），逻辑很完整（还能按订单冲抵、超出部分算预收、回写 `received_amount` 和欠款链）；
- 但**前端全项目零调用**（`grep -rn "finance/receipt" frontend/src` 空）；
- 「财务流水」页的新增表单类型只有 **收入 / 支出**（`pages/FinancePage.jsx:988`），没有"收款/付款"。
→ 所以这个能力**只有 API，没有 UI**。

**断点 ⑤（口径缺口）对账单不认销售单，开单只写"应收"不写"已收"。**
销售开单（`doc_type=outbound`）审核后写的是 `transaction_type=receivable`（例如 public #12123：29.64，「销售开单 XS20261018001 产生应收」）。这代表"债权成立"，不代表"钱到账"。
- 对账单的已收只认 `receipt` → 29.64 这笔永远不会进"本期已收"；
- 对账单的"本期新增"只认合同 → 29.64 也不会进"本期新增"。
结果：**即使你开了单、客户也付了钱，只要没录合同，对账单还是空**。

**额外发现（不是本次问题，但会算错数）**：`/invoices/sync-finance` 把**所有**发票一律记成 `expense`（支出，`erp_invoice.py:1534`），销项发票（我方开出去、应该是收入/应收）也被记成支出。co_02 那 4 笔 expense 就是它生成的。这会让"日常收支/利润"方向反掉。

### 2.4 那要怎么录，才能被对账单抓到

按现在代码的口径，**最小可用闭环是 3 步**（缺一不可）：

1. **录合同**：销售管理 →「合同台账」→ 新建 → 方向选**销售（out）** → 对方选这个客户 → 签约日期落在对账区间内 → 保存（状态草稿即可，只要不是作废）。
2. **录收款**：目前**只能调接口**，UI 没有入口（见断点 ④）。要么等任务 3 补按钮，要么先用 `POST /api/v1/finance/receipt`：
   ```json
   { "party_id": 720, "amount": 1000, "order_id": 4077, "occurred_at": "2026-10-18", "note": "首款" }
   ```
   `order_id` 可省；带了会自动冲抵并把订单的"实收/累欠"重算。
3. **录发票（可选）**：即使录了，当前也抓不到——必须先修断点 ②③（方向映射 + 名字/税号匹配）。

> 一句话：**合同是唯一"现在就能被抓到"的入口**。你先在合同台账录一张该客户的销售合同，再点生成草稿，就一定能出数（这一点我可以先陪你验一次，不改代码）。

---

## 三、任务 2：重复流程梳理

### 3.1 现状全表：菜单 ↔ 表 ↔ 谁在写

| 菜单（分组） | key | 落到哪张表 | 写入方 | 评价 |
| --- | --- | --- | --- | --- |
| 购销合同（销售） | `contracts` | `contracts` | ContractsPage → `POST /contracts` | **和「合同台账」同一张表**，纯 UI 重复 |
| 合同台账（销售） | `contracts-ledger` | `contracts` | ContractsLedger → `POST /contracts` | 功能全（明细/原件/OCR/导出），**保留这个** |
| 开单管理（销售） | `sales` | `sales_orders` (`doc_type=outbound`) | App.jsx → `POST /sales-orders` | 无订单也能直接出库，**绕过订单** |
| 销售订单（销售） | `sales-order` | `sales_orders` (`doc_type=order`) | OrderBoard → `POST /sales-orders` | 正规上游；`转开单` 生成 outbound |
| 销售出库（多单位） | `sales-units` | `sales_orders` (`doc_type=outbound`) | SalesOrderUnitsModal | **第三个出库入口**，同一张表 |
| 销售对账单（销售） | `sales-statement` | — | **菜单别名** → 跳「往来对账」客户视图 | 旧口径（读资金流水） |
| 采购对账单（采购） | `purchase-statement` | — | 同上，供应商视图 | 同上 |
| 增强对账单（销售） | `statements-editor` | `statements` + `statement_items` | 新页面 | 新口径（合同+发票+收付款），**保留** |
| 采购入库（采购） | `purchase` | `purchase_orders` (`doc_type=inbound`) | App.jsx | 无订单也能直接入库 |
| 采购订单（采购） | `purchase-order` | `purchase_orders` (`doc_type=order`) | OrderBoard → `转入库单` | 正规上游 |
| 发票管理（财务） | `invoices` | `invoices` | InvoicesPage | **有**，但同步财务一律记支出 |
| 财务流水（财务） | `finance` | `financial_transactions` | FinancePage（只有收入/支出） | **收付款没入口** |
| 应收账款/应付账款 | `receivable`/`payable` | 读 `financial_transactions` | — | 只读汇总 |
| 往来对账 | `ledger` | 读 `financial_transactions` | — | 旧对账口径 |

### 3.2 "两套"的真相其实分三种

1. **同表不同 UI（纯重复）**：「购销合同」vs「合同台账」——都写 `contracts`。
   → 废弃不需要迁移数据，只要撤菜单 + 撤页面。
2. **同表不同入口（口径重复）**：「开单管理」vs「销售出库（多单位）」——都写 `sales_orders` 且 `doc_type=outbound`，区别只是后者支持辅助单位。
3. **不同表不同口径（数字会打架）**：「销售/采购对账单（= 往来对账，读资金流水）」vs「增强对账单（读合同+发票+收付款）」。
   → 同一个客户在两边看到的"期末应收"可以不一样，因为一个算的是流水累计，一个算的是合同−已收。

### 3.3 建议的标准闭环

```
① 合同层   合同台账（contracts, direction=out/in）
              │  一张合同 → N 张订单（小单可跳过合同，见待拍板 Q3）
              ▼
② 订单层   销售订单 / 采购订单（doc_type=order）
              draft 草稿 → pending 待审核 → approved 已审核
              ▲ 审核通过才允许转单（现在没有这道闸）
              ▼
③ 出库层   销售出库 / 采购入库（doc_type=outbound / inbound）
              approved → shipped 已发货 → completed 已出库
              自动写：库存流水 + 应收/应付流水（receivable / payable）
              ▼
④ 票款层   发票管理（invoices, direction=output/input，关联 customer_id + contract_id）
              收款/付款（financial_transactions, type=receipt/payment，关联 order_id）
              ▼
⑤ 对账层   增强对账单（statements）
              本期新增 = 合同额（或出库额）· 已开票 · 已收 · 期末应收
              打印/导出 → PDF / Excel
```

一句话：**合同 → 订单 → 审核 → 出库 → 开票 → 收款 → 对账**，每层只允许一个入口。

### 3.4 逐层建议（按"改动小、风险低"排序）

**合同层：废弃「购销合同」，统一「合同台账」。**
- 理由：同表，功能是子集；合同台账已有 direction / 明细 / 原件 / OCR / 导出。
- 做法：菜单项下架（`menuGroups` 删 `contracts` 一项 + 后端 `PERMISSION_CATALOG` 同步）→ 页面组件保留一个版本周期（深链兜底），下个版本删。
- 风险：**零数据迁移**。唯一影响是用户收藏的旧链接。

**出库层：保留「销售订单 → 审核 → 转开单」为唯一标准路径，把另外两个降级。**
- 「开单管理」建议**保留但改名**为「销售开单（现货直发）」，明确它只服务"没有订单、当场发货"的场景；
- 「销售出库（多单位）」**合并进「开单管理」做成"多单位模式"**（它们本来就是同一张表、同一个 `doc_type`），下架独立菜单；
- 不建议直接删「开单管理」：它是历史数据的入口，删了旧出库单就查不到了（除非先做出库台账页）。
- 采购侧对称：`采购入库` 同样改名「采购入库（现货直收）」，正规路径走「采购订单 → 转入库单」。

**资金层：发票有、收付款没有 → 这就是对账单算不出数的根因。**
- 发票：入口在「财务管理 → 发票管理」，能录、能传原件、能同步财务；问题是同步一律记 `expense`，且不挂客户。
- 收付款：**唯一缺口**。后端接口齐全（含订单冲抵、预收拆分、欠款链重算），只差 UI。
- 建议：把「收款/付款」做成**两个入口**——① 财务流水页的新增类型；② 订单列表操作列的「收款/付款」按钮（自动带 party_id、金额默认未收余额）。两个入口都调同一个 `POST /finance/receipt|payment`。

**对账层：保留「增强对账单」，把两个旧"对账单"菜单改名。**
- 「销售对账单 / 采购对账单」本质是「往来对账」的预设视图，建议改名「往来对账（客户）/（供应商）」并挪到财务分组，避免和"对账单"抢名字。
- 「增强对账单」承担对外正式对账（可打印、可导出、有快照）。

### 3.5 建议的菜单终态（供讨论）

```
销售管理：销售订单 · 销售开单（现货直发） · 报价单 · 销售退货 · 合同台账 · 增强对账单
采购管理：采购订单 · 采购入库（现货直收） · 采购退货
财务管理：财务流水 · 收款登记 · 付款登记 · 应收 · 应付 · 往来对账 · 发票管理 · 现金银行 · 日常收支
（下架：购销合同 · 销售出库（多单位） · 销售对账单 · 采购对账单）
```

---

## 四、任务 3 的代码方案（**待你拍板后再动手**）

### 4.1 状态机（含旧数据兼容）

| 你现在要的 | 建议 code | 兼容旧值 | 说明 |
| --- | --- | --- | --- |
| 草稿 | `draft` | 已有 | 可改可删 |
| 待审核 | `pending` | **旧 `submitted` 视作 pending** | 提交后进入 |
| 已审核 | `approved` | — | 才能转出库 |
| 已发货 | `shipped` | — | 出库单生成时 |
| （终态） | `completed` | 已有 | 转单完成，保留可追溯 |
| 已取消 | `cancelled` | 已有 | 非终态可取消 |

> 关键：**不要改全局 `DOC_STATUS_LABELS`**（`lib/appLib.js:138` 被生产单/盘点/调拨等十几个模块共用，改 `submitted` 的中文会全站变字）。新加一份 `ORDER_STATUS_LABELS` 只给订单用。

### 4.2 后端改动（3 个文件）

| 文件 | 位置 | 改什么 |
| --- | --- | --- |
| `app/api/v1/routes/erp_sales.py` | `:384` PATCH status | 加白名单 + 合法迁移表（`draft→pending→approved→shipped→completed`，`cancelled` 从非终态可达），非法迁移 409 带中文原因 |
| 同上 | `:426` to-outbound | 加守卫：`status == 'approved'` 才允许（现在只挡 `completed`）；转出后订单置 `shipped`（或直接 `completed`，见 Q4） |
| 同上 | 新接口 | `POST /sales-orders/{id}/approve`、`/reject`（审核留痕：`approved_by` / `approved_at` 两列，可空，DDL 走 `_add_missing_columns`） |
| `app/api/v1/routes/erp_purchase.py` | `:297` / `:315` | 同上对称改造 |
| `app/api/v1/routes/erp_finance.py` | `:271` / `:278` | **已就绪，不用改**；只补一句：`order_id` 与 `party_id` 不一致时 400 |

### 4.3 前端改动（4 处）

| 文件 | 位置 | 改什么 |
| --- | --- | --- |
| `lib/appLib.js` | `:138` 后 | 新增 `ORDER_STATUS_LABELS` + `emptyOrderPaymentForm` |
| `components/docs/OrderBoard.jsx` | `:295` 状态列 | 用新标签表；状态徽标按 draft/pending/approved/shipped/completed 上色 |
| 同上 | `:304` 操作列 | 加「审核」（`draft|pending` 可见）+「收款/付款」（`approved|shipped` 可见，金额默认 = 应收−实收） |
| `components/docs/OrderPaymentDialog.jsx` | 新建 | 收款/付款弹窗：金额、日期、方式、备注；提交 `POST /finance/receipt|payment` |
| `App.jsx` | ctx 装配处 | 加 `approveOrder` / `openOrderPayment` 两个 handler 注入 ctx（OrderBoard 是共享组件，采购/销售都靠 ctx 拿差异） |

> OrderBoard 是采购/销售**共用**组件（`pages/SalesOrderPage.jsx` 只有 21 行转发），所以这 4 处改一次，两张订单页同时生效——这也是它当初被抽出来的原因。

### 4.4 对账单口径必须一起修（否则任务 3 白做）

`erp_statement.py` `generate` 里改 4 处：

1. `:335` 发票方向映射：`out → output`、`in → input`（一行映射，修断点 ②）
2. `:339` 发票匹配：优先 `Invoice.customer_id == party_id`（需给 `invoices` 加 `customer_id` / `contract_id` 两列，均可空），退回 `counterparty_name` 时用**去括号/去空格的包含匹配**（修断点 ③）
3. `:373` 收付款加 `direction` 过滤（现在 `receipt` 和 `payment` 一起捞，应收账单会混进付款）
4. 新增 `include_orders`（默认 true）：把 `doc_type=outbound/inbound` 且期间内的单据作为"本期新增"，`received_amount` 作为已收——这样**没录合同、但开了单**的客户也能出对账单（修断点 ⑤）

---

## 五、需要你拍板的 5 个问题

1. **开单管理**保留为"现货直发"（无订单直接出库），还是彻底隐藏、强制先开订单？（我倾向保留 + 改名）
2. **销售出库（多单位）**合并进开单管理（同一张表），可以吗？
3. **合同是不是必经环节**？小单没有合同，能不能直接"订单 → 出库"？（我倾向：合同可选，`include_orders` 兜住）
4. **审核**是"一人可审"还是"制单≠审核"（按角色/用户隔离）？转单后订单停在哪一步：`shipped` 还是直接 `completed`？
5. **发票要不要加 `customer_id` / `contract_id` 两列**？（加了才能根治名字匹配；不加只能靠模糊匹配，仍会错配）

拍板后我按"一次一步"来：先后端状态机 + 守卫（含 3 组反证），验收后再做前端按钮，最后改对账单口径。
