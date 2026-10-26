# MANUAL_PATCHES.md —— 生成物上的人工改动清单

> 只登记**直接改在 `frontend/src/pages/*.jsx` 生成物上**的补丁。
> 改在 `App.jsx` / 组件 / lib / CSS 里的东西不在此列（那些不会被生成器覆盖）。

---

## 1. 为什么需要这份清单

`scripts/extract_pages.py` 的工作方式是：从 `App.jsx` 里把 `{selectedTab === 'xxx' && (...)}`
这一整块 JSX **逐字抽出来，整文件覆盖** `src/pages/XxxPage.jsx`（文件头那行
`// 自动提取自 App.jsx（selectedTab='xxx'）` 就是它的签名）。

所以任何**在生成物上加的手工改动，重跑一次就全没了**。麻烦在于它不会报错：

| 丢失的东西 | 构建 | 页面表现 | 怎么发现 |
|---|---|---|---|
| `import { itemRowError }` 但 `<p>` 还在 | 通过 | 该页运行时报 `itemRowError is not defined`，白屏 | 打开页面就炸，好发现 |
| `import` 和 `<p>` 一起没（生成器原样） | 通过 | 红字校验凭空消失，半填能直接提交 | **只能靠肉眼** |
| `data-doc-form` 属性没了 | 通过 | 表单瞬间退回旧样式（焦点环、必填标签、合计条全没了） | **只能靠肉眼** |
| `unitOptionsFor` 解构没、但 `<select>` 还在 | 通过 | 打开页面即 `unitOptionsFor is not defined`，白屏 | 好发现 |
| 解构和「单位」下拉一起没 | 通过 | 单位列整列消失，只能按基础单位录数量，**换算不会发生** | **只能靠肉眼** |
| `SearchSelect` 的 import 在、商品块退回 `<select>` | 通过 | 商品列变回 260 项长下拉，搜索能力静默消失 | **只能靠肉眼** |
| 商品块是 `SearchSelect`、但 import 没了 | 通过 | 该页运行时 `SearchSelect is not defined`，白屏 | 好发现 |

后几行就是这份清单存在的理由：**静默失效**。

---

## 2. 一键恢复（推荐用这个，不用手抄）

```bash
python scripts/patch_doc_forms.py            # 体检：只报告，不改文件
python scripts/patch_doc_forms.py --apply    # 打补丁
python scripts/patch_doc_forms.py --check    # 有缺失就退出码 1（可挂进 CI / 构建前）
```

特性：

- **幂等**：已经打过的不会重复打，连跑两次第二遍是「全部补丁在位」。
- **不猜**：找不到插入锚点（生成物结构变了）就报错退出，绝不"大概插在这儿"。
- **跟随换行符**：这几个页面是 CRLF，补进去的每一行也是 CRLF。
- **已验证**：把 4 个单据页的补丁全部剥掉，再 `--apply`，产物与手工版本
  **逐字节一致**（`filecmp.cmp(shallow=False)` 四个文件全 `True`）。

标准重抽流程：

```bash
python scripts/extract_pages.py --keys purchase,sales,purchase-order,sales-order
python scripts/patch_doc_forms.py --apply
python scripts/patch_doc_forms.py --check      # 必须是 0
cd frontend && npm run build
```

> 只重抽了别的页面也要跑一次 `--apply`：它对没动的文件是空操作。

---

## 3. 清单（2026-10-17 第 14/15 轮）

行号是登记时的，**动手时以锚点为准**（生成器一重跑就会漂）。

### 3.1 单据页 · 补丁（⚠️ 2026-10-17 第三步-B 结束：**0 页**，四家全薄壳）

