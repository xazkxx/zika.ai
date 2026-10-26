// 自动提取自 App.jsx（selectedTab='products'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/products/ProductsBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文，需执行：
//        python scripts/patch_products_board.py --apply
//    把它压回下面这一行（脚本幂等，已压过则空操作）。
//
//   历史手工修改（内容已全部搬到 ProductsBoard）：
//     ① 分类树 <div className="category-tree">{renderCategoryNodes()}</div>
//     ② 产品列表首列「图片」缩略图
//     ③ 第二步示范重构：ErpCard × 2 + ErpTable + EmptyState
import ProductsBoard from '../components/products/ProductsBoard.jsx';

export default function ProductsPage({ ctx }) {
  return <ProductsBoard ctx={ctx} />;
}
