/**
 * PurchaseInboundBoard —— 「采购入库」整页 UI（第三步-B 第一家）
 *
 * 改造前：`pages/PurchasePage.jsx` 1134 行，左表单 + 右列表全部手写：
 *   · 表头字段走 `.form-row.two-col > <label>`
 *   · 明细行走 `.form-row.four-col`，每行 5 个控件 + 一个常驻空 `<p>` 红字
 *   · 右下角手搓一段 `合计 ¥…` 的 div
 *   · 右侧列表是 `.data-table.wide-table` + 手写空态
 * 现在：ErpFormGrid/ErpFormRow 接管表头，ErpTable dense 接管明细（render 插槽放控件、
 * footer 放合计行），右侧列表也用 ErpTable（sticky 操作列）。
 *
 * 职责边界（刻意的）：
 *   · 只读 `ctx`，**不自己发请求、不自己算库存**：提交、单位解析、库存提示、跳档案
 *     全部沿用 App.jsx 里现成的函数（`submitInboundForm` / `unitOptionsFor` /
 *     `renderStockHint` / `renderPartyLink`），这一轮**零业务逻辑改动**。
 *   · `data-doc-form="inbound"` 保留在 `<form>` 上 —— styles.css 里那一整节
 *     `[data-doc-form] …` 还服务着另外三个单据表单，删了会连带打坏它们。
 *
 * 两个交互细节：
 *   ① **点明细行 = 选中该行**，按 Delete 删行（焦点在输入框里时不删，避免打字误删）。
 *      这是 ErpTable 的 `onRowClick` 在这页的真实用途 —— 不造"点了没反应"的假交互。
 *   ② 半填行红字仍然是常驻 `<p class="line-invalid">`：内容为空时 CSS `:empty` 隐藏，
 *      `lib/orderLines.isBlankItemRow` 的口径不变（空行静默丢弃、半填 400）。
 */

import { useCallback, useMemo, useState } from 'react';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import { itemRowError } from '../../lib/orderLines';
import { exportWord } from '../../lib/wordExport.js';
import { lineAmount, sumAmounts } from '../../lib/money';
import ProductMultiSelectModal from './ProductMultiSelectModal.jsx';
import { AuditBadge, PayBadge } from './StatusBadges.jsx';
import './docs.css';

