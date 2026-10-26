/**
 * 菜单树拖拽 —— 纯逻辑层（不依赖 React / dnd-kit，可直接单测）
 *
 * 为什么把这部分单独拆出来：
 *   拖拽最容易出错的不是"拖"这个动作，而是"松手之后树变成什么样、该给后端发什么"。
 *   把它做成纯函数，就能用 Node 直接跑几十个用例覆盖各种边界（拖到自己下级、拖进叶子、
 *   超过深度上限、跨组移动…），而不用靠鼠标一遍遍试 —— 那些用例靠手点是测不全的。
 *
 * 数据结构（与 GET /system/menus 返回的 tree 节点一致）：
 *   { id, parent_id, label, page_key, sort_order, is_enabled, is_builtin,
 *     kind, kind_label, page_label, depth, has_children, note, children: [] }
 */

// ── 缩进：动态计算，不逐层枚举 CSS ─────────────────────────────────────────
// 严格按 paddingLeft = 20 + depth * 16（depth 从 1 起）：
//   depth=1 ⇒ 36px，depth=2 ⇒ 52px，depth=3 ⇒ 68px …
// 前两档正好等于现有 styles.css 的 .nav-depth-1(36px) / .nav-depth-2(52px)，
// 所以这次改动对现有两层菜单的观感是零变化，只对第 3 层起生效。
export const INDENT_BASE = 20;
export const INDENT_STEP = 16;

export function rowIndent(depth) {
  const d = Number.isFinite(depth) && depth > 0 ? depth : 1;
  return INDENT_BASE + d * INDENT_STEP;
}

/** 每组同级节点的序号步长：和播种规则一致（10/20/30…），中间留空档好手工插项。 */
export const ORDER_STEP = 10;

// ── 基础遍历 ──────────────────────────────────────────────────────────────
/** 叶子（菜单项）= 挂了页面的节点；分组 = page_key 为空的容器。 */
export function isLeaf(node) {
  return Boolean(node && node.page_key);
}

/** 深度优先索引整棵树：id → { node, depth, parentId }（depth 从 1 起）。 */
export function indexTree(nodes, depth = 1, parentId = null, out = new Map()) {
  (nodes || []).forEach((node) => {
    out.set(node.id, { node, depth, parentId });
    if ((node.children || []).length > 0) {
      indexTree(node.children, depth + 1, node.id, out);
    }
  });
  return out;
}

/** 某个节点在树里的父 id（顶层为 null）。找不到返回 undefined。 */
export function parentIdOf(tree, id) {
  const hit = indexTree(tree).get(id);
  return hit ? hit.parentId : undefined;
}

/** 节点在树里的层级（从 1 起）。找不到返回 0。 */
export function depthOf(tree, id) {
  const hit = indexTree(tree).get(id);
  return hit ? hit.depth : 0;
}

/** targetId 是不是 ancestorId 的后代（用于挡住"拖到自己下级"）。 */
export function isDescendant(tree, ancestorId, targetId) {
  const hit = indexTree(tree).get(ancestorId);
  if (!hit) return false;
  let found = false;
  (function walk(list) {
    (list || []).forEach((n) => {
      if (n.id === targetId) found = true;
      walk(n.children);
    });
  })(hit.node.children);
  return found;
}

/** 某棵子树自身的高度（只有自己 = 1，带一层子 = 2 …）。用于深度上限校验。 */
export function subtreeHeight(node) {
  const kids = node?.children || [];
  if (kids.length === 0) return 1;
  return 1 + Math.max(...kids.map(subtreeHeight));
}

/**
 * 把树拍平成"当前可见的行"（折叠的分组不展开）。
 * 返回值直接喂给 dnd-kit 的 SortableContext 和渲染循环。
 */
