/**
 * StatusBadges —— 单据列表「多维状态分离」的三个小徽标（2026-10-20 老系统 UX 升级）。
 *
 * 以前列表只有一列「状态」，审核/钱/货三种信息挤在一个词里，用户看不出
 * "这单审核过了没"和"这单收没收到钱"——现在拆成三列彩色徽标：
 *   「审核状态」draft/submitted/completed 的流程位置（黄=待处理，绿=走完）。
 *   「收付款状态」看后端算好的 settled / outstanding_amount（销售）或
 *     total_debt（采购）——**前端不自算**，口径唯一权威在后端
 *     `_apply_settlement_fields`。订单（doc_type=order）没有结算字段 → 不渲染。
 *   「发货状态」销售出库看签收（signed_at），订单看转单（completed）。
 *
 * 样式只用全局现成的 `.status-badge` 色调（ok / muted / warn / danger），
 * 不加新 CSS —— 这些类是全站验证过的对比度，别再造第四套颜色。
 */

/** 审核状态：labels 由调用方传（出库单/订单/采购各有一套文案） */
export function AuditBadge({ row, labels }) {
  const status = row.status || '';
  const tone = status === 'completed' ? 'ok' : status === 'draft' ? 'muted' : 'warn';
  return <span className={`status-badge ${tone}`}>{labels[status] || status || '—'}</span>;
}

/** 收付款状态：settled=true 绿「已结清」；欠款>0 红「欠 ¥x」；没有字段就不渲染 */
export function PayBadge({ row }) {
  if (typeof row.settled === 'boolean') {
    if (row.settled) {
      return <span className="status-badge ok">已结清</span>;
    }
    const owe = Number(row.outstanding_amount || 0);
    return (
      <span className="status-badge danger" title="应收余额（净额 − 已收）">
        {owe > 0 ? `欠 ¥${owe.toFixed(2)}` : '未结清'}
      </span>
    );
  }
  // 采购侧口径：total_debt > 0 = 还有应付没付清
  const debt = Number(row.total_debt || 0);
  if (Number.isFinite(debt) && (debt > 0 || row.paid_amount !== undefined)) {
    return debt > 0 ? (
      <span className="status-badge danger" title="应付余额">
        欠 ¥{debt.toFixed(2)}
      </span>
    ) : (
      <span className="status-badge ok">已付清</span>
    );
  }
  return null;
}

/** 发货/签收状态：sales 出库单看 signed_at；订单看 completed（已转开单） */
export function ShipBadge({ row, kind }) {
  if (kind === 'signed') {
    return row.signed_at ? (
      <span className="status-badge ok">已签收</span>
    ) : (
      <span className="status-badge muted">未签收</span>
    );
  }
  if (kind === 'convert') {
    return row.status === 'completed' ? (
      <span className="status-badge ok">已转单</span>
    ) : (
      <span className="status-badge muted">未转单</span>
    );
  }
  return null;
}
