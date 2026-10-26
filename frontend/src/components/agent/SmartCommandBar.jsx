/**
 * SmartCommandBar —— 🤖 智能指令搜索框（2026-10-23）
 *
 * 放在工作台最顶部：输入一句人话（"给我湖南华邦的对账单"），
 * 后端 `/agent/dispatch` 解析意图 + 认人 + 取数，这里把结果渲染成**悬浮卡片**，
 * 每个卡片带一两个"真能干活"的按钮（预览 / 生成 PDF / 导出 Word / 去修改）。
 *
 * ## 三条克制
 *
 * 1. **不替代任何页面**。这里只做"找得到、看得见、跳得过去"：
 *    真正的编辑/审核/生成动作仍然在「购销合同」「增强对账单」页面上完成 ——
 *    那两页有各自的校验、编号、权限与留痕，搜索框里再实现一遍就是两套逻辑。
 * 2. **只读**。组件自己只发三类请求：dispatch（查）、preview（看）、pdf/word（导出）。
 *    没有任何写操作，点错最坏就是白看一次。
 * 3. **认不出人要说清楚**。后端返回 `candidates` 时列表在这儿可点，
 *    点一下就用那家的名字重新查 —— 比让用户回去改错别字快得多。
 *
 * ## 为什么要 `<mark>` 高亮命中的人名
 * 用户打了简称（"蒲白750"），系统认成"蒲白750千伏输变电工程(线路工程包2)"，
 * 必须让他一眼看到"你到底给我挑的是哪一家"，否则会拿错单位的对账单。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE as DEFAULT_API_BASE } from '../../lib/appLib.js';
import { saveBlobSmart } from '../../lib/download.js';
import './smartCommand.css';

const EXAMPLES = [
  '给我湖南华邦的对账单',
  '蒲白750 的合同',
  '陕西送变电的对账',
];

// 下拉项的类型 → 徽标样式与文案（2026-10-24 加分类节点）
const SUG_BADGE = {
  customer: 'blue',
  supplier: 'teal',
  'customer-category': 'blue',
  'supplier-category': 'teal',
};
const SUG_LABEL = {
  customer: '客户',
  supplier: '供应商',
  'customer-category': '客户分类',
  'supplier-category': '供应商分类',
};

const fmtMoney = (value) => {
  const num = Number(value || 0);
  return `¥${num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const STATUS_TONE = {
  draft: 'gray',
  confirmed: 'blue',
  sent: 'teal',
  void: 'red',
  active: 'blue',
  signed: 'blue',
  executing: 'teal',
  finished: 'green',
  unsettled: 'amber',
};

export default function SmartCommandBar({
  apiBase = DEFAULT_API_BASE,
  authHeaders,
  /** 跳到业务页并预填筛选：({page, ...}) => void，由 App.jsx 提供 */
  onGoto,
}) {
  const inputRef = useRef(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null); // {kind, loading, data, error}
  // —— 实时下拉（2026-10-24）：输入即提示，点击即执行 ——
  const [sugs, setSugs] = useState([]);
  const [sugOpen, setSugOpen] = useState(false);
  const [sugIndex, setSugIndex] = useState(0);
  // 点选某条提示后 800ms 内不许下拉再弹出来 —— 否则会盖在结果卡片上
  const suppressSugRef = useRef(0);

  const headers = useCallback(() => (authHeaders ? authHeaders() : {}), [authHeaders]);

  /**
   * 实时认人：输入变化后 180ms 防抖调 `/agent/suggest`。
   * 静默失败 —— 提示拉不到只是少个下拉，绝不能挡住用户手打回车的老路。
   */
  useEffect(() => {
    const query = String(text || '').trim();
    if (!query) {
      setSugs([]);
      setSugOpen(false);
      return undefined;
    }
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `${apiBase}/agent/suggest?q=${encodeURIComponent(query)}`,
          { headers: headers() },
        );
        if (!response.ok) return;
        const data = await response.json().catch(() => ({}));
        if (Date.now() - suppressSugRef.current < 800) return;
        const list = Array.isArray(data.suggestions) ? data.suggestions : [];
        setSugs(list);
        setSugIndex(0);
        // 2026-10-24：只要请求回来了就开下拉 —— 命中就列人，
        // 没命中显示"没找到"空态行。否则"库里没这个人"和"功能坏了"
        // 在用户眼里是同一个样子（什么都不出现），没法排查。
        setSugOpen(true);
      } catch {
        /* 下拉是锦上添花，静默 */
      }
    }, 180);
    return () => clearTimeout(timer);
  }, [text, apiBase, headers]);

  /** 点下拉项 = 自动补成完整指令并立刻执行（用户一个字都不用再敲）。
   *  分类节点（客户分类/供应商分类）没有"对账单"可查 —— 跳到对应档案页
   *  并把分类名填进搜索框，让列表直接筛出这个分类下的档案。 */
  const pickSuggestion = (item) => {
    if (!item) return;
    suppressSugRef.current = Date.now();
    setSugs([]);
    setSugOpen(false);
    if (item.type === 'customer-category' || item.type === 'supplier-category') {
      onGoto?.({
        page: item.type === 'customer-category' ? 'customers' : 'suppliers',
        keyword: item.name,
      });
      return;
    }
    // 用户输入里带了"合同/协议"就补合同，否则默认对账单（最高频意图）
    const suffix = /合同|协议/.test(text) ? '的合同' : '的对账单';
    const command = `给我${item.name}${suffix}`;
    setText(command);
    run(command);
  };

  const run = useCallback(
    async (raw) => {
      const query = String(raw ?? text ?? '').trim();
      if (!query) {
        setError('先说一句要查什么，例如「给我湖南华邦的对账单」');
        return;
      }
      setBusy('dispatch');
      setError('');
      try {
        const response = await fetch(`${apiBase}/agent/dispatch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...headers() },
          body: JSON.stringify({ text: query }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === 'string' ? data.detail : `查询失败（HTTP ${response.status}）`);
        }
        setResult(data);
        setOpen(true);
      } catch (err) {
        setError(err.message || '查询失败');
      } finally {
        setBusy('');
      }
    },
    [apiBase, headers, text],
  );

  /** 用候选单位名重查（点候选 chip 时） */
  const requeryParty = (party) => {
    const suffix = result?.type === 'contract' ? '的合同' : '的对账单';
    const next = `${party.name}${suffix}`;
    setText(next);
    run(next);
  };

  // Esc 关闭：预览弹窗 > 下拉提示 > 结果面板（就近原则，一层一层关）
  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      if (preview) {
        setPreview(null);
        return;
      }
      if (sugOpen) {
        setSugOpen(false);
        return;
      }
      if (open) setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, preview, sugOpen]);

  const openContractPreview = async (card) => {
    setPreview({ kind: 'contract', loading: true, card, data: null, error: '' });
    try {
      const response = await fetch(`${apiBase}/contracts/document/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers() },
        body: JSON.stringify({ contract_id: card.id }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '读不到合同正文');
      setPreview({ kind: 'contract', loading: false, card, data: data.document, error: '' });
    } catch (err) {
      setPreview({ kind: 'contract', loading: false, card, data: null, error: err.message || '预览失败' });
    }
  };

  const openStatementPreview = async (card) => {
    setPreview({ kind: 'statement', loading: true, card, data: null, error: '' });
    try {
      const response = await fetch(`${apiBase}/statements/${card.id}`, { headers: headers() });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '读不到对账单');
      setPreview({ kind: 'statement', loading: false, card, data, error: '' });
    } catch (err) {
      setPreview({ kind: 'statement', loading: false, card, data: null, error: err.message || '预览失败' });
    }
  };

  /** 对账单 PDF：走 `Accept: application/json` 的 base64 通道（PDF 直链会被浏览器接管） */
  const downloadStatementPdf = async (card) => {
    setBusy(`pdf-${card.id}`);
    setError('');
    try {
      const response = await fetch(`${apiBase}/print/statement-record/${card.id}`, {
        headers: { ...headers(), Accept: 'application/json' },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.content_base64) {
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 PDF 失败');
      }
      const raw = atob(data.content_base64);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
      if (!bytes.length) throw new Error('生成的对账单 PDF 是空的');
      const blob = new Blob([bytes], { type: 'application/pdf' });
      // 落盘统一口：PDF 被打上来源标记后，Edge/Acrobat 也会进受保护视图
      // （用户看到的是"文件已损坏"，与 Excel 那次是同一个病，见 lib/download.js 顶部）。
      await saveBlobSmart(blob, data.filename || `${card.no}.pdf`);
    } catch (err) {
      setError(err.message || '生成 PDF 失败');
    } finally {
      setBusy('');
    }
  };

  /** 合同 Word：二进制直链（docx 不像 zip 那样会被浏览器拦），但要挡 0 字节 */
  const downloadContractWord = async (card) => {
    setBusy(`word-${card.id}`);
    setError('');
    try {
      const response = await fetch(`${apiBase}/exports/word/contract/${card.id}`, { headers: headers() });
      if (!response.ok) throw new Error(`导出 Word 失败（HTTP ${response.status}）`);
      const blob = await response.blob();
      if (!blob.size) throw new Error('导出的 Word 是空文件');
      // 合同 Word 同样走统一落盘口（Word 也做受保护视图）
      await saveBlobSmart(blob, `${card.no || 'contract'}.docx`);
    } catch (err) {
      setError(err.message || '导出 Word 失败');
    } finally {
      setBusy('');
    }
  };

  const goto = (pagePayload) => {
    if (!pagePayload || !onGoto) return;
    setOpen(false);
    onGoto(pagePayload);
  };

  const cards = result?.matched_data || [];
  const statementCards = cards.filter((row) => row.kind === 'statement');
  const documentCards = cards.filter((row) => row.kind === 'document');
  const contractCards = cards.filter((row) => row.kind === 'contract');
  const party = result?.party || null;
  const gotoLink = result?.goto || {};

  return (
    <section className="scb" data-smart-command>
      <div className="scb__bar">
        <span className="scb__icon" aria-hidden="true">🤖</span>
        <input
          ref={inputRef}
          className="scb__input"
          data-scb-input
          value={text}
          placeholder="用一句话找我：给我湖南华邦的对账单 / 蒲白750 的合同"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // 下拉开着时，方向键/回车先归下拉用；Esc 先关下拉（全局监听兜底）
            if (sugOpen && sugs.length) {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setSugIndex((index) => Math.min(index + 1, sugs.length - 1));
                return;
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                setSugIndex((index) => Math.max(index - 1, 0));
                return;
              }
              if (event.key === 'Enter') {
                event.preventDefault();
                pickSuggestion(sugs[sugIndex] || sugs[0]);
                return;
              }
              if (event.key === 'Escape') {
                event.preventDefault();
                setSugOpen(false);
                return;
              }
            }
            if (event.key === 'Enter') {
              event.preventDefault();
              run();
            }
          }}
          onFocus={() => {
            if (result) setOpen(true);
          }}
        />
        <button
          type="button"
          className="primary-btn scb__run"
          data-scb-run
          onClick={() => run()}
          disabled={busy === 'dispatch'}
        >
          {busy === 'dispatch' ? '查询中…' : '执行'}
        </button>

        {/* —— 实时认人下拉（zgp / 周 → 周广平…），点击即执行 —— */}
        {sugOpen ? (
          sugs.length ? (
            <ul className="scb__sug" data-scb-sug role="listbox" aria-label="匹配到的往来单位">
              {sugs.map((item, index) => (
                <li key={`${item.type}-${item.id}`}>
                  <button
                    type="button"
                    className={`scb__sug-item ${index === sugIndex ? 'is-on' : ''}`}
                    data-scb-sug-item={item.name}
                    role="option"
                    aria-selected={index === sugIndex}
                    // onMouseDown 而不是 onClick：赶在 input blur 之前触发，
                    // 否则点下去先失焦、下拉先消失，onClick 永远轮不到
                    onMouseDown={(event) => {
                      event.preventDefault();
                      pickSuggestion(item);
                    }}
                    onMouseEnter={() => setSugIndex(index)}
                  >
                  <span className="scb__sug-name">{item.name}</span>
                  <span className={`scb__badge is-${SUG_BADGE[item.type] || 'gray'}`}>
                    {SUG_LABEL[item.type] || (item.type === 'supplier' ? '供应商' : '客户')}
                  </span>
                    {item.contact ? (
                      <span className="scb__sug-contact">联系人 {item.contact}</span>
                    ) : null}
                  {/pinyin/.test(item.matched_by || '') ? (
                    <span className="scb__sug-hint">拼音认出</span>
                  ) : item.matched_by === 'category' ? (
                    <span className="scb__sug-hint">分类节点</span>
                  ) : item.matched_by === 'contact' ? (
                    <span className="scb__sug-hint">按联系人</span>
                  ) : null}
                  </button>
                </li>
              ))}
              <li className="scb__sug-foot">↑↓ 选择 · 回车执行 · Esc 关闭</li>
            </ul>
          ) : (
            // 空态也要说话：区分"库里没这个人"和"功能没生效"
            <div className="scb__sug scb__sug-none" data-scb-sug-none>
              没找到与「{text.trim()}」匹配的往来单位 —— 回车按原话查询
            </div>
          )
        ) : null}
      </div>

      <div className="scb__examples">
        <span>试试：</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="scb__example"
            data-scb-example={example}
            onClick={() => {
              setText(example);
              run(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error ? (
        <p className="scb__error" data-scb-error>
          {error}
        </p>
      ) : null}

      {open && result ? (
        <div className="scb__panel" data-scb-panel={`${result.type}-${cards.length}`}>
          <div className="scb__panel-head">
            <div className="scb__panel-title">
              {party ? (
                <>
                  找到 <mark className="scb__mark">{party.name}</mark>
                  <span className="scb__party-tag">{party.type === 'supplier' ? '供应商' : '客户'}</span>
                </>
              ) : (
                // 2026-10-24：不再说指代不清的"没锁定具体单位"，
                // 后端的 message（"没找到「xx」…"）本身就是给用户看的
                <span>{result.message || '没找到匹配的往来单位'}</span>
              )}
            </div>
            <div className="scb__panel-meta">
              <span>{result.message}</span>
              <span className="scb__parser">解析：{result.intent?.parser === 'rules' ? '规则' : result.intent?.parser}</span>
            </div>
            <button type="button" className="scb__close" data-scb-close onClick={() => setOpen(false)} aria-label="关闭">
              ×
            </button>
          </div>

          {!party && (result.candidates || []).length ? (
            <div className="scb__candidates">
              <span>是不是：</span>
              {(result.candidates || []).map((item) => (
                <button
                  key={`${item.type}-${item.id}`}
                  type="button"
                  className="scb__candidate"
                  data-scb-candidate={item.name}
                  onClick={() => requeryParty(item)}
                >
                  {item.name}
                </button>
              ))}
            </div>
          ) : null}

          {/* —— 自动生成闭环（2026-10-25）：后端静默落了一张真草稿 ——
              高亮卡片置顶，[预览 PDF] 走页面内弹窗（里面还能直接生成 PDF），
              [去确认生成] 跳对账单编辑页。不踢去左侧列表。 —— */}
          {result.generated ? (
            <div className="scb__generated" data-scb-generated={result.generated.statement_no}>
              <div className="scb__generated-main">
                <span className="scb__generated-flag">⚡ 已自动生成草稿</span>
                <strong>{result.generated.statement_no}</strong>
                <span className="scb__generated-meta">
                  {result.generated.period ? `期间 ${result.generated.period} · ` : ''}
                  总金额 <b>{fmtMoney(result.generated.amount)}</b>
                </span>
              </div>
              <div className="scb__generated-actions">
                <button
                  type="button"
                  className="secondary-btn small-btn"
                  data-scb-generated-preview
                  onClick={() =>
                    openStatementPreview({
                      id: result.generated.id,
                      no: result.generated.statement_no,
                    })
                  }
                >
                  预览 PDF
                </button>
                {gotoLink.page ? (
                  <button
                    type="button"
                    className="primary-btn small-btn scb__generated-confirm"
                    data-scb-generated-confirm
                    onClick={() => goto({ ...gotoLink, nonce: Date.now() })}
                  >
                    去确认生成
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {statementCards.length ? (
            <div className="scb__group">
              <h4>已生成的对账单（{statementCards.length}）</h4>
              <div className="scb__cards">
                {statementCards.map((card) => (
                  <article className="scb__card" key={`st-${card.id}`} data-scb-card={`statement-${card.id}`}>
                    <div className="scb__card-head">
                      <strong>{card.no}</strong>
                      <span className={`scb__badge is-${STATUS_TONE[card.status] || 'gray'}`}>{card.status_label}</span>
                    </div>
                    <div className="scb__card-body">
                      <span>期间 {card.period || '—'}</span>
                      <span>金额 <b>{fmtMoney(card.amount)}</b></span>
                    </div>
                    <div className="scb__card-actions">
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        data-scb-preview={`statement-${card.id}`}
                        onClick={() => openStatementPreview(card)}
                      >
                        打开预览
                      </button>
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        data-scb-pdf={card.id}
                        onClick={() => downloadStatementPdf(card)}
                        disabled={busy === `pdf-${card.id}`}
                      >
                        {busy === `pdf-${card.id}` ? '生成中…' : '生成 PDF'}
                      </button>
                      {gotoLink.page ? (
                        <button type="button" className="link-btn" data-scb-goto onClick={() => goto(gotoLink)}>
                          去修改
                        </button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {documentCards.length ? (
            <div className="scb__group">
              <h4>
                未结清单据（{documentCards.length}）
                <span className="scb__group-note">欠款合计 {fmtMoney(result.summary?.outstanding_total)}</span>
              </h4>
              <div className="scb__cards">
                {documentCards.map((card) => (
                  <article
                    className="scb__card is-doc"
                    key={`doc-${card.id}`}
                    data-scb-card={`document-${card.id}`}
                  >
                    <div className="scb__card-head">
                      <strong>{card.no}</strong>
                      <span className="scb__badge is-amber">{card.status_label}</span>
                    </div>
                    <div className="scb__card-body">
                      <span>{card.date || '—'}</span>
                      <span>单据 {fmtMoney(card.amount)}</span>
                      <span>
                        欠款 <b className="is-owe">{fmtMoney(card.remaining)}</b>
                      </span>
                    </div>
                    <div className="scb__card-actions">
                      {gotoLink.page ? (
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          data-scb-goto
                          onClick={() => goto({ ...gotoLink, nonce: Date.now() })}
                        >
                          去生成对账单
                        </button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {contractCards.length ? (
            <div className="scb__group">
              <h4>
                合同（{contractCards.length}）
                <span className="scb__group-note">合计 {fmtMoney(result.summary?.amount_total)}</span>
              </h4>
              <div className="scb__cards">
                {contractCards.map((card) => (
                  <article className="scb__card" key={`ct-${card.id}`} data-scb-card={`contract-${card.id}`}>
                    <div className="scb__card-head">
                      <strong>{card.no}</strong>
                      <span className={`scb__badge is-${STATUS_TONE[card.status] || 'gray'}`}>{card.status_label}</span>
                    </div>
                    <div className="scb__card-body">
                      <span>{card.title || '购销合同'}</span>
                      <span>签订 {card.sign_date || '—'}</span>
                      <span>金额 <b>{fmtMoney(card.amount)}</b></span>
                    </div>
                    <div className="scb__card-actions">
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        data-scb-preview={`contract-${card.id}`}
                        onClick={() => openContractPreview(card)}
                      >
                        打开预览
                      </button>
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        data-scb-word={card.id}
                        onClick={() => downloadContractWord(card)}
                        disabled={busy === `word-${card.id}`}
                      >
                        {busy === `word-${card.id}` ? '导出中…' : '导出 Word'}
                      </button>
                      <button type="button" className="link-btn" data-scb-goto onClick={() => goto(gotoLink)}>
                        去确认
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {!cards.length && party ? (
            // empty=true（名下没单据）→ 黄字提示；说人话，别让用户猜是不是查错了人
            <p className={`scb__empty ${result.empty ? 'is-warn' : ''}`} data-scb-empty>
              {result.message ||
                (result.type === 'statement'
                  ? '这家单位暂时没有未结清单据，也没生成过对账单。'
                  : '这家单位名下还没有合同。')}
            </p>
          ) : null}
        </div>
      ) : null}

      {/* ================= 预览弹窗 ================= */}
      {preview ? (
        <div className="scb__mask" data-scb-preview-mask onClick={() => setPreview(null)}>
          <div className="scb__dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="scb__dialog-head">
              <strong>
                {preview.kind === 'contract'
                  ? `合同正文 · ${preview.data?.template_name || '内置范本'}`
                  : '对账单预览'}{' '}
                · {preview.card?.no}
              </strong>
              {preview.kind === 'contract' && preview.data ? (
                // 合同自己有标题（"克拉玛依…采购合同"），模板名单独标出来 ——
                // 用户要能一眼看出"正文是按哪套范本生成的"
                <span className="scb__dialog-tag" data-scb-template={preview.data.template_name || ''}>
                  {preview.data.template_name || ''}
                </span>
              ) : null}
              <button type="button" className="scb__close" data-scb-preview-close onClick={() => setPreview(null)}>
                ×
              </button>
            </div>
            <div className="scb__dialog-body">
              {preview.loading ? (
                <p className="scb__empty">读取中…</p>
              ) : preview.error ? (
                <p className="scb__error">{preview.error}</p>
              ) : preview.kind === 'contract' && preview.data ? (
                <>
                  <h3 className="scb__doc-title">{preview.data.title}</h3>
                  <p className="scb__doc-sub">
                    合同编号：{preview.data.contract_no} · 签订日期：{preview.data.sign_date || '—'}
                  </p>
                  <div className="scb__doc-parties">
                    <div>
                      <span>甲方</span>
                      <b>{preview.data.parties?.buyer?.name || '—'}</b>
                    </div>
                    <div>
                      <span>乙方</span>
                      <b>{preview.data.parties?.seller?.name || '—'}</b>
                    </div>
                  </div>
                  <table className="scb__table">
                    <thead>
                      <tr>
                        <th>序号</th>
                        <th>产品名称</th>
                        <th>规格</th>
                        <th>单位</th>
                        <th className="is-num">数量</th>
                        <th className="is-num">单价</th>
                        <th className="is-num">金额</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(preview.data.items || []).map((item) => (
                        <tr key={item.no}>
                          <td>{item.no}</td>
                          <td>{item.product_name}</td>
                          <td>{item.standards || ''}</td>
                          <td>{item.unit || ''}</td>
                          <td className="is-num">{item.quantity}</td>
                          <td className="is-num">{Number(item.unit_price).toFixed(2)}</td>
                          <td className="is-num">{Number(item.amount).toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={6}>合计（{preview.data.totals?.chinese}）</td>
                        <td className="is-num">{Number(preview.data.totals?.amount || 0).toFixed(2)}</td>
                      </tr>
                    </tfoot>
                  </table>
                  <ol className="scb__clauses">
                    {(preview.data.clauses || []).map((clause) => (
                      <li key={clause.no}>
                        <b>
                          {clause.no} {clause.heading}
                        </b>
                        {(clause.paragraphs || []).map((line) => (
                          <p key={line}>{line}</p>
                        ))}
                      </li>
                    ))}
                  </ol>
                </>
              ) : preview.kind === 'statement' && preview.data ? (
                <>
                  <div className="scb__doc-parties">
                    <div>
                      <span>往来单位</span>
                      <b>{preview.data.party_name || '—'}</b>
                    </div>
                    <div>
                      <span>账期</span>
                      <b>
                        {preview.data.period_start || '—'} ~ {preview.data.period_end || '—'}
                      </b>
                    </div>
                  </div>
                  <table className="scb__table">
                    <thead>
                      <tr>
                        <th>单据</th>
                        <th>日期</th>
                        <th className="is-num">金额</th>
                        <th className="is-num">已收/已付</th>
                        <th className="is-num">未收/未付</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(preview.data.items || []).slice(0, 12).map((item) => (
                        <tr key={item.id}>
                          <td>{item.doc_no || item.source_no || '—'}</td>
                          <td>{item.doc_date || item.business_date || '—'}</td>
                          <td className="is-num">{fmtMoney(item.amount)}</td>
                          <td className="is-num">{fmtMoney(item.received_amount)}</td>
                          <td className="is-num">{fmtMoney(item.outstanding_amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="scb__doc-sub">
                    共 {preview.data.items?.length || 0} 行 · 剩余未收 {fmtMoney(preview.data.outstanding_amount)}
                  </p>
                </>
              ) : null}
            </div>
            <div className="scb__dialog-actions">
              <button type="button" className="secondary-btn" data-scb-preview-close onClick={() => setPreview(null)}>
                关闭
              </button>
              {preview.kind === 'contract' && preview.card ? (
                <button
                  type="button"
                  className="primary-btn"
                  data-scb-preview-word
                  onClick={() => downloadContractWord(preview.card)}
                >
                  导出 Word
                </button>
              ) : null}
              {preview.kind === 'statement' && preview.card ? (
                <button
                  type="button"
                  className="primary-btn"
                  data-scb-preview-pdf
                  onClick={() => downloadStatementPdf(preview.card)}
                >
                  生成 PDF
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
