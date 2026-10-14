from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinancialTransaction(Base):
    """财务流水 —— 业务事件驱动的记账中心。

    改造要点（「财务模块要和所有模块保持关联」）：
    1. 原有 related_order_id 是个裸整数，不知道指向哪张表；补 related_type 明确单据类型。
    2. 补 product_id / warehouse_id / project_id，让库存、生产、项目模块也能挂到财务。
    3. 补 direction（收/付方向）与 period（会计期间），支持按期间出报表。
    4. 补 occurred_at（业务发生日期），与 created_at（录入时间）区分。

    规矩：单据审核后由系统自动写流水，人工只能登记收付款与费用。
    """

    __tablename__ = "financial_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # 业务类型：receivable 应收 / payable 应付 / receipt 收款 / payment 付款 /
    #          cost 成本 / expense 费用 / income 收入 / scrap 报损 / overflow 报溢
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # 来源单据类型，取值见 DOC_TYPES（purchase_order / sales_order / inv_check ...）
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 来源单据号快照

    # 方向：in 流入（收/收入） / out 流出（付/成本/费用）
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)

    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 商品维度（库存/生产成本）
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 仓库维度（库存类）
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 项目维度（项目成本归集）

    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)

    occurred_at: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 业务发生日期 YYYY-MM-DD
    period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)  # 会计期间 YYYY-MM

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 单据类型字典：财务流水 related_type 的合法取值。
# 「财务与所有模块关联」靠这张字典落地，将来新增模块时在这里登记即可。
DOC_TYPES: dict[str, str] = {
    "purchase_order": "采购订单",
    "purchase_in": "采购入库",
    "purchase_return": "采购退货",
    "sales_order": "销售订单",
    "sales_out": "销售开单",
    "sales_return": "销售退货",
    "receipt": "收款登记",
    "payment": "付款登记",
    "inv_check": "库存盘点",
    "inv_scrap": "报损",
    "inv_overflow": "报溢",
    "inv_transfer": "库存调拨",
    "production_order": "生产工单",
    "production_plan": "生产计划",
    "production_issue": "生产领料",
    "production_return": "生产退料",
    "production_in": "成品入库",
    "production_wage": "计件工资",
    "outsourcing": "委外加工",
    "project_cost": "项目费用",
    "invoice": "发票",
    "expense": "日常支出",
    "contract": "购销合同",
}
