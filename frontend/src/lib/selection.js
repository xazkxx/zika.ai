/**
 * selection —— 列表多选里唯一需要"想清楚"的那一步（纯函数，无 React、无 DOM）
 *
 * `<ErpTable selectable>` 只负责"画"和"算全选/半选"，**选中集由父级持有**。
 * 于是父级就得回答一个问题：数据变了，那些已经不存在的 key 怎么办？
 *
 * 不处理会出两种事故，而且都很隐蔽：
 *   ① 批量删除成功后没清选中集 → 再点一次"批量删除"，把已经删掉的 id 又发一遍，
 *      后端返回一堆 not_found，用户看到"删除成功但好像没删干净"；
 *   ② 换了账套/重新加载后 id 复用 → 选中集里的旧 id 恰好对应到**另一条记录**，
 *      下一次批量操作就动到了用户没勾过的数据。
 *
 * 所以规则只有一条：**选中集必须是当前数据的子集**。这里不做"保留跨页选择"之类的
 * 聪明事 —— 那种需求要显式的"跨页选择"UI，靠一个 prune 猜不出来。
 */

/**
 * 把选中集里已经不存在的 key 剔掉。
 *
 * @param {Array<string|number>} keys 当前选中集
 * @param {Array<object>} rows        当前全量数据（**不是**筛选后的那一份）
 * @param {string|Function} key       `'id'` 或 `(row) => key`
 * @returns {Array<string|number>}    原数组（当没有需要剔除的项时**返回同一个引用**）
 *
 * ⚠️ 第三个返回值细节很重要：React 里 `setState(同一个引用)` 会跳过重渲染，
 * 而这个函数经常被写在 `useEffect(() => setKeys(prune(...)), [rows])` 里 ——
 * 每次都返回新数组会引发"effect → setState → 重渲染 → effect"的循环。
 */
export function pruneSelection(keys, rows, key = 'id') {
  const list = Array.isArray(keys) ? keys : [];
  if (list.length === 0) return list;

  const alive = new Set();
  (rows || []).forEach((row, index) => {
    const value = typeof key === 'function' ? key(row, index) : row?.[key];
    if (value !== null && value !== undefined) alive.add(value);
  });

  const next = list.filter((k) => alive.has(k));
  return next.length === list.length ? list : next;
}

/**
 * 勾选/取消一个 key，返回新数组（受控组件要的是不可变更新）。
 * 顺带保证顺序稳定：新勾的追加在末尾，而不是每次都重排序 ——
 * 否则"批量删除"的请求体顺序会随机变，排查日志时对不上。
 */
export function toggleKey(keys, key) {
  const list = Array.isArray(keys) ? keys : [];
  return list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
}
