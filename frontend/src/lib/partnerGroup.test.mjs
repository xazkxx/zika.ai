/**
 * partnerGroup 纯逻辑单测（Node 直接跑，不需要浏览器 / 不需要装测试框架）
 *
 * 跑法： E:\AI\ERP软件\frontend 下
 *   node --test src/lib/partnerGroup.test.mjs
 *
 * 覆盖重点（这几条都是"点鼠标点不出来"的）：
 *   · 维度根节点的计数**不含**未归组
 *   · 未归组永远排在最后
 *   · 取值里带冒号时，树键解析不能切错
 *   · 首字母兜底（short_name 缺失 / 中文 / 小写）
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  UNGROUPED,
  buildPartnerTree,
  filterPartnersByGroup,
  keyOf,
  partnerGroupLabel,
  rawValueOf,
} from './partnerGroup.js';

const CUSTOMERS = [
  { id: 1, name: 'A公司', level: '零售价1', businesser: '范先生' },
  { id: 2, name: 'B公司', level: '零售价1', businesser: '范先生' },
  { id: 3, name: 'C公司', level: '零售价3', businesser: null },
  { id: 4, name: 'D公司', level: '', businesser: '范先生' },
  { id: 5, name: 'E公司', level: null, businesser: undefined },
];

const SUPPLIERS = [
  { id: 1, name: '深圳市凯歌电子有限公司', short_name: 'szskgdzyxgs' },
  { id: 2, name: '石家庄合众瑞通科技有限公司', short_name: 'sjzhzrtkj yxgs' },
  { id: 3, name: '海康威视', short_name: 'hkws' },
  { id: 4, name: '无简称的供应商', short_name: null },
  { id: 5, name: '', short_name: '' },
];

test('buildPartnerTree：客户两个维度、计数正确', () => {
  const { nodes, counts, total } = buildPartnerTree(CUSTOMERS, 'customer');

  assert.equal(total, 5);
  assert.equal(nodes.length, 2);
  assert.deepEqual(nodes.map((n) => n.key), ['level', 'businesser']);
  assert.deepEqual(nodes.map((n) => n.label), ['客户级别', '业务员']);

  const level = nodes[0];
  assert.deepEqual(
    level.children.map((c) => [c.label, c.count]),
    [
      ['零售价1', 2],
      ['零售价3', 1],
      ['未分级', 2],
    ],
  );
});

test('buildPartnerTree：维度根节点计数**不含**未归组', () => {
  const { counts } = buildPartnerTree(CUSTOMERS, 'customer');
  // 5 条里 level 有值的只有 3 条（零售价1 ×2、零售价3 ×1）
  assert.equal(counts.get('level'), 3);
  assert.equal(counts.get('level:' + '零售价1'), 2);
  assert.equal(counts.get(`level:${UNGROUPED}`), 2);
  // businesser 有值 3 条、未指派 2 条
  assert.equal(counts.get('businesser'), 3);
  assert.equal(counts.get(`businesser:${UNGROUPED}`), 2);
});

test('buildPartnerTree：未归组永远排在最后一位', () => {
  const { nodes } = buildPartnerTree(CUSTOMERS, 'customer');
  const levelChildren = nodes[0].children;
  assert.equal(levelChildren[levelChildren.length - 1].label, '未分级');

  // 逆序数据也一样（未归组 2 条，比其它都多，按条数排会被顶到前面）
  const reversed = [...CUSTOMERS].reverse();
  const again = buildPartnerTree(reversed, 'customer');
  assert.equal(again.nodes[0].children.at(-1).label, '未分级');
});

test('buildPartnerTree：空数组不炸，计数为 0', () => {
  const { nodes, counts, total } = buildPartnerTree([], 'customer');
  assert.equal(total, 0);
  assert.equal(counts.get('level'), 0);
  assert.equal(nodes[0].children.length, 0);
  // 默认参数也要能用
  assert.equal(buildPartnerTree().total, 0);
});

test('buildPartnerTree：供应商按拼音首字母分组，大小写统一', () => {
  const { nodes, counts } = buildPartnerTree(SUPPLIERS, 'supplier');
  assert.equal(nodes.length, 1);
  assert.equal(nodes[0].key, 'initial');

  const labels = nodes[0].children.map((c) => c.label);
  // S ×2（szskgdzyxgs / sjzhzrtkj）；H ×1（hkws）；
  // '#' ×1（没有简称、名称是中文「无简称的供应商」→ 非拉丁开头）；
  // 「其他」×1（名称和简称都空，进未归组桶，且**必须排最后**）
  assert.deepEqual(labels, ['S', '#', 'H', '其他']);
  assert.equal(counts.get('initial:S'), 2);
  assert.equal(counts.get('initial:H'), 1);
  assert.equal(counts.get('initial:#'), 1);
  assert.equal(counts.get(`initial:${UNGROUPED}`), 1);
  // 维度根节点只数"首字母能取到"的 4 条，# 也算有值
  assert.equal(counts.get('initial'), 4);
});

test('rawValueOf：首字母兜底顺序 short_name → name → 空', () => {
  assert.equal(rawValueOf({ short_name: 'hkws', name: '海康威视' }, 'initial'), 'H');
  assert.equal(rawValueOf({ short_name: null, name: 'abc' }, 'initial'), 'A');
  assert.equal(rawValueOf({ short_name: '', name: '' }, 'initial'), '');
  assert.equal(rawValueOf(null, 'initial'), '');
  // 非 ASCII 且没有简称 → '#'
  assert.equal(rawValueOf({ short_name: '', name: '中铁一局' }, 'initial'), '#');
});

test('filterPartnersByGroup：null 返回全部（原数组引用不拷贝）', () => {
  assert.equal(filterPartnersByGroup(CUSTOMERS, 'customer', null).length, 5);
  assert.equal(filterPartnersByGroup(CUSTOMERS, 'customer', '').length, 5);
  assert.equal(filterPartnersByGroup(undefined, 'customer', null).length, 0);
});

test('filterPartnersByGroup：维度根节点只留该维度有值的行', () => {
  const rows = filterPartnersByGroup(CUSTOMERS, 'customer', 'level');
  assert.deepEqual(rows.map((r) => r.id), [1, 2, 3]);
});

test('filterPartnersByGroup：叶子节点精确匹配', () => {
  assert.deepEqual(
    filterPartnersByGroup(CUSTOMERS, 'customer', 'level:零售价1').map((r) => r.id),
    [1, 2],
  );
  assert.deepEqual(
    filterPartnersByGroup(CUSTOMERS, 'customer', 'businesser:范先生').map((r) => r.id),
    [1, 2, 4],
  );
});

test('filterPartnersByGroup：未归组只留空值行', () => {
  assert.deepEqual(
    filterPartnersByGroup(CUSTOMERS, 'customer', `level:${UNGROUPED}`).map((r) => r.id),
    [4, 5],
  );
});

test('filterPartnersByGroup：取值里带冒号时按第一个冒号切分', () => {
  const rows = [{ id: 1, level: 'A:B' }, { id: 2, level: 'A' }];
  assert.equal(keyOf('level', 'A:B'), 'level:A:B');
  assert.deepEqual(
    filterPartnersByGroup(rows, 'customer', 'level:A:B').map((r) => r.id),
    [1],
  );
});

test('filterPartnersByGroup：未知维度返回空集而不是全部', () => {
  assert.equal(filterPartnersByGroup(CUSTOMERS, 'customer', 'nope:x').length, 0);
});

test('partnerGroupLabel：维度名与取值拼装', () => {
  assert.equal(partnerGroupLabel(null), '');
  assert.equal(partnerGroupLabel('level'), '客户级别');
  assert.equal(partnerGroupLabel('level:零售价1'), '客户级别 · 零售价1');
  assert.equal(partnerGroupLabel(`initial:${UNGROUPED}`), '名称首字母 · 其他');
  assert.equal(partnerGroupLabel('unknown:1'), '');
});
