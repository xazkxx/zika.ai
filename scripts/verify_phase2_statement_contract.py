# -*- coding: utf-8 -*-
"""第二阶段 P2-2 / P2-1 接口验收：对账单预览 + 合同换对方单位。

现场造数据，不依赖库里恰好有什么（pytest 跑完会清掉大量单据）。
断言只看**真数据**：
  预览提交后库里对账单数量不变（预览绝不能偷偷建单）
  按预览行建单 → 行数等于勾选行数（尊重用户勾选，不是重新取一遍）
  合同 PATCH 换 party 后 party_id 与 party_name 同步换掉
"""
import sys
from datetime import date

import requests

BASE = "http://127.0.0.1:8011/api/v1"
S = requests.Session()
S.trust_env = False
ok = fail = 0


def check(label, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {extra}")


token = S.post(f"{BASE}/auth/login", json={"username": "admin", "password": "Admin123"}).json()["access_token"]
H = {"Authorization": f"Bearer {token}"}
TODAY = date.today().isoformat()
YEAR = TODAY[:4]

customers = S.get(f"{BASE}/customers", headers=H).json()
suppliers = S.get(f"{BASE}/suppliers", headers=H).json()
products = S.get(f"{BASE}/products", headers=H).json()
customer = customers[0]
product = next((p for p in products if p.get("sale_price")), products[0])


def make_contract(party_id, status="draft"):
    body = {
        "contract_type": "sales",
        "party_type": "customer",
        "party_id": party_id,
        "sign_date": TODAY,
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 1200}],
    }
    if status != "draft":
        body["status"] = status
    return S.post(f"{BASE}/contracts", json=body, headers=H)


def statement_total():
    return len(S.get(f"{BASE}/statements?limit=200", headers=H).json())


# ------------------------------------------------------------- 造两张合同
c1 = make_contract(customer["id"])
check("造合同 201", c1.status_code == 201, c1.text[:300])
contract_a = c1.json() if c1.status_code == 201 else None

before = statement_total()
r = S.post(
    f"{BASE}/statements/preview",
    json={
        "direction": "out",
        "party_type": "customer",
        "party_id": customer["id"],
        "period_start": f"{YEAR}-01-01",
        "period_end": f"{YEAR}-12-31",
    },
    headers=H,
)
check("预览 200", r.status_code == 200, r.text[:300])
data = r.json() if r.status_code == 200 else {}
print(f"  （{customer['name']} · 预览 {data.get('line_count')} 行）")
check("预览有行", data.get("line_count", 0) > 0, data.get("line_count"))
check("预览后对账单数量不变（没偷建单）", statement_total() == before, f"{statement_total()} vs {before}")
check("预览回 party_name", bool(data.get("party_name")), data.get("party_name"))

items = data.get("items") or []
if items:
    first = items[0]
    for field in ("line_no", "business_date", "source_type", "summary", "contract_amount", "invoiced_amount"):
        check(f"明细含字段 {field}", field in first, list(first)[:8])
    check("合同行能对上刚建的合同号", any(row.get("contract_no") == contract_a["contract_no"] for row in items),
          [row.get("contract_no") for row in items])

    # 只勾第一行去建单
    created = S.post(
        f"{BASE}/statements",
        json={
            "direction": "out",
            "party_type": "customer",
            "party_id": customer["id"],
            "party_name": data["party_name"],
            "period_start": f"{YEAR}-01-01",
            "period_end": f"{YEAR}-12-31",
            "opening_balance": 0,
            "items": [{**first, "line_no": 1}],
        },
        headers=H,
    )
    check("按预览行建单 201", created.status_code == 201, created.text[:300])
    if created.status_code == 201:
        doc = created.json()
        check("建出来只有 1 行（尊重勾选）", doc.get("item_count") == 1, doc.get("item_count"))
        check("单号前缀 DZ", str(doc.get("statement_no", "")).startswith("DZ"), doc.get("statement_no"))
        S.delete(f"{BASE}/statements/{doc['id']}", headers=H)

bad = S.post(
    f"{BASE}/statements/preview",
    json={"direction": "out", "party_type": "supplier", "party_id": 1,
          "period_start": f"{YEAR}-01-01", "period_end": f"{YEAR}-12-31"},
    headers=H,
)
check("应收配供应商 → 400", bad.status_code == 400, bad.status_code)

# ------------------------------------------------------- 合同换对方单位
contract_b = make_contract(customer["id"])
check("造第二张草稿合同 201", contract_b.status_code == 201, contract_b.text[:300])
if contract_b.status_code == 201:
    draft = contract_b.json()
    check("新合同状态是 draft", draft.get("status") == "draft", draft.get("status"))
    new_party = next((row for row in customers if row["id"] != customer["id"]), None)
    if new_party:
        r = S.patch(
            f"{BASE}/contracts/{draft['id']}",
            json={"party_id": new_party["id"], "party_name": new_party["name"]},
            headers=H,
        )
        check("合同 PATCH 200", r.status_code == 200, r.text[:300])
        if r.status_code == 200:
            body = r.json()
            check("party_id 已换", body.get("party_id") == new_party["id"], body.get("party_id"))
            check("party_name 同步", body.get("party_name") == new_party["name"], body.get("party_name"))
    # 反审核：退回草稿（对已草稿是幂等）
    r = S.patch(f"{BASE}/contracts/{draft['id']}/status", json={"status": "draft"}, headers=H)
    check("合同状态接口 200", r.status_code == 200, r.status_code)
    S.delete(f"{BASE}/contracts/{draft['id']}", headers=H)

if contract_a:
    S.delete(f"{BASE}/contracts/{contract_a['id']}", headers=H)

print(f"\n=== {ok} PASS / {fail} FAIL ===")
sys.exit(1 if fail else 0)
