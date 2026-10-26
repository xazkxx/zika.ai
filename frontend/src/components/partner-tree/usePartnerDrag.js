/**
 * usePartnerDrag —— 分类树唯一的拖动手势引擎（鼠标 / 触屏 / 触控笔同一套）。
 *
 * 为什么不用 HTML5 原生 Drag and Drop（原来是这套）：
 *   触屏根本不派发 `dragstart`（iOS Safari / Android Chrome 都不），手机上不是拖不准，
 *   是**一点反应都没有**；而且原生 DnD 没有自动滚动，"树比屏幕高"时拖不到屏幕外的行。
 *   所以整棵树改成 Pointer Events 单一路径 —— 桌面和触屏走同一份代码，
 *   只按 `pointerType` 切换两件事：激活方式、三档落点的比例。
 *
 * 三个必须知道的约束（每条都是踩过的）：
 *
 *   ① **"长按拖拽"和"手指能滚树"物理冲突**
 *      `touch-action` 在 pointerdown 那一刻就定了：写成 `none` 手指就滚不动树，
 *      写成 `pan-y` 浏览器一旦判定为滚动就会发 `pointercancel`，拖拽必断。
 *      所以触屏**不给"长按进入拖拽"**，改成：
 *        手柄（`.ptree__grip`，`touch-action:none`）→ 立刻拖；
 *        行体长按 500ms → 打开操作菜单（移入/上移/下移），这条路不吃 `touch-action`。
 *
 *   ② **落点比例按指针类型分开**
 *      鼠标 28/44/28；触屏 20/60/20（手指遮住约 40px，56px 行高里上下各 11px 已是下限）。
 *
 *   ③ **命中测试用"拖动开始时缓存的 rect + 滚动增量"，不是 elementFromPoint**
 *      拖动中行会因自动滚动上下移动，`elementFromPoint` 拿到的还可能是 ghost 自己；
 *      缓存 rect 后只需把探测点按 `scrollTop` 增量平移（O(1)），既准又不会每帧 layout。
 *
 * 落点语义不在这里重算：`resolveDrop()` 仍是唯一真源（防环、防自落都在里面）。
 * 这里只负责"手在哪、落到谁、要不要滚"。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { dropZoneFromRatio, resolveDrop } from '../../lib/partnerTree.js';

/** 鼠标从行体起拖：移动超过这个距离才算拖（否则是一次点击） */
const MOUSE_ACTIVATE_PX = 4;
/** 触屏长按多久弹菜单 */
const LONG_PRESS_MS = 500;
/** 长按期间指针抖动超过这个距离就算"想滚屏"，取消长按 */
const LONG_PRESS_TOLERANCE_PX = 8;
/** 距离容器上下边缘多少像素开始自动滚动 */
const EDGE_SCROLL_PX = 48;
/** 自动滚动每帧步长 */
const EDGE_SCROLL_STEP = 8;
/** 触屏 ghost 相对手指的纵向偏移（往上挪，别被手指遮住） */
const TOUCH_GHOST_OFFSET = -46;

/** 两套落点比例：鼠标精度高，排序区给足；触屏一切为了防误触 */
export const ZONES = {
  mouse: { before: 0.28, after: 0.28 },
  touch: { before: 0.2, after: 0.2 },
};

/** 从树体往上找真正在滚的那个祖先（没有就返回 null，自动滚动自动失效） */
function findScroller(element) {
  let node = element;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1) return node;
    node = node.parentElement;
  }
  return null;
}

