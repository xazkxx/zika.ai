"""给历史资金流水补「流水号」（`FL<yyyymmdd><3位>`），幂等。

## 为什么要补

`financial_transactions.flow_no` 这一列库里一直有，但**模型里没映射、写入时也没赋值** ——
133 条流水里只有 7 条（更早的版本写的）有号。对账单新加的「收款流水号」列如果空着，
这一列就白加了：客户拿银行回单来对账，系统里找不到对照物。

## 口径

- 格式与 `_write_finance` 自动生成的一致：`FL` + 当天日期 + 3 位序号（如 `FL20261022001`）；
- 按 `occurred_at, id` 顺序补，**同一天接在已有最大序号后面**，不会与旧号冲突；
- 只处理 `flow_no IS NULL` 的行 —— 已有的一律不动（包括人工改过的）；
- 默认只预演，`--apply` 才写库。

跑法：
    python scripts/backfill_flow_no.py
    python scripts/backfill_flow_no.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.v1.routes.erp_common import _next_flow_no  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.finance import FinancialTransaction  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="给历史资金流水补流水号")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        total = db.query(FinancialTransaction).count()
        missing = (
            db.query(FinancialTransaction)
            .filter(FinancialTransaction.flow_no.is_(None))
            .order_by(FinancialTransaction.occurred_at, FinancialTransaction.id)
            .all()
        )
        have = total - len(missing)
        print(f"资金流水 {total} 条：已有流水号 {have} 条，待补 {len(missing)} 条")
        if not missing:
            print("无需处理。")
            return 0

        # 预演也要算出真实号，才能把"会补成什么"给用户看；不 commit 即不落库
        planned: list[tuple[int, str, str | None]] = []
        for row in missing:
            day = (row.occurred_at or (str(row.created_at)[:10] if row.created_at else ""))[:10]
            no = _next_flow_no(db, day)
            planned.append((row.id, no, day))
            row.flow_no = no
            db.flush()  # 让下一条能看到这一条，序号才能连上

        for row_id, no, day in planned[:10]:
            print(f"  #{row_id:<7} {day}  →  {no}")
        if len(planned) > 10:
            print(f"  … 另有 {len(planned) - 10} 条")

        if not args.apply:
            db.rollback()
            print(f"\n（预演模式：会给 {len(planned)} 条补号，未写库。确认后加 --apply）")
            return 0

        db.commit()
        print(f"\n✅ 已补 {len(planned)} 条流水号")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
