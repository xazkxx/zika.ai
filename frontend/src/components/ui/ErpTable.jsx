/**
 * ErpTable —— 声明式表格（零依赖）
 *
 * 全站表格其实只有 4 种形态，差异全部可以压进 `columns` 声明里，
 * 不需要 4 个组件、也不需要 `mode` 之类的开关：
 *
 *   ① 普通列表（33 处 .data-table）：列 + 操作列
 *      { key:'sku' } + { key:'actions', render: row => <按钮组/> }
 *
 *   ② 宽表（11 处 .data-table.wide-table）：列多到必须横滚
 *      给列加 width/minWidth，外层的 .erp-table-wrap 自动横滚；
 *      操作列加 sticky:'right'，滚到最右也一直吸附在右边。
 *
 *   ③ 单据明细（.invoice-line-table）：单元格里是输入框，底部有合计行
 *      用 render 返回控件即可；合计行传 footer={<tr>…</tr>}（渲染在 tfoot）。
 *
 *   ④ 弹窗内的紧凑/选择表（.detail-table）
 *      dense + 不传 footer + 行点击 onRowClick。
 *
 *   ⑤ 多选列表（商品 / 供应商 / 客户档案）
 *      `selectable` + `selectedKeys` + `onSelectionChange`，最左侧自动多一列
 *      Checkbox（表头带全选/半选），有选中时在表格上方浮出批量操作条。
 *      **全选 = 选中本次渲染出来的这些行**（父级传进来的 rows 已经是筛选/分页后的
 *      结果）。这条口径是硬约束：跨页"全选"会让用户删掉屏幕上看不见的行，而且
 *      没法撤销 —— 发票页早就踩过，那里的注释还留着。
 *      选中项由父级持有（受控），组件自己不存业务状态；父级换数据后要把已经不
 *      存在的 key 剔掉，`lib/useRowSelection.js` 就是干这个的。
 *
 * 加载与空态**内置**，页面不用再写 `rows.length === 0 ? '暂无数据' : …`：
 *   loading → 表头保留、tbody 换成 Skeleton（不跳版）
 *   空     → tbody 换成 EmptyState（可传 emptyProps 定制文案与按钮）
 *
 * 用法：
 *
 *   const columns = [
 *     { key: 'sku', title: '编号', mono: true, width: 120 },
 *     { key: 'name', title: '名称', ellipsis: true },
 *     { key: 'purchase_price', title: '成本价', align: 'right', num: true,
 *       format: (v) => `¥${Number(v || 0).toLocaleString()}` },
 *     { key: 'actions', title: '操作', width: 130, align: 'right', sticky: 'right',
 *       render: (row) => <><button>编辑</button><button>删除</button></> },
 *   ];
 *
 *   <ErpTable columns={columns} rows={products} loading={busy} emptyProps={{ variant: 'search' }} />
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import Skeleton from './Skeleton.jsx';
import EmptyState from './EmptyState.jsx';
import './erp-table.css';

/** 行的唯一 key：`rowKey` 可以是字段名，也可以是 `(row, index) => key` */
function keyOfRow(rowKey, row, index) {
  return typeof rowKey === 'function' ? rowKey(row, index) : (row[rowKey] ?? index);
}

/* ── 列宽持久化（columnResize 专用）─────────────────────────────────────
 * 存储坏掉（隐私模式、被别的版本写了非法 JSON）时**静默退回默认列宽** ——
 * 拖列宽是锦上添花的能力，绝不能因为它让整张表打不开。
 */
const COLWIDTH_PREFIX = 'erp:colw:';

function readStoredWidths(key) {
  if (!key) return {};
  try {
    const raw = window.localStorage.getItem(`${COLWIDTH_PREFIX}${key}`);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const clean = {};
    Object.entries(parsed).forEach(([colKey, value]) => {
      const px = Number(value);
      if (Number.isFinite(px) && px >= 40 && px <= 1200) clean[colKey] = px;
    });
    return clean;
  } catch {
    return {};
  }
}

function writeStoredWidths(key, widths) {
  if (!key) return;
  try {
    if (!widths || Object.keys(widths).length === 0) {
      window.localStorage.removeItem(`${COLWIDTH_PREFIX}${key}`);
      return;
    }
    window.localStorage.setItem(`${COLWIDTH_PREFIX}${key}`, JSON.stringify(widths));
  } catch {
    /* 存不进去就算了，本次会话内的拖动照样有效 */
  }
}

