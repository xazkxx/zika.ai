# 第 13 批 · 第三阶段（二）第一步：合同台账页面

> 日期：2026-10-18　交付：`合同台账` 页面（进/出 Tab + ErpTable + ErpSearchSelect + 附件 + OCR 占位 + 导出 Excel）
> 快照：`_contract_module/backup/20261018_frontend_step1/`（本次改动的 7 个文件）

---

## 1. 先说一个必须讲清的决定：为什么没改 `ContractsPage.jsx`

`pages/ContractsPage.jsx` 确实存在（1378 行），但它是 `scripts/extract_pages.py`
从 `App.jsx` 里**原样抽出来的 JSX 片段**：文件开头就是 300 多行 `ctx` 解构
（`contractForm` / `contracts` / `addContractItem` / `contractToOrder` …），
它自己不持有任何状态，所有逻辑都在 App.jsx 里。

要在这上面加「方向 Tab + 导出 + 原件 + OCR」，等于：
1. 改 App.jsx 里合同建单那条链路（还挂着转单、打印、强制删除）；
2. 一旦有人重跑 `extract_pages.py`，手改的 JSX 会被**整段覆盖**。

所以按项目既定规矩 **「不动核心逻辑，先写独立组件」**：

| | 老页面「购销合同」 | 新页面「合同台账」 |
|---|---|---|
| 文件 | `pages/ContractsPage.jsx`（ctx 驱动） | `components/contracts/ContractsLedger.jsx`（自包含） |
| 定位 | 逐条填 A2 条款（20+ 条）、转单 | 看 / 筛 / 导出 / 挂原件 / 看识别结果 |
| 数据 | App.jsx 传下来的 `contracts` | 自己 fetch（token 从 localStorage 取） |
| 状态 | App.jsx 的 useState | 组件内部 |

两个页面并存，互不影响。老页面**一行没动**。

---

## 2. 交付内容

### 2.1 新增文件（3 个）

| 文件 | 行数 | 作用 |
|---|---|---|
| `frontend/src/lib/contractsLedger.js` | 244 | 纯函数：Tab 定义、金额换算、表单校验、建单载荷、文件名解析。**零 React 依赖**，可被 node 直接测 |
| `frontend/src/components/contracts/ContractsLedger.jsx` | 995 | 页面本体：Tab + 工具栏 + ErpTable + 新建弹窗 + 详情弹窗 + 原件 + OCR 区 |
| `frontend/src/components/contracts/contractsLedger.css` | 501 | 样式，前缀统一 `.cledger-`，只用 tokens.css 变量 |

### 2.2 挂载（App.jsx 三处，行号精确）

| 行 | 内容 |
|---|---|
| `5` | `import { Fragment, Suspense, lazy, useCallback, … } from 'react'`（加了 `lazy` / `Suspense`） |
| `28` | `const ContractsLedger = lazy(() => import('./components/contracts/ContractsLedger.jsx'));` |
| `132` | `menuGroups` 里 `{ key: 'contracts-ledger', label: '合同台账' }`（销售管理组**末尾**） |
| `10937` | 分发区 `{selectedTab === 'contracts-ledger' && (<Suspense fallback=…><ContractsLedger /></Suspense>)}` |

**为什么懒加载**：本页带着明细编辑表与 OCR 面板，压缩后 7.69 KB gzip。
静态引入会直接进首屏主包，而它只在「销售管理 → 合同台账」这一条路径上用得到
——与 `MenusPage` 里的 `MenuTreeEditor` 同一口径（那里的注释算过账：静态 +46.8KB，懒加载 +1.15KB）。

构建结果（`npm run build`）：

```
dist/assets/index-D8-OWjDH.js          2,418.85 kB │ gzip: 564.92 kB   ← 首屏主包，未增大
dist/assets/ContractsLedger-*.js          22.18 kB │ gzip:   7.69 kB   ← 独立分包
dist/assets/ContractsLedger-*.css          7.66 kB │ gzip:   1.71 kB
```

### 2.3 后端配套（两处，缺了菜单点不到）

| 文件:行 | 内容 |
|---|---|
| `app/core/permissions.py:65` | `PERMISSION_CATALOG` 销售管理组末尾加 `{"key": "contracts-ledger", "label": "合同台账"}` |
| `app/models/role.py:82` | `sales` 角色的菜单表加 `"contracts-ledger"`（与 `contracts` 同口径：能看购销合同的人就能看台账） |

