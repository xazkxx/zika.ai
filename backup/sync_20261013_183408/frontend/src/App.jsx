import { useEffect, useMemo, useState } from 'react';
import jsQR from 'jsqr';
import * as pdfjsLib from 'pdfjs-dist';
import Tesseract from 'tesseract.js';
import * as XLSX from 'xlsx';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();

// 使用同源相对路径：开发时由 Vite 代理转发到后端；
// 手机/局域网访问时请求也走当前服务器，不会指向错误的 127.0.0.1。
const API_BASE = '/api/v1';
// 菜单按业务域分组。items 里的 key 与业务逻辑一一对应，改分组不会影响任何功能。
// 左侧菜单框架 —— 业务域对齐浩技云进销存（基础资料 / 采购 / 销售 / 库存 / 生产 / 财务 / 系统设置），
// 并保留本系统独有的模块（工作台、报表分析、项目管理、移动与智能）。
//
// 设计口径：
//   1. 分组名与功能名沿用浩技云的说法，员工从浩技云迁过来零学习成本；
//   2. 基础档案类保留本系统原有叫法（客户档案 / 商品档案…），比「客户管理」更准确；
//   3. `todo: true` = 框架位已按浩技云预留、功能待建设，点击显示「模块建设中」占位页；
//   4. key 一律沿用原有值，改的只是分组归属与显示名，不触及任何业务逻辑。
const menuGroups = [
  {
    key: 'workspace',
    label: '工作台',
    origin: 'own',
    items: [{ key: 'overview', label: '运营概览' }],
  },
  {
    key: 'basic',
    label: '基础资料',
    origin: 'haoji',
    items: [
      { key: 'customers', label: '客户档案' },
      { key: 'suppliers', label: '供应商档案' },
      { key: 'products', label: '商品档案' },
      { key: 'warehouses', label: '仓库档案' },
      { key: 'staff', label: '员工档案', todo: true },
      { key: 'opening-stock', label: '商品期初库存', todo: true },
      { key: 'dataio', label: '导入导出' },
    ],
  },
  {
    key: 'purchase',
    label: '采购管理',
    origin: 'haoji',
    items: [
      { key: 'purchase', label: '采购入库' },
      { key: 'purchase-order', label: '采购订单' },
      { key: 'purchase-return', label: '采购退货' },
      { key: 'purchase-statement', label: '采购对账单', todo: true },
    ],
  },
  {
    key: 'sales',
    label: '销售管理',
    origin: 'haoji',
    items: [
      { key: 'sales', label: '开单管理' },
      { key: 'sales-order', label: '销售订单' },
      { key: 'quotation', label: '报价单' },
      { key: 'sales-return', label: '销售退货' },
      { key: 'contracts', label: '购销合同' },
      { key: 'sales-statement', label: '销售对账单', todo: true },
    ],
  },
  {
    key: 'inventory',
    label: '库存管理',
    origin: 'haoji',
    items: [
      { key: 'inventory', label: '库存管理' },
      { key: 'stock-logs', label: '变动查询' },
      { key: 'transfer', label: '调拨管理' },
      { key: 'stocktaking', label: '盘点管理' },
      { key: 'assembly', label: '组合拆卸', todo: true },
      { key: 'loss-overflow', label: '报损报溢' },
    ],
  },
  {
    key: 'manufacture',
    label: '生产管理',
    origin: 'haoji',
    items: [
      { key: 'production', label: '生产单' },
      { key: 'bom', label: 'BOM 清单' },
      { key: 'production-plan', label: '生产计划' },
      { key: 'mrp', label: 'MRP 运算' },
      { key: 'material-issue', label: '生产领料' },
      { key: 'material-return', label: '生产退料' },
      { key: 'finished-goods', label: '成品入库' },
      { key: 'outsourcing', label: '委外加工' },
    ],
  },
  {
    key: 'finance',
    label: '财务管理',
    origin: 'haoji',
    items: [
      { key: 'finance', label: '财务流水' },
      { key: 'receivable', label: '应收账款' },
      { key: 'payable', label: '应付账款' },
      { key: 'ledger', label: '往来对账' },
      { key: 'bank', label: '现金银行', todo: true },
      { key: 'income-expense', label: '日常收支', todo: true },
      { key: 'payroll', label: '工资管理', todo: true },
      { key: 'invoices', label: '开票管理', todo: true },
    ],
  },
  {
    key: 'analysis',
    label: '报表分析',
    origin: 'own',
    items: [
      { key: 'reports', label: '报表中心' },
      { key: 'analysis', label: '经营分析' },
    ],
  },
  {
    key: 'project',
    label: '项目管理',
    origin: 'own',
    items: [{ key: 'projects', label: '项目台账' }],
  },
  {
    key: 'mobile',
    label: '移动与智能',
    origin: 'own',
    items: [
      { key: 'agent', label: '智能助手' },
      { key: 'mobile', label: '移动端预览' },
    ],
  },
  {
    key: 'system',
    label: '系统设置',
    origin: 'haoji',
    items: [
      { key: 'settings', label: '公司信息' },
      { key: 'users', label: '用户角色', todo: true },
      { key: 'params', label: '参数设置', todo: true },
      { key: 'print-templates', label: '打印模板', todo: true },
      { key: 'logs', label: '操作日志', todo: true },
    ],
  },
];

// 扁平视图：供顶栏标题查找、权限过滤等按 key 检索的场景使用
const tabs = menuGroups.flatMap((group) =>
  group.items.map((item) => ({ ...item, group: group.key, groupLabel: group.label })),
);

const emptyCustomerForm = {
  code: '',
  name: '',
  phone: '',
  email: '',
  address: '',
};

const emptyProductForm = {
  sku: '',
  name: '',
  category: '',
  unit: '',
  purchase_price: '',
  sale_price: '',
};

// 采购/销售订单（doc_type=order）：只订货不动库存财务，多行明细
const emptyOrderItem = { product_id: '', quantity: '1', unit_price: '0' };
const emptyPurchaseOrderForm = {
  supplier_id: '',
  warehouse_id: '',
  delivery_date: '',
  payment_method: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
const emptySalesOrderForm = {
  customer_id: '',
  warehouse_id: '',
  delivery_date: '',
  payment_method: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
// 采购入库单（doc_type=inbound）：真实入库，写库存 + 应付
const emptyInboundForm = {
  supplier_id: '',
  warehouse_id: '',
  order_date: '',
  payment_method: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
// 销售开单 / 出库单（doc_type=outbound）：真实出库，写库存 + 应收
const emptyOutboundForm = {
  customer_id: '',
  warehouse_id: '',
  order_date: '',
  payment_method: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
const DOC_STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  completed: '已转单',
  cancelled: '已取消',
};

const emptySupplierForm = {
  code: '',
  name: '',
  phone: '',
  email: '',
  address: '',
};

// 仓库档案：进销存的采购入库 / 销售出库 / 调拨都要选仓库，是库存模块的主数据。
const emptyWarehouseForm = {
  code: '',
  name: '',
  location: '',
  manager: '',
  phone: '',
  is_active: true,
  note: '',
};

// 购销合同（模板 A2 · 标准版）表单。条款变量留空则由后端用行业常规表述兜底，
// 所以这里只给必填项与几个常用默认值，用户想改再改。
const emptyContractForm = {
  contract_type: 'sales',
  party_id: '',
  warehouse_id: '',
  own_name: '',
  own_tax_no: '',
  own_legal_person: '',
  own_address: '',
  own_contact: '',
  own_phone: '',
  own_bank_name: '',
  own_bank_account: '',
  sign_date: '',
  sign_place: '',
  delivery_date: '',
  delivery_place: '',
  delivery_method: '',
  freight_bearer: '',
  payment_terms: '',
  invoice_requirement: '',
  quality_standard: '',
  package_standard: '',
  inspection_days: '7',
  objection_days: '15',
  warranty_terms: '',
  penalty_rate: '5', // 万分之（违约金日利率）
  dispute_resolution: '',
  copies: '2',
  service_address: '',
  other_terms: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 合同状态 → 中文标签
const CONTRACT_STATUS_LABEL = {
  draft: '草稿',
  signed: '已签订',
  executing: '执行中',
  finished: '已完成',
  void: '已作废',
};
const contractStatusLabel = (status) => CONTRACT_STATUS_LABEL[status] || status;

// 销售报价单表单（对齐浩技云「销售 → 报价单」）。报价单是商务意向文件，
// 不产生应收、不动库存；客户确认后一键转成销售订单再走单据链路。
const emptyQuotationForm = {
  customer_id: '',
  customer_name: '',
  customer_address: '',
  contact: '',
  contact_phone: '',
  fax: '',
  quote_date: '',
  valid_until: '',
  warehouse_id: '',
  businesser: '',
  payment_method: '银行转账',
  transport_method: '货运',
  delivery_place: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 报价单状态 → 中文标签
const QUOTATION_STATUS_LABEL = {
  draft: '草稿',
  quoted: '已报价',
  accepted: '已接受',
  rejected: '已拒绝',
  void: '已作废',
};
const quotationStatusLabel = (status) => QUOTATION_STATUS_LABEL[status] || status;

// 采购退货单表单（对齐浩技云「采购管理 → 退货管理」）。退货是采购入库的反向单据：
// 货退回给供应商，库存减少、应付冲减。选供应商自动带出联系人/电话/地址快照。
const emptyPurchaseReturnForm = {
  supplier_id: '',
  warehouse_id: '',
  businesser: '',
  return_date: '',
  return_reason: '',
  payment_method: '',
  note: '',
  source_order_id: '',
  source_order_no: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 采购退货状态 → 中文标签
const PURCHASE_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退货',
  cancelled: '已取消',
};
const purchaseReturnStatusLabel = (status) => PURCHASE_RETURN_STATUS_LABEL[status] || status;

// 销售退货单表单（对齐浩技云「销售管理 → 销售退货」）。退货是销售开单（出库）的反向单据：
// 客户把货退回来，库存增加、应收冲减。选客户自动带出联系人/电话/地址快照。
const emptySalesReturnForm = {
  customer_id: '',
  warehouse_id: '',
  businesser: '',
  return_date: '',
  return_reason: '',
  payment_method: '',
  note: '',
  source_order_id: '',
  source_order_no: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 销售退货状态 → 中文标签
const SALES_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退货',
  cancelled: '已取消',
};
const salesReturnStatusLabel = (status) => SALES_RETURN_STATUS_LABEL[status] || status;

// 库存调拨单表单（对齐浩技云「库存管理 → 调拨管理」）。调拨是同一企业内部的库存
// 位置转移：货物从调出仓库搬到调入仓库，总量与资产总额都不变，所以只写库存流水、
// 不写财务流水。明细只录数量（成本单价可选，仅打印参考）。
const emptyTransferForm = {
  from_warehouse_id: '',
  to_warehouse_id: '',
  transfer_date: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 调拨单状态 → 中文标签
const TRANSFER_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已调拨',
  cancelled: '已取消',
};
const transferStatusLabel = (status) => TRANSFER_STATUS_LABEL[status] || status;

// 库存盘点单表单（对齐浩技云「库存管理 → 盘点管理」）。盘点是账实核对：
// 账面数由系统按现存量带出（「带出账面库存」按钮调 /stocktakings/plan），
// 人只填实盘数，盈亏由后端统一算（实盘 - 账面）。
const emptyStocktakingForm = {
  warehouse_id: '',
  check_date: '',
  handler: '',
  scope: '',
  note: '',
  items: [],
};

const STOCKTAKING_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已调整',
  cancelled: '已取消',
};
const stocktakingStatusLabel = (status) => STOCKTAKING_STATUS_LABEL[status] || status;

// 报损报溢单表单（对齐浩技云「库存管理 → 报损报溢」）。报损与报溢是同一张表的
// 两个方向，用 adjust_type 区分：报损减库存、报溢加库存；明细数量恒正。
const emptyAdjustmentForm = {
  adjust_type: 'scrap',
  warehouse_id: '',
  adjust_date: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const ADJUSTMENT_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已生效',
  cancelled: '已取消',
};
const adjustmentStatusLabel = (status) => ADJUSTMENT_STATUS_LABEL[status] || status;

// 报损报溢类型 → 中文标签 + 库存方向
const ADJUST_TYPE_LABEL = { scrap: '报损', overflow: '报溢' };
const ADJUST_TYPE_DIRECTION = { scrap: '减少库存', overflow: '增加库存' };
const adjustTypeLabel = (type) => ADJUST_TYPE_LABEL[type] || type;

// 生产计划单表单（对齐浩技云「生产管理 → 生产计划」）。计划只是排产意图，
// 不写库存、不写财务，是整条生产链路的起点：MRP → 领料 → 退料 → 成品入库。
const emptyProductionPlanForm = {
  plan_type: 'self',
  warehouse_id: '',
  plan_date: '',
  delivery_date: '',
  handler: '',
  workshop: '',
  source_order_no: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const PLAN_TYPE_LABEL = { self: '自制', outsource: '委外' };
const planTypeLabel = (type) => PLAN_TYPE_LABEL[type] || type;

const PRODUCTION_PLAN_STATUS_LABEL = {
  draft: '草稿',
  planned: '已计划',
  released: '已下达',
  closed: '已关闭',
  cancelled: '已取消',
};
const productionPlanStatusLabel = (status) => PRODUCTION_PLAN_STATUS_LABEL[status] || status;

// MRP 物料行状态 → 中文标签（product=顶层产出，不参与缺料判定）
const MRP_STATUS_LABEL = {
  product: '产出',
  sufficient: '库存充足',
  partial: '部分缺料',
  shortage: '缺料',
};
const mrpStatusLabel = (status) => MRP_STATUS_LABEL[status] || status;

// 生产领料单表单（对齐浩技云「生产管理 → 生产领料」）。领料把原材料从仓库
// 发到车间：原材料库存减少，属纯库存单据，不写财务。可按生产计划一键带出底稿。
const emptyMaterialIssueForm = {
  plan_id: '',
  warehouse_id: '',
  issue_date: '',
  workshop: '',
  handler: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const MATERIAL_ISSUE_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已领料',
  cancelled: '已取消',
};
const materialIssueStatusLabel = (status) => MATERIAL_ISSUE_STATUS_LABEL[status] || status;

// 生产退料单表单（领料的反向单据）：车间余料退回仓库，原材料库存增加。
const emptyMaterialReturnForm = {
  plan_id: '',
  warehouse_id: '',
  return_date: '',
  workshop: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const MATERIAL_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退料',
  cancelled: '已取消',
};
const materialReturnStatusLabel = (status) => MATERIAL_RETURN_STATUS_LABEL[status] || status;

// 成品入库单表单（对齐浩技云「生产管理 → 成品入库」）。成品入库是生产链路
// 的收口：车间把成品交回仓库，成品库存增加，并结转生产成本（写财务成本流水）。
const emptyFinishedGoodsForm = {
  plan_id: '',
  warehouse_id: '',
  receipt_date: '',
  workshop: '',
  handler: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const FINISHED_GOODS_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已入库',
  cancelled: '已取消',
};
const finishedGoodsStatusLabel = (status) => FINISHED_GOODS_STATUS_LABEL[status] || status;

// 委外加工单表单（对齐浩技云「生产管理 → 委外加工」）。一张单两个方向：
// 发料（原材料出库）+ 收成品（成品入库），并按加工费产生应付。
const emptyOutsourcingForm = {
  supplier_id: '',
  warehouse_id: '',
  order_date: '',
  handler: '',
  product_id: '',
  quantity: '1',
  unit_price: '0',
  process_fee: '0',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

const OUTSOURCING_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已收发',
  cancelled: '已取消',
};
const outsourcingStatusLabel = (status) => OUTSOURCING_STATUS_LABEL[status] || status;

// ——— 报表中心（第 4 批）———
// 16 张报表**不写死在前端**：目录由后端 /reports/catalog 下发（唯一事实来源），
// 页面按目录渲染菜单，再按 report.shape 选渲染器。加一张报表只需改后端目录。
const REPORT_SHAPE_LABEL = {
  crosstab: '交叉表',
  detail: '明细表',
  flow: '收发存',
  overview: '大盘',
};

// 报表查询条件。留空 = 用后端给的默认区间（日报 30 天、月报 12 个月…）。
const emptyReportQuery = {
  date_from: '',
  date_to: '',
  dimension: '',
  period: '',
  keyword: '',
};

const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
const plain = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

const emptyInventoryForm = {
  product_id: '',
  warehouse_id: '',
  transaction_type: 'inbound',
  quantity: '1',
  unit_price: '0',
};

// 现存量状态 → 中文标签与样式类（阈值来自商品档案的库存上下限）
const STOCK_STATUS_LABEL = {
  shortage: '缺货',
  low_stock: '低库存',
  overstock: '积压',
  normal: '正常',
};
const stockStatusLabel = (status) => STOCK_STATUS_LABEL[status] || '正常';

// 单据来源 → 中文标签。库存流水/财务流水共用后端 DOC_TYPES 的 key，
// 再补一个库存专用的 opening（期初建账）。
const DOC_TYPE_LABEL = {
  purchase_order: '采购订单',
  purchase_in: '采购入库',
  purchase_return: '采购退货',
  sales_order: '销售订单',
  sales_out: '销售开单',
  sales_return: '销售退货',
  receipt: '收款登记',
  payment: '付款登记',
  inv_check: '库存盘点',
  inv_scrap: '报损',
  inv_overflow: '报溢',
  inv_transfer: '库存调拨',
  production_order: '生产工单',
  production_plan: '生产计划',
  production_issue: '生产领料',
  production_return: '生产退料',
  production_in: '成品入库',
  production_wage: '计件工资',
  outsourcing: '委外加工',
  project_cost: '项目费用',
  invoice: '发票',
  expense: '日常支出',
  contract: '购销合同',
  opening: '期初建账',
};
const docTypeLabel = (type) => DOC_TYPE_LABEL[type] || type || '手工登记';

// 变动查询页的筛选条件
const emptyStockLogFilter = { type: '', warehouse_id: '', keyword: '' };

const emptyFinanceForm = {
  transaction_type: 'income',
  amount: '0',
  currency: 'CNY',
  note: '',
  related_order_id: '',
  customer_id: '',
  supplier_id: '',
};

function App() {
  const getStoredToken = () => {
    try {
      return localStorage.getItem('erp_token') || '';
    } catch {
      return '';
    }
  };

  const [summary, setSummary] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [products, setProducts] = useState([]);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [salesOrders, setSalesOrders] = useState([]);
  // 采购/销售订单页（doc_type=order）独立数据源，与老出入库页互不干扰
  const [purchaseOrderList, setPurchaseOrderList] = useState([]);
  const [salesOrderList, setSalesOrderList] = useState([]);
  const [selectedPurchaseOrder, setSelectedPurchaseOrder] = useState(null);
  const [selectedSalesOrder, setSelectedSalesOrder] = useState(null);
  const [productionOrders, setProductionOrders] = useState([]);
  const [projects, setProjects] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [printParty, setPrintParty] = useState({ customer_id: '', supplier_id: '', from: '', to: '' });
  // 现存量看板：按需拉取（切到库存页才请求），不挤进首页那批并发请求里
  const [stockData, setStockData] = useState({ rows: [], summary: {} });
  // —— 跨页关联（单据 ↔ 库存 / 档案）——
  // inventoryKeyword：库存页搜索框（外部跳转时会被自动填入商品名/SKU）
  const [inventoryKeyword, setInventoryKeyword] = useState('');
  // inventoryFocus：从单据页跳来的「聚焦提示」，告诉用户是被哪张单据带过来的
  const [inventoryFocus, setInventoryFocus] = useState(null);
  // archiveFocus：跳到档案页时高亮的目标行 { tab, id }，让用户一眼看到关联的那条档案
  const [archiveFocus, setArchiveFocus] = useState(null);
  // 采购入库页（doc_type=inbound）与开单管理页（doc_type=outbound）的表单
  const [inboundForm, setInboundForm] = useState(emptyInboundForm);
  const [outboundForm, setOutboundForm] = useState(emptyOutboundForm);
  const [finance, setFinance] = useState([]);
  const [financeAnalysis, setFinanceAnalysis] = useState({
    total_revenue: 0,
    total_expense: 0,
    net_profit: 0,
    by_customer: [],
    monthly_trend: [],
  });
  const [financeDecision, setFinanceDecision] = useState({
    summary: { total_income: 0, total_expense: 0, net_cash_flow: 0, gross_margin_rate: 0, expense_ratio: 0 },
    status: { liquidity: '待评估', trend: '待评估', cash_position: '待评估' },
    risk_level: 'healthy',
    recommendations: [],
  });
  const [operationsBoard, setOperationsBoard] = useState({
    production_orders: [],
    project_summary: { total: 0, in_progress: 0, completed: 0, avg_progress: 0, budget_total: 0 },
    high_priority_orders: [],
    status_breakdown: { planned: 0, in_progress: 0, completed: 0 },
    milestones: [],
    cost_summary: { material_cost: 0, labor_cost: 0, overhead_cost: 0, total_cost: 0 },
    gantt: [],
    production_flow: [],
    recommendations: [],
    bom_summary: { total_items: 0, total_quantity: 0, total_cost: 0 },
    work_orders: [],
    production_schedule: [],
    bom_alerts: [],
    line_board: [],
    auto_schedule: [],
    inventory_alerts: [],
    purchase_recommendations: [],
    supplier_performance: [],
    payment_alerts: [],
    work_report_summary: { total_work_orders: 0, completed_today: 0, progress_rate: 0, avg_output: 0, oee: 0 },
  });
  const [executiveDashboard, setExecutiveDashboard] = useState({
    kpis: [],
    status: { health: 'healthy', production: 0, margin: 0, risk_count: 0 },
    alerts: [],
  });
  const [mobileDashboard, setMobileDashboard] = useState({
    status: 'healthy',
    risk_count: 0,
    updated_at: '',
    summary: { sales_total: 0, purchase_total: 0, net_profit: 0, customers: 0, products: 0, inventory_alerts: 0, payment_alerts: 0 },
    kpis: [],
    recommendations: [],
  });
  const [bomTree, setBomTree] = useState([]);
  const [bomForm, setBomForm] = useState({
    product_id: '',
    component_product_id: '',
    parent_id: '',
    name: '',
    code: '',
    quantity: '1',
    unit_cost: '0',
    bom_type: 'assembly',
    level: '0',
    description: '',
  });
  const [invoiceItems, setInvoiceItems] = useState([]);
  const [invoiceDetail, setInvoiceDetail] = useState(null);
  const [invoiceAggregate, setInvoiceAggregate] = useState({
    total_count: 0,
    total_amount: 0,
    total_tax: 0,
    by_type: [],
    deduction: { deducted_count: 0, deducted_amount: 0, undeducted_count: 0, undeducted_amount: 0 },
    monthly: {},
  });
  const [invoiceAgentReport, setInvoiceAgentReport] = useState(null);
  const [analysisRange, setAnalysisRange] = useState({ startDate: '', endDate: '' });
  const [agentPrompt, setAgentPrompt] = useState('请评估当前业务健康度，并给出建议。');
  const [agentResponse, setAgentResponse] = useState({ answer: '', summary: {}, risk_level: '健康' });
  const [selectedTab, setSelectedTab] = useState('overview');
  const [collapsedGroups, setCollapsedGroups] = useState([]);
  // 手机端：侧边栏改成抽屉，用这个开关控制滑出/收起（桌面端不生效）
  const [menuOpen, setMenuOpen] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getStoredToken()));
  const [authToken, setAuthToken] = useState(getStoredToken());
  const [userProfile, setUserProfile] = useState({ username: '', role: 'staff' });
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [customerForm, setCustomerForm] = useState(emptyCustomerForm);
  const [supplierForm, setSupplierForm] = useState(emptySupplierForm);
  const [warehouseForm, setWarehouseForm] = useState(emptyWarehouseForm);
  // null = 新增态；数字 = 正在编辑的仓库 id
  const [editingWarehouseId, setEditingWarehouseId] = useState(null);

  // —— 第 1 批页面：变动查询 / 应收应付 / 往来对账 ——
  const [stockLogFilter, setStockLogFilter] = useState(emptyStockLogFilter);
  const [receivables, setReceivables] = useState([]);
  const [payables, setPayables] = useState([]);
  // 账龄分析：按需计算（FIFO 冲抵较慢，不随页面自动跑）
  const [aging, setAging] = useState({ party_type: '', as_of: '', buckets: {}, total: 0, details: [] });
  const [ledgerParty, setLedgerParty] = useState({ party_type: 'customer', party_id: '', from: '', to: '' });
  const [ledgerData, setLedgerData] = useState(null);
  const [financeBusy, setFinanceBusy] = useState('');
  const [productForm, setProductForm] = useState(emptyProductForm);
  // 采购/销售订单录入表单（多行明细，与出入库单表单分开）
  const [purchaseOrderForm, setPurchaseOrderForm] = useState(emptyPurchaseOrderForm);
  const [salesOrderForm, setSalesOrderForm] = useState(emptySalesOrderForm);
  const [contracts, setContracts] = useState([]);
  const [contractMeta, setContractMeta] = useState(null);
  const [contractForm, setContractForm] = useState(emptyContractForm);
  // 销售报价单：列表 / 字典 / 录入表单 / 搜索词 / 详情弹窗
  const [quotations, setQuotations] = useState([]);
  const [quotationMeta, setQuotationMeta] = useState(null);
  const [quotationForm, setQuotationForm] = useState(emptyQuotationForm);
  const [quotationKeyword, setQuotationKeyword] = useState('');
  const [selectedQuotation, setSelectedQuotation] = useState(null);
  // 采购退货：列表 / 录入表单 / 搜索词
  const [purchaseReturns, setPurchaseReturns] = useState([]);
  const [purchaseReturnForm, setPurchaseReturnForm] = useState(emptyPurchaseReturnForm);
  const [purchaseReturnKeyword, setPurchaseReturnKeyword] = useState('');
  // 销售退货：列表 / 录入表单 / 搜索词
  const [salesReturns, setSalesReturns] = useState([]);
  const [salesReturnForm, setSalesReturnForm] = useState(emptySalesReturnForm);
  const [salesReturnKeyword, setSalesReturnKeyword] = useState('');
  // 库存调拨：列表 / 录入表单 / 搜索词
  const [transfers, setTransfers] = useState([]);
  const [transferForm, setTransferForm] = useState(emptyTransferForm);
  const [transferKeyword, setTransferKeyword] = useState('');
  // 库存盘点：列表 / 录入表单 / 搜索词 / 底稿加载提示
  const [stocktakings, setStocktakings] = useState([]);
  const [stocktakingForm, setStocktakingForm] = useState(emptyStocktakingForm);
  const [stocktakingKeyword, setStocktakingKeyword] = useState('');
  const [stocktakingPlanHint, setStocktakingPlanHint] = useState('');
  // 报损报溢：列表 / 录入表单 / 搜索词 / 类型筛选（scrap / overflow / 空=全部）
  const [adjustments, setAdjustments] = useState([]);
  const [adjustmentForm, setAdjustmentForm] = useState(emptyAdjustmentForm);
  const [adjustmentKeyword, setAdjustmentKeyword] = useState('');
  const [adjustmentTypeFilter, setAdjustmentTypeFilter] = useState('');
  // 生产计划：列表 / 录入表单 / 搜索词 / 类型筛选（self / outsource / 空=全部）
  const [productionPlans, setProductionPlans] = useState([]);
  const [productionPlanForm, setProductionPlanForm] = useState(emptyProductionPlanForm);
  const [productionPlanKeyword, setProductionPlanKeyword] = useState('');
  const [productionPlanTypeFilter, setProductionPlanTypeFilter] = useState('');
  // MRP 运算：需求表单 / 运算结果 / 忙碌标记
  const [mrpForm, setMrpForm] = useState({
    warehouse_id: '',
    plan_id: '',
    items: [{ product_id: '', quantity: '1' }],
  });
  const [mrpResult, setMrpResult] = useState(null);
  const [mrpBusy, setMrpBusy] = useState(false);
  // 生产领料：列表 / 录入表单 / 搜索词 / 底稿加载提示
  const [materialIssues, setMaterialIssues] = useState([]);
  const [materialIssueForm, setMaterialIssueForm] = useState(emptyMaterialIssueForm);
  const [materialIssueKeyword, setMaterialIssueKeyword] = useState('');
  const [issueSuggestionHint, setIssueSuggestionHint] = useState('');
  // 生产退料：列表 / 录入表单 / 搜索词
  const [materialReturns, setMaterialReturns] = useState([]);
  const [materialReturnForm, setMaterialReturnForm] = useState(emptyMaterialReturnForm);
  const [materialReturnKeyword, setMaterialReturnKeyword] = useState('');
  // 成品入库：列表 / 录入表单 / 搜索词
  const [finishedGoodsList, setFinishedGoodsList] = useState([]);
  const [finishedGoodsForm, setFinishedGoodsForm] = useState(emptyFinishedGoodsForm);
  const [finishedGoodsKeyword, setFinishedGoodsKeyword] = useState('');
  // 委外加工：列表 / 录入表单 / 搜索词
  const [outsourcings, setOutsourcings] = useState([]);
  const [outsourcingForm, setOutsourcingForm] = useState(emptyOutsourcingForm);
  const [outsourcingKeyword, setOutsourcingKeyword] = useState('');

  // 报表中心：目录（后端下发）+ 当前选中的报表 + 查询条件 + 取数结果
  const [reportCatalog, setReportCatalog] = useState({ total: 0, groups: [], dimensions: {}, periods: {} });
  const [reportKey, setReportKey] = useState('boss');
  const [reportQuery, setReportQuery] = useState(emptyReportQuery);
  const [reportResult, setReportResult] = useState(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [companyForm, setCompanyForm] = useState({
    own_name: '',
    own_tax_no: '',
    own_legal_person: '',
    own_address: '',
    own_contact: '',
    own_phone: '',
    own_bank_name: '',
    own_bank_account: '',
  });
  const [contractKeyword, setContractKeyword] = useState('');
  const [selectedContract, setSelectedContract] = useState(null);
  const [inventoryForm, setInventoryForm] = useState(emptyInventoryForm);
  const [financeForm, setFinanceForm] = useState(emptyFinanceForm);
  const [productionForm, setProductionForm] = useState({ product_id: '', order_no: '', quantity: '1', status: 'planned', priority: 'normal', note: '' });
  const [projectForm, setProjectForm] = useState({ code: '', name: '', manager: '', status: 'planned', progress: '0', budget: '0', deadline: '', note: '' });
  const [selectedRecommendation, setSelectedRecommendation] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // 删除确认弹窗：{ id, ids, endpoint, label, kind }
  const [confirmDelete, setConfirmDelete] = useState(null);
  // 发票列表批量勾选删除：已勾选的发票 id 数组
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState([]);
  // 数据导入导出（Excel）：支持的类别 / 预检待确认 / 正式导入结果
  const [excelKinds, setExcelKinds] = useState([]);
  const [excelPending, setExcelPending] = useState(null);
  const [excelOutcome, setExcelOutcome] = useState(null);
  const [excelBusy, setExcelBusy] = useState('');

  useEffect(() => {
    async function loadCurrentUser() {
      if (!authToken) {
        setUserProfile({ username: '', role: 'staff' });
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });

        if (!response.ok) {
          throw new Error('401');
        }

        const data = await response.json();
        setUserProfile({ username: data.username, role: data.role || 'staff' });
      } catch {
        localStorage.removeItem('erp_token');
        setAuthToken('');
        setIsAuthenticated(false);
      }
    }

    loadCurrentUser();
  }, [authToken]);

  useEffect(() => {
    if (selectedTab !== 'inventory' || !authToken) return;
    // 从单据「查库存」跳进来时保留筛选；从左侧菜单正常进入则展示全量
    if (inventoryFocus) {
      refreshStock(inventoryKeyword);
    } else {
      if (inventoryKeyword) setInventoryKeyword('');
      refreshStock('');
    }
    // refreshStock 每次渲染都是新引用，这里只关心「切到库存页」这一个时机
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    // 离开库存/档案页就丢掉「跳转定位」，避免下次从菜单进来还挂着上一次的筛选与高亮
    if (selectedTab !== 'inventory' && inventoryFocus) setInventoryFocus(null);
    if (archiveFocus && selectedTab !== archiveFocus.tab) setArchiveFocus(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab]);

  useEffect(() => {
    if (selectedTab !== 'dataio' || !authToken) return;
    loadExcelKinds();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    if (selectedTab !== 'contracts' || !authToken) return;
    loadContractMeta();
    refreshContracts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    if (selectedTab !== 'settings' || !authToken) return;
    loadCompanySettings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    // 仓库是低频主数据，切到该页才拉取，不挤进首页那批并发请求
    if (selectedTab !== 'warehouses' || !authToken) return;
    refreshWarehouses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    // 订单页：只拉 doc_type=order 的单据；仓库下拉也在这里才取（低频主数据按页加载）
    if (selectedTab === 'purchase-order' && authToken) {
      refreshPurchaseOrderList();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'sales-order' && authToken) {
      refreshSalesOrderList();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'purchase' && authToken) {
      // 采购入库页：只拉 doc_type=inbound 的入库单 + 仓库下拉 + 现存量（商品行内提示）
      refreshPurchaseInboundList();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'sales' && authToken) {
      // 开单管理页：只拉 doc_type=outbound 的出库单 + 仓库下拉 + 现存量
      refreshSalesOutboundList();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'quotation' && authToken) {
      // 报价单页：列表 + 出货仓库下拉 + 付款/运输方式字典
      refreshQuotations();
      refreshWarehouses();
      loadQuotationMeta();
      refreshStock('');
    }
    if (selectedTab === 'purchase-return' && authToken) {
      // 采购退货页：列表 + 退货仓库下拉
      refreshPurchaseReturns();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'sales-return' && authToken) {
      // 销售退货页：列表 + 退货入库仓库下拉
      refreshSalesReturns();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'transfer' && authToken) {
      // 调拨管理页：列表 + 调出/调入仓库下拉 + 现存量（按仓库提示可调数量）
      refreshTransfers();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'stocktaking' && authToken) {
      // 盘点管理页：列表 + 盘点仓库下拉 + 现存量（盘点底稿按仓库带出账面数）
      refreshStocktakings();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'loss-overflow' && authToken) {
      // 报损报溢页：列表 + 发生仓库下拉 + 现存量（明细行内提示现存）
      refreshAdjustments();
      refreshWarehouses();
      refreshStock('');
    }
    if (selectedTab === 'production-plan' && authToken) {
      // 生产计划页：列表 + 生产仓库下拉（计划不写库存财务）
      refreshProductionPlans();
      refreshWarehouses();
    }
    if (selectedTab === 'mrp' && authToken) {
      // MRP 运算页：可选生产计划 + 仓库下拉
      refreshProductionPlans();
      refreshWarehouses();
    }
    if (selectedTab === 'material-issue' && authToken) {
      // 生产领料页：列表 + 仓库下拉 + 生产计划下拉（按计划带出底稿）
      refreshMaterialIssues();
      refreshWarehouses();
      refreshProductionPlans();
      refreshStock('');
    }
    if (selectedTab === 'material-return' && authToken) {
      // 生产退料页：列表 + 仓库下拉 + 生产计划下拉
      refreshMaterialReturns();
      refreshWarehouses();
      refreshProductionPlans();
      refreshStock('');
    }
    if (selectedTab === 'finished-goods' && authToken) {
      // 成品入库页：列表 + 仓库下拉 + 生产计划下拉（可按计划交库）
      refreshFinishedGoods();
      refreshWarehouses();
      refreshProductionPlans();
      refreshStock('');
    }
    if (selectedTab === 'outsourcing' && authToken) {
      // 委外加工页：列表 + 外协厂下拉 + 仓库下拉 + 现存量（发料行内提示现存）
      refreshOutsourcings();
      refreshWarehouses();
      refreshSuppliers();
      refreshStock('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 报表中心：进页面先拉目录（16 张报表的元数据由后端下发），目录只拉一次
  useEffect(() => {
    if (!authToken || selectedTab !== 'reports') return;
    refreshReportCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 报表中心：选中的报表或查询条件一变就重新取数
  useEffect(() => {
    if (!authToken || selectedTab !== 'reports' || !reportKey) return;
    refreshReportData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken, reportKey, reportQuery]);

  useEffect(() => {
    if (!authToken) return;
    // 变动查询要显示商品名/仓库名，顺带确保两张档案已加载
    if (selectedTab === 'stock-logs') {
      refreshInventory();
      refreshWarehouses();
    }
    if (selectedTab === 'receivable') refreshPartyBalances('customer');
    if (selectedTab === 'payable') refreshPartyBalances('supplier');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  useEffect(() => {
    async function loadDashboard() {
      if (!authToken) {
        setLoading(false);
        return;
      }

      try {
        const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
        const params = new URLSearchParams();
        if (analysisRange.startDate) params.set('start_date', analysisRange.startDate);
        if (analysisRange.endDate) params.set('end_date', analysisRange.endDate);
        const financeAnalysisUrl = `${API_BASE}/finance/analysis${params.toString() ? `?${params.toString()}` : ''}`;

        const [summaryRes, customersRes, suppliersRes, productsRes, purchaseRes, salesRes, productionRes, projectRes, inventoryRes, financeRes, financeAnalysisRes, financeDecisionRes, operationsRes, executiveRes, mobileRes, bomTreeRes, invoicesRes, invoicesSummaryRes] = await Promise.all([
          fetch(`${API_BASE}/summary`, { headers }),
          fetch(`${API_BASE}/customers`, { headers }),
          fetch(`${API_BASE}/suppliers`, { headers }),
          fetch(`${API_BASE}/products`, { headers }),
          fetch(`${API_BASE}/purchase-orders`, { headers }),
          fetch(`${API_BASE}/sales-orders`, { headers }),
          fetch(`${API_BASE}/production-orders`, { headers }),
          fetch(`${API_BASE}/projects`, { headers }),
          fetch(`${API_BASE}/inventory`, { headers }),
          fetch(`${API_BASE}/finance`, { headers }),
          fetch(financeAnalysisUrl, { headers }),
          fetch(`${API_BASE}/finance/decision-support`, { headers }),
          fetch(`${API_BASE}/dashboard/operations`, { headers }),
          fetch(`${API_BASE}/dashboard/executive`, { headers }),
          fetch(`${API_BASE}/mobile/dashboard`, { headers }),
          fetch(`${API_BASE}/production-boms/tree`, { headers }),
          fetch(`${API_BASE}/invoices`, { headers }),
          fetch(`${API_BASE}/invoices/summary`, { headers }),
        ]);

        if (!summaryRes.ok || !customersRes.ok || !suppliersRes.ok || !productsRes.ok || !purchaseRes.ok || !salesRes.ok || !productionRes.ok || !projectRes.ok || !inventoryRes.ok || !financeRes.ok || !financeAnalysisRes.ok || !financeDecisionRes.ok || !operationsRes.ok || !executiveRes.ok || !mobileRes.ok || !bomTreeRes.ok || !invoicesRes.ok || !invoicesSummaryRes.ok) {
          throw new Error('请求失败');
        }

        const [summaryData, customersData, suppliersData, productsData, purchaseData, salesData, productionData, projectData, inventoryData, financeData, financeAnalysisData, financeDecisionData, operationsData, executiveData, mobileData, bomTreeData, invoicesData, invoicesSummaryData] = await Promise.all([
          summaryRes.json(),
          customersRes.json(),
          suppliersRes.json(),
          productsRes.json(),
          purchaseRes.json(),
          salesRes.json(),
          productionRes.json(),
          projectRes.json(),
          inventoryRes.json(),
          financeRes.json(),
          financeAnalysisRes.json(),
          financeDecisionRes.json(),
          operationsRes.json(),
          executiveRes.json(),
          mobileRes.json(),
          bomTreeRes.json(),
          invoicesRes.json(),
          invoicesSummaryRes.json(),
        ]);

        setSummary(summaryData);
        setCustomers(customersData);
        setSuppliers(suppliersData);
        setProducts(productsData);
        setPurchaseOrders(purchaseData);
        setSalesOrders(salesData);
        setProductionOrders(productionData);
        setProjects(projectData);
        setInventory(inventoryData);
        setFinance(financeData);
        setFinanceAnalysis(financeAnalysisData);
        setFinanceDecision(financeDecisionData);
        setOperationsBoard(operationsData);
        setExecutiveDashboard(executiveData);
        setMobileDashboard(mobileData);
        setBomTree(Array.isArray(bomTreeData) ? bomTreeData : []);
        setInvoiceItems(Array.isArray(invoicesData) ? invoicesData.map(normalizeInvoiceRecord) : []);
        setInvoiceAggregate(invoicesSummaryData);
      } catch (err) {
        //setError('无法连接到 ERP 后端，请确认后端已启动。');
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
  }, [authToken, analysisRange.startDate, analysisRange.endDate]);

  const cards = useMemo(
    () =>
      summary
        ? [
            { label: '客户数', value: summary.customers ?? 0 },
            { label: '供应商数', value: summary.suppliers ?? 0 },
            { label: '产品数', value: summary.products ?? 0 },
            { label: '销售总额', value: `¥${Number(summary.sales_total ?? 0).toLocaleString()}` },
            { label: '采购总额', value: `¥${Number(summary.purchase_total ?? 0).toLocaleString()}` },
            { label: '财务总额', value: `¥${Number(summary.finance_total ?? 0).toLocaleString()}` },
          ]
        : [],
    [summary]
  );

  const overviewTrend = useMemo(() => {
    if (Array.isArray(financeAnalysis.monthly_trend) && financeAnalysis.monthly_trend.length > 0) {
      return financeAnalysis.monthly_trend.slice(-6).map((item) => ({
        label: item.month || '本月',
        income: Number(item.income || 0),
        expense: Number(item.expense || 0),
      }));
    }

    const baseSales = Number(summary?.sales_total || 0);
    const basePurchase = Number(summary?.purchase_total || 0);
    const baseFinance = Number(summary?.finance_total || 0);

    return [
      { label: '本月', income: baseSales, expense: basePurchase },
      { label: '上月', income: Math.max(baseSales * 0.9, 0), expense: Math.max(basePurchase * 0.92, 0) },
      { label: '前月', income: Math.max(baseSales * 0.8, 0), expense: Math.max(basePurchase * 0.86, 0) },
      { label: '3月', income: Math.max(baseSales * 0.72, 0), expense: Math.max(basePurchase * 0.82, 0) },
      { label: '4月', income: Math.max(baseSales * 0.68, 0), expense: Math.max(basePurchase * 0.78, 0) },
      { label: '5月', income: Math.max(baseSales * 0.64, 0), expense: Math.max(basePurchase * 0.74, 0) },
    ].map((item) => ({
      ...item,
      finance: baseFinance * 0.6,
    }));
  }, [financeAnalysis.monthly_trend, summary]);

  const leadershipBoard = useMemo(() => {
    const health = executiveDashboard.status?.health === 'healthy' ? 88 : 66;
    const cashFlow = Math.min(100, Math.max(40, ((Number(summary?.sales_total || 0) - Number(summary?.purchase_total || 0)) / Math.max(Number(summary?.sales_total || 0), 1)) * 100 + 20));
    const supplyRisk = Math.min(100, Math.max(15, (Number(executiveDashboard.status?.risk_count || 0) / 60) * 100));
    const productionHealth = Number(operationsBoard.work_report_summary?.progress_rate || 0);

    return {
      cards: [
        { label: '业务健康度', value: `${health}%`, tone: 'good' },
        { label: '现金流健康', value: `${cashFlow.toFixed(0)}%`, tone: 'good' },
        { label: '供应链风险', value: `${supplyRisk.toFixed(0)}%`, tone: supplyRisk > 60 ? 'warn' : 'good' },
        { label: '生产节奏', value: `${productionHealth.toFixed(0)}%`, tone: productionHealth > 70 ? 'good' : 'warn' },
      ],
      actions: [
        `优先处理 ${executiveDashboard.alerts?.[0]?.title || '库存风险'}，避免停线和交付延迟。`,
        `继续压缩非必要采购支出，提升 ${(Number(summary?.sales_total || 0) - Number(summary?.purchase_total || 0)) > 0 ? '利润率' : '成本控制'}。`,
        `盘点 ${operationsBoard.work_orders?.length || 0} 个工单的推进状态，确保生产线稳定运行。`,
      ],
    };
  }, [executiveDashboard, operationsBoard, summary]);

  const handleLoginChange = (field) => (event) => {
    setLoginForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleCustomerChange = (field) => (event) => {
    setCustomerForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleSupplierChange = (field) => (event) => {
    setSupplierForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleProductChange = (field) => (event) => {
    setProductForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const updateSalesOrderStatus = async (orderId, nextStatus) => {
    if (!orderId) return false;

    try {
      const response = await fetch(`${API_BASE}/sales-orders/${orderId}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ status: nextStatus }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '更新订单状态失败' }));
        throw new Error(errorData.detail ?? '更新订单状态失败');
      }

      const updatedOrder = await response.json();
      setSalesOrders((prev) => prev.map((item) => (item.id === orderId ? { ...item, status: updatedOrder.status || nextStatus } : item)));
      setSelectedSalesOrder((prev) => (prev && prev.id === orderId ? { ...prev, status: updatedOrder.status || nextStatus } : prev));
      setNotice(`订单 ${updatedOrder.order_no || orderId} 已更新为 ${updatedOrder.status || nextStatus}。`);
      return true;
    } catch (err) {
      setNotice(err.message || '更新订单状态失败');
      return false;
    }
  };

  const handleInventoryChange = (field) => (event) => {
    setInventoryForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleFinanceChange = (field) => (event) => {
    setFinanceForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleProductionChange = (field) => (event) => {
    setProductionForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleProjectChange = (field) => (event) => {
    setProjectForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleBomFormChange = (field) => (event) => {
    setBomForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const printPdf = async (path, filename) => {
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '生成打印文件失败' }));
        throw new Error(errorData.detail ?? '生成打印文件失败');
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice(`打印文件「${filename}」已生成并开始下载。`);
    } catch (err) {
      setNotice(err.message || '生成打印文件失败');
    }
  };

  const printPeriodQuery = () => {
    const params = new URLSearchParams();
    if (printParty.from) params.set('from_date', printParty.from);
    if (printParty.to) params.set('to_date', printParty.to);
    const qs = params.toString();
    return qs ? `?${qs}` : '';
  };

  // ── 数据导入导出（Excel）────────────────────────────────────────────────
  const authHeaders = () => (authToken ? { Authorization: `Bearer ${authToken}` } : {});

  async function loadExcelKinds() {
    try {
      const response = await fetch(`${API_BASE}/excel/kinds`, { headers: authHeaders() });
      if (!response.ok) return;
      const data = await response.json();
      setExcelKinds(Array.isArray(data) ? data : []);
    } catch {
      // 静默失败：页面会提示暂无可用类别
    }
  }

  const downloadFromApi = async (path, fallbackName) => {
    const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || '下载失败');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    let filename = fallbackName;
    const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
    if (utf8Match) filename = decodeURIComponent(utf8Match[1]);
    else if (plainMatch) filename = plainMatch[1];
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return filename;
  };

  const downloadExcelTemplate = async (kind, label) => {
    try {
      setExcelBusy(`template-${kind}`);
      const name = await downloadFromApi(`/excel/templates/${kind}`, `${label}.xlsx`);
      setNotice(`导入模板已下载：${name}`);
    } catch (err) {
      setNotice(err.message || '模板下载失败');
    } finally {
      setExcelBusy('');
    }
  };

  const exportExcelData = async (kind, label) => {
    try {
      setExcelBusy(`export-${kind}`);
      const name = await downloadFromApi(`/excel/export/${kind}`, `${label}.xlsx`);
      setNotice(`数据已导出：${name}`);
    } catch (err) {
      setNotice(err.message || '导出失败');
    } finally {
      setExcelBusy('');
    }
  };

  const runExcelImport = async (kind, file, dryRun) => {
    const form = new FormData();
    form.append('file', file);
    const response = await fetch(
      `${API_BASE}/excel/import/${kind}?mode=upsert&dry_run=${dryRun ? 'true' : 'false'}`,
      { method: 'POST', headers: authHeaders(), body: form },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || '导入失败');
    }
    return data;
  };

  const handleExcelFilePicked = (kind, label) => async (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    try {
      setExcelBusy(`import-${kind}`);
      setExcelOutcome(null);
      const preview = await runExcelImport(kind, file, true); // 先预检，不落库
      setExcelPending({ kind, label, fileName: file.name, file, preview });
    } catch (err) {
      setNotice(err.message || '预检失败');
    } finally {
      setExcelBusy('');
    }
  };

  const confirmExcelImport = async () => {
    if (!excelPending) return;
    const { kind, label, file } = excelPending;
    try {
      setExcelBusy(`import-${kind}`);
      const result = await runExcelImport(kind, file, false);
      setExcelOutcome({ kind, label, result });
      setExcelPending(null);
      setNotice(
        `${label}导入完成：新增 ${result.created}、更新 ${result.updated}、跳过 ${result.skipped}、失败 ${result.failed}`,
      );
      await reloadAfterImport(kind);
    } catch (err) {
      setNotice(err.message || '导入失败');
    } finally {
      setExcelBusy('');
    }
  };

  const reloadAfterImport = async (kind) => {
    const headers = authHeaders();
    const jobs = [];
    if (kind === 'products' || kind === 'opening-stock') {
      jobs.push(fetch(`${API_BASE}/products`, { headers }).then((r) => r.json()).then((d) => setProducts(d)));
    }
    if (kind === 'customers') {
      jobs.push(fetch(`${API_BASE}/customers`, { headers }).then((r) => r.json()).then((d) => setCustomers(d)));
    }
    if (kind === 'suppliers') {
      jobs.push(fetch(`${API_BASE}/suppliers`, { headers }).then((r) => r.json()).then((d) => setSuppliers(d)));
    }
    if (kind === 'opening-stock') {
      jobs.push(refreshStock());
    }
    await Promise.allSettled(jobs);
  };

  const handleDeleteConfirm = async () => {
    if (!confirmDelete) return;
    const { id, ids, endpoint, label, kind, force } = confirmDelete;
    setConfirmDelete(null);
    try {
      const url = force
        ? `${API_BASE}${endpoint}${endpoint.includes('?') ? '&' : '?'}force=true`
        : `${API_BASE}${endpoint}`;
      const response = await fetch(url, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: ids ? JSON.stringify({ ids }) : undefined,
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '删除失败' }));
        // 档案被业务数据引用时后端返回 409，改为二次确认，让用户决定是否强制删除
        if (response.status === 409 && ['customer', 'supplier', 'product', 'warehouse', 'contract', 'quotation'].includes(kind)) {
          // detail 可能是字符串（档案类）也可能是对象（合同带引用清单），统一取成可读文案
          const detail = errorData.detail;
          const reason = typeof detail === 'string'
            ? detail
            : [detail?.message, detail?.hint].filter(Boolean).join('；') || '该记录已被其他数据引用';
          setConfirmDelete({ id, endpoint, label, kind, force: true, blockedReason: reason });
          return;
        }
        throw new Error(errorData.detail ?? '删除失败');
      }
      if (kind === 'sales-order') {
        setSalesOrders((prev) => prev.filter((row) => row.id !== id));
        // 销售订单页（doc_type=order）与老开单页共用删除入口，两份列表都刷新
        setSalesOrderList((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'purchase-order') {
        setPurchaseOrderList((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'purchase-inbound') {
        setPurchaseOrders((prev) => prev.filter((row) => row.id !== id));
        // 入库单删除会冲销库存流水，现存量看板一并刷新
        refreshStock();
      } else if (kind === 'contract') {
        setContracts((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'quotation') {
        setQuotations((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'purchase-return') {
        setPurchaseReturns((prev) => prev.filter((row) => row.id !== id));
        // 退货单删除会冲销库存流水，现存量看板数据一并刷新
        refreshStock();
      } else if (kind === 'sales-return') {
        setSalesReturns((prev) => prev.filter((row) => row.id !== id));
        // 退货单删除会冲销库存流水，现存量看板数据一并刷新
        refreshStock();
      } else if (kind === 'inventory-transfer') {
        setTransfers((prev) => prev.filter((row) => row.id !== id));
        // 调拨单删除会同时冲销「调出/调入」两条流水，两侧仓库现存量一并刷新
        refreshStock();
      } else if (kind === 'stocktaking') {
        setStocktakings((prev) => prev.filter((row) => row.id !== id));
        // 盘点单删除会把盘盈盘亏一起冲销，现存量看板数据一并刷新
        refreshStock();
      } else if (kind === 'inventory-adjustment') {
        setAdjustments((prev) => prev.filter((row) => row.id !== id));
        // 报损报溢单删除会冲销库存流水，现存量看板数据一并刷新
        refreshStock();
      } else if (kind === 'production-plan') {
        // 生产计划不写库存不写财务，删单只需把列表里的这一行去掉
        setProductionPlans((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'material-issue') {
        setMaterialIssues((prev) => prev.filter((row) => row.id !== id));
        // 删领料单会把发出的材料退回仓库，现存量看板一并刷新
        refreshStock();
      } else if (kind === 'material-return') {
        setMaterialReturns((prev) => prev.filter((row) => row.id !== id));
        // 删退料单会把退回的料再扣回车间，现存量看板一并刷新
        refreshStock();
      } else if (kind === 'finished-goods') {
        setFinishedGoodsList((prev) => prev.filter((row) => row.id !== id));
        // 删成品入库单会把成品扣回车间并冲销成本流水，现存量看板一并刷新
        refreshStock();
      } else if (kind === 'outsourcing') {
        setOutsourcings((prev) => prev.filter((row) => row.id !== id));
        // 删委外单会冲销发料/收成品两类库存流水与加工费应付，现存量看板一并刷新
        refreshStock();
      } else if (kind === 'bom') {
        // BOM 是树形结构，删除后重新拉取整棵树
        const refreshed = await fetch(`${API_BASE}/production-boms/tree`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        const bomData = await refreshed.json();
        setBomTree(Array.isArray(bomData) ? bomData : []);
      } else if (kind === 'invoice') {
        setInvoiceItems((prev) => prev.filter((row) => row.id !== id));
        await refreshInvoiceAggregate();
      } else if (kind === 'invoice-batch') {
        setInvoiceItems((prev) => prev.filter((row) => !ids.includes(row.id)));
        setSelectedInvoiceIds([]);
        await refreshInvoiceAggregate();
      } else if (kind === 'customer') {
        setCustomers((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'supplier') {
        setSuppliers((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'product') {
        setProducts((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'warehouse') {
        setWarehouses((prev) => prev.filter((row) => row.id !== id));
        // 删掉的正是正在编辑的那条时，顺手把表单复位
        if (editingWarehouseId === id) {
          setWarehouseForm(emptyWarehouseForm);
          setEditingWarehouseId(null);
        }
      }
      setNotice(`${label}已删除。`);
    } catch (err) {
      setNotice(err.message || '删除失败');
    }
  };

  const refreshInvoiceAggregate = async () => {
    // 发票汇总数据跟着列表一起刷新
    const summaryRes = await fetch(`${API_BASE}/invoices/summary`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    });
    if (summaryRes.ok) {
      setInvoiceAggregate(await summaryRes.json());
    }
  };

  const toggleInvoiceSelect = (invoiceId) => {
    setSelectedInvoiceIds((prev) =>
      prev.includes(invoiceId) ? prev.filter((x) => x !== invoiceId) : [...prev, invoiceId]
    );
  };

  const toggleSelectAllInvoices = () => {
    const visibleIds = invoiceItems.slice(0, 8).map((row) => row.id);
    if (visibleIds.length > 0 && selectedInvoiceIds.length === visibleIds.length) {
      setSelectedInvoiceIds([]);
    } else {
      setSelectedInvoiceIds(visibleIds);
    }
  };

  const submitBomNode = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/production-boms`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          product_id: Number(bomForm.product_id),
          component_product_id: Number(bomForm.component_product_id),
          parent_id: bomForm.parent_id ? Number(bomForm.parent_id) : null,
          name: bomForm.name || null,
          code: bomForm.code || null,
          quantity: Number(bomForm.quantity || 1),
          unit_cost: Number(bomForm.unit_cost || 0),
          bom_type: bomForm.bom_type || 'component',
          level: Number(bomForm.level || 0),
          description: bomForm.description || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建 BOM 失败' }));
        throw new Error(errorData.detail ?? '创建 BOM 失败');
      }

      const refreshed = await fetch(`${API_BASE}/production-boms/tree`, {
        headers: { ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}) },
      });
      if (refreshed.ok) {
        const bomData = await refreshed.json();
        setBomTree(Array.isArray(bomData) ? bomData : []);
      }
      setBomForm({
        product_id: '',
        component_product_id: '',
        parent_id: '',
        name: '',
        code: '',
        quantity: '1',
        unit_cost: '0',
        bom_type: 'assembly',
        level: '0',
        description: '',
      });
      setNotice('BOM 节点已成功新增。');
    } catch (err) {
      setNotice(JSON.stringify(err) || 'BOM 新增失败');
    }
  };

  const renderBomTree = (nodes, depth = 0) =>
    nodes.map((node) => (
      <li key={node.id} className="bom-node-item">
        <div className="bom-node-row" style={{ marginLeft: `${depth * 18}px` }}>
          <span className="bom-node-label">{node.name || node.code || `BOM-${node.id}`}</span>
          <span className="bom-node-meta">{node.bom_type || 'component'} · {node.quantity}件</span>
          <button
            type="button"
            className="danger-btn"
            onClick={() =>
              setConfirmDelete({
                id: node.id,
                endpoint: `/production-boms/${node.id}`,
                label: `BOM 节点 ${node.name || node.code || node.id}`,
                kind: 'bom',
              })
            }
          >
            删除
          </button>
        </div>
        {node.children && node.children.length > 0 ? <ul className="bom-node-children">{renderBomTree(node.children, depth + 1)}</ul> : null}
      </li>
    ));

  const submitProductionOrder = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/production-orders`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          product_id: Number(productionForm.product_id),
          order_no: productionForm.order_no,
          quantity: Number(productionForm.quantity),
          status: productionForm.status,
          priority: productionForm.priority,
          note: productionForm.note || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建生产单失败' }));
        throw new Error(errorData.detail ?? '创建生产单失败');
      }

      const item = await response.json();
      setProductionOrders((prev) => [item, ...prev]);
      setProductionForm({ product_id: '', order_no: '', quantity: '1', status: 'planned', priority: 'normal', note: '' });
      setNotice('生产单已成功新增。');
    } catch (err) {
      setNotice(err.message || '生产单新增失败');
    }
  };

  const submitProject = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/projects`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          code: projectForm.code,
          name: projectForm.name,
          manager: projectForm.manager || null,
          status: projectForm.status,
          progress: Number(projectForm.progress),
          budget: Number(projectForm.budget),
          deadline: projectForm.deadline || null,
          note: projectForm.note || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建项目失败' }));
        throw new Error(errorData.detail ?? '创建项目失败');
      }

      const item = await response.json();
      setProjects((prev) => [item, ...prev]);
      setProjectForm({ code: '', name: '', manager: '', status: 'planned', progress: '0', budget: '0', deadline: '', note: '' });
      setNotice('项目已成功新增。');
    } catch (err) {
      setNotice(err.message || '项目新增失败');
    }
  };

  const inferInvoiceCategory = (item) => {
    const noteText = `${item?.note || ''} ${item?.customer_name || ''} ${item?.status || ''}`.toLowerCase(); 
    if (/采购|办公|耗材|设备|供应商|原材料|材料/.test(noteText)) return '采购';
    if (/销售|收入|客户|服务|订单/.test(noteText)) return '销售';
    if (/交通|差旅|出差|机票|酒店/.test(noteText)) return '差旅';
    if (/税|增值税|手续费|银行|利息/.test(noteText)) return '税费';
    return '其他';
  };

  const normalizeInvoiceRows = (list) =>
    Array.isArray(list)
      ? list.map((item, index) => ({
          id: item.id || item.invoice_no || item.invoiceId || item.no || `INV-${index + 1}`,
          customer_name: item.customer_name || item.customer || item.company || item.buyer || '未知客户',
          amount: Number(item.amount || item.total || item.invoice_amount || item.money || 0),
          date: item.date || item.invoice_date || item.issue_date || item.created_at || '—',
          status: item.status || item.payment_status || '已确认',
          note: item.note || item.remark || '',
          category: item.category || inferInvoiceCategory(item),
        }))
      : [];

  // 后端持久化发票 → 前端结构：保留全部字段，补上列表渲染用的别名
  const normalizeInvoiceRecord = (item) => ({
    ...item,
    id: item.id || item.invoice_no,
    invoice_no: item.invoice_no || item.id,
    customer_name: item.counterparty_name || item.seller_name || item.customer_name || '未知单位',
    seller_name: item.seller_name || item.counterparty_name || item.customer_name || '未知单位',
    buyer_name: item.buyer_name || '—',
    amount: Number(item.total_amount ?? item.amount ?? 0),
    date: item.issue_date || item.date || '—',
    status: item.status || '已确认',
    category: item.category || inferInvoiceCategory(item),
    items: Array.isArray(item.items) ? item.items : [],
  });

  // 月份渲染统一入口：解析失败（空值/不规范格式）显示"未知月份"，绝不输出 NaN
  const formatMonth = (month) => {
    const match = String(month || '').match(/^(\d{4})-(\d{1,2})$/);
    if (!match) return '未知月份';
    return `${match[1]}年${Number(match[2])}月`;
  };

  const parseStructuredInvoiceText = (rawText) => {
    const text = String(rawText || '').trim();
    if (!text) {
      return [];
    }

    const parseCsvLine = (line) => {
      const matches = line.match(/(".*?"|[^,]+)(?=,|$)/g) || [];
      return matches.map((cell) => cell.replace(/^"|"$/g, '').trim());
    };

    try {
      const parsed = JSON.parse(text);
      const list = Array.isArray(parsed) ? parsed : parsed.invoices || parsed.data || parsed.items || [];
      return normalizeInvoiceRows(list);
    } catch {
      if (/=/.test(text) && /(?:customer|amount|invoice|buyer|total)/i.test(text)) {
        const records = text
          .split(/[\r\n;]+/)
          .map((line) => line.trim())
          .filter(Boolean)
          .map((line) => {
            const pairs = line.split(/\s*[,;]\s*/).filter(Boolean);
            const entry = {};
            pairs.forEach((part) => {
              const match = part.match(/^([^:=]+)\s*[:=]\s*(.+)$/);
              if (match) {
                entry[match[1].trim().toLowerCase()] = match[2].trim();
              }
            });
            return entry;
          })
          .filter((entry) => entry.customer || entry.customer_name || entry.amount || entry.total || entry.invoice_no);

        if (records.length > 0) {
          return records.map((entry, index) => ({
            id: entry.invoice_no || entry.no || entry.id || `INV-${index + 1}`,
            customer_name: entry.customer_name || entry.customer || entry.buyer || '未知客户',
            amount: Number(entry.amount || entry.total || entry.invoice_amount || 0),
            date: entry.date || entry.invoice_date || entry.issue_date || '—',
            status: entry.status || entry.payment_status || '已确认',
            note: entry.note || entry.remark || '',
          }));
        }
      }

      const rows = text.split(/\r?\n/).filter(Boolean);
      if (rows.length < 2) return [];

      const headers = parseCsvLine(rows[0]).map((header) => header.toLowerCase().replace(/\s+/g, '_'));
      return rows.slice(1).map((line, index) => {
        const values = parseCsvLine(line);
        const record = {};
        headers.forEach((header, idx) => {
          record[header] = values[idx] || '';
        });
        return {
          id: record.invoice_no || record.no || record.id || `INV-${index + 1}`,
          customer_name: record.customer_name || record.customer || record.company || '未知客户',
          amount: Number(record.amount || record.total || record.invoice_amount || 0),
          date: record.date || record.invoice_date || record.issue_date || '—',
          status: record.status || record.payment_status || '已确认',
          note: record.note || record.remark || '',
        };
      }).filter((row) => row.customer_name || row.amount || row.id);
    }
  };

  const readPdfInvoiceText = async (file) => {
    const buffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
    let extractedText = '';

    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const pageText = await page.getTextContent();
      extractedText += pageText.items.map((item) => ('str' in item ? item.str : '')).join(' ') + '\n';
    }

    return normalizeInvoiceRows(parseStructuredInvoiceText(extractedText));
  };

  const readQrFromImage = async (file) => {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('二维码读取失败'));
      reader.readAsDataURL(file);
    });

    const img = new Image();
    img.src = dataUrl;
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
    });

    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    canvas.width = img.width;
    canvas.height = img.height;
    context.drawImage(img, 0, 0, canvas.width, canvas.height);
    const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imageData.data, canvas.width, canvas.height, { inversionAttempts: 'dontInvert' });

    if (!code) {
      return [];
    }

    return normalizeInvoiceRows(parseStructuredInvoiceText(code.data));
  };

  const readImageInvoiceText = async (file) => {
    try {
      const { data } = await Tesseract.recognize(file, 'chi_sim+eng');
      const textFromOcr = data?.text || '';
      const qrItems = await readQrFromImage(file);
      const ocrItems = normalizeInvoiceRows(parseStructuredInvoiceText(textFromOcr));
      const combined = [...qrItems, ...ocrItems];
      if (combined.length > 0) {
        return combined;
      }
      return [];
    } catch {
      return [];
    }
  };

  const classifyInvoiceBatch = async (records) => {
    const sanitized = records.map((item) => ({
      ...item,
      category: item.category || inferInvoiceCategory(item),
      amount: Number(item.amount || 0),
    }));

    try {
      const response = await fetch(`${API_BASE}/invoices/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ invoices: sanitized }),
      });

      if (!response.ok) {
        throw new Error('classification failed');
      }

      const data = await response.json();
      if (Array.isArray(data.items) && data.items.length > 0) {
        // 与原始记录合并：保留 OCR 提取的双方信息、明细、原始文本
        const originals = new Map(sanitized.map((record) => [record.invoice_no || record.id, record]));
        return data.items.map((item) => {
          const original = originals.get(item.invoice_no || item.id) || {};
          return {
            ...original,
            ...item,
            amount: Number(item.amount || original.amount || 0),
            category: item.category || inferInvoiceCategory(item),
          };
        });
      }
    } catch {
      // 回退到本地分类逻辑，确保功能可用。
    }

    return sanitized.map((item) => ({
      ...item,
      category: inferInvoiceCategory(item),
    }));
  };

  const parseInvoiceText = async (file) => {
    const extension = file.name.split('.').pop()?.toLowerCase();

    if (extension === 'pdf') {
      return readPdfInvoiceText(file);
    }

    if (['png', 'jpg', 'jpeg', 'bmp', 'gif', 'webp'].includes(extension)) {
      return readImageInvoiceText(file);
    }

    const rawText = await file.text();
    return normalizeInvoiceRows(parseStructuredInvoiceText(rawText));
  };

  const handleInvoiceUpload = async (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;

    try {
      setNotice('正在批量识别发票内容，请稍候...');
      const allItems = [];
      let backendFailed = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);

        const ocrResponse = await fetch(`${API_BASE}/invoices/parse`, {
          method: 'POST',
          headers: {
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: formData,
        });

        if (ocrResponse.ok) {
          const ocrData = await ocrResponse.json();
          // 只有真实识别结果才入库（rapidocr/paddleocr=OCR、qrcode=二维码、pdf_text=PDF 文本层），
          // 避免把兜底占位文字当成发票记录塞给用户
          const realOcr = ocrData && ['rapidocr', 'paddleocr', 'qrcode', 'pdf_text'].includes(ocrData.provider);
          if (realOcr) {
            allItems.push({
              id: ocrData.invoice_no,
              invoice_no: ocrData.invoice_no || `INV-${allItems.length + 1}`,
              customer_name: ocrData.seller_name || '本地发票',
              amount: Number(ocrData.total_amount || 0),
              date: ocrData.invoice_date || '—',
              status: '已确认',
              note: ({ rapidocr: '本地OCR识别', paddleocr: 'OCR识别', qrcode: '二维码识别', pdf_text: 'PDF文本提取' })[ocrData.provider] || 'OCR识别',
              category: '采购',
              invoice_type: ocrData.invoice_type || '未知',
              invoice_code: ocrData.invoice_code || '',
              tax_rate: ocrData.tax_rate ?? null,
              tax_amount: ocrData.tax_amount ?? null,
              excl_tax_amount: ocrData.excl_tax_amount ?? null,
              deducted: false,
              counterparty_name: ocrData.seller_name || '',
              buyer_name: ocrData.buyer_name || '',
              buyer_tax_no: ocrData.buyer_tax_no || '',
              seller_name: ocrData.seller_name || '',
              seller_tax_no: ocrData.seller_tax_no || '',
              items: ocrData.items || [],
              raw_text: ocrData.raw_text || '',
            });
          } else {
            backendFailed += 1;
          }
        } else {
          backendFailed += 1;
        }

        const parsedItems = await parseInvoiceText(file);
        allItems.push(...parsedItems);
      }

      const classifiedItems = await classifyInvoiceBatch(allItems);

      // 保存到数据库（后端按发票号码幂等去重，重复上传不会重复入库）
      let savedCount = 0;
      for (const item of classifiedItems) {
        try {
          const saveResponse = await fetch(`${API_BASE}/invoices`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
            },
            body: JSON.stringify({
              invoice_no: item.invoice_no || item.id,
              invoice_type: item.invoice_type || (item.tax_rate ? '专票' : '未知'),
              issue_date: item.date && item.date !== '—' ? item.date : null,
              counterparty_name: item.customer_name,
              invoice_code: item.invoice_code || null,
              total_amount: Number(item.amount || 0),
              tax_rate: item.tax_rate ?? null,
              tax_amount: item.tax_amount ?? null,
              excl_tax_amount: item.excl_tax_amount ?? null,
              deducted: Boolean(item.deducted),
              category: item.category || '其他',
              status: item.status,
              buyer_name: item.buyer_name || null,
              buyer_tax_no: item.buyer_tax_no || null,
              seller_name: item.seller_name || null,
              seller_tax_no: item.seller_tax_no || null,
              items: Array.isArray(item.items) ? item.items : [],
              raw_text: item.raw_text || null,
            }),
          });
          if (saveResponse.ok) {
            savedCount += 1;
          }
        } catch {
          // 保存失败不阻塞识别结果展示
        }
      }

      // 展示以数据库为准（含历史发票），汇总数据同步刷新
      try {
        const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
        const [listRes, summaryRes] = await Promise.all([
          fetch(`${API_BASE}/invoices`, { headers }),
          fetch(`${API_BASE}/invoices/summary`, { headers }),
        ]);
        if (listRes.ok) {
          const dbList = await listRes.json();
          setInvoiceItems(Array.isArray(dbList) ? dbList.map(normalizeInvoiceRecord) : classifiedItems);
        } else {
          setInvoiceItems(classifiedItems);
        }
        if (summaryRes.ok) {
          setInvoiceAggregate(await summaryRes.json());
        }
      } catch {
        setInvoiceItems(classifiedItems);
      }

      if (classifiedItems.length > 0) {
        setNotice(
          `已批量处理 ${files.length} 个文件，识别到 ${classifiedItems.length} 条发票记录，已保存 ${savedCount} 条到数据库` +
          (backendFailed > 0 ? `（${backendFailed} 个后端识别失败，已用浏览器识别兜底）` : '。')
        );
      } else {
        setNotice('未能从发票中识别出内容：请确认图片清晰、为印刷体，并检查本地 OCR 引擎依赖。');
      }
    } catch (err) {
      setNotice('发票文件读取失败，请检查文件格式或图片质量。');
    }
  };

  const handleDeepSeekInvoiceAnalysis = async () => {
    if (invoiceItems.length === 0) {
      setNotice('请先上传或解析发票后再执行智能分析。');
      return;
    }

    try {
      const data = await classifyInvoiceBatch(invoiceItems);
      setInvoiceItems(data);
      setNotice('智能发票分类已完成。');
    } catch (err) {
      setNotice('智能分析失败，已自动回退到本地分类。');
    }
  };

  const handleInvoiceAgentAnalysis = async () => {
    if (invoiceItems.length === 0) {
      setNotice('请先上传发票后再让智能体分析。');
      return;
    }
    setNotice('智能体正在分析发票汇总数据...');
    try {
      const response = await fetch(`${API_BASE}/invoices/agent-analysis`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ summary: invoiceAggregate }),
      });
      if (response.ok) {
        const report = await response.json();
        setInvoiceAgentReport(report);
        setNotice(report.provider === 'deepseek' ? '智能体分析完成（DeepSeek）。' : '智能体分析完成（本地规则兜底：未配置 DEEPSEEK_API_KEY）。');
      } else {
        setNotice('智能体分析失败，请稍后重试。');
      }
    } catch {
      setNotice('智能体分析失败：无法连接后端。');
    }
  };

  const handleSyncInvoicesToFinance = async () => {
    if (invoiceItems.length === 0) {
      setNotice('当前没有可同步到财务的发票。');
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/invoices/sync-finance`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        const result = await response.json();
        setNotice(`财务同步完成：${result.message}`);
        // 财务数据刷新
        const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
        const params = new URLSearchParams();
        if (analysisRange.startDate) params.set('start_date', analysisRange.startDate);
        if (analysisRange.endDate) params.set('end_date', analysisRange.endDate);
        const [financeRes, analysisRes] = await Promise.all([
          fetch(`${API_BASE}/finance`, { headers }),
          fetch(`${API_BASE}/finance/analysis${params.toString() ? `?${params.toString()}` : ''}`, { headers }),
        ]);
        if (financeRes.ok) setFinance(await financeRes.json());
        if (analysisRes.ok) setFinanceAnalysis(await analysisRes.json());
      } else {
        setNotice('财务同步失败，请稍后重试。');
      }
    } catch {
      setNotice('财务同步失败：无法连接后端。');
    }
  };

  const handleToggleDeducted = async (item) => {
    if (!item || item.id == null) return;
    const nextDeducted = !item.deducted;
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ deducted: nextDeducted }),
      });
      if (response.ok) {
        const updated = await response.json();
        setInvoiceItems((prev) => prev.map((row) => (row.id === updated.id ? normalizeInvoiceRecord(updated) : row)));
        const summaryRes = await fetch(`${API_BASE}/invoices/summary`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        if (summaryRes.ok) setInvoiceAggregate(await summaryRes.json());
        setNotice(nextDeducted ? '已标记为已抵扣。' : '已取消抵扣标记。');
      } else {
        setNotice('更新抵扣状态失败。');
      }
    } catch {
      setNotice('更新抵扣状态失败：无法连接后端。');
    }
  };

  // 勾选导出 Excel：只导出勾选的发票，按开票日期升序 + 同日期按购买方名称拼音排序
  const exportInvoiceReportXlsx = () => {
    if (selectedInvoiceIds.length === 0) {
      setNotice('请先在发票列表里勾选要导出的条目。');
      return;
    }

    const selected = invoiceItems.filter((item) => selectedInvoiceIds.includes(item.id));
    if (selected.length === 0) {
      setNotice('没有找到勾选的发票记录。');
      return;
    }

    // 双重排序：日期升序（空日期排最后），同一日期按购买方名称首字母（拼音）排序
    const sorted = [...selected].sort((a, b) => {
      const dateA = String(a.date || '');
      const dateB = String(b.date || '');
      const cmp = dateA === dateB ? 0 : dateA ? (dateB ? dateA.localeCompare(dateB) : -1) : 1;
      if (cmp !== 0) return cmp;
      return String(a.buyer_name || '').localeCompare(String(b.buyer_name || ''), 'zh-Hans-CN');
    });

    const sheetRows = sorted.map((item) => ({
      开票日期: item.date || '—',
      发票号码: item.invoice_no || item.id || '—',
      销售方名称: item.seller_name || '—',
      购买方名称: item.buyer_name || '—',
      发票代码: item.invoice_code || '—',
      发票类型: item.invoice_type || '未知',
      分类: item.category || inferInvoiceCategory(item),
      税价合计: Number(item.amount || 0),
      税率: item.tax_rate != null ? `${item.tax_rate}%` : '—',
      不含税额: Number(item.excl_tax_amount || 0),
      税额: Number(item.tax_amount || 0),
      已抵扣: item.invoice_type === '专票' ? (item.deducted ? '是' : '否') : '—',
    }));

    const worksheet = XLSX.utils.json_to_sheet(sheetRows);
    worksheet['!cols'] = [
      { wch: 12 }, { wch: 24 }, { wch: 28 }, { wch: 28 }, { wch: 14 }, { wch: 10 },
      { wch: 10 }, { wch: 12 }, { wch: 8 }, { wch: 12 }, { wch: 12 }, { wch: 8 },
    ];
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, '发票报表');

    const fileName = `erp_invoice_report_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(workbook, fileName);
    setNotice(`已导出 ${sorted.length} 张发票到 ${fileName}`);
  };

  const exportInvoiceReport = () => {
    if (invoiceItems.length === 0) {
      setNotice('当前没有可导出的发票记录。');
      return;
    }

    const rows = invoiceItems.map((item) => ({
      invoice_no: item.id || item.invoice_no || '',
      customer_name: item.customer_name || '',
      category: item.category || inferInvoiceCategory(item),
      amount: Number(item.amount || 0),
      date: item.date || '',
      status: item.status || '',
      note: item.note || '',
    }));

    const headers = ['invoice_no', 'customer_name', 'category', 'amount', 'date', 'status', 'note'];
    const csv = [headers.join(',')]
      .concat(rows.map((row) => headers.map((key) => `"${String(row[key] ?? '').replace(/"/g, '""')}"`).join(',')))
      .join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'erp_invoice_report.csv';
    anchor.click();
    URL.revokeObjectURL(url);
    setNotice('发票报表已导出为 CSV。');
  };

  const exportInvoiceReportHtml = () => {
    if (invoiceItems.length === 0) {
      setNotice('当前没有可导出的发票记录。');
      return;
    }

    const rows = invoiceItems.map((item) => {
      const detail = (item.items || [])
        .map((line) => `${line.item_name || ''} ×${line.quantity ?? 1} ¥${Number(line.amount || 0).toFixed(2)}`)
        .join('；');
      return {
        invoice_no: item.invoice_no || item.id || '—',
        date: item.date || '—',
        buyer: [item.buyer_name, item.buyer_tax_no].filter(Boolean).join('<br>') || '—',
        seller: [item.seller_name || item.customer_name, item.seller_tax_no].filter(Boolean).join('<br>') || '—',
        detail: detail || '—',
        amount: Number(item.amount || 0),
        category: item.category || inferInvoiceCategory(item),
        status: item.status || '—',
      };
    });

    const total = rows.reduce((sum, row) => sum + row.amount, 0);
    const byCategory = {};
    rows.forEach((row) => {
      byCategory[row.category] = (byCategory[row.category] || 0) + row.amount;
    });

    const escapeHtml = (value) => String(value ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    const categoryChips = Object.entries(byCategory)
      .map(([category, amount]) => `<span class="chip">${escapeHtml(category)}：¥${Number(amount).toLocaleString()}</span>`)
      .join('');

    const bodyRows = rows.map((row) => `
      <tr>
        <td>${escapeHtml(row.invoice_no)}</td>
        <td>${escapeHtml(row.date)}</td>
        <td class="party">${escapeHtml(row.buyer)}</td>
        <td class="party">${escapeHtml(row.seller)}</td>
        <td class="detail">${escapeHtml(row.detail)}</td>
        <td class="num">¥${Number(row.amount).toLocaleString()}</td>
        <td>${escapeHtml(row.category)}</td>
        <td>${escapeHtml(row.status)}</td>
      </tr>`).join('');

    const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>发票汇总报表</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #1e293b; background: #f1f5f9; padding: 32px; }
  .sheet { max-width: 1080px; margin: 0 auto; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 16px rgba(15, 23, 42, .08); overflow: hidden; }
  .head { background: linear-gradient(135deg, #2563eb, #1e40af); color: #fff; padding: 24px 32px; }
  .head h1 { font-size: 22px; font-weight: 600; }
  .head p { font-size: 13px; opacity: .85; margin-top: 6px; }
  .summary { display: flex; gap: 12px; flex-wrap: wrap; padding: 20px 32px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }
  .summary .chip { background: #eef2ff; color: #3730a3; border: 1px solid #c7d2fe; border-radius: 999px; padding: 6px 14px; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th { background: #f1f5f9; color: #475569; text-align: left; padding: 12px 14px; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }
  tbody td { padding: 12px 14px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
  tbody tr:nth-child(even) { background: #f8fafc; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  td.party, td.detail { max-width: 200px; }
  tfoot td { padding: 14px; font-weight: 700; background: #eff6ff; border-top: 2px solid #bfdbfe; }
  .foot { padding: 16px 32px; color: #64748b; font-size: 12px; border-top: 1px solid #e2e8f0; }
  @media print { body { background: #fff; padding: 0; } .sheet { box-shadow: none; border-radius: 0; } }
</style>
</head>
<body>
<div class="sheet">
  <div class="head">
    <h1>发票汇总报表</h1>
    <p>导出时间：${new Date().toLocaleString('zh-CN')} · 共 ${rows.length} 张 · 合计 ¥${Number(total).toLocaleString()}</p>
  </div>
  <div class="summary">${categoryChips}</div>
  <table>
    <thead>
      <tr><th>发票号码</th><th>开票日期</th><th>购买方</th><th>销售方</th><th>产品明细</th><th>金额</th><th>分类</th><th>状态</th></tr>
    </thead>
    <tbody>${bodyRows}</tbody>
    <tfoot>
      <tr><td colspan="5">合计（${rows.length} 张发票）</td><td class="num">¥${Number(total).toLocaleString()}</td><td colspan="2"></td></tr>
    </tfoot>
  </table>
  <div class="foot">本报表由本地 ERP 系统生成 · 表格可在浏览器中直接打印或另存为 PDF</div>
</div>
</body>
</html>`;

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `erp_invoice_report_${new Date().toISOString().slice(0, 10)}.html`;
    anchor.click();
    URL.revokeObjectURL(url);
    setNotice('发票汇总已导出为美观表格（HTML，可打印为 PDF）。');
  };

  const exportDailyReport = async () => {
    try {
      const response = await fetch(`${API_BASE}/reports/daily-export`, {
        headers: {
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });

      if (!response.ok) {
        throw new Error('日报导出失败');
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `erp_daily_report_${new Date().toISOString().slice(0, 10)}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice('日报表已导出为 CSV。');
    } catch (err) {
      setNotice(err.message || '日报导出失败');
    }
  };

  const invoiceSummary = useMemo(() => {
    const total = invoiceItems.reduce((sum, item) => sum + Number(item.amount || 0), 0);
    const customerMap = new Map();
    const categoryMap = new Map();

    for (const item of invoiceItems) {
      const key = item.customer_name || '未知客户';
      customerMap.set(key, (customerMap.get(key) || 0) + Number(item.amount || 0));
      const categoryKey = item.category || inferInvoiceCategory(item);
      categoryMap.set(categoryKey, (categoryMap.get(categoryKey) || 0) + Number(item.amount || 0));
    }

    return {
      total,
      count: invoiceItems.length,
      topCustomers: [...customerMap.entries()].map(([customer_name, totalAmount]) => ({ customer_name, totalAmount })).sort((a, b) => b.totalAmount - a.totalAmount).slice(0, 5),
      byCategory: [...categoryMap.entries()].map(([category, totalAmount]) => ({ category, totalAmount })).sort((a, b) => b.totalAmount - a.totalAmount),
    };
  }, [invoiceItems]);

  const handleAnalysisRangeChange = (field) => (event) => {
    setAnalysisRange((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const submitAgentPrompt = async () => {
    try {
      const response = await fetch(`${API_BASE}/agent/assistant`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          prompt: agentPrompt,
          context: {
            customers: summary?.customers ?? 0,
            products: summary?.products ?? 0,
            sales_total: summary?.sales_total ?? 0,
            purchase_total: summary?.purchase_total ?? 0,
            finance_total: summary?.finance_total ?? 0,
          },
        }),
      });

      if (!response.ok) {
        throw new Error('智能体调用失败');
      }

      const data = await response.json();
      setAgentResponse({
        answer: data.answer || '暂无建议。',
        summary: data.summary || {},
        risk_level: data.risk_level || '健康',
      });
      setNotice('移动助手已完成分析。');
    } catch (err) {
      setNotice(err.message || '智能体分析失败');
    }
  };

  const submitLogin = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '登录失败' }));
        throw new Error(errorData.detail ?? '登录失败');
      }

      const data = await response.json();
      const nextToken = data.access_token;
      const nextRole = data.role || 'staff';
      localStorage.setItem('erp_token', nextToken);
      localStorage.setItem('erp_user', JSON.stringify({ username: loginForm.username, role: nextRole }));
      setUserProfile({ username: loginForm.username, role: nextRole });
      setAuthToken(nextToken);
      setIsAuthenticated(true);
      setLoginForm({ username: '', password: '' });
      setNotice('登录成功。');
    } catch (err) {
      setNotice(err.message || '登录失败');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('erp_token');
    localStorage.removeItem('erp_user');
    setUserProfile({ username: '', role: 'staff' });
    setAuthToken('');
    setIsAuthenticated(false);
    setNotice('已退出登录。');
  };

  const submitCustomer = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/customers`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          ...customerForm,
          phone: customerForm.phone || null,
          email: customerForm.email || null,
          address: customerForm.address || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建客户失败' }));
        throw new Error(errorData.detail ?? '创建客户失败');
      }

      const newCustomer = await response.json();
      setCustomers((prev) => [newCustomer, ...prev]);
      setCustomerForm(emptyCustomerForm);
      setNotice('客户已成功新增。');
    } catch (err) {
      setNotice(err.message || '客户新增失败');
    }
  };

  const submitSupplier = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/suppliers`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          ...supplierForm,
          phone: supplierForm.phone || null,
          email: supplierForm.email || null,
          address: supplierForm.address || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建供应商失败' }));
        throw new Error(errorData.detail ?? '创建供应商失败');
      }

      const newSupplier = await response.json();
      setSuppliers((prev) => [newSupplier, ...prev]);
      setSupplierForm(emptySupplierForm);
      setNotice('供应商已成功新增。');
    } catch (err) {
      setNotice(err.message || '供应商新增失败');
    }
  };

  // ---------- 仓库档案 ----------

  const handleWarehouseChange = (field) => (event) => {
    const value = field === 'is_active' ? event.target.checked : event.target.value;
    setWarehouseForm((prev) => ({ ...prev, [field]: value }));
  };

  async function refreshWarehouses() {
    try {
      const response = await fetch(`${API_BASE}/warehouses`, { headers: authHeaders() });
      if (!response.ok) throw new Error('仓库列表加载失败');
      const data = await response.json();
      setWarehouses(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '仓库列表加载失败');
    }
  }

  async function refreshSuppliers() {
    try {
      const response = await fetch(`${API_BASE}/suppliers`, { headers: authHeaders() });
      if (!response.ok) throw new Error('供应商列表加载失败');
      const data = await response.json();
      setSuppliers(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '供应商列表加载失败');
    }
  }

  const resetWarehouseForm = () => {
    setWarehouseForm(emptyWarehouseForm);
    setEditingWarehouseId(null);
  };

  const startEditWarehouse = (row) => {
    setEditingWarehouseId(row.id);
    setWarehouseForm({
      code: row.code || '',
      name: row.name || '',
      location: row.location || '',
      manager: row.manager || '',
      phone: row.phone || '',
      is_active: row.is_active !== false,
      note: row.note || '',
    });
    setNotice('');
  };

  const submitWarehouse = async (event) => {
    event.preventDefault();
    setNotice('');

    const payload = {
      code: warehouseForm.code,
      name: warehouseForm.name,
      location: warehouseForm.location || null,
      manager: warehouseForm.manager || null,
      phone: warehouseForm.phone || null,
      is_active: warehouseForm.is_active,
      note: warehouseForm.note || null,
    };

    try {
      const isEdit = editingWarehouseId != null;
      const response = await fetch(
        isEdit ? `${API_BASE}/warehouses/${editingWarehouseId}` : `${API_BASE}/warehouses`,
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...authHeaders(),
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存仓库失败' }));
        const detail = errorData.detail ?? '保存仓库失败';
        throw new Error(
          typeof detail === 'string' && detail.includes('already exists') ? '仓库编码已存在' : detail,
        );
      }

      const saved = await response.json();
      if (isEdit) {
        setWarehouses((prev) => prev.map((row) => (row.id === saved.id ? saved : row)));
        setNotice(`仓库「${saved.name}」已更新。`);
      } else {
        setWarehouses((prev) => [saved, ...prev]);
        setNotice(`仓库「${saved.name}」已新增。`);
      }
      resetWarehouseForm();
    } catch (err) {
      setNotice(err.message || '保存仓库失败');
    }
  };

  // ---------- 变动查询 / 应收应付 / 往来对账 ----------

  async function refreshInventory() {
    try {
      const response = await fetch(`${API_BASE}/inventory`, { headers: authHeaders() });
      if (response.ok) setInventory(await response.json());
    } catch {
      // 拉取失败保留上一次数据，不打断页面
    }
  }

  // 应收（客户）/ 应付（供应商）汇总，共用一个函数
  async function refreshPartyBalances(partyType) {
    const path = partyType === 'customer' ? '/finance/receivable' : '/finance/payable';
    try {
      const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('往来账加载失败');
      const data = await response.json();
      if (partyType === 'customer') setReceivables(data);
      else setPayables(data);
    } catch (err) {
      setNotice(err.message || '往来账加载失败');
    }
  }

  // 账龄分析：按需触发（后端 FIFO 冲抵，不进页自动跑）
  async function loadAging(partyType) {
    setFinanceBusy(`aging-${partyType}`);
    try {
      const response = await fetch(`${API_BASE}/finance/aging?party_type=${partyType}`, {
        headers: authHeaders(),
      });
      if (response.ok) setAging(await response.json());
    } catch (err) {
      setNotice(err.message || '账龄分析失败');
    } finally {
      setFinanceBusy('');
    }
  }

  // 往来对账：期初余额 → 逐笔发生 → 期末余额（对账单同源）
  async function loadLedger(partyType, partyId, from, to) {
    const type = partyType || ledgerParty.party_type;
    const pid = partyId || ledgerParty.party_id;
    if (!pid) {
      setNotice('请先选择往来单位');
      return;
    }
    const f = from ?? ledgerParty.from;
    const t = to ?? ledgerParty.to;
    setFinanceBusy('ledger');
    try {
      const params = new URLSearchParams();
      if (f) params.set('from_date', f);
      if (t) params.set('to_date', t);
      const qs = params.toString() ? `?${params}` : '';
      const response = await fetch(`${API_BASE}/finance/reconciliation/${type}/${pid}${qs}`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error('往来账加载失败');
      setLedgerData(await response.json());
    } catch (err) {
      setNotice(err.message || '往来账加载失败');
      setLedgerData(null);
    } finally {
      setFinanceBusy('');
    }
  }

  // 应收 / 应付共用一个页面骨架，只换数据源与标题
  const renderPartyBalancePage = (partyType) => {
    const isCustomer = partyType === 'customer';
    const rows = isCustomer ? receivables : payables;
    const title = isCustomer ? '应收账款' : '应付账款';
    const partyWord = isCustomer ? '客户' : '供应商';
    const parties = isCustomer ? customers : suppliers;
    const total = rows.reduce((sum, row) => sum + Number(row.balance || 0), 0);
    const agingActive = aging.party_type === partyType;
    const statementPath = (partyId) => {
      const params = new URLSearchParams();
      if (printParty.from) params.set('from_date', printParty.from);
      if (printParty.to) params.set('to_date', printParty.to);
      const qs = params.toString() ? `?${params}` : '';
      return `/print/statement/${partyType}/${partyId}${qs}`;
    };

    return (
      <div className="management-grid">
        <section className="panel form-panel">
          <div className="section-header">
            <h2>{title}</h2>
            <span className="status-badge">未{isCustomer ? '收' : '付'}余额</span>
          </div>

          <div className="report-summary-grid" style={{ marginBottom: '16px' }}>
            <div className="metric-card">
              <span>{isCustomer ? '应收合计' : '应付合计'}</span>
              <strong>¥{total.toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
            </div>
            <div className="metric-card">
              <span>{partyWord}数</span>
              <strong>{rows.length}</strong>
            </div>
          </div>

          <div className="contract-item-actions">
            <button type="button" className="secondary-btn small-btn" onClick={() => refreshPartyBalances(partyType)}>
              刷新
            </button>
            <button
              type="button"
              className="secondary-btn small-btn"
              disabled={financeBusy === `aging-${partyType}`}
              onClick={() => loadAging(partyType)}
            >
              {financeBusy === `aging-${partyType}` ? '计算中…' : '账龄分析'}
            </button>
          </div>

          {agingActive && (
            <>
              <div className="stock-kpis" style={{ marginTop: '16px' }}>
                {Object.entries(aging.buckets || {}).map(([bucket, amount]) => (
                  <div className="stock-kpi" key={bucket}>
                    <span className="stock-kpi-label">{bucket}</span>
                    <strong>¥{Number(amount || 0).toLocaleString()}</strong>
                  </div>
                ))}
              </div>
              <p className="table-hint">
                账龄截至 {aging.as_of}，合计 ¥{Number(aging.total || 0).toLocaleString()}（{aging.total_upper}）
              </p>
              {(aging.details || []).length > 0 && (
                <table className="data-table" style={{ marginTop: '12px' }}>
                  <thead>
                    <tr>
                      <th>{partyWord}</th>
                      <th>未结金额</th>
                      <th>0-30天</th>
                      <th>31-60天</th>
                      <th>61-90天</th>
                      <th>90天以上</th>
                    </tr>
                  </thead>
                  <tbody>
                    {aging.details.map((row) => {
                      const party = parties.find((p) => p.id === row.party_id);
                      return (
                        <tr key={row.party_id}>
                          <td>{party?.name || `ID ${row.party_id}`}</td>
                          <td>¥{Number(row.outstanding || 0).toLocaleString()}</td>
                          <td>¥{Number(row['0-30天'] || 0).toLocaleString()}</td>
                          <td>¥{Number(row['31-60天'] || 0).toLocaleString()}</td>
                          <td>¥{Number(row['61-90天'] || 0).toLocaleString()}</td>
                          <td>¥{Number(row['90天以上'] || 0).toLocaleString()}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </>
          )}
        </section>

        <section className="panel table-panel">
          <div className="section-header">
            <h2>{title}明细</h2>
            <span className="status-badge">{rows.length} 家</span>
          </div>

          {rows.length === 0 ? (
            <div className="empty-state">暂无未{isCustomer ? '收' : '付'}款项</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>编码</th>
                  <th>{partyWord}</th>
                  <th>联系人</th>
                  <th>电话</th>
                  <th>期初</th>
                  <th>增加</th>
                  <th>减少</th>
                  <th>余额</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.party_id}>
                    <td>{row.party_code}</td>
                    <td>{row.party_name}</td>
                    <td>{row.contact || '—'}</td>
                    <td>{row.phone || '—'}</td>
                    <td>¥{Number(row.opening_balance || 0).toLocaleString()}</td>
                    <td>¥{Number(row.increase_total || 0).toLocaleString()}</td>
                    <td>¥{Number(row.decrease_total || 0).toLocaleString()}</td>
                    <td>¥{Number(row.balance || 0).toLocaleString()}</td>
                    <td>
                      <div className="contract-item-actions">
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          onClick={() => {
                            setLedgerParty({
                              party_type: partyType,
                              party_id: String(row.party_id),
                              from: printParty.from,
                              to: printParty.to,
                            });
                            setSelectedTab('ledger');
                            loadLedger(partyType, row.party_id, printParty.from, printParty.to);
                          }}
                        >
                          看明细
                        </button>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          onClick={() => printPdf(statementPath(row.party_id), `${row.party_name}_对账单.pdf`)}
                        >
                          对账单
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="table-hint">
            对账单期间沿用「财务管理 → 打印中心」里设置的起止日期；未设置则统计全部期间。
          </p>
        </section>
      </div>
    );
  };

  // 变动查询：库存流水的溯源检索（不再只显示裸 product_id）
  const renderStockLogsPage = () => {
    const productName = {};
    products.forEach((p) => {
      productName[p.id] = p.name;
    });
    const warehouseName = {};
    warehouses.forEach((w) => {
      warehouseName[w.id] = w.name;
    });

    const keyword = stockLogFilter.keyword.trim().toLowerCase();
    const rows = inventory.filter((row) => {
      if (stockLogFilter.type && row.transaction_type !== stockLogFilter.type) return false;
      if (stockLogFilter.warehouse_id && String(row.warehouse_id) !== stockLogFilter.warehouse_id) return false;
      if (keyword) {
        const docNo = (row.doc_no || '').toLowerCase();
        const name = (productName[row.product_id] || '').toLowerCase();
        if (!docNo.includes(keyword) && !name.includes(keyword)) return false;
      }
      return true;
    });
    const inbound = rows
      .filter((row) => row.transaction_type === 'inbound')
      .reduce((sum, row) => sum + Number(row.quantity || 0), 0);
    const outbound = rows
      .filter((row) => row.transaction_type === 'outbound')
      .reduce((sum, row) => sum + Number(row.quantity || 0), 0);

    return (
      <div className="management-grid">
        <section className="panel form-panel">
          <div className="section-header">
            <h2>流水筛选</h2>
            <span className="status-badge">出入库溯源</span>
          </div>

          <div className="erp-form">
            <div className="form-row two-col">
              <label>
                类型
                <select
                  value={stockLogFilter.type}
                  onChange={(event) => setStockLogFilter((prev) => ({ ...prev, type: event.target.value }))}
                >
                  <option value="">全部</option>
                  <option value="inbound">入库</option>
                  <option value="outbound">出库</option>
                </select>
              </label>
              <label>
                仓库
                <select
                  value={stockLogFilter.warehouse_id}
                  onChange={(event) => setStockLogFilter((prev) => ({ ...prev, warehouse_id: event.target.value }))}
                >
                  <option value="">全部仓库</option>
                  {warehouses.map((w) => (
                    <option key={w.id} value={w.id}>{w.name}</option>
                  ))}
                </select>
              </label>
            </div>

            <label>
              关键字（单号 / 商品名）
              <input
                value={stockLogFilter.keyword}
                onChange={(event) => setStockLogFilter((prev) => ({ ...prev, keyword: event.target.value }))}
                placeholder="如 CG20261013001"
              />
            </label>

            <div className="contract-item-actions">
              <button type="button" className="secondary-btn small-btn" onClick={refreshInventory}>
                刷新流水
              </button>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setStockLogFilter(emptyStockLogFilter)}
              >
                重置筛选
              </button>
            </div>
          </div>

          <div className="stock-kpis" style={{ marginTop: '16px' }}>
            <div className="stock-kpi">
              <span className="stock-kpi-label">流水条数</span>
              <strong>{rows.length}</strong>
            </div>
            <div className="stock-kpi">
              <span className="stock-kpi-label">入库合计</span>
              <strong>{inbound.toLocaleString()}</strong>
            </div>
            <div className="stock-kpi">
              <span className="stock-kpi-label">出库合计</span>
              <strong>{outbound.toLocaleString()}</strong>
            </div>
          </div>
        </section>

        <section className="panel table-panel">
          <div className="section-header">
            <h2>库存流水</h2>
            <span className="status-badge">{rows.length} 条</span>
          </div>

          {rows.length === 0 ? (
            <div className="empty-state">没有符合条件的库存流水</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>单号</th>
                  <th>来源</th>
                  <th>商品</th>
                  <th>仓库</th>
                  <th>类型</th>
                  <th>数量</th>
                  <th>单价</th>
                  <th>金额</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 200).map((row) => (
                  <tr key={row.id}>
                    <td>{row.doc_no || '手工登记'}</td>
                    <td>{docTypeLabel(row.related_type)}</td>
                    <td>{productName[row.product_id] || `ID ${row.product_id}`}</td>
                    <td>{warehouseName[row.warehouse_id] || `ID ${row.warehouse_id}`}</td>
                    <td>
                      <span className={`stock-tag ${row.transaction_type === 'inbound' ? 'tag-on' : 'tag-off'}`}>
                        {row.transaction_type === 'inbound' ? '入库' : '出库'}
                      </span>
                    </td>
                    <td>{row.quantity}</td>
                    <td>¥{Number(row.unit_price || 0).toLocaleString()}</td>
                    <td>¥{(Number(row.quantity || 0) * Number(row.unit_price || 0)).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {rows.length > 200 && <div className="table-hint">共 {rows.length} 条，仅显示最近 200 条</div>}
        </section>
      </div>
    );
  };

  // 往来对账：期初 → 逐笔 → 期末，与对账单打印同源
  const renderLedgerPage = () => {
    const parties = ledgerParty.party_type === 'customer' ? customers : suppliers;
    const summary = ledgerData?.summary;
    const statementPath = () => {
      const params = new URLSearchParams();
      if (ledgerParty.from) params.set('from_date', ledgerParty.from);
      if (ledgerParty.to) params.set('to_date', ledgerParty.to);
      const qs = params.toString() ? `?${params}` : '';
      return `/print/statement/${ledgerParty.party_type}/${ledgerParty.party_id}${qs}`;
    };

    return (
      <div className="management-grid">
        <section className="panel form-panel">
          <div className="section-header">
            <h2>往来对账</h2>
            <span className="status-badge">{ledgerParty.party_type === 'customer' ? '客户往来' : '供应商往来'}</span>
          </div>

          <div className="erp-form">
            <div className="form-row two-col">
              <label>
                往来类型
                <select
                  value={ledgerParty.party_type}
                  onChange={(event) =>
                    setLedgerParty({
                      party_type: event.target.value,
                      party_id: '',
                      from: ledgerParty.from,
                      to: ledgerParty.to,
                    })
                  }
                >
                  <option value="customer">客户</option>
                  <option value="supplier">供应商</option>
                </select>
              </label>
              <label>
                {ledgerParty.party_type === 'customer' ? '客户' : '供应商'}
                <select
                  value={ledgerParty.party_id}
                  onChange={(event) => setLedgerParty((prev) => ({ ...prev, party_id: event.target.value }))}
                >
                  <option value="">— 请选择 —</option>
                  {parties.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="form-row two-col">
              <label>
                起始日期
                <input
                  type="date"
                  value={ledgerParty.from}
                  onChange={(event) => setLedgerParty((prev) => ({ ...prev, from: event.target.value }))}
                />
              </label>
              <label>
                截止日期
                <input
                  type="date"
                  value={ledgerParty.to}
                  onChange={(event) => setLedgerParty((prev) => ({ ...prev, to: event.target.value }))}
                />
              </label>
            </div>

            <div className="contract-item-actions">
              <button
                type="button"
                className="primary-btn"
                disabled={financeBusy === 'ledger'}
                onClick={() => loadLedger()}
              >
                {financeBusy === 'ledger' ? '查询中…' : '查询往来账'}
              </button>
              <button
                type="button"
                className="secondary-btn"
                disabled={!ledgerParty.party_id}
                onClick={() => printPdf(statementPath(), '对账单.pdf')}
              >
                打印对账单
              </button>
            </div>
          </div>

          {summary && (
            <>
              <div className="report-summary-grid" style={{ marginTop: '16px' }}>
                <div className="metric-card">
                  <span>期初余额</span>
                  <strong>¥{Number(summary.opening_balance || 0).toLocaleString()}</strong>
                </div>
                <div className="metric-card">
                  <span>本期增加</span>
                  <strong>¥{Number(summary.increase_total || 0).toLocaleString()}</strong>
                </div>
                <div className="metric-card">
                  <span>本期减少</span>
                  <strong>¥{Number(summary.decrease_total || 0).toLocaleString()}</strong>
                </div>
                <div className="metric-card">
                  <span>期末余额</span>
                  <strong>¥{Number(summary.closing_balance || 0).toLocaleString()}</strong>
                </div>
              </div>
              <p className="table-hint">期末余额大写：{summary.closing_balance_upper}</p>
            </>
          )}
        </section>

        <section className="panel table-panel">
          <div className="section-header">
            <h2>{ledgerData?.party?.name ? `${ledgerData.party.name} · 往来明细` : '往来明细'}</h2>
            <span className="status-badge">{(ledgerData?.rows || []).length} 笔</span>
          </div>

          {!ledgerData ? (
            <div className="empty-state">请先选择往来单位并点击「查询往来账」</div>
          ) : (ledgerData.rows || []).length === 0 ? (
            <div className="empty-state">该期间内没有往来发生</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>单号</th>
                  <th>来源</th>
                  <th>摘要</th>
                  <th>增加</th>
                  <th>减少</th>
                  <th>余额</th>
                </tr>
              </thead>
              <tbody>
                {ledgerData.rows.map((row) => (
                  <tr key={row.id}>
                    <td>{String(row.date || '').slice(0, 10) || '—'}</td>
                    <td>{row.doc_no || '—'}</td>
                    <td>{docTypeLabel(row.related_type)}</td>
                    <td>{row.summary || '—'}</td>
                    <td>{row.increase ? `¥${Number(row.increase).toLocaleString()}` : '—'}</td>
                    <td>{row.decrease ? `¥${Number(row.decrease).toLocaleString()}` : '—'}</td>
                    <td>¥{Number(row.balance || 0).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    );
  };

  const submitProduct = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/products`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          ...productForm,
          purchase_price: Number(productForm.purchase_price || 0),
          sale_price: Number(productForm.sale_price || 0),
          category: productForm.category || null,
          unit: productForm.unit || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建产品失败' }));
        throw new Error(errorData.detail ?? '创建产品失败');
      }

      const newProduct = await response.json();
      setProducts((prev) => [newProduct, ...prev]);
      setProductForm(emptyProductForm);
      setNotice('产品已成功新增。');
    } catch (err) {
      setNotice(err.message || '产品新增失败');
    }
  };

  // —— 采购入库 / 销售出库（doc_type=inbound / outbound，真实动库存与应收应付）——
  async function refreshPurchaseInboundList() {
    try {
      const response = await fetch(`${API_BASE}/purchase-orders?doc_type=inbound`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) setPurchaseOrders(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  async function refreshSalesOutboundList() {
    try {
      const response = await fetch(`${API_BASE}/sales-orders?doc_type=outbound`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) setSalesOrders(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  // —— 采购/销售订单（doc_type=order，只订货不动库存财务）——
  async function refreshPurchaseOrderList() {
    try {
      const response = await fetch(`${API_BASE}/purchase-orders?doc_type=order`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) setPurchaseOrderList(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  async function refreshSalesOrderList() {
    try {
      const response = await fetch(`${API_BASE}/sales-orders?doc_type=order`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) setSalesOrderList(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handlePurchaseOrderFormChange = (field) => (event) => {
    setPurchaseOrderForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const handleSalesOrderFormChange = (field) => (event) => {
    setSalesOrderForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const makeOrderItemHandler = (setter, priceField) => (index, field) => (event) => {
    const value = event.target.value;
    setter((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案价格带出来（采购带进价、销售带售价），省得手打
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product[priceField] ?? '0');
        }
        return next;
      }),
    }));
  };

  const handlePurchaseOrderItemChange = makeOrderItemHandler(setPurchaseOrderForm, 'purchase_price');
  const handleSalesOrderItemChange = makeOrderItemHandler(setSalesOrderForm, 'sale_price');
  const handleInboundItemChange = makeOrderItemHandler(setInboundForm, 'purchase_price');
  const handleOutboundItemChange = makeOrderItemHandler(setOutboundForm, 'sale_price');

  const makeAddItem = (setter) => () => {
    setter((prev) => ({ ...prev, items: [...prev.items, { ...emptyOrderItem }] }));
  };
  const makeRemoveItem = (setter) => (index) => {
    setter((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const addPurchaseOrderItem = makeAddItem(setPurchaseOrderForm);
  const removePurchaseOrderItem = makeRemoveItem(setPurchaseOrderForm);
  const addSalesOrderItem = makeAddItem(setSalesOrderForm);
  const removeSalesOrderItem = makeRemoveItem(setSalesOrderForm);
  const addInboundItem = makeAddItem(setInboundForm);
  const removeInboundItem = makeRemoveItem(setInboundForm);
  const addOutboundItem = makeAddItem(setOutboundForm);
  const removeOutboundItem = makeRemoveItem(setOutboundForm);

  const handleInboundFormChange = (field) => (event) => {
    const value = event.target.value;
    setInboundForm((prev) => ({ ...prev, [field]: value }));
  };
  const handleOutboundFormChange = (field) => (event) => {
    const value = event.target.value;
    setOutboundForm((prev) => ({ ...prev, [field]: value }));
  };

  // 出入库单（真实单据）提交：与订单同一套校验，区别只在 doc_type 与「必须选仓库」
  const makeSubmitStockDoc = ({
    endpoint,
    form,
    setForm,
    emptyForm,
    listSetter,
    partyField,
    partyLabel,
    docType,
    label,
  }) => async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = form.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (!form[partyField]) {
      setNotice(`请先选择${partyLabel}。`);
      return;
    }
    if (!form.warehouse_id) {
      setNotice(`请选择${docType === 'inbound' ? '入库' : '出库'}仓库，${label}必须落到具体仓库。`);
      return;
    }
    if (lines.length === 0) {
      setNotice('至少要有一行商品明细。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          doc_type: docType,
          [partyField]: Number(form[partyField]),
          items: lines,
          warehouse_id: Number(form.warehouse_id),
          order_date: form.order_date || null,
          payment_method: form.payment_method || null,
          note: form.note || null,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: `创建${label}失败` }));
        throw new Error(errorData.detail ?? `创建${label}失败`);
      }
      const created = await response.json();
      listSetter((prev) => [created, ...prev]);
      setForm(emptyForm);
      setNotice(
        `${label} ${created.order_no} 已登记，库存与${docType === 'inbound' ? '应付' : '应收'}已自动入账。`,
      );
      refreshStock('');
    } catch (err) {
      setNotice(err.message || `${label}保存失败`);
    }
  };

  const submitInboundForm = makeSubmitStockDoc({
    endpoint: 'purchase-orders',
    form: inboundForm,
    setForm: setInboundForm,
    emptyForm: emptyInboundForm,
    listSetter: setPurchaseOrders,
    partyField: 'supplier_id',
    partyLabel: '供应商',
    docType: 'inbound',
    label: '采购入库单',
  });

  const submitOutboundForm = makeSubmitStockDoc({
    endpoint: 'sales-orders',
    form: outboundForm,
    setForm: setOutboundForm,
    emptyForm: emptyOutboundForm,
    listSetter: setSalesOrders,
    partyField: 'customer_id',
    partyLabel: '客户',
    docType: 'outbound',
    label: '销售出库单',
  });

  const makeSubmitOrder = ({ endpoint, form, setForm, emptyForm, listSetter, partyField, label }) => async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = form.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (!form[partyField]) {
      setNotice(`请先选择${label === '采购订单' ? '供应商' : '客户'}。`);
      return;
    }
    if (lines.length === 0) {
      setNotice('至少要有一行商品明细。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    try {
      const response = await fetch(`${API_BASE}/${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          doc_type: 'order',
          [partyField]: Number(form[partyField]),
          items: lines,
          warehouse_id: num(form.warehouse_id),
          delivery_date: form.delivery_date || null,
          payment_method: form.payment_method || null,
          note: form.note || null,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: `创建${label}失败` }));
        throw new Error(errorData.detail ?? `创建${label}失败`);
      }
      const created = await response.json();
      listSetter((prev) => [created, ...prev]);
      setForm(emptyForm);
      setNotice(`${label}已保存，可在列表中「转入库单/转开单」或直接打印。`);
    } catch (err) {
      setNotice(err.message || `${label}保存失败`);
    }
  };

  const submitPurchaseOrderForm = makeSubmitOrder({
    endpoint: 'purchase-orders',
    form: purchaseOrderForm,
    setForm: setPurchaseOrderForm,
    emptyForm: emptyPurchaseOrderForm,
    listSetter: setPurchaseOrderList,
    partyField: 'supplier_id',
    label: '采购订单',
  });

  const submitSalesOrderForm = makeSubmitOrder({
    endpoint: 'sales-orders',
    form: salesOrderForm,
    setForm: setSalesOrderForm,
    emptyForm: emptySalesOrderForm,
    listSetter: setSalesOrderList,
    partyField: 'customer_id',
    label: '销售订单',
  });

  const convertPurchaseOrder = async (row) => {
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/purchase-orders/${row.id}/to-inbound`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '转单失败' }));
        throw new Error(errorData.detail ?? '转单失败');
      }
      const inbound = await response.json();
      // 订单置为已转单；生成的入库单进入老采购入库列表
      setPurchaseOrderList((prev) => prev.map((item) => (item.id === row.id ? { ...item, status: 'completed' } : item)));
      setPurchaseOrders((prev) => [inbound, ...prev]);
      setNotice(`采购订单 ${row.order_no} 已转入库单 ${inbound.order_no}，库存与应付已自动登记。`);
    } catch (err) {
      setNotice(err.message || '转单失败');
    }
  };

  const convertSalesOrder = async (row) => {
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/sales-orders/${row.id}/to-outbound`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '转单失败' }));
        throw new Error(errorData.detail ?? '转单失败');
      }
      const outbound = await response.json();
      setSalesOrderList((prev) => prev.map((item) => (item.id === row.id ? { ...item, status: 'completed' } : item)));
      setSalesOrders((prev) => [outbound, ...prev]);
      setNotice(`销售订单 ${row.order_no} 已转开单 ${outbound.order_no}，库存与应收已自动登记。`);
    } catch (err) {
      setNotice(err.message || '转单失败');
    }
  };

  // —— 购销合同（模板 A2）——
  async function refreshContracts(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/contracts${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setContracts(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  async function loadContractMeta() {
    try {
      const response = await fetch(`${API_BASE}/contracts/meta`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) return;
      const data = await response.json();
      setContractMeta(data);
      const d = data.defaults || {};
      const own = data.default_own || {};
      // 条款变量只在用户没填过的时候补默认值，不覆盖已输入内容
      setContractForm((prev) => ({
        ...prev,
        own_name: prev.own_name || own.own_name || '',
        own_tax_no: prev.own_tax_no || own.own_tax_no || '',
        own_legal_person: prev.own_legal_person || own.own_legal_person || '',
        own_address: prev.own_address || own.own_address || '',
        own_contact: prev.own_contact || own.own_contact || '',
        own_phone: prev.own_phone || own.own_phone || '',
        own_bank_name: prev.own_bank_name || own.own_bank_name || '',
        own_bank_account: prev.own_bank_account || own.own_bank_account || '',
        quality_standard: prev.quality_standard || d.quality_standard || '',
        package_standard: prev.package_standard || d.package_standard || '',
        delivery_method: prev.delivery_method || d.delivery_method || '',
        freight_bearer: prev.freight_bearer || d.freight_bearer || '',
        warranty_terms: prev.warranty_terms || d.warranty_terms || '',
        payment_terms: prev.payment_terms || d.payment_terms || '',
        invoice_requirement: prev.invoice_requirement || d.invoice_requirement || '',
        dispute_resolution: prev.dispute_resolution || d.dispute_resolution || '',
      }));
    } catch {
      // 字典拉不到不影响录入（后端本身有兜底）
    }
  }

  const handleContractChange = (field) => (event) => {
    const value = event.target.value;
    setContractForm((prev) => {
      const next = { ...prev, [field]: value };
      // 切换采购 / 销售时清掉已选的对方单位，避免把客户 id 当供应商提交
      if (field === 'contract_type') next.party_id = '';
      return next;
    });
  };

  const handleContractItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setContractForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的价格带出来，省得手打
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.sale_price ?? product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addContractItem = () => {
    setContractForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeContractItem = (index) => {
    setContractForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitContract = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = contractForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行合同明细（商品不能为空）。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));

    try {
      const response = await fetch(`${API_BASE}/contracts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          contract_type: contractForm.contract_type,
          party_type: contractForm.contract_type === 'sales' ? 'customer' : 'supplier',
          party_id: num(contractForm.party_id),
          warehouse_id: num(contractForm.warehouse_id),
          own_name: contractForm.own_name || null,
          own_tax_no: contractForm.own_tax_no || null,
          own_legal_person: contractForm.own_legal_person || null,
          own_address: contractForm.own_address || null,
          own_contact: contractForm.own_contact || null,
          own_phone: contractForm.own_phone || null,
          own_bank_name: contractForm.own_bank_name || null,
          own_bank_account: contractForm.own_bank_account || null,
          sign_date: contractForm.sign_date || null,
          sign_place: contractForm.sign_place || null,
          delivery_date: contractForm.delivery_date || null,
          delivery_place: contractForm.delivery_place || null,
          delivery_method: contractForm.delivery_method || null,
          freight_bearer: contractForm.freight_bearer || null,
          payment_terms: contractForm.payment_terms || null,
          invoice_requirement: contractForm.invoice_requirement || null,
          quality_standard: contractForm.quality_standard || null,
          package_standard: contractForm.package_standard || null,
          inspection_days: num(contractForm.inspection_days),
          objection_days: num(contractForm.objection_days),
          warranty_terms: contractForm.warranty_terms || null,
          // 界面按「万分之几」填，后端存日利率小数
          penalty_rate: contractForm.penalty_rate === '' ? null : Number(contractForm.penalty_rate) / 10000,
          dispute_resolution: contractForm.dispute_resolution || null,
          copies: num(contractForm.copies),
          service_address: contractForm.service_address || null,
          other_terms: contractForm.other_terms || null,
          note: contractForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建合同失败' }));
        throw new Error(errorData.detail ?? '创建合同失败');
      }

      const created = await response.json();
      setContracts((prev) => [created, ...prev]);
      setContractForm({ ...emptyContractForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      await loadContractMeta();
      setNotice(`合同 ${created.contract_no} 已生成（${created.amount_chinese}）。`);
    } catch (err) {
      setNotice(err.message || '合同新增失败');
    }
  };

  const saveCompanyDefaults = async () => {
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/settings/company`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          own_name: contractForm.own_name,
          own_tax_no: contractForm.own_tax_no,
          own_legal_person: contractForm.own_legal_person,
          own_address: contractForm.own_address,
          own_contact: contractForm.own_contact,
          own_phone: contractForm.own_phone,
          own_bank_name: contractForm.own_bank_name,
          own_bank_account: contractForm.own_bank_account,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存公司信息失败' }));
        throw new Error(errorData.detail ?? '保存公司信息失败');
      }
      const saved = await response.json();
      setContractMeta((prev) => ({ ...(prev || {}), default_own: saved }));
      setNotice('公司信息已保存为默认抬头，之后新建的合同会自动带出。');
    } catch (err) {
      setNotice(err.message || '保存公司信息失败');
    }
  };

  async function loadCompanySettings() {
    try {
      const response = await fetch(`${API_BASE}/settings/company`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) return;
      const data = await response.json();
      setCompanyForm((prev) => ({ ...prev, ...data }));
    } catch {
      // 拉取失败保留上一次内容
    }
  }

  const handleCompanyChange = (field) => (event) => {
    const { value } = event.target;
    setCompanyForm((prev) => ({ ...prev, [field]: value }));
  };

  const submitCompanySettings = async (event) => {
    event.preventDefault();
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/settings/company`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify(companyForm),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存公司信息失败' }));
        throw new Error(errorData.detail ?? '保存公司信息失败');
      }
      const saved = await response.json();
      setCompanyForm((prev) => ({ ...prev, ...saved }));
      // 同步给合同页默认抬头，避免两处不一致
      setContractMeta((prev) => ({ ...(prev || {}), default_own: saved }));
      setNotice('公司信息已保存，之后新建的合同与单据打印会自动带出。');
    } catch (err) {
      setNotice(err.message || '保存公司信息失败');
    }
  };

  const contractToOrder = async (row) => {
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/contracts/${row.id}/to-order`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail ?? '转单失败');
      }
      setNotice(data.message || '已转单。');
      await refreshContracts();
      await refreshStock();
      // 单据列表也一并刷新，切过去就能看到新单
      const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
      if (data.order_type === 'sales_order') {
        const res = await fetch(`${API_BASE}/sales-orders`, { headers });
        if (res.ok) setSalesOrders(await res.json());
      } else {
        const res = await fetch(`${API_BASE}/purchase-orders`, { headers });
        if (res.ok) setPurchaseOrders(await res.json());
      }
    } catch (err) {
      setNotice(err.message || '转单失败');
    }
  };

  // —— 销售报价单 ——
  async function refreshQuotations(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/quotations${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setQuotations(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  async function loadQuotationMeta() {
    try {
      const response = await fetch(`${API_BASE}/quotations/meta`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setQuotationMeta(await response.json());
      }
    } catch {
      // 字典拉不到不影响录入（付款 / 运输方式允许自由输入）
    }
  }

  const handleQuotationChange = (field) => (event) => {
    const { value } = event.target;
    setQuotationForm((prev) => {
      const next = { ...prev, [field]: value };
      // 选了客户就把档案里的地址 / 联系人 / 电话带出来，省得手打
      if (field === 'customer_id') {
        const customer = customers.find((item) => String(item.id) === String(value));
        if (customer) {
          next.customer_name = customer.name || '';
          next.customer_address = customer.address || '';
          next.contact = customer.contact || '';
          next.contact_phone = customer.contact_phone || customer.phone || '';
        }
      }
      return next;
    });
  };

  const handleQuotationItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setQuotationForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的售价带出来，省得手打
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.sale_price ?? product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addQuotationItem = () => {
    setQuotationForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeQuotationItem = (index) => {
    setQuotationForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitQuotation = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = quotationForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行报价明细（商品不能为空）。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));

    try {
      const response = await fetch(`${API_BASE}/quotations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          customer_id: num(quotationForm.customer_id),
          customer_name: quotationForm.customer_name || null,
          customer_address: quotationForm.customer_address || null,
          contact: quotationForm.contact || null,
          contact_phone: quotationForm.contact_phone || null,
          fax: quotationForm.fax || null,
          quote_date: quotationForm.quote_date || null,
          valid_until: quotationForm.valid_until || null,
          warehouse_id: num(quotationForm.warehouse_id),
          businesser: quotationForm.businesser || null,
          payment_method: quotationForm.payment_method || null,
          transport_method: quotationForm.transport_method || null,
          delivery_place: quotationForm.delivery_place || null,
          note: quotationForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建报价单失败' }));
        throw new Error(errorData.detail ?? '创建报价单失败');
      }

      const created = await response.json();
      setQuotations((prev) => [created, ...prev]);
      setQuotationForm({ ...emptyQuotationForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setNotice(`报价单 ${created.quote_no} 已生成（${created.amount_chinese}）。`);
    } catch (err) {
      setNotice(err.message || '报价单新增失败');
    }
  };

  const quotationToOrder = async (row) => {
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/quotations/${row.id}/to-order`, {
        method: 'POST',
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail ?? '转单失败');
      }
      setNotice(data.message || '已转单。');
      await refreshQuotations();
      // 销售订单页列表一并刷新，切过去就能看到新单
      await refreshSalesOrderList();
    } catch (err) {
      setNotice(err.message || '转单失败');
    }
  };

  // —— 采购退货（对齐浩技云「采购管理 → 退货管理」）——
  async function refreshPurchaseReturns(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/purchase-returns${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setPurchaseReturns(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handlePurchaseReturnChange = (field) => (event) => {
    const { value } = event.target;
    setPurchaseReturnForm((prev) => {
      const next = { ...prev, [field]: value };
      // 选了供应商就把档案里的联系人 / 电话 / 地址带出来（快照）
      if (field === 'supplier_id') {
        const supplier = suppliers.find((item) => String(item.id) === String(value));
        if (supplier) {
          next.contact = supplier.main_contact || supplier.contact || '';
          next.contact_phone = supplier.mobile || supplier.phone || '';
          next.address = supplier.address || '';
        }
      }
      return next;
    });
  };

  const handlePurchaseReturnItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setPurchaseReturnForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的进价带出来，省得手打
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addPurchaseReturnItem = () => {
    setPurchaseReturnForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removePurchaseReturnItem = (index) => {
    setPurchaseReturnForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitPurchaseReturn = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = purchaseReturnForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (!purchaseReturnForm.supplier_id) {
      setNotice('请先选择供应商。');
      return;
    }
    if (lines.length === 0) {
      setNotice('至少要有一行退货明细（商品不能为空）。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));

    try {
      const response = await fetch(`${API_BASE}/purchase-returns`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          supplier_id: Number(purchaseReturnForm.supplier_id),
          warehouse_id: num(purchaseReturnForm.warehouse_id),
          businesser: purchaseReturnForm.businesser || null,
          return_date: purchaseReturnForm.return_date || null,
          return_reason: purchaseReturnForm.return_reason || null,
          payment_method: purchaseReturnForm.payment_method || null,
          note: purchaseReturnForm.note || null,
          source_order_id: num(purchaseReturnForm.source_order_id),
          source_order_no: purchaseReturnForm.source_order_no || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建采购退货单失败' }));
        throw new Error(errorData.detail ?? '创建采购退货单失败');
      }

      const created = await response.json();
      setPurchaseReturns((prev) => [created, ...prev]);
      setPurchaseReturnForm({ ...emptyPurchaseReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setNotice(`采购退货单 ${created.return_no} 已生成（${created.amount_chinese}），库存与应付已自动冲减。`);
    } catch (err) {
      setNotice(err.message || '采购退货单新增失败');
    }
  };

  // —— 销售退货（对齐浩技云「销售管理 → 销售退货」）——
  async function refreshSalesReturns(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/sales-returns${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setSalesReturns(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleSalesReturnChange = (field) => (event) => {
    const { value } = event.target;
    setSalesReturnForm((prev) => {
      const next = { ...prev, [field]: value };
      // 选了客户就把档案里的联系人 / 电话 / 地址带出来（快照）
      if (field === 'customer_id') {
        const customer = customers.find((item) => String(item.id) === String(value));
        if (customer) {
          next.contact = customer.contact || '';
          next.contact_phone = customer.contact_phone || customer.phone || '';
          next.address = customer.address || '';
        }
      }
      return next;
    });
  };

  const handleSalesReturnItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setSalesReturnForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的售价带出来，省得手打
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.sale_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addSalesReturnItem = () => {
    setSalesReturnForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeSalesReturnItem = (index) => {
    setSalesReturnForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitSalesReturn = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = salesReturnForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (!salesReturnForm.customer_id) {
      setNotice('请先选择客户。');
      return;
    }
    if (lines.length === 0) {
      setNotice('至少要有一行退货明细（商品不能为空）。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));

    try {
      const response = await fetch(`${API_BASE}/sales-returns`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          customer_id: Number(salesReturnForm.customer_id),
          warehouse_id: num(salesReturnForm.warehouse_id),
          businesser: salesReturnForm.businesser || null,
          return_date: salesReturnForm.return_date || null,
          return_reason: salesReturnForm.return_reason || null,
          payment_method: salesReturnForm.payment_method || null,
          note: salesReturnForm.note || null,
          source_order_id: num(salesReturnForm.source_order_id),
          source_order_no: salesReturnForm.source_order_no || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建销售退货单失败' }));
        throw new Error(errorData.detail ?? '创建销售退货单失败');
      }

      const created = await response.json();
      setSalesReturns((prev) => [created, ...prev]);
      setSalesReturnForm({ ...emptySalesReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setNotice(`销售退货单 ${created.return_no} 已生成（${created.amount_chinese}），库存与应收已自动冲减。`);
    } catch (err) {
      setNotice(err.message || '销售退货单新增失败');
    }
  };

  // —— 库存调拨（对齐浩技云「库存管理 → 调拨管理」）——
  async function refreshTransfers(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/inventory-transfers${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setTransfers(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleTransferChange = (field) => (event) => {
    const { value } = event.target;
    setTransferForm((prev) => {
      const next = { ...prev, [field]: value };
      // 调入仓库不该与调出仓库重复（后端也会拦，这里先在界面上自动避让）
      if (field === 'from_warehouse_id' && String(next.to_warehouse_id) === String(value)) {
        next.to_warehouse_id = '';
      }
      return next;
    });
  };

  const handleTransferItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setTransferForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的成本价带出来，仅作打印参考
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addTransferItem = () => {
    setTransferForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeTransferItem = (index) => {
    setTransferForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitTransfer = async (event) => {
    event.preventDefault();
    setNotice('');

    if (!transferForm.from_warehouse_id) {
      setNotice('请先选择调出仓库。');
      return;
    }
    if (!transferForm.to_warehouse_id) {
      setNotice('请先选择调入仓库。');
      return;
    }
    if (String(transferForm.from_warehouse_id) === String(transferForm.to_warehouse_id)) {
      setNotice('调出仓库与调入仓库不能相同。');
      return;
    }
    const lines = transferForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行调拨明细（商品不能为空）。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/inventory-transfers`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          from_warehouse_id: Number(transferForm.from_warehouse_id),
          to_warehouse_id: Number(transferForm.to_warehouse_id),
          transfer_date: transferForm.transfer_date || null,
          handler: transferForm.handler || null,
          reason: transferForm.reason || null,
          note: transferForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建调拨单失败' }));
        throw new Error(errorData.detail ?? '创建调拨单失败');
      }

      const created = await response.json();
      setTransfers((prev) => [created, ...prev]);
      setTransferForm({ ...emptyTransferForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setNotice(`调拨单 ${created.transfer_no} 已生成，共 ${created.total_quantity} 件，两侧仓库库存已同步更新。`);
      // 调拨会同时改动两个仓库的现存量，看板与明细行提示一并刷新
      refreshStock();
    } catch (err) {
      setNotice(err.message || '调拨单新增失败');
    }
  };

  // —— 库存盘点（对齐浩技云「库存管理 → 盘点管理」）——
  async function refreshStocktakings(keyword) {
    try {
      const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const response = await fetch(`${API_BASE}/stocktakings${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setStocktakings(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleStocktakingChange = (field) => (event) => {
    const { value } = event.target;
    setStocktakingForm((prev) => {
      const next = { ...prev, [field]: value };
      // 换仓库后原底稿的账面数已经失效（那是上一个仓库的账），整表清空更安全
      if (field === 'warehouse_id' && String(prev.warehouse_id) !== String(value)) {
        next.items = [];
      }
      return next;
    });
    if (field === 'warehouse_id') setStocktakingPlanHint('');
  };

  const handleStocktakingItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setStocktakingForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    }));
  };

  // 带出账面库存：调 /stocktakings/plan 拿该仓库的实时现存量，生成盘点底稿
  const loadStocktakingPlan = async () => {
    if (!stocktakingForm.warehouse_id) {
      setNotice('请先选择盘点仓库，再带出账面库存。');
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE}/stocktakings/plan?warehouse_id=${stocktakingForm.warehouse_id}`,
        { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '带出账面库存失败' }));
        throw new Error(errorData.detail ?? '带出账面库存失败');
      }
      const data = await response.json();
      const rows = (data.rows || []).map((row) => ({
        product_id: String(row.product_id),
        product_name: row.product_name,
        standards: row.standards,
        unit: row.unit,
        book_quantity: String(row.book_quantity ?? 0),
        actual_quantity: String(row.book_quantity ?? 0), // 默认账实一致，只改有差异的行
        unit_price: String(row.unit_price ?? 0),
      }));
      setStocktakingForm((prev) => ({ ...prev, items: rows }));
      setStocktakingPlanHint(
        rows.length
          ? `已按「${data.warehouse_name}」带出 ${rows.length} 行账面库存，默认实盘数=账面数；请只修改有差异的行。`
          : `「${data.warehouse_name}」当前没有账面库存，可手动添加商品行录入盘盈。`,
      );
      setNotice(
        rows.length
          ? `已带出「${data.warehouse_name}」${rows.length} 行账面库存。`
          : `「${data.warehouse_name}」没有账面库存，可直接手工加行。`,
      );
    } catch (err) {
      setNotice(err.message || '带出账面库存失败');
    }
  };

  // 手工补一行（账面为 0 的商品发生盘盈时用）
  const addStocktakingItem = () => {
    setStocktakingForm((prev) => ({
      ...prev,
      items: [
        ...prev.items,
        {
          product_id: '',
          product_name: '',
          standards: '',
          unit: '',
          book_quantity: '0',
          actual_quantity: '0',
          unit_price: '0',
        },
      ],
    }));
  };

  const removeStocktakingItem = (index) => {
    setStocktakingForm((prev) => ({ ...prev, items: prev.items.filter((_, i) => i !== index) }));
  };

  // 明细行选商品：补上快照 + 该商品在所选仓库的账面数、成本价
  const handleStocktakingProductPick = (index, productId) => {
    setStocktakingForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const product = products.find((item) => String(item.id) === String(productId));
        const next = {
          ...row,
          product_id: productId,
          product_name: product?.name || '',
          standards: product?.standards || '',
          unit: product?.unit || '',
        };
        if (product) {
          const book = stockByWarehouseProduct[`${prev.warehouse_id}-${productId}`];
          if (book !== undefined) {
            next.book_quantity = String(book);
            if (!next.actual_quantity || next.actual_quantity === '0') {
              next.actual_quantity = String(book);
            }
          }
          next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const submitStocktaking = async (event) => {
    event.preventDefault();
    setNotice('');

    if (!stocktakingForm.warehouse_id) {
      setNotice('请先选择盘点仓库。');
      return;
    }
    const lines = stocktakingForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        book_quantity: Number(row.book_quantity) || 0,
        actual_quantity: Number(row.actual_quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('盘点至少要有 1 行明细，请先「带出账面库存」或手工添加商品行。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/stocktakings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          warehouse_id: Number(stocktakingForm.warehouse_id),
          check_date: stocktakingForm.check_date || null,
          handler: stocktakingForm.handler || null,
          scope: stocktakingForm.scope || null,
          note: stocktakingForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建盘点单失败' }));
        throw new Error(errorData.detail ?? '创建盘点单失败');
      }

      const created = await response.json();
      setStocktakings((prev) => [created, ...prev]);
      setStocktakingForm({ ...emptyStocktakingForm });
      setStocktakingPlanHint('');
      setNotice(
        `盘点单 ${created.check_no} 已生成：盘盈 ${created.total_profit}、盘亏 ${created.total_loss}，` +
          `账面已按实盘数调整。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '盘点单新增失败');
    }
  };

  // —— 报损报溢（对齐浩技云「库存管理 → 报损报溢」）——
  async function refreshAdjustments(keyword, typeFilter) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : adjustmentKeyword;
      const tp = typeFilter !== undefined ? typeFilter : adjustmentTypeFilter;
      if (kw) params.set('keyword', kw);
      if (tp) params.set('adjust_type', tp);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/inventory-adjustments${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setAdjustments(await response.json());
      }
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleAdjustmentChange = (field) => (event) => {
    const { value } = event.target;
    setAdjustmentForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleAdjustmentItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setAdjustmentForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案里的成本价带出来（报损金额按成本口径）
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addAdjustmentItem = () => {
    setAdjustmentForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeAdjustmentItem = (index) => {
    setAdjustmentForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitAdjustment = async (event) => {
    event.preventDefault();
    setNotice('');

    if (!adjustmentForm.warehouse_id) {
      setNotice('请先选择发生仓库。');
      return;
    }
    const lines = adjustmentForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Math.abs(Number(row.quantity) || 0),
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行明细（商品不能为空）。');
      return;
    }

    const kindLabel = adjustTypeLabel(adjustmentForm.adjust_type);
    try {
      const response = await fetch(`${API_BASE}/inventory-adjustments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          adjust_type: adjustmentForm.adjust_type,
          warehouse_id: Number(adjustmentForm.warehouse_id),
          adjust_date: adjustmentForm.adjust_date || null,
          handler: adjustmentForm.handler || null,
          reason: adjustmentForm.reason || null,
          note: adjustmentForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setAdjustments((prev) => [created, ...prev]);
      setAdjustmentForm({
        ...emptyAdjustmentForm,
        adjust_type: adjustmentForm.adjust_type,
        items: [{ product_id: '', quantity: '1', unit_price: '0' }],
      });
      setNotice(
        `${kindLabel}单 ${created.adjust_no} 已生成，共 ${created.total_quantity} 件，` +
          `库存已${ADJUST_TYPE_DIRECTION[created.adjust_type] || '调整'}。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // —— 生产计划（第 3 批生产类之一）——
  async function refreshProductionPlans(keyword, typeFilter) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : productionPlanKeyword;
      const tp = typeFilter !== undefined ? typeFilter : productionPlanTypeFilter;
      if (kw) params.set('keyword', kw);
      if (tp) params.set('plan_type', tp);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/production-plans${query}`, { headers: authHeaders() });
      if (response.ok) setProductionPlans(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handlePlanChange = (field) => (event) => {
    const { value } = event.target;
    setProductionPlanForm((prev) => ({ ...prev, [field]: value }));
  };

  const handlePlanItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setProductionPlanForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了成品就把档案里的进价带出来当计划成本参考
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addPlanItem = () => {
    setProductionPlanForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removePlanItem = (index) => {
    setProductionPlanForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitProductionPlan = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = productionPlanForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行成品明细（成品不能为空）。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/production-plans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          plan_type: productionPlanForm.plan_type,
          warehouse_id: productionPlanForm.warehouse_id ? Number(productionPlanForm.warehouse_id) : null,
          plan_date: productionPlanForm.plan_date || null,
          delivery_date: productionPlanForm.delivery_date || null,
          handler: productionPlanForm.handler || null,
          workshop: productionPlanForm.workshop || null,
          source_order_no: productionPlanForm.source_order_no || null,
          note: productionPlanForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setProductionPlans((prev) => [created, ...prev]);
      setProductionPlanForm({ ...emptyProductionPlanForm, plan_type: productionPlanForm.plan_type });
      setNotice(
        `${planTypeLabel(created.plan_type)}生产计划 ${created.plan_no} 已生成，` +
          `共 ${Number(created.total_quantity || 0).toLocaleString()} 件。计划只是排产意图，` +
          `不写库存与财务，下一步可做 MRP 运算。`,
      );
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // —— MRP 运算 ——
  const handleMrpChange = (field) => (event) => {
    const { value } = event.target;
    setMrpForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleMrpItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setMrpForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    }));
  };

  const addMrpItem = () => {
    setMrpForm((prev) => ({ ...prev, items: [...prev.items, { product_id: '', quantity: '1' }] }));
  };

  const removeMrpItem = (index) => {
    setMrpForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const runMrp = async (event) => {
    if (event) event.preventDefault();
    setNotice('');
    setMrpBusy(true);
    try {
      let response;
      if (mrpForm.plan_id) {
        // 按生产计划整单运算：计划里每个成品当作顶层需求
        response = await fetch(`${API_BASE}/production-plans/${mrpForm.plan_id}/mrp`, {
          headers: authHeaders(),
        });
      } else {
        const items = mrpForm.items
          .filter((row) => row.product_id)
          .map((row) => ({ product_id: Number(row.product_id), quantity: Number(row.quantity) || 0 }));
        if (items.length === 0) {
          setNotice('请先选择要运算的成品与数量，或选择一张生产计划单。');
          setMrpBusy(false);
          return;
        }
        response = await fetch(`${API_BASE}/mrp/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({
            items,
            warehouse_id: mrpForm.warehouse_id ? Number(mrpForm.warehouse_id) : null,
          }),
        });
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'MRP 运算失败' }));
        throw new Error(errorData.detail ?? 'MRP 运算失败');
      }
      const result = await response.json();
      setMrpResult(result);
      setNotice(
        `MRP 运算完成：${result.summary.material_lines} 种物料，` +
          `其中 ${result.summary.shortage_lines} 种缺料，缺料金额 ¥${Number(
            result.summary.shortage_amount || 0,
          ).toLocaleString()}。`,
      );
    } catch (err) {
      setNotice(err.message || 'MRP 运算失败');
    } finally {
      setMrpBusy(false);
    }
  };

  // —— 生产领料（第 3 批生产类之三）——
  async function refreshMaterialIssues(keyword) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : materialIssueKeyword;
      if (kw) params.set('keyword', kw);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/material-issues${query}`, { headers: authHeaders() });
      if (response.ok) setMaterialIssues(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleIssueChange = (field) => (event) => {
    const { value } = event.target;
    setMaterialIssueForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleIssueItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setMaterialIssueForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addIssueItem = () => {
    setMaterialIssueForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeIssueItem = (index) => {
    setMaterialIssueForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  // 按生产计划带出领料底稿：BOM 展开后的物料需求（毛需求）
  const loadIssueSuggestion = async () => {
    setNotice('');
    if (!materialIssueForm.plan_id) {
      setNotice('请先选择一张生产计划，再带出领料底稿。');
      return;
    }
    try {
      const response = await fetch(
        `${API_BASE}/material-issues/suggestion?plan_id=${materialIssueForm.plan_id}`,
        { headers: authHeaders() },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '带出底稿失败' }));
        throw new Error(errorData.detail ?? '带出底稿失败');
      }
      const data = await response.json();
      setMaterialIssueForm((prev) => ({
        ...prev,
        warehouse_id: prev.warehouse_id || (data.warehouse_id ? String(data.warehouse_id) : ''),
        items: data.items.length
          ? data.items.map((row) => ({
              product_id: String(row.product_id),
              quantity: String(row.quantity ?? 0),
              unit_price: String(row.unit_price ?? 0),
            }))
          : prev.items,
      }));
      setIssueSuggestionHint(
        data.items.length
          ? `已按计划 ${data.plan_no} 带出 ${data.count} 行物料底稿（数量按 BOM 毛需求，可再改）`
          : `计划 ${data.plan_no} 未展开出物料（该成品可能还没维护 BOM）`,
      );
    } catch (err) {
      setIssueSuggestionHint('');
      setNotice(err.message || '带出底稿失败');
    }
  };

  const submitMaterialIssue = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = materialIssueForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Math.abs(Number(row.quantity) || 0),
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行材料明细（材料不能为空）。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/material-issues`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          plan_id: materialIssueForm.plan_id ? Number(materialIssueForm.plan_id) : null,
          warehouse_id: materialIssueForm.warehouse_id ? Number(materialIssueForm.warehouse_id) : null,
          issue_date: materialIssueForm.issue_date || null,
          workshop: materialIssueForm.workshop || null,
          handler: materialIssueForm.handler || null,
          note: materialIssueForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setMaterialIssues((prev) => [created, ...prev]);
      setMaterialIssueForm({ ...emptyMaterialIssueForm });
      setIssueSuggestionHint('');
      setNotice(
        `生产领料单 ${created.issue_no} 已生成，共 ${Number(created.total_quantity || 0).toLocaleString()} 件，` +
          `材料已从仓库发出。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // —— 生产退料（领料的反向单据）——
  async function refreshMaterialReturns(keyword) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : materialReturnKeyword;
      if (kw) params.set('keyword', kw);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/material-returns${query}`, { headers: authHeaders() });
      if (response.ok) setMaterialReturns(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleReturnChange = (field) => (event) => {
    const { value } = event.target;
    setMaterialReturnForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleReturnItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setMaterialReturnForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addReturnItem = () => {
    setMaterialReturnForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeReturnItem = (index) => {
    setMaterialReturnForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitMaterialReturn = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = materialReturnForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Math.abs(Number(row.quantity) || 0),
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行材料明细（材料不能为空）。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/material-returns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          plan_id: materialReturnForm.plan_id ? Number(materialReturnForm.plan_id) : null,
          warehouse_id: materialReturnForm.warehouse_id ? Number(materialReturnForm.warehouse_id) : null,
          return_date: materialReturnForm.return_date || null,
          workshop: materialReturnForm.workshop || null,
          handler: materialReturnForm.handler || null,
          reason: materialReturnForm.reason || null,
          note: materialReturnForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setMaterialReturns((prev) => [created, ...prev]);
      setMaterialReturnForm({ ...emptyMaterialReturnForm });
      setNotice(
        `生产退料单 ${created.return_no} 已生成，共 ${Number(created.total_quantity || 0).toLocaleString()} 件，` +
          `余料已退回仓库。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // 成品入库：列表 / 录入 / 明细增删 / 提交
  async function refreshFinishedGoods(keyword) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : finishedGoodsKeyword;
      if (kw) params.set('keyword', kw);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/finished-goods${query}`, { headers: authHeaders() });
      if (response.ok) setFinishedGoodsList(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  const handleFinishedGoodsChange = (field) => (event) => {
    const { value } = event.target;
    setFinishedGoodsForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleFinishedGoodsItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setFinishedGoodsForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addFinishedGoodsItem = () => {
    setFinishedGoodsForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeFinishedGoodsItem = (index) => {
    setFinishedGoodsForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitFinishedGoods = async (event) => {
    event.preventDefault();
    setNotice('');

    const lines = finishedGoodsForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Math.abs(Number(row.quantity) || 0),
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行成品明细（成品不能为空）。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/finished-goods`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          plan_id: finishedGoodsForm.plan_id ? Number(finishedGoodsForm.plan_id) : null,
          warehouse_id: finishedGoodsForm.warehouse_id ? Number(finishedGoodsForm.warehouse_id) : null,
          receipt_date: finishedGoodsForm.receipt_date || null,
          workshop: finishedGoodsForm.workshop || null,
          handler: finishedGoodsForm.handler || null,
          note: finishedGoodsForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setFinishedGoodsList((prev) => [created, ...prev]);
      setFinishedGoodsForm({ ...emptyFinishedGoodsForm });
      setNotice(
        `成品入库单 ${created.receipt_no} 已生成，共 ${Number(created.total_quantity || 0).toLocaleString()} 件，` +
          `成品已入库并结转生产成本。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // 委外加工：列表 / 录入 / 发料明细增删 / 提交
  async function refreshOutsourcings(keyword) {
    try {
      const params = new URLSearchParams();
      const kw = keyword !== undefined ? keyword : outsourcingKeyword;
      if (kw) params.set('keyword', kw);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/outsourcings${query}`, { headers: authHeaders() });
      if (response.ok) setOutsourcings(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  // ——— 报表中心（第 4 批）：目录 + 取数 + 导出 ———
  async function refreshReportCatalog() {
    try {
      const response = await fetch(`${API_BASE}/reports/catalog`, { headers: authHeaders() });
      if (!response.ok) throw new Error('报表目录加载失败');
      const data = await response.json();
      setReportCatalog(data);
      // 首次进来把选中项落到目录里真实存在的第一张报表上
      const first = (data.groups || []).flatMap((group) => group.reports || [])[0];
      if (first && !(data.groups || []).some((group) => (group.reports || []).some((item) => item.key === reportKey))) {
        setReportKey(first.key);
      }
    } catch (err) {
      setNotice(err.message || '报表目录加载失败');
    }
  }

  // 16 张报表共用一个取数入口，参数按当前选中报表的形态组装
  async function refreshReportData(overrides) {
    if (!reportKey) return;
    setReportBusy(true);
    try {
      const query = { ...reportQuery, ...(overrides || {}) };
      const params = new URLSearchParams();
      ['date_from', 'date_to', 'dimension', 'period', 'keyword'].forEach((field) => {
        if (query[field]) params.set(field, query[field]);
      });
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/reports/data/${reportKey}${suffix}`, { headers: authHeaders() });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || '报表取数失败');
      }
      setReportResult(await response.json());
    } catch (err) {
      setReportResult(null);
      setNotice(err.message || '报表取数失败');
    } finally {
      setReportBusy(false);
    }
  }

  function selectReport(key) {
    setReportResult(null);
    // 换报表时把维度/粒度重置回该报表的默认值，只在后端取到目录后才知道默认值
    setReportQuery((prev) => ({ ...prev, dimension: '', period: '' }));
    setReportKey(key);
  }

  function exportReport() {
    const query = { ...reportQuery };
    const params = new URLSearchParams();
    ['date_from', 'date_to', 'dimension', 'period', 'keyword'].forEach((field) => {
      if (query[field]) params.set(field, query[field]);
    });
    const suffix = params.toString() ? `?${params.toString()}` : '';
    // 直接让浏览器下载（后端带 Content-Disposition 与 UTF-8 BOM）
    window.open(`${API_BASE}/reports/export/${reportKey}${suffix}`, '_blank');
  }

  const handleReportQueryChange = (field) => (event) => {
    const { value } = event.target;
    setReportQuery((prev) => ({ ...prev, [field]: value }));
  };

  // 报表行下面那行小字：商品看规格/单位/分类，客户看编号，销售员看名字
  function reportRowMeta(row) {
    const extra = row.extra || {};
    if (extra.product_id) {
      return [extra.standards, extra.unit, extra.category].filter(Boolean).join(' · ');
    }
    if (extra.category) return '商品分类';
    if (extra.salesman) return `销售员：${extra.salesman}`;
    if (extra.party_id) return `客户编号 ${extra.party_id}`;
    return '';
  }

  // 趋势图：横向条形，最多画 24 根（再多一行一根读不出来）
  function renderReportChart() {
    const series = (reportResult?.series || []).slice(-24);
    if (!series.length) return null;
    const max = Math.max(...series.map((item) => Number(item.value) || 0), 1);
    return (
      <div className="chart-bars report-chart">
        {series.map((item) => (
          <div className="chart-row" key={item.label}>
            <span>{item.label}</span>
            <div className="chart-track">
              <div className="chart-fill" style={{ width: `${(Number(item.value) / max) * 100}%` }} />
            </div>
            <strong>{plain(item.value)}</strong>
          </div>
        ))}
      </div>
    );
  }

  const REPORT_DIMENSION_HEAD = { product: '商品', customer: '客户', category: '商品分类', salesman: '销售员' };

  function renderReportBody() {
    if (!reportResult) {
      return <div className="empty-state">{reportBusy ? '正在取数…' : '选择左侧报表开始查看。'}</div>;
    }
    const shape = reportResult.shape;
    const rows = reportResult.rows || [];

    if (shape === 'overview') {
      return (
        <div className="report-overview">
          {(reportResult.metric_groups || []).map((group) => (
            <section className="panel report-block" key={group.title}>
              <div className="section-header"><h2>{group.title}</h2></div>
              <div className="report-summary-grid">
                {group.metrics.map((metric) => (
                  <div className="metric-card" key={metric.label}>
                    <span>{metric.label}</span>
                    <strong>{metric.unit === 'CNY' ? money(metric.value) : `${plain(metric.value)}${metric.unit === '%' ? '%' : ''}`}</strong>
                  </div>
                ))}
              </div>
            </section>
          ))}

          {renderReportChart() && (
            <section className="panel report-block">
              <div className="section-header"><h2>月度销售趋势</h2><span className="status-badge">最近 24 期</span></div>
              {renderReportChart()}
            </section>
          )}

          <div className="report-grid">
            {(reportResult.highlights || []).map((block) => (
              <section className="panel report-block" key={block.title}>
                <div className="section-header"><h2>{block.title}</h2></div>
                {block.rows.length ? (
                  <table className="data-table">
                    <thead><tr><th>名称</th><th>数量</th><th>金额</th><th>毛利</th></tr></thead>
                    <tbody>
                      {block.rows.map((row) => (
                        <tr key={row.name}>
                          <td>{row.name}</td>
                          <td className="num">{plain(row.quantity)}</td>
                          <td className="num">{money(row.amount)}</td>
                          <td className="num">{money(row.gross_profit)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="table-hint">该区间内没有数据。</div>}
              </section>
            ))}
          </div>
        </div>
      );
    }

    if (!rows.length) {
      return <div className="empty-state">该区间内没有数据。换个日期范围或清空筛选条件试试。</div>;
    }

    if (shape === 'crosstab') {
      const buckets = reportResult.buckets || [];
      const summary = reportResult.summary || {};
      return (
        <>
          <div className="table-wrap report-table-wrap">
            <table className="data-table report-table">
              <thead>
                <tr>
                  <th className="report-sticky">{REPORT_DIMENSION_HEAD[reportResult.report.dimension] || '名称'}</th>
                  {buckets.map((bucket) => <th key={bucket} className="num">{bucket}</th>)}
                  <th className="num">合计数量</th>
                  <th className="num">合计金额</th>
                  <th className="num">毛利</th>
                  <th className="num">毛利率</th>
                  <th className="num">占比</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td className="report-sticky">
                      <div className="report-name">{row.name}</div>
                      {reportRowMeta(row) && <div className="report-meta">{reportRowMeta(row)}</div>}
                    </td>
                    {row.cells.map((cell, index) => (
                      <td className="num" key={buckets[index] || index}>
                        {cell.quantity || cell.amount ? (
                          <>
                            <div>{plain(cell.quantity)}</div>
                            <div className="report-meta">{money(cell.amount)}</div>
                          </>
                        ) : <span className="report-muted">—</span>}
                      </td>
                    ))}
                    <td className="num">{plain(row.quantity)}</td>
                    <td className="num">{money(row.amount)}</td>
                    <td className="num">{money(row.gross_profit)}</td>
                    <td className="num">{plain(row.margin)}%</td>
                    <td className="num">{plain(row.share)}%</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="report-sticky">合计（{summary.row_count || rows.length} 行）</td>
                  {buckets.map((bucket) => <td key={bucket} />)}
                  <td className="num">{plain(summary.total_quantity)}</td>
                  <td className="num">{money(summary.total_amount)}</td>
                  <td className="num">{money(summary.gross_profit)}</td>
                  <td className="num">{plain(summary.margin)}%</td>
                  <td className="num">100%</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="table-hint">共 {rows.length} 行 × {buckets.length} 期。单元格上行是数量、下行是金额。</div>
          <section className="panel report-block">
            <div className="section-header"><h2>各期合计趋势</h2><span className="status-badge">最近 24 期</span></div>
            {renderReportChart()}
          </section>
        </>
      );
    }

    if (shape === 'flow') {
      const summary = reportResult.summary || {};
      return (
        <>
          <div className="table-wrap report-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>商品</th><th>规格</th><th>仓库</th><th>单位</th>
                  <th className="num">期初</th><th className="num">本期入库</th><th className="num">本期出库</th><th className="num">期末结存</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <div className="report-name">{row.product_name}</div>
                      <div className="report-meta">{row.sku}{row.category ? ` · ${row.category}` : ''}</div>
                    </td>
                    <td>{row.standards || '—'}</td>
                    <td>{row.warehouse_name}</td>
                    <td>{row.unit || '—'}</td>
                    <td className="num">{plain(row.opening)}</td>
                    <td className="num report-in">{plain(row.inbound)}</td>
                    <td className="num report-out">{plain(row.outbound)}</td>
                    <td className="num"><strong>{plain(row.closing)}</strong></td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>合计（{summary.row_count || rows.length} 行）</td>
                  <td className="num">{plain(summary.opening)}</td>
                  <td className="num">{plain(summary.inbound)}</td>
                  <td className="num">{plain(summary.outbound)}</td>
                  <td className="num">{plain(summary.closing)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <div className="table-hint">恒等式：期初 + 本期入库 − 本期出库 = 期末结存。</div>
        </>
      );
    }

    // detail：商品销售明细表
    const summary = reportResult.summary || {};
    return (
      <>
        <div className="table-wrap report-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>日期</th><th>单号</th><th>客户</th><th>商品</th><th>规格</th><th>单位</th>
                <th className="num">数量</th><th className="num">单价</th><th className="num">金额</th>
                <th className="num">毛利</th><th>业务员</th><th>备注</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.doc_no}-${row.product_name}-${index}`}>
                  <td>{row.day}</td>
                  <td>{row.doc_no}</td>
                  <td>{row.party_name}</td>
                  <td>{row.product_name}</td>
                  <td>{row.standards || '—'}</td>
                  <td>{row.unit || '—'}</td>
                  <td className="num">{plain(row.quantity)}</td>
                  <td className="num">{money(row.unit_price)}</td>
                  <td className="num">{money(row.amount)}</td>
                  <td className="num">{money(row.gross_profit)}</td>
                  <td>{row.salesman}</td>
                  <td>{row.note || '—'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={6}>合计（{summary.total_rows || rows.length} 行）</td>
                <td className="num">{plain(summary.total_quantity)}</td>
                <td />
                <td className="num">{money(summary.total_amount)}</td>
                <td className="num">{money(summary.gross_profit)}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
        <div className="table-hint">
          {summary.total_rows > rows.length
            ? `共 ${summary.total_rows} 行，当前显示前 ${rows.length} 行；导出的 CSV 含全部行。`
            : `共 ${summary.total_rows || rows.length} 行。`}
          退货行以负数出现并标注「退货冲减」。
        </div>
        <section className="panel report-block">
          <div className="section-header"><h2>每日销售额</h2><span className="status-badge">最近 24 天</span></div>
          {renderReportChart()}
        </section>
      </>
    );
  }


  const handleOutsourcingChange = (field) => (event) => {
    const { value } = event.target;
    setOutsourcingForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'product_id') {
        const product = products.find((item) => String(item.id) === String(value));
        if (product) next.unit_price = String(product.purchase_price ?? '0');
      }
      return next;
    });
  };

  const handleOutsourcingItemChange = (index, field) => (event) => {
    const value = event.target.value;
    setOutsourcingForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) next.unit_price = String(product.purchase_price ?? '0');
        }
        return next;
      }),
    }));
  };

  const addOutsourcingItem = () => {
    setOutsourcingForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', quantity: '1', unit_price: '0' }],
    }));
  };

  const removeOutsourcingItem = (index) => {
    setOutsourcingForm((prev) => ({
      ...prev,
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));
  };

  const submitOutsourcing = async (event) => {
    event.preventDefault();
    setNotice('');

    if (!outsourcingForm.product_id) {
      setNotice('请选择委外加工要产出的成品。');
      return;
    }
    const lines = outsourcingForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Math.abs(Number(row.quantity) || 0),
        unit_price: Number(row.unit_price) || 0,
      }));
    if (lines.length === 0) {
      setNotice('至少要有一行发出材料明细。');
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/outsourcings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          supplier_id: outsourcingForm.supplier_id ? Number(outsourcingForm.supplier_id) : null,
          warehouse_id: outsourcingForm.warehouse_id ? Number(outsourcingForm.warehouse_id) : null,
          order_date: outsourcingForm.order_date || null,
          handler: outsourcingForm.handler || null,
          product_id: Number(outsourcingForm.product_id),
          quantity: Math.abs(Number(outsourcingForm.quantity) || 0),
          unit_price: Number(outsourcingForm.unit_price) || 0,
          process_fee: Number(outsourcingForm.process_fee) || 0,
          note: outsourcingForm.note || null,
          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }

      const created = await response.json();
      setOutsourcings((prev) => [created, ...prev]);
      setOutsourcingForm({ ...emptyOutsourcingForm });
      setNotice(
        `委外加工单 ${created.order_no} 已生成：发出材料减少库存、收回成品入库，` +
          `加工费 ${Number(created.process_fee || 0).toLocaleString()} 元已挂应付。`,
      );
      refreshStock();
    } catch (err) {
      setNotice(err.message || '新增失败');
    }
  };

  // 用函数声明（而非 const 箭头）以便上面的 useEffect 能在渲染后安全调用
  // keyword 省略时沿用当前搜索框内容（外部跳转时会显式传入商品名）
  async function refreshStock(keyword) {
    try {
      const kw = (keyword === undefined ? inventoryKeyword : keyword) || '';
      const query = kw ? `?keyword=${encodeURIComponent(kw)}` : '';
      const response = await fetch(`${API_BASE}/inventory/stock${query}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (response.ok) {
        setStockData(await response.json());
      }
    } catch {
      // 现存量拉取失败不影响其它功能，界面上保留上一次的数据
    }
  }

  const submitInventory = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/inventory`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          product_id: Number(inventoryForm.product_id),
          warehouse_id: Number(inventoryForm.warehouse_id),
          transaction_type: inventoryForm.transaction_type,
          quantity: Number(inventoryForm.quantity),
          unit_price: Number(inventoryForm.unit_price),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建库存记录失败' }));
        throw new Error(errorData.detail ?? '创建库存记录失败');
      }

      const item = await response.json();
      setInventory((prev) => [item, ...prev]);
      setInventoryForm(emptyInventoryForm);
      setNotice('库存记录已成功新增。');
      await refreshStock();
    } catch (err) {
      setNotice(err.message || '库存新增失败');
    }
  };

  const submitFinance = async (event) => {
    event.preventDefault();
    setNotice('');

    try {
      const response = await fetch(`${API_BASE}/finance`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          transaction_type: financeForm.transaction_type,
          amount: Number(financeForm.amount),
          currency: financeForm.currency,
          note: financeForm.note || null,
          related_order_id: financeForm.related_order_id ? Number(financeForm.related_order_id) : null,
          customer_id: financeForm.customer_id ? Number(financeForm.customer_id) : null,
          supplier_id: financeForm.supplier_id ? Number(financeForm.supplier_id) : null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建财务记录失败' }));
        throw new Error(errorData.detail ?? '创建财务记录失败');
      }

      const item = await response.json();
      setFinance((prev) => [item, ...prev]);
      setFinanceForm(emptyFinanceForm);
      setNotice('财务记录已成功新增。');
    } catch (err) {
      setNotice(err.message || '财务新增失败');
    }
  };

  // 按角色过滤菜单：非管理员看不到报表中心
  const visibleGroups = useMemo(
    () =>
      menuGroups
        .map((group) => ({
          ...group,
          items: group.items.filter((item) => userProfile.role === 'admin' || item.key !== 'reports'),
        }))
        .filter((group) => group.items.length > 0),
    [userProfile.role],
  );

  const toggleGroup = (groupKey) => {
    setCollapsedGroups((prev) =>
      prev.includes(groupKey) ? prev.filter((key) => key !== groupKey) : [...prev, groupKey],
    );
  };

  const activeTab = useMemo(() => tabs.find((tab) => tab.key === selectedTab), [selectedTab]);

  // —— 跨页关联：单据 ↔ 库存 / 档案 ——
  // 现存量按商品汇总（同一商品可能分散在多个仓库，明细行只看总量）
  const stockByProduct = useMemo(() => {
    const map = {};
    (stockData.rows || []).forEach((row) => {
      const id = row.product_id;
      if (id === undefined || id === null) return;
      map[id] = (map[id] || 0) + Number(row.quantity || 0);
    });
    return map;
  }, [stockData]);

  // 现存量按「仓库 × 商品」索引：调拨单要看到某个商品在指定仓库还有多少可调
  const stockByWarehouseProduct = useMemo(() => {
    const map = {};
    (stockData.rows || []).forEach((row) => {
      if (row.product_id === undefined || row.product_id === null) return;
      map[`${row.warehouse_id}-${row.product_id}`] = Number(row.quantity || 0);
    });
    return map;
  }, [stockData]);

  const productById = useMemo(() => {
    const map = {};
    (products || []).forEach((item) => {
      map[item.id] = item;
    });
    return map;
  }, [products]);

  // 商品 → 库存管理页：自动把商品名填进搜索框并筛选，同时留下来源提示
  const jumpToStock = (productOrId) => {
    const product =
      productOrId && typeof productOrId === 'object' ? productOrId : productById[productOrId];
    const keyword = (product?.name || '').trim();
    setInventoryKeyword(keyword);
    setInventoryFocus({
      keyword,
      from: activeTab?.label || '单据',
      productName: product?.name || '',
      sku: product?.sku || '',
      productId: product?.id ?? null,
    });
    setSelectedTab('inventory');
    refreshStock(keyword);
    setNotice(keyword ? `已跳到库存管理，并按「${keyword}」筛选现存量。` : '已跳到库存管理。');
  };

  // 供应商 / 客户 → 档案页：定位并高亮对应记录，方便核对联系方式与地址
  const jumpToArchive = (tab, id, label) => {
    setArchiveFocus(id ? { tab, id } : null);
    setSelectedTab(tab);
    if (label) setNotice(`已跳到${label}档案，已定位到对应记录。`);
  };

  const clearInventoryFocus = () => {
    setInventoryFocus(null);
    setInventoryKeyword('');
    refreshStock('');
  };

  // 单据明细行内的「现存量 + 查库存」小组件；返回 JSX 而非独立组件，避免多余 hook 开销
  const renderStockHint = (productId) => {
    if (!productId) return null;
    const qty = stockByProduct[productId];
    const known = qty !== undefined;
    const low = known && Number(qty) <= 0;
    return (
      <span className="stock-hint">
        现存
        <strong className={low ? 'num-negative' : undefined}>
          {known ? Number(qty).toLocaleString() : '—'}
        </strong>
        <button type="button" className="link-btn" onClick={() => jumpToStock(productId)}>
          查库存
        </button>
      </span>
    );
  };

  // 调拨明细行内的「调出仓可调量」提示：直接读该商品在调出仓的现存量
  const renderTransferStockHint = (productId, warehouseId) => {
    if (!productId) return null;
    if (!warehouseId) {
      return (
        <span className="stock-hint">选定调出仓库后显示可调量</span>
      );
    }
    const qty = stockByWarehouseProduct[`${warehouseId}-${productId}`];
    const known = qty !== undefined;
    const low = known && Number(qty) <= 0;
    return (
      <span className="stock-hint">
        调出仓现存
        <strong className={low ? 'num-negative' : undefined}>
          {known ? Number(qty).toLocaleString() : '0'}
        </strong>
        <button type="button" className="link-btn" onClick={() => jumpToStock(productId)}>
          查库存
        </button>
      </span>
    );
  };

  // 供应商 / 客户下拉旁的「档案」快捷入口
  const renderPartyLink = (tab, id, label) => {
    if (!id) return null;
    return (
      <button type="button" className="link-btn" onClick={() => jumpToArchive(tab, Number(id), label)}>
        查看档案
      </button>
    );
  };

  const mobileQuickActions = [
    { label: '开单管理', target: 'sales', tone: 'blue' },
    { label: '采购入库', target: 'purchase', tone: 'green' },
    { label: '库存管理', target: 'inventory', tone: 'orange' },
    { label: '财务流水', target: 'finance', tone: 'purple' },
  ];

  if (!isAuthenticated) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <div className="brand">ERP 核心系统</div>
          <h2>登录后台</h2>
          <p className="auth-subtitle">使用已注册的 ERP 账号登录后继续管理业务。</p>

          <form onSubmit={submitLogin} className="erp-form auth-form">
            <label>
              用户名
              <input value={loginForm.username} onChange={handleLoginChange('username')} required />
            </label>
            <label>
              密码
              <input type="password" value={loginForm.password} onChange={handleLoginChange('password')} required />
            </label>
            <button className="primary-btn" type="submit">登录</button>
          </form>

          {notice && <div className="notice-box">{notice}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className={`app-shell ${menuOpen ? 'menu-open' : ''}`}>
      {/* 手机端顶部条：抽屉开关 + 当前页面标题（桌面端隐藏） */}
      <div className="mobile-bar">
        <button
          type="button"
          className="mobile-menu-btn"
          aria-label="打开菜单"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className="mobile-menu-icon" aria-hidden="true" />
          菜单
        </button>
        <span className="mobile-bar-title">{activeTab?.label ?? '运营概览'}</span>
      </div>
      <aside className="sidebar">
        <div className="brand sidebar-brand">
          <span className="brand-mark">ERP</span>
          <span className="brand-text">核心系统</span>
          <button
            className="sidebar-close"
            type="button"
            aria-label="收起菜单"
            onClick={() => setMenuOpen(false)}
          >
            ×
          </button>
        </div>
        <nav className="side-nav">
          {visibleGroups.map((group) => {
            const isCollapsed = collapsedGroups.includes(group.key);
            const hasActive = group.items.some((item) => item.key === selectedTab);
            const isSingle = group.items.length === 1;
            return (
              <div className={`nav-group ${hasActive ? 'has-active' : ''}`} key={group.key}>
                <button
                  type="button"
                  className={`nav-group-title ${isCollapsed ? 'collapsed' : ''} ${isSingle ? 'is-single' : ''}`}
                  onClick={() => toggleGroup(group.key)}
                  aria-expanded={!isCollapsed}
                >
                  <span>{group.label}</span>
                  <span className="nav-group-arrow" aria-hidden="true" />
                </button>
                {!isCollapsed && (
                  <div className="nav-group-items">
                    {group.items.map((item) => (
                      <button
                        key={item.key}
                        className={`nav-item ${selectedTab === item.key ? 'active' : ''} ${item.todo ? 'is-todo' : ''}`}
                        onClick={() => {
                          setSelectedTab(item.key);
                          // 手机端选完菜单把抽屉收起来，免得挡住内容
                          setMenuOpen(false);
                        }}
                        type="button"
                        title={item.todo ? '框架位已按浩技云预留，功能建设中' : undefined}
                      >
                        <span>{item.label}</span>
                        {item.todo && <span className="nav-todo">待建</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        <button className="logout-btn" type="button" onClick={handleLogout}>退出登录</button>
      </aside>
      {/* 手机端抽屉遮罩：点击空白处收起菜单 */}
      <div
        className="sidebar-backdrop"
        role="presentation"
        onClick={() => setMenuOpen(false)}
      />

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">{activeTab?.groupLabel ?? '本地 ERP 管理后台'}</p>
            <h1>{activeTab?.label ?? '运营概览'}</h1>
          </div>
          <div className="topbar-actions">
            <button
              className="secondary-btn small-btn"
              type="button"
              onClick={() => {
                setSelectedTab('quotation');
                setNotice('已切换到报价单页面。');
              }}
            >
              新建报价
            </button>
            <button
              className="primary-btn"
              type="button"
              onClick={() => {
                setSelectedTab('sales');
                setNotice('已切换到新增销售单页面。');
              }}
            >
              新增订单
            </button>
          </div>
        </header>

        {loading ? (
          <div className="status-box">加载中...</div>
        ) : error ? (
          <div className="status-box error">{error}</div>
        ) : (
          <>
            {activeTab?.todo && (
              <section className="todo-panel">
                <span className="todo-badge">模块建设中</span>
                <h2>{activeTab.label}</h2>
                <p className="todo-sub">{activeTab.groupLabel} · 已按浩技云进销存框架预留菜单位</p>
                <p className="todo-desc">
                  这个模块的位置已经按浩技云的业务框架摆好了，功能正在按顺序建设。
                  同一分组里没有「待建」标记的菜单现在就可以正常使用。
                </p>
                <div className="todo-tip">需要优先建设这个模块的话，直接告诉我，我把它排到前面。</div>
              </section>
            )}
            {selectedTab === 'mobile' && (
              <section className="mobile-app-shell">
                <div className="mobile-hero">
                  <div>
                    <p className="eyebrow">移动经营视图</p>
                    <h2>今日经营</h2>
                  </div>
                  <span className="status-badge">{mobileDashboard.status === 'healthy' ? '健康' : mobileDashboard.status === 'warning' ? '关注' : '风险'}</span>
                </div>

                <div className="mobile-summary-grid">
                  {mobileDashboard.kpis?.map((item) => (
                    <div className="mobile-stat-card" key={item.label}>
                      <span>{item.label}</span>
                      <strong>{item.unit === 'CNY' ? `¥${Number(item.value || 0).toLocaleString()}` : item.value}</strong>
                    </div>
                  )) || []}
                </div>

                <div className="mobile-quick-grid">
                  {mobileQuickActions.map((action) => (
                    <button
                      key={action.label}
                      type="button"
                      className={`mobile-action-btn ${action.tone}`}
                      onClick={() => setSelectedTab(action.target)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>

                <div className="panel mobile-panel">
                  <div className="section-header">
                    <h3>经营提醒</h3>
                    <span className="status-badge">{mobileDashboard.risk_count ?? 0} 项风险</span>
                  </div>
                  <ul className="list">
                    {(mobileDashboard.recommendations || []).map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="panel mobile-panel">
                  <div className="section-header">
                    <h3>业务概览</h3>
                    <span className="status-badge">{mobileDashboard.updated_at || '刚刚更新'}</span>
                  </div>
                  <div className="report-pill-row">
                    <div className="report-pill">
                      <span>销售</span>
                      <strong>¥{Number(mobileDashboard.summary?.sales_total || 0).toLocaleString()}</strong>
                    </div>
                    <div className="report-pill">
                      <span>采购</span>
                      <strong>¥{Number(mobileDashboard.summary?.purchase_total || 0).toLocaleString()}</strong>
                    </div>
                    <div className="report-pill">
                      <span>利润</span>
                      <strong>¥{Number(mobileDashboard.summary?.net_profit || 0).toLocaleString()}</strong>
                    </div>
                  </div>
                </div>

                <div className="mobile-bottom-dock">
                  <button type="button" className="dock-btn active" onClick={() => setSelectedTab('mobile')}>首页</button>
                  <button type="button" className="dock-btn" onClick={() => setSelectedTab('sales')}>订单</button>
                  <button type="button" className="dock-btn" onClick={() => setSelectedTab('finance')}>财务</button>
                  <button type="button" className="dock-btn" onClick={() => setSelectedTab('agent')}>助手</button>
                </div>
              </section>
            )}

            {selectedTab === 'bom' && (
              <section className="bom-shell">
                <div className="panel">
                  <div className="section-header">
                    <h2>BOM 物料清单</h2>
                    <span className="status-badge">{bomTree.length} 个根节点</span>
                  </div>

                  <form className="erp-form bom-form" onSubmit={submitBomNode}>
                    <div className="form-row two-col">
                      <label>
                        产品 ID
                        <input value={bomForm.product_id} onChange={handleBomFormChange('product_id')} required />
                      </label>
                      <label>
                        组件 ID
                        <input value={bomForm.component_product_id} onChange={handleBomFormChange('component_product_id')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        父节点 ID
                        <input value={bomForm.parent_id} onChange={handleBomFormChange('parent_id')} placeholder="可为空" />
                      </label>
                      <label>
                        节点类型
                        <select value={bomForm.bom_type} onChange={handleBomFormChange('bom_type')}>
                          <option value="assembly">装配</option>
                          <option value="component">组件</option>
                          <option value="raw_material">原材料</option>
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        节点名称
                        <input value={bomForm.name} onChange={handleBomFormChange('name')} />
                      </label>
                      <label>
                        编码
                        <input value={bomForm.code} onChange={handleBomFormChange('code')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        数量
                        <input value={bomForm.quantity} onChange={handleBomFormChange('quantity')} type="number" min="1" />
                      </label>
                      <label>
                        单位成本
                        <input value={bomForm.unit_cost} onChange={handleBomFormChange('unit_cost')} type="number" min="0" step="0.01" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        层级
                        <input value={bomForm.level} onChange={handleBomFormChange('level')} type="number" min="0" />
                      </label>
                      <label>
                        备注
                        <input value={bomForm.description} onChange={handleBomFormChange('description')} />
                      </label>
                    </div>

                    <button className="primary-btn" type="submit">新增 BOM 节点</button>
                  </form>
                </div>

                <div className="panel">
                  <div className="section-header">
                    <h2>树形视图</h2>
                  </div>
                  {bomTree.length > 0 ? (
                    <ul className="bom-tree-root">{renderBomTree(bomTree)}</ul>
                  ) : (
                    <div className="empty-state">暂无 BOM 树，请先新增节点。</div>
                  )}
                </div>
              </section>
            )}

            {selectedTab === 'overview' && (
              <>
                {/* 顶部问候横幅 */}
                <section className="welcome-banner">
                  <div className="welcome-text">
                    <p className="welcome-date">{new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}</p>
                    <h2 className="welcome-title">{(() => { const h = new Date().getHours(); return h < 6 ? '凌晨好' : h < 12 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'; })()}，欢迎回来 👋</h2>
                    <p className="welcome-sub">
                      今日销售 ¥{Number(summary?.sales_total ?? 0).toLocaleString()}，采购 ¥{Number(summary?.purchase_total ?? 0).toLocaleString()}，
                      {executiveDashboard.status?.health === 'healthy' ? '经营整体健康。' : '有需要关注的经营事项。'}
                    </p>
                  </div>
                  <div className="welcome-actions">
                    <button type="button" className="welcome-btn ghost" onClick={() => setSelectedTab('sales')}>开销售单</button>
                    <button type="button" className="welcome-btn ghost" onClick={() => setSelectedTab('purchase')}>录入库单</button>
                    <button type="button" className="welcome-btn solid" onClick={() => setSelectedTab('quotation')}>新建报价</button>
                  </div>
                </section>

                {/* KPI 卡片组 */}
                <section className="kpi-grid">
                  {[
                    { label: '客户数', value: Number(summary?.customers ?? 0).toLocaleString(), icon: '👥', tone: 'blue', sub: '合作客户' },
                    { label: '供应商数', value: Number(summary?.suppliers ?? 0).toLocaleString(), icon: '🏭', tone: 'indigo', sub: '供货伙伴' },
                    { label: '商品数', value: Number(summary?.products ?? 0).toLocaleString(), icon: '📦', tone: 'teal', sub: '在售商品' },
                    { label: '销售总额', value: `¥${Number(summary?.sales_total ?? 0).toLocaleString()}`, icon: '📈', tone: 'green', sub: '累计销售额' },
                    { label: '采购总额', value: `¥${Number(summary?.purchase_total ?? 0).toLocaleString()}`, icon: '🛒', tone: 'amber', sub: '累计采购额' },
                    { label: '净利润', value: `¥${Number((summary?.sales_total ?? 0) - (summary?.purchase_total ?? 0)).toLocaleString()}`, icon: '💰', tone: 'rose', sub: '销售 − 采购' },
                  ].map((card) => (
                    <div className={`kpi-card kpi-${card.tone}`} key={card.label}>
                      <div className="kpi-icon">{card.icon}</div>
                      <div className="kpi-meta">
                        <span className="kpi-label">{card.label}</span>
                        <strong className="kpi-value">{card.value}</strong>
                        <span className="kpi-sub">{card.sub}</span>
                      </div>
                    </div>
                  ))}
                </section>

                {/* 趋势 + 健康度 两栏 */}
                <div className="dash-grid">
                  <section className="panel dash-panel">
                    <div className="section-header">
                      <h2>经营趋势</h2>
                      <button type="button" className="secondary-btn small-btn" onClick={exportDailyReport}>导出经营日报</button>
                    </div>
                    {overviewTrend.length > 0 ? (
                      <div className="trend-chart">
                        {(() => {
                          const maxValue = Math.max(...overviewTrend.flatMap((item) => [Number(item.income || 0), Number(item.expense || 0)]), 1);
                          const values = overviewTrend.map((item) => Number(item.income || 0));
                          const minValue = Math.min(...values, 0);
                          const range = maxValue - minValue || 1;
                          const points = values.map((v, i) => {
                            const x = (i / Math.max(values.length - 1, 1)) * 100;
                            const y = 100 - ((v - minValue) / range) * 92 - 4;
                            return `${x},${y}`;
                          }).join(' ');
                          const areaPoints = `0,100 ${points} 100,100`;
                          return (
                            <svg className="trend-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
                              <defs>
                                <linearGradient id="trendArea" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="0%" stopColor="#2563eb" stopOpacity="0.28" />
                                  <stop offset="100%" stopColor="#2563eb" stopOpacity="0" />
                                </linearGradient>
                                <linearGradient id="trendLine" x1="0" y1="0" x2="1" y2="0">
                                  <stop offset="0%" stopColor="#4f46e5" />
                                  <stop offset="100%" stopColor="#2563eb" />
                                </linearGradient>
                              </defs>
                              <polygon points={areaPoints} fill="url(#trendArea)" />
                              <polyline points={points} fill="none" stroke="url(#trendLine)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                              {values.map((v, i) => {
                                const x = (i / Math.max(values.length - 1, 1)) * 100;
                                const y = 100 - ((v - minValue) / range) * 92 - 4;
                                return <circle key={i} cx={x} cy={y} r="1.6" fill="#2563eb" vectorEffect="non-scaling-stroke" />;
                              })}
                            </svg>
                          );
                        })()}
                        <div className="trend-labels">
                          {overviewTrend.map((item) => (
                            <span key={item.label}>{item.label}</span>
                          ))}
                        </div>
                        <div className="trend-legend">
                          <span className="legend-dot income" />收入
                          <span className="legend-dot expense" />支出
                        </div>
                      </div>
                    ) : (
                      <div className="empty-state">暂无经营趋势数据</div>
                    )}
                  </section>

                  <section className="panel dash-panel">
                    <div className="section-header">
                      <h2>经营健康度</h2>
                      <span className="status-badge">{executiveDashboard.status?.health === 'healthy' ? '健康' : '关注'}</span>
                    </div>
                    <div className="health-list">
                      {leadershipBoard.cards.map((item) => {
                        const pct = Math.min(100, Math.max(0, parseInt(item.value, 10) || 0));
                        return (
                          <div className="health-row" key={item.label}>
                            <div className="health-head">
                              <span>{item.label}</span>
                              <strong className={item.tone === 'warn' ? 'health-warn' : ''}>{item.value}</strong>
                            </div>
                            <div className="health-track">
                              <div className={`health-fill ${item.tone === 'warn' ? 'fill-warn' : 'fill-good'}`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    <div className="health-metrics">
                      <div className="health-metric">
                        <span className="health-metric-label">毛利率</span>
                        <strong>{Number(executiveDashboard.status?.margin || 0).toFixed(1)}%</strong>
                      </div>
                      <div className="health-metric">
                        <span className="health-metric-label">生产进度</span>
                        <strong>{Number(executiveDashboard.status?.production || 0).toFixed(1)}%</strong>
                      </div>
                      <div className="health-metric">
                        <span className="health-metric-label">风险项</span>
                        <strong>{executiveDashboard.status?.risk_count ?? 0}</strong>
                      </div>
                    </div>
                  </section>
                </div>

                {/* 经营提醒 + 最近业务 两栏 */}
                <div className="dash-grid">
                  <section className="panel dash-panel">
                    <div className="section-header">
                      <h2>经营提醒</h2>
                      <span className="status-badge">{executiveDashboard.alerts?.length ?? 0} 项</span>
                    </div>
                    {executiveDashboard.alerts?.length ? (
                      <div className="alert-list">
                        {executiveDashboard.alerts.map((alert, index) => (
                          <div className={`alert-card alert-${alert.severity || 'info'}`} key={`${alert.title}-${index}`}>
                            <span className="alert-dot" />
                            <div className="alert-body">
                              <strong>{alert.title}</strong>
                              <p>{alert.message}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-state">暂无经营提醒</div>
                    )}

                    <div className="section-header" style={{ marginTop: '22px' }}>
                      <h3>管理建议</h3>
                    </div>
                    <ul className="advice-list">
                      {leadershipBoard.actions.map((item, index) => (
                        <li key={`${item}-${index}`}><span className="advice-num">{index + 1}</span>{item}</li>
                      ))}
                    </ul>
                  </section>

                  <section className="panel dash-panel">
                    <div className="section-header">
                      <h2>关键动态</h2>
                      <span className="status-badge">实时</span>
                    </div>
                    <div className="activity-timeline">
                      {[
                        { icon: '🧾', text: '客户订单已同步到 ERP', time: '刚刚' },
                        { icon: '🛒', text: '采购单待审核', time: '10 分钟前' },
                        { icon: '⚠️', text: `库存预警 ${executiveDashboard.status?.risk_count ?? 0} 项待处理`, time: '1 小时前' },
                        { icon: '💰', text: '财务流水已归档', time: '今天' },
                        { icon: '📦', text: `${operationsBoard.production_orders?.length ?? 0} 个生产单在排期`, time: '进行中' },
                      ].map((item, index) => (
                        <div className="timeline-item" key={index}>
                          <div className="timeline-icon">{item.icon}</div>
                          <div className="timeline-body">
                            <p>{item.text}</p>
                            <span>{item.time}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>

                {/* 运营数据速览 */}
                <section className="panel dash-panel">
                  <div className="section-header">
                    <h2>运营速览</h2>
                    <span className="status-badge">{operationsBoard.production_orders.length} 个生产单</span>
                  </div>
                  <div className="report-summary-grid">
                    <div className="metric-card"><span>在产单</span><strong>{operationsBoard.status_breakdown.in_progress ?? 0}</strong></div>
                    <div className="metric-card"><span>项目推进</span><strong>{operationsBoard.project_summary.avg_progress ?? 0}%</strong></div>
                    <div className="metric-card"><span>高优先级</span><strong>{operationsBoard.high_priority_orders.length}</strong></div>
                    <div className="metric-card"><span>项目预算</span><strong>¥{Number(operationsBoard.project_summary.budget_total ?? 0).toLocaleString()}</strong></div>
                    <div className="metric-card"><span>材料成本</span><strong>¥{Number(operationsBoard.cost_summary.material_cost ?? 0).toLocaleString()}</strong></div>
                    <div className="metric-card"><span>人工成本</span><strong>¥{Number(operationsBoard.cost_summary.labor_cost ?? 0).toLocaleString()}</strong></div>
                    <div className="metric-card"><span>总成本</span><strong>¥{Number(operationsBoard.cost_summary.total_cost ?? 0).toLocaleString()}</strong></div>
                    <div className="metric-card"><span>里程碑</span><strong>{operationsBoard.milestones.length}</strong></div>
                  </div>
                </section>
              </>
            )}

            {selectedTab === 'customers' && (
              <div className="management-grid">
                {archiveFocus?.tab === 'customers' && (
                  <div className="focus-banner">
                    <span className="focus-banner-tag">从单据跳转</span>
                    <span className="focus-banner-text">
                      已定位到客户 <strong>{customers.find((c) => c.id === archiveFocus.id)?.name || archiveFocus.id}</strong>
                    </span>
                    <button type="button" className="link-btn" onClick={() => setArchiveFocus(null)}>取消定位</button>
                  </div>
                )}
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增客户</h2>
                    <span className="status-badge">基础资料</span>
                  </div>

                  <form onSubmit={submitCustomer} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户编码
                        <input value={customerForm.code} onChange={handleCustomerChange('code')} required />
                      </label>
                      <label>
                        客户名称
                        <input value={customerForm.name} onChange={handleCustomerChange('name')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        联系电话
                        <input value={customerForm.phone} onChange={handleCustomerChange('phone')} />
                      </label>
                      <label>
                        邮箱
                        <input type="email" value={customerForm.email} onChange={handleCustomerChange('email')} />
                      </label>
                    </div>

                    <label>
                      地址
                      <textarea value={customerForm.address} onChange={handleCustomerChange('address')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存客户</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>客户列表</h2>
                    <span className="status-badge">{customers.length} 人</span>
                  </div>

                  {customers.length === 0 ? (
                    <div className="empty-state">暂无客户数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>编码</th>
                          <th>名称</th>
                          <th>电话</th>
                          <th>邮箱</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {customers.map((row) => (
                          <tr
                            key={row.id}
                            className={archiveFocus?.tab === 'customers' && archiveFocus.id === row.id ? 'focus-row' : undefined}
                          >
                            <td>{row.code}</td>
                            <td>{row.name}</td>
                            <td>{row.phone || '—'}</td>
                            <td>{row.email || '—'}</td>
                            <td>
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={() =>
                                  setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/customers/${row.id}`,
                                    label: `客户 ${row.name}`,
                                    kind: 'customer',
                                  })
                                }
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'suppliers' && (
              <div className="management-grid">
                {archiveFocus?.tab === 'suppliers' && (
                  <div className="focus-banner">
                    <span className="focus-banner-tag">从单据跳转</span>
                    <span className="focus-banner-text">
                      已定位到供应商 <strong>{suppliers.find((s) => s.id === archiveFocus.id)?.name || archiveFocus.id}</strong>
                    </span>
                    <button type="button" className="link-btn" onClick={() => setArchiveFocus(null)}>取消定位</button>
                  </div>
                )}
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增供应商</h2>
                    <span className="status-badge">采购来源</span>
                  </div>

                  <form onSubmit={submitSupplier} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        供应商编码
                        <input value={supplierForm.code} onChange={handleSupplierChange('code')} required />
                      </label>
                      <label>
                        供应商名称
                        <input value={supplierForm.name} onChange={handleSupplierChange('name')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        联系电话
                        <input value={supplierForm.phone} onChange={handleSupplierChange('phone')} />
                      </label>
                      <label>
                        邮箱
                        <input type="email" value={supplierForm.email} onChange={handleSupplierChange('email')} />
                      </label>
                    </div>

                    <label>
                      地址
                      <textarea value={supplierForm.address} onChange={handleSupplierChange('address')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存供应商</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>供应商列表</h2>
                    <span className="status-badge">{suppliers.length} 家</span>
                  </div>

                  {suppliers.length === 0 ? (
                    <div className="empty-state">暂无供应商数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>编码</th>
                          <th>名称</th>
                          <th>电话</th>
                          <th>邮箱</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {suppliers.map((row) => (
                          <tr
                            key={row.id}
                            className={archiveFocus?.tab === 'suppliers' && archiveFocus.id === row.id ? 'focus-row' : undefined}
                          >
                            <td>{row.code}</td>
                            <td>{row.name}</td>
                            <td>{row.phone || '—'}</td>
                            <td>{row.email || '—'}</td>
                            <td>
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={() =>
                                  setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/suppliers/${row.id}`,
                                    label: `供应商 ${row.name}`,
                                    kind: 'supplier',
                                  })
                                }
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'warehouses' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>{editingWarehouseId != null ? '编辑仓库' : '新增仓库'}</h2>
                    <span className="status-badge">库存主数据</span>
                  </div>

                  <form onSubmit={submitWarehouse} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        仓库编码
                        <input
                          value={warehouseForm.code}
                          onChange={handleWarehouseChange('code')}
                          placeholder="如 CK-001"
                          required
                        />
                      </label>
                      <label>
                        仓库名称
                        <input value={warehouseForm.name} onChange={handleWarehouseChange('name')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        货位
                        <input
                          value={warehouseForm.location}
                          onChange={handleWarehouseChange('location')}
                          placeholder="如 A区01号位"
                        />
                      </label>
                      <label>
                        负责人
                        <input value={warehouseForm.manager} onChange={handleWarehouseChange('manager')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        联系电话
                        <input value={warehouseForm.phone} onChange={handleWarehouseChange('phone')} />
                      </label>
                      <label className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={warehouseForm.is_active}
                          onChange={handleWarehouseChange('is_active')}
                        />
                        启用（停用后开单时不作为可选仓库）
                      </label>
                    </div>

                    <label>
                      备注
                      <textarea value={warehouseForm.note} onChange={handleWarehouseChange('note')} rows="2" />
                    </label>

                    <div className="contract-item-actions">
                      <button className="primary-btn" type="submit">
                        {editingWarehouseId != null ? '保存修改' : '保存仓库'}
                      </button>
                      {editingWarehouseId != null && (
                        <button type="button" className="secondary-btn" onClick={resetWarehouseForm}>
                          取消编辑
                        </button>
                      )}
                    </div>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>仓库列表</h2>
                    <span className="status-badge">{warehouses.length} 个</span>
                  </div>

                  {warehouses.length === 0 ? (
                    <div className="empty-state">暂无仓库数据，请先在左侧新增仓库</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>编码</th>
                          <th>名称</th>
                          <th>货位</th>
                          <th>负责人</th>
                          <th>电话</th>
                          <th>状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {warehouses.map((row) => (
                          <tr key={row.id}>
                            <td>{row.code}</td>
                            <td>{row.name}</td>
                            <td>{row.location || '—'}</td>
                            <td>{row.manager || '—'}</td>
                            <td>{row.phone || '—'}</td>
                            <td>
                              <span className={`stock-tag ${row.is_active ? 'tag-on' : 'tag-off'}`}>
                                {row.is_active ? '启用' : '停用'}
                              </span>
                            </td>
                            <td>
                              <div className="contract-item-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() => startEditWarehouse(row)}
                                >
                                  编辑
                                </button>
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() =>
                                    setConfirmDelete({
                                      id: row.id,
                                      endpoint: `/warehouses/${row.id}`,
                                      label: `仓库 ${row.name}`,
                                      kind: 'warehouse',
                                    })
                                  }
                                >
                                  删除
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'products' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增产品</h2>
                    <span className="status-badge">价格与库存</span>
                  </div>

                  <form onSubmit={submitProduct} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        SKU
                        <input value={productForm.sku} onChange={handleProductChange('sku')} required />
                      </label>
                      <label>
                        产品名称
                        <input value={productForm.name} onChange={handleProductChange('name')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        类别
                        <input value={productForm.category} onChange={handleProductChange('category')} />
                      </label>
                      <label>
                        单位
                        <input value={productForm.unit} onChange={handleProductChange('unit')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        采购价
                        <input type="number" step="0.01" value={productForm.purchase_price} onChange={handleProductChange('purchase_price')} />
                      </label>
                      <label>
                        销售价
                        <input type="number" step="0.01" value={productForm.sale_price} onChange={handleProductChange('sale_price')} />
                      </label>
                    </div>

                    <button className="primary-btn" type="submit">保存产品</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>产品列表</h2>
                    <span className="status-badge">{products.length} 件</span>
                  </div>

                  {products.length === 0 ? (
                    <div className="empty-state">暂无产品数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>SKU</th>
                          <th>名称</th>
                          <th>类别</th>
                          <th>售价</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {products.map((row) => (
                          <tr key={row.id}>
                            <td>{row.sku}</td>
                            <td>{row.name}</td>
                            <td>{row.category || '—'}</td>
                            <td>¥{Number(row.sale_price || 0).toLocaleString()}</td>
                            <td>
                              <button
                                type="button"
                                className="danger-btn"
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
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'dataio' && (
              <div className="management-grid">
                <section className="panel table-panel" style={{ gridColumn: '1 / -1' }}>
                  <div className="section-header">
                    <h2>Excel 导入导出</h2>
                    <span className="status-badge">批量建账 / 数据迁移</span>
                  </div>
                  <p className="io-hint">
                    下载模板 → 填好数据 → 上传导入。上传后会先做一次<strong>预检</strong>（不写库），确认无误再点「确认导入」。
                    已存在的编码默认<strong>更新</strong>，不会重复新增；单行出错不影响其他行。
                  </p>

                  <div className="io-grid">
                    {excelKinds.map((item) => (
                      <div className="io-card" key={item.kind}>
                        <div className="io-card-head">
                          <h3>{item.label}</h3>
                          {item.key_fields.length > 0 && (
                            <span className="io-keys">按 {item.key_fields.join(' + ')} 识别</span>
                          )}
                        </div>
                        <div className="io-card-meta">
                          <span>{item.column_count} 列</span>
                          {item.required_fields.length > 0 && (
                            <span className="io-required">必填：{item.required_fields.join('、')}</span>
                          )}
                        </div>
                        <div className="io-card-actions">
                          <button
                            type="button"
                            className="secondary-btn small-btn"
                            disabled={excelBusy === `template-${item.kind}`}
                            onClick={() => downloadExcelTemplate(item.kind, item.label)}
                          >
                            下载模板
                          </button>
                          <label className="secondary-btn small-btn io-file-btn">
                            {excelBusy === `import-${item.kind}` ? '处理中…' : '选择文件导入'}
                            <input
                              type="file"
                              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                              hidden
                              onChange={handleExcelFilePicked(item.kind, item.label)}
                            />
                          </label>
                          <button
                            type="button"
                            className="secondary-btn small-btn"
                            disabled={excelBusy === `export-${item.kind}`}
                            onClick={() => exportExcelData(item.kind, item.label)}
                          >
                            导出数据
                          </button>
                        </div>
                      </div>
                    ))}
                    {excelKinds.length === 0 && <div className="empty-state">暂无可导入的数据类别</div>}
                  </div>
                </section>

                {excelPending && (
                  <section className="panel table-panel" style={{ gridColumn: '1 / -1' }}>
                    <div className="section-header">
                      <h2>导入预检 · {excelPending.label}</h2>
                      <span className="status-badge">未写入数据库</span>
                    </div>
                    <p className="io-hint">
                      文件：<strong>{excelPending.fileName}</strong> —— 下面是预检结果，确认后才会真正写入。
                    </p>
                    <div className="io-stats">
                      <span className="io-stat ok">新增 {excelPending.preview.created}</span>
                      <span className="io-stat warn">更新 {excelPending.preview.updated}</span>
                      <span className="io-stat muted">跳过 {excelPending.preview.skipped}</span>
                      <span className={`io-stat ${excelPending.preview.failed ? 'bad' : 'muted'}`}>
                        失败 {excelPending.preview.failed}
                      </span>
                    </div>
                    {excelPending.preview.errors.length > 0 && (
                      <div className="io-errors">
                        <h4>需要处理的行</h4>
                        <table className="data-table">
                          <thead>
                            <tr><th>行号</th><th>原因</th></tr>
                          </thead>
                          <tbody>
                            {excelPending.preview.errors.map((err, idx) => (
                              <tr key={`${err.row}-${idx}`}>
                                <td>第 {err.row} 行</td>
                                <td>{err.message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="io-actions">
                      <button type="button" className="secondary-btn" onClick={() => setExcelPending(null)}>取消</button>
                      <button
                        type="button"
                        className="primary-btn"
                        disabled={excelBusy === `import-${excelPending.kind}`}
                        onClick={confirmExcelImport}
                      >
                        {excelBusy === `import-${excelPending.kind}` ? '导入中…' : '确认导入'}
                      </button>
                    </div>
                  </section>
                )}

                {excelOutcome && (
                  <section className="panel table-panel" style={{ gridColumn: '1 / -1' }}>
                    <div className="section-header">
                      <h2>导入结果 · {excelOutcome.label}</h2>
                      <span className="status-badge">已写入</span>
                    </div>
                    <div className="io-stats">
                      <span className="io-stat ok">新增 {excelOutcome.result.created}</span>
                      <span className="io-stat warn">更新 {excelOutcome.result.updated}</span>
                      <span className="io-stat muted">跳过 {excelOutcome.result.skipped}</span>
                      <span className={`io-stat ${excelOutcome.result.failed ? 'bad' : 'muted'}`}>
                        失败 {excelOutcome.result.failed}
                      </span>
                    </div>
                    {excelOutcome.result.errors.length > 0 && (
                      <div className="io-errors">
                        <h4>未导入的行</h4>
                        <table className="data-table">
                          <thead>
                            <tr><th>行号</th><th>原因</th></tr>
                          </thead>
                          <tbody>
                            {excelOutcome.result.errors.map((err, idx) => (
                              <tr key={`${err.row}-${idx}`}>
                                <td>第 {err.row} 行</td>
                                <td>{err.message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="io-actions">
                      <button type="button" className="secondary-btn" onClick={() => setExcelOutcome(null)}>关闭</button>
                    </div>
                  </section>
                )}
              </div>
            )}

            {selectedTab === 'purchase-order' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增采购订单</h2>
                    <span className="status-badge">只订货 · 不动库存</span>
                  </div>

                  <form onSubmit={submitPurchaseOrderForm} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        供应商
                        <select value={purchaseOrderForm.supplier_id} onChange={handlePurchaseOrderFormChange('supplier_id')} required>
                          <option value="">请选择供应商</option>
                          {suppliers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('suppliers', purchaseOrderForm.supplier_id, '供应商')}
                      </label>
                      <label>
                        进货仓库（转单时生效）
                        <select value={purchaseOrderForm.warehouse_id} onChange={handlePurchaseOrderFormChange('warehouse_id')}>
                          <option value="">转单时再选</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        送货日期
                        <input type="date" value={purchaseOrderForm.delivery_date} onChange={handlePurchaseOrderFormChange('delivery_date')} />
                      </label>
                      <label>
                        付款方式
                        <input value={purchaseOrderForm.payment_method} onChange={handlePurchaseOrderFormChange('payment_method')} placeholder="如：银行转账 / 月结30天" />
                      </label>
                    </div>

                    <label>
                      备注
                      <input value={purchaseOrderForm.note} onChange={handlePurchaseOrderFormChange('note')} />
                    </label>

                    <div className="section-header">
                      <h3>商品明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addPurchaseOrderItem}>+ 添加一行</button>
                    </div>
                    {purchaseOrderForm.items.map((row, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={row.product_id} onChange={handlePurchaseOrderItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(row.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={row.quantity} onChange={handlePurchaseOrderItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" step="0.01" value={row.unit_price} onChange={handlePurchaseOrderItemChange(index, 'unit_price')} />
                        </label>
                      </div>
                    ))}
                    <div className="order-items-summary">
                      共 {purchaseOrderForm.items.filter((row) => row.product_id).length} 行 ·
                      合计 ¥{purchaseOrderForm.items
                        .reduce((sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>

                    <button className="primary-btn" type="submit">保存采购订单</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>采购订单列表</h2>
                    <span className="status-badge">{purchaseOrderList.length} 张</span>
                  </div>

                  {purchaseOrderList.length === 0 ? (
                    <div className="empty-state">暂无采购订单。订单只确认订货意向，转入库单后才登记库存与应付。</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>订单号</th>
                          <th>供应商</th>
                          <th>行数</th>
                          <th>金额</th>
                          <th>送货日期</th>
                          <th>状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {purchaseOrderList.map((row) => (
                          <tr key={row.id}>
                            <td>{row.order_no}</td>
                            <td>{suppliers.find((s) => s.id === row.supplier_id)?.name || row.supplier_id}</td>
                            <td>{row.items.length}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{row.delivery_date || '—'}</td>
                            <td><span className="status-badge">{DOC_STATUS_LABELS[row.status] || row.status}</span></td>
                            <td className="row-actions">
                              <button type="button" className="secondary-btn small-btn" onClick={() => printPdf(`/print/purchase-order/${row.id}`, `采购订单_${row.order_no}.pdf`)}>打印</button>{' '}
                              {row.status !== 'completed' && (
                                <>
                                  <button type="button" className="secondary-btn small-btn" onClick={() => convertPurchaseOrder(row)}>转入库单</button>{' '}
                                  <button
                                    type="button"
                                    className="danger-btn"
                                    onClick={() => setConfirmDelete({
                                      id: row.id,
                                      endpoint: `/purchase-orders/${row.id}`,
                                      label: `采购订单 ${row.order_no}`,
                                      kind: 'purchase-order',
                                    })}
                                  >
                                    删除
                                  </button>
                                </>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'purchase' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增采购入库单</h2>
                    <span className="status-badge">真实入库 · 写库存与应付</span>
                  </div>

                  <form onSubmit={submitInboundForm} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        供应商
                        <select value={inboundForm.supplier_id} onChange={handleInboundFormChange('supplier_id')} required>
                          <option value="">请选择供应商</option>
                          {suppliers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('suppliers', inboundForm.supplier_id, '供应商')}
                      </label>
                      <label>
                        入库仓库
                        <select value={inboundForm.warehouse_id} onChange={handleInboundFormChange('warehouse_id')} required>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        单据日期
                        <input type="date" value={inboundForm.order_date} onChange={handleInboundFormChange('order_date')} />
                      </label>
                      <label>
                        付款方式
                        <input value={inboundForm.payment_method} onChange={handleInboundFormChange('payment_method')} placeholder="如：银行转账 / 月结30天" />
                      </label>
                    </div>

                    <label>
                      备注
                      <input value={inboundForm.note} onChange={handleInboundFormChange('note')} placeholder="如：随货同行单号、验收情况" />
                    </label>

                    <div className="section-header">
                      <h3>商品明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addInboundItem}>+ 添加一行</button>
                    </div>
                    {inboundForm.items.map((row, index) => (
                      <div className="form-row four-col" key={index}>
                        <label>
                          商品
                          <select value={row.product_id} onChange={handleInboundItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(row.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={row.quantity} onChange={handleInboundItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" step="0.01" value={row.unit_price} onChange={handleInboundItemChange(index, 'unit_price')} />
                        </label>
                        <button
                          type="button"
                          className="danger-btn small-btn row-remove-btn"
                          onClick={() => removeInboundItem(index)}
                          disabled={inboundForm.items.length <= 1}
                          title={inboundForm.items.length <= 1 ? '至少保留一行' : '删除此行'}
                        >
                          删行
                        </button>
                      </div>
                    ))}
                    <div className="order-items-summary">
                      共 {inboundForm.items.filter((row) => row.product_id).length} 行 ·
                      合计 ¥{inboundForm.items
                        .reduce((sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>

                    <button className="primary-btn" type="submit">保存并入库</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>采购入库单列表</h2>
                    <span className="status-badge">{purchaseOrders.length} 张</span>
                  </div>

                  {purchaseOrders.length === 0 ? (
                    <div className="empty-state">
                      暂无入库单。这里登记的是真实入库（库存 + 应付），与「采购订单」的订货意向分开管理。
                    </div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>入库单号</th>
                            <th>供应商</th>
                            <th>仓库</th>
                            <th>行数</th>
                            <th>金额</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {purchaseOrders.map((row) => (
                            <tr key={row.id}>
                              <td>{row.order_no}</td>
                              <td>{suppliers.find((s) => s.id === row.supplier_id)?.name || row.supplier_id}</td>
                              <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                              <td>{row.items?.length ?? 0}</td>
                              <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.order_date || row.delivery_date || '—'}</td>
                              <td><span className="status-badge">{DOC_STATUS_LABELS[row.status] || row.status}</span></td>
                              <td className="row-actions">
                                <button type="button" className="secondary-btn small-btn" onClick={() => printPdf(`/print/purchase-inbound/${row.id}`, `入库单_${row.order_no}.pdf`)}>打印</button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/purchase-orders/${row.id}`,
                                    label: `采购入库单 ${row.order_no}`,
                                    kind: 'purchase-inbound',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'sales-order' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增销售订单</h2>
                    <span className="status-badge">只订货 · 不动库存</span>
                  </div>

                  <form onSubmit={submitSalesOrderForm} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户
                        <select value={salesOrderForm.customer_id} onChange={handleSalesOrderFormChange('customer_id')} required>
                          <option value="">请选择客户</option>
                          {customers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('customers', salesOrderForm.customer_id, '客户')}
                      </label>
                      <label>
                        出货仓库（转单时生效）
                        <select value={salesOrderForm.warehouse_id} onChange={handleSalesOrderFormChange('warehouse_id')}>
                          <option value="">转单时再选</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        送货日期
                        <input type="date" value={salesOrderForm.delivery_date} onChange={handleSalesOrderFormChange('delivery_date')} />
                      </label>
                      <label>
                        付款方式
                        <input value={salesOrderForm.payment_method} onChange={handleSalesOrderFormChange('payment_method')} placeholder="如：银行转账 / 月结30天" />
                      </label>
                    </div>

                    <label>
                      备注
                      <input value={salesOrderForm.note} onChange={handleSalesOrderFormChange('note')} />
                    </label>

                    <div className="section-header">
                      <h3>商品明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addSalesOrderItem}>+ 添加一行</button>
                    </div>
                    {salesOrderForm.items.map((row, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={row.product_id} onChange={handleSalesOrderItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(row.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={row.quantity} onChange={handleSalesOrderItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" step="0.01" value={row.unit_price} onChange={handleSalesOrderItemChange(index, 'unit_price')} />
                        </label>
                      </div>
                    ))}
                    <div className="order-items-summary">
                      共 {salesOrderForm.items.filter((row) => row.product_id).length} 行 ·
                      合计 ¥{salesOrderForm.items
                        .reduce((sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>

                    <button className="primary-btn" type="submit">保存销售订单</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>销售订单列表</h2>
                    <span className="status-badge">{salesOrderList.length} 张</span>
                  </div>

                  {salesOrderList.length === 0 ? (
                    <div className="empty-state">暂无销售订单。订单只确认订货意向，转开单后才扣库存、记应收。</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>订单号</th>
                          <th>客户</th>
                          <th>行数</th>
                          <th>金额</th>
                          <th>送货日期</th>
                          <th>状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {salesOrderList.map((row) => (
                          <tr key={row.id}>
                            <td>{row.order_no}</td>
                            <td>{customers.find((c) => c.id === row.customer_id)?.name || row.customer_id}</td>
                            <td>{row.items.length}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{row.delivery_date || '—'}</td>
                            <td><span className="status-badge">{DOC_STATUS_LABELS[row.status] || row.status}</span></td>
                            <td className="row-actions">
                              <button type="button" className="secondary-btn small-btn" onClick={() => printPdf(`/print/sales-order/${row.id}`, `销售订单_${row.order_no}.pdf`)}>打印</button>{' '}
                              {row.status !== 'completed' && (
                                <>
                                  <button type="button" className="secondary-btn small-btn" onClick={() => convertSalesOrder(row)}>转开单</button>{' '}
                                  <button
                                    type="button"
                                    className="danger-btn"
                                    onClick={() => setConfirmDelete({
                                      id: row.id,
                                      endpoint: `/sales-orders/${row.id}`,
                                      label: `销售订单 ${row.order_no}`,
                                      kind: 'sales-order',
                                    })}
                                  >
                                    删除
                                  </button>
                                </>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'sales' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增销售出库单</h2>
                    <span className="status-badge">真实出库 · 写库存与应收</span>
                  </div>

                  <form onSubmit={submitOutboundForm} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户
                        <select value={outboundForm.customer_id} onChange={handleOutboundFormChange('customer_id')} required>
                          <option value="">请选择客户</option>
                          {customers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('customers', outboundForm.customer_id, '客户')}
                      </label>
                      <label>
                        出库仓库
                        <select value={outboundForm.warehouse_id} onChange={handleOutboundFormChange('warehouse_id')} required>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        单据日期
                        <input type="date" value={outboundForm.order_date} onChange={handleOutboundFormChange('order_date')} />
                      </label>
                      <label>
                        收款方式
                        <input value={outboundForm.payment_method} onChange={handleOutboundFormChange('payment_method')} placeholder="如：现金 / 微信 / 月结30天" />
                      </label>
                    </div>

                    <label>
                      备注
                      <input value={outboundForm.note} onChange={handleOutboundFormChange('note')} placeholder="如：送货地址、客户要求" />
                    </label>

                    <div className="section-header">
                      <h3>商品明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addOutboundItem}>+ 添加一行</button>
                    </div>
                    {outboundForm.items.map((row, index) => (
                      <div className="form-row four-col" key={index}>
                        <label>
                          商品
                          <select value={row.product_id} onChange={handleOutboundItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(row.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={row.quantity} onChange={handleOutboundItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" step="0.01" value={row.unit_price} onChange={handleOutboundItemChange(index, 'unit_price')} />
                        </label>
                        <button
                          type="button"
                          className="danger-btn small-btn row-remove-btn"
                          onClick={() => removeOutboundItem(index)}
                          disabled={outboundForm.items.length <= 1}
                          title={outboundForm.items.length <= 1 ? '至少保留一行' : '删除此行'}
                        >
                          删行
                        </button>
                      </div>
                    ))}
                    <div className="order-items-summary">
                      共 {outboundForm.items.filter((row) => row.product_id).length} 行 ·
                      合计 ¥{outboundForm.items
                        .reduce((sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>

                    <button className="primary-btn" type="submit">保存并出库</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>销售出库单列表</h2>
                    <span className="status-badge">{salesOrders.length} 张</span>
                  </div>

                  {salesOrders.length === 0 ? (
                    <div className="empty-state">
                      暂无出库单。这里登记的是真实出库（库存 + 应收），与「销售订单」的订货意向分开管理。
                    </div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>出库单号</th>
                          <th>客户</th>
                          <th>仓库</th>
                          <th>状态</th>
                          <th>金额</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {salesOrders.map((row) => (
                          <tr
                            key={row.id}
                            onClick={() => setSelectedSalesOrder(row)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setSelectedSalesOrder(row);
                              }
                            }}
                            tabIndex={0}
                            style={{ cursor: 'pointer' }}
                          >
                            <td>{row.order_no}</td>
                            <td>{customers.find((c) => c.id === row.customer_id)?.name || row.customer_id}</td>
                            <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                            <td><span className="status-badge">{DOC_STATUS_LABELS[row.status] || row.status}</span></td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/sales-order/${row.id}`, `${row.order_no}.pdf`);
                                }}
                              >
                                打印
                              </button>{' '}
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/delivery-note/${row.id}`, `送货单_${row.order_no}.pdf`);
                                }}
                              >
                                送货单
                              </button>{' '}
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/sales-orders/${row.id}`,
                                    label: `销售出库单 ${row.order_no}`,
                                    kind: 'sales-order',
                                  });
                                }}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      </table>
                    </div>
                  )}
                </section>

                {selectedSalesOrder && (
                  <div className="modal-overlay" onClick={() => setSelectedSalesOrder(null)}>
                    <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                      <div className="modal-header">
                        <h3>销售订单详情</h3>
                        <button type="button" className="secondary-btn small-btn" onClick={() => setSelectedSalesOrder(null)}>关闭</button>
                      </div>

                      <div className="modal-body">
                        <p><strong>单号：</strong> {selectedSalesOrder.order_no}</p>
                        <p><strong>客户：</strong> {selectedSalesOrder.customer_id}</p>
                        <p><strong>状态：</strong> {selectedSalesOrder.status}</p>
                        <p><strong>金额：</strong> ¥{Number(selectedSalesOrder.total_amount || 0).toLocaleString()}</p>
                      </div>

                      <div className="modal-actions">
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={async () => {
                            const success = await updateSalesOrderStatus(selectedSalesOrder.id, 'completed');
                            if (success) {
                              setSelectedSalesOrder(null);
                            }
                          }}
                        >
                          标记为已完结
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {selectedTab === 'production' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增生产单</h2>
                    <span className="status-badge">车间计划</span>
                  </div>

                  <form onSubmit={submitProductionOrder} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        生产单号
                        <input value={productionForm.order_no} onChange={handleProductionChange('order_no')} required />
                      </label>
                      <label>
                        产品 ID
                        <input type="number" value={productionForm.product_id} onChange={handleProductionChange('product_id')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        数量
                        <input type="number" min="1" value={productionForm.quantity} onChange={handleProductionChange('quantity')} required />
                      </label>
                      <label>
                        优先级
                        <select value={productionForm.priority} onChange={handleProductionChange('priority')}>
                          <option value="low">低</option>
                          <option value="normal">正常</option>
                          <option value="high">高</option>
                        </select>
                      </label>
                    </div>

                    <label>
                      状态
                      <select value={productionForm.status} onChange={handleProductionChange('status')}>
                        <option value="planned">计划中</option>
                        <option value="in_progress">生产中</option>
                        <option value="completed">已完成</option>
                      </select>
                    </label>

                    <label>
                      备注
                      <textarea value={productionForm.note} onChange={handleProductionChange('note')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存生产单</button>
                  </form>
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>生产流程状态</h2>
                    <span className="status-badge">{operationsBoard.production_flow.length} 条流程</span>
                  </div>

                  {operationsBoard.production_flow.length === 0 ? (
                    <div className="empty-state">暂无生产流程状态</div>
                  ) : (
                    <div className="flow-list">
                      {operationsBoard.production_flow.map((flow) => (
                        <div key={flow.order_no} className="flow-card">
                          <div className="flow-header">
                            <strong>{flow.order_no}</strong>
                            <span className="status-badge">{flow.status}</span>
                          </div>
                          <div className="flow-steps">
                            {flow.steps.map((step, index) => (
                              <div key={`${flow.order_no}-${step.name}-${index}`} className={`flow-step ${step.status}`}>
                                <span>{index + 1}</span>
                                <small>{step.name}</small>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>工单 / 排程 / 产线看板</h2>
                    <span className="status-badge">{operationsBoard.work_orders.length} 个工单</span>
                  </div>

                  <div className="operations-grid">
                    <div className="mini-panel">
                      <h3>工单执行</h3>
                      {(operationsBoard.work_orders || []).length === 0 ? (
                        <div className="empty-state">暂无工单</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.work_orders.map((workOrder) => (
                            <li key={workOrder.id}>
                              <div>
                                <strong>{workOrder.order_no}</strong>
                                <small>{workOrder.line_name} · {workOrder.product_id}</small>
                              </div>
                              <span>{workOrder.status}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>排程</h3>
                      {(operationsBoard.production_schedule || []).length === 0 ? (
                        <div className="empty-state">暂无排程</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.production_schedule.map((item, index) => (
                            <li key={`${item.order_no}-${index}`}>
                              <div>
                                <strong>{item.order_no}</strong>
                                <small>{item.line_name} · {item.date}</small>
                              </div>
                              <span>{item.status}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>BOM 缺料预警</h3>
                      {(operationsBoard.bom_alerts || []).length === 0 ? (
                        <div className="empty-state">暂无预警</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.bom_alerts.map((alert, index) => (
                            <li key={`${alert.product_id}-${alert.component_id}-${index}`}>
                              <div>
                                <strong>{alert.message}</strong>
                                <small>组件 {alert.component_id} · 用量 {alert.quantity}</small>
                              </div>
                              <span>{alert.level}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>自动排程</h3>
                      {(operationsBoard.auto_schedule || []).length === 0 ? (
                        <div className="empty-state">暂无排程结果</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.auto_schedule.map((item, index) => (
                            <li key={`${item.order_no}-${index}`}>
                              <div>
                                <strong>{item.order_no}</strong>
                                <small>{item.line_name} · {item.start_date}</small>
                              </div>
                              <span>{item.load_rate}%</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>工单报工</h3>
                      <div className="report-pill-row">
                        <div className="report-pill">
                          <span>已完成</span>
                          <strong>{operationsBoard.work_report_summary?.completed_today ?? 0}</strong>
                        </div>
                        <div className="report-pill">
                          <span>进度</span>
                          <strong>{operationsBoard.work_report_summary?.progress_rate ?? 0}%</strong>
                        </div>
                        <div className="report-pill">
                          <span>OEE</span>
                          <strong>{operationsBoard.work_report_summary?.oee ?? 0}%</strong>
                        </div>
                      </div>
                    </div>

                    <div className="mini-panel">
                      <h3>产线看板</h3>
                      {(operationsBoard.line_board || []).length === 0 ? (
                        <div className="empty-state">暂无产线数据</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.line_board.map((line) => (
                            <li key={line.line_name}>
                              <div>
                                <strong>{line.line_name}</strong>
                                <small>产量 {line.output} · 利用率 {line.utilization}%</small>
                              </div>
                              <span>{line.status}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>库存预警</h3>
                      {(operationsBoard.inventory_alerts || []).length === 0 ? (
                        <div className="empty-state">库存正常</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.inventory_alerts.map((alert) => (
                            <li key={`${alert.product_id}-${alert.warehouse_id}`}>
                              <div>
                                <strong>{alert.product_name}</strong>
                                <small>仓库 {alert.warehouse_id} · 可用 {alert.available_quantity}</small>
                              </div>
                              <span>{alert.status === 'low_stock' ? '低库存' : '关注'}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="mini-panel">
                      <h3>采购补货建议</h3>
                      {(operationsBoard.purchase_recommendations || []).length === 0 ? (
                        <div className="empty-state">暂无补货建议</div>
                      ) : (
                        <ul className="mini-list">
                          {operationsBoard.purchase_recommendations.map((item, index) => (
                            <li key={`${item.product_id}-${index}`}>
                              <div>
                                <strong>{item.product_name}</strong>
                                <small>{item.reason}</small>
                              </div>
                              <span>{item.priority === 'high' ? '重点' : '建议'} {item.recommended_quantity}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>BOM 关联建议</h2>
                    <span className="status-badge">{operationsBoard.bom_summary.total_items} 个 BOM</span>
                  </div>

                  <div className="recommendation-list">
                    {(operationsBoard.recommendations || []).map((recommendation) => (
                      <button
                        key={recommendation.title}
                        type="button"
                        className={`recommendation-item ${selectedRecommendation === recommendation.title ? 'selected' : ''}`}
                        onClick={() => setSelectedRecommendation(recommendation.title)}
                      >
                        <div className="recommendation-topline">
                          <strong>{recommendation.title}</strong>
                          <span className={`priority-tag ${recommendation.priority}`}>{recommendation.priority}</span>
                        </div>
                        <small>{recommendation.description}</small>
                      </button>
                    ))}
                  </div>

                  <div className="selected-recommendation-box">
                    {selectedRecommendation
                      ? `已选择：${selectedRecommendation}`
                      : '请选择一条建议，作为当前生产决策参考。'}
                  </div>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>生产计划列表</h2>
                    <span className="status-badge">{productionOrders.length} 张</span>
                  </div>

                  {productionOrders.length === 0 ? (
                    <div className="empty-state">暂无生产计划</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>单号</th>
                          <th>产品</th>
                          <th>数量</th>
                          <th>状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {productionOrders.slice(0, 8).map((row) => (
                          <tr key={row.id}>
                            <td>{row.order_no}</td>
                            <td>{row.product_id}</td>
                            <td>{row.quantity}</td>
                            <td>{row.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {productionOrders.length > 8 && (
                    <div className="table-hint">共 {productionOrders.length} 条，仅显示最近 8 条</div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'projects' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增项目</h2>
                    <span className="status-badge">阶段管理</span>
                  </div>

                  <form onSubmit={submitProject} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        项目编码
                        <input value={projectForm.code} onChange={handleProjectChange('code')} required />
                      </label>
                      <label>
                        项目名称
                        <input value={projectForm.name} onChange={handleProjectChange('name')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        负责人
                        <input value={projectForm.manager} onChange={handleProjectChange('manager')} />
                      </label>
                      <label>
                        状态
                        <select value={projectForm.status} onChange={handleProjectChange('status')}>
                          <option value="planned">计划中</option>
                          <option value="in_progress">进行中</option>
                          <option value="delayed">延期</option>
                          <option value="completed">已完成</option>
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        进度 %
                        <input type="number" min="0" max="100" value={projectForm.progress} onChange={handleProjectChange('progress')} />
                      </label>
                      <label>
                        预算
                        <input type="number" step="0.01" value={projectForm.budget} onChange={handleProjectChange('budget')} />
                      </label>
                    </div>

                    <label>
                      截止日期
                      <input type="date" value={projectForm.deadline} onChange={handleProjectChange('deadline')} />
                    </label>

                    <label>
                      备注
                      <textarea value={projectForm.note} onChange={handleProjectChange('note')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存项目</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>项目列表</h2>
                    <span className="status-badge">{projects.length} 个</span>
                  </div>

                  {projects.length === 0 ? (
                    <div className="empty-state">暂无项目数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>编码</th>
                          <th>名称</th>
                          <th>负责人</th>
                          <th>进度</th>
                        </tr>
                      </thead>
                      <tbody>
                        {projects.slice(0, 8).map((row) => (
                          <tr key={row.id}>
                            <td>{row.code}</td>
                            <td>{row.name}</td>
                            <td>{row.manager || '—'}</td>
                            <td>{row.progress}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {projects.length > 8 && (
                    <div className="table-hint">共 {projects.length} 条，仅显示最近 8 条</div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'reports' && (
              <div className="report-center">
                {/* 左：报表目录（后端 /reports/catalog 下发，前端不写死） */}
                <aside className="report-nav">
                  <div className="report-nav-head">
                    <h2>报表中心</h2>
                    <span className="status-badge">{reportCatalog.total || 0} 张</span>
                  </div>
                  {(reportCatalog.groups || []).map((group) => (
                    <div className="report-nav-group" key={group.group}>
                      <div className="report-nav-title">{group.group}</div>
                      {(group.reports || []).map((item) => (
                        <button
                          type="button"
                          key={item.key}
                          className={`report-nav-item ${reportKey === item.key ? 'active' : ''}`}
                          onClick={() => selectReport(item.key)}
                          title={item.desc}
                        >
                          <span>{item.name}</span>
                          <em>{REPORT_SHAPE_LABEL[item.shape] || item.shape}</em>
                        </button>
                      ))}
                    </div>
                  ))}
                </aside>

                {/* 右：报表本体（四种形态共用一个渲染入口） */}
                <section className="panel report-body">
                  <div className="section-header report-header">
                    <div>
                      <h2>{reportResult?.report?.name || '报表'}</h2>
                      <p className="table-hint">{reportResult?.report?.desc || '从左侧目录选择一张报表。'}</p>
                    </div>
                    <div className="report-toolbar">
                      <label className="report-field">
                        起
                        <input type="date" value={reportQuery.date_from} onChange={handleReportQueryChange('date_from')} />
                      </label>
                      <label className="report-field">
                        止
                        <input type="date" value={reportQuery.date_to} onChange={handleReportQueryChange('date_to')} />
                      </label>

                      {reportResult?.shape === 'crosstab' && (
                        <>
                          <select
                            className="report-select"
                            value={reportQuery.period || reportResult?.report?.period || ''}
                            onChange={handleReportQueryChange('period')}
                          >
                            {Object.entries(reportCatalog.periods || {}).map(([key, label]) => (
                              <option key={key} value={key}>{label}</option>
                            ))}
                          </select>
                          <select
                            className="report-select"
                            value={reportQuery.dimension || reportResult?.report?.dimension || ''}
                            onChange={handleReportQueryChange('dimension')}
                          >
                            {Object.entries(reportCatalog.dimensions || {}).map(([key, label]) => (
                              <option key={key} value={key}>按{label}</option>
                            ))}
                          </select>
                        </>
                      )}

                      <input
                        className="report-search"
                        placeholder="筛选名称 / 商品"
                        value={reportQuery.keyword}
                        onChange={handleReportQueryChange('keyword')}
                      />
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        onClick={() => refreshReportData()}
                        disabled={reportBusy}
                      >
                        {reportBusy ? '取数中…' : '查询'}
                      </button>
                      <button type="button" className="secondary-btn small-btn" onClick={exportReport}>导出 CSV</button>
                    </div>
                  </div>

                  <div className="report-range-hint">
                    数据区间：{reportResult?.range?.date_from || '—'} ~ {reportResult?.range?.date_to || '—'}
                    {reportResult?.report?.dimension ? ` · 按${reportCatalog.dimensions?.[reportResult.report.dimension] || ''}` : ''}
                    {reportResult?.report?.period ? ` · ${reportCatalog.periods?.[reportResult.report.period] || ''}粒度` : ''}
                  </div>

                  {renderReportBody()}

                  {reportResult?.notes?.length ? (
                    <ul className="report-notes">
                      {reportResult.notes.map((note) => <li key={note}>{note}</li>)}
                    </ul>
                  ) : null}
                </section>
              </div>
            )}

            {selectedTab === 'analysis' && (
              <div className="report-grid">
                <section className="panel">
                  <div className="section-header">
                    <h2>财务分析窗口</h2>
                    <span className="status-badge">实时汇总</span>
                  </div>

                  <div className="report-summary-grid">
                    <div className="metric-card">
                      <span>收入合计</span>
                      <strong>¥{Number(financeAnalysis.total_revenue || 0).toLocaleString()}</strong>
                    </div>
                    <div className="metric-card">
                      <span>支出合计</span>
                      <strong>¥{Number(financeAnalysis.total_expense || 0).toLocaleString()}</strong>
                    </div>
                    <div className="metric-card">
                      <span>净利润</span>
                      <strong>¥{Number(financeAnalysis.net_profit || 0).toLocaleString()}</strong>
                    </div>
                    <div className="metric-card">
                      <span>发票条数</span>
                      <strong>{invoiceSummary.count}</strong>
                    </div>
                  </div>
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>按客户收入分析</h2>
                    <span className="status-badge">Top客户</span>
                  </div>

                  <div className="analysis-filter-row">
                    <label>
                      <span>开始日期</span>
                      <input type="date" value={analysisRange.startDate} onChange={handleAnalysisRangeChange('startDate')} />
                    </label>
                    <label>
                      <span>结束日期</span>
                      <input type="date" value={analysisRange.endDate} onChange={handleAnalysisRangeChange('endDate')} />
                    </label>
                  </div>

                  {financeAnalysis.by_customer && financeAnalysis.by_customer.length > 0 ? (
                    <>
                      <div className="chart-bars">
                        {(() => {
                          const maxValue = Math.max(...financeAnalysis.by_customer.map((item) => Number(item.total || 0)), 1);
                          return financeAnalysis.by_customer.slice(0, 6).map((item) => (
                            <div className="chart-row" key={item.customer_id || item.customer_name}>
                              <span>{item.customer_name}</span>
                              <div className="chart-track">
                                <div className="chart-fill" style={{ width: `${((Number(item.total || 0) / maxValue) * 100)}%` }} />
                              </div>
                              <strong>¥{Number(item.total || 0).toLocaleString()}</strong>
                            </div>
                          ));
                        })()}
                      </div>

                      <div className="customer-rank-list">
                        {financeAnalysis.by_customer.slice(0, 5).map((item, index) => (
                          <div className="rank-item" key={`${item.customer_name}-${index}`}>
                            <span className="rank-badge">#{index + 1}</span>
                            <div>
                              <strong>{item.customer_name}</strong>
                              <small>贡献收入</small>
                            </div>
                            <div className="invoice-amount">¥{Number(item.total || 0).toLocaleString()}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="empty-state">暂无客户收入数据</div>
                  )}
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>发票汇总</h2>
                    <span className="status-badge">OCR 识别 · 财务关联 · 智能分析</span>
                  </div>

                  <label className="upload-box">
                    <input type="file" multiple accept=".png,.jpg,.jpeg,.pdf" onChange={handleInvoiceUpload} />
                    <span>批量选择本地发票文件（支持 PDF / 图片 / OCR 识别 / 二维码解析）</span>
                  </label>

                  <div className="invoice-action-row">
                    <button type="button" className="primary-btn small-btn" onClick={handleDeepSeekInvoiceAnalysis}>智能分类分析</button>
                    <button type="button" className="primary-btn small-btn" onClick={handleInvoiceAgentAnalysis}>智能体分析</button>
                    <button type="button" className="primary-btn small-btn" onClick={handleSyncInvoicesToFinance}>同步到财务</button>
                    <button type="button" className="secondary-btn" onClick={exportInvoiceReportXlsx}>导出报表</button>
                    <button type="button" className="secondary-btn" onClick={exportInvoiceReportHtml}>导出美观表格</button>
                  </div>

                  {invoiceItems.length > 0 ? (
                    <>
                      <div className="invoice-chart-grid">
                        <div className="chart-card">
                          <div className="chart-card-title">发票类别对比</div>
                          {(() => {
                            const total = Math.max(Number(invoiceAggregate.total_amount || 0), 1);
                            const spec = Number((invoiceAggregate.by_type || []).find((t) => t.type === '专票')?.amount || 0);
                            const gen = Number((invoiceAggregate.by_type || []).find((t) => t.type === '普票')?.amount || 0);
                            const other = Math.max(total - spec - gen, 0);
                            const specPct = (spec / total) * 100;
                            const genPct = (gen / total) * 100;
                            return (
                              <div className="donut-wrap">
                                <div className="donut" style={{ background: `conic-gradient(#6366f1 0 ${specPct}%, #22c55e ${specPct}% ${specPct + genPct}%, #94a3b8 ${specPct + genPct}% 100%)` }}>
                                  <div className="donut-hole" />
                                </div>
                                <div className="donut-legend">
                                  <div><i className="legend-dot" style={{ background: '#6366f1' }} />专票 ¥{spec.toLocaleString()}（{specPct.toFixed(1)}%）</div>
                                  <div><i className="legend-dot" style={{ background: '#22c55e' }} />普票 ¥{gen.toLocaleString()}（{genPct.toFixed(1)}%）</div>
                                  {other > 0 && <div><i className="legend-dot" style={{ background: '#94a3b8' }} />其他 ¥{other.toLocaleString()}</div>}
                                </div>
                              </div>
                            );
                          })()}
                        </div>

                        <div className="chart-card">
                          <div className="chart-card-title">专票抵扣情况</div>
                          <div className="deduct-legend">
                            <div className="deduct-line">
                              <i className="legend-dot" style={{ background: '#16a34a' }} />
                              已抵扣 {invoiceAggregate.deduction.deducted_count} 张 ¥{Number(invoiceAggregate.deduction.deducted_amount || 0).toLocaleString()}
                            </div>
                            <div className="deduct-line red-text">
                              <i className="legend-dot" style={{ background: '#dc2626' }} />
                              未抵扣 {invoiceAggregate.deduction.undeducted_count} 张 ¥{Number(invoiceAggregate.deduction.undeducted_amount || 0).toLocaleString()}
                            </div>
                          </div>
                        </div>

                        <div className="chart-card">
                          <div className="chart-card-title">普票月度金额对比（元）</div>
                          {(() => {
                            const months = Object.keys(invoiceAggregate.monthly || {}).slice(-12);
                            const values = months.map((m) => Number(invoiceAggregate.monthly[m]?.['普票']?.amount || 0));
                            const max = Math.max(...values, 1);
                            return (
                              <div className="mini-bars">
                                {months.map((m, i) => (
                                  <div className="mini-bar-col" key={m} title={`${m}：¥${values[i].toLocaleString()}`}>
                                    <div className="mini-bar-fill bar-green" style={{ height: `${Math.max((values[i] / max) * 100, values[i] > 0 ? 6 : 2)}%` }} />
                                    <span>{m.slice(5)}月</span>
                                  </div>
                                ))}
                              </div>
                            );
                          })()}
                        </div>

                        <div className="chart-card">
                          <div className="chart-card-title">专票月度金额对比（元）</div>
                          {(() => {
                            const months = Object.keys(invoiceAggregate.monthly || {}).slice(-12);
                            const values = months.map((m) => Number(invoiceAggregate.monthly[m]?.['专票']?.amount || 0));
                            const max = Math.max(...values, 1);
                            return (
                              <div className="mini-bars">
                                {months.map((m, i) => (
                                  <div className="mini-bar-col" key={m} title={`${m}：¥${values[i].toLocaleString()}`}>
                                    <div className="mini-bar-fill bar-indigo" style={{ height: `${Math.max((values[i] / max) * 100, values[i] > 0 ? 6 : 2)}%` }} />
                                    <span>{m.slice(5)}月</span>
                                  </div>
                                ))}
                              </div>
                            );
                          })()}
                        </div>
                      </div>

                      {invoiceAgentReport && (
                        <div className="agent-report-box">
                          <div className="agent-report-header">
                            <strong>智能体分析报告</strong>
                            <span className="status-badge">{invoiceAgentReport.provider === 'deepseek' ? 'DeepSeek 智能体' : '本地规则分析'}</span>
                          </div>
                          <pre>{invoiceAgentReport.analysis}</pre>
                        </div>
                      )}

                      <div className="invoice-summary-row">
                        <div className="metric-card">
                          <span>发票总额</span>
                          <strong>¥{Number(invoiceAggregate.total_amount || 0).toLocaleString()}</strong>
                        </div>
                        <div className="metric-card">
                          <span>发票数量</span>
                          <strong>{invoiceAggregate.total_count}</strong>
                        </div>
                        <div className="metric-card">
                          <span>税额合计</span>
                          <strong>¥{Number(invoiceAggregate.total_tax || 0).toLocaleString()}</strong>
                        </div>
                        <div className="metric-card">
                          <span>未抵扣专票</span>
                          <strong className="red-text">¥{Number(invoiceAggregate.deduction.undeducted_amount || 0).toLocaleString()}</strong>
                        </div>
                      </div>

                      {selectedInvoiceIds.length > 0 && (
                        <div className="batch-delete-bar">
                          <span>已勾选 {selectedInvoiceIds.length} 张发票</span>
                          <button
                            type="button"
                            className="danger-btn"
                            onClick={() =>
                              setConfirmDelete({
                                ids: selectedInvoiceIds,
                                endpoint: '/invoices/batch',
                                label: `已勾选的 ${selectedInvoiceIds.length} 张发票`,
                                kind: 'invoice-batch',
                              })
                            }
                          >
                            批量删除
                          </button>
                          <button type="button" className="link-btn" onClick={() => setSelectedInvoiceIds([])}>取消勾选</button>
                        </div>
                      )}

                      <div className="invoice-table-wrap">
                        <table className="invoice-summary-table">
                          <thead>
                            <tr>
                              <th className="select-col">
                                <input
                                  type="checkbox"
                                  checked={invoiceItems.length > 0 && selectedInvoiceIds.length === invoiceItems.slice(0, 8).length}
                                  onChange={toggleSelectAllInvoices}
                                  aria-label="全选发票"
                                />
                              </th>
                              <th>月份</th><th>税价合计</th>
                              <th>序号</th><th>开票日期</th><th>发票号码</th><th>销售方名称</th><th>购买方名称</th><th>发票代码</th>
                              <th>发票类型</th><th>税价合计</th><th>税率</th><th>不含税额</th><th>税额</th><th>已抵扣</th><th>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(() => {
                              const groups = new Map();
                              invoiceItems.slice(0, 8).forEach((item) => {
                                const month = String(item.date || '—').slice(0, 7);
                                if (!groups.has(month)) groups.set(month, []);
                                groups.get(month).push(item);
                              });
                              const months = Array.from(groups.keys()).sort();
                              const rows = [];
                              let serial = 0;
                              months.forEach((month) => {
                                const list = groups.get(month);
                                const monthTotal = list.reduce((sum, r) => sum + Number(r.amount || 0), 0);
                                rows.push(
                                  <tr key={`month-${month}`} className="invoice-month-row">
                                    <td />
                                    <td>{formatMonth(month)}</td>
                                    <td>¥{monthTotal.toLocaleString()}</td>
                                    <td colSpan={13} />
                                  </tr>
                                );
                                list.forEach((item) => {
                                  serial += 1;
                                  const undeducted = item.invoice_type === '专票' && !item.deducted;
                                  rows.push(
                                    <tr key={`inv-${item.id || item.invoice_no}`} className={undeducted ? 'invoice-red-row' : ''}>
                                      <td>
                                        <input
                                          type="checkbox"
                                          checked={selectedInvoiceIds.includes(item.id)}
                                          onChange={() => toggleInvoiceSelect(item.id)}
                                          aria-label={`勾选发票 ${item.invoice_no}`}
                                        />
                                      </td>
                                      <td colSpan={2} />
                                      <td>{serial}</td>
                                      <td>{item.date}</td>
                                      <td>{item.invoice_no}</td>
                                      <td>{item.seller_name || '—'}</td>
                                      <td>{item.buyer_name || '—'}</td>
                                      <td>{item.invoice_code || '—'}</td>
                                      <td>{item.invoice_type || '未知'}</td>
                                      <td>¥{Number(item.amount || 0).toLocaleString()}</td>
                                      <td>{item.tax_rate != null ? `${item.tax_rate}%` : '—'}</td>
                                      <td>¥{Number(item.excl_tax_amount || 0).toLocaleString()}</td>
                                      <td>¥{Number(item.tax_amount || 0).toLocaleString()}</td>
                                      <td>
                                        {item.invoice_type === '专票' ? (
                                          <label className="deduct-check">
                                            <input type="checkbox" checked={Boolean(item.deducted)} onChange={() => handleToggleDeducted(item)} />
                                            已抵扣
                                          </label>
                                        ) : '—'}
                                      </td>
                                      <td>
                                        <button type="button" className="link-btn" onClick={() => setInvoiceDetail(item)}>查看</button>
                                        <button
                                          type="button"
                                          className="danger-btn"
                                          onClick={() =>
                                            setConfirmDelete({
                                              id: item.id,
                                              endpoint: `/invoices/${item.id}`,
                                              label: `发票 ${item.invoice_no || item.id}`,
                                              kind: 'invoice',
                                            })
                                          }
                                        >
                                          删除
                                        </button>
                                      </td>
                                    </tr>
                                  );
                                });
                              });
                              return rows;
                            })()}
                          </tbody>
                          <tfoot>
                            <tr>
                              <td />
                              <td>合计</td>
                              <td>¥{Number(invoiceAggregate.total_amount || 0).toLocaleString()}</td>
                              <td colSpan={13} />
                            </tr>
                          </tfoot>
                        </table>
                      </div>

                      {invoiceItems.length > 8 && (
                        <div className="table-hint">共 {invoiceItems.length} 张发票，仅显示最近 8 张（勾选条目后点「导出报表」可生成 Excel）</div>
                      )}

                      {invoiceDetail && (
                        <div className="modal-backdrop" onClick={() => setInvoiceDetail(null)}>
                          <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                            <div className="modal-header">
                              <h3>发票详情</h3>
                              <button type="button" className="close-btn" onClick={() => setInvoiceDetail(null)}>×</button>
                            </div>
                            <div className="invoice-detail-grid">
                              <div className="detail-field"><span>发票号码</span><strong>{invoiceDetail.invoice_no || invoiceDetail.id || '—'}</strong></div>
                              <div className="detail-field"><span>开票日期</span><strong>{invoiceDetail.date || '—'}</strong></div>
                              <div className="detail-field"><span>金额</span><strong>¥{Number(invoiceDetail.amount || 0).toLocaleString()}</strong></div>
                              <div className="detail-field"><span>分类</span><strong>{invoiceDetail.category || inferInvoiceCategory(invoiceDetail) || '其他'}</strong></div>
                              <div className="detail-field"><span>发票代码</span><strong>{invoiceDetail.invoice_code || '—'}</strong></div>
                              <div className="detail-field"><span>发票类型</span><strong>{invoiceDetail.invoice_type || '未知'}</strong></div>
                              <div className="detail-field"><span>税率</span><strong>{invoiceDetail.tax_rate != null ? `${invoiceDetail.tax_rate}%` : '—'}</strong></div>
                              <div className="detail-field"><span>税额</span><strong>¥{Number(invoiceDetail.tax_amount || 0).toLocaleString()}</strong></div>
                              <div className="detail-field"><span>购买方</span><strong>{invoiceDetail.buyer_name || '—'}</strong><small>{invoiceDetail.buyer_tax_no || ''}</small></div>
                              <div className="detail-field"><span>销售方</span><strong>{invoiceDetail.seller_name || invoiceDetail.customer_name || '—'}</strong><small>{invoiceDetail.seller_tax_no || ''}</small></div>
                            </div>
                            {Array.isArray(invoiceDetail.items) && invoiceDetail.items.length > 0 && (
                              <table className="detail-table">
                                <thead>
                                  <tr><th>产品明细</th><th>数量</th><th>单价</th><th>金额</th></tr>
                                </thead>
                                <tbody>
                                  {invoiceDetail.items.map((line, index) => (
                                    <tr key={`${line.item_name || 'line'}-${index}`}>
                                      <td>{line.item_name || '—'}</td>
                                      <td>{line.quantity ?? '—'}</td>
                                      <td>¥{Number(line.unit_price || 0).toLocaleString()}</td>
                                      <td>¥{Number(line.amount || 0).toLocaleString()}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                            {invoiceDetail.raw_text && (
                              <details className="raw-text-box">
                                <summary>OCR 原始识别文字（可展开）</summary>
                                <pre>{invoiceDetail.raw_text}</pre>
                              </details>
                            )}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="empty-state">未读取到本地发票文件</div>
                  )}
                </section>

                <section className="panel">
                  <div className="section-header">
                    <h2>月度现金流</h2>
                    <span className="status-badge">趋势</span>
                  </div>

                  {financeAnalysis.monthly_trend && financeAnalysis.monthly_trend.length > 0 ? (
                    <div className="chart-bars">
                      {(() => {
                        const maxValue = Math.max(
                          ...financeAnalysis.monthly_trend.map((item) => Math.max(Number(item.income || 0), Number(item.expense || 0))),
                          1,
                        );
                        return financeAnalysis.monthly_trend.map((item) => (
                          <div className="chart-row" key={item.month}>
                            <span>{item.month}</span>
                            <div className="chart-track">
                              <div className="chart-fill" style={{ width: `${((Math.max(Number(item.income || 0), Number(item.expense || 0)) / maxValue) * 100)}%` }} />
                            </div>
                            <strong>¥{Number(item.income || 0).toLocaleString()}</strong>
                          </div>
                        ));
                      })()}
                    </div>
                  ) : (
                    <div className="empty-state">暂无月度现金流数据</div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'finance' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增财务记录</h2>
                    <span className="status-badge">收支流水</span>
                  </div>

                  <form onSubmit={submitFinance} className="erp-form">
                    <div className="report-summary-grid" style={{ marginBottom: '18px' }}>
                      <div className="metric-card">
                        <span>净现金流</span>
                        <strong>¥{Number(financeDecision.summary.net_cash_flow || 0).toLocaleString()}</strong>
                      </div>
                      <div className="metric-card">
                        <span>毛利率</span>
                        <strong>{Number(financeDecision.summary.gross_margin_rate || 0).toFixed(1)}%</strong>
                      </div>
                      <div className="metric-card">
                        <span>风险</span>
                        <strong>{financeDecision.risk_level === 'healthy' ? '健康' : financeDecision.risk_level === 'watch' ? '关注' : '风险'}</strong>
                      </div>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        类型
                        <select value={financeForm.transaction_type} onChange={handleFinanceChange('transaction_type')}>
                          <option value="income">收入</option>
                          <option value="expense">支出</option>
                        </select>
                      </label>
                      <label>
                        金额
                        <input type="number" step="0.01" value={financeForm.amount} onChange={handleFinanceChange('amount')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        货币
                        <input value={financeForm.currency} onChange={handleFinanceChange('currency')} />
                      </label>
                      <label>
                        关联订单 ID
                        <input type="number" value={financeForm.related_order_id} onChange={handleFinanceChange('related_order_id')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        客户 ID
                        <input type="number" value={financeForm.customer_id} onChange={handleFinanceChange('customer_id')} />
                      </label>
                      <label>
                        供应商 ID
                        <input type="number" value={financeForm.supplier_id} onChange={handleFinanceChange('supplier_id')} />
                      </label>
                    </div>

                    <label>
                      备注
                      <textarea value={financeForm.note} onChange={handleFinanceChange('note')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存财务记录</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>打印中心</h2>
                    <span className="status-badge">对账单 / 余额确认单</span>
                  </div>

                  <div className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户（对账单 / 确认单）
                        <select value={printParty.customer_id} onChange={(event) => setPrintParty((prev) => ({ ...prev, customer_id: event.target.value }))}>
                          <option value="">— 选择客户 —</option>
                          {customers.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        供应商（对账单）
                        <select value={printParty.supplier_id} onChange={(event) => setPrintParty((prev) => ({ ...prev, supplier_id: event.target.value }))}>
                          <option value="">— 选择供应商 —</option>
                          {suppliers.map((s) => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        起始日期
                        <input type="date" value={printParty.from} onChange={(event) => setPrintParty((prev) => ({ ...prev, from: event.target.value }))} />
                      </label>
                      <label>
                        截止日期
                        <input type="date" value={printParty.to} onChange={(event) => setPrintParty((prev) => ({ ...prev, to: event.target.value }))} />
                      </label>
                    </div>

                    <div className="modal-actions" style={{ justifyContent: 'flex-start' }}>
                      <button
                        type="button"
                        className="primary-btn"
                        disabled={!printParty.customer_id}
                        onClick={() => printPdf(`/print/statement/customer/${printParty.customer_id}${printPeriodQuery()}`, '客户对账单.pdf')}
                      >
                        打印客户对账单
                      </button>
                      <button
                        type="button"
                        className="secondary-btn"
                        disabled={!printParty.customer_id}
                        onClick={() => printPdf(`/print/balance-confirm/customer/${printParty.customer_id}${printPeriodQuery()}`, '往来余额确认单.pdf')}
                      >
                        打印余额确认单
                      </button>
                      <button
                        type="button"
                        className="secondary-btn"
                        disabled={!printParty.supplier_id}
                        onClick={() => printPdf(`/print/statement/supplier/${printParty.supplier_id}${printPeriodQuery()}`, '供应商对账单.pdf')}
                      >
                        打印供应商对账单
                      </button>
                    </div>
                  </div>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>财务流水</h2>
                    <span className="status-badge">{finance.length} 条</span>
                  </div>

                  {finance.length === 0 ? (
                    <div className="empty-state">暂无财务记录</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>类型</th>
                          <th>金额</th>
                          <th>货币</th>
                          <th>备注</th>
                        </tr>
                      </thead>
                      <tbody>
                        {finance.slice(0, 8).map((row) => (
                          <tr key={row.id}>
                            <td>{row.transaction_type}</td>
                            <td>¥{Number(row.amount || 0).toLocaleString()}</td>
                            <td>{row.currency}</td>
                            <td>{row.note || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {finance.length > 8 && (
                    <div className="table-hint">共 {finance.length} 条，仅显示最近 8 条</div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'stock-logs' && renderStockLogsPage()}

            {selectedTab === 'receivable' && renderPartyBalancePage('customer')}

            {selectedTab === 'payable' && renderPartyBalancePage('supplier')}

            {selectedTab === 'ledger' && renderLedgerPage()}

            {selectedTab === 'contracts' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增购销合同</h2>
                    <span className="status-badge">模板 A2 · 标准版</span>
                  </div>

                  <form onSubmit={submitContract} className="erp-form">
                    <div className="contract-own-block">
                      <div className="section-header compact-header">
                        <h3>我方信息（合同抬头）</h3>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          onClick={saveCompanyDefaults}
                        >
                          保存为公司默认
                        </button>
                      </div>
                      <div className="contract-item-row" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 2fr) 140px' }}>
                        <input
                          value={contractForm.own_name}
                          onChange={handleContractChange('own_name')}
                          placeholder="单位名称"
                        />
                        <input
                          value={contractForm.own_address}
                          onChange={handleContractChange('own_address')}
                          placeholder="地址"
                        />
                        <input
                          value={contractForm.own_legal_person}
                          onChange={handleContractChange('own_legal_person')}
                          placeholder="法定代表人"
                        />
                      </div>
                      <div className="contract-item-row" style={{ gridTemplateColumns: 'minmax(0, 2fr) 140px 140px' }}>
                        <input
                          value={contractForm.own_tax_no}
                          onChange={handleContractChange('own_tax_no')}
                          placeholder="统一社会信用代码"
                        />
                        <input
                          value={contractForm.own_contact}
                          onChange={handleContractChange('own_contact')}
                          placeholder="联系人"
                        />
                        <input
                          value={contractForm.own_phone}
                          onChange={handleContractChange('own_phone')}
                          placeholder="联系电话"
                        />
                      </div>
                      <div className="contract-item-row" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)' }}>
                        <input
                          value={contractForm.own_bank_name}
                          onChange={handleContractChange('own_bank_name')}
                          placeholder="开户银行"
                        />
                        <input
                          value={contractForm.own_bank_account}
                          onChange={handleContractChange('own_bank_account')}
                          placeholder="银行账号"
                        />
                      </div>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        合同类型
                        <select value={contractForm.contract_type} onChange={handleContractChange('contract_type')}>
                          <option value="sales">销售合同（我方为供方）</option>
                          <option value="purchase">采购合同（我方为需方）</option>
                        </select>
                      </label>
                      <label>
                        {contractForm.contract_type === 'sales' ? '客户' : '供应商'}
                        <select value={contractForm.party_id} onChange={handleContractChange('party_id')} required>
                          <option value="">请选择</option>
                          {(contractForm.contract_type === 'sales' ? customers : suppliers).map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        签订日期
                        <input type="date" value={contractForm.sign_date} onChange={handleContractChange('sign_date')} />
                      </label>
                      <label>
                        签订地点
                        <input value={contractForm.sign_place} onChange={handleContractChange('sign_place')} placeholder="如：西安市" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        交货时间
                        <input value={contractForm.delivery_date} onChange={handleContractChange('delivery_date')} placeholder="如：2026-10-20" />
                      </label>
                      <label>
                        交货地点
                        <input value={contractForm.delivery_place} onChange={handleContractChange('delivery_place')} placeholder="默认按对方单位地址" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        验收期限（天）
                        <input type="number" min="1" value={contractForm.inspection_days} onChange={handleContractChange('inspection_days')} />
                      </label>
                      <label>
                        违约金日利率（万分之）
                        <input type="number" min="0" step="0.5" value={contractForm.penalty_rate} onChange={handleContractChange('penalty_rate')} />
                      </label>
                    </div>

                    <label>
                      付款方式与节点
                      <input value={contractForm.payment_terms} onChange={handleContractChange('payment_terms')} placeholder="如：货到验收合格后 30 日内付清全款" />
                    </label>

                    <label>
                      质量标准
                      <input value={contractForm.quality_standard} onChange={handleContractChange('quality_standard')} placeholder="如：GB/T 12224 国家标准" />
                    </label>

                    <div className="form-row two-col">
                      <label>
                        开票要求
                        <input value={contractForm.invoice_requirement} onChange={handleContractChange('invoice_requirement')} />
                      </label>
                      <label>
                        合同份数
                        <input type="number" min="1" value={contractForm.copies} onChange={handleContractChange('copies')} />
                      </label>
                    </div>

                    <label>
                      包装标准
                      <input value={contractForm.package_standard} onChange={handleContractChange('package_standard')} />
                    </label>

                    <label>
                      运输与风险承担
                      <input value={contractForm.freight_bearer} onChange={handleContractChange('freight_bearer')} />
                    </label>

                    <label>
                      质保与售后
                      <input value={contractForm.warranty_terms} onChange={handleContractChange('warranty_terms')} />
                    </label>

                    <label>
                      争议解决方式
                      <input value={contractForm.dispute_resolution} onChange={handleContractChange('dispute_resolution')} />
                    </label>

                    <label>
                      送达地址
                      <input value={contractForm.service_address} onChange={handleContractChange('service_address')} />
                    </label>

                    <label>
                      补充条款（打印时作为「第十二条 补充约定」）
                      <textarea rows="2" value={contractForm.other_terms} onChange={handleContractChange('other_terms')} />
                    </label>

                    <div className="contract-items">
                      <div className="section-header compact-header">
                        <h3>合同标的（明细）</h3>
                        <span className="status-badge">{contractForm.items.length} 行</span>
                      </div>
                      {contractForm.items.map((row, index) => (
                        <div className="contract-item-row" key={index}>
                          <select value={row.product_id} onChange={handleContractItemChange(index, 'product_id')}>
                            <option value="">选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name}
                                {item.standards ? ` / ${item.standards}` : ''}
                              </option>
                            ))}
                          </select>
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={row.quantity}
                            onChange={handleContractItemChange(index, 'quantity')}
                            placeholder="数量"
                          />
                          <input
                            type="number"
                            step="0.01"
                            value={row.unit_price}
                            onChange={handleContractItemChange(index, 'unit_price')}
                            placeholder="单价"
                          />
                          <button
                            type="button"
                            className="secondary-btn small-btn"
                            onClick={() => removeContractItem(index)}
                            disabled={contractForm.items.length <= 1}
                          >
                            删行
                          </button>
                        </div>
                      ))}
                      <div className="contract-item-actions">
                        <button type="button" className="secondary-btn small-btn" onClick={addContractItem}>
                          ＋ 添加明细行
                        </button>
                        <span className="table-hint">
                          预计金额 ¥
                          {contractForm.items
                            .reduce(
                              (sum, row) => sum + (Number(row.quantity) || 0) * (Number(row.unit_price) || 0),
                              0,
                            )
                            .toLocaleString()}
                        </span>
                      </div>
                    </div>

                    <label>
                      备注
                      <input value={contractForm.note} onChange={handleContractChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存合同</button>
                    <p className="table-hint">
                      条款变量留空时由系统按行业常规表述兜底，保存后可直接打印 A2 标准版合同。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>合同列表</h2>
                    <span className="status-badge">{contracts.length} 份</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={contractKeyword}
                      onChange={(event) => setContractKeyword(event.target.value)}
                      placeholder="按合同号 / 名称 / 对方单位搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshContracts(contractKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setContractKeyword('');
                        refreshContracts();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {contracts.length === 0 ? (
                    <div className="empty-state">暂无合同数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>合同号</th>
                          <th>类型</th>
                          <th>对方单位</th>
                          <th>金额</th>
                          <th>状态</th>
                          <th>签订日期</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {contracts.map((row) => (
                          <tr
                            key={row.id}
                            onClick={() => setSelectedContract(row)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setSelectedContract(row);
                              }
                            }}
                            tabIndex={0}
                            style={{ cursor: 'pointer' }}
                          >
                            <td>{row.contract_no}</td>
                            <td>{row.contract_type === 'sales' ? '销售' : '采购'}</td>
                            <td>{row.party_name || '—'}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{contractStatusLabel(row.status)}</td>
                            <td>{row.sign_date || '—'}</td>
                            <td>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/contract/${row.id}`, `购销合同_${row.contract_no}.pdf`);
                                }}
                              >
                                打印
                              </button>{' '}
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  contractToOrder(row);
                                }}
                                disabled={Boolean(row.order_id)}
                              >
                                {row.order_id ? `已转 ${row.order_no}` : '生成单据'}
                              </button>{' '}
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/contracts/${row.id}`,
                                    label: `合同 ${row.contract_no}`,
                                    kind: 'contract',
                                  });
                                }}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>

                {selectedContract && (
                  <div className="modal-overlay" onClick={() => setSelectedContract(null)}>
                    <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                      <div className="modal-header">
                        <h3>合同 {selectedContract.contract_no}</h3>
                        <button type="button" className="close-btn" onClick={() => setSelectedContract(null)}>×</button>
                      </div>
                      <div className="contract-detail">
                        <p>
                          <strong>{selectedContract.contract_type === 'sales' ? '销售合同' : '采购合同'}</strong>
                          {' · '}
                          {contractStatusLabel(selectedContract.status)}
                          {selectedContract.order_no ? ` · 已生成单据 ${selectedContract.order_no}` : ''}
                        </p>
                        <p>对方单位：{selectedContract.party_name || '—'}</p>
                        <p>签订日期：{selectedContract.sign_date || '—'}　签订地点：{selectedContract.sign_place || '—'}</p>
                        <p>金额：¥{Number(selectedContract.total_amount || 0).toLocaleString()}（{selectedContract.amount_chinese || '—'}）</p>
                        <p>付款：{selectedContract.payment_terms || '—'}</p>
                        <p>质量标准：{selectedContract.quality_standard || '—'}</p>
                        <p>交货：{selectedContract.delivery_date || '—'} / {selectedContract.delivery_place || '—'}</p>
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>商品</th>
                              <th>规格</th>
                              <th>单位</th>
                              <th>数量</th>
                              <th>单价</th>
                              <th>金额</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(selectedContract.items || []).map((line) => (
                              <tr key={line.id}>
                                <td>{line.product_name}</td>
                                <td>{line.standards || '—'}</td>
                                <td>{line.unit || '—'}</td>
                                <td>{line.quantity}</td>
                                <td>¥{Number(line.unit_price || 0).toLocaleString()}</td>
                                <td>¥{Number(line.amount || 0).toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="modal-actions">
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => printPdf(`/print/contract/${selectedContract.id}`, `购销合同_${selectedContract.contract_no}.pdf`)}
                        >
                          打印合同
                        </button>
                        <button type="button" className="secondary-btn" onClick={() => setSelectedContract(null)}>关闭</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {selectedTab === 'quotation' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增销售报价单</h2>
                    <span className="status-badge">只报价 · 不动库存</span>
                  </div>

                  <form onSubmit={submitQuotation} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户
                        <select value={quotationForm.customer_id} onChange={handleQuotationChange('customer_id')}>
                          <option value="">请选择客户</option>
                          {customers.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                        {renderPartyLink('customers', quotationForm.customer_id, '客户')}
                      </label>
                      <label>
                        客户地址
                        <input
                          value={quotationForm.customer_address}
                          onChange={handleQuotationChange('customer_address')}
                          placeholder="选客户后自动带出"
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        联系人
                        <input value={quotationForm.contact} onChange={handleQuotationChange('contact')} />
                      </label>
                      <label>
                        联系电话
                        <input value={quotationForm.contact_phone} onChange={handleQuotationChange('contact_phone')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        报价日期
                        <input type="date" value={quotationForm.quote_date} onChange={handleQuotationChange('quote_date')} />
                      </label>
                      <label>
                        报价效期
                        <input type="date" value={quotationForm.valid_until} onChange={handleQuotationChange('valid_until')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        出货仓库
                        <select value={quotationForm.warehouse_id} onChange={handleQuotationChange('warehouse_id')}>
                          <option value="">转单时再选</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        业务员
                        <input value={quotationForm.businesser} onChange={handleQuotationChange('businesser')} placeholder="如：范先生" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        付款方式
                        <select value={quotationForm.payment_method} onChange={handleQuotationChange('payment_method')}>
                          <option value="">请选择</option>
                          {(quotationMeta?.payment_methods || []).map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        运输方式
                        <select value={quotationForm.transport_method} onChange={handleQuotationChange('transport_method')}>
                          <option value="">请选择</option>
                          {(quotationMeta?.transport_methods || []).map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        传真号码
                        <input value={quotationForm.fax} onChange={handleQuotationChange('fax')} />
                      </label>
                      <label>
                        交货地点
                        <input value={quotationForm.delivery_place} onChange={handleQuotationChange('delivery_place')} />
                      </label>
                    </div>

                    <div className="contract-items">
                      <div className="section-header compact-header">
                        <h3>报价明细</h3>
                        <button type="button" className="secondary-btn small-btn" onClick={addQuotationItem}>
                          + 添加一行
                        </button>
                      </div>
                      {quotationForm.items.map((line, index) => (
                        <div className="contract-item-row" key={index}>
                          <select value={line.product_id} onChange={handleQuotationItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.name}
                              </option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.quantity}
                            onChange={handleQuotationItemChange(index, 'quantity')}
                            placeholder="数量"
                          />
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleQuotationItemChange(index, 'unit_price')}
                            placeholder="报价单价"
                          />
                          <button
                            type="button"
                            className="danger-btn"
                            onClick={() => removeQuotationItem(index)}
                            disabled={quotationForm.items.length <= 1}
                          >
                            移除
                          </button>
                        </div>
                      ))}
                      <p className="table-hint">
                        共 {quotationForm.items.filter((r) => r.product_id).length} 行 · 合计 ¥
                        {quotationForm.items
                          .reduce((sum, r) => sum + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0), 0)
                          .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </p>
                    </div>

                    <label>
                      备注
                      <input value={quotationForm.note} onChange={handleQuotationChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存报价单</button>
                    <p className="table-hint">
                      报价单只是报价意向，不产生应收、不扣库存；客户确认后点「转销售订单」生成订单，再走单据流程。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>报价单列表</h2>
                    <span className="status-badge">{quotations.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={quotationKeyword}
                      onChange={(event) => setQuotationKeyword(event.target.value)}
                      placeholder="按报价单号 / 客户 / 业务员搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshQuotations(quotationKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setQuotationKeyword('');
                        refreshQuotations();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {quotations.length === 0 ? (
                    <div className="empty-state">暂无报价单</div>
                  ) : (
                    <div className="quotation-table-wrap">
                      <table className="data-table quotation-table">
                      <thead>
                        <tr>
                          <th>报价单号</th>
                          <th>客户</th>
                          <th>金额</th>
                          <th>业务员</th>
                          <th>状态</th>
                          <th>报价日期</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {quotations.map((row) => (
                          <tr
                            key={row.id}
                            onClick={() => setSelectedQuotation(row)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                setSelectedQuotation(row);
                              }
                            }}
                            tabIndex={0}
                            style={{ cursor: 'pointer' }}
                          >
                            <td>{row.quote_no}</td>
                            <td>{row.customer_name || '—'}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{row.businesser || '—'}</td>
                            <td>{quotationStatusLabel(row.status)}</td>
                            <td>{row.quote_date || '—'}</td>
                            <td>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/quotation/${row.id}`, `报价单_${row.quote_no}.pdf`);
                                }}
                              >
                                打印
                              </button>{' '}
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  quotationToOrder(row);
                                }}
                                disabled={Boolean(row.order_id)}
                              >
                                {row.order_id ? `已转 ${row.order_no}` : '转订单'}
                              </button>{' '}
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/quotations/${row.id}`,
                                    label: `报价单 ${row.quote_no}`,
                                    kind: 'quotation',
                                  });
                                }}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      </table>
                    </div>
                  )}
                </section>

                {selectedQuotation && (
                  <div className="modal-overlay" onClick={() => setSelectedQuotation(null)}>
                    <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                      <div className="modal-header">
                        <h3>报价单 {selectedQuotation.quote_no}</h3>
                        <button type="button" className="close-btn" onClick={() => setSelectedQuotation(null)}>×</button>
                      </div>
                      <div className="contract-detail">
                        <p>
                          <strong>{quotationStatusLabel(selectedQuotation.status)}</strong>
                          {selectedQuotation.order_no ? ` · 已生成销售订单 ${selectedQuotation.order_no}` : ''}
                        </p>
                        <p>客户：{selectedQuotation.customer_name || '—'}　联系人：{selectedQuotation.contact || '—'}</p>
                        <p>联系电话：{selectedQuotation.contact_phone || '—'}　传真：{selectedQuotation.fax || '—'}</p>
                        <p>客户地址：{selectedQuotation.customer_address || '—'}</p>
                        <p>报价日期：{selectedQuotation.quote_date || '—'}　效期至：{selectedQuotation.valid_until || '—'}</p>
                        <p>业务员：{selectedQuotation.businesser || '—'}　付款方式：{selectedQuotation.payment_method || '—'}</p>
                        <p>运输方式：{selectedQuotation.transport_method || '—'}　交货地点：{selectedQuotation.delivery_place || '—'}</p>
                        <p>金额：¥{Number(selectedQuotation.total_amount || 0).toLocaleString()}（{selectedQuotation.amount_chinese || '—'}）</p>
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>商品</th>
                              <th>规格</th>
                              <th>单位</th>
                              <th>数量</th>
                              <th>单价</th>
                              <th>金额</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(selectedQuotation.items || []).map((line) => (
                              <tr key={line.id}>
                                <td>{line.product_name}</td>
                                <td>{line.standards || '—'}</td>
                                <td>{line.unit || '—'}</td>
                                <td>{line.quantity}</td>
                                <td>¥{Number(line.unit_price || 0).toLocaleString()}</td>
                                <td>¥{Number(line.amount || 0).toLocaleString()}</td>
                              </tr>
                            ))}
                            {(selectedQuotation.items || []).length === 0 && (
                              <tr>
                                <td colSpan={6}>该报价单暂无明细（浩技云历史导入数据只含单头）</td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="modal-actions">
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => printPdf(`/print/quotation/${selectedQuotation.id}`, `报价单_${selectedQuotation.quote_no}.pdf`)}
                        >
                          打印报价单
                        </button>
                        <button type="button" className="secondary-btn" onClick={() => setSelectedQuotation(null)}>关闭</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {selectedTab === 'purchase-return' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增采购退货单</h2>
                    <span className="status-badge">退货冲减库存 · 应付</span>
                  </div>

                  <form onSubmit={submitPurchaseReturn} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        供应商
                        <select value={purchaseReturnForm.supplier_id} onChange={handlePurchaseReturnChange('supplier_id')} required>
                          <option value="">请选择供应商</option>
                          {suppliers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('suppliers', purchaseReturnForm.supplier_id, '供应商')}
                      </label>
                      <label>
                        退货仓库
                        <select value={purchaseReturnForm.warehouse_id} onChange={handlePurchaseReturnChange('warehouse_id')}>
                          <option value="">默认仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退货日期
                        <input type="date" value={purchaseReturnForm.return_date} onChange={handlePurchaseReturnChange('return_date')} />
                      </label>
                      <label>
                        业务员
                        <input value={purchaseReturnForm.businesser} onChange={handlePurchaseReturnChange('businesser')} placeholder="如：采购员" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退款方式
                        <input value={purchaseReturnForm.payment_method} onChange={handlePurchaseReturnChange('payment_method')} placeholder="如：银行转账 / 现金" />
                      </label>
                      <label>
                        来源单号
                        <input value={purchaseReturnForm.source_order_no} onChange={handlePurchaseReturnChange('source_order_no')} placeholder="关联的采购入库单号（可选）" />
                      </label>
                    </div>

                    <label>
                      退货原因
                      <input value={purchaseReturnForm.return_reason} onChange={handlePurchaseReturnChange('return_reason')} placeholder="如：质量不合格 / 规格不符" />
                    </label>

                    <div className="section-header">
                      <h3>退货明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addPurchaseReturnItem}>+ 添加一行</button>
                    </div>
                    {purchaseReturnForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={line.product_id} onChange={handlePurchaseReturnItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={line.quantity} onChange={handlePurchaseReturnItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" min="0" step="0.01" value={line.unit_price} onChange={handlePurchaseReturnItemChange(index, 'unit_price')} />
                        </label>
                        {purchaseReturnForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removePurchaseReturnItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {purchaseReturnForm.items.filter((r) => r.product_id).length} 行 · 合计 ¥
                      {purchaseReturnForm.items
                        .reduce((sum, r) => sum + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>

                    <label>
                      备注
                      <input value={purchaseReturnForm.note} onChange={handlePurchaseReturnChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存采购退货单</button>
                    <p className="table-hint">
                      退货审核后自动冲减库存与应付，删除退货单会撤销这两笔动作。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>采购退货列表</h2>
                    <span className="status-badge">{purchaseReturns.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={purchaseReturnKeyword}
                      onChange={(event) => setPurchaseReturnKeyword(event.target.value)}
                      placeholder="按退货单号 / 供应商 / 业务员搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshPurchaseReturns(purchaseReturnKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setPurchaseReturnKeyword('');
                        refreshPurchaseReturns();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {purchaseReturns.length === 0 ? (
                    <div className="empty-state">暂无采购退货单。退货单会把货退回供应商，同时冲减库存与应付。</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>退货单号</th>
                          <th>供应商</th>
                          <th>金额</th>
                          <th>业务员</th>
                          <th>退货原因</th>
                          <th>状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {purchaseReturns.map((row) => (
                          <tr key={row.id}>
                            <td>{row.return_no}</td>
                            <td>{row.supplier_name || suppliers.find((s) => s.id === row.supplier_id)?.name || row.supplier_id}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{row.businesser || '—'}</td>
                            <td>{row.return_reason || '—'}</td>
                            <td><span className="status-badge">{purchaseReturnStatusLabel(row.status)}</span></td>
                            <td className="row-actions">
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={() => printPdf(`/print/purchase-return/${row.id}`, `采购退货单_${row.return_no}.pdf`)}
                              >
                                打印
                              </button>{' '}
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={() => setConfirmDelete({
                                  id: row.id,
                                  endpoint: `/purchase-returns/${row.id}`,
                                  label: `采购退货单 ${row.return_no}`,
                                  kind: 'purchase-return',
                                })}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'sales-return' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增销售退货单</h2>
                    <span className="status-badge">退货冲减库存 · 应收</span>
                  </div>

                  <form onSubmit={submitSalesReturn} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户
                        <select value={salesReturnForm.customer_id} onChange={handleSalesReturnChange('customer_id')} required>
                          <option value="">请选择客户</option>
                          {customers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}（{item.code}）</option>
                          ))}
                        </select>
                        {renderPartyLink('customers', salesReturnForm.customer_id, '客户')}
                      </label>
                      <label>
                        退货入库仓库
                        <select value={salesReturnForm.warehouse_id} onChange={handleSalesReturnChange('warehouse_id')}>
                          <option value="">默认仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退货日期
                        <input type="date" value={salesReturnForm.return_date} onChange={handleSalesReturnChange('return_date')} />
                      </label>
                      <label>
                        业务员
                        <input value={salesReturnForm.businesser} onChange={handleSalesReturnChange('businesser')} placeholder="如：销售员" />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退款方式
                        <input value={salesReturnForm.payment_method} onChange={handleSalesReturnChange('payment_method')} placeholder="如：银行转账 / 现金" />
                      </label>
                      <label>
                        来源单号
                        <input value={salesReturnForm.source_order_no} onChange={handleSalesReturnChange('source_order_no')} placeholder="关联的销售出库单号（可选）" />
                      </label>
                    </div>

                    <label>
                      退货原因
                      <input value={salesReturnForm.return_reason} onChange={handleSalesReturnChange('return_reason')} placeholder="如：客户拒收 / 规格不符" />
                    </label>

                    <div className="section-header">
                      <h3>退货明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addSalesReturnItem}>+ 添加一行</button>
                    </div>
                    {salesReturnForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={line.product_id} onChange={handleSalesReturnItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          数量
                          <input type="number" min="1" value={line.quantity} onChange={handleSalesReturnItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          单价
                          <input type="number" min="0" step="0.01" value={line.unit_price} onChange={handleSalesReturnItemChange(index, 'unit_price')} />
                        </label>
                        {salesReturnForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeSalesReturnItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {salesReturnForm.items.filter((r) => r.product_id).length} 行 · 合计 ¥
                      {salesReturnForm.items
                        .reduce((sum, r) => sum + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0), 0)
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>

                    <label>
                      备注
                      <input value={salesReturnForm.note} onChange={handleSalesReturnChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存销售退货单</button>
                    <p className="table-hint">
                      退货后自动增加库存并冲减应收，删除退货单会撤销这两笔动作。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>销售退货列表</h2>
                    <span className="status-badge">{salesReturns.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={salesReturnKeyword}
                      onChange={(event) => setSalesReturnKeyword(event.target.value)}
                      placeholder="按退货单号 / 客户 / 业务员搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshSalesReturns(salesReturnKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setSalesReturnKeyword('');
                        refreshSalesReturns();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {salesReturns.length === 0 ? (
                    <div className="empty-state">暂无销售退货单。退货单会把货收回仓库，同时冲减库存与应收。</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>退货单号</th>
                          <th>客户</th>
                          <th>金额</th>
                          <th>业务员</th>
                          <th>退货原因</th>
                          <th>状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {salesReturns.map((row) => (
                          <tr key={row.id}>
                            <td>{row.return_no}</td>
                            <td>{row.customer_name || customers.find((c) => c.id === row.customer_id)?.name || row.customer_id}</td>
                            <td>¥{Number(row.total_amount || 0).toLocaleString()}</td>
                            <td>{row.businesser || '—'}</td>
                            <td>{row.return_reason || '—'}</td>
                            <td><span className="status-badge">{salesReturnStatusLabel(row.status)}</span></td>
                            <td className="row-actions">
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={() => printPdf(`/print/sales-return/${row.id}`, `销售退货单_${row.return_no}.pdf`)}
                              >
                                打印
                              </button>{' '}
                              <button
                                type="button"
                                className="danger-btn"
                                onClick={() => setConfirmDelete({
                                  id: row.id,
                                  endpoint: `/sales-returns/${row.id}`,
                                  label: `销售退货单 ${row.return_no}`,
                                  kind: 'sales-return',
                                })}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'transfer' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增调拨单</h2>
                    <span className="status-badge">内部移库 · 不影响财务</span>
                  </div>

                  <form onSubmit={submitTransfer} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        调出仓库（库存减少）
                        <select value={transferForm.from_warehouse_id} onChange={handleTransferChange('from_warehouse_id')} required>
                          <option value="">请选择调出仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        调入仓库（库存增加）
                        <select value={transferForm.to_warehouse_id} onChange={handleTransferChange('to_warehouse_id')} required>
                          <option value="">请选择调入仓库</option>
                          {warehouses
                            .filter((item) => String(item.id) !== String(transferForm.from_warehouse_id))
                            .map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        调拨日期
                        <input type="date" value={transferForm.transfer_date} onChange={handleTransferChange('transfer_date')} />
                      </label>
                      <label>
                        经办人
                        <input value={transferForm.handler} onChange={handleTransferChange('handler')} placeholder="如：仓管员" />
                      </label>
                    </div>

                    <label>
                      调拨原因
                      <input value={transferForm.reason} onChange={handleTransferChange('reason')} placeholder="如：门店补货 / 仓库整合" />
                    </label>

                    <div className="section-header">
                      <h3>调拨明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addTransferItem}>+ 添加一行</button>
                    </div>
                    {transferForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={line.product_id} onChange={handleTransferItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderTransferStockHint(line.product_id, transferForm.from_warehouse_id)}
                        </label>
                        <label>
                          调拨数量
                          <input type="number" min="1" value={line.quantity} onChange={handleTransferItemChange(index, 'quantity')} />
                        </label>
                        <label>
                          成本单价
                          <input type="number" min="0" step="0.01" value={line.unit_price} onChange={handleTransferItemChange(index, 'unit_price')} />
                        </label>
                        {transferForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeTransferItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {transferForm.items.filter((r) => r.product_id).length} 行 · 合计数量{' '}
                      {transferForm.items
                        .reduce((sum, r) => sum + (Number(r.quantity) || 0), 0)
                        .toLocaleString()}
                    </p>

                    <label>
                      备注
                      <input value={transferForm.note} onChange={handleTransferChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存调拨单</button>
                    <p className="table-hint">
                      调拨是同一企业内部的库存位置转移，只改动两个仓库的现存量、不产生财务流水；删除调拨单会把两侧库存同时还原。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>调拨单列表</h2>
                    <span className="status-badge">{transfers.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={transferKeyword}
                      onChange={(event) => setTransferKeyword(event.target.value)}
                      placeholder="按调拨单号 / 经办人 / 原因搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshTransfers(transferKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setTransferKeyword('');
                        refreshTransfers();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {transfers.length === 0 ? (
                    <div className="empty-state">暂无调拨单。调拨单把货从一个仓库搬到另一个仓库，只改现存量、不涉财务。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>调拨单号</th>
                            <th>调拨方向</th>
                            <th>数量</th>
                            <th>经办人</th>
                            <th>调拨日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {transfers.map((row) => (
                            <tr key={row.id}>
                              <td>{row.transfer_no}</td>
                              <td>
                                {warehouses.find((w) => w.id === row.from_warehouse_id)?.name || row.from_warehouse_id}
                                <span className="transfer-arrow"> → </span>
                                {warehouses.find((w) => w.id === row.to_warehouse_id)?.name || row.to_warehouse_id}
                              </td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{row.handler || '—'}</td>
                              <td>{row.transfer_date || '—'}</td>
                              <td><span className="status-badge">{transferStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() => printPdf(`/print/inventory-transfer/${row.id}`, `调拨单_${row.transfer_no}.pdf`)}
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/inventory-transfers/${row.id}`,
                                    label: `调拨单 ${row.transfer_no}`,
                                    kind: 'inventory-transfer',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'stocktaking' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增盘点单</h2>
                    <span className="status-badge">账实核对 · 不影响财务</span>
                  </div>

                  <form onSubmit={submitStocktaking} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        盘点仓库
                        <select
                          value={stocktakingForm.warehouse_id}
                          onChange={handleStocktakingChange('warehouse_id')}
                          required
                        >
                          <option value="">请选择盘点仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        盘点日期
                        <input
                          type="date"
                          value={stocktakingForm.check_date}
                          onChange={handleStocktakingChange('check_date')}
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        盘点人
                        <input
                          value={stocktakingForm.handler}
                          onChange={handleStocktakingChange('handler')}
                          placeholder="如：仓管员"
                        />
                      </label>
                      <label>
                        盘点范围
                        <input
                          value={stocktakingForm.scope}
                          onChange={handleStocktakingChange('scope')}
                          placeholder="如：全仓 / 仅 A 区货架"
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>盘点明细（账面 → 实盘）</h3>
                      <span className="section-actions">
                        <button type="button" className="secondary-btn small-btn" onClick={loadStocktakingPlan}>
                          带出账面库存
                        </button>
                        <button type="button" className="secondary-btn small-btn" onClick={addStocktakingItem}>
                          + 手工加行
                        </button>
                      </span>
                    </div>

                    {stocktakingPlanHint && <p className="focus-banner">{stocktakingPlanHint}</p>}

                    {stocktakingForm.items.length === 0 ? (
                      <div className="empty-state">
                        先选仓库，再点「带出账面库存」——系统会按实时现存量生成盘点底稿，
                        你只需要改有差异的行；账面为 0 却盘出货物的，用「手工加行」补。
                      </div>
                    ) : (
                      <div className="wide-table-wrap">
                        <table className="data-table stocktaking-table">
                          <thead>
                            <tr>
                              <th>商品</th>
                              <th>账面数</th>
                              <th>实盘数</th>
                              <th>盈亏</th>
                              <th>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {stocktakingForm.items.map((line, index) => {
                              const diff =
                                (Number(line.actual_quantity) || 0) - (Number(line.book_quantity) || 0);
                              return (
                                <tr key={index}>
                                  <td>
                                    {line.product_name ? (
                                      <>
                                        <span className="line-product">{line.product_name}</span>
                                        {renderStockHint(line.product_id)}
                                      </>
                                    ) : (
                                      <select
                                        value={line.product_id}
                                        onChange={(event) =>
                                          handleStocktakingProductPick(index, event.target.value)
                                        }
                                      >
                                        <option value="">请选择商品</option>
                                        {products.map((item) => (
                                          <option key={item.id} value={item.id}>{item.name}</option>
                                        ))}
                                      </select>
                                    )}
                                  </td>
                                  <td>
                                    <input
                                      type="number"
                                      step="0.01"
                                      value={line.book_quantity}
                                      onChange={handleStocktakingItemChange(index, 'book_quantity')}
                                    />
                                  </td>
                                  <td>
                                    <input
                                      type="number"
                                      step="0.01"
                                      value={line.actual_quantity}
                                      onChange={handleStocktakingItemChange(index, 'actual_quantity')}
                                    />
                                  </td>
                                  <td>
                                    <span
                                      className={
                                        diff > 0 ? 'num-profit' : diff < 0 ? 'num-loss' : undefined
                                      }
                                    >
                                      {diff > 0 ? `+${diff}` : diff}
                                    </span>
                                  </td>
                                  <td className="row-actions">
                                    <button
                                      type="button"
                                      className="danger-btn small-btn"
                                      onClick={() => removeStocktakingItem(index)}
                                    >
                                      移除
                                    </button>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}

                    <p className="table-hint">
                      共 {stocktakingForm.items.length} 行 ·
                      盘盈{' '}
                      <strong className="num-profit">
                        {stocktakingForm.items
                          .reduce((sum, r) => {
                            const d = (Number(r.actual_quantity) || 0) - (Number(r.book_quantity) || 0);
                            return sum + (d > 0 ? d : 0);
                          }, 0)
                          .toLocaleString()}
                      </strong>{' '}
                      · 盘亏{' '}
                      <strong className="num-loss">
                        {stocktakingForm.items
                          .reduce((sum, r) => {
                            const d = (Number(r.actual_quantity) || 0) - (Number(r.book_quantity) || 0);
                            return sum + (d < 0 ? -d : 0);
                          }, 0)
                          .toLocaleString()}
                      </strong>
                    </p>

                    <label>
                      备注
                      <input value={stocktakingForm.note} onChange={handleStocktakingChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存盘点单并调整库存</button>
                    <p className="table-hint">
                      保存后系统按盈亏直接调整现存量（盘盈入库、盘亏出库），只动库存、不生成财务流水；
                      删除盘点单会把盘盈盘亏一起冲销，账面与库存同时还原到盘点前。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>盘点单列表</h2>
                    <span className="status-badge">{stocktakings.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={stocktakingKeyword}
                      onChange={(event) => setStocktakingKeyword(event.target.value)}
                      placeholder="按盘点单号 / 盘点人 / 范围搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshStocktakings(stocktakingKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setStocktakingKeyword('');
                        refreshStocktakings();
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {stocktakings.length === 0 ? (
                    <div className="empty-state">暂无盘点单。盘点用于账实核对，盈亏会直接调整现存量。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>盘点单号</th>
                            <th>仓库</th>
                            <th>盘盈</th>
                            <th>盘亏</th>
                            <th>盘点日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stocktakings.map((row) => (
                            <tr key={row.id}>
                              <td>{row.check_no}</td>
                              <td>
                                {warehouses.find((w) => w.id === row.warehouse_id)?.name || row.warehouse_id}
                              </td>
                              <td className="num-profit">
                                {Number(row.total_profit || 0) > 0 ? `+${Number(row.total_profit).toLocaleString()}` : '—'}
                              </td>
                              <td className="num-loss">
                                {Number(row.total_loss || 0) > 0 ? `-${Number(row.total_loss).toLocaleString()}` : '—'}
                              </td>
                              <td>{row.check_date || '—'}</td>
                              <td><span className="status-badge">{stocktakingStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() => printPdf(`/print/stocktaking/${row.id}`, `盘点单_${row.check_no}.pdf`)}
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/stocktakings/${row.id}`,
                                    label: `盘点单 ${row.check_no}`,
                                    kind: 'stocktaking',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'loss-overflow' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增{adjustTypeLabel(adjustmentForm.adjust_type)}单</h2>
                    <span className="status-badge">
                      {ADJUST_TYPE_DIRECTION[adjustmentForm.adjust_type]} · 不影响财务
                    </span>
                  </div>

                  <div className="type-switch">
                    {['scrap', 'overflow'].map((type) => (
                      <button
                        key={type}
                        type="button"
                        className={`type-switch-btn ${adjustmentForm.adjust_type === type ? 'active' : ''}`}
                        onClick={() => setAdjustmentForm((prev) => ({ ...prev, adjust_type: type }))}
                      >
                        {adjustTypeLabel(type)}
                        <span className="type-switch-sub">{ADJUST_TYPE_DIRECTION[type]}</span>
                      </button>
                    ))}
                  </div>

                  <form onSubmit={submitAdjustment} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        发生仓库
                        <select
                          value={adjustmentForm.warehouse_id}
                          onChange={handleAdjustmentChange('warehouse_id')}
                          required
                        >
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        单据日期
                        <input
                          type="date"
                          value={adjustmentForm.adjust_date}
                          onChange={handleAdjustmentChange('adjust_date')}
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        经办人
                        <input
                          value={adjustmentForm.handler}
                          onChange={handleAdjustmentChange('handler')}
                          placeholder="如：仓管员"
                        />
                      </label>
                      <label>
                        {`${adjustTypeLabel(adjustmentForm.adjust_type)}原因`}
                        <input
                          value={adjustmentForm.reason}
                          onChange={handleAdjustmentChange('reason')}
                          placeholder={
                            adjustmentForm.adjust_type === 'scrap'
                              ? '如：包装破损 / 过期报废'
                              : '如：入库少记补登'
                          }
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>{adjustTypeLabel(adjustmentForm.adjust_type)}明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addAdjustmentItem}>
                        + 添加一行
                      </button>
                    </div>
                    {adjustmentForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          商品
                          <select value={line.product_id} onChange={handleAdjustmentItemChange(index, 'product_id')}>
                            <option value="">请选择商品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          {`${adjustTypeLabel(adjustmentForm.adjust_type)}数量`}
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handleAdjustmentItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          成本单价
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleAdjustmentItemChange(index, 'unit_price')}
                          />
                        </label>
                        {adjustmentForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeAdjustmentItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {adjustmentForm.items.filter((r) => r.product_id).length} 行 · 合计数量{' '}
                      {adjustmentForm.items
                        .reduce((sum, r) => sum + Math.abs(Number(r.quantity) || 0), 0)
                        .toLocaleString()}{' '}
                      · 合计金额{' '}
                      {adjustmentForm.items
                        .reduce(
                          (sum, r) =>
                            sum + Math.abs(Number(r.quantity) || 0) * (Number(r.unit_price) || 0),
                          0,
                        )
                        .toLocaleString()}
                    </p>

                    <label>
                      备注
                      <input value={adjustmentForm.note} onChange={handleAdjustmentChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">
                      保存{adjustTypeLabel(adjustmentForm.adjust_type)}单
                    </button>
                    <p className="table-hint">
                      报损让库存减少、报溢让库存增加，明细数量一律填正数，方向由上面的类型决定；
                      两者都只调整现存量、不生成应收应付与财务流水，删除单据即把库存还原。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>报损报溢列表</h2>
                    <span className="status-badge">{adjustments.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={adjustmentKeyword}
                      onChange={(event) => setAdjustmentKeyword(event.target.value)}
                      placeholder="按单号 / 经办人 / 原因搜索"
                    />
                    <select
                      value={adjustmentTypeFilter}
                      onChange={(event) => {
                        setAdjustmentTypeFilter(event.target.value);
                        refreshAdjustments(adjustmentKeyword, event.target.value);
                      }}
                    >
                      <option value="">全部类型</option>
                      <option value="scrap">仅报损</option>
                      <option value="overflow">仅报溢</option>
                    </select>
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshAdjustments(adjustmentKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setAdjustmentKeyword('');
                        setAdjustmentTypeFilter('');
                        refreshAdjustments('', '');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {adjustments.length === 0 ? (
                    <div className="empty-state">暂无报损报溢单。报损减库存、报溢加库存，都只动库存不涉财务。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>类型</th>
                            <th>仓库</th>
                            <th>数量</th>
                            <th>金额</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {adjustments.map((row) => (
                            <tr key={row.id}>
                              <td>{row.adjust_no}</td>
                              <td>
                                <span className={row.adjust_type === 'scrap' ? 'num-loss' : 'num-profit'}>
                                  {adjustTypeLabel(row.adjust_type)}
                                </span>
                              </td>
                              <td>
                                {warehouses.find((w) => w.id === row.warehouse_id)?.name || row.warehouse_id}
                              </td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.adjust_date || '—'}</td>
                              <td><span className="status-badge">{adjustmentStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(
                                      `/print/inventory-${row.adjust_type === 'scrap' ? 'scrap' : 'overflow'}/${row.id}`,
                                      `${adjustTypeLabel(row.adjust_type)}单_${row.adjust_no}.pdf`,
                                    )
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/inventory-adjustments/${row.id}`,
                                    label: `${adjustTypeLabel(row.adjust_type)}单 ${row.adjust_no}`,
                                    kind: 'inventory-adjustment',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'production-plan' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增{planTypeLabel(productionPlanForm.plan_type)}生产计划</h2>
                    <span className="status-badge">排产意图 · 不动库存财务</span>
                  </div>

                  <div className="type-switch">
                    {['self', 'outsource'].map((type) => (
                      <button
                        key={type}
                        type="button"
                        className={`type-switch-btn ${productionPlanForm.plan_type === type ? 'active' : ''}`}
                        onClick={() => setProductionPlanForm((prev) => ({ ...prev, plan_type: type }))}
                      >
                        {planTypeLabel(type)}
                        <span className="type-switch-sub">{type === 'self' ? '车间自制' : '外协加工'}</span>
                      </button>
                    ))}
                  </div>

                  <form onSubmit={submitProductionPlan} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        生产仓库
                        <select value={productionPlanForm.warehouse_id} onChange={handlePlanChange('warehouse_id')}>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        车间 / 产线
                        <input
                          value={productionPlanForm.workshop}
                          onChange={handlePlanChange('workshop')}
                          placeholder="如：一号车间"
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        计划日期
                        <input type="date" value={productionPlanForm.plan_date} onChange={handlePlanChange('plan_date')} />
                      </label>
                      <label>
                        计划完工日期
                        <input type="date" value={productionPlanForm.delivery_date} onChange={handlePlanChange('delivery_date')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        计划员
                        <input
                          value={productionPlanForm.handler}
                          onChange={handlePlanChange('handler')}
                          placeholder="如：李计划"
                        />
                      </label>
                      <label>
                        来源订单号
                        <input
                          value={productionPlanForm.source_order_no}
                          onChange={handlePlanChange('source_order_no')}
                          placeholder="按销售订单排产（可空）"
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>计划明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addPlanItem}>
                        + 添加一行
                      </button>
                    </div>
                    {productionPlanForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          成品
                          <select value={line.product_id} onChange={handlePlanItemChange(index, 'product_id')}>
                            <option value="">请选择成品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          计划数量
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handlePlanItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          计划单位成本
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handlePlanItemChange(index, 'unit_price')}
                          />
                        </label>
                        {productionPlanForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removePlanItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {productionPlanForm.items.filter((r) => r.product_id).length} 行 · 计划总量{' '}
                      {productionPlanForm.items
                        .reduce((sum, r) => sum + (Number(r.quantity) || 0), 0)
                        .toLocaleString()}{' '}
                      · 计划金额{' '}
                      {productionPlanForm.items
                        .reduce(
                          (sum, r) => sum + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0),
                          0,
                        )
                        .toLocaleString()}
                    </p>

                    <label>
                      备注
                      <input value={productionPlanForm.note} onChange={handlePlanChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存生产计划</button>
                    <p className="table-hint">
                      生产计划只登记"打算生产什么、什么时候完工"，不写库存也不写财务；
                      保存后在右侧点「MRP 运算」，按 BOM 算出缺哪些料。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>生产计划列表</h2>
                    <span className="status-badge">{productionPlans.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={productionPlanKeyword}
                      onChange={(event) => setProductionPlanKeyword(event.target.value)}
                      placeholder="按单号 / 计划员 / 车间 / 订单号搜索"
                    />
                    <select
                      value={productionPlanTypeFilter}
                      onChange={(event) => {
                        setProductionPlanTypeFilter(event.target.value);
                        refreshProductionPlans(productionPlanKeyword, event.target.value);
                      }}
                    >
                      <option value="">全部类型</option>
                      <option value="self">仅自制</option>
                      <option value="outsource">仅委外</option>
                    </select>
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshProductionPlans(productionPlanKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setProductionPlanKeyword('');
                        setProductionPlanTypeFilter('');
                        refreshProductionPlans('', '');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {productionPlans.length === 0 ? (
                    <div className="empty-state">暂无生产计划。计划只排产不动库存，是 MRP 与领料的起点。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>类型</th>
                            <th>仓库</th>
                            <th>计划量</th>
                            <th>计划金额</th>
                            <th>计划完工</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {productionPlans.map((row) => (
                            <tr key={row.id}>
                              <td>{row.plan_no}</td>
                              <td>{planTypeLabel(row.plan_type)}</td>
                              <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.delivery_date || '—'}</td>
                              <td><span className="status-badge">{productionPlanStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() => {
                                    setMrpForm({
                                      warehouse_id: row.warehouse_id ? String(row.warehouse_id) : '',
                                      plan_id: String(row.id),
                                      items: [{ product_id: '', quantity: '1' }],
                                    });
                                    setMrpResult(null);
                                    setSelectedTab('mrp');
                                  }}
                                >
                                  MRP 运算
                                </button>{' '}
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(`/print/production-plan/${row.id}`, `生产计划单_${row.plan_no}.pdf`)
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/production-plans/${row.id}`,
                                    label: `生产计划 ${row.plan_no}`,
                                    kind: 'production-plan',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'mrp' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>MRP 物料需求运算</h2>
                    <span className="status-badge">按 BOM 展开 · 只算不动账</span>
                  </div>

                  <form onSubmit={runMrp} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        运算仓库
                        <select value={mrpForm.warehouse_id} onChange={handleMrpChange('warehouse_id')}>
                          <option value="">全部仓库（合计现有量）</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        按生产计划运算
                        <select value={mrpForm.plan_id} onChange={handleMrpChange('plan_id')}>
                          <option value="">不使用（手工输入成品）</option>
                          {productionPlans.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.plan_no} · {Number(item.total_quantity || 0)} 件
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    {!mrpForm.plan_id && (
                      <>
                        <div className="section-header">
                          <h3>成品需求</h3>
                          <button type="button" className="secondary-btn small-btn" onClick={addMrpItem}>
                            + 添加一行
                          </button>
                        </div>
                        {mrpForm.items.map((line, index) => (
                          <div className="form-row two-col" key={index}>
                            <label>
                              成品
                              <select value={line.product_id} onChange={handleMrpItemChange(index, 'product_id')}>
                                <option value="">请选择成品</option>
                                {products.map((item) => (
                                  <option key={item.id} value={item.id}>{item.name}</option>
                                ))}
                              </select>
                            </label>
                            <label>
                              需求数量
                              <input
                                type="number"
                                min="0"
                                step="1"
                                value={line.quantity}
                                onChange={handleMrpItemChange(index, 'quantity')}
                              />
                            </label>
                            {mrpForm.items.length > 1 && (
                              <button
                                type="button"
                                className="danger-btn small-btn"
                                onClick={() => removeMrpItem(index)}
                              >
                                移除
                              </button>
                            )}
                          </div>
                        ))}
                      </>
                    )}

                    <button className="primary-btn" type="submit" disabled={mrpBusy}>
                      {mrpBusy ? '运算中…' : '开始 MRP 运算'}
                    </button>
                    <p className="table-hint">
                      MRP 按 BOM 逐层展开：成品 → 半成品 → 原材料，再拿现存量一减得出净需求。
                      运算只在屏幕上进行，不生成任何单据、不动库存与财务。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>运算结果</h2>
                    {mrpResult && <span className="status-badge">{mrpResult.levels} 层 BOM</span>}
                  </div>

                  {!mrpResult ? (
                    <div className="empty-state">
                      还没有运算结果。选好成品数量或一张生产计划，点「开始 MRP 运算」。
                    </div>
                  ) : (
                    <>
                      <div className="mrp-summary">
                        <div className="mrp-metric">
                          <span>需求成品</span>
                          <strong>{mrpResult.summary.demand_lines}</strong>
                        </div>
                        <div className="mrp-metric">
                          <span>物料种类</span>
                          <strong>{mrpResult.summary.material_lines}</strong>
                        </div>
                        <div className={`mrp-metric ${mrpResult.summary.shortage_lines ? 'warn' : ''}`}>
                          <span>缺料种类</span>
                          <strong>{mrpResult.summary.shortage_lines}</strong>
                        </div>
                        <div className={`mrp-metric ${mrpResult.summary.shortage_amount ? 'warn' : ''}`}>
                          <span>缺料金额</span>
                          <strong>¥{Number(mrpResult.summary.shortage_amount || 0).toLocaleString()}</strong>
                        </div>
                      </div>

                      {!mrpResult.bom_ready && (
                        <p className="table-hint">
                          系统里还没有 BOM 数据，本次只按成品本身计算，未展开下层物料。去「BOM 清单」维护配方后再算。
                        </p>
                      )}

                      <div className="wide-table-wrap">
                        <table className="data-table wide-table">
                          <thead>
                            <tr>
                              <th>层级</th>
                              <th>物料</th>
                              <th>规格</th>
                              <th>单位</th>
                              <th>毛需求</th>
                              <th>现存量</th>
                              <th>净需求</th>
                              <th>参考进价</th>
                              <th>缺料金额</th>
                              <th>状态</th>
                            </tr>
                          </thead>
                          <tbody>
                            {mrpResult.rows.map((row) => (
                              <tr
                                key={`${row.level}-${row.product_id}`}
                                className={row.is_product ? 'mrp-product-row' : ''}
                              >
                                <td>{row.level}</td>
                                <td>{row.product_name}</td>
                                <td>{row.standards || '—'}</td>
                                <td>{row.unit || '—'}</td>
                                <td>{Number(row.gross_quantity || 0).toLocaleString()}</td>
                                <td>{Number(row.on_hand || 0).toLocaleString()}</td>
                                <td>{row.is_product ? '—' : Number(row.net_quantity || 0).toLocaleString()}</td>
                                <td>{Number(row.unit_price || 0).toLocaleString()}</td>
                                <td>{row.is_product ? '—' : Number(row.amount || 0).toLocaleString()}</td>
                                <td>
                                  <span
                                    className={
                                      row.is_product
                                        ? 'status-badge'
                                        : Number(row.net_quantity) > 0
                                          ? 'num-loss'
                                          : 'num-profit'
                                    }
                                  >
                                    {mrpStatusLabel(row.status)}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'material-issue' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增生产领料单</h2>
                    <span className="status-badge">材料出库 · 不影响财务</span>
                  </div>

                  <form onSubmit={submitMaterialIssue} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        关联生产计划
                        <select value={materialIssueForm.plan_id} onChange={handleIssueChange('plan_id')}>
                          <option value="">不关联（手工领料）</option>
                          {productionPlans.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.plan_no} · {Number(item.total_quantity || 0)} 件
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        领料仓库
                        <select value={materialIssueForm.warehouse_id} onChange={handleIssueChange('warehouse_id')}>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="section-actions">
                      <button type="button" className="secondary-btn small-btn" onClick={loadIssueSuggestion}>
                        按计划带出领料底稿
                      </button>
                      {issueSuggestionHint && <span className="table-hint">{issueSuggestionHint}</span>}
                    </div>

                    <div className="form-row two-col">
                      <label>
                        领料日期
                        <input type="date" value={materialIssueForm.issue_date} onChange={handleIssueChange('issue_date')} />
                      </label>
                      <label>
                        领料车间
                        <input
                          value={materialIssueForm.workshop}
                          onChange={handleIssueChange('workshop')}
                          placeholder="如：装配车间"
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        领料人
                        <input
                          value={materialIssueForm.handler}
                          onChange={handleIssueChange('handler')}
                          placeholder="如：王师傅"
                        />
                      </label>
                      <label>
                        备注
                        <input value={materialIssueForm.note} onChange={handleIssueChange('note')} />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>领料明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addIssueItem}>
                        + 添加一行
                      </button>
                    </div>
                    {materialIssueForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          材料
                          <select value={line.product_id} onChange={handleIssueItemChange(index, 'product_id')}>
                            <option value="">请选择材料</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          领料数量
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handleIssueItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          单价
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleIssueItemChange(index, 'unit_price')}
                          />
                        </label>
                        {materialIssueForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeIssueItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {materialIssueForm.items.filter((r) => r.product_id).length} 行 · 合计数量{' '}
                      {materialIssueForm.items
                        .reduce((sum, r) => sum + Math.abs(Number(r.quantity) || 0), 0)
                        .toLocaleString()}
                    </p>

                    <button className="primary-btn" type="submit">保存领料单</button>
                    <p className="table-hint">
                      领料把材料从仓库发到车间（减少原料库存），属纯库存单据、不生成应收应付与财务流水；
                      删除单据即把材料退回仓库。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>生产领料列表</h2>
                    <span className="status-badge">{materialIssues.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={materialIssueKeyword}
                      onChange={(event) => setMaterialIssueKeyword(event.target.value)}
                      placeholder="按单号 / 计划号 / 车间 / 领料人搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshMaterialIssues(materialIssueKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setMaterialIssueKeyword('');
                        refreshMaterialIssues('');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {materialIssues.length === 0 ? (
                    <div className="empty-state">暂无生产领料单。领料把材料发到车间（减原料库存），不涉财务。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>关联计划</th>
                            <th>仓库</th>
                            <th>数量</th>
                            <th>金额</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {materialIssues.map((row) => (
                            <tr key={row.id}>
                              <td>{row.issue_no}</td>
                              <td>{row.plan_no || '—'}</td>
                              <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.issue_date || '—'}</td>
                              <td><span className="status-badge">{materialIssueStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(`/print/material-issue/${row.id}`, `生产领料单_${row.issue_no}.pdf`)
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/material-issues/${row.id}`,
                                    label: `生产领料单 ${row.issue_no}`,
                                    kind: 'material-issue',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'material-return' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增生产退料单</h2>
                    <span className="status-badge">余料退回 · 不影响财务</span>
                  </div>

                  <form onSubmit={submitMaterialReturn} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        关联生产计划
                        <select value={materialReturnForm.plan_id} onChange={handleReturnChange('plan_id')}>
                          <option value="">不关联（手工退料）</option>
                          {productionPlans.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.plan_no} · {Number(item.total_quantity || 0)} 件
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        退料仓库
                        <select value={materialReturnForm.warehouse_id} onChange={handleReturnChange('warehouse_id')}>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退料日期
                        <input type="date" value={materialReturnForm.return_date} onChange={handleReturnChange('return_date')} />
                      </label>
                      <label>
                        退料车间
                        <input
                          value={materialReturnForm.workshop}
                          onChange={handleReturnChange('workshop')}
                          placeholder="如：装配车间"
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        退料人
                        <input
                          value={materialReturnForm.handler}
                          onChange={handleReturnChange('handler')}
                          placeholder="如：王师傅"
                        />
                      </label>
                      <label>
                        退料原因
                        <input
                          value={materialReturnForm.reason}
                          onChange={handleReturnChange('reason')}
                          placeholder="如：余料退回 / 领错料退回"
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>退料明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addReturnItem}>
                        + 添加一行
                      </button>
                    </div>
                    {materialReturnForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          材料
                          <select value={line.product_id} onChange={handleReturnItemChange(index, 'product_id')}>
                            <option value="">请选择材料</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          退料数量
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handleReturnItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          单价
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleReturnItemChange(index, 'unit_price')}
                          />
                        </label>
                        {materialReturnForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeReturnItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {materialReturnForm.items.filter((r) => r.product_id).length} 行 · 合计数量{' '}
                      {materialReturnForm.items
                        .reduce((sum, r) => sum + Math.abs(Number(r.quantity) || 0), 0)
                        .toLocaleString()}
                    </p>

                    <label>
                      备注
                      <input value={materialReturnForm.note} onChange={handleReturnChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存退料单</button>
                    <p className="table-hint">
                      退料把车间余料退回仓库（增加原料库存），是领料的反向单据，同样不写财务；
                      删除单据即把退回的料再扣回车间。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>生产退料列表</h2>
                    <span className="status-badge">{materialReturns.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={materialReturnKeyword}
                      onChange={(event) => setMaterialReturnKeyword(event.target.value)}
                      placeholder="按单号 / 计划号 / 车间 / 原因搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshMaterialReturns(materialReturnKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setMaterialReturnKeyword('');
                        refreshMaterialReturns('');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {materialReturns.length === 0 ? (
                    <div className="empty-state">暂无生产退料单。退料把车间余料退回仓库（加原料库存），不涉财务。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>关联计划</th>
                            <th>仓库</th>
                            <th>数量</th>
                            <th>金额</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {materialReturns.map((row) => (
                            <tr key={row.id}>
                              <td>{row.return_no}</td>
                              <td>{row.plan_no || '—'}</td>
                              <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.return_date || '—'}</td>
                              <td><span className="status-badge">{materialReturnStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(`/print/material-return/${row.id}`, `生产退料单_${row.return_no}.pdf`)
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/material-returns/${row.id}`,
                                    label: `生产退料单 ${row.return_no}`,
                                    kind: 'material-return',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'finished-goods' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增成品入库单</h2>
                    <span className="status-badge">成品入库 · 结转生产成本</span>
                  </div>

                  <form onSubmit={submitFinishedGoods} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        关联生产计划
                        <select value={finishedGoodsForm.plan_id} onChange={handleFinishedGoodsChange('plan_id')}>
                          <option value="">不关联（手工入库）</option>
                          {productionPlans.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.plan_no} · {Number(item.total_quantity || 0)} 件
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        入库仓库
                        <select value={finishedGoodsForm.warehouse_id} onChange={handleFinishedGoodsChange('warehouse_id')}>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        入库日期
                        <input type="date" value={finishedGoodsForm.receipt_date} onChange={handleFinishedGoodsChange('receipt_date')} />
                      </label>
                      <label>
                        生产车间
                        <input
                          value={finishedGoodsForm.workshop}
                          onChange={handleFinishedGoodsChange('workshop')}
                          placeholder="如：总装车间"
                        />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        交库人
                        <input
                          value={finishedGoodsForm.handler}
                          onChange={handleFinishedGoodsChange('handler')}
                          placeholder="如：李班长"
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>入库成品明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addFinishedGoodsItem}>
                        + 添加一行
                      </button>
                    </div>
                    {finishedGoodsForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          成品
                          <select value={line.product_id} onChange={handleFinishedGoodsItemChange(index, 'product_id')}>
                            <option value="">请选择成品</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          入库数量
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handleFinishedGoodsItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          单位成本
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleFinishedGoodsItemChange(index, 'unit_price')}
                          />
                        </label>
                        {finishedGoodsForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeFinishedGoodsItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      共 {finishedGoodsForm.items.filter((r) => r.product_id).length} 行 · 合计数量{' '}
                      {finishedGoodsForm.items
                        .reduce((sum, r) => sum + Math.abs(Number(r.quantity) || 0), 0)
                        .toLocaleString()}
                      　·　合计成本{' '}
                      {finishedGoodsForm.items
                        .reduce(
                          (sum, r) =>
                            sum + Math.abs(Number(r.quantity) || 0) * (Number(r.unit_price) || 0),
                          0,
                        )
                        .toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>

                    <label>
                      备注
                      <input value={finishedGoodsForm.note} onChange={handleFinishedGoodsChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存入库单</button>
                    <p className="table-hint">
                      成品入库让成品现存量增加，并按入库成本结转生产成本（成本口径流水，不影响应收应付）；
                      删除单据即把成品扣回车间并冲销成本流水。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>成品入库列表</h2>
                    <span className="status-badge">{finishedGoodsList.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={finishedGoodsKeyword}
                      onChange={(event) => setFinishedGoodsKeyword(event.target.value)}
                      placeholder="按单号 / 计划号 / 车间 / 交库人搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshFinishedGoods(finishedGoodsKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setFinishedGoodsKeyword('');
                        refreshFinishedGoods('');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {finishedGoodsList.length === 0 ? (
                    <div className="empty-state">暂无成品入库单。成品入库让成品库存增加，并结转生产成本。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>关联计划</th>
                            <th>仓库</th>
                            <th>数量</th>
                            <th>入库成本</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {finishedGoodsList.map((row) => (
                            <tr key={row.id}>
                              <td>{row.receipt_no}</td>
                              <td>{row.plan_no || '—'}</td>
                              <td>{warehouses.find((w) => w.id === row.warehouse_id)?.name || '—'}</td>
                              <td>{Number(row.total_quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.receipt_date || '—'}</td>
                              <td><span className="status-badge">{finishedGoodsStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(`/print/finished-goods/${row.id}`, `成品入库单_${row.receipt_no}.pdf`)
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/finished-goods/${row.id}`,
                                    label: `成品入库单 ${row.receipt_no}`,
                                    kind: 'finished-goods',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'outsourcing' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增委外加工单</h2>
                    <span className="status-badge">发料 + 收成品 · 加工费挂应付</span>
                  </div>

                  <form onSubmit={submitOutsourcing} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        外协厂
                        <select value={outsourcingForm.supplier_id} onChange={handleOutsourcingChange('supplier_id')}>
                          <option value="">请选择外协厂</option>
                          {suppliers.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        发料 / 收料仓
                        <select value={outsourcingForm.warehouse_id} onChange={handleOutsourcingChange('warehouse_id')}>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        加工日期
                        <input type="date" value={outsourcingForm.order_date} onChange={handleOutsourcingChange('order_date')} />
                      </label>
                      <label>
                        经办人
                        <input
                          value={outsourcingForm.handler}
                          onChange={handleOutsourcingChange('handler')}
                          placeholder="如：采购张工"
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>加工产出（收回成品）</h3>
                    </div>
                    <div className="form-row three-col">
                      <label>
                        产出成品
                        <select value={outsourcingForm.product_id} onChange={handleOutsourcingChange('product_id')}>
                          <option value="">请选择成品</option>
                          {products.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        收回数量
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={outsourcingForm.quantity}
                          onChange={handleOutsourcingChange('quantity')}
                        />
                      </label>
                      <label>
                        成品单位成本
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={outsourcingForm.unit_price}
                          onChange={handleOutsourcingChange('unit_price')}
                        />
                      </label>
                    </div>

                    <div className="section-header">
                      <h3>发出材料明细</h3>
                      <button type="button" className="secondary-btn small-btn" onClick={addOutsourcingItem}>
                        + 添加一行
                      </button>
                    </div>
                    {outsourcingForm.items.map((line, index) => (
                      <div className="form-row three-col" key={index}>
                        <label>
                          材料
                          <select value={line.product_id} onChange={handleOutsourcingItemChange(index, 'product_id')}>
                            <option value="">请选择材料</option>
                            {products.map((item) => (
                              <option key={item.id} value={item.id}>{item.name}</option>
                            ))}
                          </select>
                          {renderStockHint(line.product_id)}
                        </label>
                        <label>
                          发出数量
                          <input
                            type="number"
                            min="0"
                            step="1"
                            value={line.quantity}
                            onChange={handleOutsourcingItemChange(index, 'quantity')}
                          />
                        </label>
                        <label>
                          单价
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={handleOutsourcingItemChange(index, 'unit_price')}
                          />
                        </label>
                        {outsourcingForm.items.length > 1 && (
                          <button
                            type="button"
                            className="danger-btn small-btn"
                            onClick={() => removeOutsourcingItem(index)}
                          >
                            移除
                          </button>
                        )}
                      </div>
                    ))}
                    <p className="table-hint">
                      发出材料 {outsourcingForm.items.filter((r) => r.product_id).length} 行 · 合计发出数量{' '}
                      {outsourcingForm.items
                        .reduce((sum, r) => sum + Math.abs(Number(r.quantity) || 0), 0)
                        .toLocaleString()}
                    </p>

                    <div className="form-row two-col">
                      <label>
                        加工费（应付外协厂）
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={outsourcingForm.process_fee}
                          onChange={handleOutsourcingChange('process_fee')}
                        />
                      </label>
                    </div>

                    <label>
                      备注
                      <input value={outsourcingForm.note} onChange={handleOutsourcingChange('note')} />
                    </label>

                    <button className="primary-btn" type="submit">保存委外加工单</button>
                    <p className="table-hint">
                      委外加工一张单两个方向：发出材料减少原材料库存、收回成品增加成品库存，
                      并按加工费对外协厂产生应付；删除单据即一次性全冲。
                    </p>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>委外加工列表</h2>
                    <span className="status-badge">{outsourcings.length} 张</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={outsourcingKeyword}
                      onChange={(event) => setOutsourcingKeyword(event.target.value)}
                      placeholder="按单号 / 成品 / 经办人搜索"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshOutsourcings(outsourcingKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setOutsourcingKeyword('');
                        refreshOutsourcings('');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  {outsourcings.length === 0 ? (
                    <div className="empty-state">暂无委外加工单。委外加工发料出库、收回成品入库，并按加工费挂应付。</div>
                  ) : (
                    <div className="wide-table-wrap">
                      <table className="data-table wide-table">
                        <thead>
                          <tr>
                            <th>单号</th>
                            <th>外协厂</th>
                            <th>产出成品</th>
                            <th>收回数量</th>
                            <th>加工费</th>
                            <th>发出材料</th>
                            <th>日期</th>
                            <th>状态</th>
                            <th>操作</th>
                          </tr>
                        </thead>
                        <tbody>
                          {outsourcings.map((row) => (
                            <tr key={row.id}>
                              <td>{row.order_no}</td>
                              <td>{suppliers.find((s) => s.id === row.supplier_id)?.name || '—'}</td>
                              <td>{row.product_name || '—'}</td>
                              <td>{Number(row.quantity || 0).toLocaleString()}</td>
                              <td>{Number(row.process_fee || 0).toLocaleString()}</td>
                              <td>{Number(row.total_amount || 0).toLocaleString()}</td>
                              <td>{row.order_date || '—'}</td>
                              <td><span className="status-badge">{outsourcingStatusLabel(row.status)}</span></td>
                              <td className="row-actions">
                                <button
                                  type="button"
                                  className="secondary-btn small-btn"
                                  onClick={() =>
                                    printPdf(`/print/outsourcing/${row.id}`, `委外加工单_${row.order_no}.pdf`)
                                  }
                                >
                                  打印
                                </button>{' '}
                                <button
                                  type="button"
                                  className="danger-btn"
                                  onClick={() => setConfirmDelete({
                                    id: row.id,
                                    endpoint: `/outsourcings/${row.id}`,
                                    label: `委外加工单 ${row.order_no}`,
                                    kind: 'outsourcing',
                                  })}
                                >
                                  删除
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'settings' && (
              <section className="panel form-panel">
                <div className="section-header">
                  <h2>公司信息</h2>
                  <span className="status-badge">打印抬头</span>
                </div>
                <p className="settings-hint">
                  这里填公司抬头信息，购销合同、对账单等打印件会自动带出。信息保存在程序目录下的
                  company.json，改完立即生效，不需要重启服务。
                </p>

                <form onSubmit={submitCompanySettings} className="erp-form">
                  <div className="form-row two-col">
                    <label>
                      公司名称
                      <input
                        value={companyForm.own_name}
                        onChange={handleCompanyChange('own_name')}
                        placeholder="营业执照上的全称"
                      />
                    </label>
                    <label>
                      纳税人识别号
                      <input
                        value={companyForm.own_tax_no}
                        onChange={handleCompanyChange('own_tax_no')}
                        placeholder="统一社会信用代码"
                      />
                    </label>
                  </div>

                  <div className="form-row two-col">
                    <label>
                      法定代表人
                      <input value={companyForm.own_legal_person} onChange={handleCompanyChange('own_legal_person')} />
                    </label>
                    <label>
                      联系电话
                      <input value={companyForm.own_phone} onChange={handleCompanyChange('own_phone')} />
                    </label>
                  </div>

                  <div className="form-row two-col">
                    <label>
                      联系人
                      <input value={companyForm.own_contact} onChange={handleCompanyChange('own_contact')} />
                    </label>
                    <label>
                      注册地址
                      <input value={companyForm.own_address} onChange={handleCompanyChange('own_address')} />
                    </label>
                  </div>

                  <div className="form-row two-col">
                    <label>
                      开户银行
                      <input value={companyForm.own_bank_name} onChange={handleCompanyChange('own_bank_name')} />
                    </label>
                    <label>
                      银行账号
                      <input value={companyForm.own_bank_account} onChange={handleCompanyChange('own_bank_account')} />
                    </label>
                  </div>

                  <button className="primary-btn" type="submit">保存公司信息</button>
                  <button
                    className="secondary-btn"
                    type="button"
                    style={{ marginLeft: 10 }}
                    onClick={loadCompanySettings}
                  >
                    重新载入
                  </button>
                </form>
              </section>
            )}

            {selectedTab === 'inventory' && (
              <div className="management-grid">
                {inventoryFocus && (
                  <div className="focus-banner">
                    <span className="focus-banner-tag">来自「{inventoryFocus.from}」</span>
                    <span className="focus-banner-text">
                      已按 <strong>{inventoryFocus.keyword || inventoryFocus.productName || '该商品'}</strong> 筛选现存量
                      {inventoryFocus.sku ? `（SKU ${inventoryFocus.sku}）` : ''}
                    </span>
                    <button type="button" className="link-btn" onClick={clearInventoryFocus}>清除筛选</button>
                  </div>
                )}

                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>出入库登记</h2>
                    <span className="status-badge">手工调整库存</span>
                  </div>

                  <form onSubmit={submitInventory} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        商品
                        <select value={inventoryForm.product_id} onChange={handleInventoryChange('product_id')} required>
                          <option value="">请选择商品</option>
                          {products.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                        {renderStockHint(inventoryForm.product_id)}
                      </label>
                      <label>
                        仓库
                        <select value={inventoryForm.warehouse_id} onChange={handleInventoryChange('warehouse_id')} required>
                          <option value="">请选择仓库</option>
                          {warehouses.map((item) => (
                            <option key={item.id} value={item.id}>{item.name}</option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        类型
                        <select value={inventoryForm.transaction_type} onChange={handleInventoryChange('transaction_type')}>
                          <option value="inbound">入库</option>
                          <option value="outbound">出库</option>
                        </select>
                      </label>
                      <label>
                        数量
                        <input type="number" min="1" value={inventoryForm.quantity} onChange={handleInventoryChange('quantity')} required />
                      </label>
                    </div>

                    <label>
                      单价
                      <input type="number" step="0.01" value={inventoryForm.unit_price} onChange={handleInventoryChange('unit_price')} />
                    </label>

                    <button className="primary-btn" type="submit">保存库存记录</button>
                  </form>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>现存量</h2>
                    <span className="status-badge">{stockData.summary.stock_lines || 0} 条</span>
                  </div>

                  <div className="contract-search">
                    <input
                      value={inventoryKeyword}
                      onChange={(event) => {
                        setInventoryKeyword(event.target.value);
                        refreshStock(event.target.value);
                      }}
                      placeholder="按商品名称 / SKU 搜索现存量"
                    />
                    <button type="button" className="secondary-btn small-btn" onClick={() => refreshStock(inventoryKeyword)}>
                      查询
                    </button>
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => {
                        setInventoryKeyword('');
                        setInventoryFocus(null);
                        refreshStock('');
                      }}
                    >
                      重置
                    </button>
                  </div>

                  <div className="stock-kpis">
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">库存总量</span>
                      <strong>{Number(stockData.summary.total_quantity || 0).toLocaleString()}</strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">库存金额（成本）</span>
                      <strong>¥{Number(stockData.summary.estimated_value || 0).toLocaleString()}</strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">缺货</span>
                      <strong className="num-negative">{stockData.summary.shortage_count || 0}</strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">低库存</span>
                      <strong>{stockData.summary.low_stock_count || 0}</strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">积压</span>
                      <strong>{stockData.summary.overstock_count || 0}</strong>
                    </div>
                  </div>

                  {(stockData.rows || []).length === 0 ? (
                    <div className="empty-state">暂无库存数据，开一张采购单就会自动入库</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>仓库</th>
                          <th>商品</th>
                          <th>规格</th>
                          <th>现存量</th>
                          <th>下限</th>
                          <th>上限</th>
                          <th>状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(stockData.rows || []).map((row) => (
                          <tr key={`${row.warehouse_id}-${row.product_id}`}>
                            <td>{row.warehouse_name}</td>
                            <td>{row.product_name}</td>
                            <td>{row.standards || '—'}</td>
                            <td className={row.quantity < 0 ? 'num-negative' : undefined}>
                              {row.quantity}{row.unit ? ` ${row.unit}` : ''}
                            </td>
                            <td>{row.stock_lower ?? '—'}</td>
                            <td>{row.stock_upper ?? '—'}</td>
                            <td>
                              <span className={`stock-tag ${row.status}`}>{stockStatusLabel(row.status)}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>库存流水</h2>
                    <span className="status-badge">{inventory.length} 条</span>
                  </div>

                  {inventory.length === 0 ? (
                    <div className="empty-state">暂无库存记录</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>来源单号</th>
                          <th>产品</th>
                          <th>类型</th>
                          <th>数量</th>
                          <th>单价</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventory.map((row) => (
                          <tr key={row.id}>
                            <td>{row.doc_no || '手工登记'}</td>
                            <td>{row.product_id}</td>
                            <td>{row.transaction_type === 'inbound' ? '入库' : '出库'}</td>
                            <td>{row.quantity}</td>
                            <td>¥{Number(row.unit_price || 0).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>
            )}

            {selectedTab === 'agent' && (
              <div className="management-grid">
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>移动智能体助手</h2>
                    <span className="status-badge">iOS / Android / AI</span>
                  </div>

                  <div className="erp-form">
                    <label>
                      询问内容
                      <textarea value={agentPrompt} onChange={(event) => setAgentPrompt(event.target.value)} rows="4" />
                    </label>
                    <button className="primary-btn" type="button" onClick={submitAgentPrompt}>启动智能分析</button>
                  </div>
                </section>

                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>分析结果</h2>
                    <span className="status-badge">{agentResponse.risk_level || '健康'}</span>
                  </div>

                  <div className="agent-card">
                    <p>{agentResponse.answer || '尚未进行分析。'}</p>
                    <div className="agent-summary-grid">
                      <div className="metric-card">
                        <span>销售额</span>
                        <strong>¥{Number(agentResponse.summary.sales_total || 0).toLocaleString()}</strong>
                      </div>
                      <div className="metric-card">
                        <span>采购额</span>
                        <strong>¥{Number(agentResponse.summary.purchase_total || 0).toLocaleString()}</strong>
                      </div>
                      <div className="metric-card">
                        <span>毛利率</span>
                        <strong>{Number(agentResponse.summary.gross_margin_rate || 0).toFixed(1)}%</strong>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            )}

            {notice && <div className="notice-box">{notice}</div>}

            {confirmDelete && (
              <div className="modal-backdrop" onClick={() => setConfirmDelete(null)}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>删除确认</h3>
                    <button type="button" className="close-btn" onClick={() => setConfirmDelete(null)}>×</button>
                  </div>
                  <p className="confirm-text">确定要删除「{confirmDelete.label}」吗？</p>
                  {confirmDelete.kind === 'bom' && (
                    <p className="confirm-hint">BOM 节点是树形结构，删除会连同其子节点一起删除。</p>
                  )}
                  {confirmDelete.kind === 'sales-order' && (
                    <p className="confirm-hint">订单明细也会一并删除。</p>
                  )}
                  {confirmDelete.kind === 'contract' && (
                    <p className="confirm-hint">合同明细（标的物清单）也会一并删除。</p>
                  )}
                  {confirmDelete.force && (
                    <div className="confirm-blocked">
                      <p className="confirm-hint">{confirmDelete.blockedReason}</p>
                      <p className="confirm-hint">
                        {confirmDelete.kind === 'contract'
                          ? '强制删除只移除合同本身，已生成的单据与库存、财务流水保持不变。'
                          : '强制删除只移除档案本身，历史单据里保存的名称快照仍然保留。'}
                      </p>
                    </div>
                  )}
                  <div className="modal-actions">
                    <button type="button" className="secondary-btn" onClick={() => setConfirmDelete(null)}>取消</button>
                    <button type="button" className="danger-btn" onClick={handleDeleteConfirm}>
                      {confirmDelete.force ? '强制删除' : '确认删除'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default App;
