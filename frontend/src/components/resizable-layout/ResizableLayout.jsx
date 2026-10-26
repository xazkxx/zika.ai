/**
 * ResizableLayout —— 左右两栏可拖拽的布局容器（零依赖，手写 Pointer Events）
 *
 * 为什么自己写：`react-resizable` / `re-resizable` 会带进几十 KB 和一套自己的
 * 事件模型，而我们要的就三件事 —— 拖、夹住最小宽度、记到 localStorage。
 * Pointer Events 一个 setPointerCapture 就解决了"鼠标移出元素后还继续跟手"
 * 这个老问题，不需要往 document 上挂 mousemove/mouseup。
 *
 * 用法（就是 `.management-grid` 的替身，一个字符都不用改子元素）：
 *
 *     <ResizableLayout>
 *       <section className="panel form-panel">…</section>
 *       <section className="panel table-panel">…</section>
 *     </ResizableLayout>
 *
 * 设计上的四个决定：
 *
 * ① **只有恰好 2 个子元素才可拖拽**。`.management-grid` 全站 35 处，其中有
 *    1 个子面板（整行表格）、3 个、5 个的（生产页）。没有"左/右"分界的网格
 *    硬塞一根手柄只会让第三块掉到下一行，比不改更糟。这时组件**原样降级**成
 *    `<div className="management-grid">` —— DOM 与改造前逐字节相同。
 *
 * ② **手柄本身占一列（16px），正好等于原来的 gap**。这样视觉间距没变，
 *    但可点区域从"一条线"变成了 16px 宽的整条，不用像素级瞄准。
 *    拖动时只改第一列的宽度变量 `--mgrid-left`，右栏 `minmax(0, 1fr)` 自动吃掉剩余。
 *
 * ③ **宽度只在拖动后才是像素值**。没拖过时用 CSS 的默认比例
 *    `calc((100% - 16px) * 0.4)`（= 改造前 `1fr 1.5fr` 的实际比例），
 *    所以首次进入页面的宽度与改造前一模一样，不会"变宽/变窄"。
 *
 * ④ **持久化默认全局共用一个 key**。全站的列表页长得差不多，用户拖一次就该
 *    处处生效；要按页区分就传 `storageKey="purchase"` 之类的值。
 */

import { Children, useCallback, useEffect, useRef, useState } from 'react';
import './resizableLayout.css';

const DEFAULT_STORAGE_KEY = 'erp:mgrid:left';
const MIN_LEFT = 300;
const MIN_RIGHT = 400;
/** 手柄列宽，必须与 resizableLayout.css 里 `.mgrid--split` 的第二列一致 */
const HANDLE_W = 16;
/** 方向键每按一次的步长 */
const KEY_STEP = 16;

function readStored(key) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    // 隐私模式 / 存储被禁用时 localStorage 会抛异常 —— 拖拽功能不该因此崩掉
    return null;
  }
}

function writeStored(key, value) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, String(Math.round(value)));
  } catch {
    /* 存不了就算了，本次会话内仍然可拖 */
  }
}

