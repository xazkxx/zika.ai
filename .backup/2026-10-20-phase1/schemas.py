from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

# ===========================================================================
# 金额 / 单价类型（2026-10-19 金额精度升级）
# ===========================================================================
# 内部一律 **Decimal**：数据库列已经是 numeric(14,2) / numeric(14,4)，psycopg
# 读出来也是 Decimal —— 在 schema 里写回 float，等于把已经对齐到分位的钱重新
# 扔回二进制浮点，`Decimal + float` 还会当场 TypeError。
#
# 但 **JSON 出参必须是数字**：pydantic v2 默认把 Decimal 序列化成 "42862.58"
# 这种**字符串**，前端 `Number(x)` 之外的地方（`a + b` 变字符串拼接、`.toFixed`
# 直接报错）会当场炸。所以统一用下面两个 Annotated：
#   · 校验 / 内部计算 → Decimal（钱精确到分，单价精确到万分之一）
#   · JSON 序列化     → float（前端拿到的仍是 42862.58 这个数字）
#
# ⚠️ 别在 schema 里退回去写 `float`：那样 Decimal 一进 validate 就被 float() 了。
# ⚠️ 也别直接写 `Decimal`：接口会返回字符串，前端每一处 `+` 都可能变拼接。
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
MoneyRate = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]

# ⚠️ 对账单的金额推导**只能有一份实现**：模型层 `app/models/statement.py` 里那两个
#    纯函数就是唯一口径。schema 这里若自己再写一遍 round(float(...))，
#    两份公式迟早分叉 —— 表现是"接口校验算出来的未开票"和"对账单落库里的"差一分钱。
from app.models.statement import derive_item_amounts, infer_invoice_status


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
    # 可选：这次登录进哪个账套（账套号或 schema 名）。
    # 不传就用该用户的默认账套 —— 老前端不带这个字段也能正常登录。
    company: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    role: str = 'staff'
    # 当前账套（schema 名）与该用户可进入的账套清单。
    # 前端靠它们渲染顶栏的账套切换与当前公司名。
    company: Optional[str] = None
    company_name: Optional[str] = None
    companies: list[dict] = []
    model_config = ConfigDict(from_attributes=True)


class CustomerCreate(BaseModel):
    # 编码**留空即自动生成**（CUS + 日期 + 3 位流水，路由层 `_next_doc_no`）；
    # 仍允许手填（导入老数据时保留原编码）。编辑态锁定：CustomerUpdate 传不同值 → 400。
    code: Optional[str] = None
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
    # 所属分类（`customer_categories.id`）。NULL = 未分类 —— 存量 25 位客户全在这一档，
    # 不强制必填，否则光是迁移就得先给每一条编一个分类。
    category_id: Optional[int] = None


