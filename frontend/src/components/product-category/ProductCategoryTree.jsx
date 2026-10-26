/**
 * ProductCategoryTree —— 商品档案左侧的类别树（**带拖拽**）
 *
 * 职责边界（刻意的）：
 *   · 这个组件**只负责显示 + 交互**，不持有"选了哪个类别"这个业务状态。
 *     选中项由外部传入（`value`）并通过 `onChange` 回调出去 ——
 *     因为右侧商品列表的过滤发生在 App.jsx 里（`filteredProducts`），
 *     状态放在组件内部它就拿不到了。
 *   · 折叠/展开是纯展示状态，跟业务无关，所以留在组件内部（`collapsed`）。
 *   · 拖着走的**过程**（浮标、落点高亮）也留在这里；落地的**结果**（改分层、发请求、
 *     数据从哪来）一律交给 `onMove` —— 组件不知道接口长什么样。
 *
 * 交互约定：
 *   点整行     → 选中该类别；再点一次取消选中（回到「全部商品」）
 *   点小三角   → 折叠 / 展开（stopPropagation，不影响选中）
 *   点 +子类/改/删 → 各自回调出去，同样不影响选中
 *   按下手柄拖 → 改变层级 / 同级顺序（拖到行上三分之一 = 插在上面，
 *                下三分之一 = 插在下面，中间 = 变成它的子类）
 *
 * ---------------------------------------------------------------------------
 * 拖拽为什么复用 `partner-tree` 那套，而不是再写一套（2026-10-20）
 *
 *   客户/供应商分类树的拖拽已经踩完了全部坑，逐条都有注释可查：
 *     · 触屏不派发 HTML5 `dragstart` → 根本不能用原生 DnD（`usePartnerDrag` 改 Pointer Events）
 *     · 「长按拖」和「手指滚树」在 `touch-action` 上物理冲突 → 触屏只能从手柄起手
 *     · 命中测试必须用"拖动开始时缓存的 rect + 滚动增量"，`elementFromPoint` 会命中 ghost 自己
 *     · 松手后浏览器会在起手行补一个 click → 不吞掉就会"拖完顺手把这一行选中了"
 *   所以这里直接 import 那两件现成资产，**不复制粘贴**：
 *     `usePartnerDrag`（手势引擎）、`lib/partnerTree`（落点解析 / 防环 / 乐观重排，有单测）。
 *   带来的结果是这三行 class 与客户树同名（`is-drop-before` 等），样式表里已有现成规则可直接用。
 *
 *   ⚠️ 为什么没做成"通用 Tree 组件"给三处共用：
 *      客户树有搜索、多选、批量移动、内联重命名、操作菜单（1390 行），商品树只有 4 个按钮。
 *      硬抽公共壳子，要么把所有能力都塞进参数表，要么两边各写一堆开关 —— 那才是维护灾难。
 *      共用的部分（手势 + 落点算法）已经抽出来了，**界面与业务各自持有**才是对的边界。
 *
 * 与客户树的**实质差异**（不要照抄对方的规则）：
 *   · 商品的 `category` 是**名称字符串**，不是 category_id → 同一父级下不能重名，
 *     移动分类不用（也不能）去改任何商品的字段。
 *   · 商品树的缩进是 `depth * 14`，客户树是 `indentOf(depth)`（8 + 14n）——
 *     两者差 8px 的起始留白，这里保持页面原样，不动右表布局。
 *
 * 样式在 `src/styles.css` 的「商品档案 · 左侧类别树交互」一节（类名前缀 .cat-）；
 * 拖拽态的类名与 `.ptree` 共用（`is-drop-before` / `is-drop-inside` /
 * `is-drop-after` / `is-dragging-source` / `is-drop-forbidden`），
 * 但**样式是 `.cat-` 自己的一套**，写在 styles.css 里，不 import 客户树的 css。
 *
 * 依赖：React、`../../lib/partnerTree`、`../partner-tree/usePartnerDrag`。无第三方库。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { UNCATEGORIZED, categoryIdOf, categoryNameOf } from '../../lib/productCategory';
import { ancestorsOf, indexTree } from '../../lib/partnerTree';
import { isLatinQuery, pinyinInitials } from '../../lib/pinyinInitials';
import { ALL } from '../../lib/treeSelection';
import { usePartnerDrag } from '../partner-tree/usePartnerDrag';

/** 所有"有子类"的 id —— 默认全部折叠，只露出一级类别 */
function groupIds(nodes, out = []) {
  (nodes || []).forEach((node) => {
    if ((node.children || []).length > 0) {
      out.push(node.id);
      groupIds(node.children, out);
    }
  });
  return out;
}

