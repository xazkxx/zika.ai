# -*- coding: utf-8 -*-
"""完结闸验收台（2026-10-20，状态机重构 B 部分）。

验证链路：建单(1000) → 直接完结 409 → 收款 1000 → 仍 409(未开票)
        → 开票 1000 → settled=True → 完结 200 → 清场。
口径唯一权威：后端 `_apply_settlement_fields`（净额=应收-折让；应收余额=净额-已收；
未开票=净额-已开票；settled=两者都≤0）。

反证铁律：每条断言都要"改坏会红"。本脚本用**精确数值断言**（不 is not None），
且清场阶段硬删数据后核对列表里不再出现。
"""
import sys
import requests

BASE = "http://127.0.0.1:8011/api/v1"
S = requests.Session()
S.trust_env = False  # 本机代理会拦 localhost

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("" if cond else f"  | {detail}"))


def find_order(keyword, doc_type="outbound"):
    r = S.get(f"{BASE}/sales-orders", params={"keyword": keyword, "doc_type": doc_type}, timeout=15)
    r.raise_for_status()
    for item in r.json():
        if item["order_no"] == keyword:
            return item
    return None


def purge_payment_flows(order_id):
    """红冲/删单前置：按 journal_entry_lines→journal_entries→financial_transactions 硬清本单流水。

    ⚠️ 实测（2026-10-20）：销售出库产生的 related_type 是 `sales_out`（开单应收）
    + `receipt`（收款登记），不是 'sales_order' —— 写错一个都清不干净、删单 409。
    """
    import psycopg
    conn = psycopg.connect("postgresql://erp:erp123456@127.0.0.1:5432/erp")
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM journal_entry_lines WHERE entry_id IN (
            SELECT je.id FROM journal_entries je
            JOIN financial_transactions ft ON je.flow_id = ft.id
            WHERE ft.related_order_id = %s
              AND ft.related_type IN ('sales_out', 'receipt'))
        """,
        (order_id,),
    )
    cur.execute(
        """DELETE FROM journal_entries WHERE flow_id IN (
            SELECT id FROM financial_transactions
            WHERE related_order_id = %s
              AND related_type IN ('sales_out', 'receipt'))""",
        (order_id,),
    )
    cur.execute(
        "DELETE FROM financial_transactions WHERE related_order_id=%s"
        " AND related_type IN ('sales_out', 'receipt')",
        (order_id,),
    )
    conn.commit()
    cur.close()
    conn.close()


def main():
    import time
    stamp = time.strftime("%H%M%S")
    order_no = f"CGB{stamp}"

    # ── 前置：拿客户/仓库/商品 ──
    customers = S.get(f"{BASE}/customers", timeout=15).json()
    warehouses = S.get(f"{BASE}/warehouses", timeout=15).json()
    products = S.get(f"{BASE}/products", timeout=15).json()
    assert customers and warehouses and products, "前置档案为空"
    cust, wh, prod = customers[0], warehouses[0], products[0]

    # ── 1. 建单：总额 1000 ──
    r = S.post(
        f"{BASE}/sales-orders",
        json={
            "order_no": order_no,
            "doc_type": "outbound",
            "customer_id": cust["id"],
            "warehouse_id": wh["id"],
            "order_date": time.strftime("%Y-%m-%d"),
            "items": [{"product_id": prod["id"], "quantity": 1000, "unit_price": 1.0}],
        },
        timeout=15,
    )
    check("1. 建单 201", r.status_code == 201, f"got {r.status_code} {r.text[:200]}")
    row = r.json()
    oid = row["id"]
    check("1a. total_amount=1000", abs(float(row["total_amount"]) - 1000) < 1e-6, row["total_amount"])

    # ── 2. 没收钱没开票 → 完结必须 409 ──
    r = S.patch(f"{BASE}/sales-orders/{oid}/status", json={"status": "completed"}, timeout=15)
    ok409 = r.status_code == 409
    d = r.json().get("detail") if ok409 else r.text[:200]
    check("2. 完结 409（没收钱没开票）", ok409, f"got {r.status_code}")
    check("2a. detail.code=not_settled", isinstance(d, dict) and d.get("code") == "not_settled", str(d)[:150])
    check("2b. outstanding=1000", isinstance(d, dict) and abs(float(d.get("outstanding_amount", 0)) - 1000) < 1e-6, str(d)[:200])
    check("2c. uninvoiced=1000", isinstance(d, dict) and abs(float(d.get("uninvoiced_amount", 0)) - 1000) < 1e-6, str(d)[:200])

    # ── 3. 收款 1000 → 列表字段：outstanding=0，uninvoiced 仍 1000，settled=False ──
    r = S.post(f"{BASE}/finance/receipt", json={"party_id": cust["id"], "order_id": oid, "amount": 1000}, timeout=15)
    check("3. 收款 1000 成功", r.status_code in (200, 201), f"got {r.status_code} {r.text[:200]}")
    row = find_order(order_no)
    check("3a. outstanding=0", abs(float(row["outstanding_amount"])) < 1e-6, row["outstanding_amount"])
    check("3b. uninvoiced=1000（还没开票）", abs(float(row["uninvoiced_amount"]) - 1000) < 1e-6, row["uninvoiced_amount"])
    check("3c. settled=False", row["settled"] is False, row["settled"])

    # ── 4. 仍完结 → 409（未开票）──
    r = S.patch(f"{BASE}/sales-orders/{oid}/status", json={"status": "completed"}, timeout=15)
    d = r.json().get("detail") if r.status_code == 409 else r.text[:200]
    check("4. 收完款未开票完结仍 409", r.status_code == 409, f"got {r.status_code}")
    check("4a. message 提到未开票", isinstance(d, dict) and "未开" in str(d.get("message", "")), str(d)[:200])

    # ── 5. 开票 1000（销项、挂本单）→ settled=True ──
    r = S.post(
        f"{BASE}/invoices",
        json={
            "invoice_no": f"TESTINV{stamp}",
            "invoice_type": "普票",
            "issue_date": time.strftime("%Y-%m-%d"),
            "total_amount": 1000,
            "direction": "output",
            "customer_id": cust["id"],
            "buyer_name": cust.get("name"),
            "related_order_id": oid,
        },
        timeout=15,
    )
    check("5. 开票 201", r.status_code == 201, f"got {r.status_code} {r.text[:200]}")
    inv = r.json()
    row = find_order(order_no)
    check("5a. uninvoiced=0", abs(float(row["uninvoiced_amount"])) < 1e-6, row["uninvoiced_amount"])
    check("5b. outstanding=0", abs(float(row["outstanding_amount"])) < 1e-6, row["outstanding_amount"])
    check("5c. settled=True", row["settled"] is True, row["settled"])

    # ── 6. 完结 200 ──
    r = S.patch(f"{BASE}/sales-orders/{oid}/status", json={"status": "completed"}, timeout=15)
    check("6. 完结 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    check("6a. 状态=completed", r.json().get("status") == "completed", r.json().get("status"))

    # ── 7. 超额开票兜底：再来 500 的票不应把 uninvoiced 打成负数上报口径混乱 ──
    #   （只验证列表字段仍 ≥0 且 settled 仍 True；不强约束后端拒绝开票）
    # （省略：核心闸已验证，避免引入第二张票的清理负担）

    # ── 清场：删发票 → 硬清收款流水 → 删单 ──
    r = S.delete(f"{BASE}/invoices/{inv['id']}", timeout=15)
    if r.status_code == 404:
        # 发票列表找 id 再删
        lst = S.get(f"{BASE}/invoices", params={"keyword": f"TESTINV{stamp}"}, timeout=15).json()
        items = lst.get("items", lst) if isinstance(lst, dict) else lst
        for it in items:
            if str(it.get("invoice_no")) == f"TESTINV{stamp}":
                r = S.delete(f"{BASE}/invoices/{it['id']}", timeout=15)
    check("C1. 删发票", r.status_code in (200, 204), f"got {r.status_code}")
    try:
        purge_payment_flows(oid)
        check("C2. 硬清收款流水", True, "")
    except Exception as exc:  # noqa: BLE001
        check("C2. 硬清收款流水", False, str(exc)[:150])
    r = S.delete(f"{BASE}/sales-orders/{oid}", timeout=15)
    check("C3. 删单", r.status_code in (200, 204), f"got {r.status_code} {r.text[:150]}")
    check("C4. 列表已无此单", find_order(order_no) is None, "")

    print(f"\n===== 完结闸验收台：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
    if FAIL:
        print("失败明细：")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
