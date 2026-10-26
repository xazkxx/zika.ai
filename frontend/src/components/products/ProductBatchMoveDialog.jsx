/**
 * ProductBatchMoveDialog —— 商品「批量移动到分类」小窗（v76 新增）
 *
 * 用法：<ProductBatchMoveDialog open={...} ids={[...]} onClose={...} onMoved={...} ctx={ctx} />
 *
 * 职责边界（与 PartnerModal 同一套约定）：
 *   · 只管"选目标分类 + 调接口"，不持有商品数据；
 *   · 成功/失败提示走 ctx.setNotice（页面顶部横幅），不用 alert；
 *   · 数据形状：products.category 存**类别名称字符串**（不是 id），
 *     所以 ErpTreeSelect 用 getNodeValue=node.name —— 与商品弹窗的「类别」
 *     字段同一约定（见 ProductCategory 模型注释）。
 *
 * ⚠️ Esc 处理：本弹窗自管 Esc（捕获阶段 + stopPropagation），busy 时禁关。
 *    卡片在 .modal-backdrop(z 1000) 内部，天然画在页面之上，无需自抬 z-index。
 */

import { useEffect, useState } from 'react';
import ErpTreeSelect from '../ui/ErpTreeSelect.jsx';
import { parseApiDetail } from '../../lib/apiDetail.js';

/**
 * 批量移动小窗的独占样式。
 * ⚠️ 只写 .batch-move-* 类名，绝不覆盖全局（本项目铁律）。
 * 红字提示用「深红字 + 浅红底」而不是纯红字：和表单里 .form-error 的观感一致，
 * 用户一眼知道"这是没填完的原因，不是后端报错"。
 */
const STYLE_TEXT = `
.batch-move-hint {
  margin: 8px 0 0;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  color: #b42318;
  background: #fef3f2;
  border: 1px solid #fecdc9;
}
.batch-move-cleared {
  margin: 8px 0 0;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  color: #b54708;
  background: #fffaeb;
  border: 1px solid #fedf89;
}
`;

/**
 * ⚠️ 错误提示统一走 `lib/apiDetail.js` 的 `parseApiDetail`（v76 白屏事故的修复点）：
 * FastAPI 的 `detail` 有两种形状 —— 我们自己 raise 的 400 是**字符串**，
 * Pydantic 校验失败的 422 是**数组**。旧代码写 `setNotice?.(data.detail || …)`
 * 把数组原样塞进 React 状态 → 渲染时 "Objects are not valid as a React child"
 * → 整棵页面树卸载 → 白屏。那个函数保证永远返回 **非空字符串**，
 * 有 11 条 node --test 单测守着（`src/lib/apiDetail.test.mjs`）。
 */

