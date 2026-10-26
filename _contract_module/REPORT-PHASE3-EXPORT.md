# 第 13 批 · 第三阶段（一）：全单据导出 + 对账单（单据）打印

> 日期：2026-10-18　范围：**只做后端**，前端三块界面留到下一步（合同进/出台账、客户文件抽屉、对账单编辑器）。
> 备份：`_contract_module/backup/20261018_phase3/`（erp_print / erp_dataio / excel_io / erp_statement 四个原文件）

---

## 1. 这一步到底补了什么

第二阶段结束时，导出能力盘点下来是这样的：

| 能力 | 之前 | 现在 |
|---|---|---|
| 合同 PDF | ✅ 已有（`/print/contract/{id}`） | 不变 |
| 报价单 PDF | ✅ 已有（`/print/quotation/{id}`） | 不变 |
| 对账单 PDF | ⚠️ 只有**实时聚合**版（按往来单位现算流水） | ✅ 新增**单据版** `/print/statement-record/{id}`（读快照） |
| 档案 Excel | ✅ 6 类（商品/客户/供应商/仓库/员工/期初库存，可导可出） | 不变 |
| 合同 / 报价单 / 对账单 Excel | ❌ 完全没有 | ✅ 新增 `/exports/kinds`、`/exports/{kind}` |

所以本步新增的是两块拼图：**单据台账的 Excel 导出**，和**对账单（已定稿单据）的 PDF**。

---

## 2. 新增接口

### 2.1 `GET /api/v1/exports/kinds`

```json
[
  {"kind": "contracts",  "label": "合同台账",   "sheets": ["合同", "合同明细"],
   "date_field": "sign_date",  "summary": "…", "header_columns": [...], "detail_columns": [...]},
  {"kind": "quotations", "label": "报价单台账", "sheets": ["报价单", "报价明细"], "date_field": "quote_date"},
  {"kind": "statements", "label": "对账单台账", "sheets": ["对账单", "对账明细"], "date_field": "period_end"}
]
```

### 2.2 `GET /api/v1/exports/{kind}`

查询参数（全部可选）：`from_date`、`to_date`、`direction`（in/out，仅合同与对账单有效）、`status`。

返回 xlsx（`Content-Disposition: attachment`，中文文件名 + RFC 5987）。

错误码：
- `404` 未知 kind
- `400` `direction` 不是 in/out
- `400` `from_date > to_date`

### 2.3 `GET /api/v1/print/statement-record/{id}`

打印**已定稿**的对账单。与旧接口的区别写在函数 docstring 里，这里再说一遍：

| | `/print/statement/{party_type}/{party_id}` | `/print/statement-record/{id}` |
|---|---|---|
| 数据来源 | 合同 + 发票 + 收付款**实时聚合** | `statements` 表**头部快照** |
| 用途 | 临时查"这个客户欠多少" | 打印一张已经发给对方的凭证 |
| 金额会变吗 | 会（随时按最新单据重算） | **不会**（除非显式 `POST /statements/{id}/recalc`） |

两条路径段数不同（2 段 vs 3 段），FastAPI 不会互相吃掉。

---

## 3. Excel 的形状：为什么是"一个文件两张表"

合同与报价单的明细是**商品行**，对账单的明细是**业务事实行**（合同/发票/收款）。
把两者拍平进一张宽表会立刻出问题：对账单里「合同金额」和「已开票」是两列不同口径的数，
拍平后一行里同时有合同额、开票额、收款额、余额 —— 任何人在 Excel 里对这一列按 Ctrl+↓ 求和，
得到的都是**重复计算的垃圾**。所以坚持：

```
工作簿
├── 主表（一行一份单据）   ← 可以求和、可以筛选、可以透视
└── 明细（一行一个商品/事实）← 只用来追溯，不参与汇总
```

两张表的排版一致：第 1 行标题、第 2 行副标题（条数 + 导出时间 + **筛选条件回显**）、
第 3 行表头（深蓝底白字）、第 4 行起数据、末尾一行「合计」。
表头带自动筛选、前 3 行冻结。

### 3.1 合计行只汇总金额/数量列

`TOTAL_FIELDS` 显式列出哪些字段可求和。编号、日期、状态列在合计行里留空 ——
合计行里混进一个"对账单号"是外行做法，也会让下游脚本误读。

### 3.2 金额必须过 `float`

```python
def _money(value) -> float:
    """Decimal / 字符串 / None → 两位小数 float。
    ⚠️ 必须过 float：openpyxl 收到 Decimal 会按文本写入，Excel 里 SUM 全 0。"""
```

