/**
 * 图 B · 资金占用（v1.81.0）
 *
 * 上半：两根柱 —— 垫资额 / 占用费，**同一根轴**（元）。占用费通常只有垫资的零点几个点，
 *       所以给它一个 4px 的最小可见高度，并在旁边直说"占垫资 x%"：
 *       偷着换一套轴虽然"好看"，但会让老板误以为占用费有垫资的十分之一。
 * 下半：回款天数 → 落袋净利 的折线（数据来自后端 `sensitivity`）。
 *       付款周期固定，只动回款 —— 这一条比"占用费"本身更有决策价值：
 *       账期每拖 30 天，净利掉多少，一眼可见。
 *
 * 纯 SVG，不用 canvas；精确值走 <title>。
 */
import { memo, useMemo } from 'react';
import { money, moneyWan, num, percent } from '../../lib/projectCalc';

const W = 660;
const H = 236;
const BAR_MAX = 520;

function CapitalBars({ capital, sensitivity }) {
  const advance = num(capital?.advance);
  const fee = num(capital?.fee);
  const feeShare = advance > 0 ? fee / advance : 0;

  const line = useMemo(() => {
    const rows = (sensitivity || []).map((row) => ({
      days: num(row.collect_days),
      net: num(row.net_after_fee),
    }));
    if (rows.length < 2) return null;
    const values = rows.map((row) => row.net);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || Math.max(max * 0.02, 1);
    const x0 = 52;
    const x1 = W - 24;
    const yTop = 184;
    const yBot = 214;
    const points = rows.map((row, index) => ({
      ...row,
      x: x0 + ((x1 - x0) * index) / (rows.length - 1),
      y: yBot - ((row.net - min) / span) * (yBot - yTop),
    }));
    return { points, min, max, yTop, yBot };
  }, [sensitivity]);

  return (
    <svg
      className="pc-chart__svg"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-labelledby="pc-capital-title"
      preserveAspectRatio="xMidYMid meet"
    >
      <title id="pc-capital-title">
        资金占用：垫资 {money(advance)}，占用 {num(capital?.occupy_days)} 天，资金成本 {money(fee)}，
        扣掉资金成本后净利 {money(capital?.net_after_fee)}
      </title>

      {/* —— 垫资额 —— */}
      <text x="0" y="12" fontSize="12" className="pc-chart__axis">
        垫资额
      </text>
      <rect x="0" y="20" width={Math.max((BAR_MAX * Math.min(advance / Math.max(advance, fee, 1), 1)), 3)} height="26" rx="5" fill="#2563eb" opacity="0.9" />
      <text x="10" y="38" fontSize="12.5" fill="#fff">
        {money(advance)}
      </text>

      {/* —— 占用费（同轴，最小可见高度；旁边直说占比）—— */}
      <text x="0" y="70" fontSize="12" className="pc-chart__axis">
        占用费
      </text>
      <rect
        x="0"
        y="78"
        width={Math.max((advance > 0 ? BAR_MAX * (fee / advance) : 0), fee > 0 ? 4 : 0)}
        height="26"
        rx="5"
        fill="#f59e0b"
      />
      <text x={advance > 0 && fee / advance > 0.18 ? 10 : (fee > 0 ? BAR_MAX * (fee / advance) + 10 : 10)} y="96" fontSize="12.5" fill={advance > 0 && fee / advance > 0.18 ? '#fff' : 'var(--fg)'}>
        {money(fee)}
        {advance > 0 ? `　占垫资 ${percent(feeShare, 2)}` : ''}
      </text>

      <text x="0" y="124" fontSize="11.5" className="pc-chart__axis">
        {advance > 0
          ? `占用 ${num(capital?.occupy_days)} 天 × 日利率 ${percent(capital?.daily_rate, 2)}（年化 ${percent(capital?.annual_rate, 2)}）`
          : '预收 + 定金已覆盖成本与税费，本项目不需要垫资'}
      </text>

      <line x1="0" y1="144" x2={W} y2="144" stroke="var(--border)" strokeWidth="1" />

      {/* —— 回款拖久的代价 —— */}
      {line ? (
        <>
          <text x="0" y="164" fontSize="12" className="pc-chart__axis">
            回款拖久的代价（净利）
          </text>
          <polyline
            points={line.points.map((point) => `${point.x},${point.y}`).join(' ')}
            fill="none"
            stroke="#16a34a"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {line.points.map((point) => (
            <g key={point.days}>
              <title>{`回款 ${point.days} 天：净利 ${money(point.net)}`}</title>
              <circle cx={point.x} cy={point.y} r="3.2" fill="#fff" stroke="#16a34a" strokeWidth="2" />
              <text x={point.x} y={H - 6} textAnchor="middle" fontSize="11" className="pc-chart__axis">
                {point.days} 天
              </text>
              <text x={point.x} y={point.y - 9} textAnchor="middle" fontSize="11" className="pc-chart__value">
                {moneyWan(point.net)}
              </text>
            </g>
          ))}
        </>
      ) : (
        <text x="0" y="176" fontSize="12" className="pc-chart__axis">
          回款敏感性需要至少两组数据
        </text>
      )}
    </svg>
  );
}

export default memo(CapitalBars);
