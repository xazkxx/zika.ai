"""现金银行 与 日常收支（财务管理收尾）回归测试。

这一批的风险是**余额算错**，而且错了很难被发现 —— 账面数字看着都像对的。
所以最重要的两条是：

1. `test_account_balance_counts_only_cash_flows` —— 账户余额只认**真实资金移动**。
   应收应付是债权债务（钱还没动）、成本是内部结转、报损报溢是数量损益，
   这三类流水**一律不进余额**。把它们算进去，账上就会凭空多出一笔没收到手的钱。
2. `test_transfer_is_symmetric_and_reversible` —— 一笔转账必须同时改两个账户的余额，
   删掉它两边一起复原。只改一边就是凭空生钱或掉钱。

其余覆盖：账户档案 CRUD 与删前守卫（有流水禁删）、流水账的期初/区间口径、
日常收支的筛选与合计、**只有人工登记的收支能删**、收支类别字典的播种与前端挂载。

测试数据命名遵守 scripts/clean_test_data.py 的签名：账户编码一律 `TEST-BANK-` 前缀
（与 TEST-USR- / TEST-ROLE- / TEST-DEPT- 同一套约定）。

**转账单号没法用签名识别** —— 它是后端按业务格式生成的（TR+日期+流水），真实用户的
转账长得一模一样。所以清理时转账与账户流水一律按「挂在哪个账户名下」归属：
测试账户名下的就是测试数据。为此本文件所有账户都必须带 TEST-BANK- 前缀。
"""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.bank import ACCOUNT_DECREASE_TYPES, ACCOUNT_INCREASE_TYPES, BANK_ACCOUNT_TYPES, account_delta

client = TestClient(app)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def books():
    """两个资金账户（现金 1000 期初 / 银行 0），用完即删。

    收尾顺序不能颠倒：先删本次造的收支与转账，再删账户（有流水时账户删不掉）。
    """
    headers = _headers()
    tag = _hex()
    cash = client.post(
        "/api/v1/bank-accounts",
        json={"code": f"TEST-BANK-CASH-{tag}", "name": f"验收现金-{tag}", "account_type": "cash", "init_balance": 1000},
        headers=headers,
    ).json()
    bank = client.post(
        "/api/v1/bank-accounts",
        json={
            "code": f"TEST-BANK-BOC-{tag}", "name": f"验收银行-{tag}", "account_type": "bank",
            "bank_name": "中国银行", "account_no": f"6217{tag}", "init_balance": 0,
        },
        headers=headers,
    ).json()
    yield {"headers": headers, "tag": tag, "cash": cash, "bank": bank}

    # 清流水（人工收支）→ 清转账（连带其两条流水）→ 删账户
    entries = client.get("/api/v1/finance/entries", headers=headers).json()["items"]
    account_ids = {cash["id"], bank["id"]}
    for row in entries:
        if row.get("bank_account_id") in account_ids:
            client.delete(f"/api/v1/finance/entries/{row['id']}", headers=headers)
    for row in client.get("/api/v1/bank-transfers", headers=headers).json():
        if row["from_account_id"] in account_ids or row["to_account_id"] in account_ids:
            client.delete(f"/api/v1/bank-transfers/{row['id']}", headers=headers)
    # 单据自动生成的流水（测试造的应收/成本）按 id 直接清掉，避免污染账户删除
    for row in client.get("/api/v1/finance", headers=headers).json():
        if row.get("bank_account_id") in account_ids:
            _purge_financial_row(row["id"])
    for account in (cash, bank):
        client.delete(f"/api/v1/bank-accounts/{account['id']}", headers=headers)


