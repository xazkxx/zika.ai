from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    manager: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    deadline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 项目状态字典 —— 前端下拉与后端校验共用。
# 之前这个字段只在前端硬编码了几个 option、后端不校验，写进什么都会存下来。
# ⚠️ 取值必须与前端下拉**完全一致**：前端原本就有 `delayed`（延期），
# 字典里少一个，用户一选那个选项保存就会被校验挡下来（400），
# 而且报错信息是"状态只能是 xxx"—— 用户看不出到底哪个能选。
PROJECT_STATUS: dict[str, str] = {
    "planned": "计划中",
    "in_progress": "进行中",
    "delayed": "延期",
    "completed": "已完成",
    "closed": "已关闭",
}
