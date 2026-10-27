/**
 * OrderBoard —— 「采购订单 / 销售订单」整页 UI（第三步-B 第三、四家）
 *
 * 为什么两页共用一个组件：
 *   改造前 `PurchaseOrderPage.jsx` 与 `SalesOrderPage.jsx` **各 1133 行、逐字同构**，
 *   差异只有 6 处（称谓、提交函数、转单函数、打印路径、列表数据源、空态文案）。
 *   各写一遍必然漂移 —— 事实上它们已经漂了：两页的明细行都是 `.form-row.three-col`
 *   却塞了 4 个控件，页面上从来没有「删行」按钮，而 App.jsx 里
 *   `removePurchaseOrderItem` / `removeSalesOrderItem` 早就写好了却没人调用（死代码）。
 *   所以这里用 `CONFIG` 收口，第 4 家不可能跟第 3 家长得不一样。
 *
 * ══════════════════════════════════════════════════════════════════════════
 * 「转入库单 / 转开单」——本轮**重点保护**的业务动作
 * ══════════════════════════════════════════════════════════════════════════
 * 订单只是订货意向（`doc_type=order`，不动库存、不动应收应付）；真正写库存与账款
 * 的是转出来的那张出入库单。链路：
 *
 *   按钮 → `convertPurchaseOrder(row)` / `convertSalesOrder(row)`（App.jsx:4808 / 4829）
 *        → POST `/purchase-orders/{id}/to-inbound`（销售侧 `/sales-orders/{id}/to-outbound`）
 *        → 订单状态置 completed、新单 unshift 进门面列表、notice 提示单号
 *
 * 三处**绝不能丢**的既有约束，都原样保留：
 *   ① `row.status !== 'completed'` 才显示「转入库单」「删除」——
 *      已转单的订单不能重复转、也不能删（后端有库存/账款引用）。
 *   ② 「打印」对**所有**状态都可用（含已转单历史单据）。
 *   ③ 转单是**真实副作用**，不是预览。本轮加的两个保护都不改变流程：
 *      · `convertingId` 在请求飞行期间禁用按钮 —— 原来双击会发两次 POST，
 *        等于同一张订单转出两张入库单、库存与应付双记；
 *      · 已转单的行不再"按钮凭空消失"，改显示「已转入库 / 已转开单」灰标 ——
 *        原来按钮消失看起来像 bug，现在是明确的状态。
 *      仍然保持**单击即转**（没有加二次确认弹窗，不改动既有交互节奏）。
 *
 * 与采购入库相同的标准：表头 `ErpFormGrid/ErpFormRow`、明细 `ErpTable dense`
 * （render 插槽放控件 + footer 合计 + 点行选中/Delete 删行）、列表 `ErpTable`
 * （操作列 sticky）。零业务逻辑改动：提交、单位解析、库存提示、跳档案全部沿用 ctx。
 */

import { useMemo, useState } from 'react';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import ErpMoreMenu from '../ui/ErpMoreMenu.jsx';
import ErpDrawer from '../ui/ErpDrawer.jsx';
import ErpKpiStrip from '../ui/ErpKpiStrip.jsx';
import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import { itemRowError } from '../../lib/orderLines';
// 订单专用状态标签与分组（2026-10-18 单步审核）。**不要**改用 ctx 里的
// DOC_STATUS_LABELS —— 那张表给生产单/盘点/调拨用，中文口径不一样。
import { orderStatusGroup, orderStatusLabel } from '../../lib/appLib';
import { ShipBadge } from './StatusBadges.jsx';
import ProductMultiSelectModal from './ProductMultiSelectModal.jsx';
import LineColConfigModal from './LineColConfigModal.jsx';
import './docs.css';

const money = (value) =>
  Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * 两页的全部差异都在这里。加第三类订单（比如「委外订单」）只需再加一条。
 *
 * ⚠️ `convert*` 的名字必须与 App.jsx 暴露到 ctx 的函数一致 —— 这里按名字从 ctx 取，
 *    写错了会在点击时抛 "is not a function"，验证台有一条专门断言它可点。
 */
