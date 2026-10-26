/* ERP PWA 服务工作者
 *
 * 作用：
 * 1. 首次安装时缓存应用外壳（页面、图标、清单）
 * 2. 静态资源：优先用缓存（离线也能打开），后台悄悄更新
 * 3. 业务接口 /api：永远走网络，不缓存（保证数据实时）
 *
 * 注意：改了版本号 CACHE_VERSION 后，旧缓存会自动清理（activate 里删掉所有非当前版本）。
 *
 * 什么时候要 bump：**每次发布**都建议 +1。历史教训：
 * 这个值曾经长期停在 'erp-pwa-v1'，而 shell 缓存里存着 '/'(index.html)，
 * 于是浏览器一直拿着旧首页 → 指向旧 hash 的 js → 前端明明重新构建了却「改了没变化」。
 * 现在服务端已给 index.html / sw.js 发 `Cache-Control: no-cache`（见 app/main.py 的
 * CacheControlledStaticFiles），bump 版本号只是**兜底**，防止老客户端残留。
 *
 * v2 → v3（2026-10-15）：侧边栏菜单字体改版。bump 后 activate 会删掉
 * 'erp-pwa-v2-shell'（里面存着旧 '/'），老客户端下次导航即自动恢复。
 * 同时把导航请求改成 `cache: 'no-store'`，让 index.html 永不从 HTTP 缓存里取。
 * v3 → v4（2026-10-16）：菜单树编辑器接入菜单管理页（新增按需 chunk）。
 * v4 → v5（2026-10-16）：商品档案左侧类别树（新增 lib/productCategory + 组件）。
 * v5 → v6（2026-10-16）：商品弹窗抽成独立组件并新增图片本地上传预览
 *   （新增 lib/productImage + components/product-edit）。图片本身走
 *   /api/v1/uploads/*，命不中本 SW 的 fetch 拦截（/api/ 开头直接 return），
 *   所以图片的缓存由后端下发的 Cache-Control 决定，这里不用管。
 * v6 → v7（2026-10-16）：商品列表新增首列「图片」缩略图 + 移除死代码
 *   flattenCategories。表格列号整体后移一位，CSS 的 nth-child 规则同步改了，
 *   老客户端若缓存了旧 CSS/JS，会出现"表头 13 列、内容 12 格"的错位
 *   —— 这一版必须 bump，不能省。
 * v7 → v8（2026-10-16）：商品弹窗新增「辅助单位与换算」维护区
 *   （新增 lib/productUnits + components/product-edit/ProductUnitsField）。
 *   bump 的原因不只是"有新代码"：**「包装数」这个输入框从可编辑改成了只读**，
 *   而且弹窗底部多了一整块表单。老客户端拿着旧 JS 打开弹窗时，用户会看到
 *   一个"改了不生效"的包装数输入框 —— 那比报错更难排查。
 * v8 → v9（2026-10-17）：单据明细行 + 商品期初库存的商品选择换成可搜索的
 *   SearchSelect；商品档案左栏类别树定宽。**这次的教训必须记下来**：改完忘了
 *   bump，构建成功、dist 也换了 hash，用户刷新看到的却还是原生 <select> ——
 *   Service Worker 拿 v8 的旧缓存把 index.html 原样还回去了。
 *   判定方法（不要跳过）：`grep -o 'combobox' dist/assets/index-*.js` 有命中、
 *   页面上却没有新组件 ⇒ 就是 SW 缓存，bump 版本号。
 * v9 → v10（2026-10-17，同日第二个发布）：Excel 导入导出页卡片字阶统一。
 *   同一天连发两版时**每版都要 bump**：v9 缓存里存着的老 index.html 会指向
 *   已经被 `vite build` 清掉的旧 hash 文件名，断网回退时会白屏。
 *   顺带澄清一个容易误判的点：本 SW 的**页面导航是「网络优先 + no-store」**，
 *   所以只要用户真按了 F5，index.html 一定是新的；他看到旧界面通常是
 *   "SPA 一直没整页刷新"（切菜单不会触发 navigation）。静态资源那条才是
 *   缓存优先，因此 bump 仍然必要。
 * v10 → v11（2026-10-17，同日第三个发布）：全局面板拖拽（新增
 *   components/resizable-layout，替换 35 处 management-grid）。
 *   这一版**必须先 bump 再让用户看效果**：老客户端里没有 ResizableLayout，
 *   JS 是旧的（表格布局照旧），用户会以为"拖拽根本没做"。
 * v11 → v12（2026-10-17，同一功能修复版）：修了两个只有真浏览器才暴露的问题 ——
 *   ① 组件 CSS 被 Vite 提到 styles.css 之前，同特异性下 `.management-grid`
 *      反压成功，网格仍是 2 列、手柄被塞进第二行（= 用户报的"拖不动"）。
 *      选择器升级成 `.management-grid.mgrid--split`（0,2,0）。
 *   ② pointerdown 里的 preventDefault 压掉了 mousedown/click 序列，
 *      导致 onDoubleClick 永远不触发（双击恢复默认是死的）、
 *      手柄点完也拿不到焦点（方向键微调失效）。
 *   两处都是"构建成功、页面能开、就是不对"的典型，必须 bump。
 * v12 → v13（2026-10-17，第二步示范重构）：商品档案页整页换成 ErpCard × 2 +
 *   ErpTable + EmptyState，商品弹窗两套表单合并成一套 ErpFormGrid。
 *   老客户端 JS 里还是 section.panel + 手写表格，用户会看到"重构没生效"。
 * v13 → v14（2026-10-17，第三步-A：客户/供应商档案）：两页从「单栏 data-table」
 *   换成 ErpCard × 2 + ErpTree 分组树 + ErpTable，弹窗换成 ErpFormGrid。
 *   页面结构变动很大（多了左侧树与拖拽手柄），必须 bump。
 * v14 → v15（2026-10-17，第三步-B：采购入库）：明细行从 `.form-row.four-col`
 *   换成 ErpTable dense（render 插槽放控件 + footer 合计），表头换 ErpFormGrid。
 *   老客户端 JS 里还是四列表单行，必须 bump。
 * v15 → v16（2026-10-17，清缓存 + 重新打包）：本次无功能改动，纯粹为了让所有
 *   已开着的客户端在下次导航时丢掉旧 shell 缓存、换成这次重新构建的产物
 *   （index.html 的 hash 变了，老 SW 缓存里的 '/' 会指向已经不存在的旧 chunk）。
 * v16 → v17（2026-10-17，销售出库重构）：SalesPage 1196 行 → 薄壳，
 *   整页 UI 搬进 components/docs/SalesOutboundBoard.jsx；ErpTable 新增可选的
 *   `rowProps`（补回列表行 Enter/空格 打开详情的键盘可达性）。
 *   这一版**必须** bump：明细行从 `.form-row.four-col` 变成 `.erp-table`，
 *   旧 JS + 新 CSS（或反过来）会让明细表渲染成一堆没有表头的裸输入框。
 * v17 → v18（2026-10-17，订单两页重构）：PurchaseOrderPage / SalesOrderPage 各 1133 行
 *   → 21 行薄壳，整页 UI 进 components/docs/OrderBoard.jsx（两页共用 CONFIG）。
 *   必须 bump 的理由同 v17：明细行从 `.form-row.three-col` 变成 `.erp-table`，
 *   订单列表多了「已转单」灰标、少了按钮，旧 JS 配新 CSS 会错位。
 * v18 → v19（2026-10-17，v1.0.0 发布：清道夫 + 重打桌面版）：
 *   ① styles.css 删掉 3 组已无宿主的规则（两条 :has() + 四/三列网格重写），
 *      全局 `.form-row.three-col`(12 页) / `.form-row.four-col` 原样保留；
 *   ② 修掉 v18 那段的注释收尾 —— 上一版把结束定界符写在了段落中间（星号+斜杠
 *      单独占一行），导致本文件**下方全部是语法错误**，SW 从 v18 起就没注册成功
 *      过（`node --check sw.js` exit 1）。写这类注释时务必别把结束定界符写进正文。
 *   必须 bump：CSS 内容变了，老客户端 shell 缓存里的 index-*.css 是旧 hash。
 * v19 → v20（2026-10-17，第一阶段 Step 1：客户/供应商「编辑」闭环）：
 *   两页的列表操作列多了「编辑」按钮，弹窗从"只有新增"变成"新增 / 编辑双模"，
 *   编码在编辑态只读；后端新增 PATCH /customers/{id} 与 PATCH /suppliers/{id}。
 *   必须 bump：老客户端 JS 里没有 partner-edit-btn、也不知道 PATCH 怎么发，
 *   用户点「编辑」会是彻底没反应 —— 这种"功能像没做"最难自证，先 bump 再让人看。
 *   同日注意：本版只是 Step 1，Step 2（ErpTable 多选）落地后还要再 bump 一次。
 * v20 → v21（2026-10-17，第一阶段 Step 2：ErpTable 多选 + 批量删除）：
 *   商品/客户/供应商列表最左侧多了一列 Checkbox（表头带全选/半选），有选中时
 *   表格上方浮出「已选中 N 项 + 批量删除」；批量删除走早已存在的
 *   `/products|/customers|/suppliers/batch`，按 deleted/blocked 分开报数。
 *   必须 bump：老客户端 JS 里没有选择列，也没有 bulkbar 的 CSS ——
 *   用户会以为"多选没做"。表格列数也整体后移一位，旧 CSS 配新 DOM 会错位。
 * v151 → v152（2026-10-21，封版收尾）：
 *   左侧分类树改造（分类下平铺客户叶子 + 同级手风琴折叠 + 拖拽后自动展开定位）、
 *   客户/供应商/商品三表列宽可拖并持久化、拖拽归档（客户/供应商/商品）、
 *   弹窗「所属分类」树形下拉回显修复。
 *   必须 bump：老客户端缓存着旧 index-*.js，里面没有 .ptree__leaf / 列宽抓手，
 *   用户会看到"树还是纯目录、表头拖不动"—— 也就是"改了没变化"。
 * v253 → v254（2026-10-24，合同页收尾）：
 *   合同左侧表单断层二次加固 + 模板库幽灵记录自动清扫 + 无变量模板前置汇总页。
 *   必须 bump：v253 缓存里的 index-*.css 是 10-24 10:50 之前的旧 hash，
 *   stale-while-revalidate 会先把旧样式还给用户 —— 用户报告"断层修了还在"。
 *   bump 后 activate 直接删旧缓存，下次导航必然拿到最新构建。 */

const CACHE_VERSION = 'erp-pwa-v265';
const CACHE_NAME = `${CACHE_VERSION}-shell`;

// 应用外壳：离线打开至少要有的文件
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

// 安装：预缓存应用外壳
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// 激活：删除旧版本缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// 请求拦截策略
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 业务接口：只走网络，失败时返回提示（不缓存真实数据）
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // 页面导航：网络优先（强制 cache:'no-store'，绕过 HTTP 缓存），断网时退回缓存首页
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() => caches.match('/'))
    );
    return;
  }

  // 其他静态资源：缓存优先 + 后台更新（stale-while-revalidate）
  if (event.request.method === 'GET') {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const network = fetch(event.request)
          .then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) =>
              cache.put(event.request, copy)
            );
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
