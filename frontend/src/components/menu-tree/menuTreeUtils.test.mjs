/**
 * menuTreeUtils 纯逻辑单测（Node 直接跑，不需要浏览器 / 不需要装测试框架）
 *
 * 跑法： E:\AI\ERP软件\frontend 下
 *   node --test src/components/menu-tree/menuTreeUtils.test.mjs
 *   或（本项目 node 版本较新时）node src/components/menu-tree/menuTreeUtils.test.mjs
 *
 * 覆盖重点：拖拽最容易错的那几类边界，靠鼠标点是不可能点全的。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  rowIndent,
  indexTree,
  flattenVisible,
  isDescendant,
  subtreeHeight,
  computeDropIntent,
  planDrop,
  planShift,
  planIndent,
  planOutdent,
  collectPayload,
  auditTree,
  countNodes,
  treeDepth,
  refreshDerived,
} from './menuTreeUtils.js';

/** 造一棵和真库同构的测试树：2 层 + 一个三层用的分组。 */
function makeTree() {
  return [
    {
      id: 1,
      parent_id: null,
      label: '工作台',
      page_key: '',
      sort_order: 10,
      is_enabled: true,
      is_builtin: true,
      children: [
        { id: 11, parent_id: 1, label: '运营概览', page_key: 'overview', sort_order: 10, is_enabled: true, is_builtin: true, children: [] },
      ],
    },
    {
      id: 2,
      parent_id: null,
      label: '基础资料',
      page_key: '',
      sort_order: 20,
      is_enabled: true,
      is_builtin: true,
      children: [
        { id: 21, parent_id: 2, label: '客户档案', page_key: 'customers', sort_order: 10, is_enabled: true, is_builtin: true, children: [] },
        { id: 22, parent_id: 2, label: '商品档案', page_key: 'products', sort_order: 20, is_enabled: true, is_builtin: true, children: [] },
        {
          id: 23,
          parent_id: 2,
          label: '导入导出',
          page_key: 'dataio',
          sort_order: 30,
          is_enabled: true,
          is_builtin: true,
          children: [],
        },
        {
          id: 24,
          parent_id: 2,
          label: '进销存子分组', // 分组：page_key 为空，可以挂子节点
          page_key: '',
          sort_order: 40,
          is_enabled: true,
          is_builtin: false,
          children: [
            { id: 241, parent_id: 24, label: '三级菜单项', page_key: 'stock-logs', sort_order: 10, is_enabled: true, is_builtin: false, children: [] },
          ],
        },
      ],
    },
    { id: 3, parent_id: null, label: '系统设置', page_key: '', sort_order: 30, is_enabled: true, is_builtin: true, children: [] },
  ];
}

const ids = (list) => list.map((n) => n.id);
const labels = (list) => list.map((n) => n.label);

// ─────────────────────────────────────────────────────────────────────────────
test('缩进：严格 20 + depth*16，且 depth 1/2 与现有 CSS 完全一致', () => {
  assert.equal(rowIndent(1), 36, 'depth1 必须等于 .nav-depth-1 的 36px');
  assert.equal(rowIndent(2), 52, 'depth2 必须等于 .nav-depth-2 的 52px');
  assert.equal(rowIndent(3), 68);
  assert.equal(rowIndent(4), 84);
  // 非法输入不能崩，回落成 depth=1
  assert.equal(rowIndent(0), 36);
  assert.equal(rowIndent(undefined), 36);
  assert.equal(rowIndent(-5), 36);
});

test('indexTree：层级与父 id 正确，depth 从 1 起', () => {
  const idx = indexTree(makeTree());
  assert.equal(idx.get(1).depth, 1);
  assert.equal(idx.get(1).parentId, null);
  assert.equal(idx.get(21).depth, 2);
  assert.equal(idx.get(21).parentId, 2);
  assert.equal(idx.get(241).depth, 3);
  assert.equal(idx.get(241).parentId, 24);
});

test('flattenVisible：折叠的分组不展开子节点', () => {
  const all = flattenVisible(makeTree(), []);
  assert.equal(all.length, 9);
  assert.deepEqual(all.slice(0, 3).map((r) => r.id), [1, 11, 2]);

  const collapsed = flattenVisible(makeTree(), [2]);
  assert.ok(!collapsed.some((r) => r.id === 21), '折叠「基础资料」后子节点不该出现');
  assert.ok(collapsed.some((r) => r.id === 2));
});

test('isDescendant / subtreeHeight', () => {
  const t = makeTree();
  assert.equal(isDescendant(t, 2, 241), true, '241 是 2 的后代');
  assert.equal(isDescendant(t, 241, 2), false);
  assert.equal(isDescendant(t, 2, 3), false);
  assert.equal(subtreeHeight(makeTree()[0]), 2);
  assert.equal(subtreeHeight(indexTree(makeTree()).get(2).node), 3, '基础资料 → 子分组 → 三级项 = 3 层');
  assert.equal(subtreeHeight(indexTree(makeTree()).get(21).node), 1);
});

