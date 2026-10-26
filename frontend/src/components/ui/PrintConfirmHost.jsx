/**
 * PrintConfirmHost —— 打印/危险动作二次确认的宿主弹窗（2026-10-18 建，2026-10-20 扩展）
 *
 * 挂在 App 的弹窗区一次即可，所有页面通过 `lib/printConfirm.js` 的
 * `confirmPrint()` / `confirmDanger()` 调用它 —— 入口太多
 * （订单/入库/出库/合同/发票/对账单/打印中心/反审核/红冲…），逐个页面加确认必然漏，
 * 所以在**唯一收敛点**拦一次。
 *
 * 2026-10-20 扩展：`danger: true` 时变成"红冲确认"——
 *   · 标题/正文/按钮文案由调用方传，按钮走红样式；
 *   · `requireReason` 时多一个原因输入框，空着不让确认（冲账必须留痕）；
 *   · 结算值从 boolean 改成 `{ok, reason}`，旧调用方（confirmPrint）只取 boolean，
 *     由 lib/printConfirm.js 统一归一，互不影响。
 *
 * 三个细节：
 *  ① 连续两次点击（用户手快）：新请求会把旧请求按「取消」结算，
 *     否则旧 Promise 永远悬着 —— 表象是"点了两次，只弹了一个框"。
 *  ② 焦点落在「确认」上：这条路径就是为了防误触，ESC / 点遮罩都能取消，不会把人卡住。
 *  ③ 按钮文案必须说清在确认什么（「确认打印」/「确认红冲」），不用「确定」。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { registerPrintConfirm } from '../../lib/printConfirm.js';
import './print-confirm.css';

export default function PrintConfirmHost() {
  const [request, setRequest] = useState(null);
  const [reason, setReason] = useState('');
  /** 上一个还没结算的请求：新请求进来时把它按"取消"结算掉（见文件头 ①） */
  const pendingRef = useRef(null);
  const okRef = useRef(null);

  useEffect(
    () =>
      registerPrintConfirm(
        (options) =>
          new Promise((resolve) => {
            const prev = pendingRef.current;
            if (prev) prev.resolve(prev.danger ? { ok: false, reason: '' } : false);
            pendingRef.current = { resolve, danger: Boolean(options?.danger) };
            setReason('');
            setRequest({ ...options, resolve });
          }),
      ),
    [],
  );

  const settle = useCallback((ok) => {
    const current = pendingRef.current;
    pendingRef.current = null;
    setRequest(null);
    if (!current) return;
    if (current.danger) current.resolve({ ok, reason: ok ? reason : '' });
    else current.resolve(ok);
  }, [reason]);

  // ESC = 取消（确认框不拦截键盘用户，也不该让 ESC 等价于"确认"）
  useEffect(() => {
    if (!request) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') settle(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [request, settle]);

  // 打开即把焦点放到确认按钮：键盘用户回车就能继续，鼠标用户也不会点到遮罩上
  useEffect(() => {
    if (request && okRef.current) okRef.current.focus();
  }, [request]);

  if (!request) return null;

  const danger = Boolean(request.danger);
  const needReason = Boolean(request.requireReason);
  const blockedByReason = needReason && !reason.trim();

  return (
    <div className="modal-backdrop print-confirm__backdrop" onClick={() => settle(false)} data-print-confirm-backdrop>
      <div
        className={`modal-card print-confirm${danger ? ' print-confirm--danger' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={danger ? '确认红冲' : '确认打印'}
        data-print-confirm
        data-print-confirm-danger={danger ? '1' : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{request.title || (danger ? '确认执行这个操作？' : '确认打印此单据？')}</h3>
          <button type="button" className="close-btn" onClick={() => settle(false)} aria-label="关闭">
            ×
          </button>
        </div>

        {request.name ? (
          <p className="print-confirm__name" data-print-confirm-name>
            {request.name}
          </p>
        ) : null}

        <p className="print-confirm__hint" data-print-confirm-hint>
          {request.hint ||
            (danger
              ? '这个动作会改动库存与应收的记录，不能撤销。'
              : '确认后会生成 PDF 并开始下载。单据内容如需调整，请先关闭本框回去修改。')}
        </p>

        {needReason ? (
          <label className="print-confirm__reason" data-print-confirm-reason-wrap>
            <span>{request.reasonLabel || '作废原因（必填，会记录在单据备注里）'}</span>
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={request.reasonPlaceholder || '例如：客户取消退货'}
              data-print-confirm-reason
            />
          </label>
        ) : null}

        <div className="modal-actions">
          <button type="button" className="secondary-btn" onClick={() => settle(false)} data-print-confirm-cancel>
            取消
          </button>
          <button
            type="button"
            className={danger ? 'danger-btn' : 'primary-btn'}
            ref={okRef}
            disabled={blockedByReason}
            title={blockedByReason ? '请先填写原因' : undefined}
            onClick={() => settle(true)}
            data-print-confirm-ok
          >
            {request.confirmLabel || (danger ? '确认执行' : '确认打印')}
          </button>
        </div>
      </div>
    </div>
  );
}