const money = (value) =>
  Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PurchaseInboundBoard({ ctx }) {
  const {
    DOC_STATUS_LABELS,
    addInboundItem,
    addProductsToInbound,
    copyInboundItem,
    handleInboundFormChange,
    handleInboundItemChange,
    inboundForm,
    printPdf,
    products,
    purchaseOrders,
    removeInboundItem,
    renderPartyLink,
    renderStockHint,
    setConfirmDelete,
    setNotice,
    submitInboundForm,
    suppliers,
    unitOptionsFor,
    warehouses,
  } = ctx;

  const [selectedLine, setSelectedLine] = useState(null);
  // 批量选商品弹窗（2026-10-20 老系统 UX 升级）
  const [productPickerOpen, setProductPickerOpen] = useState(false);

  // ---- 导出 Word（任务 E · 2026-10-19）----
  // 纯读导出：不动单据、不改状态、不刷新列表。失败只走全局提示。
  // 用 useCallback 包住是为了让下面的 lineColumns / 列表列 useMemo 的依赖保持稳定
  // （否则每次渲染都换函数身份，整张表的列定义会白算一遍）。
  const [wordBusy, setWordBusy] = useState(false);
  const exportInboundWord = useCallback(
    async (row) => {
      if (!row?.id || wordBusy) return;
      setWordBusy(true);
      try {
        const name = await exportWord(
          'inbound',
          row.id,
          `入库单-${row.order_no || row.id}.docx`,
        );
        setNotice(`已导出 ${name}`);
      } catch (err) {
        setNotice(err.message || '导出失败');
      } finally {
        setWordBusy(false);
      }
    },
    [setNotice, wordBusy],
  );

  const items = inboundForm.items || [];
  const filled = items.filter((row) => row.product_id).length;
  // 合计 = 逐行金额累加。**不能**写成 reduce 里直接 `qty * price`：
  // 单价是 4 位"费率"，直接乘会把 0.005 级的差一路带进合计。
  // 也不能看 items 上的 `amount` 字段 —— 那是**上一次保存**的值，改了数量它不会变。
  const total = sumAmounts(items, (row) => lineAmount(row.unit_price, row.quantity));

  const lineColumns = useMemo(
    () => [
      {
        key: 'product_id',
        title: '商品',
        // ⚠️ 商品列是明细表的"主列"：可搜索下拉 + 库存提示 + 半填红字都住这里。
        // 数量/单位/单价收窄到 56/56/84，把宽度让给它（列宽在 auto 布局下只是下限，
        // 剩余空间全归这列 —— minWidth 是它在大窗口里继续变宽的保证）。
        minWidth: 260,
        render: (row, index) => (
          <div className="doc-line-product">
            <ErpSearchSelect
              options={products}
              value={String(row.product_id ?? '')}
              onChange={handleInboundItemChange(index, 'product_id')}
              placeholder="搜索商品名称 / SKU / 助记码"
            />
            {renderStockHint(row.product_id)}
            {/* 半填行红字：空行时内容为空串，CSS 用 :empty 隐藏 */}
            <p className="line-invalid" role="alert">
              {itemRowError(row, index)}
            </p>
          </div>
        ),
      },
      {
        key: 'quantity',
        title: '数量',
        width: 56,
        minWidth: 56,
        align: 'right',
        render: (row, index) => (
          <input
            type="number"
            min="1"
            value={row.quantity}
            aria-label={`第 ${index + 1} 行数量`}
            onChange={handleInboundItemChange(index, 'quantity')}
          />
        ),
      },
      {
        key: 'unit',
        title: '单位',
        width: 56,
        minWidth: 56,
        render: (row, index) => {
          const options = unitOptionsFor(row.product_id) || [];
          return (
            <select
              value={row.unit || options[0]?.name || ''}
              aria-label={`第 ${index + 1} 行单位`}
              onChange={handleInboundItemChange(index, 'unit')}
              disabled={!row.product_id}
            >
              {options.length === 0 && (
                <option value="">{row.product_id ? '该商品未设单位' : '先选商品'}</option>
              )}
              {options.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name}
                </option>
              ))}
            </select>
          );
        },
      },
      {
        key: 'unit_price',
        title: '单价',
        width: 84,
        minWidth: 84,
        align: 'right',
        render: (row, index) => (
          <input
            type="number"
            step="any"
            value={row.unit_price}
            aria-label={`第 ${index + 1} 行单价`}
            onChange={handleInboundItemChange(index, 'unit_price')}
          />
        ),
      },
      {
        key: 'amount',
        title: '金额',
        width: 84,
        minWidth: 84,
        align: 'right',
        num: true,
        format: (_value, row) => money(lineAmount(row.unit_price, row.quantity)),
      },
      {
        key: 'actions',
        title: '',
        // 2026-10-20 加「复制」：44 → 88
        width: 88,
        align: 'center',
        render: (row, index) => (
          <>
            <button
              type="button"
              className="secondary-btn small-btn row-copy-btn"
              onClick={() => copyInboundItem(index)}
              disabled={!row.product_id}
              title={row.product_id ? '复制此行到末尾（数量重置 1）' : '空行不能复制'}
            >
              复制
            </button>
            <button
              type="button"
              className="danger-btn small-btn row-remove-btn"
              onClick={() => {
                removeInboundItem(index);
                setSelectedLine(null);
              }}
              disabled={items.length <= 1}
              title={items.length <= 1 ? '至少保留一行' : '删除此行'}
            >
              删行
            </button>
          </>
        ),
      },
    ],
    [products, items.length, handleInboundItemChange, removeInboundItem, copyInboundItem, renderStockHint, unitOptionsFor],
  );

  const orderColumns = useMemo(
    () => [
      { key: 'order_no', title: '入库单号', mono: true, width: 140 },
      {
        key: 'supplier_id',
        title: '供应商',
        ellipsis: true,
        minWidth: 140,
        format: (value) => suppliers.find((item) => item.id === value)?.name || value,
      },
      {
        key: 'total_amount',
        title: '金额',
        width: 104,
        align: 'right',
        num: true,
        // 金额必须排在仓库/日期前面：右栏窄时横滚会把后面的列滚走，
        // 而金额是这张单最该一眼看到的数字（真机截图抓出来的问题）
        format: (value) => `¥${Number(value || 0).toLocaleString()}`,
      },
      { key: 'items', title: '行数', width: 64, align: 'right', num: true, format: (v) => (v?.length ?? 0) },
      {
        key: 'warehouse_id',
        title: '仓库',
        hideBelow: 'md',
        minWidth: 84,
        ellipsis: true,
        fallback: '—',
        format: (value) => warehouses.find((item) => item.id === value)?.name || '—',
      },
      {
        key: 'order_date',
        title: '日期',
        hideBelow: 'md',
        width: 104,
        ellipsis: true,
        fallback: '—',
        format: (value, row) => value || row.delivery_date || '—',
      },
      {
        // 多维状态分离（2026-10-20）：审核 / 付款两列（入库单没有物流/签收流，
        // 第三维不硬造 —— 入库本身就是"货到了"）
        key: 'audit_status',
        title: '审核',
        width: 84,
        render: (row) => <AuditBadge row={row} labels={DOC_STATUS_LABELS} />,
      },
      {
        key: 'pay_status',
        title: '付款',
        width: 110,
        render: (row) => <PayBadge row={row} />,
      },
      {
        key: 'actions',
        title: '操作',
        width: 208,
        align: 'right',
        sticky: 'right',
        nowrap: true,
        render: (row) => (
          <div className="row-actions">
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => printPdf(`/print/purchase-inbound/${row.id}`, `入库单_${row.order_no}.pdf`)}
            >
              打印
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              data-word-export="inbound"
              onClick={() => exportInboundWord(row)}
              disabled={wordBusy}
            >
              Word
            </button>
            <button
              type="button"
              className="danger-btn"
              onClick={() =>
                setConfirmDelete({
                  id: row.id,
                  endpoint: `/purchase-orders/${row.id}`,
                  label: `采购入库单 ${row.order_no}`,
                  kind: 'purchase-inbound',
                })
              }
            >
              删除
            </button>
          </div>
        ),
      },
    ],
    [DOC_STATUS_LABELS, exportInboundWord, printPdf, setConfirmDelete, suppliers, warehouses, wordBusy],
  );

  /** Delete 删行 —— 焦点在控件里时不删，否则打字删一个字符就把整行干掉 */
  const onLineKeyDown = (event) => {
    if (event.key !== 'Delete' || selectedLine === null) return;
    const tag = (event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    event.preventDefault();
    if (items.length <= 1) return;
    removeInboundItem(selectedLine);
    setSelectedLine(null);
  };

  return (
    /* ⚠️ 单据页必须给独立的 storageKey + 更高的 minLeft（2026-10-18）：
       · 默认 key `erp:mgrid:left` 是全站共用的，用户在客户档案把左栏拖到 300px 后，
         回到单据页也是 300px —— 明细表 min-width 600，直接被压成"一条 + 横滚"，
         商品搜索框只剩半截（用户截图报的就是这个）；
       · 660 = 明细表 600 + 卡片左右内边距 50，是这张表能放平的最小左栏宽度。
       · 2026-10-20 加批量选商品弹窗后包了 <>…</>：弹窗必须挂在 ResizableLayout
         **外面**（第 3 个子元素会让拖拽静默失效）。 */
    <>
      <ResizableLayout
      className="doc-page"
      storageKey="erp:mgrid:doc"
      minLeft={660}
    >
      <ErpCard title="新增采购入库单" subtitle="真实入库 · 写库存与应付">
        <form onSubmit={submitInboundForm} data-doc-form="inbound" className="doc-form">
          <ErpFormGrid columns={2} gap="md">
            <ErpFormRow label="供应商" required>
              {/* 供应商档案可能几百条：平铺下拉改可搜索。
                  ⚠️ 原生 `required` 随 select 一起消失 —— 必填由 submitInboundForm
                  （App.jsx `makeSubmitStockDoc` 里的 partyField 守卫）兜住，别删那个守卫。 */}
              <ErpSearchSelect
                options={suppliers}
                value={String(inboundForm.supplier_id ?? '')}
                onChange={(value) => handleInboundFormChange('supplier_id')({ target: { value } })}
                placeholder="搜索供应商名称 / 编码"
                emptyText="没有匹配的供应商"
                getOptionValue={(item) => String(item.id)}
                getOptionLabel={(item) => `${item.name}（${item.code}）`}
                getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
              />
              {renderPartyLink('suppliers', inboundForm.supplier_id, '供应商')}
            </ErpFormRow>

            <ErpFormRow label="入库仓库" required>
              <select
                value={inboundForm.warehouse_id}
                onChange={handleInboundFormChange('warehouse_id')}
                required
              >
                <option value="">请选择仓库</option>
                {warehouses.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </ErpFormRow>

            <ErpFormRow label="单据日期">
              <input
                type="date"
                value={inboundForm.order_date}
                onChange={handleInboundFormChange('order_date')}
              />
            </ErpFormRow>

            <ErpFormRow label="付款方式">
              <input
                list="lookup-payment-method"
                value={inboundForm.payment_method}
                onChange={handleInboundFormChange('payment_method')}
                placeholder="如：银行转账 / 月结30天"
              />
            </ErpFormRow>

            <ErpFormRow label="备注" span={2}>
              <input
                value={inboundForm.note}
                onChange={handleInboundFormChange('note')}
                placeholder="如：随货同行单号、验收情况"
              />
            </ErpFormRow>
          </ErpFormGrid>

          <div className="doc-lines">
            <div className="doc-lines__head">
              <h3>商品明细</h3>
              <span className="doc-lines__hint">
                {selectedLine === null ? '点一行可选中，按 Delete 删行' : `已选中第 ${selectedLine + 1} 行`}
              </span>
              <button type="button" className="secondary-btn small-btn" onClick={addInboundItem}>
                + 添加一行
              </button>
              {/* 2026-10-20 老系统 UX：复制选中行 / 批量选商品 */}
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => copyInboundItem(selectedLine)}
                disabled={selectedLine === null}
                title={selectedLine === null ? '先点一行选中' : '复制选中行到末尾（数量重置 1）'}
              >
                复制选中行
              </button>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setProductPickerOpen(true)}
                title="勾选多个商品一次性带入明细"
              >
                批量选商品
              </button>
            </div>

            <div className="doc-lines__table" onKeyDown={onLineKeyDown}>
              <ErpTable
                dense
                columns={lineColumns}
                rows={items}
                rowKey={(_row, index) => index}
                ariaLabel="采购入库明细"
                minWidth={600}
                onRowClick={(_row, index) => setSelectedLine(index)}
                rowClassName={(_row, index) => (index === selectedLine ? 'doc-line--selected' : '')}
                footer={
                  <tr className="doc-total-row">
                    <td colSpan={4} className="doc-total-row__label">
                      共 {filled} 行 · 合计
                    </td>
                    <td className="doc-total-row__value">¥{money(total)}</td>
                    <td />
                  </tr>
                }
              />
            </div>
          </div>

          <ErpFormActions>
            <button className="primary-btn" type="submit">
              保存并入库
            </button>
          </ErpFormActions>
        </form>
      </ErpCard>

      <ErpCard
        title="采购入库单列表"
        subtitle={`${purchaseOrders.length} 张`}
        padding="md"
        flush
        divider
      >
        <ErpTable
          columns={orderColumns}
          rows={purchaseOrders}
          ariaLabel="采购入库单列表"
          minWidth={700}
          emptyProps={{
            variant: 'data',
            title: '还没有入库单',
            description: '这里登记的是真实入库（库存 + 应付），与「采购订单」的订货意向分开管理。',
          }}
        />
      </ErpCard>
      </ResizableLayout>

      {/* 批量选商品弹窗：挂在 ResizableLayout 外面 */}
      {productPickerOpen && (
        <ProductMultiSelectModal
          products={products}
          onClose={() => setProductPickerOpen(false)}
          onConfirm={(productIds) => {
            addProductsToInbound(productIds);
            setProductPickerOpen(false);
          }}
        />
      )}
    </>
  );
}
