/**
 * ErpMoreMenu —— 「⋯ 更多」下拉菜单（2026-10-26，增强对账单 UI 重构第一批）
 *
 * 为什么要有它：
 *   单据页顶部的收尾动作（打印 PDF / 导出 Excel / 导出 Word）频率远低于「保存」，
 *   但importance 很高。以前六个按钮平铺成一行，主按钮（保存）被淹没在灰按钮里，
 *   用户每次都要"读一遍"才知道该点哪个。收进 ⋯ 以后一屏只剩一个主视觉焦点。
 *
 * 与既有实现的关系：
 *   · **不复用** `.modal-*`：那是全站 14 处弹窗共用的，改一处会连带崩别处；
 *   · 也**不复用** `ErpSearchSelect` 的下拉：那个是"搜索 + 键盘导航 + 分面"的
 *     重组件，给三个动作套上它属于杀鸡用牛刀，而且它的选中态语义完全不同。
 *   这里另起一套 `.erp-more*`，只做"点开 → 选一项 → 关闭"。
 *
 * 四条踩过坑的约束：
 *   ① **点外面关闭用 pointerdown 捕获阶段**：用 click 会晚一拍 —— 在别的按钮上按下，
 *      菜单先被那次 click 抢走焦点，菜单自己却还开着，看起来像"点不动"。
 *   ② **Esc 用捕获阶段 + stopPropagation**：页面里可能还套着抽屉/弹窗，
 *      冒泡阶段会被外层先收到，关掉的是外层而不是菜单。
 *   ③ **选中即关闭**，且先关再执行 —— 动作里如果弹了确认框，菜单不能浮在确认框上面。
 *   ④ z-index 60：高于表格吸顶表头（2/3）与列宽抓手，低于 `.modal-backdrop`（100），
 *      保证"导出前弹确认"这类弹窗永远在菜单之上。
 *
 * 2026-10-26 封版前补两条（用户报"销售订单行末 ⋯ 完全点不动"）：
 *   ⑤ **面板必须 portal 到 document.body**。原先面板是触发器（在 `<td>` 里）的
 *      absolute 子元素，于是同时吃了两道刀：
 *        · 操作列是 `position: sticky; z-index: 1`（自己的层叠上下文），
 *          面板的 z-index:60 只在这个上下文里有效 —— 让位给下面几行的单元格；
 *        · `.erp-table-wrap` 是 `overflow-x:auto`（按规范另一轴也算 auto）、
 *          外层 `.erp-card` 还是 `overflow:hidden`，行末那一格的菜单往下展开
 *          直接被裁掉。
 *      实测（CDP 探针）：点完 `is-open` 已置真，但面板中心 `elementFromPoint`
 *      命中的是 `TD` / `.erp-table-wrap` —— 菜单确实渲染了，用户在屏幕上看不到。
 *      改成 body 级 `position: fixed` 后既不受层叠上下文影响，也不会被裁。
 *   ⑥ **触发器 click 不冒泡**：列表以后要做"点行开详情"时，这一下会连带打开详情，
 *      用户只会说"点 ⋯ 没用，反而跳走了"。
 *
 * 用法：
 *   <ErpMoreMenu items={[
 *     { key: 'print', label: '打印 PDF', hint: 'A4 横版', onSelect: printPdf },
 *     { key: 'excel', label: '导出 Excel', onSelect: exportExcel, disabled: busy },
 *   ]} />
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import './erp-more-menu.css';

export default function ErpMoreMenu({
  /** 触发器上的文字；不传则只显示 ⋯ */
  label = '',
  /** [{ key, label, hint?, disabled?, danger?, onSelect, attrs? }] */
  items = [],
  align = 'right',
  disabled = false,
  title = '更多操作',
  /** 数据钩子：`[data-erp-more="<testId>"]`，验收脚本按它定位 */
  testId,
}) {
  const [open, setOpen] = useState(false);
  /** 面板的视口坐标。ready=false 时面板先藏在屏幕外，量完尺寸再摆位（避免闪一下） */
  const [pos, setPos] = useState({ top: -9999, left: -9999, ready: false });
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const panelRef = useRef(null);

  /* 摆位：默认贴触发器下方 6px；下方放不下就翻到上方；左右夹在视口内。
     用 viewport 坐标（position: fixed），因为面板挂在 document.body 上 —— 见下方 ⑤。 */
  const place = useCallback(() => {
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!trigger || !panel) return;

    const t = trigger.getBoundingClientRect();
    const p = panel.getBoundingClientRect();
    const gap = 6;
    const margin = 8;

    let left = align === 'right' ? t.right - p.width : t.left;
    left = Math.min(Math.max(margin, left), Math.round(window.innerWidth - p.width - margin));

    let top = t.bottom + gap;
    if (top + p.height > window.innerHeight - margin) {
      const above = t.top - gap - p.height;
      top = above >= margin ? above : Math.max(margin, window.innerHeight - p.height - margin);
    }

    setPos({ top, left, ready: true });
  }, [align]);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  // ① 点外面关闭（捕获阶段）/ ② Esc 关闭（捕获阶段，先于页面其它监听）
  // ④ 滚动 / 缩放就关：面板是 fixed 的，表格一滚它就"脱层"，跟着算反而更晃眼。
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      const inTrigger = rootRef.current && rootRef.current.contains(event.target);
      const inPanel = panelRef.current && panelRef.current.contains(event.target);
      if (!inTrigger && !inPanel) setOpen(false);
    };
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      setOpen(false);
    };
    const onReflow = () => setOpen(false);
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('resize', onReflow);
    window.addEventListener('scroll', onReflow, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('resize', onReflow);
      window.removeEventListener('scroll', onReflow, true);
    };
  }, [open]);

  return (
    <div className={`erp-more erp-more--${align}`} ref={rootRef} data-erp-more={testId || 'default'}>
      <button
        type="button"
        className={`erp-more__trigger${open ? ' is-open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={title}
        title={title}
        disabled={disabled}
        data-erp-more-trigger
        ref={triggerRef}
        /* ⑥ 不冒泡：菜单多半长在"点行打开详情"的表格里，不拦这一下，点 ⋯ 会连带把
              行详情也打开 —— 用户看到的是"菜单没出来，倒是跳详情了"。 */
        onClick={(event) => {
          event.stopPropagation();
          setOpen((prev) => !prev);
        }}
      >
        <span className="erp-more__dots" aria-hidden="true">
          ⋯
        </span>
        {label ? <span className="erp-more__label">{label}</span> : null}
      </button>

      {open
        ? createPortal(
            <div
              className="erp-more__panel"
              role="menu"
              aria-label={title}
              data-erp-more-panel={testId || 'default'}
              ref={panelRef}
              style={{ top: pos.top, left: pos.left }}
              onClick={(event) => event.stopPropagation()}
            >
              {items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="menuitem"
                  className={`erp-more__item${item.danger ? ' is-danger' : ''}`}
                  data-more-item={item.key}
                  disabled={item.disabled}
                  onClick={() => {
                    setOpen(false); // ③ 先关再执行
                    item.onSelect?.();
                  }}
                  {...(item.attrs || {})}
                >
                  <span className="erp-more__item-label">{item.label}</span>
                  {item.hint ? <span className="erp-more__item-hint">{item.hint}</span> : null}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
