/**
 * 图 C · 税负结构环形图（v1.81.0）
 *
 * 七个税种共用一个圆环。画法用 `stroke-dasharray` 而不是 path 三角函数：
 *   · 一圈 = 圆周长 C，某段的 dash 长度 = 占比 × C，剩下的空白 = C − dash；
 *   · 每段用 `stroke-dashoffset` 负值推到自己的起点，从 12 点方向开始顺时针排；
 *   · 好处：没有一条手算的贝塞尔坐标，改半径/线宽不会算错角。
 *
 * 两个诚实处理：
 *   · 增值税为负（留抵）时它不进环 —— 环里放负数会自我抵消，看着像"没交税"；
 *     图例里仍然显示真实值（红色），并在环心下方写明"含留抵"。
 *   · 占比 < 2% 的段在环上仍然画（哪怕只有 1px），不做合并：
 *     合并后"其他"这根色带会让老板以为有个叫"其他"的税种。
 */
import { memo, useMemo } from 'react';
import { money, moneyWan, num, percent } from '../../lib/projectCalc';

const W = 660;
const H = 236;
const CX = 112;
const CY = 114;
const R = 76;
const STROKE = 26;
const C = 2 * Math.PI * R;

const PALETTE = {
  vat: '#2563eb',
  city: '#0891b2',
  edu: '#0d9488',
  ledu: '#65a30d',
  stamp: '#f59e0b',
  water: '#c026d3',
  income: '#dc2626',
};

function TaxDonut({ taxes, totals, summary }) {
  const segments = useMemo(() => {
    const list = (taxes || []).map((tax, index) => ({
      ...tax,
      value: num(tax.amount),
      color: PALETTE[tax.key] || '#64748b',
      index,
    }));
    const positiveTotal = list.reduce((sum, tax) => sum + Math.max(tax.value, 0), 0);
    let offset = 0;
    return list.map((tax) => {
      const share = positiveTotal > 0 ? Math.max(tax.value, 0) / positiveTotal : 0;
      const dash = share * C;
      const segment = { ...tax, share, dash, offset };
      offset += dash;
      return segment;
    });
  }, [taxes]);

  const taxTotal = num(totals?.tax_total);
  const saleExcl = num(summary?.sale_excl);
  const burden = saleExcl > 0 ? taxTotal / saleExcl : 0;
  const hasCredit = segments.some((tax) => tax.key === 'vat' && tax.value < 0);

  return (
    <svg
      className="pc-chart__svg"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-labelledby="pc-tax-title"
      preserveAspectRatio="xMidYMid meet"
    >
      <title id="pc-tax-title">
        税负结构：税金合计 {money(taxTotal)}，占不含税销售额 {percent(burden)}
      </title>

      {/* 底环：数据为 0 时也有个圆，不至于空一块 */}
      <circle cx={CX} cy={CY} r={R} fill="none" stroke="var(--border)" strokeWidth={STROKE} opacity="0.45" />

      <g transform={`rotate(-90 ${CX} ${CY})`}>
        {segments
          .filter((tax) => tax.dash > 0)
          .map((tax) => (
            <circle
              key={tax.key}
              cx={CX}
              cy={CY}
              r={R}
              fill="none"
              stroke={tax.color}
              strokeWidth={STROKE}
              strokeDasharray={`${Math.max(tax.dash - 1.5, 0.6)} ${C}`}
              strokeDashoffset={-tax.offset}
              strokeLinecap="butt"
            >
              <title>{`${tax.label}：${money(tax.value)}（占税金 ${percent(tax.share)}）`}</title>
            </circle>
          ))}
      </g>

      <text x={CX} y={CY - 16} textAnchor="middle" fontSize="11.5" className="pc-chart__axis">
        税金合计
      </text>
      <text x={CX} y={CY + 12} textAnchor="middle" fontSize="17" className="pc-chart__value">
        {moneyWan(taxTotal)}
      </text>
      <text x={CX} y={CY + 34} textAnchor="middle" fontSize="11.5" className="pc-chart__axis">
        占销售额 {percent(burden)}
        {hasCredit ? '（含留抵）' : ''}
      </text>

      {/* 图例：逐项列金额，老板要往微信里发数字，所以文本可选中 */}
      {segments.map((tax, index) => {
        const y = 26 + index * 25;
        return (
          <g key={tax.key}>
            <title>{`${tax.label}：基数 ${money(tax.base)} × ${percent(tax.rate, 4)} = ${money(tax.value)}`}</title>
            <rect x="258" y={y - 9} width="10" height="10" rx="2" fill={tax.color} />
            <text x="276" y={y} fontSize="12" className="pc-chart__axis">
              {tax.label}
            </text>
            <text
              x={W - 66}
              y={y}
              textAnchor="end"
              fontSize="12"
              className={`pc-chart__value${tax.value < 0 ? ' is-negative' : ''}`}
            >
              {money(tax.value)}
            </text>
            <text x={W} y={y} textAnchor="end" fontSize="11.5" className="pc-chart__axis">
              {tax.value > 0 ? percent(tax.share, 1) : '留抵'}
            </text>
          </g>
        );
      })}

      <text x="258" y={H - 10} fontSize="11" className="pc-chart__axis">
        增值税与附加税已减半计（六税两费）；所得税按税前利润 5%
      </text>
    </svg>
  );
}

export default memo(TaxDonut);
