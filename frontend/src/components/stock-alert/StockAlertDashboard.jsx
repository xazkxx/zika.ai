import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import KpiCards from './KpiCards';
import StockTrendChart from './StockTrendChart';
import AlertList from './AlertList';
import { fetchStockAlert, getStockAlertMock } from './stockAlertApi';
import { enrichAlerts, countByLevel } from './alertRules';
import { formatDateTime } from './stockAlertUtils';
import './stockAlert.css';

/* ==========================================================================
 * <StockAlertDashboard /> —— 库存预警看板（容器组件）
 * ---------------------------------------------------------------------------
 * 职责边界：
 *   - 唯一的数据源：负责拉取数据、管理 range、管理 loading / error
 *   - KpiCards / StockTrendChart / AlertList 是纯展示组件，只吃 props，
 *     自己不请求数据。以后要加「补货单」之类的板块，还是这一个请求。
 *   - 页面级样式全部收敛在 .erpstock 这个根节点下，不污染宿主页面
 *   - 紧急度判定不在本文件，全部在 alertRules.js
 *
 * props:
 *   initialRange  {'30d' | '7d'}  默认 '30d'（库存看的是月度周转，默认给长的）
 *   title         {string}        默认 '库存预警看板'
 *
 * 用法（本项目没配 @ 别名，用相对路径）：
 *   src/pages/ 下的页面：import StockAlertDashboard from '../components/stock-alert';
 *   src/App.jsx：        import StockAlertDashboard from './components/stock-alert';
 *
 *   <StockAlertDashboard />
 * ========================================================================== */

/**
 * 🔧 后端接口还没上线时想先调界面：把这里改成 true，
 *    就会走 stockAlertApi.js 里的本地 mock，完全不发请求。
 *    上线前记得改回 false。
 */
const USE_MOCK = false;

/**
 * 统一的取数入口 —— 真实接口 / 本地 mock 只在这一处分叉
 * @param {import('./stockAlertApi').RangeKey} range
 * @param {{ signal?: AbortSignal }} options
 * @returns {Promise<import('./stockAlertApi').StockAlertData>}
 */
function requestStockAlert(range, options) {
  if (USE_MOCK) return getStockAlertMock(range);
  return fetchStockAlert(range, options);
}


/**
 * @param {{
 *   initialRange?: import('./stockAlertApi').RangeKey,
 *   title?: string,
 * }} props
 */
function StockAlertDashboard({ initialRange = '30d', title = '库存预警看板' }) {
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

    requestStockAlert(range, { signal: controller ? controller.signal : undefined })
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

  /** @param {import('./stockAlertApi').RangeKey} next */
  const handleRangeChange = useCallback((next) => {
    setRange((prev) => (prev === next ? prev : next));
  }, []);

  const handleRetry = useCallback(() => setReloadKey((k) => k + 1), []);

  /* --------------------------------------------------------------------------
   * 预警明细的「派生」只在这里做一次：
   *   原始字段 → 补上 缺口 / 预计可用天数 / 紧急度，并按可用天数升序重排。
   * 判定口径全部在 alertRules.js，本组件不硬编码任何阈值。
   * ------------------------------------------------------------------------ */
  const alerts = useMemo(() => enrichAlerts(data && data.alerts), [data]);
  const levelCounts = useMemo(() => countByLevel(alerts), [alerts]);

  const hasAlerts = alerts.length > 0;

  return (
    <div className="erpstock">
      <header className="erpstock__head">
        <div>
          <h1 className="erpstock__title">{title}</h1>
          <p className="erpstock__sub">
            {data ? `数据更新于 ${formatDateTime(data.updatedAt)}` : '数据加载中…'}
          </p>
        </div>

        {hasAlerts ? (
          <div className="erpstock__summary">
            <span className="erpstock__sum-item">
              紧急
              <b className="erpstock__sum-num erpstock__sum-num--urgent">{levelCounts.urgent}</b>
              种
            </span>
            <span className="erpstock__sum-item">
              预警
              <b className="erpstock__sum-num erpstock__sum-num--warn">{levelCounts.warn}</b>
              种
            </span>
            <span className="erpstock__sum-item">
              正常
              <b className="erpstock__sum-num erpstock__sum-num--normal">{levelCounts.normal}</b>
              种
            </span>
          </div>
        ) : null}
      </header>

      {error ? (
        <div className="erpstock-error" role="alert">
          <div className="erpstock-error__text">数据加载失败：{error.message}</div>
          <button type="button" className="erpstock-error__btn" onClick={handleRetry}>
            重新加载
          </button>
        </div>
      ) : null}

      <KpiCards items={data?.kpis} loading={loading} />

      <StockTrendChart
        chart={data?.chart ?? null}
        range={range}
        onRangeChange={handleRangeChange}
        loading={loading}
      />

      <AlertList items={alerts} loading={loading} />
    </div>
  );
}

export default StockAlertDashboard;
