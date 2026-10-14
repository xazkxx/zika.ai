"""组织机构（部门树）—— 系统管理第 1 轮。

为什么用自引用树而不是扁平列表：浩技云的组织机构管理是一棵树
（公司 → 部门 → 班组），且用户要能挂到任意层级上。
parent_id 自引用是项目里 BOM 已在用的模式（production_boms），照抄即可。

删除规则：有子部门 / 有在职用户挂靠时禁止删除（接口层返回 409），
防止把树删出一个断链。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 部门编码：不允许重名重码，便于导入导出与对接
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 上级部门：NULL 表示顶层（公司）
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    leader: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 层级：0=公司，1=一级部门…… 由接口按 parent 链自动算出，前端按此缩进
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
