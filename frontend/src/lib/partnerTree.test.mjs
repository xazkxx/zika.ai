/**
 * partnerTree 单测 —— `node --test frontend/src/lib/partnerTree.test.mjs`
 *
 * 夹具是一棵**真实的集团架构**（用户给的原话）：
 *   集团客户 → 分公司 → 子公司 → 项目 → 子项目 → 班组（6 层）
 * 深级拖拽和搜索定位这两个重点，必须在这棵树上验，两级扁平的假数据验不出问题。
 *
 *   id  name          parent  depth  count
 *    1  集团客户        -        0      0
 *    2  华北分公司      1        1      0
 *    3  子公司甲        2        2      0
 *    4  项目A           3        3      2
 *    5  子项目A1        4        4      0
 *    6  班组a           5        5      1
 *    7  子公司乙        2        2      1
 *    8  项目C           7        3      3
 *    9  华东分公司      1        1      0
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  UNCLASSIFIED,
  INDENT_PX,
  MAX_INDENT_DEPTH,
  indexTree,
  flattenTree,
  ancestorsOf,
  isDescendant,
  subtreeIds,
  pathLabel,
  rowInCategory,
  searchNodes,
  matchPartnerLeaves,
  buildVisibleRows,
  indentOf,
  dropZoneFromRatio,
  nextSiblingId,
  resolveDrop,
  applyMove,
  rebuildTree,
  recomputeTotals,
  expandableIds,
  defaultExpandedIds,
  insertNode,
  renameNode,
  removeNode,
  nextSortOrder,
  validateCategoryName,
  normalizeSelection,
  batchMovePlan,
} from './partnerTree.js';

/** 每次拿到的都是新对象，避免某个用例改了树污染下一个 */
function fixture() {
  const node = (id, name, count, children = []) => ({
    id,
    name,
    parent_id: null,
    sort_order: 10,
    count,
    total: count,
    children,
  });
  const tree = [
    node(1, '集团客户', 0, [
      node(2, '华北分公司', 0, [
        node(3, '子公司甲', 0, [
          node(4, '项目A', 2, [node(5, '子项目A1', 0, [node(6, '班组a', 1)])]),
        ]),
        node(7, '子公司乙', 1, [node(8, '项目C', 3)]),
      ]),
      node(9, '华东分公司', 0),
    ]),
  ];
  // parent_id / total 交给下面统一补，避免手写夹具时写错
  const stamp = (list, parentId) => {
    list.forEach((item, position) => {
      item.parent_id = parentId;
      item.sort_order = (position + 1) * 10;
      stamp(item.children, item.id);
    });
  };
  stamp(tree, null);
  return recomputeTotals(tree);
}

// ═══════════════════════════════════════════════════════════ 索引 / 路径

