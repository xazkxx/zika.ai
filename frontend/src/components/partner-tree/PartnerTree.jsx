/**
 * PartnerTree —— 客户 / 供应商「真实分类树」（无限极 + 深级拖拽 + 搜索定位）
 *
 * 与 `components/ui/ErpTree.jsx` 的关系（**不要合并**）：
 *   `ErpTree` 是"分组视图树"，节点由调用方现场算出来（`lib/partnerGroup.js`），
 *   两级、只读、拖不动。这棵树背后是 `customer_categories` / `supplier_categories`
 *   物理表，**层级没有上限**、可跨级拖拽、可搜索定位 —— 交互与失败模式完全不同。
 *   硬把两者塞进一个组件，会得到一堆 `if (draggable)` 分支，两个场景都变差。
 *
 * 三个高级特性（对应真实集团架构：集团客户 → 分公司 → 子公司 → 项目 → 子项目 → 班组）
 *
 *   ① 深度缩进与折叠（视觉防崩塌）
 *      每级 14px（`INDENT_PX`），**10 层封顶**（再深不再缩进，靠 L 角标读层级）；
 *      默认只展开 3 层（`defaultExpandDepth`），第 5 层起折叠图标放大加框，
 *      并且**只渲染展开分支** —— DOM 里永远没有"看不见的几百行"。
 *
 *   ② 拖拽级联联动（业务核心）
 *      落点分三档：行上 28% / 下 28% = 插到前后，中间 44% = 变成子级。
 *      换算成后端要的 `{ parentId, beforeId }` 后交给 `onMove`；
 *      **乐观更新**在数据层做（`usePartnerCategories`），成功后页面派生出的
 *      表格「分类」列 / 计数 / 过滤结果会**同一帧**跟着变，不需要额外刷新。
 *      非法落点（拖进自己的后代、拖到自己身上）**一个请求都不发**。
 *
 *   ③ 树内模糊搜索与定位
 *      顶部搜索框，子串匹配（大小写不敏感）；命中项的**所有父级强制展开**，
 *      命中的片段用 `<mark>` 高亮、行本身打 `is-hit`；回车逐个跳、Esc 清空。
 *      搜索**不改用户的折叠状态** —— 清空后树回到原样，不会"一搜就全开了"。
 *
 * 只吃 props，不 import App.jsx、不读 ctx、不自己发请求（数据从 `usePartnerCategories` 来）。
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  DEEP_DEPTH,
  UNCLASSIFIED,
  ancestorsOf,
  buildVisibleRows,
  defaultExpandedIds,
  expandableIds,
  indexTree,
  indentOf,
  matchPartnerLeaves,
  searchNodes,
  isDescendant,
  batchMovePlan,
  normalizeSelection,
  siblingMoveTarget,
} from '../../lib/partnerTree.js';
import { ALL } from '../../lib/treeSelection.js';
import { usePartnerDrag } from './usePartnerDrag.js';
import './partner-tree.css';

/** 拖拽提示条：只在按住拖动时出现，松手就消失 */
const DRAG_TIP = '拖到行中间 = 变成它的子级；拖到上下边缘 = 调顺序；拖到最下面 = 移到顶级';

/** 勾选框在多选态占的横向宽度（16px 方框 + 6px flex gap），给非常规行补缩进用 */
const CHECK_SLOT = 22;

/** 一个分类下最多平铺多少个客户：再多就折成「还有 N 个客户…」。
 *  单个分类有几百条档案时全量渲染会把树拖慢（每个叶子都是可拖元素）。 */
const LEAF_LIMIT = 50;

/** 行内操作图标：手写 SVG，不引图标库（首屏体积 + 能离线跑） */
function IconPlus() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 3.2v9.6M3.2 8h9.6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function IconPencil() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M10.4 2.4l3.2 3.2M2.6 13.4l.8-3.4 7.4-7.4 2.6 2.6-7.4 7.4-3.4.8z"
        stroke="currentColor"
        strokeWidth="1.35"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M2.8 4.3h10.4M6.2 4.3V2.8h3.6v1.5M4.4 4.3l.6 8.9h6l.6-8.9M6.7 6.7v4.3M9.3 6.7v4.3"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconMore() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <circle cx="3.4" cy="8" r="1.35" />
      <circle cx="8" cy="8" r="1.35" />
      <circle cx="12.6" cy="8" r="1.35" />
    </svg>
  );
}


/** 把命中片段包成 <mark>。不用正则 —— 关键词里可能有 `.` `(` 这些元字符 */
function renderHighlighted(text, term) {
  const value = String(text === null || text === undefined ? '' : text);
  const needle = String(term || '').trim();
  if (!needle) return value;

  const haystack = value.toLowerCase();
  const target = needle.toLowerCase();
  const parts = [];
  let cursor = 0;
  let guard = 0;

  while (guard < 100) {
    guard += 1;
    const found = haystack.indexOf(target, cursor);
    if (found < 0) break;
    if (found > cursor) parts.push(value.slice(cursor, found));
    parts.push(
      <mark className="ptree__mark" key={`m${found}`}>
        {value.slice(found, found + target.length)}
      </mark>,
    );
    cursor = found + target.length;
  }
  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts.length ? parts : value;
}