> ⚠️ **必须追加在组末**：`default_menu_specs()` 用 `items 下标 × 10` 当 `sort_order`，
> 插中间会与既有行撞号；而 `_backfill_builtin_menus` **只补不改不重编号**。
>
> 实测回填结果（public.menus）：
> ```
> 3002  购销合同          contracts           50
> 3003  销售对账单        sales-statement     60
> 3004  销售出库（多单位）sales-units         70
> 3041  合同台账          contracts-ledger    80   ← 新回填，无撞号
> ```
>
> 重启一次服务即自动补齐（`ensure_default_menus` → `_backfill_builtin_menus`），**不需要 `POST /menus/reset`**。

### 2.4 缓存版本

`frontend/public/sw.js`：`CACHE_VERSION` `erp-pwa-v33` → **`erp-pwa-v34`**（发版必 bump，已核验 dist/sw.js 内是 v34）。

---

## 3. 页面功能对照你提的六条

| 你的要求 | 落地方式 |
|---|---|
| **路由与布局**：左侧列表 + 右侧详情/表单 | 列表占满主区（ErpTable，自动横滚 + 操作列右吸附）；详情走弹窗（`.modal-card.modal-wide`），不挤占列表。理由：合同字段多，右侧固定栏会把表格压到 4 列 |
| **必须用 ErpTable / ErpSearchSelect** | 列表 = `<ErpTable />`（含 `loading` / 空态 / 行键盘可达）；对方单位、商品明细全部 `<ErpSearchSelect />`，且都显式写 `getOptionValue={String(item.id)}` |
| **Tab 切进/出，请求带 direction** | 两个 Tab 直接以 `direction=in/out` 请求 `/contracts?direction=…&keyword=…`；列标题跟着变「供应商 / 客户」，新增按钮变「新增采购合同 / 新增销售合同」 |
| **新增合同 + 上传文件（PDF/Word/图片）** | 弹窗内可选文件；**先建合同再传原件**（原件接口要 contract id）。上传失败**不废单**，提示"可在详情里重新上传"。`accept` 与大小上限从 `/contracts/meta` 读，不写死 |
| **OCR 展示区（骨架屏/占位，留调用点）** | 新建弹窗与详情弹窗都有 OCR 区：3 条扫光骨架屏 + 状态徽标 + 原始 JSON 折叠区。调用点 `submitOcrResult(contractId, payload)` 已写好（`PATCH /contracts/{id}/ocr`）；「开始识别」按钮**故意不写假数据**，只提示接口已就绪 —— 塞假 JSON 会把状态卡在"已识别待核对"永远没人核 |
| **导出 Excel** | 列表顶部「导出 Excel」→ `GET /exports/contracts?direction=<当前 Tab>`，文件名从 `Content-Disposition` 的 RFC5987 段解码（否则中文名会变下划线） |

另外顺手做了（都在弹窗里）：详情查看、合同 PDF 打印（走 `/print/contract/{id}` 的 JSON 通道）、明细行增删与金额实时计算、只剩一行时删除按钮禁用。

---

## 4. 验证

### 4.1 构建

`npm run build` 通过（Vite 5.4.21 / 200 modules / 7.49s）。首屏主包 2,418.85 kB（gzip 564.92）**与改动前持平**。

### 4.2 真浏览器 E2E：`_contract_module/verify_frontend_step1.mjs` **39/39**

不是 jsdom——**真 Chrome**（puppeteer-core + chrome-155），因为本次要验的正是
"Grid/Flex 布局 + Portal 下拉浮层 + 弹窗"这些 jsdom 测不到的东西。

断言链（每条都读真实 DOM 文本，不看"有没有报错"）：

