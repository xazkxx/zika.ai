# 第 13 批 · 需求 2 + 需求 3 交付报告

> 时间：2026-10-18
> 需求 2：财务流水「详情」只读抽屉
> 需求 3：全局打印二次确认
> 验证台：`_contract_module/verify_step7_flow_drawer_print.mjs` —— **31 / 31 全绿**（真 Chrome）
> 反证：两组改坏 → 变红 → 还原 → 复跑全绿，`grep PROBE` = 0

---

## 一、需求 2：财务流水详情抽屉

### 1.1 交付物

| 文件 | 类型 | 说明 |
|---|---|---|
| `frontend/src/components/finance/FinanceFlowDrawer.jsx` | 新建（LF，166 行） | 只读右侧抽屉本体 |
| `frontend/src/components/finance/finance-drawer.css` | 新建（LF） | 只写 `.flow-drawer*` 独占类名，不碰全局样式 |
| `frontend/src/pages/FinancePage.jsx` | 修改（CRLF） | 入口按钮 + 行点击 + 挂载抽屉 |

### 1.2 两个入口（都要能用，缺一个就算没做完）

- **点行**：`<tr data-flow-row={row.id} onClick={() => setFlowDetail(row)}>` —— `FinancePage.jsx:1151/1154`
- **点按钮**：操作列「详情」`<button className="link-btn" data-flow-detail={row.id}>` —— `:1164`
  按钮里必须 `event.stopPropagation()`，否则点按钮会先冒泡到行、再触发一次（值一样但会多渲染一次）。

### 1.3 抽屉内容（对齐「完整快照」这五个字）

类型（收/付）、金额、方向、关联单据、单据类型、往来单位、业务日期、会计期间、登记时间、操作人、资金账户、收支类别、备注。

- 金额 `¥1,234.56`（千分位 + 两位小数）；
- 关联单据号优先取 `flow.doc_no`（**登记当时的快照**），没有才退回 `${单据类型} #${内部 id}`；
- 登记时间走 `new Date()` 本地时区格式化，**不能直接 slice ISO 字符串**（会差 8 小时）；
- 底部固定一行提示「要冲销不要改这里」——抽屉是只读的，别让人以为能改。

### 1.4 三个技术要点（都是踩过的）

1. **抽屉必须挂在 `ResizableLayout` 外面**。
   `ResizableLayout` 只在"恰好 2 个子元素"时可拖拽（`Children.toArray(children).length === 2`），
   多挂一个就**静默降级**成普通网格 —— 拖不动，也不报错。
   所以 `return` 外面包 `<>…</>`，抽屉放在 `</ResizableLayout>` 之后（`FinancePage.jsx:1184`）。
2. **只读要能被证伪**：抽屉里 `input/select/textarea` 数量必须是 0（验证台 D10）。
3. **ESC / 遮罩 / 「知道了」三种关法**都给（D13/D15）。

---

## 二、需求 3：全局打印二次确认

### 2.1 交付物

| 文件 | 类型 | 说明 |
|---|---|---|
| `frontend/src/lib/printConfirm.js` | 新建（LF，37 行） | 模块级单例，`confirmPrint()` 返回 Promise |
| `frontend/src/components/ui/PrintConfirmHost.jsx` | 新建（LF，109 行） | 全局唯一宿主弹窗 |
| `frontend/src/components/ui/print-confirm.css` | 新建（LF） | 只写 `.print-confirm*` |
| `frontend/src/App.jsx` | 修改（CRLF） | `:10-11` import；`:1604` 拦在 `printPdf` 最前；`:10734` 挂宿主 |
| `frontend/src/components/statements/StatementEditor.jsx` | 修改（LF） | `:58` import；`:293` 拦在 `setBusy('print')` 之前 |

### 2.2 为什么是"单例模块 + 宿主"，而不是 React Context