这是本步最容易埋的坑：库里全是 `Numeric(12,2)` → SQLAlchemy 给出来是 `Decimal`。
直接把 `Decimal` 塞给 openpyxl，Excel 打开看得见数字、求和却是 0，用户只会说"你们导出的数不对"。

### 3.3 状态 / 方向列给人看中文

`direction`、`status`、`ocr_status`、`invoice_status`、`source_type` 全部翻译成中文
（`STATEMENT_DIRECTIONS` / `CONTRACT_STATUS` / `STATEMENT_INVOICE_STATUS` …）。
库里存 `partial`，表里必须是「部分开票」—— 导出文件是给会计和对方看的，不是给程序员看的。

---

## 4. 六个决策（以及为什么不能反过来做）

### 4.1 为什么不塞进 `/excel/*`

`erp_dataio.py` 的 `GET /excel/kinds` 是「导入导出」面板的数据源，每一项都配着
**下载模板 + 导入**两个按钮，且 `_IMPORT_TARGETS[kind]` 里必须有对应模型。
单据是**只出不进**的（合同靠业务生成，不靠 Excel 导回来）。塞进去，那个面板就会出现
一个点「导入」必然 404 的类别，以及一个 `excel_io.COLUMNS` 里没有列的"模板"。

所以：**两套各自独立**。回归断言 R3 就是盯这个 ——
`/excel/kinds` 必须仍然恰好 6 项，且不含 contracts/quotations/statements。

### 4.2 合同方向过滤为什么用 `or_`

```python
q.filter(or_(Contract.direction == want,
             Contract.contract_type == normalize_contract_type(want)))
```

老数据的 `direction` 是后来补的列，`server_default='out'`。也就是说：
**历史上所有采购合同的 `direction` 值都是 `out`**，只有 `contract_type='purchase'` 是对的。
只按 `direction` 过滤，导出的采购台账会整体少掉十几份合同，而且不报错、没人发现。
双条件是把老数据兜住，等某次全量对齐后再收窄。

### 4.3 对账单导出/打印绝不重算

`statements` 头部的 10 个金额是**冗余快照**（第一阶段就定下的）。导出时如果顺手
`compute_totals()` 一遍，会出现这种事：3 月发给客户的对账单写的是应收 3050，
6 月改了一张发票，客户再下载 3 月那份 PDF，变成 2800 —— 对账永远扯不清。

验证台 E85/E86/E87 就是这条：**导出前后头部金额必须逐字节不变**。

### 4.4 打印走哪个通道

复用 `_pdf_response(spec, filename, db, doc_type, as_json)`，不另写一份。
它已经处理了 Edge 内置 PDF 阅读器会接管 `application/pdf` 的老问题：
`Accept: application/json` 时返回 base64 JSON，前端 `fetch` 才拿得到字节。
验证台 P8–P11 两条通道都验，并断言两边的 PDF 字节数一致。

### 4.5 `statement-record` 必须进 `DOC_TYPE_ORDER`

`printable_doc_types()` 是打印模板表的播种清单，而 `sort_doc_types()` 只按
`DOC_TYPE_ORDER` 排序 —— 未归类的会排到末尾，且有测试断言"注册表里的类型必须都已归类"。
所以新增打印类型要**同时**做三件事：

1. `_PRINT_KINDS["statement-record"] = (...)`
2. `print_template.DOC_TYPE_ORDER` 加 `"statement-record"`
3. 重启服务（模板表按清单播种，新增行只在启动时补）

验证台 P17 直接查 `/system/print-templates`，确认这行真的播种进去了 ——
只看 `printable_doc_types()` 是假绿（那只是内存里的 list）。

### 4.6 日期过滤用字符串比较，不 `::date`

`sign_date` / `quote_date` / `period_end` 都是 `String(20)`。字符串比较对
`YYYY-MM-DD` 天然正确，而且**空串不会炸**。业务上"没填签订日期"的草稿合同
本来就应该在"不过滤"时出现；一旦 `CAST(... AS date)`，一条空串就整表 500。

---

## 5. 验证

### 5.1 新增 `_contract_module/verify_export_phase3.py`（127 项）

不只看状态码，**把 xlsx 解开来逐格核对**：