- **L1–L3** 登录拿 token；**现造**一条采购合同（不靠种子数据，换账套也不会假红）
- **F1–F4** 应用外壳 → 侧边栏有「销售管理」→ 真有「合同台账」菜单项（从而证明后端回填生效）→ 点击后 `.cledger` 挂载
- **F5–F10** 标题 / 2 个 Tab / Tab 文案含进+出 / 默认选中「销售合同（出）」/ 导出按钮 / 新增按钮
- **F11–F13** 用了 ErpTable / 表头含「合同编号」/ 销售方向下往来列是「客户」
- **F14–F18** 切到采购 Tab → 列标题变「供应商」→ 列表**出现刚建的合同**（证明 direction 过滤生效）→ 金额显示 `¥2,468.10`（千分位）→ 按钮变「新增采购合同」
- **F19–F20** 点导出 → 真发出 `/api/v1/exports/contracts?direction=in`
- **F21–F26** 弹窗标题 / 2 个 ErpSearchSelect / 明细默认 1 行 / 删除禁用 / OCR 骨架 3 条 / 文案含 `/contracts/:id/ocr`
- **F27–F28** 加一行 → 2 行；删一行 → 1 行
- **F29–F30** **空表单提交被拦**并给中文提示（这条最关键：ErpSearchSelect 的触发器是 `div[role=combobox]`，原生 `required` 已彻底失效）
- **F31–F34** 取消关闭 / 点行开详情 / 详情金额 / OCR 面板状态「未识别」
- **F35** 控制台零 JS 异常（只过滤 React 的 act/DevTools 噪音，**没有** `console.error = () => {}`）
- **Z** 清理残留 = 0

### 4.3 反证 2 组（改坏 → 重新构建 → 变红 → 还原 → 重建）

`_contract_module/probe_frontend_step1.py`

| 反证 | 改了什么 | 结果 |
|---|---|---|
| A | 采购 Tab 的 `partyLabel: '供应商'` → `'客户'` | **37/39**，F15 红（表头变「客户」），F30 也跟着红（错误文案变成"请选择客户"） |
| B | 去掉"对方单位必选"校验 | **38/39**，F30 红（提示退化成"至少要有一行合同明细"） |

> ⚠️ 这个脚本的**关键**是它每次都重新 `npm run build`。
> 只改源码不构建，8011 托的还是旧 `dist`，反证会"全绿"——等于什么都没验到。

### 4.4 菜单一致性单测

```
pytest tests/test_system_users.py -k permission_catalog_matches_frontend_menu  → 1 passed
```

这条把 `App.jsx` 的 `menuGroups` 当数据源，与后端 `PERMISSION_CATALOG`
**逐项比对（含顺序）**。两边漂移是静默故障（角色勾了菜单但界面没有），所以必须绿。

---

## 5. 已知限制（你验收时可能会问的）

1. **「合同台账」排在「销售出库（多单位）」之后**，不是紧挨「购销合同」。
   原因见 §2.3（组末追加避免 `sort_order` 撞号，且回填只补不改不重编号）。
   想挪位置：在「系统管理 → 菜单管理」里拖，或直接改 `menus.sort_order`。
2. **已有账套里的 `sales` / `manager` 角色不会自动获得这个菜单**
   （`ensure_default_roles` 只补不覆盖）。`admin` 是 `all: true`，所以你现在能看到。
   要给销售员看，去「角色权限」勾一下即可。代码侧（新装库）已经写进 `BUILTIN_ROLES`。
3. **OCR 只有调用点，没有引擎**。「开始识别」只弹提示，不写库。
   接引擎时只需实现 `ContractsLedger.jsx` 里的 `submitOcrResult`。
4. **台账页建单只覆盖核心字段**：标题 / 对方单位 / 签订日期 / 有效期 / 税率 / 含税 / 付款条款 / 备注 / 明细 / 原件。
   A2 那 20 多条细则条款仍在「购销合同」页填——那边才是逐条拟合同的地方。
5. **导出是"当前方向全量"**，不是"只导搜出来的"：后端 `/exports/contracts` 只接受
   `direction / from_date / to_date / status`，没有 `keyword`。要按关键字导，得先给后端加参数（下一步可做）。
6. **台账页不做编辑/删除**：避免与老页的删除逻辑（含强制删除、级联提示）打架。删除仍在「购销合同」页。
7. **首次进页面多一次 chunk 下载**（7.69 KB gzip），换来首屏不变。

---

## 6. 你需要做的一步

**双击 `启动ERP.bat` 重启**。原因：8010 上的进程是 17:18 起的，比
`erp_export.py`（17:25）与 `erp_print.py`（17:30）都老 —— 不重启的话：

- 侧边栏的「合同台账」会出现（菜单行已经在数据库里，是 8011 那次启动补的）；
- 但点「导出 Excel」会 404（旧进程没有 `/exports/contracts`）。

重启后缓存版本已是 `erp-pwa-v34`，浏览器会自动清掉旧 SW 缓存，不需要手动强刷。

---

## 7. 回滚

