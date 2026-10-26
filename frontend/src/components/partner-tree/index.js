/**
 * partner-tree —— 客户/供应商「真实分类树」组件包
 *
 *   PartnerTree          展示 + 交互（无限极、深级拖拽、搜索定位），只吃 props
 *   usePartnerCategories 数据层（拉树 / 乐观拖拽 / 回滚 / 路径与子树索引）
 *   partnerTreeApi       10 条后端路由的封装
 *   纯逻辑在 `src/lib/partnerTree.js`（27 条单测）
 *
 * 接入方式见 `_partner_tree_step5/README.md`。
 */

export { default as PartnerTree } from './PartnerTree.jsx';
export { usePartnerCategories } from './usePartnerCategories.js';
export {
  fetchCategories,
  moveCategory,
  createCategory,
  updateCategory,
  deleteCategory,
  readErrorDetail,
  routeOf,
} from './partnerTreeApi.js';
