/**
 * partnerTree —— 客户/供应商「真实分类树」的纯逻辑（无 React、无 DOM）
 *
 * 为什么单独抽出来：
 *   这棵树跟「按业务员分组」那棵（`lib/partnerGroup.js`）不是一回事 —— 那棵是**视图树**
 *   （按字段现场分组、天生两级、拖不动）；这棵是**物理树**（`customer_categories` 表，
 *   无限极、可跨级拖拽）。真正有边界条件的是这几块，靠鼠标点是点不全的：
 *     · 深级缩进与折叠（层级没有上限，DOM 不能全渲染）
 *     · 拖拽落点解析（inside / before / after → 后端要的 parent_id + before_id）
 *     · 跨级拖拽的**合法性**（不能拖进自己的后代里，否则数据成环）
 *     · 搜索命中 + 父级自动展开
 *   所以这里做成纯函数，用 `node --test` 守着（`partnerTree.test.mjs`）。
 */

import { isLatinQuery, pinyinInitials } from './pinyinInitials.js';

/**
 * 数据形状（后端 `GET /api/v1/{kind}-categories`）：
 *   { id, name, parent_id, sort_order, note, created_at, count, total, children: [] }
 *     count = 直接挂在本节点下的档案数
 *     total = 含全部子孙的合计
 *
 * 设计口径：
 *   · **只认 id，不认 name** —— 分类可改名、可跨分支重名（同父级才唯一），
 *     用 name 当键会在"改名/重名"这两件事上同时出错。
 *   · **不修改入参** —— 所有变换都返回新对象（乐观更新时要能整体回滚）。
 *   · **环一律当"断链"处理** —— 后端已经挡了，但导入脚本/手工改库仍可能造环；
 *     这里所有遍历都带 `seen` + 深度上限，最坏结果是"某几个节点不显示"，绝不 RecursionError。
 */

/** 「未分类」伪节点的键。不能用 0 / -1 —— 真实 id 从 1 开始，但 0 在某些序列里会合法 */
export const UNCLASSIFIED = '__unclassified__';

/** 每级缩进（px）。14px 是深树的上限值：再大，第 8 层就把标签挤成 2 个字 */
export const INDENT_PX = 14;

/** 超过这个深度算「深层」：折叠图标要更明显 */
export const DEEP_DEPTH = 4;

/**
 * 缩进的视觉上限（层）。
 * ⚠️ 深树的缩进必须**封顶**：14px × 20 层 = 280px，标签只剩一条缝。
 *    超过 10 层后不再继续缩进（标签仍在，靠 `title` 与右侧层级角标兜底）。
 */
export const MAX_INDENT_DEPTH = 10;

/** 遍历的安全上限（防脏数据成环时把栈打爆） */
const MAX_WALK_DEPTH = 64;

const num = (value) => Number(value);

function idOf(node) {
  const id = num(node && node.id);
  return Number.isFinite(id) ? id : null;
}

/**
 * 建索引：一次遍历把"找自己 / 找爹 / 找孩子 / 看深度"全备好。
 *
 * 为什么不用 `node.children` 直接递归：
 *   拖拽后我们要判断"目标是不是我的后代"，而这时树可能正处在乐观更新前的旧状态。
 *   用 id → parent 的扁平映射判断，与渲染出来的数据无关，结论永远一致。
 *
 * @returns {{byId: Map<number, Object>, parentOf: Map<number, number|null>,
 *            childrenOf: Map<number|null, number[]>, depthOf: Map<number, number>,
 *            preorder: number[]}}
 */
export function indexTree(roots = []) {
  const byId = new Map();
  const parentOf = new Map();
  const childrenOf = new Map();
  const depthOf = new Map();
  const preorder = [];

  const walk = (list, parentId, depth) => {
    if (depth > MAX_WALK_DEPTH) return;
    (Array.isArray(list) ? list : []).forEach((node) => {
      const id = idOf(node);
      if (id === null || byId.has(id)) return; // 脏数据（重复 id / 环）：先到的赢
      byId.set(id, node);
      parentOf.set(id, parentId);
      depthOf.set(id, depth);
      preorder.push(id);
      if (!childrenOf.has(parentId)) childrenOf.set(parentId, []);
      childrenOf.get(parentId).push(id);
      walk(node.children, id, depth + 1);
    });
  };

  walk(roots, null, 0);
  // 每个节点（含根级 null）都先占一个空数组：
  // `childrenOf.get(叶子)` 必须返回 `[]` 而不是 `undefined`。
  // 否则调用方每处都要写 `|| []`，漏一处就是 `undefined.forEach` 崩在渲染里（实测踩过）。
  byId.forEach((_node, id) => {
    if (!childrenOf.has(id)) childrenOf.set(id, []);
  });
  if (!childrenOf.has(null)) childrenOf.set(null, []);
  return { byId, parentOf, childrenOf, depthOf, preorder };
}

