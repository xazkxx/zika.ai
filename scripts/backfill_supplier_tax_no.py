"""按已有发票回填供应商税号（只读预演 / --apply 落库）。

## 为什么需要它

`suppliers.tax_no` 是 2026-10-22 才补的列。库里 63 家供应商**只有 1 家有税号** ——
于是"税号优先"匹配对剩下 62 家等于没生效（还是退回按名称）。

而税号的原料其实**已经在库里**了：进项发票的 `seller_tax_no` 就是供应商的税号，
只是以前没地方存。这个脚本按"发票上的销售方税号 → 供应商档案"回填一次。

## 安全边界（三条）

1. **只回填空值**：已经有税号的供应商一律不动（包括人工填过的）。
2. **只认唯一**：同一个税号必须只对应一个供应商候选。
   名称归一化后相等（去空格/括号/大小写）才认；同名多家直接跳过，
   因为"挑一个填税号"比"填不上"危险得多 —— 税号一错，以后所有进项票都会挂错单。
3. **默认只读**：不加 `--apply` 只打印"会改哪几家"，不动库。

跑法：
    python scripts/backfill_supplier_tax_no.py              # 预演
    python scripts/backfill_supplier_tax_no.py --apply      # 落库
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.invoice import _normalize_name, _normalize_tax_no  # noqa: E402
from app.models.supplier import Supplier  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.invoice import Invoice  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="按进项发票回填供应商税号")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        suppliers = db.query(Supplier).all()
        filled = [s for s in suppliers if (s.tax_no or "").strip()]
        print(f"供应商 {len(suppliers)} 家，已有税号 {len(filled)} 家")

        # 发票侧的原料：进项票的销售方税号，按"归一化名称 → 税号集合"聚合
        invoices = (
            db.query(Invoice)
            .filter(Invoice.direction == "input")
            .filter(Invoice.seller_tax_no.isnot(None))
            .all()
        )
        print(f"参考进项发票 {len(invoices)} 张（带销售方税号）")

        by_name: dict[str, set[str]] = {}
        for inv in invoices:
            key = _normalize_name(inv.seller_name or inv.counterparty_name)
            tax = _normalize_tax_no(inv.seller_tax_no)
            if key and tax:
                by_name.setdefault(key, set()).add(tax)

        # 供应商侧：同名多家 → 标记歧义
        name_count: dict[str, int] = {}
        for row in suppliers:
            key = _normalize_name(row.name)
            name_count[key] = name_count.get(key, 0) + 1

        planned: list[tuple[Supplier, str]] = []
        skipped: list[tuple[str, str]] = []
        for row in suppliers:
            if (row.tax_no or "").strip():
                continue
            key = _normalize_name(row.name)
            if name_count.get(key, 0) > 1:
                skipped.append((row.name, "档案里有同名多家，不猜"))
                continue
            taxes = by_name.get(key) or set()
            if not taxes:
                skipped.append((row.name, "发票里没有完全同名的销售方（可能是简称）"))
                continue
            if len(taxes) > 1:
                skipped.append((row.name, f"发票上有 {len(taxes)} 个不同税号，不猜"))
                continue
            planned.append((row, next(iter(taxes))))

        print(f"\n可回填 {len(planned)} 家：")
        for row, tax in planned:
            print(f"  #{row.id:<6} {row.name}  →  {tax}")
        if skipped:
            print(f"\n跳过 {len(skipped)} 家：")
            for name, why in skipped[:15]:
                print(f"  {name}  —  {why}")
            if len(skipped) > 15:
                print(f"  … 另有 {len(skipped) - 15} 家")

        if not args.apply:
            print("\n（预演模式：没有写库。确认无误后加 --apply）")
            return 0

        for row, tax in planned:
            row.tax_no = tax
        db.commit()
        print(f"\n✅ 已写入 {len(planned)} 家供应商税号")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