打印的调用点散在 20+ 个页面里，很多是普通函数（不是组件），拿不到 Context。
所以 `lib/printConfirm.js` 只暴露两个函数：

```js
let impl = null;
export function registerPrintConfirm(fn) { impl = fn; return () => { if (impl === fn) impl = null; }; }
export function confirmPrint(options = {}) {
  if (!impl) return Promise.resolve(true);   // ← 宿主没挂载就放行
  return impl(options);
}
```

**"宿主没挂载就放行"是故意的**：确认框是**防误触**，不是权限闸口。
如果因为"框弹不出来"就静默不打印，用户表现为"点了没反应、控制台不报错"，
这是最难排查的一类 bug。宁可漏一次确认，也不能让打印变成哑巴。

### 2.3 两个必须守住的时序

1. **确认必须在 `fetch` 之前**（`App.jsx:1604`、`StatementEditor.jsx:293`）。
   晚一步就等于"用户点取消时 PDF 已经生成好了"，白跑一次后端渲染。
2. **连续点击要按取消结算**：`PrintConfirmHost` 里 `pendingRef` 存的旧请求先 `resolve(false)`，
   再换成新的；否则前一个 Promise 永远悬着，那次打印会"卡住"。

### 2.4 覆盖的三个入口（验证台各点一次）

| 入口 | 走哪条通道 | 验证项 |
|---|---|---|
| 销售订单行「打印」 | `ctx.printPdf`（`App.jsx:1595`，20+ 页面共用） | P1–P7 |
| 财务页「打印中心 → 打印客户对账单」 | 同上 | P8 |
| 销售管理 → 增强对账单「打印 PDF」 | **`StatementEditor` 自带一份 printPdf，不走 ctx** | P9 |

第三条是最容易漏的：它对 `saveBlob` 是直接调的，压根不经过 `ctx`。

---

## 三、验证台账（真 Chrome + CDP 下载行为）

验证台不是"看框弹没弹"，是**看磁盘**：`Browser.setDownloadBehavior({behavior:'allow', downloadPath})`
显式允许下载，然后比文件数变化。

```
A1 admin 登录成功
A2 建好一条收款流水（带单号/客户/经办人）
A3 浏览器加载的 bundle = dist 里的本次构建     ← 防 SW 缓存伪装全绿
D0 能进入「财务流水」页
D1 列表里能找到这条流水，且行内有「详情」按钮
D2 点行弹出只读抽屉
D3 金额显示为 ¥1,234.56
D4 类型显示「收款」
D5 关联单据号正确（doc_no 快照）
D6 往来单位解析成客户名
D7 登记时间格式为 YYYY-MM-DD HH:mm
D8 操作人显示「张三」
D9 备注显示完整
D10 抽屉里没有任何输入控件（只读）
D11 抽屉贴在右侧且宽度合理（≥380px）
D12 底部说明了「要冲销不要改这里」
D13 ESC 能关闭抽屉
D14 行内「详情」按钮也能打开，且只会开一个抽屉
D15 点遮罩能关闭抽屉
D16 抽屉没有破坏财务页的分栏（仍 ≥2 列）   ← 证明挂载位置正确
P0 能进入「销售订单」页
P1 订单行上有「打印」按钮并已点击
P2 弹出「确认打印此单据？」
P3 确认框里写明了要打印哪张单（文件名含单号）
P4 两个按钮是「取消 / 确认打印」
P5 点「取消」后确认框消失
P6 取消后磁盘上没有新文件（真的没打印，不是"打了但没提示"）
P7 点「确认打印」后真的产出了文件
P8 打印中心「打印客户对账单」也先弹确认（覆盖对账单入口）
P9 「增强对账单」的打印也接了确认（这条通道不走 ctx.printPdf）
P10 全程没有 JS 异常

通过 31 / 31
```

### 反证（证明断言不是摆设）