/** 取一行里某一列的显示内容：render > format > 原值 > fallback */
function renderCell(col, row, index) {
  if (typeof col.render === 'function') return col.render(row, index);
  const raw = col.key ? row[col.key] : undefined;
  if (typeof col.format === 'function') return col.format(raw, row, index);
  if (raw === null || raw === undefined || raw === '') {
    return col.fallback === undefined ? '—' : col.fallback;
  }
  return raw;
}

function cellClass(col, isHead) {
  return [
    'erp-table__cell',
    isHead ? 'erp-table__cell--head' : '',
    col.align ? `erp-table__cell--${col.align}` : '',
    col.num ? 'erp-table__cell--num' : '',
    col.mono ? 'erp-table__cell--mono' : '',
    col.ellipsis ? 'erp-table__cell--ellipsis' : '',
    // 2026-10-22：`wrap: true` 的列允许折行 —— 行高交给内容决定，不再一律截断成省略号。
    // 只对显式声明的列生效：金额、状态这类短字段仍然单行，避免整表忽高忽低。
    col.wrap ? 'erp-table__cell--wrap' : '',
    col.nowrap ? 'erp-table__cell--nowrap' : '',
    col.sticky === 'right' ? 'erp-table__cell--sticky-right' : '',
    col.className || '',
  ]
    .filter(Boolean)
    .join(' ');
}

