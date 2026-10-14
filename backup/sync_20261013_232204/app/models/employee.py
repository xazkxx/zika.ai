"""员工档案 —— 基础资料收尾（对齐浩技云「基础资料 → 员工档案」）。

**为什么和 `users` 分开两张表**：这是两个完全不同的东西。

- `users` 是**登录账号**：有密码、有角色、有菜单权限，系统管理页在管它。
- `employees` 是**人员档案**：工号、部门、岗位、入职离职、联系方式。
  车间里绝大多数员工根本不会登录 ERP，但他们需要出现在单据上
  （领料人、送货人、业务员）。

硬把两者合成一张表，就会逼着"给每个人开一个登录账号"，
权限表和人员表从此缠在一起 —— 这是进销存系统里最常见的错。
所以这里刻意**不做关联字段**：需要时再说，不给未来留一个空列。

**只有 `status`（在职/离职），没有 `is_active`**：两个布尔表达同一件事必然漂移。
离职 = 不再参与选择，一条状态就够了。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 在职状态：离职员工保留档案（历史单据还要显示人名），只是不再参与新业务选择
EMPLOYEE_STATUS: dict[str, str] = {"active": "在职", "left": "离职"}

# 性别：进销存档案里就是个展示字段，不做过细的枚举（留空也允许）
GENDER_OPTIONS: list[str] = ["男", "女"]


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 工号：与 users.username 无关，由企业自己的规则编
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 部门挂组织机构树（departments.id）。不设数据库外键，与 users.department_id 保持一致：
    # 档案表之间靠应用层校验，避免删部门时被外键卡住而无法清理。
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    id_card: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 日期一律存字符串 YYYY-MM-DD，与单据的 order_date / 客户的 relation_date 同一约定
    hire_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    leave_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # active=在职 / left=离职（见 EMPLOYEE_STATUS）
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    base_salary: Mapped[float | None] = mapped_column(Float, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(80), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    emergency_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
