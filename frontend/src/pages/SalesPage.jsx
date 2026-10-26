// 销售出库 —— 整页 UI 已抽到 components/docs/SalesOutboundBoard.jsx（第三步-B 第二家）
//
// 这个文件为什么只剩一个转发（19 行里 17 行是注释）：
//   改造前的 1196 行全部是 App.jsx 里 `selectedTab === 'sales' && ( … )` 的展开件，
//   由 scripts/extract_pages.py 整块生成。现在 App.jsx 那一处已经是
//   `{selectedTab === 'sales' && <SalesPage ctx={appCtx} />}`（**没有 `&& (` 括号块**），
//   生成器按括号块匹配，找不到块就不会再覆盖这个文件 —— 所以**不需要**像
//   SalesPage 旧结构那样往 scripts/patch_doc_forms.py 里登记补丁。
//
// ⚠️ 如果哪天有人把整页 JSX 搬回 App.jsx（恢复成 `&& (` 形式），必须同时：
//    ① 在 scripts/patch_doc_forms.py 的 SPECS 里把 SalesPage.jsx 加回去
//       （否则 `data-doc-form="outbound"`、单位下拉、ErpSearchSelect、半填红字会静默消失）；
//    ② 把 `data-doc-form` 与 `unitOptionsFor` 那几处改动同步到 App.jsx。
//   现在的安排（页面只做转发、逻辑在组件里）是唯一"重抽生成器也不会丢东西"的形态。
import SalesOutboundBoard from '../components/docs/SalesOutboundBoard.jsx';

export default function SalesPage({ ctx }) {
  return <SalesOutboundBoard ctx={ctx} />;
}
