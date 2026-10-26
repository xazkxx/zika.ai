"""精准删除重复的空壳商品分类（2026-10-22 用户确认）。

删除名单：877「4G视频设备」、879「第一分公司」——两者都是**同名重复**：
  · 877 与 id=1 同名（id=1 现在挂在 机具设备分公司 下，9 个商品按名称归它）
  · 879 与 id=867 同名（在 陕西送变电 下）

**保留 878「塞拉利昂」**：它是全库唯一叫「塞拉利昂」的分类节点，
而 products.category 存的是**名称字符串**，有 2 个商品（PE篷布、快速连接环O型）
归在这个名称下。删了节点，这 2 个商品会在树里变成"未分类"——所以按
"保留有商品的原有分类"这条口径，它不能删。

安全闸（任一条不满足就跳过，不硬删）：
  ① 没有子分类；
  ② 同名的另一个分类确实存在（保证删完名称仍有归属）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.product_category import ProductCategory  # noqa: E402

TARGETS = [877, 879]
KEEP = {878: "全库唯一叫「塞拉利昂」的分类，2 个商品按名称挂在它下面，删了会变未分类"}


def main() -> int:
    db = SessionLocal()
    try:
        for cid in TARGETS:
            row = db.get(ProductCategory, cid)
            if row is None:
                print(f"{cid} 已不存在，跳过")
                continue
            kids = db.query(ProductCategory).filter(ProductCategory.parent_id == cid).count()
            twin = (
                db.query(ProductCategory)
                .filter(ProductCategory.name == row.name, ProductCategory.id != cid)
                .all()
            )
            if kids:
                print(f"❗ {cid}「{row.name}」还有 {kids} 个子分类，跳过")
                continue
            if not twin:
                print(f"❗ {cid}「{row.name}」没有同名分类兜底，删了会留下无归属名称 —— 跳过")
                continue
            twin_desc = "、".join(f"id={t.id}(parent={t.parent_id})" for t in twin)
            print(f"删 {cid}「{row.name}」 parent={row.parent_id}  → 同名保留：{twin_desc}")
            db.delete(row)
        db.commit()

        for cid, reason in KEEP.items():
            row = db.get(ProductCategory, cid)
            if row:
                print(f"保留 {cid}「{row.name}」：{reason}")

        print(f"\n复核：877/879 存在={db.query(ProductCategory).filter(ProductCategory.id.in_(TARGETS)).count()}"
              f"  878 存在={db.query(ProductCategory).filter(ProductCategory.id == 878).count()}"
              f"  商品分类总数={db.query(ProductCategory).count()}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
