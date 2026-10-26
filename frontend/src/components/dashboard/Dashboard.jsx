import { useCallback, useEffect, useRef, useState } from 'react';
import KpiCards from './KpiCards';
import TrendChart from './TrendChart';
import { fetchDashboard } from './dashboardApi';
import { formatDateTime } from './dashboardUtils';
import './dashboard.css';

/* ==========================================================================
 * <Dashboard /> —— 容器组件
 * ---------------------------------------------------------------------------
 * 职责边界：
 *   - 唯一的数据源：负责拉取数据、管理 range、管理 loading / error
 *   - KpiCards / TrendChart 是纯展示组件，只吃 props，自己不请求数据
 *     （这样以后加下半部分的排行榜 / 明细表时，不会有多个组件抢着请求）
 *   - 页面级样式全部收敛在 .erpdash 这个根节点下，不污染宿主页面
 *
 * props:
 *   initialRange  {'7d' | '30d'}  默认 '7d'
 *   title         {string}         默认 'ERP 经营看板'
 *
 * 用法（本项目没配 @ 别名，用相对路径）：
 *   在 src/pages/ 下的页面里：import { Dashboard } from '../components/dashboard';
 *   在 src/App.jsx 里：       import { Dashboard } from './components/dashboard';
 *
 *   <Dashboard />
 * ========================================================================== */

/**
 * @param {{
 *   initialRange?: import('./dashboardApi').RangeKey,
 *   title?: string,
 * }} props
 */
function Dashboard({ initialRange = '7d', title = 'ERP 经营看板' }) {
  const [range, setRange] = useState(initialRange);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const hasDataRef = useRef(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let alive = true;

    // 已有数据时不清空旧图，只标记 loading —— 切换区间不会闪屏
    if (hasDataRef.current) setLoading(true);
    setError(null);

    fetchDashboard(range, { signal: controller ? controller.signal : undefined })
      .then((res) => {
        if (!alive) return;
        hasDataRef.current = true;
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        // StrictMode 下 dev 会跑两次 effect，第一次会被 abort，这里要静默忽略
        if (!alive) return;
        if (err && err.name === 'AbortError') return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      });

    return () => {
      alive = false;
      if (controller) controller.abort();
    };
  }, [range, reloadKey]);

  /** @param {import('./dashboardApi').RangeKey} next */
  const handleRangeChange = useCallback((next) => {
    setRange((prev) => (prev === next ? prev : next));
  }, []);

  const handleRetry = useCallback(() => setReloadKey((k) => k + 1), []);

  return (
    <div className="erpdash">
      <header className="erpdash__head">
        <h1 className="erpdash__title">{title}</h1>
        <p className="erpdash__sub">
          {data ? `数据更新于 ${formatDateTime(data.updatedAt)}` : '数据加载中…'}
          <span className="erpdash__badge">模拟数据</span>
        </p>
      </header>

      {error ? (
        <div className="erpdash-error" role="alert">
          <div className="erpdash-error__text">数据加载失败：{error.message}</div>
          <button type="button" className="erpdash-error__btn" onClick={handleRetry}>
            重新加载
          </button>
        </div>
      ) : null}

      <KpiCards items={data?.kpis} loading={loading} />

      <TrendChart
        chart={data?.chart ?? null}
        range={range}
        onRangeChange={handleRangeChange}
        loading={loading}
      />
    </div>
  );
}

export default Dashboard;
