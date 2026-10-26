import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { buildAreaPath, buildPath, fmtInt, niceScale, xTickEvery } from './stockAlertUtils';
import { RANGE_OPTIONS } from './stockAlertApi';

/* ==========================================================================
 * <StockTrendChart /> —— 中间主图表：近 30 天出入库趋势（双轴）
 * ---------------------------------------------------------------------------
 * 左轴 出入库量（件）：入库量=面积主线，出库量=实线
 * 右轴 出库同比增速（%）：虚线，跨正负区间，0% 有加粗基准线
 *
 * 纯手写 SVG，不引入 ECharts / Chart.js，无 canvas、无 WebGL。
 *
 * props:
 *   chart         {ChartConfig | null}
 *   range         {'30d' | '7d'}
 *   onRangeChange {(range) => void}
 *   loading       {boolean}
 *   title         {string}
 *
 * 性能要点：
 *   1. 悬浮交互完全走 ref 直接改 DOM，**不 setState**，
 *      所以 mousemove 不会触发任何 React 渲染。
 *   2. 尺寸用 ResizeObserver + rAF 节流，只在宽度真的变化时才 setState。
 *   3. 所有几何计算都在 useMemo 里，依赖 [chart, hidden, 尺寸]。
 * ========================================================================== */

const PAD = { top: 26, right: 52, bottom: 34, left: 62 };
const DEFAULT_HEIGHT = 300;

let uidSeed = 0;
/**
 * 兼容 React 16.8+ 的实例唯一 id（不用 React 18 才有的 useId）
 * @returns {string}
 */
const nextUid = () => {
  uidSeed += 1;
  return `erpstock${uidSeed}`;
};

/**
 * @typedef {Object} Geo
 * @property {number} W
 * @property {number} H
 * @property {number} innerW
 * @property {number} innerH
 * @property {number} baseY
 * @property {number} n
 * @property {(i: number) => number} xAt
 * @property {(s: import('./stockAlertApi').ChartSeries, v: number) => number} yOf
 * @property {boolean} hasRight
 * @property {{ y: number, zero: boolean }[]} gridLines
 * @property {{ y: number, text: string }[]} leftTicks
 * @property {{ y: number, text: string }[]} rightTicks
 * @property {{ x: number, text: string }[]} xTicks
 * @property {{
 *   index: number,
 *   series: import('./stockAlertApi').ChartSeries,
 *   line: string,
 *   area: string | null,
 *   dots: import('./stockAlertUtils').ValuePt[] | null,
 * }[]} plotted
 */

/**
 * @param {{
 *   chart: import('./stockAlertApi').ChartConfig | null,
 *   range: import('./stockAlertApi').RangeKey,
 *   onRangeChange?: (range: import('./stockAlertApi').RangeKey) => void,
 *   loading?: boolean,
 *   title?: string,
 * }} props
 */
