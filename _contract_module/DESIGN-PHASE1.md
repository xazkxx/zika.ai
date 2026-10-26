# 第 13 批 · 第一阶段设计说明书

> 合同双向管理 / 客户文件归档 / 报价单关联 / 增强版对账单
> 范围：**数据库表结构 + Pydantic Schema**。本阶段**没有写任何前端代码，也没有写路由**。
> 日期：2026-10-18　｜　状态：已完成并落库验证（93/93 + 74/74 + 反证 3 组）

---

## 0. 一句话结论

四张核心表（`contracts` 扩展 + `customer_files` / `statements` / `statement_items` 新建 + `quotations` 扩展）
已经在 **public / co_02 / co_03 三个账套**全部建好、补好列、金额列转成 `numeric(12,2)`；
明细全部独立成表；外键只在**新表**上出现，存量表一律不补（理由见 §4 决策矩阵）。

---

## 1. ER 关系

```
                          ┌────────────────────────┐
                          │      customers         │  （存量表，未改动）
                          └───────────┬────────────┘
                                      │ 1
                                      │            ON DELETE RESTRICT ★
                                      │ N
                          ┌───────────┴────────────┐
                          │    customer_files      │  客户归档：合同/资质/发票/对账单/其他
                          └────────────────────────┘

  ┌─────────────────────────────────┐
  │           contracts             │  合同主表（in 采购 / out 销售 双向共用）
  │  direction  'in' | 'out'        │
  │  contract_type 'purchase'|'sales'│ ← 旧的兼容字段，与 direction 永远一致
  │  source_file_* / ocr_json       │  原件 + OCR 原始 JSON
  └───────┬─────────────────┬───────┘
          │ 1               │ 1
          │                 │ (无外键，靠应用层 + SET NULL 语义)
          │ N               │ N
  ┌───────┴──────────┐  ┌───┴──────────────────┐
  │  contract_items  │  │     quotations       │  报价单（contract_id 可选）
  │  （存量明细表）   │  │  contract_id (整数)   │
  └──────────────────┘  └───────┬──────────────┘
                                │ 1
                                │ N
                        ┌───────┴──────────────┐
                        │   quotation_items    │ （存量明细表）
                        └──────────────────────┘

  ┌─────────────────────────────────┐
  │           statements            │  对账单**头部**（一张对账单一行）
  │  10 个金额字段（冗余快照）        │
  └───────┬─────────────────────────┘
          │ 1
          │ N      ON DELETE CASCADE ★
  ┌───────┴─────────────────────────┐
  │        statement_items          │  对账单**明细区**（一条业务一行）
  │  contract_id → SET NULL ★       │
  └─────────────────────────────────┘
```

★ = 新表上的真实外键（全库一共 4 个外键：这 3 个 + 存量 `production_boms.parent_id` 自引用）。

---

## 2. 表 1：合同主表 + 明细（进/出双向）

### 2.1 `contracts`（存量表，本批扩展）