test('computeDropIntent：三区分法，叶子中间区降级为 after', () => {
  const rect = { top: 100, height: 40 }; // 100~140
  assert.equal(computeDropIntent({ overRect: rect, pointerY: 105, overIsLeaf: false }), 'before');
  assert.equal(computeDropIntent({ overRect: rect, pointerY: 137, overIsLeaf: false }), 'after');
  assert.equal(computeDropIntent({ overRect: rect, pointerY: 120, overIsLeaf: false }), 'inside');
  // 叶子不允许 inside → 降级 after
  assert.equal(computeDropIntent({ overRect: rect, pointerY: 120, overIsLeaf: true }), 'after');
  // 缺参数不能崩
  assert.equal(computeDropIntent({ overRect: null, pointerY: 120, overIsLeaf: false }), 'after');
});

test('planDrop：同级重排（把客户档案拖到商品档案后面）', () => {
  const res = planDrop(makeTree(), { activeId: 21, overId: 22, intent: 'after', maxDepth: 8 });
  assert.equal(res.ok, true);
  const basic = res.tree.find((n) => n.id === 2);
  assert.deepEqual(ids(basic.children), [22, 21, 23, 24]);
  // 序号重排为 10/20/30/40
  assert.deepEqual(basic.children.map((n) => n.sort_order), [10, 20, 30, 40]);
  // 注入了父级引用（旧父=新父=2，去重后只一批）
  assert.deepEqual(res.items.filter((i) => i.id === 21), [{ id: 21, parent_id: 2, sort_order: 20 }]);
});

test('planDrop：跨组移动（把导入导出拖进「进销存子分组」）', () => {
  const res = planDrop(makeTree(), { activeId: 23, overId: 24, intent: 'inside', maxDepth: 8 });
  assert.equal(res.ok, true);
  const basic = res.tree.find((n) => n.id === 2);
  const sub = basic.children.find((n) => n.id === 24);
  assert.deepEqual(ids(sub.children), [241, 23], '落到子分组末尾');
  assert.deepEqual(ids(basic.children), [21, 22, 24], '原位置已摘除');
  assert.deepEqual(basic.children.map((n) => n.sort_order), [10, 20, 30], '旧父级序号补上空洞');
  // 两批 payload：旧父级(2) 与 新父级(24)
  const parents = [...new Set(res.items.map((i) => i.parent_id))].sort((a, b) => a - b);
  assert.deepEqual(parents, [2, 24]);
});

test('planDrop：拖到自己下级 → 拒绝', () => {
  const res = planDrop(makeTree(), { activeId: 2, overId: 241, intent: 'after', maxDepth: 8 });
  assert.equal(res.ok, false);
  assert.match(res.reason, /自己的下一级/);
});

test('planDrop：拖到自己身上 → 无操作', () => {
  const res = planDrop(makeTree(), { activeId: 21, overId: 21, intent: 'after', maxDepth: 8 });
  assert.equal(res.ok, false);
  assert.equal(res.noop, true);
});

test('planDrop：往叶子里放 → 拒绝并说明', () => {
  const res = planDrop(makeTree(), { activeId: 3, overId: 21, intent: 'inside', maxDepth: 8 });
  assert.equal(res.ok, false);
  assert.match(res.reason, /是菜单项/);
});

test('planDrop：超过深度上限 → 拒绝，且报出会到第几层', () => {
  // 把带 1 层子的「工作台」移到「进销存子分组」(depth3) 下 → 最深到第 3+1+1-1 = 4 层
  const res = planDrop(makeTree(), { activeId: 1, overId: 24, intent: 'inside', maxDepth: 3 });
  assert.equal(res.ok, false);
  assert.match(res.reason, /最多 3 层/);
  assert.match(res.reason, /第 4 层/);
  // 上限放宽就应当通过 —— 证明不是一律拒绝
  assert.equal(
    planDrop(makeTree(), { activeId: 1, overId: 24, intent: 'inside', maxDepth: 4 }).ok,
    true,
  );
});

test('planDrop：不改动入参（纯函数）', () => {
  const tree = makeTree();
  const snapshot = JSON.stringify(tree);
  planDrop(tree, { activeId: 21, overId: 22, intent: 'after', maxDepth: 8 });
  assert.equal(JSON.stringify(tree), snapshot, '原树必须一个字节都不变');
});

test('planDrop：结果里 depth / has_children 被重算', () => {
  const res = planDrop(makeTree(), { activeId: 23, overId: 24, intent: 'inside', maxDepth: 8 });
  const idx = indexTree(res.tree);
  assert.equal(idx.get(23).depth, 3, '导入导出 现在在第 3 层');
  assert.equal(idx.get(24).node.has_children, true);
  assert.equal(idx.get(23).node.has_children, false);
});

