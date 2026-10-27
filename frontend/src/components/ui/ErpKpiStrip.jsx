/**
 * ErpKpiStrip —— 单据页顶部的「KPI 计量条」（v1.78.0，UI 标准铺开第二批）
 *
 * 为什么要抽成组件：
 *   增强对账单里那排「期初 / 本期新增 / 已开票 / 已收 / 期末应收」卡片，
 *   视觉上是**一条连续的计量条**（无边框、分段线、末段蓝条点睛），
 *   而不是五个各自带边框的小盒子 —— 后者看起来像五块互不相干的报表。
 *   订单页 / 开单页也要同一套，所以把 `.stmt__cards` 那套做法提炼成
 *   `.erp-kpi*` 独立命名空间（**不改** styles.css 里的既有卡片样式）。
 *
 * 三条设计约束：
 *   ① 只用 CSS 变量与 flex/grid，不依赖任何业务 class —— 任何页面都能放；
 *   ② 数字列用 `tabular-nums`：金额滚动时不抖动（对账页踩过这个坑）；
 *   ③ `strong` 的那一格加顶部 3px 主色条 + 浅色渐变底，一屏只允许一个
 *      （它代表"这张单最终要盯的那个数"）。
 *
 * 用法：
 *   <ErpKpiStrip
 *     items={[
 *       { key: 'count', label: '本页单据', value: '12 张', hint: '含已转单' },
 *       { key: 'amount', label: '金额合计', value: '¥123,456.00', strong: true },
 *     ]}
 *   />
 */

import './erp-kpi-strip.css';

export default function ErpKpiStrip({
  /** [{ key, label, value, hint?, title?, strong? }] */
  items = [],
  /** 固定列数；不传则按项目数自动铺满一行 */
  columns,
  /** 紧凑形态：单据页内嵌在列表卡头部时用（行高更小） */
  dense = false,
  className = '',
  style,
  ...rest
}) {
  if (!items.length) return null;

  // 外部 style 要能叠加（往来账那页用它加 marginTop），所以合并而不是整体覆盖
  const mergedStyle = {
    '--erp-kpi-cols': String(columns || items.length),
    ...(style || {}),
  };

  return (
    <div
      className={`erp-kpi${dense ? ' erp-kpi--dense' : ''}${className ? ` ${className}` : ''}`}
      style={mergedStyle}
      data-erp-kpi
      {...rest}
    >
      {items.map((item) => (
        <div
          key={item.key}
          className={`erp-kpi__cell${item.strong ? ' erp-kpi__cell--strong' : ''}`}
          title={item.title || undefined}
        >
          <span className="erp-kpi__label">{item.label}</span>
          <b className="erp-kpi__value">{item.value == null || item.value === '' ? '—' : item.value}</b>
          {item.hint ? <span className="erp-kpi__hint">{item.hint}</span> : null}
        </div>
      ))}
    </div>
  );
}
