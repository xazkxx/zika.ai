# -*- coding: utf-8 -*-
"""老系统 UX 升级验收台（2026-10-20 无人值守夜）。

覆盖：
  A. 反审核（unsubmit）：
     A1 造销售订单 → 审核 approved → 反审核 → draft=200，列表字段带回；
     A2 已产生流水的单 → 409（文案含"流水"）；
     A3 completed → 409。
  B. agent/summary：无 token 401；带 token 200 且关键键齐全、数值是 float。
  C. agent 501 占位：/agent/stock-alerts。

清场：删订单（无流水可直接删）。
"""
import sys
import time

import requests

BASE = "http://127.0.0.1:8011/api/v1"
S = requests.Session()
S.trust_env = False

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  | {detail}"))


def main():
    token = S.post(
        f"{BASE}/auth/login", json={"username": "admin", "password": "Admin123"}, timeout=15
    ).json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}

    customers = S.get(f"{BASE}/customers", timeout=15).json()
    warehouses = S.get(f"{BASE}/warehouses", timeout=15).json()
    products = S.get(f"{BASE}/products", timeout=15).json()
    cust, wh, prod = customers[0], warehouses[0], products[0]
    stamp = time.strftime("%H%M%S")

    # ── A1 反审核成功链 ──
    r = S.post(
        f"{BASE}/sales-orders",
        json={
            "order_no": f"UXT{stamp}",
            "doc_type": "order",
            "customer_id": cust["id"],
            "warehouse_id": wh["id"],
            "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": 2.0}],
        },
        timeout=15,
    )
    check("A0 建销售订单 201", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
    oid = r.json()["id"]

    r = S.patch(f"{BASE}/sales-orders/{oid}/status", json={"status": "approved"}, headers=H, timeout=15)
    check("A1 审核 approved", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

    r = S.patch(f"{BASE}/sales-orders/{oid}/unsubmit", headers=H, timeout=15)
    ok = r.status_code == 200
    check("A1 反审核 200", ok, f"{r.status_code} {r.text[:150]}")
    check("A1a 状态回到 draft", ok and r.json().get("status") == "draft", str(r.json())[:120])

    # 审核回去，验证 unsubmit 幂等可用
    r = S.patch(f"{BASE}/sales-orders/{oid}/status", json={"status": "approved"}, headers=H, timeout=15)
    r = S.patch(f"{BASE}/sales-orders/{oid}/unsubmit", headers=H, timeout=15)
    check("A1b 二次反审核仍 200", r.status_code == 200 and r.json().get("status") == "draft", f"{r.status_code}")

    # ── A2 有流水的单 → 409 ──
    r = S.post(
        f"{BASE}/sales-orders",
        json={
            "order_no": f"UXO{stamp}",
            "doc_type": "outbound",
            "customer_id": cust["id"],
            "warehouse_id": wh["id"],
            "items": [{"product_id": prod["id"], "quantity": 1, "unit_price": 2.0}],
        },
        timeout=15,
    )
    outbound_id = r.json()["id"]
    # outbound 创建即 submitted 且写流水 → unsubmit 必须被闸口拦下
    r = S.patch(f"{BASE}/sales-orders/{outbound_id}/unsubmit", headers=H, timeout=15)
    check("A2 出库单(有流水)反审核 409", r.status_code == 409, f"{r.status_code} {r.text[:150]}")
    check("A2a 文案提到流水", "流水" in str(r.json().get("detail", "")), r.text[:150])

    # ── A3 completed → 409 ──
    # 给出库单收款+开票+完结（完结闸路径），然后 unsubmit 应被第一道闸拦
    S.post(f"{BASE}/finance/receipt", json={"party_id": cust["id"], "order_id": outbound_id, "amount": 2}, timeout=15)
    S.post(
        f"{BASE}/invoices",
        json={
            "invoice_no": f"UXINV{stamp}",
            "invoice_type": "普票",
            "total_amount": 2,
            "direction": "output",
            "customer_id": cust["id"],
            "related_order_id": outbound_id,
        },
        timeout=15,
    )
    S.patch(f"{BASE}/sales-orders/{outbound_id}/status", json={"status": "completed"}, headers=H, timeout=15)
    r = S.patch(f"{BASE}/sales-orders/{outbound_id}/unsubmit", headers=H, timeout=15)
    check("A3 completed 反审核 409", r.status_code == 409, f"{r.status_code} {r.text[:150]}")

    # ── B agent/summary ──
    r = S.get(f"{BASE}/agent/summary", timeout=15)
    check("B1 无 token 401", r.status_code == 401, r.status_code)
    r = S.get(f"{BASE}/agent/summary", headers=H, timeout=15)
    d = r.json() if r.status_code == 200 else {}
    check("B2 带 token 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
    check(
        "B3 键齐全",
        all(k in d for k in ("counts", "today", "receivable", "payable", "sales_orders_by_status")),
        str(list(d.keys())),
    )
    check("B4 金额是 float", isinstance(d.get("today", {}).get("sales_amount"), float), str(d.get("today")))
    r = S.get(f"{BASE}/agent/stock-alerts", headers=H, timeout=15)
    check("C1 占位接口 501", r.status_code == 501, r.status_code)

    # ── 清场 ──
    # UXO 单有流水：红冲太重，直接 SQL 清（与 verify_completion_gate 同法）
    sys.path.insert(0, "scripts")
    from verify_completion_gate import purge_payment_flows

    purge_payment_flows(outbound_id)
    # 删它的发票
    lst = S.get(f"{BASE}/invoices", params={"keyword": f"UXINV{stamp}"}, timeout=15).json()
    for it in (lst.get("items") if isinstance(lst, dict) else lst) or []:
        if str(it.get("invoice_no")) == f"UXINV{stamp}":
            S.delete(f"{BASE}/invoices/{it['id']}", timeout=15)
    check("D1 删出库单", S.delete(f"{BASE}/sales-orders/{outbound_id}", timeout=15).status_code == 204, "")
    check("D2 删订单", S.delete(f"{BASE}/sales-orders/{oid}", timeout=15).status_code == 204, "")

    print(f"\n===== UX 升级验收台：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
    if FAIL:
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
