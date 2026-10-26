/**
 * PartnersBoard —— 客户档案 / 供应商档案整页 UI（一套代码，两个 kind）
 *
 * 改造前：`pages/CustomersPage.jsx` 与 `pages/SuppliersPage.jsx` 各 1035 行，
 * 里面是同一张 `<table className="data-table">` + 手写 `<th>/<td>` + 手写空态，
 * 而且**只有一栏**（`gridColumn: '1 / -1'`），左边空着。
 * 现在：ResizableLayout + ErpCard(分组树) + ErpCard(列表 + ErpTable)。
 *
 * 角色：`customer`（客户档案）/ `supplier`（供应商档案）两页共用，`kind` 决定文案与列。
 * 布局：`ResizableLayout` = ErpCard(左侧视图) + ErpCard(列表 + ErpTable)。
 *
 * 左侧**两棵树**（`treeMode` 切换，各自记住自己的过滤状态）：
 *   · `category`（默认）真实分类树 —— `components/partner-tree/PartnerTree.jsx`，
 *     背后是 `customer_categories` / `supplier_categories` 物理表，无限极、可跨级拖拽、
 *     可搜索定位。拖完节点，右侧表格的「分类」列会跟着变（两者都从同一棵树上派生）。
 *   · `group` 原「按级别 / 业务员 / 首字母」视图树 —— `components/ui/ErpTree.jsx`,
 *     数据由 `lib/partnerGroup.js` 现场算。业务上确实有人按业务员点货，保留成辅助视图。
 *
 * 职责边界（刻意的）：
 *   · 只吃 9 个 props，**不 import App.jsx、不读 `ctx`**。删除/编辑用的 endpoint
 *     与副作用由页面薄壳拼好再传进来（`onDelete(row)` / `onEdit(row)`），
 *     这里不认识 `/customers/{id}`，也不发请求（分类树的请求封装在
 *     `partner-tree/usePartnerCategories.js` 里，token 从 localStorage 取）。
 *   · 「按业务员分组」的数据怎么来在 `lib/partnerGroup.js`（纯函数，13 条单测）；
 *     「真实分类树」的层级/拖拽/搜索逻辑在 `lib/partnerTree.js`（纯函数，27 条单测）。
 *
 * 为什么客户按「级别 / 业务员」、供应商按「名称首字母」分组：
 *   三套账真实数据决定的（2026-10-17 实测）——
 *   客户 25 条：level 有 零售价1×21 / 零售价2 / 零售价3，businesser 有 范先生×20；
 *   供应商 61 条：没有级别也没有业务员字段，但 `short_name` 61/61 都是拼音首字母串
 *   （`szskgdzyxgs` → S），按首字母分组才有意义。
 *   硬给供应商编一个"地区/类别"的树，就是造一棵假树。
 */

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
// Excel 引擎（~860 KB）改为按需加载：导出档案的那一刻才下载（B4b，2026-10-27）。
// 与 App.jsx 共用 lib/lazyLibs.js 的同一份缓存，先导过的再导不会重复下载。
import { loadXLSX } from '../../lib/lazyLibs';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import PartnerTree from '../partner-tree/PartnerTree.jsx';
import { usePartnerCategories } from '../partner-tree/usePartnerCategories.js';
import ArchiveImportDialog from '../dataio/ArchiveImportDialog.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import ErpTree from '../ui/ErpTree.jsx';
import ExportColumnsDialog from './ExportColumnsDialog.jsx';
import { buildPartnerTree, filterPartnersByGroup, partnerGroupLabel } from '../../lib/partnerGroup.js';
import {
  buildPartnerSheet,
  partnerColumns,
  partnerDefaultKeys,
  partnerExportFileName,
} from '../../lib/partnerExport.js';
import { UNCLASSIFIED, subtreeIds } from '../../lib/partnerTree.js';
import { ALL, isAll, isPicked, pickPrompt } from '../../lib/treeSelection.js';
import { pruneSelection } from '../../lib/selection.js';
import './partners.css';

/**
 * 客户文件抽屉按需加载。
 *
 * 它只有客户页的「📁 文件」按下去才需要，却带着自己的 CSS（约 8KB）——
 * 挂到主包里就是让每个打开首页的人都下载这段永远用不到的样式。
 * 与 `pages/MenusPage.jsx` 里 `MenuTreeEditor` 的做法一致：`lazy` + `Suspense fallback={null}`。
 */
const CustomerFilesDrawer = lazy(() => import('./CustomerFilesDrawer.jsx'));

/**
 * 拖拽归档（2026-10-21）：客户 + 供应商都已开放。
 *
 * 用户口径：客户先试点、手感 OK 后推给供应商和商品 —— 现在三类档案都有。
 * 商品档案的 category 是**名称字符串**不是外键，走的是另一套
 * `/products/batch-category`（实现在 ProductsBoard + ProductCategoryTree），
 * 不能照抄本文件的 category_id 逻辑。
 */
