from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Stocktaking(Base):
    """库存盘点单（对齐浩技云「库存管理 → 盘点管理」）。

    融合改造要点：

    1. 盘点是**账实核对**：账面数由系统按现存量带出、实盘数由人盘点录入，
       两者的差额就是盈亏。盘点单保存后按差额调整库存 ——
       盘盈（实盘 > 账面）写 inbound，盘亏（实盘 < 账面）写 outbound。

    2. 盘点与调拨一样属于**纯库存单据**：只调整现存量、**不写财务流水**。
       盘盈盘亏的账务处理（待处理财产损溢、管理费用）由用户走日常收支，
       系统不擅自记账 —— 这一点在测试里用反向断言锁死。

    3. 新增接口 `GET /stocktakings/plan` 会按仓库带出账面库存，直接生成
       盘点底稿，避免手工一行行敲账面数（这是盘点与其他单据最大的不同）。

    4. 盈亏方向由**明细行自己**决定，所以一张盘点单会同时产生 inbound 与
       outbound 两类流水，共用 `related_type="inv_check"` + 本单 id，
       删单时 `_revert_stock` 一次全冲，账实同时回到盘点前。
    """

    __tablename__ = "stocktakings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    check_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # —— 单据头 ——
    warehouse_id: Mapped[int] = mapped_column(Integer, nullable=False)  # 盘点仓库
    check_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 盘点日期
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 盘点人
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 盘点范围说明
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # —— 合计：盘盈 / 盘亏分开记，避免"一正一负抵消成 0"看不出问题 ——
    total_profit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 盘盈数量合计
    total_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 盘亏数量合计
    profit_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 盘盈行数
    loss_lines: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 盘亏行数
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 盈亏金额净额（成本口径）

    # draft 草稿 / submitted 已调整 / cancelled 已取消
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StocktakingItem(Base):
    """盘点明细：一行 = 一个商品的账面数 / 实盘数 / 盈亏数。

    `diff_quantity = actual_quantity - book_quantity`（正数盘盈、负数盘亏），
    由后端统一计算，前端不许自己算 —— 否则口径一分叉，库存就烂了。
    """

    __tablename__ = "stocktaking_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stocktaking_id: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格型号
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)

    book_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 账面数
    actual_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 实盘数
    diff_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 盈亏数
    unit_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 成本单价
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 盈亏金额

    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 盘点单状态字典 —— 前端下拉与后端校验共用
STOCKTAKING_STATUS: dict[str, str] = {
    "draft": "草稿",
    "submitted": "已调整",
    "cancelled": "已取消",
}