| 分组 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 主键 | `id` | serial | |
| 编号 | `contract_no` | varchar(50) **unique** | 不传则 `HT+日期+序号` 自动生成（第二阶段） |
| **方向** | **`direction`** | **varchar(10) NOT NULL DEFAULT 'out'** | **`in` 采购（形成应付） / `out` 销售（形成应收）** |
| 兼容 | `contract_type` | varchar(20) NOT NULL | `sales`/`purchase`，与 `direction` 强制同步（见 §5.1） |
| 模板 | `template` / `title` | varchar | A1 简约 / A2 标准 / A3 详尽 / A4 框架 |
| 状态 | `status` | varchar(30) | 草稿 `draft` / 待审 `pending` / 生效 `active` / 完成 `finished` / 作废 `void`（旧值 `signed`/`executing` 仍兼容） |
| 对方快照 | `party_type` / `party_id` / `party_name` / `party_tax_no` / `party_legal_person` / `party_address` / `party_contact` / `party_phone` / `party_bank_*` | | **快照**，不跟随档案变化（合同是法律文件） |
| 我方快照 | `own_name` / `own_tax_no` / `own_legal_person` / `own_address` / `own_bank_*` | | 同上 |
| 签订 | `sign_date` / `sign_place` / `valid_from` / `valid_to` | varchar(20) | 统一 `YYYY-MM-DD` 字符串（与全系统一致，避免时区坑） |
| **金额** | **`total_amount`** | **numeric(12,2) NOT NULL DEFAULT 0** | 上限 9,999,999,999.99 |
| 税额 | `tax_rate`(float) / `is_tax_included`(bool) / `amount_chinese` | | 税率百分比、含税标志、金额大写（冗余便于打印） |
| A2 条款 | `quality_standard` / `package_standard` / `delivery_date` / `delivery_place` / `delivery_method` / `freight_bearer` / `inspection_days` / `objection_days` / `warranty_terms` / `penalty_rate` / `dispute_resolution` / `copies` / `service_address` / `other_terms` | | 合同正文的变量占位 |
| 关联 | `warehouse_id` / `order_id` / `order_no` | int/str | 转单后回填单据 id / 单号 |
| **原件** | **`source_file_path`** | varchar(500) | **相对 `storage_root`**（绝对路径换盘即失效，与 `invoices.source_path` 同口径） |
| | `source_file_name` / `source_file_size` / `source_file_mime` | | 原始文件名 / 字节 / `application/pdf`、`image/png`… |
| **OCR** | **`ocr_json`** | **text** | **引擎原始输出，原样保存**（人工核对时必须能看到"当时到底吐了什么"） |
| | `ocr_status` | varchar(20) NOT NULL DEFAULT 'none' | `none` 未识别 / `pending` 识别中 / `parsed` 已识别待核对 / `reviewed` 已人工核对 / `failed` 失败 |
| 审计 | `created_at` / `updated_at` | timestamptz | |

> **为什么 OCR 结果不拆字段落库**：识别一定有错，核对结论只需要一个状态位（`ocr_status=reviewed`）。
> 把识别结果拆成结构化字段，等于把"可能错的猜测"混进业务数据，后面永远分不清哪个数字是人填的。
> 第二阶段核对流程：展示 `ocr_json` ↔ 表单字段并排 → 人工确认 → 覆盖字段 + 置 `reviewed`。

### 2.2 `contract_items`（存量明细表，仅金额转列）

`id` / `contract_id`(int，**无外键**) / `product_id` / `product_name` / `standards` / `unit` /
`quantity`(float) / **`unit_price` numeric(12,2)** / **`amount` numeric(12,2)** / `note` / `created_at`

> 存**商品快照**：合同是历史文件，商品改名改价后，旧合同打印出来必须还是当年那份内容。

---

## 3. 表 2 / 表 3 / 表 4

### 3.1 `customer_files`（新建）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | serial | |
| `customer_id` | int **NOT NULL** → `customers.id` **ON DELETE RESTRICT** | 见 §4 |
| `original_name` | varchar(255) NOT NULL | 用户上传时的文件名（中文原文） |
| `stored_name` | varchar(255) NOT NULL | 磁盘文件名（uuid + 扩展名），**避免中文/重名/路径穿越** |
| `file_path` | varchar(500) | 相对 `storage_root` |
| `file_size` | **bigint** | 字节（>2GB 不溢出，`integer` 只能到 2.1GB） |
| `mime_type` | varchar(100) | 白名单校验在路由层（`CUSTOMER_FILE_MIME_WHITELIST`） |
| `checksum` | varchar(64) index | sha256，用于"同一份文件重复上传"检测 |
| `category` | varchar(20) NOT NULL DEFAULT 'other' | `contract` 合同 / `qualification` 资质 / `invoice` 发票 / `statement` 对账单 / `other` 其他 |
| `uploaded_at` / `uploaded_by` / `note` | | 审计 |
| 索引 | `ix_customer_files_customer_category (customer_id, category)` | 客户抽屉里按分类分页是高频操作 |

### 3.2 `quotations`（存量表，本批扩展）

