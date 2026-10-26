"""清理 2026-10-22 交互验收残留（只删指定 id，删前逐条核对）。

被删对象都是我刚造的测试数据：
  customers  11756 CUST-IN-471578   已在目标里-471578
  customers  11757 CUST-DRAG-471578 待拖客户-471578
  categories 447   联动子级-471578（446 的子级）
  categories 446   联动目标-471578（含上面两个客户）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.partner_category import CustomerCategory  # noqa: E402

CUSTOMER_IDS = [11756, 11757]
CATEGORY_IDS = [447, 446]  # 先子后父


def main() -> int:
    db = SessionLocal()
    try:
        for cid in CUSTOMER_IDS:
            row = db.get(Customer, cid)
            if row is None:
                print(f"客户 {cid} 已不存在")
                continue
            print(f"删客户 {cid}  {row.code}  {row.name}")
            db.delete(row)
        db.flush()
        for cid in CATEGORY_IDS:
            row = db.get(CustomerCategory, cid)
            if row is None:
                print(f"分类 {cid} 已不存在")
                continue
            kids = db.query(CustomerCategory).filter(CustomerCategory.parent_id == cid).count()
            used = db.query(Customer).filter(Customer.category_id == cid).count()
            if kids or used:
                print(f"❗ 分类 {cid}「{row.name}」还有 {kids} 个子级 / {used} 个客户，跳过")
                continue
            print(f"删分类 {cid}  {row.name}")
            db.delete(row)
        db.commit()
        left = db.query(CustomerCategory).filter(CustomerCategory.name.like("联动%")).count()
        print(f"\n复核：剩余「联动*」分类 {left} 个")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
