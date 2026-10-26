/**
 * MenuTreeEditor —— 支持无限层级（默认上限 8）与拖拽排序/归类的树形菜单编辑器
 *
 * 设计要点（每一条都有原因，不是随手写的）
 * ─────────────────────────────────────────────────────────────────────────────
 * 1. **拖拽 + 按钮双通道**。dnd-kit 的拖拽在桌面上很好用，但移动端触摸、以及
 *    只有键盘的场景体验很差。所以每一行同时给出 上移/下移/缩进/取消缩进 四个按钮 ——
 *    它们走的是同一套 planXxx 纯函数，行为完全一致，不存在"拖和按结果不同"。
 *
 * 2. **落点靠"三区分法"**，不做左右拖拽定层级（那种交互在窄面板里很难精确）：
 *      行的上 30% → 插到它前面（同级）
 *      行的下 30% → 插到它后面（同级）
 *      行的中间 40% 且目标是分组 → 变成它的子节点
 *    目标是菜单项时中间区自动降级为"插到后面"（后端禁止菜单项有下级）。
 *
 * 3. **缩进用 inline style 算**：paddingLeft = 20 + depth * 16。
 *    depth 1/2 得到 36/52px，与现有 styles.css 的 .nav-depth-1 / .nav-depth-2 完全一致，
 *    所以对现有两层菜单观感零变化；第 3 层起不再掉回基础 padding，视觉不会乱。
 *
 * 4. **乐观更新 + 失败回滚**。拖放立刻改本地树（手感不能卡），同时发请求；
 *    后端拒绝或网络失败就把树还原并提示原因 —— 绝不留下"界面变了库里没变"的假象。
 *
 * 5. **不改任何路由逻辑**。拖拽只写 parent_id / sort_order，`page_key` 一个字节都不动，
 *    所以 App.jsx 的 selectedTab 切换完全不受影响。组件只做两件事：
 *    高亮 pageKey === selectedTab 的行，以及点击菜单项时回调 onNavigate(pageKey)。
 *
 * 依赖：@dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities（已安装）
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

import {
  auditTree,
  computeDropIntent,
  countNodes,
  flattenVisible,
  isLeaf,
  planDrop,
  planIndent,
  planOutdent,
  planShift,
  refreshDerived,
  rowIndent,
  treeDepth,
} from './menuTreeUtils.js';
import { probeReorderApi, saveMenuOrder } from './menuTreeApi.js';

import './menuTreeEditor.css';

const TONE_CLASS = {
  ok: 'mtree-msg--ok',
  warn: 'mtree-msg--warn',
  error: 'mtree-msg--error',
  info: 'mtree-msg--info',
};

// ─────────────────────────────────────────────────────────────────────────────
// 单行（必须是独立组件：useSortable 是 hook）
// ─────────────────────────────────────────────────────────────────────────────
function TreeRow({
  row,
  isActive,
  dropHint,
  isDraggingId,
  readOnly,
  onToggleCollapse,
  onAction,
  onNavigate,
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: row.id,
    disabled: readOnly,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    paddingLeft: rowIndent(row.depth), // ← 动态缩进：20 + depth*16
  };

  const showsInside = dropHint && dropHint.overId === row.id && dropHint.intent === 'inside';
  const showsBefore = dropHint && dropHint.overId === row.id && dropHint.intent === 'before';
  const showsAfter = dropHint && dropHint.overId === row.id && dropHint.intent === 'after';

  const cls = [
    'mtree-row',
    row.kind === 'group' ? 'is-group' : 'is-menu',
    !row.isEnabled ? 'is-disabled' : '',
    isActive ? 'is-active' : '',
    isDragging ? 'is-dragging' : '',
    isDraggingId === row.id ? 'is-source' : '',
    showsInside ? 'drop-inside' : '',
    showsBefore ? 'drop-before' : '',
    showsAfter ? 'drop-after' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cls}
      data-menu-id={row.id}
      data-depth={row.depth}
      data-testid={`mtree-row-${row.id}`}
    >
      {/* 折叠箭头 / 占位，保证同层不同"有无子节点"的行文字左边界对齐 */}
      {row.hasChildren ? (
        <button
          type="button"
          className={`mtree-caret ${row.collapsed ? 'is-collapsed' : ''}`}
          onClick={() => onToggleCollapse(row.id)}
          aria-expanded={!row.collapsed}
          aria-label={row.collapsed ? `展开 ${row.label}` : `折叠 ${row.label}`}
          title={row.collapsed ? '展开' : '折叠'}
        >
          <span aria-hidden="true" />
        </button>
      ) : (
        <span className="mtree-caret mtree-caret--empty" aria-hidden="true" />
      )}

      {/* 拖拽手柄：只有手柄可拖，避免点按钮时误触发起拖拽 */}
      {!readOnly && (
        <span
          className="mtree-handle"
          {...attributes}
          {...listeners}
          title="拖拽调整位置 / 层级"
          aria-label={`拖拽 ${row.label}`}
        >
          <span aria-hidden="true">⠿</span>
        </span>
      )}

      <span className={`mtree-kind mtree-kind--${row.kind}`}>
        {row.kind === 'group' ? '分组' : '菜单项'}
      </span>

      <span className="mtree-label" title={row.note || row.label}>
        {row.label}
      </span>

      {row.pageKey && (
        <button
          type="button"
          className="mtree-page"
          onClick={() => onNavigate?.(row.pageKey, row.label)}
          title={`打开页面：${row.pageKey}`}
        >
          {row.pageKey}
        </button>
      )}

      {!row.isEnabled && <span className="mtree-badge mtree-badge--off">停用</span>}
      {row.isBuiltin && <span className="mtree-badge mtree-badge--builtin">内置</span>}
      {row.childCount > 0 && <span className="mtree-count">{row.childCount}</span>}

      <span className="mtree-depth" title="层级（决定缩进）">
        L{row.depth}
      </span>

      {!readOnly && (
        <span className="mtree-actions">
          <button type="button" onClick={() => onAction('up', row)} title="上移一位">
            ↑
          </button>
          <button type="button" onClick={() => onAction('down', row)} title="下移一位">
            ↓
          </button>
          <button type="button" onClick={() => onAction('indent', row)} title="缩进一级（成为上一个同级节点的子级）">
            →
          </button>
          <button type="button" onClick={() => onAction('outdent', row)} title="取消缩进一级">
            ←
          </button>
        </span>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────────────────────────────────────
export default function MenuTreeEditor({
  tree: treeProp,
  maxDepth = 8,
  apiBase = '/api/v1',
  authHeaders,
  selectedTab = '',
  readOnly = false,
  onNavigate,
  onSaved,
  onError,
}) {
  const [tree, setTree] = useState(() => refreshDerived(treeProp || []));
  const [collapsed, setCollapsed] = useState([]);
  const [draggingId, setDraggingId] = useState(null);
  const [dropHint, setDropHint] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [apiReady, setApiReady] = useState(null); // null=未探测 true/false

  const pointerYRef = useRef(0);
  const treeRef = useRef(tree);
  treeRef.current = tree;

  // 外部 tree 变化（父组件重新拉取）时同步进来
  useEffect(() => {
    setTree(refreshDerived(treeProp || []));
  }, [treeProp]);

  // 记一份指针 Y 作为最后兜底（dnd-kit 的 rect 拿不到时才用）。
  // 用 capture 阶段挂在 document 上：dnd-kit 自己的 pointermove 处理里可能会
  // stopPropagation，挂 window 的冒泡监听会收不到后段移动。
  useEffect(() => {
    const onMove = (event) => {
      pointerYRef.current = event.clientY;
    };
    document.addEventListener('pointermove', onMove, { passive: true, capture: true });
    return () => document.removeEventListener('pointermove', onMove, { capture: true });
  }, []);

  // 探测后端是否已合并批量重排接口，好在界面上说清楚
  useEffect(() => {
    let alive = true;
    probeReorderApi({ apiBase, authHeaders })
      .then((ok) => alive && setApiReady(ok))
      .catch(() => alive && setApiReady(false));
    return () => {
      alive = false;
    };
  }, [apiBase, authHeaders]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const rows = useMemo(() => flattenVisible(tree, collapsed), [tree, collapsed]);
  const rowById = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const visibleIds = useMemo(() => rows.map((r) => r.id), [rows]);
  const problems = useMemo(() => auditTree(tree, { maxDepth }), [tree, maxDepth]);
  const stats = useMemo(
    () => ({ nodes: countNodes(tree), depth: treeDepth(tree), groups: rows.filter((r) => r.kind === 'group').length }),
    [tree, rows],
  );

  const say = useCallback(
    (tone, text) => {
      setMessage(text ? { tone, text } : null);
      if (tone === 'error' || tone === 'warn') onError?.(text);
    },
    [onError],
  );

  /** 把一次计划落到后端：先乐观更新，失败回滚。 */
  const commit = useCallback(
    async (plan, successText) => {
      if (!plan?.ok) {
        if (plan && !plan.noop) say('warn', plan.reason);
        else if (plan?.noop && plan.reason) say('info', plan.reason);
        return false;
      }
      const before = treeRef.current;
      setTree(plan.tree);
      setMessage(null);

      if (readOnly) {
        onSaved?.(plan.tree);
        return true;
      }

      setSaving(true);
      try {
        const res = await saveMenuOrder({ apiBase, authHeaders, items: plan.items });
        // ⚠️ 只在响应里带回**非空**树时才采纳它。
        //    空数组是 truthy —— 曾经这里写成 `if (res?.tree) setTree(...)`，
        //    于是后端（或 mock）返回 {"tree": []} 时把本地树整个清空，
        //    界面上表现为"保存成功后菜单全没了"。宁可继续用本地已算好的树。
        const serverTree = Array.isArray(res?.tree) && res.tree.length > 0 ? res.tree : null;
        if (serverTree) setTree(refreshDerived(serverTree));
        say('ok', successText || `已保存（${plan.items.length} 个节点的顺序）`);
        onSaved?.(serverTree || plan.tree);
        setApiReady(true);
        return true;
      } catch (err) {
        setTree(before); // ← 回滚，不留"界面变了库里没变"
        const text = err?.message || '保存失败';
        say('error', `${text}（已还原到改动前）`);
        if (/404|还没有/.test(text)) setApiReady(false);
        return false;
      } finally {
        setSaving(false);
      }
    },
    [apiBase, authHeaders, onSaved, readOnly, say],
  );

  const handleAction = useCallback(
    (kind, row) => {
      const base = { activeId: row.id, maxDepth };
      const plan =
        kind === 'up'
          ? planShift(treeRef.current, { ...base, delta: -1 })
          : kind === 'down'
            ? planShift(treeRef.current, { ...base, delta: 1 })
            : kind === 'indent'
              ? planIndent(treeRef.current, base)
              : planOutdent(treeRef.current, base);
      const wording = { up: '上移', down: '下移', indent: '缩进', outdent: '取消缩进' }[kind];
      commit(plan, `「${row.label}」${wording}成功`);
    },
    [commit, maxDepth],
  );

  const handleDragStart = useCallback((event) => {
    setDraggingId(event.active.id);
    setDropHint(null);
  }, []);

  /**
   * 算出"松手时想把节点放到哪"。
   *
   * ⚠️ 坐标系必须一致（踩过）：
   *    dnd-kit 的 over.rect 不是视口坐标，而是**带滚动偏移**的同一套内部坐标。
   *    所以不能用 pointermove 记下的 event.clientY（视口坐标）去跟 over.rect.top 相减 ——
   *    页面一滚动，比值恒为负，永远判成"插到上方"。
   *    改用 dnd-kit 自己给的 active.rect.current.translated（同一坐标系）。
   *
   * ⚠️ 还必须**在 onDragEnd 里重算**（踩过）：
   *    dnd-kit 只在 over 发生变化时才触发 onDragOver。也就是说"最后一段拖动"
   *    往往不会再触发一次 —— 若直接用 dragOver 阶段存下来的意图，
   *    用的是"刚进入这一行时"的位置（通常是上缘），永远落不到 inside。
   */
  const resolveIntent = useCallback(
    (active, over) => {
      const overRow = rowById.get(over?.id);
      const rect = active?.rect?.current;
      const probe = rect?.translated || rect?.initial;
      const probeY = probe ? probe.top + probe.height / 2 : pointerYRef.current;
      return computeDropIntent({
        overRect: over?.rect,
        pointerY: probeY,
        overIsLeaf: overRow ? overRow.kind === 'menu' : false,
      });
    },
    [rowById],
  );

  const handleDragMove = useCallback(
    (event) => {
      const { active, over } = event;
      if (!over || active.id === over.id) {
        setDropHint(null);
        return;
      }
      // 仅用于画落点指示线；真正的落点判定在 onDragEnd 里重算
      setDropHint({ overId: over.id, intent: resolveIntent(active, over) });
    },
    [resolveIntent],
  );

  const handleDragEnd = useCallback(
    async (event) => {
      const { active, over } = event;
      setDraggingId(null);
      setDropHint(null);
      if (!over) return;
      // 落点在松手这一刻重算（onDragOver 只在 over 变化时触发，不能拿来当最终意图）
      const intent = resolveIntent(active, over);
      const plan = planDrop(treeRef.current, {
        activeId: active.id,
        overId: over.id,
        intent,
        maxDepth,
      });
      const label = rowById.get(active.id)?.label || '';
      const wording = { before: '移到上方', after: '移到下方', inside: '移入下级' }[intent];
      await commit(plan, `「${label}」${wording}成功`);
    },
    [commit, maxDepth, resolveIntent, rowById],
  );

  const toggleCollapse = useCallback((id) => {
    setCollapsed((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const expandAll = () => setCollapsed([]);
  const collapseAll = () =>
    setCollapsed(
      (function walk(list, acc) {
        list.forEach((n) => {
          if ((n.children || []).length) {
            acc.push(n.id);
            walk(n.children, acc);
          }
        });
        return acc;
      })(tree, []),
    );

  return (
    <div className="mtree" data-testid="menu-tree-editor">
      <div className="mtree-toolbar">
        <div className="mtree-toolbar__left">
          <strong className="mtree-title">菜单结构</strong>
          <span className="mtree-stat">
            共 {stats.nodes} 项（分组 {stats.groups}）
          </span>
          <span className="mtree-stat">
            最大深度 <b>{stats.depth}</b> 层 / 上限 {maxDepth} 层
          </span>
          {problems.length > 0 && (
            <span className="mtree-stat mtree-stat--bad">{problems.length} 处结构问题</span>
          )}
        </div>
        <div className="mtree-toolbar__right">
          {saving && <span className="mtree-saving">保存中…</span>}
          <button type="button" className="mtree-btn" onClick={expandAll}>
            展开全部
          </button>
          <button type="button" className="mtree-btn" onClick={collapseAll}>
            折叠全部
          </button>
        </div>
      </div>

      {apiReady === false && (
        <div className="mtree-msg mtree-msg--warn" data-testid="mtree-api-missing">
          后端尚未提供 <code>POST /system/menus/reorder</code>，保存会失败。
          请先合并 <code>_menu_tree_refactor/step1_backend/02_menu_reorder.py</code>（见 INTEGRATION.md）。
          <b>拖动本身可以正常预览</b>，只是不会落库。
        </div>
      )}
      {message && (
        <div className={`mtree-msg ${TONE_CLASS[message.tone] || ''}`} data-testid="mtree-message">
          {message.text}
        </div>
      )}
      {problems.length > 0 && (
        <div className="mtree-msg mtree-msg--error" data-testid="mtree-problems">
          <b>结构自检发现问题：</b>
          <ul>
            {problems.slice(0, 5).map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mtree-hint">
        拖动左侧 ⠿ 手柄即可调整；行的上/下缘 = 同级排序，行的中段 = 变成它的下级。
        目标是「菜单项」时中段会自动降级为同级排序（菜单项不能有下级）。
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragMove={handleDragMove}
        onDragEnd={handleDragEnd}
        onDragCancel={() => {
          setDraggingId(null);
          setDropHint(null);
        }}
      >
        <SortableContext items={visibleIds} strategy={verticalListSortingStrategy}>
          <div className="mtree-body">
            {rows.map((row) => (
              <TreeRow
                key={row.id}
                row={row}
                isActive={Boolean(row.pageKey) && row.pageKey === selectedTab}
                dropHint={dropHint}
                isDraggingId={draggingId}
                readOnly={readOnly}
                onToggleCollapse={toggleCollapse}
                onAction={handleAction}
                onNavigate={onNavigate}
              />
            ))}
            {rows.length === 0 && <div className="mtree-empty">没有菜单节点。</div>}
          </div>
        </SortableContext>

        <DragOverlay dropAnimation={null}>
          {draggingId ? (
            <div className="mtree-row mtree-drag-overlay">
              <span className="mtree-label">{rowById.get(draggingId)?.label}</span>
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