/** 先序遍历成扁平数组（展开全部 / 批量判断用） */
export function flattenTree(roots = []) {
  const out = [];
  const walk = (list, parentId, depth) => {
    if (depth > MAX_WALK_DEPTH) return;
    (Array.isArray(list) ? list : []).forEach((node) => {
      out.push({ node, parentId, depth });
      walk(node.children, node.id, depth + 1);
    });
  };
  walk(roots, null, 0);
  return out;
}

/** 所有祖先 id，**从根到父**（不含自己）。找不到返回 []。 */
export function ancestorsOf(index, id) {
  const chain = [];
  let cursor = index.parentOf.has(id) ? index.parentOf.get(id) : null;
  let guard = 0;
  while (cursor !== null && cursor !== undefined && guard < MAX_WALK_DEPTH) {
    chain.unshift(cursor);
    cursor = index.parentOf.has(cursor) ? index.parentOf.get(cursor) : null;
    guard += 1;
  }
  return chain;
}

/**
 * `id` 是否在 `ancestorId` 的子树里（含自己）。
 * 拖拽的唯一硬约束：不能把节点拖进自己的后代 —— 否则它在树上消失、在库里成环。
 */
export function isDescendant(index, ancestorId, id) {
  if (ancestorId === null || ancestorId === undefined) return false;
  let cursor = id;
  let guard = 0;
  while (cursor !== null && cursor !== undefined && guard < MAX_WALK_DEPTH) {
    if (cursor === ancestorId) return true;
    cursor = index.parentOf.has(cursor) ? index.parentOf.get(cursor) : null;
    guard += 1;
  }
  return false;
}

/** 子树全部 id（含自己）。用于「选中分类 → 过滤表格」的包含口径 */
export function subtreeIds(index, id) {
  const out = new Set();
  const stack = [id];
  let guard = 0;
  while (stack.length && guard < 10000) {
    guard += 1;
    const cursor = stack.pop();
    if (out.has(cursor)) continue; // 环保护
    out.add(cursor);
    (index.childrenOf.get(cursor) || []).forEach((childId) => stack.push(childId));
  }
  return out;
}

/**
 * 分类的全路径名，给表格的「分类」列用：`集团客户 / 分公司 / 子公司甲 / 项目A`。
 * id 为空、或该 id 已不在树里（比如被别的窗口删了）→ 返回空串，由调用方回落「未分类」。
 */
export function pathLabel(index, id, separator = ' / ') {
  if (id === null || id === undefined || id === '') return '';
  const target = num(id);
  if (!index.byId.has(target)) return '';
  const names = [...ancestorsOf(index, target), target]
    .map((each) => (index.byId.get(each) || {}).name)
    .filter(Boolean);
  return names.join(separator);
}

/**
 * 档案行是否落在选中分类的**子树**里。
 *   selectedId = null / UNCLASSIFIED → 未分类那一档
 *   selectedId = 具体 id            → 含全部子孙（集团客户选中时，下面所有分公司都算）
 */
export function rowInCategory(row, index, selectedId) {
  const raw = row ? row.category_id : null;
  if (selectedId === UNCLASSIFIED) return raw === null || raw === undefined || raw === '';
  if (selectedId === null || selectedId === undefined) return true;
  if (raw === null || raw === undefined || raw === '') return false;
  return subtreeIds(index, num(selectedId)).has(num(raw));
}

/**
 * 搜索：命中的节点 + 它们的全部祖先。
 *
 * 返回 `order` 是**先序**的命中列表 —— 回车跳"下一个"必须跟眼睛看到的顺序一致，
 * 用 Set 的插入顺序会得到"先命中子级、再命中父级"的乱序。
 */
/** 客户/供应商档案里参与搜索的字段（编码、联系人、电话都算 —— 用户常按"周广平"找人） */
export const PARTNER_SEARCH_FIELDS = [
  'name',
  'code',
  'contact',
  'phone',
  'mobile',
  'contact_phone',
  'businesser',
  'short_name',
  'tax_no',
];