export function flattenVisible(nodes, collapsed = [], depth = 1, parentId = null, out = []) {
  (nodes || []).forEach((node) => {
    const kids = node.children || [];
    const hasChildren = kids.length > 0;
    const isCollapsed = collapsed.includes(node.id);
    out.push({
      id: node.id,
      label: node.label,
      pageKey: node.page_key || '',
      depth,
      parentId,
      sortOrder: node.sort_order,
      isEnabled: node.is_enabled !== false,
      isBuiltin: Boolean(node.is_builtin),
      kind: isLeaf(node) ? 'menu' : 'group',
      hasChildren,
      collapsed: isCollapsed,
      childCount: kids.length,
      note: node.note || '',
    });
    if (hasChildren && !isCollapsed) {
      flattenVisible(kids, collapsed, depth + 1, node.id, out);
    }
  });
  return out;
}

/** 树的浅拷贝（结构化克隆；节点里只有原始值 + children，够用且比 JSON 快）。 */
export function cloneTree(nodes) {
  return (nodes || []).map((n) => ({ ...n, children: cloneTree(n.children) }));
}

/** 移动完后重算每个节点的 depth / has_children，保证与后端返回的形状一致。 */
export function refreshDerived(tree, depth = 1) {
  return (tree || []).map((node) => {
    const children = refreshDerived(node.children || [], depth + 1);
    return {
      ...node,
      depth,
      has_children: children.length > 0,
      children,
    };
  });
}

/** 找节点对象（引用）。 */
export function findNode(tree, id) {
  const hit = indexTree(tree).get(id);
  return hit ? hit.node : null;
}

// ── 拖拽意图：把"鼠标落在哪"翻译成 before / after / inside ──────────────────
/**
 * 三区分法（可预测、好测）：
 *   行的上 30% → before（插到它前面，与它同级）
 *   行的下 30% → after （插到它后面，与它同级）
 *   中间 40% 且目标是分组 → inside（变成它的子节点）
 *
 * ⚠️ 目标是叶子（挂了页面的菜单项）时中间区降级为 after —— 后端明确禁止
 *    "菜单项有下级"（点它是跳页还是展开会含糊），前端就别给出这个假动作。
 */
export const DROP_ZONE_EDGE = 0.3;

export function computeDropIntent({ overRect, pointerY, overIsLeaf }) {
  if (!overRect || !Number.isFinite(pointerY)) return 'after';
  const ratio = (pointerY - overRect.top) / Math.max(1, overRect.height);
  if (ratio < DROP_ZONE_EDGE) return 'before';
  if (ratio > 1 - DROP_ZONE_EDGE) return 'after';
  return overIsLeaf ? 'after' : 'inside';
}

// ── 落点计划：算出新树 + 要给后端发的 items ────────────────────────────────
/**
 * 计算一次 drop 的结果。**纯函数，不改入参。**
 *
 * @returns {{ok: boolean, reason?: string, tree?: Array, items?: Array,
 *            activeId?: number, affectedParents?: Array}}
 *   ok=false 时 reason 是给用户看的中文原因（前端直接弹提示，不必等后端 400）。
 *   items 形如 [{id, parent_id, sort_order}]，已按目标顺序把受影响父级下
 *   **全部**子节点排好号 —— 既满足新端点的契约，也能兼容"后端还没合并"的过渡期
 *   （那种情况下前端自己发的序号就是对的，虽然要发多条 PATCH）。
 */