test('indexTree：6 层树的 parent / depth / 先序都对', () => {
  const index = indexTree(fixture());
  assert.equal(index.byId.size, 9);
  assert.deepEqual(index.preorder, [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.equal(index.depthOf.get(1), 0);
  assert.equal(index.depthOf.get(6), 5, '班组a 在第 6 层（depth 5）');
  assert.equal(index.parentOf.get(8), 7);
  assert.equal(index.parentOf.get(1), null);
  assert.deepEqual(index.childrenOf.get(2), [3, 7]);
});

test('indexTree：脏数据（重复 id、自环）不会死循环', () => {
  const bad = [{ id: 1, name: 'a', children: [{ id: 1, name: 'a-again', children: [] }] }];
  const index = indexTree(bad);
  assert.equal(index.byId.size, 1);
  assert.equal(index.byId.get(1).name, 'a', '先到的赢，重复 id 被丢弃');

  const cyclic = [{ id: 1, name: 'x', children: [] }];
  cyclic[0].children.push(cyclic[0]);
  assert.doesNotThrow(() => indexTree(cyclic));
});

test('flattenTree：先序 + 深度', () => {
  const rows = flattenTree(fixture());
  assert.equal(rows.length, 9);
  assert.deepEqual(
    rows.map((row) => row.node.id),
    [1, 2, 3, 4, 5, 6, 7, 8, 9],
  );
  assert.equal(rows.find((row) => row.node.id === 6).depth, 5);
});

test('ancestorsOf：从根到父，不含自己', () => {
  const index = indexTree(fixture());
  assert.deepEqual(ancestorsOf(index, 6), [1, 2, 3, 4, 5]);
  assert.deepEqual(ancestorsOf(index, 1), []);
  assert.deepEqual(ancestorsOf(index, 999), []);
});

test('isDescendant：自己算，兄弟不算，跨分支不算', () => {
  const index = indexTree(fixture());
  assert.equal(isDescendant(index, 3, 3), true, '自己算自己的后代（拖拽判断因此要额外查 ===）');
  assert.equal(isDescendant(index, 3, 6), true);
  assert.equal(isDescendant(index, 3, 7), false);
  assert.equal(isDescendant(index, 4, 3), false, '方向必须是"目标在后代里"');
  assert.equal(isDescendant(index, null, 6), false);
});

test('subtreeIds：含自己与全部子孙', () => {
  const index = indexTree(fixture());
  assert.deepEqual([...subtreeIds(index, 3)].sort((a, b) => a - b), [3, 4, 5, 6]);
  assert.deepEqual([...subtreeIds(index, 8)], [8]);
});

test('pathLabel：全路径 / 未知 id → 空串', () => {
  const index = indexTree(fixture());
  assert.equal(pathLabel(index, 6), '集团客户 / 华北分公司 / 子公司甲 / 项目A / 子项目A1 / 班组a');
  assert.equal(pathLabel(index, null), '');
  assert.equal(pathLabel(index, 999), '');
});

test('rowInCategory：选中父级包含子孙；未分类是独立一档', () => {
  const index = indexTree(fixture());
  assert.equal(rowInCategory({ category_id: 6 }, index, 3), true, '选中子公司甲 → 深处班组的档案也算');
  assert.equal(rowInCategory({ category_id: 8 }, index, 3), false, '另一个分支的不算');
  assert.equal(rowInCategory({ category_id: null }, index, 3), false);
  assert.equal(rowInCategory({ category_id: null }, index, UNCLASSIFIED), true);
  assert.equal(rowInCategory({ category_id: 8 }, index, UNCLASSIFIED), false);
  assert.equal(rowInCategory({ category_id: 8 }, index, null), true, '不选 = 全部');
});

// ═══════════════════════════════════════════════════════════ 可见行 / 折叠

test('buildVisibleRows：默认只展开到指定层，深层默认不渲染', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const expanded = defaultExpandedIds(roots, 3); // depth ≤ 3 的父节点

  const { rows } = buildVisibleRows(roots, index, { expanded });
  assert.deepEqual(
    rows.map((row) => row.id),
    [1, 2, 3, 4, 7, 8, 9],
    '班组a(6) 与 子项目A1(5) 在 depth 4/5，不在初始展开范围',
  );
  assert.equal(rows.find((row) => row.id === 4).hasChildren, true);
  assert.equal(rows.find((row) => row.id === 4).isOpen, false, '项目A 有子级但没展开');
  assert.equal(rows.find((row) => row.id === 8).hasChildren, false, '项目C 是叶子');
});

test('buildVisibleRows：展开 5 之后 6 才出现（深级逐层）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const expanded = new Set([...defaultExpandedIds(roots, 3), 4, 5]);
  const { rows } = buildVisibleRows(roots, index, { expanded });
  assert.deepEqual(
    rows.map((row) => row.id),
    [1, 2, 3, 4, 5, 6, 7, 8, 9],
  );
  assert.equal(rows.find((row) => row.id === 6).depth, 5);
});

test('indentOf：每级 14px，且 10 层封顶（不封顶会把标签挤成一条缝）', () => {
  assert.equal(INDENT_PX, 14);
  assert.equal(indentOf(0), 8);
  assert.equal(indentOf(1), 22);
  assert.equal(indentOf(4), 64);
  assert.equal(indentOf(MAX_INDENT_DEPTH + 6), 8 + MAX_INDENT_DEPTH * 14, '超过 10 层不再缩进');
});

// ═══════════════════════════════════════════════════════════ 搜索

test('searchNodes：命中叶子 → 祖先全被记下，顺序是先序', () => {
  const found = searchNodes(fixture(), '班组');
  assert.deepEqual([...found.matched], [6]);
  assert.deepEqual([...found.ancestors].sort((a, b) => a - b), [1, 2, 3, 4, 5]);
  assert.deepEqual(found.order, [6]);
});

