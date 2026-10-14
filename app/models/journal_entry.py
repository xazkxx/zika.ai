from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JournalEntry(Base):
    """会计凭证 —— 复式记账的事实源（对账、出报表都以它为准）。

    在此之前系统的财务是「单式流水」，没有凭证概念。这张表补上凭证层：
    - 业务单据审核后，按过账规则自动生成凭证（借/贷双分录，借贷平衡）；
    - 凭证带 related_type / related_order_id / doc_no，能**追溯到源单据**（关联能力）。

    凭证一旦生成即视为已过账（本系统不单独做"草稿→审核→过账"的多态流程，
    与现有单据「审核即写流水」同构，避免两套状态机打架）。
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entry_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)  # 如 JV-202610-0001
    entry_date: Mapped[str] = mapped_column(String(20), nullable=False)  # YYYY-MM-DD
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # 会计期间 YYYY-MM
    summary: Mapped[str] = mapped_column(String(255), nullable=True)  # 摘要

    # 关联源单据：凭证 → 单据 追溯
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # 见 DOC_TYPES
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    doc_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 来源单据号快照

    # 源财务流水 id：凭证与流水"同生共死"——删流水时按它把凭证一并删掉，
    # 否则人工收支删掉后凭证会残留成孤儿，污染科目余额表与明细账。
    flow_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    total_debit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 借方合计
    total_credit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 贷方合计
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JournalEntryLine(Base):
    """凭证分录 —— 每张凭证的借贷明细（至少两行，借贷平衡）。"""

    __tablename__ = "journal_entry_lines"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entry_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 凭证 id
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 科目 id
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)  # 科目编码快照（科目改名不影响历史）
    account_name: Mapped[str] = mapped_column(String(80), nullable=False)  # 科目名称快照

    debit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 借方金额
    credit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 贷方金额

    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 分录摘要
    # 分录级别的关联（一条凭证可能汇总多张同类型单据）
    related_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