export function planDrop(tree, { activeId, overId, intent = 'after', maxDepth = 8 }) {
  if (activeId == null || overId == null) return { ok: false, reason: '没有可落下的目标' };
  if (activeId === overId) return { ok: false, reason: '拖回了原位，未做改动', noop: true };

  const index = indexTree(tree);
  const activeHit = index.get(activeId);
  const overHit = index.get(overId);
  if (!activeHit || !overHit) return { ok: false, reason: '找不到被拖动或目标节点' };

  const active = activeHit.node;
  const over = overHit.node;

  // ① 不能拖到自己的下级里（否则成环）
  if (isDescendant(tree, activeId, overId)) {
    return { ok: false, reason: `不能把「${active.label}」拖到它自己的下一级里` };
  }

  // ② 目标父级：inside ⇒ 目标自己；before/after ⇒ 目标的父级
  let targetParentId;
  if (intent === 'inside') {
    targetParentId = overId;
  } else {
    targetParentId = overHit.parentId;
  }

  // ③ 叶子不能当爹：中间区落在叶子上已在 computeDropIntent 里降级，
  //    这里再兜一次（直接调 planDrop 的调用方可能没走那个函数）
  if (intent === 'inside' && isLeaf(over)) {
    return { ok: false, reason: `「${over.label}」是菜单项，不能再往下加一级` };
  }

  const targetDepth =
    targetParentId == null ? 1 : (index.get(targetParentId)?.depth || 1) + 1;

  // ④ 深度上限：被拖子树的最深处也不能超
  const height = subtreeHeight(active);
  const deepest = targetDepth + height - 1;
  if (deepest > maxDepth) {
    return {
      ok: false,
      reason: `最多 ${maxDepth} 层，「${active.label}」放过去会到第 ${deepest} 层`,
    };
  }

  // ── 开始改：深拷贝，避免污染 React state 里的原树 ──
  const next = cloneTree(tree);
  const oldParentId = activeHit.parentId;

  const detached = detach(next, activeId);
  if (!detached) return { ok: false, reason: '内部错误：未能从原位置摘出节点' };

  let inserted = false;
  if (intent === 'inside') {
    const target = findNode(next, overId);
    if (target) {
      target.children = [...(target.children || []), detached.node];
      inserted = true;
    }
  } else {
    const siblings = targetParentId == null ? next : findNode(next, targetParentId)?.children;
    if (siblings) {
      const at = siblings.findIndex((n) => n.id === overId);
      const pos = intent === 'before' ? at : at + 1;
      siblings.splice(pos < 0 ? siblings.length : pos, 0, detached.node);
      inserted = true;
    }
  }
  if (!inserted) return { ok: false, reason: '内部错误：未能插入到目标位置' };

  // ⑤ 受影响的两个父级下的序号重排成 10/20/30…（不留空洞、不重号）
  const affectedParents = dedupeParents([oldParentId, targetParentId]);
  affectedParents.forEach((pid) => renumber(next, pid));

  const items = collectPayload(next, affectedParents);
  return {
    ok: true,
    tree: refreshDerived(next),
    items,
    activeId,
    affectedParents,
  };
}

function dedupeParents(list) {
  const seen = new Set();
  const out = [];
  list.forEach((p) => {
    const key = p == null ? '__root__' : String(p);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(p == null ? null : p);
    }
  });
  return out;
}

/** 从树里摘下某节点。找不到返回 null。 */
function detach(tree, id) {
  // ⚠️ 栈里放的是"数组"（每一个 children 列表），不是节点 ——
  // 早先写成 `[...tree]` 把顶层节点铺进栈，循环里 list.findIndex 直接崩。
  const stack = [tree];
  while (stack.length) {
    const list = stack.pop();
    const at = list.findIndex((n) => n.id === id);
    if (at >= 0) {
      const [node] = list.splice(at, 1);
      return { node };
    }
    list.forEach((n) => {
      if ((n.children || []).length > 0) stack.push(n.children);
    });
  }
  return null;
}

/** 把某个父级下的子节点按当前顺序重排为 10/20/30… */
function renumber(tree, parentId) {
  const siblings = parentId == null ? tree : findNode(tree, parentId)?.children;
  if (!siblings) return;
  siblings.forEach((node, i) => {
    node.sort_order = (i + 1) * ORDER_STEP;
  });
}

/**
 * 生成后端要的 items：只包含"受影响父级下的全部子节点"。
 * 一次 drop 影响两个父级（旧位置、新位置），所以最多两批。
 */
export function collectPayload(tree, affectedParents) {
  const items = [];
  affectedParents.forEach((pid) => {
    const siblings = pid == null ? tree : findNode(tree, pid)?.children || [];
    siblings.forEach((node, i) => {
      items.push({
        id: node.id,
        parent_id: pid,
        sort_order: (i + 1) * ORDER_STEP,
      });
    });
  });
  return items;
}

// ── 键盘/按钮操作用的辅助（移动端拖拽不友好，留一条可点的路）───────────────
/**
 * 把节点上移/下移一位（同级内）。返回 planDrop 同构的结果。
 * 「上移」= 与它前一个兄弟交换 ⇒ 等价于拖到前一个兄弟的 before 位置。
 */
