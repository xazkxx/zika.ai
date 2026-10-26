/**
 * ProductsBoard —— 商品档案页的两栏看板（示范重构）
 *
 * ## 为什么单独抽一个组件
 *
 * `pages/ProductsPage.jsx` 由 `scripts/extract_pages.py` **整文件生成**，
 * 任何手改都会在下次重抽时被覆盖（这个文件头上本来就记着两条历史手改）。
 * 把整页 UI 搬到这里之后，页面文件只剩一行 `<ProductsBoard ctx={ctx} />`，
 * 重抽后用 `scripts/patch_products_board.py` 一条命令就能压回薄壳 ——
 * 补丁面积从「一千行 JSX」缩到「一行」，这是能用脚本维护的前提。
 *
 * ## 这一页改了什么
 *
 * | 改造前 | 改造后 |
 * |---|---|
 * | 两个 `<section className="panel">` | 两个 `<ErpCard>`（统一标题层级与内边距） |
 * | `<div className="section-header">` + h2 + 徽标 + 按钮 | `ErpCard` 的 `title` / `subtitle` / `extra` |
 * | 手写 13 列 `<table>` + 三嵌套三元 | `<ErpTable columns={…}>`，加载/空态内置 |
 * | `'暂无产品数据'` / `'没有匹配的产品'` | `EmptyState` 两种场景（带插画与行动按钮） |
 * | 无 | 窄屏自动隐藏次要列（条码/助记码/规格/颜色/尺码），操作列吸附右侧 |
 *
 * ## 刻意没动的
 *
 * · `.product-thumb` / `.category-tree` / `.cat-*` 这些**页面专属样式类保留** ——
 *   它们已经调好（缩略图 32px 是算出来的），换成组件内联样式只会引入回归。
 * · 搜索框仍用 `.search-input`：`styles.css` 里针对它的那几条 `:has()` 规则
 *   依旧能命中（ErpCard 里仍然有 `.product-table`），不需要改 styles.css 一行。
 * · 业务逻辑一行没搬：过滤（`filteredProducts`）、选中类别、打开弹窗、
 *   删除确认，全部仍由 App.jsx 通过 `ctx` 提供。
 */

import { useEffect, useRef, useState } from 'react';

import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ArchiveImportDialog from '../dataio/ArchiveImportDialog.jsx';
import ProductBatchMoveDialog from './ProductBatchMoveDialog.jsx';
import { resolveImageSrc } from '../../lib/productImage';
import { pruneSelection } from '../../lib/selection.js';
import { ALL } from '../../lib/treeSelection.js';
import { isPicked, pickPrompt } from '../../lib/treeSelection.js';
import { UNCATEGORIZED } from '../../lib/productCategory.js';