test('planShift / planIndent / planOutdent', () => {
  // 下移一位
  const down = planShift(makeTree(), { activeId: 21, delta: 1, maxDepth: 8 });
  assert.equal(down.ok, true);
  assert.deepEqual(ids(down.tree.find((n) => n.id === 2).children), [22, 21, 23, 24]);

  // 已在最前 → 拒绝但标记 noop
  const first = planShift(makeTree(), { activeId: 21, delta: -1, maxDepth: 8 });
  assert.equal(first.ok, false);
  assert.equal(first.noop, true);
  assert.match(first.reason, /最前面/);

  // 缩进：客户档案 变成「客户档案」上面没有兄弟 → 拒绝
  const noPrev = planIndent(makeTree(), { activeId: 21, maxDepth: 8 });
  assert.equal(noPrev.ok, false);
  assert.match(noPrev.reason, /上面没有同级节点/);

  // 缩进：商品档案 → 变成客户档案的子级（但客户档案是叶子 → 拒绝）
  const intoLeaf = planIndent(makeTree(), { activeId: 22, maxDepth: 8 });
  assert.equal(intoLeaf.ok, false);
  assert.match(intoLeaf.reason, /不能当上级/);

  // 缩进：导入导出 → 变成商品档案的子级（叶子）应拒绝；换成挂到子分组才有意义
  // 这里用「进销存子分组」缩进到「商品档案」下面 → 同样是叶子，拒绝
  const intoLeaf2 = planIndent(makeTree(), { activeId: 24, maxDepth: 8 });
  assert.equal(intoLeaf2.ok, false);

  // 取消缩进：三级菜单项 → 挂到 基础资料 里，紧跟「进销存子分组」之后
  const out = planOutdent(makeTree(), { activeId: 241, maxDepth: 8 });
  assert.equal(out.ok, true);
  const basic = out.tree.find((n) => n.id === 2);
  assert.deepEqual(ids(basic.children), [21, 22, 23, 24, 241]);

  // 取消缩进：客户档案（在基础资料下）→ 升到顶层、紧跟在「基础资料」后面
  const upOne = planOutdent(makeTree(), { activeId: 21, maxDepth: 8 });
  assert.equal(upOne.ok, true);
  assert.deepEqual(labels(upOne.tree), ['工作台', '基础资料', '客户档案', '系统设置']);

  // 已经是最外层（parent_id 为 null）→ noop
  const root = planOutdent(makeTree(), { activeId: 1, maxDepth: 8 });
  assert.equal(root.ok, false);
  assert.equal(root.noop, true);
  assert.match(root.reason, /最外层/);
});

test('collectPayload：只产出受影响父级的全部子节点，序号连续', () => {
  const tree = makeTree();
  const items = collectPayload(tree, [2]);
  assert.deepEqual(ids(items), [21, 22, 23, 24]);
  assert.deepEqual(items.map((i) => i.sort_order), [10, 20, 30, 40]);
  assert.ok(items.every((i) => i.parent_id === 2));

  // 顶层（parent_id = null）
  const tops = collectPayload(tree, [null]);
  assert.deepEqual(ids(tops), [1, 2, 3]);
  assert.ok(tops.every((i) => i.parent_id === null));
});

test('auditTree：能查出超深 / 重名 / 叶子带子节点', () => {
  assert.deepEqual(auditTree(makeTree(), { maxDepth: 8 }), []);

  const deep = makeTree();
  const problems = auditTree(deep, { maxDepth: 1 });
  assert.ok(problems.some((p) => /超过上限/.test(p)), '超深应被报出');

  const dup = makeTree();
  dup[1].children.push({ id: 999, parent_id: 2, label: '客户档案', page_key: 'staff', sort_order: 50, children: [] });
  assert.ok(auditTree(dup, { maxDepth: 8 }).some((p) => /重名/.test(p)));

  const badLeaf = makeTree();
  badLeaf[1].children[0].children = [{ id: 998, label: '违规子节点', page_key: '', sort_order: 10, children: [] }];
  assert.ok(auditTree(badLeaf, { maxDepth: 8 }).some((p) => /带着 1 个子节点/.test(p)));
});

test('countNodes / treeDepth', () => {
  assert.equal(countNodes(makeTree()), 9);
  assert.equal(treeDepth(makeTree()), 3);
  assert.equal(treeDepth([]), 0);
});

test('refreshDerived：depth 与 has_children 全树对齐', () => {
  const t = refreshDerived(makeTree());
  const idx = indexTree(t);
  assert.equal(idx.get(241).depth, 3);
  assert.equal(idx.get(3).node.has_children, false);
  assert.equal(idx.get(24).node.has_children, true);
});

test('计划一次拖拽 → 直接喂给后端 payload 的形状是对的', () => {
  const res = planDrop(makeTree(), { activeId: 21, overId: 3, intent: 'before', maxDepth: 8 });
  assert.equal(res.ok, true);
  res.items.forEach((it) => {
    assert.equal(typeof it.id, 'number');
    assert.ok(it.parent_id === null || typeof it.parent_id === 'number');
    assert.equal(typeof it.sort_order, 'number');
  });
  // 顶层顺序变成 工作台 → 基础资料 → 客户档案 → 系统设置
  // （「客户档案」插到「系统设置」之前；顶层数组本身此时是 [1,2,3]，插在索引 2）
  assert.deepEqual(labels(res.tree), ['工作台', '基础资料', '客户档案', '系统设置']);
});