| 文件 | `data-doc-form` 值 | 提交处理函数 | 明细行 handler | 状态 |
|---|---|---|---|---|
| ~~`PurchasePage.jsx`（采购入库）~~ | `inbound` | `submitInboundForm` | `handleInboundItemChange` | **已移出**：第三步-B 改成薄壳（`components/docs/PurchaseInboundBoard.jsx`），`data-doc-form` 等已随 UI 搬进组件；App.jsx 里该页只剩挂载行，extract_pages.py 不会再覆盖 |
| ~~`SalesPage.jsx`（销售出库/开单）~~ | `outbound` | `submitOutboundForm` | `handleOutboundItemChange` | **已移出**：第三步-B 第二家改成薄壳（`components/docs/SalesOutboundBoard.jsx`，`patch_doc_forms.py` 的 SPECS 已同步移除）。注意菜单标签是**「开单管理」**（`page_key=sales`）。`serializeSalesItems`/`price_auto` 不在本页 —— 那是 `sales-units`（销售出库（多单位））页的链路 |
| ~~`PurchaseOrderPage.jsx`（采购订单）~~ | `purchase-order` | `submitPurchaseOrderForm` | `handlePurchaseOrderItemChange` | **已移出**：第三步-B 第三家改成薄壳（`components/docs/OrderBoard.jsx`，与销售订单共用 CONFIG）。「转入库单」按钮保留在 OrderBoard 里，只在 `status !== 'completed'` 时出现 |
| ~~`SalesOrderPage.jsx`（销售订单）~~ | `sales-order` | `submitSalesOrderForm` | `handleSalesOrderItemChange` | **已移出**：第三步-B 第四家，同上（`kind="sales"`，按钮叫「转开单」） |

**补丁 A —— import（第 2–3 行，紧跟生成器注释那行）**

```jsx
// 自动提取自 App.jsx（selectedTab='purchase'）— 见 scripts/extract_pages.py
import SearchSelect from '../components/search-select/SearchSelect.jsx';
import { itemRowError } from '../lib/orderLines';
export default function PurchasePage({ ctx }) {
```

锚点：`// 自动提取自 App.jsx` 那行的**下一行**。两条 import 顺序无所谓（补丁 A 和补丁 F
各自独立插入，脚本跑第二遍时不会重排）。

**补丁 B —— 表单作用域属性（`<form>` 那一行，原第 968 行）**

```jsx
<form onSubmit={submitInboundForm} className="erp-form" data-doc-form="inbound">
```

锚点：`<form onSubmit={submitXxx} className="erp-form"` 这个前缀（每个文件只应命中 1 次）。
**这个属性是 CSS 的命根子**：`styles.css` 末段那 150 余行单据表单样式全部挂在 `[data-doc-form]` 上，
属性没了 = 样式静默失效，但构建照样成功。

**补丁 C —— 半填红字（明细行 `</div>` 之前，原第 1041 行）**

```jsx
                        {/* 半填行红字：空行时内容为空串，CSS 用 :empty 直接隐藏 */}
                        <p className="line-invalid" role="alert">{itemRowError(row, index)}</p>
                      </div>
                    ))}
                    <div className="order-items-summary">
```

锚点：`                    <div className="order-items-summary">` **之前**最近的那个
`                      </div>`（即明细行 div 的收尾）。缩进 24 空格。

> 为什么 `<p>` 常驻、而不是条件渲染：空行时它的内容是空串，CSS 用
> `[data-doc-form] .line-invalid:empty { display: none }` 直接隐藏 ——
> 既保证「空行零视觉噪音」，又不用在 JSX 里写三元表达式。

**补丁 D —— ctx 解构补 `unitOptionsFor`（`} = ctx;` 之前，原第 958 行）**

```jsx
    warehouses,
    // 明细行「单位」下拉的选项（基础单位恒在，辅助单位异步补齐）
    unitOptionsFor
  } = ctx;
```

锚点：`    warehouses` + 换行 + `  } = ctx;`。
⚠️ 判"要不要补"只能看**解构区**（`unitOptionsFor` 紧跟 `} = ctx;`）；
全文搜 `unitOptionsFor` 会假绿 —— 补丁 E 的 JSX 里也有这个词，而**解构丢了页面必崩**。

**补丁 E —— 「单位」下拉（「数量」的 `</label>` 之后、「单价」的 `<label>` 之前）**

```jsx
                        <label>
                          单位
                          <select
                            value={row.unit || unitOptionsFor(row.product_id)[0]?.name || ''}
                            onChange={handleInboundItemChange(index, 'unit')}
                            disabled={!row.product_id}
                          >
                            {unitOptionsFor(row.product_id).length === 0 && (
                              <option value="">{row.product_id ? '该商品未设单位' : '先选商品'}</option>
                            )}
                            {unitOptionsFor(row.product_id).map((option) => (
                              <option key={option.name} value={option.name}>{option.name}</option>
                            ))}
                          </select>
                        </label>
```

