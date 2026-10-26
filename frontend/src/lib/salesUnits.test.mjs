/**
 * salesUnits.js 单测（第三阶段 3c）
 *
 *   node --test src/lib/salesUnits.test.mjs
 *
 * 与 productUnits.test.mjs / productCategory.test.mjs / productImage.test.mjs
 * 同一套做法：纯逻辑零依赖,秒级跑完。
 *
 * 这里**只测纯函数**。组件的行为（下拉框真的换了、提示真的显示了）
 * 归 jsdom 挂载测试管（`_product_units_step3/verify_3c_frontend/`）。
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  BASE_UNIT_FACTOR,
  baseQuantity,
  baseUnitCost,
  buildUnitOptions,
  defaultUnitPrice,
  describeConversion,
  lineAmount,
  makeEmptySalesLine,
  resolveFactorFor,
  serializeSalesItems,
  suggestUnitPrice,
  summarizeLines,
  unitOptionLabel,
  validateSalesLines,
} from './salesUnits.js';

/** 一个 盒(基本单位) / 箱=12 / 大箱=48 的商品,规格取自真实档案形状。 */
const PRODUCT = {
  id: 1707,
  name: '焊条',
  unit: '盒',
  sale_price: 15,
  purchase_price: 8,
};

const UNIT_ROWS = [
  { unit_name: '箱', factor: 12, sale_price: 180, price: 96, is_enabled: true },
  { unit_name: '大箱', factor: 48, sale_price: 700, price: 380, is_enabled: true },
  // 停用的行必须被剔除 —— 后端 _resolve_unit_factor 只认 is_enabled=true
  { unit_name: '托', factor: 480, sale_price: 7000, price: 3800, is_enabled: false },
];

// ───────────────────────── buildUnitOptions ─────────────────────────

test('buildUnitOptions: 基本单位排在第一位,且 factor 恒为 1', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(options[0].name, '盒');
  assert.equal(options[0].factor, BASE_UNIT_FACTOR);
  assert.equal(options[0].isBase, true);
});

test('buildUnitOptions: 辅助单位按换算率升序（箱 12 在大箱 48 之前）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.deepEqual(
    options.map((o) => o.name),
    ['盒', '箱', '大箱']
  );
});

test('buildUnitOptions: is_enabled=false 的辅助单位不出现（否则用户必选到一个 400）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(options.some((o) => o.name === '托'), false);
});

test('buildUnitOptions: 脏换算率（0 / 1 / 小数 / 负数 / 空）全部剔除', () => {
  const options = buildUnitOptions(PRODUCT, [
    { unit_name: '甲', factor: 0, is_enabled: true },
    { unit_name: '乙', factor: 1, is_enabled: true },
    { unit_name: '丙', factor: 2.5, is_enabled: true },
    { unit_name: '丁', factor: -12, is_enabled: true },
    { unit_name: '戊', factor: '', is_enabled: true },
    { unit_name: '己', factor: 6, is_enabled: true },
  ]);
  assert.deepEqual(
    options.map((o) => o.name),
    ['盒', '己']
  );
});

test('buildUnitOptions: 与基本单位同名的辅助单位去重（不出现两个"盒"）', () => {
  const options = buildUnitOptions(PRODUCT, [{ unit_name: '盒', factor: 12, is_enabled: true }]);
  assert.equal(options.filter((o) => o.name === '盒').length, 1);
  assert.equal(options[0].isBase, true);
});

test('buildUnitOptions: 没有基本单位时只剩辅助单位,不崩', () => {
  const options = buildUnitOptions({ id: 1, unit: '' }, UNIT_ROWS);
  assert.deepEqual(
    options.map((o) => o.name),
    ['箱', '大箱']
  );
});

test('buildUnitOptions: units 为 null / undefined / 非数组都被当成空表', () => {
  for (const bad of [null, undefined, 'oops', 0]) {
    const options = buildUnitOptions(PRODUCT, bad);
    assert.deepEqual(
      options.map((o) => o.name),
      ['盒']
    );
  }
});