新增 `contract_id` **integer + 索引，故意无外键**（理由见 §4）、`total_amount` → numeric(12,2)；
`quotation_items.unit_price` / `amount` → numeric(12,2)。
报价单原有字段（`quotation_no` / `customer_id` / `valid_to` / `status`）不变。

### 3.3 `statements`（新建，**头部**）

| 字段 | 类型 | 口径 |
|---|---|---|
| `statement_no` | varchar(50) unique | `DZ+日期+序号`（第二阶段生成） |
| `direction` | varchar(10) NOT NULL DEFAULT 'out' | `out` 应收对账单 / `in` 应付对账单 |
| `party_type` / `party_id` / `party_name` / `party_tax_no` | | `customer`↔`out`、`supplier`↔`in`，**Schema 层强制校验** |
| `period_start` / `period_end` / `statement_date` | varchar(20) | 对账区间与制单日 |
| `currency` | varchar(10) DEFAULT 'CNY' | |
| `opening_balance` | numeric(12,2) DEFAULT 0 | 期初应收/应付（取自 `customers.init_receivable` / `suppliers.init_payable`） |
| `contract_amount` | numeric(12,2) | 本期合同金额合计 |
| `invoiced_amount` | numeric(12,2) | 已开票金额合计 |
| `uninvoiced_amount` | numeric(12,2) | **= 合同金额 − 已开票** |
| `received_amount` | numeric(12,2) | 已收/已付合计 |
| `prepaid_received` | numeric(12,2) | 本期预收/预付发生额 |
| `prepaid_applied` | numeric(12,2) | 预收已核销（抵本期应收的部分） |
| `prepaid_balance` | numeric(12,2) | **= 本期预收 − 预收已核销** |
| `receivable_balance` | numeric(12,2) | **= 期初 + 本期已开票 − 本期已收 − 预收已核销** |
| `outstanding_amount` | numeric(12,2) | **= 合同金额 − 已收/已付 − 预收已核销** |
| `item_count` / `status` / `confirmed_at` / `note` / `created_by` / `created_at` / `updated_at` | | `status`: `draft`/`confirmed`/`sent`/`void` |
| 索引 | `(party_type, party_id, period_end)`、`(direction, status)` | |

### 3.4 `statement_items`（新建，**明细区**）

| 字段 | 类型 | 说明 |
|---|---|---|
| `statement_id` | int → `statements.id` **ON DELETE CASCADE** | |
| `line_no` | int | 打印顺序 |
| `business_date` | varchar(20) | **业务日期**（需求点名的字段） |
| `source_type` / `source_id` / `source_no` | | `contract`/`order`/`inbound`/`outbound`/`opening`（`invoice`/`receipt`/`payment` 预留） |
| `contract_id` | int → `contracts.id` **ON DELETE SET NULL** | 合同删了，对账单作为凭证仍要能打开 |
| `contract_no` | varchar(50) | **快照兜底**：链接断了也看得出这一行是哪份合同 |
| `summary` | varchar(255) | 打印在明细行上的摘要 |
| `contract_amount` / `invoiced_amount` / `uninvoiced_amount` / `received_amount` / `prepaid_received` / `prepaid_applied` / `outstanding_amount` | numeric(12,2) | 行级金额，后两个是**计算结果** |
| `invoice_status` | varchar(10) DEFAULT 'none' | `none` 未开 / `partial` 部分开 / `full` 已开（**由金额推导，不接受手填**） |
| `invoice_count` | int | 关联发票张数 |
| `note` / `created_at` | | |

---

## 4. 外键 / 级联决策矩阵（用户点名要求的分节）