```powershell
cd E:\AI\ERP软件
# 1) 删掉新增的三个前端文件
Remove-Item frontend\src\components\contracts -Recurse -Force
Remove-Item frontend\src\lib\contractsLedger.js -Force

# 2) App.jsx 撤三处（行号见 §2.2）：第 5 行的 lazy/Suspense、第 28 行的 lazy const、
#    第 132 行的 menuGroups 项、第 10937 行的分发块
# 3) permissions.py:65 与 role.py:82 各删一行
# 4) sw.js 版本号可留 v34（无害，只是多一次缓存清理）
cd frontend; npm run build
```

数据库侧：`menus` 表里已回填的 `contracts-ledger` 行可以留着（`_backfill` 只补不删，
下次启动若清单里没有它也不会被删）。想彻底清干净就 `DELETE FROM menus WHERE page_key='contracts-ledger'`。

---

## 8. 下一步（等你验收）

**第三步前先说清顺序**：你原计划是「第二步：客户文件抽屉」。它依赖
`/customers/{id}/files` 那 8 个接口（第二阶段已完成），可以直接开；
建议把抽屉挂在「客户档案」列表的行操作里，与这次的台账页同一套自包含组件写法。

---
---

# 第二批：明细行布局修复 + 客户文件抽屉

> 2026-10-18 追加。上一批（合同台账）已验收通过，本批解决两件事：
> ① 你截图反馈的「商品搜索框被挤成方块」；② 「客户档案」的文件抽屉。

## 9. 明细行布局：两个根因，不是一个

你给的修法（`table-layout: fixed` + 指定列宽 + 弹窗加宽）方向完全正确，
但实测发现**即使全照做也修不好**，因为真正的根因有两个，而且会互相掩盖。

用 `_contract_module/measure_items.mjs`（真 Chrome 量 `getBoundingClientRect`）
在修之前量到的数字：

| 量点 | 修前 | 修后 |
| --- | --- | --- |
| 弹窗卡片宽 | **640** | **1040** |
| 卡片的 `max-width` | `640px` | `1080px` |
| 明细表宽 | 598 | 998 |
| 商品列 | **38** | **462** |
| 规格 / 单位 / 数量 / 单价 / 金额 | 130 / 74 / … | 88 / 80 / 100 / 100 / 120 |
| 商品搜索框（`.ssel`） | **26** | **450** |

### 根因 1：`.modal-wide` 只写了 `width`，被基础样式钳住

`styles.css` 里 `.modal-card { max-width: 640px }`。上一版 `.modal-wide` 只加了
`width: min(1040px, 94vw)` —— **`max-width` 优先于 `width`**，所以卡片实际就是 640px，
表格只有 598px。修法是把两者**双写**：

```css
.cledger__modal { width: min(1080px, 94vw); max-width: min(1080px, 94vw); }
```

### 根因 2：`table-layout: fixed` 下 `min-width` 完全无效

上一版把宽度写在 `<th>` 上：`<th style={{ minWidth: 220 }}>商品 *</th>`。
**fixed 布局只认第一行（`<col>` 或 `<th>`）的 `width`，`min-width` 直接被忽略** ——
于是商品列没有任何宽度依据，只能分到"扣掉其他列后剩下的"38px。

修法是用 `<colgroup>` 显式定宽，且商品列写 `auto`（把余量全给它）：

```jsx
<colgroup>
  <col />                        {/* 商品：余量全给它，实测 ≥250 */}
  <col style={{ width: 88 }} />  {/* 规格 */}
  <col style={{ width: 80 }} />  {/* 单位 */}
  <col style={{ width: 100 }} /> {/* 数量 */}
  <col style={{ width: 100 }} /> {/* 单价 */}
  <col style={{ width: 120 }} /> {/* 金额 */}
  <col style={{ width: 48 }} />  {/* 操作 */}
</colgroup>
```

### 附带两处（你没提但会一起犯的）

1. **容器要能横滚**：`table-layout: fixed` 不换行，内容只会溢出单元格。
   加 `.cledger__items-wrap { overflow-x: auto }` —— 宁可左右滚，也不把输入框挤成方块。
2. **触发器高度对齐 input**：`.ssel-trigger` 自带 `min-height: 38px`，而同行 input 是 30px，
   一行明细会被撑高一圈。明细表内单独压到 30px。

## 10. 客户文件抽屉

### 10.1 为什么挂在 `PartnersBoard` 里，而不是 App.jsx

`PartnersBoard` 的职责边界写着"只吃 props、不 import App.jsx、不读 ctx"。
抽屉只需要「客户 id + 名字」，两样都在 `row` 上；文件接口又是自包含的
（token 从 `localStorage` 取，与 `partnerTreeApi` 同一套约定）。

