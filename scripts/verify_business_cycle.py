"""业务闭环核查：从期初建账一路走到销售回款，逐环节验证，把断点暴露出来。

## 为什么用「临时账套」跑

多账套落地之后，这成了最干净的做法：
- **完全不碰真实数据** —— 整条链跑在一个新建的临时 schema 里，跑完连 schema 一起删；
- 顺便**验证账套隔离**本身（临时账套里的期初/单据/库存/财务，绝不泄漏到另外三家）。

## 核查的链路（对照 ERPNext 的 P2P + O2C）

```
建账套
  └ ① 期初建账     仓库 / 商品 / 客户 / 供应商 → 期初库存 + 期初往来
      └ ② 采购     采购订单 → 采购入库 → 付款
          └ ③ 库存  数量与金额核对
              └ ④ 销售  报价单 → 销售订单 → 销售出库
                  └ ⑤ 开票  销项发票
                      └ ⑥ 回款  收款登记
                          └ ⑦ 财务  应收应付 / 往来对账 / 期间汇总
                              └ ⑧ 项目  成本归集
```

每一环都断言"上一环的副作用真的落地了"（库存变了没、财务流水写了没、余额冲减了没），
而不是只看接口返回 200 —— **接口 200 但库存没动，才是最难发现的问题**。

    python scripts/verify_business_cycle.py
"""

from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import tenant  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.company import Company, UserCompany  # noqa: E402
from app.models.user import User  # noqa: E402

client = TestClient(app)
TAG = uuid.uuid4().hex[:6].upper()
CODE = f"co_cycle_{TAG.lower()}"

RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((label, bool(ok), detail))
    mark = "✓" if ok else "✗"
    print(f"   {mark} {label}" + (f"   {detail}" if detail else ""))
    return bool(ok)


def section(title: str) -> None:
    print(f"\n{'─' * 74}\n{title}\n{'─' * 74}")


