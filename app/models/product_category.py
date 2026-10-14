from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductCategory(Base):
    """商品类别（多级树形）。

    之前商品档案里的「类别」只是一个扁平字符串（`products.category`），
    浩技云 5.0 的左侧是**多级类别树**（顶级=客户/板块，二级=商品类别，如
    「中国中铁 → 劳保」「国家电网 → 物资供应」）。这张表就是那棵树的落点。

    商品表不改外键、继续存类别名称字符串，避免迁移 262 个存量商品；
    前端从这棵树选完类别，把「路径」或「节点名」写回 `products.category`。
    """

    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 类别名
    # 上级分类；NULL = 顶级。类别名在同一父级下不重复（由路由层校验），
    # 因为商品选类别时靠「名称」回写字符串，重名会歧义。
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 同级排序
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