test('searchNodes：大小写/空白不敏感；无关键词与无命中都返回空', () => {
  // ⚠️ 子串语义：搜「项目A」会把「子项目A1」一起捞出来（"子项目a1".includes("项目a") 为真）。
  //    这是**故意的** —— 用户敲三个字就该看到所有含这三个字的节点，而不是要求全等。
  assert.deepEqual(searchNodes(fixture(), '  项目A  ').order, [4, 5]);
  assert.deepEqual(searchNodes(fixture(), '项目C').order, [8]);
  assert.equal(searchNodes(fixture(), '   ').matched.size, 0);
  assert.equal(searchNodes(fixture(), '不存在的名字').matched.size, 0);
  assert.equal(searchNodes(fixture(), '不存在的名字').ancestors.size, 0);
});

test('searchNodes：多个命中按先序（父在前），回车跳"下一个"才不会乱', () => {
  const found = searchNodes(fixture(), '项目');
  assert.deepEqual(found.order, [4, 5, 8], '项目A → 子项目A1 → 项目C');
});

test('buildVisibleRows：搜索时只留命中 + 祖先，且祖先**强制展开**', () => {
  const roots = fixture();
  const index = indexTree(roots);
  // 用户之前的折叠状态：全部收起（连根都没展开）
  const { rows, hitIds } = buildVisibleRows(roots, index, { expanded: [], query: '班组' });

  assert.deepEqual(
    rows.map((row) => row.id),
    [1, 2, 3, 4, 5, 6],
    '搜到深处班组，必须把它的 5 层祖先全铺出来',
  );
  assert.deepEqual(hitIds, [6]);
  assert.equal(rows.filter((row) => row.isMatched).length, 1);
  assert.equal(rows.find((row) => row.id === 6).isMatched, true);
  assert.equal(rows.find((row) => row.id === 2).isMatched, false);
});

test('buildVisibleRows：清空搜索后回到用户原来的折叠状态（搜索不改 expanded）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const expanded = []; // 用户全收起
  const during = buildVisibleRows(roots, index, { expanded, query: '班组' });
  assert.ok(during.rows.length > 1);

  const after = buildVisibleRows(roots, index, { expanded: during.rows.length ? expanded : [], query: '' });
  assert.deepEqual(after.rows.map((row) => row.id), [1]);
  assert.deepEqual(expanded, [], '搜索期间绝不能偷偷往 expanded 里塞东西');
});

test('buildVisibleRows：无命中时树是空的（而不是退回显示全部）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const { rows, searching } = buildVisibleRows(roots, index, { expanded: expandableIds(roots), query: 'zzz' });
  assert.deepEqual(rows, []);
  assert.equal(searching, true);
});

// ── focusOnly：搜索时"一次只摊开一条路径"（2026-10-19 新增交互） ──
//
// 旧行为把所有命中项的祖先链同时铺开，搜一个常用字就摊开十几条链，
// 用户原话"非常难以识别"。新交互：树里只显示**当前定位的那一条**链路，
// 其余命中靠"找到 N 个 ↑↓"逐个抵达。
test('buildVisibleRows：focusOnly 只铺当前命中的那条链（第一条）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const { rows, hitIds } = buildVisibleRows(roots, index, {
    expanded: [],
    query: '项目',
    focusOnly: true,
    focusIndex: 0,
  });

  // '项目' 命中 4(项目A) / 5(子项目A1) / 8(项目C)，先序
  assert.deepEqual(hitIds, [4, 5, 8], '命中集合不能因为 focusOnly 而缩水，↑↓ 还要能跳');
  assert.deepEqual(rows.map((row) => row.id), [1, 2, 3, 4], '只铺 项目A 这条链，别的命中不摊开');
  assert.equal(rows.find((row) => row.id === 4).isOpen, false, '命中项自己不展开 —— 否则又一次"全摊开"');
});

test('buildVisibleRows：focusOnly 换一个 focusIndex 就换成另一条链', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const third = buildVisibleRows(roots, index, {
    expanded: [],
    query: '项目',
    focusOnly: true,
    focusIndex: 2,
  });
  assert.deepEqual(third.rows.map((row) => row.id), [1, 2, 7, 8], '第 3 个命中是 项目C，链走 子公司乙');
});

test('buildVisibleRows：focusIndex 越界不会崩，回落到最后一个命中', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const { rows } = buildVisibleRows(roots, index, {
    expanded: [],
    query: '项目',
    focusOnly: true,
    focusIndex: 99,
  });
  assert.deepEqual(rows.map((row) => row.id), [1, 2, 7, 8]);
});