| 关系 | 决策 | 为什么不是别的 | 代价 / 配套动作 |
|---|---|---|---|
| `customer_files.customer_id` → `customers.id` | **RESTRICT**（默认拒绝） | **CASCADE 会静默删掉客户的合同原件、资质扫描件** —— 删一个客户把人家三年的合同 PDF 一起干掉，是不可接受的数据丢失；`SET NULL` 会造出一堆无主文件，等于同样的数据丢失外加污染 | 删客户时数据库抛 `IntegrityError` → **路由必须先调 `count_customer_files()` 查一次，返回 409 + 中文原因**（"该客户名下还有 N 个归档文件，请先归档或转移"）。禁止把 `IntegrityError` 直接抛给前端 |
| `statement_items.statement_id` → `statements.id` | **CASCADE** | 明细是头部的**组成部分**，不是独立实体；留着孤儿明细会让"按合同汇总"凭空多出金额 | 无。ORM 侧同步配 `cascade="all, delete-orphan"`，删头部不用手动删明细 |
| `statement_items.contract_id` → `contracts.id` | **SET NULL** | 对账单发出去是**法律凭证**，合同被删/被作废也必须能打开，只是断开关联 | `contract_no` 快照兜底；打印时优先用快照 |
| `contracts.party_id` → customers **或** suppliers | **不加外键**（应用层校验） | 它是**多态引用**（由 `party_type` 决定指向哪张表），单个外键表达不了；PG 也做不了条件外键 | 创建/更新合同时校验档案存在；合同里 `party_name` 等字段是快照，档案删了合同照样可读 |
| `statements.party_id` | **不加外键** | 同上（多态） | 同上 |
| `contract_items.contract_id`、`quotation_items.quotation_id` | **不加外键** | 存量表，三个账套里早就在，由既有 ORM 代码"先删明细、再删主表"。补外键要全表校验孤儿行，**失败会让服务起不来**，收益只是"多一道保险" | 现有代码路径已经保证一致（侦察确认孤儿行 0） |
| `quotations.contract_id` | **不加外键**（虽然它是新列） | 模型上写 `ForeignKey` 只对**新建库**生效（`create_all` 不给已存在的表加约束）→ 结果"开发机新库有约束、生产老库没有"，同一份代码两边行为不同 | 删除合同前路由先 `UPDATE quotations SET contract_id=NULL`。**反证时踩到过**：模型里带 FK 时，临时 schema 建出 5 个外键、真实库只有 4 个 —— 这条差异已消除 |

> **一条总原则**：**新表**（`customer_files` / `statements` / `statement_items`）全部带外键并精确定义级联语义；
> **存量表**（`contracts` / `contract_items` / `quotations` / `quotation_items`）一律只加列 + 索引，不加约束。

---

## 5. 与现有表的兼容策略

### 5.1 `direction` vs `contract_type`

- **`direction` 是权威字段**，`contract_type` 保留只为兼容老前端/老数据（老代码还在写 `contract_type`）。
- 模型层 `normalize_direction()` / `normalize_contract_type()` 双向映射；
  `ContractCreate` 的 `model_validator(mode="after")` **强制回写**两者，
  **永远不会落库出 `direction=out` 而 `contract_type=purchase` 这种自相矛盾的行**。
- 启动迁移里有一条一次性对齐 SQL（只动矛盾行）：采购类型 → `direction='in'`，反之亦然。
- 字典 `CONTRACT_STATUS` **保留旧值** `signed` / `executing`：删掉字典项会让老合同的标签变空白。

### 5.2 `float` → `numeric(12,2)`

| 表.列 | 转换前 | 转换后 |
|---|---|---|
| `contracts.total_amount` | double precision | numeric(12,2) |
| `contract_items.unit_price` / `amount` | double precision | numeric(12,2) |
| `quotations.total_amount` | double precision | numeric(12,2) |
| `quotation_items.unit_price` / `amount` | double precision | numeric(12,2) |

- 迁移用 `ALTER TABLE ... TYPE numeric(12,2) USING round(col::numeric, 2)`，**不写 COALESCE** ——
  可空列的 NULL 必须保持 NULL（`round(NULL)` 仍是 NULL），把"未填"抹成 0 会让对账单分不清两种语义。
- **Python 侧**：计算一律 `Decimal`（`_dec()` 两位小数、显式 `ROUND_HALF_UP` 四舍五入；
  Decimal 默认是银行家舍入，100.005 会变 100.00 —— 国内对账不能这么舍）。
