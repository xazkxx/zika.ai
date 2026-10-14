from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Quotation(Base):
    """销售报价单（对齐浩技云「销售 → 报价单」）。

    融合改造要点：

    1. 报价单是**商务意向文件**，报价本身不产生应收、不扣库存 —— 客户还没确认，
       货还没出，会计上什么都不能确认。所以本表**不写财务流水、不写库存流水**。
    2. 与业务单据的连接点是「一键转单」：``POST /quotations/{id}/to-order``
       把报价单转成**销售订单**（`doc_type='order'`），订单再转入库/开单，由单据去
       联动库存与财务 —— 与购销合同完全同一条链路，溯源线索是报价单号。
    3. 客户信息在**创建时快照**（名称/地址/联系人/电话），与客户档案解耦：
       报价单是发给客户的历史凭证，客户档案改地址不能把旧报价改掉。
    4. 字段口径对齐浩技云报价单页：报价单号 / 客户 / 客户地址 / 联系人 / 联系电话 /
       报价日期 / 报价效期 / 出货仓库 / 业务员 / 付款方式 / 传真号码 / 运输方式 /
       交货地点 / 商品数量 / 金额 / 审核状态。
    """

    __tablename__ = "quotations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    quote_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 客户快照 ——
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    customer_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fax: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # —— 报价有效期 ——
    quote_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 报价日期
    valid_until: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 报价效期

    # —— 交货与结算 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 出货仓库
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 付款方式
    transport_method: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 运输方式
    delivery_place: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 交货地点

    # —— 金额 ——
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 商品数量合计
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_chinese: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 金额大写（冗余，便于打印）

    # draft 草稿 / quoted 已报价 / accepted 已接受 / rejected 已拒绝 / void 已作废
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)

    # —— 转单后回填 ——
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotationItem(Base):
    """报价单明细（报价商品清单）。

    与单据 / 合同明细一样存**商品快照**：报价单发出去后就是历史凭证，
    商品改名改价后重印必须还是当年报出去的那份价格。
    """

    __tablename__ = "quotation_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    quotation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 报价单状态字典 —— 前端下拉与后端校验共用
QUOTATION_STATUS: dict[str, str] = {
    "draft": "草稿",
    "quoted": "已报价",
    "accepted": "已接受",
    "rejected": "已拒绝",
    "void": "已作废",
}

# 报价单常用付款方式 / 运输方式（前端下拉建议值，允许自由输入）
QUOTATION_PAYMENT_METHODS: list[str] = ["银行转账", "现金", "承兑汇票", "月结30天", "月结60天", "预付"]
QUOTATION_TRANSPORT_METHODS: list[str] = ["货运", "快递", "自提", "送货上门", "空运"]