锚点：`value={row.quantity} onChange={handleXxx(index, 'quantity')} />` 那一行之后的第一个
`</label>`。缩进 24 空格。

几处设计说明：

- `value` 在 `row.unit` 为空时回落到**第一个选项**（基础单位），避免 React 受控值不在
  options 里导致下拉显示空白。
- **只有选项为空才渲染占位 option**（"先选商品" / "该商品未设单位"）。否则下拉里会出现
  "基本单位"和"箱"两条指向同一件事的项，反而让人以为选错了。
- 单位列表来自 `App.jsx` 的 `unitOptionsFor()` → `lib/salesUnits.buildUnitOptions()`：
  **基础单位恒在第一位**，辅助单位按 factor 升序，**已停用和 factor<2 的脏数据被剔除**
  （后端 `_resolve_unit_factor` 对这两类都是 400，放出来只会让用户选一个必然失败的项）。
- 换单位会带出该单位自己的价格（`purchasePrice` / `salePrice`）；辅助单位没单独定价时
  **保留原值，绝不静默改成 0**。

> 网格也跟着改了：`[data-doc-form] .form-row.four-col` / `.three-col` 在 `styles.css` 末段
> 重写成 5 列 / 4 列。类名没动 —— `.form-row.three-col` 还被另外 10 个页面用着。

**补丁 F —— 商品选择改用 `SearchSelect`（2026-10-17 第三批，原第 1017–1022 行）**

原来（生成器原样，260+ 商品时要一路滚）：

```jsx
<label>
  商品
  <select value={row.product_id} onChange={handleInboundItemChange(index, 'product_id')}>
    <option value="">请选择商品</option>
    {products.map((item) => (
      <option key={item.id} value={item.id}>{item.name}</option>
    ))}
  </select>
  {renderStockHint(row.product_id)}
</label>
```

改成：

```jsx
<label>
  商品
  <SearchSelect
    options={products}
    value={String(row.product_id ?? '')}
    onChange={handleInboundItemChange(index, 'product_id')}
    placeholder="搜索商品名称 / SKU / 助记码"
  />
  {renderStockHint(row.product_id)}
</label>
```

锚点：整段旧 `<select value={row.product_id} …>` 到它自己的 `</select>`（每个文件命中 1 次）。

三处不能想当然的地方：

- `value` 必须 `String(row.product_id ?? '')`。`SearchSelect` 内部按**字符串**比 key
  （`String(getOptionValue(item)) === currentKey`），传 `null`/`number` 会让"已选中"
  判定失效 —— 下拉里看不出当前选了谁，但功能不报错。
- `onChange` 这里**直接把 `handler(index,'product_id')` 传进去**，不要包一层
  `(e) => …`。`App.jsx` 的 `makeOrderItemHandler` 已经用 `readChangeValue()`
  兼容"事件对象"和"原始值"两种入参，所以 `SearchSelect` 回调的 `(nextId, option)`
  里第一个参数（字符串 id）能直接被消费；包一层 `(e)=>handler(e)` 反而会把 id 丢掉。
- **不加 `allowClear={false}`**：明细行清空商品正是要走 `onChange('')`，
  让 handler 顺手把 `unit` / `unit_price` 复位（和原来 `<select>` 选"请选择商品"等价）。

### 3.2 商品档案页 · 已被「薄壳」方案取代（2026-10-17 第二批）

> ⚠️ 本条是**历史记录**。`ProductsPage.jsx` 现在由 `scripts/patch_products_board.py`
> 整体压回薄壳（16 行），`resolveImageSrc` 的 import 已随缩略图逻辑搬进
> `components/products/ProductsBoard.jsx`，不再属于"页面级补丁"。
> 重抽后只需 `python scripts/patch_products_board.py --apply`。

原来要补的内容（已搬家，留档）：`import { resolveImageSrc } from '../lib/productImage';`
——丢了的表现：商品列表缩略图不再走「后端相对路径 → 可访问 URL」的解析，图片空白。

