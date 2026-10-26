/**
 * ErpDrawer —— 通用的「右侧抽屉」容器（2026-10-20，第三阶段 UI 重构）
 *
 * 为什么要有它：
 *   生产单 / BOM / 项目台账这类页面的新增表单原先**内联在列表左边**，一屏被表单吃掉
 *   半幅，用户看不到自己刚录的数据。改成「右上角 + 新增 → 右侧滑出抽屉」以后，
 *   列表始终是主体，录完即关，视线不跳。
 *
 * 与既有实现的关系：
 *   财务流水详情抽屉（components/finance/FinanceFlowDrawer.jsx）是"只读详情"，
 *   类名 `flow-drawer__*` 与它的语义（两列字段快照）绑得很死，不能直接复用。
 *   这里另起一套 `erp-drawer__*`，宽度可调（窄 380 / 标准 520 / 宽 760），
 *   内部放表单，所以 body 要能滚动、footer 要能固定。
 *
 * 六条设计约束（都是踩过坑的）：
 *   ① **Esc 用捕获阶段 + stopPropagation**：表单里可能还套着别的弹窗（比如快速建档案），
 *      冒泡阶段会被外层抢走，关掉的是外层而不是抽屉。
 *   ② **busy 时禁止关闭**：提交中关掉会让人误以为没提交（实际后台已经写库了）。
 *   ③ **点遮罩关闭、点内容不关闭**：onClick 在 aside 上 stopPropagation。
 *   ④ **不覆写 .modal-***：那是全站 14 处弹窗共用的，改一处会连带崩别处。
 *   ⑤ **z-index 129**：必须高于 .modal-backdrop（100），低于打印确认（150）。
 *   ⑥ **挂载位置**：如果父页面用了 `ResizableLayout`，抽屉要和它**同级**、
 *      用 `<>…</>` 包起来 —— ResizableLayout 只认恰好 2 个子元素，塞第三个进去
 *      拖拽分割条会整块失效。
 *
 * 用法：
 *   <ErpDrawer open={modalOpen} title="新增生产单" onClose={() => setModalOpen(false)}
 *              footer={<><button …>保存</button></>}>
 *     <form …>…</form>
 *   </ErpDrawer>
 */

import { useEffect } from 'react';

import './erp-drawer.css';

export default function ErpDrawer({
  open,
  title,
  subtitle,
  size = 'md',
  busy = false,
  onClose,
  footer,
  children,
  testId,
}) {
  // ① Esc 关闭 —— 捕获阶段拦截，避免被内层/外层弹窗抢走
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      if (busy) return; // ② 提交中不许关
      event.stopPropagation();
      onClose?.();
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open, busy, onClose]);

  if (!open) return null;

  return (
    <div
      className="erp-drawer__backdrop"
      onClick={() => {
        if (!busy) onClose?.();
      }}
      data-erp-drawer-backdrop
    >
      <aside
        className={`erp-drawer erp-drawer--${size}`}
        role="dialog"
        aria-modal="true"
        aria-label={title || '编辑'}
        data-erp-drawer={testId || 'default'}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="erp-drawer__head">
          <div className="erp-drawer__headline">
            <h3>{title}</h3>
            {subtitle ? <span className="erp-drawer__sub">{subtitle}</span> : null}
          </div>
          <button
            type="button"
            className="erp-drawer__close"
            aria-label="关闭"
            onClick={onClose}
            disabled={busy}
          >
            ×
          </button>
        </header>

        <div className="erp-drawer__body">{children}</div>

        {footer ? <footer className="erp-drawer__foot">{footer}</footer> : null}
      </aside>
    </div>
  );
}