于是这一批**没有动 App.jsx 一行**：

| 文件 | 改了什么 |
| --- | --- |
| `components/partners/PartnersBoard.jsx` | `lazy` 引入抽屉；`filesFor` state；操作列加「📁 文件」；列宽 152 → 208 |
| `components/partners/CustomerFilesDrawer.jsx` | 新增（约 500 行） |
| `components/partners/customerFilesDrawer.css` | 新增（约 570 行，`.pcfd-` 前缀） |
| `lib/customerFiles.js` | 新增纯函数层（分类/Tab/大小/时间/文件名/预检/base64） |
| `public/sw.js` | `CACHE_VERSION` v34 → **v35** |

供应商页零改动：`canFiles = kind === 'customer'`，供应商那页连按钮都不渲染
（E2E 的 F7 专门断言这一点，且同时断言"编辑"按钮在，防止页面没加载完时假绿）。

### 10.2 ⭐ 下载撞上的坑：浏览器会把 PDF 从 `fetch()` 手里抢走

第一版按常规写法：`fetch(url)` → `response.blob()` → 存盘。实测**下下来是 0 字节**，
而且 `response.ok` 还是 `true`。在页面里打点看到的是：

```
{ "status": 204, "bytes": 0, "len": null, "type": null, "controlled": true }
```

同一个 URL 用 Node `fetch` 是 `200 + 正确字节`。也就是说**只有浏览器里坏**。

根因在仓库里早有人记过 —— `app/api/v1/routes/erp_print.py:106`：

> Edge 的内置 PDF 阅读器会把 application/pdf 的响应从 JS 手里接管走，
> 于是 `fetch()` 拿到的是一个空响应（实测状态 204、body 为空），
> 而 `response.ok` 对 2xx 依然为真 —— 前端会静默下载一个 0 字节的空 PDF。

后端为此专门留了 `_wants_json(request)` 通道。本抽屉改成：

```js
fetch(url, { headers: { ...authHeaders(), Accept: 'application/json' } })
// → { filename, content_type, content_base64, size }
```

`filename` 是原文，**不经过 Content-Disposition**，中文天然不乱码。
二进制通道保留成兜底（老后端不认 Accept 时按 `filename*` 解析）。

这条不是"顺手改的"，是这轮唯一一个真 bug，反证 A 组把 `Accept` 去掉后
`F40b 浏览器真的把文件存下来了 —— 目录：空`、`F40d 0 字节` 立刻变红。

### 10.3 下载断言怎么做的（这条值得留着）

只看"提示文案说已开始下载"是**假绿** —— 文案是前端自己写的。
所以 E2E 用 CDP 把浏览器下载目录指到临时目录，点完下载**读磁盘上的文件名**：

```js
await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dlDir });
// …点击下载、等落盘…
check('F40c 存盘文件名 = 中文原名', savedName === '测试合同扫描件.pdf');
check('F40d 存盘文件非空', savedSize > 0);
```

同时仍然断言服务端 `Content-Disposition` 里的 `filename*=UTF-8''`（F41/F42），
保证"直接用链接/curl 下载"这条路也是对的。

### 10.4 抽屉做了哪些事

- **Tab**：全部 + 合同 / 资质 / 发票 / 对账单 / 其他，角标来自 `/files/stats`（独立接口，
  不跟着分页/搜索变）。角标没到之前显示 `…` 而不是 0 —— 0 是"确实没有"，`…` 是"还不知道"。
- **上传**：多选、真实 `input[type=file]`、可拖拽到面板。归档分类跟着当前 Tab 走；
  在「全部」下出现一排分类 chip 让你挑。整批预检（大小/空文件）不合格就整批不动，
  避免"传了 2 个第 3 个报错"的半截状态。后端按 sha256 去重，命中会提示"内容重复已跳过"。
- **列表**：名称（带 PDF/DOC/XLS/IMG 角标）+ 分类标签 + 备注 / 大小 / 上传时间 / 操作。
  后端返回 `file_exists: false` 的（磁盘上被人手工删了）显示红标「文件已丢失」并禁用下载。
- **删除**：二次确认（明确告知磁盘文件一起删），`?purge=true`。
- **交互**：ESC 关闭、点遮罩关闭、打开时锁 body 滚动、`role=dialog` + `aria-modal`。

## 11. 验证

| 套件 | 结果 |
| --- | --- |
| `verify_frontend_step1.mjs`（合同台账，含新增的 F36–F41 列宽断言） | **45 / 45** |
| `verify_frontend_step2.mjs`（文件抽屉） | **61 / 61** |
| `probe_frontend_step1.py`（4 组反证） | 全部命中预期红 |
| `probe_frontend_step2.py`（4 组反证） | 全部命中预期红 |

step1 新增的 6 条列宽断言（真像素，不是"有没有元素"）：

- F36 明细表是 fixed 布局
- F37 弹窗 ≥1000px 且 `max-width ≠ 640px`
- F38 商品列 ≥250px
- F39 其余列 88/80/100/100/120（±3）
- F40 搜索框宽度 ≥ 单元格 − 16
- F41 容器可横向滚动

反证（改坏 → 重建 → 变红 → 还原 → 重建）：

| 组 | 改坏什么 | 变红的断言 |
| --- | --- | --- |
| step1-A | 采购 Tab 的往来列标签写成"客户" | F15、F30 |
| step1-B | 去掉"对方单位必选"校验 | F30 |
| step1-C | 弹窗 `max-width` 退回 640px | F37、F38 |
| step1-D | 商品列从 `auto` 改成写死 60px | F38、F39 |
| step2-A | 下载去掉 `Accept: application/json` | F40、F40b、F40c、F40d（0 字节） |
| step2-B | `canFiles = false`（隐藏入口） | F6 |
| step2-C | 上传忽略所选分类 | F34、F35 |
| step2-D | 列表请求丢掉 `category` 参数 | F35、F36 |

`npm run build`：203 modules，主包 **2,419.33 kB**（gzip 565.10，比上批 +0.48 kB），
抽屉单独分包 10.61 kB（gzip 4.70）。

## 12. 回滚（本批）

```powershell
cd E:\AI\ERP软件
Remove-Item frontend\src\components\partners\CustomerFilesDrawer.jsx
Remove-Item frontend\src\components\partners\customerFilesDrawer.css
Remove-Item frontend\src\lib\customerFiles.js
# PartnersBoard.jsx 撤五处：lazy 引入、filesFor state、canFiles、操作列按钮、宽 208→152
# ContractsLedger.jsx / contractsLedger.css 用 _contract_module\backup\20261018_frontend_step2\ 覆盖
# sw.js 版本号可留 v35（无害，只多一次缓存清理）
cd frontend; npm run build
```

**数据库零变更**：本批没有建表、没有加列，文件表是第二阶段就有的。

## 13. 已知限制

1. 操作列从 2 个按钮变 3 个，客户列表在 ~1200px 以下会先挤「文件」再挤「编辑」
   （列宽是下限不是硬约束，`table-layout: auto` 下列会被内容撑开）。
2. 没有做「重命名 / 改分类」（后端 `PATCH /customer-files/{id}` 已就绪），
   也没做行上的文件数角标（`GET .../files/count` 已就绪）—— 本步只做你点名的四件事。
3. 抽屉一次最多渲染全部文件（不分页）。后端支持 `skip/limit`，文件过百再加。
4. `formatFileSize` / `fileNameFromDisposition` 与 `lib/contractsLedger.js` 重复了 15 行。
   刻意没动那个已验收模块；将来收口时两边一起抽到 `lib/fileUtils.js` 并双跑验证台。

---

# 第三批：增强版对账单编辑器

## 14. 交付文件

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `frontend/src/lib/statementEditor.js` | 291 | 纯函数层：格式化、行派生、合计、校验、请求拼装。**零 React 依赖**，可单测 |
| `frontend/src/lib/download.js` | 60 | 收口 `saveBlob` / `base64ToBlob` / `fileNameFromDisposition`（新模块专用，不动已验收实现） |
| `frontend/src/components/statements/StatementEditor.jsx` | ≈707 | 页面本体，自带 `authHeaders()` / `api()`，不依赖 App 内闭包 |
| `frontend/src/components/statements/statementEditor.css` | 452 | `.stmt` 前缀，全部走 `tokens.css` 变量 |
| `frontend/src/App.jsx` | 3 处 | `:32` lazy const、`:139` menuGroups 销售管理组末项、`:10951` 分发区 |
| `app/core/permissions.py` | `:66` | `PERMISSION_CATALOG` 销售管理组末加一条 |
| `app/models/role.py` | 2 处 | `sales`、`finance` 角色各加 `statements-editor` |
| `frontend/public/sw.js` | 1 行 | `CACHE_VERSION` v35 → **v36** |