/**
 * 搜索**挂在分类下的叶子**（客户/供应商档案）。
 *
 * 为什么单独一个函数：`searchNodes` 只走 `children`（分类树），
 * 而档案是按 `category_id` 挂在分类下的另一份数据（`rowsByCategory`）。
 * 两份数据合起来才是"用户眼里的这棵树" —— 只能搜到分类名、搜不到客户，
 * 就是这次要修的那个缺陷（搜"周广平"什么都出不来）。
 *
 * @param {Map|Object} buckets 分类 id → 该分类下的档案行
 * @returns {{byCategory: Map<string, Array>, hitIds: number[], terms: string}}
 *   键统一成**字符串**：调用方既可能用数字 id，也可能来自 `<select>` 的字符串。
 */
export function matchPartnerLeaves(buckets, query = '', fields = PARTNER_SEARCH_FIELDS) {
  const byCategory = new Map();
  const hitIds = [];
  const needle = String(query || '').trim().toLowerCase();
  if (!needle || !buckets) return { byCategory, hitIds, terms: '' };

  // 拼音首字母（2026-10-23）：zgp → 周广平。只在关键词纯拉丁时才走拼音通道，
  // 否则汉字搜索会平白多一轮换算。`pinyinInitials` 内部有 memo，不会反复算。
  const latin = isLatinQuery(needle);

  const entries = buckets instanceof Map ? buckets.entries() : Object.entries(buckets);
  for (const [rawId, rows] of entries) {
    const list = Array.isArray(rows) ? rows : [];
    const hits = list.filter((row) =>
      fields.some((field) => {
        const value = row ? row[field] : '';
        if (value === null || value === undefined) return false;
        const text = String(value).toLowerCase();
        if (text.includes(needle)) return true;
        return latin && pinyinInitials(text).includes(needle);
      }),
    );
    if (!hits.length) continue;
    byCategory.set(String(rawId), hits);
    const numeric = Number(rawId);
    hitIds.push(Number.isNaN(numeric) ? rawId : numeric);
  }
  return { byCategory, hitIds, terms: String(query).trim() };
}

export function searchNodes(roots = [], query = '') {
  const needle = String(query || '').trim().toLowerCase();
  const empty = { matched: new Set(), ancestors: new Set(), order: [], terms: '' };
  if (!needle) return empty;

  // 拼音首字母（2026-10-23）：zgp → 周广平。与子串匹配是「或」关系：
  // 汉字照旧按字面搜，拉丁关键词额外试一遍首字母串。
  const latin = isLatinQuery(needle);

  const matched = new Set();
  const ancestors = new Set();
  const order = [];

  const walk = (list, chain, depth) => {
    if (depth > MAX_WALK_DEPTH) return;
    (Array.isArray(list) ? list : []).forEach((node) => {
      const name = String(node && node.name ? node.name : '');
      const nameL = name.toLowerCase();
      let hit = nameL.includes(needle);
      if (!hit && latin) hit = pinyinInitials(nameL).includes(needle);
      const nextChain = [...chain, idOf(node)];
      if (hit) {
        const id = idOf(node);
        if (id !== null && !matched.has(id)) {
          matched.add(id);
          order.push(id);
          chain.forEach((each) => ancestors.add(each));
        }
      }
      walk(node.children, nextChain, depth + 1);
    });
  };

  walk(roots, [], 0);
  return { matched, ancestors, order, terms: String(query || '').trim() };
}

/**
 * 把树摊成"当前应该渲染成哪几行"。
 *
 * 两条完全不同的可见性规则，混在一起写必错：
 *   · 无搜索：**只有展开的分支**才往下走（这是深树不撑爆屏幕的根本）
 *   · 有搜索：只显示命中节点 + 它们的祖先，**祖先强制展开**（用户搜"项目A"要能看见
 *     它在哪个集团下面），但**不写入** `expanded` —— 否则一清空搜索，树就全开了
 *
 * @returns {{rows: Array, hitIds: number[]}}
 *   rows[i] = { id, node, depth, parentId, hasChildren, isOpen, isMatched }
 */