test('buildVisibleRows：focusOnly 不传 focusIndex 时 = 第一个命中（打字瞬间就该看到东西）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const { rows } = buildVisibleRows(roots, index, { expanded: [], query: '项目', focusOnly: true });
  assert.deepEqual(rows.map((row) => row.id), [1, 2, 3, 4]);
});

// ═══════════════════════════════════════════════════════════ 拖拽落点

test('dropZoneFromRatio：上下 28% 是"插到前后"，中间是"放进去"', () => {
  assert.equal(dropZoneFromRatio(0), 'before');
  assert.equal(dropZoneFromRatio(0.27), 'before');
  assert.equal(dropZoneFromRatio(0.28), 'inside');
  assert.equal(dropZoneFromRatio(0.5), 'inside');
  assert.equal(dropZoneFromRatio(0.72), 'inside');
  assert.equal(dropZoneFromRatio(0.73), 'after');
  assert.equal(dropZoneFromRatio(1), 'after');
  assert.equal(dropZoneFromRatio(NaN), 'inside', '量不到高度时按"放进去"，比拒绝拖拽好');
});

test('nextSiblingId：最后一个兄弟返回 null', () => {
  const index = indexTree(fixture());
  assert.equal(nextSiblingId(index, 3), 7);
  assert.equal(nextSiblingId(index, 7), null);
  assert.equal(nextSiblingId(index, 1), null);
});

test('resolveDrop：inside / before / after 三种落点换算', () => {
  const index = indexTree(fixture());
  // 把 项目C(8) 放进 子公司甲(3)
  assert.deepEqual(resolveDrop(index, 8, 3, 'inside'), { parentId: 3, beforeId: null });
  // 插到 子公司乙(7) 前面 → 父级是 7 的父级(华北 2)
  assert.deepEqual(resolveDrop(index, 8, 7, 'before'), { parentId: 2, beforeId: 7 });
  // 插到 子公司甲(3) 后面 → 父级 2，落点 = 3 的下一个兄弟 7
  assert.deepEqual(resolveDrop(index, 8, 3, 'after'), { parentId: 2, beforeId: 7 });
  // 插到 子公司乙(7) 后面 → 它是最后一个兄弟，beforeId = null（排最后）
  assert.deepEqual(resolveDrop(index, 8, 7, 'after'), { parentId: 2, beforeId: null });
});

test('resolveDrop：拖进自己的后代 → null（否则库内成环、节点在树上消失）', () => {
  const index = indexTree(fixture());
  assert.equal(resolveDrop(index, 3, 6, 'inside'), null, '子公司甲 拖进 班组a');
  assert.equal(resolveDrop(index, 3, 4, 'after'), null, '子公司甲 拖到自己孙子的后面');
  assert.equal(resolveDrop(index, 4, 4, 'inside'), null, '拖到自己身上');
  assert.equal(resolveDrop(index, null, 4, 'inside'), null);
  assert.equal(resolveDrop(index, 999, 4, 'inside'), null, '被拖的节点已不在树里');
});

// ═══════════════════════════════════════════════════════════ 乐观移动

test('applyMove：跨级拖拽后 parent / 顺序 / total 全对', () => {
  const roots = fixture();
  const snapshot = JSON.stringify(roots);

  const { roots: moved, changed } = applyMove(roots, 4, 7, null); // 项目A → 子公司乙 末尾
  assert.equal(changed, true);
  assert.equal(JSON.stringify(roots), snapshot, '入参必须原样不动（失败时要能整体回滚）');

  const index = indexTree(moved);
  assert.equal(index.parentOf.get(4), 7);
  assert.deepEqual(index.childrenOf.get(7), [8, 4], '项目C(10) 在前，项目A 排到 20');
  assert.equal(index.byId.get(4).sort_order, 20);
  assert.deepEqual(index.childrenOf.get(3), [], '子公司甲 下面的项目A 已被移走');

  const totals = indexTree(recomputeTotals(moved));
  assert.equal(totals.byId.get(7).total, 7, '子公司乙 = 直接 1 + 项目C 3 + 项目A 3（自身 2 + 班组a 1）');
  assert.equal(totals.byId.get(3).total, 0);
  assert.equal(totals.byId.get(1).total, 7, '根节点总数不变（只是换了分支）');
});