export default function ErpTable({
  columns = [],
  rows = [],
  rowKey = 'id',
  loading = false,
  loadingRows = 5,
  emptyProps = null,
  dense = false,
  striped = true,
  hover = true,
  footer = null,
  minWidth,
  maxHeight,
  onRowClick = null,
  /**
   * 行级额外属性，签名 `(row, index) => ({ tabIndex, onKeyDown, title, … })`。
   *
   * 存在的理由只有一个：`onRowClick` 只解决鼠标，键盘用户按 Enter / 空格
   * 打不开详情 —— 而改造前的单据列表**是**能开的（手写 tr 上有 tabIndex +
   * onKeyDown）。换成声明式表格不能把这层无障碍能力丢掉，所以留这个口子。
   *
   * ⚠️ 只接"额外"属性：`className` 用 `rowClassName`、`onClick` 用 `onRowClick`，
   *    这里的 onClick 会被上面两个覆盖（展开顺序刻意如此）。
   */
  rowProps = null,
  rowClassName = null,
  caption = null,
  ariaLabel = '',
  /**
   * 多选。传 `selectable` 即最左侧多一列 Checkbox。
   *
   * `selectedKeys` 传了就是**受控**（父级持有选中集），不传则组件内部自持 ——
   * 两种都支持，因为"只想勾一勾看看"的临时表和"勾了要批量删"的档案列表诉求不同。
   * 受控时务必记得在数据变化后剔除失效 key，否则批量删除会带上已删掉的 id。
   */
  selectable = false,
  selectedKeys = null,
  onSelectionChange = null,
  /** 批量操作区：ReactNode，或 `({ keys, clear }) => ReactNode` */
  bulkActions = null,
  selectColumnWidth = 44,
  className = '',
  tableClassName = '',
  wrapClassName = '',
  /**
   * 列宽可拖（2026-10-21）：表头右缘出现抓手，拖动改列宽、双击恢复默认，
   * 结果按 `erp:colw:<columnResizeKey>` 存 localStorage。
   *
   * 默认关闭 —— 大部分表（明细表、选择表、弹窗里的小表）列宽是"内容说了算"，
   * 给它们加抓手只会让表头变吵。只给客户/供应商/商品这类**大档案表**开。
   *
   * 开启后表格切到 `table-layout: fixed`：
   *   · 好处：列宽真的等于用户拖出来的值（auto 布局下 width 只是建议，
   *     长中文会把列撑回去，拖了没反应）；
   *   · 代价：所有列必须有可算的宽度，所以 colgroup 里未声明的列由浏览器均分剩余宽度。
   */
  columnResize = false,
  columnResizeKey = '',
}) {
  const cols = (columns || []).filter(Boolean);
  const data = rows || [];

  /* ── 列宽覆盖（只有 columnResize 时才参与计算）─────────────────────────
   * 存的是**用户拖出来的像素值**，不存"相对比例"：比例在不同屏幕宽度下
   * 会让"我明明拖窄了"的错觉（宽屏自动放大），档案表的诉求是"这一列就 220px"。
   */
  const [colWidths, setColWidths] = useState(() => readStoredWidths(columnResizeKey));
  const widthsRef = useRef(colWidths);
  widthsRef.current = colWidths;

  const widthOf = (col) => {
    if (columnResize && col.key && colWidths[col.key] != null) return colWidths[col.key];
    if (col.width) return col.width;
    // 列宽可拖时表格是 `table-layout: fixed`：没写 width 的列会被浏览器"均分剩余
    // 空间"，中文列常被压成三四字宽（实测客户档案的「分类」列只剩「国家电网公…」）。
    // 退一步用 minWidth 当初值 —— 它本来就是这一列"最少要这么宽"的声明。
    if (columnResize && col.minWidth) return col.minWidth;
    return null;
  };

  /* 拖列宽的整段交互：pointerdown 记起点 → pointermove 改宽度（跟手）→
     pointerup 落盘。用 window 级监听而不是元素级：鼠标滑出表头（甚至滑出表格）
     时列宽还得跟着走，否则拖到一半"断了"手感极差。 */
  const lastColClick = useRef({ key: null, at: 0 });
  const beginColumnResize = (event, col) => {
    if (!columnResize || !col.key) return;
    if (event.button !== 0) return;
    // 双击复位：自己数"400ms 内同一列的第二次按下"。
    // ⚠️ 不能依赖 `event.detail`（PointerEvent 的 detail 恒为 0），也不能只靠
    //    onDoubleClick（自动化/触摸模拟常常只给 click 不给 dblclick）——
    //    两种环境都验过：只有"自己数点击数"最稳。
    const now = Date.now();
    const last = lastColClick.current;
    if (last.key === col.key && now - last.at < 400) {
      lastColClick.current = { key: null, at: 0 };
      event.stopPropagation();
      resetColumnWidth(col);
      return;
    }
    lastColClick.current = { key: col.key, at: now };
    // ⚠️ 这里**不能** preventDefault()：pointerdown 上禁默认会连带取消后续的
    //    click（浏览器规范），双击/单击都会受影响。
    //    拖选文字的问题由 `is-col-resizing` 的 user-select:none 兜住。
    event.stopPropagation();
    const th = event.currentTarget.parentElement;
    if (!th) return;
    const startWidth = th.getBoundingClientRect().width;
    const startX = event.clientX;
    const MIN_COL_WIDTH = 56;
    const onMove = (moveEvent) => {
      const next = Math.max(MIN_COL_WIDTH, Math.round(startWidth + (moveEvent.clientX - startX)));
      widthsRef.current = { ...widthsRef.current, [col.key]: next };
      setColWidths(widthsRef.current);
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      document.body.classList.remove('is-col-resizing');
      writeStoredWidths(columnResizeKey, widthsRef.current);
    };
    document.body.classList.add('is-col-resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  };

  /** 双击表头分隔线：只复位这一列（整表复位太粗暴，用户往往只想撤回上一次拖动） */
  const resetColumnWidth = (col) => {
    if (!columnResize || !col.key) return;
    setColWidths((prev) => {
      if (prev[col.key] == null) return prev;
      const next = { ...prev };
      delete next[col.key];
      writeStoredWidths(columnResizeKey, next);
      widthsRef.current = next;
      return next;
    });
  };

  // ── 多选状态 ────────────────────────────────────────────────────────
  // 口径：**全选 = 选中本次渲染出来的这些行**。父级若做了分页/筛选，
  // 这里看到的已经是那一页/那份结果，所以不会"勾了全选却删掉屏幕上看不见的行"。
  const [innerKeys, setInnerKeys] = useState([]);
  const controlled = Array.isArray(selectedKeys);
  const pickedKeys = controlled ? selectedKeys : innerKeys;

  const toKey = useCallback((row, index) => keyOfRow(rowKey, row, index), [rowKey]);

  const visibleKeys = useMemo(() => data.map((row, i) => toKey(row, i)), [data, toKey]);
  const visibleSet = useMemo(() => new Set(visibleKeys), [visibleKeys]);
  const pickedSet = useMemo(() => new Set(pickedKeys), [pickedKeys]);

  const allChecked = selectable && visibleKeys.length > 0 && visibleKeys.every((k) => pickedSet.has(k));
  // 半选：有选中但没全选。**没有单独的状态**，由这两个集合算出来 ——
  // 存一个 Boolean 迟早会和数据不同步（删一行之后还显示全选）。
  const someChecked = selectable && !allChecked && visibleKeys.some((k) => pickedSet.has(k));
  const selectedCount = pickedSet.size;
  // 选中了但当前筛选里看不到的（搜索过滤后仍保留），要如实告诉用户
  const hiddenCount = useMemo(
    () => pickedKeys.filter((k) => !visibleSet.has(k)).length,
    [pickedKeys, visibleSet],
  );

  const emitSelection = (next) => {
    if (!controlled) setInnerKeys(next);
    if (typeof onSelectionChange === 'function') onSelectionChange(next);
  };

  const toggleRow = (key) => {
    emitSelection(pickedSet.has(key) ? pickedKeys.filter((k) => k !== key) : [...pickedKeys, key]);
  };

  const toggleAll = () => {
    if (allChecked) {
      emitSelection(pickedKeys.filter((k) => !visibleSet.has(k)));
    } else {
      emitSelection(Array.from(new Set([...pickedKeys, ...visibleKeys])));
    }
  };

  // `indeterminate` 没有对应的 HTML 属性，只能走 DOM；React 不会替你设也不会替你清。
  const headBoxRef = useRef(null);
  useEffect(() => {
    if (headBoxRef.current) headBoxRef.current.indeterminate = someChecked;
  }, [someChecked]);

  // 列数（colSpan 累加）—— 加载/空态那一个占位 td 要用。
  // 选择列不在 `columns` 里（它由组件自己渲染），所以要单独 +1。
  const colCount = (cols.reduce((sum, c) => sum + (c.colSpan || 1), 0) || 1) + (selectable ? 1 : 0);

  // 没显式给 minWidth 时，按各列**当前生效宽度**求和；再兜一个下限，
  // 免得列少的表在宽屏上被拉得稀稀拉拉。
  // 列宽可拖时这一步很关键：用户把几列都拖宽后，表格必须撑出横向滚动条，
  // 而不是反过来把刚才拖宽的列又压回去（那会让"拖了没反应"重现）。
  const sumWidth =
    cols.reduce((sum, c) => {
      const w = widthOf(c);
      return sum + (typeof w === 'number' ? w : Number.parseFloat(w) || c.minWidth || 0);
    }, 0) + (selectable ? selectColumnWidth : 0);
  const tableMinWidth = minWidth ?? Math.max(sumWidth || 0, 0);

  const wrapClass = [
    'erp-table-wrap',
    dense ? 'erp-table-wrap--dense' : '',
    maxHeight ? 'erp-table-wrap--scroll-y' : '',
    wrapClassName,
  ]
    .filter(Boolean)
    .join(' ');

  const tableClass = [
    'erp-table',
    striped ? 'erp-table--striped' : '',
    hover ? 'erp-table--hover' : '',
    // 列宽可拖时必须 fixed：auto 布局下 width 只是建议，长中文会把列撑回去
    columnResize ? 'erp-table--resizable' : '',
    className,
    tableClassName,
  ]
    .filter(Boolean)
    .join(' ');

  const body = (() => {
    if (loading) {
      return (
        <tbody>
          <tr className="erp-table__state-row">
            <td colSpan={colCount} className="erp-table__state-cell">
              <Skeleton
                variant="table"
                rows={loadingRows}
                columns={Math.max(2, Math.min(colCount, 6))}
              />
            </td>
          </tr>
        </tbody>
      );
    }

    if (data.length === 0) {
      return (
        <tbody>
          <tr className="erp-table__state-row">
            <td colSpan={colCount} className="erp-table__state-cell">
              <EmptyState size="sm" compact {...(emptyProps || {})} />
            </td>
          </tr>
        </tbody>
      );
    }

    return (
      <tbody>
        {data.map((row, index) => {
          const key = toKey(row, index);
          const extraProps = rowProps ? rowProps(row, index) || {} : null;
          const isPicked = selectable && pickedSet.has(key);
          return (
            <tr
              key={key}
              {...(extraProps || {})}
              className={`erp-table__row${rowClassName ? ` ${rowClassName(row, index) || ''}` : ''}${
                onRowClick ? ' erp-table__row--clickable' : ''
              }${isPicked ? ' erp-table__row--selected' : ''}`}
              onClick={onRowClick ? () => onRowClick(row, index) : undefined}
            >
              {selectable && (
                <td className="erp-table__cell erp-table__cell--select">
                  <input
                    type="checkbox"
                    className="erp-table__check"
                    checked={isPicked}
                    onChange={() => toggleRow(key)}
                    // 勾选不该顺带打开详情：onRowClick 的表（订单/发票）依赖这条
                    onClick={(event) => event.stopPropagation()}
                    aria-label={`选择第 ${index + 1} 行`}
                  />
                </td>
              )}
              {cols.map((col, ci) => {
                const content = renderCell(col, row, index);
                // ⚠️ 省略号必须包一层：td 上的 max-width 在 table-layout:auto 下
                //    被浏览器忽略（CSS 规范未定义单元格的 max-width 行为），
                //    直接写只会得到「照常折行、一行一个字竖排」。
                return (
                  <td
                    key={col.key || `c${ci}`}
                    className={cellClass(col)}
                    colSpan={col.colSpan}
                    data-hide={col.hideBelow || undefined}
                  >
                    {col.ellipsis ? (
                      <span
                        className="erp-table__ellipsis"
                        title={typeof content === 'string' ? content : undefined}
                      >
                        {content}
                      </span>
                    ) : (
                      content
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    );
  })();

  const bulkBar = selectable && selectedCount > 0 && (
    <div className="erp-table-bulkbar" role="region" aria-label="批量操作">
      <span className="erp-table-bulkbar__count" data-selected-count={selectedCount}>
        已选中 <b>{selectedCount}</b> 项
      </span>
      {hiddenCount > 0 && (
        <span className="erp-table-bulkbar__hint">其中 {hiddenCount} 项不在当前筛选内</span>
      )}
      <div className="erp-table-bulkbar__actions">
        {typeof bulkActions === 'function'
          ? bulkActions({ keys: pickedKeys, clear: () => emitSelection([]) })
          : bulkActions}
      </div>
      <button type="button" className="link-btn" onClick={() => emitSelection([])}>
        取消选择
      </button>
    </div>
  );

  return (
    <>
      {bulkBar}
      <div
        className={wrapClass}
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table
          className={tableClass}
          style={tableMinWidth ? { minWidth: `${tableMinWidth}px` } : undefined}
          aria-label={ariaLabel || undefined}
        >
          {caption && <caption className="erp-table__caption">{caption}</caption>}

          {/* 列宽用 colgroup 下发：比每个 th 都写 style 更规范，
              而且表格布局算宽度时先看 col，横滚宽度也更稳。
              ⚠️ minWidth 必须落在 th 上：col 不支持 min-width，而 auto 布局下
              中文的 min-content 只有「一个字」—— 不给 th minWidth 的文本列
              会被压成一字一行竖排（商品档案的「类别」列实测踩过）。 */}
          {(columnResize || cols.some((c) => c.width) || selectable) && (
            <colgroup>
              {selectable && <col style={{ width: selectColumnWidth }} />}
              {cols.map((col, ci) => {
                const w = widthOf(col);
                return (
                  <col
                    key={col.key || `col${ci}`}
                    style={w ? { width: typeof w === 'number' ? `${w}px` : w } : undefined}
                    // 窄屏隐藏的列，col 也要跟着隐藏 —— 否则 fixed 布局下
                    // 隐形列仍占着宽度，右边会多出一条空白（实测 1100px 出现）
                    data-hide={col.hideBelow || undefined}
                  />
                );
              })}
            </colgroup>
          )}

          <thead>
            <tr>
              {selectable && (
                <th scope="col" className="erp-table__cell erp-table__cell--head erp-table__cell--select">
                  <input
                    ref={headBoxRef}
                    type="checkbox"
                    className="erp-table__check erp-table__check--head"
                    checked={allChecked}
                    onChange={toggleAll}
                    aria-label="全选当前列表"
                  />
                </th>
              )}
              {cols.map((col, ci) => (
                <th
                  key={col.key || `h${ci}`}
                  scope="col"
                  className={cellClass(col, true)}
                  colSpan={col.colSpan}
                  data-hide={col.hideBelow || undefined}
                  style={col.minWidth ? { minWidth: col.minWidth } : undefined}
                >
                  {col.title}
                  {/* 拖列宽的抓手：贴在表头右缘。
                      最后一列（多半是 sticky 的操作列）不给 —— 它宽度由按钮内容定，
                      拖宽了反而把按钮拉散。 */}
                  {columnResize && col.key && ci < cols.length - 1 && !col.colSpan ? (
                    <span
                      className="erp-table__resizer"
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={`调整「${col.title || col.key}」列宽（双击恢复）`}
                      tabIndex={-1}
                      data-col-resizer={col.key}
                      onPointerDown={(event) => beginColumnResize(event, col)}
                      onDoubleClick={() => resetColumnWidth(col)}
                      onClick={(event) => event.stopPropagation()}
                    />
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>

          {body}

          {footer && <tfoot className="erp-table__foot">{footer}</tfoot>}
        </table>
      </div>
    </>
  );
}