export function buildVisibleRows(
  roots = [],
  index,
  { expanded = [], query = '', focusOnly = false, focusIndex = -1, leafHits = [] } = {},
) {
  const openSet = expanded instanceof Set ? expanded : new Set(expanded || []);
  const search = searchNodes(roots, query);

  /**
   * 叶子命中（2026-10-23）：`leafHits` = "有档案命中的分类 id"。
   *
   * 三个连带效果，缺一个都会"搜到了却看不见"：
   *   ① 这些分类本身算命中（计数、逐跳都要带上）；
   *   ② 它们的**祖先链**要强制展开（不然客户藏在折叠的分支里）；
   *   ③ 它们自己要被展开（客户行是插在分类行下面的，分类不展开就没有位置）。
   *
   * 顺带解决"空壳文件夹"：可见性只按"命中 / 命中祖先 / 命中分类"三个条件算，
   * 没命中的兄弟分类自然一个都不渲染。
   */
  const leafHitSet = new Set((leafHits || []).map((id) => (typeof id === 'number' ? id : String(id))));
  const leafAncestors = new Set();
  const leafOrder = [];
  leafHitSet.forEach((id) => {
    (ancestorsOf(index, id) || []).forEach((ancestor) => leafAncestors.add(ancestor));
    if (!search.matched.has(id)) leafOrder.push(id);
  });
  // 命中顺序：先分类名命中（先序），再"只有档案命中的分类"（也算一处命中，Enter 能跳到）
  const hitOrder = [...search.order, ...leafOrder];
  const searching = hitOrder.length > 0 || String(query || '').trim() !== '';
  const rows = [];

  /**
   * 「一次只展开一条路径」（2026-10-19 改）。
   *
   * 旧行为：**所有**命中项的祖先链同时强制展开 —— 搜一个常见字（"公司"）
   * 会瞬间摊开十几条链，用户原话"非常难以识别"。而且它和页面上已经有的
   * 「找到 N 个 ↑↓ 逐个跳」是两套互相打架的设计：既然能逐个跳，
   * 就不该把所有链一次性摊在屏幕上。
   *
   * 新行为（`focusOnly`）：树里只保留**当前定位的那一条**链路
   * （命中项 + 它的父级），其余命中项通过 ↑↓ 按键逐个抵达；
   * `focusIndex` = 命中序号（`hitIds` 的下标），-1 时取第一个命中。
   *
   * 默认 `false`，保持老行为 —— 单测与其它调用方不受影响。
   */
  const focusId = !searching || !focusOnly || !hitOrder.length
    ? null
    : (hitOrder[Math.max(0, Math.min(focusIndex, hitOrder.length - 1))] ?? null);
  const focusChain = focusId === null ? null : new Set([...ancestorsOf(index, focusId), focusId]);

  const walk = (list, depth, parentId) => {
    if (depth > MAX_WALK_DEPTH) return;
    (Array.isArray(list) ? list : []).forEach((node) => {
      const id = idOf(node);
      if (id === null) return;
      const children = Array.isArray(node.children) ? node.children : [];
      const hasChildren = children.length > 0;
      const isMatched = search.matched.has(id);

      const isLeafHolder = leafHitSet.has(id);
      const isLeafAncestor = leafAncestors.has(id);

      // 有搜索时：只保留"命中 + 命中项的祖先 + 有档案命中的分类及其祖先"
      // （focusOnly 时再收窄到一条链，但**客户命中的分类永远保留**，否则客户没地方显示）
      const visible = !searching
        || (focusChain
          ? focusChain.has(id) || isLeafHolder
          : isMatched || search.ancestors.has(id) || isLeafHolder || isLeafAncestor);
      if (!visible) return;

      const isOpen = searching
        ? (focusChain
          ? (focusChain.has(id) && (id !== focusId || isLeafHolder)) || isLeafHolder
          : search.ancestors.has(id) || isLeafAncestor || isLeafHolder)
        : openSet.has(id);

      rows.push({ id, node, depth, parentId, hasChildren, isOpen, isMatched, searching });
      if (hasChildren && isOpen) walk(children, depth + 1, id);
    });
  };

  walk(roots, 0, null);
  return {
    rows,
    hitIds: hitOrder,
    categoryHitIds: search.order,
    leafHitIds: leafOrder,
    searching,
  };
}

/** 一行的左内边距（px）。封顶在 `MAX_INDENT_DEPTH`，深树才不会把标签挤没 */
export function indentOf(depth, base = 8) {
  const level = Math.max(0, Math.min(Number(depth) || 0, MAX_INDENT_DEPTH));
  return base + level * INDENT_PX;
}

/**
 * 指针在行内的相对高度 → 落点语义。
 *   ratio < 0.28  → before（插到这一行上面）
 *   ratio > 0.72  → after （插到这一行下面）
 *   其余          → inside（成为这一行的子级）
 * 中间 44% 留给 inside：拖拽时"想插到两行之间"和"想放进去"是两种意图，
 * 而"放进去"更常见，给的判定带要更宽。
 *
 * 触屏另有一套比例（20% / 60% / 20%），见 `zones` 参数。
 *
 * @param {number} ratio 0~1
 * @param {{before?: number, after?: number}} [zones] 上下两档各占多少比例
 */
