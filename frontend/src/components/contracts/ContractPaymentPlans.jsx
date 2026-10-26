/**
 * 合同付款计划（多期次）—— 2026-10-23
 *
 * 放在合同详情弹窗里。四件事：
 *   1. 汇总条：总额 / 已计划 / 已付 / 未付缺口 + 进度条；
 *   2. 期次表：计划日期、比例、金额、已付、差额、回单；
 *   3. 行内编辑：计划日期 / 计划金额 / 已付金额（失焦即保存，不弹二次框）；
 *   4. 回单：上传 / 查看 / 替换（文件走 fetch+blob，令牌带不了进 img 的 src）。
 *
 * 口径说明：已付金额是**财务按期间登记**的数，不从流水反推 ——
 * 一笔流水可能同时覆盖两期，硬塞到某一期会让账失真。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../../lib/appLib.js';
import { saveBlob } from '../../lib/download.js';

const money = (value) =>
  `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function ContractPaymentPlans({ contractId, authHeaders, onSummary, readOnly = false }) {
  const [plans, setPlans] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  // 行内编辑草稿：{ [planId]: { plan_date, plan_amount, paid_amount } }
  const [draft, setDraft] = useState({});
  // 新增一期的表单
  const [adding, setAdding] = useState(false);
  const [newPlan, setNewPlan] = useState({ name: '', plan_date: '', plan_ratio: '', plan_amount: '' });
  const fileRefs = useRef({});

  const apply = useCallback(
    (data) => {
      setPlans(Array.isArray(data.plans) ? data.plans : []);
      setSummary(data.summary || null);
      onSummary?.(data.summary || null);
    },
    [onSummary],
  );

  const load = useCallback(async () => {
    if (!contractId) return;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/contracts/${contractId}/payment-plans`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`读取付款计划失败（HTTP ${response.status}）`);
      apply(await response.json());
    } catch (err) {
      setError(err.message || '读取付款计划失败');
    } finally {
      setLoading(false);
    }
  }, [contractId, authHeaders, apply]);

  useEffect(() => {
    load();
  }, [load]);

  const post = async (url, body, method = 'POST') => {
    const response = await fetch(`${API_BASE}${url}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败');
    }
    return response.status === 204 ? null : response.json();
  };

  const buildTemplate = async () => {
    setBusy('template');
    setError('');
    setNotice('');
    try {
      const data = await post(`/contracts/${contractId}/payment-plans/template`, {});
      apply(data);
      setNotice('已按 30% / 40% / 30% 生成三期，可逐期改金额与日期');
    } catch (err) {
      setError(err.message || '生成失败');
    } finally {
      setBusy('');
    }
  };

  const addPlan = async (event) => {
    event.preventDefault();
    setBusy('add');
    setError('');
    setNotice('');
    try {
      const body = {
        name: newPlan.name,
        plan_date: newPlan.plan_date,
        plan_ratio: newPlan.plan_ratio === '' ? null : Number(newPlan.plan_ratio),
        plan_amount: newPlan.plan_amount === '' ? null : Number(newPlan.plan_amount),
      };
      const data = await post(`/contracts/${contractId}/payment-plans`, body);
      apply(data);
      setNewPlan({ name: '', plan_date: '', plan_ratio: '', plan_amount: '' });
      setAdding(false);
      setNotice('已新增一期');
    } catch (err) {
      setError(err.message || '新增失败');
    } finally {
      setBusy('');
    }
  };

  const saveRow = async (plan, field, value) => {
    const original = plan[field];
    const next = value === '' ? null : value;
    // 值没变就不要打扰后端（失焦会无条件触发）
    if (String(original ?? '') === String(next ?? '')) return;
    try {
      const payload = { [field]: next };
      if (field === 'plan_amount') delete payload.plan_ratio; // 金额优先，比例由后端反算
      const data = await post(`/payment-plans/${plan.id}`, payload, 'PATCH');
      apply(data);
      setNotice('已保存');
    } catch (err) {
      setError(err.message || '保存失败');
      // 保存失败要把输入框恢复成库里的值，否则界面上显示的是"没生效的数字"
      setDraft((prev) => ({
        ...prev,
        [plan.id]: { ...(prev[plan.id] || {}), [field]: original ?? '' },
      }));
    }
  };

  const removePlan = async (plan) => {
    setBusy(`del-${plan.id}`);
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/payment-plans/${plan.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!response.ok && response.status !== 204) throw new Error('删除失败');
      await load();
      setNotice(`已删除第 ${plan.period_no} 期`);
    } catch (err) {
      setError(err.message || '删除失败');
    } finally {
      setBusy('');
    }
  };

  const uploadReceipt = async (plan, file) => {
    if (!file) return;
    setBusy(`up-${plan.id}`);
    setError('');
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(`${API_BASE}/payment-plans/${plan.id}/receipt`, {
        method: 'POST',
        headers: authHeaders(), // 不要手动设 Content-Type，浏览器要带 boundary
        body: form,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '上传失败');
      }
      apply(await response.json());
      setNotice(`第 ${plan.period_no} 期回单已上传`);
    } catch (err) {
      setError(err.message || '上传失败');
    } finally {
      setBusy('');
      if (fileRefs.current[plan.id]) fileRefs.current[plan.id].value = '';
    }
  };

  const openReceipt = async (plan) => {
    try {
      const response = await fetch(`${API_BASE}/payment-plans/${plan.id}/receipt`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`回单打不开（HTTP ${response.status}）`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(err.message || '回单打不开');
    }
  };

  const progress = summary?.progress;
  const overpaid = (summary?.shortfall ?? 0) < 0;

  return (
    <section className="payplan" data-contract-payment-plans>
      <div className="payplan__head">
        <h4>付款计划（多期次）</h4>
        <div className="payplan__actions">
          {!readOnly && plans.length === 0 ? (
            <button
              type="button"
              className="secondary-btn small-btn"
              data-payplan-template
              onClick={buildTemplate}
              disabled={busy === 'template'}
            >
              {busy === 'template' ? '生成中…' : '一键三期 30/40/30'}
            </button>
          ) : null}
          {!readOnly ? (
            <button
              type="button"
              className="secondary-btn small-btn"
              data-payplan-add
              onClick={() => setAdding((prev) => !prev)}
            >
              {adding ? '取消' : '+ 增加一期'}
            </button>
          ) : null}
        </div>
      </div>

      {summary ? (
        <div className="payplan__summary" data-payplan-summary>
          <span>
            合同总额 <b>{money(summary.contract_amount)}</b>
          </span>
          <span>
            已计划 <b>{money(summary.planned_amount)}</b>
          </span>
          <span>
            已付 <b className="is-paid">{money(summary.paid_amount)}</b>
          </span>
          <span className={overpaid ? 'is-over' : 'is-gap'}>
            未付缺口 <b>{money(Math.abs(summary.shortfall))}{overpaid ? '（超付）' : ''}</b>
          </span>
          <div className="payplan__bar" title={progress === null ? '合同金额为 0' : `已付 ${progress}%`}>
            <div
              className={`payplan__bar-fill${progress !== null && progress >= 100 ? ' is-full' : ''}${overpaid ? ' is-over' : ''}`}
              style={{ width: `${progress === null ? 0 : progress}%` }}
            />
            <span className="payplan__bar-text">
              {progress === null ? '—' : `${progress}%`}
            </span>
          </div>
        </div>
      ) : null}

      {error ? (
        <p className="payplan__alert payplan__alert--error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p className="payplan__alert payplan__alert--ok">{notice}</p> : null}

      {adding && !readOnly ? (
        <form className="payplan__add" onSubmit={addPlan} data-payplan-add-form>
          <input
            placeholder="期次名称，如 预付款 30%"
            value={newPlan.name}
            onChange={(event) => setNewPlan((prev) => ({ ...prev, name: event.target.value }))}
          />
          <input
            type="date"
            value={newPlan.plan_date}
            onChange={(event) => setNewPlan((prev) => ({ ...prev, plan_date: event.target.value }))}
          />
          <input
            type="number"
            step="any"
            placeholder="比例 %"
            value={newPlan.plan_ratio}
            onChange={(event) => setNewPlan((prev) => ({ ...prev, plan_ratio: event.target.value }))}
          />
          <input
            type="number"
            step="any"
            placeholder="金额（与比例二选一）"
            value={newPlan.plan_amount}
            onChange={(event) => setNewPlan((prev) => ({ ...prev, plan_amount: event.target.value }))}
          />
          <button type="submit" className="primary-btn small-btn" disabled={busy === 'add'}>
            {busy === 'add' ? '保存中…' : '保存这一期'}
          </button>
        </form>
      ) : null}

      <div className="payplan__table-wrap">
        <table className="payplan__table">
          <thead>
            <tr>
              <th>期次</th>
              <th>名称</th>
              <th>计划日期</th>
              <th>比例</th>
              <th>计划金额</th>
              <th>已付金额</th>
              <th>差额</th>
              <th>回单</th>
              {readOnly ? null : <th>操作</th>}
            </tr>
          </thead>
          <tbody>
            {plans.length === 0 && !loading ? (
              <tr>
                <td colSpan={readOnly ? 8 : 9} className="payplan__empty">
                  还没有付款计划。可以点「一键三期 30/40/30」快速铺好，再逐期改日期与金额。
                </td>
              </tr>
            ) : null}
            {plans.map((plan) => {
              const rowDraft = draft[plan.id] || {};
              const planDate = rowDraft.plan_date ?? plan.plan_date ?? '';
              const planAmount = rowDraft.plan_amount ?? plan.plan_amount ?? '';
              const paidAmount = rowDraft.paid_amount ?? plan.paid_amount ?? '';
              return (
                <tr key={plan.id} data-payplan-row={plan.id} className={plan.settled ? 'is-settled' : ''}>
                  <td>{plan.period_no}</td>
                  <td title={plan.name || ''}>{plan.name || '—'}</td>
                  <td>
                    <input
                      type="date"
                      value={planDate}
                      disabled={readOnly}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          [plan.id]: { ...(prev[plan.id] || {}), plan_date: event.target.value },
                        }))
                      }
                      onBlur={(event) => saveRow(plan, 'plan_date', event.target.value)}
                    />
                  </td>
                  <td>{plan.plan_ratio === null ? '—' : `${plan.plan_ratio}%`}</td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      className="is-money"
                      value={planAmount}
                      disabled={readOnly}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          [plan.id]: { ...(prev[plan.id] || {}), plan_amount: event.target.value },
                        }))
                      }
                      onBlur={(event) => saveRow(plan, 'plan_amount', event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="any"
                      className="is-money is-paid"
                      data-payplan-paid={plan.id}
                      value={paidAmount}
                      disabled={readOnly}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          [plan.id]: { ...(prev[plan.id] || {}), paid_amount: event.target.value },
                        }))
                      }
                      onBlur={(event) => saveRow(plan, 'paid_amount', event.target.value)}
                    />
                  </td>
                  <td className={plan.shortfall > 0 ? 'is-gap' : 'is-ok'}>
                    {money(Math.abs(plan.shortfall))}
                    {plan.shortfall < 0 ? '（超）' : ''}
                  </td>
                  <td>
                    {plan.has_receipt ? (
                      <button
                        type="button"
                        className="link-btn"
                        data-payplan-receipt={plan.id}
                        onClick={() => openReceipt(plan)}
                        title={plan.receipt_name || '查看回单'}
                      >
                        查看回单
                      </button>
                    ) : readOnly ? (
                      '—'
                    ) : (
                      <label className="payplan__upload">
                        <input
                          type="file"
                          accept=".pdf,.png,.jpg,.jpeg,.webp,.bmp"
                          ref={(node) => {
                            fileRefs.current[plan.id] = node;
                          }}
                          onChange={(event) => uploadReceipt(plan, event.target.files?.[0])}
                          data-payplan-upload={plan.id}
                        />
                        <span>{busy === `up-${plan.id}` ? '上传中…' : '上传'}</span>
                      </label>
                    )}
                  </td>
                  {readOnly ? null : (
                    <td>
                      <button
                        type="button"
                        className="secondary-btn small-btn cledger__danger"
                        onClick={() => removePlan(plan)}
                        disabled={busy === `del-${plan.id}`}
                      >
                        删除
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="payplan__hint">
        计划金额与「已付金额」失焦即保存；「已付」由财务按期登记（不是从流水反推），
        回单支持 PDF / 图片，单份 20MB 以内。
      </p>
    </section>
  );
}
