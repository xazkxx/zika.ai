"""总账 / 复式记账核心：科目播种、自动过账、凭证生成。

把现有的「单式流水」（financial_transactions）升级成「复式记账」：
业务单据审核后写流水（现有机制不动），这里按过账规则把流水翻译成**借贷双分录的凭证**。

设计要点：
- 凭证是事实源，分录带 related_type / related_order_id / doc_no，能追溯到源单据（关联能力）。
- 过账规则用「特殊标记」解析资金账户/费用科目：
    @cash    → 按 bank_account_id 的账户类型取 1001 库存现金 / 1002 银行存款
    @expense → 按 category 映射费用科目（默认 6602 管理费用）
- 转账（transfer_in/out 一笔写两条流水）在 transfer_out 那条上合成一张凭证（借转入/贷转出）。
- 未登记的流水类型不生成凭证（宁可少记，不凭空多记）。
"""

from sqlalchemy.orm import Session

from app.models.account import BUILTIN_ACCOUNTS, Account
from app.models.bank import BankAccount
from app.models.finance import FinancialTransaction
from app.models.journal_entry import JournalEntry, JournalEntryLine


# 过账规则：transaction_type → (借方科目, 贷方科目)
POSTING_RULES: dict[str, tuple[str | None, str | None]] = {
    "receivable": ("1122", "6001"),    # 借 应收账款 / 贷 主营业务收入
    "payable": ("1405", "2202"),       # 借 库存商品 / 贷 应付账款
    "receipt": ("@cash", "1122"),      # 借 资金账户 / 贷 应收账款
    "payment": ("2202", "@cash"),      # 借 应付账款 / 贷 资金账户
    "expense": ("@expense", "@cash"),  # 借 费用 / 贷 资金账户
    "income": ("@cash", "6051"),       # 借 资金账户 / 贷 其他业务收入
    "cost": ("6401", "1405"),          # 借 主营业务成本 / 贷 库存商品
    "scrap": ("6711", "1405"),         # 借 营业外支出 / 贷 库存商品
    "overflow": ("1405", "6301"),      # 借 库存商品 / 贷 营业外收入
    "transfer_in": (None, None),       # 转账转入：不单独生成，等 transfer_out 合成
    "transfer_out": (None, None),      # 转账转出：合成一张凭证（借转入/贷转出）
}

# 销售相关费用类别 → 销售费用；其余默认管理费用
SALES_EXPENSE_CATEGORIES = {"销售费用", "广告费", "业务招待费", "促销费"}
DEFAULT_EXPENSE_ACCOUNT = "6602"  # 管理费用


def ensure_default_accounts(db: Session) -> None:
    """幂等播种内置科目（只补不覆盖，管理员改过的科目不被冲掉）。"""
    existing = {a.code for a in db.query(Account.code).all()}
    added = 0
    for code, name, category, balance_direction in BUILTIN_ACCOUNTS:
        if code in existing:
            continue
        db.add(
            Account(
                code=code,
                name=name,
                category=category,
                balance_direction=balance_direction,
                is_leaf=True,
                sort_order=int(code),
            )
        )
        added += 1
    if added:
        db.commit()


def _cash_account_code(db: Session, bank_account_id: int | None) -> str:
    """资金账户 → 科目编码。现金账户 → 1001，其余（银行/未挂账户）→ 1002。"""
    if bank_account_id:
        acct = db.get(BankAccount, bank_account_id)
        if acct is not None and getattr(acct, "account_type", None) == "cash":
            return "1001"
    return "1002"


def _expense_account_code(category: str | None) -> str:
    """费用类别 → 科目编码。销售相关 → 6601 销售费用，其余 → 6602 管理费用。"""
    if category in SALES_EXPENSE_CATEGORIES:
        return "6601"
    return DEFAULT_EXPENSE_ACCOUNT


