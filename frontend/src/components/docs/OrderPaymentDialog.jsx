/**
 * OrderPaymentDialog —— 订单「收款 / 付款」登记弹窗（采购、销售共用一套）
 *
 * 存在意义：后端 `POST /finance/receipt|payment`（erp_finance.py:271/278）逻辑一直是完整的
 * （冲订单欠款 + 超出部分拆预收 + 重算欠款链），但**前端零调用** —— 所以
 * `financial_transactions` 里从来没有 receipt/payment，对账单的「本期已收」永远是 0。
 * 这个弹窗就是那条断掉的前端链路。
 *
 * 职责边界（与 PartnerModal / sales-units 同一套约定）：
 *   · **完全受控**：自己不发请求、不知道接口路径。金额校验在本地做，
 *     落库成功/失败都靠父级传进来的 `result` / `error` 回显。
 *   · 不 import App.jsx、不读 ctx。
 *
 * 三个金额口径（跟后端 _register_payment 严格对齐，别自己发明）：
 *   净额   = total_amount - discount_amount
 *   已登记 = received_amount（销售） / paid_amount（采购）
 *   未收款 = max(净额 - 已登记, 0)
 * 录入金额允许 > 未收款：后端会把超出的部分拆成「预收/预付」，不硬挂在单据上
 * （否则单据会出现负欠款）。这里提前用黄字提示，避免你以为填错了。
 *
 * ⚠️ 「方式」目前**只写进流水备注**（`financial_transactions` 没有 method 列，
 *    `_write_finance` 也没有这个入参）。等以后要按方式出报表，再给流水表加列 +
 *    在 erp_finance.py 里透传 bank_account_id，那时只改父级拼备注那一行。
 *
 * ── 业财一体化（2026-10-22）：采购付款的「无票强提醒」──────────────────────
 * 业务规则是"先款后票"：钱先付、票后到。但"这笔付款没有票"在账上是**看不见**的，
 * 于是要么忘了催票，要么年底汇算才发现缺票。
 *
 * 所以付款弹窗多了一道**闸**（不是一句提示）：
 *   `invoiceStatus.need_invoice === true` 时，点「确认付款」**不会直接提交**，
 *   而是切到警告面板，逼你在三个出口里明确选一个：
 *       ① 先去索取发票（关掉弹窗，不付款）
 *       ② 做暂估处理并付款（流水备注打【暂估】）
 *       ③ 仍然付款、不记票（流水备注打【无票付款】）
 *
 * 为什么必须"拦一下"而不是弹个 toast：toast 会被当成"保存成功"的反馈，
 * 用户点完就走；而"这笔钱没票"是三个月后要还的债，必须当场留疤。
 * 注意后端**不拦**（钱已经付了，拦也变不出票），只把票属性如实记在流水上。
 */

import { useEffect, useState } from 'react';
import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import './pay-dialog.css';

const round2 = (value) => Math.round(Number(value || 0) * 100) / 100;

const money = (value) =>
  Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 本地日期 yyyy-mm-dd。⚠️ 别用 toISOString()：那是 UTC，晚上 8 点后会变成"昨天" */
function today() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

/** 收款方式。候选值刻意保持"人话"，落库进备注，不做枚举校验。 */
const METHODS = ['现金', '微信', '支付宝', '银行转账', '承兑汇票', '其他'];

const COPY = {
  sales: {
    verb: '收款',
    title: '登记收款',
    dueLabel: '应收',
    doneLabel: '已收',
    leftLabel: '待收',
    amountLabel: '本次收款金额',
    submit: '确认收款',
    hint: '按回车或点「确认收款」写入资金流水，并冲减本单欠款',
  },
  purchase: {
    verb: '付款',
    title: '登记付款',
    dueLabel: '应付',
    doneLabel: '已付',
    leftLabel: '待付',
    amountLabel: '本次付款金额',
    submit: '确认付款',
    hint: '按回车或点「确认付款」写入资金流水，并冲减本单欠款',
  },
};