- **API 出参一律 `float`**：pydantic 的 `Decimal` 默认序列化成**字符串** `"12.30"`，前端拿到会更坑。
  精度损失只发生在"读出来的最后一公里"，DB 与计算链路全程定点。

### 5.3 头部合计是**冗余快照**（重要）

`statements` 的 10 个金额是**生成那一刻算好后写进去的快照**，不是视图、不实时重算：

- 对账单一经发出就是**法律凭证**，事后有人补录一张发票，不能让去年 12 月那张对账单自己变数；
- 重算只能是**显式动作**：`POST /statements/{id}/recalc`（第二阶段实现），由 `compute_totals()` 统一算；
- `compute_totals()` / `derive_item_amounts()` / `infer_invoice_status()` 是**唯一口径**，
  Schema 校验也调它们（不再各写一份 `round(float(...))`）。

### 5.4 四个余额公式（写进 `app/models/statement.py` 文件头）

```
未开票金额       = 合同金额 − 已开票金额
剩余未收/未付     = 合同金额 − 已收/已付 − 预收已核销
应收账款余额     = 期初应收 + 本期已开票 − 本期已收 − 预收已核销
预收账款余额     = 本期预收 − 预收已核销
```

⚠️ `outstanding_amount`（剩余未收/付）与 `receivable_balance`（应收余额）**不是同一个数**：
前者只针对**本期合同**，后者含**期初 + 往期**。把两者混用，客户拿到对账单第一句就是"你这数不对"。

---

## 6. 本阶段实际动到的文件

| 文件 | 动作 |
|---|---|
| `app/models/contract.py` | 加 `direction` / `source_file_*` / `ocr_*` / `updated_at`；金额 → Numeric；加字典与双向归一函数 |
| `app/models/customer_file.py` | **新建**：模型 + 分类字典 + MIME 白名单 + `count_customer_files()` |
| `app/models/statement.py` | **新建**：`Statement` + `StatementItem` + `_dec/derive_item_amounts/infer_invoice_status/compute_totals` |
| `app/models/quotation.py` | `contract_id`（整数 + 索引，无外键）；金额 → Numeric |
| `app/models/__init__.py` | 注册全部新符号 |
| `app/schemas.py` | 新增 347 行（`CustomerFile*` / `Statement*` / `ContractCreate` 扩展 / `QuotationCreate.contract_id`）；`StatementItemBase._derive` 改为调用模型纯函数 |
| `app/main.py` | 新增 `CONTRACT_ADDITIONS` / `QUOTATION_ADDITIONS` / `MONEY_COLUMNS_TO_NUMERIC` / `_ensure_numeric_money()` / `ensure_contract_module()`，在 `create_app()` 与 `ensure_all_tenant_schemas()` 两处调用 |

### 6.1 启动迁移做了什么（幂等，每个 schema 各一遍）

1. 新表由 `Base.metadata.create_all()` 建（**不重复写 DDL**，避免两份定义分叉）；
2. `_add_missing_columns` 给 `contracts` / `quotations` 补新列；
3. `_ensure_numeric_money` 把 6 个金额列从 `double precision` 转 `numeric(12,2)`；
4. 对齐 `direction` ↔ `contract_type` 的矛盾行；
5. `CREATE INDEX IF NOT EXISTS` 补 `contracts.direction` / `quotations.contract_id` 索引
   （`create_all` 不会给已存在的表建索引）。

---

## 7. 验证结果

| 套件 | 结果 | 覆盖 |
|---|---|---|
| `_contract_module/verify_db_phase1.py` | **93/93** | 三 schema 的新表 / 新列 / 索引 / 金额精度 / 外键 ondelete / 方向无矛盾行 |
| `_contract_module/verify_phase1_models.py` | **74/74** | 金额精度（Decimal、四舍五入、0.1+0.2）/ direction 双向 / 对账单方向互斥 / 明细派生 / 客户文件 / **临时 schema 真建表 + 级联实证**（跑完 CASCADE 删干净） |
| 幂等 | ✅ | `import app.main` 连续跑 3 次，两次核对都是 93/93 |

