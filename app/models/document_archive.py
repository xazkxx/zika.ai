"""单据归档台账 —— P0-5（2026-10-26）"删除必须留痕"的落点。

为什么需要它
------------
改造前，业务单据与发票的 `DELETE` 是**物理删除**：删掉之后
「这张单原来长什么样、谁删的、什么时候删的、为什么删」全部消失，
只剩若干条被冲销的流水。对账时看到「那批货不知去向」，
连一张能拿去跟客户/供应商对质的单据都没有。

本表把**被作废/被删除前的完整快照**（表头 + 明细 + 金额 + 状态 + 原件路径）
连同操作人、时间、原因一起存下来，作为独立的审计证据链：

- 单据/发票作废（P0-5 的默认路径）→ 业务表保留记录 + 本表记一条 `void`；
- 历史数据清理（运维/测试）→ 业务表可以删，本表必须留 `delete` 一条。

约定
----
· `payload` 是**整单 JSON 快照**（含明细），不是差量 —— 归档表要能独立还原单据；
· `files` 是原件相对路径清单（发票 PDF/图片），**文件本身不删**，
  只是从 `data/invoices` 移到 `data/archive/invoices`；
· 本表只允许 INSERT 与查询，**不提供修改/删除接口**（审计表可改就等于没有）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 归档动作：作废 / 删除（历史清理）/ 红冲（预留给后续"红字单据"）
ARCHIVE_ACTIONS: tuple[str, ...] = ("void", "delete", "reissue")
ACTION_LABELS: dict[str, str] = {
    "void": "作废",
    "delete": "删除",
    "reissue": "重开",
}

# 支持的归档对象类型（与前端/接口路径一一对应，便于按类型筛选）
ARCHIVE_DOC_TYPES: dict[str, str] = {
    "sales_order": "销售单",
    "purchase_order": "采购单",
    "sales_return": "销售退货单",
    "purchase_return": "采购退货单",
    "invoice": "发票",
}


class DocumentArchive(Base):
    """一条"单据曾经存在过"的证据。"""

    __tablename__ = "document_archives"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # sales_order / purchase_order / sales_return / purchase_return / invoice
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    doc_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # void / delete / reissue
    action: Mapped[str] = mapped_column(String(20), default="void", nullable=False, index=True)
    status_before: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(30), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # 为什么作废/删除 —— 前端二次确认里让用户填，事后追责靠这一句
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 操作人快照（不随用户改名/删除而失效）
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # 整单快照（JSON 文本）：表头 + 明细 + 关联信息，能独立还原单据
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 原件路径清单（JSON 数组），文件本体留在归档目录
    files: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False, index=True
    )