test('applyMove：插到指定兄弟前面（beforeId 生效）', () => {
  const roots = fixture();
  const { roots: moved } = applyMove(roots, 8, 2, 3); // 项目C 插到 子公司甲 前面
  const index = indexTree(moved);
  assert.deepEqual(index.childrenOf.get(2), [8, 3, 7], '顺序必须是 项目C → 子公司甲 → 子公司乙');
  assert.equal(index.byId.get(8).sort_order, 10);
  assert.equal(index.byId.get(3).sort_order, 20);
  assert.equal(index.byId.get(7).sort_order, 30);
});

test('applyMove：移到顶级（parentId = null）', () => {
  const roots = fixture();
  const { roots: moved } = applyMove(roots, 8, null, 1); // 项目C 提到顶级、排在集团客户前面
  const index = indexTree(moved);
  assert.equal(index.parentOf.get(8), null);
  assert.deepEqual(index.childrenOf.get(null), [8, 1]);
  assert.deepEqual(index.childrenOf.get(7), [], '子公司乙 下面空了');
});

test('applyMove：非法拖拽（进自己的后代）→ changed=false，树一模一样', () => {
  const roots = fixture();
  const before = JSON.stringify(roots);
  const { roots: after, changed } = applyMove(roots, 3, 6, null);
  assert.equal(changed, false);
  assert.equal(JSON.stringify(after), before);
});

test('rebuildTree：兄弟按 sort_order 排，同号按 id 兜底', () => {
  const flat = [
    { id: 3, name: 'c', parent_id: null, sort_order: 10 },
    { id: 1, name: 'a', parent_id: null, sort_order: 10 },
    { id: 2, name: 'b', parent_id: 1, sort_order: 10 },
  ];
  const roots = rebuildTree(flat);
  assert.deepEqual(roots.map((node) => node.id), [1, 3]);
  assert.deepEqual(roots[0].children.map((node) => node.id), [2]);
});

test('recomputeTotals：后序累加，不改入参', () => {
  const roots = fixture();
  const before = JSON.stringify(roots);
  const next = recomputeTotals(roots);
  assert.equal(JSON.stringify(roots), before);
  const index = indexTree(next);
  assert.equal(index.byId.get(4).total, 3, '项目A = 直接 2 + 班组a 1');
  assert.equal(index.byId.get(2).total, 7, '华北 = 子公司甲 3 + 子公司乙 4');
  assert.equal(index.byId.get(1).total, 7);
});

// ═══════════════════════════════════════════════════════════ 建类（增 / 改 / 删）

test('insertNode：加到指定父级下，按 sort_order 排到最后', () => {
  const roots = fixture();
  const before = JSON.stringify(roots);

  const next = insertNode(roots, 3, { id: 100, name: '项目D', count: 0, total: 0, sort_order: 20 });
  assert.equal(JSON.stringify(roots), before, '入参不能被改');

  const index = indexTree(next);
  assert.equal(index.parentOf.get(100), 3);
  assert.deepEqual(index.childrenOf.get(3), [4, 100], '项目A(10) 在前，新节点(20) 在后');
  assert.equal(pathLabel(index, 100), '集团客户 / 华北分公司 / 子公司甲 / 项目D');
});

test('insertNode：parentId = null 时加到顶级末尾', () => {
  const next = insertNode(fixture(), null, { id: 200, name: '新集团', sort_order: 20 });
  const index = indexTree(next);
  assert.equal(index.parentOf.get(200), null);
  assert.deepEqual(index.childrenOf.get(null), [1, 200]);
});

test('insertNode：父级不存在（并发删除）→ 原样返回，不炸', () => {
  const roots = fixture();
  assert.equal(insertNode(roots, 999, { id: 300, name: 'x' }), roots);
});

test('renameNode：只改目标节点，层级与兄弟不变', () => {
  const roots = fixture();
  const next = renameNode(roots, 4, '项目A（改名）');
  const index = indexTree(next);
  assert.equal(index.byId.get(4).name, '项目A（改名）');
  assert.equal(index.parentOf.get(5), 4, '子级仍然挂在它下面');
  assert.equal(index.byId.get(3).name, '子公司甲', '别的节点没被动');
  assert.equal(renameNode(roots, 999, 'x'), roots, 'id 不存在 → 原样返回');
});

test('removeNode：连子树一起摘掉、兄弟保持完整', () => {
  const roots = fixture();
  const next = removeNode(roots, 4); // 项目A 带 子项目A1 → 班组a
  const index = indexTree(next);
  assert.equal(index.byId.has(4), false);
  assert.equal(index.byId.has(6), false, '孙级也跟着没了（整棵子树）');
  assert.deepEqual(index.childrenOf.get(3), [], '子公司甲 下面空了');
  assert.equal(index.byId.get(7).name, '子公司乙', '兄弟节点不受影响');
});

