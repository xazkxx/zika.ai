/**
 * ReverseFlowDialog —— 财务流水「红冲」二次确认弹窗
 *
 * 为什么单独做一个组件（而不是复用打印确认框）：
 *   打印确认只需要「确认/取消」，红冲要展示**冲哪一笔、冲多少、冲完会怎样**，
 *   还要让用户写一句原因。信息密度完全不同，硬套会让两边都别扭。
 *
 * 三条设计约束：
 *   ① **金额与单号必须可见**：红冲是不可撤销的记账动作，用户至少要看得到
 *      "我冲的是哪一笔、多少钱"，不能只弹一句"确定吗"。
 *   ② **原因可选但默认给出提示**：留痕的价值远大于强制填写的摩擦力 ——
 *      默认不填也能提交，但输入框一直在那儿，提醒"写一句为什么"。
 *   ③ **busy 时禁用两个按钮并拦住 ESC**：红冲是一次网络写操作，
 *      点完连点第二下、或者手快按 ESC 关掉，都会让用户不知道到底冲没冲。
 */

import { useEffect, useRef, useState } from 'react';
import './reverse-dialog.css';

const money = (value) => {
  const num = Number(value || 0);
  const text = Math.abs(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `¥${num < 0 ? '-' : ''}${text}`;
};

export default function ReverseFlowDialog({
  open = false,
  flow = null,
  typeLabel = (key) => key || '—',
  docTypeLabel = (key) => key || '—',
  busy = false,
  error = '',
  onCancel,
  onConfirm,
}) {
  const [reason, setReason] = useState('');
  const reasonRef = useRef(null);

  // 每次打开都清空原因 —— 上一笔的原因带到下一笔是最容易出的事故
  useEffect(() => {
    if (!open) return;
    setReason('');
    const timer = setTimeout(() => reasonRef.current?.focus(), 30);
    return () => clearTimeout(timer);
  }, [open, flow?.id]);

  // ESC = 取消，但 busy 时不许关（否则用户不知道红冲到底有没有提交）
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      if (!busy) onCancel?.();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, busy, onCancel]);

  if (!open || !flow) return null;

  const docText = flow.doc_no
    ? flow.doc_no
    : flow.related_order_id
      ? `${docTypeLabel(flow.related_type)} #${flow.related_order_id}`
      : '未关联单据';

  return (
    <div
      className="reverse-flow__backdrop"
      onClick={() => {
        if (!busy) onCancel?.();
      }}
      data-reverse-backdrop
    >
      <div
        className="reverse-flow"
        role="dialog"
        aria-modal="true"
        aria-label="确认红冲"
        data-reverse-dialog
        data-reverse-flow-id={flow.id}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="reverse-flow__head">
          <h3>确认红冲这笔{typeLabel(flow.transaction_type)}？</h3>
          <span className="reverse-flow__no">流水 #{flow.id}</span>
        </div>

        <div className="reverse-flow__summary">
          <div className="reverse-flow__row">
            <span>金额</span>
            <b data-reverse-amount>{money(flow.amount)}</b>
          </div>
          <div className="reverse-flow__row">
            <span>关联单据</span>
            <b data-reverse-doc>{docText}</b>
          </div>
          <div className="reverse-flow__row">
            <span>业务日期</span>
            <b>{flow.occurred_at || '—'}</b>
          </div>
        </div>

        <label className="reverse-flow__field">
          红冲原因（选填）
          <input
            ref={reasonRef}
            type="text"
            value={reason}
            maxLength={80}
            placeholder="例如：金额登记错误 / 客户退款 / 重复登记"
            onChange={(event) => setReason(event.target.value)}
            onKeyDown={(event) => {
              // Enter 直接提交（这个框在表单外，不会被浏览器当成提交）
              if (event.key === 'Enter' && !busy) {
                event.preventDefault();
                onConfirm?.(reason.trim());
              }
            }}
            data-reverse-reason
          />
        </label>

        <p className="reverse-flow__hint">
          红冲会<b>新增一条等额负数流水</b>（原流水标记「已冲销」，两条都留痕，合计归零），
          不会删除原记录；挂在这笔钱上的单据会同步回退已收 / 已付金额。
          <b>一笔收付款只能红冲一次，且红冲本身不可撤销。</b>
        </p>

        {error ? (
          <div className="reverse-flow__error" role="alert" data-reverse-error>
            {error}
          </div>
        ) : null}

        <div className="reverse-flow__actions">
          <button type="button" className="secondary-btn" onClick={onCancel} disabled={busy} data-reverse-cancel>
            取消
          </button>
          <button
            type="button"
            className="danger-btn"
            onClick={() => onConfirm?.(reason.trim())}
            disabled={busy}
            data-reverse-ok
          >
            {busy ? '红冲中…' : '确认红冲'}
          </button>
        </div>
      </div>
    </div>
  );
}