test('buildUnitOptions: includeUnit 把已停用的单位补回来并标 disabledOption（改单不能被迫换单位）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS, '托');
  const hit = options.find((o) => o.name === '托');
  assert.ok(hit, '停用单位必须仍能出现在下拉里');
  assert.equal(hit.disabledOption, true);
  assert.equal(unitOptionLabel(hit, PRODUCT.unit).includes('已停用'), true);
});

test('buildUnitOptions: includeUnit 传的是已存在的单位时不会重复添加', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS, '箱');
  assert.equal(options.filter((o) => o.name === '箱').length, 1);
});

test('buildUnitOptions: 把辅助单位的独立售价/进价带出来（供自动预填）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  const box = options.find((o) => o.name === '箱');
  assert.equal(box.salePrice, 180);
  assert.equal(box.purchasePrice, 96);
  assert.equal(options[0].salePrice, 15);
});

// ───────────────────────── resolveFactorFor ─────────────────────────

test('resolveFactorFor: 基本单位 → 1', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(resolveFactorFor(options, '盒'), 1);
});

test('resolveFactorFor: 箱 → 12,大箱 → 48', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(resolveFactorFor(options, '箱'), 12);
  assert.equal(resolveFactorFor(options, '大箱'), 48);
});

test('resolveFactorFor: 空 / 未选 / 未知名 → 1（不换算,与后端"未指定单位"一致）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  for (const bad of ['', null, undefined, '   ', '不存在的单位']) {
    assert.equal(resolveFactorFor(options, bad), 1);
  }
});

// ───────────────────────── baseQuantity（核心换算）─────────────────────────

test('baseQuantity: 3 箱 × 12 = 36 盒', () => {
  assert.equal(baseQuantity('3', 12), 36);
});

test('baseQuantity: 基本单位不放大（1 盒 × 1 = 1 盒）', () => {
  assert.equal(baseQuantity('5', 1), 5);
});

test('baseQuantity: 算不出来时返回 null 而不是 0（0 会被误读成"不出库"）', () => {
  assert.equal(baseQuantity('', 12), null);
  assert.equal(baseQuantity('abc', 12), null);
  assert.equal(baseQuantity('3', ''), null);
  assert.equal(baseQuantity(null, null), null);
});

test('baseQuantity: 数量为 0 返回 0（这是真的 0,不是"算不出"）', () => {
  assert.equal(baseQuantity('0', 12), 0);
});

test('baseQuantity: 大数量不丢精度（Number 安全整数范围内）', () => {
  assert.equal(baseQuantity('9999', 999999), 9999 * 999999);
});

// ───────────────────────── baseUnitCost ─────────────────────────

test('baseUnitCost: 录入单价 180/箱 ÷ 12 = 15 元/盒（后端写进流水的就是这个）', () => {
  assert.equal(baseUnitCost('180', 12), 15);
});

test('baseUnitCost: 基本单位原样（15 ÷ 1 = 15）', () => {
  assert.equal(baseUnitCost(15, 1), 15);
});

test('baseUnitCost: 除不尽保留浮点真值,不四舍五入（避免展示层和落库层不一致）', () => {
  assert.equal(baseUnitCost('100', 3), 100 / 3);
});

test('baseUnitCost: 单价空 / factor 非法 → null', () => {
  assert.equal(baseUnitCost('', 12), null);
  assert.equal(baseUnitCost('180', 0), null);
  assert.equal(baseUnitCost('180', ''), null);
});

// ───────────────────────── 金额不变量 ─────────────────────────

test('lineAmount: 录入口径 = 数量 × 录入单价', () => {
  assert.equal(lineAmount('3', '180'), 540);
});

