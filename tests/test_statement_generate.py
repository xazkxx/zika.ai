"""对账单自动生成：发票匹配口径回归测试（2026-10-22）。

## 为什么单独建这个文件

E2E（`scripts/verify_full_business_flow.cjs` 第 18 步）在打包版上跑出来一张
**明显不对**的对账单：客户全额开票（¥120）、全额收款（¥120），可是

    本期已开票 ¥0.00   →   期末应收 −¥120.00（看起来像"客户多付了"）

根因：`generate_statement` 只按 `counterparty_name` 匹配发票，而 App 内手工新建的
销项发票写的是 `buyer_name` + `customer_id`，`counterparty_name` 为空 ——
**自己开的票永远进不了自己的对账单**。

而同一个文件里的"四流穿透"底稿（`_ledger_preview`）早就是
`or_(customer_id, counterparty_name)` 双口径 —— 两条路径不一致才是真 bug。

这里钉住三件事：
1. 销项：只挂 `customer_id` 的发票必须进对账单；
2. 销项：只有 `counterparty_name` 的历史发票也进（别为了修前者把后者弄丢）；
3. 别的客户的发票、区间外的发票、进项方向的发票都不许混进来。
"""

import uuid
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_customer(name: str | None = None) -> dict:
    payload = {"code": _uniq("CUST"), "name": name or f"对账测试客户{uuid.uuid4().hex[:6]}"}
    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _make_invoice(**fields) -> dict:
    payload = {
        "invoice_no": _uniq("INV"),
        "invoice_type": "普票",
        "issue_date": date.today().isoformat(),
        "seller_name": "西安寨卡信息技术有限公司",
        "total_amount": 120.0,
        "direction": "output",
        "status": "正常",
    }
    payload.update(fields)
    response = client.post("/api/v1/invoices", json=payload)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _generate(customer_id: int, **extra) -> dict:
    payload = {
        "direction": "out",
        "party_type": "customer",
        "party_id": customer_id,
        "period_start": date.today().replace(day=1).isoformat(),
        "period_end": date.today().isoformat(),
    }
    payload.update(extra)
    response = client.post("/api/v1/statements/generate", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _invoice_lines(statement: dict) -> list[dict]:
    return [row for row in (statement.get("items") or []) if row.get("source_type") == "invoice"]


def _invoiced_total(statement: dict) -> float:
    """明细金额在 JSON 里是字符串（Decimal → str），必须逐项转 float 再相加。"""
    return round(sum(float(line.get("invoiced_amount") or 0) for line in _invoice_lines(statement)), 2)


def test_generated_statement_picks_invoice_matched_by_customer_id():
    """App 内新建的销项发票只有 customer_id（counterparty_name 为空）也要进对账单。"""
    customer = _make_customer()
    _make_invoice(buyer_name=customer["name"], customer_id=customer["id"], total_amount=120.0)

    statement = _generate(customer["id"])

    lines = _invoice_lines(statement)
    assert lines, f"对账单里没有发票行：{statement}"
    assert round(sum(float(line["invoiced_amount"] or 0) for line in lines), 2) == 120.0
    # 期初 0 + 本期开票 120 − 本期收款 0 = 120
    assert round(float(statement["receivable_balance"]), 2) == 120.0


def test_generated_statement_picks_legacy_invoice_matched_by_name():
    """历史导入的发票只有 counterparty_name，不能因为修了 id 口径就丢掉。"""
    customer = _make_customer()
    _make_invoice(counterparty_name=customer["name"], total_amount=88.0)

    statement = _generate(customer["id"])

    lines = _invoice_lines(statement)
    assert lines, f"按名称的发票没进对账单：{statement}"
    assert round(sum(float(line["invoiced_amount"] or 0) for line in lines), 2) == 88.0


def test_generated_statement_ignores_other_parties_and_out_of_range_invoices():
    """别的客户、区间外、反方向的发票都不许混进来（防止 or_ 写成"全量"。）"""
    customer = _make_customer()
    other = _make_customer()

    _make_invoice(buyer_name=customer["name"], customer_id=customer["id"], total_amount=10.0)
    _make_invoice(buyer_name=other["name"], customer_id=other["id"], total_amount=999.0)
    _make_invoice(
        buyer_name=customer["name"],
        customer_id=customer["id"],
        total_amount=777.0,
        issue_date="2020-01-01",
    )
    _make_invoice(
        buyer_name=customer["name"],
        customer_id=customer["id"],
        total_amount=555.0,
        direction="input",
    )

    statement = _generate(customer["id"])

    lines = _invoice_lines(statement)
    assert lines, f"对账单里没有发票行：{statement}"
    assert round(sum(float(line["invoiced_amount"] or 0) for line in lines), 2) == 10.0


def test_generated_statement_full_invoice_and_receipt_nets_to_zero():
    """全额开票 + 全额收款 → 期末应收 0（这条就是 E2E 里那个 −120 的反例）。"""
    customer = _make_customer()
    _make_invoice(buyer_name=customer["name"], customer_id=customer["id"], total_amount=120.0)

    receipt = client.post(
        "/api/v1/finance/receipt",
        json={
            "party_id": customer["id"],
            "amount": 120.0,
            "occurred_at": date.today().isoformat(),
            "note": "对账单回归：全额收款",
        },
    )
    assert receipt.status_code in (200, 201), receipt.text

    statement = _generate(customer["id"])

    assert round(float(statement["receivable_balance"]), 2) == 0.0, statement
