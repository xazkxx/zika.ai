/**
 * SalesOutboundBoard —— 「销售出库」整页 UI（第三步-B 第二家）
 *
 * 改造前：`pages/SalesPage.jsx` 1196 行，左表单 + 右列表 + 详情弹窗全部手写：
 *   · 表头字段走 `.form-row.two-col > <label>`
 *   · 明细行走 `.form-row.four-col`，每行 5 个控件 + 一个常驻空 `<p>` 红字
 *   · 右下角手搓一段 `合计 ¥…` 的 div
 *   · 右侧列表 `.data-table.wide-table` + 手写空态
 *   · 详情弹窗**挂在 `<ResizableLayout>` 内部**（见下面「修掉的三个真问题」③）
 * 现在：ErpFormGrid/ErpFormRow 接管表头，ErpTable dense 接管明细（render 插槽放控件、
 * footer 放合计行），右侧列表也用 ErpTable（sticky 操作列），详情弹窗用 ErpTable 展示明细。
 *
 * ══════════════════════════════════════════════════════════════════════════
 * 多单位换算：这一层**一行都没改**，原封不动沿用 App.jsx 的既有函数
 * ══════════════════════════════════════════════════════════════════════════
 * 销售出库比采购入库多的那层换算，真正落在这四处（全在 App.jsx，本文件只调用）：
 *
 *   ① `unitOptionsFor(productId)`                     App.jsx:4535
 *      选项来源。基础单位恒排第一，辅助单位由 `/products/{id}/units` 异步补齐
 *      （`unitCacheRef` 并发去重、失败不写缓存）。**本文件不自己拼选项。**
 *
 *   ② `handleOutboundItemChange(index,'product_id')(v)` App.jsx:4550 → 4559
 *      选商品 → 带出 `sale_price` + 把 `unit` 归位到**基本单位** + 触发拉取辅助单位。
 *
 *   ③ `handleOutboundItemChange(index,'unit')(v)`       App.jsx:4571
 *      换单位 → 把这个单位自己的价格带出来（箱价 ≠ 盒价）；辅助单位**没单独定价**
 *      （null）时保留原值，绝不静默改成 0。
 *
 *   ④ `submitOutboundForm` → `makeSubmitStockDoc`      App.jsx:4709 / 4615
 *      提交时**只发 `unit`、绝不发 factor**：
 *          const unit = String(row.unit ?? '').trim();
 *          if (unit) line.unit = unit;
 *      换算率由后端 `erp_common._resolve_unit_factor` 从 `unit` 现场解析，
 *      再把 `unit_factor` 作为**快照**写进明细行。客户端说得越多，库存越容易被放大。
 *
 * ⚠️ 所以本文件里**没有** `serializeSalesItems` 调用，也**没有** `price_auto` 字段 ——
 *    那两样属于另一页（`selectedTab === 'sales-units'` 的「销售出库（多单位）」，
 *    见 `components/sales-units/SalesOrderUnitsModal.jsx`）。本页（`sales`）走的是
 *    上面那条老链路：单价由 `makeOrderItemHandler` 联动，提交由 `makeSubmitStockDoc` 拼装。
 *    改造前后**逐字节相同**，只是换了控件的外壳。
 *
 * ══════════════════════════════════════════════════════════════════════════
 * 修掉的三个真问题（都不是"顺手重构"，是真会咬人的）
 * ══════════════════════════════════════════════════════════════════════════
 *   ① **金额列被横滚滚走**：右栏窄时「操作」之后才看到金额，最该一眼看到的数字反而
 *      要滚 —— 金额列提到仓库/日期前面（与采购入库同一处理）。
 *   ② **明细行会被压成一字一行**：`minWidth` 必须下发到 `<th>`、省略号必须落 td
 *      内部块级 span（`ErpTable` 里已封好，这里只负责给每列写 width/minWidth）。
 *   ③ **点开详情后拖拽手柄消失**：弹窗原本是 `ResizableLayout` 的第三个子元素，
 *      而该组件「恰好 2 个子元素才启用」，第 3 个一来就**静默降级**成普通 div ——
 *      网格列宽回到 `1fr 1.5fr`，两栏当着用户的面跳一下。现在弹窗提到布局**外面**，
 *      布局永远只有 2 个子元素（`.modal-overlay` 是 `position:fixed`，放哪都一样）。
 *
 * 一个刻意的展示增强：`SHOW_UNIT_CONVERSION`
 *   选「箱」时在行内直接显示 `×12` / `= 36 公斤` / `≈ 45.83/公斤`，
 *   让「3 箱到底出多少基本单位、单价折合多少」在录入时就看得见，不必保存完再去库存页找答案
 *   （这也正是 `lib/salesUnits.js` 头部写的设计意图）。**纯展示、零载荷影响**，
 *   全部由 `unitOptionsFor` 的 `factor` 推导，不参与任何提交；不想要就把下面这个
 *   开关改成 `false`，三处小字一起消失。
 */

import { useEffect, useMemo, useState } from 'react';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import { itemRowError } from '../../lib/orderLines';
import ArchiveImportDialog from '../dataio/ArchiveImportDialog.jsx';
import { AuditBadge, PayBadge, ShipBadge } from './StatusBadges.jsx';
import ProductMultiSelectModal from './ProductMultiSelectModal.jsx';
import './docs.css';