test('nextSortOrder：取同级最大值 + 10', () => {
  const index = indexTree(fixture());
  assert.equal(nextSortOrder(index, null), 20, '顶级只有 集团客户(10)');
  assert.equal(nextSortOrder(index, 2), 30, '华北下 子公司甲(10)/子公司乙(20)');
  assert.equal(nextSortOrder(index, 3), 20);
  assert.equal(nextSortOrder(index, 8), 10, '叶子下面建第一个子级');
});

test('validateCategoryName：空 / 全空格 / 超长 / 同级重名', () => {
  assert.equal(validateCategoryName('', []), '分类名称不能为空');
  assert.equal(validateCategoryName('   ', []), '分类名称不能为空');
  assert.equal(validateCategoryName('x'.repeat(101), []), '分类名称最多 100 个字');
  const siblings = [{ id: 1, name: '项目A' }];
  assert.equal(validateCategoryName('项目A', siblings), '同一上级下已有同名分类');
  assert.equal(validateCategoryName(' 项目A ', siblings), '同一上级下已有同名分类', '前后空格不算新名字');
  assert.equal(validateCategoryName('项目A', siblings, 1), '', '改回自己原来的名字是合法的');
  assert.equal(validateCategoryName('项目B', siblings), '');
});

// ═══════════════════════════════════════════════════════════ 多选 / 批量移动（2A）

test('normalizeSelection：没有父子关系时全部保留', () => {
  const index = indexTree(fixture());
  const result = normalizeSelection(index, [3, 9]);
  assert.deepEqual(result.kept, [3, 9]);
  assert.deepEqual(result.covered, []);
  assert.deepEqual(result.ignored, []);
});

test('normalizeSelection：父子同选只留父节点，子节点记进 covered', () => {
  const index = indexTree(fixture());
  const result = normalizeSelection(index, [2, 3]);
  assert.deepEqual(result.kept, [2], '父节点在选区里 → 子节点不需要单独移动');
  assert.deepEqual(result.covered, [3]);
});

test('normalizeSelection：祖孙三代同选只留最上面那个', () => {
  const index = indexTree(fixture());
  const result = normalizeSelection(index, [2, 3, 4, 5]);
  assert.deepEqual(result.kept, [2]);
  assert.deepEqual(result.covered, [3, 4, 5], '整条链都只跟着 2 走');
});

test('normalizeSelection：结论与输入顺序无关', () => {
  const index = indexTree(fixture());
  const a = normalizeSelection(index, [2, 3]);
  const b = normalizeSelection(index, [3, 2]);
  assert.deepEqual(a, b, '先点子再点父，结果必须一样');
});

test('normalizeSelection：兄弟同选互不影响', () => {
  const index = indexTree(fixture());
  const result = normalizeSelection(index, [3, 7]);
  assert.deepEqual(result.kept, [3, 7], '同一个爹的两个子节点都要单独移动');
  assert.deepEqual(result.covered, []);
});

test('normalizeSelection：保持传入顺序（批量移动的落地顺序就是它）', () => {
  const index = indexTree(fixture());
  assert.deepEqual(normalizeSelection(index, [9, 3, 7]).kept, [9, 3, 7]);
});

test('normalizeSelection：重复选中与 Set 输入', () => {
  const index = indexTree(fixture());
  assert.deepEqual(normalizeSelection(index, [3, 3, 9, 3]).kept, [3, 9]);
  assert.deepEqual(normalizeSelection(index, new Set([9, 3])).kept, [9, 3], 'Set 也要保持顺序');
});

test('normalizeSelection：树上没有的 id 进 ignored，不报错', () => {
  const index = indexTree(fixture());
  const result = normalizeSelection(index, [3, 999]);
  assert.deepEqual(result.kept, [3]);
  assert.deepEqual(result.ignored, [999], '并发删掉的节点不该让整批失败');
});

test('normalizeSelection：空输入 / 脏值不会变成 id 0', () => {
  const index = indexTree(fixture());
  assert.deepEqual(normalizeSelection(index, []), { kept: [], covered: [], ignored: [] });
  assert.deepEqual(normalizeSelection(index, null), { kept: [], covered: [], ignored: [] });
  // Number(null) === 0 —— 这是真实踩过的坑：脏值必须被挡掉，不能变成合法的 id 0
  assert.deepEqual(normalizeSelection(index, [null, undefined, '', 'abc']).ignored, []);
});

