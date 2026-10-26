# 任务 D · OCR 引擎两个 Bug 修复（2026-10-19）

> 用户报障原文：
> 「Bug 1：上传 6.5MB 的 PDF，点「开始识别」直接报错：
> `cannot access local variable '_ocr_image_bytes' where it is not associated with a value`。
> Bug 2：上传 .docx 后点识别，直接弹红字说不支持，体验太差。」

结论：**两个 Bug 都已修复，并且用用户桌面上的那份真实合同（6,823,575 字节 / 18 页 / 零文本层扫描件）
从引擎层和界面层各跑通一次，25 项 + 21 项全绿；四套旧验证台 95 项全绿；7 组反证逐一"改坏→变红→改回"。**

---

## 一、Bug 1：为什么带文本层的 PDF 测不出这个错

### 1.1 报错本身

```
UnboundLocalError: cannot access local variable '_ocr_image_bytes'
                     where it is not associated with a value
```

### 1.2 根因（不是"变量写在 if 里"，是 Python 的作用域规则）

`app/services/contract_ocr.py` 的 `extract_text()` 是一个函数，里面有三条分支：

| 分支 | 用到的引擎函数 |
| --- | --- |
| `.pdf` | `_pdf_text_layer`、`_pdf_page_pngs`、**`_ocr_image_bytes`** |
| `.png/.jpg/...` | `_ocr_image_bytes` |

修复前，`.pdf` 分支只 import 了前两个；`_ocr_image_bytes` 是在**另一个分支**（图片分支）里 import 的。

而 Python 编译期就决定了：**只要函数体内部任何位置出现 `import X` / `from ... import X`，
`X` 就是整个函数的"局部名字"**，不管那行 import 到底会不会执行。于是：

- 扫件 PDF 走到 `.pdf` 分支 → 调用 `_ocr_image_bytes(...)` → 这个名字**在本函数里从未被赋值** →
  `UnboundLocalError`（而不是 ImportError，也不是 NameError）；
- 带文本层的 PDF 在调用它**之前**就 `return` 了 → 一路顺风；
- 图片走 `.png` 分支 → 那里有 import，正常。

所以旧的 21 项接口验证台全绿，也测不出这个错 —— 它画的是 PNG。**这是"测试用例覆盖不到分支"的经典陷阱。**

### 1.3 修复

`app/services/contract_ocr.py:230-240` —— 三个函数一起 import，并留下注释钉住这个坑：

```python
if suffix == ".pdf":
    # ⚠️⚠️ 三个函数**必须一起 import**：Python 把函数体内的任何 import 都当成
    # 「局部名字绑定」，哪怕它在另一个分支里。之前这里只导入了前两个，
    # 扫描件分支却调用 `_ocr_image_bytes` → 必然抛 UnboundLocalError，
    # 而且带文本层的 PDF 提前返回了、测不出来 —— 只有真实扫描件才会踩。
    from app.api.v1.routes.erp_invoice import (
        _ocr_image_bytes,
        _pdf_page_pngs,
        _pdf_text_layer,
    )
```

### 1.4 顺带修掉的第二个隐患：大合同一次渲几十页

`_pdf_page_pngs()` 原来把 PDF **每一页**都渲成 PNG。用户那份合同 18 页，按 `zoom=3`（≈300 DPI）
每页 1.2–2 MB，一次就是 20–35 MB 常驻内存 —— 而 OCR 侧最多只认前 10 页，多渲的纯属浪费。

- `app/api/v1/routes/erp_invoice.py:492-524` 加参数 `max_pages: int | None = None`，渲染循环里到量即 `break`；
- `app/services/contract_ocr.py:246` 调用时传 `max_pages=MAX_PAGES + 1`（+1 页只用来判断"后面还有没有"，好给用户提示"已识别前 10 页"）；
- 不传 `max_pages` 的老调用方（发票二维码检测）行为完全不变（A6b 专项断言 18 页照渲 18 张）。

---

## 二、Bug 2：Word 原件改为"选文件时就拦住"

### 2.1 设计取舍

后端**仍然**对 `.doc/.docx` 返回 400（"Word 请先另存为 PDF"）——因为服务端解析 Word 是另一个坑，
而且业务上也不该让 Word 走 OCR。但**用户不该点完按钮才吃这个红字**。

所以改成两层：

| 层 | 行为 |
| --- | --- |
| 前端（新增） | 选中 `.doc/.docx/.docm/.dot/.dotx/.rtf/.wps`（或 MIME 命中）→ **不上传**、不置 `draftFile`、「开始识别」保持禁用、按钮上方弹**黄色**提示 |
| 后端（保留） | 万一绕过前端（脚本直调），仍然 400 + 中文提示，不是 500 |

### 2.2 代码位置