export function usePartnerDrag({
  index,
  bodyRef,
  ghostRef,
  onMove,
  onBegin,
  onFinish,
  onLongPress,
  longPressMs = LONG_PRESS_MS,
}) {
  const [dragId, setDragId] = useState(null);
  const [preview, setPreview] = useState(null); // { kind, targetId, move }
  const [rootOver, setRootOver] = useState(false);

  // 高频变化的东西一律放 ref：60fps 改 state 会让整棵树每帧重渲染
  const indexRef = useRef(index);
  indexRef.current = index;
  const stateRef = useRef(null);
  const previewRef = useRef(null);
  const rootOverRef = useRef(false);
  rootOverRef.current = rootOver; // 松手时要读到"最新"的高亮状态，不能靠闭包
  const ghostPos = useRef({ x: 0, y: 0 });
  const suppressUntil = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** 拖动结束后统一收摊：监听、RAF、指针捕获、文本选择 */
  const teardown = useCallback(() => {
    const state = stateRef.current;
    stateRef.current = null;
    if (!state) return;
    window.removeEventListener('pointermove', state.onPointerMove);
    window.removeEventListener('pointerup', state.onPointerUp);
    window.removeEventListener('pointercancel', state.onPointerCancel);
    window.removeEventListener('keydown', state.onKeyDown);
    if (state.longPress) clearTimeout(state.longPress);
    if (state.raf) cancelAnimationFrame(state.raf);
    if (state.scroller) state.scroller.style.removeProperty('scroll-behavior');
    document.body.classList.remove('ptree-dragging');
    if (state.capture && state.captureEl && state.captureEl.releasePointerCapture) {
      try {
        state.captureEl.releasePointerCapture(state.pointerId);
      } catch (_error) {
        /* 指针已经没了，忽略 */
      }
    }
    previewRef.current = null;
    // 拖动期间把点击压到"永久"，正常收摊必须把它恢复成一个短窗口，
    // 否则拖动结束后整个树再也点不动（这个 bug 只有真机点一下才会发现）
    if (suppressUntil.current === Number.MAX_SAFE_INTEGER) suppressUntil.current = Date.now() + 350;
    if (mounted.current) {
      setDragId(null);
      setPreview(null);
      setRootOver(false);
    }
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  const applyPreview = useCallback((next) => {
    const current = previewRef.current;
    const same = current === next
      || (current && next && current.kind === next.kind && current.targetId === next.targetId);
    if (same) return;
    previewRef.current = next;
    if (mounted.current) setPreview(next);
  }, []);

  /** 命中测试：把探测点按"已滚动多少"平移，再和拖动开始时缓存的 rect 比 */
  const hitTest = (state, clientY) => {
    const cache = state.cache;
    if (!cache) return null;
    const delta = state.scroller ? state.scroller.scrollTop - state.scrollTop0 : 0;
    const probe = clientY + delta;
    for (let i = 0; i < cache.rows.length; i += 1) {
      const row = cache.rows[i];
      if (probe >= row.top && probe < row.bottom) return row;
    }
    // 最后一行下面、容器底部以上 = "移到顶级"（不依赖那个提示条自己的 rect）
    if (probe > cache.rowsBottom && probe <= cache.bodyBottom) return { id: 'root', top: cache.rowsBottom, bottom: cache.bodyBottom, height: 40 };
    return null;
  };

  const updatePreview = useCallback((state) => {
    const hit = hitTest(state, state.lastY);
    if (!hit) {
      applyPreview(null);
      if (mounted.current) setRootOver(false);
      return;
    }
    if (hit.id === 'root') {
      applyPreview(null);
      if (mounted.current) setRootOver(true);
      return;
    }
    if (mounted.current) setRootOver(false);
    const zone = dropZoneFromRatio((state.lastY - hit.top + (state.scroller ? state.scroller.scrollTop - state.scrollTop0 : 0)) / (hit.height || 1), state.zones);
    const move = resolveDrop(indexRef.current, state.id, hit.id, zone);
    applyPreview({ kind: move ? zone : 'forbidden', targetId: hit.id, move });
  }, [applyPreview]);

  /** 自动滚动：手指贴在容器上下边缘时持续滚，并把落点重算一遍 */
  const tickScroll = useCallback(() => {
    const state = stateRef.current;
    if (!state) return;
    if (!state.scrollDir || !state.scroller) {
      state.raf = 0;
      return;
    }
    state.scroller.scrollTop += state.scrollDir * EDGE_SCROLL_STEP;
    updatePreview(state);
    state.raf = requestAnimationFrame(tickScroll);
  }, [updatePreview]);

  const activate = useCallback((state) => {
    if (state.active) return;
    state.active = true;
    // ⚠️ 手柄在触屏上是「按下即拖」，但 rowPointerDown 仍然给触屏挂了一条长按定时器。
    //    不在这里掐掉，拖过 500ms 就会突然弹菜单、把正在进行的拖动打断 ——
    //    这个 bug 只有真机"按住手柄慢慢拖"才踩得到（jsdom 里一瞬就松手了）。
    if (state.longPress) {
      clearTimeout(state.longPress);
      state.longPress = null;
    }
    suppressUntil.current = Number.MAX_SAFE_INTEGER; // 拖动期间不要再触发点击
    state.cache = (() => {
      const body = bodyRef.current;
      if (!body) return null;
      const rows = Array.from(body.querySelectorAll('[data-node-id]')).map((el) => {
        const rect = el.getBoundingClientRect();
        return { id: Number(el.dataset.nodeId), top: rect.top, bottom: rect.bottom, height: rect.height };
      });
      const bodyRect = body.getBoundingClientRect();
      return {
        rows,
        rowsBottom: rows.length ? rows[rows.length - 1].bottom : bodyRect.top,
        bodyBottom: bodyRect.bottom,
      };
    })();
    state.scroller = findScroller(bodyRef.current);
    state.scrollTop0 = state.scroller ? state.scroller.scrollTop : 0;

    // 指针捕获：手指移出容器也不会断（jsdom / 老浏览器没有就退化为 window 监听）
    const element = state.captureEl;
    if (element && element.setPointerCapture) {
      try {
        element.setPointerCapture(state.pointerId);
        state.capture = true;
      } catch (_error) {
        state.capture = false;
      }
    }
    document.body.classList.add('ptree-dragging');
    if (mounted.current) setDragId(state.id);
    onBegin && onBegin(state.id);
    updatePreview(state);
  }, [bodyRef, onBegin, updatePreview]);

  const finish = useCallback(async (state, commit) => {
    const dragFrom = state.id;
    const current = previewRef.current;
    const overRoot = rootOverRef.current;
    const move = commit ? (current && current.move ? current.move : overRoot ? { parentId: null, beforeId: null } : null) : null;
    suppressUntil.current = Date.now() + 350;
    teardown();
    if (!move || !onMove) return;
    const ok = await onMove(dragFrom, move);
    onFinish && onFinish(dragFrom, ok);
  }, [onMove, onFinish, teardown]);

  /** 行体按下：鼠标 → 准备拖（4px 激活）；触屏 → 长按弹菜单 */
  const rowPointerDown = useCallback((event, row) => {
    if (event.button !== undefined && event.button !== 0) return;
    if (stateRef.current) return;

    const pointerType = event.pointerType || 'mouse';
    const state = {
      id: row.id,
      name: row.node ? row.node.name : '',
      pointerId: event.pointerId === undefined ? 1 : event.pointerId,
      pointerType,
      zones: pointerType === 'mouse' ? ZONES.mouse : ZONES.touch,
      startX: event.clientX || 0,
      startY: event.clientY || 0,
      lastY: event.clientY || 0,
      active: false,
      captureEl: event.currentTarget,
      fromHandle: false,
      longPress: null,
      raf: 0,
      scrollDir: 0,
    };

    state.onPointerMove = (moveEvent) => {
      if (moveEvent.pointerId !== undefined && state.pointerId !== undefined && moveEvent.pointerId !== state.pointerId) return;
      const dx = (moveEvent.clientX || 0) - state.startX;
      const dy = (moveEvent.clientY || 0) - state.startY;
      state.lastY = moveEvent.clientY || 0;

      if (!state.active) {
        // 触屏：手指一移动就说明想滚屏，长按取消
        if (state.longPress && Math.hypot(dx, dy) > LONG_PRESS_TOLERANCE_PX) {
          clearTimeout(state.longPress);
          state.longPress = null;
        }
        if (state.pointerType === 'mouse' && Math.hypot(dx, dy) >= MOUSE_ACTIVATE_PX) {
          activate(state);
        } else {
          return;
        }
      }

      moveEvent.preventDefault();
      if (ghostRef && ghostRef.current) {
        const offset = state.pointerType === 'mouse' ? -8 : TOUCH_GHOST_OFFSET;
        ghostPos.current = { x: moveEvent.clientX || 0, y: state.lastY + offset };
        ghostRef.current.style.transform = `translate3d(${ghostPos.current.x + 12}px, ${ghostPos.current.y}px, 0)`;
      }

      // 自动滚动：只看指针在滚动容器里的相对位置
      if (state.scroller) {
        const rect = state.scroller.getBoundingClientRect();
        let dir = 0;
        if (state.lastY < rect.top + EDGE_SCROLL_PX) dir = -1;
        else if (state.lastY > rect.bottom - EDGE_SCROLL_PX) dir = 1;
        state.scrollDir = dir;
        if (dir && !state.raf) state.raf = requestAnimationFrame(tickScroll);
      }

      updatePreview(state);
    };

    state.onPointerUp = () => {
      if (state.longPress) {
        clearTimeout(state.longPress);
        state.longPress = null;
      }
      if (!state.active) {
        teardown();
        return;
      }
      finish(state, true);
    };

    state.onPointerCancel = () => {
      // 来电 / 系统手势 / 浏览器抢走滚动：干净取消，绝不"半路提交"
      if (state.active) teardown();
      else teardown();
    };

    state.onKeyDown = (keyEvent) => {
      if (keyEvent.key === 'Escape') {
        keyEvent.preventDefault();
        teardown();
      }
    };

    stateRef.current = state;
    window.addEventListener('pointermove', state.onPointerMove, { passive: false });
    window.addEventListener('pointerup', state.onPointerUp);
    window.addEventListener('pointercancel', state.onPointerCancel);
    window.addEventListener('keydown', state.onKeyDown);

    if (pointerType !== 'mouse') {
      state.longPress = setTimeout(() => {
        state.longPress = null;
        suppressUntil.current = Date.now() + 400;
        const point = { x: state.startX, y: state.startY };
        teardown();
        onLongPress && onLongPress(row, point);
      }, longPressMs);
    }
  }, [activate, finish, ghostRef, onLongPress, teardown, tickScroll, updatePreview]);

  /** 手柄按下：立刻进入拖动态（手柄 `touch-action:none`，触屏也不会被滚屏抢走） */
  const handlePointerDown = useCallback((event, row) => {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    rowPointerDown(event, row);
    const state = stateRef.current;
    if (state && !state.active) activate(state);
  }, [activate, rowPointerDown]);

  const cancel = useCallback(() => teardown(), [teardown]);

  /**
   * 这次点击要不要吞掉？
   *
   * 松手时浏览器会**在起手那一行上补一个 click**，不吞就会出现"拖完顺手把这一行选中了"。
   * 但只吞**紧跟松手的那一次**（一次性）：时间窗只是上限，避免某些浏览器不发补发 click 时
   * 把用户后面一次真实点击也吃掉。
   */
  const isClickSuppressed = useCallback(() => {
    if (Date.now() >= suppressUntil.current) return false;
    suppressUntil.current = 0;
    return true;
  }, []);

  return {
    dragId,
    preview,
    rootOver,
    rowPointerDown,
    handlePointerDown,
    cancel,
    isClickSuppressed,
  };
}
