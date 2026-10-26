from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SalesReturn(Base):
    """销售退货单（对齐浩技云「销售管理 → 销售退货」）。

    融合改造要点：

    1. 销售退货是**销售开单（出库）的反向**单据：客户把货退回来，
       库存增加（inbound 流水）、应收冲减（sales_return 财务流水）。
       因此**独立成表**，与 sales_orders 分开 —— 出库与退货的库存/财务
       方向完全相反，共表会让「删单冲销 / 现存量聚合 / 对账单」全乱掉。

    2. 与来源销售单的关联靠 `source_order_id`（退货时可选填来源出库单），
       便于溯源；不强制，允许直接手工录退货。

    3. 客户信息在**创建时快照**（名称/联系人/电话/地址），与档案解耦：
       退货单是历史凭证，客户改信息不能把旧退货单一起改掉。

    4. 财务口径：退货后自动写 `sales_return` 应收流水（金额记负数，
       对账时自然抵减，方向 in）。人工不允许手录。
    """

    __tablename__ = "sales_returns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    return_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # —— 客户快照（创建时带出，与档案解耦）——
    customer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 单据头 ——
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 退货入库仓库
    businesser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 业务员
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 退货日期
    return_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 退货原因
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 退款方式
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 溯源：可选的来源出库单/销售单 ——
    source_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_order_no: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # —— 金额 ——
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_chinese: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 金额大写（冗余，便于打印）

    # draft 草稿 / submitted 已退货 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SalesReturnItem(Base):
    """销售退货明细（客户退回商品清单）。

    与销售/采购明细一样存**商品快照**：退货单发出后就是历史凭证，
    商品改名改价后重印必须还是当初退回来的那份。
    """

    __tablename__ = "sales_return_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sales_return_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # —— 多单位换算快照（3c）——
    # 「1 个录入单位 = 几个最小单位」。默认 1 = 不换算 = 与 3c 之前逐字节等价，
    # 所以历史退货明细不需要任何迁移。
    #
    # ⚠️ 绝不接受客户端传入，一律由服务端从 `unit` 现场解析
    #    （见 `erp_common._resolve_unit_factor`）。
    unit_factor: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 销售退货状态字典 —— 前端下拉与后端校验共用
SALES_RETURN_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已退货",
    "cancelled": "已取消",
}
