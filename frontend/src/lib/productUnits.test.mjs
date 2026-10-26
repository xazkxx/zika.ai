/**
 * 商品辅助单位纯逻辑的回归测试（第三阶段 3a）。
 *
 * 跑法：
 *   node --test src/lib/productUnits.test.mjs
 *   # 或在本目录：node --test productUnits.test.mjs
 *
 * 重点不是覆盖率，而是把「会让库存静默算错」的那几条**钉死**：
 *   · `factor` 只收 ≥2 的整数（小数 / 0 / 1 / 空串 / 科学计数全拒）
 *   · 辅助单位名不能等于基本单位名、不能互相重名
 *   · 默认辅助单位最多一个；包装数镜像只认默认那一行
 *   · 空串价格必须变 null（后端 `Optional[float]` 收 `''` 直接 422）
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  MAX_UNITS_PER_PRODUCT,
  UNIT_FACTOR_MAX,
  UNIT_FACTOR_MIN,
  defaultUnitName,
  describeFactor,
  factorIsValid,
  makeEmptyUnitDraft,
  normalizeUnitName,
  packQtyMirror,
  serializeUnits,
  setDefaultUnit,
  unitToDraft,
  unitsToDrafts,
  validateUnits,
} from './productUnits.js';

// ───────────────────────────────────────────────────────────────────────────
// factorIsValid —— 整个设计的安全阀
// ───────────────────────────────────────────────────────────────────────────

test('factorIsValid：只收 ≥2 的整数', () => {
  // 合法
  for (const value of [2, 3, 10, 12, 24, 100, '2', '10', ' 12 ', UNIT_FACTOR_MAX, String(UNIT_FACTOR_MAX)]) {
    assert.equal(factorIsValid(value), true, `应接受 ${JSON.stringify(value)}`);
  }

  // 非法：这些问题全都会让"只乘不除"的前提崩掉
  for (const value of [
    1, '1', // 与基本单位重复，无意义
    0, '0', // 空值被误当成 0 的经典陷阱
    -3, '-3', // 负数
    2.5, '2.5', 0.1, '0.1', // 小数 —— 一旦允许，方向就可能反
    '', '   ', null, undefined, // 空输入（Number('') === 0 的陷阱）
    'abc', '2箱', '1e3', '0x10', 'NaN', // 非纯数字串
    UNIT_FACTOR_MAX + 1, // 超出上限
  ]) {
    assert.equal(factorIsValid(value), false, `应拒绝 ${JSON.stringify(value)}`);
  }
});

test('factorIsValid：小数被拒 —— 这是"库存静默消失"的第一道闸', () => {
  // 记下这条规则为什么存在：如果允许 0.1，
  // 后端 int(3 × 0.1) === 0，而 _apply_stock 判到 qty === 0 会**一条流水都不写**。
  assert.equal(factorIsValid('0.1'), false);
  assert.equal(factorIsValid('1.0'), false, '即便数值等于整数，字符串带小数点也应拒绝');
  assert.equal(Math.trunc(3 * 0.1), 0, '后端会算成 0（这条断言就是上面的理由）');
});

test('UNIT_FACTOR_MIN / MAX 的边界与常量本身一致', () => {
  assert.equal(UNIT_FACTOR_MIN, 2);
  assert.equal(UNIT_FACTOR_MAX, 999999);
  assert.equal(factorIsValid(UNIT_FACTOR_MIN - 1), false);
  assert.equal(factorIsValid(UNIT_FACTOR_MIN), true);
  assert.equal(factorIsValid(UNIT_FACTOR_MAX), true);
  assert.equal(factorIsValid(UNIT_FACTOR_MAX + 1), false);
});

// ───────────────────────────────────────────────────────────────────────────
// normalizeUnitName / makeEmptyUnitDraft
// ───────────────────────────────────────────────────────────────────────────

test('normalizeUnitName：只 trim，不动其它字符', () => {
  assert.equal(normalizeUnitName('  箱  '), '箱');
  assert.equal(normalizeUnitName('盒'), '盒');
  assert.equal(normalizeUnitName(null), '');
  assert.equal(normalizeUnitName(undefined), '');
  assert.equal(normalizeUnitName(0), '0');
  assert.equal(normalizeUnitName('  '), '');
});

test('makeEmptyUnitDraft：换算率预填 2（逼用户看见它并改）', () => {
  const draft = makeEmptyUnitDraft();
  assert.deepEqual(draft, {
    unit_name: '',
    factor: '2',
    price: '',
    sale_price: '',
    bar_code: '',
    is_default: false,
    is_enabled: true,
    note: '',
  });
  assert.equal(factorIsValid(draft.factor), true, '预填值本身必须是合法的');
});

// ───────────────────────────────────────────────────────────────────────────
// 接口行 ⇄ 表单行
// ───────────────────────────────────────────────────────────────────────────

test('unitToDraft：数字转字符串、空值归一、布尔保留', () => {
  assert.deepEqual(
    unitToDraft({
      id: 9,
      product_id: 5,
      unit_name: '箱',
      factor: 10,
      price: 25.5,
      sale_price: 30,
      bar_code: 'BC-1',
      is_default: true,
      is_enabled: false,
      note: '备注',
      sort_order: 0,
      created_at: '2026-10-16T00:00:00Z',
    }),
    {
      unit_name: '箱',
      factor: '10',
      price: 25.5,
      sale_price: 30,
      bar_code: 'BC-1',
      is_default: true,
      is_enabled: false,
      note: '备注',
    },
  );
});

test('unitToDraft：字段缺失时给安全默认值（不产生 undefined 受控输入）', () => {
  const draft = unitToDraft({ unit_name: '打' });
  assert.equal(draft.factor, '2');
  assert.equal(draft.price, '');
  assert.equal(draft.sale_price, '');
  assert.equal(draft.bar_code, '');
  assert.equal(draft.is_default, false);
  assert.equal(draft.is_enabled, true, 'is_enabled 缺失时按"启用"处理，与数据库默认值一致');
  assert.equal(draft.note, '');
  // 关键：任何字段都不能是 undefined —— 否则 React 会把受控输入降级成非受控
  for (const [key, value] of Object.entries(draft)) {
    assert.notEqual(value, undefined, `${key} 不应是 undefined`);
  }
});

test('unitToDraft：factor 为 null/空串时回落到 2，而不是 NaN', () => {
  assert.equal(unitToDraft({ factor: null }).factor, '2');
  assert.equal(unitToDraft({ factor: undefined }).factor, '2');
  assert.equal(unitToDraft({ factor: '' }).factor, '2');
  assert.equal(unitToDraft({ factor: 0 }).factor, '0', '0 要如实显示出来让人看见它是错的');
});

test('unitsToDrafts：非数组输入安全返回空数组', () => {
  assert.deepEqual(unitsToDrafts(undefined), []);
  assert.deepEqual(unitsToDrafts(null), []);
  assert.deepEqual(unitsToDrafts('箱'), []);
  assert.equal(unitsToDrafts([{ unit_name: '箱' }, { unit_name: '打' }]).length, 2);
});

// ───────────────────────────────────────────────────────────────────────────
// describeFactor
// ───────────────────────────────────────────────────────────────────────────

test('describeFactor：正常情况给出「1 X = N 基本单位」', () => {
  assert.equal(describeFactor(10, '箱', '盒'), '1 箱 = 10 盒');
  assert.equal(describeFactor('12', ' 打 ', ' 支 '), '1 打 = 12 支');
  assert.equal(describeFactor(2, '套', '个'), '1 套 = 2 个');
});

test('describeFactor：非法/缺失时明确显示 ? 或占位，不猜', () => {
  assert.equal(describeFactor('', '箱', '盒'), '1 箱 = ? 盒');
  assert.equal(describeFactor('1', '箱', '盒'), '1 箱 = ? 盒');
  assert.equal(describeFactor('2.5', '箱', '盒'), '1 箱 = ? 盒');
  assert.equal(describeFactor(10, '', '盒'), '1 （未命名） = 10 盒');
  assert.equal(describeFactor(10, '箱', ''), '1 箱 = 10 （未填基本单位）');
});

// ───────────────────────────────────────────────────────────────────────────
// setDefaultUnit / packQtyMirror / defaultUnitName
// ───────────────────────────────────────────────────────────────────────────

test('setDefaultUnit：radio 语义 —— 设了新的就取消其余全部', () => {
  const drafts = [
    { unit_name: '箱', factor: '10', is_default: true },
    { unit_name: '打', factor: '12', is_default: false },
    { unit_name: '托盘', factor: '240', is_default: false },
  ];
  const after = setDefaultUnit(drafts, 1);
  assert.deepEqual(
    after.map((d) => d.is_default),
    [false, true, false],
  );
  assert.equal(after.filter((d) => d.is_default).length, 1, '任何时刻最多一个默认');
  assert.equal(after[1].unit_name, '打');

  // 不修改原数组（纯函数）
  assert.deepEqual(
    drafts.map((d) => d.is_default),
    [true, false, false],
  );
});

test('setDefaultUnit：非数组输入安全', () => {
  assert.deepEqual(setDefaultUnit(undefined, 0), []);
});

test('packQtyMirror：默认辅助单位的换算率，没有默认则 null', () => {
  assert.equal(packQtyMirror([{ factor: '10', is_default: true }]), 10);
  assert.equal(packQtyMirror([{ factor: '10', is_default: false }]), null, '不自动挑一行当默认');
  assert.equal(packQtyMirror([]), null);
  assert.equal(packQtyMirror(undefined), null);
  assert.equal(
    packQtyMirror([
      { factor: '10', is_default: false },
      { factor: '24', is_default: true },
    ]),
    24,
    '只认勾了默认的那一行，跟它在数组里的位置无关',
  );
});

test('packQtyMirror：默认那行的换算率非法时返回 null（不把脏值写进包装数）', () => {
  assert.equal(packQtyMirror([{ factor: '1', is_default: true }]), null);
  assert.equal(packQtyMirror([{ factor: '', is_default: true }]), null);
  assert.equal(packQtyMirror([{ factor: '2.5', is_default: true }]), null);
});

test('defaultUnitName：拿到默认那行的单位名（trim 过）', () => {
  assert.equal(
    defaultUnitName([
      { unit_name: '箱', is_default: false },
      { unit_name: '  打  ', is_default: true },
    ]),
    '打',
  );
  assert.equal(defaultUnitName([{ unit_name: '箱', is_default: false }]), '');
  assert.equal(defaultUnitName(undefined), '');
});

// ───────────────────────────────────────────────────────────────────────────
// validateUnits
// ───────────────────────────────────────────────────────────────────────────

test('validateUnits：空表永远合法（没配辅助单位就是现状）', () => {
  assert.equal(validateUnits([], '盒').ok, true);
  assert.equal(validateUnits(undefined, '盒').ok, true);
  assert.equal(validateUnits(null, '').ok, true, '没单位又没辅助单位 = 合法');
});

test('validateUnits：有辅助单位但没填基本单位 → 拦下', () => {
  const result = validateUnits([{ unit_name: '箱', factor: '10' }], '');
  assert.equal(result.ok, false);
  assert.equal(result.index, -1);
  assert.match(result.error, /请先填上面的「单位」/);
});

test('validateUnits：合法表通过', () => {
  const result = validateUnits(
    [
      { unit_name: '盒', factor: '2' },
      { unit_name: '箱', factor: '10', is_default: true },
      { unit_name: '托盘', factor: '240', bar_code: 'T-1' },
    ],
    '个',
  );
  assert.deepEqual(result, { ok: true, index: -1, error: '' });
});

test('validateUnits：单位名为空 → 定位到那一行', () => {
  const result = validateUnits(
    [
      { unit_name: '箱', factor: '10' },
      { unit_name: '   ', factor: '10' },
    ],
    '盒',
  );
  assert.equal(result.ok, false);
  assert.equal(result.index, 1);
  assert.match(result.error, /第 2 行/);
  assert.match(result.error, /名称不能为空/);
});

test('validateUnits：辅助单位名等于基本单位名 → 单独一句提示', () => {
  const result = validateUnits([{ unit_name: '箱', factor: '10' }], '箱');
  assert.equal(result.ok, false);
  assert.equal(result.index, 0);
  assert.match(result.error, /和本商品的基本单位重名了/);
  assert.match(result.error, /必须比基本单位大/);
});

test('validateUnits：辅助单位之间重名 → 与基本单位重名区分开', () => {
  const result = validateUnits(
    [
      { unit_name: '箱', factor: '10' },
      { unit_name: ' 箱 ', factor: '12' },
    ],
    '盒',
  );
  assert.equal(result.ok, false);
  assert.equal(result.index, 1);
  assert.match(result.error, /和上面的辅助单位重复了/);
  assert.doesNotMatch(result.error, /基本单位重名/);
});

test('validateUnits：换算率非法 → 提示里带上单位名和基本单位名', () => {
  const bad = ['', '1', '0', '2.5', 'abc', '-3'];
  for (const factor of bad) {
    const result = validateUnits([{ unit_name: '箱', factor }], '盒');
    assert.equal(result.ok, false, `factor=${JSON.stringify(factor)} 应被拒`);
    assert.equal(result.index, 0);
    assert.match(result.error, /换算率要填 ≥2 的整数/);
    assert.match(result.error, /「箱」/);
    assert.match(result.error, /几个盒/);
  }
});

test('validateUnits：条码重复被拦；条码为空的行互不冲突', () => {
  const dup = validateUnits(
    [
      { unit_name: '箱', factor: '10', bar_code: 'BC-1' },
      { unit_name: '打', factor: '12', bar_code: ' BC-1 ' },
    ],
    '盒',
  );
  assert.equal(dup.ok, false);
  assert.equal(dup.index, 1);
  assert.match(dup.error, /条码「BC-1」和上面重复了/);

  const blanks = validateUnits(
    [
      { unit_name: '箱', factor: '10', bar_code: '' },
      { unit_name: '打', factor: '12', bar_code: '' },
      { unit_name: '托盘', factor: '240' },
    ],
    '盒',
  );
  assert.equal(blanks.ok, true, '多个空条码必须允许（数据库那边也是这个口径）');
});

test('validateUnits：多个默认 → 拦下；一个默认 → 通过', () => {
  const two = validateUnits(
    [
      { unit_name: '箱', factor: '10', is_default: true },
      { unit_name: '打', factor: '12', is_default: true },
    ],
    '盒',
  );
  assert.equal(two.ok, false);
  assert.equal(two.index, -1);
  assert.match(two.error, /只能把一个辅助单位设为默认/);

  const one = validateUnits(
    [
      { unit_name: '箱', factor: '10', is_default: true },
      { unit_name: '打', factor: '12', is_default: false },
    ],
    '盒',
  );
  assert.equal(one.ok, true);
});

test('validateUnits：超过上限被拦（与后端 MAX_PRODUCT_UNITS 同口径）', () => {
  const many = Array.from({ length: MAX_UNITS_PER_PRODUCT + 1 }, (_, i) => ({
    unit_name: `U${i}`,
    factor: '2',
  }));
  const result = validateUnits(many, '盒');
  assert.equal(result.ok, false);
  assert.equal(result.index, -1);
  assert.match(result.error, new RegExp(`最多 ${MAX_UNITS_PER_PRODUCT} 个`));

  const atLimit = many.slice(0, MAX_UNITS_PER_PRODUCT);
  assert.equal(validateUnits(atLimit, '盒').ok, true, '正好到上限应通过');
});

test('validateUnits：校验顺序 —— 先报靠前的错', () => {
  // 第 0 行合法、第 1 行名称空、第 2 行换算率错
  const result = validateUnits(
    [
      { unit_name: '箱', factor: '10' },
      { unit_name: '', factor: '10' },
      { unit_name: '打', factor: '0' },
    ],
    '盒',
  );
  assert.equal(result.index, 1, '应报第 2 行（索引 1），而不是更靠后的换算率错');
});

// ───────────────────────────────────────────────────────────────────────────
// serializeUnits
// ───────────────────────────────────────────────────────────────────────────

test('serializeUnits：空串价格/条码/备注一律转 null（后端 Optional[float] 收 "" 会 422）', () => {
  const payload = serializeUnits([
    {
      unit_name: ' 箱 ',
      factor: '10',
      price: '',
      sale_price: '',
      bar_code: '   ',
      is_default: true,
      is_enabled: true,
      note: '',
    },
  ]);
  assert.deepEqual(payload, [
    {
      unit_name: '箱',
      factor: 10,
      price: null,
      sale_price: null,
      bar_code: null,
      is_default: true,
      is_enabled: true,
      note: null,
    },
  ]);
});

test('serializeUnits：factor 是真数字，不是字符串', () => {
  const [unit] = serializeUnits([{ unit_name: '箱', factor: '10' }]);
  assert.equal(typeof unit.factor, 'number');
  assert.equal(unit.factor, 10);
  assert.ok(Number.isInteger(unit.factor), '必须是整数 —— 后端 schema 是 int');
});

test('serializeUnits：is_enabled 缺失按 true；显式 false 保留', () => {
  assert.equal(serializeUnits([{ unit_name: '箱', factor: '2' }])[0].is_enabled, true);
  assert.equal(serializeUnits([{ unit_name: '箱', factor: '2', is_enabled: false }])[0].is_enabled, false);
  assert.equal(serializeUnits([{ unit_name: '箱', factor: '2', is_enabled: 0 }])[0].is_enabled, false);
  assert.equal(serializeUnits([{ unit_name: '箱', factor: '2', is_default: 'yes' }])[0].is_default, true);
});

test('serializeUnits：数字价格原样保留（含 0）', () => {
  const [unit] = serializeUnits([{ unit_name: '箱', factor: '10', price: 0, sale_price: '25.50' }]);
  assert.equal(unit.price, 0, '0 是有效价格，不能被当成空');
  assert.equal(unit.sale_price, 25.5);
});

test('serializeUnits：非数组输入安全', () => {
  assert.deepEqual(serializeUnits(undefined), []);
  assert.deepEqual(serializeUnits(null), []);
});

test('serializeUnits 的输出形状与后端 ProductUnitInput 逐键对齐', () => {
  const keys = Object.keys(serializeUnits([makeEmptyUnitDraft()])[0]).sort();
  assert.deepEqual(keys, [
    'bar_code',
    'factor',
    'is_default',
    'is_enabled',
    'note',
    'price',
    'sale_price',
    'unit_name',
  ]);
});

// ───────────────────────────────────────────────────────────────────────────
// 往返一致性
// ───────────────────────────────────────────────────────────────────────────

test('取回 → 提交 的往返不丢数据（除了有意归一化的空值）', () => {
  const serverRows = [
    {
      id: 1,
      product_id: 7,
      unit_name: '箱',
      factor: 10,
      price: 25.5,
      sale_price: 30,
      bar_code: 'BC-1',
      is_default: true,
      is_enabled: true,
      note: '整箱',
      sort_order: 0,
      created_at: '2026-10-16T00:00:00Z',
    },
    {
      id: 2,
      product_id: 7,
      unit_name: '打',
      factor: 12,
      price: null,
      sale_price: null,
      bar_code: null,
      is_default: false,
      is_enabled: false,
      note: null,
      sort_order: 1,
      created_at: '2026-10-16T00:00:00Z',
    },
  ];

  const payload = serializeUnits(unitsToDrafts(serverRows));
  assert.deepEqual(payload, [
    {
      unit_name: '箱',
      factor: 10,
      price: 25.5,
      sale_price: 30,
      bar_code: 'BC-1',
      is_default: true,
      is_enabled: true,
      note: '整箱',
    },
    {
      unit_name: '打',
      factor: 12,
      price: null,
      sale_price: null,
      bar_code: null,
      is_default: false,
      is_enabled: false,
      note: null,
    },
  ]);

  // 往返后仍然是合法的 —— 否则"打开弹窗什么都不改直接保存"就会报错
  assert.equal(validateUnits(unitsToDrafts(serverRows), '盒').ok, true);
});
