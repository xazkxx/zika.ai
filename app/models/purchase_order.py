from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchaseOrder(Base):
    """采购单据。

    融合「浩技云进销存」后，单据不再只是"订单"，而是承担完整的
    结算链（应付 → 优惠 → 实付）与欠款链（本次欠款 → 前次欠款 → 累欠货款）。
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 单据性质：order=采购订单（只订货） / inbound=采购入库单（真实入库+财务+库存）——
    # 对照浩技云「采购订单 ?list2」与「采购入库 ?list」两页，共用一张表靠 doc_type 区分。
    doc_type: Mapped[str] = mapped_column(String(20), default="inbound", nullable=False)
    # 订单转入库单后，生成的入库单回指来源订单（可空；入库单手工新建时为 NULL）
    source_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # —— 单据头：仓库绑定与业务信息（融合改造新增，全部可空）——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 进货仓库
    # 归集到哪个项目（可空）。项目成本/收入就是靠这个字段从财务流水里归集出来的 ——
    # 在此之前 `financial_transactions.project_id` 有这个字段，但**没有任何调用方传它**，
    # 项目维度等于是空的。
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 开单日期
    delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 送货日期
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 付款方式
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 联系人（下单时快照）
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 收货地址快照
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # —— 采购侧对齐销售侧（2026-10-21 补齐）——
    # shipped_at：首批入库时间（历史数据从库存流水回填，见 scripts/backfill_shipped_at.py）
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 自采（不走供应商账期，自己垫付）：付了多少、对应哪个供应商
    self_purchase_paid: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    self_purchase_supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


    # —— 结算链：应付 → 优惠 → 实付 ——
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 应付金额（明细合计）
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 优惠金额
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 实付金额
    is_invoiced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # 是否开票

    # —— 欠款链：本次欠款 → 前次欠款 → 累欠货款 ——
    current_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 本次欠款
    prev_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 前次欠款
    total_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)  # 累欠货款


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)  # 单价（费率，4 位不截断）
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 明细快照：打印单据时不需要再回查商品档案 ——
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 单位
    # —— 多单位换算快照（3b）——
    # 「1 个录入单位 = 几个基本单位」。默认 1 = 不换算 = 与 3b 之前逐字节等价，
    # 所以历史明细（以及其它 13 个不动 factor 的调用点）都不需要任何迁移。
    #
    # ⚠️ 它只记录"开单当时用的是哪个换算率"，**绝不接受客户端传入** ——
    #    值一律由服务端从 `unit` 现场解析（见 `erp_common._resolve_unit_factor`）。
    #    客户端能把自己那 3 箱说成 3000 盒，库存就凭空放大 1000 倍。
    unit_factor: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
