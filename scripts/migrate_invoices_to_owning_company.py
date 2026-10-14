"""把发票按**卖方**归到它所属公司的账套。

## 为什么需要这一步

多账套之前，所有发票都在 `public`（＝第一个账套）里。但用户实际有**三家公司**
（西安寨卡信息技术有限公司 / 西安华诺迈贸易有限公司 / 陕西寨纬智能科技有限公司），
12 张票里有 4 张是华诺迈开的、4 张是寨纬开的。它们现在挂在寨卡的账上，
**是错的账**：一家公司只能把自己开的票记成销项，别人的票挂在自己账上，
税负统计、进销项报表全都不对。

## 判定规则（只有一条，不猜）

按发票的**销售方税号**匹配账套的**本公司税号**：
- 销售方税号 == 某账套的本公司税号 → 这张票是那家公司开的（销项），归到那个账套；
- 匹配不上任何账套 → **留在原地不动**，并打印出来让人工处理。

绝不用"名称像不像"来兜底 —— 名称会被 OCR 认错、会有简称全称之别，
而税号是唯一的。匹配不上就是匹配不上，宁可留给人看。

## 安全措施

- 跑之前把 12 张票全量导出成 JSON 快照（`backup/invoices_before_split_*.json`）；
- 用 `--dry-run` 先看一遍会怎么分，确认无误再真跑；
- 保留原 id（跨 schema 移动时把目标 schema 的序列推到 max(id) 之后），
  这样"哪张票去哪了"可以对着看；
- 只动 `invoices` 表，不碰原件文件（原件路径是**相对** storage_root 的，
  换 schema 后依然指向同一个文件，不需要搬）。

    python scripts/migrate_invoices_to_owning_company.py --dry-run
    python scripts/migrate_invoices_to_owning_company.py
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.core import tenant  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.invoice import DIRECTION_LABELS, Invoice, detect_direction  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"


def _normalize_tax(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isalnum()).upper()


def _row_dict(inv: Invoice) -> dict:
    return {c.name: getattr(inv, c.name) for c in Invoice.__table__.columns}


def _snapshot_all(schemas: list[str]) -> Path | None:
    """动手之前，把每个账套的发票全量导出成 JSON。

    这是这次迁移唯一的"后悔药"：跨 schema 移动没有事务可回滚，
    真挪错了只能照着快照一条条对回来。
    """
    rows: list[dict] = []
    for schema in schemas:
        session = tenant.session_factory_for(schema)()
        try:
            for inv in session.query(Invoice).order_by(Invoice.id).all():
                rows.append({"__schema": schema, **_row_dict(inv)})
        finally:
            session.close()
    if not rows:
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    path = BACKUP_DIR / f"invoices_before_split_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="把发票按卖方归到所属公司的账套")
    parser.add_argument("--dry-run", action="store_true", help="只看会怎么分，不动数据")
    args = parser.parse_args()

    # —— 账套清单 ——
    meta = SessionLocal()
    try:
        companies = meta.query(Company).filter(Company.is_active.is_(True)).order_by(Company.sort_order).all()
        # 用税号做索引。税号为空/重复的账套要显式报出来 ——
        # 静默跳过会让"某些票归不进去"变成没人知道的事。
        by_tax: dict[str, Company] = {}
        conflicted: set[str] = set()
        for company in companies:
            tax = _normalize_tax(company.tax_no)
            if not tax:
                print(f"! 账套「{company.name}」没填本公司税号，跳过（先去「公司信息」补上）")
                continue
            if tax in conflicted:
                continue
            if tax in by_tax:
                print(f"! 税号 {tax} 同时属于「{by_tax[tax].name}」与「{company.name}」，无法判定，两个都跳过")
                conflicted.add(tax)
                continue
            by_tax[tax] = company
        for tax in conflicted:
            by_tax.pop(tax, None)
        info = {c.id: (c.schema_name, c.name, c.tax_no) for c in companies}
    finally:
        meta.close()

    print(f"参与匹配的账套 {len(by_tax)} 个：")
    for tax, company in by_tax.items():
        print(f"  {company.name}（{tax}）→ schema {company.schema_name}")
    print()

    if not args.dry_run:
        path = _snapshot_all([schema for schema, _n, _t in info.values()])
        print(f"已备份全部发票到：{path}\n" if path else "没有发票需要备份\n")

    # —— 逐账套扫发票 ——
    moved = 0
    stayed = 0
    unresolved: list[tuple[str, str]] = []
    for schema, name, _tax in info.values():
        session = tenant.session_factory_for(schema)()
        try:
            rows = session.query(Invoice).order_by(Invoice.id).all()
            if not rows:
                continue
            print(f"【{name}】(schema={schema}) 现有 {len(rows)} 张")
            for inv in rows:
                seller_tax = _normalize_tax(inv.seller_tax_no)
                target = by_tax.get(seller_tax)
                if target is None:
                    unresolved.append((inv.invoice_no, inv.seller_name or "?"))
                    print(f"  ? {inv.invoice_no} 卖方「{inv.seller_name}」({seller_tax or '无税号'}) 匹配不到账套，留在原地")
                    continue
                if target.schema_name == schema:
                    stayed += 1
                    print(f"  · {inv.invoice_no} 本来就对（{target.name}）")
                    continue

                if args.dry_run:
                    print(f"  → {inv.invoice_no} 应移到「{target.name}」")
                    moved += 1
                    continue
                if not _move_one(session, inv, target.schema_name, seller_tax, target.tax_no):
                    continue
                moved += 1
                print(f"  ✓ {inv.invoice_no} 已移到「{target.name}」")
            if not args.dry_run:
                session.commit()
        finally:
            session.close()

    print()
    print(f"{'（试运行，未改动数据）' if args.dry_run else ''}需移动 {moved} 张，原本就对 {stayed} 张，匹配不到 {len(unresolved)} 张")
    for no, seller in unresolved:
        print(f"  ! {no} 卖方「{seller}」—— 请人工确认它属于哪个账套")


def _move_one(
    src_session,
    inv: Invoice,
    target_schema: str,
    seller_tax: str,
    own_tax: str,
) -> bool:
    """把一行发票从当前 schema 挪到目标 schema。

    跨 schema 没有事务可用（两个连接、两个事务），所以按
    **先在目标库插好、再删源库**的顺序做：
    - 先插后删：中途失败最多是"两边都有一份"，重复数据看得见、能手工清；
      反过来先删后插，中途失败就是**票没了**。
    - 删除前按 (schema, id) 精确删，不用"删全部"这类写法。
    """
    data = {c.name: getattr(inv, c.name) for c in Invoice.__table__.columns}
    target = tenant.session_factory_for(target_schema)()
    try:
        if target.query(Invoice).filter(Invoice.invoice_no == inv.invoice_no).first() is not None:
            print(f"  ! {inv.invoice_no} 在目标账套已存在，跳过（不覆盖已有数据）")
            return False
        if target.get(Invoice, data["id"]) is not None:
            data = {**data, "id": None}  # id 被占用了，让目标库重新分配

        # 方向按**目标公司自己的税号**重判：这张票对它是销项
        direction = detect_direction(
            own_tax_no=own_tax,
            own_name=None,
            seller_tax_no=seller_tax,
            seller_name=inv.seller_name,
            buyer_tax_no=inv.buyer_tax_no,
            buyer_name=inv.buyer_name,
        )
        assert direction in DIRECTION_LABELS, direction
        target.add(Invoice(**{**data, "direction": direction}))
        target.commit()

        # 保留原 id 时，把目标 schema 的序列推过去，否则下一条 INSERT 会撞主键
        if data.get("id"):
            target.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('invoices', 'id'), "
                    "GREATEST((SELECT COALESCE(MAX(id), 1) FROM invoices), 1))"
                )
            )
            target.commit()
    finally:
        target.close()

    # 目标库插好了，才删源库这一行
    src_session.delete(inv)
    src_session.flush()
    return True


if __name__ == "__main__":
    main()