export function dropZoneFromRatio(ratio, zones = {}) {
  const value = Number(ratio);
  if (!Number.isFinite(value)) return 'inside';
  const before = Number(zones.before) > 0 ? Number(zones.before) : 0.28;
  const after = Number(zones.after) > 0 ? Number(zones.after) : 0.28;
  if (value < before) return 'before';
  if (value > 1 - after) return 'after';
  return 'inside';
}

/** 某个节点在其父级下的下一个兄弟 id（没有就 null = 排最后） */
export function nextSiblingId(index, id) {
  const parentId = index.parentOf.has(id) ? index.parentOf.get(id) : null;
  const siblings = index.childrenOf.get(parentId === undefined ? null : parentId) || [];
  const at = siblings.indexOf(id);
  if (at < 0 || at === siblings.length - 1) return null;
  return siblings[at + 1];
}

/**
 * 「上移 / 下移」换算成落点（按钮通道用）。
 *
 * 为什么按钮也要走 `{parentId, beforeId}` 而不是自己算 sort_order：
 *   拖拽和按钮必须**落到同一套落点语义**上，否则同一个动作在两种入口下
 *   顺序会不一样，而且服务端的重排规则只有一份。
 *
 * @param {object} index `indexTree()` 的返回
 * @param {number} id 要移动的节点
 * @param {number} delta -1 = 上移一格，+1 = 下移一格
 * @returns {{parentId: number|null, beforeId: number|null}|null} null = 已在边界，不动
 */
export function siblingMoveTarget(index, id, delta) {
  const target = num(id);
  if (!index || !index.byId.has(target)) return null;
  const parentId = index.parentOf.has(target) ? index.parentOf.get(target) : null;
  const siblings = index.childrenOf.get(parentId) || [];
  const at = siblings.indexOf(target);
  if (at < 0) return null;

  const step = Number(delta) < 0 ? -1 : 1;
  const next = at + step;
  if (next < 0 || next >= siblings.length) return null; // 到顶 / 到底

  if (step < 0) return { parentId, beforeId: siblings[next] };
  // 下移 = 插到「下下个」之前；下下个不存在（自己是倒数第二个）→ 追加到末尾
  return { parentId, beforeId: next + 1 < siblings.length ? siblings[next + 1] : null };
}

/**
 * 拖拽落点 → 后端 `/move` 要的 `{ parentId, beforeId }`。
 * 返回 `null` 表示**这次拖拽不合法，一个请求都别发**：
 *   · 拖到自己身上
 *   · 拖进自己的后代（会把子树从树上摘掉 + 库内成环）
 *   · 目标节点已经不在树里（并发删除）
 */
export function resolveDrop(index, dragId, targetId, zone) {
  if (dragId === null || dragId === undefined) return null;
  if (targetId === null || targetId === undefined) return null;
  const from = num(dragId);
  const to = num(targetId);
  if (from === to) return null;
  if (!index.byId.has(from) || !index.byId.has(to)) return null;
  if (isDescendant(index, from, to)) return null;

  if (zone === 'inside') return { parentId: to, beforeId: null };
  const parentId = index.parentOf.get(to);
  if (zone === 'before') return { parentId: parentId === undefined ? null : parentId, beforeId: to };
  return {
    parentId: parentId === undefined ? null : parentId,
    beforeId: nextSiblingId(index, to),
  };
}

/**
 * 多选批量：把用户选中的一堆 id 收敛成「真正要发请求的」+「会跟着父级一起走的」。
 *
 * 为什么要归一化：
 *   移父节点时子节点**本来就跟着走**（parent_id 不变）。如果父子同时发请求，
 *   结果取决于调用顺序（先移子再移父 = 子被父带回去，白移一次；先移父 = 子还留在旧父下），
 *   而且服务端每处理一条都要重排一次兄弟链表 —— 多发一条就多一次无意义的写入。
 *   所以只保留"祖先在选区里"最靠上的那些，被覆盖的记进 `covered`，由 UI 标灰并提示。
 *
 * @param {object} index `indexTree()` 的返回
 * @param {Iterable<number>|number[]} ids 用户选中的 id（允许重复、允许 Set、允许脏值）
 * @returns {{kept: number[], covered: number[], ignored: number[]}}
 *   kept    真正要移动的（保持传入顺序，批量移动的落地顺序就是它）
 *   covered 被选区里的祖先包住、只需要跟着走的
 *   ignored 树上已经不存在的（并发删除 / 脏数据），既不移动也不报错
 */
