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