const PARTNER_DND_KINDS = new Set(['customer', 'supplier']);

const CONFIG = {
  customer: {
    tab: 'customers',
    noun: '客户',
    unit: '位',
    allLabel: '全部客户',
    treeTitle: '客户分组',
    listTitle: '客户列表',
    searchPlaceholder: '搜索 编码 / 名称 / 电话 / 邮箱…',
    addLabel: '新增客户',
    storageKey: 'erp:mgrid:customers',
    emptyTitle: '还没有客户档案',
    emptyDescription: '客户档案是销售开单与应收对账的基础，先建一条试试。',
    emptySearchTitle: '没有匹配的客户',
    columns: [
      { key: 'code', title: '编码', mono: true, width: 140 },
      { key: 'name', title: '名称', ellipsis: true, minWidth: 190 },
      { key: 'level', title: '级别', fallback: '未分级', hideBelow: 'sm', minWidth: 88 },
      { key: 'businesser', title: '业务员', fallback: '未指派', hideBelow: 'md', minWidth: 84 },
      { key: 'phone', title: '电话', mono: true, nowrap: true, hideBelow: 'md', minWidth: 120 },
      { key: 'email', title: '邮箱', ellipsis: true, hideBelow: 'md', minWidth: 150 },
    ],
  },
  supplier: {
    tab: 'suppliers',
    noun: '供应商',
    unit: '家',
    allLabel: '全部供应商',
    treeTitle: '供应商分组',
    listTitle: '供应商列表',
    searchPlaceholder: '搜索 编码 / 名称 / 电话 / 邮箱…',
    addLabel: '新增供应商',
    storageKey: 'erp:mgrid:suppliers',
    emptyTitle: '还没有供应商档案',
    emptyDescription: '供应商档案是采购开单与应付对账的基础，先建一条试试。',
    emptySearchTitle: '没有匹配的供应商',
    columns: [
      { key: 'code', title: '编码', mono: true, width: 140 },
      { key: 'name', title: '名称', ellipsis: true, minWidth: 220 },
      // 税号（2026-10-22）：进项票"税号优先"匹配的依据，列表里必须能一眼看出谁还没登记
      { key: 'tax_no', title: '纳税人识别号', mono: true, ellipsis: true, hideBelow: 'md', minWidth: 170, fallback: '未登记' },
      { key: 'short_name', title: '简称', mono: true, ellipsis: true, hideBelow: 'sm', minWidth: 120 },
      { key: 'contact', title: '联系人', fallback: '—', hideBelow: 'md', minWidth: 84 },
      { key: 'mobile', title: '手机', mono: true, nowrap: true, hideBelow: 'md', minWidth: 120 },
    ],
  },
};

/** 与 App.jsx 里 filteredCustomers / filteredSuppliers 完全相同的检索口径 */
function matchSearch(row, q) {
  if (!q) return true;
  return [row.code, row.name, row.phone, row.email].some(
    (value) => value !== null && value !== undefined && String(value).toLowerCase().includes(q),
  );
}

