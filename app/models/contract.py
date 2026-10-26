from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Contract(Base):
    """购销合同（模板 A2 · 标准版）—— 第 13 批起承担「合同双向管理」。

    融合改造要点：

    1. 合同是**意向性文件**，签订本身不产生应收应付 —— 会计上不能凭一纸合同确认
       收入或负债，否则报表立刻虚增。所以本合同表**不直接写财务流水**。
    2. 与财务/库存的关联靠「一键转单」落地：``POST /contracts/{id}/to-order``
       把合同生成正式采购单 / 销售单，由单据去联动库存与财务（`related_type='contract'`
       登记在财务单据类型字典里，转单时带上合同号为溯源线索）。
    3. 甲乙方信息在**创建时快照**，与档案解耦 —— 合同是法律文件，不能让"客户改了地址"
       把三年前的合同一起改掉。
    4. A2 标准版的条款正文由模板生成，这里只存**变量占位**（质量标准、验收期限、
       付款节点、违约金比例……），条文框架在 `pdf_render` 侧的模板函数里。

    ⚠️ 第 13 批的三条硬规则：

    · **`direction` 是新的权威字段**（`in` 采购 / `out` 销售），历史 `contract_type`
      （sales / purchase）保留兼容 —— 前端老代码还在写它，两者由
      `normalize_direction()` 双向对齐，**不允许出现 direction=out 而 contract_type=purchase**
      这种自相矛盾的行。
    · **金额一律 `Numeric(12, 2)`**。原来是 `Float`（= PG 的 double precision），
      `0.1 + 0.2 != 0.3` 会在对账单汇总时累积成"差一分钱"，对账场景不可接受。
      已有库由 `ensure_money_numeric()` 幂等转列（见 `app/main.py`）。
    · **`party_id` 故意不加外键**：它是指向 customers 或 suppliers 的**多态引用**
      （由 `party_type` 决定指向哪张表），单个外键表达不了。
      档案被删后合同必须仍然可读，所以定稿处理是「快照 + 应用层校验」，
      而不是数据库外键。详见 `_contract_module/DESIGN-PHASE1.md` 的决策矩阵。
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contract_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    template: Mapped[str] = mapped_column(String(20), default="A2", nullable=False)  # A1简约/A2标准/A3详尽/A4框架

    # 模板库里选中的那一份（`contract_templates.id`，2026-10-22）。
    # NULL = 走系统内置的《工矿产品购销合同》范本，不上传任何附件。
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_type: Mapped[str] = mapped_column(String(20), default="sales", nullable=False)  # sales 销售 / purchase 采购
    # —— 第 13 批：合同方向（与 contract_type 一一映射，out↔sales、in↔purchase）——
    # 加 index：对账/台账按方向过滤是高频路径
    direction: Mapped[str] = mapped_column(
        String(10), default="out", server_default="out", nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(150), default="购销合同", nullable=False)
    # draft 草稿 / pending 待审 / active 生效 / finished 完成 / void 作废
    # （历史值 signed / executing 仍然兼容，见 CONTRACT_STATUS）
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)

    # —— 对方单位（客户或供应商）快照 ——
    party_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # customer / supplier
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    party_tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    party_legal_person: Mapped[str | None] = mapped_column(String(50), nullable=True)
    party_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    party_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    party_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    party_bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    party_bank_account: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # —— 我方单位快照（销售合同=供方，采购合同=需方）——
    own_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    own_tax_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    own_legal_person: Mapped[str | None] = mapped_column(String(50), nullable=True)
    own_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    own_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    own_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    own_bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    own_bank_account: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # —— 签订与有效期 ——
    sign_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 签订日期
    sign_place: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 签订地点
    valid_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # —— 金额与结算 ——
    # ⚠️ Numeric(12,2) = 最大 9,999,999,999.99，两位小数。
    #    合同金额用 Float 会在累加时漂移（对账单要拿它做减法），必须定点数。
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    amount_chinese: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 金额大写（冗余，便于列表展示）
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 税率 %
    is_tax_included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # 是否含税价
    payment_terms: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 付款节点与比例
    invoice_requirement: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 开票要求

    # —— A2 条款变量 ——
    quality_standard: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 质量标准
    package_standard: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 包装标准与费用承担
    delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 交货时间
    delivery_place: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 交货地点
    delivery_method: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 交货方式
    freight_bearer: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 运输与风险承担
    inspection_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 验收期限（天）
    objection_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 质量异议期限（天）
    warranty_terms: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 质保与售后
    penalty_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 违约金日比例，0.0005=万分之五
    dispute_resolution: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 争议解决方式
    copies: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 合同份数
    service_address: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 送达地址
    other_terms: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # 补充条款

    # —— 与业务单据的关联 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 转单后回填单据 id
    order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 转单后回填单据号

    # —— 第 13 批：合同原件与 OCR ——
    # 路径一律存**相对 storage_root**（与 invoices.source_path 同口径）：
    # 存绝对路径换台机器/换盘就全失效。
    source_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 用户原始文件名
    source_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 字节
    source_file_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)  # application/pdf / image/png…
    # OCR 原始 JSON **原样保存**，不做结构化落库：
    # 识别结果一定有错，人工核对时要看到"引擎当时到底吐了什么"，
    # 只存清洗后的字段就永远说不清了。核对结论另存 ocr_status。
    ocr_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # none 未识别 / pending 识别中 / parsed 已识别待核对 / reviewed 已人工核对 / failed 识别失败
    ocr_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none", nullable=False
    )

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, onupdate=func.now(), nullable=True
    )


class ContractItem(Base):
    """合同明细（标的物清单）。

    与单据明细一样存**商品快照**：合同是历史文件，商品档案改名改价后，
    旧合同打印出来必须还是当年那份内容。

    ⚠️ **不为 `contract_id` 加外键**（第 13 批的决策，不是遗漏）：
    本表是历史表，已在三个账套里存在且由既有 ORM 代码显式"先删明细、再删主表"。
    给存量表补外键要全表校验孤儿行、失败会让服务起不来，收益只是"多一道保险"。
    新表（statements / customer_files）全部有外键，见 DESIGN-PHASE1.md 决策矩阵。
    """

    __tablename__ = "contract_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # ⚠️ 单价用 `Numeric(14, 4)` 而**不是** (12,2)：单价是"费率"不是"钱"。
    #    真实合同里 73.901 元/米这种三位单价很常见（含税↔不含税换算出来的），
    #    (12,2) 会把它四舍五入成 73.90 —— 580 米就少 0.58 元，合计对不上合同总额。
    #    金额仍是 (12,2)：钱就是分，多一位都不该有。
    unit_price: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 合同状态字典 —— 前端下拉与后端校验共用
# ⚠️ 第 13 批按需求补了 pending / active 两态，但**旧的 signed / executing 必须留着**：
#    存量数据里就写着这两个值，删掉字典项会让老合同的标签变成空白。
CONTRACT_STATUS: dict[str, str] = {
    "draft": "草稿",
    "pending": "待审",
    "active": "生效",
    "signed": "已签订",      # 旧值，等价于 active
    "executing": "执行中",   # 旧值，等价于 active
    "finished": "完成",
    "void": "作废",
}

# 合同类型字典
CONTRACT_TYPES: dict[str, str] = {
    "sales": "销售合同",
    "purchase": "采购合同",
}

# ── 第 13 批：双向合同 ──
# in  = 采购方向（我方买入 / 形成应付）
# out = 销售方向（我方卖出 / 形成应收）
CONTRACT_DIRECTIONS: dict[str, str] = {
    "in": "采购（进）",
    "out": "销售（出）",
}

DIRECTION_TO_TYPE: dict[str, str] = {"in": "purchase", "out": "sales"}
TYPE_TO_DIRECTION: dict[str, str] = {"purchase": "in", "sales": "out"}

# OCR 处理状态
CONTRACT_OCR_STATUS: dict[str, str] = {
    "none": "未识别",
    "pending": "识别中",
    "parsed": "已识别待核对",
    "reviewed": "已人工核对",
    "failed": "识别失败",
}


def normalize_direction(direction: str | None = None, contract_type: str | None = None) -> str:
    """把 `direction` / `contract_type` 归一成一个方向值（`in` / `out`）。

    **`direction` 优先**：它是第 13 批的权威字段；只有它缺失时才从老的
    `contract_type` 推。两者都缺 → 默认 `out`（与 `contract_type` 默认 sales 一致）。

    这样做的原因：前端旧版本只会传 `contract_type`，新版本只传 `direction`，
    服务端必须两种都能吃，并且**不能出现 direction=out 而 contract_type=purchase**
    这种自相矛盾的行 —— 对账单按方向取数时会被它骗。
    """
    value = str(direction or "").strip().lower()
    if value in DIRECTION_TO_TYPE:
        return value
    legacy = str(contract_type or "").strip().lower()
    return TYPE_TO_DIRECTION.get(legacy, "out")


def normalize_contract_type(direction: str | None = None, contract_type: str | None = None) -> str:
    """方向 → 老字段 `contract_type`，供仍按 sales/purchase 过滤的旧代码使用。"""
    value = str(contract_type or "").strip().lower()
    if value in TYPE_TO_DIRECTION:
        return value
    return DIRECTION_TO_TYPE[normalize_direction(direction, None)]

# 模板版本字典（A2 已落地，其余预留）
CONTRACT_TEMPLATES: dict[str, str] = {
    "A2": "购销合同 · 标准版",
}
