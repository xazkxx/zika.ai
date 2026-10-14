"""收尾两件事 + 补一个根因。

## 一、报价单 `BJ202504140002` 的归属

它没有仓库，无从判断。依据三条旁证定为**西安寨卡**（仓库 `CK-001 寨卡仓库`）：
- 与 `BJ202504150003` **同一个客户**（#706 西安明珠电力安装工程有限公司）；
- 报价单号**连号**（0002 / 0003）；
- 日期**相邻**（2025-04-14 / 04-15），而 0003 的仓库正是 204。

三条独立线索指向同一结论，够定；定完把仓库补上，以后就有据可依了。

## 二、孤儿财务流水

`#1055`（¥4,910.89）指向**已被删除**的发票 `25612000000093948510`
（就是那张无原件、税号与名称矛盾的异常票，按用户指示删掉的）。
发票没了，这条支出就是凭空多出来的 —— **删掉**。

## 三、回填历史流水的关联字段（根因的另一半）

`sync_invoices_to_finance` 以前只把票号写进 `note` 文本，`related_type` / `doc_no`
全是空的。后果有两个：删发票时**找不到**这条流水（孤儿就是这么来的），
而且没有 `occurred_at` 的流水在「日常收支」按日期筛选时会被整个漏掉。

代码已经改了（新同步的会带上关联与日期）。这里把**存量**也补齐，
否则"删发票时按 doc_no 清理"对老数据不生效，孤儿还会再出现。

    python scripts/fix_invoice_finance_links.py --dry-run
    python scripts/fix_invoice_finance_links.py
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import text  # noqa: E402

from app.core import tenant  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.finance import FinancialTransaction  # noqa: E402
from app.models.quotation import Quotation  # noqa: E402
from app.models.warehouse import Warehouse  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"

# 报价单号 → 补哪个仓库（依据见模块 docstring）
QUOTE_WAREHOUSE = {"BJ202504140002": 204}

# 票号写在 note 里的固定前缀，形如「发票 26612000001006203301 | 陕西送变电…」
_NOTE_INVOICE_RE = re.compile(r"^发票\s+(\S+)")


def _snapshot(specs: list[tuple[str, object]]) -> Path | None:
    rows: list[dict] = []
    for schema, model in specs:
        session = tenant.session_factory_for(schema)()
        try:
            for obj in session.query(model).all():
                data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
                rows.append({"__schema": schema, "__table": model.__tablename__, **data})
        finally:
            session.close()
    if not rows:
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    path = BACKUP_DIR / f"before_finance_link_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="报价单归属 + 清理孤儿流水 + 回填发票流水关联")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    meta = tenant.session_factory_for("public")()
    schemas = [c.schema_name for c in meta.query(Company).order_by(Company.sort_order).all()]
    meta.close()

    if not dry:
        path = _snapshot([(s, FinancialTransaction) for s in schemas] + [(s, Quotation) for s in schemas])
        print(f"已备份到：{path}\n")

    for schema in schemas:
        session = tenant.session_factory_for(schema)()
        try:
            print(f"\n===== {schema} =====")

            # —— 1. 报价单补仓库 ——
            for quote_no, warehouse_id in QUOTE_WAREHOUSE.items():
                quote = session.query(Quotation).filter(Quotation.quote_no == quote_no).first()
                if quote is None:
                    continue
                wh = session.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
                wh_label = f"{wh.code} {wh.name}" if wh else f"id={warehouse_id}"
                print(f"  报价单 {quote_no}：仓库 {quote.warehouse_id} → {wh_label}（同客户连号旁证）")
                if not dry:
                    quote.warehouse_id = warehouse_id

            # —— 2/3. 发票流水的关联与日期 ——
            invoices = {str(no): issue for no, issue in session.execute(
                text("SELECT invoice_no, issue_date FROM invoices")
            ).fetchall()}
            rows = (
                session.query(FinancialTransaction)
                .filter(FinancialTransaction.note.ilike("发票 %"))
                .order_by(FinancialTransaction.id)
                .all()
            )
            orphan = []
            filled = 0
            for row in rows:
                match = _NOTE_INVOICE_RE.match(str(row.note or ""))
                invoice_no = match.group(1) if match else ""
                if invoice_no not in invoices:
                    orphan.append(row)
                    print(f"  ! 流水 #{row.id} ¥{row.amount} 指向不存在的发票 {invoice_no or '(解析不出票号)'} → 孤儿")
                    continue
                issue_date = invoices[invoice_no] or None
                needs = (
                    row.related_type != "invoice"
                    or row.doc_no != invoice_no
                    or (issue_date and row.occurred_at != issue_date)
                )
                if not needs:
                    continue
                filled += 1
                if dry:
                    print(f"  → 流水 #{row.id} 回填关联：related_type=invoice  doc_no={invoice_no}  occurred_at={issue_date}")
                else:
                    row.related_type = "invoice"
                    row.doc_no = invoice_no
                    row.direction = row.direction or "out"
                    if issue_date:
                        row.occurred_at = issue_date
                        row.period = str(issue_date)[:7]
            print(f"  发票流水：需回填 {filled} 条，孤儿 {len(orphan)} 条")

            # —— 2. 删孤儿 ——
            for row in orphan:
                print(f"  {'→ 将删除' if dry else '删除'}孤儿流水 #{row.id} ¥{row.amount}（{str(row.note)[:44]}）")
                if not dry:
                    session.delete(row)

            if not dry:
                session.commit()
        finally:
            session.close()

    print("\n" + ("（试运行，未改动任何数据）" if dry else "完成。"))


if __name__ == "__main__":
    main()