- `ContractsLedger.jsx:70-88` —— `isWordFile()`：后缀与 MIME 双判（有些系统给 `.docx` 的 `type` 是空串）
- `ContractsLedger.jsx:138` —— 新 state `draftWordHint`（**刻意与 `draftError` 红字分开**：选错格式不是错误）
- `ContractsLedger.jsx:375-390` —— `pickDraftFile()` 顶部拦截：设提示、清红字、清空 input 的 value（否则改完格式再选同名文件不触发 change）
- `ContractsLedger.jsx:1025-1030` —— 提示条，`data-draft-word-hint`，位置在「开始识别」按钮**上方**
- `contractsLedger.css:675-697` —— `.cledger__draft-hint`，用 `--color-warning-soft / -border / -strong`（与冲突条同一套黄色），左侧加 3px 竖条；`span` 显式 `min-width:0`，长文件名不会撑破容器
- `ContractsLedger.jsx:245` —— `resetDraft()` 里清 `draftWordHint`（关弹窗/重开不带残留）

提示文案：

> **这份原件暂时没法识别**
> 「xxx.docx」是 Word 文档，暂不支持直接识别。请在 Word 里「另存为」PDF，再回来上传。

---

## 三、真实合同暴露出的三处"认错了"

跑真实合同（不是脚本画的图）时，除了崩溃，还暴露出字段提取在真实排版上会**认错**。
按"宁可漏、不可错"的原则一并收紧 —— 认错比认不出严重得多，用户会直接信：

| 现象 | 原因 | 修复 |
| --- | --- | --- |
| 合同金额认成 **30.0** | 全文是"（1）本合同暂定含税总价：人民币（大写）贰佰陆拾壹万柒仟伍佰陆拾捌元贰分 ⏎（￥2617568.02元）" —— 阿拉伯数字在**下一行**，而旧的正则窗口只有 12 个字，于是只认出后文"暂定总价的30%"里的 30 | `contract_ocr.py:50-56` 窗口放到 60 字并允许跨行；`_looks_like_money()`（`:154`）挡掉"紧跟 %"和"不像钱"的数字；`_extract_amount()`（`:173`）先按关键字找，再退回"带 ￥ 的最大数" |
| 对方单位认成 **「需在2个工作日内出具调价确认单」** | 旧正则 `(甲方\|乙方\|…)\s*[:：]?\s*(名字)` 把冒号写成**可选**，正文里"乙方需在…""甲方有权…"全被当成"角色+名称" | `contract_ocr.py:77-85` 冒号改成**硬条件**，并允许中间一段括注（"甲方（采购方/盖章）：湖南华邦建设有限公司"）；`:96-108` 增加句子词表过滤；`:189` `_party_name_score()` 打分，取**分数最高**而不是第一个（盖章行/带公司字样 +2+2） |
| 签订日期填不进 | OCR 出来是"2026年9月16日"，去掉非数字只有 7 位（月是个位数），旧的"必须 8 位"判断失败 → 原样返回 | `contract_ocr.py:132-152` 改成按年月日三组解析 + 补零 → `2026-09-16` |

修复后，用户这份真实合同（采购方向）认出：

```json
{
  "contract_no": "XAZKKLMY20260916-01",
  "title": "克拉玛依储能项目电缆采购合同",
  "party_name": "西安寨卡信息技术有限公司",
  "total_amount": 2617568.02,
  "sign_date": "2026-09-16"
}
```

销售方向则认甲方 `湖南华邦建设有限公司` —— 方向真的起作用（A10f 专项断言）。

---

## 四、验证矩阵（本次共 148 项）

| 验证台 | 项数 | 结果 | 说明 |
| --- | --- | --- | --- |
| `verify_taskD_ocr_pdf.py`（新） | 32 | ✅ 全绿 | 引擎层 + 接口层，**用真实的 6.5MB/18 页扫描件** |
| `verify_taskD_word_guard.mjs`（新） | 21 | ✅ 全绿 | 真浏览器：Word 拦截 + 真实 PDF 界面端识别 |
| `verify_contract_draft_api.py` | 23 | ✅ 全绿 | 任务 C 回归（智能优先） |
| `verify_contract_draft_ui.mjs` | 29 | ✅ 全绿 | 任务 C 回归 |
| `verify_contract_ocr_api.py` | 21 | ✅ 全绿 | 任务 B 回归（详情页 OCR） |
| `verify_contract_ocr_ui.mjs` | 22 | ✅ 全绿 | 任务 B 回归 |

关键断言（都在新台子里，且都做了反证）：

