/**
 * selection.js 的单测（`node --test src/lib/selection.test.mjs`）
 *
 * 这里守的都是"看起来显然、但一改就出事"的边界：
 *   · 空选中集必须返回**同一个引用**（否则 useEffect 里会无限重渲染）
 *   · 有变化必须返回新数组（否则 React 认为没变，UI 不更新）
 *   · id 为 0 的合法行不能被当成"假值"剔掉（`row.id || fallback` 那种写法会）
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { pruneSelection, toggleKey } from './selection.js';

const rows = [{ id: 1 }, { id: 2 }, { id: 3 }];

test('空选中集返回同一个引用（避免 effect 循环）', () => {
  const keys = [];
  assert.equal(pruneSelection(keys, rows), keys);
});

test('全部有效时返回同一个引用（不制造无谓重渲染）', () => {
  const keys = [1, 3];
  assert.equal(pruneSelection(keys, rows), keys);
});

test('剔除已不存在的 key，且保持原有顺序', () => {
  assert.deepEqual(pruneSelection([3, 99, 1], rows), [3, 1]);
});

test('数据清空后选中集也清空', () => {
  assert.deepEqual(pruneSelection([1, 2], []), []);
});

test('key 可以是函数', () => {
  const list = [{ code: 'a' }, { code: 'b' }];
  assert.deepEqual(pruneSelection(['a', 'z'], list, (r) => r.code), ['a']);
});

test('id = 0 是合法 key，不能被当成假值丢掉', () => {
  assert.deepEqual(pruneSelection([0, 1], [{ id: 0 }, { id: 1 }]), [0, 1]);
});

test('null / undefined 的 key 一律视为不存在', () => {
  assert.deepEqual(pruneSelection([1], [{ id: null }]), []);
});

test('toggleKey 追加与移除', () => {
  assert.deepEqual(toggleKey([1], 2), [1, 2]);
  assert.deepEqual(toggleKey([1, 2], 1), [2]);
});

test('toggleKey 不修改入参（受控组件的前提）', () => {
  const keys = [1];
  toggleKey(keys, 2);
  assert.deepEqual(keys, [1]);
});
