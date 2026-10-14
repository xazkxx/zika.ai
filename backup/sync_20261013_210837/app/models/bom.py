from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BillOfMaterial(Base):
    __tablename__ = "production_boms"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("production_boms.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    component_product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bom_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default="component")
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent: Mapped[BillOfMaterial | None] = relationship(
        back_populates="children",
        remote_side="BillOfMaterial.id",
    )
    children: Mapped[list[BillOfMaterial]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )
