from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sale_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 默认税率（%）：开单/开票时按商品带出，可逐单改。
    # 为什么不设默认值 13：不同商品适用不同档（货物 13%、农产品 9%、服务 6%…），
    # 给一个"看起来合理"的默认值，用户不改就会开错票 —— 留空逼着人选。
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 以下为对齐「浩技云进销存」商品档案补齐的字段，全部可空，不影响历史数据 ——
    mnemonic: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 助记码
    standards: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 规格
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 型号
    bar_code: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 条码
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 颜色
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 尺码
    manufacturer: Mapped[str | None] = mapped_column(String(150), nullable=True)  # 生产商
    serial_no: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 序列号
    unit_weight: Mapped[float | None] = mapped_column(Float, nullable=True)  # 单位重量
    stock_upper: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 库存上限
    stock_lower: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 库存下限
    pack_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 包装数
    shelf_life: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 保质期（天）
    warn_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 预警天数
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 商品图片
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