export default function OrderPaymentDialog({
  open = false,
  kind = 'sales',
  order = null,
  /** 对方名称（客户/供应商）：只用于弹窗标题下的说明，由父级查好传进来 */
  partyName = '',
  /**
   * 票据状态（父级拉 `GET /orders/purchase/{id}/invoice-status` 得到）：
   * `{ net_amount, invoiced_amount, uninvoiced_amount, invoice_count, status, need_invoice }`
   * 只有采购（付款）会用到；销售传 null 即可。
   */
  invoiceStatus = null,
  /** 票据状态还在路上：付款按钮先别让点，免得"无票闸门"因为数据没到而被绕过 */
  invoiceLoading = false,
  onSubmit,
  onClose,
  busy = false,
  /** 后端返回体：{ amount, applied_amount, prepaid_amount, occurred_at } —— 有值就切到"成功"态 */
  result = null,
  /** 父级把接口错误文案透传进来 */
  error = '',
}) {
  const isSales = kind !== 'purchase';
  const copy = isSales ? COPY.sales : COPY.purchase;

  const [amount, setAmount] = useState('');
  const [occurredAt, setOccurredAt] = useState(today());
  const [method, setMethod] = useState('银行转账');
  const [note, setNote] = useState('');
  const [localError, setLocalError] = useState('');
  /** 无票闸门：true = 正卡在"这笔没票，你选一个出口"的警告面板上 */
  const [invoiceGate, setInvoiceGate] = useState(false);

  const orderId = order?.id ?? null;
  const net = round2(Number(order?.total_amount || 0) - Number(order?.discount_amount || 0));
  const done = round2(order?.[isSales ? 'received_amount' : 'paid_amount'] || 0);
  const left = round2(Math.max(net - done, 0));

  // —— 无票判定：只有采购付款才看它 ——
  // 以**后端**为准（后端口径 = 完结闸口径），前端不自己算一遍，否则两个口径一漂，
  // 就会出现"弹窗说没票、完结却说开满了"这种没人信得过的提示。
  const invoicedAmount = round2(invoiceStatus?.invoiced_amount ?? 0);
  const uninvoicedAmount = round2(invoiceStatus?.uninvoiced_amount ?? 0);
  const invoiceCount = Number(invoiceStatus?.invoice_count ?? 0);
  const needInvoice = Boolean(!isSales && invoiceStatus && invoiceStatus.need_invoice);

  // 每次"换一张单 / 重新打开"都重置成默认值：金额默认填满待收（最常见的情况），
  // 方式优先用单据上已经选过的 payment_method。
  // 依赖只放 open 与 orderId —— 金额按需重新算，不放 left 是为了避免
  // 父级列表刷新（order 对象换新）时把你正在输入的金额冲掉。
  useEffect(() => {
    if (!open) return;
    setAmount(left > 0 ? left.toFixed(2) : '');
    setOccurredAt(today());
    setMethod(order?.payment_method || '银行转账');
    setNote('');
    setLocalError('');
    setInvoiceGate(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, orderId]);

  // ESC 关闭：和客户文件抽屉保持一致的手感。
  // 登记中不给关；**已经有结果**时放行 —— 那之后 busy 只是在等父级刷新列表。
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && (!busy || result)) onClose?.();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, busy, result, onClose]);

  if (!open || !order) return null;

  const value = Number(amount);
  const valid = Number.isFinite(value) && value > 0;
  const overflow = valid ? round2(value - left) : 0;
  const message = localError || error;

  // 真正提交（带票属性标记）。闸门上的两个出口都走它。
  const doSubmit = (extra = {}) => {
    setInvoiceGate(false);
    onSubmit?.({
      amount: round2(value),
      occurred_at: occurredAt,
      method,
      note: note.trim(),
      ...extra,
    });
  };

  const submit = (event) => {
    event.preventDefault();
    if (busy) return;
    if (!Number.isFinite(value) || value <= 0) {
      setLocalError('金额必须大于 0');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(occurredAt)) {
      setLocalError('日期格式应为 YYYY-MM-DD');
      return;
    }
    if (!isSales && invoiceLoading) {
      // 票据状态还没回来就提交，等于让闸门形同虚设 —— 先等一下
      setLocalError('正在核对这张单的进项发票，请稍候…');
      return;
    }
    setLocalError('');
    // ⭐ 无票闸门：点「确认付款」**不提交**，先切到警告面板让用户明确选出口。
    //    这里刻意不用 toast/confirm()：toast 会被当成"保存成功"，拦不住任何人。
    if (needInvoice) {
      setInvoiceGate(true);
      return;
    }
    doSubmit();
  };

  return (
    <div className="modal-backdrop" onClick={() => (!busy || result ? onClose?.() : null)}>
      <div
        className="modal-card order-pay-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={copy.title}
        data-order-pay-dialog={kind}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{copy.title}</h3>
          <button
            type="button"
            className="close-btn"
            onClick={onClose}
            disabled={busy && !result}
            aria-label="关闭"
            data-pay-cancel
          >
            ×
          </button>
        </div>

        <div className="order-pay-dialog__meta">
          <span className="order-pay-dialog__no">{order.order_no || `#${order.id}`}</span>
          {partyName ? <span className="order-pay-dialog__party">{partyName}</span> : null}
          {/* 票据角标：付款前就能看见"这单有没有票"，不用等点了才知道 */}
          {!isSales && invoiceStatus ? (
            <span
              className={`order-pay-dialog__ticket${needInvoice ? ' is-missing' : ' is-ok'}`}
              data-pay-ticket-status={invoiceStatus.status || ''}
              title={`已挂进项发票 ${invoiceCount} 张，合计 ¥${money(invoicedAmount)}`}
            >
              {needInvoice
                ? `进项票缺 ¥${money(uninvoicedAmount)}`
                : `进项票已齐 ¥${money(invoicedAmount)}`}
            </span>
          ) : null}
        </div>

        {result ? (
          /* —— 成功态：把后端算好的三个数摊开给你看，别只丢一句"保存成功" —— */
          <div className="order-pay-dialog__result" data-pay-result>
            <div className="order-pay-dialog__result-head">
              {copy.verb}登记成功：¥{money(result.amount)}
            </div>
            <ul className="order-pay-dialog__result-list">
              <li>
                <span>冲减本单</span>
                <strong>¥{money(result.applied_amount)}</strong>
              </li>
              <li>
                <span>{isSales ? '预收（未挂单）' : '预付（未挂单）'}</span>
                <strong>¥{money(result.prepaid_amount)}</strong>
              </li>
              <li>
                <span>业务日期</span>
                <strong>{result.occurred_at || occurredAt}</strong>
              </li>
              {/* 票属性：这笔钱到底挂了哪张进项票（或"当时没票"） */}
              {!isSales ? (
                <li>
                  <span>进项发票</span>
                  <strong className={result.has_invoice ? '' : 'is-warn'} data-pay-result-invoice>
                    {result.has_invoice
                      ? result.invoice_no || '已挂票'
                      : result.estimate
                        ? '无票 · 已记暂估'
                        : result.no_invoice
                          ? '无票付款（已留痕）'
                          : '未挂票'}
                  </strong>
                </li>
              ) : null}
            </ul>
            <ErpFormActions>
              <button type="button" className="primary-btn" onClick={onClose} data-pay-done>
                完成
              </button>
            </ErpFormActions>
          </div>
        ) : invoiceGate ? (
          /* ================= 无票闸门（强提醒） =================
             居中打断，不给"点一下就过去"的机会：
             三个出口都必须明确点，且**没有**默认焦点在"仍然付款"上。 */
          <div className="order-pay-dialog__gate" role="alertdialog" aria-label="此笔付款暂无发票" data-pay-noinvoice>
            <div className="order-pay-dialog__gate-head">
              <span className="order-pay-dialog__gate-icon" aria-hidden="true">!</span>
              <div>
                <strong>此笔付款暂无发票</strong>
                <p>请及时索取发票，或做暂估处理。</p>
              </div>
            </div>

            <ul className="order-pay-dialog__gate-facts">
              <li>
                <span>本单应付</span>
                <strong>¥{money(net)}</strong>
              </li>
              <li>
                <span>已挂进项票</span>
                <strong>
                  ¥{money(invoicedAmount)}
                  {invoiceCount > 0 ? `（${invoiceCount} 张）` : '（0 张）'}
                </strong>
              </li>
              <li className="is-warn">
                <span>还差票</span>
                <strong>¥{money(uninvoicedAmount)}</strong>
              </li>
            </ul>

            <p className="order-pay-dialog__gate-note">
              「暂估」会把这笔付款记成"已付但未取得发票"，年底汇算时可单独筛出来；
              「无票付款」只留痕，不做暂估。两者都在流水备注上打标，事后可查。
            </p>

            <div className="order-pay-dialog__gate-actions">
              <button
                type="button"
                className="primary-btn"
                onClick={() => {
                  setInvoiceGate(false);
                  onClose?.();
                }}
                data-pay-gate-ask
              >
                先去索取发票
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => doSubmit({ estimate: true })}
                disabled={busy}
                data-pay-gate-estimate
              >
                做暂估处理并付款
              </button>
              <button
                type="button"
                className="secondary-btn order-pay-dialog__gate-plain"
                onClick={() => doSubmit({ no_invoice: true })}
                disabled={busy}
                data-pay-gate-continue
              >
                仍然付款（不记票）
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="order-pay-dialog__form">
            <div className="order-pay-dialog__summary">
              <span>
                {copy.dueLabel} <strong>¥{money(net)}</strong>
              </span>
              <span>
                {copy.doneLabel} <strong>¥{money(done)}</strong>
              </span>
              <span className={left > 0 ? 'is-left' : 'is-clear'}>
                {copy.leftLabel} <strong>¥{money(left)}</strong>
              </span>
            </div>

            <ErpFormGrid columns={2}>
              <ErpFormRow label={copy.amountLabel} required>
                <input
                  type="number"
                  step="any"
                  min="0"
                  inputMode="decimal"
                  value={amount}
                  onChange={(event) => {
                    setAmount(event.target.value);
                    setLocalError('');
                  }}
                  placeholder="0.00"
                  autoFocus
                  data-pay-field="amount"
                />
              </ErpFormRow>
              <ErpFormRow label="业务日期" required>
                <input
                  type="date"
                  value={occurredAt}
                  onChange={(event) => setOccurredAt(event.target.value)}
                  data-pay-field="date"
                />
              </ErpFormRow>
              <ErpFormRow label={`${copy.verb}方式`}>
                <select
                  value={method}
                  onChange={(event) => setMethod(event.target.value)}
                  data-pay-field="method"
                >
                  {METHODS.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </ErpFormRow>
              <ErpFormRow label="备注" span={2}>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="如：转账流水号、票据号，可留空"
                  rows="2"
                  maxLength={120}
                  data-pay-field="note"
                />
              </ErpFormRow>
            </ErpFormGrid>

            {overflow > 0 ? (
              <p className="order-pay-dialog__warn" data-pay-overflow>
                超出待{copy.verb === '收款' ? '收' : '付'} ¥{money(left)} 的部分（¥{money(overflow)}
                ）会记为{isSales ? '预收' : '预付'}，不挂在本单上。
              </p>
            ) : null}

            {!isSales && needInvoice ? (
              /* 提前示警：让用户在点之前就知道"这单没票，点下去会被拦一下" */
              <p className="order-pay-dialog__warn" data-pay-nowarn-hint>
                本单还有 ¥{money(uninvoicedAmount)} 未取得进项发票。点「{copy.submit}」会先让你选择
                索取发票 / 做暂估 / 无票付款。
              </p>
            ) : null}

            {message ? (
              <p className="order-pay-dialog__error" role="alert" data-pay-error>
                {message}
              </p>
            ) : null}

            <p className="order-pay-dialog__hint">{copy.hint}</p>

            <ErpFormActions>
              <button type="button" className="secondary-btn" onClick={onClose} disabled={busy}>
                取消
              </button>
              <button
                type="submit"
                className="primary-btn"
                disabled={busy || !valid || (!isSales && invoiceLoading)}
                data-pay-submit
              >
                {busy ? '提交中…' : !isSales && invoiceLoading ? '核对票据中…' : copy.submit}
              </button>
            </ErpFormActions>
          </form>
        )}
      </div>
    </div>
  );
}