def _purge_financial_row(row_id: int) -> None:
    """直接删一条流水（用于清理测试造的"单据类"流水，这些走不了 /finance/entries）。"""
    from app.db.session import SessionLocal
    from app.models.finance import FinancialTransaction

    db = SessionLocal()
    try:
        row = db.get(FinancialTransaction, row_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _balance(headers: dict[str, str], account_id: int) -> float:
    rows = client.get("/api/v1/bank-accounts?include_inactive=true", headers=headers).json()
    return next(row["current_balance"] for row in rows if row["id"] == account_id)


def _entry(headers: dict[str, str], **payload):
    return client.post("/api/v1/finance", json=payload, headers=headers)


# ============================================================
# 余额口径（本轮最重要的一条）
# ============================================================
def test_account_delta_only_recognises_cash_flows():
    """纯函数级锁定：哪些类型动钱、哪些不动。"""
    assert ACCOUNT_INCREASE_TYPES == {"income", "receipt", "transfer_in"}
    assert ACCOUNT_DECREASE_TYPES == {"expense", "payment", "transfer_out"}
    assert account_delta("income", 100) == 100
    assert account_delta("receipt", 100) == 100
    assert account_delta("expense", 100) == -100
    assert account_delta("payment", 100) == -100
    # 非资金类：一分钱都不动
    for kind in ("receivable", "payable", "cost", "scrap", "overflow"):
        assert account_delta(kind, 12345) == 0, f"{kind} 不该进账户余额"


def test_account_balance_counts_only_cash_flows(books):
    """账户余额 = 期初 + 资金流水。应收应付 / 成本 / 报损报溢一律不算。"""
    headers, cash, bank = books["headers"], books["cash"], books["bank"]
    assert _balance(headers, cash["id"]) == 1000.0

    _entry(headers, transaction_type="income", amount=500, bank_account_id=cash["id"], category="利息收入")
    _entry(headers, transaction_type="expense", amount=200, bank_account_id=cash["id"], category="办公费")
    assert _balance(headers, cash["id"]) == 1300.0

    # 单据类流水：挂到账户上也不能影响余额（钱还没动）
    for kind, amount in (("receivable", 9999), ("payable", 8888), ("cost", 777), ("scrap", 100), ("overflow", 50)):
        created = _entry(headers, transaction_type=kind, amount=amount, bank_account_id=cash["id"])
        assert created.status_code == 201, created.text
    assert _balance(headers, cash["id"]) == 1300.0, "非资金类流水被算进余额了"

    # 收付款是真实资金移动，要算
    _entry(headers, transaction_type="receipt", amount=300, bank_account_id=cash["id"])
    _entry(headers, transaction_type="payment", amount=100, bank_account_id=cash["id"])
    assert _balance(headers, cash["id"]) == 1500.0

    # 账户列表里带出流水条数（含非资金类，因为那些也是这个账户的账）
    row = next(r for r in client.get("/api/v1/bank-accounts", headers=headers).json() if r["id"] == cash["id"])
    assert row["flow_count"] >= 7
    assert row["account_type_label"] == "现金"
    assert bank["id"] != cash["id"]


# ============================================================
# 转账
# ============================================================
def test_transfer_is_symmetric_and_reversible(books):
    """一笔转账同时改两个账户，删掉两边一起复原。"""
    headers, cash, bank = books["headers"], books["cash"], books["bank"]

    created = client.post(
        "/api/v1/bank-transfers",
        json={
            "from_account_id": cash["id"], "to_account_id": bank["id"],
            "amount": 300, "transfer_date": "2026-10-13", "handler": "出纳",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["transfer_no"].startswith("TR")
    assert body["from_account_name"] == cash["name"] and body["to_account_name"] == bank["name"]
    assert _balance(headers, cash["id"]) == 700.0, "转出账户没扣钱"
    assert _balance(headers, bank["id"]) == 300.0, "转入账户没加钱"

    # 两条流水，方向相反，挂在同一个 related_order_id 上
    from app.db.session import SessionLocal
    from app.models.finance import FinancialTransaction

    db = SessionLocal()
    try:
        flows = (
            db.query(FinancialTransaction)
            .filter(FinancialTransaction.related_type == "bank_transfer")
            .filter(FinancialTransaction.related_order_id == body["id"])
            .all()
        )
    finally:
        db.close()
    assert len(flows) == 2, "转账必须写两条流水"
    assert {flow.transaction_type for flow in flows} == {"transfer_in", "transfer_out"}
    assert {flow.direction for flow in flows} == {"in", "out"}

    # 去掉转账 → 两边复原
    assert client.delete(f"/api/v1/bank-transfers/{body['id']}", headers=headers).status_code == 204
    assert _balance(headers, cash["id"]) == 1000.0
    assert _balance(headers, bank["id"]) == 0.0
    assert client.get("/api/v1/bank-transfers", headers=headers).json() == []
    assert client.delete(f"/api/v1/bank-transfers/{body['id']}", headers=headers).status_code == 404


def test_transfer_validation(books):
    headers, cash, bank = books["headers"], books["cash"], books["bank"]
    same = client.post(
        "/api/v1/bank-transfers",
        json={"from_account_id": cash["id"], "to_account_id": cash["id"], "amount": 10},
        headers=headers,
    )
    assert same.status_code == 400 and "同一个账户" in same.json()["detail"]

    for amount in (0, -5):
        resp = client.post(
            "/api/v1/bank-transfers",
            json={"from_account_id": cash["id"], "to_account_id": bank["id"], "amount": amount},
            headers=headers,
        )
        assert resp.status_code == 400 and "大于 0" in resp.json()["detail"]

    missing = client.post(
        "/api/v1/bank-transfers",
        json={"from_account_id": cash["id"], "to_account_id": 99999999, "amount": 10},
        headers=headers,
    )
    assert missing.status_code == 400 and "不存在" in missing.json()["detail"]

    assert client.post(
        "/api/v1/bank-transfers",
        json={"from_account_id": cash["id"], "to_account_id": bank["id"], "amount": "abc"},
        headers=headers,
    ).status_code == 400


# ============================================================
# 账户档案
# ============================================================
def test_account_crud_and_delete_guard(books):
    headers, cash = books["headers"], books["cash"]
    tag = books["tag"]

    duplicate = client.post(
        "/api/v1/bank-accounts", json={"code": cash["code"], "name": "重复编码"}, headers=headers
    )
    assert duplicate.status_code == 400 and "已存在" in duplicate.json()["detail"]

    bad_type = client.post(
        "/api/v1/bank-accounts",
        json={"code": f"TEST-BANK-X-{tag}", "name": "怪类型", "account_type": "bitcoin"},
        headers=headers,
    )
    assert bad_type.status_code == 400 and "账户类型" in bad_type.json()["detail"]
    assert client.post("/api/v1/bank-accounts", json={"code": f"TEST-BANK-Y-{tag}"}, headers=headers).status_code == 400

    # 改账户：改名 + 调期初，余额跟着动
    patched = client.patch(
        f"/api/v1/bank-accounts/{cash['id']}",
        json={"code": cash["code"], "name": f"改名现金-{tag}", "account_type": "cash", "init_balance": 2000},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == f"改名现金-{tag}"
    assert patched.json()["current_balance"] == 2000.0

    # 有流水就删不掉（409），且提示引导去停用
    _entry(headers, transaction_type="income", amount=10, bank_account_id=cash["id"])
    blocked = client.delete(f"/api/v1/bank-accounts/{cash['id']}", headers=headers)
    assert blocked.status_code == 409
    assert "停用" in blocked.json()["detail"]

    # 停用后不出现在默认列表里，但 include_inactive 能看到
    client.patch(
        f"/api/v1/bank-accounts/{cash['id']}",
        json={"code": cash["code"], "name": cash["name"], "account_type": "cash", "is_active": False},
        headers=headers,
    )
    assert cash["id"] not in {row["id"] for row in client.get("/api/v1/bank-accounts", headers=headers).json()}
    assert cash["id"] in {
        row["id"] for row in client.get("/api/v1/bank-accounts?include_inactive=true", headers=headers).json()
    }

    # 干净账户可以删
    spare = client.post(
        "/api/v1/bank-accounts", json={"code": f"TEST-BANK-TMP-{tag}", "name": "临时账户"}, headers=headers
    ).json()
    assert client.delete(f"/api/v1/bank-accounts/{spare['id']}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/bank-accounts/{spare['id']}", headers=headers).status_code == 404
    assert client.patch(f"/api/v1/bank-accounts/99999999", json={"code": "x", "name": "x"}, headers=headers).status_code == 404


def test_account_ledger_period_filter(books):
    """流水账：期初把区间之前的累计算进去，期末 = 期初 + 本期净额。"""
    headers, cash = books["headers"], books["cash"]

    _entry(headers, transaction_type="income", amount=100, bank_account_id=cash["id"], occurred_at="2026-09-01")
    _entry(headers, transaction_type="expense", amount=40, bank_account_id=cash["id"], occurred_at="2026-09-10")
    _entry(headers, transaction_type="income", amount=200, bank_account_id=cash["id"], occurred_at="2026-10-05")
    _entry(headers, transaction_type="expense", amount=60, bank_account_id=cash["id"], occurred_at="2026-10-20")

    ledger = client.get(
        f"/api/v1/bank-accounts/{cash['id']}/ledger?from_date=2026-10-01&to_date=2026-10-31", headers=headers
    ).json()
    # 期初 = 1000 + 100 - 40 = 1060
    assert ledger["summary"]["opening_balance"] == 1060.0
    assert ledger["summary"]["increase"] == 200.0
    assert ledger["summary"]["decrease"] == 60.0
    assert ledger["summary"]["closing_balance"] == 1200.0
    assert [row["occurred_at"] for row in ledger["rows"]] == ["2026-10-05", "2026-10-20"]
    # 明细带出增减方向
    assert [row["delta"] for row in ledger["rows"]] == [200.0, -60.0]

    # 不传期间 = 全部
    whole = client.get(f"/api/v1/bank-accounts/{cash['id']}/ledger", headers=headers).json()
    assert whole["summary"]["opening_balance"] == 1000.0
    assert whole["summary"]["closing_balance"] == 1200.0
    assert len(whole["rows"]) == 4

    assert client.get("/api/v1/bank-accounts/99999999/ledger", headers=headers).status_code == 404


# ============================================================
# 日常收支
# ============================================================
def test_finance_entries_filter_and_summary(books):
    """列表 + 合计 + 各种筛选。

    ⚠️ 测试直连**正式库**，库里本来就有真实的收支流水，所以这里所有查询
    都必须带上本次的标记 `mark`（写在备注里，keyword 会搜备注）来圈定范围。
    不带标记去断言合计，就是在拿全公司的账对本用例的三行数 —— 必然不等。
    """
    headers, cash, bank = books["headers"], books["cash"], books["bank"]
    mark = f"验收{books['tag']}"

    def query(**params):
        return client.get("/api/v1/finance/entries", params={"keyword": mark, **params}, headers=headers).json()

    _entry(headers, transaction_type="income", amount=500, bank_account_id=cash["id"],
           category="利息收入", handler="张三", occurred_at="2026-10-13", note=f"季度结息-{mark}")
    _entry(headers, transaction_type="expense", amount=120, bank_account_id=bank["id"],
           category="办公费", handler="李四", occurred_at="2026-10-14", note=f"打印纸-{mark}")
    _entry(headers, transaction_type="expense", amount=80, bank_account_id=cash["id"],
           category="差旅费", handler="张三", occurred_at="2026-09-30", note=f"出差-{mark}")

    all_rows = query()
    assert all_rows["summary"] == {"total_income": 500.0, "total_expense": 200.0, "net": 300.0}
    # 只挑 income/expense：单据自动写的应收应付不在这个列表里
    assert {row["transaction_type"] for row in all_rows["items"]} == {"income", "expense"}

    only_income = query(entry_type="income")
    assert only_income["summary"]["total_expense"] == 0.0
    assert all(row["transaction_type"] == "income" for row in only_income["items"])

    october = query(from_date="2026-10-01", to_date="2026-10-31")
    assert october["summary"]["total_expense"] == 120.0
    assert len(october["items"]) == 2

    by_account = query(bank_account_id=bank["id"])
    assert [row["bank_account_name"] for row in by_account["items"]] == [bank["name"]]

    by_keyword = client.get(
        "/api/v1/finance/entries", params={"keyword": f"打印纸-{mark}"}, headers=headers
    ).json()
    assert len(by_keyword["items"]) == 1 and by_keyword["items"][0]["category"] == "办公费"

    # keyword 也搜经办人
    by_handler = client.get("/api/v1/finance/entries", params={"keyword": "李四"}, headers=headers).json()
    assert any(row["note"] == f"打印纸-{mark}" for row in by_handler["items"])

    assert client.get("/api/v1/finance/entries?entry_type=refund", headers=headers).status_code == 400
    # 账户必须存在
    bad = _entry(headers, transaction_type="income", amount=1, bank_account_id=99999999)
    assert bad.status_code == 400 and "资金账户" in bad.json()["detail"]


def test_only_manual_entries_can_be_deleted(books):
    """只有人工登记的收支能删；单据自动生成的流水必须跟着单据走。"""
    headers, cash = books["headers"], books["cash"]
    manual = _entry(headers, transaction_type="expense", amount=50, bank_account_id=cash["id"], category="办公费").json()
    assert client.delete(f"/api/v1/finance/entries/{manual['id']}", headers=headers).status_code == 204
    assert _balance(headers, cash["id"]) == 1000.0
    assert client.delete(f"/api/v1/finance/entries/{manual['id']}", headers=headers).status_code == 404

    # 单据类流水（带 related_type）不许在这里删
    order_like = _entry(
        headers,
        transaction_type="receivable",
        amount=888,
        bank_account_id=cash["id"],
        related_type="sales_out",
        doc_no="XS20261013001",
    )
    assert order_like.status_code == 201
    blocked = client.delete(f"/api/v1/finance/entries/{order_like.json()['id']}", headers=headers)
    assert blocked.status_code == 409
    assert "只有日常收入" in blocked.json()["detail"] or "自动生成" in blocked.json()["detail"]

    # 非收支类型（如成本）也不许
    cost = _entry(headers, transaction_type="cost", amount=10, related_type="production_in").json()
    assert client.delete(f"/api/v1/finance/entries/{cost['id']}", headers=headers).status_code == 409
    _purge_financial_row(cost["id"])


def test_entry_category_dictionaries_seeded():
    """收支类别走数字字典：可维护、可停用，且前端挂上了 datalist。"""
    from pathlib import Path

    from app.models.system_config import DEFAULT_DICTIONARIES

    seeded = {str(spec["dict_type"]) for spec in DEFAULT_DICTIONARIES}
    assert {"income_category", "expense_category"} <= seeded

    headers = _headers()
    lookups = client.get(
        "/api/v1/system/lookups?types=income_category,expense_category", headers=headers
    ).json()
    assert len(lookups["income_category"]) >= 3
    assert len(lookups["expense_category"]) >= 5
    assert any(item["value"] == "办公费" for item in lookups["expense_category"])

    frontend = Path(__file__).resolve().parent.parent / "frontend" / "src"
    source = (frontend / "App.jsx").read_text(encoding="utf-8")
    # 录入表单在 2026-10-14 拆页时搬到了 pages/IncomeExpensePage.jsx，
    # 而 datalist 声明留在 App.jsx 底部（全局共用）。两边都要读。
    entry_page = (frontend / "pages" / "IncomeExpensePage.jsx").read_text(encoding="utf-8")
    for dict_type in ("income_category", "expense_category"):
        # 光有 list="lookup-xxx" 的引用不算数 —— 必须真的声明了 datalist，
        # 否则输入框点开是空的（这个坑真踩过一次：引用写了、datalist 忘了加，
        # 而当时"只查字符串出现"的断言照样绿）。
        assert re.search(rf'<datalist id="lookup-{dict_type}">', source), f"{dict_type} 没有声明 datalist"
        assert re.search(rf"lookupValues\('{dict_type}'\)", source), f"{dict_type} 的 datalist 没有取字典值"
    # 登记表单要按类型切换指向哪一个候选表
    assert re.search(
        r"list=\{entryForm\.transaction_type === 'income' \? 'lookup-income_category'",
        entry_page,
    ), "登记表单没按收支类型切候选表 —— 支出会拿收入类别去提示"


def test_frontend_pages_and_menu_are_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

    for key in ("bank", "income-expense"):
        assert f"selectedTab === '{key}'" in source, f"{key} 页面没有渲染分支"
        line = next(l for l in source.splitlines() if f"{{ key: '{key}', label:" in l)
        assert "todo: true" not in line, f"{key} 菜单还标着「待建」"

    for endpoint in ("/bank-accounts", "/bank-transfers", "/finance/entries"):
        assert endpoint in source, f"前端没有调用 {endpoint}"
    for handler in ("refreshBankAccounts", "submitBankAccount", "submitBankTransfer", "submitFinanceEntry"):
        assert handler in source, f"前端缺少处理函数 {handler}"


def test_bank_types_dictionary():
    assert set(BANK_ACCOUNT_TYPES) == {"cash", "bank", "other"}
    assert BANK_ACCOUNT_TYPES["cash"] == "现金"
