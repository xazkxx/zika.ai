"""总账 / 复式记账路由：科目、凭证、科目余额表、明细账。

这是「财务能力 + 关联能力」的落点：业务单据审核后自动过账生成凭证（见 services/ledger.py），
这里提供查询与报表接口，凭证能追溯到源单据（related_type/related_order_id/doc_no）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.account import ACCOUNT_CATEGORIES, Account
from app.models.journal_entry import JournalEntry, JournalEntryLine
from app.models.user import User
from app.services.ledger import account_balance_report, account_ledger

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """科目列表（扁平，按编码排序）。"""
    accounts = db.query(Account).order_by(Account.code).all()
    return {
        "categories": ACCOUNT_CATEGORIES,
        "accounts": [
            {
                "id": a.id,
                "code": a.code,
                "name": a.name,
                "category": a.category,
                "category_label": ACCOUNT_CATEGORIES.get(a.category, a.category),
                "balance_direction": a.balance_direction,
                "is_leaf": a.is_leaf,
            }
            for a in accounts
        ],
    }


@router.get("/journal-entries")
def list_journal_entries(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict]:
    """凭证列表（含借贷合计、来源单据）。"""
    q = db.query(JournalEntry).order_by(JournalEntry.id.desc())
    if limit is not None:
        q = q.offset(skip).limit(limit)
    return [
        {
            "id": e.id,
            "entry_no": e.entry_no,
            "entry_date": e.entry_date,
            "period": e.period,
            "summary": e.summary,
            "related_type": e.related_type,
            "related_order_id": e.related_order_id,
            "doc_no": e.doc_no,
            "flow_id": e.flow_id,
            # 金额列是 numeric → SQLAlchemy 回来是 Decimal，FastAPI 会把它序列化成**字符串**，
            # 前端/断言做 `-` 运算会直接 TypeError。这里显式转 float，保证接口契约是数字。
            "total_debit": float(e.total_debit or 0),
            "total_credit": float(e.total_credit or 0),
        }
        for e in q.all()
    ]


@router.get("/journal-entries/{entry_id}")
def get_journal_entry(entry_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """凭证详情 + 分录（借贷双方）。"""
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="凭证不存在")
    lines = (
        db.query(JournalEntryLine)
        .filter(JournalEntryLine.entry_id == entry_id)
        .order_by(JournalEntryLine.sort_order)
        .all()
    )
    return {
        "id": entry.id,
        "entry_no": entry.entry_no,
        "entry_date": entry.entry_date,
        "period": entry.period,
        "summary": entry.summary,
        "related_type": entry.related_type,
        "related_order_id": entry.related_order_id,
        "doc_no": entry.doc_no,
        "flow_id": entry.flow_id,
        "total_debit": float(entry.total_debit or 0),
        "total_credit": float(entry.total_credit or 0),
        "lines": [
            {
                "account_code": l.account_code,
                "account_name": l.account_name,
                "debit": float(l.debit or 0),
                "credit": float(l.credit or 0),
                "summary": l.summary,
            }
            for l in lines
        ],
    }


@router.get("/balance")
def balance_report(
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """科目余额表（试算平衡）：借/贷发生额 + 期末余额。"""
    return account_balance_report(db, from_date, to_date)


@router.get("/account/{account_code}")
def ledger_detail(
    account_code: str,
    from_date: str | None = None,
    to_date: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """明细账：某科目的全部分录，可追溯到源单据。"""
    acct = db.query(Account).filter(Account.code == account_code).first()
    if acct is None:
        raise HTTPException(status_code=404, detail="科目不存在")
    return account_ledger(db, account_code, from_date, to_date)
