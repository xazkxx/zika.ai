"""合同模板库（2026-10-22）。

## 为什么单独一张表

用户手里本来就有自己的合同范本（Word/PDF/扫描件），系统要能"反复套用"：
上传一次 → 以后每份合同选它 → 生成单据时把**表单数据 + 原模板**打包成一份完整合同。

## 字段取舍

- `file_path` 存**相对 storage_root 的相对路径**（`contract_templates/xxx.docx`）——
  与发票原件、合同原件同口径。存绝对路径的话，换台机器/换个盘符全部失效。
- `mime_type` 单独存一列：判断"能不能在线预览"（image/*、application/pdf）
  和"能不能做变量替换"（Word）全靠它，别指望每次都去猜后缀。
- `note` 是给人看的（"2026 版、含质量附件"），不参与任何逻辑。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContractTemplate(Base):
    __tablename__ = "contract_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 相对 storage_root 的路径，如 `contract_templates/ab12cd34-标准工矿产品购销合同.docx`
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