const ORDER_CONFIG = {
  purchase: {
    docForm: 'purchase-order',
    formKey: 'purchaseOrderForm',
    listKey: 'purchaseOrderList',
    partyField: 'supplier_id',
    partyLabel: '供应商',
    partnerListKey: 'suppliers',
    partnerLinkType: 'suppliers',
    title: '新增采购订单',
    subtitle: '只订货 · 不动库存',
    listTitle: '采购订单列表',
    warehouseLabel: '进货仓库（转单时生效）',
    warehousePlaceholder: '转单时再选',
    // 选供应商自动带出：地址字段的业务叫法（销售叫送货、采购叫收货）
    addressLabel: '收货地址',
    notePlaceholder: '如：交期要求、随货资料',
    submitLabel: '保存采购订单',
    // —— 审核 / 转单 ——
    // approveKey 必须与 App.jsx 暴露到 ctx 的函数同名（同 convertKey 的约定）
    approveKey: 'approvePurchaseOrder',
    auditTitle: '审核通过后才能转入库单',
    convertKey: 'convertPurchaseOrder',
    convertLabel: '转入库单',
    convertedLabel: '已转入库',
    convertTitle: '按本单明细生成采购入库单：会真正写库存与应付，订单随即置为已转单',
    convertLockedTitle: '先点「审核」通过后，才能转入库单',
    // —— 付款 ——
    payLabel: '付款',
    payField: 'paid_amount', // 采购侧字段叫 paid_amount（销售侧是 received_amount）
    payTitle: '登记一笔付款：写资金流水 + 冲减订单欠款，对账单「本期已付」取这里',
    printPath: (id) => `/print/purchase-order/${id}`,
    printName: (row) => `采购订单_${row.order_no}.pdf`,
    deleteEndpoint: (id) => `/purchase-orders/${id}`,
    deleteKind: 'purchase-order',
    deleteLabel: (row) => `采购订单 ${row.order_no}`,
    emptyText: '暂无采购订单。订单只确认订货意向，转入库单后才登记库存与应付。',
  },
  sales: {
    docForm: 'sales-order',
    formKey: 'salesOrderForm',
    listKey: 'salesOrderList',
    partyField: 'customer_id',
    partyLabel: '客户',
    partnerListKey: 'customers',
    partnerLinkType: 'customers',
    title: '新增销售订单',
    subtitle: '只订货 · 不动库存',
    listTitle: '销售订单列表',
    warehouseLabel: '出货仓库（转单时生效）',
    warehousePlaceholder: '转单时再选',
    // 选客户自动带出：地址字段的业务叫法
    addressLabel: '送货地址',
    notePlaceholder: '如：送货地址、客户要求',
    submitLabel: '保存销售订单',
    // —— 审核 / 转单 ——
    approveKey: 'approveSalesOrder',
    auditTitle: '审核通过后才能转开单',
    convertKey: 'convertSalesOrder',
    convertLabel: '转开单',
    convertedLabel: '已转开单',
    convertTitle: '按本单明细生成销售出库单：会真正扣库存、记应收，订单随即置为已转单',
    convertLockedTitle: '先点「审核」通过后，才能转开单',
    // —— 收款 ——
    payLabel: '收款',
    payField: 'received_amount',
    payTitle: '登记一笔收款：写资金流水 + 冲减订单欠款，对账单「本期已收」取这里',
    printPath: (id) => `/print/sales-order/${id}`,
    printName: (row) => `销售订单_${row.order_no}.pdf`,
    deleteEndpoint: (id) => `/sales-orders/${id}`,
    deleteKind: 'sales-order',
    deleteLabel: (row) => `销售订单 ${row.order_no}`,
    emptyText: '暂无销售订单。订单只确认订货意向，转开单后才扣库存、记应收。',
  },
};

