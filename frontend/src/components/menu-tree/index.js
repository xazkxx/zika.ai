/**
 * 菜单树编辑器 —— 桶文件
 *
 * 用法（独立挂载，不改 App.jsx）：
 *   import MenuTreeEditor from './components/menu-tree';
 */

export { default as MenuTreeEditor } from './MenuTreeEditor.jsx';
export {
  planDrop,
  planShift,
  planIndent,
  planOutdent,
  computeDropIntent,
  flattenVisible,
  indexTree,
  auditTree,
  rowIndent,
  countNodes,
  treeDepth,
} from './menuTreeUtils.js';
export { fetchMenuTree, saveMenuOrder, probeReorderApi } from './menuTreeApi.js';