### 7.1 反证（断言必须能变红）

| 反证 | 改坏什么 | 结果 |
|---|---|---|
| A | `derive_item_amounts` 的未开票改成 `contract + invoiced` | **71/74**，红：A1 / D1 / D6 |
| B | 去掉 `StatementCreate` 的 out+supplier 拦截 | **73/74**，红：C4 |
| C | `customer_files.customer_id` 的 `RESTRICT` → `CASCADE` | **71/74**，红：F4 / F11（+ F12 连带） |
| — | 全部还原后 | **74/74** 重新全绿 |

### 7.2 反证过程中真查出来的 3 个问题（都已修）

1. **`isinstance(x, Numeric)` 判断不了浮点**：SQLAlchemy 是 `Float(Numeric)`、`DOUBLE_PRECISION(Float)`，
   第一版迁移把 double precision 当成 numeric 放过，**迁移"成功"但列没变**（落库核对抓到的）。
2. **`getattr(dict, 'contract_amount', None)` 恒 None**：`compute_totals()` 对 dict 入参算出一堆 0.00 不报错。
   第二阶段接口必然要传 dict → 已加 `_field()` 显式分流。
3. **`quotations.contract_id` 上的 ForeignKey**：会让新建库有 5 个外键、生产库 4 个。已去掉，模型与库一致。

---

## 8. 回滚步骤

代码回滚（三个文件组的备份都在 `_contract_module/backup/`）：

```powershell
# 1) 代码
Copy-Item _contract_module\backup\20261018_154140\app_main.py                          app\main.py
Copy-Item _contract_module\backup\20261018_154140\app_schemas.py                        app\schemas.py
Copy-Item _contract_module\backup\20261018_154140\app_models_contract.py                app\models\contract.py
Copy-Item _contract_module\backup\20261018_154140\app_models_quotation.py               app\models\quotation.py
Copy-Item _contract_module\backup\20261018_154140\app_models___init__.py                app\models\__init__.py
Remove-Item app\models\customer_file.py, app\models\statement.py

# 2) 数据库（新增的东西不影响旧代码：旧代码不读这些表/列）
#    真的想退回干净状态时执行（⚠️ 会删掉已经归档的客户文件索引！先备份）
#    DROP TABLE IF EXISTS statement_items, statements, customer_files;
#    ALTER TABLE contracts DROP COLUMN IF EXISTS direction, source_file_path, ...;
```

> **注意**：金额列**不要**改回 double precision（`numeric` 是超集，旧代码读 numeric 完全正常）。

---

## 9. 第二阶段计划（等你审核通过再动手）

| # | 内容 |
|---|---|
| 1 | `app/api/v1/endpoints/contracts.py`：CRUD + 状态流转 + `POST /{id}/to-order` 转单 |
| 2 | `contracts` 原件上传 / 下载（复用 `file_storage`），OCR 结果回写 + 核对接口 |
| 3 | `customer_files`：multipart 上传（大小/MIME 白名单、sha256 去重）、列表、下载、删除；**删客户前 409 守卫** |
| 4 | `quotations`：CRUD + 关联合同 |
| 5 | `statements`：按区间生成 → 明细落库 → `POST /{id}/recalc` 重算 → 确认/发送 |
| 6 | 全单据导出（Excel / PDF）：合同、报价单、对账单 |
| 7 | 前端：合同双向台账（进/出切换）、客户文件抽屉、对账单编辑器 |

---

## 10. 一句话验收（给你自己看的）

1. 重启服务（双击 `启动ERP.bat`）—— 启动日志没有报错，就说明三个账套的迁移都跑过了。
2. 想复核：`.venv\Scripts\python.exe _contract_module\verify_db_phase1.py` → 应打印 `结果：93/93`。
3. 届时界面没有任何变化 —— **本阶段只有数据库和契约，没有前端**，这是预期的。
