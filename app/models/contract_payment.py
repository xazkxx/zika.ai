"""合同付款计划（多期次）—— 2026-10-23。

## 为什么单独一张表，而不是塞进 contracts 的 JSON 字段

付款计划天然是**多行**（30% 预付 / 40% 发货 / 30% 尾款），而且每一期都要记
"计划 / 实际 / 回单 / 日期"。塞 JSON 之后：没法按"逾期未付"筛选、没法 join 流水、
更没法让财务逐期上传回单。所以一期末行一记录。

## 三个刻意的口径

1. **`plan_amount` 与 `plan_ratio` 同时存**：只存比例的话，合同金额一改，
   历史计划的金额会跟着变（财务已经按旧金额付过款了）；只存金额的话，
   又没法回答"这一期是按百分之几谈的"。两个都存，写入时由后端按比例算金额。
2. **`paid_amount` 是"已登记的实际付款"**，不是从流水反推的。
   流水里可能有一笔钱同时覆盖两期，硬塞到某一期反而失真；财务按期间登记最准。
   后续做「三单匹配」时以这里的数字为准，流水只作为佐证。
3. **回单文件存相对 data/ 的路径**（`contract_receipts/xxx.pdf`），与合同原件、
   发票扫描件同一口径 —— 换机器/换盘不失效。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContractPaymentPlan(Base):
    __tablename__ = "contract_payment_plans"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # 期次（1、2、3…）+ 名称（"预付款 30%"），两者都要：
    # 期次用于排序，名称用于打印/对账时人眼看懂
    period_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    plan_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plan_ratio: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)  # 0~100
    plan_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    # 实际已付（财务按期间登记，不由流水反推）
    paid_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    paid_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 付款回单（PDF/图片），路径相对 storage_root
    receipt_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
