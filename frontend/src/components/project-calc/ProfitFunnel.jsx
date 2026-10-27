/**
 * 图 A · 利润漏斗（v1.81.0）
 *
 * 五段：含税销售 → 不含税销售 → 不含税毛利 → 税前利润 → 净利。
 * 宽度全部按**含税销售额**的比例画，所以第一段永远是满宽 —— 这样"钱被谁吃掉多少"
 * 是一眼可比的，而不是四张各自缩放的图拼在一起。
 *
 * 纯手写 SVG（沿用 `TrendChart.jsx` 的约定，不引 ECharts）：
 *   · 没有 canvas、没有动画库，打印和截图都稳；
 *   · 精确值走 `<title>` 原生悬浮提示，不额外维护 tooltip 状态；
 *   · 文字用 currentColor / CSS 变量，换主题不用改这里。
 */
import { memo, useMemo } from 'react';
import { money, moneyWan, num, percent } from '../../lib/projectCalc';

const W = 660;
const H = 230;
const ROW_H = 30;
const GAP = 9;
const LABEL_W = 78;
const AMOUNT_W = 150;

const STAGES = [
  { key: 'sale_incl', label: '含税销售', tone: '#2563eb', source: 'summary' },
  { key: 'sale_excl', label: '不含税销售', tone: '#3b82f6', source: 'summary' },
  { key: 'gross_profit', label: '不含税毛利', tone: '#0891b2', source: 'summary' },
  { key: 'pretax_profit', label: '税前利润', tone: '#7c3aed', source: 'totals' },
  { key: 'net_profit', label: '税后净利', tone: '#16a34a', source: 'totals' },
];

function ProfitFunnel({ summary, totals }) {
  const rows = useMemo(() => {
    const base = Math.max(num(summary?.sale_incl), 1);
    const barMax = W - LABEL_W - AMOUNT_W;
    return STAGES.map((stage, index) => {
      const value = num((stage.source === 'summary' ? summary : totals)?.[stage.key]);
      const share = value / base;
      return {
        ...stage,
        value,
        share,
        width: Math.max(barMax * Math.min(share, 1), 3),
        y: index * (ROW_H + GAP),
        barMax,
      };
    });
  }, [summary, totals]);

  const hasData = rows[0].value > 0;

  return (
    <svg
      className="pc-chart__svg"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-labelledby="pc-funnel-title"
      preserveAspectRatio="xMidYMid meet"
    >
      <title id="pc-funnel-title">
        利润漏斗：含税销售 {money(summary?.sale_incl)}，不含税毛利 {money(summary?.gross_profit)}，
        税后净利 {money(totals?.net_profit)}
      </title>

      {rows.map((row) => (
        <g key={row.key} className="pc-funnel__row">
          <title>{`${row.label}：${money(row.value)}（占含税销售 ${percent(row.share)}）`}</title>
          <text x="0" y={row.y + 19} className="pc-chart__axis" fontSize="12">
            {row.label}
          </text>
          <rect
            x={LABEL_W}
            y={row.y}
            width={row.width}
            height={ROW_H}
            rx="6"
            fill={row.tone}
            opacity={row.key === 'net_profit' ? 1 : 0.86}
          />
          {row.width > 74 ? (
            <text x={LABEL_W + 10} y={row.y + 19} fontSize="11" fill="#fff" opacity="0.9">
              {percent(row.share, 1)}
            </text>
          ) : null}
          <text
            x={W}
            y={row.y + 19}
            textAnchor="end"
            fontSize="12.5"
            className="pc-chart__value"
          >
            {row.value >= 10000 ? `${moneyWan(row.value)}` : money(row.value)}
          </text>
        </g>
      ))}

      {!hasData ? (
        <text x={LABEL_W} y={H - 8} fontSize="12" className="pc-chart__axis">
          先填销售金额，漏斗才有形状
        </text>
      ) : (
        <text x={LABEL_W} y={H - 8} fontSize="11.5" className="pc-chart__axis">
          条形长度 = 占含税销售额的比例；净利率 {percent(totals?.net_margin)}
        </text>
      )}
    </svg>
  );
}

export default memo(ProfitFunnel);
