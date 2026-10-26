/**
 * FinanceFlowDrawer —— 财务流水的只读详情抽屉（2026-10-18，需求 2）
 *
 * 为什么是"抽屉"而不是弹窗：财务流水的详情是**一串字段快照**，用户看的是
 * 「这笔钱是谁的、挂在哪张单上、什么时候登记的」。抽屉从右侧滑出、不遮住列表，
 * 换一条流水时上下文还在；弹窗会把列表盖住，看完一条再关掉才能看下一条。
 *
 * 三条设计约束：
 *  ① **只读**：这里不出现任何输入框。要改流水只能走红冲/补登，不能在详情里"顺手改"，
 *     否则审计链路就断了（`financial_transactions` 是账，不是草稿）。
 *  ② **自己解析名称**：后端存的是 customer_id / supplier_id / bank_account_id，
 *     组件按传进来的字典翻译，不做二次请求 —— 列表页手里已经有这几份数据。
 *  ③ **不 import App.jsx、不读 ctx**：与 PartnerModal / OrderPaymentDialog 同一套约定，
 *     这样它能在任何页面复用，也不会把 App 的依赖图搅进来。
 *
 * 用法：
 *   <FinanceFlowDrawer
 *     open={Boolean(flowDetail)} flow={flowDetail}
 *     customers={customers} suppliers={suppliers} bankAccounts={bankAccounts}
 *     typeLabel={financeTypeLabel} docTypeLabel={(key) => DOC_TYPE_LABEL[key] || key}
 *     onClose={() => setFlowDetail(null)}
 *   />
 */

import { useEffect } from 'react';

import './finance-drawer.css';

const DIRECTION_LABEL = { in: '资金流入', out: '资金流出' };

const money = (value) =>
  `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** 时间戳 → `YYYY-MM-DD HH:mm`（本地时区）。
 *  后端给的是带时区的 ISO 串，直接 slice 会把 UTC 时间当本地时间显示（差 8 小时）。 */
function formatStamp(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function pick(list, id) {
  if (id === null || id === undefined || id === '') return null;
  return (list || []).find((item) => String(item.id) === String(id)) || null;
}

/** 一行「标签 + 值」。空值统一显示 `—`，不留空白格（看起来像没加载出来） */
function Row({ label, value, strong = false, mono = false, wide = false }) {
  const empty = value === null || value === undefined || value === '';
  return (
    <div className={`flow-drawer__row${wide ? ' flow-drawer__row--wide' : ''}`}>
      <span className="flow-drawer__label">{label}</span>
      <span
        className={`flow-drawer__value${strong ? ' flow-drawer__value--strong' : ''}${
          mono ? ' flow-drawer__value--mono' : ''
        }`}
      >
        {empty ? '—' : value}
      </span>
    </div>
  );
}

export default function FinanceFlowDrawer({
  open,
  flow,
  customers = [],
  suppliers = [],
  bankAccounts = [],
  typeLabel = (key) => key || '—',
  docTypeLabel = (key) => key || '—',
  onClose,
}) {
  // ESC 关闭：抽屉不是全屏模态，键盘用户必须能一键退出
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open || !flow) return null;

  const customer = pick(customers, flow.customer_id);
  const supplier = pick(suppliers, flow.supplier_id);
  const account = pick(bankAccounts, flow.bank_account_id);
  const partyName = customer
    ? `客户：${customer.name}${customer.code ? `（${customer.code}）` : ''}`
    : supplier
      ? `供应商：${supplier.name}${supplier.code ? `（${supplier.code}）` : ''}`
      : '';

  // 关联单据号：优先用登记时写下的 doc_no（那是"当时的单号快照"，
  // 单据后来改名/删除都不影响它）；没有就退回"类型 + 内部 id"，至少能追溯。
  const docText = flow.doc_no
    ? flow.doc_no
    : flow.related_order_id
      ? `${docTypeLabel(flow.related_type)} #${flow.related_order_id}`
      : '';

  return (
    <div className="flow-drawer__backdrop" onClick={onClose} data-flow-drawer-backdrop>
      <aside
        className="flow-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="财务流水详情"
        data-flow-drawer
        data-flow-id={flow.id}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flow-drawer__head">
          <div className="flow-drawer__headline">
            <h3>流水详情</h3>
            <span className="flow-drawer__no">#{flow.id}</span>
          </div>
          <button type="button" className="flow-drawer__close" onClick={onClose} aria-label="关闭" data-flow-close>
            ×
          </button>
        </header>

        <div className="flow-drawer__amount">
          <span className="flow-drawer__amount-value" data-flow-amount>
            {money(flow.amount)}
          </span>
          <span className={`flow-drawer__tag flow-drawer__tag--${flow.direction === 'out' ? 'out' : 'in'}`}>
            {typeLabel(flow.transaction_type)}
          </span>
          {flow.direction ? (
            <span className="flow-drawer__direction">{DIRECTION_LABEL[flow.direction] || flow.direction}</span>
          ) : null}
        </div>

        <div className="flow-drawer__body">
          <Row label="类型" value={typeLabel(flow.transaction_type)} strong />
          <Row label="金额" value={`${money(flow.amount)} ${flow.currency || 'CNY'}`} strong />
          <Row label="方向" value={DIRECTION_LABEL[flow.direction] || flow.direction || ''} />
          <Row
            label="冲销状态"
            value={
              flow.reversal_of_id
                ? `红冲（冲销的是 #${flow.reversal_of_id}）`
                : flow.is_reversed
                  ? `已冲销${flow.reversed_flow_id ? `（红字 #${flow.reversed_flow_id}）` : ''}`
                  : '正常'
            }
            strong={Boolean(flow.reversal_of_id || flow.is_reversed)}
          />
          <Row label="关联单据" value={docText} mono wide />
          <Row label="单据类型" value={flow.related_type ? docTypeLabel(flow.related_type) : ''} />
          <Row label="往来单位" value={partyName} wide />
          <Row label="业务日期" value={flow.occurred_at || ''} />
          <Row label="会计期间" value={flow.period || ''} />
          <Row label="登记时间" value={formatStamp(flow.created_at)} wide />
          <Row label="操作人" value={flow.handler || ''} />
          <Row label="资金账户" value={account ? account.name : ''} />
          <Row label="收支类别" value={flow.category || ''} />
          <Row label="备注" value={flow.note || ''} wide />
        </div>

        <footer className="flow-drawer__foot">
          <p className="flow-drawer__note">
            这是一条已入账的资金流水，仅供查看。金额或对象登记错了不要改这里 ——
            收款 / 付款请回到列表点行尾的「红冲」生成一笔反向流水（原记录留痕、合计归零）；
            其它类型请到对应单据上冲销。
          </p>
          <button type="button" className="primary-btn" onClick={onClose} data-flow-drawer-ok>
            知道了
          </button>
        </footer>
      </aside>
    </div>
  );
}
