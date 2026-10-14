from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str
    full_name: Optional[str] = None
    role: str = "staff"
    password: str = Field(..., min_length=6)


class UserRead(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str = "staff"
    is_active: bool = True
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    role: str = 'staff'
    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(BaseModel):
    code: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    # 对齐浩技云进销存的客户档案字段，全部可选
    businesser: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    tax_no: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    level: Optional[str] = None
    discount: Optional[float] = None
    credit_limit: Optional[float] = None
    init_receivable: Optional[float] = None
    init_invoice_debt: Optional[float] = None
    relation_date: Optional[str] = None
    business_type: Optional[str] = None
    main_products: Optional[str] = None
    potential_amount: Optional[float] = None
    note: Optional[str] = None


class CustomerRead(CustomerCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SupplierCreate(BaseModel):
    code: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    # 对齐浩技云进销存的供应商档案字段，全部可选
    short_name: Optional[str] = None
    contact: Optional[str] = None
    main_contact: Optional[str] = None
    mobile: Optional[str] = None
    postcode: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    init_payable: Optional[float] = None
    init_invoice_debt: Optional[float] = None
    note: Optional[str] = None


class SupplierRead(SupplierCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    purchase_price: float = 0.0
    sale_price: float = 0.0
    # 对齐浩技云进销存的商品档案字段，全部可选
    mnemonic: Optional[str] = None
    standards: Optional[str] = None
    brand: Optional[str] = None
    bar_code: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_no: Optional[str] = None
    unit_weight: Optional[float] = None
    stock_upper: Optional[int] = None
    stock_lower: Optional[int] = None
    pack_qty: Optional[int] = None
    shelf_life: Optional[int] = None
    warn_days: Optional[int] = None
    image_url: Optional[str] = None
    note: Optional[str] = None


class ProductRead(ProductCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class WarehouseCreate(BaseModel):
    code: str
    name: str
    location: Optional[str] = None
    manager: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    note: Optional[str] = None


class WarehouseRead(WarehouseCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float
    product_name: Optional[str] = None  # 明细快照，打印单据用
    standards: Optional[str] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    order_no: Optional[str] = None  # 不传则按 CG+日期+序号 自动生成
    items: list[PurchaseOrderItemCreate]
    # 单据性质：order=采购订单（只订货，不动库存财务） / inbound=采购入库单（默认）
    doc_type: Optional[str] = None
    # 单据头（可选）
    warehouse_id: Optional[int] = None
    businesser: Optional[str] = None
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_method: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    # 结算链：不传 discount_amount / paid_amount 时视为"本单全额挂账"（实付 0）
    discount_amount: float = 0.0
    paid_amount: Optional[float] = None
    is_invoiced: bool = False


class PurchaseOrderItemRead(PurchaseOrderItemCreate):
    id: int
    purchase_order_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderRead(PurchaseOrderCreate):
    id: int
    status: str
    total_amount: float
    doc_type: str = "inbound"
    source_order_id: Optional[int] = None
    payable_amount: float = 0.0
    current_debt: float = 0.0
    prev_debt: float = 0.0
    total_debt: float = 0.0
    created_at: datetime
    items: list[PurchaseOrderItemRead] = []
    model_config = ConfigDict(from_attributes=True)


class SalesOrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: float
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    note: Optional[str] = None


class SalesOrderCreate(BaseModel):
    customer_id: int
    order_no: Optional[str] = None  # 不传则按 XS+日期+序号 自动生成
    items: list[SalesOrderItemCreate]
    # 单据性质：order=销售订单（只订货，不动库存财务） / outbound=销售开单（默认）
    doc_type: Optional[str] = None
    # 单据头（可选）
    warehouse_id: Optional[int] = None
    businesser: Optional[str] = None
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_method: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    # 结算链
    discount_amount: float = 0.0
    received_amount: Optional[float] = None
    is_invoiced: bool = False


class SalesOrderItemRead(SalesOrderItemCreate):
    id: int
    sales_order_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class SalesOrderRead(SalesOrderCreate):
    id: int
    status: str
    total_amount: float
    doc_type: str = "outbound"
    source_order_id: Optional[int] = None
    receivable_amount: float = 0.0
    current_debt: float = 0.0
    prev_debt: float = 0.0
    total_debt: float = 0.0
    created_at: datetime
    items: list[SalesOrderItemRead] = []
    model_config = ConfigDict(from_attributes=True)


class InventoryTransactionCreate(BaseModel):
    product_id: int
    warehouse_id: int
    transaction_type: str
    quantity: int
    unit_price: float = 0.0


class InventoryTransactionRead(InventoryTransactionCreate):
    id: int
    created_at: datetime
    # 溯源字段：这条流水由哪张单产生（手工录入的流水这几个字段为空）
    related_type: Optional[str] = None
    related_order_id: Optional[int] = None
    doc_no: Optional[str] = None
    note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class FinancialTransactionCreate(BaseModel):
    transaction_type: str
    amount: float
    currency: str = "CNY"
    note: Optional[str] = None
    related_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    supplier_id: Optional[int] = None
    # 财务 × 全模块关联（可选）
    related_type: Optional[str] = None  # 单据类型，取值见 app.models.finance.DOC_TYPES
    doc_no: Optional[str] = None
    direction: Optional[str] = None  # in / out
    product_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    project_id: Optional[int] = None
    occurred_at: Optional[str] = None  # YYYY-MM-DD，不传取当天
    period: Optional[str] = None  # YYYY-MM，不传由 occurred_at 推导


class FinancialTransactionRead(FinancialTransactionCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InvoiceCreate(BaseModel):
    invoice_no: str
    invoice_type: str = "普票"
    issue_date: Optional[str] = None
    counterparty_name: Optional[str] = None
    invoice_code: Optional[str] = None
    total_amount: float = 0.0
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None
    excl_tax_amount: Optional[float] = None
    deducted: bool = False
    category: Optional[str] = None
    status: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_tax_no: Optional[str] = None
    seller_name: Optional[str] = None
    seller_tax_no: Optional[str] = None
    items: list[dict] = []
    raw_text: Optional[str] = None


class InvoiceUpdate(BaseModel):
    invoice_type: Optional[str] = None
    deducted: Optional[bool] = None
    category: Optional[str] = None
    status: Optional[str] = None


class InvoiceRead(InvoiceCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BillOfMaterialCreate(BaseModel):
    product_id: int
    component_product_id: int
    quantity: int = 1
    unit_cost: float = 0.0
    note: Optional[str] = None
    parent_id: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    bom_type: str = "component"
    level: int = 0
    description: Optional[str] = None


class BillOfMaterialRead(BillOfMaterialCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductionOrderCreate(BaseModel):
    product_id: int
    bom_id: Optional[int] = None
    order_no: str
    quantity: int = 1
    status: str = "planned"
    priority: str = "normal"
    note: Optional[str] = None


class ProductionOrderRead(ProductionOrderCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    code: str
    name: str
    manager: Optional[str] = None
    status: str = "planned"
    progress: int = 0
    budget: float = 0.0
    deadline: Optional[str] = None
    note: Optional[str] = None


class ProjectRead(ProjectCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# 融合改造：购销合同（模板 A2 · 标准版）
# ============================================================================


class ContractItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class ContractItemRead(ContractItemCreate):
    id: int
    contract_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class ContractCreate(BaseModel):
    contract_type: str = "sales"  # sales 销售合同 / purchase 采购合同
    template: str = "A2"
    title: Optional[str] = None
    contract_no: Optional[str] = None  # 不传则按 HT+日期+序号 自动生成
    status: Optional[str] = None
    items: list[ContractItemCreate] = []

    # 对方单位（客户或供应商）
    party_type: Optional[str] = None
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    party_tax_no: Optional[str] = None
    party_legal_person: Optional[str] = None
    party_address: Optional[str] = None
    party_contact: Optional[str] = None
    party_phone: Optional[str] = None
    party_bank_name: Optional[str] = None
    party_bank_account: Optional[str] = None

    # 我方单位
    own_name: Optional[str] = None
    own_tax_no: Optional[str] = None
    own_legal_person: Optional[str] = None
    own_address: Optional[str] = None
    own_contact: Optional[str] = None
    own_phone: Optional[str] = None
    own_bank_name: Optional[str] = None
    own_bank_account: Optional[str] = None

    # 签订与有效期
    sign_date: Optional[str] = None
    sign_place: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    # 金额与结算
    tax_rate: Optional[float] = None
    is_tax_included: bool = True
    payment_terms: Optional[str] = None
    invoice_requirement: Optional[str] = None

    # A2 条款变量
    quality_standard: Optional[str] = None
    package_standard: Optional[str] = None
    delivery_date: Optional[str] = None
    delivery_place: Optional[str] = None
    delivery_method: Optional[str] = None
    freight_bearer: Optional[str] = None
    inspection_days: Optional[int] = None
    objection_days: Optional[int] = None
    warranty_terms: Optional[str] = None
    penalty_rate: Optional[float] = None
    dispute_resolution: Optional[str] = None
    copies: Optional[int] = None
    service_address: Optional[str] = None
    other_terms: Optional[str] = None

    # 关联
    warehouse_id: Optional[int] = None
    note: Optional[str] = None


class ContractRead(ContractCreate):
    id: int
    contract_no: str
    status: str
    total_amount: float
    amount_chinese: Optional[str] = None
    order_id: Optional[int] = None
    order_no: Optional[str] = None
    created_at: datetime
    items: list[ContractItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 采购退货 ——————————————————————
class PurchaseReturnItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class PurchaseReturnItemRead(PurchaseReturnItemCreate):
    id: int
    purchase_return_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class PurchaseReturnCreate(BaseModel):
    return_no: Optional[str] = None  # 不传则按 CGTH+日期+序号 自动生成
    supplier_id: int
    # 供应商快照（选档案后自动带出）
    supplier_name: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    # 单据头
    warehouse_id: Optional[int] = None
    businesser: Optional[str] = None
    return_date: Optional[str] = None
    return_reason: Optional[str] = None
    payment_method: Optional[str] = None
    note: Optional[str] = None
    # 溯源：可选来源入库单/采购单
    source_order_id: Optional[int] = None
    source_order_no: Optional[str] = None
    status: Optional[str] = None
    items: list[PurchaseReturnItemCreate] = []


class PurchaseReturnRead(PurchaseReturnCreate):
    id: int
    return_no: str
    status: str
    total_amount: float
    amount_chinese: Optional[str] = None
    created_at: datetime
    items: list[PurchaseReturnItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 销售退货 ——————————————————————
class SalesReturnItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class SalesReturnItemRead(SalesReturnItemCreate):
    id: int
    sales_return_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class SalesReturnCreate(BaseModel):
    return_no: Optional[str] = None  # 不传则按 XSTH+日期+序号 自动生成
    customer_id: int
    # 客户快照（选档案后自动带出）
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    # 单据头
    warehouse_id: Optional[int] = None
    businesser: Optional[str] = None
    return_date: Optional[str] = None
    return_reason: Optional[str] = None
    payment_method: Optional[str] = None
    note: Optional[str] = None
    # 溯源：可选来源出库单/销售单
    source_order_id: Optional[int] = None
    source_order_no: Optional[str] = None
    status: Optional[str] = None
    items: list[SalesReturnItemCreate] = []


class SalesReturnRead(SalesReturnCreate):
    id: int
    return_no: str
    status: str
    total_amount: float
    amount_chinese: Optional[str] = None
    created_at: datetime
    items: list[SalesReturnItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 销售报价单 ——————————————————————
class QuotationItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class QuotationItemRead(QuotationItemCreate):
    id: int
    quotation_id: int
    amount: float
    model_config = ConfigDict(from_attributes=True)


class QuotationCreate(BaseModel):
    quote_no: Optional[str] = None  # 不传则按 BJ+日期+序号 自动生成
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_address: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    fax: Optional[str] = None
    quote_date: Optional[str] = None
    valid_until: Optional[str] = None
    warehouse_id: Optional[int] = None
    businesser: Optional[str] = None
    payment_method: Optional[str] = None
    transport_method: Optional[str] = None
    delivery_place: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    items: list[QuotationItemCreate] = []


class QuotationRead(QuotationCreate):
    id: int
    quote_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float
    amount_chinese: Optional[str] = None
    order_id: Optional[int] = None
    order_no: Optional[str] = None
    created_at: datetime
    items: list[QuotationItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 库存调拨 ——————————————————————
class InventoryTransferItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class InventoryTransferItemRead(InventoryTransferItemCreate):
    id: int
    inventory_transfer_id: int
    model_config = ConfigDict(from_attributes=True)


class InventoryTransferCreate(BaseModel):
    transfer_no: Optional[str] = None  # 不传则按 DBD+日期+序号 自动生成
    from_warehouse_id: int  # 调出仓库
    to_warehouse_id: int  # 调入仓库
    transfer_date: Optional[str] = None
    handler: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[InventoryTransferItemCreate] = []


class InventoryTransferRead(InventoryTransferCreate):
    id: int
    transfer_no: str
    status: str
    total_quantity: float = 0.0
    created_at: datetime
    items: list[InventoryTransferItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 库存盘点 ——————————————————————
class StocktakingItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    # book_quantity 不传时后端按当前现存量带出（盘点底稿就是这么生成的）
    book_quantity: Optional[float] = None
    actual_quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class StocktakingItemRead(BaseModel):
    id: int
    stocktaking_id: int
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    book_quantity: float = 0.0
    actual_quantity: float = 0.0
    diff_quantity: float = 0.0
    unit_price: float = 0.0
    amount: float = 0.0
    note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class StocktakingCreate(BaseModel):
    check_no: Optional[str] = None  # 不传则按 PD+日期+序号 自动生成
    warehouse_id: int  # 盘点仓库
    check_date: Optional[str] = None
    handler: Optional[str] = None
    scope: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[StocktakingItemCreate] = []


class StocktakingRead(StocktakingCreate):
    id: int
    check_no: str
    status: str
    total_profit: float = 0.0
    total_loss: float = 0.0
    profit_lines: int = 0
    loss_lines: int = 0
    total_amount: float = 0.0
    created_at: datetime
    items: list[StocktakingItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 报损报溢 ——————————————————————
class InventoryAdjustmentItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0  # 恒正，方向看单据头 adjust_type
    unit_price: float = 0.0
    note: Optional[str] = None


class InventoryAdjustmentItemRead(InventoryAdjustmentItemCreate):
    id: int
    inventory_adjustment_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class InventoryAdjustmentCreate(BaseModel):
    adjust_no: Optional[str] = None  # 不传则按 BS/BY+日期+序号 自动生成
    adjust_type: str = "scrap"  # scrap 报损 / overflow 报溢
    warehouse_id: int
    adjust_date: Optional[str] = None
    handler: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[InventoryAdjustmentItemCreate] = []


class InventoryAdjustmentRead(InventoryAdjustmentCreate):
    id: int
    adjust_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float = 0.0
    created_at: datetime
    items: list[InventoryAdjustmentItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 生产计划 ——————————————————————
class ProductionPlanItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0  # 计划生产数量
    unit_price: float = 0.0  # 计划单位成本
    bom_id: Optional[int] = None  # 关联 BOM 根节点（MRP / 领料按它展开）
    note: Optional[str] = None


class ProductionPlanItemRead(ProductionPlanItemCreate):
    id: int
    production_plan_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class ProductionPlanCreate(BaseModel):
    plan_no: Optional[str] = None  # 不传则按 SCJH/WWJH+日期+序号 自动生成
    plan_type: str = "self"  # self 自制 / outsource 委外
    warehouse_id: Optional[int] = None
    plan_date: Optional[str] = None
    delivery_date: Optional[str] = None
    handler: Optional[str] = None
    workshop: Optional[str] = None
    source_order_id: Optional[int] = None
    source_order_no: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    items: list[ProductionPlanItemCreate] = []


class ProductionPlanRead(ProductionPlanCreate):
    id: int
    plan_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float = 0.0
    created_at: datetime
    items: list[ProductionPlanItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 生产领料 ——————————————————————
class MaterialIssueItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class MaterialIssueItemRead(MaterialIssueItemCreate):
    id: int
    material_issue_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class MaterialIssueCreate(BaseModel):
    issue_no: Optional[str] = None  # 不传则按 SCLL+日期+序号 自动生成
    plan_id: Optional[int] = None  # 关联生产计划（可空）
    plan_no: Optional[str] = None
    warehouse_id: Optional[int] = None  # 领料仓库
    issue_date: Optional[str] = None
    workshop: Optional[str] = None
    handler: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[MaterialIssueItemCreate] = []


class MaterialIssueRead(MaterialIssueCreate):
    id: int
    issue_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float = 0.0
    created_at: datetime
    items: list[MaterialIssueItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 生产退料 ——————————————————————
class MaterialReturnItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class MaterialReturnItemRead(MaterialReturnItemCreate):
    id: int
    material_return_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class MaterialReturnCreate(BaseModel):
    return_no: Optional[str] = None  # 不传则按 SCTL+日期+序号 自动生成
    plan_id: Optional[int] = None
    plan_no: Optional[str] = None
    warehouse_id: Optional[int] = None  # 退料仓库
    return_date: Optional[str] = None
    workshop: Optional[str] = None
    handler: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[MaterialReturnItemCreate] = []


class MaterialReturnRead(MaterialReturnCreate):
    id: int
    return_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float = 0.0
    created_at: datetime
    items: list[MaterialReturnItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 成品入库 ——————————————————————
class FinishedGoodsItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class FinishedGoodsItemRead(FinishedGoodsItemCreate):
    id: int
    finished_goods_receipt_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class FinishedGoodsCreate(BaseModel):
    receipt_no: Optional[str] = None  # 不传则按 CPRK+日期+序号 自动生成
    plan_id: Optional[int] = None
    plan_no: Optional[str] = None
    warehouse_id: Optional[int] = None  # 成品入库仓
    receipt_date: Optional[str] = None
    workshop: Optional[str] = None
    handler: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: list[FinishedGoodsItemCreate] = []


class FinishedGoodsRead(FinishedGoodsCreate):
    id: int
    receipt_no: str
    status: str
    total_quantity: float = 0.0
    total_amount: float = 0.0
    created_at: datetime
    items: list[FinishedGoodsItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 委外加工 ——————————————————————
class OutsourcingItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class OutsourcingItemRead(OutsourcingItemCreate):
    id: int
    outsourcing_order_id: int
    amount: float = 0.0
    model_config = ConfigDict(from_attributes=True)


class OutsourcingCreate(BaseModel):
    order_no: Optional[str] = None  # 不传则按 WWJG+日期+序号 自动生成
    supplier_id: Optional[int] = None  # 外协加工商
    warehouse_id: Optional[int] = None  # 发料 / 收料仓
    order_date: Optional[str] = None
    handler: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    # 加工产出（成品）
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0.0
    unit_price: float = 0.0
    process_fee: float = 0.0  # 加工费总额（对外协厂的应付）
    items: list[OutsourcingItemCreate] = []


class OutsourcingRead(OutsourcingCreate):
    id: int
    order_no: str
    status: str
    total_amount: float = 0.0  # 发出材料成本合计
    created_at: datetime
    items: list[OutsourcingItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 系统管理（第 5 批）—— 组织机构 / 角色 / 用户
# ============================================================
class DepartmentCreate(BaseModel):
    code: Optional[str] = None  # 不传则自动按 DEPT+序号 生成
    name: str
    parent_id: Optional[int] = None
    leader: Optional[str] = None
    phone: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    note: Optional[str] = None


class DepartmentUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    parent_id: Optional[int] = None
    leader: Optional[str] = None
    phone: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    note: Optional[str] = None


class DepartmentRead(BaseModel):
    id: int
    code: str
    name: str
    parent_id: Optional[int] = None
    leader: Optional[str] = None
    phone: Optional[str] = None
    level: int = 0
    sort_order: int = 0
    is_active: bool = True
    note: Optional[str] = None
    # 只读统计：便于前端在树上直接显示"这个部门有几个人"，不用再发一轮请求
    user_count: int = 0
    children: list["DepartmentRead"] = []
    model_config = ConfigDict(from_attributes=True)


class RoleCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    permissions: dict = {}
    sort_order: int = 0
    is_active: bool = True


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[dict] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class RoleRead(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    permissions: dict = {}
    is_builtin: bool = False
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime
    # 只读统计：该角色下有多少在职用户（删除前的提示依据）
    user_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class SystemUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: str = Field(..., min_length=6)
    role_id: Optional[int] = None
    role: Optional[str] = None  # 角色 code，不传则按 role_id 反查
    department_id: Optional[int] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    remark: Optional[str] = None
    is_active: bool = True


class SystemUserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role_id: Optional[int] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    remark: Optional[str] = None
    is_active: Optional[bool] = None


class SystemUserRead(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "staff"
    role_id: Optional[int] = None
    role_name: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    remark: Optional[str] = None
    is_active: bool = True
    last_login_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6)


# ============================================================
# 系统管理（第 5 批第 2 轮）—— 参数设置 / 数字字典
# ============================================================
class SystemParamCreate(BaseModel):
    param_key: str = Field(..., min_length=2, max_length=80)
    param_value: str = ""
    param_group: str = "system"
    label: str = Field(..., min_length=1, max_length=80)
    value_type: str = "string"
    description: Optional[str] = None
    sort_order: int = 0


class SystemParamUpdate(BaseModel):
    param_value: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    value_type: Optional[str] = None
    param_group: Optional[str] = None
    sort_order: Optional[int] = None


class SystemParamRead(BaseModel):
    id: int
    param_key: str
    param_value: str = ""
    param_group: str = "system"
    label: str
    value_type: str = "string"
    description: Optional[str] = None
    is_editable: bool = True
    sort_order: int = 0
    # 内置默认值：前端「恢复默认」按钮要用
    default_value: str = ""
    model_config = ConfigDict(from_attributes=True)


class ParamValueIn(BaseModel):
    param_key: str
    param_value: str


class ParamBatchSave(BaseModel):
    items: list[ParamValueIn] = []


class DictionaryCreate(BaseModel):
    dict_type: str = Field(..., min_length=2, max_length=60)
    dict_name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = None
    is_active: bool = True


class DictionaryUpdate(BaseModel):
    dict_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DictionaryRead(BaseModel):
    id: int
    dict_type: str
    dict_name: str
    description: Optional[str] = None
    is_system: bool = False
    is_active: bool = True
    created_at: datetime
    # 只读统计：该字典下有多少项（含停用），列表页直接显示
    item_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class DictionaryItemCreate(BaseModel):
    item_value: str = Field(..., min_length=1, max_length=80)
    item_label: Optional[str] = None  # 不传则与 item_value 相同
    sort_order: int = 0
    is_enabled: bool = True
    remark: Optional[str] = None


class DictionaryItemUpdate(BaseModel):
    item_value: Optional[str] = None
    item_label: Optional[str] = None
    sort_order: Optional[int] = None
    is_enabled: Optional[bool] = None
    remark: Optional[str] = None


class DictionaryItemRead(BaseModel):
    id: int
    dict_type: str
    item_value: str
    item_label: str
    sort_order: int = 0
    is_enabled: bool = True
    remark: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 系统管理（第 5 批第 3 轮）—— 打印模板 / 操作日志
# ============================================================
class PrintTemplateUpdate(BaseModel):
    """模板只改外观项：渲染器不支持的字段这里不存在（见 models/print_template.py）。"""

    name: Optional[str] = None
    title: Optional[str] = None
    header_text: Optional[str] = None
    footer_text: Optional[str] = None
    show_company: Optional[bool] = None
    show_signatures: Optional[bool] = None
    note: Optional[str] = None


class PrintTemplateRead(BaseModel):
    id: int
    doc_type: str
    doc_label: str
    name: str
    title: str
    header_text: str
    footer_text: str
    show_company: bool = True
    show_signatures: bool = True
    note: Optional[str] = None
    sort_order: int = 0
    # 该 doc_type 是否仍在打印注册表里（false = 打印入口已下线，模板成了孤儿）
    registered: bool = True
    # 出厂默认值快照，供前端「恢复默认」
    default_title: str = ""
    default_name: str = ""
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class OperationLogRead(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: str = ""
    role: str = ""
    method: str = ""
    path: str = ""
    action: str = ""
    target_type: str = ""
    target_id: Optional[int] = None
    status_code: int = 0
    duration_ms: int = 0
    ip: str = ""
    user_agent: str = ""
    detail: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class OperationLogPage(BaseModel):
    items: list[OperationLogRead] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    pages: int = 1
    # 筛选下拉用的候选（出现过的方法 / 用户）
    methods: list[str] = []
    users: list[str] = []


# ============================================================
# 员工档案（基础资料收尾）
# ============================================================
class EmployeeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=80)
    gender: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    id_card: Optional[str] = None
    hire_date: Optional[str] = None
    leave_date: Optional[str] = None
    status: str = "active"
    base_salary: Optional[float] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    emergency_contact: Optional[str] = None
    emergency_phone: Optional[str] = None
    note: Optional[str] = None


class EmployeeRead(EmployeeCreate):
    id: int
    # 只读派生：部门名（列表页直接显示，不必前端再查一次组织树）
    department_name: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 组合拆卸（库存管理）
# ============================================================
class AssemblyItemIn(BaseModel):
    """子件明细入参。数量是**总用量**（已按成品数量折算），前端可从 BOM 带出后修改。"""

    product_id: int
    quantity: float = Field(..., gt=0)
    unit_price: Optional[float] = None
    note: Optional[str] = None


class AssemblyOrderCreate(BaseModel):
    doc_type: str = "combo"
    product_id: int
    quantity: int = Field(..., gt=0)
    warehouse_id: Optional[int] = None
    order_date: Optional[str] = None
    handler: Optional[str] = None
    note: Optional[str] = None
    items: list[AssemblyItemIn] = []


class AssemblyOrderItemRead(BaseModel):
    id: int
    assembly_order_id: int
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: float = 0
    unit_price: float = 0
    note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class AssemblyOrderRead(BaseModel):
    id: int
    order_no: str
    doc_type: str = "combo"
    doc_type_label: str = ""
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    product_id: int
    product_name: Optional[str] = None
    standards: Optional[str] = None
    unit: Optional[str] = None
    quantity: int = 1
    total_quantity: float = 0
    order_date: Optional[str] = None
    handler: Optional[str] = None
    note: Optional[str] = None
    status: str = "submitted"
    created_at: datetime
    items: list[AssemblyOrderItemRead] = []
    # 库存不足等提示。必须在响应模型里声明 —— 否则 FastAPI 会把附加字段剥掉，
    # 前端永远拿不到"这一单会欠货"的提醒。
    warnings: list[str] = []
    model_config = ConfigDict(from_attributes=True)
