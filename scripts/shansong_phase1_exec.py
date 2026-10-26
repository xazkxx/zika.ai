# -*- coding: utf-8 -*-
"""陕送票历史数据 —— 第一批执行（2026-10-20 用户批准）。

## 本批范围（用户原话决策）

1. **45 组跨工程重复行暂停**（涉及 91 行 / ¥151,771.14，用户拿去对原始单据）。
   ⚠️ 45 是**组数**不是行数：每组 2~3 行，整组暂停，所以真正无争议的是
   106 行 / ¥309,054.81，不是用户口算的 152（197-45 每组只扣了 1 行）。
2. **本批只导 2025-04 ~ 06**：17 行 / ¥81,516.87，全部无争议、无待建客户。
   其中 2 张已导过（用户的测试单），自动跳过，**实际新建 5 张**。
3. **客户档案**：
   · 「西延高铁西安段330千伏包1」→ 映射到已有客户 甲47000017（同一工程，用户确认）
   · 其余 8 个新建，挂分类树；拿不准的挂「施工一部」节点，以后可在界面挪
4. **供应商**「西安市碑林区良田电子产品经营部」新建（发票侧缺失，1 张票 ¥4,620）。

## 跑法

    # 预检（不写库）
    ./.venv/Scripts/python.exe scripts/shansong_phase1_exec.py

    # 建档案 + 真导
    ./.venv/Scripts/python.exe scripts/shansong_phase1_exec.py --commit
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from app.core.money import money  # noqa: E402
from shansong_import_plan import norm, plan  # noqa: E402

MONTHS = ("2025-04", "2025-05", "2025-06")

# 8 个新建客户的分类归属（category_id，见 customer_categories）：
#   323=施工一部  325=谭涛总  326=周广平总  328=谭涛总→王宪全经理
# 规律：与已挂 328 的「蒲白750包1 / 三通道包12」同包系 → 328；
#       拿不准的 → 323 施工一部（不猜谭/周，用户以后界面里挪）。
NEW_CUSTOMERS: list[tuple[str, int]] = [
    ("蒲白330", 323),
    ("蒲白330千伏输变电工程(线路工程包1)", 323),
    ("蒲白330千伏输变电工程(线路工程包2)", 323),
    ("蒲白330千伏输变电工程(线路工程包4)", 323),
    ("蒲白330千伏输变电工程(线路工程包5)", 323),
    ("蒲白750千伏输变电工程(线路工程包2)", 328),   # 跟包1(711→328) 同包系
    ("西延高铁", 323),
    ("陕北至关中第三通道750千伏输变电工程(包13)", 328),  # 跟包12(713→328) 同包系
]

NEW_SUPPLIER = {
    "name": "西安市碑林区良田电子产品经营部",
    "tax_no": "92610103MA6UECEDX5",
    "note": "历史导入：发票侧缺失，2026-10-20 用户批准新建（1 张票 ¥4,620）",
}


def collect_lines() -> tuple[list[dict], list[dict]]:
    """取本批要导的行：4~6月 ∩ 无跨工程重复 ∩ 状态 ok。返回 (行, 被暂停的行)。"""
    d = plan()
    dup_keys = {
        (g["源单号"], norm(g["商品"]), str(g["数量"]), str(g["单价"]))
        for g in d["risks"]["dup_groups"] if g["类型"] == "跨工程重复"
    }
    batch, paused = [], []
    for rec in d["records"]:
        is_dup = (rec["doc_no"], norm(rec["product_raw"]), str(rec["qty"]), str(rec["price"])) in dup_keys
        if is_dup:
            paused.append(rec)
            continue
        if (rec["date"] or "")[:7] in MONTHS and rec["status"] == "ok":
            batch.append(rec)
    return batch, paused


def to_engine_lines(batch: list[dict]) -> list[dict]:
    """plan 的 records → 导入引擎的 line 格式。"""
    out = []
    for i, rec in enumerate(batch, 1):
        out.append({
            "__row__": i,
            "order_date": rec["date"],
            "warehouse": rec["warehouse"],
            "external_no": rec["doc_no"],
            "customer": rec["party"],
            "product": rec["product_raw"],
            "spec": "",
            "model": "",
            "unit": rec["unit"],
            "quantity": Decimal(str(rec["qty"])),
            "unit_price": Decimal(str(rec["price"])),
            "amount": Decimal(str(rec["amount"])),
            "doc_note": "",
            "line_note": "",
        })
    return out


def ensure_archives() -> None:
    """建 8 个客户 + 1 个供应商。**先查再建**，重复执行安全。"""
    from app.core.doc_no import build_partner_code
    from app.models.customer import Customer
    from app.models.supplier import Supplier
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        existing = {norm(c.name): c for c in db.query(Customer).all()}
        codes = [c.code for c in db.query(Customer.code).all()]
        created = 0
        for name, cat_id in NEW_CUSTOMERS:
            if norm(name) in existing:
                print(f"  客户已存在，跳过：{name}")
                continue
            code = build_partner_code(codes, "customer")
            codes.append(code)
            db.add(Customer(code=code, name=name, category_id=cat_id))
            created += 1
            print(f"  + 客户 {code} {name}（挂分类 {cat_id}）")
        if created:
            db.commit()
            print(f"✅ 新建客户 {created} 个")
        else:
            print("（客户无新增）")

        sup = db.query(Supplier).filter(Supplier.name == NEW_SUPPLIER["name"]).first()
        if sup is None:
            scodes = [s.code for s in db.query(Supplier.code).all()]
            code = build_partner_code(scodes, "supplier")
            db.add(Supplier(code=code, name=NEW_SUPPLIER["name"],
                            tax_no=NEW_SUPPLIER["tax_no"], note=NEW_SUPPLIER["note"]))
            db.commit()
            print(f"✅ 新建供应商 {code} {NEW_SUPPLIER['name']}")
        else:
            print(f"（供应商已存在：{sup.code}）")
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="陕送票第一批执行（2025-04~06）")
    ap.add_argument("--commit", action="store_true", help="建档案并真导（默认只预检）")
    ap.add_argument("--skip-archives", action="store_true", help="跳过建档案")
    args = ap.parse_args()

    batch, paused = collect_lines()
    total = sum((Decimal(x["amount"] or 0) for x in batch), Decimal("0"))
    print("=" * 68)
    print(f"第一批范围：{MONTHS} ｜ 无争议行 {len(batch)} 行 ｜ 金额 ¥{money(total)}")
    print(f"（全库跨工程重复暂停 {len(paused)} 行，等财务核实原始单据）")
    print("=" * 68)

    from app.db.session import SessionLocal
    from app.services.sales_history_import import import_sales_history

    lines = to_engine_lines(batch)
    db = SessionLocal()
    try:
        # ⚠️ 预检展示**永远 dry_run**。第一版这里写成 `dry_run=not args.commit`，
        #    结果 --commit 时"预检展示"那次调用就真导了，后面建档案后的第二次调用
        #    全部 skipped —— 单是导进去了，但流程日志完全是误导。
        res = import_sales_history(db, lines, dry_run=True,
                                   source_file="rows.jsonl(4-6月无争议批)")
        ins = res["inspected"]
        print(f"\n预检：行 {ins['line_total']} / ok {ins['ok_lines']} / 错 {ins['error_lines']}")
        print(f"      将建 {ins['new_groups']} 张（已导过跳过 {res['skipped']}，"
              f"被挡 {ins['blocked_groups']}）")
        print(f"      本次导入金额 ¥{res['imported_amount']}")
        if ins["miss_customers"] or ins["miss_warehouses"] or ins["miss_products"]:
            print("      ⚠️ 缺档案：", ins["miss_customers"], ins["miss_warehouses"], ins["miss_products"])
        print()
        print("本批单据：")
        for g in res["groups"]:
            state = "已导→" + g["imported_as"] if g["imported_as"] else (
                "被挡" if g["incomplete"] else "将建")
            print(f"  {g['external_no']:<18} {g['order_date']}  {g['customer'][:34]:<36}"
                  f" {len(g['lines']):>2}行  ¥{g['total']:>11}  [{state}]")

        if not args.commit:
            print("\n⚠️ 预检模式，未写库。加 --commit 执行。")
            return 0

        # 档案必须在真导**之前**就绪（本批 4~6 月虽然无待建客户，但别名映射的
        # 甲47000017 必须在库里——它在；后续批次才依赖新建的 8 个客户）
        if not args.skip_archives:
            print("\n—— 建档案 ——")
            ensure_archives()
        # 档案就绪后**只真导一次**（幂等：已导过的自动跳过）
        res = import_sales_history(db, lines, dry_run=False,
                                   source_file="rows.jsonl(4-6月无争议批)")

        print("\n—— 导入结果 ——")
        print(f"新建 {res['created']} 张 / 跳过 {res['skipped']} 张 / 失败 {len(res['failed'])}")
        print(f"导入金额 ¥{res['imported_amount']}")
        for o in res["created_orders"]:
            print(f"  ✅ {o['order_no']}  ← {o['外部单号']}  {o['lines']}行  ¥{o['total']}")
        for f in res["failed"]:
            print(f"  ❌ {f['外部单号']}  {f['原因']}")
        return 0 if not res["failed"] else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
