from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InventoryTransaction(Base):
    """库存流水。

    融合改造后，库存不再靠手工录入，而是**由业务单据驱动**：
    采购单 → inbound 入库，销售单 → outbound 出库。
    因此每条流水必须能追到它的来源单据，否则删单时无法冲销、对账时说不清货从哪来。
    """

    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 溯源字段（融合改造新增，全部可空，不影响历史流水）——
    # related_type 取值见 finance.DOC_TYPES，如 purchase_in / sales_out / inv_check
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 来源单号快照
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
