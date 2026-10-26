// 自动提取自 App.jsx（selectedTab='warehouses'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/warehouses/WarehousesBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文（约 1030 行），
//    需要再次压回下面这几行。
//
//    为什么搬走：这一页原来是一个 ResizableLayout 套**一个** section
//    （只有一个子元素，拖拽手柄从来没生效过），右侧还把 warehouse 全量铺开。
//    搬成组件后：左侧状态树 = 入口，未选中时右表为空，与客户/供应商/商品同款手感。
import WarehousesBoard from '../components/warehouses/WarehousesBoard.jsx';

export default function WarehousesPage({ ctx }) {
  return <WarehousesBoard ctx={ctx} />;
}
