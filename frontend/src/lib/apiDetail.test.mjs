/**
 * parseApiDetail 回归测试
 *   node --test src/lib/apiDetail.test.mjs
 *
 * 核心断言：**永远返回非空字符串**。只要这一条不破，前端就不会因为
 * 把数组塞进 React 状态而白屏。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseApiDetail } from './apiDetail.js';

test('字符串 detail 原样返回', () => {
  assert.equal(parseApiDetail('请先勾选要移动的商品', '兜底'), '请先勾选要移动的商品');
});

test('字符串两侧空白会被 trim', () => {
  assert.equal(parseApiDetail('  分类名称过长  ', '兜底'), '分类名称过长');
});

test('空字符串落到兜底', () => {
  assert.equal(parseApiDetail('', '兜底文案'), '兜底文案');
  assert.equal(parseApiDetail('   ', '兜底文案'), '兜底文案');
});

test('422 数组取 detail[0].msg 并翻成中文', () => {
  const detail = [
    { type: 'int_parsing', loc: ['body', 'ids', 0], msg: 'Input should be a valid integer', input: 'abc' },
  ];
  const text = parseApiDetail(detail, '兜底');
  assert.equal(typeof text, 'string');
  assert.ok(text.includes('0'), `应带上字段位置，实际：${text}`);
  assert.ok(text.includes('整数'), `应翻成中文，实际：${text}`);
});

test('422 数组多条时取第一条', () => {
  const detail = [
    { loc: ['body', 'category'], msg: 'Field required' },
    { loc: ['body', 'ids'], msg: 'Input should be a valid list' },
  ];
  assert.equal(parseApiDetail(detail, '兜底'), '缺少必填参数「category」');
});

test('数组元素是字符串时直接用', () => {
  assert.equal(parseApiDetail(['第一条错误'], '兜底'), '第一条错误');
});

test('空数组落到兜底', () => {
  assert.equal(parseApiDetail([], '兜底'), '兜底');
});

test('对象 detail 取 msg', () => {
  assert.equal(parseApiDetail({ msg: '对象里的消息' }, '兜底'), '对象里的消息');
});

test('undefined / null 落到兜底', () => {
  assert.equal(parseApiDetail(undefined, '兜底'), '兜底');
  assert.equal(parseApiDetail(null, '兜底'), '兜底');
});

test('兜底本身非法时给默认文案', () => {
  assert.equal(parseApiDetail(undefined, undefined), '请求失败，请稍后重试');
  assert.equal(parseApiDetail(null, ''), '请求失败，请稍后重试');
});

test('任何输入都返回字符串（防白屏总闸）', () => {
  const samples = [
    undefined, null, '', '   ', 0, 123, true, [], {}, [{}], [{ loc: [] }],
    [{ msg: '' }], [{ msg: 123 }], { msg: {} }, [[1, 2]], { detail: 'x' },
    [{ type: 'x', loc: ['body', 'f'], msg: 'String should have at most 5 characters' }],
  ];
  for (const sample of samples) {
    const out = parseApiDetail(sample, '兜底');
    assert.equal(typeof out, 'string', `输入 ${JSON.stringify(sample)} 返回了 ${typeof out}`);
    assert.ok(out.length > 0, `输入 ${JSON.stringify(sample)} 返回空串`);
  }
});