export default function OrderBoard({ ctx, kind = 'purchase' }) {
  const cfg = ORDER_CONFIG[kind];

  const {
    printPdf,
    products,
    projects,
    renderPartyLink,
    renderStockHint,
    setConfirmDelete,
    unitOptionsFor,
    warehouses,
  } = ctx;

  const form = ctx[cfg.formKey];
  const list = ctx[cfg.listKey] || [];
  const partners = ctx[cfg.partnerListKey] || [];

  // 四个 handler 也按命名约定从 ctx 取（两页命名完全对称）
  const handlerPrefix = kind === 'purchase' ? 'PurchaseOrder' : 'SalesOrder';
  const handleFormChange = ctx[`handle${handlerPrefix}FormChange`];
  const handleItemChange = ctx[`handle${handlerPrefix}ItemChange`];
  const addItem = ctx[`add${handlerPrefix}Item`];
  const removeItem = ctx[`remove${handlerPrefix}Item`];
  // 2026-10-20 老系统 UX：复制行 / 批量选商品（ctx 命名约定与 add/remove 对称）
  const copyItem = ctx[`copy${handlerPrefix}Item`];
  const addProducts = ctx[`addProductsTo${handlerPrefix}`];
  const submitForm = ctx[`submit${handlerPrefix}Form`];
  const convertOrder = ctx[cfg.convertKey];
  // 审核与收付款：下一步（收款弹窗）接进来前，`openOrderPayment` 由 App.jsx 提供一个
  // 只提示"未接入"的占位实现；缺了它按钮会静默无反应，所以这里再兜一层。
  const approveOrder = ctx[cfg.approveKey];
  // 反审核（2026-10-20 老系统 UX）：sales/purchase 两侧同一命名约定
  const unsubmitOrder = kind === 'purchase' ? ctx.unsubmitPurchaseOrder : ctx.unsubmitSalesOrder;
  const openOrderPayment = ctx.openOrderPayment;

  // ── 选客带出（2026-10-21 老系统 UX 下沉）────────────────────────────────
  // 选中客户/供应商后，把 联系人 / 电话 / 地址 回填到**空字段**：
  // 只补空、绝不覆盖手填值 —— 老系统的坑就是改完手输又被带出值冲掉。
  const handlePartyPicked = (value) => {
    const picked = partners.find((item) => String(item.id) === String(value));
    handleFormChange(cfg.partyField)({ target: { value } });
    if (!picked) return;
    const autoFill = {
      contact: picked.contact,
      contact_phone: picked.contact_phone || picked.phone,
      address: picked.address,
    };
    for (const [field, val] of Object.entries(autoFill)) {
      if (val && !String(form[field] || '').trim()) {
        handleFormChange(field)({ target: { value: val } });
      }
    }
  };

  const [selectedLine, setSelectedLine] = useState(null);
  // 批量选商品弹窗（2026-10-20 老系统 UX 升级）
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  /** 正在转单的行 id —— 请求飞行期间禁用按钮，避免双击转出两张单 */
  const [convertingId, setConvertingId] = useState(null);
  /** 正在审核的行 id —— 同上，防双击 */
  const [auditingId, setAuditingId] = useState(null);
  /**
   * 详情抽屉里正在看的订单（2026-10-26）。
   *
   * 存的**就是列表行本身**：后端 `/sales-orders` 返回的 SalesOrderRead 已经带
   * `items`（行数那一列就是数它），所以点单号不必再发一次详情请求 —— 少一次
   * "列表说 3 行、抽屉显示 2 行"的对不上风险。
   * 只读快照：抽屉开着时别处改了状态，这里不会自动刷新，重新点一次即可。
   */
  const [detailOrder, setDetailOrder] = useState(null);
  // ── 紧凑表头（2026-10-21 老系统 UX 下沉）───────────────────────────────
  // 老系统录单页表头能折叠：行数多时收起表头，把屏幕留给明细。
  const [formCollapsed, setFormCollapsed] = useState(false);
  // ── 明细列配置（同上）──────────────────────────────────────────────────
  // 隐藏清单存 localStorage，销售/采购各存各的；商品列与操作列永远显示。
  const colStoreKey = `erp:doccols:${kind}`;
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [hiddenCols, setHiddenCols] = useState(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(`erp:doccols:${kind}`) || 'null');
      return Array.isArray(raw?.hidden) ? raw.hidden : [];
    } catch {
      return [];
    }
  });
  const toggleLineCol = (key) =>
    setHiddenCols((prev) => {
      const next = prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key];
      try {
        localStorage.setItem(colStoreKey, JSON.stringify({ hidden: next }));
      } catch {
        /* 隐私模式写不进去就算了：本次会话内仍然生效 */
      }
      return next;
    });
  const resetLineCols = () => {
    setHiddenCols([]);
    try {
      localStorage.removeItem(colStoreKey);
    } catch {
      /* 同上 */
    }
  };

  const items = form.items || [];
  const filled = items.filter((row) => row.product_id).length;
  const total = items.reduce(
    (sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0),
    0,
  );

  const lineColumns = useMemo(
    () => [
      {
        key: 'product_id',
        title: '商品',
        // 与出入库同一套列宽契约：商品列是主列，数量/单位/单价收窄让位
        minWidth: 260,
        render: (row, index) => (
          <div className="doc-line-product">
            <ErpSearchSelect
              options={products}
              value={String(row.product_id ?? '')}
              onChange={handleItemChange(index, 'product_id')}
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
            onChange={handleItemChange(index, 'quantity')}
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
              onChange={handleItemChange(index, 'unit')}
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
            onChange={handleItemChange(index, 'unit_price')}
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
              onClick={() => copyItem(index)}
              disabled={!row.product_id}
              title={row.product_id ? '复制此行到末尾（数量重置 1）' : '空行不能复制'}
            >
              复制
            </button>
            <button
              type="button"
              className="danger-btn small-btn row-remove-btn"
              onClick={() => {
                removeItem(index);
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
    [products, items.length, handleItemChange, removeItem, copyItem, renderStockHint, unitOptionsFor],
  );

  // 列配置生效：商品列与操作列永远显示，其余按隐藏清单过滤。
  // footer 的 colSpan 也要跟着可见列数走 —— 写死 4 会把合计挤到表格外面。
  const visibleLineColumns = useMemo(
    () => lineColumns.filter((col) => col.key === 'product_id' || col.key === 'actions' || !hiddenCols.includes(col.key)),
    [lineColumns, hiddenCols],
  );
  // 标签格跨的列数 = 可见数据列 - 1（金额格单独一格放合计）
  const totalLabelSpan = Math.max(1, visibleLineColumns.filter((col) => col.key !== 'actions').length - 1);

  const orderColumns = useMemo(
    () => [
      {
        key: 'order_no',
        title: '订单号',
        mono: true,
        width: 140,
        // 2026-10-26：单号可点 → 只读详情抽屉（与「开单管理」点单号看详情同一手感）。
        // stopPropagation 兜底：这行将来若加 onRowClick，点单号只该开一次。
        render: (row) => (
          <button
            type="button"
            className="link-btn doc-no-link-btn"
            style={{ padding: 0, font: 'inherit', background: 'none', border: 'none' }}
            title="查看订单详情"
            data-order-detail={row.id}
            onClick={(event) => {
              event.stopPropagation();
              setDetailOrder(row);
            }}
          >
            {row.order_no}
          </button>
        ),
      },
      {
        key: cfg.partyField,
        title: cfg.partyLabel,
        ellipsis: true,
        minWidth: 150,
        format: (value) => partners.find((item) => item.id === value)?.name || value,
      },
      {
        key: 'total_amount',
        title: '金额',
        width: 104,
        align: 'right',
        num: true,
        format: (value) => `¥${Number(value || 0).toLocaleString()}`,
      },
      { key: 'items', title: '行数', width: 64, align: 'right', num: true, format: (v) => (v?.length ?? 0) },
      {
        key: 'delivery_date',
        title: '送货日期',
        hideBelow: 'md',
        width: 108,
        ellipsis: true,
        fallback: '—',
      },
      {
        // 多维状态分离（2026-10-20）：审核 / 收款 / 转单三列。审核沿用
        // order-status 专属配色；收款口径与本页操作列的判断完全一致（payField）；
        // 转单只认 completed（转单由后端直写，别在前端猜中间态）
        key: 'status',
        title: '审核',
        width: 96,
        render: (row) => {
          const group = orderStatusGroup(row.status);
          return (
            <span className={`status-badge order-status order-status--${group || 'unknown'}`} data-order-status>
              {orderStatusLabel(row.status)}
            </span>
          );
        },
      },
      {
        key: 'pay_status',
        title: cfg.payLabel,
        width: 96,
        render: (row) => {
          const settledAmount = Number(row[cfg.payField] || 0);
          const payable = Number(row.total_amount || 0) - Number(row.discount_amount || 0);
          const settled = payable > 0 && settledAmount >= payable - 0.005;
          if (settled) return <span className="status-badge ok">已收清</span>;
          if (settledAmount > 0) return <span className="status-badge warn">部分收款</span>;
          return <span className="status-badge muted">未收款</span>;
        },
      },
      {
        key: 'convert_status',
        title: '转单',
        width: 84,
        hideBelow: 'md',
        render: (row) => <ShipBadge row={row} kind="convert" />,
      },
      {
        key: 'actions',
        title: '操作',
        // v1.78.0：打印 / 反审核 / 删除 收进行尾 ⋯ 后，操作列只要放
        // 「审核 → 转单 → 收款」主链路 + ⋯（352 → 264）。
        // 省下的 88px 还给客户/金额列 —— 右栏 696px 里这是实打实的一列钱。
        width: 264,
        align: 'right',
        sticky: 'right',
        nowrap: true,
        render: (row) => {
          // ⚠️ 这一坨是本页真正的业务核心：审核 → 转单 → 收款 → 删除。
          //   状态判断统一走 `orderStatusGroup()`，与后端 `app/core/doc_status.py`
          //   的 flow 一一对应（submitted 在订单上就是 pending，标签显示「待审核」）。
          const group = orderStatusGroup(row.status);
          const converted = group === 'completed';
          const approved = group === 'approved';
          const needsAudit = group === 'pending';
          const busy = convertingId === row.id;
          const auditing = auditingId === row.id;
          const settledAmount = Number(row[cfg.payField] || 0);
          const payable = Number(row.total_amount || 0) - Number(row.discount_amount || 0);
          // 分位容差：金额是 numeric(12,2)，避免 99.999999 判成未结清
          const settled = payable > 0 && settledAmount >= payable - 0.005;
          return (
            <div className="row-actions order-actions">
              {needsAudit ? (
                // 只有「待审核」（库里可能是 submitted 或 pending）才出现审核按钮
                <button
                  type="button"
                  className="primary-btn small-btn order-audit-btn"
                  title={cfg.auditTitle}
                  data-order-audit={row.id}
                  disabled={auditing}
                  onClick={async () => {
                    if (auditing) return;
                    setAuditingId(row.id);
                    try {
                      await approveOrder(row);
                    } finally {
                      setAuditingId(null);
                    }
                  }}
                >
                  {auditing ? '审核中…' : '审核'}
                </button>
              ) : null}
              {/* 反审核（2026-10-20）：审核过了但还没转单/没收付钱 → 可退回草稿。
                  后端闸口兜底：有库存/资金流水一律 409，前端只做显隐。
                  v1.78.0：低频动作收进行尾 ⋯（见下方 ErpMoreMenu），
                  主链路「审核 → 转单 → 收款」不再被灰按钮淹没。 */}
              {converted ? (
                // 已转单：显式说明，而不是让按钮凭空消失（原来那样看起来像 bug）
                <span className="doc-converted-tag" title="本单已生成出入库单，不能再转或删">
                  {cfg.convertedLabel}
                </span>
              ) : (
                <>
                  <button
                    type="button"
                    className="secondary-btn small-btn doc-convert-btn"
                    title={approved ? cfg.convertTitle : cfg.convertLockedTitle}
                    // 未审核一律禁用：后端也会 409，前端不给"点了才报错"的体验
                    disabled={busy || !approved}
                    data-order-convert={row.id}
                    onClick={async () => {
                      if (busy || !approved) return;
                      setConvertingId(row.id);
                      try {
                        await convertOrder(row);
                      } finally {
                        setConvertingId(null);
                      }
                    }}
                  >
                    {busy ? '转单中…' : cfg.convertLabel}
                  </button>
                </>
              )}
              {approved || converted ? (
                settled ? (
                  <span className="order-paid-tag" title={`已${cfg.payLabel === '收款' ? '收' : '付'} ¥${money(settledAmount)}`}>
                    已结清
                  </span>
                ) : (
                  <button
                    type="button"
                    className="secondary-btn small-btn order-pay-btn"
                    title={cfg.payTitle}
                    data-order-pay={row.id}
                    onClick={() => openOrderPayment?.(row, kind)}
                  >
                    {cfg.payLabel}
                  </button>
                )
              ) : null}

              {/* 收尾动作收进 ⋯（v1.78.0 UI 标准）：
                  打印对所有状态可用（含已转单历史单据）；反审核只对「已审核未转单」；
                  删除只对未转单（后端有库存/账款引用，转了就不给删）。
                  三条原有的显隐与权限规则一条没改，只是换了个落点。 */}
              <ErpMoreMenu
                testId={`order-${row.id}`}
                title="打印 / 反审核 / 删除"
                items={[
                  {
                    key: 'print',
                    label: '打印 PDF',
                    hint: cfg.printName(row),
                    onSelect: () => printPdf(cfg.printPath(row.id), cfg.printName(row)),
                  },
                  approved
                    ? {
                        key: 'unaudit',
                        label: '反审核',
                        hint: '退回草稿，可改后重新审核',
                        attrs: { 'data-order-unaudit': row.id },
                        onSelect: () => unsubmitOrder(row),
                      }
                    : null,
                  !converted
                    ? {
                        key: 'delete',
                        label: '删除本单',
                        hint: '仅未转单的订单可删',
                        danger: true,
                        onSelect: () =>
                          setConfirmDelete({
                            id: row.id,
                            endpoint: cfg.deleteEndpoint(row.id),
                            label: cfg.deleteLabel(row),
                            kind: cfg.deleteKind,
                          }),
                      }
                    : null,
                ].filter(Boolean)}
              />
            </div>
          );
        },
      },
    ],
    [
      cfg,
      partners,
      printPdf,
      setConfirmDelete,
      setDetailOrder,
      convertingId,
      auditingId,
      convertOrder,
      approveOrder,
      unsubmitOrder,
      openOrderPayment,
      kind,
    ],
  );

  /**
   * 列表卡顶部的 KPI 计量条（v1.78.0 UI 标准铺开）。
   *
   * 口径说明：只统计**本页已加载的 list**，不是全库 —— 这是「眼前这批单」的
   * 体检表，每一格都能在下面表格里对上号。全库口径在「报表 / 分析」看。
   * 待审核/已转单走 `orderStatusGroup()`（与后端 doc_status.py 的 flow 同源），
   * 不自己拍 status 字符串，避免哪天后端多加一个状态这里就统计漏。
   */
  const kpiItems = useMemo(() => {
    let pending = 0;
    let converted = 0;
    let unsettled = 0;
    let unpaidAmount = 0;
    let totalAmount = 0;

    list.forEach((row) => {
      const group = orderStatusGroup(row.status);
      // 与行内「已结清」判定同一口径：total - discount，2 位小数容差
      const payable = Number(row.total_amount || 0) - Number(row.discount_amount || 0);
      const paid = Number(row[cfg.payField] || 0);
      totalAmount += payable;
      if (group === 'pending') pending += 1;
      if (group === 'completed') converted += 1;
      // 未审核的单还没有应收/应付，不算"未结清"（否则新单全被算成欠款）
      if (group !== 'pending' && payable > 0 && paid < payable - 0.005) {
        unsettled += 1;
        unpaidAmount += payable - paid;
      }
    });

    const ratio = list.length ? Math.round((converted / list.length) * 100) : 0;
    return [
      { key: 'count', label: '本页单据', value: `${list.length} 张`, hint: `待审核 ${pending} 张` },
      { key: 'converted', label: '已转单', value: `${converted} 张`, hint: `本页转单率 ${ratio}%` },
      {
        key: 'unsettled',
        label: '未结清',
        value: `${unsettled} 张`,
        hint: unsettled > 0 ? `欠 ¥${money(unpaidAmount)}` : '已全部结清',
      },
      {
        key: 'amount',
        label: '金额合计',
        value: `¥${money(totalAmount)}`,
        hint: unpaidAmount > 0 ? `其中未结 ¥${money(unpaidAmount)}` : '本页合计',
        strong: true,
      },
    ];
  }, [list, cfg.payField]);

  /** Delete 删行 —— 焦点在控件里时不删，否则打字删一个字符就把整行干掉 */
  const onLineKeyDown = (event) => {
    if (event.key !== 'Delete' || selectedLine === null) return;
    const tag = (event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    event.preventDefault();
    if (items.length <= 1) return;
    removeItem(selectedLine);
    setSelectedLine(null);
  };

  return (
    // ⚠️ 单据页必须给独立的 storageKey + 更高的 minLeft（2026-10-18）：
    //   · 默认 key `erp:mgrid:left` 是全站共用的，用户在客户档案把左栏拖到 300px 后，
    //     回到单据页也是 300px —— 明细表 min-width 600，直接被压成"一条 + 横滚"，
    //     商品搜索框只剩半截（用户截图报的就是这个）；
    //   · 660 = 明细表 600 + 卡片左右内边距 50，是这张表能放平的最小左栏宽度。
    // 2026-10-20 加批量选商品弹窗后包了 <>…</>：弹窗必须挂在 ResizableLayout
    // **外面**（第 3 个子元素会让拖拽静默失效）。
    <>
    <ResizableLayout
      className="doc-page"
      storageKey="erp:mgrid:doc"
      minLeft={660}
    >
      <ErpCard
        title={cfg.title}
        subtitle={cfg.subtitle}
        extra={
          <button
            type="button"
            className="secondary-btn small-btn"
            onClick={() => setFormCollapsed((prev) => !prev)}
            data-doc-form-collapse
            title={formCollapsed ? '展开表头继续填写' : '收起表头，把屏幕留给明细行'}
          >
            {formCollapsed ? '展开表头 ▾' : '收起表头 ▴'}
          </button>
        }
      >
        <form onSubmit={submitForm} data-doc-form={cfg.docForm} className="doc-form">
          {formCollapsed ? (
            /* 折叠态摘要：常用信息一行看完，点击展开回去补 */
            <p className="doc-form-collapsed-hint" data-doc-form-collapsed-hint>
              {form[cfg.partyField]
                ? `已选${cfg.partyLabel}：${partners.find((item) => item.id === Number(form[cfg.partyField]))?.name || '—'}`
                : `尚未选择${cfg.partyLabel}`}
              {' · 明细 '}{filled}{' 行 · 合计 ¥'}{money(total)}
              <button type="button" className="link-btn" onClick={() => setFormCollapsed(false)}>
                展开
              </button>
            </p>
          ) : (
          <ErpFormGrid columns={2} gap="md">
            <ErpFormRow label={cfg.partyLabel} required>
              {/* 客户/供应商可能几百条：平铺下拉改可搜索（商品行同款 ErpSearchSelect）。
                  onChange 用 `{ target: { value } }` 适配 handleFormChange 的 event 签名。 */}
              <ErpSearchSelect
                options={partners}
                value={String(form[cfg.partyField] ?? '')}
                onChange={handlePartyPicked}
                placeholder={`搜索${cfg.partyLabel}名称 / 编码`}
                emptyText={`没有匹配的${cfg.partyLabel}`}
                getOptionValue={(item) => String(item.id)}
                getOptionLabel={(item) => `${item.name}（${item.code}）`}
                getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
              />
              {renderPartyLink(cfg.partnerLinkType, form[cfg.partyField], cfg.partyLabel)}
            </ErpFormRow>

            <ErpFormRow label={cfg.warehouseLabel}>
              <select value={form.warehouse_id} onChange={handleFormChange('warehouse_id')}>
                <option value="">{cfg.warehousePlaceholder}</option>
                {warehouses.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </ErpFormRow>

            <ErpFormRow label="归属项目（可空）">
              {/* 项目台账可能上百条：平铺下拉改可搜索。same 适配器口径见上 */}
              <ErpSearchSelect
                options={projects}
                value={String(form.project_id ?? '')}
                onChange={(value) => handleFormChange('project_id')({ target: { value } })}
                placeholder="搜索项目编号 / 名称"
                emptyText="没有匹配的项目"
                getOptionValue={(item) => String(item.id)}
                getOptionLabel={(item) => `${item.code} ${item.name}`}
                getSearchText={(item) => [item.code, item.name].filter(Boolean).join(' ')}
              />
            </ErpFormRow>

            <ErpFormRow label="送货日期">
              <input
                type="date"
                value={form.delivery_date}
                onChange={handleFormChange('delivery_date')}
              />
            </ErpFormRow>

            <ErpFormRow label="付款方式">
              <input
                list="lookup-payment-method"
                value={form.payment_method}
                onChange={handleFormChange('payment_method')}
                placeholder="如：银行转账 / 月结30天"
              />
            </ErpFormRow>

            <ErpFormRow label="联系人">
              {/* 选客带出（只回填空字段），也可手改；随单快照落库 */}
              <input
                value={form.contact}
                onChange={handleFormChange('contact')}
                placeholder="选客户/供应商自动带出"
              />
            </ErpFormRow>

            <ErpFormRow label="联系电话">
              <input
                value={form.contact_phone}
                onChange={handleFormChange('contact_phone')}
                placeholder="选客户/供应商自动带出"
              />
            </ErpFormRow>

            <ErpFormRow label={cfg.addressLabel}>
              <input
                value={form.address}
                onChange={handleFormChange('address')}
                placeholder="选客户/供应商自动带出"
              />
            </ErpFormRow>

            <ErpFormRow label="备注">
              <input
                value={form.note}
                onChange={handleFormChange('note')}
                placeholder={cfg.notePlaceholder}
              />
            </ErpFormRow>
          </ErpFormGrid>
          )}

          <div className="doc-lines">
            <div className="doc-lines__head">
              <h3>商品明细</h3>
              <span className="doc-lines__hint">
                {selectedLine === null
                  ? '点一行可选中，按 Delete 删行'
                  : `已选中第 ${selectedLine + 1} 行`}
              </span>
              <button type="button" className="secondary-btn small-btn" onClick={addItem}>
                + 添加一行
              </button>
              {/* 2026-10-20 老系统 UX：复制选中行 / 批量选商品 */}
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => copyItem(selectedLine)}
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
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setColPickerOpen(true)}
                data-doc-col-config
                title="勾选要显示的明细列，配置保存在本机"
              >
                列配置
              </button>
            </div>

            <div className="doc-lines__table" onKeyDown={onLineKeyDown}>
              <ErpTable
                dense
                columns={visibleLineColumns}
                rows={items}
                rowKey={(_row, index) => index}
                ariaLabel={`${cfg.listTitle}明细`}
                minWidth={600}
                onRowClick={(_row, index) => setSelectedLine(index)}
                rowClassName={(_row, index) => (index === selectedLine ? 'doc-line--selected' : '')}
                footer={
                  <tr className="doc-total-row">
                    <td colSpan={totalLabelSpan} className="doc-total-row__label">
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
              {cfg.submitLabel}
            </button>
          </ErpFormActions>
        </form>
      </ErpCard>

      <ErpCard title={cfg.listTitle} subtitle={`${list.length} 张`} padding="md" flush divider>
        {/* KPI 计量条：卡片是 flush（表格贴边），所以这里自己留内边距，
            不能靠卡片 padding —— 否则表格第一行会和左右边框对不齐。 */}
        <div className="doc-kpi">
          <ErpKpiStrip dense items={kpiItems} />
        </div>
        <ErpTable
          columns={orderColumns}
          rows={list}
          ariaLabel={cfg.listTitle}
          // ⚠️ 不能给 820：右栏可视宽度约 696px，超出的部分会被 sticky 操作列
          //    盖住（真机截图里「金额」只剩半截）。700 与采购入库同档，
          //    让 auto 布局把供应商列压下去（它有 ellipsis，牺牲得起）。
          minWidth={700}
          emptyProps={{ variant: 'data', title: '还没有订单', description: cfg.emptyText }}
        />
      </ErpCard>
      </ResizableLayout>

      {/* 批量选商品弹窗：挂在 ResizableLayout 外面（第 3 个子元素会让拖拽静默失效） */}
      {productPickerOpen && (
        <ProductMultiSelectModal
          products={products}
          onClose={() => setProductPickerOpen(false)}
          onConfirm={(productIds) => {
            addProducts(productIds);
            setProductPickerOpen(false);
          }}
        />
      )}

      {/* 明细列配置弹窗：同上，也挂在 ResizableLayout 外面 */}
      {colPickerOpen && (
        <LineColConfigModal
          hiddenCols={hiddenCols}
          onToggle={toggleLineCol}
          onReset={resetLineCols}
          onClose={() => setColPickerOpen(false)}
        />
      )}

      {/* 订单详情（2026-10-26）：点单号打开。
          抽屉必须挂在 ResizableLayout 外面（同上面两个弹窗：第三个子元素会让拖拽静默失效）。
          只读、不写库：这里一个按钮都不放业务动作，「审核 / 转单 / 收付款」仍在行内操作列 ——
          详情弹出来时列表还在原地，关掉就能接着点。 */}
      <ErpDrawer
        open={Boolean(detailOrder)}
        size="lg"
        title={kind === 'purchase' ? '采购订单详情' : '销售订单详情'}
        subtitle={detailOrder?.order_no}
        onClose={() => setDetailOrder(null)}
        testId={`order-detail-${kind}`}
      >
        {detailOrder ? (
          <>
            <dl className="doc-detail__facts">
              <div>
                <dt>状态</dt>
                <dd>{orderStatusLabel(detailOrder.status)}</dd>
              </div>
              <div>
                <dt>{cfg.partyLabel}</dt>
                <dd>
                  {partners.find((item) => item.id === detailOrder[cfg.partyField])?.name || '—'}
                </dd>
              </div>
              <div>
                <dt>仓库</dt>
                <dd>{warehouses.find((item) => item.id === detailOrder.warehouse_id)?.name || '—'}</dd>
              </div>
              <div>
                <dt>业务员</dt>
                <dd>{detailOrder.businesser || '—'}</dd>
              </div>
              <div>
                <dt>订单日期</dt>
                <dd>{detailOrder.order_date || '—'}</dd>
              </div>
              <div>
                <dt>{kind === 'purchase' ? '到货日期' : '送货日期'}</dt>
                <dd>{detailOrder.delivery_date || '—'}</dd>
              </div>
              <div>
                <dt>联系人</dt>
                <dd>
                  {[detailOrder.contact, detailOrder.contact_phone].filter(Boolean).join(' · ') || '—'}
                </dd>
              </div>
              <div className="is-wide">
                <dt>{cfg.addressLabel}</dt>
                <dd>{detailOrder.address || '—'}</dd>
              </div>
              <div className="is-wide">
                <dt>备注</dt>
                <dd>{detailOrder.note || '—'}</dd>
              </div>
            </dl>

            <h4 className="doc-detail__subtitle">
              明细（{(detailOrder.items || []).length} 行）
            </h4>
            <ErpTable
              dense
              ariaLabel="订单明细"
              rows={detailOrder.items || []}
              emptyProps={{ variant: 'data', title: '这张单没有明细' }}
              columns={[
                {
                  key: 'product_name',
                  title: '商品',
                  minWidth: 200,
                  render: (row) =>
                    row.product_name ||
                    products.find((item) => item.id === row.product_id)?.name ||
                    '—',
                },
                { key: 'standards', title: '规格', width: 100, fallback: '—' },
                { key: 'unit', title: '单位', width: 64, fallback: '—' },
                { key: 'quantity', title: '数量', width: 64, align: 'right', num: true },
                {
                  key: 'unit_price',
                  title: '单价',
                  width: 88,
                  align: 'right',
                  num: true,
                  format: (value) => `¥${money(value)}`,
                },
                {
                  key: 'amount',
                  title: '金额',
                  width: 96,
                  align: 'right',
                  num: true,
                  format: (value) => `¥${money(value)}`,
                },
              ]}
            />

            <dl className="doc-detail__facts doc-detail__facts--money">
              <div>
                <dt>合计金额</dt>
                <dd>¥{money(detailOrder.total_amount)}</dd>
              </div>
              <div>
                <dt>优惠</dt>
                <dd>¥{money(detailOrder.discount_amount)}</dd>
              </div>
              <div>
                <dt>应付</dt>
                <dd>
                  ¥{money(
                    Number(detailOrder.total_amount || 0) - Number(detailOrder.discount_amount || 0),
                  )}
                </dd>
              </div>
              <div>
                <dt>{kind === 'purchase' ? '已付' : '已收'}</dt>
                <dd>¥{money(detailOrder[cfg.payField])}</dd>
              </div>
            </dl>

            <p className="doc-detail__hint">
              这里只是「只读快照」（打开抽屉那一刻的数据）：审核、转单、{cfg.payLabel}、打印
              都还在列表行的操作区，关掉抽屉就能接着点。订单本身不动库存与账款 ——
              真正写库存的是转出来的那张{kind === 'purchase' ? '入库单' : '开单'}。
            </p>
          </>
        ) : null}
      </ErpDrawer>
    </>
  );
}