export default function PartnerTree({
  kind = 'customer',
  tree = [],
  loading = false,
  error = '',
  notReady = false,
  selected = null,
  onSelect,
  uncategorizedCount = 0,
  allCount = null,
  onMove,
  /**
   * 拖拽归档（2026-10-21，客户档案试点）：把右侧表格的行拖到分类节点上。
   *
   * 与上面的 `onMove` / `onBatchMove` **不是同一件事**：
   *   · `onMove/onBatchMove` 搬的是**分类节点**（改 parent_id，用 pointer 事件实现）；
   *   · 这一组接的是**档案行**（改 category_id，用原生 HTML5 DnD 实现）。
   * 两套并存、互不干扰，别合并 —— 混在一起会出现"拖分类却归档了客户"。
   *
   * `onPartnerDrop(targetId|null)`：松手时回调，null = 「未分类」。
   * `onPartnerDragStart(row, event)`：未分类展开后的叶子行也要能拖。
   */
  partnerDropEnabled = false,
  onPartnerDrop,
  onPartnerDragStart,
  onPartnerDragEnd,
  partnerDragCount = 0,
  /**
   * "给我看这个节点"信号：`{ id, at }`，`at` 变一次触发一次。
   *
   * 拖拽归档之后用 —— 目标分类可能折叠在深层，右侧列表已经过滤好了，
   * 左侧却还是一片折叠，用户会以为"没生效"。收到信号就：
   *   ① 把它的所有祖先展开（否则行根本不存在，scrollIntoView 无从下手）；
   *   ② 滚到可见；
   *   ③ 闪一下（复用选中搜索命中的那个 is-flash 动画）。
   * 用 `at`（时间戳/计数器）而不是只看 id：同一个分类连续拖两次，
   * 第二次也要再展开+闪一次，否则"拖了没反应"。
   */
  revealSignal = null,
  /** 「未分类」展开后直接列出的行（由看板按 category_id==null 过滤好传进来） */
  uncategorizedRows = [],
  /**
   * 每个分类节点下"挂着的档案"：`{ [categoryId]: row[] }`。
   *
   * 2026-10-21 用户口径：树不能再是纯目录 —— 展开「施工一部」要能看见
   * 下面平铺的客户（像文件夹里的文件）。数据由看板按 `category_id` 分好传进来，
   * 树只负责画（不自己 fetch，保持"只吃 props"的契约）。
   * 叶子插在**整棵子树之后**（子分类先、文件后），空分类不插入任何东西。
   */
  rowsByCategory = null,
  /** 点某个客户叶子：(row) => void。看板用它把右表筛到这一条 */
  onPickRow,
  /**
   * 批量移动（多选拖拽）：(ids, parentId) => Promise<{moved,total}|null>
   * 不传时多选拖拽退化为"整批不可拖"（选区还能勾，但拖动按单条走）。
   * 由数据层提供（`usePartnerCategories().batchMove`）：内部串行 + 失败重拉。
   */
  onBatchMove,
  onRetry,
  /** 新建分类：(parentId|null, name) => Promise<createdNode|null> */
  onAdd,
  /** 重命名：(id, name) => Promise<boolean> */
  onRename,
  /** 删除：(id) => Promise<boolean> */
  onDelete,
  /** 建/改/删 进行中 —— 按钮禁用，避免连点造出两个同名节点 */
  busy = false,
  /**
   * 首次渲染时自动展开到第几层。
   * 2026-10-19：3 → **0**（只露出顶级分类，其余全部折叠）。
   * 原来展开 3 层，一进页面就是几十行，"左边像目录、右边像流水"，
   * 用户根本分不清自己在看哪一类。要看下层点小三角即可。
   */
  defaultExpandDepth = 0,
}) {
  const noun = kind === 'supplier' ? '供应商' : '客户';

  // ── 折叠状态：按 id 记，不按 name（分类可改名、跨分支可重名）
  const [expanded, setExpanded] = useState(() => new Set(defaultExpandedIds(tree, defaultExpandDepth)));
  const seeded = useRef(tree.length > 0);

  // 首次拿到数据时铺开前 N 层。只做一次 —— 之后用户的折叠结果必须留住，
  // 否则每次拖拽（树对象换新）都会把树重新摊开。
  useEffect(() => {
    if (seeded.current || !tree.length) return;
    seeded.current = true;
    setExpanded(new Set(defaultExpandedIds(tree, defaultExpandDepth)));
  }, [tree, defaultExpandDepth]);

  const [query, setQuery] = useState('');
  const [hitCursor, setHitCursor] = useState(-1);
  const [flashId, setFlashId] = useState(null);
  const [notice, setNotice] = useState('');
  /** 行尾 ⋯ / 长按 打开的操作菜单：{ id, x, y }（内联浮层，不是弹窗） */
  const [menu, setMenu] = useState(null);
  /** 「移入子分类…」的点选模式：正在为哪些节点选新父级。
   *  2E 起是**数组**：1 项 = 单条（旧行为），多项 = 整批（多选操作条「移动…」/ 行菜单批量入口）；
   *  提交时只把 moving[0] 交给 commitMove —— 批量分支靠 selection.has(fromId) 自己分流 */
  const [pickFor, setPickFor] = useState(null);
  /**
   * 多选（批量改分类的第一步）：
   *   selection 选区（id 集合，保持插入顺序 —— 批量移动的落地顺序就是它）
   *   anchorId  Shift 范围选择的锚点（范围按**当前可见行顺序**算，不跨折叠）
   *   selectMode 是否处于多选态。触屏没有修饰键可依附，靠长按菜单「多选」显式进入
   *   —— 只有它能让 checkbox 出现，不能只用 `selection.size > 0` 推导（刚进多选时是空的）
   */
  const [selection, setSelection] = useState(() => new Set());
  const [anchorId, setAnchorId] = useState(null);
  const [selectMode, setSelectMode] = useState(false);
  const bodyRef = useRef(null);
  const ghostRef = useRef(null);

  /**
   * 建类三态 —— 全部**内联**，不用弹窗：
   *   `editing` = { mode:'create'|'rename', id, parentId }
   *   深层节点被 modal 遮住是这个业务场景下最难受的体验（用户原话"避免遮住深层节点"），
   *   所以输入框就长在树上：新建子类 = 父级下一行；改名/删除 = 原地变形。
   */
  const [editing, setEditing] = useState(null);
  // —— 拖拽归档（试点）：高亮哪个节点 / 「未分类」是否展开 ——
  const [partnerOver, setPartnerOver] = useState(null);
  const [uncatOpen, setUncatOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [confirmId, setConfirmId] = useState(null);
  const draftRef = useRef(null);
  /** 防重复提交：blur 与按钮 click 可能连着触发两次 */
  const submitted = useRef(false);

  const index = useMemo(() => indexTree(tree), [tree]);

  /* ── 档案级搜索（2026-10-23）────────────────────────────────────────
   * 以前只能搜分类名：敲"周广平"什么也出不来，因为客户是挂在分类下的另一份数据。
   * 现在先在这份数据里找命中，把"有命中的分类 id"交给 buildVisibleRows ——
   * 它会把这些分类的祖先链强制展开（客户才露得出来），没命中的分支自然不渲染。 */
  const leafMatches = useMemo(
    () => matchPartnerLeaves(rowsByCategory, query),
    [rowsByCategory, query],
  );

  const nameHitCount = useMemo(
    () => (String(query || '').trim() ? searchNodes(tree, query).order.length : 0),
    [tree, query],
  );

  const { rows, hitIds, categoryHitIds, leafHitIds, searching } = useMemo(() => {
    // `focusOnly`：命中太多时只展开当前定位的那一条链（否则搜"公司"会摊开十几条）。
    // 命中少（<= 8）时全部铺开 —— 用户搜一个具体名字，就该一次看到它。
    const total = leafMatches.hitIds.length;
    const focusOnly = total + nameHitCount > 8;
    return buildVisibleRows(tree, index, {
      expanded,
      query,
      focusOnly,
      focusIndex: hitCursor,
      leafHits: leafMatches.hitIds,
    });
  }, [tree, index, expanded, query, hitCursor, leafMatches, nameHitCount]);

  /* 每个分类节点下要平铺的客户行，插在**该节点整棵子树之后**。
     算法：先序遍历里，某节点的子树到"下一个深度 <= 自己深度"的行为止。
     节点数很少（十几个），O(n²) 的 end 扫描完全够用，换来的是渲染顺序跟目录一致：
     子分类先、文件后。空分类 / 折叠着的节点不插入任何东西。 */
  const leafRowsOf = useCallback(
    (id) => (rowsByCategory && rowsByCategory[id] ? rowsByCategory[id] : []),
    [rowsByCategory],
  );

  const leafSlots = useMemo(() => {
    const out = new Map();
    if (!rowsByCategory) return out;
    rows.forEach((row, i) => {
      // 搜索态：只挂"这个分类下命中的客户"；非搜索态：照旧挂全部
      const kids = searching
        ? leafMatches.byCategory.get(String(row.id)) || []
        : rowsByCategory[row.id];
      // ⚠️ 这里判 `expanded` 而不是 `row.isOpen`：后者是 buildVisibleRows 按"有没有
      //    子分类"算出来的，纯叶子分类（例如「机具分公司」没有子类、只有 1 个客户）
      //    永远是 false —— 于是它的客户永远看不到。有客户的节点也必须可展开。
      // 搜索时由 buildVisibleRows 决定"这个分类是开着的"（命中客户的分类强制展开），
      // 不再看用户的折叠状态 —— 否则搜到了客户却因为它所在分类折叠着而看不见。
      const opened = searching ? row.isOpen : expanded.has(row.id);
      if (!kids || !kids.length || !opened) return;
      // ⚠️ 挂在**节点自己这一行之后、子分类之前**（用户口径：出现在所有子分类的**上方**）。
      //    早先是"插到整棵子树末尾"，用 `Map<末尾行下标, 客户[]>` 存 —— 但父子两级的
      //    "子树末尾"经常是**同一个下标**（父级最后一个子分类没有更深的后代时），
      //    后写的子级客户把父级的直接客户整组覆盖掉了。
      //    现象：角标 8（2 直挂 + 4 + 2），展开却只能数到 6 个叶子 —— 少的正是父级直挂的那 2 个。
      out.set(i, kids);
    });
    return out;
  }, [rows, rowsByCategory, searching, leafMatches]);

  const rowRefs = useRef(new Map());
  const flashTimer = useRef(null);
  useEffect(() => () => clearTimeout(flashTimer.current), []);

  const flash = useCallback((id) => {
    setFlashId(id);
    clearTimeout(flashTimer.current);
    // 与 CSS 的 ptree-flash 时长保持一致（1.6s）；短了会在动画没收尾时被摘掉
    flashTimer.current = setTimeout(() => setFlashId(null), 1600);
  }, []);

  // "展开祖先 + 滚到 + 闪一下"：拖拽归档完成后由看板触发
  const revealHandled = useRef(null);
  const revealTimer = useRef(null);
  useEffect(() => () => clearTimeout(revealTimer.current), []);
  useEffect(() => {
    if (!revealSignal || !revealSignal.id) return;
    if (revealHandled.current === revealSignal.at) return;
    revealHandled.current = revealSignal.at;
    const targetId = revealSignal.id;
    // 树若还停在搜索过滤态，目标很可能被剪掉 —— 那就永远"定位"不到。
    // 清掉关键词，让整棵树重新铺开（用户拖完想看的是"它进了哪个分类"，
    // 不是"我上次搜的那几个字"）。
    setQuery('');
    // 未分类不是树节点（category_id IS NULL），它本来就常驻可见，只需闪一下
    if (targetId !== UNCLASSIFIED) {
      const chain = ancestorsOf(index, targetId);
      // 目标自己也要展开（如果它有子级）：刚归档进来的档案会挂在**目标这一层**，
      // 但用户的下一步往往是继续往子级分拣 —— 顺手展开省一次点击。
      const self = index.byId ? index.byId.get(targetId) : null;
      const hasChildren = Boolean(self && Array.isArray(self.children) && self.children.length);
      if ((chain && chain.length) || hasChildren) {
        setExpanded((prev) => {
          const next = new Set(prev);
          (chain || []).forEach((id) => next.add(id));
          if (hasChildren) next.add(targetId);
          return next;
        });
      }
    }
    // 展开是 setState，得等这一帧画完行才在 DOM 里。
    // ⚠️ 这个 timer **不能在 cleanup 里清掉**：拖完紧接着 cats.reload()，
    //    `index`（依赖项）会立刻变一次，cleanup 一清，60ms 后的闪烁就永远不执行了
    //    —— 现象是"展开生效、闪烁没有"，很难看出是 effect 被重跑打断。
    //    改成：timer 存 ref，只在卸载时清；重复触发由 revealHandled 挡住。
    // 轮询等行出现（最多 1.2s）：固定 60ms 在"接口慢一点 / 机器忙一点"时就落空了 ——
    // 那时行还没渲染，scrollIntoView 无从下手，用户看到的就是"没定位到"。
    let tries = 0;
    clearTimeout(revealTimer.current);
    const tick = () => {
      const el = rowRefs.current.get(targetId);
      if (el) {
        if (typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
        flash(targetId);
        return;
      }
      tries += 1;
      if (tries < 24) revealTimer.current = setTimeout(tick, 50);
    };
    revealTimer.current = setTimeout(tick, 30);
  }, [revealSignal, index, flash]);

  /**
   * 兜底：**只要选中项变了且它不可见，就自动展开祖先**。
   *
   * 拖拽走的是上面的 revealSignal，但"选中"还有别的入口（从别的页面跳转聚焦、
   * 搜索命中、代码里 setCategoryId…）。这些入口以前都会留下"树里找不到当前选中的
   * 那一项"的状态。这里统一收口：选中谁，就把谁露出来。
   * 不闪、不滚 —— 只保证可见（滚动交给上面的 reveal 或用户自己）。
   */
  useEffect(() => {
    if (selected === null || selected === UNCLASSIFIED || selected === ALL) return;
    if (!index.byId || !index.byId.has(selected)) return;
    const hidden = ancestorsOf(index, selected).filter((id) => !expanded.has(id));
    if (!hidden.length) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      hidden.forEach((id) => next.add(id));
      return next;
    });
  }, [selected, index, expanded]);

  const toggle = useCallback((id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        return next;
      }
      // 手风琴（2026-10-21 用户要求）：展开一个节点时，把**同一个父级下**的
      // 其它已展开节点收起来 —— 点开「中铁一局集团」时「国家电网公司」连同它的
      // 子孙和客户一起折叠，屏幕上永远只留一条线在看。
      // 只折叠"兄弟"、不动父级链：否则展开子级时会把刚点开的父级自己关掉。
      const parentId = index.parentOf ? index.parentOf.get(id) : null;
      const siblings = index.childrenOf ? index.childrenOf.get(parentId) || [] : [];
      siblings.forEach((sid) => {
        if (sid !== id) next.delete(sid);
      });
      next.add(id);
      return next;
    });
  }, [index]);

  const expandAll = () => setExpanded(new Set(expandableIds(tree)));
  const collapseAll = () => setExpanded(new Set());

  // ── 选中：再点同一个就取消（回到「全部」）
  const select = useCallback(
    (id) => {
      if (!onSelect) return;
      onSelect(id === selected ? null : id);
    },
    [onSelect, selected],
  );

  // ── 多选：Ctrl/⌘ 离散、Shift 范围（按屏幕上的可见行顺序）、Esc 退出
  const multi = selectMode;
  /** 归一化结果只用来做文案：被祖先包住的那批"跟着走"，不能悄悄吞掉不说 */
  const selectionInfo = useMemo(() => normalizeSelection(index, selection), [index, selection]);
  const visibleIds = useMemo(() => rows.map((row) => row.id), [rows]);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selection.has(id));

  const exitSelectMode = useCallback(() => {
    setSelection(new Set());
    setAnchorId(null);
    setSelectMode(false);
  }, []);

  const toggleSelect = useCallback((id) => {
    setSelectMode(true);
    setAnchorId(id);
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /**
   * 行点击的多选分支。
   * Shift 的"范围"用的是 `visibleIds`（当前折叠 / 搜索结果下的可见行）——
   * 用户心里的顺序就是屏幕上的顺序，跨折叠去选看不见的节点只会让人困惑。
   */
  const handleRowClickSelect = useCallback(
    (row, { additive = false, range = false } = {}) => {
      setSelectMode(true);

      if (range && anchorId !== null) {
        const from = visibleIds.indexOf(anchorId);
        const to = visibleIds.indexOf(row.id);
        if (from >= 0 && to >= 0) {
          const [start, end] = from <= to ? [from, to] : [to, from];
          const span = visibleIds.slice(start, end + 1);
          setSelection((prev) => {
            const next = new Set(additive ? prev : []);
            span.forEach((id) => next.add(id));
            return next;
          });
          return; // 锚点不动：连续 Shift 点击可继续扩大 / 收缩范围
        }
      }

      setSelection((prev) => {
        const next = new Set(prev);
        // 多选态下（或按住修饰键）点已选中的 = 取消
        if ((additive || multi) && next.has(row.id)) next.delete(row.id);
        else next.add(row.id);
        return next;
      });
      setAnchorId(row.id);
    },
    [anchorId, visibleIds, multi],
  );

  const selectAllVisible = useCallback(() => {
    setSelectMode(true);
    setSelection((prev) => {
      const next = new Set(prev);
      visibleIds.forEach((id) => next.add(id));
      return next;
    });
    setAnchorId(visibleIds.length ? visibleIds[visibleIds.length - 1] : null);
  }, [visibleIds]);

  // Esc 退出多选。优先级：菜单 > 点选模式 > 多选（前两者各自有监听，这里避开它们）
  useEffect(() => {
    if (!selectMode || pickFor !== null || menu) return undefined;
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setSelection(new Set());
      setAnchorId(null);
      setSelectMode(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectMode, pickFor, menu]);

  // ── 建类：开始 / 提交 / 取消
  // 输入框挂载后自动聚焦并全选（改名时直接覆盖旧名字）
  useEffect(() => {
    if (!editing) return undefined;
    const timer = setTimeout(() => {
      const element = draftRef.current;
      if (element && typeof element.focus === 'function') {
        element.focus();
        if (typeof element.select === 'function') element.select();
      }
    }, 0);
    return () => clearTimeout(timer);
  }, [editing]);

  const beginCreate = useCallback((parentId = null) => {
    const parent = parentId === undefined ? null : parentId;
    setConfirmId(null);
    setNotice('');
    setEditing({ mode: 'create', id: null, parentId: parent });
    setDraft('');
    // 新建子类时先把父级摊开 —— 否则输入框长出来了，父级却还是收起的
    if (parent !== null) setExpanded((prev) => new Set([...prev, parent]));
    // 搜索态下新建的节点多半不在结果集里，会显得"点了没反应" → 顺手收掉搜索
    setQuery('');
  }, []);

  const beginRename = useCallback((row) => {
    setConfirmId(null);
    setNotice('');
    setEditing({ mode: 'rename', id: row.id, parentId: null });
    setDraft(row.node.name || '');
  }, []);

  const cancelEdit = useCallback(() => {
    setEditing(null);
    setDraft('');
  }, []);

  const commitEdit = useCallback(async () => {
    if (!editing || submitted.current) return;
    const name = String(draft || '').trim();
    const current = editing;
    // 空名 = 用户点开又什么都没写 → 当取消处理，不要弹"名称不能为空"来骂人
    if (!name) {
      cancelEdit();
      return;
    }
    submitted.current = true;
    setEditing(null);
    setDraft('');
    try {
      if (current.mode === 'create') {
        const created = onAdd ? await onAdd(current.parentId, name) : null;
        if (created && created.id !== undefined && created.id !== null) {
          flash(created.id);
        } else if (onAdd) {
          // 失败（重名 / 网络 / 400）：把输入框还给用户，原因已经由上面的 banner 说清楚
          setDraft(name);
          setEditing(current);
        }
      } else {
        const ok = onRename ? await onRename(current.id, name) : false;
        if (ok) flash(current.id);
        else if (onRename) {
          setDraft(name);
          setEditing(current);
        }
      }
    } finally {
      submitted.current = false;
    }
  }, [editing, draft, onAdd, onRename, flash, cancelEdit]);

  const doDelete = useCallback(
    async (id) => {
      setConfirmId(null);
      if (onDelete) await onDelete(id);
    },
    [onDelete],
  );

  /** 内联输入框（新建行、改名行共用同一份，行为才不会两套） */
  const renderDraftInput = () => (
    <>
      <input
        ref={draftRef}
        className="ptree__edit-input"
        type="text"
        value={draft}
        maxLength={100}
        placeholder={editing && editing.mode === 'rename' ? '分类名称' : '输入名称，如「集团客户」'}
        aria-label="分类名称"
        data-ptree-edit-input="1"
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          commitEdit();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            commitEdit();
            return;
          }
          if (event.key === 'Escape') {
            event.preventDefault();
            cancelEdit();
          }
        }}
      />
      <span className="ptree__edit-acts">
        <button
          type="button"
          className="ptree__edit-ok"
          title="保存（Enter）"
          disabled={busy}
          // mousedown 的 preventDefault 只为**不让 input 先 blur**（blur 会提交一次，
          // 按钮再 click 就是第二次）；它不会像 pointerdown 那样压掉 click
          onMouseDown={(event) => event.preventDefault()}
          onClick={(event) => {
            event.stopPropagation();
            commitEdit();
          }}
        >
          保存
        </button>
        <button
          type="button"
          className="ptree__edit-cancel"
          title="取消（Esc）"
          onMouseDown={(event) => event.preventDefault()}
          onClick={(event) => {
            event.stopPropagation();
            cancelEdit();
          }}
        >
          取消
        </button>
      </span>
    </>
  );

  /** 「新建子类」时插在父级下一行的那一行（缩进比父级深一级） */
  const renderDraftRow = (depth) => (
    <div
      className="ptree__row ptree__row--edit"
      data-ptree-draft="1"
      style={{ paddingLeft: `${indentOf(depth, 8)}px` }}
    >
      <span className="ptree__caret ptree__caret--leaf" aria-hidden="true" />
      {renderDraftInput()}
    </div>
  );

  /* ── 拖拽归档（试点）：把档案行接到分类节点上 ──────────────────────────
   * 命中判定认自定义 MIME，而不是"任意 drag"：
   *   浏览器从桌面拖一个文件进来时同样会触发 dragover/drop，
   *   不区分的话会把文件当成档案行去归档（还静默失败）。
   */
  const isPartnerDrag = (event) => {
    const types = event && event.dataTransfer ? Array.from(event.dataTransfer.types || []) : [];
    return types.includes('application/x-erp-partners');
  };

  /** targetId：分类 id；`UNCLASSIFIED` 表示「未分类」（回传时转成 null）。 */
  const partnerDropProps = (targetId) => {
    if (!partnerDropEnabled) return {};
    return {
      onDragEnter: (event) => {
        if (!isPartnerDrag(event)) return;
        event.preventDefault();
        setPartnerOver(targetId);
      },
      onDragOver: (event) => {
        if (!isPartnerDrag(event)) return;
        // 不 preventDefault 就不允许放下 —— 这一步是"我能接"的唯一声明
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        if (partnerOver !== targetId) setPartnerOver(targetId);
      },
      onDragLeave: (event) => {
        if (!isPartnerDrag(event)) return;
        // 在子元素之间移动也会触发 dragleave，判一下是不是真的离开这一行
        if (event.currentTarget && event.currentTarget.contains(event.relatedTarget)) return;
        setPartnerOver((current) => (current === targetId ? null : current));
      },
      onDrop: (event) => {
        if (!isPartnerDrag(event)) return;
        event.preventDefault();
        event.stopPropagation();
        setPartnerOver(null);

        /* 落点判定（2026-10-22 修"拖进 A 提示 B"）：
           原来直接回传这一行闭包里的 targetId —— 只要浏览器把 drop 派给了另一行
           （滚动/重排/吸附表头挡一下都可能），提示的分类和实际落库的分类就会对不上。
           现在以**松手坐标下真正那一行**为准：命中谁就是谁，命不中才退回闭包值。 */
        let resolved = targetId;
        try {
          const under = document.elementFromPoint(event.clientX, event.clientY);
          const rowEl = under && under.closest ? under.closest('[data-node-id]') : null;
          const raw = rowEl ? rowEl.getAttribute('data-node-id') : null;
          if (raw !== null && raw !== '') {
            resolved = raw === String(UNCLASSIFIED) ? UNCLASSIFIED : Number(raw);
          }
        } catch {
          /* 坐标拿不到就用闭包值 */
        }

        /* 被拖的 id 也在这里读一遍：dragend 与 drop 的先后顺序各浏览器不完全一致，
           万一 dragend 先把 ref 清了，页面那边还能从 payload 拿到真实列表。 */
        let payloadIds = [];
        try {
          const raw = event.dataTransfer.getData('application/x-erp-partners');
          if (raw) payloadIds = JSON.parse(raw);
        } catch {
          payloadIds = [];
        }

        const node = resolved !== UNCLASSIFIED && index.byId ? index.byId.get(resolved) : null;
        if (onPartnerDrop) {
          onPartnerDrop(resolved === UNCLASSIFIED ? null : resolved, {
            ids: Array.isArray(payloadIds) ? payloadIds : [],
            name: resolved === UNCLASSIFIED ? '未分类' : node ? node.name : '',
          });
        }
      },
    };
  };

  /**
   * 分类下的客户叶子：可拖走（归档到别的分类）、点了在右表定位这一条。
   * `ownerId` = 这个叶子所属的分类 —— 客户叶子**自身也是合法落点**：
   * 用户把档案拖到"文件上"松手，意思就是"放进这个文件夹"。
   * 早先叶子不带 drop props，拖到叶子上松手是彻底的静默失败（"完全没反应"）。
   */
  const renderCategoryLeaf = (row, depth, ownerId, hit = false) => (
    <div
      key={`leaf-${row.id}`}
      className={`ptree__leaf${hit ? ' is-hit' : ''}`}
      style={{ paddingLeft: `${indentOf(depth, 8) + 22}px` }}
      title={`${row.name}${row.code ? `（${row.code}）` : ''}`}
      data-partner-leaf={row.id}
      data-leaf-owner={ownerId}
      data-leaf-hit={hit ? 1 : undefined}
      {...partnerDropProps(ownerId)}
      draggable={Boolean(partnerDropEnabled)}
      onDragStart={(event) => onPartnerDragStart && onPartnerDragStart(row, event)}
      onDragEnd={() => onPartnerDragEnd && onPartnerDragEnd()}
      onClick={(event) => {
        event.stopPropagation();
        if (onPickRow) onPickRow(row);
      }}
    >
      <span className="ptree__leaf-dot" aria-hidden="true" />
      <span className="ptree__leaf-name">
        {hit ? renderHighlighted(row.name, query) : row.name}
      </span>
      {/* 搜索命中时补一条"为什么命中"：按联系人搜的（周广平），名字本身不含关键词，
          不显示出来用户会以为"这不是我要的人"。 */}
      {hit && row.contact ? <span className="ptree__leaf-meta">{row.contact}</span> : null}
    </div>
  );

  /** 未分类展开后的叶子行：可拖、可点（点了就等于在右表筛这条） */
  const renderUncatLeaves = () => {
    if (!uncatOpen) return null;
    const rows = Array.isArray(uncategorizedRows) ? uncategorizedRows : [];
    if (!rows.length) {
      return (
        <div className="ptree__leaf ptree__leaf--empty" style={{ paddingLeft: `${indentOf(0, 8) + 28}px` }}>
          没有未分类的档案
        </div>
      );
    }
    return rows.slice(0, 200).map((row) => (
      <div
        key={`uncat-${row.id}`}
        className="ptree__leaf"
        style={{ paddingLeft: `${indentOf(0, 8) + 22}px` }}
        title={`${row.name}${row.code ? `（${row.code}）` : ''}`}
        data-uncat-row={row.id}
        draggable={Boolean(partnerDropEnabled)}
        onDragStart={(event) => onPartnerDragStart && onPartnerDragStart(row, event)}
        onDragEnd={() => onPartnerDragEnd && onPartnerDragEnd()}
        onClick={() => onSelect && onSelect(UNCLASSIFIED)}
      >
        {/* 只显示名字：左栏只有 ~190px，名字 + 编码并排会让名字只剩四个字。
            编码放进 title（悬停可见），比"两个都看不全"有用。 */}
        <span className="ptree__leaf-name">{row.name}</span>
      </div>
    ));
  };

  /** 行内三按钮：+ 子类 / 改名 / 删除（hover 才出现，键盘 focus-within 也出现） */
  const renderRowActions = (row) => {
    // 一个回调都没传（只读模式）→ 连空 span 都不渲染，别给 DOM 添垃圾
    if (!onAdd && !onRename && !onDelete && !onMove) return null;
    return (
      <span className="ptree__acts">
        {/* 多选态下 + ✎ 🗑 全部隐藏：这时候点它们到底改的是哪一条？只会产生歧义。
            批量操作走顶部操作条，「⋯」保留（它本身不修改数据）。 */}
        {!multi && onAdd && (
          <button
            type="button"
            className="ptree__act"
            title={`在「${row.node.name}」下新建子分类`}
            aria-label="新建子分类"
            disabled={busy}
            data-ptree-act="add"
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              beginCreate(row.id);
            }}
          >
            <IconPlus />
          </button>
        )}
        {!multi && onRename && (
          <button
            type="button"
            className="ptree__act"
            title={`重命名「${row.node.name}」`}
            aria-label="重命名"
            disabled={busy}
            data-ptree-act="rename"
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              beginRename(row);
            }}
          >
            <IconPencil />
          </button>
        )}
        {!multi && onDelete && (
          <button
            type="button"
            className="ptree__act ptree__act--danger"
            title={`删除「${row.node.name}」`}
            aria-label="删除"
            disabled={busy}
            data-ptree-act="delete"
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              setEditing(null);
              setConfirmId(row.id);
            }}
          >
            <IconTrash />
          </button>
        )}
        {/* 「⋯」= 按钮通道入口。触屏上手指点它比拖拽稳，键盘也能用 */}
        {onMove && (
          <button
            type="button"
            className="ptree__act"
            title="更多操作：移入 / 上移 / 下移 / 移到顶级"
            aria-label="更多操作"
            data-ptree-act="menu"
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              const rect = event.currentTarget.getBoundingClientRect();
              openMenu(row, { x: rect.right - 150, y: rect.bottom + 4 });
            }}
          >
            <IconMore />
          </button>
        )}
      </span>
    );
  };

  // ── 搜索：回车逐个跳（顺序与眼睛看到的一致，见 `searchNodes` 的先序保证）
  useEffect(() => {
    setHitCursor(-1);
  }, [query]);

  /** 清空搜索 = 回到默认折叠（用户口径 2026-10-23）。
   *
   * 以前搜索不改 `expanded`，清空后树还是"上次手动摊开的样子"；现在明确要求
   * "清空即恢复默认全量折叠"。这里只复位到 `defaultExpandedIds`（默认 0 层 = 全折叠），
   * 不硬写成空集 —— 将来若把默认展开层数调大，这里自动跟着走。
   */
  const clearSearch = useCallback(() => {
    setQuery('');
    setHitCursor(-1);
    setExpanded(new Set(defaultExpandedIds(tree, defaultExpandDepth)));
  }, [tree, defaultExpandDepth]);

  const jumpHit = useCallback(
    (delta) => {
      if (!hitIds.length) return;
      const next = (hitCursor + delta + hitIds.length) % hitIds.length;
      setHitCursor(next);
      const id = hitIds[next];
      const el = rowRefs.current.get(id);
      // jsdom 里没有 scrollIntoView —— 可选调用，别让验证台因此崩
      if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
      flash(id);
    },
    [hitIds, hitCursor, flash],
  );

  // clearSearch 在 jumpHit 之前定义，onSearchKeyDown 直接用（同一次 render 内）

  const onSearchKeyDown = (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      jumpHit(event.shiftKey ? -1 : 1);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      clearSearch();
    }
  };

  // ── 移动：拖拽和按钮通道**共用**这一个提交口，落点语义只有一个真源
  const commitMove = useCallback(
    async (fromId, target) => {
      // 多选拖拽：拖的是选区里的一行 → 整批走批量通道。
      // 落点只取 parentId（批量不排序，一律追加到目标末尾），
      // hook 传来的 target.parentId 已经是换算好的：行中间=进它里面，行边缘=和它同级。
      if (multi && onBatchMove && selection.has(fromId)) {
        const plan = batchMovePlan(index, selection, target.parentId);
        if (!plan.ok) {
          // noop（全都在目标下了）不算失败，说清楚就行
          setNotice(plan.code === 'noop' ? '选中的分类已经在这个分类下了' : plan.reason);
          return plan.code === 'noop';
        }
        const result = await onBatchMove(plan.ids, target.parentId);
        if (!result) {
          setNotice('移动没有生效，分类已还原');
          return false;
        }
        if (target.parentId !== null && target.parentId !== undefined) {
          setExpanded((prev) => new Set([...prev, target.parentId]));
        }
        exitSelectMode(); // 批量完成后选区已经"用掉了"，留着只会让人想再拖一次
        flash(fromId);
        // ⚠️ 部分成功必须留提示，别被下面的 setNotice('') 冲掉
        if (result.moved < plan.ids.length) {
          setNotice(`只移动了 ${result.moved}/${plan.ids.length} 项，已同步为后端当前状态`);
        } else {
          setNotice('');
        }
        return true;
      }

      if (!onMove || !target) return false;
      const ok = await onMove(fromId, target);
      if (!ok) {
        setNotice('移动没有生效，分类已还原');
        return false;
      }
      // 多选态下拖了**未选中**的行 = 单条操作：顺手退出多选，别让勾选框悬在半空
      if (multi) exitSelectMode();
      // 移进一个收起的节点时顺手展开 —— 否则用户会觉得"东西移丢了"
      if (target.parentId !== null && target.parentId !== undefined) {
        setExpanded((prev) => new Set([...prev, target.parentId]));
      }
      flash(fromId);
      setNotice('');
      return true;
    },
    [onMove, onBatchMove, flash, multi, selection, index, exitSelectMode],
  );

  const drag = usePartnerDrag({
    index,
    bodyRef,
    ghostRef,
    onMove: commitMove,
    onBegin: () => {
      // 开始拖的一瞬间把其它内联状态收掉，避免输入框跟着手指走
      setEditing(null);
      setConfirmId(null);
      setMenu(null);
      setPickFor(null);
      setNotice('');
    },
    onFinish: (id, ok) => {
      if (!ok) setNotice('移动没有生效，分类已还原');
    },
    onLongPress: (row, point) => {
      setEditing(null);
      setConfirmId(null);
      openMenu(row, point);
    },
  });

  const dragId = drag.dragId;
  const dropOver = drag.preview; // { kind:'before'|'after'|'inside'|'forbidden', targetId, move }

  /**
   * 批量拖拽生效中：拖的是选区里的一行 → 落点语义换成"整批移入"。
   * hook 的 preview 仍是单条语义（inside/before/after），这里做两件事：
   *   ① 换算出批量真正的落点父级（行中间 = 进它里面；行边缘 = 和它同级、追加末尾）；
   *   ② 目标落进**任何一个选中项**的子树里 → 整批改判 forbidden（单条校验只防 dragId 自己）。
   * 行高亮 / 浮标 / 提交全部以 `shownPreview` 为准 —— 只看一半就会"看着是绿的，松手是被拒的"。
   */
  const batchDrag = multi && dragId !== null && selection.has(dragId) && Boolean(onBatchMove);
  const shownPreview = useMemo(() => {
    if (!dropOver || !batchDrag) return dropOver;
    if (dropOver.kind === 'forbidden') return dropOver;
    const parentId = dropOver.kind === 'inside'
      ? dropOver.targetId
      : (index.parentOf.has(dropOver.targetId) ? index.parentOf.get(dropOver.targetId) : null);
    const plan = batchMovePlan(index, selection, parentId);
    return {
      ...dropOver,
      batchParentId: parentId,
      batchPlan: plan,
      kind: plan.ok || plan.code === 'noop' ? dropOver.kind : 'forbidden',
    };
  }, [dropOver, batchDrag, index, selection]);

  /** 打开操作菜单（行尾 ⋯ 与长按共用）。坐标会被夹在视口内，贴边时不至于飞出屏幕 */
  function openMenu(row, point) {
    const width = 168;
    const height = 238; // 5 项操作 + 多选
    const maxX = (typeof window === 'undefined' ? 1200 : window.innerWidth) - width - 8;
    const maxY = (typeof window === 'undefined' ? 800 : window.innerHeight) - height - 8;
    setMenu({
      id: row.id,
      name: row.node ? row.node.name : '',
      x: Math.max(8, Math.min(point.x || 0, maxX)),
      y: Math.max(8, Math.min(point.y || 0, maxY)),
    });
  }

  const closeMenu = () => setMenu(null);

  /** 「上移 / 下移」：换算成同一套 {parentId, beforeId}，到边界就明说不动 */
  const moveByStep = async (delta) => {
    if (!menu) return;
    const target = siblingMoveTarget(index, menu.id, delta);
    const id = menu.id;
    closeMenu();
    if (!target) {
      setNotice(delta < 0 ? '已经在同级最前面了' : '已经在同级最后面了');
      return;
    }
    await commitMove(id, target);
  };

  /** 「移到顶级」 */
  const moveToRoot = async () => {
    if (!menu) return;
    const id = menu.id;
    closeMenu();
    await commitMove(id, { parentId: null, beforeId: null });
  };

  /** 「移入子分类…」：进入点选模式。多选态下被选中的行 = 整批进点选（2E 菜单通道） */
  const startPickParent = () => {
    if (!menu) return;
    if (multi && selection.has(menu.id) && onBatchMove && selection.size > 1) {
      setPickFor([...selection]);
      setNotice(`点一个分类，把选中的 ${selection.size} 项移进去；按 Esc 取消`);
    } else {
      setPickFor([menu.id]);
      setNotice('点一个分类，把它移进去；按 Esc 取消');
    }
    closeMenu();
  };

  /** 点选模式下点行 = 确认新父级。pickFor 是数组：1 项 = 单条、多项 = 整批（交给 commitMove 分流） */
  const pickParent = async (row) => {
    const moving = pickFor;
    setPickFor(null);
    if (!Array.isArray(moving) || moving.length === 0) return;
    const blockedBy = moving.find((id) => id === row.id || isDescendant(index, id, row.id));
    if (blockedBy !== undefined) {
      // 批量时说清楚是"选区里有它自己/它的上级"，别让人对着 N 项猜是哪条
      setNotice(
        moving.length > 1
          ? '选中的分类里包含它自己或它的上级，不能移到这里'
          : blockedBy === row.id
            ? '不能移到自己身上'
            : '不能移进它自己的子级里',
      );
      return;
    }
    await commitMove(moving[0], { parentId: row.id, beforeId: null });
  };

  // 点选模式 / 菜单都支持 Esc 退出（菜单的 Esc 由全局监听处理，见下）
  useEffect(() => {
    if (pickFor === null) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setPickFor(null);
        setNotice('');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pickFor]);

  useEffect(() => {
    if (!menu) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMenu(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menu]);

  const onRowKeyDown = (event, row) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      // 点选模式优先：空格/回车 = 确认这个目标（和鼠标点击同一条路）
      if (pickFor) {
        pickParent(row);
        return;
      }
      // 多选态下空格/回车 = 勾选，不再是"过滤到这个分类"
      if (multi) toggleSelect(row.id);
      else select(row.id);
      return;
    }
    if (event.key === 'ArrowRight' && row.hasChildren && !row.isOpen) {
      event.preventDefault();
      toggle(row.id);
      return;
    }
    if (event.key === 'ArrowLeft' && row.hasChildren && row.isOpen) {
      event.preventDefault();
      toggle(row.id);
    }
  };

  // 只有点过「全部」才是激活态；null = 还没选（初始态右表为空，这里也不该亮）
  const allActive = selected === ALL;

  return (
    <div className={`ptree ptree--${kind}`}>
      {/* ── 搜索框：树的顶部，是这棵深树的"入口"，不是列表的附属品 ── */}
      <div className="ptree__search">
        <span className="ptree__search-icon" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="6.8" cy="6.8" r="4.6" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.4 10.4 L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </span>
        <input
          className="ptree__search-input"
          type="search"
          value={query}
          placeholder={`搜索${noun}分类 / 项目名称…`}
          aria-label={`搜索${noun}分类`}
          onChange={(event) => {
            const next = event.target.value;
            if (!next.trim()) {
              // 退格删空也算"清空搜索"，同样要恢复默认折叠
              clearSearch();
              return;
            }
            setQuery(next);
            // 边打字边回到"第一个命中"：否则沿用上一次的序号，
            // 会出现"停在搜不到的序号上，树里一条链都不展开"的尴尬。
            setHitCursor(-1);
          }}
          onKeyDown={onSearchKeyDown}
          data-ptree-search="1"
        />
        {query && (
          <button
            type="button"
            className="ptree__search-clear"
            title="清空搜索（Esc）"
            aria-label="清空搜索"
            onClick={() => clearSearch()}
          >
            ×
          </button>
        )}
      </div>

      {/* 命中统计 + 上下跳。只在真的有关键词时出现，平时不占高度 */}
      {searching && (
        <div
          className="ptree__hits"
          data-ptree-hits="1"
          title="树里只展开当前定位的这一条路径；按 Enter / ↑↓ 逐个定位"
        >
          {hitIds.length ? (
            <>
              <span data-ptree-hit-count={hitIds.length}>
                找到 <strong>{hitIds.length}</strong> 处
                {leafHitIds.length ? <em className="ptree__hits-leaf">（含 {leafHitIds.length} 个分类下有{noun}命中）</em> : null}
                {hitCursor >= 0 ? `（第 ${hitCursor + 1} 个）` : ''}
              </span>
              <span className="ptree__hits-nav">
                <button type="button" onClick={() => jumpHit(-1)} title="上一个（Shift+Enter）">
                  ↑
                </button>
                <button type="button" onClick={() => jumpHit(1)} title="下一个（Enter）">
                  ↓
                </button>
              </span>
            </>
          ) : (
            <span className="ptree__hits-none">没有匹配的{noun}分类或档案</span>
          )}
        </div>
      )}

      {/* 展开/折叠全部：深树手动逐层点太慢，但也不该在搜索时出现（搜索有自己的可见性规则） */}
      {!searching && (
        <div className="ptree__tools">
          {onAdd && (
            <button
              type="button"
              className="ptree__add"
              title="在顶级新建一个分类（如「集团客户」）"
              disabled={busy || notReady || multi}
              data-ptree-add-root="1"
              onClick={() => beginCreate(null)}
            >
              <IconPlus />
              新建分类
            </button>
          )}
          <button type="button" className="link-btn" onClick={expandAll}>
            展开全部
          </button>
          <button type="button" className="link-btn" onClick={collapseAll}>
            折叠全部
          </button>
          <span className="ptree__tools-meta">{index.byId.size} 个分类</span>
        </div>
      )}

      {/* 多选操作条：sticky 贴在树体上方，滚多深都看得见"选了几个、下一步点什么" */}
      {multi && (
        <div className="ptree__multi" data-ptree-multi="1" role="status">
          <span className="ptree__multi-count" data-ptree-multi-count="1">
            {selection.size ? (
              <>
                已选 <strong>{selection.size}</strong> 项
                {selectionInfo.covered.length > 0 && (
                  <span className="ptree__multi-note">
                    （其中 {selectionInfo.covered.length} 项随父级移动）
                  </span>
                )}
              </>
            ) : (
              <span className="ptree__multi-note">勾选要移动的分类</span>
            )}
          </span>
          <span className="ptree__multi-acts">
            <button
              type="button"
              className="link-btn"
              data-ptree-multi-move="1"
              disabled={selection.size === 0}
              title="点一个分类，把勾选的全部移进去"
              onClick={() => {
                setPickFor([...selection]);
                setNotice('');
              }}
            >
              移动…
            </button>
            <button
              type="button"
              className="link-btn"
              data-ptree-multi-all="1"
              title={allVisibleSelected ? '取消全部勾选' : '勾选当前看得见的所有分类'}
              onClick={allVisibleSelected ? () => setSelection(new Set()) : selectAllVisible}
            >
              {allVisibleSelected ? '清空选择' : '全选可见'}
            </button>
            <button
              type="button"
              className="link-btn"
              data-ptree-multi-cancel="1"
              onClick={exitSelectMode}
            >
              取消（Esc）
            </button>
          </span>
        </div>
      )}

      {/* ⚠️ 「后端没有这条路由」(404) 和「后端真的报错」必须分开处理：
          前者是**功能没上线**（代码合并了但服务没重启），这时左树该安静地降级成
          「全部 / 未分类」两个出口 + 一条灰提示；弹红框只会让人以为数据坏了。
          后者（401/5xx/网络）才是真错误，才配红色 + 重试。 */}
      {notReady ? (
        <div className="ptree__notice" data-ptree-notready="1">
          <span className="ptree__notice-text">
            分类功能未就绪{error ? `（${error}）` : ''}
          </span>
          {onRetry && (
            <button type="button" className="link-btn" onClick={onRetry}>
              重试
            </button>
          )}
        </div>
      ) : null}

      {!notReady && (error || notice) && (
        <div className="ptree__banner" role="alert">
          <span>{error || notice}</span>
          {error && onRetry && (
            <button type="button" className="link-btn" onClick={onRetry}>
              重试
            </button>
          )}
          {!error && (
            <button type="button" className="link-btn" onClick={() => setNotice('')}>
              知道了
            </button>
          )}
        </div>
      )}

      {/* 「移入子分类…」的点选模式：直接用树本身当选择器，不再套一层弹窗 */}
      {pickFor !== null && (
        <div className="ptree__pickbar" data-ptree-pickbar="1" role="status">
          <span className="ptree__pickbar-text">
            {pickFor.length > 1 ? (
              <>
                点一个分类，把选中的 <strong>{pickFor.length}</strong> 项移进去
              </>
            ) : (
              <>
                点一个分类，把
                <strong>
                  {(() => {
                    const item = rows.find((row) => row.id === pickFor[0]);
                    return item ? item.node.name : '它';
                  })()}
                </strong>
                移进去
              </>
            )}
          </span>
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setPickFor(null);
              setNotice('');
            }}
          >
            取消（Esc）
          </button>
        </div>
      )}

      <div
        ref={bodyRef}
        className={`ptree__body${dragId !== null ? ' is-dragging' : ''}${pickFor !== null ? ' is-picking' : ''}${multi ? ' is-multi' : ''}`}
        role="tree"
        aria-label={`${noun}分类树`}
        aria-busy={loading ? 'true' : 'false'}
      >
        {/* 「全部」= 取消分类过滤。搜索时藏起来：结果集里没有"全部"这个概念 */}
        {!searching && (
          <div
            className={`ptree__row ptree__row--all${allActive ? ' is-active' : ''}`}
            role="treeitem"
            aria-selected={allActive}
            tabIndex={0}
            style={{ paddingLeft: `${indentOf(0, 8) + (multi ? CHECK_SLOT : 0)}px` }}
            onClick={() => onSelect && onSelect(ALL)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                if (onSelect) onSelect(ALL);
              }
            }}
          >
            <span className="ptree__caret ptree__caret--leaf" aria-hidden="true" />
            <span className="ptree__label">全部{noun}</span>
            {allCount !== null && <span className="ptree__count">{allCount}</span>}
          </div>
        )}

        {loading && rows.length === 0 && (
          <div className="ptree__skeleton" aria-hidden="true">
            <span /><span /><span /><span />
          </div>
        )}

        {/* 「新建顶级分类」的输入行：放在「全部」下面，即使树很深也一定看得见 */}
        {editing && editing.mode === 'create' && editing.parentId === null && renderDraftRow(0)}

        {rows.map((row, rowIndex) => {
          const renaming = Boolean(editing && editing.mode === 'rename' && editing.id === row.id);
          const confirming = confirmId === row.id;
          const picking = Array.isArray(pickFor) && pickFor.length > 0;
          const pickSource = picking && pickFor.includes(row.id);
          // 自己的子孙不能当新父级（后端也会拒，但这里先灰掉，别让用户白点）；批量时任一选中项的子孙都算
          const pickBlocked = picking && !pickSource && pickFor.some((id) => isDescendant(index, id, row.id));
          const classes = [
            'ptree__row',
            row.isOpen ? 'is-open' : '',
            row.id === selected ? 'is-active' : '',
            row.isMatched ? 'is-hit' : '',
            row.depth >= DEEP_DEPTH ? 'is-deep' : '',
            renaming ? 'is-editing' : '',
            confirming ? 'is-confirming' : '',
            dragId === row.id ? 'is-dragging-source' : '',
            shownPreview && shownPreview.targetId === row.id && shownPreview.kind !== 'forbidden'
              ? `is-drop-${shownPreview.kind}`
              : '',
            shownPreview && shownPreview.targetId === row.id && shownPreview.kind === 'forbidden'
              ? 'is-drop-forbidden'
              : '',
            pickSource ? 'is-pick-source' : '',
            picking && !pickSource && !pickBlocked ? 'is-pick-target' : '',
            pickBlocked ? 'is-pick-disabled' : '',
            multi && selection.has(row.id) ? 'is-selected' : '',
            // 被选区里的祖先包住：勾选框给"半选"视觉，提示它其实跟着父级走
            multi && selectionInfo.covered.includes(row.id) ? 'is-covered' : '',
            flashId === row.id ? 'is-flash' : '',
            // 拖拽归档：这一行正被拖过来的档案行悬停
            partnerOver === row.id ? 'is-partner-drop' : '',
          ]
            .filter(Boolean)
            .join(' ');

          return (
            <Fragment key={row.id}>
              <div
                ref={(element) => {
                  if (element) rowRefs.current.set(row.id, element);
                  else rowRefs.current.delete(row.id);
                }}
                className={classes}
                role="treeitem"
                aria-level={row.depth + 1}
                aria-selected={row.id === selected}
                aria-expanded={row.hasChildren || leafRowsOf(row.id).length ? expanded.has(row.id) : undefined}
                tabIndex={0}
                data-node-id={row.id}
                data-depth={row.depth}
                {...partnerDropProps(row.id)}
                title={row.node.note ? `${row.node.name} · ${row.node.note}` : row.node.name}
                style={{ paddingLeft: `${indentOf(row.depth)}px` }}
                onClick={(event) => {
                  // 拖完那一下的 click 必须吞掉，否则"拖完顺手把这一行选中了"
                  if (drag.isClickSuppressed()) return;
                  if (picking) {
                    pickParent(row);
                    return;
                  }
                  if (renaming || confirming) return;
                  // Ctrl/⌘ 离散、Shift 范围、多选态下普通点击 = 勾选切换
                  const additive = event.ctrlKey || event.metaKey;
                  const range = event.shiftKey;
                  if (additive || range || multi) {
                    handleRowClickSelect(row, { additive, range });
                    return;
                  }
                  select(row.id);
                }}
                // 行内按钮的键盘事件会冒泡上来，别把"按 Enter 点按钮"变成"选中这一行"
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  onRowKeyDown(event, row);
                }}
                // 鼠标：按下后移动 4px 才开始拖（否则算点击）；触屏：行体长按 500ms 弹菜单。
                // 触屏拖拽只能从手柄起手 —— 行体必须留给"滚动"，见 usePartnerDrag 顶部注释。
                onPointerDown={(event) => {
                  if (renaming || confirming || picking || !onMove) return;
                  drag.rowPointerDown(event, row);
                }}
              >
                {/* 多选态才出现勾选框：平时树是"导航工具"，常驻 checkbox 会把
                    「点一下过滤」这个主操作挤成必须瞄准的小目标（深树还很吃缩进） */}
                {multi && !renaming && !confirming && (
                  <span className="ptree__check">
                    <input
                      type="checkbox"
                      className="ptree__checkbox"
                      checked={selection.has(row.id)}
                      aria-label={`选择「${row.node.name}」`}
                      data-ptree-check={row.id}
                      tabIndex={-1}
                      onClick={(event) => event.stopPropagation()}
                      onChange={() => toggleSelect(row.id)}
                    />
                  </span>
                )}

                {row.hasChildren || leafRowsOf(row.id).length ? (
                  <span
                    className={[
                      'ptree__caret',
                      expanded.has(row.id) ? 'is-open' : 'is-collapsed',
                      row.depth >= DEEP_DEPTH ? 'ptree__caret--deep' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    title={`${row.isOpen ? '折叠' : '展开'}（第 ${row.depth + 1} 层）`}
                    aria-hidden="true"
                    onClick={(event) => {
                      event.stopPropagation();
                      toggle(row.id);
                    }}
                  >
                    <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                      <path
                        d="M1 2.5 L4 6 L7 2.5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                ) : (
                  <span className="ptree__caret ptree__caret--leaf" aria-hidden="true" />
                )}

                {renaming ? (
                  renderDraftInput()
                ) : confirming ? (
                  <>
                    <span className="ptree__label ptree__label--danger">
                      删除「{row.node.name}」？
                    </span>
                    <span className="ptree__edit-acts">
                      <button
                        type="button"
                        className="ptree__edit-ok ptree__edit-ok--danger"
                        title="确认删除（有子级或仍被档案引用时后端会拒绝）"
                        disabled={busy}
                        data-ptree-confirm="1"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={(event) => {
                          event.stopPropagation();
                          doDelete(row.id);
                        }}
                      >
                        删除
                      </button>
                      <button
                        type="button"
                        className="ptree__edit-cancel"
                        title="不删了"
                        data-ptree-confirm-cancel="1"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={(event) => {
                          event.stopPropagation();
                          setConfirmId(null);
                        }}
                      >
                        取消
                      </button>
                    </span>
                  </>
                ) : (
                  <>
                    <span className="ptree__label">{renderHighlighted(row.node.name, query)}</span>

                    {/* 深度角标：缩进 10 层封顶之后，靠它读"我在第几层" */}
                    {row.depth >= DEEP_DEPTH && (
                      <span className="ptree__depth" aria-hidden="true">
                        L{Math.min(row.depth + 1, 99)}
                      </span>
                    )}

                    {renderRowActions(row)}

                    <span
                      className="ptree__count"
                      title={`直接 ${row.node.count || 0} · 含子孙 ${row.node.total || 0}`}
                    >
                      {row.node.total || 0}
                    </span>

                    <span
                      className="ptree__grip"
                      role="button"
                      tabIndex={-1}
                      aria-label={`拖动「${row.node.name}」调整位置`}
                      title={
                        typeof window !== 'undefined'
                        && window.matchMedia
                        && window.matchMedia('(pointer: coarse)').matches
                          ? '按住这里拖动'
                          : '拖动调整层级 / 顺序'
                      }
                      data-ptree-grip="1"
                      // 手柄是触屏唯一的拖拽入口：`touch-action:none` 让浏览器别抢手势
                      onPointerDown={(event) => {
                        if (renaming || confirming || picking || !onMove) return;
                        drag.handlePointerDown(event, row);
                      }}
                    >
                      <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden="true">
                        <circle cx="3" cy="2.5" r="1" /><circle cx="7" cy="2.5" r="1" />
                        <circle cx="3" cy="6" r="1" /><circle cx="7" cy="6" r="1" />
                        <circle cx="3" cy="9.5" r="1" /><circle cx="7" cy="9.5" r="1" />
                      </svg>
                    </span>
                  </>
                )}
              </div>

              {/* 「新建子类」的输入行紧贴父级下方，缩进深一级：位置本身就是"它将挂在哪" */}
              {editing && editing.mode === 'create' && editing.parentId === row.id
                ? renderDraftRow(row.depth + 1)
                : null}

              {/* 挂在这个分类下的**客户叶子**（像文件夹里的文件），
                  插在整棵子树之后：子分类先、客户后。折叠着就不插。 */}
              {(leafSlots.get(rowIndex) || []).slice(0, LEAF_LIMIT).map((leaf) =>
                renderCategoryLeaf(leaf, row.depth + 1, row.id, searching),
              )}
              {(leafSlots.get(rowIndex) || []).length > LEAF_LIMIT ? (
                <div
                  className="ptree__leaf ptree__leaf--more"
                  style={{ paddingLeft: `${indentOf(row.depth + 1, 8) + 22}px` }}
                >
                  还有 {(leafSlots.get(rowIndex) || []).length - LEAF_LIMIT} 个客户…
                </div>
              ) : null}
            </Fragment>
          );
        })}

        {/* 空态：区分"还没建" / "搜不到" / "加载失败" —— 三种情况该给的建议完全不同。
            `notReady` 时不显示：上面的灰提示已经说明白了，再来一句就是重复。
            正在新建时也不显示（输入框已经在上面了，下面再来一句"还没有分类"很蠢）。 */}
        {!loading && rows.length === 0 && !notReady && !editing && (
          <div className="ptree__empty">
            <span>
              {searching
                ? '换个关键词试试，或点右侧 × 清空'
                : error
                  ? '分类加载失败，点上面的「重试」再试一次'
                  : `还没有建${noun}分类，先建一个「集团客户」吧`}
            </span>
            {onAdd && !searching && !error && (
              <button
                type="button"
                className="ptree__empty-add"
                data-ptree-empty-add="1"
                onClick={() => beginCreate(null)}
              >
                <IconPlus />
                新建第一个分类
              </button>
            )}
          </div>
        )}

        {/* 拖拽时铺一条"移到顶级"的落点：没有它，节点挪不回根上。
            命中判定不靠这个元素自己的 rect（拖动中它才挂载，量不到稳定位置），
            而是"最后一行下方 / 容器底部上方"这段区域，见 usePartnerDrag.hitTest */}
        {dragId !== null && (
          <div className={`ptree__rootdrop${drag.rootOver ? ' is-over' : ''}`} data-ptree-rootdrop="1">
            拖到这里 → 移到顶级
          </div>
        )}

        {/* 「未分类」固定在树尾：它不是树里的节点（category_id IS NULL），
            但用户必须能一键看到"还没归类的那批"。 */}
        {!searching && (
          <div
            className={[
              'ptree__row',
              'ptree__row--uncat',
              selected === UNCLASSIFIED ? 'is-active' : '',
              uncatOpen ? 'is-open' : '',
              partnerOver === UNCLASSIFIED ? 'is-partner-drop' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            role="treeitem"
            aria-selected={selected === UNCLASSIFIED}
            aria-expanded={uncategorizedCount > 0 ? uncatOpen : undefined}
            tabIndex={0}
            style={{ paddingLeft: `${indentOf(0, 8) + (multi ? CHECK_SLOT : 0)}px` }}
            data-uncat-node="1"
            {...partnerDropProps(UNCLASSIFIED)}
            onClick={() => onSelect && onSelect(UNCLASSIFIED)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                if (onSelect) onSelect(UNCLASSIFIED);
              }
              if (event.key === 'ArrowRight' && !uncatOpen) setUncatOpen(true);
              if (event.key === 'ArrowLeft' && uncatOpen) setUncatOpen(false);
            }}
          >
            {/* 像文件夹一样可展开：点小三角只展开，点行本身仍然是"筛到未分类" */}
            <button
              type="button"
              className={`ptree__caret ptree__caret--toggle${uncatOpen ? ' is-open' : ''}`}
              aria-label={uncatOpen ? '收起未分类档案' : '展开未分类档案'}
              title={uncatOpen ? '收起' : '展开看看里面有哪些'}
              disabled={!uncategorizedCount}
              data-uncat-toggle="1"
              onClick={(event) => {
                event.stopPropagation();
                setUncatOpen((open) => !open);
              }}
            >
              <svg viewBox="0 0 12 12" width="9" height="9" aria-hidden="true">
                <path d="M4 2.5 L8.5 6 L4 9.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            </button>
            <span className="ptree__label">未分类</span>
            <span className="ptree__count">{uncategorizedCount}</span>
          </div>
        )}
        {!searching && renderUncatLeaves()}

        {dragId !== null && <div className="ptree__dragtip">{DRAG_TIP}</div>}
      </div>

      {/* 拖动中的浮标：跟手的一个小标签。
          为什么必须有它：手指会遮住落点，触屏上没有"禁止"光标这类提示，
          用户只能靠这个浮标 + 行高亮来确认"松手会发生什么"。 */}
      {dragId !== null && (
        <div className="ptree__ghost" ref={ghostRef} data-ptree-ghost="1" aria-hidden="true">
          <span className="ptree__ghost-name">
            {(() => {
              // 批量：浮标报"几项"比报"哪一行"有用 —— 整批都在动
              if (batchDrag) return `${selectionInfo.kept.length} 项`;
              const hit = rows.find((item) => item.id === dragId);
              return hit ? hit.node.name : '';
            })()}
          </span>
          <span className="ptree__ghost-hint">
            {(() => {
              if (batchDrag) {
                const count = selectionInfo.kept.length;
                if (drag.rootOver) return `移动 ${count} 项 → 移到顶级`;
                if (shownPreview && shownPreview.kind === 'forbidden') {
                  const plan = shownPreview.batchPlan;
                  return plan && plan.code === 'cycle' ? '不能移进选中的分类里面' : '不能放到这里';
                }
                if (shownPreview && shownPreview.batchParentId !== undefined) {
                  const parentName = shownPreview.batchParentId === null
                    ? '顶级'
                    : (index.byId.get(shownPreview.batchParentId) || {}).name || '';
                  return `移动 ${count} 项 → 移入「${parentName}」`;
                }
                return `移动 ${count} 项…`;
              }
              return drag.rootOver
                ? '移到顶级'
                : shownPreview && shownPreview.kind === 'forbidden'
                  ? '不能放到这里'
                  : shownPreview && shownPreview.kind === 'inside'
                    ? `移入「${(rows.find((item) => item.id === shownPreview.targetId) || { node: {} }).node.name || ''}」`
                    : shownPreview && shownPreview.kind === 'before'
                      ? '插到上一行前面'
                      : shownPreview && shownPreview.kind === 'after'
                        ? '插到这一行后面'
                        : '拖动中…';
            })()}
          </span>
        </div>
      )}

      {/* 操作菜单（行尾 ⋯ / 触屏长按 共用）：内联浮层，不是 modal */}
      {menu && (
        <>
          <div className="ptree__menu-mask" onClick={closeMenu} data-ptree-menu-mask="1" />
          <div
            className="ptree__menu"
            role="menu"
            style={{ left: `${menu.x}px`, top: `${menu.y}px` }}
            data-ptree-menu="1"
          >
            <div className="ptree__menu-title" title={menu.name}>
              {menu.name}
            </div>
            {/* 触屏没有 Ctrl/Shift 可依附 —— 「多选」是移动端进入多选态的唯一显式入口 */}
            <button
              type="button"
              role="menuitem"
              data-ptree-menu-item="select"
              onClick={() => {
                const id = menu.id;
                closeMenu();
                setSelectMode(true);
                setAnchorId(id);
                setSelection((prev) => {
                  const next = new Set(prev);
                  next.add(id);
                  return next;
                });
              }}
            >
              多选
            </button>
            <button type="button" role="menuitem" data-ptree-menu-item="pick" onClick={startPickParent}>
              移入子分类…
            </button>
            <button type="button" role="menuitem" data-ptree-menu-item="up" onClick={() => moveByStep(-1)}>
              上移
            </button>
            <button type="button" role="menuitem" data-ptree-menu-item="down" onClick={() => moveByStep(1)}>
              下移
            </button>
            <button type="button" role="menuitem" data-ptree-menu-item="root" onClick={moveToRoot}>
              移到顶级
            </button>
            <button type="button" role="menuitem" className="ptree__menu-cancel" onClick={closeMenu}>
              取消
            </button>
          </div>
        </>
      )}
    </div>
  );
}