| 改坏哪里 | 预期 | 实测 |
|---|---|---|
| `App.jsx:1604` 注释掉 `confirmPrint` | P2/P3/P4/P6/P8 红 | ✅ 红（P6：`0 → 1`，磁盘真的多了一个 PDF） |
| `FinanceFlowDrawer` 的 `docText` 退回"只显示内部 id" | D5 红 | ✅ 红（只看到 `XS-ZZB2-099653` 就失败） |

合计 **25 / 31**，红的恰好是这 6 条；还原后复跑 **31 / 31**，`grep PROBE` = 0。

> 注意 P9 在反证 ① 里仍绿 —— 这是对的：`StatementEditor` 用的是它自己那份 `confirmPrint`，
> 没被改坏。恰好反证了"三条入口是三条独立通道"。

### 验证脚本第一版的两条红（自身操作路径问题，非功能缺陷）

1. **P8 选不到客户**：脚本取了 `div[role="combobox"]` 的第 0 个 —— 那是「新增财务记录」表单里的下拉，
   不是打印中心那一格 → `printParty.customer_id` 仍空 → 按钮恒灰。
   而且 `ErpSearchSelect` 的触发器开面板走的是 **`onClick`**，派发 `mousedown` 根本展不开。
   改为：按 `label` 文案「客户（对账单」锚定 `.ssel` 下标 → `page.click()` → 选项派发 `mousedown`（组件就挂在这个事件上）。
2. **P9「打印 PDF」是灰的**：`disabled={!statement}` —— 编辑器必须先载入一张对账单。
   改为：脚本先用 `POST /statements/generate` 造一张草稿（测试客户 + 2026 全年），
   再用编辑器右侧「载入已存对账单」下拉选中它，等 `[data-statement-no]` 不再是「未生成」，然后点打印。
   跑完 `DELETE /statements/{id}` 把草稿删掉。

---

## 四、测试数据清理

新增 `_contract_module/cleanup_step7.py`（默认干跑，加 `--apply` 才执行）：

- **收付款流水删不掉**（`DELETE /finance/entries` 对 `receipt/payment` 一律 409）→ 只能 SQL 清，
  顺序 `journal_entry_lines → journal_entries → financial_transactions`；
- 订单明细表列名是 **`sales_order_id`**，不是 `order_id`（踩过一次）；
- 孤儿体检必须**按 `related_type` 找对应的表**：`sales_return` 指的是 `sales_returns.id`，
  拿它去 `sales_orders` 里找必然"找不到"，会把合法的退货冲减（#12093 `XSTH20261017001`）误报成孤儿。

本次实清：流水 4 条、凭证 4 张/8 行、订单 4 张/4 行、临时客户 4 个，残留全部归零，孤儿 0。

---

## 五、改动清单（便于回滚）

备份：`backup/20261018_step7_flow_drawer_print/`（9 个文件）

```
frontend/src/App.jsx                                      :10-11  import
                                                          :1604    printPdf 开头拦一次（在所有页面之前）
                                                          :10734   挂 <PrintConfirmHost />
frontend/src/pages/FinancePage.jsx                        :6      import FinanceFlowDrawer
                                                          :968    flowDetail state
                                                          :1151   <tr onClick>
                                                          :1164   操作列「详情」按钮
                                                          :1184-1193  挂在 </ResizableLayout> 之后
frontend/src/components/statements/StatementEditor.jsx    :58     import confirmPrint
                                                          :293    拦在 setBusy('print') 之前
frontend/src/components/finance/FinanceFlowDrawer.jsx     新建
frontend/src/components/finance/finance-drawer.css        新建
frontend/src/lib/printConfirm.js                          新建
frontend/src/components/ui/PrintConfirmHost.jsx           新建
frontend/src/components/ui/print-confirm.css              新建
frontend/public/sw.js                                     CACHE_VERSION = erp-pwa-v42
```

构建：`✓ built in 7.75s`，产物 `assets/index-*.js` 与浏览器实载一致（A3）。
