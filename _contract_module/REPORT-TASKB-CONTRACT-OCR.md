# 任务 B 交付报告：合同原件 OCR 识别接入

> 2026-10-19 · 承接任务 A（财务红冲，已验收）之后交付
> 交付纪律：验证全绿 + 反证命中 + 测试数据清零 + 快照 + 使用说明

---

## 一、交付内容

### 后端（2 个文件）

| 文件 | 改动 |
| --- | --- |
| `app/services/contract_ocr.py`（新建，LF） | OCR 引擎封装：PDF 文本层优先（≥20 个中文字符直接用）→ 扫描件逐页渲染 PNG（zoom=3 ≈ 300 DPI）→ 图片直接 OCR，复用发票模块已验证的 rapidocr→paddle 链路（惰性 import，不复制引擎代码）。字段提取"宁可漏、不可错"：金额只认带"金额/总价/合计"字样的，裸数字绝不认（页码、电话都会撞上）；往来对象按方向分组（销售认甲方/需方/买方，采购认乙方/供方/卖方）；明细行**双形态**解析（一行四列 + 表格逐单元格四行一组），全角逗号归一。上限 10 页。 |
| `app/api/v1/routes/erp_sales.py`（CRLF，2098 行） | 抽出 `_save_contract_ocr()`（run / write-back 共用唯一落库口）；**新增 `POST /contracts/{id}/ocr`**：无原件 409、原件丢失 404、不支持的格式 400（Word 提示转 PDF）、引擎崩了也留痕（status=failed + 502）；成功按行数落 `parsed`/`failed`，返回字段候选 + 明细 + `provider/engine/page_count/truncated`。 |

### 前端（2 个文件）

| 文件 | 改动 |
| --- | --- |
| `ContractsLedger.jsx`（CRLF，1267 行） | 详情 OCR 面板：`[data-ocr-start]` 开始识别（未传原件 disabled+title 提示）→ 骨架屏扫光 `[data-ocr-running]` → 字段 chips `[data-ocr-fields]` + **识别 vs 合同对照表** `[data-ocr-diff]`（相同绿/不同红）+ 原始 JSON 折叠面板 → **一键回填表单** `[data-ocr-apply]`（只填新表单，绝不直接改已保存合同）→ **确认无误** `[data-ocr-review]`（`confirm_empty: true`，reviewed 后按钮变「已核对」并禁用）。 |
| `contractsLedger.css`（CRLF） | 追加 `.cledger__ocr-error/-fields/-field/-diff/-actions`（is-same 绿 / is-diff 红）。 |

### 本轮追加修复（验证台揪出的真实 UX 缺口）

- **商品档案匹配**：`applyOcrToForm` 现按名称归一后**精确匹配**商品档案——命中带 `product_id`（触发器直接显示档案名），不命中留空。
- **`displayValue` 兜底**：对方单位与商品两个 `ErpSearchSelect` 加 `displayValue`——未匹配档案时 OCR 识别名照样**可见**（否则回填的明细在表单里"看不见"，C6d/C7b 两红揪出）。
- `frontend/public/sw.js` → **`erp-pwa-v44`**。

### 使用说明（新规范首次落地）

- `docs/使用说明_合同OCR识别.md`（入口 / 操作步骤 / 业务规则 / 防呆提示 / 状态流转图）
- `docs/使用说明_财务红冲.md`（追溯补齐任务 A 的合规文档）

---

## 二、验证结果

### 接口层 `verify_contract_ocr_api.py` — **21/21 全绿**

真实 rapidocr 引擎 3.0s 识别出编号 / 标题 / 甲方 / 金额 1,234,500 / 签订日期 / 付款条款 / 2 行明细；状态机（PATCH 想直接置 reviewed 被 400 拦；空 review 无 confirm_empty 被 400 拦且状态保持 parsed）；confirm_empty 语义（核对不改业务字段）；已 reviewed 可重新识别且结果稳定。

### 界面层 `verify_contract_ocr_ui.mjs` — **22/22 全绿**（真 Chrome）

C0 登录+造数+上传 → C1 按钮可点 → C2 骨架屏扫光+状态徽标「已识别待核对」 → C3 字段 chips（含编号与金额） → C4 对照表 → C5 原始 JSON 面板 → C6 一键回填（标题/对方档案命中/高压柜+数量3 可见） → C7 未匹配档案给提示且**不猜档案**（第二份合同甲方写不存在的名字） → C8 确认无误→「已人工核对」+按钮禁用 → C9 bundle=dist 本次构建、全程零 JS 异常。

> 排障记录：首跑 `.cledger` 不出现——根因是**侧边栏分组默认收起**，「合同台账」`.nav-item` 根本不存在（先例 `verify_reverse_ui.mjs`：先点组标题展开）。修脚本后 15/18 → 补 `displayValue` + 重新打开详情（`applyOcrToForm` 会 `closeDetail`）+ 等按钮脱离「提交中…」→ 22/22。

### 反证（break → 红 → restore → 绿，PROBE 归零）

| 反证 | break 点 | 结果 |
| --- | --- | --- |
| 金额提取 | `_RE_AMOUNT` 改成只认不存在的字样 | **仅 O4d 红**（金额=None），其余 20 项绿 → 精确命中 |
| confirm_empty 守卫 | `if not applied and not payload.get("confirm_empty")` → `if False` | 首跑全绿 → **暴露断言空缺** → 补 O7b/O7c → 复跑 **O7b(HTTP 200 应 400) + O7c(被静默置 reviewed) 双红** → 还原后 21/21 |

### 回归

- 红冲接口台 `verify_reverse_api.py` **27/27**（确认 `erp_sales.py` 改动无破坏）
- `npm run build` 通过；产物哈希断言（C9a）绿

---

## 三、清理与快照

- `cleanup_reverse.py --apply`：凭证分录 18 / 凭证 9 / 流水 9 / 销售单 3 / 采购单 1 / 客户供应商各 1，残留 0、孤儿红字行 0
- `cleanup_contract_ocr.py --apply`（新建）：原件文件 12 / 合同明细 24 / 合同 13 / 客户 11，残留客户 0、合同 0
- 孤儿体检：孤儿凭证 0、孤儿合同明细 0；流水 #12093 为 10-17 销售退货冲减（`related_type=sales_return`），合法记录非孤儿
- 快照 `backup/20261019_taskB_contract_ocr/`（11 文件，含两份 docs 与验证/清理/反证脚本）

---

## 四、部署提醒（重要）

`desktop_app.py` **无 `--reload`**：请重启「启动ERP.bat」后使用，否则新增的 `POST /contracts/{id}/ocr` 路由是 404。前端 dist 已即时生效（v44）。

---

## 五、遗留 / 后续可选

- 404 友好提示：红冲前端已有"请重启「启动ERP.bat」"引导，合同 OCR 的 startOcr 错误分支目前直接显示后端 detail（404 时文案不够友好）——建议下轮顺手对齐。
- 早先排队未做：菜单「开单管理」→「现货开单」；发票页「关联客户」ErpSearchSelect（12 张存量发票待认领）；对账单 generate 四断点；批 3 下拉扫盲剩 35 处。
- App.jsx 拆分遗留的 7 条过期断言（用户明确"现在不修"）。