# ===========================================================================
def make_temp_company() -> int:
    """建一个临时账套（隔离：整条链跑在自己的 schema 里）。"""
    from app.core.tenant import create_tenant_schema, create_tenant_tables

    db = SessionLocal()
    try:
        company = Company(
            code=CODE,
            name=f"闭环核查公司-{TAG}",
            own_name=f"闭环核查公司-{TAG}",
            tax_no=f"91CYCLE{TAG}",
            schema_name=CODE,
            is_active=True,
            sort_order=999,
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        cid = company.id
        admin = db.query(User).filter_by(username="admin").first()
        db.add(UserCompany(user_id=admin.id, company_id=cid, is_default=False))
        db.commit()
    finally:
        db.close()

    create_tenant_schema(CODE)
    create_tenant_tables(CODE, Base.metadata)
    return cid


def drop_temp_company(cid: int) -> None:
    db = SessionLocal()
    try:
        db.query(UserCompany).filter(UserCompany.company_id == cid).delete()
        db.query(Company).filter(Company.id == cid).delete()
        db.commit()
    finally:
        db.close()
    with tenant.engine_for("public").begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{CODE}" CASCADE'))


def login() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123", "company": CODE})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def stock_qty(headers, warehouse_id: int, product_id: int) -> float:
    rows = client.get("/api/v1/inventory/stock", headers=headers).json()
    rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    for row in rows:
        if row.get("warehouse_id") == warehouse_id and row.get("product_id") == product_id:
            return float(row.get("quantity") or 0)
    return 0.0


def recon(headers, party_type: str, party_id: int) -> dict:
    resp = client.get(f"/api/v1/finance/reconciliation/{party_type}/{party_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ===========================================================================
def main() -> None:
    print(f"业务闭环核查（临时账套 {CODE}，跑完即删）")
    cid = make_temp_company()
    try:
        h = login()

        # ---------------------------------------------------------------
        section("① 期初建账（建账是整条链的起点，没有它后面全是浮的）")
        wh = client.post("/api/v1/warehouses", json={"code": f"WH-{TAG}", "name": "闭环核查仓"}, headers=h).json()
        prod = client.post(
            "/api/v1/products",
            json={"sku": f"SKU-CYCLE-{TAG}", "name": "闭环核查商品", "unit": "件",
                  "purchase_price": 80, "sale_price": 120, "tax_rate": 13},
            headers=h,
        ).json()
        cust = client.post("/api/v1/customers", json={"code": f"CUST-{TAG}", "name": "闭环客户"}, headers=h).json()
        supp = client.post("/api/v1/suppliers", json={"code": f"SUP-{TAG}", "name": "闭环供应商"}, headers=h).json()
        check("建仓库 / 商品 / 客户 / 供应商", all(x.get("id") for x in (wh, prod, cust, supp)))

        r = client.put(
            "/api/v1/opening-stock",
            json={"items": [{"warehouse_id": wh["id"], "product_id": prod["id"], "quantity": 100, "unit_price": 80}]},
            headers=h,
        )
        check("写期初库存（100 件 @80）", r.status_code == 200, r.text[:100])
        q0 = stock_qty(h, wh["id"], prod["id"])
        check("期初库存已体现为现存量", q0 == 100, f"现存量={q0}")

        r = client.put(
            "/api/v1/opening-balances",
            json={"receivable": [{"id": cust["id"], "init_amount": 5000}],
                  "payable": [{"id": supp["id"], "init_amount": 3000}]},
            headers=h,
        )
        check("写期初应收 5000 / 应付 3000", r.status_code == 200, r.text[:100])
        c0 = recon(h, "customer", cust["id"])
        check("客户对账单体现期初", float(c0["summary"]["opening_balance"]) == 5000, f"期初={c0['summary']['opening_balance']}")

        # ---------------------------------------------------------------
        section("② 采购：订单 → 入库 → 付款")
        po = client.post(
            "/api/v1/purchase-orders",
            json={"supplier_id": supp["id"], "doc_type": "order", "order_date": "2026-10-01",
                  "items": [{"product_id": prod["id"], "quantity": 50, "unit_price": 80}]},
            headers=h,
        )
        check("采购订单创建", po.status_code == 201, po.text[:140])
        po_body = po.json()
        qty_before_po = stock_qty(h, wh["id"], prod["id"])
        check("采购订单**不动库存**（只订货）", qty_before_po == q0, f"{qty_before_po} vs {q0}")

        po2 = client.post(f"/api/v1/purchase-orders/{po_body['id']}/to-inbound", headers=h)
        check("采购订单 → 采购入库单", po2.status_code == 200, po2.text[:140])
        q1 = stock_qty(h, wh["id"], prod["id"])
        check("入库后库存 +50", q1 == 150, f"现存量={q1}")

        cp = recon(h, "supplier", supp["id"])
        check("入库后应付 = 期初 3000 + 采购 4000", float(cp["summary"]["closing_balance"]) == 7000,
              f"期末={cp['summary']['closing_balance']}")

        pay = client.post("/api/v1/finance/payment",
                          json={"party_id": supp["id"], "amount": 4000, "occurred_at": "2026-10-05",
                                "order_id": po2.json()["id"]}, headers=h)
        check("付款 4000", pay.status_code == 201, pay.text[:140])
        if pay.status_code == 201:
            check("付款金额全额冲抵到单据", float(pay.json()["applied_amount"]) == 4000, str(pay.json()))
        cp2 = recon(h, "supplier", supp["id"])
        check("付款后应付回落到 3000", float(cp2["summary"]["closing_balance"]) == 3000,
              f"期末={cp2['summary']['closing_balance']}")

        # ---------------------------------------------------------------
        section("③ 库存")
        q2 = stock_qty(h, wh["id"], prod["id"])
        check("现存量 = 期初100 + 采购50 = 150", q2 == 150, f"现存量={q2}")

        # ---------------------------------------------------------------
        section("④ 销售：报价单 → 销售订单 → 销售出库（挂项目）")
        prj = client.post(
            "/api/v1/projects",
            json={"code": f"PRJ-{TAG}", "name": "闭环核查项目", "manager": "张三",
                  "status": "in_progress", "progress": 30, "budget": 100000},
            headers=h,
        ).json()
        pid = prj.get("id")
        check("先建项目（后面整条销售链都挂到它上面）", bool(pid), str(prj)[:100])
        qt = client.post(
            "/api/v1/quotations",
            json={"customer_id": cust["id"], "warehouse_id": wh["id"], "quote_date": "2026-10-10",
                  "items": [{"product_id": prod["id"], "quantity": 20, "unit_price": 120}]},
            headers=h,
        )
        check("报价单创建", qt.status_code == 201, qt.text[:140])

        so = client.post(
            "/api/v1/sales-orders",
            json={"customer_id": cust["id"], "warehouse_id": wh["id"], "project_id": pid,
                  "doc_type": "order", "order_date": "2026-10-11",
                  "items": [{"product_id": prod["id"], "quantity": 20, "unit_price": 120}]},
            headers=h,
        )
        check("销售订单创建", so.status_code == 201, so.text[:140])
        q3 = stock_qty(h, wh["id"], prod["id"])
        check("销售订单**不动库存**", q3 == 150, f"现存量={q3}")

        so2 = client.post(f"/api/v1/sales-orders/{so.json()['id']}/to-outbound", headers=h)
        check("销售订单 → 销售出库", so2.status_code == 200, so2.text[:160])
        q4 = stock_qty(h, wh["id"], prod["id"])
        check("出库后库存 -20 → 130", q4 == 130, f"现存量={q4}")

        cc = recon(h, "customer", cust["id"])
        check("出库后应收 = 期初 5000 + 销售 2400", float(cc["summary"]["closing_balance"]) == 7400,
              f"期末={cc['summary']['closing_balance']}")

        # ---------------------------------------------------------------
        section("⑤ 开票（销项）")
        inv = client.post(
            "/api/v1/invoices",
            json={"invoice_no": f"2661CYCLE{TAG}", "invoice_type": "普票", "issue_date": "2026-10-12",
                  "total_amount": 2400, "tax_amount": 276.11, "excl_tax_amount": 2123.89, "tax_rate": 13,
                  "buyer_name": "闭环客户", "buyer_tax_no": f"91CUST{TAG}",
                  "seller_name": f"闭环核查公司-{TAG}", "seller_tax_no": f"91CYCLE{TAG}",
                  "items": [{"item_name": "闭环核查商品", "quantity": 20, "unit_price": 120, "amount": 2400}]},
            headers=h,
        )
        check("销项发票入库", inv.status_code == 201, inv.text[:140])
        if inv.status_code == 201:
            check("进销项自动判为**销项**", inv.json()["direction"] == "output",
                  f"判为 {inv.json()['direction_label']}")

        # ---------------------------------------------------------------
        section("⑥ 回款")
        rec = client.post("/api/v1/finance/receipt",
                          json={"party_id": cust["id"], "amount": 2400, "occurred_at": "2026-10-15",
                                "order_id": so2.json()["id"]}, headers=h)
        check("收款 2400", rec.status_code == 201, rec.text[:140])
        cc2 = recon(h, "customer", cust["id"])
        check("回款后应收回落到 5000", float(cc2["summary"]["closing_balance"]) == 5000,
              f"期末={cc2['summary']['closing_balance']}")

        # ---------------------------------------------------------------
        section("⑦ 财务闭环")
        ledger = client.get("/api/v1/finance", headers=h).json()
        ledger = ledger.get("items", ledger) if isinstance(ledger, dict) else ledger
        check("单据自动写了财务流水（人工一条没录）", len(ledger) >= 4, f"{len(ledger)} 条")
        types = [row.get("related_type") for row in ledger]
        for want, label in [("purchase_in", "采购入库→应付"), ("sales_out", "销售出库→应收"),
                            ("payment", "付款"), ("receipt", "收款")]:
            check(f"流水里有 {label}", want in types)
        ps = client.get("/api/v1/finance/period-summary", headers=h)
        check("期间汇总可用", ps.status_code == 200, ps.text[:100])

        # ---------------------------------------------------------------
        section("⑧ 项目模块：成本归集（用户要求「顺便加上」）")
        upd = client.patch(f"/api/v1/projects/{pid}", json={"progress": 60}, headers=h)
        check("改进度（PATCH /projects/{id}）", upd.status_code == 200, upd.text[:140])
        check("状态非法取值被挡", client.patch(
            f"/api/v1/projects/{pid}", json={"status": "乱写的状态"}, headers=h).status_code == 400)

        # 再挂一笔项目费用，检验"成本 + 费用"两侧都能归集
        exp = client.post(
            "/api/v1/finance",
            json={"transaction_type": "expense", "amount": 888, "category": "差旅费",
                  "occurred_at": "2026-10-16", "note": "项目差旅", "project_id": pid},
            headers=h,
        )
        check("日常支出可挂到项目（project_id）", exp.status_code == 201, exp.text[:160])

        cost = client.get(f"/api/v1/projects/{pid}/cost", headers=h)
        check("查项目成本归集（GET /projects/{id}/cost）", cost.status_code == 200, cost.text[:140])
        if cost.status_code == 200:
            sm = cost.json()["summary"]
            # 销售出库写了应收 2400（带 project_id）→ 应当归到项目收入
            check("单据产生的应收被归集为项目收入 2400", float(sm["income"]) == 2400, f"income={sm['income']}")
            check("项目费用归集 888", float(sm["expense"]) == 888, f"expense={sm['expense']}")
            check("毛利 = 2400 − 0 − 888 = 1512", float(sm["gross_profit"]) == 1512, f"毛利={sm['gross_profit']}")
            check("归集口径有明细（by_source）", len(cost.json()["by_source"]) >= 2,
                  str(cost.json()["by_source"])[:120])

        # 有单据/流水挂靠时不允许删项目
        blocked = client.delete(f"/api/v1/projects/{pid}", headers=h)
        check("挂着单据的项目不能删（409）", blocked.status_code == 409, blocked.text[:120])

    finally:
        drop_temp_company(cid)
        print("\n（临时账套已删除，真实数据未被触碰）")

    # ---------------------------------------------------------------
    section("核查结果")
    bad = [(label, detail) for label, ok, detail in RESULTS if not ok]
    for label, ok, _d in RESULTS:
        print(f"  {'✓' if ok else '✗'} {label}")
    print(f"\n共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(bad)} 项，**断点 {len(bad)} 项**")
    if bad:
        print("\n断点清单：")
        for label, detail in bad:
            print(f"  ✗ {label}   {detail[:120]}")


if __name__ == "__main__":
    main()