export function normalizeSelection(index, ids) {
  // ⚠️ 不能直接用 `num()`：`Number(null) === 0`，脏值会变成 id 0 混进选区
  const toId = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const id = Number(value);
    return Number.isFinite(id) ? id : null;
  };
  const raw = ids && typeof ids[Symbol.iterator] === 'function' ? Array.from(ids) : [];
  const list = [];
  const seen = new Set();
  raw.forEach((value) => {
    const id = toId(value);
    if (id === null || seen.has(id)) return; // 去重：同一批里重复选了同一个节点
    seen.add(id);
    list.push(id);
  });

  if (!index || !index.byId) return { kept: [], covered: [], ignored: list };

  const onTree = [];
  const ignored = [];
  list.forEach((id) => {
    (index.byId.has(id) ? onTree : ignored).push(id);
  });

  const chosen = new Set(onTree);
  const kept = [];
  const covered = [];
  onTree.forEach((id) => {
    // 祖先链里只要有一个也在选区里，这个节点就不需要单独发请求
    const carriedByAncestor = ancestorsOf(index, id).some((ancestorId) => chosen.has(ancestorId));
    (carriedByAncestor ? covered : kept).push(id);
  });
  return { kept, covered, ignored };
}

/**
 * 批量移动的合法性 + 计划（把 `normalizeSelection` 和落点校验合成一步，
 * 调用方不会"忘了先归一化再校验"）。
 *
 * 返回的 `ids` 就是**要串行调用 `/move` 的列表**；`beforeId` 一律 null ——
 * 多个节点来自不同父级，它们的相对顺序在目标父级里没有语义，追加到末尾是唯一可预测的结果。
 *
 * code 语义：
 *   ok      可以移动
 *   empty   没有可移动的节点（一个都没选中 / 全被父级覆盖 / 全不在树上）
 *   missing 目标分类已经不在了（并发删除）
 *   self    目标是选中项自己
 *   cycle   目标是某个选中项的后代 → 会把子树摘下来并成环
 *   noop    选中的全都已经在目标父级下了，一个请求都不用发（不算失败）
 *
 * @param {object} index `indexTree()` 的返回
 * @param {Iterable<number>|number[]} ids
 * @param {number|null} targetId 目标父级；null = 移到顶级
 * @returns {{ok: boolean, code: string, reason: string, ids: number[], covered: number[], ignored: number[], alreadyThere: number[], blockedBy?: number}}
 *   `alreadyThere` 是"父级已经是目标"的那批：**不移动**（否则服务端会把它们从原位置重排到末尾）
 */
export function batchMovePlan(index, ids, targetId) {
  const { kept, covered, ignored } = normalizeSelection(index, ids);
  const base = { ids: kept, covered, ignored };

  if (!kept.length) {
    return { ...base, ok: false, code: 'empty', reason: '没有可移动的分类' };
  }

  // targetId = null 是合法落点（移到顶级）；其余必须能在树上找到
  const to = targetId === null || targetId === undefined || targetId === '' ? null : Number(targetId);
  if (to !== null && (!Number.isFinite(to) || !index.byId.has(to))) {
    return { ...base, ok: false, code: 'missing', reason: '目标分类已经不在了' };
  }
  if (to !== null && kept.includes(to)) {
    return { ...base, ok: false, code: 'self', reason: '不能把分类移到自己下面' };
  }
  const inside = kept.find((id) => isDescendant(index, id, to));
  if (inside !== undefined) {
    return { ...base, ok: false, code: 'cycle', reason: '不能移进它自己的子级里', blockedBy: inside };
  }

  const parentOf = (id) => (index.parentOf.has(id) ? index.parentOf.get(id) : null);
  // 已经在目标父级下的**不能**再发一次 move：服务端会把它从原位置重排到末尾，
  // 用户看到的就是"我没动它，它怎么跑到最后去了"。剔除并单独告知。
  const alreadyThere = kept.filter((id) => parentOf(id) === to);
  const moving = kept.filter((id) => parentOf(id) !== to);
  if (!moving.length) {
    return { ...base, ids: [], alreadyThere, ok: false, code: 'noop', reason: '已经在这个分类下了' };
  }

  return { ...base, ids: moving, alreadyThere, ok: true, code: 'ok', reason: '' };
}