/** 行内换算小字总开关（纯展示：关掉不影响任何计算与提交） */
const SHOW_UNIT_CONVERSION = true;

const money = (value) =>
  Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 单价折合到基本单位：录入单价 ÷ factor（与 lib/salesUnits 的「只乘不除」相反方向，
 *  这里只用于显示最小单位成本，不写回任何 state）
 *
 *  ⚠️ 除号必须真的写：第一版这里只写了 `value.toFixed(2)`，于是「箱价 550」被原样
 *  显示成「≈ 550.00/公斤」（正确值是 45.83）—— 验证台第一轮就把它抓红了。
 *  展示层的数字只要算错，用户对整页的信任就没了，比不显示更糟。 */
const unitCost = (price, factor) => {
  const value = Number(price);
  if (!Number.isFinite(value) || !factor || factor <= 1) return '';
  return (value / factor).toFixed(2);
};

export default function SalesOutboundBoard({ ctx }) {
  const {
    API_BASE,
    DOC_STATUS_LABELS,
    OUTBOUND_STATUS_LABELS,
    addOutboundItem,
    authHeaders,
    customers,
    copyOutboundItem,
    addProductsToOutbound,
    handleOutboundFormChange,
    handleOutboundItemChange,
    openOrderPayment,
    outboundForm,
    printPdf,
    products,
    refreshSalesOutboundList,
    removeOutboundItem,
    renderPartyLink,
    renderStockHint,
    salesOrders,
    selectedSalesOrder,
    setConfirmDelete,
    setNotice,
    setSelectedSalesOrder,
    submitOutboundForm,
    unitOptionsFor,
    updateSalesOrderStatus,
    saveSalesOrderLogistics,
    warehouses,
  } = ctx;

  const [selectedLine, setSelectedLine] = useState(null);
  // 批量选商品弹窗（true=开；带完商品自动关）
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  // 开票登记弹窗：存「哪一行」而不是整个表单，避免行数据过期时表单跟着过期
  const [invoiceDialogRow, setInvoiceDialogRow] = useState(null);
  // 一键开票的忙碌态（按钮文案 + 防连点）
  const [issueBusy, setIssueBusy] = useState(false);

  /**
   * 一键开票（2026-10-22，先销后票）：
   * 服务端按本单明细生成销项发票、金额取未开票余额、并当场挂 related_order_id。
   * 票号由服务端给占位号（KP-<单号>）—— 真实票号拿到后再用「登记票号」补。
   *
   * ⚠️ 成功后必须重拉列表：uninvoiced_amount / settled 都变了，
   *    不重拉就会「票开了，完结按钮还是灰的」。
   */
  const issueInvoiceOneClick = async (row) => {
    if (issueBusy || !row) return;
    setIssueBusy(true);
    try {
      const response = await fetch(`${API_BASE}/sales-orders/${row.id}/issue-invoice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        throw new Error(
          typeof detail === 'string'
            ? detail
            : (detail && detail.message) || `开票失败（HTTP ${response.status}）`,
        );
      }
      await refreshSalesOutboundList();
      setNotice(
        data.message ||
          `已生成销项发票（${row.order_no}）：本次 ¥${Number(data.invoiced_amount || 0).toFixed(2)}`,
      );
      // 关抽屉：`settled` / `uninvoiced_amount` 都是**后端算的**，前端不复算
      // （复算必然出现"前端说能完结、后端 409"的两张皮）。关掉后用户重开即是新数据。
      setSelectedSalesOrder(null);
    } catch (err) {
      setNotice(err.message || '一键开票失败');
    } finally {
      setIssueBusy(false);
    }
  };
  // 历史销售单导入弹窗（2026-10-20 闭环补口）：导完自动重拉列表
  const [historyImportOpen, setHistoryImportOpen] = useState(false);

  // 详情抽屉的 Esc 关闭（2026-10-20）：抽屉没有遮罩层可点，Esc 是第二关法。
  // 捕获阶段 + stopPropagation：App 全局 Esc（关抽屉等）与这里会抢同一个按键。
  // 上面叠着开票/选商品/导入弹窗时**不接手**，让上层弹窗自己的逻辑去响应。
  useEffect(() => {
    if (!selectedSalesOrder) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      if (invoiceDialogRow || productPickerOpen || historyImportOpen) return;
      event.stopPropagation();
      setSelectedSalesOrder(null);
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [selectedSalesOrder, invoiceDialogRow, productPickerOpen, historyImportOpen]);

  // —— 完结闸（2026-10-20）——
  // 按钮置灰的唯一依据是后端算好的 `settled`（口径唯一权威在
  // erp_sales._apply_settlement_fields：应收余额 = 净额 − 已收，未开票 = 净额 − 已开票）。
  // ⚠️ 弹窗快照会过期：收款/开票后列表已重拉，selectedSalesOrder 还停在点开那一刻，
  // 所以详情弹窗里的结算信息一律从**最新列表**按 id 现取，取不到才退回快照。
  const detailRow = selectedSalesOrder
    ? salesOrders.find((item) => item.id === selectedSalesOrder.id) || selectedSalesOrder
    : null;
  const canComplete = Boolean(detailRow?.settled);
  const COMPLETE_LOCKED_TITLE = '尚有未结清款项或未开具发票，无法完结';

  const items = outboundForm.items || [];
  const filled = items.filter((row) => row.product_id).length;
  const total = items.reduce(
    (sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0),
    0,
  );

  /** 行当前生效的单位选项（与下拉框显示的 value 同一口径：`row.unit || 选项[0]`） */
  const optionOf = (row) => {
    const options = unitOptionsFor(row.product_id) || [];
    const name = row.unit || options[0]?.name || '';
    return options.find((item) => item.name === name) || options[0] || null;
  };

  /**
   * 一行的换算展示数据（**纯展示**）。
   * 只在「选了辅助单位（factor > 1）」时才有内容；基本单位行三处小字全为空。
   * 数字全部由录入值现算，不写回 state、不进请求体。
   */
  const conversionOf = (row) => {
    const option = optionOf(row);
    const factor = option?.factor || 1;
    if (!SHOW_UNIT_CONVERSION || factor <= 1) return null;
    const base = baseUnitOf(row, unitOptionsFor);
    const qty = Number(row.quantity);
    const perBase = unitCost(row.unit_price, factor);
    return {
      factor,
      qtyText: Number.isFinite(qty) && qty > 0 ? `= ${qty * factor} ${base}`.trim() : '',
      costText: perBase ? `≈ ${perBase}/${base}` : '',
    };
  };

  const lineColumns = useMemo(
    () => [
      {
        key: 'product_id',
        title: '商品',
        // 与采购入库同一套列宽契约：商品列是主列，数量/单位/单价收窄让位
        minWidth: 260,
        render: (row, index) => (
          <div className="doc-line-product">
            <ErpSearchSelect
              options={products}
              value={String(row.product_id ?? '')}
              onChange={handleOutboundItemChange(index, 'product_id')}
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
        render: (row, index) => {
          const hint = conversionOf(row);
          return (
            <div className="doc-line-cell">
              <input
                type="number"
                min="1"
                value={row.quantity}
                aria-label={`第 ${index + 1} 行数量`}
                onChange={handleOutboundItemChange(index, 'quantity')}
              />
              {hint?.qtyText && <span className="doc-line-sub">{hint.qtyText}</span>}
            </div>
          );
        },
      },
      {
        key: 'unit',
        title: '单位',
        width: 56,
        minWidth: 56,
        render: (row, index) => {
          const options = unitOptionsFor(row.product_id) || [];
          const hint = conversionOf(row);
          return (
            <div className="doc-line-cell">
              <select
                value={row.unit || options[0]?.name || ''}
                aria-label={`第 ${index + 1} 行单位`}
                onChange={handleOutboundItemChange(index, 'unit')}
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
              {hint && (
                <span className="doc-line-sub" title={`1 ${row.unit} = ${hint.factor} 个基本单位`}>
                  ×{hint.factor}
                </span>
              )}
            </div>
          );
        },
      },
      {
        key: 'unit_price',
        title: '单价',
        width: 84,
        minWidth: 84,
        align: 'right',
        render: (row, index) => {
          const hint = conversionOf(row);
          return (
            <div className="doc-line-cell doc-line-cell--end">
              <input
                type="number"
                step="any"
                value={row.unit_price}
                aria-label={`第 ${index + 1} 行单价`}
                onChange={handleOutboundItemChange(index, 'unit_price')}
              />
              {hint?.costText && (
                <span className="doc-line-sub" title="折合到基本单位的单价（单价 ÷ 换算率）">
                  {hint.costText}
                </span>
              )}
            </div>
          );
        },
      },
      {
        key: 'amount',
        title: '金额',
        width: 84,
        minWidth: 84,
        align: 'right',
        num: true,
        format: (_value, row) => money((Number(row.quantity) || 0) * (Number(row.unit_price) || 0)),
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
              onClick={() => copyOutboundItem(index)}
              disabled={!row.product_id}
              title={row.product_id ? '复制此行到末尾（数量重置 1）' : '空行不能复制'}
            >
              复制
            </button>
            <button
              type="button"
              className="danger-btn small-btn row-remove-btn"
              onClick={() => {
                removeOutboundItem(index);
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
    [products, items.length, handleOutboundItemChange, removeOutboundItem, copyOutboundItem, renderStockHint, unitOptionsFor],
  );

  const orderColumns = useMemo(
    () => [
      // 2026-10-21 用户反馈：要有直观的「单据预览」入口 —— 单号可点（点行任何位置等效），
      // 操作列第一个再加显式「预览」按钮，双入口都打开左侧详情抽屉
      {
        key: 'order_no',
        title: '出库单号',
        mono: true,
        width: 140,
        render: (row) => (
          <span className="doc-no-link" title="点击预览单据详情">
            {row.order_no}
          </span>
        ),
      },
      {
        key: 'customer_id',
        title: '客户',
        ellipsis: true,
        minWidth: 140,
        format: (value) => customers.find((item) => item.id === value)?.name || value,
      },
      {
        key: 'total_amount',
        title: '金额',
        width: 104,
        align: 'right',
        num: true,
        // 金额排在仓库/日期前面：右栏窄时横滚会把后面的列滚走，
        // 而金额是这张单最该一眼看到的数字（采购入库真机截图抓出来的同一个问题）
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
        // 多维状态分离（2026-10-20）：审核 / 收款 / 签收三列彩色徽标，
        // 钱和货的状态一眼分开，不再挤在一个词里
        key: 'audit_status',
        title: '审核',
        width: 84,
        render: (row) => <AuditBadge row={row} labels={OUTBOUND_STATUS_LABELS} />,
      },
      {
        key: 'pay_status',
        title: '收款',
        width: 110,
        render: (row) => <PayBadge row={row} />,
      },
      {
        key: 'ship_status',
        title: '签收',
        width: 84,
        hideBelow: 'md',
        render: (row) => <ShipBadge row={row} kind="signed" />,
      },
      {
        key: 'actions',
        title: '操作',
        // 2026-10-20 完结闸：196 → 384，新插入 收款/开票/完结 三个按钮（业务闭环：
        // 收款 → 开票 → 完结）。完结按钮的置灰是**业务规则**不是 UI 状态：
        // 只有后端 settled（应收余额≤0 且 未开票≤0）才放行。
        // 2026-10-21 加「预览」首位入口 + 单号可点（见 order_no 列注释）：384 → 440
        width: 440,
        minWidth: 440,
        align: 'right',
        sticky: 'right',
        nowrap: true,
        render: (row) => (
          <div className="row-actions">
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => setSelectedSalesOrder(row)}
              title="预览单据：客户、明细、物流签收、收票情况一眼看完"
            >
              预览
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => printPdf(`/print/sales-order/${row.id}`, `${row.order_no}.pdf`)}
            >
              打印
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => printPdf(`/print/delivery-note/${row.id}`, `送货单_${row.order_no}.pdf`)}
            >
              送货单
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => openOrderPayment(row, 'sales')}
              title="登记收款（实收冲减本单应收，超收转预收）"
            >
              收款
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              onClick={() => setInvoiceDialogRow(row)}
              title="登记销项发票（计入本单已开票金额）"
            >
              开票
            </button>
            <button
              type="button"
              className="primary-btn small-btn"
              disabled={!row.settled || row.status === 'completed'}
              title={
                row.status === 'completed'
                  ? '该单已完结'
                  : row.settled
                    ? '标记为已完结'
                    : COMPLETE_LOCKED_TITLE
              }
              onClick={() => updateSalesOrderStatus(row.id, 'completed')}
            >
              完结
            </button>
            <button
              type="button"
              className="danger-btn"
              onClick={() =>
                setConfirmDelete({
                  id: row.id,
                  endpoint: `/sales-orders/${row.id}`,
                  label: `销售出库单 ${row.order_no}`,
                  kind: 'sales-order',
                })
              }
            >
              删除
            </button>
          </div>
        ),
      },
    ],
    [
      DOC_STATUS_LABELS,
      OUTBOUND_STATUS_LABELS,
      COMPLETE_LOCKED_TITLE,
      customers,
      openOrderPayment,
      printPdf,
      setConfirmDelete,
      setInvoiceDialogRow,
      updateSalesOrderStatus,
      warehouses,
    ],
  );

  /** 详情弹窗里的明细：把服务端存的 `unit_factor` 快照也显示出来 */
  const detailColumns = useMemo(
    () => [
      {
        key: 'product_name',
        title: '商品',
        minWidth: 140,
        ellipsis: true,
        format: (value, row) => value || row.product_id,
      },
      { key: 'quantity', title: '数量', width: 68, align: 'right', num: true },
      {
        key: 'unit',
        title: '单位',
        width: 84,
        format: (value, row) => {
          const factor = Number(row.unit_factor) || 1;
          return factor > 1 ? `${value || '—'} ×${factor}` : value || '—';
        },
      },
      {
        key: 'unit_price',
        title: '单价',
        width: 84,
        align: 'right',
        num: true,
        format: (value) => money(value),
      },
      {
        key: 'amount',
        title: '金额',
        width: 92,
        align: 'right',
        num: true,
        format: (value, row) => money(value ?? (Number(row.quantity) || 0) * (Number(row.unit_price) || 0)),
      },
    ],
    [],
  );

  /** Delete 删行 —— 焦点在控件里时不删，否则打字删一个字符就把整行干掉 */
  const onLineKeyDown = (event) => {
    if (event.key !== 'Delete' || selectedLine === null) return;
    const tag = (event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    event.preventDefault();
    if (items.length <= 1) return;
    removeOutboundItem(selectedLine);
    setSelectedLine(null);
  };

  return (
    <>
      {/* ⚠️ 单据页必须给独立的 storageKey + 更高的 minLeft（2026-10-18）：
           · 默认 key `erp:mgrid:left` 是全站共用的，用户在客户档案把左栏拖到 300px 后，
          回到单据页也是 300px —— 明细表 min-width 600，直接被压成"一条 + 横滚"，
          商品搜索框只剩半截（用户截图报的就是这个）；
           · 660 = 明细表 600 + 卡片左右内边距 50，是这张表能放平的最小左栏宽度。 */}
      <ResizableLayout
        className="doc-page"
        storageKey="erp:mgrid:doc"
        minLeft={660}
      >
        <ErpCard title="新增销售出库单" subtitle="真实出库 · 写库存与应收">
          <form onSubmit={submitOutboundForm} data-doc-form="outbound" className="doc-form">
            <ErpFormGrid columns={2} gap="md">
              <ErpFormRow label="客户" required>
                {/* 客户档案可能几百条：平铺下拉改可搜索。
                    ⚠️ 原生 `required` 随 select 一起消失 —— 必填由 submitOutboundForm
                    （App.jsx `makeSubmitStockDoc` 里的 partyField 守卫）兜住，别删那个守卫。 */}
                <ErpSearchSelect
                  options={customers}
                  value={String(outboundForm.customer_id ?? '')}
                  onChange={(value) => handleOutboundFormChange('customer_id')({ target: { value } })}
                  placeholder="搜索客户名称 / 编码"
                  emptyText="没有匹配的客户"
                  getOptionValue={(item) => String(item.id)}
                  getOptionLabel={(item) => `${item.name}（${item.code}）`}
                  getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                />
                {renderPartyLink('customers', outboundForm.customer_id, '客户')}
              </ErpFormRow>

              <ErpFormRow label="出库仓库" required>
                <select
                  value={outboundForm.warehouse_id}
                  onChange={handleOutboundFormChange('warehouse_id')}
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
                  value={outboundForm.order_date}
                  onChange={handleOutboundFormChange('order_date')}
                />
              </ErpFormRow>

              <ErpFormRow label="收款方式">
                <input
                  list="lookup-payment-method"
                  value={outboundForm.payment_method}
                  onChange={handleOutboundFormChange('payment_method')}
                  placeholder="如：现金 / 微信 / 月结30天"
                />
              </ErpFormRow>

              {/* —— 物流流 + 签收（四流合一 2026-10-19）——
                  放在开单表单里，是因为现货开单常是"司机当场带回签收单"，
                  要等出库后再补录，十个里有八个会忘。
                  全部非必填：先发货后签收是常态，强制填只会让人乱填。 */}
              <ErpFormRow label="物流公司">
                <input
                  value={outboundForm.logistics_company}
                  onChange={handleOutboundFormChange('logistics_company')}
                  placeholder="如：顺丰 / 德邦 / 自送"
                  maxLength={100}
                />
              </ErpFormRow>

              <ErpFormRow label="物流单号">
                <input
                  value={outboundForm.logistics_no}
                  onChange={handleOutboundFormChange('logistics_no')}
                  placeholder="快递单号 / 运单号"
                  maxLength={100}
                />
              </ErpFormRow>

              <ErpFormRow label="签收人">
                <input
                  value={outboundForm.signed_by}
                  onChange={handleOutboundFormChange('signed_by')}
                  placeholder="客户方签字人姓名"
                  maxLength={50}
                />
              </ErpFormRow>

              <ErpFormRow label="签收时间">
                <input
                  type="datetime-local"
                  value={outboundForm.signed_at}
                  onChange={handleOutboundFormChange('signed_at')}
                />
              </ErpFormRow>

              <ErpFormRow label="备注" span={2}>
                <input
                  value={outboundForm.note}
                  onChange={handleOutboundFormChange('note')}
                  placeholder="如：送货地址、客户要求"
                />
              </ErpFormRow>
            </ErpFormGrid>

            <div className="doc-lines">
              <div className="doc-lines__head">
                <h3>商品明细</h3>
                <span className="doc-lines__hint">
                  {selectedLine === null
                    ? '点一行可选中，按 Delete 删行'
                    : `已选中第 ${selectedLine + 1} 行`}
                </span>
                <button type="button" className="secondary-btn small-btn" onClick={addOutboundItem}>
                  + 添加一行
                </button>
                {/* 2026-10-20 老系统 UX：复制选中行 / 批量选商品 */}
                <button
                  type="button"
                  className="secondary-btn small-btn"
                  onClick={() => copyOutboundItem(selectedLine)}
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
                  ariaLabel="销售出库明细"
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
                保存并出库
              </button>
            </ErpFormActions>
          </form>
        </ErpCard>

        <ErpCard
          title="销售出库单列表"
          subtitle={`${salesOrders.length} 张`}
          padding="md"
          flush
          divider
          extra={
            <button
              type="button"
              className="secondary-btn small-btn"
              data-open-history-import
              title="把老系统对账单 Excel 导成销售出库单（先预检再写库，已导过的单自动跳过）"
              onClick={() => setHistoryImportOpen(true)}
            >
              导入历史单
            </button>
          }
        >
          <ErpTable
            columns={orderColumns}
            rows={salesOrders}
            ariaLabel="销售出库单列表"
            minWidth={1000}
            onRowClick={(row) => setSelectedSalesOrder(row)}
            // 2026-10-20 详情抽屉配套：抽屉开着时高亮"正在看的那一行"，
            // 否则用户点来点去不知道自己看的是哪一单（用户实测反馈）
            rowClassName={(row) =>
              selectedSalesOrder && row.id === selectedSalesOrder.id ? 'doc-row--active' : ''
            }
            // 改造前每行是 tabIndex + Enter/空格 打开详情；声明式表格要把这层补回来
            rowProps={(row) => ({
              tabIndex: 0,
              onKeyDown: (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedSalesOrder(row);
                }
              },
            })}
            emptyProps={{
              variant: 'data',
              title: '还没有出库单',
              description: '这里登记的是真实出库（库存 + 应收），与「销售订单」的订货意向分开管理。',
            }}
          />
        </ErpCard>
      </ResizableLayout>

      {/* ⚠️ 详情弹窗必须在 ResizableLayout 外面：它是第 3 个子元素，
          放进去会让「恰好 2 个才可拖拽」的判定失败、整个网格静默降级。 */}
      <ArchiveImportDialog
        open={historyImportOpen}
        kind="sales-orders"
        onClose={() => setHistoryImportOpen(false)}
        onImported={() => refreshSalesOutboundList?.()}
      />
      {selectedSalesOrder && (
        /* 详情改右侧抽屉（2026-10-20）：**不加全屏遮罩** —— 财务对单是逐张核的
           高频动作，遮罩会把列表盖死只能"开→关→开→关"；现在列表保持可见可点，
           直接点别的行就切换详情。⚠️ 仍挂在 ResizableLayout 外面
           （放进去就是第 3 个子元素，网格拖拽静默失效）。 */
        <aside
          className="doc-drawer doc-detail"
          role="dialog"
          aria-label="销售出库单详情"
          data-doc-drawer="sales-outbound"
        >
            <div className="modal-header doc-drawer__head">
              <div className="doc-drawer__title">
                {/* 2026-10-20 视觉强化（用户反馈）：单号大字加粗 + 与列表同款三维徽标，
                    一眼确认"我看的是哪一单、它现在什么状态"，不再和背景表单混成一片 */}
                <span className="doc-drawer__label">销售出库单详情</span>
                <div className="doc-drawer__idline" data-drawer-idline>
                  <h3 className="doc-drawer__no">{detailRow.order_no}</h3>
                  <AuditBadge row={detailRow} labels={OUTBOUND_STATUS_LABELS} />
                  <PayBadge row={detailRow} />
                  <ShipBadge row={detailRow} kind="signed" />
                </div>
              </div>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setSelectedSalesOrder(null)}
              >
                关闭
              </button>
            </div>

            <div className="modal-body">
              <p>
                <strong>单号：</strong> {selectedSalesOrder.order_no}
              </p>
              <p>
                <strong>客户：</strong>{' '}
                {customers.find((item) => item.id === selectedSalesOrder.customer_id)?.name ||
                  selectedSalesOrder.customer_id}
              </p>
              <p>
                <strong>仓库：</strong>{' '}
                {warehouses.find((item) => item.id === selectedSalesOrder.warehouse_id)?.name || '—'}
              </p>
              <p>
                <strong>状态：</strong>{' '}
                {OUTBOUND_STATUS_LABELS[detailRow.status] || detailRow.status}
              </p>
              <p>
                <strong>金额：</strong> ¥{money(detailRow.total_amount)}
              </p>
              {/* 结算行：三个数全部来自后端 `settled` 同一口径（_apply_settlement_fields），
                  前端不自算 —— 自算必然出现"前端说能完结、后端 409"的两张皮。 */}
              <p className="doc-detail__settlement" data-settlement-line>
                <strong>结算：</strong>
                {Number(detailRow.outstanding_amount || 0) > 0
                  ? `应收余额 ¥${Number(detailRow.outstanding_amount).toFixed(2)}`
                  : '应收已结清'}
                {' · '}
                {Number(detailRow.uninvoiced_amount || 0) > 0
                  ? `未开票 ¥${Number(detailRow.uninvoiced_amount).toFixed(2)}`
                  : '已开齐'}
                {detailRow.settled ? '（可完结）' : `（${COMPLETE_LOCKED_TITLE}）`}
              </p>

              {/* 物流 / 签收：既显示也当场可改 —— 签收大多发生在出库之后，
                  只读展示等于逼用户回列表再找一遍这张单。 */}
              <LogisticsSection
                key={selectedSalesOrder.id}
                order={selectedSalesOrder}
                onSave={saveSalesOrderLogistics}
              />

              <ErpTable
                dense
                columns={detailColumns}
                rows={selectedSalesOrder.items || []}
                rowKey={(_row, index) => index}
                ariaLabel="销售出库单明细"
                minWidth={480}
                emptyProps={{ variant: 'data', title: '这张单没有明细行' }}
              />
              <p className="doc-detail__hint">
                单位后的 <code>×N</code> 是保存时后端写入的 <code>unit_factor</code> 快照 ——
                换算率在开单那一刻就固定下来，日后改档案不影响历史单据。
              </p>
            </div>

            {/* 三按钮 = 业务闭环顺序：收款 → 开票 → 完结。
                ⚠️ 完结的 disabled 读的是 canComplete（来自 detailRow = 最新列表），
                收款/开票成功后列表重拉，按钮会当场解禁 —— 用旧快照就会"收了钱还是灰的"。 */}
            <div className="modal-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => openOrderPayment(detailRow, 'sales')}
              >
                收款
              </button>
              {/* 一键开票（2026-10-22，先销后票）：
                  金额取后端算好的未开票余额、明细取本单明细、related_order_id 由服务端挂 ——
                  三件都不用人填。原「开票」弹窗保留在旁边，用于要精确录真实票号的场景。 */}
              <button
                type="button"
                className="primary-btn"
                disabled={issueBusy || Number(detailRow.uninvoiced_amount || 0) <= 0}
                title={
                  Number(detailRow.uninvoiced_amount || 0) > 0
                    ? `按本单明细生成销项发票（未开票 ¥${Number(detailRow.uninvoiced_amount || 0).toFixed(2)}）`
                    : '本单已开齐，无需再开票'
                }
                data-issue-invoice={detailRow.id}
                onClick={() => issueInvoiceOneClick(detailRow)}
              >
                {issueBusy ? '开票中…' : '一键开票'}
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setInvoiceDialogRow(detailRow)}
              >
                登记票号
              </button>
              <button
                type="button"
                className="primary-btn"
                disabled={!canComplete}
                title={canComplete ? '标记为已完结' : COMPLETE_LOCKED_TITLE}
                onClick={async () => {
                  const success = await updateSalesOrderStatus(detailRow.id, 'completed');
                  if (success) {
                    setSelectedSalesOrder(null);
                  }
                }}
              >
                标记为已完结
              </button>
            </div>
        </aside>
      )}

      {/* 开票登记弹窗：必须与详情弹窗同级、挂在 ResizableLayout **外面** ——
          放进去就成了第 3 个子元素，整个网格静默降级成不可拖拽。
          row 同样从最新列表现取（快照里的 uninvoiced_amount 可能已过期）。 */}
      {invoiceDialogRow && (
        <InvoiceQuickDialog
          row={salesOrders.find((item) => item.id === invoiceDialogRow.id) || invoiceDialogRow}
          customers={customers}
          apiBase={API_BASE}
          authHeaders={authHeaders}
          onClose={() => setInvoiceDialogRow(null)}
          onSaved={(invoice) => {
            setInvoiceDialogRow(null);
            // 已开票金额变了 → settled / 完结按钮都可能跟着变，必须重拉
            refreshSalesOutboundList();
            setNotice(
              `发票 ${invoice?.invoice_no || ''} 已登记（销项，挂单据 ${invoiceDialogRow.order_no}）。`,
            );
          }}
        />
      )}

      {/* 批量选商品弹窗：同样必须挂 ResizableLayout 外面（第 3 个子元素会让拖拽静默失效） */}
      {productPickerOpen && (
        <ProductMultiSelectModal
          products={products}
          onClose={() => setProductPickerOpen(false)}
          onConfirm={(productIds) => {
            addProductsToOutbound(productIds);
            setProductPickerOpen(false);
          }}
        />
      )}
    </>
  );
}

/** 该商品的基本单位名（行上没选商品时返回空串，不硬造"盒"） */
function baseUnitOf(row, unitOptionsFor) {
  const options = unitOptionsFor(row.product_id) || [];
  const base = options.find((option) => option.isBase);
  return base ? base.name : '';
}

/**
 * 把后端返回的 ISO 时间转成 <input type="datetime-local"> 认识的值。
 *
 * 为什么不能直接把 ISO 串塞进 value：datetime-local 只认 `YYYY-MM-DDTHH:mm`
 * （带秒/带时区/带 Z 都会被浏览器判成非法值、显示成空）。
 * 而"空"在用户眼里就是"没登记过" —— 一个格式问题会被误读成数据丢失。
 */
function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * 出库单详情里的「物流 / 签收」区块（可编辑）。
 *
 * 独立成组件是为了让表单状态跟着**单据 id** 走（外层用 key={id} 强制重挂载）：
 * 点开另一张单时，输入框里必须是那张单的值，不能残留上一张的签收人。
 */
function LogisticsSection({ order, onSave }) {
  const [form, setForm] = useState(() => ({
    logistics_company: order.logistics_company || '',
    logistics_no: order.logistics_no || '',
    signed_by: order.signed_by || '',
    signed_at: toLocalInput(order.signed_at),
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const setField = (field) => (event) => {
    const { value } = event.target;
    setForm((prev) => ({ ...prev, [field]: value }));
    setError('');
  };

  const submit = async () => {
    if (typeof onSave !== 'function') {
      setError('页面没有接上保存动作（ctx.saveSalesOrderLogistics 缺失）');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const ok = await onSave(order.id, {
        logistics_company: form.logistics_company.trim() || null,
        logistics_no: form.logistics_no.trim() || null,
        signed_by: form.signed_by.trim() || null,
        signed_at: form.signed_at || null,
      });
      if (!ok) setError('保存失败，请查看顶部提示');
    } finally {
      setBusy(false);
    }
  };

  const signed = Boolean(order.signed_at);

  return (
    <section className="doc-logistics" data-logistics-section>
      <header className="doc-logistics__head">
        <h4>物流 / 签收</h4>
        <span className={`status-badge ${signed ? 'ok' : 'muted'}`}>
          {signed ? '已签收' : '未签收'}
        </span>
      </header>

      <div className="doc-logistics__grid">
        <label>
          <span>物流公司</span>
          <input
            value={form.logistics_company}
            onChange={setField('logistics_company')}
            placeholder="如：顺丰 / 德邦 / 自送"
            maxLength={100}
          />
        </label>
        <label>
          <span>物流单号</span>
          <input
            value={form.logistics_no}
            onChange={setField('logistics_no')}
            placeholder="快递单号 / 运单号"
            maxLength={100}
          />
        </label>
        <label>
          <span>签收人</span>
          <input
            value={form.signed_by}
            onChange={setField('signed_by')}
            placeholder="客户方签字人"
            maxLength={50}
          />
        </label>
        <label>
          <span>签收时间</span>
          <input type="datetime-local" value={form.signed_at} onChange={setField('signed_at')} />
        </label>
      </div>

      {error ? (
        <p className="doc-logistics__error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="doc-logistics__actions">
        <button type="button" className="primary-btn small-btn" onClick={submit} disabled={busy}>
          {busy ? '保存中…' : signed ? '更新物流/签收' : '登记签收'}
        </button>
        <span className="doc-logistics__hint">
          签收时间留空 = 这张单回到「未签收」；不允许填未来时间。
        </span>
      </div>
    </section>
  );
}

/**
 * 开票登记弹窗（完结闸第二步，2026-10-20）。
 *
 * 为什么不跳「发票管理」页：现货开单的常态是"货送到了、票当场开"，让人切页面、
 * 找单、再关联一遍，十个里九个直接不录 —— 完结闸就永远过不去。
 * 所以这里只收最少的四个字段，落库口径与发票管理完全一致（POST /invoices）。
 *
 * 防呆（两条都是真会咬人的）：
 * ① **同号预检**：后端 POST /invoices 遇到相同发票号码会**删旧建新**（OCR 上传
 *    的幂等设计）。在这里抄错一位号码，就会把库里那张真发票顶掉 —— 所以保存前
 *    先按号码精确查重，命中就拦下并说明原因。
 * ② **金额预填**：默认填后端算好的 `uninvoiced_amount`（本单还没开票的钱），
 *    可改小做分次开票；填超过未开票的数，后端 settled 口径会把本单判成"已开齐"，
 *    与实际票面不符 —— 所以这里不做上限校验，但结算行会如实显示。
 *
 * 落库必须带 `related_order_id`：完结闸的"已开票"就是按它聚合的（erp_sales
 * `_invoiced_amounts_by_order`），不挂单的发票对完结闸不可见。
 */
function InvoiceQuickDialog({ row, customers, apiBase, authHeaders, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({
    invoice_no: '',
    invoice_type: '普票',
    issue_date: new Date().toISOString().slice(0, 10),
    total_amount:
      Number(row.uninvoiced_amount || 0) > 0 ? Number(row.uninvoiced_amount).toFixed(2) : '',
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const setField = (field) => (event) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
    setError('');
  };

  const submit = async () => {
    const invoiceNo = String(form.invoice_no || '').trim();
    if (!invoiceNo) {
      setError('请填写发票号码。');
      return;
    }
    const amount = Number(form.total_amount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setError('开票金额必须是大于 0 的数字。');
      return;
    }

    setBusy(true);
    setError('');
    try {
      // ① 同号预检：命中即拦（见上方防呆说明）
      const check = await fetch(
        `${apiBase}/invoices?keyword=${encodeURIComponent(invoiceNo)}`,
        { headers: authHeaders() },
      );
      if (check.ok) {
        const data = await check.json();
        const hit = (data.items || []).find((item) => String(item.invoice_no) === invoiceNo);
        if (hit) {
          setError(
            `发票号码 ${invoiceNo} 已存在（${hit.issue_date || '日期未知'}，¥${Number(
              hit.total_amount || 0,
            ).toFixed(2)}）。保存同号发票会顶掉这条记录，请核实号码，或先到「发票管理」处理那张票。`,
          );
          setBusy(false);
          return;
        }
      }

      // ② 落库：销项 + 挂本单
      const customer = customers.find((item) => item.id === row.customer_id);
      const response = await fetch(`${apiBase}/invoices`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          invoice_no: invoiceNo,
          invoice_type: form.invoice_type,
          issue_date: form.issue_date || null,
          total_amount: amount,
          direction: 'output',
          customer_id: row.customer_id ?? null,
          buyer_name: customer?.name || null,
          related_order_id: row.id,
        }),
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({ detail: '开票登记失败' }));
        const d = errData.detail;
        // FastAPI 422 的 detail 是数组；完结闸类 409 的 detail 是对象 —— 三种都要接住
        const message =
          typeof d === 'string'
            ? d
            : Array.isArray(d)
              ? d.map((item) => item?.msg || item).join('；')
              : (d && d.message) || '开票登记失败';
        throw new Error(message);
      }
      const invoice = await response.json();
      onSaved(invoice);
    } catch (err) {
      setError(err.message || '开票登记失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>开票登记 · {row.order_no}</h3>
          <button type="button" className="secondary-btn small-btn" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="modal-body">
          <p className="doc-detail__hint">
            本单未开票金额 ¥{Number(row.uninvoiced_amount || 0).toFixed(2)}
            （开齐后才能标记为已完结）。金额已按此预填，可改小做分次开票。
          </p>
          <div className="doc-logistics__grid">
            <label>
              <span>发票号码</span>
              <input
                value={form.invoice_no}
                onChange={setField('invoice_no')}
                placeholder="发票右上角的号码"
                maxLength={40}
              />
            </label>
            <label>
              <span>发票类型</span>
              <select value={form.invoice_type} onChange={setField('invoice_type')}>
                <option value="普票">普票</option>
                <option value="专票">专票</option>
                <option value="电子普票">电子普票</option>
                <option value="电子专票">电子专票</option>
              </select>
            </label>
            <label>
              <span>开票日期</span>
              <input type="date" value={form.issue_date} onChange={setField('issue_date')} />
            </label>
            <label>
              <span>开票金额（价税合计）</span>
              <input
                type="number"
                step="any"
                min="0"
                value={form.total_amount}
                onChange={setField('total_amount')}
              />
            </label>
          </div>
          {error ? (
            <p className="doc-logistics__error" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <div className="modal-actions">
          <button type="button" className="primary-btn" onClick={submit} disabled={busy}>
            {busy ? '登记中…' : '登记开票'}
          </button>
        </div>
      </div>
    </div>
  );
}