export default function ResizableLayout({
  children,
  storageKey = DEFAULT_STORAGE_KEY,
  minLeft = MIN_LEFT,
  minRight = MIN_RIGHT,
  className = '',
}) {
  // ⚠️ Children.toArray 会自动丢掉 null / undefined / false，
  //    所以 `{cond && <section/>}` 这类条件面板不会把计数算错。
  //
  // ⚠️⚠️ 2026-10-21 白屏事故（商品档案右侧列表消失）：
  //    以前判据是 `items.length === 2`，多一个子元素就整块退化成普通栅格 ——
  //    而 `.management-grid` 的三条轨道是 264px / 16px / 1fr，
  //    于是「左卡片进第一轨、右卡片被挤进 16px 的手柄轨」= 列表当场消失，
  //    而且弹窗关掉后也回不来（轨道是 CSS 定的，不会自己复原）。
  //    现在只认**前两个**当左右栏，其余（弹窗/抽屉这类 fixed 覆盖层）
  //    原样挂到栅格外面 —— 页面上多挂一个弹窗不再能影响分栏。
  const items = Children.toArray(children);
  const panes = items.slice(0, 2);
  const extras = items.slice(2);
  const resizable = panes.length === 2;

  const rootRef = useRef(null);
  const dragRef = useRef(null);
  const [leftWidth, setLeftWidth] = useState(() => {
    const stored = readStored(storageKey);
    if (stored === null) return null;
    // ⚠️ 读出来**当场夹下限**（2026-10-18 用户实测）：这个 key 全站共用一个
    //   （见文件头 ④），用户可能在档案页把左栏拖到 300px，回到单据页时
    //   明细表需要 600px+ —— 直接沿用 300 的结果就是「表格被压成一条 +
    //   底部冒出横向滚动条 + 商品搜索框只剩半截」。
    //   这里不能只靠 clamp()：它算上限要用容器实际宽度，首帧还量不到。
    return Math.max(minLeft, stored);
  });
  const [dragging, setDragging] = useState(false);

  const clamp = useCallback(
    (next) => {
      const el = rootRef.current;
      const total = el ? el.getBoundingClientRect().width : 0;
      // 容器还没量到（首帧 / display:none）时只夹左侧下限，交给 CSS 兜着
      if (!total) return Math.max(minLeft, next);
      const max = Math.max(minLeft, total - HANDLE_W - minRight);
      // 容器本身就装不下 minLeft + 手柄 + minRight 时，**下限优先**：
      // 宁可让右栏被压（它内部是横滚表格），也不能把左栏的明细表压废。
      if (max <= minLeft) return minLeft;
      return Math.min(Math.max(next, minLeft), max);
    },
    [minLeft, minRight],
  );

  const handlePointerDown = (event) => {
    // 只响应主键（触屏 pointerType 为 touch 时 button 是 0）
    if (event.button !== 0) return;
    const el = rootRef.current;
    if (!el) return;

    // 起点宽度优先取「实际渲染宽度」：没拖过时 leftWidth 是 null，
    // 此时第一列的宽度由 CSS 的比例算出，必须现量一次才知道是多少。
    const first = el.firstElementChild;
    const startWidth = leftWidth
      ?? (first ? first.getBoundingClientRect().width : el.getBoundingClientRect().width * 0.4);

    dragRef.current = { startX: event.clientX, startWidth };
    // 指针捕获：鼠标拖到手柄外面（甚至窗口外）也能继续收到 move/up
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);

    // ⚠️ 这里【绝对不能】写 event.preventDefault()，2026-10-17 踩过：
    //   pointerdown 被 cancel 后，浏览器会连带压掉后续的 mousedown / click 序列，
    //   于是 onDoubleClick 永远收不到（实测 dblclick 计数恒为 0，双击恢复是死的），
    //   div[tabindex] 也拿不到焦点，方向键微调跟着一起失效。
    //   防选中文字改由 body.user-select 承担（见下面的 effect），不靠 preventDefault。
  };

  const handlePointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    setLeftWidth(clamp(drag.startWidth + (event.clientX - drag.startX)));
  };

  const handlePointerUp = (event) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setDragging(false);
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      /* 某些浏览器在指针已释放时会抛，忽略 */
    }
    // 落库只在松手时做一次：拖动过程中每帧写 localStorage 是纯浪费
    setLeftWidth((current) => {
      writeStored(storageKey, current);
      return current;
    });
  };

  /** 双击手柄 = 恢复默认比例（顺便清掉本地记录） */
  const handleReset = () => {
    writeStored(storageKey, null);
    setLeftWidth(null);
  };

  const handleKeyDown = (event) => {
    const el = rootRef.current;
    const first = el ? el.firstElementChild : null;
    const current = leftWidth ?? (first ? first.getBoundingClientRect().width : 0);
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      const next = clamp(current + (event.key === 'ArrowRight' ? KEY_STEP : -KEY_STEP));
      setLeftWidth(next);
      writeStored(storageKey, next);
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      handleReset();
    }
  };

  // 拖动期间：整页换成 col-resize 光标，并禁掉文字选中（否则会顺手选一大片）
  useEffect(() => {
    if (!dragging) return undefined;
    const { body } = document;
    const prevCursor = body.style.cursor;
    const prevSelect = body.style.userSelect;
    body.style.cursor = 'col-resize';
    body.style.userSelect = 'none';
    return () => {
      body.style.cursor = prevCursor;
      body.style.userSelect = prevSelect;
    };
  }, [dragging]);

  // 挂载后 + 窗口变化时，把已存的宽度重新夹一遍：
  //   · 挂载这一遍必须有 —— 只监听 resize 的话，进页面那一刻不会夹，
  //     存了 900 的用户在 1280 屏上会看到右栏直接消失；
  //   · 夹的是**已存值**（null 表示用 CSS 默认比例，不动）。
  useEffect(() => {
    const apply = () => {
      setLeftWidth((current) => (current === null ? current : clamp(current)));
    };
    apply();
    window.addEventListener('resize', apply);
    return () => window.removeEventListener('resize', apply);
  }, [clamp]);

  if (!resizable) {
    return <div className={`management-grid${className ? ` ${className}` : ''}`}>{children}</div>;
  }

  return (
    <>
      <div
        ref={rootRef}
        className={`management-grid mgrid--split${dragging ? ' is-dragging' : ''}${className ? ` ${className}` : ''}`}
        style={leftWidth === null ? undefined : { '--mgrid-left': `${leftWidth}px` }}
      >
        {panes[0]}
        <div
          className="mgrid-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="拖动调整左右宽度（双击恢复默认）"
          aria-valuemin={minLeft}
          aria-valuenow={leftWidth === null ? undefined : Math.round(leftWidth)}
          tabIndex={0}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onDoubleClick={handleReset}
          onKeyDown={handleKeyDown}
        >
          <span className="mgrid-handle-line" aria-hidden="true" />
        </div>
        {panes[1]}
      </div>
      {/* 第三个及以后的子元素（弹窗、抽屉）不进栅格 */}
      {extras}
    </>
  );
}
