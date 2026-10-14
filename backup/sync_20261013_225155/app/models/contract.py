from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Contract(Base):
    """购销合同（模板 A2 · 标准版）。

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
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contract_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    template: Mapped[str] = mapped_column(String(20), default="A2", nullable=False)  # A1简约/A2标准/A3详尽/A4框架
    contract_type: Mapped[str] = mapped_column(String(20), default="sales", nullable=False)  # sales 销售 / purchase 采购
    title: Mapped[str] = mapped_column(String(150), default="购销合同", nullable=False)
    # draft 草稿 / signed 已签订 / executing 执行中 / finished 已完成 / void 已作废
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
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
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

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContractItem(Base):
    """合同明细（标的物清单）。

    与单据明细一样存**商品快照**：合同是历史文件，商品档案改名改价后，
    旧合同打印出来必须还是当年那份内容。
    """

    __tablename__ = "contract_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 合同状态字典 —— 前端下拉与后端校验共用
CONTRACT_STATUS: dict[str, str] = {
    "draft": "草稿",
    "signed": "已签订",
    "executing": "执行中",
    "finished": "已完成",
    "void": "已作废",
}

# 合同类型字典
CONTRACT_TYPES: dict[str, str] = {
    "sales": "销售合同",
    "purchase": "采购合同",
}

# 模板版本字典（A2 已落地，其余预留）
CONTRACT_TEMPLATES: dict[str, str] = {
    "A2": "购销合同 · 标准版",
}
