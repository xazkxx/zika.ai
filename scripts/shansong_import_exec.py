# -*- coding: utf-8 -*-
"""陕送票历史数据 —— **导入执行器**（默认 dry-run，加 `--commit` 才写库）。

## 为什么历史单不能建成 draft

`erp_sales.py` 的 `unsubmit_sales_order` 注释里写得很清楚：
> 「不允许挂着流水停在草稿」

而 `create_sales_order` 在创建时就写应收 + 写出库流水。
所以历史数据只有两条路：
  A. 正常建单（写流水、写应收、状态 submitted）—— 账实一致
  B. 建"销售订单"（doc_type=order，不动库存也不产生应收）—— 只记销售意向

本脚本默认走 **A**（用户 2026-10-20 确认："正常建单+标历史来源"），
`--as-order` 可切成 B。

## 幂等

按「备注里的源单号」判断这张单是不是已经导过：
  备注格式：`历史导入|源单号=XS202507060001|来源=xxx.xls`
重复执行只会跳过，不会建第二张。**这是唯一安全的重复保护**——
不用单号前缀猜，因为历史单号和新单号不属于同一套编码。

## 事务策略

**每张单一个事务**（不是整批一个）：
  · 整批一个事务：120 张单里错 1 张就要整批回滚，排查成本极高；
  · 每单一个事务：单张失败只记错误，其余照常入库，最后给你一份失败清单。
但**建档案（客户/供应商）是一个事务**：档案不齐会导致所有单全失败，
所以要么全建成功，要么一个都不建。

跑法
----
    # 预演（不写库，只打印将要做什么）
    ./.venv/Scripts/python.exe scripts/shansong_import_exec.py --dry-run

    # 真正写库
    ./.venv/Scripts/python.exe scripts/shansong_import_exec.py --commit

    # 只导前 3 张单试水
    ./.venv/Scripts/python.exe scripts/shansong_import_exec.py --commit --limit 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from app.core.doc_no import format_doc_no, next_seq, prefix_of  # noqa: E402
from app.core.money import ZERO, line_amount, money  # noqa: E402

import shansong_import_plan as plan_mod  # noqa: E402

NOTE_TAG = "历史导入"
DATA_DIR = ROOT_DIR / "artifacts" / "shansong_import"


# ---------------------------------------------------------------------------
# 档案补齐
# ---------------------------------------------------------------------------
def ensure_customers(db, names: list[str], category_map: dict[str, int]) -> dict[str, int]:
    """把缺的客户建出来，返回 {名称: id}。

    ⚠️ 编码必须走 `doc_no.build_partner_code` 规则（甲CUSxxxx），
       不能自己拼 —— 否则跟现有 33 个客户的编码体系打架。
    """
    from app.core.doc_no import build_partner_code
    from app.models.customer import Customer

    created: dict[str, int] = {}
    existing = [c.code for c in db.query(Customer.code).all()]
    codes = list(existing)

    for name in names:
        code = build_partner_code(codes, "customer")
        codes.append(code)
        cust = Customer(code=code, name=name, category_id=category_map.get(name))
        db.add(cust)
        db.flush()          # 立刻拿 id，后面建单要用
        created[name] = cust.id
    return created


# ---------------------------------------------------------------------------
# 建单
# ---------------------------------------------------------------------------
def _alloc_order_no(db, order_date: str) -> str:
    """按 doc_no 规则取号：XS + 日期 + 3 位流水。

    ⚠️ 不用 `ORDER BY order_no DESC`（字符串序会撞号），统一走 `next_seq`。
    """
    from app.models.sales_order import SalesOrder

    period = (order_date or "").replace("-", "")[:8]
    if len(period) != 8:
        period = datetime.now().strftime("%Y%m%d")
    prefix = prefix_of("sales_outbound")
    existing = [
        r[0]
        for r in db.query(SalesOrder.order_no).filter(SalesOrder.order_no.like(f"{prefix}{period}%")).all()
    ]
    return format_doc_no(prefix, period, next_seq(existing, prefix, period))


def create_one_order(db, group: dict, ids: dict, as_order: bool) -> dict:
    """把一组明细建成一张单。**单张一个事务**，出错由调用方回滚。"""
    from app.models.sales_order import SalesOrder, SalesOrderItem

    order_date = group["date"] or datetime.now().strftime("%Y-%m-%d")
    order_no = _alloc_order_no(db, order_date)
    # 备注由 build_groups 拼好：拆单时形如 `历史导入|源单号=X|工程=Y|来源=f.xls`
    # —— 幂等判据就是这条备注（源单号 + 工程），不能再只看源单号。
    note = group.get("note") or f"{NOTE_TAG}|源单号={group['src_no']}|来源={group['source']}"

    order = SalesOrder(
        order_no=order_no,
        customer_id=group["customer_id"],
        status="draft",
        total_amount=ZERO,
        doc_type="order" if as_order else "outbound",
        warehouse_id=group["warehouse_id"],
        order_date=order_date,
        note=note[:255],
    )
    db.add(order)
    db.flush()

    total = ZERO
    items = []
    for line in group["lines"]:
        amt = line_amount(line["price"], line["qty"])
        items.append(
            SalesOrderItem(
                sales_order_id=order.id,
                product_id=line["product_id"],
                quantity=int(line["qty"]),
                unit_price=Decimal(str(line["price"])),
                amount=amt,
                product_name=line["product_raw"],
                unit=line["unit"] or None,
                unit_factor=1,
            )
        )
        total += amt
    db.add_all(items)

    order.total_amount = money(total)
    order.receivable_amount = money(total)
    order.discount_amount = ZERO
    order.received_amount = ZERO
    order.current_debt = money(total)

    if not as_order:
        # 出库单：正常业务会写的库存与应收，这里必须一起写，
        # 否则就是"挂着 submitted、账上一分钱没有"的半截数据。
        #
        # ⚠️ 这两步必须**成对**出现。第一版只写了库存没写应收，
        #    结果是单据状态 submitted、库存已扣、但应收账款是空的 ——
        #    对账时"这单卖了多少"和"客户欠多少"完全对不上。
        from app.api.v1.routes.erp_common import _apply_stock, _write_finance

        for row in items:
            _apply_stock(
                db,
                product_id=row.product_id,
                warehouse_id=order.warehouse_id,
                quantity=row.quantity,
                transaction_type="outbound",
                unit_price=row.unit_price,
                related_type="sales_out",
                related_order_id=order.id,
                doc_no=order_no,
                unit_factor=1,
                note=f"历史导入出库 {order_no}",
            )
        if money(total) > ZERO:
            _write_finance(
                db,
                transaction_type="receivable",
                direction="in",
                amount=money(total),
                related_type="sales_out",
                related_order_id=order.id,
                doc_no=order_no,
                customer_id=order.customer_id,
                warehouse_id=order.warehouse_id,
                occurred_at=order_date,
                note=f"历史导入应收 {order_no}",
            )
        order.status = "submitted"
    else:
        order.receivable_amount = ZERO
        order.current_debt = ZERO

    db.flush()
    return {"order_no": order_no, "lines": len(items), "total": str(money(total))}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_groups(result: dict, split_by_party: bool = False) -> list[dict]:
    """把预检结果组装成「一张单 = 一组明细」。

    `split_by_party=True`：**同一张源单跨多个工程时，按工程拆成多张系统单**。

    为什么要拆（2026-10-21）：剩余 18 张历史单每张都横跨 2~3 个工程（工程=客户）。
    `SalesOrder` 只有**一个** `customer_id`，整张导进去等于把所有行的应收都挂到
    `lines[0]` 的工程头上 —— 另外两个工程一分钱应收都没有，对账必错。
    拆开之后每张单一个客户，金额总和不变（只是分配对象正确）。
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for rec in result["records"]:
        if rec["status"] != "ok":
            continue
        buckets[rec["doc_no"] or f"NO-{rec['date']}-{rec['party']}"].append(rec)

    if split_by_party:
        split: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for src_no, lines in buckets.items():
            for line in lines:
                split[(src_no, line["party"])].append(line)
        buckets = split  # type: ignore[assignment]

    groups = []
    for key, lines in buckets.items():
        first = lines[0]
        src_no, party = key if isinstance(key, tuple) else (key, first["party"])
        source = Path(str(first["source"])).name
        note = (
            f"{NOTE_TAG}|源单号={src_no}|工程={party}|来源={source}"
            if split_by_party
            else f"{NOTE_TAG}|源单号={src_no}|来源={source}"
        )
        groups.append(
            {
                "src_no": src_no,
                "party": party,
                "key": f"{src_no}#{party}" if split_by_party else src_no,
                "note": note[:255],
                "date": first["date"],
                "customer": first["party"],
                "customer_id": int(first["customer_id"]),
                "warehouse": first["warehouse"],
                "warehouse_id": int(first["warehouse_id"]),
                "source": source,
                "lines": lines,
                "total": str(money(sum((money(l["amount"]) for l in lines), ZERO))),
            }
        )
    groups.sort(key=lambda g: (g["date"] or "", g["src_no"], g.get("party") or ""))
    return groups