**没改**：`App.jsx` 的 `visibleGroups` / 路由逻辑、`ErpTable` / `ErpSearchSelect`、`styles.css`、后端任何业务代码（第二阶段的接口全部原样复用）。

## 15. 接口对照（全部第二阶段已就绪，本批只消费）

| 前端动作 | 接口 | 备注 |
| --- | --- | --- |
| 载入下拉 + 最近对账单 | `GET /customers` · `GET /suppliers` · `GET /statements?limit=50` | 三个并发，任一失败只影响自己那一块 |
| 生成草稿 | `POST /statements/generate` | 入参 `{direction, party_id, period_start, period_end, opening_balance}` |
| 读整张单据 | `GET /statements/{id}` | `/recalc` 只回 totals，改完必须再 GET 一次 |
| 保存 | `PUT /statements/{id}` | 只送勾选行 → 服务端 `item_count` 跟着变 |
| 重算 | `POST /statements/{id}/recalc` | 回 `{totals, item_count, message}`，**不是整张单据** |
| 打印 PDF | `GET /print/statement-record/{id}` + `Accept: application/json` | 走 `_wants_json` 的 base64 通道 |
| 导出台账 | `GET /exports/statements?start&end&direction` | xlsx，走 blob 通道即可（实测落盘字节正常） |

## 16. 头部 6 张卡的口径

`headerCards()` 与后端 `compute_totals()`（`app/models/statement.py:249`）逐字对齐：

```
期初余额   = 入参 opening_balance（不进合计，永远照抄）
本期新增   = Σ contract_amount
本期已开票 = Σ invoiced_amount        ← 跟着勾选变
本期已收/付 = Σ received_amount        ← 跟着勾选变
期末应收/付 = 期初 + Σ开票 − Σ已收 − Σ预收核销
剩余未收   = Σ合同额 − Σ已收 − Σ预收核销
```

- 「已收」两字随方向变：应收对账显示**本期已收**，应付对账显示**本期已付**；「期末应收 / 期末应付」同理。
- 期末余额那张卡带 `--strong` 描边（主色），是这一页唯一的视觉重心。
- **前端只算预览，绝不把预览值提交** —— 保存后头部 10 个金额以服务端回写的快照为准。这是刻意的：`_apply_totals` 不回写 `opening_balance`，前端自己算的期初永远只是"看着对"。

## 17. 勾选语义（你点名的"逻辑联动"）

- 明细表 `selectable` + `rowKey={(row) => row.key}`；`checkedRows` 由 `selectedKeys` 过滤得出，`preview = computeTotals(checkedRows, opening)`。
- **不勾 = 不参与合计 = 不写库**。表尾合计行会写「已勾选 N 行」，保存时也只送这 N 行 —— 于是服务端的 `item_count` 就是 N。E2E 里 F26–F30 验的就是这条：取消第二行后卡片从 ¥3,468.10 掉到 ¥2,468.10，且提示"不会写入"。
- 行内两个可编辑 input：**已开票**、**已收·已付**。改完立刻重算该行的「未开票」「剩余未收」「发票状态徽标」（`deriveRow()`）。徽标三态判定里 `full` 的前提是 `contract_amount > 0` —— 否则纯收款行会被误标成"已开票"（这个坑写进注释了）。
- 金额在 state 里存**字符串**而不是 number：`''` 能表示"用户清空了"，`0` 不能。

## 18. 打印通道（本批唯一的技术陷阱）

```js
// ⚠️ 必须 Accept: application/json —— 浏览器会把 application/pdf 的响应抢走，
//    fetch 拿到 204 + 空 body 而 response.ok 仍为 true → 静默存 0 字节
const response = await fetch(`${API_BASE}${printPath(statement.id)}`, {
  headers: { Accept: 'application/json', ...authHeaders() },
});
const payload = await response.json();
saveBlob(base64ToBlob(payload.content_base64, payload.content_type || 'application/pdf'),
         payload.filename || `${statement.statement_no}.pdf`);
```

与客户文件抽屉同一条硬规则。`saveBlob` 里对 0 字节直接抛错，宁可报错也不留空文件。

## 19. 验证

| 套件 | 结果 |
| --- | --- |
| `verify_frontend_step3.mjs`（真 Chrome E2E） | **66 / 66** |
| `probe_frontend_step3.py`（4 组反证） | 全部命中预期红 |
| `pytest -k permission_catalog_matches_frontend_menu` | 1 passed（前端 menuGroups 与后端目录逐项一致） |