test('⭐ 金额不变量：(q×f) × (p/f) === q×p —— 换算前后金额分文不差', () => {
  for (const [q, p, f] of [
    ['3', '180', 12],
    ['7', '33.33', 48],
    ['1', '0.01', 999],
    ['999', '1234.56', 6],
  ]) {
    const byInput = lineAmount(q, p);
    const byBase = baseQuantity(q, f) * baseUnitCost(p, f);
    assert.ok(
      Math.abs(byInput - byBase) < 1e-9,
      `q=${q} p=${p} f=${f}: 录入侧 ${byInput} != 基本单位侧 ${byBase}`
    );
  }
});

// ───────────────────────── describeConversion ─────────────────────────

test('describeConversion: 3 箱 = 36 盒', () => {
  assert.equal(describeConversion('3', 12, '箱', '盒'), '3 箱 = 36 盒');
});

test('describeConversion: 选的就是基本单位时不写"= 自己"', () => {
  assert.equal(describeConversion('3', 1, '盒', '盒'), '3 盒');
});

test('describeConversion: 算不出来显示 — 占位', () => {
  assert.equal(describeConversion('', 12, '箱', '盒'), '—');
});

// ───────────────────────── defaultUnitPrice ─────────────────────────

test('defaultUnitPrice: 箱 → 180（辅助单位自带售价）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(defaultUnitPrice(options, '箱'), 180);
});

test('defaultUnitPrice: 基本单位取档案售价 15', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(defaultUnitPrice(options, '盒'), 15);
});

test('defaultUnitPrice: 未知名 → null（由界面决定是否回退,不在这里猜）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(defaultUnitPrice(options, '不存在'), null);
});

test('defaultUnitPrice: 辅助单位没填售价 → null（要回退到档案价,但回退值必须 = 档案价 × factor）', () => {
  const options = buildUnitOptions(PRODUCT, [{ unit_name: '箱', factor: 12, is_enabled: true }]);
  assert.equal(defaultUnitPrice(options, '箱'), null);
});

// ───────────────────────── suggestUnitPrice（换单位时的预填建议）─────────────

test('suggestUnitPrice: 辅助单位有独立售价时优先用它（箱 → 180,不是 15×12 的巧合）', () => {
  const options = buildUnitOptions(PRODUCT, [
    { unit_name: '箱', factor: 12, sale_price: 199, is_enabled: true },
  ]);
  assert.equal(suggestUnitPrice(options, '箱', PRODUCT), 199);
});

test('suggestUnitPrice: 辅助单位没定价 → 档案售价 × factor（15 × 12 = 180）', () => {
  const options = buildUnitOptions(PRODUCT, [{ unit_name: '箱', factor: 12, is_enabled: true }]);
  assert.equal(suggestUnitPrice(options, '箱', PRODUCT), 180);
});

test('suggestUnitPrice: 基本单位 → 档案售价原样（15 × 1）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(suggestUnitPrice(options, '盒', PRODUCT), 15);
});

test('suggestUnitPrice: 大箱没定价 → 15 × 48 = 720,且收敛到分（不出现 720.0000000000001）', () => {
  const options = buildUnitOptions(PRODUCT, [{ unit_name: '大箱', factor: 48, is_enabled: true }]);
  const price = suggestUnitPrice(options, '大箱', PRODUCT);
  assert.equal(price, 720);
  assert.equal(String(price).includes('.'), false);
});

test('⭐ suggestUnitPrice: 档案也没有售价 → null,绝不返回 0（0 会变成白送单）', () => {
  const options = buildUnitOptions({ unit: '盒', sale_price: null }, [
    { unit_name: '箱', factor: 12, is_enabled: true },
  ]);
  assert.equal(suggestUnitPrice(options, '箱', { unit: '盒', sale_price: null }), null);
  assert.equal(suggestUnitPrice(options, '箱', null), null);
});

test('suggestUnitPrice: 单位留空/未知名 → 回退到档案价（= 基本单位价）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(suggestUnitPrice(options, '', PRODUCT), 15);
  assert.equal(suggestUnitPrice(options, '不存在', PRODUCT), 15);
});

