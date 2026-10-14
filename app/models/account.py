from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Account(Base):
    """会计科目 —— 总账 / 复式记账的科目表。

    在此之前系统的财务是「单式流水」（`financial_transactions` 每笔一个方向一个金额），
    没有科目、没有借贷分录、没有凭证。这张表就是补上「总账」的地基：
    单据事件按过账规则映射到科目，记成借贷双分录。

    支持父子级（parent_id），内置一套中国会计准则常用科目。
    balance_direction 是余额方向：资产/成本/费用类借余，负债/权益/收入类贷余。
    只有叶子科目（is_leaf=True）能记分录。
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)  # 如 1001
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # asset/liability/equity/cost/income
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 父子级，NULL=顶级
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    balance_direction: Mapped[str] = mapped_column(String(10), default="debit", nullable=False)  # debit 借余 / credit 贷余
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 科目大类
ACCOUNT_CATEGORIES: dict[str, str] = {
    "asset": "资产",
    "liability": "负债",
    "equity": "权益",
    "cost": "成本",
    "income": "损益",
}

# 内置标准科目（中国会计准则常用，覆盖进销存 + 总账的核心科目）。
# 字段顺序：(code, name, category, balance_direction)
# balance_direction：资产/成本/费用类借余(debit)，负债/权益/收入类贷余(credit)。
BUILTIN_ACCOUNTS: list[tuple[str, str, str, str]] = [
    # 资产类
    ("1001", "库存现金", "asset", "debit"),
    ("1002", "银行存款", "asset", "debit"),
    ("1122", "应收账款", "asset", "debit"),
    ("1123", "预付账款", "asset", "debit"),
    ("1221", "其他应收款", "asset", "debit"),
    ("1405", "库存商品", "asset", "debit"),
    ("1601", "固定资产", "asset", "debit"),
    # 负债类
    ("2202", "应付账款", "liability", "credit"),
    ("2203", "预收账款", "liability", "credit"),
    ("2211", "应付职工薪酬", "liability", "credit"),
    ("2221", "应交税费", "liability", "credit"),
    # 权益类
    ("4001", "实收资本", "equity", "credit"),
    ("4103", "本年利润", "equity", "credit"),
    ("4104", "利润分配", "equity", "credit"),
    # 成本类
    ("5001", "生产成本", "cost", "debit"),
    # 损益类（收入贷余 / 费用借余）
    ("6001", "主营业务收入", "income", "credit"),
    ("6051", "其他业务收入", "income", "credit"),
    ("6301", "营业外收入", "income", "credit"),
    ("6401", "主营业务成本", "income", "debit"),
    ("6403", "税金及附加", "income", "debit"),
    ("6601", "销售费用", "income", "debit"),
    ("6602", "管理费用", "income", "debit"),
    ("6603", "财务费用", "income", "debit"),
    ("6711", "营业外支出", "income", "debit"),
]