class CustomerRead(CustomerCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CustomerUpdate(BaseModel):
    """客户档案的**部分更新**（PATCH）。

    ⚠️ 这里故意**保留** `code` 字段，但路由层只要发现"传了且与库里不同"就直接 400。
    为什么不用 `extra="ignore"` 静默丢掉：调用方以为改成功了、界面上编码却还是旧的，
    这种"静默不生效"比报错难查一个数量级。编码是档案的业务主键 —— 单据、对账、
    打印模板都存着它，改了会让历史单据指向另一个人。

    其余字段全部 `None` 默认 + 路由层 `exclude_unset=True`：
    **没传 ≠ 置空**。前端只发改过的字段也不会把别的列清掉。
    """

    code: Optional[str] = None  # 允许传（便于给出明确报错），但值必须与库里一致
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
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
    # 显式传 null = 移到「未分类」；不传 = 分类不动（`exclude_unset` 口径）。
    # 想让"清空分类"和"没改分类"变成两件事，就必须留着这个字段而不是靠 `or None`。
    category_id: Optional[int] = None


class SupplierCreate(BaseModel):
    # 编码留空自动生成（SUP + 日期 + 流水），口径同 CustomerCreate.code。
    code: Optional[str] = None
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
    category_id: Optional[int] = None  # 所属分类（`supplier_categories.id`），NULL = 未分类


class SupplierRead(SupplierCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SupplierUpdate(BaseModel):
    """供应商档案的部分更新（PATCH）。编码锁定规则同 `CustomerUpdate`。"""

    code: Optional[str] = None  # 同上：可传，但必须与库里一致
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
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
    # 显式传 null = 移到「未分类」；不传 = 分类不动（同 `CustomerUpdate`）。
    category_id: Optional[int] = None


class ProductUnitInput(BaseModel):
    """辅助单位的**写入**形态（新增商品时随商品一起提交，一个事务）。

    `factor` 的下界这里先挡一道（`ge=2`），数据库再挡一道（`CHECK factor >= 2`）。
    两层都留着不是重复：pydantic 只管 API 入口，将来若有人直接写 SQL 或批量导入
    脚本，就只剩那条 CHECK 了。

    `factor` ＝ 「1 个本行单位 = factor 个基本单位」。

    ⚠️ **不提供 `sort_order` 字段**：顺序就是提交顺序（后端写下标）。
    让前端传一个"排序号"没有意义 —— 界面上看见的顺序就是它。
    """

    unit_name: str = Field(..., min_length=1, max_length=50)
    factor: int = Field(..., ge=2, le=999999)
    price: Optional[float] = None
    sale_price: Optional[float] = None
    bar_code: Optional[str] = Field(None, max_length=80)
    is_default: bool = False
    is_enabled: bool = True
    note: Optional[str] = Field(None, max_length=255)


class ProductUnitRead(ProductUnitInput):
    id: int
    product_id: int
    sort_order: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class _ProductFields(BaseModel):
    """商品的字段本体（新增 / 读取共用的那一份）。

    为什么不直接把 `units` 加在原来的 `ProductCreate` 上：

    原来写的是 `class ProductRead(ProductCreate)`。一旦给 `ProductCreate` 加
    `units`，`ProductRead` 会**跟着继承**一个 `units` 字段 —— 而商品列表接口
    `GET /products` 返回的是 `Product` ORM 对象，它根本没有 `units` 属性，
    于是 261 行商品会**每行都报一个 `units: []`**。那不是"空"，是 API 撒谎：
    商品明明配了辅助单位，列表却说没有，而且改成真值就得 N+1 查询。

    拆出这层基类之后两边各自干净：`ProductCreate` 有 `units`，`ProductRead` 没有。
    """

    sku: str
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    purchase_price: float = 0.0
    sale_price: float = 0.0
    # 默认税率（%）。留空是**刻意**的：货物 13 / 农产品 9 / 服务 6 各档不同，
    # 给个默认值用户不改就会开错票。
    tax_rate: Optional[float] = None
    # 对齐浩技云进销存的商品档案字段，全部可选
    mnemonic: Optional[str] = None
    standards: Optional[str] = None
    brand: Optional[str] = None
    bar_code: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    # 生产厂家：name 是**快照**（供应商改名/删除后历史单据与列表仍显示原名字），
    # manufacturer_id 才是真关联。故意不加外键（本库只有 3 个 FK，靠应用层保证）。
    manufacturer: Optional[str] = None
    manufacturer_id: Optional[int] = None
    serial_no: Optional[str] = None
    unit_weight: Optional[float] = None
    stock_upper: Optional[int] = None
    stock_lower: Optional[int] = None
    pack_qty: Optional[int] = None
    shelf_life: Optional[int] = None
    warn_days: Optional[int] = None
    image_url: Optional[str] = None
    note: Optional[str] = None


class ProductCreate(_ProductFields):
    """新增商品。`units` 与商品本体在**同一个事务**里落库（用户 2026-10-16 拍板）。

    默认 `[]`：不带辅助单位的商品，行为与加这个字段之前**逐字节相同**。
    """

    units: list[ProductUnitInput] = Field(default_factory=list)


class ProductRead(_ProductFields):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductUpdate(BaseModel):
    """改商品：除 SKU 外全部可选，只改传了的字段。

    刻意不提供改 `sku` 的入口 —— SKU 是商品的唯一标识，单据、库存流水、
    打印模板里都在引用它，改了会让历史对不上。要改编号就新建一个商品。
    """

    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    purchase_price: Optional[float] = None
    sale_price: Optional[float] = None
    tax_rate: Optional[float] = None
    mnemonic: Optional[str] = None
    standards: Optional[str] = None
    brand: Optional[str] = None
    bar_code: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    # 生产厂家：name 是**快照**（供应商改名/删除后历史单据与列表仍显示原名字），
    # manufacturer_id 才是真关联。故意不加外键（本库只有 3 个 FK，靠应用层保证）。
    manufacturer: Optional[str] = None
    manufacturer_id: Optional[int] = None
    serial_no: Optional[str] = None
    unit_weight: Optional[float] = None
    stock_upper: Optional[int] = None
    stock_lower: Optional[int] = None
    pack_qty: Optional[int] = None
    shelf_life: Optional[int] = None
    warn_days: Optional[int] = None
    image_url: Optional[str] = None
    note: Optional[str] = None
    # 辅助单位（2026-10-16 第三阶段）：与商品字段**同一个事务**提交。
    #
    # 三种情况必须分清（靠 `model_dump(exclude_unset=True)` 区分）：
    #   · 请求体里**没有** `units` 这个键 → 一个字段都不碰（老客户端 / 列表页批量改价）
    #   · `units: []`                      → 清空该商品的全部辅助单位
    #   · `units: null`                    → 按"不碰"处理（显式的 null 不当作清空，
    #                                        避免任何"手滑传 null 就清库"的可能）
    units: Optional[list[ProductUnitInput]] = None


class ProductCategoryCreate(BaseModel):
    """商品类别（多级树）：name 在同一父级下唯一。"""

    name: str
    parent_id: Optional[int] = None
    sort_order: int = 0
    note: Optional[str] = None


class ProductCategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    note: Optional[str] = None


class ProductCategoryRead(ProductCategoryCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductCategoryNode(ProductCategoryRead):
    """树形节点：给前端左侧类别树用，children 递归嵌套。"""

    children: list["ProductCategoryNode"] = []


# ============================================================================
# 客户 / 供应商分类（真实物理表 · 无限极 · 每个账套各一棵）
#
# 与 `product_categories` 的关系：形状一致（前端同一套树组件能吃），但档案挂的是
# `category_id` 而不是节点名 —— 所以**改分类名不会产生孤儿**，也不受"跨分支重名"困扰。
# 详见 `app/models/partner_category.py` 的模块注释。
# ============================================================================


class PartnerCategoryCreate(BaseModel):
    """分类节点（新建）。`name` 在同一父级下唯一：路由层给中文 400，库里有部分唯一索引兜底。"""

    name: str
    parent_id: Optional[int] = None
    sort_order: int = 0
    note: Optional[str] = None


class PartnerCategoryUpdate(BaseModel):
    """分类节点（PATCH）。

    ⚠️ `parent_id` 的语义要靠 `exclude_unset` 区分，前端必须搞清楚这两件事：
      · **不传** `parent_id` → 层级不动；
      · **显式传 `null`**   → 移到顶级（拖到根节点就用这个）。
    少一个字段都不行 —— 所以这里不能写 `if parent_id is None: 当没传`。
    """

    name: Optional[str] = None
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None
    note: Optional[str] = None


class PartnerCategoryMove(BaseModel):
    """拖拽落点（`POST /xxx-categories/{id}/move`）。

    前端只发"放到哪个父级下、排在谁前面"，`sort_order` 由服务端整段重排成 10/20/30…
    让前端自己算序号，一定会和别人的拖拽打架（两边都写 15，顺序就随机了）。

    `before_id = null` 表示"排到该父级下最后"。若 `before_id` 不属于 `parent_id`，
    服务端按"追加到末尾"处理而不是报错 —— 拖拽时前后端对落点理解有偏差是常态，
    这种情况下用户看到的是"没排到我以为的位置"，比弹一个错误框好得多。
    """

    parent_id: Optional[int] = None
    before_id: Optional[int] = None


class CustomerCategoryCreate(PartnerCategoryCreate):
    """客户分类新建。字段与供应商侧完全一致，单独命名只为 OpenAPI 文档可读。"""


class CustomerCategoryUpdate(PartnerCategoryUpdate):
    """客户分类更新。"""


class CustomerCategoryRead(PartnerCategoryCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CustomerCategoryNode(CustomerCategoryRead):
    """客户分类树节点。

    · `count` = **直接**挂在本节点下的客户数
    · `total` = 含所有子孙的合计

    两个都要给：左侧导航显示的是 `total`（父节点显示 0 会让人以为没数据），
    点中某个节点后列表上方的「x / y 位」要的是 `count` 与全局总数。
    """

    count: int = 0
    total: int = 0
    children: list["CustomerCategoryNode"] = []


class SupplierCategoryCreate(PartnerCategoryCreate):
    """供应商分类新建。"""


class SupplierCategoryUpdate(PartnerCategoryUpdate):
    """供应商分类更新。"""


class SupplierCategoryRead(PartnerCategoryCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SupplierCategoryNode(SupplierCategoryRead):
    """供应商分类树节点（`count` / `total` 口径同 `CustomerCategoryNode`）。"""

    count: int = 0
    total: int = 0
    children: list["SupplierCategoryNode"] = []


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
    unit_price: MoneyRate
    product_name: Optional[str] = None  # 明细快照，打印单据用
    standards: Optional[str] = None
    # 录入单位（3b）。可空 —— 不传就是基本单位，老前端原样能用。
    # ⚠️ max_length 对齐列宽 VARCHAR(50)：不写则由 PG 报错，会冒成 500
    unit: Optional[str] = Field(None, max_length=50)
    note: Optional[str] = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    order_no: Optional[str] = None  # 不传则按 CG+日期+序号 自动生成
    items: list[PurchaseOrderItemCreate]
    # 单据性质：order=采购订单（只订货，不动库存财务） / inbound=采购入库单（默认）
    doc_type: Optional[str] = None
    # 单据头（可选）
    warehouse_id: Optional[int] = None
    # 归集到哪个项目：项目成本/收入就是靠它从财务流水里归集出来的
    project_id: Optional[int] = None
    businesser: Optional[str] = None
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_method: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    # 结算链：不传 discount_amount / paid_amount 时视为"本单全额挂账"（实付 0）
    discount_amount: Money = Decimal("0.00")
    paid_amount: Optional[Money] = None
    is_invoiced: bool = False


class PurchaseOrderItemRead(PurchaseOrderItemCreate):
    id: int
    purchase_order_id: int
    amount: Money
    # 换算率快照（3b）：「1 个录入单位 = 几个基本单位」。
    # ⚠️ **只加在 Read、不加在 Create** —— Create 的字段会进请求体，
    #    加进去就等于"承诺接受客户端传 factor"，那是防篡改底线，不能破。
    unit_factor: int = 1
    model_config = ConfigDict(from_attributes=True)


class PurchaseOrderRead(PurchaseOrderCreate):
    id: int
    status: str
    total_amount: Money
    doc_type: str = "inbound"
    source_order_id: Optional[int] = None
    payable_amount: Money = Decimal("0.00")
    current_debt: Money = Decimal("0.00")
    prev_debt: Money = Decimal("0.00")
    total_debt: Money = Decimal("0.00")
    created_at: datetime
    items: list[PurchaseOrderItemRead] = []
    model_config = ConfigDict(from_attributes=True)


class SalesOrderItemCreate(BaseModel):
    product_id: int
    quantity: int
    unit_price: MoneyRate
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
    # 归集到哪个项目：项目成本/收入就是靠它从财务流水里归集出来的
    project_id: Optional[int] = None
    businesser: Optional[str] = None
    order_date: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_method: Optional[str] = None
    contact: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    # —— 物流流 + 签收（四流合一 2026-10-19）——
    # signed_at 用 datetime：前端 <input type="datetime-local"> 传 "2026-10-19T15:30"，
    # FastAPI/pydantic 直接解析成 datetime；不传 = None = 未签收。
    logistics_company: Optional[str] = None
    logistics_no: Optional[str] = None
    signed_by: Optional[str] = None
    signed_at: Optional[datetime] = None
    # 结算链
    discount_amount: Money = Decimal("0.00")
    received_amount: Optional[Money] = None
    is_invoiced: bool = False


class SalesOrderItemRead(SalesOrderItemCreate):
    id: int
    sales_order_id: int
    # —— 多单位换算快照（3c）：1 个录入单位 = 几个最小单位 ——
    # ⚠️ 只出现在 **Read**，`SalesOrderItemCreate` 里**没有**这个字段 ——
    #    客户端的换算率一律由服务端从 `unit` 现场解析
    #    （见 `erp_common._resolve_unit_factor`），绝不能由客户端注入。
    unit_factor: int = 1
    amount: Money
    model_config = ConfigDict(from_attributes=True)


class SalesOrderRead(SalesOrderCreate):
    id: int
    status: str
    total_amount: Money
    doc_type: str = "outbound"
    source_order_id: Optional[int] = None
    receivable_amount: Money = Decimal("0.00")
    current_debt: Money = Decimal("0.00")
    prev_debt: Money = Decimal("0.00")
    total_debt: Money = Decimal("0.00")
    # —— 完结闸（2026-10-20 状态机收紧）。四个字段全部**后端现算**：
    #    口径只有一份（erp_sales._apply_settlement_fields），前端不许再自己算一遍 ——
    #    两份公式迟早分叉，表现是"按钮亮了钱没收齐"。
    #    invoiced_amount  已开票 = 关联销项发票（invoices.related_order_id）的价税合计
    #    outstanding_amount  应收余额 =（价税合计 − 优惠）− 实收
    #    uninvoiced_amount   未开票 =（价税合计 − 优惠）− 已开票
    #    settled             应收余额=0 且 未开票=0 → 「标记为已完结」才可点
    invoiced_amount: Money = Decimal("0.00")
    outstanding_amount: Money = Decimal("0.00")
    uninvoiced_amount: Money = Decimal("0.00")
    settled: bool = False
    created_at: datetime
    items: list[SalesOrderItemRead] = []
    model_config = ConfigDict(from_attributes=True)


class InventoryTransactionCreate(BaseModel):
    product_id: int
    warehouse_id: int
    transaction_type: str
    quantity: int
    unit_price: MoneyRate = Decimal("0.0000")


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
    amount: Money
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
    # 现金银行：资金账户与收支类别（日常收支页用）
    bank_account_id: Optional[int] = None
    category: Optional[str] = None
    handler: Optional[str] = None


class FinancialTransactionRead(FinancialTransactionCreate):
    id: int
    created_at: datetime
    # ---- 红冲（2026-10-19）----
    # reversal_of_id / applied_amount 是**表列**，由 ORM 直接带出；
    # is_reversed / reversed_flow_id 不是表列，由 `/finance` 列表接口一次聚合查询现算，
    # 再挂到 ORM 实例上（逐行查一次会变成 N+1）。
    reversal_of_id: Optional[int] = None
    applied_amount: Optional[Money] = None
    is_reversed: bool = False
    reversed_flow_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class InvoiceCreate(BaseModel):
    invoice_no: str
    invoice_type: str = "普票"
    issue_date: Optional[str] = None
    counterparty_name: Optional[str] = None
    invoice_code: Optional[str] = None
    total_amount: Money = Decimal("0.00")
    tax_rate: Optional[float] = None
    tax_amount: Optional[Money] = None
    excl_tax_amount: Optional[Money] = None
    deducted: bool = False
    category: Optional[str] = None
    status: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_tax_no: Optional[str] = None
    seller_name: Optional[str] = None
    seller_tax_no: Optional[str] = None
    items: list[dict] = []
    raw_text: Optional[str] = None
    # 第 11 批：业务属性。direction 留空时由后端按本公司抬头自动判定
    direction: Optional[str] = None
    invoice_flag: str = "blue"
    issue_mode: str = "manual"
    handler: Optional[str] = None
    # 原件：由 /invoices/import 落盘后返回的**相对路径**，前端回传以建立关联
    source_path: Optional[str] = None
    source_name: Optional[str] = None
    source_size: Optional[int] = None
    source_mime: Optional[str] = None
    # 第 14 批：挂档案 id（不传时，销项发票由后端按购买方名称/税号自动匹配客户）
    customer_id: Optional[int] = None
    contract_id: Optional[int] = None
    # 四流合一（2026-10-19）：挂具体单据。
    # 销项 → sales_orders.id；进项 → purchase_orders.id（方向决定指向哪张表，后端校验）
    related_order_id: Optional[int] = None


class InvoiceUpdate(BaseModel):
    # ⚠️ 2026-10-19 补全（四流合一阶段发现的真 bug）：
    # 这里的字段决定 `PATCH /invoices/{id}` **能改什么**。pydantic 默认忽略未声明的字段，
    # 所以之前前端"编辑"弹窗里改的发票号码 / 金额 / 日期 / 抬头 / 税号,
    # 后端一个都没收 —— 接口照样 200，页面刷新后原样退回。
    # 弹窗是 OCR 之后唯一的补录入口，这些字段缺一个都等于"这张票改不了"。
    invoice_no: Optional[str] = None
    invoice_code: Optional[str] = None
    issue_date: Optional[str] = None
    counterparty_name: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_tax_no: Optional[str] = None
    seller_name: Optional[str] = None
    seller_tax_no: Optional[str] = None
    total_amount: Optional[Money] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[Money] = None
    excl_tax_amount: Optional[Money] = None
    invoice_type: Optional[str] = None
    deducted: Optional[bool] = None
    category: Optional[str] = None
    status: Optional[str] = None
    # 第 11 批：允许手工改判进销项 / 红蓝字 / 开票方式
    direction: Optional[str] = None
    invoice_flag: Optional[str] = None
    issue_mode: Optional[str] = None
    handler: Optional[str] = None
    # 第 14 批：允许把发票手工挂到客户 / 合同上（对账单按 id 取数）
    customer_id: Optional[int] = None
    contract_id: Optional[int] = None
    # 四流合一：挂单据。
    # ⚠️ 用 `model_fields_set` 区分"没传"和"传了 null"：
    #    没传 = 不动这列；传 null = 显式解除关联。
    related_order_id: Optional[int] = None


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


class ProjectUpdate(BaseModel):
    """改项目：全部可选，只改传了的字段。

    刻意不提供改 `code` 的入口 —— 项目编码是对外的标识（合同、对账单上会写），
    改了会让历史引用对不上。要改编码就新建一个项目。
    """

    name: Optional[str] = None
    manager: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    budget: Optional[float] = None
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
    # —— 第 13 批：双向合同 ——
    # in 采购 / out 销售。**不传就按 contract_type 推**，两者由 model_validator 对齐，
    # 永远不可能出现 direction=out 而 contract_type=purchase 的矛盾组合。
    direction: Optional[str] = None
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

    # —— 第 13 批：合同原件与 OCR（由上传/识别接口回填，创建时可留空）——
    # 新建流程「智能优先」：前端在弹窗里先传原件到 tmp/（拿到 temp_token）、
    # 先识别、再保存。保存时把这个 token 带上来，由后端把文件搬进正式目录 ——
    # 客户端**不能**直接写 source_file_path（服务器相对路径，等于路径注入后门）。
    source_temp_token: Optional[str] = None
    source_file_path: Optional[str] = None
    source_file_name: Optional[str] = None
    source_file_size: Optional[int] = None
    source_file_mime: Optional[str] = None
    ocr_json: Optional[str] = None
    ocr_status: Optional[str] = None

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        if text not in ("in", "out"):
            raise ValueError("direction 只能是 in（采购）或 out（销售）")
        return text

    @field_validator("ocr_status")
    @classmethod
    def _check_ocr_status(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        if text not in ("none", "pending", "parsed", "reviewed", "failed"):
            raise ValueError("ocr_status 只能是 none/pending/parsed/reviewed/failed")
        return text

    @model_validator(mode="after")
    def _sync_direction(self):
        """direction 与 contract_type 双向对齐。

        规则：**direction 优先**（新字段），缺失时从 contract_type 推；
        然后把 contract_type 回写成与新方向一致的值。
        这样旧前端（只发 contract_type）和新前端（只发 direction）都能用，
        而且落库后两个字段永远一致 —— 对账单按方向取数时不会被自相矛盾的行骗到。
        """
        raw_type = str(self.contract_type or "").strip().lower()
        raw_dir = str(self.direction or "").strip().lower()
        if raw_dir in ("in", "out"):
            direction = raw_dir
        else:
            direction = {"purchase": "in", "sales": "out"}.get(raw_type, "out")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "contract_type", {"in": "purchase", "out": "sales"}[direction])
        return self


class ContractRead(ContractCreate):
    id: int
    contract_no: str
    status: str
    direction: str = "out"
    ocr_status: str = "none"
    total_amount: float
    amount_chinese: Optional[str] = None
    order_id: Optional[int] = None
    order_no: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    items: list[ContractItemRead] = []
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 采购退货 ——————————————————————
class PurchaseReturnItemCreate(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    standards: Optional[str] = None
    # 录入单位（3b）。max_length 对齐列宽 VARCHAR(50)，理由同采购明细。
    unit: Optional[str] = Field(None, max_length=50)
    # ⚠️ 刻意保持 float 而**不是** int：改成 int 会让 "3.5" 在 Pydantic 层变成
    #    英文 422（"Input should be a valid integer"），不符合本项目"中文、指到第几行"
    #    的报错风格。非整数由 `erp_purchase._purchase_return_quantity` 显式拦成 400。
    quantity: float = 0.0
    unit_price: float = 0.0
    note: Optional[str] = None


class PurchaseReturnItemRead(PurchaseReturnItemCreate):
    id: int
    purchase_return_id: int
    amount: float
    # 换算率快照（3b）。同样**只在 Read**，理由见 PurchaseOrderItemRead。
    unit_factor: int = 1
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
    # —— 多单位换算快照（3c）—— 只出现在 Read，Create 里没有（同上）
    unit_factor: int = 1
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
    # 第 13 批：可选关联合同（框架合同下的分次报价）
    contract_id: Optional[int] = None
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


# ============================================================
# 第 10 批（动态菜单）—— 菜单节点
# ============================================================
class MenuCreate(BaseModel):
    """新建菜单节点。

    `page_key` 有值 = 菜单项（叶子，点它切到那个页面）；留空 = 分组（容器）。
    只有"有没有挂页面"一个判据，不需要 type 字段 —— 见 models/menu.py 的说明。
    """

    label: str = Field(..., min_length=1, max_length=20)
    parent_id: Optional[int] = None
    page_key: Optional[str] = Field(None, max_length=50)
    sort_order: int = 0
    is_enabled: bool = True
    note: Optional[str] = None


class MenuUpdate(BaseModel):
    """改菜单节点。字段都是可选的，只改传进来的那些。"""

    label: Optional[str] = Field(None, min_length=1, max_length=20)
    parent_id: Optional[int] = None
    page_key: Optional[str] = Field(None, max_length=50)
    sort_order: Optional[int] = None
    is_enabled: Optional[bool] = None
    note: Optional[str] = None


class MenuReorderItem(BaseModel):
    """树上一个节点的目标位置（拖拽落库用）。

    ⚠️ `parent_id` **必填且没有默认值**（2026-10-16）：
    早先写成 `Optional[int] = None`，于是调用方漏传这个字段时会被**静默解释成
    「移到顶层」** —— 实测真发生过：一次还原请求漏了 parent_id，7 个子菜单当场被顶到
    顶层（顶层从 11 个变成 18 个），而接口返回的却是 200。
    静默错误比报错可怕得多，所以现在漏传直接 422。

    语义：顶层节点写 `parent_id: null`，子节点写父级 id。**显式 null 是合法的**，
    只有"整个键不存在"才会被拒 —— 前端 `collectPayload` 一直是显式传值
    （`parent_id: pid`，顶层时 pid 就是 null），所以不受这个收紧影响。
    """

    id: int
    parent_id: Optional[int]  # 无默认值 = 必填
    sort_order: int = 0

    @model_validator(mode="before")
    @classmethod
    def _parent_id_must_be_explicit(cls, data: object) -> object:
        """漏传 parent_id 时给一句人能看懂的报错，而不是 Pydantic 默认的 "Field required"。

        用 before 校验器：字段缺失时普通字段校验只会抛一条干巴巴的
        `loc=['body','items',0,'parent_id'] msg='Field required'`，
        调用方未必能立刻明白"少写一个字段会把菜单搬到顶层"。
        """
        if isinstance(data, dict) and "parent_id" not in data:
            raise ValueError(
                "items 里的每一项都必须显式给出 parent_id："
                "顶层节点写 null，子节点写父级 id。"
                "（这个字段漏传会被误当成「移到顶层」，所以接口直接拒收）"
            )
        return data


class MenuReorderRequest(BaseModel):
    """批量移动 / 重排菜单节点。

    一次拖拽 drop 会同时改「被拖动节点」和它新旧两个兄弟组，逐条 PATCH 的话
    中途失败会留下半新半旧的顺序，所以做成一个事务内的批量接口
    —— 见 routes/system.py 的 `reorder_menus`。

    `items` 只需包含受影响的节点；服务端会把每个受影响父级下的**全部**子节点
    按 (sort_order, id) 重新编号成 10/20/30…，所以永远不会有重号或空洞。
    传空 items 是合法的（无操作，直接返回当前树）。
    """

    items: list[MenuReorderItem] = Field(default_factory=list)


class MenuRead(BaseModel):
    id: int
    parent_id: Optional[int] = None
    label: str
    page_key: Optional[str] = None
    sort_order: int = 0
    is_enabled: bool = True
    is_builtin: bool = False
    # 派生字段：界面上直接显示"分组/菜单项"，以及当前挂的页面中文名
    kind: str = "group"
    kind_label: str = "分组"
    page_label: Optional[str] = None
    depth: int = 1
    has_children: bool = False
    # 子节点只在树形返回里出现
    children: list["MenuRead"] = []
    model_config = ConfigDict(from_attributes=True)


MenuRead.model_rebuild()


# ===========================================================================
# 第 13 批：合同双向管理 · 客户文件归档 · 报价单关联 · 增强对账单
#
# 本节的三个约定（全节一致，别各写各的）：
#   ① 金额一律 `float` **只在 API 边界上**：数据库是 Numeric(12,2)，
#      出参用 float 是为了 JSON 里仍是数字（pydantic 的 Decimal 会序列化成字符串，
#      前端 `Number(x)` 之外的地方会拿到 "12.30" 这种值，反而更坑）。
#      真正的精度保证在 DB 列类型 + 计算时用 Decimal（见 app/models/statement.py）。
#      → 2026-10-19 起，同一件事有了统一的写法：用文件头的 `Money` / `MoneyRate`。
#        它们内部是 Decimal、JSON 出参是数字，比手写 `float` 两头都不丢。
#   ② 计算字段（未开票 / 剩余未收 / 发票状态）**以公式为准**：
#      客户端传了也按公式覆盖，避免手填与金额对不上。
#   ③ 所有"更新"用独立的 `XxxUpdate`，字段全 Optional —— 与仓库里既有写法一致。
# ===========================================================================

# —————————————————————— 客户文件归档 ——————————————————————
class CustomerFileCreate(BaseModel):
    """登记一个归档文件。

    第二阶段的上传接口走 multipart，`stored_name` / `file_path` / `file_size` /
    `mime_type` / `checksum` 由服务端填写；这里把它们设成可选，
    是为了兼容"文件已经在磁盘上、只补一条记录"的补录场景。
    """

    customer_id: int
    original_name: str = Field(..., min_length=1, max_length=255)
    stored_name: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = Field(None, ge=0)
    mime_type: Optional[str] = None
    checksum: Optional[str] = Field(None, max_length=64)
    # contract 合同 / qualification 资质 / invoice 发票 / statement 对账单 / other 其他
    category: str = "other"
    note: Optional[str] = None
    uploaded_by: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, value):
        text = str(value or "other").strip().lower()
        allowed = {"contract", "qualification", "invoice", "statement", "other"}
        if text not in allowed:
            raise ValueError("category 只能是 contract/qualification/invoice/statement/other")
        return text


class CustomerFileUpdate(BaseModel):
    original_name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = None
    note: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _check_category(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        allowed = {"contract", "qualification", "invoice", "statement", "other"}
        if text not in allowed:
            raise ValueError("category 只能是 contract/qualification/invoice/statement/other")
        return text


class CustomerFileRead(BaseModel):
    id: int
    customer_id: int
    original_name: str
    stored_name: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    category: str = "other"
    note: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 增强对账单：明细 ——————————————————————
class StatementItemBase(BaseModel):
    line_no: int = 1
    business_date: Optional[str] = None

    # contract 合同 / order 订单 / inbound 入库 / outbound 出库 / opening 期初
    # （invoice/receipt/payment 预留给"收付款流水"明细，默认不单独成行，见模型注释）
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_no: Optional[str] = None
    contract_id: Optional[int] = None
    contract_no: Optional[str] = None
    summary: Optional[str] = None

    contract_amount: float = 0.0
    invoiced_amount: float = 0.0
    received_amount: float = 0.0
    prepaid_received: float = 0.0
    prepaid_applied: float = 0.0
    # 这两个是计算结果；允许入参（前端会回显），但会被 validator 按公式覆盖
    uninvoiced_amount: Optional[float] = None
    outstanding_amount: Optional[float] = None

    invoice_status: Optional[str] = None
    invoice_count: int = 0
    note: Optional[str] = None

    @field_validator("source_type")
    @classmethod
    def _check_source_type(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        allowed = {"contract", "order", "inbound", "outbound", "invoice", "receipt", "payment", "opening"}
        if text not in allowed:
            raise ValueError("source_type 不合法")
        return text

    @model_validator(mode="after")
    def _derive(self):
        """未开票 / 剩余未收 / 发票状态 —— 一律按金额推导。

        宁可覆盖客户端传来的值，也不要让"明细行金额加不出头部合计"这种事发生：
        对账单一旦发出去，任何一处对不上都要人工翻账。

        ⚠️ 公式本身**不在本文件**：调用 `app/models/statement.py` 的纯函数，
           保证"接口算的"与"落库/重算算的"永远是同一份实现（Decimal，不走 float）。
        """
        derived = derive_item_amounts(self)
        object.__setattr__(self, "uninvoiced_amount", float(derived["uninvoiced_amount"]))
        object.__setattr__(self, "outstanding_amount", float(derived["outstanding_amount"]))
        object.__setattr__(
            self,
            "invoice_status",
            infer_invoice_status(self.contract_amount, self.invoiced_amount),
        )
        return self


class StatementItemCreate(StatementItemBase):
    pass


class StatementItemUpdate(BaseModel):
    """明细行更新：全部可选，只改传了的字段（计算字段仍然会被重算）。"""

    line_no: Optional[int] = None
    business_date: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_no: Optional[str] = None
    contract_id: Optional[int] = None
    contract_no: Optional[str] = None
    summary: Optional[str] = None
    contract_amount: Optional[float] = None
    invoiced_amount: Optional[float] = None
    received_amount: Optional[float] = None
    prepaid_received: Optional[float] = None
    prepaid_applied: Optional[float] = None
    invoice_count: Optional[int] = None
    note: Optional[str] = None


class StatementItemRead(StatementItemBase):
    id: int
    statement_id: int
    uninvoiced_amount: float = 0.0
    outstanding_amount: float = 0.0
    invoice_status: str = "none"
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


# —————————————————————— 增强对账单：头部 ——————————————————————
class StatementCreate(BaseModel):
    statement_no: Optional[str] = None  # 不传则按 DZ+日期+序号 自动生成（第二阶段实现）

    # in 应付（采购） / out 应收（销售）
    direction: str = "out"
    party_type: str = "customer"  # customer / supplier
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    party_tax_no: Optional[str] = None

    period_start: Optional[str] = None
    period_end: Optional[str] = None
    statement_date: Optional[str] = None
    currency: str = "CNY"

    # 期初由调用方给（取自 customers.init_receivable / suppliers.init_payable）；
    # 其余合计一律由 items 汇总，**不接受客户端直接指定**（见文件头 ②）
    opening_balance: float = 0.0

    status: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    items: list[StatementItemCreate] = []

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value):
        text = str(value or "out").strip().lower()
        if text not in ("in", "out"):
            raise ValueError("direction 只能是 in（应付/采购）或 out（应收/销售）")
        return text

    @field_validator("party_type")
    @classmethod
    def _check_party_type(cls, value):
        text = str(value or "customer").strip().lower()
        if text not in ("customer", "supplier"):
            raise ValueError("party_type 只能是 customer 或 supplier")
        return text

    @field_validator("status")
    @classmethod
    def _check_status(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        if text not in ("draft", "confirmed", "sent", "void"):
            raise ValueError("status 只能是 draft/confirmed/sent/void")
        return text

    @model_validator(mode="after")
    def _check_party_direction(self):
        """方向与往来单位类型必须自洽。

        out（应收）只能对客户，in（应付）只能对供应商 —— 反过来是数据错误，
        会直接导致对账单开给错的单位。这里**一次性拦掉**，而不是等打印时才发现。
        """
        if self.direction == "out" and self.party_type == "supplier":
            raise ValueError("应收（out）对账单的往来单位必须是客户（customer）")
        if self.direction == "in" and self.party_type == "customer":
            raise ValueError("应付（in）对账单的往来单位必须是供应商（supplier）")
        return self


class StatementUpdate(BaseModel):
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    party_tax_no: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    statement_date: Optional[str] = None
    opening_balance: Optional[float] = None
    status: Optional[str] = None
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, value):
        if value in (None, ""):
            return None
        text = str(value).strip().lower()
        if text not in ("draft", "confirmed", "sent", "void"):
            raise ValueError("status 只能是 draft/confirmed/sent/void")
        return text


class StatementRead(BaseModel):
    id: int
    statement_no: str
    direction: str
    party_type: str
    party_id: Optional[int] = None
    party_name: Optional[str] = None
    party_tax_no: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    statement_date: Optional[str] = None
    currency: str = "CNY"

    # 10 个金额（口径见 app/models/statement.py 文件头公式）
    opening_balance: float = 0.0
    contract_amount: float = 0.0
    invoiced_amount: float = 0.0
    uninvoiced_amount: float = 0.0
    received_amount: float = 0.0
    prepaid_received: float = 0.0
    prepaid_applied: float = 0.0
    prepaid_balance: float = 0.0
    receivable_balance: float = 0.0
    outstanding_amount: float = 0.0

    item_count: int = 0
    status: str = "draft"
    confirmed_at: Optional[datetime] = None
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: list[StatementItemRead] = []
    model_config = ConfigDict(from_attributes=True)


class StatementRecalcResult(BaseModel):
    """重算接口的返回（第二阶段 `POST /statements/{id}/recalc`）。"""

    statement_id: int
    item_count: int
    totals: dict[str, float]