/**
 * 拖动期间必须把**路径上所有父级**展开。
 *
 * 为什么不做成"松手后自动展开"：拖拽的落点高亮依赖"这一行在屏幕上算出的 rect"，
 * 父级如果收着，子树根本没渲染 —— 悬停到收起的父级上只能落到父级本身，
 * 用户永远拖不进一个折叠起来的分支。松手前就摊开才是对的。
 */
function ancestorsOfId(nodes, targetId, chain = []) {
  for (const node of nodes || []) {
    if (node.id === targetId) return chain;
    const hit = ancestorsOfId(node.children || [], targetId, [...chain, node.id]);
    if (hit) return hit;
  }
  return null;
}

/**
 * 去掉指定父级下名字重复的节点。
 *
 * 为什么需要它：商品档案挂的是**名称字符串**（`products.category`），同一父级下重名
 * 会让"这个商品属于哪个类"出现歧义 —— 后端 `/move` 因此会返回 400 拒绝移动。
 * 但如果库里**已经**存在历史遗留的两条同名类，那这一支整片都拖不动了。
 * 这里做一层防御：重名的后来者只渲染、不参与拖拽（没有手柄），其余的照常拖。
 * 正常数据（后端一直拦着重名）走不到这个分支。
 */
function duplicateIds(nodes, out = new Set()) {
  const walk = (list) => {
    const seen = new Set();
    (list || []).forEach((node) => {
      const key = String(node.name || '').trim();
      if (seen.has(key)) out.add(node.id);
      else seen.add(key);
      walk(node.children);
    });
  };
  walk(nodes);
  return out;
}

const DRAG_TIP = '拖到行上/下沿 = 换顺序，拖到行中间 = 变成它的子类';

/**
 * @param {object}   props
 * @param {Array}    props.nodes           类别树（GET /api/v1/product-categories 的返回）
 * @param {number|string|null} props.value 当前选中：null=全部 / UNCATEGORIZED=未分类 / 数字 id
 * @param {(key)=>void} props.onChange     选中项变化
 * @param {{byId: Map, uncategorized: number, all: number}} props.counts 各类别商品数
 * @param {string}   props.busy            正在删的类别标记（`cat-del-<id>`），用于禁用按钮
 * @param {(node)=>void} props.onAddChild  点「+子类」
 * @param {(node)=>void} props.onEdit      点「改」
 * @param {(node)=>void} props.onDelete    点「删」
 * @param {(dragId:number, move:{parentId:number|null, beforeId:number|null})=>Promise<boolean>} [props.onMove]
 *        拖拽落地。返回 `true` = 外部已改好数据（组件不动）；
 *        返回 `false`/抛错 = 组件按 `nodes` 重新渲染（因为 `nodes` 源头没变，等于自动回滚）。
 *        不传 = 只读树，一个抓手都不渲染。
 */