E2E 分段：L1–L6 造数（1 客户 + 2 合同 2,468.10 / 1,000.00 + 字典）→ F1–F12 菜单与首屏（6 张卡顺序、两方向 Tab、默认 `out`、默认账期本年年初~今天、5 个按钮、空态）→ F13–F25 选客户 + 生成草稿（2 行、全选、¥3,468.10）→ F26–F30 取消勾选联动 → F31–F37 改已开票 1000 / 已收 500（未开票 1,468.10、徽标"部分开票"、期末 ¥500.00、剩余 ¥1,968.10）→ F38–F46 保存后服务端 `item_count=1 / invoiced=1000 / received=500 / outstanding=1968.1 / receivable=500` → F47 重算 → F48–F53 **PDF 与 xlsx 落盘**（CDP `Browser.setDownloadBehavior` + 读磁盘文件名与字节数）→ F54–F56 切应付清空 → F57 控制台零异常 → Z 清理残留 0。

反证（改坏 → 重建 → 变红 → 还原 → 重建）：

| 组 | 改坏什么 | 变红的断言 |
| --- | --- | --- |
| A | 头部合计不吃勾选（`checkedRows` 换成 `rows`） | F26、F27、F28、F29 |
| B | 期末应收漏掉「已收」项 | **只有 F36**（F32 那格已收还是 0，漏项与算对同值 —— 包含式断言不足的典型，别写成两条） |
| C | 打印退回二进制通道（去掉 `Accept`） | F48（`Unexpected token '%'`）、F49（0 字节）、F50 |
| D | 保存时忽略勾选（送 `rows`） | F39、F40、F41、F44 |

`npm run build`：203 modules，主包 **2,419.67 kB**（gzip 565.21，比上批 +0.34 kB），
`StatementEditor` 单独分包 16.82 kB（gzip **6.72**），CSS 7.17 kB（gzip 1.51）。

## 20. 顺带修掉的两个真 bug（不是测试脚本的问题）

1. `ContractsLedger.loadRows` 没有"只认最后一次请求"守卫 → 进页面先发 `direction=out`，用户快速切到采购 Tab 发 `direction=in`，若前者的响应后到会覆盖 `rows` → 表现成"切了 Tab 显示空态"，且**偶发**。step1 偶发 43/45 就是它。加 `requestRef` ticket 守卫后连跑 4 次 45/45。
2. `CustomerFilesDrawer.loadList` 的搜索/切 Tab 同一模式，一并加 `listTicket`。

## 21. 回滚（本批）

```powershell
cd E:\AI\ERP软件
Remove-Item frontend\src\components\statements -Recurse
Remove-Item frontend\src\lib\statementEditor.js
Remove-Item frontend\src\lib\download.js
# App.jsx 撤三处：第 32 行的 lazy const、第 139 行的 menuGroups 项、第 10951 行的分发块
# permissions.py:66 与 role.py 各删一行
# 或者直接覆盖：_contract_module\backup\20261018_frontend_step3\App.jsx 等 8 个文件
# sw.js 版本号可留 v36（无害，只多一次缓存清理）
cd frontend; npm run build
```

**数据库零变更**：本批纯前端 + 两行菜单常量。表是第二阶段建的。

## 22. 已知限制

1. **不能改明细行数**（只能勾/不勾 + 改已开票/已收）。要加行、删行得重生成草稿 —— 后端 `PUT` 接受整份明细，但前端没做"加空行"的入口，等你确认要不要。
2. **非草稿态只读**（后端 `_assert_editable` → 409）。`void` 之后不能复用同一张单，要重新生成；作废入口本批没做。
3. 「最近对账单」只拉 50 条，没做分页/筛选（第二阶段的列表接口支持，本批按"够用"处理）。
4. PDF 模板是第二阶段定稿的 A4 版式，本批**没有**新增字段（比如把勾选状态印上去）。
5. 651 行以后是纯展示的 `tfoot` 合计，不参与 `ErpTable` 的排序/固定列（ErpTable 未支持 footer 与 fixed column 并存）。

## 23. 你需要做的一步

8010 **必须重启**（`permissions.py` / `role.py` 改了菜单，不重启侧边栏看不到「增强对账单」），然后 **Ctrl+F5**（SW 已 bump 到 v36）。

