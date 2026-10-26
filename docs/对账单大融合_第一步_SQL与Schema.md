# 对账单大融合 · 第一步：SQL 字段清单 + 聚合 API Schema

> 2026-10-21 · **本稿只做设计，未动任何代码**。请您逐列检查"字段全不全"，确认后我再动第二步。
> 阅读顺序：先看【一、逐列盘点】（哪些已有、哪些要加），再看【二、SQL】和【三、Schema】。

---

## 一、逐列盘点（您要的每一列，现有系统对号入座）

### 1. 基础信息

| 您要的列 | 系统现状 | 结论 |
|---|---|---|
| 业务日期 | `statement_items.business_date` | ✅ 已有 |
| 单据号 | `statement_items.source_no` | ✅ 已有 |
| 客户名称/工程项目名 | `statement.party_name` + `sales_orders.project_id → projects` | ✅ 已有（聚合时带出项目名） |
| 仓库 | `sales_orders.warehouse_id → warehouses.name` | ✅ 已有（聚合带出） |
| 商品名称 | `sales_order_items.product_name` | ✅ 已有 |
| 规格 | `sales_order_items.standards` | ✅ 已有 |
| **型号** | ❌ 商品档案和明细行**都没有** model 字段 | ➕ **新增**（见 SQL-3/4） |
| 单位 | `sales_order_items.unit` | ✅ 已有 |
| 数量/单价/金额 | `quantity / unit_price / amount` | ✅ 已有（单价 4 位不截断） |

### 2. 物流签收流

| 您要的列 | 系统现状 | 结论 |
|---|---|---|
| 送货日期 | `sales_orders.delivery_date` | ✅ 已有 |
| **发货时间** | ❌ 无字段。可选口径：a) 聚合时取该单第一条出库流水的 `created_at`（不落库）；b) 落库 `shipped_at` | ➕ 建议 **b) 落库**（快照稳定，历史单可回填；见 SQL-2） |
| 签收人 | `sales_orders.signed_by` | ✅ 已有 |
| 签收时间 | `sales_orders.signed_at` | ✅ 已有 |
| **客户确认时间** | ❌ 无（`statements.confirmed_at` 是对账单自己的确认，不是单据的） | ➕ **新增** `sales_orders.confirmed_at`（见 SQL-1） |
| 电子签（预留） | — | 不建字段，预览接口先返回 `e_sign_status: null` 占位 |

### 3. 发票流

| 您要的列 | 系统现状 | 结论 |
|---|---|---|
| 开票状态 | 单头 `is_invoiced`；对账单行级 `invoice_status(none/partial/full)` | ✅ 已有 |
| 开票时间 | `invoices.issue_date`（发票表有 `related_order_id` 挂单据） | ✅ **聚合时实时 join**，不落库 |
| 开票金额 | `invoices.total_amount`（按 `direction=output` 汇总） | ✅ 同上 |
| 发票号码 | `invoices.invoice_no`（可多张，聚合成"号1、号2"或 JSON 数组） | ✅ 同上 |
| 欠票金额 | `statement_items.uninvoiced_amount` / 单头 `uninvoiced_amount` | ✅ 已有 |

> 设计原则：发票数据**一律实时从 invoices 汇总**，不在 sales_orders 里存第二份——存了必然两张皮。

### 4. 资金流

| 您要的列 | 系统现状 | 结论 |
|---|---|---|
| 付款时间 | `financial_transactions.occurred_at`（`transaction_type=receipt/payment`，`related_order_id` 挂单） | ✅ 聚合实时算 |
| 付款金额 | 单头 `received_amount`（销售）/ `paid_amount`（采购）；流水逐笔可摊 | ✅ 已有 |
| 剩余欠款 | `current_debt / total_debt / outstanding_amount` | ✅ 已有 |
| 付款方式 | `sales_orders.payment_method` | ✅ 已有 |

### 5. 历史专属列（陕送票）

| 您要的列 | 系统现状 | 结论与映射建议 |
|---|---|---|
| 陕送付给的收款 | 单头 `received_amount` 就是"客户付给我们的钱" | ✅ 直接映射，不新增字段 |
| **已付给自采金额** | ❌ 无。业务=这单背后我们付给自采供应商（如良田电子）的钱 | ➕ 单据级新增 `self_purchase_paid`（见 SQL-5）；配套 `self_purchase_supplier_id` 可空挂供应商 |
| **供货价格** | ❌ 无。业务=实际供货价（≠开单售价） | ➕ 行级新增 `supply_price Numeric(14,4)`（见 SQL-6） |
| 单据备注 | `sales_orders.note` | ✅ 已有 |
| 行备注 | `sales_order_items.note` | ✅ 已有 |
| 联系人 | `sales_orders.contact / contact_phone` | ✅ 已有（下单时快照） |

### 6. 采购应付对账单（对称穿透：入库→签收→进项票→付款）

