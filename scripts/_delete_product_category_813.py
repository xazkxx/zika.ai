"""精准删除商品分类 id=813「国家电网公司」（测试误加）。

删前逐条核对：无子分类、无商品按名称引用它（商品归属靠 products.category 字符串）。
任一条不满足就中止，不硬删。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.product_category import ProductCategory  # noqa: E402

TARGET_ID = 813


def main() -> int:
    db = SessionLocal()
    try:
        row = db.get(ProductCategory, TARGET_ID)
        if row is None:
            print(f"分类 {TARGET_ID} 已不存在，无需处理")
            return 0
        print(f"目标：{row.id}  {row.name}  parent={row.parent_id}  创建于 {row.created_at}")

        kids = db.query(ProductCategory).filter(ProductCategory.parent_id == TARGET_ID).count()
        used = db.query(Product).filter(Product.category == row.name).count()
        if kids or used:
            print(f"❗ 还有 {kids} 个子分类 / {used} 个商品引用它，中止（不删）")
            return 1

        db.delete(row)
        db.commit()
        left = db.query(ProductCategory).filter(ProductCategory.id == TARGET_ID).count()
        total = db.query(ProductCategory).count()
        print(f"✅ 已删除，复核：id={TARGET_ID} 存在={left}，商品分类总数 {total}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