/** 把扁平节点按 parent 关系装回树；兄弟按 sort_order 排，同号再按 id 兜底 */
export function rebuildTree(flat = []) {  const nodes = new Map();
  flat.forEach((item) => {
    const id = idOf(item);
    if (id === null) return;
    nodes.set(id, { ...item, children: [] });
  });

  const roots = [];
  flat.forEach((item) => {
    const id = idOf(item);
    if (id === null) return;
    const node = nodes.get(id);
    const parentId = item.parent_id === undefined || item.parent_id === null ? null : num(item.parent_id);
    const parent = parentId === null ? null : nodes.get(parentId);
    if (parent && parentId !== id) parent.children.push(node);
    else roots.push(node);
  });

  const sortDeep = (list) => {
    list.sort((a, b) => {
      const diff = (num(a.sort_order) || 0) - (num(b.sort_order) || 0);
      return diff !== 0 ? diff : num(a.id) - num(b.id);
    });
    list.forEach((node) => sortDeep(node.children));
  };
  sortDeep(roots);
  return roots;
}

/**
 * 深拷贝整棵树。
 * ⚠️ 所有写操作（新增/改名/删除）都先拷贝再改：Tree 组件按引用比较，
 *    原地改会让 React 认为"没变"而不重渲染；而且乐观更新失败时要能整体回滚。
 */
function cloneTree(roots = []) {
  const walk = (list, depth) => {
    if (depth > MAX_WALK_DEPTH) return [];
    return (Array.isArray(list) ? list : []).map((node) => ({
      ...node,
      children: walk(node.children, depth + 1),
    }));
  };
  return walk(roots, 0);
}

/** 扁平化 + 重装（复用 `rebuildTree` 的排序规则：sort_order，再按 id） */
function normalize(roots = []) {
  return rebuildTree(
    flattenTree(cloneTree(roots)).map(({ node, parentId }) => ({
      ...node,
      parent_id: parentId,
      children: [],
    })),
  );
}

/**
 * 新增一个节点到 `parentId` 下（`null` = 顶级）。
 *
 * `node` 由服务端返回（带真 id 与 sort_order）—— 客户端不猜主键。
 * 排序交给 `normalize`：服务端给新节点的是「同级最大 + 10」，所以它自然排在最后。
 */
export function insertNode(roots = [], parentId, node) {
  if (!node || node.id === null || node.id === undefined) return roots;
  const target = parentId === null || parentId === undefined ? null : num(parentId);
  const tree = cloneTree(roots);
  const fresh = { ...node, parent_id: target, children: [] };

  let placed = false;
  if (target === null) {
    tree.push(fresh);
    placed = true;
  } else {
    const walk = (list) => {
      if (placed) return;
      list.forEach((item) => {
        if (placed) return;
        if (num(item.id) === target) {
          item.children.push(fresh);
          placed = true;
          return;
        }
        walk(item.children || []);
      });
    };
    walk(tree);
  }

  return placed ? normalize(tree) : roots; // 父级没找到 → 原样返回，调用方 reload 兜底
}

/** 改名（只动这一个节点，层级与顺序不变） */
export function renameNode(roots = [], id, name) {
  const target = num(id);
  if (!Number.isFinite(target)) return roots;
  const next = String(name === null || name === undefined ? '' : name);
  let changed = false;

  const walk = (list, depth) => {
    if (depth > MAX_WALK_DEPTH) return [];
    return (Array.isArray(list) ? list : []).map((item) => {
      const children = walk(item.children, depth + 1);
      if (num(item.id) === target) {
        changed = true;
        return { ...item, name: next, children };
      }
      return { ...item, children };
    });
  };

  const tree = walk(roots, 0);
  return changed ? tree : roots;
}

/** 删除一个节点（后端已保证"有子级 / 仍被引用"会 409，这里不做级联） */
export function removeNode(roots = [], id) {
  const target = num(id);
  const walk = (list, depth) => {
    if (depth > MAX_WALK_DEPTH) return [];
    return (Array.isArray(list) ? list : [])
      .filter((item) => num(item.id) !== target)
      .map((item) => ({ ...item, children: walk(item.children, depth + 1) }));
  };
  return walk(roots, 0);
}

/** 同级下一个 sort_order（最大 + 10）。发给服务端，让"新节点排最后"两边一致 */
export function nextSortOrder(index, parentId) {
  const target = parentId === null || parentId === undefined ? null : num(parentId);
  const siblings = index.childrenOf.get(target) || [];
  const max = siblings.reduce((acc, id) => {
    const node = index.byId.get(id);
    return Math.max(acc, Number(node && node.sort_order) || 0);
  }, 0);
  return max + 10;
}