def already_imported_map(db) -> dict[str, str]:
    """已导入的判重键 → 新单号。

    拆单批次写入的备注带 `工程=`，判重键是 `源单号#工程`；
    早期批次（未拆）写的是 `源单号=...|来源=...`，判重键就是源单号本身。
    两种都在同一个 map 里 —— 这样"上一批导过、这一批拆开再导"不会互相误判。
    """
    from app.models.sales_order import SalesOrder

    out: dict[str, str] = {}
    rows = db.query(SalesOrder.order_no, SalesOrder.note).filter(
        SalesOrder.note.like(f"{NOTE_TAG}%")
    ).all()
    for order_no, note in rows:
        src = party = None
        for part in str(note or "").split("|"):
            if part.startswith("源单号="):
                src = part.split("=", 1)[1]
            elif part.startswith("工程="):
                party = part.split("=", 1)[1]
        if src and party:
            out[f"{src}#{party}"] = order_no
        elif src:
            out[src] = order_no
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="陕送票历史数据导入执行器")
    ap.add_argument("--dry-run", action="store_true", help="只预演，不写库（默认）")
    ap.add_argument("--commit", action="store_true", help="真正写库")
    ap.add_argument("--as-order", action="store_true",
                    help="建成销售订单（不动库存、不产生应收），默认建出库单")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 张单（试水）")
    ap.add_argument("--split-cross", action="store_true",
                    help="同一张源单跨多个工程时，按工程拆成多张单（应收才不会挂错客户）")
    ap.add_argument("--exclude-risky", action="store_true",
                    help="保守导入：跳过含争议的单（重复账 dup_groups / 跨工程 cross_orders）")
    args = ap.parse_args()

    commit = args.commit and not args.dry_run

    result = plan_mod.plan()
    groups = build_groups(result, split_by_party=args.split_cross)
    if args.exclude_risky:
        risks = result.get("risks") or {}
        risky_docs = {g.get("源单号") for g in (risks.get("dup_groups") or [])}
        risky_docs |= {o.get("源单号") for o in (risks.get("cross_orders") or [])}
        risky_docs.discard(None)
        before = len(groups)
        groups = [g for g in groups if g["src_no"] not in risky_docs]
        print(f"【保守模式】重复账 {len(risks.get('dup_groups') or [])} 组 / 跨工程单 "
              f"{len(risks.get('cross_orders') or [])} 张 → 跳过 {before - len(groups)} 张单，"
              f"本次只导无争议的 {len(groups)} 张")

    from app.db.session import SessionLocal
    from app.models.product import Product
    from app.models.sales_order import SalesOrder
    from app.models.warehouse import Warehouse

    db = SessionLocal()
    try:
        done = already_imported_map(db)

        def _is_done(g: dict) -> bool:
            # 拆单模式下的键是 `源单号#工程`；但如果**上一批**是把整张单导进去的
            # （备注里没有 `工程=`），那这张源单就已经入过账了，不能再按工程拆一遍
            # —— 否则同一张单会被导两遍，金额直接翻倍。两种键都要认。
            if g.get("key", g["src_no"]) in done:
                return True
            return g["src_no"] in done

        todo = [g for g in groups if not _is_done(g)]
        skipped = [g for g in groups if _is_done(g)]

        print("=" * 68)
        print(f"{'【正式写库】' if commit else '【预演 · 不写库】'}"
              f"  单据类型={'销售订单(不动库存)' if args.as_order else '销售出库单'}")
        print("=" * 68)
        print(f"可建单 {len(groups)} 张 / 已导过 {len(skipped)} 张 / 本次处理 {len(todo)} 张")
        print()

        if not todo:
            print("没有需要新导的单据。")
            return 0

        # 档案核对：全部就绪才继续（建档案是整批一个事务的概念）
        need_customers = sorted({g["customer"] for g in todo if not g["customer_id"]})
        missing = [g for g in todo if not g["warehouse_id"]]
        if missing:
            print(f"❌ 有 {len(missing)} 张单的仓库无法识别，整批中止")
            for g in missing[:5]:
                print(f"    {g['src_no']} 仓库「{g['warehouse']}」")
            return 1

        print(f"待建客户 {len(need_customers)} 个：")
        for n in need_customers:
            print(f"    + {n}")
        print()

        if args.limit:
            todo = todo[: args.limit]
            print(f"（--limit {args.limit}：只处理前 {len(todo)} 张）\n")

        # ── 预演：逐张打印，不写 ──
        if not commit:
            grand = ZERO
            for g in todo:
                grand += money(g["total"])
                flag = "建客户" if not g["customer_id"] else "    "
                print(f"  {g['date']}  {g['src_no']:<18} {g['customer'][:26]:<28}"
                      f" {len(g['lines']):>2}行  ¥{g['total']:>12}  {flag}")
            print()
            print(f"合计 {len(todo)} 张单 / ¥{money(grand)}")
            print()
            print("⚠️ 这是预演。要真正写库请加 --commit")
            return 0

        # ── 正式写库 ──
        cat_map: dict[str, int] = {}
        if need_customers:
            created = ensure_customers(db, need_customers, cat_map)
            db.commit()
            print(f"✅ 新建客户 {len(created)} 个")
            for name, cid in created.items():
                print(f"    id={cid}  {name}")
            print()

        ok, fail = 0, []
        grand = ZERO
        for idx, g in enumerate(todo, 1):
            # 判重用**完整备注**（拆单时含工程名），否则同一源单的第二、三个工程会被当成"已存在"
            cust = db.query(SalesOrder).filter(SalesOrder.note == g["note"]).first()
            if cust is not None:
                print(f"  [{idx}/{len(todo)}] {g['src_no']} 已存在，跳过")
                continue
            try:
                out = create_one_order(db, g, {}, args.as_order)
                db.commit()
                ok += 1
                grand += money(out["total"])
                print(f"  [{idx}/{len(todo)}] ✅ {out['order_no']}  ←  {g['src_no']}"
                      f"  {out['lines']}行  ¥{out['total']}")
            except Exception as exc:
                db.rollback()
                fail.append({"src_no": g["src_no"], "error": f"{type(exc).__name__}: {exc}"})
                print(f"  [{idx}/{len(todo)}] ❌ {g['src_no']}  {exc}")

        print()
        print("=" * 68)
        print(f"成功 {ok} 张 / 失败 {len(fail)} 张 / 金额 ¥{money(grand)}")
        if fail:
            print("\n失败清单：")
            for f in fail:
                print(f"  {f['src_no']}  {f['error']}")
            (DATA_DIR / "失败清单.json").write_text(
                json.dumps(fail, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return 0 if not fail else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
