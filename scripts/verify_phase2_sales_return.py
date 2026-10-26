# -*- coding: utf-8 -*-
"""第二阶段 P2-1 验收：销售退货「草稿 / 审核 / 反审核 / 作废」的账实一致性。

⚠️ 2026-10-20 重构后的口径（旧脚本已废弃，旧口径是「反审核=冲账」，那是错的）：
  反审核（submitted → draft）  **只改状态，账一分钱都不许动**。
  作废（POST /{id}/void）      **才是唯一会红冲的入口**，撤库存 + 撤应收，单据落 cancelled。
  已审核改明细                 按「先冲后落」重算，账面等于新明细，不留双份。

断言一律看**真账**（直查 inventory_transactions / 走 /finance），不看接口返回码：
  1. 建草稿         → 库存 0 行、应收 0 笔
  2. 审核 submitted → 库存 +N、应收 -金额
  3. 反审核 draft   → 状态回 draft，**库存与应收原样保留**
  4. 反审核后再审核 → 不重复落账（幂等），仍是 1 行库存 + 1 笔应收
  5. 草稿改明细     → 金额变了，账不动（因为账还是上一版的，等审核/作废才动）
  6. 一次提交带明细 → 库存 +N 只加一次、应收只 1 笔
  7. 已审核改明细   → 冲旧落新，库存/应收与新明细一致，不留双份
  8. 作废           → 库存 0 行、应收 0 笔、状态 cancelled、备注写进原因
  9. 重复作废       → 幂等，不再冲账，不报错
 10. 删除           → 204，账上依旧干净
"""
import sys

import psycopg
import requests

BASE = "http://127.0.0.1:8011/api/v1"
S = requests.Session()
S.trust_env = False

ok = 0
fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {extra}")


def login():
    r = S.post(f"{BASE}/auth/login", json={"username": "admin", "password": "Admin123"})
    r.raise_for_status()
    return r.json()["access_token"]


token = login()
H = {"Authorization": f"Bearer {token}"}
print("登录 OK")

customers = S.get(f"{BASE}/customers", headers=H).json()
products = S.get(f"{BASE}/products", headers=H).json()
customer = customers[0]
product = next((p for p in products if p.get("sale_price")), products[0])
print(f"用客户 {customer['id']} {customer['name']} / 商品 {product['id']} {product['name']}")


from db_config import psycopg_dsn  # noqa: E402

DSN = psycopg_dsn()


def stock_rows(rid):
    """直接查库拿这张退货单的库存流水 —— /inventory 是按「仓库×商品」多行的，
    同一个商品在多仓时 next() 抓到哪一行全看返回顺序，拿它做断言会假红假绿。"""
    with psycopg.connect(DSN, autocommit=True) as conn:
        cur = conn.execute(
            "SELECT transaction_type, quantity FROM inventory_transactions"
            " WHERE related_type='sales_return' AND related_order_id=%s ORDER BY id",
            (rid,),
        )
        return [(r[0], int(r[1])) for r in cur.fetchall()]


def posted_qty(rid):
    """这张单在库存上留下的净数量（入库为正）。0 = 没落账。"""
    return sum(q for t, q in stock_rows(rid) if t == "inbound")


def flows_of(rid):
    rows = S.get(f"{BASE}/finance", headers=H).json()
    return [
        r for r in rows
        if r.get("related_type") == "sales_return" and int(r.get("related_order_id") or 0) == int(rid)
    ]


def flow_total(rid):
    return round(sum(float(f["amount"]) for f in flows_of(rid)), 2)


print("校验口径：反审核账不动 / 只有作废才红冲（2026-10-20 新语义）")

# ---------------------------------------------------------------- 1. 建草稿
payload = {
    "customer_id": customer["id"],
    "return_date": "2026-10-20",
    "return_reason": "验收台-草稿",
    "status": "draft",
    "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 100}],
}
r = S.post(f"{BASE}/sales-returns", json=payload, headers=H)
check("草稿创建 201", r.status_code == 201, r.text[:300])
doc = r.json()
rid = doc["id"]
check("草稿状态 = draft", doc["status"] == "draft", doc["status"])
check("草稿金额 = 200", float(doc["total_amount"]) == 200.0, doc["total_amount"])
check("草稿不动库存", stock_rows(rid) == [], stock_rows(rid))
check("草稿不写应收", flows_of(rid) == [], flows_of(rid))

# ---------------------------------------------------------- 2. 审核（draft→submitted）
r = S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "submitted"}, headers=H)
check("审核 200", r.status_code == 200, r.text[:300])
submitted = r.json()
check("状态 = submitted", submitted["status"] == "submitted", submitted["status"])
check("审核后库存 +2", posted_qty(rid) == 2, stock_rows(rid))
flows = flows_of(rid)
check("审核后应收 1 笔", len(flows) == 1, len(flows))
check("应收金额 = -200", flow_total(rid) == -200.0, flow_total(rid))

# ------------------------------------------------- 3. 反审核（submitted→draft，账不动！）
r = S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "draft"}, headers=H)
check("反审核 200", r.status_code == 200, r.text[:300])
check("状态回 draft", r.json()["status"] == "draft", r.json()["status"])
check("★ 反审核后库存仍在（+2，账一分不动）", posted_qty(rid) == 2 and len(stock_rows(rid)) == 1,
      stock_rows(rid))
check("★ 反审核后应收仍在（-200，账一分不动）", flow_total(rid) == -200.0, flow_total(rid))