### 3.3 客户 / 供应商档案页 · 整页薄壳（2026-10-17 第三步-A）

`CustomersPage.jsx` / `SuppliersPage.jsx` 各 1035 行生成原文 → 由
`scripts/patch_partners_pages.py` 整体压回约 33 行薄壳（幂等，`--apply` / `--check`）。
整页 UI 在 `components/partners/PartnersBoard.jsx`，弹窗在
`components/partners/PartnerModal.jsx`（App.jsx 里两段内联弹窗已换成 `<PartnerModal/>`，
该替换由 `_ui_kit_step3/rewrite_app_partner_modals.py` 完成，一次性、不需要重跑）。

薄壳从 ctx 里取 6 个值传给组件：`rows / search / onSearch / focus / onAdd / onDelete`。
丢了的表现：两页退回「单栏 data-table + 手写空态」，左侧分组树消失、表格不再 sticky。

### 3.4 已知不带页面级补丁的生成页

`MenusPage.jsx` 及其余页面都**没有**页面内 import —— 它们的 JSX 全部来自 `App.jsx`，
组件（`MenuTreeEditor`、`ProductCategoryTree`、`ProductEditModal`）是通过 `ctx` 注入的。
所以这些页面重抽是安全的（前提是 `App.jsx` 里那块没被改）。

### 3.5 商品期初库存页 · 直接改、不进补丁脚本（2026-10-17 第四批）

`pages/OpeningStockPage.jsx` 做过一处**直接改**：商品选择从原生 `<select>` 换成
`SearchSelect`（并加了它的 import）。

**为什么不像其余四页那样进 `patch_doc_forms.py`**：
`extract_pages.py` 只会抽取**当前 `App.jsx` 里存在的** `{selectedTab === 'xxx' && (…)}` 块，
而 `App.jsx` 里已经**没有** `selectedTab === 'opening-stock'` 这个块了
（只剩 `{selectedTab === 'opening-stock' && <OpeningStockPage ctx={appCtx} />}` 这种挂载，
搜 `openingDraft.product_id` 在 `App.jsx` 里 0 命中）。既然生成器不会再产出这一页，
也就不存在"重抽即丢"的问题 —— 往脚本里加一条反而会让 `--check` 永久报缺 1 处。

⚠️ 如果哪天真把这个块重新搬回 `App.jsx`（或改造生成器去抽它），**必须同时**
把这条改动登记进 `scripts/patch_doc_forms.py`，否则会被静默覆盖回 `<select>`。

---

## 4. 维护约定

1. **以后任何"直接改生成物"的改动，必须同时**：
   - 在 `scripts/patch_doc_forms.py` 的 `SPECS`（或 `IMPORT_ONLY`）里加一条；
   - 在本文档第 3 节登记，写清锚点（不要只写行号）。
2. **新页面的第一选择不是补丁，而是别改生成物**：能通过 `ctx`（改 `App.jsx`）、
   独立组件、或纯 CSS 实现，就不要在 `pages/*.jsx` 上动手。
   本轮的 `data-doc-form` 其实也可以走 ctx，但属性写在 `<form>` 上更直观，
   且补丁成本只有一条替换语句，所以选择了补丁 + 清单 + 脚本。
3. 跑完 `extract_pages.py` 后**先跑 `--check` 再 `npm run build`**，
   否则会得到一份"能构建、但样式和校验都静默回退"的产物。
4. **`management-grid` → `ResizableLayout`（2026-10-17 第五批）也受重抽影响**：
   `python scripts/wrap_resizable_layout.py --apply` 必须跟着跑一次。
   它按 `<div` / `</div>` 配平成对替换（35 处），幂等；漏跑的后果是
   该页拖拽手柄静默消失，**但构建照样成功、页面也不报错**。
5. **`ProductsPage.jsx` 里的 `storageKey="erp:mgrid:products"` 也会被重抽冲掉**
   （商品页左栏是类别树，默认 264px，必须跟全站用不同的键）。重抽后要补回，
   否则用户在某页把左栏拖到 600px，回到商品页类别树会被撑成 600px。
   改完记得 bump `frontend/public/sw.js` 的 `CACHE_VERSION`。
