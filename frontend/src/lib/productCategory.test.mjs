/**
 * productCategory 纯逻辑单测（Node 直接跑，不需要浏览器 / 不需要装测试框架）
 *
 * 跑法： E:\AI\ERP软件\frontend 下
 *   node --test src/lib/productCategory.test.mjs
 *
 * 覆盖重点：类别树的"含子类过滤"是这一步的核心，靠鼠标点是不可能点全边界的
 * （三级嵌套、跨分支重名、空类别、后端把列加上之后的双通道……）。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  UNCATEGORIZED,
  categoryIdOf,
  categoryNameOf,
  collectCategoryIds,
  collectCategoryNames,
  countProductsByCategory,
  filterProductsByCategory,
  findCategoryNode,
} from './productCategory.js';

// ── 测试用类别树：模拟用户想要的「中铁 → 中铁一局 → 劳保鞋」
//    并且故意在「中铁二局」下面也放一个同名的「劳保鞋」，把跨分支重名这个坑摆上台面。
const TREE = [
  {
    id: 1,
    name: '中铁',
    parent_id: null,
    children: [
      {
        id: 2,
        name: '中铁一局',
        parent_id: 1,
        children: [
          { id: 3, name: '劳保鞋', parent_id: 2, children: [] },
          { id: 4, name: '工作服', parent_id: 2, children: [] },
        ],
      },
      {
        id: 5,
        name: '中铁二局',
        parent_id: 1,
        children: [{ id: 6, name: '劳保鞋', parent_id: 5, children: [] }],
      },
    ],
  },
  { id: 7, name: '五金', parent_id: null, children: [] },
  { id: 8, name: '办公用品', parent_id: null, children: [] },
];

const P = (id, category, category_id = null) => ({ id, name: `商品${id}`, category, category_id });

// 没有 category_id 的（= 今天的真实状态）
const ROWS_BY_NAME = [
  P(101, '劳保鞋'),
  P(102, '工作服'),
  P(103, '劳保鞋'),
  P(104, '五金'),
  P(105, ''),
  P(106, null),
  P(107, ' 五金 '), // 带空白，应被 trim 后匹配
  P(108, '树里没有的类别'), // 孤儿名称，不属于任何节点
];

// 已经回填了 category_id 的（= 将来加了列之后的状态）
const ROWS_BY_ID = [
  P(201, '劳保鞋', 3), // 中铁一局 / 劳保鞋
  P(202, '工作服', 4), // 中铁一局 / 工作服
  P(203, '劳保鞋', 6), // 中铁二局 / 劳保鞋
  P(204, '五金', 7),
  P(205, '', null),
  P(206, '五金', null), // 名字对但还没回填 id → 应仍被按名称算进去
];

// ─────────────────────────────────────────────────────────────────────────────
test('collectCategoryNames：含自身 + 全部子孙，且是深度优先顺序', () => {
  assert.deepEqual(collectCategoryNames(TREE[0]), ['中铁', '中铁一局', '劳保鞋', '工作服', '中铁二局', '劳保鞋']);
  assert.deepEqual(collectCategoryNames(TREE[1]), ['五金']); // TREE[1] = 五金（无子级）
  assert.deepEqual(collectCategoryNames(null), []);
  assert.deepEqual(collectCategoryNames({ id: 9, name: '空壳' }), ['空壳']);
});

test('collectCategoryIds：叶子只有自己，父节点带全部子孙', () => {
  assert.deepEqual(collectCategoryIds(TREE[0]).sort((a, b) => a - b), [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(collectCategoryIds(TREE[0].children[0]), [2, 3, 4]);
  assert.deepEqual(collectCategoryIds(null), []);
});

test('findCategoryNode：能找到多层深处的节点；找不到返回 null（不抛错）', () => {
  assert.equal(findCategoryNode(TREE, 3)?.name, '劳保鞋');
  assert.equal(findCategoryNode(TREE, 6)?.name, '劳保鞋');
  assert.equal(findCategoryNode(TREE, 999), null);
  assert.equal(findCategoryNode([], 1), null);
  assert.equal(findCategoryNode(null, 1), null);
});

test('categoryNameOf / categoryIdOf：空白 trim、null 安全、非法 id 归零', () => {
  assert.equal(categoryNameOf({ category: '  五金 ' }), '五金');
  assert.equal(categoryNameOf({ category: null }), '');
  assert.equal(categoryNameOf({}), '');
  assert.equal(categoryNameOf(null), '');

  assert.equal(categoryIdOf({ category_id: 7 }), 7);
  assert.equal(categoryIdOf({ category_id: '7' }), 7);
  assert.equal(categoryIdOf({ category_id: null }), null);
  assert.equal(categoryIdOf({}), null);
  assert.equal(categoryIdOf({ category_id: 'abc' }), null);
});

// ── 过滤：按名称（今天的真实状态） ─────────────────────────────────────────────
test('过滤：null 表示全部，原样返回', () => {
  assert.equal(filterProductsByCategory(ROWS_BY_NAME, TREE, null).length, ROWS_BY_NAME.length);
  assert.equal(filterProductsByCategory(ROWS_BY_NAME, TREE, undefined).length, ROWS_BY_NAME.length);
});

test('过滤：未分类 = 类别名空白（null 与空串都算）', () => {
  const got = filterProductsByCategory(ROWS_BY_NAME, TREE, UNCATEGORIZED).map((r) => r.id);
  assert.deepEqual(got, [105, 106]);
});

test('过滤：选中二级节点 → 只出它自己和它的子孙（含 trim 后的名称匹配）', () => {
  // 中铁一局 → 劳保鞋(101,103) + 工作服(102)。五金、孤儿名称都不该进来。
  const got = filterProductsByCategory(ROWS_BY_NAME, TREE, 2).map((r) => r.id).sort((a, b) => a - b);
  assert.deepEqual(got, [101, 102, 103]);
});

test('过滤：选中顶级节点 → 整棵子树都算，兄弟分支不算', () => {
  const got = filterProductsByCategory(ROWS_BY_NAME, TREE, 1).map((r) => r.id).sort((a, b) => a - b);
  assert.deepEqual(got, [101, 102, 103]); // 中铁二局下的「劳保鞋」名称相同，按名称会一起带出（见下一条）
  const wujin = filterProductsByCategory(ROWS_BY_NAME, TREE, 7).map((r) => r.id).sort((a, b) => a - b);
  assert.deepEqual(wujin, [104, 107]);
});

test('过滤：名称匹配下「跨分支重名」确实会串（已知取舍，这里把它钉成文档）', () => {
  // 中铁一局(2) 下没有劳保鞋以外的分支，但名称「劳保鞋」在整棵树里出现两次，
  // 所以按名称过滤时，103（属于中铁二局的劳保鞋）也会被带进来。
  // 这不是 bug，是"products.category 只存名称"这个既有设计的必然结果；
  // 后端补上 products.category_id 之后，下面的 ID 版用例证明会变精确。
  const got = filterProductsByCategory(ROWS_BY_NAME, TREE, 3).map((r) => r.id);
  assert.deepEqual(got, [101, 103]);
});

test('过滤：选中的节点已被删掉 → 退回全部，不给空列表', () => {
  const got = filterProductsByCategory(ROWS_BY_NAME, TREE, 12345);
  assert.equal(got.length, ROWS_BY_NAME.length);
});

test('过滤：空商品列表 / 空树都不炸', () => {
  assert.deepEqual(filterProductsByCategory([], TREE, 2), []);
  assert.deepEqual(filterProductsByCategory(null, TREE, 2), []);
  assert.equal(filterProductsByCategory(ROWS_BY_NAME, [], 2).length, ROWS_BY_NAME.length);
});

// ── 过滤：按 id（后端加了 category_id 之后的双通道） ───────────────────────────
test('过滤（有 category_id）：同一名称的两个分支能被精确区分', () => {
  // 中铁一局 → 只有 201(劳保鞋@3) + 202(工作服@4)；中铁二局那个 203 必须被排除。
  const a = filterProductsByCategory(ROWS_BY_ID, TREE, 2).map((r) => r.id).sort((x, y) => x - y);
  assert.deepEqual(a, [201, 202]);

  const b = filterProductsByCategory(ROWS_BY_ID, TREE, 5).map((r) => r.id);
  assert.deepEqual(b, [203]);
});

test('过滤（有 category_id）：id 不在子树里的商品被明确排除，不再按名字兜底', () => {
  // 206 名称是「五金」但 id 未回填(null) → 仍按名称算进 7；
  // 203 名称是「劳保鞋」但 id=6（中铁二局），查 中铁一局(2) 时必须不出现。
  const root = filterProductsByCategory(ROWS_BY_ID, TREE, 1).map((r) => r.id).sort((x, y) => x - y);
  assert.deepEqual(root, [201, 202, 203]);
  const wujin = filterProductsByCategory(ROWS_BY_ID, TREE, 7).map((r) => r.id).sort((x, y) => x - y);
  assert.deepEqual(wujin, [204, 206]);
});

test('过滤（有 category_id）：未分类只认"既没 id 又没名称"的', () => {
  const got = filterProductsByCategory(ROWS_BY_ID, TREE, UNCATEGORIZED).map((r) => r.id);
  assert.deepEqual(got, [205]);
});

// ── 计数 ────────────────────────────────────────────────────────────────────
test('计数：每个节点都是"含子孙"的总数，未分类与总数单独给', () => {
  const { byId, uncategorized, all } = countProductsByCategory(ROWS_BY_NAME, TREE);
  assert.equal(all, 8);
  assert.equal(uncategorized, 2); // 105 空串 + 106 null
  assert.equal(byId.get(1), 3); // 中铁：101/102/103
  assert.equal(byId.get(2), 3); // 中铁一局：按名称同样带出 103（见重名那条）
  assert.equal(byId.get(5), 2); // 中铁二局：103
  assert.equal(byId.get(7), 2); // 五金：104 + 107(trim)
  assert.equal(byId.get(8), 0); // 办公用品：没有商品
});

test('计数（有 category_id）：按 id 精确归堆，未回填的仍按名称计入', () => {
  const { byId, uncategorized, all } = countProductsByCategory(ROWS_BY_ID, TREE);
  assert.equal(all, 6);
  assert.equal(uncategorized, 1); // 205
  assert.equal(byId.get(2), 2); // 201 + 202
  assert.equal(byId.get(5), 1); // 203
  assert.equal(byId.get(7), 2); // 204(id) + 206(名称)
  assert.equal(byId.get(1), 3); // 201 + 202 + 203
});

test('计数：空输入不炸', () => {
  const { byId, uncategorized, all } = countProductsByCategory([], []);
  assert.equal(all, 0);
  assert.equal(uncategorized, 0);
  assert.equal(byId.size, 0);
});
