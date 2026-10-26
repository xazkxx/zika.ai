import { memo, useMemo, useState } from 'react';
import { FILTER_OPTIONS, LEVEL_META, countByLevel } from './alertRules';
import { fmtDays, fmtInt } from './stockAlertUtils';

/* ==========================================================================
 * <AlertList /> —— 底部：缺货预警商品明细
 * ---------------------------------------------------------------------------
 * props:
 *   items   {AlertItem[]}  已经过 alertRules.enrichAlerts 补全 + 排序的视图模型
 *                          为空时渲染骨架屏
 *   loading {boolean}
 *
 * 这里不做任何业务判断：
 *   缺口(gap) / 可用天数(daysLeft) / 紧急度(level) 全部由 alertRules.js 算好，
 *   本组件只负责画。调判定规则请改 alertRules.js，不要改这里。
 *
 * 筛选状态是本组件内部状态 —— 它只影响这张表，没必要提升到容器里。
 * ========================================================================== */

/** @param {{ level: import('./stockAlertApi').AlertLevel }} props */
function LevelChip({ level }) {
  const meta = LEVEL_META[level] || LEVEL_META.normal;
  return <span className={`erpstock-chip erpstock-chip--${level}`}>{meta.label}</span>;
}

function ListSkeleton() {
  return (
    <section className="erpstock-panel">
      <div className="erpstock-panel__head">
        <div>
          <div className="erpstock-panel__title">缺货预警商品明细</div>
          <div className="erpstock-panel__desc">加载中…</div>
        </div>
      </div>
      <div className="erpstock-skel erpstock-skel--table" />
    </section>
  );
}

/**
 * @param {{ items?: import('./stockAlertApi').AlertItem[] | null, loading?: boolean }} props
 */
function AlertList({ items, loading }) {
  const [filter, setFilter] = useState('all');

  const counts = useMemo(() => countByLevel(items), [items]);

  const rows = useMemo(() => {
    const list = items || [];
    return filter === 'all' ? list : list.filter((it) => it.level === filter);
  }, [items, filter]);

  if (!items || !items.length) return <ListSkeleton />;

  return (
    <section className="erpstock-panel" aria-busy={loading ? 'true' : undefined}>
      <div className="erpstock-panel__head">
        <div>
          <div className="erpstock-panel__title">
            缺货预警商品明细
            <span className="erpstock-panel__count">共 {counts.all} 种</span>
          </div>
          <div className="erpstock-panel__desc">
            当前库存低于库存下限的商品（没设下限的按售罄判定），按预计可用天数从少到多排列（即补货优先级）
          </div>
        </div>

        <div className="erpstock-tools">
          {loading ? <span className="erpstock-spinner" aria-hidden="true" /> : null}
          <div className="erpstock-tabs" role="tablist">
            {FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                role="tab"
                aria-selected={filter === opt.value}
                className={`erpstock-tab${filter === opt.value ? ' is-active' : ''}`}
                onClick={() => setFilter(opt.value)}
              >
                {opt.label}
                <span className="erpstock-tab__num">{counts[opt.value]}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="erpstock-table-wrap">
        <table className="erpstock-table">
          <thead>
            <tr>
              <th className="erpstock-table__col-name">商品</th>
              <th>仓库</th>
              <th className="erpstock-table__num">当前库存</th>
              <th className="erpstock-table__num">安全库存</th>
              <th className="erpstock-table__num">缺口</th>
              <th className="erpstock-table__num">日均出库</th>
              <th className="erpstock-table__num">预计可用天数</th>
              <th className="erpstock-table__num">建议补货</th>
              <th className="erpstock-table__center">紧急度</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((it) => (
              <tr key={it.id}>
                <td className="erpstock-table__col-name">
                  <div className="erpstock-table__name">{it.name}</div>
                  <div className="erpstock-table__sku">{it.sku}</div>
                </td>
                <td className="erpstock-table__muted">{it.warehouse}</td>
                <td className="erpstock-table__num">{fmtInt(it.stock)}</td>
                <td className="erpstock-table__num erpstock-table__muted">{fmtInt(it.safetyStock)}</td>
                <td className="erpstock-table__num">
                  <span className="erpstock-table__gap">{fmtInt(it.gap)}</span>
                </td>
                <td className="erpstock-table__num erpstock-table__muted">
                  {it.dailyOut > 0 ? fmtInt(it.dailyOut) : '—'}
                </td>
                <td className="erpstock-table__num">
                  <span className={`erpstock-table__days erpstock-table__days--${it.level}`}>
                    {fmtDays(it.daysLeft)}
                  </span>
                </td>
                <td className="erpstock-table__num erpstock-table__strong">{fmtInt(it.suggest)}</td>
                <td className="erpstock-table__center">
                  <LevelChip level={it.level} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {rows.length === 0 ? (
          <div className="erpstock-empty">没有符合条件的商品</div>
        ) : null}
      </div>
    </section>
  );
}

export default memo(AlertList);
