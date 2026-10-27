"""发票金额编辑漏洞修复（2026-10-27）。

编辑弹窗里「价税合计 / 不含税额 / 税额 / 税率」四个字段以前能改、提交后却静默失效：
后端 `InvoiceUpdate` schema 没收这几个字段，Pydantic 默认静默忽略未声明字段，
于是改金额保存后原样不变、界面还提示「已保存」——用户以为纠正了 OCR 错金额，
实际错金额继续流入进项税抵扣、对账单、完结闸。

本测试钉住三件事：
  1. 金额编辑**真的生效**（PATCH 后落库值 = 提交值）；
  2. 「不含税 + 税额 ≠ 价税合计」被 400 拦截（不允许写脏数据）；
  3. 负数金额被 400 拦截（红字票用 invoice_flag 表达，金额本身存绝对值）。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _create_invoice(**overrides) -> dict:
    payload = {
        "invoice_no": f"AMT-{_hex()}",
        "invoice_type": "专票",
        "total_amount": 1130.0,
        "tax_rate": 13.0,
        "tax_amount": 130.0,
        "excl_tax_amount": 1000.0,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/invoices", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cleanup(invoice_id: int) -> None:
    client.delete(f"/api/v1/invoices/{invoice_id}")


def test_amount_edit_persists():
    """金额编辑真正生效：PATCH 后落库值 = 提交值（漏洞核心回归）。"""
    inv = _create_invoice()
    try:
        patched = client.patch(
            f"/api/v1/invoices/{inv['id']}",
            json={"total_amount": 2260.0, "tax_amount": 260.0, "excl_tax_amount": 2000.0},
        )
        assert patched.status_code == 200, patched.text
        body = patched.json()
        assert round(float(body["total_amount"]), 2) == 2260.0
        assert round(float(body["tax_amount"]), 2) == 260.0
        assert round(float(body["excl_tax_amount"]), 2) == 2000.0
    finally:
        _cleanup(inv["id"])


def test_amount_edit_rejects_inconsistent_sum():
    """「不含税 + 税额 ≠ 价税合计」被 400 拦截，且原因说人话。"""
    inv = _create_invoice()
    try:
        bad = client.patch(
            f"/api/v1/invoices/{inv['id']}",
            json={"total_amount": 100.0, "excl_tax_amount": 88.0, "tax_amount": 11.0},
        )
        assert bad.status_code == 400, bad.text
        assert "金额不一致" in bad.json()["detail"]
    finally:
        _cleanup(inv["id"])


def test_amount_edit_rejects_negative():
    """负数金额被 400 拦截。"""
    inv = _create_invoice()
    try:
        bad = client.patch(f"/api/v1/invoices/{inv['id']}", json={"total_amount": -1.0})
        assert bad.status_code == 400, bad.text
        assert "不能为负数" in bad.json()["detail"]
    finally:
        _cleanup(inv["id"])


def test_amount_edit_lenient_when_no_tax_breakdown():
    """只有价税合计、没有不含税/税额的历史票，改价税合计放行（无从校验恒等式）。"""
    inv = _create_invoice(total_amount=88.8, tax_amount=None, excl_tax_amount=None)
    try:
        ok = client.patch(f"/api/v1/invoices/{inv['id']}", json={"total_amount": 999.0})
        assert ok.status_code == 200, ok.text
        assert round(float(ok.json()["total_amount"]), 2) == 999.0
    finally:
        _cleanup(inv["id"])


def test_amount_edit_rounding_tolerance_one_cent():
    """分位舍入差（±0.01）不误伤：115.04 + 884.96 = 1000.00 这类合法值放行。"""
    inv = _create_invoice(total_amount=1000.0, tax_amount=115.04, excl_tax_amount=884.96)
    try:
        ok = client.patch(
            f"/api/v1/invoices/{inv['id']}",
            json={"total_amount": 1000.0, "tax_amount": 115.04, "excl_tax_amount": 884.96},
        )
        assert ok.status_code == 200, ok.text
    finally:
        _cleanup(inv["id"])