test('batchMovePlan：合法批量移动 → 只发 kept，beforeId 由调用方固定为 null', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3, 7], 9);
  assert.equal(plan.ok, true);
  assert.equal(plan.code, 'ok');
  assert.deepEqual(plan.ids, [3, 7]);
  assert.deepEqual(plan.covered, []);
});

test('batchMovePlan：父子同选 + 移入新父级 → 只移动父级一次', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [2, 3], 9);
  assert.equal(plan.ok, true);
  assert.deepEqual(plan.ids, [2], '子节点跟着父节点走');
  assert.deepEqual(plan.covered, [3]);
});

test('batchMovePlan：目标是选中项自己 → self', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3], 3);
  assert.equal(plan.ok, false);
  assert.equal(plan.code, 'self');
});

test('batchMovePlan：目标是某个选中项的后代 → cycle，并指出是谁', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [2, 9], 4); // 4 是 2 的曾孙
  assert.equal(plan.ok, false);
  assert.equal(plan.code, 'cycle');
  assert.equal(plan.blockedBy, 2);
  assert.deepEqual(plan.ids, [2, 9], '拒绝时也要把 ids 带回来，UI 才知道该给谁标红');
});

test('batchMovePlan：目标已被删掉 → missing', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3], 999);
  assert.equal(plan.ok, false);
  assert.equal(plan.code, 'missing');
});

test('batchMovePlan：全都已经在目标父级下 → noop（一个请求都不发）', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3, 7], 2); // 3 和 7 的爹就是 2
  assert.equal(plan.ok, false);
  assert.equal(plan.code, 'noop');
  assert.deepEqual(plan.ids, []);
  assert.deepEqual(plan.alreadyThere, [3, 7]);
});

test('batchMovePlan：部分已在目标下 → 只移动其余（已在那的不许重排到末尾）', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3, 9], 2);
  assert.equal(plan.ok, true);
  assert.deepEqual(plan.ids, [9], '3 已经在 2 下面，再发一次 move 会把它挪到末尾');
  assert.deepEqual(plan.alreadyThere, [3]);
});

test('batchMovePlan：移到顶级（targetId = null）', () => {
  const index = indexTree(fixture());
  const plan = batchMovePlan(index, [3, 4], null);
  assert.equal(plan.ok, true);
  assert.deepEqual(plan.ids, [3], '4 被 3 覆盖');
  assert.deepEqual(plan.covered, [4]);
});

test('batchMovePlan：全被父级覆盖（只选了一个孤儿子节点组）与空选择的区别', () => {
  const index = indexTree(fixture());
  // 只选 3：kept 非空，能移动
  assert.equal(batchMovePlan(index, [3], 9).code, 'ok');
  // 选中项全不在树上 → empty
  const gone = batchMovePlan(index, [888, 999], 9);
  assert.equal(gone.code, 'empty');
  assert.deepEqual(gone.ignored, [888, 999]);
  // 真的什么都没选 → empty
  assert.equal(batchMovePlan(index, [], 9).code, 'empty');
});


// ---------------------------------------------------------------------------
// 档案级搜索（2026-10-23）：客户/供应商是挂在分类下的另一份数据
// ---------------------------------------------------------------------------
const leaves = () => ({
  4: [
    { id: 901, name: '西安明珠电力安装工程有限公司', contact: '周广平', code: 'CUS001' },
    { id: 902, name: '蒲白750千伏输变电工程', contact: '黄校文', code: 'CUS002' },
  ],
  8: [{ id: 903, name: '陕西送变电第一分公司', contact: '闫文刚', code: 'CUS003' }],
  9: [{ id: 904, name: '华东区域临时客户', contact: '周广平', code: 'CUS004' }],
});

test('matchPartnerLeaves：按联系人也能命中（用户口径：搜"周广平"）', () => {
  const found = matchPartnerLeaves(leaves(), '周广平');
  assert.deepEqual(found.hitIds.sort(), [4, 9]);
  assert.deepEqual(found.byCategory.get('4').map((row) => row.id), [901]);
  assert.deepEqual(found.byCategory.get('9').map((row) => row.id), [904]);
});