export default function ProductCategoryTree({
  nodes = [],
  value = null,
  onChange,
  counts,
  busy = '',
  onAddChild,
  onEdit,
  onDelete,
  onMove,
  /* ── 搜索（2026-10-23）：分类名 + 商品名双向匹配 ─────────────────────────
   * 只传 `counts` 是不够的：它只有数字，没有商品名字。要"搜商品名能定位到分类"，
   * 必须把商品行本身传进来（App 里就是 `products`，与右侧列表同一份数据）。 */
  products = [],
  /* ── 拖拽归档（2026-10-21）：与客户/供应商树同一套交互 ──────────────────
   * `productDropEnabled` 打开后，每个分类行都能接住右侧表格拖来的商品行；
   * `onProductDrop(node)` 把目标节点交回页面（商品分类存的是**名称**，页面要用 node.name）。
   * `revealSignal = { id, at }`：拖完后展开祖先 + 滚到 + 闪一下，`at` 变一次触发一次。
   */
  productDropEnabled = false,
  onProductDrop,
  revealSignal = null,
}) {
  // 折叠起来的类别 id（纯展示状态）。
  // 2026-10-19：初始**全部折叠**（只露出一级类别）—— 原来 `[]` 等于全摊开，
  // 一进页面就是几十行，用户不知道该点哪儿。数据异步到，故配一个 seed 效果。
  const [collapsed, setCollapsed] = useState(() => groupIds(nodes));
  const seeded = useRef((nodes || []).length > 0);

  useEffect(() => {
    if (seeded.current || !(nodes || []).length) return;
    seeded.current = true;
    setCollapsed(groupIds(nodes));
  }, [nodes]);

  const bodyRef = useRef(null);
  const ghostRef = useRef(null);

  // 节点索引：落点解析（防环）与"这条支在不在"都靠它。数据没变就不重算。
  const index = useMemo(() => indexTree(nodes), [nodes]);

  /* ── 搜索：分类名 + 商品名双向匹配（2026-10-23）────────────────────────────
   * 用户口径（与客户树一致）：
   *   ① 输入即匹配分类名，也匹配分类下的商品名/SKU；
   *   ② 命中节点的**祖先链自动展开**（不写进 collapsed，清空即还原）；
   *   ③ 没命中的分支整支不渲染（不留空壳文件夹）；
   *   ④ 清空搜索 → 恢复默认全折叠。
   * 商品的归类有两种历史形态：`category_id`（新）与 `category` 名称（老），
   * 两种都要认，否则老商品搜不出来。 */
  const [query, setQuery] = useState('');
  const needle = query.trim().toLowerCase();

  const searchHit = useMemo(() => {
    if (!needle) return null;
    const byId = index.byId;
    const nameToIds = new Map();
    byId.forEach((node) => {
      const name = String(node.name || '').trim();
      if (!nameToIds.has(name)) nameToIds.set(name, []);
      nameToIds.get(name).push(node.id);
    });

    const productHits = new Map(); // 分类 id → 命中的商品行
    // 拼音首字母（2026-10-23）：zgp → 周广平；纯拉丁关键词才走拼音通道
    const latin = isLatinQuery(needle);
    (products || []).forEach((row) => {
      const haystack = [row.name, row.sku, row.spec, row.category]
        .filter((value) => value !== null && value !== undefined && value !== '')
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(needle) && !(latin && pinyinInitials(haystack).includes(needle))) return;
      const targets = new Set();
      const id = categoryIdOf(row);
      if (id !== null && byId.has(id)) targets.add(id);
      const name = categoryNameOf(row);
      (nameToIds.get(name) || []).forEach((nodeId) => targets.add(nodeId));
      targets.forEach((nodeId) => {
        if (!productHits.has(nodeId)) productHits.set(nodeId, []);
        productHits.get(nodeId).push(row);
      });
    });

    const nameHit = new Set();
    byId.forEach((node, id) => {
      const nameL = String(node.name || '').toLowerCase();
      if (nameL.includes(needle) || (latin && pinyinInitials(nameL).includes(needle))) {
        nameHit.add(id);
      }
    });

    const matched = new Set([...nameHit, ...productHits.keys()]);
    // 可见集合 = 命中节点 + 它们的祖先（祖先要露出来，用户才知道它在哪一支下面）
    const visible = new Set();
    matched.forEach((id) => {
      visible.add(id);
      (ancestorsOf(index, id) || []).forEach((ancestor) => visible.add(ancestor));
    });
    return { nameHit, productHits, visible, matched };
  }, [needle, index, products]);

  const searching = Boolean(needle);
  const clearSearch = () => {
    setQuery('');
    // 用户口径：清空 = 回到默认全折叠（只露一级分类）
    setCollapsed(groupIds(nodes));
  };

  /* ── 拖拽落点高亮 + "给我看这个节点" ─────────────────────────────────── */
  const [dropHover, setDropHover] = useState(null);
  const [flashId, setFlashId] = useState(null);
  const flashTimer = useRef(null);
  const revealTimer = useRef(null);
  const revealHandled = useRef(null);
  useEffect(
    () => () => {
      clearTimeout(flashTimer.current);
      clearTimeout(revealTimer.current);
    },
    [],
  );

  const isProductDrag = (event) => {
    const types = event && event.dataTransfer ? Array.from(event.dataTransfer.types || []) : [];
    return types.includes('application/x-erp-products');
  };

  const dropProps = (node) => {
    if (!productDropEnabled) return {};
    return {
      onDragOver: (event) => {
        if (!isProductDrag(event)) return;
        // 不 preventDefault 就不允许放下 —— 这是"我能接"的唯一声明
        event.preventDefault();
        event.stopPropagation();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        setDropHover((cur) => (cur === node.id ? cur : node.id));
      },
      onDragLeave: (event) => {
        if (!isProductDrag(event)) return;
        if (event.currentTarget && event.currentTarget.contains(event.relatedTarget)) return;
        setDropHover((cur) => (cur === node.id ? null : cur));
      },
      onDrop: (event) => {
        if (!isProductDrag(event)) return;
        event.preventDefault();
        event.stopPropagation();
        setDropHover(null);
        if (onProductDrop) onProductDrop(node);
      },
    };
  };

  // 揭示：展开祖先 → 等行出现（轮询，最多 1.2s）→ 滚到 + 闪
  useEffect(() => {
    if (!revealSignal || !revealSignal.id) return;
    if (revealHandled.current === revealSignal.at) return;
    revealHandled.current = revealSignal.at;
    const targetId = revealSignal.id;
    if (index.byId && index.byId.has(targetId)) {
      const chain = ancestorsOf(index, targetId);
      if (chain.length) {
        // 折叠表里"去掉祖先" = 展开它们
        setCollapsed((prev) => prev.filter((id) => !chain.includes(id)));
      }
    }
    let tries = 0;
    clearTimeout(revealTimer.current);
    const tick = () => {
      const el = document.querySelector(`.cat-node[data-node-id="${targetId}"]`);
      if (el) {
        if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        setFlashId(targetId);
        clearTimeout(flashTimer.current);
        flashTimer.current = setTimeout(() => setFlashId(null), 900);
        return;
      }
      tries += 1;
      if (tries < 24) revealTimer.current = setTimeout(tick, 50);
    };
    revealTimer.current = setTimeout(tick, 30);
  }, [revealSignal, index]);

  /** 兜底：选中的分类若被折叠在深处，自动展开祖先（拖拽以外的入口也能露出来） */
  useEffect(() => {
    if (value === null || value === undefined || value === ALL || value === UNCATEGORIZED) return;
    if (!index.byId || !index.byId.has(value)) return;
    const hidden = ancestorsOf(index, value).filter((id) => collapsed.includes(id));
    if (!hidden.length) return;
    setCollapsed((prev) => prev.filter((id) => !hidden.includes(id)));
  }, [value, index, collapsed]);
  const dupIds = useMemo(() => duplicateIds(nodes), [nodes]);
  const canDrag = typeof onMove === 'function';

  // 拖动期间临时展开的父级链（松手就丢，不写进 `collapsed`）
  const [revealed, setRevealed] = useState([]);

  const drag = usePartnerDrag({
    index,
    bodyRef,
    ghostRef,
    onMove: (dragId, move) => {
      // 落到 before/after 时 `parentId` 可能是被挂到某个父级下 —— 提前把目标父级展开，
      // 让节点落进"看得见的"位置，而不是掉进一个收起来的分支里。
      if (move && move.parentId !== null && move.parentId !== undefined) {
        setRevealed((prev) => (prev.includes(move.parentId) ? prev : [...prev, move.parentId]));
      }
      return onMove(dragId, move);
    },
    onBegin: (dragId) => {
      // 被拖的那条路径全摊开：否则拖不进折叠着的分支，也看不见自己会落到哪
      const chain = ancestorsOfId(nodes, dragId);
      if (chain && chain.length) setRevealed(chain);
    },
    onFinish: () => setRevealed([]),
  });

  const shownPreview = drag.preview;

  const byId = counts?.byId || new Map();
  const totalCount = counts?.all ?? 0;
  const uncategorizedCount = counts?.uncategorized ?? 0;

  // 生效的折叠态 = 用户自己的折叠 − 拖动期间强制展开的
  const isCollapsedOf = (id) => collapsed.includes(id) && !revealed.includes(id);

  const toggleCollapse = (id) =>
    setCollapsed((prev) => {
      // ⚠️ `collapsed` 是"折叠名单"，所以 **在名单里 = 当前是折叠的 = 这次要展开**。
      // 第一版把这个分支当成"收起"，手风琴写进了 else —— 结果点开兄弟时谁也不折叠。
      if (prev.includes(id)) {
        // 展开：把自己从折叠名单删掉，再把同父级的其它节点加进去（手风琴）
        const parentId = index.parentOf ? index.parentOf.get(id) : null;
        const siblings = (index.childrenOf ? index.childrenOf.get(parentId) : null) || [];
        const next = prev.filter((x) => Number(x) !== Number(id));
        siblings.forEach((sid) => {
          if (Number(sid) !== Number(id) && !next.some((x) => Number(x) === Number(sid))) {
            next.push(sid);
          }
        });
        return next;
      }
      return [...prev, id]; // 收起
    });

  // 点行 = 选中；**再点同一行 = 回到「全部商品」**（不是"什么都不选"，
  // 那样右表会突然全空，看着像数据丢了）。
  // 顶端两行不参与"取消"：「全部商品」本身就是 ALL；「未分类」点第二次也只是回到全部。
  const select = (key, toggleOff) => {
    if (!onChange) return;
    onChange(toggleOff && key === value ? ALL : key);
  };

  // 「点行 = 选中」那套热区属性，树节点和顶端两行共用。
  // ⚠️ `onClick` 第一件事必须是"这次点击要不要吞掉"：
  //    松手时浏览器会**在起手那一行上补一个 click**（拖拽也一样，Puppeteer 的真实
  //    鼠标事件序列实测会走到这里），不吞就会"拖完顺手把这一行选中了"。
  //    客户树是这么写的，商品树一开始漏了这行 —— E2E 第一轮 E1 直接红。
  const rowProps = (key, active, toggleOff) => ({
    className: `cat-node${active ? ' is-active' : ''}`,
    role: 'button',
    tabIndex: 0,
    onClick: () => {
      if (drag.isClickSuppressed()) return;
      select(key, toggleOff);
    },
    onKeyDown: (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        select(key, toggleOff);
      }
    },
  });

  /** 落点高亮的三个 class（与客户树同名，样式在 styles.css 里另写一套 .cat- ） */
  const dropClassOf = (id) => {
    if (!shownPreview || shownPreview.targetId !== id) return '';
    if (shownPreview.kind === 'forbidden') return ' is-drop-forbidden';
    return ` is-drop-${shownPreview.kind}`;
  };

  // 递归渲染。层数不限 —— 类别树本身就是无限级的。
  // ⚠️ 外层必须套一层普通 div 再放 .cat-node：.cat-node 自己是 flex 行，
  //    把子行直接塞进去会被 flex 排成横排（原来就是这么写的，只是因为树一直是扁的没暴露）。
  const renderNodes = (list, depth) =>
    (list || [])
      // 搜索态：整支不在 `visible` 里的分类直接不渲染（不留空壳文件夹）
      .filter((node) => !searchHit || searchHit.visible.has(node.id))
      .map((node) => {
      const hasChildren = (node.children || []).length > 0;
      // 搜索态一律展开：命中的分类如果收着，命中它的商品名就"看得见分类、看不见为什么"
      const isCollapsed = searchHit ? false : isCollapsedOf(node.id);
      const active = value === node.id;
      const draggable = canDrag && !dupIds.has(node.id);
      const nameHit = Boolean(searchHit && searchHit.nameHit.has(node.id));
      const productHitCount = searchHit && searchHit.productHits.get(node.id)
        ? searchHit.productHits.get(node.id).length
        : 0;
      const hit = nameHit || productHitCount > 0;
      return (
        <div key={node.id}>
          <div
            {...rowProps(node.id, active, true)}
            className={`cat-node${active ? ' is-active' : ''}`
              + (hit ? ' is-hit' : '')
              + (drag.dragId === node.id ? ' is-dragging-source' : '')
              + (dropHover === node.id ? ' is-product-drop' : '')
              + (flashId === node.id ? ' is-flash' : '')
              + dropClassOf(node.id)}
            {...dropProps(node)}
            data-node-id={node.id}
            data-depth={depth}
            // 整行按住 → 鼠标移动 4px 才开始拖（否则仍是一次点击）；
            // 触屏行体留给"滚树"，只能从手柄起手（见 usePartnerDrag 顶部注释）
            onPointerDown={(event) => {
              if (!draggable) return;
              drag.rowPointerDown(event, { id: node.id, node });
            }}
            style={{ paddingLeft: depth * 14 }}
          >
            {hasChildren ? (
              <span
                className={`cat-caret${isCollapsed ? ' is-collapsed' : ''}`}
                title={isCollapsed ? '展开' : '折叠'}
                onClick={(event) => {
                  event.stopPropagation();
                  toggleCollapse(node.id);
                }}
              >
                {/* 手写 SVG 小三角：展开朝下，折叠时 CSS 转 -90° 朝右 */}
                <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                  <path
                    d="M1 2.5 L4 6 L7 2.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
            ) : (
              <span className="cat-caret leaf" aria-hidden="true">
                ·
              </span>
            )}
            <span className="cat-name" title={node.name}>
              {nameHit ? highlightText(node.name, query) : node.name}
              {productHitCount ? (
                <em className="cat-hit-note" title="这个分类下有商品名匹配">
                  {productHitCount} 个商品命中
                </em>
              ) : null}
            </span>
            <span className="cat-count">{byId.get(node.id) || 0}</span>
            <span className="cat-actions">
              <button
                type="button"
                className="link-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  if (onAddChild) onAddChild(node);
                }}
              >
                +子类
              </button>
              <button
                type="button"
                className="link-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  if (onEdit) onEdit(node);
                }}
              >
                改
              </button>
              <button
                type="button"
                className="link-btn danger"
                disabled={busy === `cat-del-${node.id}`}
                onClick={(event) => {
                  event.stopPropagation();
                  if (onDelete) onDelete(node);
                }}
              >
                删
              </button>
            </span>
            {draggable && (
              <span
                className="cat-grip"
                role="button"
                tabIndex={-1}
                aria-label={`拖动「${node.name}」调整层级或顺序`}
                title="拖动调整层级 / 顺序"
                data-cat-grip="1"
                // 手柄是触屏唯一的拖拽入口：`touch-action:none` 让浏览器别把手势判成滚屏
                onPointerDown={(event) => {
                  drag.handlePointerDown(event, { id: node.id, node });
                }}
              >
                <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden="true">
                  <circle cx="3" cy="2.5" r="1" /><circle cx="7" cy="2.5" r="1" />
                  <circle cx="3" cy="6" r="1" /><circle cx="7" cy="6" r="1" />
                  <circle cx="3" cy="9.5" r="1" /><circle cx="7" cy="9.5" r="1" />
                </svg>
              </span>
            )}
          </div>
          {hasChildren && !isCollapsed && renderNodes(node.children, depth + 1)}
        </div>
      );
    });

  return (
    <>
      {/* ── 搜索框（2026-10-23）──
          与客户/供应商树同一套语义：分类名 + 商品名双向匹配、命中自动展开祖先、清空恢复折叠。
          放在树体**外面**：树体是拖拽的命中容器（bodyRef 要量行 rect），
          塞进去会让"拖到底部空白处 = 移到顶级"多出一块假区域。 */}
      <div className="cat-search">
        <input
          type="search"
          className="cat-search-input"
          value={query}
          data-cat-search="1"
          placeholder="搜索分类 / 商品名称 / SKU…"
          aria-label="搜索商品分类或商品"
          onChange={(event) => {
            const next = event.target.value;
            if (!next.trim()) {
              clearSearch();
              return;
            }
            setQuery(next);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              clearSearch();
            }
          }}
        />
        {query ? (
          <button
            type="button"
            className="cat-search-clear"
            title="清空搜索（Esc）"
            aria-label="清空搜索"
            data-cat-search-clear="1"
            onClick={clearSearch}
          >
            ×
          </button>
        ) : null}
      </div>
      {searching ? (
        <div className="cat-search-hits" data-cat-hits={searchHit ? searchHit.matched.size : 0}>
          {searchHit && searchHit.matched.size ? (
            <span>
              找到 <strong>{searchHit.matched.size}</strong> 个分类
              {(() => {
                let total = 0;
                searchHit.productHits.forEach((rows) => {
                  total += rows.length;
                });
                return total ? `（含 ${total} 个商品命中）` : '';
              })()}
            </span>
          ) : (
            <span>没有匹配的分类或商品</span>
          )}
        </div>
      ) : null}

      {/* 树体挂 ref：`usePartnerDrag` 用它量所有行的 rect（命中测试靠这个）。 */}
      <div className={`category-tree-body${drag.dragId !== null ? ' is-dragging' : ''}`} ref={bodyRef}>
        {/* 顶端固定两行。「未分类」是真实需求：实测库里 261 个商品有 16 个 category 是空的，
            没有这一行它们永远露不出来。
            ⚠️ 这两行**不参与拖拽**（它们不是树里的节点，没有 parent_id 可改）。 */}
        <div className="cat-root-group">
          {[
            { key: ALL, label: '全部商品', count: totalCount },
            { key: UNCATEGORIZED, label: '未分类', count: uncategorizedCount },
          ].map((row) => (
            <div key={row.label} {...rowProps(row.key, value === row.key, false)} style={{ paddingLeft: 0 }}>
              <span className="cat-caret leaf" aria-hidden="true">
                ·
              </span>
              <span className="cat-name">{row.label}</span>
              <span className="cat-count">{row.count}</span>
            </div>
          ))}
        </div>

        {nodes.length === 0 ? (
          <div className="empty-state">暂无类别，点「+ 新增顶级」建立分类</div>
        ) : searching && (!searchHit || searchHit.matched.size === 0) ? (
          <div className="empty-state" data-cat-empty="1">
            没有匹配的分类或商品，换个关键词试试
          </div>
        ) : (
          renderNodes(nodes, 0)
        )}

        {/* 拖到底部空白处 = 移到顶级。
            命中判定不靠这个元素的 rect（它是拖动中才挂载的，量不到稳定位置），
            而是"最后一行下方 / 容器底部上方"这段区域，见 usePartnerDrag.hitTest */}
        {drag.dragId !== null && (
          <div className={`cat-rootdrop${drag.rootOver ? ' is-over' : ''}`} data-cat-rootdrop="1">
            拖到这里 → 移到顶级
          </div>
        )}

        {drag.dragId !== null && <div className="cat-dragtip">{DRAG_TIP}</div>}
      </div>

      {/* 拖动中的浮标：跟手的小标签。
          为什么必须有：手指会遮住落点，触屏上没有"禁止"光标这类提示，
          用户只能靠浮标 + 行高亮确认"松手会发生什么"。 */}
      {drag.dragId !== null && (
        <div className="cat-ghost" ref={ghostRef} data-cat-ghost="1" aria-hidden="true">
          <span className="cat-ghost-name">{describeGhostNode(nodes, drag.dragId)}</span>
          <span className="cat-ghost-hint">
            {drag.rootOver
              ? '移到顶级'
              : shownPreview && shownPreview.kind === 'forbidden'
                ? '不能放到这里'
                : shownPreview && shownPreview.kind === 'inside'
                  ? `移入「${describeGhostNode(nodes, shownPreview.targetId)}」`
                  : shownPreview && shownPreview.kind === 'before'
                    ? '插到这一行前面'
                    : shownPreview && shownPreview.kind === 'after'
                      ? '插到这一行后面'
                      : '拖动中…'}
          </span>
        </div>
      )}
    </>
  );
}

