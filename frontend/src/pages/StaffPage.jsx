// 自动提取自 App.jsx（selectedTab='staff'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/staff/StaffBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文（约 1050 行），
//    需要再次压回下面这几行。
//
//    为什么搬走：这一页原来也是 ResizableLayout 套一个 section，左半屏空着，
//    部门靠一个下拉筛选。搬成组件后：左侧是**真实的部门层级树**（后端 department.level），
//    未选中时右表为空 —— 与客户/供应商/商品/仓库四页同一套交互契约。
import StaffBoard from '../components/staff/StaffBoard.jsx';

export default function StaffPage({ ctx }) {
  return <StaffBoard ctx={ctx} />;
}