| 组 | 项数 | 覆盖内容 |
|---|---|---|
| K | 11 | kinds 清单、两类工作表名、日期字段、非法 kind/direction/日期区间 |
| E | 约 60 | 合同/报价单/对账单三类的表头文字、我造的那一行逐字段、明细行数与行号、合计行金额 = 各行之和、direction 与日期过滤、副标题回显筛选条件 |
| E85–E87 | 3 | **导出后头部金额/期初/明细行数不变** |
| P | 25 | 打印类型清单、模板表播种、二进制与 JSON 双通道、非法 id 404、旧接口仍可用；**PDF 抽文本断言**：单号、3,050.00 出现两次（汇总块 + 合计行）、大写「叁仟零伍拾元整」、明细摘要 |
| R | 9 | `/excel/kinds` 仍 6 项且不含单据类别、四个列表接口 200、openapi 路径、注册表外 doc_type 404 |
| Z | 4 | 清理残留为 0 |

### 5.2 三组反证（改坏 → 变红 → 还原）

`_contract_module/probe_phase3.py`（跑完自动还原，`grep PROBE_ app/` 为空）

| 反证 | 改了什么 | 变红 |
|---|---|---|
| A | `if data and total_fields:` → `if False and …`（关掉合计行） | E22 / E50 / E83 |
| B | 打印合计金额 `receivable_balance` → `outstanding_amount` | P24（3,050.00 只出现 1 次） |
| C | `_PRINT_KINDS["statement-record"]` 改名 | P1 / P2 / P4 / P5 / P6 |

> B 第一次**没红** —— 因为「3,050.00」在汇总块里也出现，P19 的"包含"断言抓不到。
> 改成"必须出现两次 + 大写必须是叁仟零伍拾元整"才抓住。这条记在这里：
> **包含式断言挡不住"用错字段但值恰好也在别处"这类错**。

### 5.3 回归

| 套件 | 结果 |
|---|---|
| `verify_db_phase1.py`（三 schema 落库） | 93/93 |
| `verify_phase1_models.py`（模型 + 临时 schema 真建表） | 74/74 |
| `verify_api_phase2.py`（22 个接口） | 140/140 |
| `verify_export_phase3.py`（本步） | 127/127 |
| **合计** | **434 项全绿** |

本步**没有改动任何前端文件**，所以 `npm run build` 不适用（下一步做界面时必须过）。

---

## 6. 已知限制（下一步要记住的）

1. **前端零改动** —— 合同进/出台账、客户文件抽屉、对账单编辑器都还没有界面。
   导出接口已经能用，但用户在系统里还点不到（只能直接敲 URL）。
2. **Excel 不含图片/附件** —— 合同原件是 PDF/图片，导出只带**文件名**（`原件文件` 列），
   不带二进制。真要一起归档，是"打包 ZIP"的另一件事（涉及 `data/contracts/` 目录遍历）。
3. **报价单的 `direction` 参数是空操作** —— 报价单只有"给客户报价"一个方向，
   它的 `status` 才是业务状态。接口层接受该参数但不生效，避免前端两种页面复用同一段代码时报 400。
4. **单个对账单打印没有分页控制** —— 明细特别多的对账单靠渲染器自动翻页，
   表头不会在每页重复（`pdf_render` 的现有行为，所有单据一致，不是本步引入的）。
5. **`/exports/*` 没有鉴权** —— 与其余业务接口口径一致（无 token 也 200），
   `/system/*` 才 401。如果将来要收紧，是全站一起收，别只收这一处。

---

## 7. 回滚

```powershell
cd E:\AI\ERP软件
copy /Y _contract_module\backup\20261018_phase3\erp_print.py  app\api\v1\routes\erp_print.py
copy /Y _contract_module\backup\20261018_phase3\erp_dataio.py app\api\v1\routes\erp_dataio.py
copy /Y _contract_module\backup\20261018_phase3\excel_io.py   app\services\excel_io.py
copy /Y _contract_module\backup\20261018_phase3\erp_statement.py app\api\v1\routes\erp_statement.py
```

本步**新增**的文件（回滚时直接删）：
`app/services/doc_export.py`、`app/api/v1/routes/erp_export.py`。

还要改回两处注册（否则 import 报错）：

- `app/api/v1/routes/erp.py`：删掉 `erp_export_router` 的 import 与 `include_router`
- `app/models/print_template.py`：`DOC_TYPE_ORDER` 里删掉 `"statement-record"`

**无数据库变更**（本步不建表、不加列），所以不需要动 `__tablename__` 或迁移。
但 `print_templates` 表里已经播种的 `statement-record` 行会留着 —— 无害，
下次启动若清单里没有它，也不会被删（`_backfill` 只补不删）。
