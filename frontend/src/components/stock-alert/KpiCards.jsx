import { memo } from 'react';
import { buildPath, fmtByUnit } from './stockAlertUtils';

/* ==========================================================================
 * <KpiCards /> —— 顶部 4 个卡片：总库存 / 待入库 / 待出库 / 缺货商品
 * ---------------------------------------------------------------------------
 * props:
 *   items    {KpiItem[]}  为空时渲染骨架屏
 *   loading  {boolean}
 *
 * 性能：整块用 memo 包住，只有 items 引用变化时才重渲染。
 * ========================================================================== */

/** @type {Record<import('./stockAlertApi').Trend, string>} */
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
    <svg className="erpstock-kpi__spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
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
 * 待入库 / 待出库 / 缺货商品 属于「数字涨了是坏事」，
 * 光靠红色上涨箭头容易被误读成业务增长，所以额外给一个语义标。
 * 色值仍严格跟随数值方向（涨红跌绿），好坏由这个标签表达。
 *
 * @param {{ polarity: import('./stockAlertApi').Polarity, trend: import('./stockAlertApi').Trend }} props
 */
function StatusChip({ polarity, trend }) {
  if (polarity !== 'inverse') return null;
  const isWarn = trend === 'up';
  return (
    <span className={`erpstock-kpi__chip erpstock-kpi__chip--${isWarn ? 'warn' : 'ok'}`}>
      {isWarn ? '需关注' : '正常'}
    </span>
  );
}

/** @param {{ item: import('./stockAlertApi').KpiItem }} props */
const KpiCard = memo(function KpiCard({ item }) {
  const { key, label, value, unit, delta, trend, note, polarity, color, spark } = item;
  const sign = trend === 'flat' ? '' : delta > 0 ? '+' : '';

  return (
    <div className="erpstock-kpi" data-key={key}>
      <div className="erpstock-kpi__label">
        <span className="erpstock-kpi__dot" style={{ background: color }} />
        {label}
      </div>

      <div className="erpstock-kpi__value">
        {fmtByUnit(value, unit)}
        <span className="erpstock-kpi__unit">{unit}</span>
      </div>

      <div className="erpstock-kpi__foot">
        <div className="erpstock-kpi__meta">
          <span className={`erpstock-kpi__delta erpstock-kpi__delta--${trend}`}>
            {TREND_ICON[trend]} {sign}
            {delta}%
          </span>
          <span className="erpstock-kpi__note">{note}</span>
          <StatusChip polarity={polarity} trend={trend} />
        </div>
        <Sparkline data={spark} color={color} />
      </div>
    </div>
  );
});

function KpiSkeleton() {
  return (
    <div className="erpstock-kpi erpstock-kpi--skeleton" aria-hidden="true">
      <div className="erpstock-skel erpstock-skel--label" />
      <div className="erpstock-skel erpstock-skel--value" />
      <div className="erpstock-skel erpstock-skel--foot" />
    </div>
  );
}

/**
 * @param {{ items?: import('./stockAlertApi').KpiItem[] | null, loading?: boolean }} props
 */
function KpiCards({ items, loading }) {
  if (!items || !items.length) {
    return (
      <section className="erpstock-kpis" aria-busy={loading ? 'true' : undefined}>
        <KpiSkeleton />
        <KpiSkeleton />
        <KpiSkeleton />
        <KpiSkeleton />
      </section>
    );
  }

  return (
    <section className="erpstock-kpis">
      {items.map((item) => (
        <KpiCard key={item.key} item={item} />
      ))}
    </section>
  );
}

export default memo(KpiCards);
