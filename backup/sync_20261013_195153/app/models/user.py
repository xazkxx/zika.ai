from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # 角色 code 快照：登录签发的 JWT 与 require_roles(...) 都读它，保持既有鉴权链路不变
    role: Mapped[str] = mapped_column(String(20), default="staff", nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # —— 系统管理第 1 轮补列（历史数据全为 NULL，登录鉴权不依赖它们）——
    # 所属部门：指向 departments.id
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 角色主键：指向 roles.id（与上面的 role(code) 冗余但各有用途：code 给鉴权链路读，id 给管理页用）
    role_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
