"""现金银行 —— 对齐浩技云「财务管理 → 现金银行」。

**为什么必须单独有账户表**：`financial_transactions` 记的是"发生了多少钱的事"，
但**没有"这笔钱在哪个账户进出"这一维**。没有它，就答不了财务最常问的两个问题：
"公司账上还有多少钱"、"这个月银行户进出多少"。所以：

- `bank_accounts` 建账户档案（现金 / 银行 / 其他），带**期初余额**；
- `financial_transactions` 补一列 `bank_account_id` 把流水挂到账户上；
- `bank_transfers` 记账户之间的转账（转出 + 转入两条流水，见下）。

**余额口径（这一批最容易算错的地方）**：只有**真实的资金移动**才进账户余额。

| 进 | 出 |
|---|---|
| `income` 日常收入、`receipt` 收款、`transfer_in` 转入 | `expense` 日常支出、`payment` 付款、`transfer_out` 转出 |

**明确不进余额的**：`receivable`/`payable`（应收应付是债权债务，钱还没动）、
`cost`（成本结转是内部结转，不涉及资金）、`scrap`/`overflow`（库房数量损益，
本身不是钱）。这与"权责发生制 vs 收付实现制"是同一个区分 ——
把应收应付也算进账户余额，账上就会凭空多出一笔没收到手的钱。

**转账为什么也建一张表**：一笔转账天然是"两个账户各动一次"，
必须有个东西把这两条流水绑在一起才能在删单时成对冲销。
沿用本项目一贯的"一单一表"模式（与库存调拨同理），
两条流水共用 `related_type='bank_transfer'` + `related_order_id`=转账单 id。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 账户类型
BANK_ACCOUNT_TYPES: dict[str, str] = {
    "cash": "现金",
    "bank": "银行",
    "other": "其他",
}

# 账户余额口径：只有真实的资金移动才算。
# 两边合起来必须覆盖"会动钱"的全部流水类型，且互不重叠。
ACCOUNT_INCREASE_TYPES: frozenset[str] = frozenset({"income", "receipt", "transfer_in"})
ACCOUNT_DECREASE_TYPES: frozenset[str] = frozenset({"expense", "payment", "transfer_out"})


def account_delta(transaction_type: str, amount: float) -> float:
    """把一条流水折算成对账户余额的增减。

    不在两个集合里的类型（应收应付 / 成本 / 报损报溢）返回 0 ——
    它们是账务或数量口径，不涉及资金。**不在这里加白名单式的兜底**：
    新增类型时如果忘了归类，这里返回 0 会在测试里暴露（余额对不上），
    比默默按"收"处理安全。
    """
    if transaction_type in ACCOUNT_INCREASE_TYPES:
        return float(amount or 0.0)
    if transaction_type in ACCOUNT_DECREASE_TYPES:
        return -float(amount or 0.0)
    return 0.0


class BankAccount(Base):
    """账户档案（现金 / 银行 / 其他）。"""

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # cash 现金 / bank 银行 / other 其他，见 BANK_ACCOUNT_TYPES
    account_type: Mapped[str] = mapped_column(String(20), default="bank", nullable=False, index=True)
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    account_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 期初余额：建账那一刻账上的钱。余额 = 期初 + Σ流水增减
    init_balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BankTransfer(Base):
    """账户间转账。写两条流水（转出账户 out、转入账户 in），删单时成对冲销。"""

    __tablename__ = "bank_transfers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    transfer_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    from_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    to_account_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    transfer_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    handler: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