/** 把命中片段包成 <mark>。不用正则 —— 关键词里可能有 `.` `(` 这些元字符。
 *  与客户树 `renderHighlighted` 同一套观感（那边是 JSX 版本，商品树这边只有分类名要标）。 */
function highlightText(text, term) {
  const value = String(text === null || text === undefined ? '' : text);
  const needle = String(term || '').trim();
  if (!needle) return value;
  const haystack = value.toLowerCase();
  const target = needle.toLowerCase();
  const parts = [];
  let cursor = 0;
  let guard = 0;
  while (guard < 50) {
    guard += 1;
    const found = haystack.indexOf(target, cursor);
    if (found < 0) break;
    if (found > cursor) parts.push(value.slice(cursor, found));
    parts.push(
      <mark className="cat-mark" key={`m${found}`}>
        {value.slice(found, found + target.length)}
      </mark>,
    );
    cursor = found + target.length;
  }
  if (cursor < value.length) parts.push(value.slice(cursor));
  return parts.length ? parts : value;
}

/** 浮标上显示节点名（找不到就空串，绝不抛错 —— 它每次 render 都在调） */
function describeGhostNode(nodes, id) {
  if (id === null || id === undefined) return '';
  for (const node of nodes || []) {
    if (node.id === id) return node.name || '';
    const hit = describeGhostNode(node.children || [], id);
    if (hit) return hit;
  }
  return '';
}