| 环节 | 口径 | 结论 |
|---|---|---|
| 入库 | `purchase_orders(doc_type=inbound)` | ✅ 已有 |
| 签收 | 采购侧"签收" = 入库单审核通过那一刻 | ✅ 用现有状态机时间，**不新增字段**（若您要独立"供应商确认时间"，再加，默认不加） |
| 进项票 | `invoices.direction=input` + `related_order_id` 挂采购单 | ✅ 聚合实时算 |
| 付款 | `financial_transactions.transaction_type=payment` | ✅ 已有 |

---

## 二、SQL（共 7 列，全部可空/带默认，幂等可重跑）

### 2.1 标准 PostgreSQL DDL（给人看；实际由启动时自动加列执行，见 2.2）

```sql
-- SQL-1：客户确认时间（销售 + 采购对称加，采购侧语义=供应商确认）
ALTER TABLE sales_orders    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;

-- SQL-2：发货时间（出库那一刻的快照；历史单由回填脚本从首条出库流水回填，可空）
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMPTZ;

-- SQL-3：型号（档案级 + 明细行快照级。行级快照的理由与 product_name 相同：
--        档案日后改型号不能改写历史单据）
ALTER TABLE products           ADD COLUMN IF NOT EXISTS model VARCHAR(100);
ALTER TABLE sales_order_items  ADD COLUMN IF NOT EXISTS model  VARCHAR(100);
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS model VARCHAR(100);

-- SQL-4：对账单明细行快照（超宽表直接从对账单行取数，不必每次反查源单）
ALTER TABLE statement_items ADD COLUMN IF NOT EXISTS model VARCHAR(100);

-- SQL-5：自采（陕送历史专属）：这单已付给自采供应商的金额 + 挂哪家供应商
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS self_purchase_paid NUMERIC(14,2) NOT NULL DEFAULT 0;
ALTER TABLE sales_orders ADD COLUMN IF NOT EXISTS self_purchase_supplier_id INTEGER;

-- SQL-6：行级实际供货价（费率口径：14,4 不截断，与 unit_price 同规格）
ALTER TABLE sales_order_items    ADD COLUMN IF NOT EXISTS supply_price NUMERIC(14,4);
ALTER TABLE purchase_order_items ADD COLUMN IF NOT EXISTS supply_price NUMERIC(14,4);
```

**不新增的**（防重复建设，请重点核对）：开票时间/开票金额/发票号码、付款时间/付款金额——全部实时 join `invoices` / `financial_transactions`，绝不存第二份。

### 2.2 项目正规落地方式（`app/main.py` 的 ADDITIONS 字典，启动时对每个账套 schema 幂等执行）

```python
SALES_ORDER_ADDITIONS = {
    "confirmed_at": "TIMESTAMPTZ",            # 客户确认时间（预留电子签）
    "shipped_at": "TIMESTAMPTZ",              # 发货时间（出库快照）
    "self_purchase_paid": "NUMERIC(14,2) NOT NULL DEFAULT 0",  # 已付自采金额
    "self_purchase_supplier_id": "INTEGER",   # 自采供应商
}
PURCHASE_ORDER_ADDITIONS = {
    "confirmed_at": "TIMESTAMPTZ",            # 供应商确认时间（对称）
}
PRODUCT_ADDITIONS |= {"model": "VARCHAR(100)"}          # 型号（档案级）
SALES_ITEM_ADDITIONS = {"model": "VARCHAR(100)", "supply_price": "NUMERIC(14,4)"}
PURCHASE_ITEM_ADDITIONS |= {"model": "VARCHAR(100)", "supply_price": "NUMERIC(14,4)"}
STATEMENT_ITEM_ADDITIONS = {"model": "VARCHAR(100)"}     # 对账单行快照
```

---

## 三、聚合 API Schema（重写后的 `GET /statements/{id}/preview` 出参）

### 3.0 核心设计：**列元数据驱动前端**

超宽表 30+ 列如果前端硬编码，以后每加一列前后端两头改。所以接口返回
`columns`（列的清单、分组、宽度、是否冻结），前端超宽表**按 columns 渲染**。
您在页面上看到的列 = 本文件 §1 盘点表的直接映射。