test('matchPartnerLeaves：名称 / 编码 / 大小写 / 空白都认；无关键词返回空', () => {
  assert.deepEqual(matchPartnerLeaves(leaves(), '明珠').byCategory.get('4').length, 1);
  assert.deepEqual(matchPartnerLeaves(leaves(), 'cus003').hitIds, [8]);
  assert.equal(matchPartnerLeaves(leaves(), '   ').hitIds.length, 0);
  assert.equal(matchPartnerLeaves(leaves(), '不存在的档案').hitIds.length, 0);
});

// ── 拼音首字母（2026-10-23）：zgp → 周广平 ──────────────────────────────
test('matchPartnerLeaves：拼音首字母也能命中联系人（搜 "zgp" = 周广平）', () => {
  const found = matchPartnerLeaves(leaves(), 'zgp');
  assert.deepEqual(found.hitIds.sort(), [4, 9]);
  assert.deepEqual(found.byCategory.get('4').map((row) => row.id), [901]);
  assert.deepEqual(found.byCategory.get('9').map((row) => row.id), [904]);
  // 整串首字母 + 大写输入都认（黄校文 = hxw）
  assert.deepEqual(matchPartnerLeaves(leaves(), 'HXW').hitIds, [4]);
  // 部分首字母也命中（包含口径）——「输变电」的 sb 和「送变电」的 sb 都算
  assert.deepEqual(matchPartnerLeaves(leaves(), 'sb').hitIds.sort(), [4, 8]);
});

test('matchPartnerLeaves：拼音通道不产生假命中（不存在的首字母组合）', () => {
  assert.equal(matchPartnerLeaves(leaves(), 'xyz').hitIds.length, 0);
  // 汉字关键词不因拼音通道改变行为
  assert.deepEqual(matchPartnerLeaves(leaves(), '周广').hitIds.sort(), [4, 9]);
});

test('searchNodes：拼音首字母命中分类名（jtkh → 集团客户），祖先链随命中展开', () => {
  const found = searchNodes(fixture(), 'jtkh');
  assert.deepEqual(found.order, [1]);
  assert.equal(found.matched.has(1), true);

  const index = indexTree(fixture());
  const { rows, hitIds } = buildVisibleRows(fixture(), index, { query: 'jtkh' });
  // 命中的是顶级分类，它自己可见；空关键词时行为不变
  assert.deepEqual(hitIds, [1]);
  assert.ok(rows.some((row) => row.id === 1 && row.searching));
  assert.equal(searchNodes(fixture(), '   ').order.length, 0);
});

test('buildVisibleRows：只有客户命中时，分类与祖先链照样露出来并展开', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const found = matchPartnerLeaves(leaves(), '周广平');
  const { rows, searching, hitIds } = buildVisibleRows(roots, index, {
    query: '周广平',
    leafHits: found.hitIds,
  });
  assert.equal(searching, true);
  // 4 号「项目A」有客户命中 → 它 + 1/2/3 三条祖先都要在，且都要展开
  const ids = rows.map((row) => row.id);
  for (const id of [1, 2, 3, 4, 9]) assert.ok(ids.includes(id), `缺 ${id}`);
  // 没命中的兄弟分支不许出现（不留空壳文件夹）
  for (const id of [5, 6, 7, 8]) assert.ok(!ids.includes(id), `不该出现 ${id}`);
  // 命中分类自己是展开的（客户行要挂在它下面）
  const holder = rows.find((row) => row.id === 4);
  assert.equal(holder.isOpen, true);
  // 计数里要带上"只有客户命中的分类"
  assert.ok(hitIds.includes(4) && hitIds.includes(9));
});

test('buildVisibleRows：没有客户命中时行为与以前一致（不传 leafHits）', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const plain = buildVisibleRows(roots, index, { query: '项目A' });
  const withEmpty = buildVisibleRows(roots, index, { query: '项目A', leafHits: [] });
  assert.deepEqual(
    plain.rows.map((row) => row.id),
    withEmpty.rows.map((row) => row.id),
  );
});

test('buildVisibleRows：分类名与客户同时命中时互不吞掉', () => {
  const roots = fixture();
  const index = indexTree(roots);
  const found = matchPartnerLeaves(leaves(), '明珠');
  const { rows, hitIds } = buildVisibleRows(roots, index, {
    query: '明珠',
    leafHits: found.hitIds,
  });
  const ids = rows.map((row) => row.id);
  assert.ok(ids.includes(4));
  assert.ok(hitIds.includes(4));
});