export default function PartnersBoard({
  kind = 'customer',
  rows = [],
  search = '',
  onSearch,
  focus = null,
  onClearFocus,
  onAdd,
  onEdit,
  onDelete,
  onBatchDelete,
  onImported,
  /**
   * 拖拽归档落库：(ids, categoryId|null) => Promise<{moved, category_name}|null>
   *
   * 由页面薄壳注入（`ctx.movePartnersToCategory`）—— 本组件刻意**不发请求**，
   * 它连 `/customers/{id}` 都不认识（见文件头「职责边界」）。不传则拖拽整体关闭。
   */
  onMoveToCategory,
  onPatchPartner,
}) {
  const config = CONFIG[kind] || CONFIG.customer;
  const [group, setGroup] = useState(null);
  // 导出选列弹窗 / 导入弹窗（2026-10-20 内嵌到档案页；2026-10-21 恢复）
  const [exportOpen, setExportOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  // —— 拖拽归档（客户档案试点）——
  const dndEnabled = PARTNER_DND_KINDS.has(kind) && typeof onMoveToCategory === 'function';

  // 拖动中的 id 列表用 ref：dragstart 里写、drop 里读，中间不触发重渲染
  const dragIdsRef = useRef([]);
  const [dragging, setDragging] = useState(false);
  /** 拖完要让左侧树"展开祖先 + 滚到 + 闪一下"的目标（见 PartnerTree.revealSignal） */
  const [revealSignal, setRevealSignal] = useState(null);
  // 文件抽屉的目标客户（null = 关着）。只给客户页用：供应商没有归档接口。
  const [filesFor, setFilesFor] = useState(null);

  /**
   * 左侧栏两棵树，切换用（`treeMode`）：
   *   'category' → 真实分类树（`customer_categories` 表，无限极、可拖拽、可搜索）
   *   'group'    → 原来的「按业务员 / 首字母」视图树（辅助视图，保留）
   * 业务上确实有人按"我的业务员"点货，所以不做成二选一删掉一个。
   * 两个模式的**过滤状态各自独立**（`categoryId` / `group`），切回去还在。
   */
  const [treeMode, setTreeMode] = useState('category');
  const [categoryId, setCategoryId] = useState(null); // null=全部 | UNCLASSIFIED=未分类 | 具体 id

  /**
   * 「换文件夹」过场：切分类时先把旧行淡出（约 140ms）再显示新行。
   * 为什么要有：数据是本地过滤、瞬间就换好了，但用户看到的是"表格刷地一变"，
   * 眼睛来不及确认"这是新文件夹"。给一个极短的过场，切换感就出来了。
   */
  const [switching, setSwitching] = useState(false);
  useEffect(() => {
    if (!switching) return undefined;
    const timer = setTimeout(() => setSwitching(false), 140);
    return () => clearTimeout(timer);
  }, [switching, categoryId]);

  /**
   * 行内编辑：双击某一格直接改，不用开大弹窗。
   * `editing = { id, key, value }`；只允许改这几个"日常会写错"的文本字段，
   * 编码/分类这类会影响单据归属的字段仍然走弹窗（避免误改）。
   */
  const [editing, setEditing] = useState(null);
  const [savingCell, setSavingCell] = useState(false);
  /* 打开时的时间戳：双击的第一次 click / 浏览器把焦点移回表格都会立刻触发 blur，
     不挡一下就会出现"输入框一闪就没"（实测 2026-10-22）。250ms 内的 blur 一律忽略。 */
  const editOpenedAt = useRef(0);

  const cats = usePartnerCategories({ kind });

  const list = rows || [];
  /* 分类 → 该分类下的档案（树的客户叶子数据源）。
     未分类（category_id 为 null）不进这里 —— 它走「未分类」节点自己的展开列表。 */
  const rowsByCategory = useMemo(() => {
    const map = {};
    (list || []).forEach((row) => {
      const key = row.category_id;
      if (key === null || key === undefined) return;
      if (!map[key]) map[key] = [];
      map[key].push(row);
    });
    return map;
  }, [list]);


  // 多选（受控）。清洗口径同商品页：`products` 换新后把已不存在的 id 剔掉，
  // 删完之后不用手动 clear —— 选中条自己会缩到 0；点了取消则原样保留。
  const [selectedKeys, setSelectedKeys] = useState([]);
  useEffect(() => {
    setSelectedKeys((prev) => pruneSelection(prev, list));
  }, [list]);

  // 树的计数与「全部」都基于**全量**数据：搜索时计数不该跟着变，
  // 否则左侧数字一边打字一边跳，人就没法用它判断"该点哪个分组"。
  const tree = useMemo(() => buildPartnerTree(list, kind), [list, kind]);

  /**
   * 「选中分类」= 选中它**整棵子树**（选中"集团客户"要能看到下面所有分公司/项目）。
   * 一次算好 Set，不要每行都递归一遍（61 行 × 深树 = 上千次遍历）。
   */
  const categoryScope = useMemo(() => {
    if (!isPicked(categoryId) || isAll(categoryId) || categoryId === UNCLASSIFIED) return null;
    // ⚠️ 同时收「数字」与「字符串」两种写法：树的 id 来自后端是数字，但
    //    data-node-id 属性、URL、localStorage 里都可能是字符串。只认一种时，
    //    过滤结果会是 0 行 —— 界面上就是"左边点得好好的，右边一片空白"。
    const scope = subtreeIds(cats.index, Number(categoryId));
    scope.add(categoryId);
    scope.add(Number(categoryId));
    return scope;
  }, [cats.index, categoryId]);

  /**
   * 选中的分类**已经不在树里**（别处删了 / 树还没加载出来 / id 类型对不上）。
   * 这种情况下绝不能"过滤出 0 行"，那正是「左有右空」的来源 —— 退化成看全部，
   * 并且给出人能看懂的提示。
   */
  const staleSelection = useMemo(() => {
    if (!isPicked(categoryId) || isAll(categoryId) || categoryId === UNCLASSIFIED) return false;
    const index = cats.index;
    if (!index || !index.byId) return false;
    return !index.byId.has(Number(categoryId));
  }, [cats.index, categoryId]);

  const uncategorizedCount = useMemo(
    () =>
      list.filter((row) => row.category_id === null || row.category_id === undefined || row.category_id === '')
        .length,
    [list],
  );

  /** 表格「分类」列的文字。分类树还没加载完时显示 `…`，别把整列刷成「未分类」 */
  const categoryText = useCallback(
    (row) => {
      const raw = row ? row.category_id : null;
      if (raw === null || raw === undefined || raw === '') return '未分类';
      if (cats.loaded) return cats.pathOf(raw) || '未分类';
      // 树没加载成（404 / 断网）时，档案的 category_id 是**真的**
      // —— 不能因为查不到名字就说它是"未分类"，那是在撒谎。退化成 `#12`。
      if (cats.error) return `#${raw}`;
      return '…';
    },
    [cats.loaded, cats.error, cats.pathOf],
  );

  const visible = useMemo(() => {
    const q = String(search || '').trim().toLowerCase();
    let base = [];
    if (treeMode === 'category') {
      // 三态（见 lib/treeSelection.js）：
      //   null（还没选）→ 空表；ALL（点了「全部」）→ 全量；其它 → 该分类整棵子树
      if (!isPicked(categoryId)) {
        base = [];
      } else if (isAll(categoryId) || staleSelection) {
        // 失效选中（不在树里）按「全部」处理：宁可多显示，也不要给一片空白
        base = list;
      } else {
        base = list.filter((row) => {
          const raw = row.category_id;
          const empty = raw === null || raw === undefined || raw === '';
          if (categoryId === UNCLASSIFIED) return empty;
          if (empty) return false;
          return categoryScope ? categoryScope.has(Number(raw)) : false;
        });
      }
    } else if (!isPicked(group)) {
      base = [];
    } else if (isAll(group)) {
      base = list;
    } else {
      base = filterPartnersByGroup(list, kind, group);
    }
    return base.filter((row) => matchSearch(row, q));
  }, [list, kind, group, search, treeMode, categoryId, categoryScope, staleSelection]);

  /**
   * 导出要用哪批数据。
   * 左侧树是"三态"的：没选 → 表格空；选「全部」→ 全量；选分类 → 那一支。
   * 直接拿 `visible` 当导出数据，用户一进页面点导出就是 0 行（按钮只能是灰的）。
   * 所以这里兜底：只要没挑分类，导出就按全量走，并在弹窗里说明。
   *
   * ⚠️⚠️ **必须排在 `visible` 的 useMemo 之后**（2026-10-20 供应商页白屏事故）：
   *    `const` 的 TDZ 在函数组件每次渲染时都真实生效 ——
   *    这段原本写在 `visible` 定义之前，`exportRows = … ? visible : list`
   *    求值时 `visible` 还在暂时性死区，React 立刻抛
   *    `ReferenceError: Cannot access 'visible' before initialization`，
   *    整棵树被卸载 → 表现为**一点某个分类就整页白屏、控制台也不报红**。
   *    规则：任何引用 useMemo 结果的常量，一律写在那个 useMemo **后面**。
   */
  const pickedSomething = treeMode === 'category' ? isPicked(categoryId) : isPicked(group);
  const exportRows = pickedSomething ? visible : list;

  /**
   * 把勾选的列写成 xlsx 并下载。
   * Excel 引擎按需加载（B4b）：第一次导出才下载那个 ~860 KB 的 chunk。
   * 下载失败必须明说，不能静默什么都不做（用户会以为"点了没反应"）。
   */
  const runExport = async (keys) => {
    let xlsx;
    try {
      xlsx = await loadXLSX();
    } catch {
      window.alert('Excel 引擎加载失败（网络或缓存异常），请刷新页面后重试。');
      return;
    }
    const sheetRows = buildPartnerSheet(exportRows, kind, keys);
    const worksheet = xlsx.utils.aoa_to_sheet(sheetRows);
    // 列宽：中文列不给宽度会被压成一串 ####，对方打开先得手动拉一遍
    const picked = partnerColumns(kind).filter((column) => keys.includes(column.key));
    worksheet['!cols'] = picked.map((column) => ({ wch: column.width || 16 }));
    const workbook = xlsx.utils.book_new();
    xlsx.utils.book_append_sheet(workbook, worksheet, kind === 'supplier' ? '供应商' : '客户');
    xlsx.writeFile(workbook, partnerExportFileName(kind));
    setExportOpen(false);
  };

  const isFocused = (row) =>
    Boolean(focus && focus.tab === config.tab && String(focus.id) === String(row.id));

  /* ── 拖拽归档 ─────────────────────────────────────────────────────────────
   * 交互口径（对齐全站其它拖拽）：
   *   · 拖的是一行 → 就移这一行；拖的是**已勾选**的一行 → 移整批选中项
   *     （勾了 8 个客户再拖其中任何一个，用户期望的是 8 个一起走）
   *   · 用原生 HTML5 DnD：表格行 `draggable` + 树节点 `onDragOver/onDrop`。
   *     树自己的"移动分类节点"是 pointer 事件实现的，两套互不干扰。
   *   · dataTransfer 里带自定义 MIME，树那边据此判断"拖的是档案行"而不是
   *     从桌面拖进来的文件（否则会把文件当成档案去归档）。
   */
  const handlePartnerDragStart = (row, event) => {
    if (!dndEnabled) return;
    const fromSelection = selectedKeys.some((key) => String(key) === String(row.id));
    const ids = fromSelection && selectedKeys.length > 1 ? [...selectedKeys] : [row.id];
    dragIdsRef.current = ids.map((value) => Number(value));
    try {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('application/x-erp-partners', JSON.stringify(dragIdsRef.current));
      // 有些浏览器不带 text/plain 就不肯开始拖
      event.dataTransfer.setData('text/plain', `${ids.length}`);
    } catch {
      /* 老浏览器忽略即可 */
    }
    setDragging(true);
  };

  const handlePartnerDragEnd = () => {
    dragIdsRef.current = [];
    setDragging(false);
  };

  /**
   * 松手：targetId = 分类 id，或 null（「未分类」节点）。
   * `meta` 由树回传：`{ ids, name }` —— ids 来自 dataTransfer（不受 dragend 竞态影响），
   * name 是**用户眼前那一行**的名字（提示语以它为准，不再依赖服务端回话）。
   */
  const handlePartnerDrop = async (targetId, meta = {}) => {
    const payloadIds = Array.isArray(meta.ids) && meta.ids.length ? meta.ids : dragIdsRef.current;
    const ids = payloadIds.map((value) => Number(value)).filter((value) => Number.isFinite(value));
    dragIdsRef.current = [];
    setDragging(false);
    if (!ids.length) return;
    const result = await onMoveToCategory(ids, targetId, meta.name);
    if (!result) return;
    // ⚠️ 必须清空勾选：拖走的几条已经不在原筛选里了，选区留着会让批量条
    //    喊「已选中 N 项，但不在当前筛选内」，看着像"操作失败"（2026-10-21 实测）。
    setSelectedKeys([]);
    // ① 右侧列表切到目标分类：刚拖进去的那几条就在眼前，这就是最好的"成功了"的证据。
    //    ⚠️ 原来这里套了 `if (treeMode === 'category')` —— 只要用户恰好停在「按分组」
    //    视图，拖完右表就**完全不动**（停在"请选择分类"的空态），看起来就是"拖了个寂寞"。
    //    现在无条件切回分类视图 + 设目标分类：拖到哪个分类，就应当看到哪个分类。
    if (treeMode !== 'category') setTreeMode('category');
    setCategoryId(targetId === null ? UNCLASSIFIED : targetId);
    // 切换瞬间给表格一个"换文件夹"的过场（旧行先退场，再淡入新行）
    setSwitching(true);
    // ② 左侧树：目标可能折叠在深层，让它展开祖先 + 滚到 + 闪一下
    setRevealSignal({ id: targetId === null ? UNCLASSIFIED : targetId, at: Date.now() });
    // ③ 分组/计数都变了：树与列表各刷一次（不 await 树，避免松手后卡一下）
    if (cats && cats.reload) cats.reload();
    if (onImported) onImported();
  };

  // 拖动期间给 body 挂个标记：全站光标变抓手，避免"抓着一半又变回箭头"
  useEffect(() => {
    if (!dragging) return undefined;
    document.body.dataset.partnerDragging = '1';
    return () => {
      delete document.body.dataset.partnerDragging;
    };
  }, [dragging]);

  /**
   * 只有客户能挂文件：后端归档接口是 `/customers/{id}/files`，供应商没有对应表。
   * 用 `kind` 判断而不是让薄壳传一个 `onFiles` 回调 —— 供应商页因此**零改动**，
   * 也不会有人误以为供应商也能归档。
   */
  const canFiles = kind === 'customer';

  /* 行内可编辑的字段：都是"录错了当场改"的文本项。
     编码（主键，关联单据）、分类（拖拽/弹窗改）刻意不开放 —— 误改代价太大。 */
  const EDITABLE_KEYS = useMemo(() => new Set(['name', 'phone', 'email', 'address', 'level', 'businesser']), []);

  const commitCell = async () => {
    const cell = editing;
    if (!cell) return;
    const original = list.find((row) => String(row.id) === String(cell.id));
    const before = original ? (original[cell.key] ?? '') : '';
    const next = cell.value ?? '';
    if (String(before) === String(next)) {
      setEditing(null);
      return;
    }
    setSavingCell(true);
    const ok = await onPatchPartner(cell.id, { [cell.key]: next });
    setSavingCell(false);
    setEditing(null);
    if (ok && onImported) onImported();
  };

  const columns = useMemo(() => {
    const base = config.columns.map((col) => ({ ...col }));
    // 「分类」列插在名称后面：它是这一轮新增的归属信息，紧挨着主体字段最自然。
    // 全路径（集团客户 / 华北分公司 / 项目A）而不是叶子名 —— 分类允许跨分支重名，
    // 只显示叶子会出现两个「项目A」，看不出是哪一个。
    base.splice(2, 0, {
      key: 'category',
      title: '分类',
      ellipsis: true,
      hideBelow: 'sm',
      // 这一格放的是全路径（「中铁一局集团 / 新运工程公司 / 塞拉利昂铁路运营公司」），
      // 160px 只能看到前两段。给 240 让默认就基本读得完；还不够就拖表头分界线。
      width: 240,
      minWidth: 160,
      render: (row) => {
        const text = categoryText(row);
        return (
          <span className={text === '未分类' || text === '…' ? 'partner-category partner-category--empty' : 'partner-category'} title={text}>
            {text}
          </span>
        );
      },
    });
    base.push({
      key: 'actions',
      title: '操作',
      // 152 → 208：客户页多了「📁 文件」，三个按钮并排需要更宽的下限。
      // ⚠️ 实测（2026-10-17，探针把这里改成 96 重跑）：`table-layout: auto` 下
      //    这一列会按内容自己撑开，改回 96 后单元格实测宽度**一点没变**（仍 ≈142px），
      //    按钮也不会被裁 —— 所以这个 width 是「给内容留的基准下限」，不是硬约束，
      //    别指望改它能复现"删除被挤掉"（那种事故发生在 `table-layout: fixed` 或
      //    `overflow: hidden` 的容器上）。
      width: 208,
      align: 'right',
      sticky: 'right',
      nowrap: true,
      render: (row) => (
        <div className="row-actions">
          {canFiles ? (
            <button
              type="button"
              className="secondary-btn small-btn partner-files-btn"
              onClick={() => setFilesFor(row)}
              title="查看 / 上传这个客户的文件"
            >
              📁 文件
            </button>
          ) : null}
          <button
            type="button"
            className="secondary-btn small-btn partner-edit-btn"
            onClick={() => onEdit && onEdit(row)}
          >
            编辑
          </button>
          <button type="button" className="danger-btn" onClick={() => onDelete && onDelete(row)}>
            删除
          </button>
        </div>
      ),
    });
    // 行内编辑：给可编辑列包一层 render（编辑态出 input，平时还是原样文本）
    return base.map((col) => {
      if (!EDITABLE_KEYS.has(col.key)) return col;
      const originalRender = col.render;
      return {
        ...col,
        render: (row) => {
          const active = editing && String(editing.id) === String(row.id) && editing.key === col.key;
          if (active) {
            return (
              <input
                className="cell-edit-input"
                data-cell-edit={col.key}
                autoFocus
                value={editing.value}
                onChange={(event) => setEditing((cur) => (cur ? { ...cur, value: event.target.value } : cur))}
                onBlur={() => {
                  if (Date.now() - editOpenedAt.current < 250) return;
                  commitCell();
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    commitCell();
                  } else if (event.key === 'Escape') {
                    event.preventDefault();
                    setEditing(null);
                  }
                }}
                // 行是 draggable 的：不让输入框里的按下/拖动冒泡去启动行拖拽
                onMouseDown={(event) => event.stopPropagation()}
                onDragStart={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                }}
              />
            );
          }
          if (originalRender) return originalRender(row);
          const raw = row[col.key];
          if (raw === null || raw === undefined || raw === '') {
            return <span className="cell-empty">{col.fallback || '—'}</span>;
          }
          return String(raw);
        },
      };
    });
  }, [config.columns, onDelete, onEdit, categoryText, canFiles, setFilesFor, EDITABLE_KEYS, editing]);

  /**
   * 当前这套视图（分类 / 分组）**是否已经做过选择**。
   * 没选 → 右表必须是空表 + 「请在左侧选择一个分类」，而不是把全部档案倒出来。
   * 这是本次改造的核心：左侧树是入口，不是装饰。
   */
  const pickedNow = treeMode === 'category' ? isPicked(categoryId) : isPicked(group);

  const emptyProps =
    list.length === 0
      ? {
          variant: 'data',
          title: config.emptyTitle,
          description: config.emptyDescription,
          action: { label: config.addLabel, onClick: onAdd },
        }
      : !pickedNow
        ? pickPrompt(config.noun)
        : visible.length === 0 && !search
          ? {
              // 「选了分类但这一类确实没有档案」≠「还没选分类」。两句文案必须分开，
              // 否则用户拖完看到"请先选择一个分类"，会以为拖拽根本没生效（2026-10-22 报障）。
              variant: 'filter',
              title: `这个分类下还没有${config.noun}`,
              description: '可以点「全部」看所有档案，或把档案从右边拖进来。',
              action: { label: '查看全部', onClick: () => setCategoryId(ALL) },
            }
          : {
            variant: search ? 'search' : 'filter',
            title: config.emptySearchTitle,
            description: '换一个关键词，或在左侧点「' + config.allLabel + '」看全部。',
            action: {
              label: '查看全部',
              onClick: () => {
                if (onSearch) onSearch('');
                // 回到「全部」而不是「什么都没选」—— 点"清空筛选"的人想看全部，
                // 给他一块空表只会以为系统坏了
                setGroup(ALL);
                setCategoryId(ALL);
              },
            },
          };

  const groupText = isAll(group) ? '' : partnerGroupLabel(group);

  // 副标题：两种模式各自说自己的过滤口径，别把「客户级别 · 零售价1」和
  // 「集团客户 / 华北分公司」混在一句里 —— 用户会不知道现在看的是哪套。
  // 「全部」与"还没选"都不算过滤，副标题里不出现路径。
  const categoryPath =
    !isPicked(categoryId) || isAll(categoryId)
      ? ''
      : categoryId === UNCLASSIFIED
        ? '未分类'
        : cats.pathOf(categoryId);
  const activeFilterText = treeMode === 'category' ? categoryPath : groupText;

  const subtitle = activeFilterText
    ? `${activeFilterText} · ${visible.length} / ${list.length} ${config.unit}`
    : `${visible.length} / ${list.length} ${config.unit}`;

  const treeSubtitle = !pickedNow
    ? `共 ${list.length} ${config.unit} · 点一下开始`
    : treeMode === 'category'
      ? activeFilterText
        ? `已按「${activeFilterText}」过滤`
        : `共 ${list.length} ${config.unit}`
      : group
        ? `已按「${groupText}」过滤`
        : `共 ${list.length} ${config.unit}`;

  return (
    <div className="partners-page">
      {/* 从单据跳转过来的定位条。⚠️ 必须放在 ResizableLayout **外面**：
          ResizableLayout 只有恰好 2 个子元素才启用拖拽，塞进来会变成
          「banner | 手柄 | 列表」三块，左栏被 banner 占掉 40%。 */}
      {focus && focus.tab === config.tab && (
        <div className="focus-banner">
          <span className="focus-banner-tag">从单据跳转</span>
          <span className="focus-banner-text">
            已定位到{config.noun}{' '}
            <strong>
              {(list.find((row) => String(row.id) === String(focus.id)) || {}).name || focus.id}
            </strong>
          </span>
          <button type="button" className="link-btn" onClick={onClearFocus}>
            取消定位
          </button>
        </div>
      )}

      <ResizableLayout storageKey={config.storageKey} minLeft={260}>
        <ErpCard
          title={treeMode === 'category' ? `${config.noun}分类` : config.treeTitle}
          subtitle={treeSubtitle}
          extra={
            <div className="partners-tree-extra">
              {/* 两种树并存：真实分类（可拖拽/可搜索）是主视图，
                  「按业务员分组」保留成辅助视图 —— 业务上确实有人按业务员点货。 */}
              <div className="partners-mode" role="group" aria-label="左侧视图切换">
                <button
                  type="button"
                  className={treeMode === 'category' ? 'is-active' : ''}
                  onClick={() => setTreeMode('category')}
                >
                  分类
                </button>
                <button
                  type="button"
                  className={treeMode === 'group' ? 'is-active' : ''}
                  onClick={() => setTreeMode('group')}
                >
                  分组
                </button>
              </div>
              {activeFilterText ? (
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => (treeMode === 'category' ? setCategoryId(ALL) : setGroup(ALL))}
                >
                  重置
                </button>
              ) : null}
            </div>
          }
        >
          <div className={`partners-tree${treeMode === 'category' ? ' partners-tree--category' : ''}`}>
            {treeMode === 'category' ? (
              <PartnerTree
                kind={kind}
                tree={cats.tree}
                loading={cats.loading}
                error={cats.error}
                notReady={cats.notReady}
                selected={categoryId}
                onSelect={setCategoryId}
                uncategorizedCount={uncategorizedCount}
                allCount={list.length}
                onMove={cats.move}
                onBatchMove={cats.batchMove}
                // 拖拽归档（试点）：树只负责"接住"，落库由 onPartnerDrop 交回页面
                partnerDropEnabled={dndEnabled}
                revealSignal={revealSignal}
                rowsByCategory={rowsByCategory}
                onPickRow={(row) => onSearch && onSearch(row.name)}
                onPartnerDrop={handlePartnerDrop}
                onPartnerDragStart={handlePartnerDragStart}
                partnerDragCount={dragging ? dragIdsRef.current.length : 0}
                uncategorizedRows={list.filter((row) => row.category_id === null || row.category_id === undefined)}
                emptyText={config.emptyListText}
                onRetry={cats.reload}
                // 建类三件套：数据在 hook 里，组件只负责交互（与拖拽同一个约定）
                onAdd={cats.create}
                onRename={cats.rename}
                onDelete={cats.remove}
                busy={cats.busy}
              />
            ) : (
              <ErpTree
                nodes={tree.nodes}
                value={group}
                onChange={setGroup}
                counts={tree.counts}
                total={tree.total}
                allLabel={config.allLabel}
              />
            )}
          </div>
        </ErpCard>

        <ErpCard
          title={config.listTitle}
          subtitle={subtitle}
          extra={
            <div className="board-extra-actions">
              <button
                type="button"
                className="secondary-btn small-btn"
                data-import-open
                onClick={() => setImportOpen(true)}
                title={`从 Excel 批量导入${config.noun}（先预检，确认后才写库）`}
              >
                导入
              </button>
              <button
                type="button"
                className="secondary-btn small-btn"
                data-export-open
                onClick={() => setExportOpen(true)}
                disabled={!exportRows.length}
                title={
                  exportRows.length
                    ? pickedSomething
                      ? '勾选要导出的列再生成 Excel（导出当前筛选结果）'
                      : '勾选要导出的列再生成 Excel（未选分类，将导出全部）'
                    : '当前没有可导出的记录'
                }
              >
                导出 Excel
              </button>
              <button type="button" className="primary-btn small-btn" onClick={onAdd}>
                {config.addLabel}
              </button>
            </div>
          }
          flush
          divider
        >
          <div className="erp-card-toolbar">
            <input
              className="search-input"
              placeholder={config.searchPlaceholder}
              value={search}
              onChange={(event) => onSearch && onSearch(event.target.value)}
            />
          </div>

          <ErpTable
            columns={columns}
            rows={visible}
            rowKey="id"
            ariaLabel={config.listTitle}
            rowClassName={(row) =>
              [isFocused(row) ? 'focus-row' : '', dndEnabled ? 'is-draggable-row' : '']
                .filter(Boolean)
                .join(' ')
            }
            rowProps={(row) => ({
              // 行始终可拖（拖拽归档是主操作），双击某一格进行内编辑
              ...(dndEnabled
                ? {
                    draggable: true,
                    onDragStart: (event) => handlePartnerDragStart(row, event),
                    onDragEnd: handlePartnerDragEnd,
                  }
                : {}),
              onDoubleClick: (event) => {
                // 正在编辑时，双击落在输入框里会冒泡上来 —— 必须忽略，
                // 否则每双击一下就把草稿重置回原值，用户永远改不进去（2026-10-22 实测）
                if (editing) return;
                if (event.target && event.target.closest && event.target.closest('input, textarea, button')) return;
                const td = event.target && event.target.closest ? event.target.closest('td') : null;
                if (!td) return;
                // 表格最左边是选择列（ErpTable 的 selectable），所以列号要减 1
                const col = columns[td.cellIndex - 1];
                if (!col || !EDITABLE_KEYS.has(col.key)) return;
                event.preventDefault();
                event.stopPropagation();
                editOpenedAt.current = Date.now();
                setEditing({ id: row.id, key: col.key, value: String(row[col.key] ?? '') });
              },
            })}
            selectable
            columnResize
            columnResizeKey={`partners-${kind}`}
            selectedKeys={selectedKeys}
            onSelectionChange={setSelectedKeys}
            bulkActions={
              <button
                type="button"
                className="danger-btn small-btn"
                onClick={() => onBatchDelete && onBatchDelete(selectedKeys)}
              >
                批量删除
              </button>
            }
            emptyProps={emptyProps}
            // ⚠️ 这里刻意**不传** `loading`：分类树的 loading 只表示"树在刷"，
            //    拿它去遮右表会在每次 reload 时把已有数据换成骨架屏 ——
            //    用户看到的就是"列表空白、操作列没有按钮"。右表数据是本地过滤的，本来就不需要骨架。
            // 「换文件夹」过场：只淡入，不换成骨架屏（140ms 的骨架只会闪一下，更慌）
            wrapClassName={switching ? 'is-switching' : ''}
          />
        </ErpCard>
      </ResizableLayout>

      {/* 客户文件抽屉：`position: fixed` 的全屏层，放在这里只是"就近挂载"，
          不影响上面的 ResizableLayout 两子元素结构（多一个子元素会打断拖拽）。 */}
      {canFiles && filesFor ? (
        <Suspense fallback={null}>
          <CustomerFilesDrawer customer={filesFor} onClose={() => setFilesFor(null)} />
        </Suspense>
      ) : null}

      <ExportColumnsDialog
        open={exportOpen}
        kind={kind}
        title={`导出${config.noun}档案`}
        columns={partnerColumns(kind)}
        defaultKeys={partnerDefaultKeys(kind)}
        rowCount={exportRows.length}
        onClose={() => setExportOpen(false)}
        onConfirm={runExport}
      />

      {/* 导入弹窗：kind 就是本组件的 kind，用户在客户页点导入导的就是客户 */}
      <ArchiveImportDialog
        open={importOpen}
        kind={kind === 'supplier' ? 'suppliers' : 'customers'}
        onClose={() => setImportOpen(false)}
        onImported={() => onImported && onImported()}
      />
    </div>
  );
}
