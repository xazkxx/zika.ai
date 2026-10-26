/**
 * 三单匹配看板（合同 / 发票 / 付款）—— 2026-10-23
 *
 * 财务月底的核心动作：**逐合同核对"票开了没有、钱收了没有、差在哪一笔"**。
 *
 * 页面三段：
 *   1. KPI：合同数 / 合同总额 / 已开票 / 未开票缺口 / 已付 / 未付缺口（缺口红字）；
 *   2. 主表：逐合同一行，含两条缺口、匹配率进度条、状态灯；
 *   3. 抽屉：点「查看」从右侧滑出，把合同明细、每一张票、每一笔款按时间线摊开。
 *
 * 口径提醒（界面上也写了）：金额里可能包含"按往来单位估算"的部分 ——
 * 合同没转单时系统没有 order_id 可链，只能按单位+日期顺序分配，
 * 抽屉里每一笔都标注了「单据关联 / 按单位估算」，不假装精确。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

const STATUS_TONE = {
  both_missing: { cls: 'is-bad', label: '票款均未齐' },
  invoice_missing: { cls: 'is-warn', label: '发票未齐' },
  payment_missing: { cls: 'is-warn', label: '付款未齐' },
  closed: { cls: 'is-ok', label: '已闭环' },
};

const money = (value) =>
  `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const moneyShort = (value) => {
  const num = Number(value || 0);
  if (Math.abs(num) >= 10000) return `¥${(num / 10000).toFixed(2)} 万`;
  return money(num);
};

export default function ThreeWayMatchPage({ ctx }) {
  const { API_BASE, authHeaders, setNotice } = ctx;

  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [direction, setDirection] = useState('');

  // 抽屉
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (keyword.trim()) params.set('keyword', keyword.trim());
      if (statusFilter) params.set('status', statusFilter);
      if (direction) params.set('direction', direction);
      params.set('limit', '300');
      const response = await fetch(`${API_BASE}/three-way-match?${params.toString()}`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`读取三单匹配失败（HTTP ${response.status}）`);
      const data = await response.json();
      setRows(Array.isArray(data.rows) ? data.rows : []);
      setTotals(data.totals || null);
    } catch (err) {
      setError(err.message || '读取失败');
    } finally {
      setLoading(false);
    }
  }, [API_BASE, authHeaders, keyword, statusFilter, direction]);

  useEffect(() => {
    load();
    // 只在进入页面时拉一次；改筛选靠按钮触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = async (row) => {
    setDetailLoading(true);
    setDetail({ loading: true, contract: { contract_no: row.contract_no } });
    try {
      const response = await fetch(`${API_BASE}/contracts/${row.contract_id}/three-way-detail`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`读取明细失败（HTTP ${response.status}）`);
      const data = await response.json();
      setDetail(data);
    } catch (err) {
      setError(err.message || '读取明细失败');
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  /** 时间线：把票与款按日期并成一条流，财务按时间对最直观 */
  const timeline = useMemo(() => {
    if (!detail?.summary) return [];
    const events = [
      ...(detail.invoices || []).map((item) => ({
        key: `inv-${item.id}`,
        at: item.issue_date || '',
        kind: 'invoice',
        title: `开票 ${item.invoice_no || ''}`,
        amount: item.amount,
        source: item.source,
        extra: item.status || '',
      })),
      ...(detail.payments || []).map((item) => ({
        key: `pay-${item.id}`,
        at: (item.occurred_at || '').slice(0, 10),
        kind: 'payment',
        title: item.type === 'receipt' ? '收款' : '付款',
        amount: item.amount,
        source: item.source,
        extra: item.method || item.note || '',
      })),
    ];
    return events.sort((a, b) => String(a.at).localeCompare(String(b.at)));
  }, [detail]);

  const statusCounts = useMemo(() => {
    const counts = { both_missing: 0, invoice_missing: 0, payment_missing: 0, closed: 0 };
    rows.forEach((row) => {
      counts[row.match_status] = (counts[row.match_status] || 0) + 1;
    });
    return counts;
  }, [rows]);

  return (
    <section className="twm" data-three-way-page>
      <header className="twm__head">
        <div>
          <h2>三单匹配</h2>
          <p>
            合同 · 发票 · 付款 三方对账。缺口红字为"还差多少"；合同未转单时，票款按往来单位估算配对
            （抽屉里逐笔标注来源）。
          </p>
        </div>
        <div className="twm__filters">
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') load();
            }}
            placeholder="合同号 / 名称 / 往来单位"
            data-twm-keyword
          />
          <select value={direction} onChange={(event) => setDirection(event.target.value)} data-twm-direction>
            <option value="">全部方向</option>
            <option value="out">应收（销售合同）</option>
            <option value="in">应付（采购合同）</option>
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} data-twm-status>
            <option value="">全部状态</option>
            <option value="both_missing">票款均未齐</option>
            <option value="invoice_missing">发票未齐</option>
            <option value="payment_missing">付款未齐</option>
            <option value="closed">已闭环</option>
          </select>
          <button type="button" className="primary-btn small-btn" onClick={load} disabled={loading} data-twm-query>
            {loading ? '查询中…' : '查询'}
          </button>
          <button
            type="button"
            className="secondary-btn small-btn"
            onClick={() => {
              setKeyword('');
              setStatusFilter('');
              setDirection('');
              setTimeout(load, 0);
            }}
          >
            重置
          </button>
        </div>
      </header>

      {error ? (
        <p className="twm__alert" role="alert">
          {error}
        </p>
      ) : null}

      {/* KPI */}
      <div className="twm__kpis" data-twm-kpis>
        <div className="twm__kpi">
          <span>合同总数</span>
          <strong data-twm-kpi="count">{totals?.contract_count ?? 0}</strong>
          <em>闭环 {totals?.closed_count ?? 0} · 双缺 {totals?.both_missing ?? 0}</em>
        </div>
        <div className="twm__kpi">
          <span>合同总额</span>
          <strong data-twm-kpi="contract">{moneyShort(totals?.contract_amount)}</strong>
          <em>{totals ? money(totals.contract_amount) : '—'}</em>
        </div>
        <div className="twm__kpi">
          <span>已开票</span>
          <strong data-twm-kpi="invoiced">{moneyShort(totals?.invoiced_amount)}</strong>
          <em>{totals ? money(totals.invoiced_amount) : '—'}</em>
        </div>
        <div className="twm__kpi is-gap">
          <span>未开票缺口</span>
          <strong data-twm-kpi="invoice-gap">{moneyShort(totals?.invoice_gap)}</strong>
          <em>红字 = 还差的票额</em>
        </div>
        <div className="twm__kpi">
          <span>已付款</span>
          <strong data-twm-kpi="paid">{moneyShort(totals?.paid_amount)}</strong>
          <em>{totals ? money(totals.paid_amount) : '—'}</em>
        </div>
        <div className="twm__kpi is-gap">
          <span>未付款缺口</span>
          <strong data-twm-kpi="payment-gap">{moneyShort(totals?.payment_gap)}</strong>
          <em>红字 = 还差的钱</em>
        </div>
      </div>

      <div className="twm__table-wrap">
        <table className="twm__table" data-twm-table>
          <thead>
            <tr>
              <th>合同编号</th>
              <th>合同名称</th>
              <th>客户 / 供应商</th>
              <th className="is-num">合同金额</th>
              <th className="is-num">已开票</th>
              <th className="is-num">开票缺口</th>
              <th className="is-num">已付</th>
              <th className="is-num">付款缺口</th>
              <th>匹配率</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading ? (
              <tr>
                <td colSpan={11} className="twm__empty">
                  没有匹配的合同。换个筛选条件，或先去「购销合同」建一张。
                </td>
              </tr>
            ) : null}
            {rows.map((row) => {
              const tone = STATUS_TONE[row.match_status] || STATUS_TONE.both_missing;
              return (
                <tr key={row.contract_id} data-twm-row={row.contract_id}>
                  <td>
                    <span className="twm__no">{row.contract_no}</span>
                    {row.invoice_source === 'party' || row.payment_source === 'party' ? (
                      <span className="twm__tag" title="合同未转单，票/款按往来单位估算配对">
                        估算
                      </span>
                    ) : null}
                  </td>
                  <td title={row.title || ''}>{row.title || '—'}</td>
                  <td title={row.party_name || ''}>{row.party_name || '—'}</td>
                  <td className="is-num">{money(row.total_amount)}</td>
                  <td className="is-num">{money(row.invoiced_amount)}</td>
                  <td className={`is-num${row.invoice_gap > 0.005 ? ' is-gap' : ' is-ok'}`}>
                    {row.invoice_gap > 0.005
                      ? money(row.invoice_gap)
                      : row.invoice_gap < -0.005
                        ? `${money(Math.abs(row.invoice_gap))}（超）`
                        : '¥0.00'}
                  </td>
                  <td className="is-num">{money(row.paid_amount)}</td>
                  <td className={`is-num${row.payment_gap > 0.005 ? ' is-gap' : ' is-ok'}`}>
                    {row.payment_gap > 0.005
                      ? money(row.payment_gap)
                      : row.payment_gap < -0.005
                        ? `${money(Math.abs(row.payment_gap))}（超）`
                        : '¥0.00'}
                  </td>
                  <td>
                    <div className="twm__ratio" data-twm-ratio={row.contract_id}>
                      <span className="twm__ratio-bar">
                        <i
                          className={row.match_ratio >= 99.5 ? 'is-full' : ''}
                          style={{ width: `${Math.max(0, Math.min(100, row.match_ratio))}%` }}
                        />
                      </span>
                      <em>{row.match_ratio.toFixed(1)}%</em>
                    </div>
                  </td>
                  <td>
                    <span className={`twm__status ${tone.cls}`} data-twm-status-cell={row.contract_id}>
                      {tone.label}
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      data-twm-view={row.contract_id}
                      onClick={() => openDetail(row)}
                      disabled={detailLoading}
                    >
                      查看
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="twm__hint">
        口径：已开票 = 该合同关联的销项/进项发票合计；已付 = 实收/实付流水合计
        （应收应付的记账行不算钱）。匹配率 = 票、款两项完成度的平均值。
        当前筛选：双双未齐 {statusCounts.both_missing} · 发票未齐 {statusCounts.invoice_missing} ·
        付款未齐 {statusCounts.payment_missing} · 已闭环 {statusCounts.closed}。
      </p>

      {/* 明细抽屉 */}
      {detail ? (
        <>
          <div className="twm-drawer__mask" onClick={() => setDetail(null)} />
          <aside className="twm-drawer" data-twm-drawer>
            <header className="twm-drawer__head">
              <div>
                <h3>{detail.contract?.contract_no || '加载中…'}</h3>
                <p>
                  {detail.contract?.title || ''}
                  {detail.contract?.party_name ? ` · ${detail.contract.party_name}` : ''}
                </p>
              </div>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setDetail(null)}
                data-twm-drawer-close
              >
                关闭
              </button>
            </header>

            {detail.loading ? (
              <p className="twm-drawer__loading">读取中…</p>
            ) : (
              <div className="twm-drawer__body">
                {/* 三方对账小结 */}
                <div className="twm-drawer__cards">
                  <div>
                    <span>合同金额</span>
                    <strong>{money(detail.summary?.total_amount)}</strong>
                  </div>
                  <div>
                    <span>已开票</span>
                    <strong>{money(detail.summary?.invoiced_amount)}</strong>
                  </div>
                  <div className={detail.summary?.invoice_gap > 0.005 ? 'is-gap' : ''}>
                    <span>开票缺口</span>
                    <strong>{money(detail.summary?.invoice_gap)}</strong>
                  </div>
                  <div>
                    <span>已付</span>
                    <strong>{money(detail.summary?.paid_amount)}</strong>
                  </div>
                  <div className={detail.summary?.payment_gap > 0.005 ? 'is-gap' : ''}>
                    <span>付款缺口</span>
                    <strong>{money(detail.summary?.payment_gap)}</strong>
                  </div>
                </div>

                {detail.unlinked ? (
                  <p className="twm-drawer__warn">
                    这张合同还没转成单据，系统没有单据号可关联发票与付款；
                    下面带「按单位估算」标记的记录，是按往来单位与日期顺序推断出来的。
                  </p>
                ) : null}

                {/* 时间线 */}
                <h4>票据与款项时间线</h4>
                {timeline.length === 0 ? (
                  <p className="twm-drawer__empty">还没有任何发票或收付款记录。</p>
                ) : (
                  <ol className="twm-timeline" data-twm-timeline>
                    {timeline.map((event) => (
                      <li key={event.key} className={`twm-timeline__item is-${event.kind}`}>
                        <span className="twm-timeline__date">{event.at || '—'}</span>
                        <span className="twm-timeline__dot" />
                        <div className="twm-timeline__body">
                          <strong>{event.title}</strong>
                          <em className={event.kind === 'payment' ? 'is-paid' : 'is-inv'}>
                            {money(event.amount)}
                          </em>
                          {event.source === 'party' ? (
                            <span className="twm__tag">按单位估算</span>
                          ) : (
                            <span className="twm__tag is-order">单据关联</span>
                          )}
                          {event.extra ? <small>{event.extra}</small> : null}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}

                {/* 合同明细 */}
                <h4>合同明细（{detail.items?.length || 0} 项）</h4>
                <div className="twm-drawer__table-wrap">
                  <table className="twm-drawer__table">
                    <thead>
                      <tr>
                        <th>商品</th>
                        <th>规格</th>
                        <th>单位</th>
                        <th className="is-num">数量</th>
                        <th className="is-num">单价</th>
                        <th className="is-num">金额</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.items || []).map((item) => (
                        <tr key={item.id}>
                          <td>{item.product_name}</td>
                          <td>{item.standards || '—'}</td>
                          <td>{item.unit || '—'}</td>
                          <td className="is-num">{item.quantity}</td>
                          <td className="is-num">{money(item.unit_price)}</td>
                          <td className="is-num">{money(item.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* 付款计划（参考） */}
                {(detail.payment_plans || []).length > 0 ? (
                  <>
                    <h4>付款计划（计划侧，非实际付款）</h4>
                    <div className="twm-drawer__table-wrap">
                      <table className="twm-drawer__table">
                        <thead>
                          <tr>
                            <th>期次</th>
                            <th>名称</th>
                            <th>计划日期</th>
                            <th className="is-num">计划金额</th>
                            <th className="is-num">登记已付</th>
                            <th>回单</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.payment_plans.map((plan) => (
                            <tr key={plan.period_no}>
                              <td>{plan.period_no}</td>
                              <td>{plan.name || '—'}</td>
                              <td>{plan.plan_date || '—'}</td>
                              <td className="is-num">{money(plan.plan_amount)}</td>
                              <td className="is-num">{money(plan.paid_amount)}</td>
                              <td>{plan.has_receipt ? '已上传' : '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}
              </div>
            )}
          </aside>
        </>
      ) : null}
    </section>
  );
}