6. **`ProductsPage.jsx` 已降级为薄壳（2026-10-17 第二步 UI 重构）**：整页 UI 搬进了
   `components/products/ProductsBoard.jsx`（ErpCard × 2 + ErpTable + EmptyState）。
   重抽后执行 `python scripts/patch_products_board.py --apply` 压回一行
   `<ProductsBoard ctx={ctx} />`（整体重写、天然幂等，`--check` 给构建前用）。
   历史手工修改 ①分类树 ②图片缩略图 ③本次重构 的内容全部在 Board 里，页面壳不再携带。

---

## 5. 相关文件索引

| 文件 | 作用 |
|---|---|
| `scripts/extract_pages.py` | 生成器（会用 App.jsx 覆盖 `pages/*.jsx`） |
| `scripts/patch_doc_forms.py` | 本清单的自动执行器（幂等，支持 `--apply` / `--check`） |
| `frontend/src/lib/orderLines.js` | 空行/半填判定（`isBlankItemRow` / `itemRowError` / `inspectItemRows`） |
| `frontend/src/components/search-select/` | 可搜索下拉 `SearchSelect`（纯 JS、本地 filter、无 UI 库） |
| `frontend/src/components/resizable-layout/` | 左右两栏拖拽 `ResizableLayout`（Pointer Events、localStorage） |
| `scripts/wrap_resizable_layout.py` | 把 `management-grid` 成对替换成 `ResizableLayout`（幂等） |
| `scripts/patch_products_board.py` | 把 `ProductsPage.jsx` 压回薄壳（整体重写，幂等） |
| `scripts/patch_partners_pages.py` | 把客户/供应商档案页压回薄壳（整体重写，幂等） |
| `frontend/src/components/ui/` | UI 基础组件库（ErpCard / ErpTable / ErpForm / ErpTree / Skeleton / EmptyState） |
| `frontend/src/components/products/ProductsBoard.jsx` | 商品档案页整页 UI（第二步示范重构） |
| `frontend/src/components/docs/PurchaseInboundBoard.jsx` | 采购入库整页 UI（第三步-B 第一家） |
| `frontend/src/components/docs/SalesOutboundBoard.jsx` | 销售出库整页 UI（第三步-B 第二家；多单位换算链路原样保留，行内新增纯展示的 `×N` / 折合小字，开关 `SHOW_UNIT_CONVERSION`） |
| `_ui_kit_step3/verify-outbound.mjs` | 销售出库真浏览器验证（65 项，含提交载荷拦截断言「只发 unit 不发 unit_factor」） |
| `frontend/src/components/docs/OrderBoard.jsx` | 采购订单/销售订单共用整页 UI（第三步-B 第三、四家；「转入库单/转开单」按钮、已转单灰标、防双击忙碌态都在这里） |
| `_ui_kit_step3/verify-orders.mjs` | 订单两页真浏览器验证（85 项；自动造/回收临时订单，含已转单行不可转不可删断言） |
| `frontend/src/components/partners/` | 客户/供应商档案整页 UI + 弹窗 + 页面样式（第三步-A） |
| `frontend/src/lib/partnerGroup.js` | 客户/供应商分组树纯逻辑（buildPartnerTree / filterPartnersByGroup，13 单测） |
| `_ui_kit_step1/` `/_ui_kit_step2/` `/_ui_kit_step3/` | 各步交付的 README、补丁脚本与真浏览器验证 |
| `_search_select_step/verify/run.mjs` | SearchSelect 的 jsdom 验证台（25 项断言 + 反证记录） |
| `_resizable_layout_step/verify/run.mjs` | ResizableLayout 的 jsdom 验证台（23 项断言 + 反证记录） |
| `_resizable_layout_step/verify/browser.mjs` | 真 Chromium 拖拽验证（16 项：3 列/手柄/拖动/边界钳制/持久化） |
| `_resizable_layout_step/verify/browser-pages.mjs` | 真 Chromium 8 页面巡检（24 项：每页拖 80px + 双击复位） |
| `frontend/src/styles.css`（末段） | `[data-doc-form] …` 单据表单样式块 |
| `frontend/src/App.jsx` | 两个提交工厂（`makeSubmitStockDoc` / `makeSubmitOrder`）里的提交前体检 |