```
A1  真实扫描件 PDF 识别不再崩溃
A2  走的是 OCR 分支（provider=ocr）
A3  页数被封顶在 MAX_PAGES=10
A4  正确标记 truncated（后面还有 8 页没认）
A6  渲染封顶生效（max_pages=11 → 恰好 11 张，不是 18 张）
A6b 不传 max_pages 仍渲染全部页（老调用方零影响）
A7/A7b 带文本层的 PDF 仍走文本层分支，编号金额都对
A8/A8b .docx 被后端明确拒绝，文案含「另存为 PDF」
A9  单张图片仍能识别（图片分支未被 import 重构改坏）
A10/A10b/A10c/A10d/A10e/A10e2/A10f 真实合同：编号 / 金额 2,617,568.02 / 对方（乙方） / 日期 / 候选只有两方 / 没有一整句话 / 方向起作用
A11 只有比例（总价的30%）时不认金额
B2  真实 PDF 一次性识别成功（HTTP 200，报错里没有 UnboundLocalError）
W2/W3/W4/W5 选 .docx：黄色提示出现、按钮仍禁用、没有红字、服务端一个字节都没收到
W7b 真实 6.5MB / 18 页扫描件在界面里识别成功
W8/W8b/W8c 界面里认出 编号 / 金额 / 对方单位
```

## 五、反证（不写反证就等于没验证）

脚本：`_contract_module/_probe_taskd.py`（`break-* / restore-* / status`）+ 前端手工一步。

| # | 故意改坏 | 结果 |
| --- | --- | --- |
| P1 | 三合一 import 退回只导两个（`PROBE-IMPORT`） | **原样复现用户报错**：`UnboundLocalError: cannot access local variable '_ocr_image_bytes'` → A1 红 |
| P2 | 渲染无视 `max_pages`（`PROBE-MAXPAGES`） | 渲染页数 18（应为 11）→ A6 红 |
| P3 | 金额不判"像不像钱"（`PROBE-MONEY`） | 认成 30.0（应为 None）→ A11 红 |
| P4 | 金额窗口退回 12 字 + 去掉符号兜底（`PROBE-WINDOW`/`PROBE-FALLBACK`） | total_amount 变 None → A10b 红 |
| P5 | 往来对象冒号改回可选（`PROBE-COLON`） | 候选冒出「供应的所有低压电缆均为原厂全新正品…」等 8 条 → A10e 红 |
| P6 | 往来对象不过滤句子（`PROBE-PARTY`） | 单独不红（冒号那道闸就挡住了）→ 记录在案：**这道是第二层保险** |
| P7 | 前端关掉 `isWordFile` 拦截（`PROBE-WORD`） | 12 项红（W2–W9 全线崩），恢复后 21/21 绿 |

所有 PROBE 已还原，`grep -rn PROBE app frontend/src` = **0 处**。

## 六、发布与清理

- `frontend/public/sw.js:100` → `erp-pwa-v46`（**打开 ERP 后要强刷一次**，否则旧缓存还在）
- `npm run build` 成功（ContractsLedger 34.42 kB / styles 11.32 kB）
- 测试数据已清：`cleanup_contract_ocr.py --apply` → 删原件 14 / 明细 26 / 合同 14 / 客户 16，残留 0
- 遗留：`data/contracts/tmp/a9f9c52027d7-draft.docx`（**用户 10:07 那次失败尝试留下的**，24h 后会被下次上传顺手清掉，可忽略）
- 快照：`backup/20261019_taskD_ocr_pdf_fix/`（8 个文件）
- 使用说明已更新：`docs/使用说明_合同OCR识别.md`（新增"Word 文档怎么办"）

## 七、改动的文件清单

| 文件 | 改动 |
| --- | --- |
| `app/services/contract_ocr.py` | 三合一 import（:230-240）；金额窗口/像不像钱/抽取函数（:50-56, :154, :173）；往来对象冒号硬条件 + 句子过滤 + 打分（:77-108, :189, :321）；日期补零（:132）；付款条款标题过滤（:69, :303） |
| `app/api/v1/routes/erp_invoice.py` | `_pdf_page_pngs` 加 `max_pages`（:492-524） |
| `frontend/src/components/contracts/ContractsLedger.jsx` | `isWordFile`（:70-88）、`draftWordHint`（:138）、`pickDraftFile` 拦截（:375-390）、提示条（:1025-1030）、`resetDraft` 清理（:245） |
| `frontend/src/components/contracts/contractsLedger.css` | `.cledger__draft-hint`（:675-697），黄色 warning 变量 |
| `frontend/public/sw.js` | `CACHE_VERSION` v45 → v46 |
| `_contract_module/verify_taskD_ocr_pdf.py` | 新增（32 项） |
| `_contract_module/verify_taskD_word_guard.mjs` | 新增（21 项） |
| `_contract_module/_probe_taskd.py` | 新增（7 组反证） |