/** 列表首列的缩略图：有图显示图，没图显示手写线框 SVG（不为一个图标引依赖库） */
function ProductThumb({ row }) {
  const src = resolveImageSrc(row.image_url);

  if (!src) {
    return (
      <span className="product-thumb is-empty" title="暂无图片">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
          <rect
            x="3"
            y="4.5"
            width="18"
            height="15"
            rx="2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          />
          <circle cx="8.5" cy="10" r="1.5" fill="currentColor" />
          <path
            d="M4 16.5l5-5 3 3 3.5-3.5 5 5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }

  return (
    <a
      className="product-thumb"
      href={src}
      target="_blank"
      rel="noreferrer"
      title={`查看「${row.name}」的原图`}
    >
      <img className="product-thumb-img" src={src} alt={row.name} loading="lazy" decoding="async" />
    </a>
  );
}

const money = (value) => `¥${Number(value || 0).toLocaleString()}`;

/** 13 列 → 声明式。窄屏按 hideBelow 逐级隐藏，优先保住「编号 / 名称 / 价格 / 操作」 */
function buildColumns({ openProductEdit, setConfirmDelete }) {
  return [
    {
      key: 'image_url',
      title: '图片',
      width: 56,
      align: 'center',
      render: (row) => <ProductThumb row={row} />,
    },
    { key: 'sku', title: '编号', mono: true, width: 110 },
    // 2026-10-22：商品名一律**允许折行**（原来是 ellipsis → 长名字被截成一句半）。
    // 行高由内容撑开，配合图片列（32px 缩略图）也不会被裁。
    { key: 'name', title: '名称', wrap: true, width: 220, minWidth: 150 },
    { key: 'category', title: '类别', fallback: '', hideBelow: 'sm', minWidth: 96, wrap: true },
    { key: 'bar_code', title: '条码', mono: true, hideBelow: 'md' },
    { key: 'mnemonic', title: '助记码', mono: true, hideBelow: 'md' },
    { key: 'standards', title: '规格', hideBelow: 'md', minWidth: 96, wrap: true },
    { key: 'unit', title: '单位', hideBelow: 'sm', width: 64 },
    { key: 'purchase_price', title: '成本价', align: 'right', num: true, format: money },
    { key: 'sale_price', title: '零售价', align: 'right', num: true, format: money },
    { key: 'color', title: '颜色', hideBelow: 'md', minWidth: 96, ellipsis: true },
    { key: 'size', title: '尺码', hideBelow: 'md', ellipsis: true },
    {
      key: 'actions',
      title: '操作',
      width: 128,
      align: 'right',
      sticky: 'right',
      nowrap: true,
      fallback: '',
      render: (row) => (
        <div className="row-actions">
          <button type="button" className="link-btn" onClick={() => openProductEdit(row)}>
            编辑
          </button>
          <button
            type="button"
            className="link-btn danger"
            onClick={() =>
              setConfirmDelete({
                id: row.id,
                endpoint: `/products/${row.id}`,
                label: `商品 ${row.name}`,
                kind: 'product',
              })
            }
          >
            删除
          </button>
        </div>
      ),
    },
  ];
}

export default function ProductsBoard({ ctx }) {
  const {
    products = [],
    filteredProducts = [],
    /**
     * 表格真正要渲染的行。
     * 与 `filteredProducts` 的区别只有一个：**没选类别时它是空数组**
     * （`filteredProducts` 在没选类别时是全量，供其它页面/选择器复用，不能动）。
     * 由 App.jsx 算好传进来；万一没传（老调用方）就退回全量，不至于白屏。
     */
    productTableRows = null,
    categoryFilter = null,
    productSearch,
    setProductSearch,
    openCategoryModal,
    renderCategoryNodes,
    setProductModalOpen,
    openProductEdit,
    setConfirmDelete,
    batchDeleteProducts,
    moveProductsToCategory,
    setCategoryFilter,
    patchProduct,
  } = ctx || {};

  // 左侧类别树还没被点过 → 右表应为空 + 引导去左侧点一下
  const picked = isPicked(categoryFilter);
  /* 2026-10-22：与客户/供应商页统一口径 —— **没选类别就不出数据**。
     `filterProductsByCategory(..., null)` 的语义是"不过滤=全量"，所以这里
     必须再拦一道，否则一进商品页就是 262 行，跟客户页（空+引导）完全两种体验。
     `productTableRows` 非空时是"智能创建/选品"流程显式传进来的结果，照旧尊重它。 */
  const tableRows = productTableRows === null ? (picked ? filteredProducts : []) : productTableRows;

  // 多选：选中集放在这里（ErpTable 是受控的），因为"批量删除"要能拿到 id。
  // 数据一变就把失效 key 剔掉 —— 删除成功后不用手动清，选中条自己会缩到 0；
  // 用户在确认框里点了取消，选中也不会丢（这点比"点按钮就先清空"顺手得多）。
  const [selectedKeys, setSelectedKeys] = useState([]);
  // 批量移动小窗（v76）：选中的商品 id 集合在点按钮那一刻固化，
  // 避免弹窗开着时用户又改勾选导致「标题说 5 个实际移了 3 个」的错位
  const [batchMoveIds, setBatchMoveIds] = useState(null);
  /* ── 拖拽归档（商品）：行拖到左侧类别节点上 = 改 category ────────────────
   * 与客户/供应商同一套手感，但落库走 `/products/batch-category`（传类别名）。
   * `revealSignal` 交给左侧树做"展开祖先 + 滚到 + 闪一下"。 */
  const dragIdsRef = useRef([]);
  const [dragging, setDragging] = useState(false);
  const [categoryReveal, setCategoryReveal] = useState(null);

  /* 行内编辑（2026-10-22）：双击名称/规格/单位格子直接改。
     SKU 与类别不开放 —— SKU 是主键、类别影响统计口径，都走弹窗。 */
  const EDITABLE_KEYS = new Set(['name', 'standards', 'unit']);
  const [editing, setEditing] = useState(null);
  const editOpenedAt = useRef(0);

  const commitCell = async () => {
    const cell = editing;
    if (!cell) return;
    const original = products.find((row) => String(row.id) === String(cell.id));
    const before = original ? (original[cell.key] ?? '') : '';
    if (String(before) === String(cell.value ?? '')) {
      setEditing(null);
      return;
    }
    setEditing(null);
    if (typeof patchProduct === 'function') await patchProduct(cell.id, { [cell.key]: cell.value ?? '' });
  };
  // 导入弹窗（2026-10-20 内嵌；2026-10-21 恢复）
  const [importOpen, setImportOpen] = useState(false);
  useEffect(() => {
    setSelectedKeys((prev) => pruneSelection(prev, products));
  }, [products]);

  const dndEnabled = typeof moveProductsToCategory === 'function';

  const handleProductDragStart = (row, event) => {
    if (!dndEnabled) return;
    const inSelection = selectedKeys.some((key) => String(key) === String(row.id));
    const ids = inSelection && selectedKeys.length > 1 ? [...selectedKeys] : [row.id];
    dragIdsRef.current = ids.map((value) => Number(value));
    try {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('application/x-erp-products', JSON.stringify(dragIdsRef.current));
      event.dataTransfer.setData('text/plain', `${ids.length}`);
    } catch {
      /* 老浏览器忽略 */
    }
    setDragging(true);
  };

  const handleProductDragEnd = () => {
    dragIdsRef.current = [];
    setDragging(false);
  };

  /** 松手到某个类别节点：落库 → 右表切到该类别 → 左侧树展开祖先并闪一下 */
  const handleCategoryDrop = async (node) => {
    const ids = dragIdsRef.current;
    dragIdsRef.current = [];
    setDragging(false);
    if (!ids.length || !node) return;
    // 商品分类存的是名称：未分类节点的 name 可能就是空/「未分类」，统一按空串处理
    const name = node.id === UNCATEGORIZED ? '' : String(node.name || '');
    const result = await moveProductsToCategory(ids, name);
    if (!result) return;
    if (typeof setCategoryFilter === 'function') setCategoryFilter(node.id);
    setCategoryReveal({ id: node.id, at: Date.now() });
  };

  useEffect(() => {
    if (!dragging) return undefined;
    document.body.dataset.productDragging = '1';
    return () => {
      delete document.body.dataset.productDragging;
    };
  }, [dragging]);

  const baseColumns = buildColumns({ openProductEdit, setConfirmDelete });
  const columns = baseColumns.map((col) => {
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
        if (raw === null || raw === undefined || raw === '') return <span className="cell-empty">—</span>;
        return String(raw);
      },
    };
  });
  const noData = products.length === 0;

  return (
    <ResizableLayout storageKey="erp:mgrid:products">
      {/* ── 左：类别树 ── */}
      <ErpCard
        title="商品类别"
        subtitle={`共 ${products.length} 个商品`}
        extra={
          <button type="button" className="link-btn" onClick={() => openCategoryModal('create')}>
            + 新增顶级
          </button>
        }
        padding="md"
      >
        {/* .category-tree 保留：styles.css 里 `:has(.category-tree)` 靠它锁定
            左栏宽度与内边距，换掉这个类名会让拖拽默认宽度失效 */}
        <div className="category-tree">
          {renderCategoryNodes
            ? renderCategoryNodes({
                productDropEnabled: dndEnabled,
                onProductDrop: handleCategoryDrop,
                revealSignal: categoryReveal,
              })
            : null}
        </div>
      </ErpCard>

      {/* ── 右：搜索 + 列表 ── */}
      <ErpCard
        title="产品列表"
        subtitle={`${tableRows.length} / ${products.length} 件`}
        extra={
          <div className="board-extra-actions">
            <button
              type="button"
              className="secondary-btn small-btn"
              data-import-open
              onClick={() => setImportOpen(true)}
              title="从 Excel 批量导入商品（先预检，确认后才写库）"
            >
              导入
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              data-export-open
              onClick={() => ctx && ctx.exportExcelData && ctx.exportExcelData('products', '商品档案')}
              title="导出全部商品档案（xlsx）"
            >
              导出 Excel
            </button>
            <button
              type="button"
              className="primary-btn small-btn"
              onClick={() => setProductModalOpen(true)}
            >
              新增产品
            </button>
          </div>
        }
        flush
        divider
      >
        <div className="erp-card-toolbar">
          <input
            className="search-input"
            placeholder="搜索 名称 / 编号 / 条码 / 助记码 / 规格…"
            value={productSearch ?? ''}
            onChange={(event) => setProductSearch(event.target.value)}
          />
        </div>

        <ErpTable
          columns={columns}
          rows={tableRows}
          rowKey="id"
          tableClassName="product-table"
          ariaLabel="商品列表"
          /* 列宽可拖（2026-10-21）：商品 13 列、名称/规格又长，
             固定列宽 + 用户自己调是刚需；宽度存 localStorage（erp:colw:products） */
          columnResize
          columnResizeKey="products"
          selectable
          selectedKeys={selectedKeys}
          onSelectionChange={setSelectedKeys}
          rowProps={(row) => ({
            ...(dndEnabled
              ? {
                  draggable: true,
                  onDragStart: (event) => handleProductDragStart(row, event),
                  onDragEnd: handleProductDragEnd,
                }
              : {}),
            onDoubleClick: (event) => {
              if (editing) return;
              if (event.target && event.target.closest && event.target.closest('input, textarea, button')) return;
              const td = event.target && event.target.closest ? event.target.closest('td') : null;
              if (!td) return;
              const col = columns[td.cellIndex - 1];
              if (!col || !EDITABLE_KEYS.has(col.key)) return;
              event.preventDefault();
              event.stopPropagation();
              editOpenedAt.current = Date.now();
              setEditing({ id: row.id, key: col.key, value: String(row[col.key] ?? '') });
            },
          })}
          bulkActions={
            <>
              {/* 批量移动（v76）：与批量删除并列。点按钮时固化选中集。 */}
              <button
                type="button"
                className="secondary-btn small-btn"
                data-product-batch-move
                disabled={!selectedKeys.length}
                onClick={() => setBatchMoveIds([...selectedKeys])}
              >
                批量移动
              </button>
              <button
                type="button"
                className="danger-btn small-btn"
                onClick={() => batchDeleteProducts && batchDeleteProducts(selectedKeys)}
              >
                批量删除
              </button>
            </>
          }
          emptyProps={
            noData
              ? {
                  variant: 'data',
                  title: '还没有商品',
                  description: '新增第一个商品，或到「导入导出」用 Excel 批量导入',
                  action: { label: '新增商品', onClick: () => setProductModalOpen(true) },
                }
              : !picked
                ? pickPrompt('商品')
                : productSearch
                  ? {
                      // 搜不到：给"清空搜索"，别让用户以为类别是空的
                      variant: 'search',
                      title: '没有匹配的商品',
                      description: '换个关键词试试，或清空搜索条件',
                      action: {
                        label: '清空搜索',
                        onClick: () => setProductSearch(''),
                      },
                    }
                  : {
                      // 选了类别、也没搜索，但这一类确实没商品（≠ 还没选类别）
                      variant: 'filter',
                      title: '这个类别下还没有商品',
                      description: '可以点「全部商品」看所有商品，或把商品行拖进左侧这个类别。',
                      action: { label: '查看全部', onClick: () => setCategoryFilter(ALL) },
                    }
          }
        />
      </ErpCard>

      {/* 导入弹窗：kind 固定成本页的类别，用户不用再选一次 */}
      <ArchiveImportDialog
        open={importOpen}
        kind="products"
        onClose={() => setImportOpen(false)}
        onImported={() => ctx && ctx.reloadAfterImport && ctx.reloadAfterImport('products')}
      />

      {/* 批量移动小窗（v76）：成功后刷新列表，选中集随数据变化自动清空 */}
      <ProductBatchMoveDialog
        open={batchMoveIds !== null}
        ids={batchMoveIds || []}
        ctx={ctx}
        onClose={() => setBatchMoveIds(null)}
        onMoved={() => {
          setBatchMoveIds(null);
          if (ctx && ctx.reloadAfterImport) ctx.reloadAfterImport('products');
        }}
      />
    </ResizableLayout>
  );
}
