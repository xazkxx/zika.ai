// 销售订单 —— 整页 UI 已抽到 components/docs/OrderBoard.jsx（第三步-B 第三、四家共用）
//
// 为什么只剩一个转发：
//   「采购订单」与「销售订单」改造前各 1133 行、逐字同构，差异只有称谓、提交函数、
//   转单函数、打印路径、列表数据源、空态文案这 6 处。两页各写一遍必然漂移
//   （事实上已经漂了：两页都缺「删行」按钮，而 App.jsx 里的 removeSalesOrderItem
//   一直没人调用）。现在用 OrderBoard + ORDER_CONFIG 收口。
//
// ⚠️ 本页**核心业务动作**是「转开单」（只在 status !== 'completed' 时出现）：
//    它会 POST 到后端真的生成销售出库单、写库存与应收。
//    改这个文件/组件时，别把它当成普通按钮顺手删掉。
//
// ⚠️ 如果哪天把整页 JSX 搬回 App.jsx（恢复成 `&& (` 括号块），必须同时：
//    ① 在 scripts/patch_doc_forms.py 的 SPECS 里把 SalesOrderPage.jsx 加回去
//       （否则 data-doc-form / 单位下拉 / ErpSearchSelect / 半填红字会静默消失）；
//    ② 把这几处手工改动同步到 App.jsx。
import OrderBoard from '../components/docs/OrderBoard.jsx';

export default function SalesOrderPage({ ctx }) {
  return <OrderBoard ctx={ctx} kind="sales" />;
}
