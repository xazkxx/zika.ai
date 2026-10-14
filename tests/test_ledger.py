"""总账 / 复式记账（财务能力 + 关联能力）回归测试。

这一批的风险是「账实不一致」：凭证与流水不同步、借贷不平衡、删流水留下孤儿凭证，
都会让科目余额表 / 明细账悄悄失真，而且很难被发现 —— 数字看着都像对的。

所以最要紧的四条：
1. `test_income_expense_auto_posts_balanced_entry` —— 人工收支自动过账且借贷平衡。
   总账是复式记账，凭证必须借=贷，否则试算平衡表永远差一格。
2. `test_delete_entry_cascades_journal_entry` —— 删流水把凭证一起删（同生共死）。
   否则人工收支删掉后凭证残留成孤儿，污染科目余额表与明细账。
3. `test_balance_report_is_balanced` —— 科目余额表接口返回 balanced=True。
4. `test_general_ledger_permission_and_menu_registered` —— 「总账」权限点与菜单
   都已登记，前端 menuGroups 与后端 PERMISSION_CATALOG 对齐（一致性靠
   test_system_users.py 那条正则断言钉住，这里补后端侧的直接断言）。

其余覆盖：科目播种、凭证可追溯源流水、明细账按科目过滤、菜单缺则补的纯函数行为。

测试数据遵守 scripts/clean_test_data.py 的签名：账户编码一律 `TEST-BANK-` 前缀，
凭证靠 flow_id 指向已删流水被清理脚本兜底（见 clean_test_data.py 的凭证清理段）。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def cash_account():
    """一个 TEST-BANK 现金账户，用完即删。收入/支出都挂它名下。"""
    headers = _headers()
    tag = _hex()
    acct = client.post(
        "/api/v1/bank-accounts",
        json={
            "code": f"TEST-BANK-GL-{tag}", "name": f"总账验收现金-{tag}",
            "account_type": "cash", "init_balance": 0,
        },
        headers=headers,
    ).json()
    yield {"headers": headers, "tag": tag, "acct": acct}

    # 清掉本次造的收支（连同凭证），再删账户
    entries = client.get("/api/v1/finance/entries", headers=headers).json()["items"]
    for row in entries:
        if row.get("bank_account_id") == acct["id"]:
            client.delete(f"/api/v1/finance/entries/{row['id']}", headers=headers)
    client.delete(f"/api/v1/bank-accounts/{acct['id']}", headers=headers)


# ============================================================
# 科目播种
# ============================================================
def test_builtin_accounts_seeded():
    """24 个中国会计准则科目已播种，且编码唯一。"""
    headers = _headers()
    data = client.get("/api/v1/ledger/accounts", headers=headers).json()
    accounts = data["accounts"]
    codes = [a["code"] for a in accounts]
    # 至少要有现金/银行/应收/应付/收入/费用这些核心科目
    for required in ("1001", "1002", "1122", "2202", "6001", "6601", "6602"):
        assert required in codes, f"缺科目 {required}"
    assert len(codes) == len(set(codes)), "科目编码重复"
    assert "categories" in data


# ============================================================
# 自动过账 + 借贷平衡
# ============================================================
def test_income_expense_auto_posts_balanced_entry(cash_account):
    """人工收支自动过账，生成的凭证借=贷，且能追溯到源流水。"""
    headers, acct = cash_account["headers"], cash_account["acct"]

    created = client.post(
        "/api/v1/finance",
        json={
            "transaction_type": "income", "amount": 1000,
            "bank_account_id": acct["id"], "category": "利息收入",
            "occurred_at": "2026-10-14",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]

    # 这笔收入应生成一张凭证：借 资金账户(1001/1002)，贷 其他业务收入(6051)
    entries = client.get("/api/v1/ledger/journal-entries?limit=50", headers=headers).json()
    matched = [e for e in entries if e.get("id") and _entry_is_for_flow(e, flow_id)]
    assert matched, "人工收入没有自动生成凭证"

    detail = client.get(f"/api/v1/ledger/journal-entries/{matched[0]['id']}", headers=headers).json()
    assert abs(detail["total_debit"] - detail["total_credit"]) < 0.01, "凭证借贷不平衡"
    assert abs(detail["total_debit"] - 1000.0) < 0.01, "凭证金额不等于流水金额"
    assert len(detail["lines"]) == 2, "凭证应有借贷两条分录"
    # 借现金 / 贷其他业务收入
    codes = {line["account_code"] for line in detail["lines"]}
    assert "6051" in codes, "收入应贷 6051 其他业务收入"
    assert ("1001" in codes) or ("1002" in codes), "收入应借资金账户"


def _entry_is_for_flow(entry: dict, flow_id: int) -> bool:
    """凭证是否属于某笔流水（列表接口已返回 flow_id）。"""
    return entry.get("flow_id") == flow_id


# ============================================================
# 删流水 → 凭证同删（同生共死）
# ============================================================
def test_delete_entry_cascades_journal_entry(cash_account):
    """删掉人工收支，它的凭证一并消失，不留孤儿。"""
    headers, acct = cash_account["headers"], cash_account["acct"]

    created = client.post(
        "/api/v1/finance",
        json={"transaction_type": "expense", "amount": 300, "bank_account_id": acct["id"], "category": "办公费"},
        headers=headers,
    ).json()

    # 找凭证
    entries = client.get("/api/v1/ledger/journal-entries?limit=50", headers=headers).json()
    matched = [e for e in entries if _entry_is_for_flow(e, created["id"])]
    assert matched, "支出没有生成凭证"
    entry_id = matched[0]["id"]

    # 删收支
    assert client.delete(f"/api/v1/finance/entries/{created['id']}", headers=headers).status_code == 204

    # 凭证应已消失
    assert client.get(f"/api/v1/ledger/journal-entries/{entry_id}", headers=headers).status_code == 404


# ============================================================
# 科目余额表 / 明细账
# ============================================================
def test_balance_report_is_balanced(cash_account):
    """科目余额表接口返回 balanced=True，且借贷合计相等。"""
    headers, acct = cash_account["headers"], cash_account["acct"]
    client.post(
        "/api/v1/finance",
        json={"transaction_type": "income", "amount": 800, "bank_account_id": acct["id"], "category": "利息收入"},
        headers=headers,
    )
    client.post(
        "/api/v1/finance",
        json={"transaction_type": "expense", "amount": 200, "bank_account_id": acct["id"], "category": "办公费"},
        headers=headers,
    )

    report = client.get("/api/v1/ledger/balance", headers=headers).json()
    assert report["balanced"] is True, "复式记账下余额表必须平衡"
    assert abs(report["total_debit"] - report["total_credit"]) < 0.01
    assert report["rows"], "有发生额就应有余额表行"


def test_account_ledger_traces_source(cash_account):
    """明细账按科目过滤，行能追溯到源单据（关联能力）。"""
    headers, acct = cash_account["headers"], cash_account["acct"]
    client.post(
        "/api/v1/finance",
        json={"transaction_type": "income", "amount": 500, "bank_account_id": acct["id"], "category": "利息收入"},
        headers=headers,
    )

    detail = client.get("/api/v1/ledger/account/1001", headers=headers).json()
    assert detail["account"]["code"] == "1001"
    assert detail["rows"], "现金科目应有明细账"
    row = detail["rows"][0]
    assert row["entry_no"].startswith("JV-"), "明细账行应带凭证号"
    assert abs(detail["total_debit"] - detail["total_credit"] - detail["balance"]) < 0.01


# ============================================================
# 权限点 + 菜单注册
# ============================================================
def test_general_ledger_permission_and_menu_registered():
    """「总账」已在权限目录与菜单默认种子里登记，key 能被 all_menu_keys 识别。"""
    from app.core.permissions import PERMISSION_CATALOG, all_menu_keys
    from app.models.menu import default_menu_specs

    assert "general-ledger" in all_menu_keys()
    finance_group = next(g for g in PERMISSION_CATALOG if g["group"] == "finance")
    items = {item["key"]: item["label"] for item in finance_group["items"]}  # type: ignore[index]
    assert items.get("general-ledger") == "总账"

    specs = default_menu_specs()
    page_keys = {page_key for _, _, page_key, _ in specs if page_key}
    assert "general-ledger" in page_keys, "默认菜单树应含「总账」菜单项"
