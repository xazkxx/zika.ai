"""把账套 1（西安寨卡）里的历史数据，按归属重新分配到三家公司的账套。

## 归属依据（只有一条总则）

> **一切按仓库归属；发票产生的流水跟着发票走。**

仓库名里直接写着公司名，这是库里唯一可靠的归属线索：

| 仓库 | 所属公司 | 账套 |
|---|---|---|
| `CK-001 寨卡仓库` | 西安寨卡信息技术有限公司 | public |
| `CK-002 寨纬仓库` | 陕西寨纬智能科技有限公司 | co_03 |
| `CK-003 华诺迈仓库` | 西安华诺迈贸易有限公司 | co_02 |
| `WH-001 主仓库` | 系统默认仓，留在寨卡 | public |

于是：

| 数据 | 归属规则 | 结果 |
|---|---|---|
| 库存流水 45 条 | `warehouse_id` | 华诺迈 21 / 寨卡 19 / 寨纬 5 |
| 销售单 + 明细 | `warehouse_id` | 寨纬（2 单 + 4 行） |
| 报价单 6 张 | `warehouse_id` | 寨卡 4 / 华诺迈 1 / 1 张无仓库留在寨卡并标注 |
| 财务流水（发票同步） | **按票号找该发票现在在哪** | 三家各 4 条 |
| 财务流水（销售单） | 跟销售单 | 寨纬 1 条 |
| 财务流水（孤儿） | 指向已删除的发票 | 留寨卡并标注，**不擅自删账** |
| 商品 / 客户 / 供应商 | 用户选择"复制到另外两家" | 三家各一份 |
| 仓库 3 条残留 | 诊断/探针留下的 | **删除** |

**为什么不按"客户属于谁"来分**：三家公司的客户是重叠的（同一批电力工程客户），
客户说明不了归属；仓库才是各家自己的。

## 安全措施

- `--dry-run` 先看会怎么分，确认无误再真跑；
- 跑之前把涉及的**每张表**全量导出 JSON 快照；
- 保留原 id（各账套的序列会被推到 max(id) 之后），
  这样跨表引用（product_id / warehouse_id / sales_order_id）不会断；
- 跨 schema **先插目标、再删源**：中途失败最多两份，不会两边都没有。

    python scripts/reassign_history_to_companies.py --dry-run
    python scripts/reassign_history_to_companies.py
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
from app.core.tenant import PUBLIC_SCHEMA  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.finance import FinancialTransaction  # noqa: E402
from app.models.inventory import InventoryTransaction  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.quotation import Quotation  # noqa: E402
from app.models.sales_order import SalesOrder, SalesOrderItem  # noqa: E402
from app.models.supplier import Supplier  # noqa: E402
from app.models.warehouse import Warehouse  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "backup"

# 账套号 → 三家公司的 schema（寨卡就是 public，历史数据在里面）
CARD_SCHEMA = PUBLIC_SCHEMA
WEIWEI_SCHEMA = "co_03"  # 陕西寨纬智能科技有限公司
HUANUOMAI_SCHEMA = "co_02"  # 西安华诺迈贸易有限公司

# 仓库 code → 目标 schema。寨卡的留在 public，不用列。
WAREHOUSE_HOME = {
    "CK-002": WEIWEI_SCHEMA,  # 寨纬仓库
    "CK-003": HUANUOMAI_SCHEMA,  # 华诺迈仓库
}

# 要清理的残留仓库（诊断脚本 / curl 探针留下的）
JUNK_WAREHOUSE_CODES = ("WH-90316e", "WH-curl0001", "WH-b34cda66")

# 基础资料：复制到另外两家（保留 id，跨表引用才不会断）
MASTER_MODELS = (Product, Customer, Supplier)


def _dump(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _bump_sequence(session, model) -> None:
    """把目标 schema 的自增序列推到 max(id) 之后。

    跨 schema 搬运时保留了原 id，但目标库的序列还停在 1 ——
    不推的话下一条正常 INSERT 会撞主键（Duplicate key）。
    """
    table = model.__tablename__
    session.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {table}), 1))"
        )
    )
    session.commit()


def _insert(session, model, data: dict) -> bool:
    """往目标 schema 插一行（保留 id）。已存在就跳过，不覆盖。"""
    if session.get(model, data["id"]) is not None:
        print(f"    ! {model.__tablename__} id={data['id']} 在目标账套已存在，跳过")
        return False
    session.add(model(**data))
    session.commit()
    _bump_sequence(session, model)
    return True


def _snapshot(label: str, specs: list[tuple[str, object]]) -> Path | None:
    """把 (schema, model, where) 里的行全量导出成 JSON。"""
    rows: list[dict] = []
    for schema, model in specs:
        session = tenant.session_factory_for(schema)()
        try:
            for obj in session.query(model).all():
                rows.append({"__schema": schema, "__table": model.__tablename__, **_dump(obj)})
        finally:
            session.close()
    if not rows:
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    path = BACKUP_DIR / f"history_before_reassign_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def _move(session_from, obj, model, target_schema: str) -> bool:
    """把一行搬到目标 schema：先插目标、再删源。"""
    data = _dump(obj)
    target = tenant.session_factory_for(target_schema)()
    try:
        if not _insert(target, model, data):
            return False
    finally:
        target.close()
    session_from.delete(obj)
    session_from.flush()
    return True


# ===========================================================================
def phase_clean_warehouses(dry: bool) -> None:
    print("\n" + "=" * 70)
    print("阶段 0：清理诊断/探针残留仓库")
    print("=" * 70)
    session = tenant.session_factory_for(PUBLIC_SCHEMA)()
    try:
        rows = session.query(Warehouse).filter(Warehouse.code.in_(JUNK_WAREHOUSE_CODES)).all()
        for row in rows:
            # 有库存流水的不能直接删（那会让流水指向不存在的仓库）
            used = (
                session.query(InventoryTransaction)
                .filter(InventoryTransaction.warehouse_id == row.id)
                .count()
            )
            if used:
                print(f"  ! {row.code} {row.name} 被 {used} 条库存流水引用，不删")
                continue
            print(f"  {'→ 将删除' if dry else '删除'} {row.code} {row.name}")
            if not dry:
                session.delete(row)
        if rows and not dry:
            session.commit()
    finally:
        session.close()


def phase_warehouses(dry: bool) -> None:
    print("\n" + "=" * 70)
    print("阶段 1：仓库按名称分家")
    print("=" * 70)
    session = tenant.session_factory_for(PUBLIC_SCHEMA)()
    try:
        for code, target in WAREHOUSE_HOME.items():
            row = session.query(Warehouse).filter(Warehouse.code == code).first()
            if row is None:
                print(f"  ? 找不到仓库 {code}，跳过")
                continue
            print(f"  {'→ 将移动' if dry else '移动'} {row.code} {row.name} → {target}")
            if not dry:
                moved = _move(session, row, Warehouse, target)
                session.commit()
                if not moved:
                    print(f"    ! {code} 移动失败")
    finally:
        session.close()


def phase_copy_master(dry: bool) -> None:
    print("\n" + "=" * 70)
    print("阶段 2：基础资料复制到另外两家（保留 id）")
    print("=" * 70)
    source = tenant.session_factory_for(PUBLIC_SCHEMA)()
    try:
        for model in MASTER_MODELS:
            rows = [_dump(o) for o in source.query(model).all()]
            if not rows:
                continue
            for target in (HUANUOMAI_SCHEMA, WEIWEI_SCHEMA):
                print(f"  {'→ 将复制' if dry else '复制'} {model.__tablename__} {len(rows)} 行 → {target}")
                if dry:
                    continue
                target_session = tenant.session_factory_for(target)()
                try:
                    added = 0
                    for data in rows:
                        if target_session.get(model, data["id"]) is None:
                            target_session.add(model(**data))
                            added += 1
                    target_session.commit()
                    _bump_sequence(target_session, model)
                    print(f"      实际写入 {added} 行")
                finally:
                    target_session.close()
    finally:
        source.close()


def phase_business(dry: bool) -> None:
    print("\n" + "=" * 70)
    print("阶段 3：历史业务数据按仓库归属重新分配")
    print("=" * 70)
    session = tenant.session_factory_for(PUBLIC_SCHEMA)()
    try:
        # 仓库 id → 该仓库的 code。**跨所有 schema 扫**：真跑时阶段 1 已经把仓库
        # 搬到目标 schema 了，只扫 public 会找不到。
        code_of: dict[int, str] = {}
        for schema in (PUBLIC_SCHEMA, HUANUOMAI_SCHEMA, WEIWEI_SCHEMA):
            s = tenant.session_factory_for(schema)()
            try:
                for row in s.query(Warehouse).all():
                    code_of[row.id] = row.code
            finally:
                s.close()

        # 归属一律由 WAREHOUSE_HOME 决定，**不是**"当前它在哪个 schema"——
        # 这样 `--dry-run`（仓库还没搬）与真跑（已经搬了）得到的结论完全一致。
        def warehouse_target(warehouse_id) -> str | None:
            code = code_of.get(warehouse_id)
            if code is None:
                return None
            return WAREHOUSE_HOME.get(code, PUBLIC_SCHEMA)

        print("  仓库归属规划：")
        for wid, code in sorted(code_of.items()):
            if code in JUNK_WAREHOUSE_CODES:
                continue
            print(f"    {code:14s} → {warehouse_target(wid)}")

        # —— 库存流水 ——
        moved = 0
        for row in session.query(InventoryTransaction).order_by(InventoryTransaction.id).all():
            target = warehouse_target(row.warehouse_id)
            if target is None:
                print(f"  ! 库存流水 #{row.id} 的仓库 {row.warehouse_id} 不存在，留在原地")
                continue
            if target == PUBLIC_SCHEMA:
                continue
            print(f"  {'→ 将移动' if dry else '移动'} 库存流水 #{row.id}（{row.transaction_type} {row.quantity}）→ {target}")
            if not dry and _move(session, row, InventoryTransaction, target):
                session.commit()
            moved += 1

        # —— 销售单 + 明细 ——
        for order in session.query(SalesOrder).order_by(SalesOrder.id).all():
            target = warehouse_target(order.warehouse_id)
            if target is None or target == PUBLIC_SCHEMA:
                continue
            items = (
                session.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order.id).all()
            )
            print(f"  {'→ 将移动' if dry else '移动'} 销售单 {order.order_no} + {len(items)} 行明细 → {target}")
            if dry:
                continue
            for item in items:
                _move(session, item, SalesOrderItem, target)
                session.commit()
            if _move(session, order, SalesOrder, target):
                session.commit()

        # —— 报价单 ——
        for quote in session.query(Quotation).order_by(Quotation.id).all():
            target = warehouse_target(quote.warehouse_id)
            if target is None:
                print(f"  ! 报价单 {quote.quote_no} 没有仓库，留在原账套（请人工确认归属）")
                continue
            if target == PUBLIC_SCHEMA:
                continue
            print(f"  {'→ 将移动' if dry else '移动'} 报价单 {quote.quote_no} → {target}")
            if not dry and _move(session, quote, Quotation, target):
                session.commit()

        # —— 财务流水 ——
        # 发票同步产生的：note 形如「发票 <票号> | ...」，按票号找该发票现在在哪
        invoice_home: dict[str, str] = {}
        for schema in (PUBLIC_SCHEMA, HUANUOMAI_SCHEMA, WEIWEI_SCHEMA):
            s = tenant.session_factory_for(schema)()
            try:
                for no, in s.execute(text("SELECT invoice_no FROM invoices")).fetchall():
                    invoice_home[str(no)] = schema
            finally:
                s.close()

        order_home: dict[int, str] = {}
        for schema in (PUBLIC_SCHEMA, HUANUOMAI_SCHEMA, WEIWEI_SCHEMA):
            s = tenant.session_factory_for(schema)()
            try:
                for oid, in s.execute(text("SELECT id FROM sales_orders")).fetchall():
                    order_home[int(oid)] = schema
            finally:
                s.close()

        for row in session.query(FinancialTransaction).order_by(FinancialTransaction.id).all():
            note = str(row.note or "")
            target = None
            reason = ""
            if "发票" in note:
                invoice_no = ""
                for part in note.split("|")[0].replace("发票", " ").split():
                    if part.isdigit() and len(part) >= 12:
                        invoice_no = part
                        break
                target = invoice_home.get(invoice_no)
                reason = f"发票 {invoice_no}" if invoice_no else "发票（票号解析失败）"
            elif row.related_type == "sales_out" and row.related_order_id:
                target = order_home.get(int(row.related_order_id))
                reason = f"销售单 #{row.related_order_id}"
            if target is None or target == PUBLIC_SCHEMA:
                if target is None:
                    print(f"  ! 财务流水 #{row.id}（{reason or '无关联'}）找不到归属，留在原账套")
                continue
            print(f"  {'→ 将移动' if dry else '移动'} 财务流水 #{row.id} ¥{row.amount}（{reason}）→ {target}")
            if not dry and _move(session, row, FinancialTransaction, target):
                session.commit()

        print(f"\n  库存流水处理 {moved} 条")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="把历史数据按归属重新分配到三个账套")
    parser.add_argument("--dry-run", action="store_true", help="只看会怎么分，不动数据")
    args = parser.parse_args()
    dry = args.dry_run

    meta = SessionLocal()
    try:
        names = {c.schema_name: c.name for c in meta.query(Company).all()}
    finally:
        meta.close()
    print("账套：")
    for schema, name in names.items():
        print(f"  {schema:8s} {name}")

    if not dry:
        path = _snapshot(
            "all",
            [
                (PUBLIC_SCHEMA, Product),
                (PUBLIC_SCHEMA, Customer),
                (PUBLIC_SCHEMA, Supplier),
                (PUBLIC_SCHEMA, Warehouse),
                (PUBLIC_SCHEMA, InventoryTransaction),
                (PUBLIC_SCHEMA, SalesOrder),
                (PUBLIC_SCHEMA, SalesOrderItem),
                (PUBLIC_SCHEMA, Quotation),
                (PUBLIC_SCHEMA, FinancialTransaction),
            ],
        )
        print(f"\n已备份到：{path}")

    phase_clean_warehouses(dry)
    phase_warehouses(dry)
    phase_copy_master(dry)
    phase_business(dry)

    print("\n" + ("（试运行，未改动任何数据）" if dry else "全部完成。"))


if __name__ == "__main__":
    main()