function StockTrendChart({
  chart,
  range,
  onRangeChange,
  loading,
  title = '出入库趋势',
}) {
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const tooltipRef = useRef(null);
  const hoverLayerRef = useRef(null);
  const hoverLineRef = useRef(null);
  /** @type {import('react').MutableRefObject<Map<number, SVGCircleElement>>} */
  const dotRefs = useRef(new Map());
  const rectRef = useRef(null);

  const uidRef = useRef(null);
  if (uidRef.current === null) uidRef.current = nextUid();

  /** @param {number} i */
  const gradId = useCallback((i) => `${uidRef.current}-grad-${i}`, []);

  const [size, setSize] = useState({ w: 0, h: DEFAULT_HEIGHT });
  const [hidden, setHidden] = useState(() => new Set());

  /* 切换时间区间时重置图例显隐 */
  const lastChartRef = useRef(chart);
  useEffect(() => {
    if (lastChartRef.current !== chart) {
      lastChartRef.current = chart;
      setHidden(new Set());
    }
  }, [chart]);

  /* ---------------- 尺寸测量 ---------------- */
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const w = el.clientWidth;
    if (w) setSize({ w, h: el.clientHeight || DEFAULT_HEIGHT });
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;

    /** @param {number} w @param {number} h */
    const apply = (w, h) => {
      setSize((prev) => (Math.abs(prev.w - w) < 1 && Math.abs(prev.h - h) < 1 ? prev : { w, h }));
    };

    if (typeof ResizeObserver === 'undefined') {
      const onResize = () => apply(el.clientWidth, el.clientHeight || DEFAULT_HEIGHT);
      window.addEventListener('resize', onResize);
      return () => window.removeEventListener('resize', onResize);
    }

    let raf = 0;
    const ro = new ResizeObserver((entries) => {
      const box = entries[0].contentRect;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => apply(box.width, box.height || DEFAULT_HEIGHT));
    });
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  /* ---------------- 几何计算（含双轴刻度） ---------------- */
  /** @type {Geo | null} */
  const geo = useMemo(() => {
    if (!chart || !chart.labels.length || !size.w) return null;

    const W = size.w;
    const H = size.h || DEFAULT_HEIGHT;
    const innerW = Math.max(W - PAD.left - PAD.right, 10);
    const innerH = Math.max(H - PAD.top - PAD.bottom, 10);
    const baseY = PAD.top + innerH;
    const n = chart.labels.length;

    /** @type {number[]} */
    const leftVals = [];
    /** @type {number[]} */
    const rightVals = [];
    chart.series.forEach((s, i) => {
      if (hidden.has(i)) return;
      if (s.axis === 'right') rightVals.push(...s.data);
      else leftVals.push(...s.data);
    });

    // 左轴从 0 起（数量），右轴允许负值（同比增速会掉到 0 以下）
    const leftScale = niceScale(0, leftVals.length ? Math.max(...leftVals) : 10, 4);
    const rightScale = niceScale(
      rightVals.length ? Math.min(...rightVals, 0) : 0,
      rightVals.length ? Math.max(...rightVals) : 10,
      4,
    );
    const hasRight = rightVals.length > 0;

    /** @param {number} i */
    const xAt = (i) => PAD.left + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    /** @param {number} v */
    const yLeft = (v) => PAD.top + innerH - ((v - leftScale.min) / (leftScale.max - leftScale.min)) * innerH;
    /** @param {number} v */
    const yRight = (v) => PAD.top + innerH - ((v - rightScale.min) / (rightScale.max - rightScale.min)) * innerH;
    /**
     * @param {import('./stockAlertApi').ChartSeries} s
     * @param {number} v
     */
    const yOf = (s, v) => (s.axis === 'right' ? yRight(v) : yLeft(v));

    /** @type {{ y: number, zero: boolean }[]} */
    const gridLines = [];
    /** @type {{ y: number, text: string }[]} */
    const leftTicks = [];
    for (let t = 0; t <= leftScale.ticks; t += 1) {
      const v = leftScale.min + t * leftScale.step;
      const y = yLeft(v);
      gridLines.push({ y, zero: false });
      leftTicks.push({ y, text: fmtInt(Math.round(v)) });
    }

    /** @type {{ y: number, text: string }[]} */
    const rightTicks = [];
    if (hasRight) {
      for (let t = 0; t <= rightScale.ticks; t += 1) {
        const v = rightScale.min + t * rightScale.step;
        const y = yRight(v);
        // 0% 基准线画重一点：同比由负转正的分界
        if (Math.abs(v) < 1e-6) gridLines.push({ y, zero: true });
        rightTicks.push({ y, text: `${v}%` });
      }
    }

    const every = xTickEvery(n);
    /** @type {{ x: number, text: string }[]} */
    const xTicks = [];
    chart.labels.forEach((lb, i) => {
      if (i % every !== 0 && i !== n - 1) return;
      xTicks.push({ x: xAt(i), text: lb });
    });

    // 点太密时不画数据点，否则 30 天 3 条线会糊成一片
    const showDots = n <= 15;
    /** @type {Geo['plotted']} */
    const plotted = [];
    chart.series.forEach((s, i) => {
      if (hidden.has(i)) return;
      const points = s.data.map((v, idx) => ({ x: xAt(idx), y: yOf(s, v), v }));
      plotted.push({
        index: i,
        series: s,
        line: buildPath(points),
        area: s.type === 'area' ? buildAreaPath(points, baseY) : null,
        dots: s.type !== 'area' && showDots ? points : null,
      });
    });

    return {
      W, H, innerW, innerH, baseY, n, xAt, yOf, hasRight,
      gridLines, leftTicks, rightTicks, xTicks, plotted,
    };
  }, [chart, hidden, size.w, size.h]);

  /* ---------------- 悬浮交互：全部走 ref，零次 setState ---------------- */
  const hideTip = useCallback(() => {
    if (tooltipRef.current) tooltipRef.current.classList.remove('is-show');
    if (hoverLayerRef.current) hoverLayerRef.current.style.opacity = '0';
  }, []);

  const handleEnter = useCallback(() => {
    if (svgRef.current) rectRef.current = svgRef.current.getBoundingClientRect();
  }, []);

  /** @param {import('react').PointerEvent<HTMLDivElement>} e */
  const handleMove = useCallback(
    (e) => {
      if (!geo || !chart) return;
      // 进入时缓存过一次，避免 mousemove 里反复触发重排
      if (!rectRef.current && svgRef.current) rectRef.current = svgRef.current.getBoundingClientRect();
      const rect = rectRef.current;
      if (!rect) return;

      const mx = e.clientX - rect.left;
      let idx = 0;
      let best = Infinity;
      for (let i = 0; i < geo.n; i += 1) {
        const d = Math.abs(geo.xAt(i) - mx);
        if (d < best) { best = d; idx = i; }
        else if (geo.xAt(i) > mx) break; // x 单调递增，越过就不再往后找
      }

      if (hoverLineRef.current) {
        hoverLineRef.current.setAttribute('x1', String(geo.xAt(idx)));
        hoverLineRef.current.setAttribute('x2', String(geo.xAt(idx)));
      }
      if (hoverLayerRef.current) hoverLayerRef.current.style.opacity = '1';

      let rows = '';
      let topY = Infinity;
      chart.series.forEach((s, i) => {
        if (hidden.has(i)) return;
        const y = geo.yOf(s, s.data[idx]);
        const dot = dotRefs.current.get(i);
        if (dot) {
          dot.setAttribute('cx', String(geo.xAt(idx)));
          dot.setAttribute('cy', String(y));
        }
        if (y < topY) topY = y;

        const unit = s.axis === 'right' ? chart.rightUnit : chart.leftUnit;
        const suffix = unit === '%' ? '%' : ` ${unit}`;
        rows +=
          '<div class="erpstock-tooltip__row">' +
          '<span class="erpstock-tooltip__name">' +
          `<i class="erpstock-tooltip__key" style="background:${s.color}"></i>${s.name}</span>` +
          `<span class="erpstock-tooltip__val">${fmtInt(s.data[idx])}${suffix}</span>` +
          '</div>';
      });

      const tip = tooltipRef.current;
      if (!tip) return;
      tip.innerHTML = `<div class="erpstock-tooltip__date">${chart.labels[idx]}</div>${rows}`;
      tip.classList.add('is-show');

      // 上方放不下且下方放得下时，翻到点的下方，避免顶到面板标题
      const tipH = tip.offsetHeight;
      const roomAbove = topY - 12 >= tipH;
      const roomBelow = geo.H - topY - 14 >= tipH;
      const showBelow = !roomAbove && roomBelow;
      tip.classList.toggle('is-below', showBelow);
      tip.style.top = showBelow ? `${topY + 14}px` : `${Math.max(topY - 12, 6)}px`;

      const tw = tip.offsetWidth;
      const maxLeft = Math.max(geo.W - tw / 2 - 4, tw / 2 + 4);
      const left = Math.min(Math.max(geo.xAt(idx), tw / 2 + 4), maxLeft);
      tip.style.left = `${left}px`;
    },
    [chart, geo, hidden],
  );

  /** @param {number} i */
  const toggleSeries = useCallback((i) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }, []);

  const busy = loading ? 'true' : undefined;

  /* --------------------------------------------------------------------------
   * 注意：这里**不能**在无数据时提前 return 另一套骨架屏结构。
   * 那样 wrapRef 在首帧是空的，尺寸测量 effect（deps 为 []）空跑一次后不再执行，
   * 等数据到位时 size.w 仍是 0，geo 恒为 null，图表永远画不出来。
   * 容器必须从首次挂载就存在，骨架屏放在容器内部。
   * ------------------------------------------------------------------------ */
  return (
    <section className="erpstock-panel" aria-busy={busy}>
      <div className="erpstock-panel__head">
        <div>
          <div className="erpstock-panel__title">{title}</div>
          <div className="erpstock-panel__desc">
            {chart
              ? `${range === '7d' ? '近 7 天' : '近 30 天'} · 左轴 ${chart.leftTitle}（${chart.leftUnit}）｜右轴 ${chart.rightTitle}增速（${chart.rightUnit}）`
              : '加载中…'}
          </div>
        </div>

        <div className="erpstock-tools">
          {loading ? <span className="erpstock-spinner" aria-hidden="true" /> : null}
          <div className="erpstock-tabs" role="tablist">
            {RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="tab"
                aria-selected={range === opt.value}
                className={`erpstock-tab${range === opt.value ? ' is-active' : ''}`}
                onClick={() => onRangeChange && onRangeChange(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div
        ref={wrapRef}
        className="erpstock-chart"
        onPointerEnter={handleEnter}
        onPointerMove={handleMove}
        onPointerLeave={hideTip}
      >
        {geo ? (
          <svg
            ref={svgRef}
            className="erpstock-chart__svg"
            viewBox={`0 0 ${geo.W} ${geo.H}`}
            role="img"
            aria-label={`${title}：${chart ? chart.series.map((s) => s.name).join(' / ') : ''}`}
          >
            <defs>
              {geo.plotted.map((p) =>
                p.area ? (
                  <linearGradient key={`g${p.index}`} id={gradId(p.index)} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={p.series.color} stopOpacity="0.22" />
                    <stop offset="100%" stopColor={p.series.color} stopOpacity="0" />
                  </linearGradient>
                ) : null,
              )}
            </defs>

            {/* 网格线 */}
            {geo.gridLines.map((g, t) => (
              <line
                key={`grid-${t}`}
                x1={PAD.left}
                y1={g.y}
                x2={PAD.left + geo.innerW}
                y2={g.y}
                stroke={g.zero ? '#dfe3e8' : 'var(--erpstock-grid)'}
                strokeWidth="1"
              />
            ))}

            {/* 左轴刻度 */}
            {geo.leftTicks.map((t, i) => (
              <text
                key={`lt-${i}`}
                x={PAD.left - 10}
                y={t.y + 4}
                textAnchor="end"
                fontSize="11"
                fill="var(--erpstock-text-3)"
              >
                {t.text}
              </text>
            ))}

            {/* 右轴刻度（带短刻度线） */}
            {geo.rightTicks.map((t, i) => (
              <g key={`rt-${i}`}>
                <line
                  x1={PAD.left + geo.innerW}
                  y1={t.y}
                  x2={PAD.left + geo.innerW + 4}
                  y2={t.y}
                  stroke="#dfe3e8"
                  strokeWidth="1"
                />
                <text x={PAD.left + geo.innerW + 10} y={t.y + 4} fontSize="11" fill="var(--erpstock-text-3)">
                  {t.text}
                </text>
              </g>
            ))}

            {/* 轴向单位：放图表上角，不用旋转轴标题 */}
            {geo.hasRight ? (
              <>
                <text x={PAD.left} y="14" fontSize="11" fill="#3370ff">
                  {chart ? `${chart.leftTitle}（${chart.leftUnit}）` : ''}
                </text>
                <text x={PAD.left + geo.innerW} y="14" textAnchor="end" fontSize="11" fill="#f59e0b">
                  {chart ? `${chart.rightTitle}（${chart.rightUnit}）` : ''}
                </text>
              </>
            ) : null}

            {/* X 轴标签 */}
            {geo.xTicks.map((t, i) => (
              <text
                key={`xt-${i}`}
                x={t.x}
                y={geo.baseY + 20}
                textAnchor="middle"
                fontSize="11"
                fill="var(--erpstock-text-3)"
              >
                {t.text}
              </text>
            ))}

            {/* 曲线 */}
            {geo.plotted.map((p) => (
              <g key={`s${p.index}`}>
                {p.area ? <path d={p.area} fill={`url(#${gradId(p.index)})`} stroke="none" /> : null}
                <path
                  d={p.line}
                  fill="none"
                  stroke={p.series.color}
                  strokeWidth={p.series.type === 'area' ? 2.2 : 1.8}
                  strokeDasharray={p.series.type === 'dashed' ? '5 4' : undefined}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {p.dots
                  ? p.dots.map((pt, k) => (
                      <circle
                        key={k}
                        cx={pt.x}
                        cy={pt.y}
                        r="2.6"
                        fill="#fff"
                        stroke={p.series.color}
                        strokeWidth="1.6"
                      />
                    ))
                  : null}
              </g>
            ))}

            {/* 悬浮层：由 ref 命令式驱动，不参与 React 渲染 */}
            <g ref={hoverLayerRef} style={{ opacity: 0 }}>
              <line
                ref={hoverLineRef}
                x1={0}
                y1={PAD.top}
                x2={0}
                y2={geo.baseY}
                stroke="#c9ced6"
                strokeWidth="1"
                strokeDasharray="4 4"
              />
              {chart
                ? chart.series.map((s, i) =>
                    hidden.has(i) ? null : (
                      <circle
                        key={`hd-${i}`}
                        ref={(el) => {
                          if (el) dotRefs.current.set(i, el);
                          else dotRefs.current.delete(i);
                        }}
                        r="4"
                        fill="#fff"
                        stroke={s.color}
                        strokeWidth="2"
                        cx={-99}
                        cy={-99}
                      />
                    ),
                  )
                : null}
            </g>
          </svg>
        ) : (
          <div className="erpstock-skel erpstock-skel--chart" />
        )}

        {/* tooltip 内容由 ref 写入，React 不管理其子节点 */}
        <div ref={tooltipRef} className="erpstock-tooltip" aria-hidden="true" />
      </div>

      <div className="erpstock-legend">
        {chart
          ? chart.series.map((s, i) => (
              <button
                key={`${s.name}-${i}`}
                type="button"
                className={`erpstock-legend__item${hidden.has(i) ? ' is-off' : ''}`}
                aria-pressed={!hidden.has(i)}
                onClick={() => toggleSeries(i)}
              >
                <span
                  className={`erpstock-legend__key${s.type === 'dashed' ? ' erpstock-legend__key--dash' : ''}`}
                  style={{ background: s.type === 'dashed' ? 'none' : s.color, color: s.color }}
                />
                {s.name}
                <span className="erpstock-legend__axis">{s.axis === 'right' ? '右轴' : '左轴'}</span>
              </button>
            ))
          : null}
      </div>
    </section>
  );
}

export default memo(StockTrendChart);
