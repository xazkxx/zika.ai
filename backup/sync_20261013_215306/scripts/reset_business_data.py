"""清空全部业务数据，回到「干净起点」。

保留：登录账号（users）、仓库（warehouses）、真实发票（发票号不是 TEST- 开头的）。
清空：商品/客户/供应商档案、所有单据与明细、库存流水、财务流水、生产/BOM、项目。

背景：本库目前的数据全部是开发期反复跑测试产生的，没有任何经营数据。
正式启用前跑一次本脚本，就能得到一个干净的起点。

用法：
    .venv\\Scripts\\python.exe scripts\\reset_business_data.py            # 只看，不删
    .venv\\Scripts\\python.exe scripts\\reset_business_data.py --apply    # 执行清空

⚠️ 执行前会自动在 backup/ 下生成一份全库 JSON 快照，随时可还原。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.session import engine  # noqa: E402

# 按依赖顺序清空：明细 → 单据 → 流水 → 档案
TABLES_IN_ORDER = [
    "sales_order_items",
    "purchase_order_items",
    "sales_orders",
    "purchase_orders",
    "inventory_transactions",
    "financial_transactions",
    "production_boms",
    "production_orders",
    "projects",
    "products",
    "customers",
    "suppliers",
]

# 永不删除：登录账号、仓库。发票只删测试生成的。
KEEP_TABLES = {"users", "warehouses"}
KEEP_CONDITION = {"invoices": "invoice_no NOT LIKE 'TEST-%'"}


def snapshot() -> str:
    """全库 JSON 快照，返回文件路径。"""
    insp = inspect(engine)
    dump: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for t in sorted(insp.get_table_names()):
            dump[t] = [dict(r._mapping) for r in conn.execute(text(f'SELECT * FROM "{t}"'))]

    def default(obj):
        return obj.isoformat() if isinstance(obj, (datetime, date)) else str(obj)

    os.makedirs("backup", exist_ok=True)
    path = f"backup/pre_reset_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, ensure_ascii=False, default=default, indent=1)
    return path


def counts(conn, tables: list[str]) -> dict[str, int]:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    result = {}
    for t in tables:
        if t in existing:
            result[t] = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行清空（默认只预览）")
    parser.add_argument("--no-backup", action="store_true", help="跳过自动备份（不建议）")
    args = parser.parse_args()

    with engine.connect() as conn:
        before = counts(conn, TABLES_IN_ORDER)

    total = sum(before.values())
    print("=" * 62)
    print("待清空的业务数据")
    print("=" * 62)
    for t, n in before.items():
        if n:
            print(f"  {t:<26} {n:>6} 行")
    print(f"  {'合计':<26} {total:>6} 行")
    print()
    print("保留不动：users（登录账号）、warehouses（仓库）、发票号非 TEST- 开头的发票")

    if total == 0:
        print("\n业务数据已经是空的，无需清空。")
        return

    if not args.apply:
        print("\n（预览模式，未做任何修改。加 --apply 执行清空）")
        return

    if not args.no_backup:
        path = snapshot()
        print(f"\n已备份全库快照：{path}（{os.path.getsize(path)} bytes）")

    print("\n执行清空：")
    for t in TABLES_IN_ORDER:
        try:
            with engine.begin() as conn:
                n = conn.execute(text(f'DELETE FROM "{t}"')).rowcount
        except Exception as exc:
            print(f"  {t:<26} 跳过（{type(exc).__name__}: {str(exc).splitlines()[0][:60]}）")
            continue
        if n:
            print(f"  {t:<26} 删除 {n:>6} 行")

    for t, cond in KEEP_CONDITION.items():
        try:
            with engine.begin() as conn:
                n = conn.execute(text(f'DELETE FROM "{t}" WHERE NOT ({cond})')).rowcount
        except Exception:
            continue
        if n:
            print(f"  {t:<26} 删除 {n:>6} 行（保留条件：{cond}）")

    print("\n清空后：")
    with engine.connect() as conn:
        for t in sorted(inspect(engine).get_table_names()):
            print(f"  {t:<26} {conn.execute(text(f'SELECT COUNT(*) FROM \"{t}\"')).scalar():>6} 行")


if __name__ == "__main__":
    main()