/**
 * 节点名称的基本校验（前端先拦一道，后端还有 400 + 库里的 CHECK 兜底）。
 * @returns {string} 空串 = 合法；否则是给人看的错误文案
 */
export function validateCategoryName(name, siblings = [], excludeId = null) {
  const value = String(name === null || name === undefined ? '' : name).trim();
  if (!value) return '分类名称不能为空';
  if (value.length > 100) return '分类名称最多 100 个字';
  const clash = (siblings || []).some(
    (item) => num(item.id) !== num(excludeId) && String(item.name || '').trim() === value,
  );
  if (clash) return '同一上级下已有同名分类';
  return '';
}

/**
 * 拖拽后的**乐观**树：改 parent_id + 把目标父级下的兄弟重排成 10/20/30…
 *
 * 为什么要和上面 `resolveDrop` 分开：落点解析是"用户意图"，重排是"库里的结果"。
 * 这两件事必须产生**完全一致的顺序**，否则松手瞬间会看到节点跳一下、再跳回来。
 * 规则照抄后端 `_move`（`erp_partner_category.py`）：插入 → 1-based × 10。
 *
 * @returns {{roots: Array, changed: boolean}}
 */
export function applyMove(roots, dragId, parentId, beforeId) {
  const index = indexTree(roots);
  const from = num(dragId);
  if (!index.byId.has(from)) return { roots, changed: false };

  const targetParent = parentId === null || parentId === undefined ? null : num(parentId);
  if (targetParent !== null && !index.byId.has(targetParent)) return { roots, changed: false };
  if (targetParent !== null && isDescendant(index, from, targetParent)) {
    return { roots, changed: false };
  }

  // 摊平（用遍历出来的 parent，不用 node.parent_id —— 后者可能是脏的）
  const flat = flattenTree(roots).map(({ node, parentId: pid }) => ({
    ...node,
    parent_id: pid,
    children: [],
  }));

  const moving = flat.find((item) => num(item.id) === from);
  if (!moving) return { roots, changed: false };

  // 目标父级下的兄弟（按当前显示顺序，排除被拖的那个）
  const siblings = flat.filter(
    (item) => (item.parent_id === null ? null : num(item.parent_id)) === targetParent && num(item.id) !== from,
  );

  const at = beforeId === null || beforeId === undefined
    ? siblings.length
    : (() => {
        const found = siblings.findIndex((item) => num(item.id) === num(beforeId));
        return found < 0 ? siblings.length : found;
      })();

  siblings.splice(at, 0, moving);
  moving.parent_id = targetParent;
  siblings.forEach((item, position) => {
    item.sort_order = (position + 1) * 10;
  });

  return { roots: rebuildTree(flat), changed: true };
}

/**
 * 重算 `total`（含子孙的合计）。
 * 拖拽不改变任何一条档案的 `category_id`，所以每个节点的 `count`（直接数）**不会变**，
 * `total` 只是"换个父级后重新加一遍"。不重算的话，拖完你会看到数字还停在旧分支上。
 */
export function recomputeTotals(roots = []) {
  const walk = (list) => {
    (Array.isArray(list) ? list : []).forEach((node) => {
      const children = walk(node.children);
      node.children = children;
      const direct = Number(node.count) || 0;
      node.total = direct + children.reduce((sum, child) => sum + (Number(child.total) || 0), 0);
    });
    return list;
  };
  return walk((roots || []).map((node) => ({ ...node, children: [...(node.children || [])] })));
}

/** 全量展开用的 id 列表（只返回"有子级"的节点，省一半 Set 体积） */
export function expandableIds(roots = []) {
  return flattenTree(roots)
    .filter(({ node }) => Array.isArray(node.children) && node.children.length > 0)
    .map(({ node }) => node.id);
}

/**
 * 初始展开：让树默认能看到**第 `depth` 层（0 基）**，再深的部分等用户点。
 * 即 `depth = 3` → 展开 depth 0/1/2 的父节点 → 行最深可见到 depth 3
 * （集团 → 分公司 → 子公司 → 项目）。深树不这么切一刀，一进页面就是几百行。
 */
export function defaultExpandedIds(roots = [], depth = 3) {
  return flattenTree(roots)
    .filter(({ node, depth: at }) => at < depth && Array.isArray(node.children) && node.children.length > 0)
    .map(({ node }) => node.id);
}