```python
# ── 列元数据 ─────────────────────────────────────────────
class ColumnMeta(BaseModel):
    field: str                # 对应 StatementPreviewRow 的字段名
    label: str                # 中文列头（如「签收时间」）
    group: Literal["基础信息", "物流签收流", "发票流", "资金流", "历史专属"]
    width: int                # 建议列宽 px（超宽表横向滚动）
    frozen: bool = False      # 是否左侧冻结（业务日期/单据号/客户 冻结）
    align: Literal["left", "right"] = "left"
    kind: Literal["text", "money", "qty", "datetime"] = "text"   # 金额右对齐两位小数

# ── 明细行（超宽表的一行 = 对账单明细行，四流数据从源单实时聚合）──
class StatementPreviewRow(BaseModel):
    line_no: int
    row_kind: Literal["detail", "recv", "pay", "invoice", "summary"] = "detail"
    #   detail=业务明细行；recv/payment/invoice=独立收付款/开票行（一笔一行，
    #   没有数量单价）；summary=小计行。同号多笔收款不再挤在一个格子里。

    # —— 基础信息 ——
    business_date: str | None          # 业务日期
    source_no: str | None              # 单据号（销售 XS…/采购 CG…）
    party_name: str | None             # 客户/供应商名称
    project_name: str | None           # 工程项目名（可空）
    warehouse_name: str | None         # 仓库
    product_name: str | None           # 商品名称
    standards: str | None              # 规格
    model: str | None                  # 型号                      ← 新字段
    unit: str | None
    quantity: str | None               # 出参一律字符串（Money 口径）
    unit_price: str | None             # 4 位不截断
    amount: str | None

    # —— 物流签收流 ——
    delivery_date: str | None          # 送货日期
    shipped_at: str | None             # 发货时间                  ← 新字段
    signed_by: str | None              # 签收人
    signed_at: str | None              # 签收时间
    confirmed_at: str | None           # 客户确认时间              ← 新字段
    e_sign_status: None = None         # 电子签占位（未来智能体电子签）

    # —— 发票流（实时 join invoices：related_order_id + direction）——
    invoice_status: Literal["none", "partial", "full"] | None
    invoiced_at: str | None            # 开票时间（issue_date；多张取最早，全部号码见 invoice_no）
    invoiced_amount: str | None        # 开票金额（本行/本单累计）
    invoice_no: str | None             # 发票号码（多张顿号分隔）
    uninvoiced_amount: str | None      # 欠票金额

    # —— 资金流（实时 join financial_transactions）——
    paid_at: str | None                # 付款/收款时间（occurred_at）
    paid_amount: str | None            # 付款/收款金额（单头累计；流水行=单笔）
    remaining_debt: str | None         # 剩余欠款（current_debt）
    payment_method: str | None         # 付款方式

    # —— 历史专属（陕送票）——
    history_received: str | None       # 陕送付给的收款（=received_amount，行级为 0/单头合计行才有）
    self_purchase_paid: str | None     # 已付给自采金额            ← 新字段
    self_purchase_supplier: str | None # 自采供应商名称            ← 新字段（聚合带名）
    supply_price: str | None           # 实际供货价                ← 新字段（4 位）
    doc_note: str | None               # 单据备注
    line_note: str | None              # 行备注
    contact: str | None                # 联系人（快照）

# ── 顶层出参 ─────────────────────────────────────────────
class StatementPreviewOut(BaseModel):
    statement_id: int
    statement_no: str
    available: bool
    party_type: Literal["customer", "supplier"]
    party_id: int | None
    party_name: str | None
    period: dict                       # {"from": "2025-04-01", "to": "2025-06-30"}

    columns: list[ColumnMeta]          # ★ 前端超宽表按此渲染
    rows: list[StatementPreviewRow]    # ★ 明细行 + 独立收付款/开票行 + 小计行

    totals: dict                       # {quantity_sum, amount_sum, invoiced_sum,
                                       #  paid_sum, remaining_sum, self_purchase_sum}

    # —— 保留现有能力：往来账底稿 + 两口径差额（不自动调平的原则不变）——
    ledger: dict                       # 期初→逐笔→期末（finance_reconciliation 原样）
    statement_side: dict               # 对账单口径五个数
    diff: float                        # 差额（业务事实，不四舍五入掉）
    diff_reason: str
```

### 3.1 采购应付对账单

**同一个接口、同一套 Schema**，`party_type=supplier` 时：
- 基础/物流列语义对称（签收=入库审核时间；`signed_by` 留空则显示"已入库"）；
- 发票流 join `direction=input` 的进项票；
- 资金流 join `transaction_type=payment`；
- 历史专属列原样保留（自采单本身也是采购单，`supply_price` 直接可用）。

---

## 四、需要您拍板的 3 个问题

1. **`shipped_at`（发货时间）**：建议落库快照（历史单回填首条出库流水时间）。若您倾向"永远实时算、不落库"，SQL-2 撤掉。
2. **自采字段挂哪**：我按"挂在销售单上"设计的（`self_purchase_paid` + 供应商）。如果自采在你们实务里走的是**一张对应采购单**，更严谨的做法是挂 `source_purchase_order_id` 关联采购单、金额从那张采购单取——请告诉我实务是"只记金额"还是"有对应采购单"。
3. **型号（model）**：历史对账单里的"型号"我按商品档案新字段处理；陕送票历史数据导入时型号列我此前丢弃了（当时没有落点）——需要的话我可以在第二批导入时把型号一并回填。

---

## 五、确认后的执行顺序（第二步预告，不在本稿范围）

1. 后端：ADDITIONS 落地 + `preview` 重写 + 回填脚本（`shipped_at` 从流水回填历史单）；
2. 前端：超宽对账明细表（按 columns 渲染、横向滚动、冻结列）；
3. 录单交互：紧凑表头/复制行/批量选商品/列配置/三维状态列/打印签字区（其中复制行、批量选商品已在，差列配置与紧凑表头）；
4. 采购侧对称验证 + 真浏览器反证验收。