export default function ProductBatchMoveDialog({ open, ids = [], onClose, onMoved, ctx }) {
  const { productCategories = [], authHeaders, setNotice, API_BASE = '/api/v1' } = ctx || {};
  const [category, setCategory] = useState('');
  // cleared = 用户主动点了「未分类」。语义区分见 submit 里的注释：
  // 「什么都没选」= 不许提交，「明确选了未分类」= 允许提交（清空分类）。
  const [cleared, setCleared] = useState(false);
  const [busy, setBusy] = useState(false);
  // 面板内的红字提示（不发请求就给反馈，比顶部横幅更靠近按钮）
  const [hint, setHint] = useState('');

  // 每次打开都重置上次的选择（残留旧值会让人误以为已经选好了）
  useEffect(() => {
    if (open) {
      setCategory('');
      setCleared(false);
      setBusy(false);
      setHint('');
    }
  }, [open]);

  // 前端拦截：真的"有目标"才行 —— 选了节点，或明确点了「未分类」
  const hasTarget = cleared || Boolean(category);

  // Esc 关闭：捕获阶段 + stopPropagation，防止被下层（页面级/全局）监听抢走
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      if (busy) return;
      event.stopPropagation();
      onClose?.();
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = async (event) => {
    event.preventDefault();
    if (!ids.length) {
      setHint('请先勾选要移动的商品');
      return;
    }
    if (!hasTarget) {
      // 不发请求：没有目标分类的 PATCH 只会把分类清空，纯属事故
      setHint('请先选择一个目标分类（要清空分类请点「未分类」）');
      return;
    }
    setHint('');
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/products/batch-category`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ? authHeaders() : {}) },
        // cleared 时显式传空字符串 —— 后端靠"键存在但为空"来区分「移到未分类」
        // 与「调用方漏传参数」（后者返回 400，见 move_products_batch 注释）
        body: JSON.stringify({ ids, category: cleared ? '' : category }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setNotice?.(parseApiDetail(data && data.detail, `批量移动失败（${response.status}）`));
        return;
      }
      setNotice?.(
        cleared
          ? `已把 ${data.moved ?? ids.length} 个商品移到「未分类」`
          : `已把 ${data.moved ?? ids.length} 个商品移到「${category}」`,
      );
      onMoved?.();
      onClose?.();
    } catch (err) {
      // 网络层异常（断网 / 后端重启）：err.message 是字符串，安全
      setNotice?.(`批量移动失败：${err && err.message ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose?.()} data-batch-move-backdrop>
      {/* z-index 压过普通弹窗：这个小窗可能从商品列表的确认层之上打开 */}
      <div
        className="modal-card"
        style={{ width: 420, maxWidth: '92vw' }}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="批量移动商品到分类"
        data-batch-move-dialog
      >
        <div className="modal-header">
          <h3>批量移动 {ids.length} 个商品</h3>
          <button type="button" className="close-btn" onClick={() => !busy && onClose?.()} aria-label="关闭">
            ×
          </button>
        </div>
        <form onSubmit={submit}>
          <style>{STYLE_TEXT}</style>
          <div style={{ padding: '4px 0 12px' }}>
            <p style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--text-muted,#64748b)' }}>
              从右侧类别树选一个目标分类，选中的商品会全部移过去。
              商品分类存的是类别名，历史自定义类别不受影响。
            </p>
            <ErpTreeSelect
              nodes={productCategories}
              value={cleared ? '' : category}
              onChange={(next) => {
                const text = String(next ?? '');
                // 空值 = 用户在面板里点了「未分类（清空…）」→ 记成"明确清空"；
                // 其余情况是选了某个末级分类 → 清掉 cleared 标记。
                if (text) {
                  setCategory(text);
                  setCleared(false);
                } else {
                  setCategory('');
                  setCleared(true);
                }
                setHint('');
              }}
              placeholder="选择目标分类"
              emptyText="没有匹配的类别"
              clearLabel="未分类（清空这些商品的类别）"
              getNodeValue={(node) => String(node.name ?? '')}
              getNodeLabel={(node) => String(node.name ?? '')}
              testId="product-batch-move"
            />
            {cleared ? (
              <p className="batch-move-cleared" data-batch-move-cleared>
                已选择「未分类」：这 {ids.length} 个商品的类别会被清空。
              </p>
            ) : null}
            {hint ? (
              <p className="batch-move-hint" role="alert" data-batch-move-hint>
                {hint}
              </p>
            ) : null}
            {!hasTarget && !hint ? (
              <p className="batch-move-hint" data-batch-move-tip>
                还没选目标分类，「移动」按钮暂时不可点。
              </p>
            ) : null}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingBottom: 4 }}>
            <button type="button" className="secondary-btn" onClick={() => !busy && onClose?.()} disabled={busy}>
              取消
            </button>
            <button
              type="submit"
              className="primary-btn"
              disabled={busy || !ids.length || !hasTarget}
              data-batch-move-submit
            >
              {busy ? '移动中…' : `移动 ${ids.length} 个商品`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
