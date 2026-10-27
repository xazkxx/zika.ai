/**
 * 项目资金试算（沙盘推演）v1.81.0 · 2026-10-26
 *
 * 一句话定位：把「一批货的销售 + 采购」喂进模型，吐出
 *   毛利 → 七个税 → 净利 → **垫资占用费** → 扣完资金成本的净利。
 *
 * 三条硬约束（都是用户拍板的，改代码前先读）：
 *   1. **绝不写库**：所有数字都来自 `POST /project-calc/compute`（纯函数），
 *      草稿只进 localStorage；「从单据带出」是 GET 快照，改数不回写任何单据。
 *   2. **一次总账**：不再分第 1 批/第 2 批 —— 测算看的是整个盘子的资金占用。
 *      需要分批对比时，把批次当产品名填成两行即可。
 *   3. **进销数量分开**：采购数量留空才等于销售数量；填了就算压货。
 *
 * 交互节奏：改数 → debounce 250ms → 请求 → 只换右侧结果，输入框永远不等接口。
 * 失败不清空上一次结果，只在顶部挂一条红字（测算工具最忌讳"改个数字整页没了"）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import ErpKpiStrip from '../components/ui/ErpKpiStrip.jsx';
import CalcLineTable from '../components/project-calc/CalcLineTable';
import CapitalSettings from '../components/project-calc/CapitalSettings';
import CapitalBars from '../components/project-calc/CapitalBars';
import ProfitFunnel from '../components/project-calc/ProfitFunnel';
import TaxDonut from '../components/project-calc/TaxDonut';
import {
  DEFAULT_SETTINGS,
  SAMPLE_LINES,
  clearDraft,
  emptyLine,
  loadDraft,
  money,
  moneyWan,
  num,
  percent,
  saveDraft,
  toPayloadLines,
} from '../lib/projectCalc';
import '../components/project-calc/projectCalc.css';

const PREFILL_SOURCES = [
  { key: 'sale', label: '销售单', hint: '带出卖价与数量，成本自己补' },
  { key: 'purchase', label: '采购单', hint: '带出进价与数量，卖价按合同补' },
  { key: 'contract', label: '合同', hint: '采购合同落成本侧，销售合同落收入侧' },
];

export default function ProjectCalcPage({ ctx }) {
  const { API_BASE, authHeaders, setNotice } = ctx;

  // localStorage 只在**首次渲染读一次**：放在 useRef 的参数里会每次渲染都 JSON.parse 一遍。
  const initialRef = useRef(undefined);
  if (initialRef.current === undefined) initialRef.current = loadDraft();
  const restored = initialRef.current;

  const [label, setLabel] = useState(restored?.label || '');
  const [lines, setLines] = useState(restored?.lines || SAMPLE_LINES);
  const [settings, setSettings] = useState(restored?.settings || DEFAULT_SETTINGS);
  const [isSample, setIsSample] = useState(!restored);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 从单据带出
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerSource, setPickerSource] = useState('sale');
  const [pickerRows, setPickerRows] = useState([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerNote, setPickerNote] = useState('');
  const abortRef = useRef(null);

  /* ---------------- 改数即算 ---------------- */
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        const response = await fetch(`${API_BASE}/project-calc/compute`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, lines: toPayloadLines(lines), settings: { ...settings } }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`测算失败（HTTP ${response.status}）`);
        const data = await response.json();
        setResult(data);
        setError('');
      } catch (err) {
        if (err.name === 'AbortError') return;
        setError(err.message || '测算失败');
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
    // label 不进依赖：改项目名不需要重算数字
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines, settings, API_BASE]);

  /* ---------------- 草稿：只存浏览器 ---------------- */
  useEffect(() => {
    // 示例数据不落草稿：否则下次打开就是"一份改过的示例"，顶部那行
    // 「示例数据来自 v6，可随意改」的提示就再也不会出现了。
    if (isSample) return;
    const timer = setTimeout(() => {
      saveDraft({ label, lines, settings });
    }, 400);
    return () => clearTimeout(timer);
  }, [label, lines, settings, isSample]);

  const patchLine = useCallback((index, patch) => {
    setIsSample(false);
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }, []);

  const addLine = useCallback(() => {
    setIsSample(false);
    setLines((prev) => [...prev, emptyLine()]);
  }, []);

  const removeLine = useCallback((index) => {
    setIsSample(false);
    setLines((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const patchSettings = useCallback((patch) => {
    setIsSample(false);
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetAll = useCallback(() => {
    clearDraft();
    setLines(SAMPLE_LINES);
    setSettings(DEFAULT_SETTINGS);
    setLabel('');
    setIsSample(true);
    setNotice?.('已恢复 Excel v6 示例数据（仍不写库）');
  }, [setNotice]);

  const clearAll = useCallback(() => {
    setLines([emptyLine()]);
    setSettings(DEFAULT_SETTINGS);
    setIsSample(false);
  }, []);

  /* ---------------- 从单据带出（只读快照） ---------------- */
  const loadSources = useCallback(
    async (source) => {
      setPickerLoading(true);
      try {
        const response = await fetch(`${API_BASE}/project-calc/sources?source=${source}&limit=50`, {
          headers: authHeaders(),
        });
        if (!response.ok) throw new Error(`读取单据失败（HTTP ${response.status}）`);
        const data = await response.json();
        setPickerRows(Array.isArray(data.rows) ? data.rows : []);
        setPickerNote('');
      } catch (err) {
        setPickerRows([]);
        setPickerNote(err.message || '读取失败');
      } finally {
        setPickerLoading(false);
      }
    },
    [API_BASE, authHeaders],
  );

  const openPicker = useCallback(() => {
    setPickerOpen(true);
    setPickerNote('');
    loadSources(pickerSource);
  }, [loadSources, pickerSource]);

  const applyPrefill = useCallback(
    async (row) => {
      try {
        const response = await fetch(`${API_BASE}/project-calc/prefill/${pickerSource}/${row.id}`, {
          headers: authHeaders(),
        });
        if (!response.ok) throw new Error(`读取单据明细失败（HTTP ${response.status}）`);
        const data = await response.json();
        const next = (data.lines || []).map((line) => ({
          product_name: line.product_name || '',
          unit: line.unit || '米',
          qty: line.qty ?? '',
          cost_qty: line.cost_qty ?? '',
          sale_price: line.sale_price ?? '',
          cost_price: line.cost_price ?? '',
          has_invoice: line.has_invoice !== false,
        }));
        setLines(next.length ? next : [emptyLine()]);
        setLabel(data.label || '');
        setIsSample(false);
        setPickerOpen(false);
        setNotice?.(`已带出 ${data.label}（${next.length} 行），改数不会回写单据`);
      } catch (err) {
        setPickerNote(err.message || '带出失败');
      }
    },
    [API_BASE, authHeaders, pickerSource, setNotice],
  );

  /* ---------------- 派生展示量 ---------------- */
  const summary = result?.summary;
  const totals = result?.totals;
  const capital = result?.capital;
  const warnings = result?.warnings || [];

  const conclusion = `毛利率 ${percent(summary?.gross_margin)}、净利率 ${percent(totals?.net_margin)}；
    要垫 ${moneyWan(capital?.advance)}、压 ${num(capital?.occupy_days)} 天，资金成本 ${money(capital?.fee)}，
    折完 ${percent(capital?.net_after_margin)}。`;

  const kpis = [
    { key: 'sale', label: '含税销售', value: moneyWan(summary?.sale_incl), hint: money(summary?.sale_incl) },
    { key: 'gross', label: '不含税毛利', value: moneyWan(summary?.gross_profit), hint: `毛利率 ${percent(summary?.gross_margin)}` },
    { key: 'tax', label: '税金合计', value: moneyWan(totals?.tax_total), hint: `增值税 ${moneyWan(totals?.vat_due)}` },
    { key: 'advance', label: '要垫多少钱', value: moneyWan(capital?.advance), hint: `占用 ${num(capital?.occupy_days)} 天 · 资金成本 ${money(capital?.fee)}` },
    {
      key: 'net',
      label: '扣完资金成本净利',
      value: moneyWan(capital?.net_after_fee),
      hint: `净利率 ${percent(capital?.net_after_margin)}（原 ${percent(totals?.net_margin)}）`,
      strong: true,
    },
  ];

  return (
    <section className="pc" data-project-calc-page>
      <header className="pc__head">
        <div className="pc__title">
          <h2>项目资金试算</h2>
          <p>
            只看数、不写库。左边填进销，右边出毛利、七个税、垫资占用费 ——
            口径与《电线采购销售税额试算表 v6》逐格一致，差一分就是 bug。
          </p>
        </div>
        <div className="pc__actions">
          <input
            className="pc-input pc__label-input"
            value={label}
            placeholder="项目名 / 客户名（仅用于显示）"
            aria-label="项目名"
            onChange={(event) => setLabel(event.target.value)}
          />
          <button type="button" className="secondary-btn small-btn" onClick={openPicker}>
            从单据带出
          </button>
          <button type="button" className="secondary-btn small-btn" onClick={clearAll}>
            清空重填
          </button>
          <button type="button" className="secondary-btn small-btn" onClick={resetAll}>
            恢复示例
          </button>
        </div>
      </header>

      {error ? (
        <p className="pc__alert" role="alert">
          {error}　（下面的数字是上一次成功的结果，没被清掉）
        </p>
      ) : null}

      {isSample ? (
        <p className="pc__banner">
          示例数据来自《税额试算表 v6》的 5 个产品行（销售 261.76 万 / 成本 175.63 万），可直接改。
          草稿只存在这台电脑的浏览器里，换电脑就没了 —— 这是刻意的：测算数据绝不进业务库。
        </p>
      ) : null}

      <div className="pc__layout">
        <div className="pc__left">
          <section className="pc-card">
            <header className="pc-card__head">
              <h3>进销明细</h3>
              <span className="pc-card__sub">含税单价；采购数量留空 = 同销售数量</span>
            </header>
            <CalcLineTable lines={lines} onChange={patchLine} onAdd={addLine} onRemove={removeLine} />
          </section>

          <CapitalSettings settings={settings} onChange={patchSettings} onReset={() => setSettings(DEFAULT_SETTINGS)} />
        </div>

        <div className="pc__right">
          <ErpKpiStrip items={kpis} dense className="pc__kpis" />

          <div className="pc__charts">
            <section className="pc-card">
              <header className="pc-card__head">
                <h3>利润漏斗</h3>
                <span className="pc-card__sub">含税销售 100% 起算</span>
              </header>
              <ProfitFunnel summary={summary} totals={totals} />
            </section>

            <section className="pc-card">
              <header className="pc-card__head">
                <h3>资金占用</h3>
                <span className="pc-card__sub">垫资与回款天数的代价</span>
              </header>
              <CapitalBars capital={capital} sensitivity={result?.sensitivity} />
            </section>

            <section className="pc-card">
              <header className="pc-card__head">
                <h3>税负结构</h3>
                <span className="pc-card__sub">七项税金占比</span>
              </header>
              <TaxDonut taxes={result?.taxes} totals={totals} summary={summary} />
            </section>
          </div>

          <section className="pc-card">
            <header className="pc-card__head">
              <h3>回款敏感性</h3>
              <span className="pc-card__sub">付款固定 {num(settings.pay_days)} 天，只动回款</span>
            </header>
            <table className="pc-sens">
              <thead>
                <tr>
                  <th>回款周期</th>
                  <th className="is-num">占用天数</th>
                  <th className="is-num">资金成本</th>
                  <th className="is-num">净利</th>
                  <th className="is-num">净利率</th>
                </tr>
              </thead>
              <tbody>
                {(result?.sensitivity || []).map((row) => (
                  <tr
                    key={row.collect_days}
                    className={row.collect_days === num(settings.collect_days) ? 'is-current' : ''}
                  >
                    <td>
                      {row.collect_days} 天
                      {row.collect_days === num(settings.collect_days) ? '（当前）' : ''}
                    </td>
                    <td className="is-num">{row.days}</td>
                    <td className="is-num">{money(row.fee)}</td>
                    <td className="is-num">{money(row.net_after_fee)}</td>
                    <td className="is-num">{percent(row.margin)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="pc-card pc-conclusion">
            <header className="pc-card__head">
              <h3>一句话结论</h3>
              <span className="pc-card__sub">{loading ? '计算中…' : '按当前参数自动生成'}</span>
            </header>
            <p>{conclusion}</p>
            {warnings.length ? (
              <ul className="pc-conclusion__warnings">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <details className="pc-card pc-notes">
            <summary>口径说明（与 Excel v6 的逐格对照）</summary>
            <ul>
              <li>毛利 = 不含税销售 − 不含税成本（不是含税差，差了一整个增值税）。</li>
              <li>七个税种各自 ROUND 到分再求和；附加税三兄弟与印花税按六税两费减半。</li>
              <li>印花税基数 = 销售含税 + 采购含税；水利基金基数 = 销售不含税。两者不能互换。</li>
              <li>企业所得税不进税前利润扣减项（防循环引用），按税前利润 × 5%。</li>
              <li>未取得专票：成本不含税照旧 ÷1.13，只是进项按 0 —— 增值税会变高，这才是真实代价。</li>
              <li>垫资 = 成本含税 + 流转税现金 − 预收 − 定金；占用天数 = max(回款 − 付款, 0)；所得税默认不计入垫资。</li>
              <li>增值税留抵时附加税基数按 0 计（Excel 直接算会得出负附加税，那是错的）。</li>
            </ul>
          </details>
        </div>
      </div>

      {pickerOpen ? (
        <>
          <div className="pc-picker__mask" onClick={() => setPickerOpen(false)} />
          <aside className="pc-picker" role="dialog" aria-label="从单据带出">
            <header className="pc-picker__head">
              <h3>从单据带出（只读取一份快照）</h3>
              <button type="button" className="pc-icon-btn" onClick={() => setPickerOpen(false)} aria-label="关闭">
                ×
              </button>
            </header>
            <div className="pc-picker__tabs">
              {PREFILL_SOURCES.map((source) => (
                <button
                  key={source.key}
                  type="button"
                  className={`pc-picker__tab${pickerSource === source.key ? ' is-active' : ''}`}
                  title={source.hint}
                  onClick={() => {
                    setPickerSource(source.key);
                    loadSources(source.key);
                  }}
                >
                  {source.label}
                </button>
              ))}
            </div>
            {pickerNote ? <p className="pc-picker__note">{pickerNote}</p> : null}
            <div className="pc-picker__list">
              {pickerLoading ? <p className="pc-picker__note">读取中…</p> : null}
              {!pickerLoading && pickerRows.length === 0 ? (
                <p className="pc-picker__note">没有可带出的单据。</p>
              ) : null}
              {pickerRows.map((row) => (
                <button key={row.id} type="button" className="pc-picker__row" onClick={() => applyPrefill(row)}>
                  <span className="pc-picker__no">{row.doc_no}</span>
                  <span className="pc-picker__party">{row.party || '—'}</span>
                  <span className="pc-picker__date">{row.date || '—'}</span>
                  <span className="pc-picker__amount">{money(row.amount)}</span>
                  <span className="pc-picker__tag">{row.tag}</span>
                </button>
              ))}
            </div>
            <p className="pc-picker__foot">
              带出后就是页面上的自由变量。改多少都不会回写销售单 / 采购单 / 合同。
            </p>
          </aside>
        </>
      ) : null}
    </section>
  );
}