# ------------------------------------------- 4. 反审核后再审核：幂等，不重复落账
r = S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "submitted"}, headers=H)
check("再次审核 200", r.status_code == 200, r.text[:300])
check("★ 再次审核不重复加库存（仍 +2、仍 1 行）",
      posted_qty(rid) == 2 and len(stock_rows(rid)) == 1, stock_rows(rid))
check("★ 再次审核不重复写应收（仍 1 笔 -200）",
      len(flows_of(rid)) == 1 and flow_total(rid) == -200.0,
      [(f["amount"]) for f in flows_of(rid)])

# ------------------------------ 5. 退回草稿后改明细：金额变了，账按上一版保留（等审核才同步）
S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "draft"}, headers=H)
r = S.patch(
    f"{BASE}/sales-returns/{rid}",
    json={"items": [{"product_id": product["id"], "quantity": 5, "unit_price": 70}]},
    headers=H,
)
check("草稿改明细 200", r.status_code == 200, r.text[:300])
check("金额变 350", float(r.json()["total_amount"]) == 350.0, r.json()["total_amount"])
check("草稿改明细不改库存（账还是上一版 +2）", posted_qty(rid) == 2, stock_rows(rid))
check("草稿改明细不改应收（账还是上一版 -200）", flow_total(rid) == -200.0, flow_total(rid))

# ---------------------------------------------------------- 6. 一次提交（带明细直接审核）
r = S.patch(
    f"{BASE}/sales-returns/{rid}",
    json={"status": "submitted", "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 100}]},
    headers=H,
)
check("一次 PATCH 带状态+明细 200", r.status_code == 200, r.text[:300])
check("金额 300", float(r.json()["total_amount"]) == 300.0, r.json()["total_amount"])
check("库存 +3 且只有 1 行", posted_qty(rid) == 3 and len(stock_rows(rid)) == 1, stock_rows(rid))
flows = flows_of(rid)
check("应收只有 1 笔（没重账）", len(flows) == 1, len(flows))
check("应收金额 -300", flow_total(rid) == -300.0, flow_total(rid))

# ---------------------------------------------- 7. 已审核改明细：冲旧落新，不留双份
r = S.patch(
    f"{BASE}/sales-returns/{rid}",
    json={"items": [{"product_id": product["id"], "quantity": 4, "unit_price": 100}]},
    headers=H,
)
check("已审核改明细 200", r.status_code == 200, r.text[:300])
check("金额 400", float(r.json()["total_amount"]) == 400.0, r.json()["total_amount"])
check("库存改成 +4（旧流水冲掉，不留双份）", posted_qty(rid) == 4 and len(stock_rows(rid)) == 1,
      stock_rows(rid))
flows = flows_of(rid)
check("应收仍 1 笔且金额 -400", len(flows) == 1 and flow_total(rid) == -400.0,
      [(f["amount"]) for f in flows])

# ---------------------------------------------------------- 8. PATCH 里传 cancelled 必须被拒
r = S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "cancelled"}, headers=H)
check("★ 改状态接口不许把单子置 cancelled（400）", r.status_code == 400, r.status_code)
check("★ 被拒后库存没动（仍 +4）", posted_qty(rid) == 4, stock_rows(rid))
check("★ 被拒后应收没动（仍 -400）", flow_total(rid) == -400.0, flow_total(rid))
r = S.patch(f"{BASE}/sales-returns/{rid}", json={"status": "cancelled"}, headers=H)
check("★ 编辑接口同样不许置 cancelled（400）", r.status_code == 400, r.status_code)

# ---------------------------------------------------------------- 9. 作废（唯一红冲入口）
r = S.post(f"{BASE}/sales-returns/{rid}/void", json={"reason": "验收台-作废测试"}, headers=H)
check("作废 200", r.status_code == 200, r.text[:300])
check("状态 = cancelled", r.json()["status"] == "cancelled", r.json().get("status"))
check("★ 作废后库存流水清空", stock_rows(rid) == [], stock_rows(rid))
check("★ 作废后应收清空", flows_of(rid) == [], flows_of(rid))
note = (r.json().get("note") or "")
check("★ 作废原因写进备注", "验收台-作废测试" in note, note[:120])

# ---------------------------------------------------------------- 10. 重复作废：幂等
r = S.post(f"{BASE}/sales-returns/{rid}/void", json={"reason": "再点一次"}, headers=H)
check("重复作废 200（幂等不报错）", r.status_code == 200, r.text[:300])
check("重复作废不再冲账（库存仍空）", stock_rows(rid) == [], stock_rows(rid))
check("重复作废不再冲账（应收仍空）", flows_of(rid) == [], flows_of(rid))

# ------------------------------------------- 11. 作废单不许再编辑 / 再改状态
r = S.patch(f"{BASE}/sales-returns/{rid}", json={"return_reason": "改一下"}, headers=H)
check("★ 作废单编辑被拦（409）", r.status_code == 409, r.status_code)
r = S.patch(f"{BASE}/sales-returns/{rid}/status", json={"status": "draft"}, headers=H)
check("★ 作废单不许退回草稿（409）", r.status_code == 409, r.status_code)

# ---------------------------------------------------------------- 12. 清理
r = S.delete(f"{BASE}/sales-returns/{rid}", headers=H)
check("删除 204", r.status_code == 204, r.status_code)
check("删除后库存流水清空", stock_rows(rid) == [], stock_rows(rid))
check("删除后应收清空", flows_of(rid) == [], flows_of(rid))

print(f"\n=== {ok} PASS / {fail} FAIL ===")
sys.exit(1 if fail else 0)