def _next_entry_no(db: Session, period: str) -> str:
    """生成凭证号 JV-YYYYMM-XXXX（按期间序号）。"""
    prefix = f"JV-{period.replace('-', '')}-"
    last = (
        db.query(JournalEntry.entry_no)
        .filter(JournalEntry.entry_no.like(prefix + "%"))
        .order_by(JournalEntry.entry_no.desc())
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last[0].rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"


def _resolve_account(db: Session, marker: str | None, flow) -> str | None:
    """把规则里的科目 code 或特殊标记解析成实际科目编码。"""
    if marker == "@cash":
        return _cash_account_code(db, getattr(flow, "bank_account_id", None))
    if marker == "@expense":
        return _expense_account_code(getattr(flow, "category", None))
    return marker


def _account_of(db: Session, code: str) -> Account | None:
    return db.query(Account).filter(Account.code == code).first()


def _create_entry(db: Session, flow, lines: list[tuple[str, float, float]]) -> JournalEntry | None:
    """按借贷分录清单生成凭证。lines: [(account_code, debit, credit), ...]"""
    day = (getattr(flow, "occurred_at", None) or "")[:10] or None
    period = getattr(flow, "period", None) or (day[:7] if day else None)
    if not period:
        return None

    entry = JournalEntry(
        entry_no=_next_entry_no(db, period),
        entry_date=day or "",
        period=period,
        summary=getattr(flow, "note", None),
        related_type=getattr(flow, "related_type", None),
        related_order_id=getattr(flow, "related_order_id", None),
        doc_no=getattr(flow, "doc_no", None),
        flow_id=getattr(flow, "id", None),
        total_debit=0.0,
        total_credit=0.0,
    )
    db.add(entry)
    db.flush()  # 拿 entry.id

    total_debit = total_credit = 0.0
    for idx, (code, debit, credit) in enumerate(lines):
        if code is None or (debit <= 0 and credit <= 0):
            continue
        acct = _account_of(db, code)
        if acct is None:
            continue
        db.add(
            JournalEntryLine(
                entry_id=entry.id,
                account_id=acct.id,
                account_code=acct.code,
                account_name=acct.name,
                debit=round(float(debit), 2),
                credit=round(float(credit), 2),
                summary=entry.summary,
                related_type=entry.related_type,
                related_order_id=entry.related_order_id,
                sort_order=idx,
            )
        )
        total_debit += debit
        total_credit += credit

    if total_debit <= 0 and total_credit <= 0:
        # 分录没生成（科目缺失等），撤回这张空凭证
        db.delete(entry)
        db.flush()
        return None

    entry.total_debit = round(total_debit, 2)
    entry.total_credit = round(total_credit, 2)
    return entry


def post_reversal_entry(db: Session, flow, original) -> JournalEntry | None:
    """红冲凭证：把**原凭证的借贷方向对调**（借原贷、贷原借）。

    为什么不直接走 `post_journal_entry`：
      那里有一条 `if amount <= 0: return None` —— 而红字行的金额本来就是负数
      （只有这样，`sum(amount)` 才会自动归零，报表不用特判）。
      照那条规则走，红冲会**一条凭证都不生成**，总账里永远看不到这笔冲销，
      但流水表里却明明白白多了一行负数 —— 账和凭证对不上，是财务最忌讳的事。

    金额一律取绝对值：借方 200 / 贷方 200 才是合法分录，负数分录会被 `_create_entry`
    当成"空分录"整张撤回（它只允许 debit/credit > 0）。
    """
    rule = POSTING_RULES.get(getattr(original, "transaction_type", None) or "")
    if rule is None:
        return None
    debit_code = _resolve_account(db, rule[0], original)
    credit_code = _resolve_account(db, rule[1], original)
    if debit_code is None or credit_code is None:
        return None

    amount = abs(float(getattr(original, "amount", 0.0) or 0.0))
    if amount <= 0:
        return None
    # 方向对调：原「借 debit / 贷 credit」→ 红冲「借 credit / 贷 debit」
    return _create_entry(db, flow, [(credit_code, amount, 0.0), (debit_code, 0.0, amount)])


def post_journal_entry(db: Session, flow) -> JournalEntry | None:
    """根据一笔财务流水自动生成凭证。返回凭证或 None（未登记/无需生成）。"""
    ttype = getattr(flow, "transaction_type", None)
    if ttype == "transfer_in":
        return None
    if ttype == "transfer_out":
        return _post_transfer(db, flow)

    rule = POSTING_RULES.get(ttype)
    if rule is None:
        return None
    debit_code = _resolve_account(db, rule[0], flow)
    credit_code = _resolve_account(db, rule[1], flow)
    if debit_code is None or credit_code is None:
        return None

    amount = float(getattr(flow, "amount", 0.0) or 0.0)
    if amount <= 0:
        return None
    return _create_entry(db, flow, [(debit_code, amount, 0.0), (credit_code, 0.0, amount)])


def _post_transfer(db: Session, out_flow) -> JournalEntry | None:
    """转账合成一张凭证：借 转入账户，贷 转出账户。

    一笔转账在 financial_transactions 里写了两条（transfer_out + transfer_in，
    同 related_type + 同 related_order_id）。这里拿到转出这条，找出配对的转入那条，
    合成一张「借转入账户 / 贷转出账户」的凭证。
    """
    in_flow = (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.transaction_type == "transfer_in",
            FinancialTransaction.related_type == out_flow.related_type,
            FinancialTransaction.related_order_id == out_flow.related_order_id,
        )
        .first()
    )
    if in_flow is None:
        return None
    in_code = _cash_account_code(db, getattr(in_flow, "bank_account_id", None))
    out_code = _cash_account_code(db, getattr(out_flow, "bank_account_id", None))
    amount = float(getattr(out_flow, "amount", 0.0) or 0.0)
    if amount <= 0:
        return None
    return _create_entry(out_flow, [(in_code, amount, 0.0), (out_code, 0.0, amount)])


def delete_journal_entries_for_flow(db: Session, flow_id: int) -> int:
    """删除某笔财务流水对应的凭证（含分录），返回删除的凭证数。

    凭证与流水"同生共死"：删流水时必须同步删凭证，否则会残留孤儿凭证，
    污染科目余额表与明细账。按 `flow_id` 定位（转账的 transfer_out 合成凭证
    也挂在转出那条流水的 id 上，删转账时两条腿都会被各自的删除点覆盖到）。
    """
    if flow_id is None:
        return 0
    entries = db.query(JournalEntry).filter(JournalEntry.flow_id == flow_id).all()
    for entry in entries:
        db.query(JournalEntryLine).filter(JournalEntryLine.entry_id == entry.id).delete()
        db.delete(entry)
    return len(entries)


def account_balance_report(db: Session, from_date: str | None = None, to_date: str | None = None) -> dict:
    """科目余额表（试算平衡）：每个科目的借方发生、贷方发生、期末余额。

    期末余额按科目余额方向算：借余科目 = 借 - 贷，贷余科目 = 贷 - 借。
    balanced 表示借贷是否平衡（复式记账的试算平衡校验）。
    """
    q = db.query(JournalEntryLine).join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
    if from_date:
        q = q.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntry.entry_date <= to_date)
    lines = q.all()

    by_account: dict[str, dict[str, float]] = {}
    for line in lines:
        agg = by_account.setdefault(line.account_code, {"debit": 0.0, "credit": 0.0})
        agg["debit"] += float(line.debit or 0.0)
        agg["credit"] += float(line.credit or 0.0)

    accounts = db.query(Account).order_by(Account.code).all()
    rows: list[dict] = []
    total_debit = total_credit = 0.0
    for acct in accounts:
        agg = by_account.get(acct.code, {"debit": 0.0, "credit": 0.0})
        debit = round(agg["debit"], 2)
        credit = round(agg["credit"], 2)
        balance = round((credit - debit) if acct.balance_direction == "credit" else (debit - credit), 2)
        if debit == 0 and credit == 0:
            continue  # 无发生额、无余额的科目不显示，避免噪声
        rows.append(
            {
                "code": acct.code,
                "name": acct.name,
                "category": acct.category,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "direction": acct.balance_direction,
            }
        )
        total_debit += debit
        total_credit += credit

    return {
        "rows": rows,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "balanced": abs(total_debit - total_credit) < 0.01,
    }


def account_ledger(db: Session, account_code: str, from_date: str | None = None, to_date: str | None = None) -> dict:
    """明细账：某个科目的全部分录（按凭证号/日期排序），带凭证头信息便于追溯。"""
    q = (
        db.query(JournalEntryLine, JournalEntry)
        .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
        .filter(JournalEntryLine.account_code == account_code)
    )
    if from_date:
        q = q.filter(JournalEntry.entry_date >= from_date)
    if to_date:
        q = q.filter(JournalEntry.entry_date <= to_date)
    rows = q.order_by(JournalEntry.entry_date, JournalEntry.entry_no, JournalEntryLine.sort_order).all()

    acct = db.query(Account).filter(Account.code == account_code).first()
    total_debit = sum(float(line.debit or 0.0) for line, _ in rows)
    total_credit = sum(float(line.credit or 0.0) for line, _ in rows)
    balance = round(
        (total_credit - total_debit) if (acct and acct.balance_direction == "credit") else (total_debit - total_credit),
        2,
    )

    return {
        "account": {"code": account_code, "name": acct.name if acct else account_code,
                     "direction": acct.balance_direction if acct else "debit"},
        "rows": [
            {
                "entry_no": entry.entry_no,
                "entry_date": entry.entry_date,
                "summary": line.summary or entry.summary,
                "debit": float(line.debit or 0.0),
                "credit": float(line.credit or 0.0),
                "related_type": line.related_type or entry.related_type,
                "related_order_id": line.related_order_id or entry.related_order_id,
                "doc_no": entry.doc_no,
            }
            for line, entry in rows
        ],
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "balance": balance,
    }