// ───────────────────────── unitOptionLabel ─────────────────────────

test('unitOptionLabel: 箱（1箱=12盒）', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(unitOptionLabel(options.find((o) => o.name === '箱'), '盒'), '箱（1箱=12盒）');
});

test('unitOptionLabel: 基本单位标"基本单位",不带换算', () => {
  const options = buildUnitOptions(PRODUCT, UNIT_ROWS);
  assert.equal(unitOptionLabel(options[0], '盒'), '盒（基本单位）');
});

// ───────────────────────── validateSalesLines ─────────────────────────

const OPTIONS_MAP = new Map([[String(PRODUCT.id), buildUnitOptions(PRODUCT, UNIT_ROWS)]]);

const goodLine = (over = {}) => ({
  product_id: String(PRODUCT.id),
  unit: '箱',
  quantity: '3',
  unit_price: '180',
  note: '',
  ...over,
});

test('validateSalesLines: 一行合法明细通过', () => {
  const result = validateSalesLines([goodLine()], OPTIONS_MAP);
  assert.equal(result.ok, true, result.error);
});

test('validateSalesLines: 整表空着 → 提示"请至少填写一行"（index = -1）', () => {
  const result = validateSalesLines([makeEmptySalesLine()], OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.equal(result.index, -1);
  assert.match(result.error, /至少填写一行/);
});

test('validateSalesLines: 没选商品 → 指到那一行', () => {
  const rows = [goodLine(), goodLine({ product_id: '' })];
  const result = validateSalesLines(rows, OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.equal(result.index, 1);
  assert.match(result.error, /第 2 行还没有选择商品/);
});

test('validateSalesLines: 数量 0 / 负数 / 小数 / 空 全部拦下（后端 quantity 是 int）', () => {
  for (const bad of ['0', '-1', '2.5', '', 'abc']) {
    const result = validateSalesLines([goodLine({ quantity: bad })], OPTIONS_MAP);
    assert.equal(result.ok, false, `数量 "${bad}" 应该被拦下`);
    assert.equal(result.index, 0);
  }
});

test('validateSalesLines: 数量超上限被拦下', () => {
  const result = validateSalesLines([goodLine({ quantity: '99999999' })], OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.match(result.error, /不能超过/);
});

test('validateSalesLines: ⭐ 单价为空被拦下 —— 绝不能让后端静默按 0 落库', () => {
  const result = validateSalesLines([goodLine({ unit_price: '' })], OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.match(result.error, /单价要填数字/);
});

test('validateSalesLines: 单价为 0 是合法的（赠品,但必须是用户显式填的 0）', () => {
  const result = validateSalesLines([goodLine({ unit_price: '0' })], OPTIONS_MAP);
  assert.equal(result.ok, true, result.error);
});

test('validateSalesLines: 负单价被拦下', () => {
  const result = validateSalesLines([goodLine({ unit_price: '-1' })], OPTIONS_MAP);
  assert.equal(result.ok, false);
});

test('validateSalesLines: ⭐ 商品不在选项表里（外部塞进来的脏 product_id）被拦下', () => {
  const result = validateSalesLines([goodLine({ product_id: '999999' })], OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.match(result.error, /不在商品列表里/);
});

test('validateSalesLines: ⭐ 单位不在该商品的选项里被拦下（否则后端 _resolve_unit_factor 必 400）', () => {
  const result = validateSalesLines([goodLine({ unit: '托' })], OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.match(result.error, /没有单位「托」/);
});

test('validateSalesLines: 单位留空 = 不指定,放行（走后端"基本单位"老路径）', () => {
  const result = validateSalesLines([goodLine({ unit: '' })], OPTIONS_MAP);
  assert.equal(result.ok, true, result.error);
});

test('validateSalesLines: 第 3 行出错时 index = 2', () => {
  const rows = [goodLine(), goodLine(), goodLine({ quantity: '0' })];
  const result = validateSalesLines(rows, OPTIONS_MAP);
  assert.equal(result.ok, false);
  assert.equal(result.index, 2);
  assert.match(result.error, /第 3 行/);
});

// ───────────────────────── serializeSalesItems ─────────────────────────

test('serializeSalesItems: 只发 unit,⭐ 绝不发 factor（后端连这个字段都没有）', () => {
  const payload = serializeSalesItems([goodLine()]);
  assert.equal(payload.length, 1);
  assert.deepEqual(Object.keys(payload[0]).sort(), [
    'note',
    'product_id',
    'quantity',
    'unit',
    'unit_price',
  ]);
  assert.equal(payload[0].unit, '箱');
  assert.equal('unit_factor' in payload[0], false);
  assert.equal('factor' in payload[0], false);
});

test('serializeSalesItems: quantity 是数字 int,unit_price 是数字（后端是 int / float）', () => {
  const payload = serializeSalesItems([goodLine()]);
  assert.equal(payload[0].quantity, 3);
  assert.equal(typeof payload[0].quantity, 'number');
  assert.equal(payload[0].unit_price, 180);
  assert.equal(typeof payload[0].unit_price, 'number');
});

test('serializeSalesItems: 没选商品的行被丢掉（不产生 product_id=0 的垃圾明细）', () => {
  const payload = serializeSalesItems([goodLine(), makeEmptySalesLine()]);
  assert.equal(payload.length, 1);
});

test('serializeSalesItems: 单位为空时不发 unit 键（让后端走"未指定"路径）', () => {
  const payload = serializeSalesItems([goodLine({ unit: '' })]);
  assert.equal('unit' in payload[0], false);
});

test('serializeSalesItems: 单价空串兜底成 0（前端已拦,这里是最后一道,不发 NaN）', () => {
  const payload = serializeSalesItems([goodLine({ unit_price: '' })]);
  assert.equal(payload[0].unit_price, 0);
  assert.equal(Number.isNaN(payload[0].unit_price), false);
});

// ───────────────────────── summarizeLines ─────────────────────────

test('summarizeLines: 合计 = 各行录入金额之和（与后端 total_amount 同口径）', () => {
  const rows = [goodLine(), goodLine({ quantity: '2', unit_price: '90' })];
  const result = summarizeLines(rows, OPTIONS_MAP);
  assert.equal(result.lineCount, 2);
  assert.equal(result.amount, 540 + 180);
});

test('summarizeLines: 同一商品两行（1箱 + 5盒）的最小单位出库量合并成 17 盒', () => {
  const rows = [goodLine({ unit: '箱', quantity: '1' }), goodLine({ unit: '盒', quantity: '5' })];
  const result = summarizeLines(rows, OPTIONS_MAP);
  assert.equal(result.baseQtyByProduct.get(String(PRODUCT.id)), 17);
});

test('summarizeLines: 未选商品的行不计入', () => {
  const result = summarizeLines([goodLine(), makeEmptySalesLine()], OPTIONS_MAP);
  assert.equal(result.lineCount, 1);
});

test('summarizeLines: 金额按两位小数收敛（避免 0.1+0.2 的浮点尾数）', () => {
  const rows = [goodLine({ quantity: '3', unit_price: '0.1' }), goodLine({ quantity: '1', unit_price: '0.2' })];
  const result = summarizeLines(rows, OPTIONS_MAP);
  assert.equal(result.amount, 0.5);
});

test('summarizeLines: optionsByProduct 传普通对象也能用（不强制 Map）', () => {
  const plain = { [String(PRODUCT.id)]: buildUnitOptions(PRODUCT, UNIT_ROWS) };
  const result = summarizeLines([goodLine({ unit: '大箱', quantity: '1' })], plain);
  assert.equal(result.baseQtyByProduct.get(String(PRODUCT.id)), 48);
});