export function planShift(tree, { activeId, delta, maxDepth = 8 }) {
  const index = indexTree(tree);
  const hit = index.get(activeId);
  if (!hit) return { ok: false, reason: '找不到节点' };
  const siblings =
    hit.parentId == null ? tree : findNode(tree, hit.parentId)?.children || [];
  const at = siblings.findIndex((n) => n.id === activeId);
  const to = at + delta;
  if (to < 0 || to >= siblings.length) {
    return { ok: false, reason: delta < 0 ? '已经在最前面了' : '已经在最后面了', noop: true };
  }
  const over = siblings[to];
  return planDrop(tree, {
    activeId,
    overId: over.id,
    intent: delta < 0 ? 'before' : 'after',
    maxDepth,
  });
}

/**
 * 缩进一级：变成"前一个兄弟"的最后一个子节点。
 * 没有前一个兄弟 / 前一个兄弟是叶子 / 超深 ⇒ 拒绝并说明原因。
 */
export function planIndent(tree, { activeId, maxDepth = 8 }) {
  const index = indexTree(tree);
  const hit = index.get(activeId);
  if (!hit) return { ok: false, reason: '找不到节点' };
  const siblings =
    hit.parentId == null ? tree : findNode(tree, hit.parentId)?.children || [];
  const at = siblings.findIndex((n) => n.id === activeId);
  if (at <= 0) return { ok: false, reason: '上面没有同级节点，缩进不了' };
  const prev = siblings[at - 1];
  if (isLeaf(prev)) {
    return { ok: false, reason: `「${prev.label}」是菜单项，不能当上级` };
  }
  return planDrop(tree, { activeId, overId: prev.id, intent: 'inside', maxDepth });
}

/** 取消缩进一级：挂到"当前父级的父级"里，位置紧跟当前父级之后。 */
export function planOutdent(tree, { activeId, maxDepth = 8 }) {
  const index = indexTree(tree);
  const hit = index.get(activeId);
  if (!hit) return { ok: false, reason: '找不到节点' };
  if (hit.parentId == null) return { ok: false, reason: '已经在最外层了', noop: true };
  const grandId = index.get(hit.parentId)?.parentId ?? null;
  return planDrop(tree, { activeId, overId: hit.parentId, intent: 'after', maxDepth });
}

// ── 展示辅助 ──────────────────────────────────────────────────────────────
/** 缩进路径（用于 tooltip / 面包屑）。 */
export function pathLabels(tree, id) {
  const out = [];
  (function walk(list, trail) {
    list.forEach((n) => {
      const next = [...trail, n.label];
      if (n.id === id) out.push(...next);
      walk(n.children || [], next);
    });
  })(tree, []);
  return out;
}

/** 树里一共有多少个节点（用于顶部统计）。 */
export function countNodes(nodes) {
  return (nodes || []).reduce((sum, n) => sum + 1 + countNodes(n.children), 0);
}

/** 最大深度（从 1 起）。 */
export function treeDepth(nodes) {
  if (!nodes || nodes.length === 0) return 0;
  return 1 + Math.max(...nodes.map((n) => treeDepth(n.children)));
}

/**
 * 每次改动后的本地校验：拖拽只在内存里改，保存前先自己查一遍。
 * 与后端 _validate_menu_moves 的规则对齐（环 / 叶子当爹 / 深度 / 同层重名）。
 */
export function auditTree(tree, { maxDepth = 8 } = {}) {
  const problems = [];
  const walk = (list, depth, parentLabel) => {
    const seenNames = new Map();
    list.forEach((node) => {
      if (depth > maxDepth) {
        problems.push(`「${node.label}」在第 ${depth} 层，超过上限 ${maxDepth}`);
      }
      const name = String(node.label || '').trim();
      if (seenNames.has(name)) {
        problems.push(`「${parentLabel || '顶层'}」下有重名菜单「${name}」`);
      }
      seenNames.set(name, true);
      if ((node.children || []).length > 0 && isLeaf(node)) {
        problems.push(`「${node.label}」是菜单项，却带着 ${node.children.length} 个子节点`);
      }
      walk(node.children || [], depth + 1, node.label);
    });
  };
  walk(tree, 1, null);
  return problems;
}
