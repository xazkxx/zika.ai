/**
 * 销售出库明细行的两个「多单位」单元格（第三阶段 3c）
 *
 * 拆成两个组件是**为了列序可读**：一行是
 *
 *     商品 | 单位 | 数量 | 单价 | 实际出库（最小单位） | 删行
 *
 * 「实际出库」和「单位」之间隔着数量/单价，所以不能让一个组件一次吐两个格子 ——
 * 那样它要么被塞在错误的列上，要么就得靠 CSS `order` 硬掰，
 * 两种写法都会在下次改列序时咬人。父组件按顺序摆，谁在第几列一眼可见。
 *
 * ## ⚠️ 这里算出来的数量**不会**发给后端
 *
 * 请求体里只有 `unit`，没有 `factor`（`SalesOrderItemCreate` 连这个字段都没有）。
 * 服务端 `_resolve_unit_factor` 会从 `unit` 重新解析一遍。
 * 这里算的值只有一个用途：**让用户当场看见**。两遍必须一致 ——
 * 这正是 3c 验收要盯的那件事。
 *
 * 无第三方依赖、无全局污染。
 */

import {
  baseQuantity,
  describeConversion,
  resolveFactorFor,
  unitOptionLabel,
} from '../../lib/salesUnits';

/**
 * 单位下拉。选中项右侧的 `×12` 徽标只在真的会换算时出现。
 */
export default function UnitSelectCell({
  /** 当前商品的单位选项（`buildUnitOptions` 的产物）。空数组 = 该商品没有可用单位。 */
  options = [],
  /** 当前商品的基本单位，用于换算文案。 */
  baseUnit = '',
  /** 选中的单位名。空串 = 还没选。 */
  value = '',
  /** `(unitName: string) => void` */
  onChange,
  /** 商品还没选时把下拉禁掉 */
  disabled = false,
  /** 供测试定位用的行号 */
  rowIndex = 0,
}) {
  const factor = resolveFactorFor(options, value);
  const stale = options.some((option) => option.name === value && option.disabledOption);

  const hintText = (() => {
    if (stale) return '该单位已在商品档案里停用 —— 保存会被服务端拒绝，请换成在用的单位';
    if (!value) return '请选择单位（默认按基本单位出库）';
    if (!baseUnit) return '该商品还没填基本单位，无法换算';
    return `1 ${value} = ${factor} ${baseUnit}`;
  })();

  return (
    <label>
      单位
      <div className="sunit-unit-cell">
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || options.length === 0}
          data-sunit-unit={rowIndex}
        >
          <option value="">{disabled ? '请先选择商品' : '请选择单位'}</option>
          {options.map((option) => (
            <option key={option.name} value={option.name} disabled={option.disabledOption}>
              {unitOptionLabel(option, baseUnit)}
            </option>
          ))}
        </select>
        {factor > 1 ? <span className="sunit-factor-badge">×{factor}</span> : null}
      </div>
      <span className={`sunit-unit-hint${stale ? ' is-stale' : ''}`} data-sunit-hint={rowIndex}>
        {hintText}
      </span>
    </label>
  );
}

/**
 * 「实际出库（最小单位）」列 —— 3c 前端最核心的一格。
 *
 * 用户选「箱」之后，**这里**告诉他库存到底会动多少个。
 * 会换算时整格换成蓝底，一眼能看出这一行不是按基本单位出的货。
 */
export function BaseQuantityCell({
  options = [],
  baseUnit = '',
  unit = '',
  quantity = '',
  /** 没选商品时整格显示 —：此时"1"这种默认数量毫无意义，显示出来是误导 */
  disabled = false,
  rowIndex = 0,
}) {
  const factor = resolveFactorFor(options, unit);
  const total = disabled ? null : baseQuantity(quantity, factor);
  const converted = !disabled && factor > 1;

  return (
    <div
      className={`sunit-base-qty${converted ? ' is-converted' : ''}`}
      data-sunit-base={rowIndex}
    >
      <small>实际出库（最小单位）</small>
      <strong data-sunit-base-value={rowIndex}>
        {total === null ? '—' : `${total} ${baseUnit || ''}`.trim()}
      </strong>
      <small data-sunit-base-eq={rowIndex}>
        {disabled ? '选择商品后自动换算' : describeConversion(quantity, factor, unit, baseUnit)}
      </small>
    </div>
  );
}
