import { memo } from 'react';
import { buildPath, fmtByUnit } from './dashboardUtils';

/* ==========================================================================
 * <KpiCards /> —— 顶部 4 个 KPI 卡片
 * ---------------------------------------------------------------------------
 * props:
 *   items    {KpiItem[]}  为空时渲染骨架屏
 *   loading  {boolean}
 *
 * 性能：整块用 memo 包住，只有 items 引用变化时才重渲染。
 * ========================================================================== */

/** @type {Record<import('./dashboardApi').Trend, string>} */
const TREND_ICON = { up: '▲', down: '▼', flat: '—' };

/**
 * 迷你趋势线：纯 SVG，无依赖
 * @param {{ data: number[], color: string }} props
 */
const Sparkline = memo(function Sparkline({ data, color }) {
  const w = 84;
  const h = 28;
  const pad = 3;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = (w - pad * 2) / (data.length - 1 || 1);
  const points = data.map((v, i) => ({
    x: pad + i * step,
    y: h - pad - ((v - min) / span) * (h - pad * 2),
  }));

  return (
    <svg className="erpdash-kpi__spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path
        d={buildPath(points)}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
});

/**
 * 反向指标状态标
 *
 * 待处理订单 / 库存预警 / 应收账款 属于「涨了是坏事」，
 * 光靠红色上涨箭头容易被误读成业务增长，所以额外给一个语义标。
 * 色值仍严格跟随数值方向（涨红跌绿），好坏由这个标签表达。
 *
 * @param {{ polarity: import('./dashboardApi').Polarity, trend: import('./dashboardApi').Trend }} props
 */
function StatusChip({ polarity, trend }) {
  if (polarity !== 'inverse') return null;
  const isWarn = trend === 'up';
  return (
    <span className={`erpdash-kpi__chip erpdash-kpi__chip--${isWarn ? 'warn' : 'ok'}`}>
      {isWarn ? '需关注' : '正常'}
    </span>
  );
}

/** @param {{ item: import('./dashboardApi').KpiItem }} props */
const KpiCard = memo(function KpiCard({ item }) {
  const { key, label, value, unit, delta, trend, note, polarity, color, spark } = item;
  const sign = trend === 'flat' ? '' : delta > 0 ? '+' : '';

  return (
    <div className="erpdash-kpi" data-key={key}>
      <div className="erpdash-kpi__label">
        <span className="erpdash-kpi__dot" style={{ background: color }} />
        {label}
      </div>

      <div className="erpdash-kpi__value">
        {fmtByUnit(value, unit)}
        <span className="erpdash-kpi__unit">{unit}</span>
      </div>

      <div className="erpdash-kpi__foot">
        <div className="erpdash-kpi__meta">
          <span className={`erpdash-kpi__delta erpdash-kpi__delta--${trend}`}>
            {TREND_ICON[trend]} {sign}
            {delta}%
          </span>
          <span className="erpdash-kpi__note">{note}</span>
          <StatusChip polarity={polarity} trend={trend} />
        </div>
        <Sparkline data={spark} color={color} />
      </div>
    </div>
  );
});

function KpiSkeleton() {
  return (
    <div className="erpdash-kpi erpdash-kpi--skeleton" aria-hidden="true">
      <div className="erpdash-skel erpdash-skel--label" />
      <div className="erpdash-skel erpdash-skel--value" />
      <div className="erpdash-skel erpdash-skel--foot" />
    </div>
  );
}

/**
 * @param {{ items?: import('./dashboardApi').KpiItem[] | null, loading?: boolean }} props
 */
function KpiCards({ items, loading }) {
  if (!items || !items.length) {
    return (
      <section className="erpdash-kpis" aria-busy={loading ? 'true' : undefined}>
        <KpiSkeleton />
        <KpiSkeleton />
        <KpiSkeleton />
        <KpiSkeleton />
      </section>
    );
  }

  return (
    <section className="erpdash-kpis">
      {items.map((item) => (
        <KpiCard key={item.key} item={item} />
      ))}
    </section>
  );
}

export default memo(KpiCards);
