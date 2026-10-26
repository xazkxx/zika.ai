// 自动提取自 App.jsx（selectedTab='purchase'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已改为**薄壳**（第三步-B）：整页 UI 在
//    components/docs/PurchaseInboundBoard.jsx。
//
//    为什么这次不需要 patch 脚本：
//    App.jsx 里这一页现在是 `{selectedTab === 'purchase' && <PurchasePage ctx={appCtx} />}`
//    —— **没有括号块**了，而 extract_pages.py 只认 `selectedTab === 'X' && (` 形式，
//    所以它不会再覆盖本文件。
//    ⚠️ 如果哪天把整块 JSX 搬回 App.jsx，必须照 `scripts/patch_partners_pages.py`
//       补一个同样的压回脚本，否则重抽即丢。
//
//    本页原来的手动改动（已全部搬进 PurchaseInboundBoard）：
//     ① `<form data-doc-form="inbound">` 锚点（CSS 靠它作用域）
//     ② 明细行商品格换成 ErpSearchSelect + 常驻 `<p class="line-invalid">`
//     ③ 第三步-B：ErpCard × 2 + ErpFormGrid/ErpFormRow + ErpTable dense + footer 合计
import PurchaseInboundBoard from '../components/docs/PurchaseInboundBoard.jsx';

export default function PurchasePage({ ctx }) {
  return <PurchaseInboundBoard ctx={ctx} />;
}
