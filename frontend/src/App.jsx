import { API_BASE, APP_VERSION, APP_CACHE, APP_VERSION_LABEL, APP_BUILD_AT, APP_HASH, NAV_THEMES, emptyCustomerForm, emptyProductForm, emptyOrderItem, emptyPurchaseOrderForm, emptySalesOrderForm, emptyInboundForm, emptyOutboundForm, DOC_STATUS_LABELS, OUTBOUND_STATUS_LABELS, emptySupplierForm, emptyWarehouseForm, emptyEmployeeForm, LEDGER_ALIASES, STATEMENT_ALIASES, BANK_ACCOUNT_TYPE_LABEL, emptyBankAccountForm, emptyBankTransferForm, emptyEntryForm, emptyEntryQuery, emptyAssemblyForm, OPENING_TABS, emptyOpeningDraft, emptyContractForm, CONTRACT_STATUS_LABEL, contractStatusLabel, emptyQuotationForm, QUOTATION_STATUS_LABEL, quotationStatusLabel, emptyPurchaseReturnForm, PURCHASE_RETURN_STATUS_LABEL, purchaseReturnStatusLabel, emptySalesReturnForm, SALES_RETURN_STATUS_LABEL, salesReturnStatusLabel, emptyTransferForm, TRANSFER_STATUS_LABEL, transferStatusLabel, emptyStocktakingForm, STOCKTAKING_STATUS_LABEL, stocktakingStatusLabel, emptyAdjustmentForm, ADJUSTMENT_STATUS_LABEL, adjustmentStatusLabel, ADJUST_TYPE_LABEL, ADJUST_TYPE_DIRECTION, adjustTypeLabel, emptyProductionPlanForm, PLAN_TYPE_LABEL, planTypeLabel, PRODUCTION_PLAN_STATUS_LABEL, productionPlanStatusLabel, MRP_STATUS_LABEL, mrpStatusLabel, emptyMaterialIssueForm, MATERIAL_ISSUE_STATUS_LABEL, materialIssueStatusLabel, emptyMaterialReturnForm, MATERIAL_RETURN_STATUS_LABEL, materialReturnStatusLabel, emptyFinishedGoodsForm, FINISHED_GOODS_STATUS_LABEL, finishedGoodsStatusLabel, emptyOutsourcingForm, OUTSOURCING_STATUS_LABEL, outsourcingStatusLabel, REPORT_SHAPE_LABEL, emptyReportQuery, money, plain, emptyInventoryForm, STOCK_STATUS_LABEL, stockStatusLabel, DOC_TYPE_LABEL, docTypeLabel, financeTypeLabel, PROJECT_STATUS_LABEL, PROJECT_STATUS_TONE, emptyStockLogFilter, emptyFinanceForm, emptySystemUserForm, emptyRoleForm, emptyDepartmentForm, emptyPermissionDraft, emptyMenuForm, SYSTEM_TABS, PARAM_VALUE_TYPE_LABEL, emptyParamForm, emptyDictionaryForm, emptyDictItemForm, LOOKUP_TYPES, emptyTemplateDraft, emptyLogQuery, LOG_STATUS_TONE, formatLogTime, isTemplateCustomized, readCompanyFromToken } from './lib/appLib';
import ResizableLayout from './components/resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from './components/ui/ErpSearchSelect.jsx';
import PartnerModal from './components/partners/PartnerModal.jsx';
// 订单收/付款登记弹窗（2026-10-18）：补上「前端从不调用 /finance/receipt|payment」这条断链。
// 受控组件：自己不发请求，POST 在本文件 submitOrderPayment 里做。
import OrderPaymentDialog from './components/docs/OrderPaymentDialog.jsx';
// 打印二次确认（2026-10-18，需求 3）：宿主挂在下面弹窗区；调用口是 lib/printConfirm.js 的单例，
// 这样 `printPdf`（唯一收敛点）和 StatementEditor 自带的打印都能共用同一个确认框。
import PrintConfirmHost from './components/ui/PrintConfirmHost.jsx';
import { confirmPrint, confirmDanger } from './lib/printConfirm.js';
import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { countProductsByCategory, filterProductsByCategory } from './lib/productCategory';
// 接口错误文案统一解析（422 的 detail 是数组，直接渲染会白屏 —— v76 事故）
import { parseApiDetail } from './lib/apiDetail.js';
import { findDuplicateName, findSimilarNames } from './lib/nameGuard.js';
// 左侧树 ↔ 右侧列表的三态选中契约（null 未选 / ALL 全部 / 具体 id）
import { ALL } from './lib/treeSelection';
// 明细行空行/半填判定（2026-10-17 边界测试）：纯函数，页面与提交口共用同一套口径
import { inspectItemRows } from './lib/orderLines';
import { serializeUnits } from './lib/productUnits';
// 单据明细行的「单位」下拉复用 3c 的单位选项构造（含基础单位、过滤停用与脏 factor）
import { buildUnitOptions } from './lib/salesUnits';
import { ProductCategoryTree } from './components/product-category';
import { ProductEditModal } from './components/product-edit';
import jsQR from 'jsqr';
import * as pdfjsLib from 'pdfjs-dist';
import Tesseract from 'tesseract.js';
import * as XLSX from 'xlsx';
import AgentPage from './pages/AgentPage';
import AnalysisPage from './pages/AnalysisPage';
import AssemblyPage from './pages/AssemblyPage';
import BankPage from './pages/BankPage';
import BomPage from './pages/BomPage';
import ContractsPage from './pages/ContractsPage';
// 第 13 批（第三阶段）：合同台账 —— 独立自包含组件，不依赖 appCtx。
// 与上面的「购销合同」是两个页面：那个逐条填 A2 条款、开单；这个看/筛/导出/挂原件。
// ⚠️ 懒加载：本页带着明细编辑表 + OCR 面板，静态引入会把约 10KB gzip 塞进首屏主包，
//    而它只在「销售管理 → 合同台账」这一条路径上用得到（与 MenusPage 的 MenuTreeEditor 同一口径）。
const ContractsLedger = lazy(() => import('./components/contracts/ContractsLedger.jsx'));
// 第 13 批（第三阶段第三步）：增强版对账单编辑器。
// 同样是自包含组件（自己取数、不读 ctx），懒加载 —— 这一页带 6 张汇总卡 + 明细编辑表，
// 只有「销售管理 → 增强对账单」这条路径用得到，不该进首屏主包。
const StatementEditor = lazy(() => import('./components/statements/StatementEditor.jsx'));
import CustomersPage from './pages/CustomersPage';
import DataioPage from './pages/DataioPage';
import DictionariesPage from './pages/DictionariesPage';
import FinancePage from './pages/FinancePage';
import ThreeWayMatchPage from './pages/ThreeWayMatchPage';
import FinishedGoodsPage from './pages/FinishedGoodsPage';
import IncomeExpensePage from './pages/IncomeExpensePage';
import InventoryPage from './pages/InventoryPage';
import InvoicesPage from './pages/InvoicesPage';
import LogsPage from './pages/LogsPage';
import LossOverflowPage from './pages/LossOverflowPage';
import MaterialIssuePage from './pages/MaterialIssuePage';
import MaterialReturnPage from './pages/MaterialReturnPage';
import MenusPage from './pages/MenusPage';
import MobilePage from './pages/MobilePage';
import MrpPage from './pages/MrpPage';
import OpeningStockPage from './pages/OpeningStockPage';
import OutsourcingPage from './pages/OutsourcingPage';
import OverviewPage from './pages/OverviewPage';
import ParamsPage from './pages/ParamsPage';
import PrintTemplatesPage from './pages/PrintTemplatesPage';
import ProductionPage from './pages/ProductionPage';
import ProductionPlanPage from './pages/ProductionPlanPage';
import ProductsPage from './pages/ProductsPage';
import ProjectsPage from './pages/ProjectsPage';
import PurchaseOrderPage from './pages/PurchaseOrderPage';
import PurchasePage from './pages/PurchasePage';
import PurchaseReturnPage from './pages/PurchaseReturnPage';
import QuotationPage from './pages/QuotationPage';
import ReportsPage from './pages/ReportsPage';
import SalesOrderPage from './pages/SalesOrderPage';
import SalesPage from './pages/SalesPage';
import SalesReturnPage from './pages/SalesReturnPage';
import SettingsPage from './pages/SettingsPage';
import StaffPage from './pages/StaffPage';
import StockAlertPage from './pages/StockAlertPage';
import StocktakingPage from './pages/StocktakingPage';
import SuppliersPage from './pages/SuppliersPage';
import TransferPage from './pages/TransferPage';
import UsersPage from './pages/UsersPage';
import WarehousesPage from './pages/WarehousesPage';

/**
 * 明细行 / 表单字段的取值统一入口。
 *
 * 原生控件给的是 event（`event.target.value`），而 ErpSearchSelect 这类可搜索下拉
 * 直接抛原始值（product_id 本身，没有 target）。两种入参都要能吃。
 *
 * 放在模块级而不是组件内：有十几个 handler 定义在组件前段（比组件内定义的
 * `readChangeValue` 位置更靠前），虽然事件回调是渲染后才跑、TDZ 不会真的炸，
 * 但把纯函数提到模块级更稳，也省得以后调整顺序时踩雷。
 */
export const readChangeValue = (input) =>
  (input && typeof input === 'object' && 'target' in input ? input.target.value : input);

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
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
      { key: 'staff', label: '员工档案' },
      { key: 'opening-stock', label: '商品期初库存' },
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
      { key: 'purchase-statement', label: '采购对账单' },
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
      // 第 13 批：合同台账（进/出双向台账 + 导出 + 原件 + OCR 展示区）。
      // ⚠️ 必须追加在**组末**：后端 `PERMISSION_CATALOG` 按 items 下标 ×10 生成 sort_order，
      // 插在中间会与既有行撞号（`_backfill_builtin_menus` 只补不改不重编号）。
      { key: 'contracts-ledger', label: '合同台账' },
      // 第 13 批第三步：增强对账单（真表 + 勾选核对 + 打印/导出）。
      // 同样**只能追加在组末**（后端 sort_order = items 下标 × 10）。
      { key: 'statements-editor', label: '增强对账单' },
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
      { key: 'assembly', label: '组合拆卸' },
      { key: 'loss-overflow', label: '报损报溢' },
      { key: 'stock-alert', label: '库存预警' },
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
      { key: 'general-ledger', label: '总账' },
      { key: 'bank', label: '现金银行' },
      { key: 'income-expense', label: '日常收支' },
      { key: 'payroll', label: '工资管理', todo: true },
      { key: 'invoices', label: '发票管理' },
      // 三单匹配（2026-10-23）：合同/发票/付款 三方对账看板。
      // ⚠️ 只能追加在组末（后端 sort_order = items 下标 × 10）
      { key: 'three-way-match', label: '三单匹配' },
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
      { key: 'users', label: '用户角色' },
      { key: 'params', label: '参数设置' },
      { key: 'dictionaries', label: '数字字典' },
      { key: 'print-templates', label: '打印模板' },
      { key: 'logs', label: '操作日志' },
      { key: 'menus', label: '菜单管理' },
    ],
  },
];

// 扁平视图：供顶栏标题查找、权限过滤等按 key 检索的场景使用
const tabs = menuGroups.flatMap((group) =>
  group.items.map((item) => ({ ...item, group: group.key, groupLabel: group.label })),
);

const pageActions = {
  overview: [
    { label: '经营分析', to: 'analysis', variant: 'secondary' },
    { label: '报表中心', to: 'reports', variant: 'primary' },
  ],

  // 基础资料：档案页的下一步是"拿这个档案去开单 / 去看它的账"
  customers: [
    { label: '往来对账', to: 'ledger', variant: 'secondary' },
    { label: '销售订单', to: 'sales-order', variant: 'primary' },
  ],
  suppliers: [{ label: '采购订单', to: 'purchase-order', variant: 'primary' }],
  products: [
    { label: '商品期初库存', to: 'opening-stock', variant: 'secondary' },
    { label: '库存管理', to: 'inventory', variant: 'primary' },
  ],
  warehouses: [{ label: '商品期初库存', to: 'opening-stock', variant: 'primary' }],

  // 采购：入库与订单是一对，互为上下游
  purchase: [{ label: '采购订单', to: 'purchase-order', variant: 'primary' }],
  'purchase-order': [{ label: '采购入库', to: 'purchase', variant: 'primary' }],
  'purchase-return': [{ label: '采购入库', to: 'purchase', variant: 'primary' }],

  // 销售 —— 参考图里那两颗「新建报价 / 新增订单」本来就属于这里
  sales: [
    { label: '新建报价', to: 'quotation', variant: 'secondary' },
    { label: '新增订单', to: 'sales-order', variant: 'primary' },
  ],
  'sales-order': [
    { label: '新建报价', to: 'quotation', variant: 'secondary' },
    { label: '开单管理', to: 'sales', variant: 'primary' },
  ],
  quotation: [{ label: '销售订单', to: 'sales-order', variant: 'primary' }],
  'sales-return': [{ label: '开单管理', to: 'sales', variant: 'primary' }],
  contracts: [{ label: '销售订单', to: 'sales-order', variant: 'primary' }],

  // 库存
  inventory: [
    { label: '变动查询', to: 'stock-logs', variant: 'secondary' },
    { label: '调拨管理', to: 'transfer', variant: 'primary' },
  ],
  'stock-logs': [{ label: '库存管理', to: 'inventory', variant: 'primary' }],
  transfer: [{ label: '库存管理', to: 'inventory', variant: 'primary' }],
  assembly: [{ label: '库存管理', to: 'inventory', variant: 'primary' }],

  // 生产：计划 → 算料 → 领料 → 入库，顺着业务链往下走
  'production-plan': [{ label: 'MRP 运算', to: 'mrp', variant: 'primary' }],
  mrp: [
    { label: '生产计划', to: 'production-plan', variant: 'secondary' },
    { label: '生产领料', to: 'material-issue', variant: 'primary' },
  ],
  'material-issue': [
    { label: '生产退料', to: 'material-return', variant: 'secondary' },
    { label: '成品入库', to: 'finished-goods', variant: 'primary' },
  ],
  'material-return': [{ label: '生产领料', to: 'material-issue', variant: 'primary' }],
  'finished-goods': [{ label: '委外加工', to: 'outsourcing', variant: 'primary' }],
  outsourcing: [{ label: '成品入库', to: 'finished-goods', variant: 'primary' }],

  // 财务：钱的三条线（流水 / 现金银行 / 日常收支）互相引用得上
  finance: [
    { label: '日常收支', to: 'income-expense', variant: 'secondary' },
    { label: '现金银行', to: 'bank', variant: 'primary' },
  ],
  receivable: [
    { label: '往来对账', to: 'ledger', variant: 'secondary' },
    { label: '财务流水', to: 'finance', variant: 'primary' },
  ],
  payable: [
    { label: '往来对账', to: 'ledger', variant: 'secondary' },
    { label: '财务流水', to: 'finance', variant: 'primary' },
  ],
  ledger: [
    { label: '应收账款', to: 'receivable', variant: 'secondary' },
    { label: '应付账款', to: 'payable', variant: 'primary' },
  ],
  'general-ledger': [
    { label: '财务流水', to: 'finance', variant: 'secondary' },
    { label: '现金银行', to: 'bank', variant: 'primary' },
  ],
  bank: [{ label: '日常收支', to: 'income-expense', variant: 'primary' }],
  'income-expense': [{ label: '现金银行', to: 'bank', variant: 'primary' }],

  // 分析
  reports: [{ label: '经营分析', to: 'analysis', variant: 'primary' }],
  analysis: [{ label: '报表中心', to: 'reports', variant: 'primary' }],
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
  // —— 商品档案：补齐「浩技云商品管理」里的树形类别 / 编辑 / 搜索 ——
  const [productCategories, setProductCategories] = useState([]); // 类别树
  const [productEdit, setProductEdit] = useState(null); // null = 未打开编辑
  const [productSearch, setProductSearch] = useState(''); // 顶部搜索
  const [productBusy, setProductBusy] = useState(''); // 忙碌标记
  const [categoryModal, setCategoryModal] = useState(null); // 类别新增/编辑弹窗，{mode, node}
  // 「上级类别」下拉的受控值（ErpSearchSelect 是受控组件，不能再靠 defaultValue + FormData 读）。
  // 由 openCategoryModal 在打开时初始化；提交时 submitCategory 直接读它。
  const [categoryParentDraft, setCategoryParentDraft] = useState('');
  const [productModalOpen, setProductModalOpen] = useState(false); // 新增产品弹窗
  // 左侧类别树的选中项：null = 全部商品；'__uncategorized__' = 未分类；数字 = 类别 id（含其全部子孙）
  // （折叠/展开是纯展示状态，留在 ProductCategoryTree 组件内部，不占这里的 state）
  const [categoryFilter, setCategoryFilter] = useState(null);
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [salesOrders, setSalesOrders] = useState([]);
  // 采购/销售订单页（doc_type=order）独立数据源，与老出入库页互不干扰
  const [purchaseOrderList, setPurchaseOrderList] = useState([]);
  const [salesOrderList, setSalesOrderList] = useState([]);
  const [selectedPurchaseOrder, setSelectedPurchaseOrder] = useState(null);
  const [selectedSalesOrder, setSelectedSalesOrder] = useState(null);
  const [productionOrders, setProductionOrders] = useState([]);
  const [projects, setProjects] = useState([]);
  // —— 项目模块（补齐"改不了、看不到成本"的断点）——
  const [projectEdit, setProjectEdit] = useState(null); // null = 未打开
  const [projectCost, setProjectCost] = useState(null); // 成本归集弹窗
  const [projectBusy, setProjectBusy] = useState('');
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
  // 第 11 批（发票归拢财务）：单据视角的筛选条件。
  // 筛选放在前端做 —— 发票总量不大，而且列表本来就已经整份加载了，
  // 再往后端要一次只会多一轮往返、还让"切 Tab 立刻响应"变成要等网络。
  const [invoiceQuery, setInvoiceQuery] = useState({
    direction: 'all',
    keyword: '',
    // 2026-10-26：进项专项筛选。supplier_id 按档案比对（抬头文本不可靠），
    // deduction_state 只对进项专票生效（见 invoiceFiltered）。
    supplier_id: '',
    deduction_state: '',
  });
  // ——— 第 13 批（发票管理页改造）———
  // 展开的明细子行（一张票的明细列不进主行，用子行展开 —— 列太多会横向挤爆）
  const [expandedInvoiceIds, setExpandedInvoiceIds] = useState([]);
  // 分页：用户要"每页有左下角给出全选框"，那就先得有"每页"的概念
  const [invoicePage, setInvoicePage] = useState(1);
  const [invoicePageSize, setInvoicePageSize] = useState(10);
  // 右上角导出按钮点开后的菜单
  const [invoiceExportOpen, setInvoiceExportOpen] = useState(false);
  // 三个弹窗：看真实发票原件 / 二维码 / 编辑
  const [invoicePreview, setInvoicePreview] = useState(null); // {item, url, mime}
  const [invoiceQr, setInvoiceQr] = useState(null); // {item, dataUrl, origin}
  const [invoiceEditForm, setInvoiceEditForm] = useState(null); // null = 未打开
  const [invoiceBusy, setInvoiceBusy] = useState(''); // 正在跑的异步动作，用来禁用按钮
  // 按进销项汇总张数与金额（单据页顶部的三个徽章、以及经营分析页的跳转卡都用它）
  const invoiceDirectionCounts = useMemo(() => {
    const init = () => ({ count: 0, amount: 0 });
    const result = { input: init(), output: init(), unknown: init() };
    invoiceItems.forEach((item) => {
      const bucket = result[item.direction] || result.unknown;
      bucket.count += 1;
      bucket.amount += Number(item.amount || 0);
    });
    return result;
  }, [invoiceItems]);

  // 单据页的筛选：方向 Tab + 关键字 + 供应商/认证状态。都只作用在视图上，不改数据。
  const invoiceFiltered = useMemo(() => {
    const keyword = invoiceQuery.keyword.trim().toLowerCase();
    const stateFilter = invoiceQuery.deduction_state || '';
    return invoiceItems.filter((item) => {
      if (invoiceQuery.direction !== 'all' && item.direction !== invoiceQuery.direction) return false;
      // 供应商筛选按档案 id 比对：票面上的抬头是文本，同一家常有多个写法。
      if (
        invoiceQuery.supplier_id &&
        String(item.supplier_id ?? '') !== String(invoiceQuery.supplier_id)
      ) {
        return false;
      }
      if (stateFilter) {
        // 认证/抵扣只对**进项专票**存在。不先挡掉销项票与普票的话，
        // 选「未认证」会把这个库里所有普票都列出来 —— 等于没筛。
        if (item.direction !== 'input') return false;
        if (!String(item.invoice_type || '').includes('专票')) return false;
        if (item.deduction_state !== stateFilter) return false;
      }
      if (!keyword) return true;
      return [item.invoice_no, item.counterparty_name, item.seller_name, item.buyer_name, item.handler]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(keyword));
    });
  }, [invoiceItems, invoiceQuery]);

  // 分页切片。筛选条件或每页条数一变就回到第 1 页 ——
  // 不回到第 1 页的话，筛完之后可能停在一个已经没有数据的页码上，界面看着像"筛没了"。
  useEffect(() => {
    setInvoicePage(1);
  }, [
    invoiceQuery.direction,
    invoiceQuery.keyword,
    invoiceQuery.supplier_id,
    invoiceQuery.deduction_state,
    invoicePageSize,
  ]);

  const invoicePageCount = Math.max(1, Math.ceil(invoiceFiltered.length / invoicePageSize));
  const invoiceSafePage = Math.min(invoicePage, invoicePageCount);
  const invoicePaged = useMemo(() => {
    const start = (invoiceSafePage - 1) * invoicePageSize;
    return invoiceFiltered.slice(start, start + invoicePageSize);
  }, [invoiceFiltered, invoiceSafePage, invoicePageSize]);
  const [analysisRange, setAnalysisRange] = useState({ startDate: '', endDate: '' });
  const [agentPrompt, setAgentPrompt] = useState('请评估当前业务健康度，并给出建议。');
  const [agentResponse, setAgentResponse] = useState({ answer: '', summary: {}, risk_level: '健康' });
  // 刷新后停在上一个页面（2026-10-21 对齐 v96）：只存 sessionStorage，
  // 换标签页/重新登录仍是后端下发的落地页（登录那处显式 applyLanding=true 会覆盖它）。
  const [selectedTab, setSelectedTab] = useState(() => {
    try {
      return sessionStorage.getItem('erp:tab:last') || 'overview';
    } catch (_) {
      return 'overview';
    }
  });
  const [collapsedGroups, setCollapsedGroups] = useState([]);
  // 左侧树状导航的配色主题（多风格）。存 localStorage，刷新后保持选择。
  // `default` 不写 data-nav-theme 属性，样式与改造前完全一致。
  const [navTheme, setNavTheme] = useState(() => {
    try {
      return localStorage.getItem('erp.navTheme') || 'default';
    } catch {
      return 'default';
    }
  });
  // 记住当前页面：同一标签页刷新后回到原处（换标签页/重新登录仍走落地页）
  useEffect(() => {
    try {
      sessionStorage.setItem('erp:tab:last', selectedTab);
    } catch (_) {
      /* 隐私模式下 sessionStorage 可能不可用，忽略即可 */
    }
  }, [selectedTab]);

  // 手机端：侧边栏改成抽屉，用这个开关控制滑出/收起（桌面端不生效）
  const [menuOpen, setMenuOpen] = useState(false);  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getStoredToken()));
  const [authToken, setAuthToken] = useState(getStoredToken());
  // 用户是否已经**自己点过菜单**（见 gotoMenu）。
  //
  // 为什么需要它：登录/刷新的落地页（`system.default_page`）是跟着
  // `/system/me/permissions` 一起**异步**回来的。首屏侧边栏在权限回来之前
  // 就已经渲染并可点击了（用的是内置 menuGroups），于是存在这样一个时序：
  //
  //   1. 页面刚渲染，用户点「库存预警」→ setSelectedTab('stock-alert')
  //   2. 权限接口这时才返回 → 里面还有一句 setSelectedTab(落地页 = 'overview')
  //   3. 用户刚点开的页面被**顶回运营概览** —— 表现为"点了没反应 / 闪回首页"
  //
  // 所以：落地页只在"用户还没自己选过页面"时才生效。这个坑在集成新页面时
  // 特别容易被误判成"菜单没注册 / 分发区没加"，实测排查见 INTEGRATION.md。
  const userNavigatedRef = useRef(false);
  const [userProfile, setUserProfile] = useState({ username: '', role: 'staff' });
  // ——— 多账套（多公司）：当前账套与可进入的账套清单 ———
  // 账套号（schema 名）写在登录凭证里，所以**切换账套＝换发一张新 token**，
  // 前端只要替换 authToken，各处"依赖 authToken"的取数 Effect 会自动重跑一遍。
  const [myCompanies, setMyCompanies] = useState([]);
  const [activeCompany, setActiveCompany] = useState({ code: '', name: '' });
  const [companySwitching, setCompanySwitching] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  // 登录页状态：加载态（按钮置灰「登录中…」）+ 密码显示/隐藏
  const [loginLoading, setLoginLoading] = useState(false);
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [customerForm, setCustomerForm] = useState(emptyCustomerForm);
  const [supplierForm, setSupplierForm] = useState(emptySupplierForm);
  // —— 新增弹窗化：主界面只留列表，点「新增」才弹窗（对齐浩技云「点创建弹窗」）——
  const [customerModalOpen, setCustomerModalOpen] = useState(false);
  // 「智能识别上传 · 仅上传作为附件」暂存的文件：客户还没 id，只能先拿在手里，
  // 等 POST /customers 成功拿到 id 再逐个挂到 /customers/{id}/files。
  const [customerSmartFiles, setCustomerSmartFiles] = useState([]);
  const [supplierModalOpen, setSupplierModalOpen] = useState(false);
  // 弹窗「所属分类」下拉的选项（树 → flat 全路径）。弹窗打开时才拉，平时不发请求。
  const [partnerCategoryOptions, setPartnerCategoryOptions] = useState({ customer: [], supplier: [] });
  // null = 新增态；数字 = 正在编辑的客户 / 供应商 id（与 518 行 editingWarehouseId 同一套约定）。
  // 弹窗是同一个，靠这两个 id 决定标题文案、编码是否只读、以及提交走 POST 还是 PATCH。
  const [editingCustomerId, setEditingCustomerId] = useState(null);
  const [editingSupplierId, setEditingSupplierId] = useState(null);
  const [customerSearch, setCustomerSearch] = useState('');
  const [supplierSearch, setSupplierSearch] = useState('');
  const [warehouseForm, setWarehouseForm] = useState(emptyWarehouseForm);
  // null = 新增态；数字 = 正在编辑的仓库 id
  const [editingWarehouseId, setEditingWarehouseId] = useState(null);
  const [warehouseModalOpen, setWarehouseModalOpen] = useState(false);

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
  // 非空 = 正在编辑这张退货单（表单切到"编辑"模式，提交走 PATCH 而不是 POST）
  const [salesReturnEditingId, setSalesReturnEditingId] = useState(null);
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

  // —— 系统管理（第 5 批）——
  // myPermissions：当前登录用户可见的菜单（由后端按角色算好），未取到时为 null = 不过滤
  const [myPermissions, setMyPermissions] = useState(null);
  const [systemMeta, setSystemMeta] = useState({ departments: [], roles: [], permission_catalog: [], total_menus: 0 });
  // 第 10 批（动态菜单）：menuTree 是后端下发的**展示结构**（管理员可维护），
  // menuAdmin 是菜单管理页自己的数据（含停用项、可选页面清单）
  const [menuTree, setMenuTree] = useState([]);
  const [menuAdmin, setMenuAdmin] = useState({ tree: [], flat: [], pages: [], max_depth: 3, total: 0 });
  const [menuForm, setMenuForm] = useState(emptyMenuForm);
  // 用户**实际点的是哪个菜单入口**（{ pageKey, label }）。
  // 同一个页面可以挂多个入口（菜单管理支持这么做），光按 pageKey 反查会永远取到
  // 树里第一个 —— 点第二个入口却显示第一个入口的名字，很怪。所以要记住点击来源。
  const [activeMenuEntry, setActiveMenuEntry] = useState(null);
  // 对账单三个入口（加强版对账单 / 销售对账单 / 采购对账单）都落到同一个页面，
  // 区别只是进来时预设哪个方向。`nonce` 用来在**已经停在该页**时再点另一个入口
  // 也能强制重挂载 StatementEditor（否则 selectedTab 没变，React 不会重建组件，
  // 预设方向就不生效 —— 表现为"点了采购对账单还是应收"）。
  const [statementPreset, setStatementPreset] = useState({ scope: 'all', nonce: 0 });
  const [systemTab, setSystemTab] = useState('users');
  const [systemUsers, setSystemUsers] = useState([]);
  const [systemUserForm, setSystemUserForm] = useState(emptySystemUserForm);
  const [systemUserKeyword, setSystemUserKeyword] = useState('');
  const [systemUserDeptFilter, setSystemUserDeptFilter] = useState('');
  const [systemUserRoleFilter, setSystemUserRoleFilter] = useState('');
  const [systemBusy, setSystemBusy] = useState(false);
  // —— 基础资料收尾：员工档案 / 期初建账 ——
  const [employees, setEmployees] = useState([]);
  const [employeeForm, setEmployeeForm] = useState(emptyEmployeeForm);
  const [editingEmployeeId, setEditingEmployeeId] = useState(null);
  const [employeeModalOpen, setEmployeeModalOpen] = useState(false);
  const [employeeMeta, setEmployeeMeta] = useState({ statuses: [], genders: [], departments: [] });
  const [employeeKeyword, setEmployeeKeyword] = useState('');
  const [employeeDeptFilter, setEmployeeDeptFilter] = useState('');
  const [employeeStatusFilter, setEmployeeStatusFilter] = useState('');
  const [openingTab, setOpeningTab] = useState('stock');
  const [openingRows, setOpeningRows] = useState([]);
  const [openingSummary, setOpeningSummary] = useState({ lines: 0, total_quantity: 0, total_amount: 0, business_lines: 0 });
  // 录入草稿：先攒在页面上，点「保存全部」才落库（与参数页同一思路）
  const [openingDraftRows, setOpeningDraftRows] = useState([]);
  /* 正在编辑的期初行 id（null = 新增）。点「改这一项」时写入，
     表单按钮随之变成「保存修改」，保存后清空。 */
  const [openingEditingId, setOpeningEditingId] = useState(null);
  const [openingDraft, setOpeningDraft] = useState(emptyOpeningDraft);
  const [openingBalances, setOpeningBalances] = useState({ receivables: [], payables: [], summary: {} });
  // 期初金额的编辑草稿：{ "customer-3": { init_amount, init_invoice_debt } }
  const [balanceDraft, setBalanceDraft] = useState({});
  const [openingClearAsk, setOpeningClearAsk] = useState(false);
  // —— 组合拆卸 ——
  const [assemblyMeta, setAssemblyMeta] = useState({ doc_types: [], statuses: [], default_warehouse_id: null, prefixes: {} });
  const [assemblyForm, setAssemblyForm] = useState(emptyAssemblyForm);
  // 子件清单：从 BOM 带出后可改数量 / 增删行
  const [assemblyItems, setAssemblyItems] = useState([]);
  // BOM 预览的附带信息（成品现存量、缺口提示、是否有配方）
  const [assemblyPreview, setAssemblyPreview] = useState(null);
  const [assemblyOrders, setAssemblyOrders] = useState([]);
  const [assemblyFilter, setAssemblyFilter] = useState('');
  const [assemblyKeyword, setAssemblyKeyword] = useState('');
  const [assemblyNewItem, setAssemblyNewItem] = useState({ product_id: '', quantity: '' });
  // —— 现金银行 ——
  const [bankAccounts, setBankAccounts] = useState([]);
  const [bankAccountForm, setBankAccountForm] = useState(emptyBankAccountForm);
  const [bankTransfers, setBankTransfers] = useState([]);
  const [bankTransferForm, setBankTransferForm] = useState(emptyBankTransferForm);
  const [bankAccountModalOpen, setBankAccountModalOpen] = useState(false);
  const [bankTransferModalOpen, setBankTransferModalOpen] = useState(false);
  const [ledgerAccountId, setLedgerAccountId] = useState('');
  const [accountLedger, setAccountLedger] = useState(null);
  const [ledgerRange, setLedgerRange] = useState({ from: '', to: '' });
  // —— 日常收支 ——
  const [entryForm, setEntryForm] = useState(emptyEntryForm);
  const [entryList, setEntryList] = useState({ items: [], summary: {} });
  // 筛选条件也分"草稿/已应用"，点「查询」才取数（与日志页同一习惯）
  const [entryDraft, setEntryDraft] = useState(emptyEntryQuery);
  const [entryQuery, setEntryQuery] = useState(emptyEntryQuery);
  // —— 总账 / 复式记账 ——
  const [glAccounts, setGlAccounts] = useState([]);
  const [glEntries, setGlEntries] = useState([]);
  const [glBalance, setGlBalance] = useState(null);
  const [glRange, setGlRange] = useState({ from: '', to: '' });
  const [glAccountCode, setGlAccountCode] = useState('');
  const [glDetail, setGlDetail] = useState(null);
  const [glDetailBusy, setGlDetailBusy] = useState(false);
  const [glEntryDetail, setGlEntryDetail] = useState(null);
  const [roleForm, setRoleForm] = useState(emptyRoleForm);
  // 角色权限勾选草稿：编辑角色时先改这里，点保存才提交
  const [permissionDraft, setPermissionDraft] = useState(emptyPermissionDraft);
  const [departmentForm, setDepartmentForm] = useState(emptyDepartmentForm);
  const [selectedDeptId, setSelectedDeptId] = useState('');
  const [passwordTarget, setPasswordTarget] = useState(null);
  const [passwordDraft, setPasswordDraft] = useState({ new_password: '' });

  // —— 参数设置 / 数字字典（第 5 批第 2 轮）——
  const [paramGroups, setParamGroups] = useState([]);
  const [paramTotal, setParamTotal] = useState(0);
  // 草稿：{param_key: 值}。改完点「保存全部」才提交，避免每敲一个字发一次请求
  const [paramDraft, setParamDraft] = useState({});
  const [paramForm, setParamForm] = useState(emptyParamForm);
  const [dictList, setDictList] = useState([]);
  const [dictForm, setDictForm] = useState(emptyDictionaryForm);
  const [activeDictType, setActiveDictType] = useState('');
  const [dictItems, setDictItems] = useState([]);
  const [dictItemForm, setDictItemForm] = useState(emptyDictItemForm);
  // 业务页面用的字典候选（任何登录用户可读）
  const [lookups, setLookups] = useState({});

  // —— 打印模板 / 操作日志（第 5 批第 3 轮）——
  const [printTemplates, setPrintTemplates] = useState([]);
  // 当前选中的单据类型（左栏点选，右栏编辑）
  const [activeTemplateType, setActiveTemplateType] = useState('');
  const [templateDraft, setTemplateDraft] = useState(emptyTemplateDraft);
  // 预览用 blob URL；换模板/卸载时记得 revoke，否则内存里的 PDF 不释放
  const [templatePreviewUrl, setTemplatePreviewUrl] = useState('');
  const [logPage, setLogPage] = useState(null);
  // 筛选条件分"草稿"和"已应用"两份：输入框改的是草稿，
  // 点「查询」才写进 logQuery 触发取数 —— 否则每敲一个字发一次请求。
  const [logDraft, setLogDraft] = useState(emptyLogQuery);
  const [logQuery, setLogQuery] = useState(emptyLogQuery);
  const [logPageNo, setLogPageNo] = useState(1);
  const [logBusy, setLogBusy] = useState(false);
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
  const [projectModalOpen, setProjectModalOpen] = useState(false); // 新增项目弹窗
  const [selectedRecommendation, setSelectedRecommendation] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setRawNotice] = useState('');
  /* 提示条语气：'' 普通 / 'danger' 红字拦截 / 'warn' 黄色提醒。
     用包装函数而不是改所有调用点 —— 现有几十处 setNotice('...') 保持原样。 */
  const [noticeTone, setNoticeTone] = useState('');
  const setNotice = useCallback((message, tone = '') => {
    setRawNotice(message);
    setNoticeTone(tone);
  }, []);
  // 删除确认弹窗：{ id, ids, endpoint, label, kind }
  const [confirmDelete, setConfirmDelete] = useState(null);
  /* 名称防呆（2026-10-22）：重名红字拦下；相似弹黄框，确认后重放这次提交 */
  const [nameGuard, setNameGuard] = useState(null);
  const skipNameGuardRef = useRef(false);
  const pendingFormRef = useRef(null);

  /**
   * 提交前查名。返回 true = 放行；false = 已拦下（提示已显示）。
   * 相似命中时不直接提交，而是弹确认框；用户点"仍然新建"后用 requestSubmit 重放。
   */
  const guardName = useCallback(({ list, name, excludeId, label, form, event, mnemonicKey }) => {
    if (skipNameGuardRef.current) {
      skipNameGuardRef.current = false;
      return true;
    }
    const dup = findDuplicateName(list, name, { excludeId });
    if (dup) {
      setNotice(
        `该名称已存在：${label}「${dup.name}」${dup.code ? `（编码 ${dup.code}）` : ''}，请检查是否已录入。`,
        'danger',
      );
      return false;
    }
    const similar = findSimilarNames(list, name, { excludeId, mnemonicKey });
    if (similar.length) {
      pendingFormRef.current = form || event?.currentTarget || null;
      setNameGuard({ label, name: String(name || '').trim(), similar });
      return false;
    }
    return true;
  }, []);
  // 删单被拦（2026-10-18）：{ label, message, hint } —— 单据已登记收付款，财务上不允许删。
  // 刻意**不提供"强制删除"**：这不是"确认一下就能删"的场景，是真实的钱。
  const [deleteBlocked, setDeleteBlocked] = useState(null);
  // 订单收/付款弹窗（2026-10-18）：{ kind, row } —— 打开时记住是哪一侧、哪一行。
  // row 是点开那一刻的快照，所以提交成功后**必须重新拉列表**（金额会变），
  // 不能指望 row 自己更新。
  const [orderPayDialog, setOrderPayDialog] = useState(null);
  const [orderPayBusy, setOrderPayBusy] = useState(false);
  // 后端返回的 { amount, applied_amount, prepaid_amount, occurred_at }；有值 = 弹窗切成功态
  const [orderPayResult, setOrderPayResult] = useState(null);
  const [orderPayError, setOrderPayError] = useState('');
  // 票据状态（业财一体化 2026-10-22）：采购付款前拉一次"这单还有多少没票"，
  // 付款弹窗靠它决定要不要弹「此笔付款暂无发票」。销售不需要，留 null。
  const [orderPayInvoice, setOrderPayInvoice] = useState(null);
  const [orderPayInvoiceLoading, setOrderPayInvoiceLoading] = useState(false);
  // 发票列表批量勾选删除：已勾选的发票 id 数组
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState([]);
  // 表头复选框与左下角全选框共用这两个判断，避免两处各算一遍算岔。
  // ⚠️ 必须放在 selectedInvoiceIds **之后**：这是组件函数体里的普通语句，
  // 每次渲染都会执行；写在前面会踩 const 的暂时性死区（TDZ），
  // 一登录就整页白屏、报 "Cannot access 'X' before initialization"。
  const invoicePageAllSelected =
    invoicePaged.length > 0 && invoicePaged.every((row) => selectedInvoiceIds.includes(row.id));
  const invoicePageSomeSelected = invoicePaged.some((row) => selectedInvoiceIds.includes(row.id));
  // 数据导入导出（Excel）：支持的类别 / 预检待确认 / 正式导入结果
  const [excelKinds, setExcelKinds] = useState([]);
  const [excelPending, setExcelPending] = useState(null);
  const [excelOutcome, setExcelOutcome] = useState(null);
  const [excelBusy, setExcelBusy] = useState('');

  useEffect(() => {
    // ⚠️ 千万不要在这里写 userNavigatedRef.current = false 来"每次会话重置"。
    // useEffect 是**被动（异步）执行**的：组件挂载时排队的这个 effect，会被用户
    // 第一次点击引发的 state 更新一起刷出 —— 于是这行重置紧跟在用户点击之后执行，
    // 把刚设好的 true 抹回 false，落地页照样把他顶走。实测时序（jsdom 复现）：
    //   t+74ms  点击「库存预警」→ userNavigatedRef.current = true
    //   t+80ms  本 effect 被刷出 → 重置回 false   ← 手贱的一行
    //   t+1696ms 落地页判断读到 false → setSelectedTab('overview') → 闪回
    // 刷新页面时组件本来就是新实例、ref 天然是 false，落地页照样生效，不需要重置。
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
        // 菜单可见性由角色权限决定（后端算好），跟着登录态一起拉。
        // 落地页只在「没有可恢复的上次页面」时才跳 —— 否则刷新一下就被顶回首页，
        // 用户刚填到一半的单据页会当场消失（2026-10-21 对齐 v96 行为）。
        let canRestoreTab = false;
        try {
          canRestoreTab = Boolean(sessionStorage.getItem('erp:tab:last'));
        } catch (_) {
          canRestoreTab = false;
        }
        await loadMyPermissions(authToken, !canRestoreTab);
      } catch {
        localStorage.removeItem('erp_token');
        setAuthToken('');
        setIsAuthenticated(false);
        setMyPermissions(null);
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

  // 系统管理：进页面先拉部门树 / 角色 / 权限目录（一次取完），再拉用户列表
  useEffect(() => {
    if (!authToken || selectedTab !== 'users') return;
    loadSystemMeta();
    refreshSystemUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 参数设置：进页面才拉（低频配置，不挤进首屏）
  useEffect(() => {
    if (!authToken || selectedTab !== 'params') return;
    refreshParams();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 数字字典：进页面拉字典列表 + 第一个字典的项
  useEffect(() => {
    if (!authToken || selectedTab !== 'dictionaries') return;
    refreshDictionaries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 打印模板：进页面拉模板列表，并自动选中第一条
  useEffect(() => {
    if (!authToken || selectedTab !== 'print-templates') return;
    refreshPrintTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 操作日志：进页面拉第一页；翻页 / 改筛选条件也走这里
  useEffect(() => {
    if (!authToken || selectedTab !== 'logs') return;
    refreshOperationLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken, logPageNo, logQuery]);

  // 发票管理：进页面拉发票列表 + 汇总（进销项徽章要用）
  useEffect(() => {
    if (!authToken || selectedTab !== 'invoices') return;
    refreshInvoices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 菜单管理：进页面拉完整菜单树（含停用项）+ 可选页面清单
  useEffect(() => {
    if (!authToken || selectedTab !== 'menus') return;
    refreshMenuAdmin();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 员工档案：进页面拉列表 + 表单选项（部门下拉要能显示层级）
  useEffect(() => {
    if (!authToken || selectedTab !== 'staff') return;
    refreshEmployees();
    refreshEmployeeMeta();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 期初建账：进页面拉库存期初 + 应收应付期初
  useEffect(() => {
    if (!authToken || selectedTab !== 'opening-stock') return;
    refreshOpeningStock();
    refreshOpeningBalances();
    // 仓库是低频主数据、按页加载（见上面 warehouses 那条注释）——
    // 本页的「仓库」下拉要用它，不在这里拉就会出现"只有『请选择』一项"的空下拉。
    refreshWarehouses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 组合拆卸：进页面拉元数据 + 单据列表 + 仓库下拉
  useEffect(() => {
    if (!authToken || selectedTab !== 'assembly') return;
    refreshAssemblyMeta();
    refreshAssemblyOrders();
    refreshWarehouses();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 成品 / 单据类型 / 仓库 / 数量任一变化，就按 BOM 重算子件清单。
  // 注意这会**覆盖**手工改过的用量 —— 这是刻意的：改了套数就按配方重算，
  // 想保留手工值就别再动上面这几个字段（页面上有提示）。
  useEffect(() => {
    if (!authToken || selectedTab !== 'assembly') return;
    if (!assemblyForm.product_id) {
      setAssemblyItems([]);
      setAssemblyPreview(null);
      return;
    }
    const qty = Number(assemblyForm.quantity || 0);
    if (!Number.isFinite(qty) || qty <= 0) return;
    loadAssemblyBomPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken, assemblyForm.product_id, assemblyForm.doc_type, assemblyForm.warehouse_id, assemblyForm.quantity]);

  // 现金银行：账户 + 转账 + 默认账户的流水账
  useEffect(() => {
    if (!authToken || selectedTab !== 'bank') return;
    refreshBankAccounts();
    refreshBankTransfers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken]);

  // 日常收支：明细 + 账户下拉
  useEffect(() => {
    if (!authToken || selectedTab !== 'income-expense') return;
    refreshFinanceEntries();
    refreshBankAccounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTab, authToken, entryQuery]);

  // 业务表单的字典候选：登录后拉一次，供付款方式 / 单位 / 岗位 / 开户行使用
  useEffect(() => {
    if (!authToken) return;
    loadLookups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authToken]);

  // 多账套：刷新页面后要把"当前在哪套账"还原出来。
  // 账套就写在 token 里，所以前端自己解一下 payload 即可，不必额外请求；
  // 账套清单（给自己切着用）才需要问后端要。
  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/companies`, { headers: authHeaders() });
        if (!response.ok) return;
        const list = await response.json();
        if (cancelled || !Array.isArray(list)) return;
        setMyCompanies(list);
        const code = readCompanyFromToken(authToken);
        const active = list.find((row) => row.schema_name === code) || list.find((row) => row.is_default) || list[0];
        if (active) {
          setActiveCompany({ code: active.code, schema: active.schema_name, name: active.name });
        }
      } catch {
        // 拿不到账套清单不影响业务：顶栏不显示切换入口而已
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authToken]);

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
    // 总账：切到该页才拉取科目/凭证/余额表，不挤进首页那批并发请求
    if (selectedTab !== 'general-ledger' || !authToken) return;
    refreshGlAccounts();
    refreshGlEntries();
    refreshGlBalance();
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

        const [summaryRes, customersRes, suppliersRes, productsRes, productCategoriesRes, purchaseRes, salesRes, productionRes, projectRes, inventoryRes, financeRes, financeAnalysisRes, financeDecisionRes, operationsRes, executiveRes, mobileRes, bomTreeRes, invoicesRes, invoicesSummaryRes] = await Promise.all([
          fetch(`${API_BASE}/summary`, { headers }),
          fetch(`${API_BASE}/customers`, { headers }),
          fetch(`${API_BASE}/suppliers`, { headers }),
          fetch(`${API_BASE}/products`, { headers }),
          fetch(`${API_BASE}/product-categories`, { headers }),
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

        if (!summaryRes.ok || !customersRes.ok || !suppliersRes.ok || !productsRes.ok || !productCategoriesRes.ok || !purchaseRes.ok || !salesRes.ok || !productionRes.ok || !projectRes.ok || !inventoryRes.ok || !financeRes.ok || !financeAnalysisRes.ok || !financeDecisionRes.ok || !operationsRes.ok || !executiveRes.ok || !mobileRes.ok || !bomTreeRes.ok || !invoicesRes.ok || !invoicesSummaryRes.ok) {
          throw new Error('请求失败');
        }

        const [summaryData, customersData, suppliersData, productsData, productCategoriesData, purchaseData, salesData, productionData, projectData, inventoryData, financeData, financeAnalysisData, financeDecisionData, operationsData, executiveData, mobileData, bomTreeData, invoicesData, invoicesSummaryData] = await Promise.all([
          summaryRes.json(),
          customersRes.json(),
          suppliersRes.json(),
          productsRes.json(),
          productCategoriesRes.json(),
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
        setProductCategories(Array.isArray(productCategoriesData) ? productCategoriesData : []);
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
        // /invoices 第 11 批起返回 {items, summary}（要与其它列表接口口径一致）；
        // 兼容一下旧形状，免得后端回退版本时前端整页空掉
        const invoiceRows = Array.isArray(invoicesData) ? invoicesData : invoicesData?.items;
        setInvoiceItems(Array.isArray(invoiceRows) ? invoiceRows.map(normalizeInvoiceRecord) : []);
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

  /** 智能识别回填（供应商）：只覆盖认出来的字段（2026-10-23 铺开第二步） */
  const applySupplierSmartFill = (fields) => {
    if (!fields || typeof fields !== 'object') return;
    setSupplierForm((prev) => ({ ...prev, ...fields }));
  };

  /** 智能识别回填（商品）：报价单里的 name/standards/unit/sale_price 直接进表单 */
  const applyProductSmartFill = (patch) => {
    if (!patch || typeof patch !== 'object') return;
    setProductForm((prev) => ({ ...prev, ...patch }));
  };

  /** 智能识别回填（编辑商品）：productEdit 是编辑态的表单 state，同一套"只覆盖认出字段" */
  const applyProductEditSmartFill = (patch) => {
    if (!patch || typeof patch !== 'object') return;
    setProductEdit((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  /**
   * 报价单明细 → 批量生成商品（2026-10-23）。
   *
   * 为什么在 App.jsx 而不是面板里：POST /products 的载荷形状、SKU 去重、
   * 商品列表 state（products）都住在这里 —— 面板只认字段，落库是 App 的事。
   *
   * 规则：
   *   · 没有名称的行直接跳过（建不出有意义的档案）；
   *   · SKU 自动生成 `SP-YYMMDD-序号`，撞号追加随机尾巴（去重对照现有档案 + 本批已用）；
   *   · 报价单价进 purchase_price（供应商报价 = 成本），sale_price 留 0 由用户补；
   *   · 逐行独立提交：一行失败不拖累其它行，最后按实际成功数汇总播报。
   */
  const applyProductBulkItems = async (rows) => {
    const list = (Array.isArray(rows) ? rows : []).filter((row) =>
      String(row && row.name ? row.name : '').trim(),
    );
    if (!list.length) {
      setNotice('报价单里没有可生成商品的明细行（每行至少要有名称）。');
      return;
    }

    const taken = new Set(products.map((row) => String(row.sku || '').toUpperCase()));
    const stamp = new Date().toISOString().slice(2, 10).replace(/-/g, ''); // 261023
    const numOr0 = (value) =>
      value === '' || value === null || value === undefined ? 0 : Number(value) || 0;

    let created = 0;
    const failures = [];
    for (let index = 0; index < list.length; index += 1) {
      const row = list[index];
      let sku = `SP-${stamp}-${String(index + 1).padStart(2, '0')}`;
      while (taken.has(sku.toUpperCase())) sku += Math.floor(Math.random() * 90 + 10);
      taken.add(sku.toUpperCase());

      const payload = {
        sku,
        name: String(row.name).trim(),
        category: null,
        unit: String(row.unit || '').trim() || null,
        purchase_price: numOr0(row.unit_price),
        sale_price: 0,
        tax_rate: null,
        mnemonic: null,
        standards: String(row.spec || '').trim() || null,
        brand: null,
        bar_code: null,
        color: null,
        size: null,
        manufacturer: null,
      };
      try {
        const response = await fetch(`${API_BASE}/products`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          failures.push(`「${payload.name}」${parseApiDetail(data && data.detail, `HTTP ${response.status}`)}`);
          continue;
        }
        const saved = await response.json();
        setProducts((prev) => [saved, ...prev]);
        created += 1;
      } catch {
        failures.push(`「${payload.name}」网络错误`);
      }
    }

    if (!created) {
      setNotice(failures[0] || '没有生成任何商品。');
      return;
    }
    // 弹窗不管从哪个入口开的（新增 productForm / 编辑 productEdit）都关掉复位，
    // 让用户回到商品列表一眼看到新追加的这批
    setProductForm(emptyProductForm);
    setProductEdit(null);
    setProductModalOpen(false);
    setNotice(
      failures.length
        ? `已从报价单生成 ${created} 个商品，${failures.length} 行失败：${failures[0]}`
        : `已从报价单一键生成 ${created} 个商品（SKU 自动编号），请到「商品档案」核价。`,
    );
  };

  /** 把一行档案摊成弹窗表单（键集合以 emptyXxxForm 为准，多余/缺失都不会漏字段）
   *  —— 回填时 `null` 一律变 `''`，否则 React 会把 input 判成非受控。 */
  /**
   * 弹窗「所属分类」下拉的选项：GET /customer-categories（**树**）。
   *
   * ⚠️ 2026-10-21 修复：这里曾经把树摊平成 `[{value,label}]`（v75 的形状），
   *    而弹窗 v76 已经换成 `<ErpTreeSelect nodes={categoryOptions}>`，
   *    组件默认按 `node.id` / `node.name` 取值 —— 拿到扁平数组时：
   *      · 回显找不到 id → 兜底显示原始数字（用户看到输入框里写着「330」）；
   *      · 树渲染读不到 name → 一个节点都画不出来，只剩组件自带的「未分类」。
   *    所以**原样把后端的树传下去**，不要再摊平、不要再拼路径
   *    （路径由组件回显时自己拼，见 ErpTreeSelect 的 selectedLabel）。
   */
  const loadPartnerCategoryOptions = async (kind) => {
    try {
      const path = kind === 'customer' ? 'customer-categories' : 'supplier-categories';
      const response = await fetch(`${API_BASE}/${path}`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!response.ok) return;
      const data = await response.json();
      setPartnerCategoryOptions((prev) => ({
        ...prev,
        [kind]: Array.isArray(data) ? data : [],
      }));
    } catch {
      /* 网络失败静默：分类下拉只剩「未分类」，别的字段不受影响 */
    }
  };

  // 弹窗打开即拉一次（新增 / 编辑两个入口都汇到这两个 state，不用挨个埋点）
  useEffect(() => {
    if (customerModalOpen) loadPartnerCategoryOptions('customer');
  }, [customerModalOpen]);
  useEffect(() => {
    if (supplierModalOpen) loadPartnerCategoryOptions('supplier');
  }, [supplierModalOpen]);

  // 登录后各预拉一次：等弹窗打开才拉的话，首帧会先显示原始 id（用户会当成"回显失败"）
  useEffect(() => {
    if (!authToken) return;
    loadPartnerCategoryOptions('customer');
    loadPartnerCategoryOptions('supplier');
  }, [authToken]);

  const pickPartnerForm = (row, template) => {
    const next = { ...template };
    Object.keys(template).forEach((key) => {
      const value = row ? row[key] : '';
      next[key] = value === null || value === undefined ? '' : String(value);
    });
    return next;
  };

  // 列表「编辑」按钮 → 回填 + 打开同一个弹窗（编码在弹窗里 readOnly，后端也挡）
  const openCustomerEdit = (row) => {
    if (!row) return;
    setCustomerForm(pickPartnerForm(row, emptyCustomerForm));
    setEditingCustomerId(row.id);
    setCustomerModalOpen(true);
  };

  const openSupplierEdit = (row) => {
    if (!row) return;
    setSupplierForm(pickPartnerForm(row, emptySupplierForm));
    setEditingSupplierId(row.id);
    setSupplierModalOpen(true);
  };

  /** 关闭弹窗时把编辑态一起复位 —— 否则下次点「新增」会带着上次的 id 去 PATCH。 */
  const closeCustomerModal = () => {
    setCustomerModalOpen(false);
    setEditingCustomerId(null);
    setCustomerForm(emptyCustomerForm);
    // 关掉就把暂存附件丢掉：用户都没保存这个客户，文件也没有归属
    setCustomerSmartFiles([]);
  };

  /** 智能识别回填：只覆盖认出来的字段，其余保持用户已填的内容。 */
  const applyCustomerSmartFill = (fields) => {
    if (!fields || typeof fields !== 'object') return;
    setCustomerForm((prev) => ({ ...prev, ...fields }));
  };

  const closeSupplierModal = () => {
    setSupplierModalOpen(false);
    setEditingSupplierId(null);
    setSupplierForm(emptySupplierForm);
  };

  // 商品表单字段变更。签名是 (field, value) 而不是原来的 (field) => (event) => …
  // —— 因为新增/编辑弹窗已抽成独立组件（components/product-edit/ProductEditModal.jsx），
  // 组件不认识 event，只把值回传出来。全仓确认过：这几个 ctx 键在 pages 里只被解构、
  // 没有任何真实调用点，改签名不影响其它页面。
  const handleProductChange = (field, value) => {
    setProductForm((prev) => ({ ...prev, [field]: value }));
  };

  // 编辑态表单的同一个回调（状态是 productEdit，不是 productForm）
  const handleProductEditChange = (field, value) => {
    setProductEdit((prev) => (prev ? { ...prev, [field]: value } : prev));
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

  const handleInventoryChange = (field) => (input) => {
    const value = readChangeValue(input);
    setInventoryForm((prev) => ({ ...prev, [field]: value }));
  };

  /**
   * 物流 / 签收保存（2026-10-21 补回）。
   *
   * 出库单详情抽屉里的「物流 / 签收」区块会调 ctx.saveSalesOrderLogistics(id, payload)；
   * 代码覆盖事故后这个函数丢了，按钮点了只会提示"ctx 缺失"。
   * 后端只认这 4 个键（PATCH /sales-orders/{id}/logistics），
   * 其它字段的改动必须走冲销/转单，不能顺手改 —— 所以这里也只传这 4 个。
   */
  const saveSalesOrderLogistics = async (orderId, payload) => {
    if (!orderId) return false;
    try {
      const response = await fetch(`${API_BASE}/sales-orders/${orderId}/logistics`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify(payload || {}),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存物流信息失败' }));
        const detail = errorData && errorData.detail;
        throw new Error(typeof detail === 'string' ? detail : detail?.message || '保存物流信息失败');
      }
      const updated = await response.json();
      // 两个列表（开单管理 / 销售订单）共用同一批行数据，都要跟着更新
      const merge = (prev) =>
        prev.map((item) => (item.id === orderId ? { ...item, ...updated } : item));
      setSalesOrders(merge);
      setSalesOrderList(merge);
      setSelectedSalesOrder((prev) => (prev && prev.id === orderId ? { ...prev, ...updated } : prev));
      setNotice(`已保存 ${updated.order_no || orderId} 的物流 / 签收信息。`);
      return true;
    } catch (err) {
      setNotice(err.message || '保存物流信息失败');
      return false;
    }
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

  // 取 PDF 一律走 `Accept: application/json`（后端回 JSON + base64）。
  //
  // 为什么不直接 fetch PDF 二进制：Edge 的内置 PDF 阅读器会把 application/pdf
  // 的响应从 JS 手里接管走 —— `fetch()` 拿到的是**空响应**（实测状态 204、body 为空），
  // 而 `response.ok` 对 2xx 依然为真，于是会静默下载一个 0 字节的空 PDF。
  // JSON 不会被任何浏览器接管，且能明确判断内容是否完整。
  // ——— 发票原件与重判（第 11 批）———
  // 下载一律走 base64 JSON 通道：application/pdf 会被浏览器内置阅读器接管，
  // fetch 拿到空响应后会静默存下 0 字节空文件（第 7 批打印踩过的同一个坑）。
  const downloadBase64File = async (response, fallbackName) => {
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: '下载失败' }));
      throw new Error(errorData.detail ?? '下载失败');
    }
    const payload = await response.json();
    const binary = atob(payload.content_base64 || '');
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: payload.content_type || 'application/octet-stream' });
    // 兜底：宁可报错，也不要静默下载一个空文件
    if (blob.size === 0) throw new Error('下载到的文件是空的，请重试');
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = payload.filename || fallbackName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return payload;
  };

  const downloadInvoiceSource = async (item) => {
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}/file`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      const payload = await downloadBase64File(response, item.source_name || `${item.invoice_no}.pdf`);
      setNotice(`发票原件「${payload.filename}」已开始下载。`);
    } catch (err) {
      setNotice(err.message || '下载发票原件失败');
    }
  };

  const exportInvoiceSources = async () => {
    try {
      const params = new URLSearchParams();
      // 勾选了就只导勾选的（与"导出"菜单里其它格式保持同一个口径）；
      // 没勾选时按当前方向 Tab 过滤。
      if (selectedInvoiceIds.length > 0) params.set('ids', selectedInvoiceIds.join(','));
      else if (invoiceQuery.direction !== 'all') params.set('direction', invoiceQuery.direction);
      const qs = params.toString();
      const response = await fetch(`${API_BASE}/invoices/export/files${qs ? `?${qs}` : ''}`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      const payload = await downloadBase64File(response, '发票原件.zip');
      // 如实告知跳过了多少张（早期发票没留档原件），不假装全都导出了
      const skipped = Number(payload.skipped || 0);
      setNotice(
        `已导出 ${payload.included} 张发票原件（ZIP）` +
          (skipped ? `；另有 ${skipped} 张没有留档原件，已跳过。` : '。'),
      );
    } catch (err) {
      setNotice(err.message || '导出原件失败');
    }
  };

  const redetectInvoices = async () => {
    try {
      const response = await fetch(`${API_BASE}/invoices/redetect`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail ?? '重判失败');
      setNotice(data.message || '重判完成。');
      await refreshInvoices();
    } catch (err) {
      setNotice(err.message || '重判失败');
    }
  };

  // 发票列表 + 汇总的加载入口（发票管理页、重判、改判之后都走它）
  const refreshInvoices = async () => {
    const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
    const [listRes, summaryRes] = await Promise.all([
      fetch(`${API_BASE}/invoices`, { headers }),
      fetch(`${API_BASE}/invoices/summary`, { headers }),
    ]);
    if (listRes.ok) {
      const payload = await listRes.json();
      const rows = Array.isArray(payload) ? payload : payload?.items;
      if (Array.isArray(rows)) setInvoiceItems(rows.map(normalizeInvoiceRecord));
    }
    if (summaryRes.ok) setInvoiceAggregate(await summaryRes.json());
  };

  const changeInvoiceDirection = async (item, direction) => {
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ direction }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '修改失败' }));
        throw new Error(errorData.detail ?? '修改失败');
      }
      setNotice(`已把这张发票改为「${direction === 'input' ? '进项' : direction === 'output' ? '销项' : '待判定'}」。`);
      await refreshInvoices();
    } catch (err) {
      setNotice(err.message || '修改失败');
    }
  };

  const printPdf = async (path, filename) => {
    // 二次确认（2026-10-18）：打印入口有二十多个（打印中心对账单、销售/采购订单、
    // 入库单、出库单、合同、发票…），逐个页面加确认必然漏一个。这个函数是**唯一收敛点**，
    // 在这里拦一次，所有页面自动都有；StatementEditor 自带的那份直接调 confirmPrint。
    // 注意：确认必须发生在 fetch **之前** —— 否则用户点「取消」时 PDF 已经生成了。
    if (!(await confirmPrint({ name: filename, title: '确认打印此单据？' }))) return;
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        headers: {
          Accept: 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '生成打印文件失败' }));
        throw new Error(errorData.detail ?? '生成打印文件失败');
      }
      const payload = await response.json();
      const binary = atob(payload.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: payload.content_type || 'application/pdf' });
      if (blob.size === 0) {
        throw new Error('打印文件是空的，请重试');
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = payload.filename || filename;
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

  /**
   * 拖拽归档 · 商品版：把一批商品挂到某个类别下。
   *
   * ⚠️ 商品走的是 `/products/batch-category`，目标传的是**类别名**不是 id ——
   * `products.category` 从来就是字符串列（ProductCategory 模型注释里写了原因：
   * 避免迁移 262 个存量商品）。所以这里收 `categoryName`，不传节点 id。
   */
  async function moveProductsToCategory(ids, categoryName) {
    if (!Array.isArray(ids) || ids.length === 0) return null;
    try {
      const response = await fetch(`${API_BASE}/products/batch-category`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ ids, category: categoryName || '' }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(parseApiDetail(data && data.detail, '移动商品失败'));
      const moved = Number(data.moved ?? ids.length);
      setNotice(
        data.category
          ? `已成功移动 ${moved} 个商品至「${data.category}」类别`
          : `已成功把 ${moved} 个商品移到「未分类」`,
      );
      await reloadAfterImport('products');
      return data;
    } catch (err) {
      setNotice(err && err.message ? err.message : '移动商品失败');
      return null;
    }
  }

  /**
   * 拖拽归档（2026-10-21，客户档案试点）：把一批客户/供应商挂到某个分类下。
   *
   * 为什么收在 App 而不是 PartnersBoard：那个组件刻意"不认识 /customers/{id}、
   * 不发请求"（见其文件头「职责边界」）。档案页的增删改一直是这个分工 ——
   * 薄壳拼好 endpoint 交进去，组件只管画和交互。
   *
   * 返回后端原始结果（`{moved, category_id, category_name}`），
   * 组件据此判断"要不要刷树"；失败返回 null 并已弹提示。
   */
  async function movePartnersToCategory(kind, ids, categoryId, expectedName = '') {
    const isSupplier = kind === 'supplier';
    const path = isSupplier ? 'suppliers' : 'customers';
    const label = isSupplier ? '供应商' : '客户';
    if (!Array.isArray(ids) || ids.length === 0) return null;
    try {
      const response = await fetch(`${API_BASE}/${path}/batch-category`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        // 键必须**显式**带上（null = 移到未分类）；漏传键后端会 400，
        // 这是刻意的：静默把分类清空是最坏的一种"成功"。
        body: JSON.stringify({ ids, category_id: categoryId ?? null }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(parseApiDetail(data && data.detail, '归档失败'));
      }
      const moved = Number(data.moved ?? ids.length);
      /* 提示语以**用户松手那一行**（树回传的 name）为准。
         服务端回话只在"落库分类和用户看到的不一致"时补一句，让这种偏差立刻暴露
         —— 以前只信服务端字符串，出现"拖进国家电网、提示中铁一局"时无从判断。 */
      const serverName = data.category_name || '';
      const localName = expectedName || serverName;
      const mismatch = Boolean(serverName && expectedName && serverName !== expectedName);
      setNotice(
        moved === 0
          ? `这些${label}本来就在「${localName || '未分类'}」下，没有需要移动的`
          : localName
            ? `已成功移动 ${moved} 个${label}至「${localName}」分类${mismatch ? `（注意：服务端记录的是「${serverName}」）` : ''}`
            : `已成功把 ${moved} 个${label}移到「未分类」`,
      );
      // 乐观更新：先把本地这几行的 category_id 改掉，再让页面切到目标分类 ——
      // 否则"切了筛选但数据还是旧的"会有一段空白期，用户看到的是"列表空了、
      // 提示已选中 1 项但不在筛选内"（2026-10-21 实测）。随后 reload 校准。
      const patch = (rows) =>
        (rows || []).map((row) =>
          ids.some((id) => String(id) === String(row.id)) ? { ...row, category_id: categoryId ?? null } : row,
        );
      if (isSupplier) setSuppliers(patch);
      else setCustomers(patch);
      await reloadAfterImport(isSupplier ? 'suppliers' : 'customers');
      return data;
    } catch (err) {
      setNotice(err && err.message ? err.message : '归档失败');
      return null;
    }
  }

  /** 行内编辑提示语用的字段中文名（只在提示条里出现） */
  const FIELD_LABELS = {
    name: '名称',
    phone: '电话',
    email: '邮箱',
    address: '地址',
    level: '级别',
    businesser: '业务员',
    standards: '规格',
    unit: '单位',
  };

  /**
   * 行内编辑落库（2026-10-22）：只 PATCH 改过的那个字段。
   * 后端 `CustomerUpdate/SupplierUpdate` 是 `exclude_unset` 语义 —— 没传的列不动，
   * 所以这里绝不能把整行塞过去（会把别人正在改的字段覆盖回旧值）。
   */
  async function patchPartner(kind, id, patch) {
    const isSupplier = kind === 'supplier';
    const path = isSupplier ? 'suppliers' : 'customers';
    const label = isSupplier ? '供应商' : '客户';
    try {
      const response = await fetch(`${API_BASE}/${path}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(patch),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(parseApiDetail(data && data.detail, '保存失败'));
      // 乐观更新：先把本地这一行改掉，表格立刻显示新值（列表刷新在后台进行）
      const apply = (rows) =>
        (rows || []).map((row) => (String(row.id) === String(id) ? { ...row, ...patch } : row));
      if (isSupplier) setSuppliers(apply);
      else setCustomers(apply);
      const field = Object.keys(patch)[0];
      setNotice(`已更新${label}的${FIELD_LABELS[field] || field}`);
      return data;
    } catch (err) {
      setNotice(err && err.message ? err.message : '保存失败');
      return null;
    }
  }

  /** 商品行内编辑：只 PATCH 改过的字段（ProductUpdate 同样是 exclude_unset 语义） */
  async function patchProduct(id, patch) {
    try {
      const response = await fetch(`${API_BASE}/products/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(patch),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(parseApiDetail(data && data.detail, '保存失败'));
      setProducts((rows) => (rows || []).map((row) => (String(row.id) === String(id) ? { ...row, ...patch } : row)));
      const field = Object.keys(patch)[0];
      setNotice(`已更新商品的${FIELD_LABELS[field] || field}`);
      return data;
    } catch (err) {
      setNotice(err && err.message ? err.message : '保存失败');
      return null;
    }
  }

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

  // 档案类批量删除：这里只负责弹确认框，真正的请求仍走 handleDeleteConfirm 的
  // `ids` 分支（后端 /products|/customers|/suppliers 的 `/batch` 早就存在）。
  // 三个函数长得一样却刻意不合并：endpoint 与文案是业务信息，合并后调用处反而
  // 要传一堆配置，"少写三行"换来的是更难读。
  const batchDeleteProducts = (ids) => {
    if (!ids || !ids.length) return;
    setConfirmDelete({
      ids,
      endpoint: '/products/batch',
      label: `选中的 ${ids.length} 个商品`,
      kind: 'product',
    });
  };

  const batchDeleteCustomers = (ids) => {
    if (!ids || !ids.length) return;
    setConfirmDelete({
      ids,
      endpoint: '/customers/batch',
      label: `选中的 ${ids.length} 个客户`,
      kind: 'customer',
    });
  };

  const batchDeleteSuppliers = (ids) => {
    if (!ids || !ids.length) return;
    setConfirmDelete({
      ids,
      endpoint: '/suppliers/batch',
      label: `选中的 ${ids.length} 个供应商`,
      kind: 'supplier',
    });
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
        // 单据已登记收付款 → 直接拦死。后端两种 409：
        //   has_payment_flow       —— 这张单自己收过款/付过款
        //   has_source_payment_flow —— 这是开单，钱记在它的来源订单上
        // 这条**不能**走下面"409 → 强制删除"那条路：那等于给"抹掉真实资金记录"开后门。
        const rawDetail = errorData && errorData.detail;
        const blockedDetail = rawDetail && typeof rawDetail === 'object' ? rawDetail : null;
        const isOrderKind = ['sales-order', 'purchase-order', 'purchase-inbound'].includes(kind);
        const hitPaymentBlock =
          response.status === 409 &&
          isOrderKind &&
          (['has_payment_flow', 'has_source_payment_flow'].includes(blockedDetail?.code) ||
            // 兜底：万一跑的是旧后端（detail 还是纯字符串），也别掉进通用提示里
            (typeof rawDetail === 'string' && /资金流水|收付款|收款|付款/.test(rawDetail)));
        if (hitPaymentBlock) {
          setDeleteBlocked({
            label,
            message: blockedDetail?.message || (typeof rawDetail === 'string' ? rawDetail : '该单据存在资金流水，无法删除。'),
            hint: blockedDetail?.hint || '',
            flowCount: blockedDetail?.flow_count || 0,
          });
          return;
        }
        // 档案被业务数据引用时后端返回 409，改为二次确认，让用户决定是否强制删除
        if (response.status === 409 && ['customer', 'supplier', 'product', 'warehouse', 'contract', 'quotation', 'employee'].includes(kind)) {
          // detail 可能是字符串（档案类）也可能是对象（合同带引用清单），统一取成可读文案
          const detail = errorData.detail;
          const reason = typeof detail === 'string'
            ? detail
            : [detail?.message, detail?.hint].filter(Boolean).join('；') || '该记录已被其他数据引用';
          setConfirmDelete({ id, endpoint, label, kind, force: true, blockedReason: reason });
          return;
        }
        // detail 可能是对象（合同引用清单 / 收付款拦截等结构化 detail），
        // 直接丢进 Error 会显示成「[object Object]」，等于没有报错文案
        const plainDetail = errorData && errorData.detail;
        const reasonText =
          typeof plainDetail === 'string'
            ? plainDetail
            : [plainDetail?.message, plainDetail?.hint].filter(Boolean).join('；');
        throw new Error(reasonText || '删除失败');
      }
      // ── 批量删除（档案类）──────────────────────────────────────────
      // 与单条最大的不同：`/xxx/batch` 永远 200，被业务数据引用的行进 `blocked`
      // 而不是整体 409 —— 所以这里**不能**套下面那套 409 → force 二次确认。
      // 用"删掉几条 + 几条被拦"的老实话告诉用户，比一句"删除成功"可信得多。
      if (ids) {
        const result = await response.json().catch(() => null);
        const done = (result && result.deleted_count) ?? ids.length;
        const blocked = (result && result.blocked_count) ?? 0;
        const drop = (prev) => prev.filter((row) => !ids.includes(row.id));
        if (kind === 'product') setProducts(drop);
        else if (kind === 'customer') setCustomers(drop);
        else if (kind === 'supplier') setSuppliers(drop);
        else if (kind === 'invoice-batch') {
          // 发票列表的 state 叫 invoiceItems（不是 invoices），而且汇总卡片是另一份数据。
          // ⚠️ 这里曾经漏掉：批量分支只认 product/customer/supplier 就 return 了，
          // 发票走不到下面那段 invoice-batch —— 后端其实已经删成功（204），
          // 但列表一行没少、也没有"删了几张"的反馈，用户看到的就是"点了没反应"。
          setInvoiceItems(drop);
          setSelectedInvoiceIds([]);
          await refreshInvoiceAggregate();
        }
        setNotice(
          blocked
            ? `${label}：已删除 ${done} 条，${blocked} 条被业务数据引用未删除。`
            : `${label}：已删除 ${done} 条。`,
        );
        return;
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
      } else if (kind === 'system-user') {
        setSystemUsers((prev) => prev.filter((row) => row.id !== id));
        loadSystemMeta();
      } else if (kind === 'system-role') {
        await loadSystemMeta();
      } else if (kind === 'system-dept') {
        await loadSystemMeta();
        await refreshSystemUsers();
      } else if (kind === 'system-dict') {
        await refreshDictionaries();
        await loadLookups();
      } else if (kind === 'system-dict-item') {
        await refreshDictItems(activeDictType);
        await refreshDictionaries(true);
        await loadLookups();
      } else if (kind === 'bank-account') {
        await refreshBankAccounts();
      } else if (kind === 'bank-transfer') {
        // 删转账会连带删掉两条流水，账户余额与流水账一起刷新
        await refreshBankAccounts();
        await refreshBankTransfers();
        await refreshAccountLedger();
      } else if (kind === 'finance-entry') {
        await refreshFinanceEntries();
        await refreshBankAccounts();
      } else if (kind === 'assembly-order') {
        // 删单会冲销整单库存，库存看板一并刷新
        setAssemblyOrders((prev) => prev.filter((row) => row.id !== id));
        refreshStock();
      } else if (kind === 'system-employee') {
        setEmployees((prev) => prev.filter((row) => row.id !== id));
      } else if (kind === 'opening-line') {
        // 删掉期初会同步改现存量，库存看板也要跟着刷新
        await refreshOpeningStock();
        refreshStock();
      } else if (kind === 'menu') {
        // 删菜单只影响展示结构，但侧边栏要立刻跟着变 —— 所以两处都刷
        await refreshMenuAdmin();
        await loadMyPermissions(authToken);
      } else if (kind === 'menus-reset') {
        await resetMenus();
      } else if (kind === 'system-logs') {
        // 清空之后列表里会剩一条「删除操作日志」—— 后端刻意把这次清理也记上，
        // 清理行为本身必须留痕，否则日志可以被无声抹掉就没有意义了。
        setLogPageNo(1);
        await refreshOperationLogs();
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
    // 全选作用在**当前页**：分页之后"全选"如果跨页选中，用户看不到勾了谁，
    // 批量删除时就会删掉屏幕上没显示的行 —— 这类误删没法撤销。
    const visibleIds = invoicePaged.map((row) => row.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedInvoiceIds.includes(id));
    setSelectedInvoiceIds((prev) =>
      allSelected
        ? prev.filter((id) => !visibleIds.includes(id))
        : Array.from(new Set([...prev, ...visibleIds])),
    );
  };

  // ——— 第 13 批：发票管理页的交互 ———
  const toggleInvoiceExpand = (invoiceId) => {
    setExpandedInvoiceIds((prev) =>
      prev.includes(invoiceId) ? prev.filter((x) => x !== invoiceId) : [...prev, invoiceId],
    );
  };

  // 点发票号码 → 看真实发票。PDF 走 iframe、图片走 img；
  // 两者都用**本地 blob URL**（不把原件地址暴露到 URL 里，也不需要后端做鉴权绕过）。
  const openInvoicePreview = async (item) => {
    if (!item.has_source) {
      setNotice('这张发票没有留档原件（早期导入的数据没存原文件），看不到真实票面。');
      return;
    }
    setInvoiceBusy('preview');
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}/file`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '读取原件失败' }));
        throw new Error(errorData.detail ?? '读取原件失败');
      }
      const payload = await response.json();
      const binary = atob(payload.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const mime = payload.content_type || 'application/pdf';
      const blob = new Blob([bytes], { type: mime });
      if (blob.size === 0) throw new Error('读到的原件是空的，请重试');
      // 换看下一张时上一张的 blob URL 要释放，否则连续预览会一直占内存
      if (invoicePreview?.url) URL.revokeObjectURL(invoicePreview.url);
      setInvoicePreview({ item, url: URL.createObjectURL(blob), mime, size: blob.size });
    } catch (err) {
      setNotice(err.message || '读取原件失败');
    } finally {
      setInvoiceBusy('');
    }
  };

  const closeInvoicePreview = () => {
    // blob URL 必须显式释放：不释放的话每看一张票就在内存里留一整份 PDF
    if (invoicePreview?.url) URL.revokeObjectURL(invoicePreview.url);
    setInvoicePreview(null);
  };

  const openInvoiceQr = async (item) => {
    if (!item.has_source) {
      setNotice('这张发票没有留档原件，二维码要从原件里解，先有原件才行。');
      return;
    }
    setInvoiceBusy(`qr-${item.id}`);
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}/qrcode`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '读取二维码失败' }));
        throw new Error(errorData.detail ?? '读取二维码失败');
      }
      const payload = await response.json();
      setInvoiceQr({
        item,
        dataUrl: `data:${payload.content_type || 'image/png'};base64,${payload.content_base64}`,
        origin: payload.qr_origin || 'embedded',
      });
    } catch (err) {
      setNotice(err.message || '读取二维码失败');
    } finally {
      setInvoiceBusy('');
    }
  };

  const downloadInvoiceQr = async (item) => {
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}/qrcode`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      const payload = await downloadBase64File(response, `${item.invoice_no || item.id}.png`);
      setNotice(`二维码「${payload.filename}」已开始下载。`);
    } catch (err) {
      setNotice(err.message || '下载二维码失败');
    }
  };

  const openInvoiceEdit = (item) => {
    setInvoiceEditForm({
      id: item.id,
      invoice_no: item.invoice_no || '',
      invoice_type: item.invoice_type || '普票',
      issue_date: item.issue_date && item.issue_date !== '—' ? item.issue_date : '',
      buyer_name: item.buyer_name && item.buyer_name !== '—' ? item.buyer_name : '',
      buyer_tax_no: item.buyer_tax_no || '',
      seller_name: item.seller_name && item.seller_name !== '—' ? item.seller_name : '',
      seller_tax_no: item.seller_tax_no || '',
      invoice_code: item.invoice_code || '',
      total_amount: Number(item.amount || 0),
      tax_rate: item.tax_rate ?? '',
      tax_amount: item.tax_amount ?? '',
      excl_tax_amount: item.excl_tax_amount ?? '',
      category: item.category || '',
      status: item.status || '',
      direction: item.direction || 'unknown',
      invoice_flag: item.invoice_flag || 'blue',
      issue_mode: item.issue_mode || 'manual',
      handler: item.handler || '',
      deducted: Boolean(item.deducted),
      // 2026-10-26：认证态（进项专票）。抵扣勾选框保持原样，
      // 两者在弹窗里是两个框 —— 它们本来就是两个动作。
      certified: Boolean(item.certified),
      // 2026-10-22：关联出库单。完结闸按它统计"已开票金额"，没有它这张单永远结不了案。
      related_order_id: item.related_order_id ?? '',
    });
  };

  const submitInvoiceEdit = async (event) => {
    event.preventDefault();
    if (!invoiceEditForm) return;
    const form = invoiceEditForm;
    setInvoiceBusy('edit');
    try {
      // 只提交表单里真的改过的字段：整对象回写会把后端没返回的字段一起抹掉
      const numeric = (value) => (value === '' || value === null ? null : Number(value));
      const body = {
        invoice_no: form.invoice_no.trim(),
        invoice_type: form.invoice_type,
        issue_date: form.issue_date || null,
        buyer_name: form.buyer_name.trim() || null,
        buyer_tax_no: form.buyer_tax_no.trim() || null,
        seller_name: form.seller_name.trim() || null,
        seller_tax_no: form.seller_tax_no.trim() || null,
        invoice_code: form.invoice_code.trim() || null,
        total_amount: Number(form.total_amount || 0),
        tax_rate: numeric(form.tax_rate),
        tax_amount: numeric(form.tax_amount),
        excl_tax_amount: numeric(form.excl_tax_amount),
        category: form.category.trim() || null,
        status: form.status.trim() || null,
        direction: form.direction,
        invoice_flag: form.invoice_flag,
        issue_mode: form.issue_mode,
        handler: form.handler.trim() || null,
        deducted: Boolean(form.deducted),
        // 2026-10-26：认证态单独提交。**不传 supplier_id** —— 编辑弹窗里没有这个控件，
        // 传上去只会把后端自动匹配好的供应商抹成 null，把三方匹配的证据毁掉。
        certified: Boolean(form.certified),
      };
      // 关联单据是**方向相关**的，后端对待判定的票一律拒绝挂单（400）。
      // 所以方向没定性时干脆不提交这个字段：否则历史脏指针会让
      // "只想改个备注"直接 400，整张票卡死改不动。
      if (form.direction !== 'unknown') {
        body.related_order_id =
          form.related_order_id === '' || form.related_order_id === null || form.related_order_id === undefined
            ? null
            : Number(form.related_order_id);
      }
      const response = await fetch(`${API_BASE}/invoices/${form.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      setInvoiceEditForm(null);
      setNotice(`发票「${body.invoice_no}」已保存。`);
      await refreshInvoices();
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setInvoiceBusy('');
    }
  };

  // 导出的取数口径：**勾选了就只导勾选的，没勾选就导当前筛选的全部**。
  // 界面上写清楚这一条，避免用户以为"没勾 = 没东西"。
  const invoiceExportTargets = () =>
    selectedInvoiceIds.length > 0
      ? invoiceItems.filter((item) => selectedInvoiceIds.includes(item.id))
      : invoiceFiltered;

  const exportInvoiceDetailExcel = () => {
    const rows = invoiceExportTargets();
    if (rows.length === 0) {
      setNotice('没有可导出的发票。');
      return;
    }
    const normalized = rows.map(normalizeInvoiceRecord);
    const sorted = [...normalized].sort((a, b) => {
      const cmp = String(a.date || '').localeCompare(String(b.date || ''));
      return cmp !== 0 ? cmp : String(a.invoice_no || '').localeCompare(String(b.invoice_no || ''));
    });

    // 两张表：清单（一张票一行）+ 明细（一条明细一行）。
    // 用户要的"明细单价/数量/合计"只有拆到明细行才填得下，塞进清单会一行变一坨。
    const sheetRows = sorted.map((item, index) => {
      const lines = Array.isArray(item.items) ? item.items : [];
      return {
        序号: index + 1,
        发票日期: item.date || '—',
        发票号码: item.invoice_no || '—',
        发票类型: item.invoice_type || '未知',
        进销项: item.direction_label || '待判定',
        红蓝字: item.invoice_flag_label || '蓝字',
        购买方名称: item.buyer_name || '—',
        购买方税号: item.buyer_tax_no || '—',
        销售方名称: item.seller_name || '—',
        销售方税号: item.seller_tax_no || '—',
        明细品种数: lines.length,
        数量合计: lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0),
        不含税合计: Number(item.excl_tax_amount ?? 0),
        税额: Number(item.tax_amount ?? 0),
        价税合计: Number(item.amount || 0),
      };
    });

    const workbook = XLSX.utils.book_new();
    const sheet = XLSX.utils.json_to_sheet(sheetRows);
    sheet['!cols'] = [
      { wch: 6 }, { wch: 12 }, { wch: 22 }, { wch: 8 }, { wch: 8 }, { wch: 8 },
      { wch: 28 }, { wch: 22 }, { wch: 28 }, { wch: 22 },
      { wch: 10 }, { wch: 10 }, { wch: 12 }, { wch: 10 }, { wch: 12 },
    ];
    XLSX.utils.book_append_sheet(workbook, sheet, '发票清单');

    const detailRows = [];
    sorted.forEach((item, index) => {
      (Array.isArray(item.items) ? item.items : []).forEach((line) => {
        detailRows.push({
          发票序号: index + 1,
          发票号码: item.invoice_no || '—',
          发票日期: item.date || '—',
          品名: line.item_name || '—',
          规格型号: line.spec || '',
          单位: line.unit || '',
          数量: Number(line.quantity || 0),
          单价: Number(line.unit_price || 0),
          金额: Number(line.amount || 0),
          税率: line.tax_rate != null ? `${line.tax_rate}%` : '',
          税额: Number(line.tax_amount || 0),
        });
      });
    });
    if (detailRows.length > 0) {
      const detailSheet = XLSX.utils.json_to_sheet(detailRows);
      detailSheet['!cols'] = [
        { wch: 10 }, { wch: 22 }, { wch: 12 }, { wch: 26 }, { wch: 14 },
        { wch: 8 }, { wch: 10 }, { wch: 12 }, { wch: 12 }, { wch: 8 }, { wch: 10 },
      ];
      XLSX.utils.book_append_sheet(workbook, detailSheet, '发票明细');
    }

    const fileName = `发票清单_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(workbook, fileName);
    setNotice(`已导出 ${sorted.length} 张发票（含 ${detailRows.length} 条明细）到 ${fileName}`);
  };

  const exportInvoiceDetailPdf = () => {
    const rows = invoiceExportTargets();
    if (rows.length === 0) {
      setNotice('没有可导出的发票。');
      return;
    }
    const normalized = rows.map(normalizeInvoiceRecord);
    const total = normalized.reduce((sum, item) => sum + Number(item.amount || 0), 0);
    const escapeHtml = (value) =>
      String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    const body = normalized
      .map((item, index) => {
        const lines = Array.isArray(item.items) ? item.items : [];
        const detailRows = lines
          .map(
            (line) => `<tr>
              <td></td><td></td><td class="item">${escapeHtml(line.item_name || '—')}</td>
              <td>${escapeHtml(line.unit || '')}</td>
              <td class="num">${line.quantity != null ? Number(line.quantity) : ''}</td>
              <td class="num">${line.unit_price != null ? Number(line.unit_price).toFixed(2) : ''}</td>
              <td class="num">${line.amount != null ? Number(line.amount).toFixed(2) : ''}</td>
              <td>${line.tax_rate != null ? `${line.tax_rate}%` : ''}</td>
            </tr>`,
          )
          .join('');
        return `<tr class="main">
            <td class="num">${index + 1}</td>
            <td>${escapeHtml(item.date)}</td>
            <td class="mono">${escapeHtml(item.invoice_no)}</td>
            <td>${escapeHtml(item.invoice_type)}</td>
            <td>${escapeHtml(item.buyer_name)}<br><small>${escapeHtml(item.buyer_tax_no || '')}</small></td>
            <td>${escapeHtml(item.seller_name)}<br><small>${escapeHtml(item.seller_tax_no || '')}</small></td>
            <td class="num">${Number(item.excl_tax_amount ?? 0).toFixed(2)}</td>
            <td class="num">${Number(item.amount || 0).toFixed(2)}</td>
          </tr>${detailRows}`;
      })
      .join('');

    const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
      <title>发票清单</title>
      <style>
        * { box-sizing: border-box; }
        body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 18px; color: #1e293b; }
        h1 { font-size: 18px; margin: 0 0 4px; }
        .meta { font-size: 12px; color: #64748b; margin-bottom: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th, td { border: 1px solid #cbd5e1; padding: 4px 5px; vertical-align: top; }
        th { background: #f1f5f9; font-weight: 600; }
        tr.main td { background: #f8fafc; font-weight: 600; }
        td.item { padding-left: 16px; font-weight: 400; }
        td.num { text-align: right; white-space: nowrap; }
        td.mono { font-family: Consolas, monospace; }
        small { color: #64748b; font-weight: 400; }
        tfoot td { font-weight: 700; background: #f1f5f9; }
        @media print { body { margin: 6mm; } }
      </style></head><body>
      <h1>发票清单</h1>
      <div class="meta">共 ${normalized.length} 张 · 价税合计 ¥${total.toLocaleString('zh-CN')} · 导出时间 ${new Date().toLocaleString('zh-CN')}</div>
      <table>
        <thead><tr>
          <th style="width:34px">序号</th><th style="width:74px">发票日期</th><th style="width:140px">发票号码</th>
          <th style="width:52px">类型</th><th>购买方</th><th>销售方</th>
          <th style="width:72px">不含税合计</th><th style="width:74px">价税合计</th>
        </tr></thead>
        <tbody>${body}</tbody>
        <tfoot><tr><td colspan="7">合计</td><td class="num">${total.toFixed(2)}</td></tr></tfoot>
      </table>
      <script>window.onload = function () { window.print(); };</script>
      </body></html>`;

    const win = window.open('', '_blank');
    if (!win) {
      setNotice('浏览器拦截了新窗口，请允许弹出窗口后重试。');
      return;
    }
    win.document.write(html);
    win.document.close();
    setNotice(`已生成 ${normalized.length} 张发票的打印页，在打印对话框里选「另存为 PDF」即可。`);
  };

  const exportInvoiceQrZip = async () => {
    const rows = invoiceExportTargets();
    if (rows.length === 0) {
      setNotice('没有可导出的发票。');
      return;
    }
    setInvoiceBusy('qr-zip');
    try {
      const params = new URLSearchParams();
      if (selectedInvoiceIds.length > 0) params.set('ids', selectedInvoiceIds.join(','));
      const qs = params.toString();
      const response = await fetch(`${API_BASE}/invoices/export/qrcodes${qs ? `?${qs}` : ''}`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      const payload = await downloadBase64File(response, '发票二维码.zip');
      const skipped = Number(payload.skipped || 0) + Number(payload.no_source || 0);
      setNotice(
        `已导出 ${payload.included} 张发票的二维码（ZIP）` +
          (skipped ? `；另有 ${skipped} 张取不到二维码，已跳过。` : '。') +
          (payload.regenerated ? ` 其中 ${payload.regenerated} 张是用二维码内容重画的（原件上的图解不出来）。` : ''),
      );
    } catch (err) {
      setNotice(err.message || '导出二维码失败');
    } finally {
      setInvoiceBusy('');
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
      setProjectModalOpen(false);
      setNotice('项目已成功新增。');
    } catch (err) {
      setNotice(err.message || '项目新增失败');
    }
  };

  // —— 项目：编辑 / 删除 / 成本归集 ——
  // 在此之前项目只有"新建 + 列表"：建完进度永远停在 0、状态永远停在"计划中"，
  // 也没有任何地方能看到这个项目到底花了多少钱、赚了多少钱。
  const openProjectEdit = (row) => {
    setProjectEdit({
      id: row.id,
      code: row.code,
      name: row.name || '',
      manager: row.manager || '',
      status: row.status || 'planned',
      progress: row.progress ?? 0,
      budget: row.budget ?? 0,
      deadline: row.deadline || '',
      note: row.note || '',
    });
  };

  const submitProjectEdit = async (event) => {
    event.preventDefault();
    if (!projectEdit) return;
    setProjectBusy('edit');
    try {
      const response = await fetch(`${API_BASE}/projects/${projectEdit.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name: projectEdit.name.trim(),
          manager: projectEdit.manager.trim() || null,
          status: projectEdit.status,
          progress: Number(projectEdit.progress || 0),
          budget: Number(projectEdit.budget || 0),
          deadline: projectEdit.deadline || null,
          note: projectEdit.note.trim() || null,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail ?? '保存项目失败');
      setProjects((prev) => prev.map((row) => (row.id === data.id ? data : row)));
      setProjectEdit(null);
      setNotice(`项目「${data.name}」已保存。`);
    } catch (err) {
      setNotice(err.message || '保存项目失败');
    } finally {
      setProjectBusy('');
    }
  };

  const openProjectCost = async (row) => {
    setProjectBusy(`cost-${row.id}`);
    try {
      const response = await fetch(`${API_BASE}/projects/${row.id}/cost`, { headers: authHeaders() });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail ?? '读取项目成本失败');
      setProjectCost(data);
    } catch (err) {
      setNotice(err.message || '读取项目成本失败');
    } finally {
      setProjectBusy('');
    }
  };

  const removeProject = async (row) => {
    setProjectBusy(`del-${row.id}`);
    try {
      const response = await fetch(`${API_BASE}/projects/${row.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (response.status === 204) {
        setProjects((prev) => prev.filter((item) => item.id !== row.id));
        setNotice(`项目「${row.name}」已删除。`);
        return;
      }
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail ?? '删除项目失败');
    } catch (err) {
      setNotice(err.message || '删除项目失败');
    } finally {
      setProjectBusy('');
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
    // 第 11 批：进销项 / 红蓝字 / 开票方式 / 原件。
    // 后端已经把中文标签一起给了（direction_label 等），前端不再自己翻译一遍 ——
    // 两处各维护一份映射迟早会不一致。
    direction: item.direction || 'unknown',
    direction_label: item.direction_label || '待判定',
    invoice_flag: item.invoice_flag || 'blue',
    invoice_flag_label: item.invoice_flag_label || '蓝字',
    issue_mode: item.issue_mode || 'manual',
    issue_mode_label: item.issue_mode_label || '手工开票',
    handler: item.handler || '',
    has_source: Boolean(item.has_source),
    source_name: item.source_name || '',
    source_size: item.source_size || 0,
    deducted: Boolean(item.deducted),
    // 2026-10-26：进项认证三态 + 供应商档案。
    // `deduction_state` / `deduction_state_label` 优先用后端算好的（模型上的同一个属性），
    // 这里只做**兜底**——销项票、老接口版本下没有这两个字段时前端不至于显示空白。
    certified: Boolean(item.certified),
    certified_at: item.certified_at || null,
    deduction_state:
      item.deduction_state || (item.deducted ? 'deducted' : item.certified ? 'certified' : 'uncertified'),
    deduction_state_label:
      item.deduction_state_label || (item.deducted ? '已抵扣' : item.certified ? '已认证待抵扣' : '未认证'),
    supplier_id: item.supplier_id ?? null,
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
      // 已由 /invoices/import 入库的发票号：下面的保存循环要跳过它们，免得又建一遍
      const alreadySaved = new Set();
      let backendFailed = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);

        // ⚠️ 走 /invoices/import 而不是 /invoices/parse：
        // 只有 import 会把**上传的原件落盘留档**并同时建好记录。
        // 早先走 parse，识别完就把文件丢掉了 —— 所以库里的发票一张原件都没有，
        // "导出原始发票 PDF" 根本无从做起。
        const ocrResponse = await fetch(`${API_BASE}/invoices/import`, {
          method: 'POST',
          headers: {
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: formData,
        });

        if (ocrResponse.ok) {
          const imported = await ocrResponse.json();
          // import 已经入库了，这里只取识别结果用于展示，并记下"已保存"避免下面重复提交
          const ocrData = imported.invoice || {};
          if (ocrData.invoice_no) alreadySaved.add(ocrData.invoice_no);
          // 只有真实识别结果才入库（rapidocr/paddleocr=OCR、qrcode=二维码、pdf_text=PDF 文本层），
          // 避免把兜底占位文字当成发票记录塞给用户
          const realOcr = ['rapidocr', 'paddleocr', 'qrcode', 'pdf_text'].includes(imported.provider);
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
      let savedCount = alreadySaved.size;
      for (const item of classifiedItems) {
        const invoiceNo = item.invoice_no || item.id;
        if (alreadySaved.has(invoiceNo)) continue;
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
          const dbPayload = await listRes.json();
          const dbList = Array.isArray(dbPayload) ? dbPayload : dbPayload?.items;
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
    setInvoiceBusy(`deduct-${item.id}`);
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
        setNotice(
          nextDeducted
            ? `专票「${updated.invoice_no || updated.id}」已标记抵扣${
                updated.deducted_at ? `（${new Date(updated.deducted_at).toLocaleString('zh-CN')}）` : ''
              }。`
            : `专票「${updated.invoice_no || updated.id}」已取消抵扣标记。`
        );
      } else {
        const errorData = await response.json().catch(() => ({}));
        setNotice(errorData.detail ?? '更新抵扣状态失败。');
      }
    } catch {
      setNotice('更新抵扣状态失败：无法连接后端。');
    } finally {
      setInvoiceBusy('');
    }
  };

  // 认证（2026-10-26）：进项专票在税局的"勾选确认"，与"申报抵扣"是**两个动作**。
  // 拆开的理由见 `app/models/invoice.py`：月底最常见的真实状态是"已认证待抵扣"，
  // 一个 bool 装不下它。后端会拦销项票 / 非专票 / 已抵扣时撤认证（400），
  // 这里把 detail 原样弹出来 —— 那几句话就是给用户的操作指引。
  const handleToggleCertified = async (item) => {
    if (!item || item.id == null) return;
    const nextCertified = !item.certified;
    setInvoiceBusy(`certify-${item.id}`);
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ certified: nextCertified }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail ?? '更新认证状态失败。');
      }
      const updated = await response.json();
      setInvoiceItems((prev) => prev.map((row) => (row.id === updated.id ? normalizeInvoiceRecord(updated) : row)));
      // 汇总里的 `input_tax`（本月已认证进项税额）跟着变，必须一起刷，
      // 否则图表和列表各说各话。
      const summaryRes = await fetch(`${API_BASE}/invoices/summary`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (summaryRes.ok) setInvoiceAggregate(await summaryRes.json());
      setNotice(
        nextCertified
          ? `进项专票「${updated.invoice_no || updated.id}」已认证${
              updated.certified_at ? `（${new Date(updated.certified_at).toLocaleString('zh-CN')}）` : ''
            }，下一步是申报抵扣。`
          : `专票「${updated.invoice_no || updated.id}」已撤销认证。`
      );
    } catch (err) {
      setNotice(err.message || '更新认证状态失败。');
    } finally {
      setInvoiceBusy('');
    }
  };

  // 「待判定 → 进项/销项」一键定性（2026-10-24）：PATCH direction 后**立刻**触发
  // 自动匹配引擎（唯一强证据才写库，其余返回候选）—— 判定和挂单一步到位，
  // 不让用户判完还要自己找入口去匹配。匹配失败绝不影响判定结果本身。
  const handleSetInvoiceDirection = async (item, direction) => {
    if (!item || item.id == null) return;
    if (!['input', 'output'].includes(direction)) return;
    if (item.direction === direction) return; // 已是这个方向，重复点没有意义
    const label = direction === 'input' ? '进项' : '销项';
    setInvoiceBusy(`dir-${item.id}`);
    try {
      const response = await fetch(`${API_BASE}/invoices/${item.id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ direction }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '判定失败' }));
        throw new Error(errorData.detail ?? '判定失败');
      }
      const updated = await response.json();
      let matchNote = '';
      try {
        const matchRes = await fetch(`${API_BASE}/invoices/${item.id}/auto-match`, {
          method: 'POST',
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        if (matchRes.ok) {
          const outcome = await matchRes.json();
          if (outcome.applied && outcome.order_no) {
            matchNote = `，已自动挂单「${outcome.order_no}」`;
          } else if ((outcome.candidates || []).length > 0) {
            matchNote = `，找到 ${outcome.candidates.length} 张候选单据（${outcome.candidates[0].order_no} 等），请点「编辑」人工确认挂单`;
          } else {
            matchNote = '，暂未找到可关联的单据';
          }
        }
      } catch {
        matchNote = '（自动匹配暂时没跑成，可稍后在编辑里手动挂单）';
      }
      setInvoiceItems((prev) =>
        prev.map((row) => (row.id === updated.id ? normalizeInvoiceRecord(updated) : row))
      );
      const summaryRes = await fetch(`${API_BASE}/invoices/summary`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (summaryRes.ok) setInvoiceAggregate(await summaryRes.json());
      setNotice(`发票「${updated.invoice_no || updated.id}」已判定为${label}${matchNote}。`);
    } catch (err) {
      setNotice(err.message || '判定失败');
    } finally {
      setInvoiceBusy('');
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

    // 空值校验：给友好文案（不依赖浏览器原生 required 气泡）
    if (!loginForm.username.trim() || !loginForm.password.trim()) {
      setNotice('账号或密码不能为空');
      return;
    }

    setLoginLoading(true);
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm),
      });

      if (!response.ok) {
        // 账号不存在 / 密码错误：统一成设计要求里的友好文案，且保留已填账号（不清表单）
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          response.status === 401 ? '账号或密码错误，请重新输入' : (errorData.detail ?? '登录失败'),
        );
      }

      const data = await response.json();
      const nextToken = data.access_token;
      const nextRole = data.role || 'staff';
      localStorage.setItem('erp_token', nextToken);
      localStorage.setItem('erp_user', JSON.stringify({ username: loginForm.username, role: nextRole }));
      setUserProfile({ username: loginForm.username, role: nextRole });
      applyCompanySession(data);
      setAuthToken(nextToken);
      setIsAuthenticated(true);
      setLoginForm({ username: '', password: '' });
      setNotice(`登录成功${data.company_name ? `，当前账套：${data.company_name}` : ''}。`);
    } catch (err) {
      // fetch 网络失败时浏览器抛的 err.message 是 "Failed to fetch"，对用户毫无指导意义。
      // 最常见是双击桌面版后后端还没就绪（启动要几秒），或服务已关闭 —— 给一句能行动的话。
      const raw = err?.message || '';
      const netDown = err instanceof TypeError || /fetch/i.test(raw);
      setNotice(
        netDown
          ? '无法连接服务器：ERP 后端可能还在启动（请等几秒再试），或服务已关闭。若持续失败请重启桌面端。'
          : (raw || '登录失败'),
      );
    } finally {
      setLoginLoading(false);
    }
  };

  // 把登录/切换账套返回的账套信息落进状态（服务端已经算好了，前端不自己推）
  const applyCompanySession = (data) => {
    const list = Array.isArray(data?.companies) ? data.companies : [];
    const active =
      list.find((row) => row.schema_name === data?.company) ||
      list.find((row) => row.code === data?.company) ||
      { code: data?.company || '', name: data?.company_name || '' };
    setMyCompanies(list);
    setActiveCompany({
      code: active.code || data?.company || '',
      schema: active.schema_name || data?.company || '',
      name: active.name || data?.company_name || '',
    });
  };

  // 切换账套：换发 token → 替换 authToken → 依赖它的取数 Effect 自动重跑。
  // 不手动清各页缓存：清了容易漏（漏一处就会在新账套里看到旧账套的数据）。
  const switchCompany = async (code) => {
    if (!code || code === activeCompany.code || companySwitching) return;
    setCompanySwitching(true);
    try {
      const response = await fetch(`${API_BASE}/auth/switch-company`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ company: code }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail ?? '切换账套失败');
      localStorage.setItem('erp_token', data.access_token);
      applyCompanySession(data);
      setAuthToken(data.access_token);
      setNotice(`已切换到账套「${data.company_name}」。`);
    } catch (err) {
      setNotice(err.message || '切换账套失败');
    } finally {
      setCompanySwitching(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('erp_token');
    localStorage.removeItem('erp_user');
    setUserProfile({ username: '', role: 'staff' });
    setAuthToken('');
    setIsAuthenticated(false);
    // 清掉权限缓存，换账号登录时必须重新按新角色算菜单
    setMyPermissions(null);
    // 账套也要清：不清的话下一个登录的人会先看到上一个人的公司名
    setMyCompanies([]);
    setActiveCompany({ code: '', name: '' });
    setNotice('已退出登录。');
  };

  const submitCustomer = async (event) => {
    event.preventDefault();
    setNotice('');

    const isEdit = editingCustomerId != null;
    // 名称防呆：重名直接拦（红字），相似弹黄框确认
    if (
      !guardName({
        list: customers,
        name: customerForm.name,
        excludeId: isEdit ? editingCustomerId : null,
        label: '客户',
        event,
      })
    ) {
      return;
    }
    // 空串一律送 null（列是 nullable 的，'' 会被存成空字符串，列表里看着像有值）
    // ⚠️ `level`（客户级别）已从表单移除：这里**不再发这个键** ——
    //    发 null 会把老客户已有的级别字段清掉，而界面上根本没人维护它。
    const clean = (value) => String(value ?? '').trim() || null;
    const payload = {
      ...customerForm,
      tax_no: clean(customerForm.tax_no),
      bank_name: clean(customerForm.bank_name),
      bank_account: clean(customerForm.bank_account),
      invoice_phone: clean(customerForm.invoice_phone),
      businesser: customerForm.businesser || null,
      contact: customerForm.contact || null,
      phone: customerForm.phone || null,
      email: customerForm.email || null,
      address: customerForm.address || null,
      // 所属分类：''（未选）= null；数字字符串 = 分类 id
      category_id: customerForm.category_id === '' || customerForm.category_id == null
        ? null
        : Number(customerForm.category_id),
    };
    // 编码只读：PATCH 干脆不带这个字段（后端即使收到不同的值也会 400，双保险）；
    // 新增态 code 留空 = 后端自动生成（CUS+日期+流水），所以空串原样带上。
    if (isEdit) delete payload.code;

    try {
      const response = await fetch(
        isEdit ? `${API_BASE}/customers/${editingCustomerId}` : `${API_BASE}/customers`,
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: isEdit ? '保存客户失败' : '创建客户失败' }));
        throw new Error(errorData.detail ?? (isEdit ? '保存客户失败' : '创建客户失败'));
      }

      const saved = await response.json();
      if (isEdit) {
        setCustomers((prev) => prev.map((row) => (row.id === saved.id ? saved : row)));
        setNotice(`客户「${saved.name}」已更新。`);
      } else {
        setCustomers((prev) => [saved, ...prev]);
        setNotice('客户已成功新增。');
        // 「智能识别上传」选了「仅上传作为附件」→ 档案刚拿到 id，现在才挂得上去。
        // 逐个传、单个失败不拖累其它文件（一张图坏了不该让整个客户保存看起来失败）。
        if (customerSmartFiles.length && saved.id) {
          let uploaded = 0;
          for (const file of customerSmartFiles) {
            try {
              const body = new FormData();
              body.append('file', file, file.name);
              body.append('category', 'qualification');
              body.append('note', '智能识别上传');
              const uploadResponse = await fetch(`${API_BASE}/customers/${saved.id}/files`, {
                method: 'POST',
                headers: authHeaders ? authHeaders() : {},
                body,
              });
              if (uploadResponse.ok) uploaded += 1;
            } catch {
              /* 单个文件失败：下面按实际成功数给提示 */
            }
          }
          setNotice(
            uploaded === customerSmartFiles.length
              ? `客户已成功新增，${uploaded} 个附件已归档。`
              : `客户已成功新增，附件归档 ${uploaded}/${customerSmartFiles.length} 个，其余可在「客户档案」里补传。`,
          );
        }
      }
      setCustomerForm(emptyCustomerForm);
      setEditingCustomerId(null);
      setCustomerModalOpen(false);
      setCustomerSmartFiles([]);
    } catch (err) {
      setNotice(err.message || (isEdit ? '客户保存失败' : '客户新增失败'));
    }
  };

  const submitSupplier = async (event) => {
    event.preventDefault();
    setNotice('');

    if (
      !guardName({
        list: suppliers,
        name: supplierForm.name,
        excludeId: editingSupplierId != null ? editingSupplierId : null,
        label: '供应商',
        event,
      })
    ) {
      return;
    }

    const isEdit = editingSupplierId != null;
    const payload = {
      ...supplierForm,
      // 税号：去空格、空串归 null（后端按 null 存，不写成空字符串 —— 空串会和"没填"混在一起）
      tax_no: (supplierForm.tax_no || '').trim() || null,
      // 开票信息（2026-10-23）：开户行 / 账号 / 开票电话
      bank_name: (supplierForm.bank_name || '').trim() || null,
      bank_account: (supplierForm.bank_account || '').trim() || null,
      invoice_phone: (supplierForm.invoice_phone || '').trim() || null,
      short_name: supplierForm.short_name || null,
      contact: supplierForm.contact || null,
      mobile: supplierForm.mobile || null,
      phone: supplierForm.phone || null,
      email: supplierForm.email || null,
      address: supplierForm.address || null,
      // 所属分类：''（未选）= null；口径同 submitCustomer
      category_id: supplierForm.category_id === '' || supplierForm.category_id == null
        ? null
        : Number(supplierForm.category_id),
    };
    if (isEdit) delete payload.code;

    try {
      const response = await fetch(
        isEdit ? `${API_BASE}/suppliers/${editingSupplierId}` : `${API_BASE}/suppliers`,
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: isEdit ? '保存供应商失败' : '创建供应商失败' }));
        throw new Error(errorData.detail ?? (isEdit ? '保存供应商失败' : '创建供应商失败'));
      }

      const saved = await response.json();
      if (isEdit) {
        setSuppliers((prev) => prev.map((row) => (row.id === saved.id ? saved : row)));
        setNotice(`供应商「${saved.name}」已更新。`);
      } else {
        setSuppliers((prev) => [saved, ...prev]);
        setNotice('供应商已成功新增。');
      }
      setSupplierForm(emptySupplierForm);
      setEditingSupplierId(null);
      setSupplierModalOpen(false);
    } catch (err) {
      setNotice(err.message || (isEdit ? '供应商保存失败' : '供应商新增失败'));
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
    setWarehouseModalOpen(true);
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
      setWarehouseModalOpen(false);
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
      <ResizableLayout>
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
      </ResizableLayout>
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
      <ResizableLayout>
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
      </ResizableLayout>
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
      <ResizableLayout>
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
                {/* 档案可能几百条：平铺下拉改可搜索。切换往来类型时 party_id 已重置为 ''，
                    组件会回落到 placeholder，不会残留上一类型的选择。 */}
                <ErpSearchSelect
                  options={parties}
                  value={String(ledgerParty.party_id ?? '')}
                  onChange={(value) => setLedgerParty((prev) => ({ ...prev, party_id: value }))}
                  placeholder={`搜索${ledgerParty.party_type === 'customer' ? '客户' : '供应商'}名称 / 编码`}
                  emptyText="没有匹配的往来单位"
                  getOptionValue={(item) => String(item.id)}
                  getOptionLabel={(item) => `${item.name}（${item.code}）`}
                  getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                />
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
      </ResizableLayout>
    );
  };

  // 总账 / 复式记账：科目余额表（试算平衡）+ 凭证列表 + 明细账追溯。
  // 凭证能追溯到源单据（related_type / related_order_id / doc_no），是「关联能力」的落点。
  const renderGeneralLedgerPage = () => {
    const balanceRows = glBalance?.rows || [];
    const balanceTotal = glBalance || { total_debit: 0, total_credit: 0, balanced: true };

    return (
      <ResizableLayout>
        {/* —— 科目余额表（试算平衡）—— */}
        <section className="panel table-panel">
          <div className="section-header">
            <h2>科目余额表（试算平衡）</h2>
            <span className={`status-badge ${balanceTotal.balanced ? 'ok' : 'warn'}`}>
              {balanceTotal.balanced ? '借贷平衡 ✓' : '借贷不平 ⚠'}
            </span>
          </div>

          <div className="erp-form">
            <div className="form-row two-col">
              <label>
                起始日期
                <input
                  type="date"
                  value={glRange.from}
                  onChange={(event) => setGlRange((prev) => ({ ...prev, from: event.target.value }))}
                />
              </label>
              <label>
                截止日期
                <input
                  type="date"
                  value={glRange.to}
                  onChange={(event) => setGlRange((prev) => ({ ...prev, to: event.target.value }))}
                />
              </label>
            </div>
            <div className="form-actions">
              <button type="button" className="secondary-btn small-btn" onClick={() => refreshGlBalance()}>
                查询余额表
              </button>
            </div>
          </div>

          {balanceRows.length === 0 ? (
            <div className="empty-state">该期间内暂无凭证发生额（业务单据审核后会自动生成凭证）</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>科目编码</th>
                  <th>科目名称</th>
                  <th>借方发生</th>
                  <th>贷方发生</th>
                  <th>期末余额</th>
                </tr>
              </thead>
              <tbody>
                {balanceRows.map((row) => (
                  <tr key={row.code}>
                    <td>{row.code}</td>
                    <td>{row.name}</td>
                    <td>{row.debit ? `¥${Number(row.debit).toLocaleString()}` : '—'}</td>
                    <td>{row.credit ? `¥${Number(row.credit).toLocaleString()}` : '—'}</td>
                    <td>
                      {row.balance ? `¥${Number(row.balance).toLocaleString()}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan="2">合计</td>
                  <td>¥{Number(balanceTotal.total_debit || 0).toLocaleString()}</td>
                  <td>¥{Number(balanceTotal.total_credit || 0).toLocaleString()}</td>
                  <td>—</td>
                </tr>
              </tfoot>
            </table>
          )}
        </section>

        {/* —— 凭证列表 —— */}
        <section className="panel table-panel">
          <div className="section-header">
            <h2>记账凭证</h2>
            <span className="status-badge">{(glEntries || []).length} 张</span>
          </div>
          {(glEntries || []).length === 0 ? (
            <div className="empty-state">暂无凭证</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>凭证号</th>
                  <th>日期</th>
                  <th>摘要</th>
                  <th>来源单据</th>
                  <th>借方</th>
                  <th>贷方</th>
                </tr>
              </thead>
              <tbody>
                {(glEntries || []).map((entry) => (
                  <tr
                    key={entry.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => openGlEntry(entry.id)}
                    title="点击查看凭证分录"
                  >
                    <td>{entry.entry_no}</td>
                    <td>{String(entry.entry_date || '').slice(0, 10) || '—'}</td>
                    <td>{entry.summary || '—'}</td>
                    <td>{docTypeLabel(entry.related_type)}{entry.doc_no ? ` · ${entry.doc_no}` : ''}</td>
                    <td>¥{Number(entry.total_debit || 0).toLocaleString()}</td>
                    <td>¥{Number(entry.total_credit || 0).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* —— 明细账 —— */}
        <section className="panel table-panel">
          <div className="section-header">
            <h2>明细账</h2>
            {glDetail?.account && (
              <span className="status-badge">
                {glDetail.account.code} · {glDetail.account.name}
              </span>
            )}
          </div>
          <div className="erp-form">
            <div className="form-row two-col">
              <label>
                科目
                {/* 会计科目有上百个：平铺下拉改可搜索。
                    ⚠️ 这里的取值是**科目编码**（account.code），不是 id —— 下拉本身
                    原来没有空选项，所以关掉 allowClear，不引入"已清空"这个新状态。 */}
                <ErpSearchSelect
                  options={glAccounts}
                  value={String(glAccountCode ?? '')}
                  onChange={(value) => {
                    setGlAccountCode(value);
                    refreshGlDetail(value);
                  }}
                  placeholder={glAccounts.length === 0 ? '— 无科目 —' : '搜索科目编码 / 名称'}
                  emptyText="没有匹配的科目"
                  allowClear={false}
                  getOptionValue={(item) => String(item.code)}
                  getOptionLabel={(item) => `${item.code} · ${item.name}`}
                  getSearchText={(item) => [item.code, item.name].filter(Boolean).join(' ')}
                />
              </label>
              <div className="form-actions">
                <button
                  type="button"
                  className="secondary-btn small-btn"
                  onClick={() => refreshGlDetail()}
                  disabled={glDetailBusy}
                >
                  {glDetailBusy ? '加载中…' : '查询明细'}
                </button>
              </div>
            </div>
          </div>

          {!glDetail ? (
            <div className="empty-state">选择科目后点击「查询明细」</div>
          ) : (glDetail.rows || []).length === 0 ? (
            <div className="empty-state">该科目在期间内没有发生</div>
          ) : (
            <>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>凭证号</th>
                    <th>日期</th>
                    <th>摘要</th>
                    <th>借方</th>
                    <th>贷方</th>
                    <th>来源</th>
                  </tr>
                </thead>
                <tbody>
                  {glDetail.rows.map((row, idx) => (
                    <tr key={idx}>
                      <td>{row.entry_no}</td>
                      <td>{String(row.entry_date || '').slice(0, 10) || '—'}</td>
                      <td>{row.summary || '—'}</td>
                      <td>{row.debit ? `¥${Number(row.debit).toLocaleString()}` : '—'}</td>
                      <td>{row.credit ? `¥${Number(row.credit).toLocaleString()}` : '—'}</td>
                      <td>{docTypeLabel(row.related_type)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan="3">合计</td>
                    <td>¥{Number(glDetail.total_debit || 0).toLocaleString()}</td>
                    <td>¥{Number(glDetail.total_credit || 0).toLocaleString()}</td>
                    <td>余额 ¥{Number(glDetail.balance || 0).toLocaleString()}</td>
                  </tr>
                </tfoot>
              </table>
            </>
          )}
        </section>

        {/* —— 凭证详情弹层 —— */}
        {glEntryDetail && (
          <div className="modal-backdrop" onClick={() => setGlEntryDetail(null)}>
            <div className="modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="section-header">
                <h2>凭证分录 · {glEntryDetail.entry_no}</h2>
                <button type="button" className="close-btn" onClick={() => setGlEntryDetail(null)} aria-label="关闭">
                  ×
                </button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', fontSize: '13px', color: '#64748b', marginBottom: '14px' }}>
                <span>日期：{String(glEntryDetail.entry_date || '').slice(0, 10) || '—'}</span>
                <span>摘要：{glEntryDetail.summary || '—'}</span>
                <span>来源：{docTypeLabel(glEntryDetail.related_type)}{glEntryDetail.doc_no ? ` · ${glEntryDetail.doc_no}` : ''}</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>科目</th>
                    <th>借方</th>
                    <th>贷方</th>
                  </tr>
                </thead>
                <tbody>
                  {(glEntryDetail.lines || []).map((line, idx) => (
                    <tr key={idx}>
                      <td>{line.account_code} · {line.account_name}</td>
                      <td>{line.debit ? `¥${Number(line.debit).toLocaleString()}` : '—'}</td>
                      <td>{line.credit ? `¥${Number(line.credit).toLocaleString()}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td>合计</td>
                    <td>¥{Number(glEntryDetail.total_debit || 0).toLocaleString()}</td>
                    <td>¥{Number(glEntryDetail.total_credit || 0).toLocaleString()}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )}
      </ResizableLayout>
    );
  };

  const submitProduct = async (event) => {
    event.preventDefault();
    setNotice('');

    // 商品额外比助记码（本来就是拼音首字母，命中率最高）
    if (
      !guardName({
        list: products,
        name: productForm.name,
        label: '商品',
        event,
        mnemonicKey: 'mnemonic',
      })
    ) {
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/products`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify(serializeProductForm(productForm)),
      });

      if (!response.ok) {
        // ⚠️ 必须走 parseApiDetail：422 的 detail 是**数组**，直接当 message 会变成
        //    "[object Object]"（2026-10-22 E2E 实拍：没填价格时界面就长这样）
        const errorData = await response.json().catch(() => ({ detail: '创建产品失败' }));
        throw new Error(parseApiDetail(errorData && errorData.detail, '创建产品失败'));
      }

      const newProduct = await response.json();
      setProducts((prev) => [newProduct, ...prev]);
      setProductForm(emptyProductForm);
      setProductModalOpen(false);
      setNotice('产品已成功新增。');
    } catch (err) {
      setNotice(err.message || '产品新增失败');
    }
  };

  // —— 商品档案：序列化 / 编辑 / 树形类别 / 搜索（对齐浩技云「商品管理」）——
  // 把表单对象转成 API 载荷：数字字段空串→null，字符串字段空串→null。
  // 之前 submitProduct 只序列化了 5 个字段，新补齐的助记码/条码/规格等字段
  // 要么被丢掉、要么把 "" 直接送后端导致 float 解析失败。
  const serializeProductForm = (form) => {
    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    /* 价格/税率这类"后端非空"的数字：空串要发 0 而不是 null。
       发 null 会被 Pydantic 判成 `Input should be a valid number`（422），
       而界面上只会显示 "[object Object]"，用户完全不知道哪里错了（2026-10-22 E2E 抓到）。 */
    const numOr0 = (v) => (v === '' || v === null || v === undefined ? 0 : Number(v) || 0);
    const str = (v) => (v === '' || v === null || v === undefined ? null : v);
    return {
      sku: form.sku,
      name: form.name,
      category: str(form.category),
      unit: str(form.unit),
      purchase_price: numOr0(form.purchase_price),
      sale_price: numOr0(form.sale_price),
      tax_rate: num(form.tax_rate),
      mnemonic: str(form.mnemonic),
      standards: str(form.standards),
      brand: str(form.brand),
      bar_code: str(form.bar_code),
      color: str(form.color),
      size: str(form.size),
      manufacturer: str(form.manufacturer),
      // 生产厂家关联到供应商档案（可空）：manufacturer 仍保留名称快照 ——
      // 供应商改名/停用后，历史商品档案上显示的还是当时的名字。
      manufacturer_id: num(form.manufacturer_id),
      serial_no: str(form.serial_no),
      unit_weight: num(form.unit_weight),
      stock_upper: num(form.stock_upper),
      stock_lower: num(form.stock_lower),
      pack_qty: num(form.pack_qty),
      shelf_life: num(form.shelf_life),
      warn_days: num(form.warn_days),
      image_url: str(form.image_url),
      note: str(form.note),
      // 辅助单位（第三阶段 3a）：**只有 form.units 是数组时才带上这个键**。
      //   · 新增态：emptyProductForm.units = []，随 POST /products 一起提交，
      //     后端把商品和它的辅助单位放在**一个事务**里落库
      //   · 编辑态：打开弹窗时由 ProductUnitsField 异步拉取，拉回来之后才是数组；
      //     拉不到（网络失败）时是 undefined → 键不出现 → 后端 PATCH 用
      //     `exclude_unset` 就一个字段都不碰，**绝不会把已有的辅助单位清空**
      ...(Array.isArray(form.units) ? { units: serializeUnits(form.units) } : {}),
    };
  };

  const loadProductCategories = async () => {
    try {
      const response = await fetch(`${API_BASE}/product-categories`, { headers: authHeaders() });
      const data = await response.json().catch(() => []);
      if (!response.ok) throw new Error(data.detail ?? '加载商品类别失败');
      setProductCategories(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '加载商品类别失败');
    }
  };

  // 编辑商品：之前商品只有「新增 + 删除」，录错的条码/助记码/规格只能删了重建
  const openProductEdit = (row) => {
    setProductEdit({
      id: row.id,
      sku: row.sku,
      name: row.name || '',
      category: row.category || '',
      unit: row.unit || '',
      purchase_price: row.purchase_price ?? '',
      sale_price: row.sale_price ?? '',
      tax_rate: row.tax_rate ?? '',
      mnemonic: row.mnemonic || '',
      standards: row.standards || '',
      brand: row.brand || '',
      bar_code: row.bar_code || '',
      color: row.color || '',
      size: row.size || '',
      manufacturer: row.manufacturer || '',
      manufacturer_id: row.manufacturer_id ?? '',
      serial_no: row.serial_no || '',
      unit_weight: row.unit_weight ?? '',
      stock_upper: row.stock_upper ?? '',
      stock_lower: row.stock_lower ?? '',
      pack_qty: row.pack_qty ?? '',
      shelf_life: row.shelf_life ?? '',
      warn_days: row.warn_days ?? '',
      image_url: row.image_url || '',
      note: row.note || '',
    });
  };

  const submitProductEdit = async (event) => {
    event.preventDefault();
    if (!productEdit) return;
    if (
      !guardName({
        list: products,
        name: productEdit.name,
        excludeId: productEdit.id,
        label: '商品',
        event,
        mnemonicKey: 'mnemonic',
      })
    ) {
      return;
    }
    setProductBusy('edit');
    try {
      const response = await fetch(`${API_BASE}/products/${productEdit.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(serializeProductForm(productEdit)),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail ?? '保存商品失败');
      setProducts((prev) => prev.map((row) => (row.id === data.id ? data : row)));
      setProductEdit(null);
      setNotice(`商品「${data.name}」已保存。`);
    } catch (err) {
      setNotice(err.message || '保存商品失败');
    } finally {
      setProductBusy('');
    }
  };

  // 类别管理：录入 / 编辑 / 删除 / 刷新（图片里的四个操作）
  const openCategoryModal = (mode, node = null) => {
    // 同步初始化「上级类别」的受控值：新增子类默认挂到当前节点下，编辑时取父级
    setCategoryParentDraft(
      mode === 'edit'
        ? String(node?.parent_id ?? '')
        : (node ? String(node.id) : ''),
    );
    setCategoryModal({ mode, node });
  };
  const submitCategory = async (event) => {
    event.preventDefault();
    if (!categoryModal) return;
    // ⚠️ 防重复提交：按钮虽然有 disabled，但**在输入框里按回车**会直接触发表单提交、
    // 绕过按钮的 disabled —— 连按两下回车就是两次 POST，第二次命中唯一性校验报
    // 「同一上级下已有同类别」，用户看到的却是"新建失败"（其实第一次已经建成了）。
    if (productBusy === 'cat') return;
    const { mode, node } = categoryModal;
    const name = (event.currentTarget.elements?.name?.value || '').trim();
    // ⚠️ 上级类别是 ErpSearchSelect（受控、不是表单控件），读不到 elements.parent_id，
    // 必须读 state。这一步是替换成可搜索下拉时最容易静默出错的地方：
    // 读不到就会当成空值，把子类偷偷存成顶级类。
    const parentId = categoryParentDraft || '';
    const note = (event.currentTarget.elements?.note?.value || '').trim();
    if (!name) { setNotice('请填写类别名称'); return; }
    // 同一父级下不允许重名（后端 409 兜底，这里先挡一道省一个来回）
    {
      const parentKey = String(parentId === '' ? '' : parentId);
      const flat = [];
      const walk = (list) =>
        (list || []).forEach((node) => {
          flat.push({ id: node.id, name: node.name, parent_id: node.parent_id, code: '' });
          walk(node.children);
        });
      walk(productCategories);
      const sameParent = flat.filter((n) => String(n.parent_id ?? '') === parentKey);
      const isEditMode = mode === 'edit' && node;
      if (
        !guardName({
          list: sameParent,
          name,
          excludeId: isEditMode ? node.id : null,
          label: '分类',
          event,
        })
      ) {
        return;
      }
    }
    setProductBusy('cat');
    try {
      const isEdit = mode === 'edit' && node;
      const response = await fetch(isEdit ? `${API_BASE}/product-categories/${node.id}` : `${API_BASE}/product-categories`, {
        method: isEdit ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name,
          parent_id: parentId === '' ? null : Number(parentId),
          note: note || null,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        // 重名不是"系统坏了"：先刷新树，让用户看见那个已经存在的分类，
        // 再给一句能指导下一步的话（是要改名，还是它本来就在）。
        const detail = String(data.detail ?? '');
        if (/同一上级下已有同类别|已存在/.test(detail)) {
          await loadProductCategories();
          setCategoryModal(null);
          setNotice(`已存在同名类别「${name}」，已刷新左侧类别树 —— 换个名字，或直接用现有的那个。`);
          return;
        }
        throw new Error(detail || '保存类别失败');
      }
      setCategoryModal(null);
      await loadProductCategories();
      setNotice(isEdit ? `类别「${data.name}」已保存。` : `类别「${data.name}」已新增。`);
    } catch (err) {
      setNotice(err.message || '保存类别失败');
    } finally {
      setProductBusy('');
    }
  };

  const removeCategory = async (node) => {
    setProductBusy(`cat-del-${node.id}`);
    try {
      const response = await fetch(`${API_BASE}/product-categories/${node.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (response.status === 204) {
        await loadProductCategories();
        setNotice(`类别「${node.name}」已删除。`);
        return;
      }
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail ?? '删除类别失败');
    } catch (err) {
      setNotice(err.message || '删除类别失败');
    } finally {
      setProductBusy('');
    }
  };

  /**
   * 拖拽落地：发 `POST /product-categories/{id}/move`，然后**重拉整棵树**。
   *
   * 为什么不在这里做乐观更新（客户/供应商树是做的）：
   *   商品树的节点**不带 count/total**，树上的角标来自 `countProductsByCategory()`
   *   —— 那是从 `productCategories` 现场算的。乐观改树 = 角标也要一起算一遍，
   *   而"移动一个类"根本不改变任何商品的归属，角标本来就一个数都不会变。
   *   少一半代码、少一处分叉，失败时也不需要"回滚"（组件按原 `nodes` 重渲染即可）。
   *   代价是松手到树重排之间有不到一个 RTT 的空档 —— 拖拽浮标撤得比它快，实际看不出来。
   *
   * 为什么必须重拉而不是"本地改 parent_id"：
   *   后端会把**目标父级下的兄弟整段重排成 10/20/30**，我们本地猜不到新的 sort_order，
   *   自己拼一遍迟早和服务端不一致（下一次刷新就跳位）。
   *
   * 返回 `true` 表示已处理；`false`/抛错时组件保持原样，等于自动回滚。
   */
  /**
   * 商品类别拖拽落地（2026-10-22 重写）。
   *
   * ⚠️ 原来打的是 `POST /product-categories/{id}/move` —— **这个路由后端根本没有**，
   *    而且 `renderCategoryNodes` 也没把 onMove 传下去，所以商品树既没有拖拽手柄、
   *    也拖不动（一旦接上就是 404）。现在改成用现成的 `PATCH /product-categories/{id}`：
   *    先改 `parent_id`，再按目标父级重新排 `sort_order`（后端支持这两个字段）。
   *
   * 为什么自己排 sort_order：接口没有 "插入到某节点之前" 的语义，
   * 而拖拽松手给的是 `beforeId`。把目标父级下的兄弟按现有顺序排一遍、
   * 把被拖节点插到 beforeId 前面，再逐条 PATCH 序号，结果与用户看到的一致。
   */
  const moveCategory = async (dragId, move) => {
    if (!dragId || !move) return false;
    const { parentId = null, beforeId = null } = move;
    const headers = { 'Content-Type': 'application/json', ...authHeaders() };
    try {
      // 1) 换父级（后端会校验成环与重名）
      const res = await fetch(`${API_BASE}/product-categories/${dragId}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ parent_id: parentId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setNotice(parseApiDetail(data && data.detail, `调整类别位置失败（${res.status}）`));
        return false;
      }

      // 2) 重排目标父级下的顺序：拿到最新树，找到落点
      const fresh = await fetch(`${API_BASE}/product-categories`, { headers: authHeaders() })
        .then((r) => r.json())
        .catch(() => null);
      const findSiblings = (list, pid) => {
        if (pid === null) return Array.isArray(list) ? list : [];
        const stack = [...(Array.isArray(list) ? list : [])];
        while (stack.length) {
          const node = stack.pop();
          if (Number(node.id) === Number(pid)) return node.children || [];
          (node.children || []).forEach((child) => stack.push(child));
        }
        return [];
      };
      const siblings = findSiblings(fresh, parentId).filter((n) => Number(n.id) !== Number(dragId));
      const insertAt = beforeId
        ? Math.max(0, siblings.findIndex((n) => Number(n.id) === Number(beforeId)))
        : siblings.length;
      const ordered = [
        ...siblings.slice(0, insertAt === -1 ? siblings.length : insertAt),
        { id: dragId },
        ...siblings.slice(insertAt === -1 ? siblings.length : insertAt),
      ];

      // 3) 逐条写序号（只有真的变了才发请求）
      const jobs = [];
      ordered.forEach((node, index) => {
        const next = (index + 1) * 10;
        if (Number(node.sort_order) !== next) {
          jobs.push(
            fetch(`${API_BASE}/product-categories/${node.id}`, {
              method: 'PATCH',
              headers,
              body: JSON.stringify({ sort_order: next }),
            }),
          );
        }
      });
      await Promise.all(jobs);

      await loadProductCategories();
      return true;
    } catch (err) {
      setNotice(parseApiDetail(err && err.message, '调整类别位置失败，请检查网络后重试'));
      return false;
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

  // ── 单据明细行的「单位」下拉（2026-10-17）─────────────────────────────────
  // 采购入库 / 采购订单 / 销售开单 / 销售订单 这四张老表单原本只能按**基本单位**
  // 录数量，辅助单位（箱/包）只有多单位看板支持 —— 于是「3 箱」只能手算成 36 盒再录。
  //
  // 这里补一套共享缓存：选中商品时异步拉 `/products/{id}/units`，同一商品只发一次
  // （并发去重），失败**不写缓存**（否则改完档案回来还是空表，界面一直说"没有单位"）。
  // `unitEpoch` 只负责在数据回来时触发一次重渲染 —— 读的是 ref，不怕快照过期。
  const unitCacheRef = useRef(new Map());
  const unitInflightRef = useRef(new Map());
  const [unitEpoch, setUnitEpoch] = useState(0);

  const loadProductUnits = useCallback(async (productId) => {
    const key = String(productId ?? '');
    if (!key) return [];
    if (unitCacheRef.current.has(key)) return unitCacheRef.current.get(key);
    if (unitInflightRef.current.has(key)) return unitInflightRef.current.get(key);

    const task = (async () => {
      try {
        const response = await fetch(`${API_BASE}/products/${key}/units`, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        if (!response.ok) throw new Error(`读取商品单位失败（HTTP ${response.status}）`);
        const rows = await response.json();
        const list = Array.isArray(rows) ? rows : [];
        unitCacheRef.current.set(key, list);
        setUnitEpoch((value) => value + 1);
        return list;
      } finally {
        unitInflightRef.current.delete(key);
      }
    })();

    unitInflightRef.current.set(key, task);
    return task;
  }, [authToken]);

  /** 某商品可选的全部单位（基础单位恒在第一位；还没加载完时先给基础单位，下拉不会空着）。 */
  const unitOptionsFor = useCallback((productId) => {
    const key = String(productId ?? '');
    if (!key) return [];
    const product = products.find((item) => String(item.id) === key) || null;
    const cached = unitCacheRef.current.get(key);
    if (cached === undefined) return product ? buildUnitOptions(product, []) : [];
    return buildUnitOptions(product, cached);
    // unitEpoch 是"数据到了"的信号：进依赖让函数身份跟着变，页面才会重算选项
  }, [products, unitEpoch]);

  // 明细行的输入既可能来自原生控件的事件，也可能是 ErpSearchSelect 直接抛出来的原始值
  // （商品下拉改成可搜索组件后，onChange 给的是 product_id 本身，不是 event）
  // `readChangeValue` 已提到模块级（见文件顶部），这里不再重复定义。

  const makeOrderItemHandler = (setter, priceField) => (index, field) => (input) => {
    const value = readChangeValue(input);
    setter((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        // 选了商品就把档案价格带出来（采购带进价、销售带售价），省得手打；
        // 同时把单位归位到基本单位，并去拉这个商品的辅助单位。
        if (field === 'product_id') {
          const product = products.find((item) => String(item.id) === String(value));
          if (product) {
            next.unit_price = String(product[priceField] ?? '0');
            next.unit = product.unit || '';
          } else {
            next.unit = '';
          }
          if (value) loadProductUnits(value).catch(() => {});
        }
        // 换单位：把这个单位自己的价格带出来（箱价 ≠ 盒价）。
        // 辅助单位没单独定价（null）就保留原值，绝不静默改成 0 —— 那是丢钱。
        if (field === 'unit') {
          const option = unitOptionsFor(row.product_id).find((item) => item.name === value);
          const price = option ? (priceField === 'sale_price' ? option.salePrice : option.purchasePrice) : null;
          if (price !== null && price !== undefined) next.unit_price = String(price);
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

  // ── 复制行（2026-10-21 补回）─────────────────────────────────────────────
  // OrderBoard 按命名约定从 ctx 取 `copy{sales|purchase}OrderItem`；
  // 代码覆盖事故后这两个函数丢了，点「复制」会 `undefined is not a function`。
  // 语义：整行复制到末尾，**数量重置为 1**（复制的是商品+价格，不是重复下单）。
  const makeCopyItem = (setter) => (index) => {
    setter((prev) => {
      const row = (prev.items || [])[index];
      if (!row) return prev;
      return { ...prev, items: [...prev.items, { ...row, quantity: '1' }] };
    });
  };
  const copySalesOrderItem = makeCopyItem(setSalesOrderForm);
  const copyPurchaseOrderItem = makeCopyItem(setPurchaseOrderForm);

  // ── 批量选商品（2026-10-21 补回）─────────────────────────────────────────
  // OrderBoard 取 `addProductsTo{sales|purchase}Order`。语义：把勾选的商品
  // 一次性追加成明细行，单价取档案价（销售 sale_price / 采购 purchase_price），
  // 数量默认 1；**先复用第一行空行**，避免用户看到"多出来一行空的"。
  const makeAddProducts = (setter, priceField) => (productIds) => {
    const ids = (Array.isArray(productIds) ? productIds : []).filter(Boolean);
    if (ids.length === 0) return;
    setter((prev) => {
      const lines = prev.items || [];
      const emptyIndex = lines.findIndex((row) => !row.product_id);
      const base = emptyIndex >= 0 ? lines.filter((_, i) => i !== emptyIndex) : lines;
      const added = ids.map((id) => {
        const product = products.find((item) => String(item.id) === String(id));
        return {
          ...emptyOrderItem,
          product_id: String(id),
          quantity: '1',
          unit_price: String(product ? (product[priceField] ?? '0') : '0'),
          unit: product?.unit || '',
        };
      });
      return { ...prev, items: [...base, ...added] };
    });
  };
  const addProductsToSalesOrder = makeAddProducts(setSalesOrderForm, 'sale_price');
  const addProductsToPurchaseOrder = makeAddProducts(setPurchaseOrderForm, 'purchase_price');

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

    // 往来对象必选由下面的 `if (!form[partyField])` 兜住（这里原本就有，
    // 只是位置在明细体检之后）。客户/供应商换成 ErpSearchSelect 后原生 required 失效，
    // 但 JS 守卫还在，所以无需另加 —— 别因为"看起来没有 required"就重复补一遍。

    // 明细行先体检：半填行红字拦截、空行静默丢弃 —— 半填的一行都不许发给后端
    const check = inspectItemRows(form.items);
    if (check.issues.length > 0) {
      setNotice(
        check.issues.length === 1
          ? check.issues[0].message
          : `有 ${check.issues.length} 行明细不完整：${check.issues[0].message}（其余 ${check.issues.length - 1} 行同理）`,
      );
      return;
    }
    const lines = check.usable.map((row) => {
      const line = {
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      };
      // 只发 `unit`、**不发 factor** —— 换算率由后端按 unit 现场解析。
      // 空串省略该键，让后端走"未指定单位 = 基本单位"的老路径。
      const unit = String(row.unit ?? '').trim();
      if (unit) line.unit = unit;
      return line;
    });
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
          // 物流签收：出库单才有意义；采购入库走同一提交函数，多传的键后端忽略
          logistics_company: form.logistics_company || null,
          logistics_no: form.logistics_no || null,
          signed_by: form.signed_by || null,
          signed_at: form.signed_at || null,
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

  const makeSubmitOrder = ({ endpoint, form, setForm, emptyForm, listSetter, partyField, partyLabel, label }) => async (event) => {
    event.preventDefault();
    setNotice('');

    // 往来对象必选：客户/供应商换成了 ErpSearchSelect（可搜索，但没有原生 select 的
    // required 拦截），不挡的话 `Number('') === 0` 会把脏值发给后端。
    if (!form[partyField]) {
      setNotice(`请先选择${partyLabel}再提交。`);
      return;
    }

    // 明细行先体检：半填行红字拦截、空行静默丢弃 —— 半填的一行都不许发给后端
    const check = inspectItemRows(form.items);
    if (check.issues.length > 0) {
      setNotice(
        check.issues.length === 1
          ? check.issues[0].message
          : `有 ${check.issues.length} 行明细不完整：${check.issues[0].message}（其余 ${check.issues.length - 1} 行同理）`,
      );
      return;
    }
    const lines = check.usable.map((row) => {
      const line = {
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      };
      // 只发 `unit`、**不发 factor** —— 换算率由后端按 unit 现场解析。
      // 空串省略该键，让后端走"未指定单位 = 基本单位"的老路径。
      const unit = String(row.unit ?? '').trim();
      if (unit) line.unit = unit;
      return line;
    });
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
          project_id: num(form.project_id),
          delivery_date: form.delivery_date || null,
          payment_method: form.payment_method || null,
          // 选客带出的三项快照：落库后对账单/送货单不必再回查档案
          contact: form.contact || null,
          contact_phone: form.contact_phone || null,
          address: form.address || null,
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
    partyLabel: '供应商',
    label: '采购订单',
  });

  const submitSalesOrderForm = makeSubmitOrder({
    endpoint: 'sales-orders',
    form: salesOrderForm,
    setForm: setSalesOrderForm,
    emptyForm: emptySalesOrderForm,
    listSetter: setSalesOrderList,
    partyField: 'customer_id',
    partyLabel: '客户',
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

  // —— 审核（单步：制单 → 审核）2026-10-18 ——
  // 状态的合法性**只由后端判定**（app/core/doc_status.py）：前端发 approved，
  // 非法流转/未知状态一律 409/400，把 detail 原样显示给你看。
  // 采购/销售共用一份实现，差异只有 endpoint 与两个列表 setter。
  const approveOrderRow = async (kind, row) => {
    if (!row) return;
    setNotice('');
    const prefix = kind === 'purchase' ? 'purchase-orders' : 'sales-orders';
    const label = kind === 'purchase' ? '采购订单' : '销售订单';
    try {
      const response = await fetch(`${API_BASE}/${prefix}/${row.id}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ status: 'approved' }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '审核失败' }));
        // FastAPI 422 的 detail 是数组，直接拼进 Error 会变成 [object Object]
        throw new Error(typeof errorData.detail === 'string' ? errorData.detail : '审核失败');
      }
      const updated = await response.json();
      const listSetter = kind === 'purchase' ? setPurchaseOrderList : setSalesOrderList;
      listSetter((prev) =>
        prev.map((item) => (item.id === row.id ? { ...item, ...updated } : item)),
      );
      setNotice(
        `${label} ${row.order_no} 已审核通过，现在可以${kind === 'purchase' ? '转入库单' : '转开单'}。`,
      );
    } catch (err) {
      setNotice(err.message || '审核失败');
    }
  };

  const approvePurchaseOrder = (row) => approveOrderRow('purchase', row);
  const approveSalesOrder = (row) => approveOrderRow('sales', row);

  // —— 收款 / 付款（2026-10-18 接上真弹窗）——
  // 改造前：`POST /finance/receipt|payment`（erp_finance.py:271/278）逻辑完整但**前端零调用**
  // → financial_transactions 里从来没有 receipt/payment → 对账单「本期已收」永远是 0。
  // 现在：订单行点「收款/付款」→ 弹窗 → 落一笔流水并冲减本单欠款（后端还会重算欠款链）。
  const openOrderPayment = (row, kind) => {
    if (!row) return;
    setOrderPayError('');
    setOrderPayResult(null);
    setOrderPayInvoice(null);
    setOrderPayDialog({ kind: kind === 'purchase' ? 'purchase' : 'sales', row });
    // 采购：先问后端"这单还有多少没票"（口径与完结闸一致，不在这里自己算）。
    // 拿不到也不拦人 —— 提醒是加分项，不能因为一个只读接口挂了就付不了款；
    // 但 loading 期间「确认付款」是禁用的，避免闸门在数据没到的那半秒被绕过。
    if (kind === 'purchase') {
      setOrderPayInvoiceLoading(true);
      fetch(`${API_BASE}/orders/purchase/${row.id}/invoice-status`, {
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      })
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => setOrderPayInvoice(data))
        .catch(() => setOrderPayInvoice(null))
        .finally(() => setOrderPayInvoiceLoading(false));
    }
  };

  const closeOrderPayment = () => {
    // 登记中不给关，避免"钱收了但不知道结果"。
    // ⚠️ 但**已经拿到结果**时必须放行：成功面板是在 await 刷新列表**之前**渲染的，
    //    那段时间 busy 还是 true，早先版本 `if (busy) return` 会把「完成」按钮按死，
    //    表现为"点了没反应、弹窗关不掉"（E2E F12 抓到）。
    if (orderPayBusy && !orderPayResult) return;
    setOrderPayDialog(null);
    setOrderPayResult(null);
    setOrderPayError('');
  };

  // 弹窗里点「确认收款/付款」：POST 一次，成功后立刻重拉列表（金额变了）。
  // `estimate` / `no_invoice` 来自无票闸门的两个出口（只有采购付款会有）：
  // 后端据此在流水备注打【暂估】/【无票付款】，并在流水上记 invoice_id（如果挂了票）。
  const submitOrderPayment = async ({ amount, occurred_at, method, note, estimate, no_invoice }) => {
    const current = orderPayDialog;
    if (!current?.row) return;
    const isSales = current.kind !== 'purchase';
    const row = current.row;
    const partyId = isSales ? row.customer_id : row.supplier_id;
    if (!partyId) {
      setOrderPayError(
        `该订单没有关联${isSales ? '客户' : '供应商'}，无法登记${isSales ? '收款' : '付款'}。请先编辑订单补上往来单位。`,
      );
      return;
    }

    setOrderPayBusy(true);
    setOrderPayError('');
    try {
      const verb = isSales ? '收款' : '付款';
      // 后端没有"方式"列（financial_transactions / _write_finance 都没有这个入参），
      // 所以方式拼进备注 —— 先把信息留住，不丢；将来加列只改这一行。
      const partyName =
        (isSales
          ? customers.find((item) => item.id === partyId)?.name
          : suppliers.find((item) => item.id === partyId)?.name) || '';
      const composedNote = [
        `${verb}登记：${partyName || row.order_no || ''}`,
        method ? `方式：${method}` : '',
        note || '',
      ]
        .filter(Boolean)
        .join('｜');

      const response = await fetch(`${API_BASE}/finance/${isSales ? 'receipt' : 'payment'}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          party_id: partyId,
          order_id: row.id,
          amount,
          occurred_at,
          note: composedNote,
          doc_no: row.order_no || '',
          // 无票闸门的选择：null = 正常付款（有票或没提醒）
          estimate: Boolean(estimate),
          no_invoice: Boolean(no_invoice),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '登记失败' }));
        // FastAPI 422 的 detail 是数组，直接拼进 Error 会变成 [object Object]
        const detail =
          typeof errorData.detail === 'string'
            ? errorData.detail
            : Array.isArray(errorData.detail)
              ? errorData.detail.map((item) => item?.msg || item).join('；')
              : '登记失败';
        throw new Error(detail);
      }

      const result = await response.json();
      setOrderPayResult(result);
      // 金额/欠款链都变了：重拉列表，不能只改这一行（后面的单据欠款也被重算过）
      if (isSales) await refreshSalesOrderList();
      else await refreshPurchaseOrderList();
      setNotice(
        `${verb} ¥${Number(result.amount || 0).toFixed(2)} 已登记（冲本单 ¥${Number(
          result.applied_amount || 0,
        ).toFixed(2)}${Number(result.prepaid_amount || 0) > 0 ? `，预收/预付 ¥${Number(result.prepaid_amount).toFixed(2)}` : ''}）。`,
      );
    } catch (err) {
      setOrderPayError(err.message || '登记失败');
    } finally {
      setOrderPayBusy(false);
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

  const handleContractItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

    // 合同相对方必选：下拉换成 ErpSearchSelect 后原生 required 失效，这里补守卫。
    // ⚠️ `Number('') === 0` 会让空值变成合法 id 0，必须在提交前挡掉。
    if (!contractForm.party_id) {
      setNotice(contractForm.contract_type === 'sales' ? '请先选择客户再提交。' : '请先选择供应商再提交。');
      return;
    }

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
          // 模板库里选中的模板（NULL = 系统内置《工矿产品购销合同》范本）
          template_id: num(contractForm.template_id),
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

  const handleQuotationItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handlePurchaseReturnItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleSalesReturnItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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
    const editingId = salesReturnEditingId;
    const payload = {
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
    };

    try {
      // 编辑走 PATCH：后端按「草稿不碰账 / 已落账先冲后落」四路径收口
      const response = await fetch(
        editingId ? `${API_BASE}/sales-returns/${editingId}` : `${API_BASE}/sales-returns`,
        {
          method: editingId ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify(payload),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: editingId ? '保存退货单失败' : '创建销售退货单失败' }));
        throw new Error(parseApiDetail(errorData.detail) || (editingId ? '保存退货单失败' : '创建销售退货单失败'));
      }

      const saved = await response.json();
      setSalesReturnEditingId(null);
      setSalesReturnForm({ ...emptySalesReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      if (editingId) {
        setSalesReturns((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
        setNotice(`退货单 ${saved.return_no} 已保存修改（${saved.amount_chinese}）。草稿状态下库存与应收没有变动。`);
      } else {
        setSalesReturns((prev) => [saved, ...prev]);
        setNotice(`销售退货单 ${saved.return_no} 已生成（${saved.amount_chinese}），库存与应收已自动冲减。`);
      }
    } catch (err) {
      setNotice(err.message || (editingId ? '保存退货单失败' : '销售退货单新增失败'));
    }
  };

  /** 销售退货「编辑」：把单据载回上方表单。
   *
   * 只允许编辑**草稿**：已退货的单据改明细会触发后端「先冲后落」，
   * 对账期间动它风险太大 —— 要改就先反审核退回草稿（那条路账一分不动）。
   */
  function startEditSalesReturn(row) {
    if (row.status !== 'draft') {
      setNotice('只有草稿状态的退货单可以编辑。要改已退货的单，请先点「反审核」把它退回草稿。');
      return;
    }
    setSalesReturnEditingId(row.id);
    setSalesReturnForm({
      ...emptySalesReturnForm,
      customer_id: row.customer_id ?? '',
      warehouse_id: row.warehouse_id ?? '',
      businesser: row.businesser || '',
      return_date: row.return_date || '',
      return_reason: row.return_reason || '',
      payment_method: row.payment_method || '',
      note: row.note || '',
      source_order_no: row.source_order_no || '',
      contact: row.contact || '',
      contact_phone: row.contact_phone || '',
      address: row.address || '',
      items: (row.items && row.items.length ? row.items : [{ product_id: '', quantity: '1', unit_price: '0' }]).map(
        (item) => ({
          product_id: item.product_id ?? '',
          quantity: String(item.quantity ?? '1'),
          unit_price: String(item.unit_price ?? '0'),
          batch_no: item.batch_no || '',
        }),
      ),
    });
    setNotice(`正在编辑退货单 ${row.return_no}（改完点「保存修改」）。`);
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function cancelEditSalesReturn() {
    setSalesReturnEditingId(null);
    setSalesReturnForm({ ...emptySalesReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
    setNotice('已取消编辑。');
  }

  /** 销售退货「反审核」：只把状态退回草稿，**账一个字都不动**。
   *
   * 为什么文案要专门说「账没变」：用户点反审核的本意是「退回去改一下」，
   * 而不是「作废」。早先这两件事被塞进同一段逻辑，改两次就出入两次库存、
   * 冲减两次应收，且全程无提示（2026-10-20 已拆分，见 erp_sales.py 的
   * `_sales_return_apply_ledger` / `_sales_return_red_flush`）。
   */
  async function reverseSalesReturn(row) {
    try {
      const response = await fetch(`${API_BASE}/sales-returns/${row.id}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ status: 'draft' }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '反审核失败' }));
        throw new Error(parseApiDetail(errorData.detail) || '反审核失败');
      }
      const updated = await response.json();
      setSalesReturns((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setNotice(`退货单 ${row.return_no} 已退回草稿，库存与应收没有变动（审核时会按新明细重算）。`);
    } catch (err) {
      setNotice(err.message || '反审核失败');
    }
  }

  /** 销售退货「作废」：唯一会反向冲账的入口 —— 撤库存、撤应收、留痕。
   *
   * 必须二次确认（`confirmDanger` 宿主未挂载时返回 `{ok:false}`，即拒绝），
   * 而且必须填原因：事后对账要有人可问。
   */
  async function voidSalesReturn(row) {
    const label = `销售退货单 ${row.return_no}`;
    const decision = await confirmDanger({
      title: '作废（红冲）退货单',
      name: label,
      hint: '会撤回这张单加过的库存、冲回的应收，并把单据落为「已取消」。此动作不可撤销。',
      requireReason: true,
    });
    if (!decision.ok) return;
    try {
      const response = await fetch(`${API_BASE}/sales-returns/${row.id}/void`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ reason: decision.reason || '' }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '作废失败' }));
        throw new Error(parseApiDetail(errorData.detail) || '作废失败');
      }
      const updated = await response.json();
      setSalesReturns((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setNotice(`${label} 已作废，库存与应收已红冲撤回。`);
    } catch (err) {
      setNotice(err.message || '作废失败');
    }
  }

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

  const handleTransferItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleStocktakingItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleAdjustmentItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handlePlanItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleMrpItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleIssueItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleReturnItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  const handleFinishedGoodsItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

  // ——— 系统管理（第 5 批）：组织机构 / 角色 / 用户 ———
  // token 参数化：登录成功那一刻 authToken state 还没刷新，必须显式传进来
  //
  // ⚠️ `applyLanding` 必须显式开启，只在**登录 / 首次加载**时传 true。
  // 这条接口除了返回权限，还会下发 `ui.default_page`（系统参数里的默认落地页）。
  // 早先它无条件把 selectedTab 设成落地页 —— 于是任何"顺手刷新一下权限"的地方
  // （保存菜单、保存角色、改参数…）都会把用户**当场弹回首页**：
  // 在菜单管理里存一次就被踢走一次，页面看起来像点了没反应。
  async function loadMyPermissions(token, applyLanding = false) {
    try {
      const response = await fetch(`${API_BASE}/system/me/permissions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error('权限加载失败');
      const data = await response.json();
      setMyPermissions(data);
      // 侧边栏渲染用后端下发的菜单树（管理员可在「菜单管理」里维护层级）；
      // 拿不到就留空数组，visibleGroups 会回退到内置的 menuGroups 定义。
      const tree = Array.isArray(data?.menu_tree) ? data.menu_tree : [];
      setMenuTree(tree);
      // 分组默认折叠：登录后侧边栏只显示一级分组，点标题才展开二级菜单。
      // 折叠键与 renderNavNodes 里的一致（`${depth}:${label}`），顶层分组 depth=0。
      setCollapsedGroups(tree.map((group) => `0:${group.label}`));
      // 登录落地页来自系统参数 system.default_page（后端已确保它在该用户可见菜单内）。
      // 只有登录/首次加载才跳，见函数上方关于 applyLanding 的说明。
      const landing = data?.ui?.default_page;
      // ⚠️ 必须带 userNavigatedRef 判断：这个请求是异步的，用户很可能在它返回之前
      // 就已经点了菜单。少了这个条件，用户刚点开的页面会被这里**顶回落地页**
      // （历史 Bug：点「库存预警」闪回「运营概览」，详见 userNavigatedRef 声明处的说明）。
      if (applyLanding && landing && !userNavigatedRef.current) setSelectedTab(landing);
    } catch {
      // 拉不到就放开全部菜单（UI 层的诚实降级，接口本身另有 admin 鉴权兜底）
      setMyPermissions(null);
      setMenuTree([]);
    }
  }

  async function loadSystemMeta() {
    try {
      const response = await fetch(`${API_BASE}/system/meta`, { headers: authHeaders() });
      if (response.status === 403) {
        setNotice('当前账号没有系统管理权限。');
        return;
      }
      if (!response.ok) throw new Error('系统管理数据加载失败');
      const data = await response.json();
      setSystemMeta({
        departments: data.departments || [],
        roles: data.roles || [],
        permission_catalog: data.permission_catalog || [],
        total_menus: data.total_menus || 0,
      });
      // 默认选中根部门，右侧用户列表才有归属可筛；同时把新增表单的部门预填上
      if (!selectedDeptId && (data.departments || []).length) {
        const firstId = String(data.departments[0].id);
        setSelectedDeptId(firstId);
        setSystemUserForm((prev) => (prev.id || prev.department_id ? prev : { ...prev, department_id: firstId }));
      }
    } catch (err) {
      setNotice(err.message || '系统管理数据加载失败');
    }
  }

  async function refreshSystemUsers(overrides) {
    try {
      const params = new URLSearchParams();
      const keyword = overrides?.keyword !== undefined ? overrides.keyword : systemUserKeyword;
      const deptId = overrides?.department_id !== undefined ? overrides.department_id : systemUserDeptFilter;
      const roleId = overrides?.role_id !== undefined ? overrides.role_id : systemUserRoleFilter;
      if (keyword) params.set('keyword', keyword);
      if (deptId) params.set('department_id', deptId);
      if (roleId) params.set('role_id', roleId);
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/system/users${query}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('用户列表加载失败');
      setSystemUsers(await response.json());
    } catch (err) {
      setNotice(err.message || '用户列表加载失败');
    }
  }

  // 把部门树压成带缩进的扁平列表：下拉框与树渲染共用
  function flattenDepartments(nodes, depth = 0, out = []) {
    (nodes || []).forEach((node) => {
      out.push({ ...node, depth });
      flattenDepartments(node.children, depth + 1, out);
    });
    return out;
  }

  const departmentOptions = useMemo(() => flattenDepartments(systemMeta.departments), [systemMeta.departments]);

  function resetSystemUserForm() {
    // 新增用户默认落在当前选中的部门，省一次选择
    setSystemUserForm({ ...emptySystemUserForm, department_id: selectedDeptId || '' });
  }

  function startEditSystemUser(row) {
    setSystemUserForm({
      id: String(row.id),
      username: row.username,
      password: '',
      full_name: row.full_name || '',
      email: row.email || '',
      role_id: row.role_id ? String(row.role_id) : '',
      department_id: row.department_id ? String(row.department_id) : '',
      phone: row.phone || '',
      position: row.position || '',
      remark: row.remark || '',
      is_active: row.is_active,
    });
    setSystemTab('users');
  }

  const handleSystemUserChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setSystemUserForm((prev) => ({ ...prev, [field]: value }));
  };

  async function submitSystemUser(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const isEdit = Boolean(systemUserForm.id);
      if (!isEdit && !systemUserForm.password) throw new Error('新增用户必须设置初始密码');
      if (systemUserForm.password && systemUserForm.password.length < 6) throw new Error('密码至少 6 位');

      const payload = {
        full_name: systemUserForm.full_name || null,
        email: systemUserForm.email || null,
        role_id: systemUserForm.role_id ? Number(systemUserForm.role_id) : null,
        department_id: systemUserForm.department_id ? Number(systemUserForm.department_id) : null,
        phone: systemUserForm.phone || null,
        position: systemUserForm.position || null,
        remark: systemUserForm.remark || null,
        is_active: systemUserForm.is_active,
      };

      let response;
      if (isEdit) {
        response = await fetch(`${API_BASE}/system/users/${systemUserForm.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(payload),
        });
      } else {
        response = await fetch(`${API_BASE}/system/users`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ ...payload, username: systemUserForm.username, password: systemUserForm.password }),
        });
      }
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }

      setNotice(isEdit ? '用户已更新。' : '用户已创建。');
      resetSystemUserForm();
      await refreshSystemUsers();
      await loadSystemMeta();
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function toggleSystemUser(row) {
    try {
      const response = await fetch(`${API_BASE}/system/users/${row.id}/toggle`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '操作失败' }));
        throw new Error(errorData.detail ?? '操作失败');
      }
      setNotice(row.is_active ? `已停用「${row.username}」。` : `已启用「${row.username}」。`);
      await refreshSystemUsers();
    } catch (err) {
      setNotice(err.message || '操作失败');
    }
  }

  async function submitResetPassword(event) {
    event.preventDefault();
    if (!passwordTarget) return;
    try {
      const response = await fetch(`${API_BASE}/system/users/${passwordTarget.id}/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ new_password: passwordDraft.new_password }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '重置失败' }));
        throw new Error(errorData.detail ?? '重置失败');
      }
      setNotice(`「${passwordTarget.username}」的密码已重置。`);
      setPasswordTarget(null);
      setPasswordDraft({ new_password: '' });
    } catch (err) {
      setNotice(err.message || '重置失败');
    }
  }

  function resetRoleForm() {
    setRoleForm(emptyRoleForm);
    setPermissionDraft(emptyPermissionDraft);
  }

  function startEditRole(role) {
    setRoleForm({
      id: String(role.id),
      code: role.code,
      name: role.name,
      description: role.description || '',
      sort_order: String(role.sort_order ?? 0),
      is_active: role.is_active,
    });
    setPermissionDraft({
      all: Boolean(role.permissions?.all),
      menus: Array.isArray(role.permissions?.menus) ? [...role.permissions.menus] : [],
    });
  }

  const handleRoleChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setRoleForm((prev) => ({ ...prev, [field]: value }));
  };

  const togglePermissionMenu = (key) => {
    setPermissionDraft((prev) => ({
      ...prev,
      menus: prev.menus.includes(key) ? prev.menus.filter((item) => item !== key) : [...prev.menus, key],
    }));
  };

  const togglePermissionGroup = (group) => {
    const keys = (group.items || []).map((item) => item.key);
    setPermissionDraft((prev) => {
      const allChecked = keys.every((key) => prev.menus.includes(key));
      return {
        ...prev,
        menus: allChecked
          ? prev.menus.filter((key) => !keys.includes(key))
          : [...new Set([...prev.menus, ...keys])],
      };
    });
  };

  async function submitRole(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const isEdit = Boolean(roleForm.id);
      if (!isEdit && !roleForm.code.trim()) throw new Error('角色编码不能为空');
      if (!roleForm.name.trim()) throw new Error('角色名称不能为空');

      const payload = {
        name: roleForm.name.trim(),
        description: roleForm.description || null,
        sort_order: Number(roleForm.sort_order || 0),
        is_active: roleForm.is_active,
        permissions: { all: permissionDraft.all, menus: permissionDraft.menus },
      };
      if (!isEdit) payload.code = roleForm.code.trim();

      const response = isEdit
        ? await fetch(`${API_BASE}/system/roles/${roleForm.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          })
        : await fetch(`${API_BASE}/system/roles`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }

      setNotice(isEdit ? '角色已更新。' : '角色已创建。');
      resetRoleForm();
      await loadSystemMeta();
      // 自己改了自己的角色，菜单要跟着变
      if (myPermissions && myPermissions.role === roleForm.code) await loadMyPermissions(authToken);
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  function resetDepartmentForm(parentId) {
    setDepartmentForm({ ...emptyDepartmentForm, parent_id: parentId ? String(parentId) : '' });
  }

  function startEditDepartment(node) {
    setDepartmentForm({
      id: String(node.id),
      code: node.code,
      name: node.name,
      parent_id: node.parent_id ? String(node.parent_id) : '',
      leader: node.leader || '',
      phone: node.phone || '',
      sort_order: String(node.sort_order ?? 0),
      is_active: node.is_active,
      note: node.note || '',
    });
    setSelectedDeptId(String(node.id));
  }

  const handleDepartmentChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setDepartmentForm((prev) => ({ ...prev, [field]: value }));
  };

  async function submitDepartment(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const isEdit = Boolean(departmentForm.id);
      if (!departmentForm.name.trim()) throw new Error('部门名称不能为空');

      const payload = {
        name: departmentForm.name.trim(),
        parent_id: departmentForm.parent_id ? Number(departmentForm.parent_id) : null,
        leader: departmentForm.leader || null,
        phone: departmentForm.phone || null,
        sort_order: Number(departmentForm.sort_order || 0),
        is_active: departmentForm.is_active,
        note: departmentForm.note || null,
      };
      if (!isEdit && departmentForm.code.trim()) payload.code = departmentForm.code.trim();

      const response = isEdit
        ? await fetch(`${API_BASE}/system/departments/${departmentForm.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          })
        : await fetch(`${API_BASE}/system/departments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      const saved = await response.json();
      setNotice(isEdit ? '部门已更新。' : '部门已创建。');
      setSelectedDeptId(String(saved.id));
      resetDepartmentForm(null);
      await loadSystemMeta();
      await refreshSystemUsers();
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  // ——— 参数设置（第 5 批第 2 轮）———
  async function refreshParams() {
    try {
      const response = await fetch(`${API_BASE}/system/params`, { headers: authHeaders() });
      if (!response.ok) throw new Error('参数加载失败');
      const data = await response.json();
      const groups = data.groups || [];
      setParamGroups(groups);
      setParamTotal(data.total || 0);
      // 用服务端值重置草稿，保证「未改动」与原值一致
      const draft = {};
      groups.forEach((group) => (group.items || []).forEach((item) => { draft[item.param_key] = item.param_value; }));
      setParamDraft(draft);
    } catch (err) {
      setNotice(err.message || '参数加载失败');
    }
  }

  const handleParamDraftChange = (paramKey) => (event) => {
    const value = event?.target?.type === 'checkbox' ? (event.target.checked ? 'true' : 'false') : event.target.value;
    setParamDraft((prev) => ({ ...prev, [paramKey]: value }));
  };

  async function saveParams() {
    setSystemBusy(true);
    try {
      const items = Object.entries(paramDraft).map(([param_key, param_value]) => ({
        param_key,
        param_value: param_value === null || param_value === undefined ? '' : String(param_value),
      }));
      const response = await fetch(`${API_BASE}/system/params`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ items }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      const data = await response.json();
      setNotice(data.message || '参数已保存。');
      await refreshParams();
      // 落地页 / 库存预警属于界面偏好，跟着刷新一次
      await loadMyPermissions(authToken);
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const handleParamFormChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setParamForm((prev) => ({ ...prev, [field]: value }));
  };

  // 把单个参数恢复成内置默认值（只改草稿，仍需点保存才落库）
  function resetParamToDefault(row) {
    setParamDraft((prev) => ({ ...prev, [row.param_key]: row.default_value ?? '' }));
    setNotice(`「${row.label}」已填回默认值，点「保存全部」生效。`);
  }

  async function submitParam(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/params`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          param_key: paramForm.param_key.trim(),
          label: paramForm.label.trim(),
          param_value: paramForm.param_value,
          param_group: paramForm.param_group,
          value_type: paramForm.value_type,
          description: paramForm.description || null,
          sort_order: Number(paramForm.sort_order || 0),
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '新增失败' }));
        throw new Error(errorData.detail ?? '新增失败');
      }
      setNotice('自定义参数已新增。');
      setParamForm(emptyParamForm);
      await refreshParams();
    } catch (err) {
      setNotice(err.message || '新增失败');
    } finally {
      setSystemBusy(false);
    }
  }

  // ——— 数字字典（第 5 批第 2 轮）———
  async function refreshDictionaries(preserveActive) {
    try {
      const response = await fetch(`${API_BASE}/system/dictionaries`, { headers: authHeaders() });
      if (!response.ok) throw new Error('字典列表加载失败');
      const rows = await response.json();
      setDictList(rows);
      const current = preserveActive && rows.some((row) => row.dict_type === activeDictType)
        ? activeDictType
        : (rows[0]?.dict_type || '');
      setActiveDictType(current);
      if (current) await refreshDictItems(current);
      else setDictItems([]);
    } catch (err) {
      setNotice(err.message || '字典列表加载失败');
    }
  }

  async function refreshDictItems(dictType) {
    if (!dictType) {
      setDictItems([]);
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/system/dictionaries/${dictType}/items`, { headers: authHeaders() });
      if (!response.ok) throw new Error('字典项加载失败');
      setDictItems(await response.json());
    } catch (err) {
      setNotice(err.message || '字典项加载失败');
    }
  }

  const handleDictionaryChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setDictForm((prev) => ({ ...prev, [field]: value }));
  };

  // ——— 菜单管理（第 10 批）———
  async function refreshMenuAdmin() {
    try {
      const response = await fetch(`${API_BASE}/system/menus`, { headers: authHeaders() });
      if (!response.ok) throw new Error('菜单加载失败');
      setMenuAdmin(await response.json());
    } catch (err) {
      setNotice(err.message || '菜单加载失败');
    }
  }

  const handleMenuFormChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setMenuForm((prev) => ({ ...prev, [field]: value }));
  };

  const resetMenuForm = (parentId = '') => {
    setMenuForm({ ...emptyMenuForm, parent_id: parentId === null ? '' : String(parentId || '') });
  };

  const startEditMenu = (node) => {
    setMenuForm({
      id: node.id,
      label: node.label,
      parent_id: node.parent_id ? String(node.parent_id) : '',
      page_key: node.page_key || '',
      sort_order: node.sort_order ?? 0,
      is_enabled: node.is_enabled !== false,
      note: node.note || '',
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  async function submitMenu(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const payload = {
        label: menuForm.label.trim(),
        parent_id: menuForm.parent_id ? Number(menuForm.parent_id) : null,
        // 空字符串要显式变成 null：后端用"有没有 page_key"区分分组与菜单项
        page_key: menuForm.page_key ? menuForm.page_key : null,
        sort_order: Number(menuForm.sort_order || 0),
        is_enabled: menuForm.is_enabled,
        note: menuForm.note || null,
      };
      const editing = Boolean(menuForm.id);
      const response = await fetch(
        editing ? `${API_BASE}/system/menus/${menuForm.id}` : `${API_BASE}/system/menus`,
        {
          method: editing ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      setNotice(editing ? '菜单已更新。' : '菜单已创建。');
      resetMenuForm();
      await Promise.all([refreshMenuAdmin(), loadMyPermissions(authToken)]);
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function toggleMenuEnabled(node) {
    try {
      const response = await fetch(`${API_BASE}/system/menus/${node.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_enabled: !node.is_enabled }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '操作失败' }));
        throw new Error(errorData.detail ?? '操作失败');
      }
      setNotice(node.is_enabled ? `已隐藏「${node.label}」。` : `已显示「${node.label}」。`);
      await Promise.all([refreshMenuAdmin(), loadMyPermissions(authToken)]);
    } catch (err) {
      setNotice(err.message || '操作失败');
    }
  }

  async function resetMenus() {
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/menus/reset`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '恢复失败' }));
        throw new Error(errorData.detail ?? '恢复失败');
      }
      setNotice('已恢复默认菜单。');
      await Promise.all([refreshMenuAdmin(), loadMyPermissions(authToken)]);
    } catch (err) {
      setNotice(err.message || '恢复失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function submitDictionary(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/dictionaries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          dict_type: dictForm.dict_type.trim(),
          dict_name: dictForm.dict_name.trim(),
          description: dictForm.description || null,
          is_active: dictForm.is_active,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建失败' }));
        throw new Error(errorData.detail ?? '创建失败');
      }
      const saved = await response.json();
      setNotice('字典已创建。');
      setDictForm(emptyDictionaryForm);
      setActiveDictType(saved.dict_type);
      await refreshDictionaries(true);
    } catch (err) {
      setNotice(err.message || '创建失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const handleDictItemChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setDictItemForm((prev) => ({ ...prev, [field]: value }));
  };

  function startEditDictItem(item) {
    setDictItemForm({
      id: String(item.id),
      item_value: item.item_value,
      item_label: item.item_label,
      sort_order: String(item.sort_order ?? 0),
      is_enabled: item.is_enabled,
      remark: item.remark || '',
    });
  }

  async function submitDictItem(event) {
    event.preventDefault();
    if (!activeDictType) return;
    setSystemBusy(true);
    try {
      const payload = {
        item_value: dictItemForm.item_value.trim(),
        item_label: dictItemForm.item_label.trim() || dictItemForm.item_value.trim(),
        sort_order: Number(dictItemForm.sort_order || 0),
        is_enabled: dictItemForm.is_enabled,
        remark: dictItemForm.remark || null,
      };
      const isEdit = Boolean(dictItemForm.id);
      const response = isEdit
        ? await fetch(`${API_BASE}/system/dictionary-items/${dictItemForm.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          })
        : await fetch(`${API_BASE}/system/dictionaries/${activeDictType}/items`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
          });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      setNotice(isEdit ? '字典项已更新。' : '字典项已新增。');
      setDictItemForm(emptyDictItemForm);
      await refreshDictItems(activeDictType);
      await refreshDictionaries(true);
      await loadLookups();
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function toggleDictItem(item) {
    try {
      const response = await fetch(`${API_BASE}/system/dictionary-items/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_enabled: !item.is_enabled }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '操作失败' }));
        throw new Error(errorData.detail ?? '操作失败');
      }
      await refreshDictItems(activeDictType);
      await loadLookups();
    } catch (err) {
      setNotice(err.message || '操作失败');
    }
  }

  // 业务表单的候选：登录后拉一次即可，字典改动时会主动重拉
  async function loadLookups() {
    try {
      const response = await fetch(`${API_BASE}/system/lookups?types=${LOOKUP_TYPES.join(',')}`, {
        headers: authHeaders(),
      });
      if (!response.ok) return;
      setLookups(await response.json());
    } catch {
      // 拿不到候选不影响业务：这些字段本来就可以自由输入
    }
  }

  // 取某类字典的候选值数组（<datalist> 直接用）
  const lookupValues = (dictType) => (lookups[dictType] || []).map((item) => item.value);

  // 取完整候选（value + label）。税率这类"值要精确、说明要给人看"的字典必须用它 ——
  // 只给 value 的话下拉里全是光秃秃的 "13""9""6"，用户不知道哪档管哪些业务。
  const lookupItems = (dictType) => lookups[dictType] || [];

  // ——— 打印模板（第 5 批第 3 轮）———
  // 模板是"一张单据一条"，没有增删，只有改与恢复默认。
  // 左栏选单据类型，右栏改外观项；预览用样例数据当场出 PDF，改完立刻看得见。
  function applyTemplateDraft(row) {
    setActiveTemplateType(row.doc_type);
    setTemplateDraft({
      name: row.name || '',
      title: row.title || '',
      header_text: row.header_text || '',
      footer_text: row.footer_text || '',
      show_company: row.show_company !== false,
      show_signatures: row.show_signatures !== false,
      note: row.note || '',
    });
  }

  async function refreshPrintTemplates(preserveActive) {
    try {
      const response = await fetch(`${API_BASE}/system/print-templates`, { headers: authHeaders() });
      if (!response.ok) throw new Error('打印模板加载失败');
      const data = await response.json();
      const items = data.items || [];
      setPrintTemplates(items);
      const keep = preserveActive ? items.find((row) => row.doc_type === activeTemplateType) : null;
      const target = keep || items.find((row) => row.doc_type === activeTemplateType) || items[0];
      if (target) applyTemplateDraft(target);
    } catch (err) {
      setNotice(err.message || '打印模板加载失败');
    }
  }

  const handleTemplateDraftChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setTemplateDraft((prev) => ({ ...prev, [field]: value }));
  };

  function activeTemplate() {
    return printTemplates.find((row) => row.doc_type === activeTemplateType) || null;
  }

  function dropTemplatePreview() {
    setTemplatePreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return '';
    });
  }

  async function savePrintTemplate() {
    const row = activeTemplate();
    if (!row) return;
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/print-templates/${row.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(templateDraft),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存失败' }));
        throw new Error(errorData.detail ?? '保存失败');
      }
      setNotice(`「${row.doc_label}」模板已保存，下次打印立即生效。`);
      dropTemplatePreview();
      await refreshPrintTemplates(true);
    } catch (err) {
      setNotice(err.message || '保存失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function resetPrintTemplate() {
    const row = activeTemplate();
    if (!row) return;
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/print-templates/${row.id}/reset`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error('恢复默认失败');
      setNotice(`「${row.doc_label}」模板已恢复默认。`);
      dropTemplatePreview();
      await refreshPrintTemplates(true);
    } catch (err) {
      setNotice(err.message || '恢复默认失败');
    } finally {
      setSystemBusy(false);
    }
  }

  // 预览：拿后端渲染好的 PDF 塞进 <iframe>（blob URL），不开新窗口
  async function previewPrintTemplate() {
    const row = activeTemplate();
    if (!row) return;
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/system/print-templates/${row.id}/preview`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error('预览生成失败');
      const blob = await response.blob();
      dropTemplatePreview();
      setTemplatePreviewUrl(URL.createObjectURL(blob));
      setNotice('预览用的是样例数据（不是真实单据），保存前可以先看效果。');
    } catch (err) {
      setNotice(err.message || '预览生成失败');
    } finally {
      setSystemBusy(false);
    }
  }

  // 离开页面时释放预览 blob，避免攒着一堆临时 PDF
  useEffect(() => () => dropTemplatePreview(), []);

  // ——— 操作日志（第 5 批第 3 轮）———
  async function refreshOperationLogs() {
    setLogBusy(true);
    try {
      const params = new URLSearchParams();
      Object.entries(logQuery).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      params.set('page', String(logPageNo));
      const response = await fetch(`${API_BASE}/system/logs?${params.toString()}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('操作日志加载失败');
      setLogPage(await response.json());
    } catch (err) {
      setNotice(err.message || '操作日志加载失败');
    } finally {
      setLogBusy(false);
    }
  }

  const handleLogDraftChange = (field) => (event) => {
    const value = event.target.value;
    setLogDraft((prev) => ({ ...prev, [field]: value }));
  };

  // 只有点「查询 / 重置」才真正取数（草稿 → 已应用）
  function applyLogQuery(event) {
    if (event) event.preventDefault();
    setLogQuery({ ...logDraft });
    setLogPageNo(1);
  }

  function resetLogQuery() {
    setLogDraft(emptyLogQuery);
    setLogQuery(emptyLogQuery);
    setLogPageNo(1);
  }

  // ——— 现金银行 ———
  async function refreshBankAccounts() {
    try {
      const response = await fetch(`${API_BASE}/bank-accounts?include_inactive=true`, { headers: authHeaders() });
      if (!response.ok) throw new Error('账户列表加载失败');
      const data = await response.json();
      setBankAccounts(Array.isArray(data) ? data : []);
      // 首次进来把流水账落到第一个账户上，省得空着
      if (!ledgerAccountId && data.length) setLedgerAccountId(String(data[0].id));
    } catch (err) {
      setNotice(err.message || '账户列表加载失败');
    }
  }

  async function refreshBankTransfers() {
    try {
      const response = await fetch(`${API_BASE}/bank-transfers`, { headers: authHeaders() });
      if (!response.ok) throw new Error('转账记录加载失败');
      const data = await response.json();
      setBankTransfers(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '转账记录加载失败');
    }
  }

  async function refreshAccountLedger(accountId, range) {
    const id = accountId ?? ledgerAccountId;
    if (!id) {
      setAccountLedger(null);
      return;
    }
    const span = range ?? ledgerRange;
    try {
      const params = new URLSearchParams();
      if (span.from) params.set('from_date', span.from);
      if (span.to) params.set('to_date', span.to);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/bank-accounts/${id}/ledger${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('账户流水加载失败');
      setAccountLedger(await response.json());
    } catch (err) {
      setNotice(err.message || '账户流水加载失败');
    }
  }

  // ——— 总账 / 复式记账 ———
  async function refreshGlAccounts() {
    try {
      const response = await fetch(`${API_BASE}/ledger/accounts`, { headers: authHeaders() });
      if (!response.ok) throw new Error('科目列表加载失败');
      const data = await response.json();
      const accounts = Array.isArray(data?.accounts) ? data.accounts : [];
      setGlAccounts(accounts);
      if (!glAccountCode && accounts.length) setGlAccountCode(String(accounts[0].code));
    } catch (err) {
      setNotice(err.message || '科目列表加载失败');
    }
  }

  async function refreshGlEntries() {
    try {
      const response = await fetch(`${API_BASE}/ledger/journal-entries?limit=200`, { headers: authHeaders() });
      if (!response.ok) throw new Error('凭证列表加载失败');
      const data = await response.json();
      setGlEntries(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '凭证列表加载失败');
    }
  }

  async function refreshGlBalance(range) {
    const span = range ?? glRange;
    try {
      const params = new URLSearchParams();
      if (span.from) params.set('from_date', span.from);
      if (span.to) params.set('to_date', span.to);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/ledger/balance${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('科目余额表加载失败');
      setGlBalance(await response.json());
    } catch (err) {
      setNotice(err.message || '科目余额表加载失败');
    }
  }

  async function refreshGlDetail(code) {
    const accountCode = code ?? glAccountCode;
    if (!accountCode) {
      setGlDetail(null);
      return;
    }
    setGlDetailBusy(true);
    try {
      const params = new URLSearchParams();
      if (glRange.from) params.set('from_date', glRange.from);
      if (glRange.to) params.set('to_date', glRange.to);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/ledger/account/${accountCode}${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('明细账加载失败');
      setGlDetail(await response.json());
    } catch (err) {
      setNotice(err.message || '明细账加载失败');
    } finally {
      setGlDetailBusy(false);
    }
  }

  async function openGlEntry(entryId) {
    try {
      const response = await fetch(`${API_BASE}/ledger/journal-entries/${entryId}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('凭证详情加载失败');
      setGlEntryDetail(await response.json());
    } catch (err) {
      setNotice(err.message || '凭证详情加载失败');
    }
  }

  const handleBankAccountFormChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setBankAccountForm((prev) => ({ ...prev, [field]: value }));
  };

  const resetBankAccountForm = () => setBankAccountForm(emptyBankAccountForm);

  const startEditBankAccount = (row) => {
    setBankAccountForm({
      id: row.id,
      code: row.code || '',
      name: row.name || '',
      account_type: row.account_type || 'bank',
      bank_name: row.bank_name || '',
      account_no: row.account_no || '',
      init_balance: String(row.init_balance ?? 0),
      sort_order: String(row.sort_order ?? 0),
      is_active: row.is_active !== false,
      note: row.note || '',
    });
    setBankAccountModalOpen(true);
    setNotice('');
  };

  async function submitBankAccount(event) {
    event.preventDefault();
    setSystemBusy(true);
    const isEdit = Boolean(bankAccountForm.id);
    try {
      const response = await fetch(
        isEdit ? `${API_BASE}/bank-accounts/${bankAccountForm.id}` : `${API_BASE}/bank-accounts`,
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({
            code: bankAccountForm.code.trim(),
            name: bankAccountForm.name.trim(),
            account_type: bankAccountForm.account_type,
            bank_name: bankAccountForm.bank_name || null,
            account_no: bankAccountForm.account_no || null,
            init_balance: Number(bankAccountForm.init_balance || 0),
            sort_order: Number(bankAccountForm.sort_order || 0),
            is_active: bankAccountForm.is_active,
            note: bankAccountForm.note || null,
          }),
        },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存账户失败' }));
        throw new Error(errorData.detail ?? '保存账户失败');
      }
      const saved = await response.json();
      setNotice(`账户「${saved.name}」已${isEdit ? '更新' : '创建'}，当前余额 ${money(saved.current_balance)}。`);
      resetBankAccountForm();
      setBankAccountModalOpen(false);
      await refreshBankAccounts();
    } catch (err) {
      setNotice(err.message || '保存账户失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function submitBankTransfer(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/bank-transfers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          from_account_id: Number(bankTransferForm.from_account_id),
          to_account_id: Number(bankTransferForm.to_account_id),
          amount: Number(bankTransferForm.amount || 0),
          transfer_date: bankTransferForm.transfer_date || null,
          handler: bankTransferForm.handler || null,
          note: bankTransferForm.note || null,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '转账失败' }));
        throw new Error(errorData.detail ?? '转账失败');
      }
      const saved = await response.json();
      setNotice(`${saved.transfer_no}：${saved.from_account_name} → ${saved.to_account_name} ${money(saved.amount)} 已记账。`);
      setBankTransferForm(emptyBankTransferForm);
      setBankTransferModalOpen(false);
      await refreshBankAccounts();
      await refreshBankTransfers();
      await refreshAccountLedger();
    } catch (err) {
      setNotice(err.message || '转账失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const handleBankTransferFormChange = (field) => (event) => {
    const value = event.target.value;
    setBankTransferForm((prev) => ({ ...prev, [field]: value }));
  };

  // ——— 日常收支 ———
  const handleEntryFormChange = (field) => (event) => {
    const value = event.target.value;
    setEntryForm((prev) => ({ ...prev, [field]: value }));
  };

  async function submitFinanceEntry(event) {
    event.preventDefault();
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/finance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          transaction_type: entryForm.transaction_type,
          amount: Number(entryForm.amount || 0),
          category: entryForm.category || null,
          bank_account_id: entryForm.bank_account_id ? Number(entryForm.bank_account_id) : null,
          occurred_at: entryForm.occurred_at || null,
          handler: entryForm.handler || null,
          note: entryForm.note || null,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '登记失败' }));
        throw new Error(errorData.detail ?? '登记失败');
      }
      const saved = await response.json();
      const label = saved.transaction_type === 'income' ? '收入' : '支出';
      setNotice(`已登记${label} ${money(saved.amount)}${saved.category ? `（${saved.category}）` : ''}。`);
      setEntryForm((prev) => ({ ...emptyEntryForm, transaction_type: prev.transaction_type, bank_account_id: prev.bank_account_id }));
      await refreshFinanceEntries();
      await refreshBankAccounts();
    } catch (err) {
      setNotice(err.message || '登记失败');
    } finally {
      setSystemBusy(false);
    }
  }

  // 财务流水列表（/finance）—— 只有登录时拉过一次，之后谁改了账都不会自动更新。
  // 财务流水页进入时调它，避免刚收的钱在这一页看不到。
  async function refreshFinance() {
    try {
      const response = await fetch(`${API_BASE}/finance?limit=500`, { headers: authHeaders() });
      if (response.ok) setFinance(await response.json());
    } catch {
      // 拉取失败保留上一次数据
    }
  }

  async function refreshFinanceEntries() {
    try {
      const params = new URLSearchParams();
      Object.entries(entryQuery).forEach(([key, value]) => {
        if (value) params.set(key === 'from' ? 'from_date' : key === 'to' ? 'to_date' : key, value);
      });
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/finance/entries${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('日常收支加载失败');
      setEntryList(await response.json());
    } catch (err) {
      setNotice(err.message || '日常收支加载失败');
    }
  }

  const handleEntryDraftChange = (field) => (event) => {
    const value = event.target.value;
    setEntryDraft((prev) => ({ ...prev, [field]: value }));
  };

  const applyEntryQuery = (event) => {
    if (event) event.preventDefault();
    setEntryQuery({ ...entryDraft });
  };

  const resetEntryQuery = () => {
    setEntryDraft(emptyEntryQuery);
    setEntryQuery(emptyEntryQuery);
  };

  // ——— 组合拆卸（库存管理）———
  async function refreshAssemblyMeta() {
    try {
      const response = await fetch(`${API_BASE}/assembly-orders/meta`, { headers: authHeaders() });
      if (!response.ok) throw new Error('组合拆卸元数据加载失败');
      const data = await response.json();
      setAssemblyMeta(data);
      // 仓库没选过就落到默认仓，省得每次都要手选
      setAssemblyForm((prev) => (prev.warehouse_id ? prev : { ...prev, warehouse_id: data.default_warehouse_id ? String(data.default_warehouse_id) : '' }));
    } catch (err) {
      setNotice(err.message || '组合拆卸元数据加载失败');
    }
  }

  async function refreshAssemblyOrders() {
    try {
      const params = new URLSearchParams();
      if (assemblyFilter) params.set('doc_type', assemblyFilter);
      if (assemblyKeyword) params.set('keyword', assemblyKeyword);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/assembly-orders${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('组合拆卸单加载失败');
      const data = await response.json();
      setAssemblyOrders(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '组合拆卸单加载失败');
    }
  }

  // 按 BOM 带出子件清单（一级展开），并拿到现存量与缺口提示
  async function loadAssemblyBomPreview() {
    const qty = Number(assemblyForm.quantity || 0);
    if (!assemblyForm.product_id || !Number.isFinite(qty) || qty <= 0) return;
    try {
      const params = new URLSearchParams({
        product_id: String(assemblyForm.product_id),
        quantity: String(qty),
        doc_type: assemblyForm.doc_type,
      });
      if (assemblyForm.warehouse_id) params.set('warehouse_id', String(assemblyForm.warehouse_id));
      const response = await fetch(`${API_BASE}/assembly-orders/bom-preview?${params.toString()}`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || '配方载入失败');
      }
      const data = await response.json();
      setAssemblyPreview(data);
      // 数量已经按套数折算成总用量，页面上直接可改
      setAssemblyItems(
        (data.items || []).map((row) => ({
          product_id: String(row.product_id),
          product_name: row.product_name,
          standards: row.standards,
          unit: row.unit,
          per_unit: row.per_unit,
          quantity: String(row.quantity),
          unit_price: row.unit_price,
          on_hand: row.on_hand,
        })),
      );
    } catch (err) {
      setNotice(err.message || '配方载入失败');
    }
  }

  const handleAssemblyFormChange = (field) => (input) => {
    const value = readChangeValue(input);
    setAssemblyForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleAssemblyItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
    setAssemblyItems((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  };

  const removeAssemblyItem = (index) => {
    setAssemblyItems((prev) => prev.filter((_, i) => i !== index));
  };

  // 手工补一行：BOM 不完整、或偶尔多用几颗料时用
  function addAssemblyItem() {
    const pid = assemblyNewItem.product_id;
    if (!pid) {
      setNotice('请先选择要补充的子件。');
      return;
    }
    if (assemblyItems.some((row) => row.product_id === String(pid))) {
      setNotice('该子件已在清单里，直接改它的数量即可。');
      return;
    }
    const product = products.find((item) => String(item.id) === String(pid));
    setAssemblyItems((prev) => [
      ...prev,
      {
        product_id: String(pid),
        product_name: product ? product.name : String(pid),
        standards: product ? product.standards : '',
        unit: product ? product.unit : '',
        per_unit: null,
        quantity: assemblyNewItem.quantity || '1',
        unit_price: product ? product.purchase_price : 0,
        on_hand: null,
      },
    ]);
    setAssemblyNewItem({ product_id: '', quantity: '' });
  }

  async function submitAssemblyOrder(event) {
    event.preventDefault();
    // 成品下拉换成 ErpSearchSelect 后原生 required 失效，这里补守卫
    if (!assemblyForm.product_id) {
      setNotice('请先选择成品。');
      return;
    }
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/assembly-orders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          doc_type: assemblyForm.doc_type,
          product_id: Number(assemblyForm.product_id),
          quantity: Number(assemblyForm.quantity),
          warehouse_id: assemblyForm.warehouse_id ? Number(assemblyForm.warehouse_id) : null,
          order_date: assemblyForm.order_date || null,
          handler: assemblyForm.handler || null,
          note: assemblyForm.note || null,
          items: assemblyItems.map((row) => ({
            product_id: Number(row.product_id),
            quantity: Number(row.quantity || 0),
          })),
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '开单失败' }));
        throw new Error(errorData.detail ?? '开单失败');
      }
      const saved = await response.json();
      const warnings = saved.warnings || [];
      setNotice(
        warnings.length
          ? `${saved.order_no} 已开单（${saved.doc_type_label}）。注意：${warnings.join('；')}`
          : `${saved.order_no} 已开单（${saved.doc_type_label}），库存已同步。`,
      );
      setAssemblyForm((prev) => ({ ...emptyAssemblyForm, warehouse_id: prev.warehouse_id, doc_type: prev.doc_type }));
      setAssemblyItems([]);
      setAssemblyPreview(null);
      await refreshAssemblyOrders();
      refreshStock();
    } catch (err) {
      setNotice(err.message || '开单失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const assemblyItemAmount = (row) => Number(row.quantity || 0) * Number(row.unit_price || 0);

  // ——— 员工档案（基础资料收尾）———
  async function refreshEmployees() {
    try {
      const params = new URLSearchParams();
      if (employeeKeyword) params.set('keyword', employeeKeyword);
      if (employeeDeptFilter) params.set('department_id', employeeDeptFilter);
      if (employeeStatusFilter) params.set('status', employeeStatusFilter);
      const suffix = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`${API_BASE}/employees${suffix}`, { headers: authHeaders() });
      if (!response.ok) throw new Error('员工列表加载失败');
      const data = await response.json();
      setEmployees(Array.isArray(data) ? data : []);
    } catch (err) {
      setNotice(err.message || '员工列表加载失败');
    }
  }

  async function refreshEmployeeMeta() {
    try {
      const response = await fetch(`${API_BASE}/employees/meta`, { headers: authHeaders() });
      if (!response.ok) return;
      setEmployeeMeta(await response.json());
    } catch {
      // 拿不到选项不影响填表：部门可以先不选，状态默认在职
    }
  }

  const handleEmployeeChange = (field) => (event) => {
    const value = event?.target?.type === 'checkbox' ? event.target.checked : event.target.value;
    setEmployeeForm((prev) => ({ ...prev, [field]: value }));
  };

  const resetEmployeeForm = () => {
    setEmployeeForm(emptyEmployeeForm);
    setEditingEmployeeId(null);
  };

  const startEditEmployee = (row) => {
    setEditingEmployeeId(row.id);
    setEmployeeForm({
      code: row.code || '',
      name: row.name || '',
      gender: row.gender || '',
      department_id: row.department_id == null ? '' : String(row.department_id),
      position: row.position || '',
      phone: row.phone || '',
      id_card: row.id_card || '',
      hire_date: row.hire_date || '',
      leave_date: row.leave_date || '',
      status: row.status || 'active',
      base_salary: row.base_salary == null ? '' : String(row.base_salary),
      bank_name: row.bank_name || '',
      bank_account: row.bank_account || '',
      emergency_contact: row.emergency_contact || '',
      emergency_phone: row.emergency_phone || '',
      note: row.note || '',
    });
    setEmployeeModalOpen(true);
    setNotice('');
  };

  const submitEmployee = async (event) => {
    event.preventDefault();
    setNotice('');
    setSystemBusy(true);
    const payload = {
      ...employeeForm,
      code: employeeForm.code.trim(),
      name: employeeForm.name.trim(),
      // 空串要送 null，否则后端会拿 "" 去 int() 转换
      department_id: employeeForm.department_id === '' ? null : Number(employeeForm.department_id),
      base_salary: employeeForm.base_salary === '' ? null : Number(employeeForm.base_salary),
      gender: employeeForm.gender || null,
      hire_date: employeeForm.hire_date || null,
      leave_date: employeeForm.leave_date || null,
    };
    try {
      const isEdit = editingEmployeeId != null;
      const response = await fetch(
        isEdit ? `${API_BASE}/employees/${editingEmployeeId}` : `${API_BASE}/employees`,
        {
          method: isEdit ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存员工失败' }));
        throw new Error(errorData.detail ?? '保存员工失败');
      }
      const saved = await response.json();
      setNotice(`员工「${saved.name}」已${isEdit ? '更新' : '新增'}。`);
      resetEmployeeForm();
      setEmployeeModalOpen(false);
      await refreshEmployees();
    } catch (err) {
      setNotice(err.message || '保存员工失败');
    } finally {
      setSystemBusy(false);
    }
  };

  const departmentLabel = (id) => {
    const hit = (employeeMeta.departments || []).find((d) => d.id === id);
    return hit ? hit.label : '—';
  };

  // ——— 期初建账（库存 / 应收 / 应付）———
  async function refreshOpeningStock() {
    try {
      const response = await fetch(`${API_BASE}/opening-stock`, { headers: authHeaders() });
      if (!response.ok) throw new Error('期初库存加载失败');
      const data = await response.json();
      setOpeningRows(data.items || []);
      setOpeningSummary(data.summary || { lines: 0, total_quantity: 0, total_amount: 0, business_lines: 0 });
    } catch (err) {
      setNotice(err.message || '期初库存加载失败');
    }
  }

  async function refreshOpeningBalances() {
    try {
      const response = await fetch(`${API_BASE}/opening-balances`, { headers: authHeaders() });
      if (!response.ok) throw new Error('期初应收应付加载失败');
      const data = await response.json();
      setOpeningBalances(data);
      // 草稿用服务端值重置，保证「没动过」和「原值」一致
      const draft = {};
      (data.receivables || []).forEach((row) => {
        draft[`customer-${row.id}`] = {
          init_amount: String(row.init_amount ?? 0),
          init_invoice_debt: String(row.init_invoice_debt ?? 0),
        };
      });
      (data.payables || []).forEach((row) => {
        draft[`supplier-${row.id}`] = {
          init_amount: String(row.init_amount ?? 0),
          init_invoice_debt: String(row.init_invoice_debt ?? 0),
        };
      });
      setBalanceDraft(draft);
    } catch (err) {
      setNotice(err.message || '期初应收应付加载失败');
    }
  }

  // 期初录入行的通用 setter。
  // 兼容两种入参：原生控件给的 event（`event.target.value`），
  // 以及 ErpSearchSelect / 自定义组件直接回传的原始值。
  // 与 makeOrderItemHandler 里的 `readChangeValue` 同一口径 —— 商品那格已经
  // 换成可搜索下拉，它回传的是字符串 id，没有 target。
  const handleOpeningDraftChange = (field) => (input) => {
    const value = readChangeValue(input);
    setOpeningDraft((prev) => ({ ...prev, [field]: value }));
  };

  // 把录入表单的内容加进待保存清单。同一「仓库 × 商品」只留一行（后填的覆盖先填的），
  // 否则一次提交里会出现两行同样的键 —— 后端 upsert 两次，最后一行赢，人会看糊涂。
  function addOpeningDraftRow() {
    const { warehouse_id, product_id } = openingDraft;
    if (!warehouse_id || !product_id) {
      setNotice('请先选择仓库与商品。');
      return;
    }
    const quantity = Number(openingDraft.quantity || 0);
    const unit_price = Number(openingDraft.unit_price || 0);
    if (!Number.isFinite(quantity) || quantity < 0) {
      setNotice('期初数量必须是不小于 0 的数字。');
      return;
    }
    if (!Number.isFinite(unit_price) || unit_price < 0) {
      setNotice('成本单价必须是不小于 0 的数字。');
      return;
    }
    const row = {
      warehouse_id: String(warehouse_id),
      product_id: String(product_id),
      quantity,
      unit_price,
      note: openingDraft.note || '',
    };
    setOpeningDraftRows((prev) => {
      const rest = prev.filter((item) => !(item.warehouse_id === row.warehouse_id && item.product_id === row.product_id));
      return [...rest, row];
    });
    setOpeningDraft(emptyOpeningDraft);
    setNotice('已加入待保存清单，记得点「保存全部」。');
  }

  const removeOpeningDraftRow = (index) => {
    setOpeningDraftRows((prev) => prev.filter((_, i) => i !== index));
  };

  // 从已有期初载入到录入表单，改成新值再加回清单即可（后端按仓库×商品覆盖）
  const loadOpeningRowIntoDraft = (row) => {
    setOpeningDraft({
      warehouse_id: String(row.warehouse_id),
      product_id: String(row.product_id),
      quantity: String(row.quantity ?? 0),
      unit_price: String(row.unit_price ?? 0),
      note: row.note || '',
    });
    // 记住"正在改哪一条"：表单按钮随之从「加入清单」变成「保存修改」，
    // 点它直接按 (仓库×商品) upsert 落库，不用再走"加入清单 → 保存全部"两步。
    setOpeningEditingId(row.id);
    setOpeningTab('stock');
    setNotice(`已载入「${row.product_name || '该商品'}」的期初，改完点「保存修改」。`);
  };

  /** 放弃编辑，回到"新增一行"的状态 */
  const cancelOpeningEdit = () => {
    setOpeningEditingId(null);
    setOpeningDraft({ warehouse_id: '', product_id: '', quantity: '', unit_price: '', note: '' });
  };

  /** 把当前草稿按"一条"保存（编辑态专用）：PUT /opening-stock 是幂等 upsert */
  async function saveOpeningSingle() {
    const wid = Number(openingDraft.warehouse_id || 0);
    const pid = Number(openingDraft.product_id || 0);
    if (!wid || !pid) {
      setNotice('先选好仓库和商品再保存。');
      return;
    }
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/opening-stock`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          items: [
            {
              warehouse_id: wid,
              product_id: pid,
              quantity: Number(openingDraft.quantity || 0),
              unit_price: Number(openingDraft.unit_price || 0),
              note: openingDraft.note || '',
            },
          ],
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(parseApiDetail(data && data.detail, '保存期初失败'));
      setNotice('期初已更新。');
      setOpeningEditingId(null);
      setOpeningDraft({ warehouse_id: '', product_id: '', quantity: '', unit_price: '', note: '' });
      await refreshOpeningStock();
    } catch (err) {
      setNotice(err.message || '保存期初失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const draftAmount = (row) => Number(row.quantity || 0) * Number(row.unit_price || 0);

  async function saveOpeningStock() {
    if (openingDraftRows.length === 0) {
      setNotice('待保存清单是空的，先把要建账的项加进来。');
      return;
    }
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/opening-stock`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          items: openingDraftRows.map((row) => ({
            warehouse_id: Number(row.warehouse_id),
            product_id: Number(row.product_id),
            quantity: Number(row.quantity || 0),
            unit_price: Number(row.unit_price || 0),
            note: row.note || null,
          })),
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存期初失败' }));
        throw new Error(errorData.detail ?? '保存期初失败');
      }
      const data = await response.json();
      setOpeningDraftRows([]);
      setNotice(`${data.message}。期初会直接计入现存量，请到「库存管理」核对。`);
      await refreshOpeningStock();
    } catch (err) {
      setNotice(err.message || '保存期初失败');
    } finally {
      setSystemBusy(false);
    }
  }

  async function clearOpeningStock() {
    setOpeningClearAsk(false);
    setSystemBusy(true);
    try {
      const response = await fetch(`${API_BASE}/opening-stock/clear`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error('清空期初失败');
      const data = await response.json();
      setOpeningDraftRows([]);
      setNotice(`${data.message}。注意：现存量的期初基数已经归零。`);
      await refreshOpeningStock();
    } catch (err) {
      setNotice(err.message || '清空期初失败');
    } finally {
      setSystemBusy(false);
    }
  }

  const handleBalanceDraftChange = (entity, id, field) => (event) => {
    const value = event.target.value;
    setBalanceDraft((prev) => ({
      ...prev,
      [`${entity}-${id}`]: { ...(prev[`${entity}-${id}`] || {}), [field]: value },
    }));
  };

  async function saveOpeningBalances() {
    setSystemBusy(true);
    try {
      const collect = (rows, entity) =>
        rows
          .map((row) => {
            const draft = balanceDraft[`${entity}-${row.id}`];
            return {
              id: row.id,
              init_amount: Number(draft?.init_amount ?? row.init_amount ?? 0),
              init_invoice_debt: Number(draft?.init_invoice_debt ?? row.init_invoice_debt ?? 0),
            };
          })
          .filter((item) => Number.isFinite(item.init_amount) && Number.isFinite(item.init_invoice_debt));
      const response = await fetch(`${API_BASE}/opening-balances`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          receivable: collect(openingBalances.receivables || [], 'customer'),
          payable: collect(openingBalances.payables || [], 'supplier'),
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存期初往来失败' }));
        throw new Error(errorData.detail ?? '保存期初往来失败');
      }
      const data = await response.json();
      setOpeningBalances(data);
      setNotice(data.message || '期初应收应付已保存。');
    } catch (err) {
      setNotice(err.message || '保存期初往来失败');
    } finally {
      setSystemBusy(false);
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


  const handleOutsourcingChange = (field) => (input) => {
    const value = readChangeValue(input);
    setOutsourcingForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'product_id') {
        const product = products.find((item) => String(item.id) === String(value));
        if (product) next.unit_price = String(product.purchase_price ?? '0');
      }
      return next;
    });
  };

  const handleOutsourcingItemChange = (index, field) => (input) => {
    const value = readChangeValue(input);
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

    // 商品原来靠原生 `required` 拦；换成 ErpSearchSelect 后那条路断了，
    // 不补守卫就会把 `Number('') === 0` 当合法商品 id 发出去。
    // 仓库仍是原生 select（第三批才换），这里一并先挡上，换成组件时不用再改。
    if (!inventoryForm.product_id) {
      setNotice('请先选择商品。');
      return;
    }
    if (!inventoryForm.warehouse_id) {
      setNotice('请先选择仓库。');
      return;
    }

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

  // 侧边栏数据源（统一成 { label, page_key, children[] } 一种形状，渲染只认这一种）。
  //
  // 优先用后端下发的菜单树 —— 它是**展示结构**，管理员可以在「菜单管理」里
  // 自由增删层级、改名、换父级、隐藏。权限过滤已经在后端做过了
  // （只留有权限的菜单项 + 还有子孙的分组），所以这里不用再过滤一遍。
  //
  // 拿不到菜单树（接口失败 / 老版本后端）时回退到内置的 `menuGroups`：
  // 侧边栏是用户唯一的导航，宁可显示得多一点，也不能整块空掉。
  const visibleGroups = useMemo(() => {
    if (Array.isArray(menuTree) && menuTree.length > 0) return menuTree;
    const allowed = myPermissions && !myPermissions.all ? new Set(myPermissions.menus) : null;
    return menuGroups
      .map((group) => ({
        label: group.label,
        page_key: '',
        children: group.items
          .filter((item) => !allowed || allowed.has(item.key))
          .map((item) => ({ label: item.label, page_key: item.key, children: [] })),
      }))
      .filter((group) => group.children.length > 0);
  }, [menuTree, myPermissions]);

  // 在菜单树里按页面 key 找节点（用于顶栏标题 / 分组名）。
  // 管理员可能给同一个页面挂多个菜单，取**先遇到的**那个，保证标题稳定。
  const findMenuNode = useCallback((nodes, pageKey) => {
    for (const node of nodes || []) {
      if (node.page_key === pageKey) return node;
      const hit = findMenuNode(node.children, pageKey);
      if (hit) return hit;
    }
    return null;
  }, []);

  // 把菜单树摊平成 [{ depth, ...node }]，交给「菜单管理」页渲染缩进列表
  const flattenMenuTree = useCallback((nodes, depth = 1, out = []) => {
    (nodes || []).forEach((node) => {
      out.push({ ...node, depth });
      flattenMenuTree(node.children, depth + 1, out);
    });
    return out;
  }, []);

  // 权限收紧后当前页可能已经不可见（例如管理员刚把自己的角色改了），
  // 或者管理员刚把某个菜单删了/隐藏了 —— 都自动落到第一个可见页。
  useEffect(() => {
    const pages = new Set();
    const collect = (nodes) => {
      (nodes || []).forEach((node) => {
        if (node.page_key) pages.add(node.page_key);
        collect(node.children);
      });
    };
    collect(visibleGroups);
    if (pages.size && !pages.has(selectedTab)) {
      const first = [...pages][0];
      if (first) setSelectedTab(first);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleGroups]);

  // 库存预警开关：系统参数 stock.warn_enabled。取不到时按开启处理（与出厂默认一致）
  const stockWarnEnabled = myPermissions?.ui?.stock_warn_enabled !== false;

  const toggleGroup = (groupKey) => {
    setCollapsedGroups((prev) =>
      prev.includes(groupKey) ? prev.filter((key) => key !== groupKey) : [...prev, groupKey],
    );
  };

  // 切换左侧导航配色。写进 localStorage，下次打开还是这套。
  const chooseNavTheme = (theme) => {
    setNavTheme(theme);
    try {
      localStorage.setItem('erp.navTheme', theme);
    } catch {
      /* 无痕模式写不了 localStorage，本次会话内仍然生效 */
    }
  };

  /** 智能指令「去修改/去确认」的统一落点（2026-10-23）。
   *
   *  两件事必须一起做：**切页面** + **把筛选条件填好**。
   *  只切页面的话用户还得自己再搜一遍单位，等于没帮他。
   *
   *  · 对账单：走 `statementPreset`（scope + party + nonce）。nonce 变化会让
   *    StatementEditor 重挂载 —— 已经在那一页时也能把新单位带进去。
   *  · 合同：把关键字写进 `contractKeyword` 并立即按它拉一次列表。
   */
  const agentGoto = useCallback((payload) => {
    if (!payload || !payload.page) return;
    if (payload.page === 'statements-editor') {
      setStatementPreset((prev) => ({
        scope: payload.scope === 'in' ? 'in' : payload.scope === 'all' ? 'all' : 'out',
        party: payload.party || '',
        name: payload.party_name || '',
        nonce: (prev?.nonce || 0) + 1,
      }));
      setSelectedTab('statements-editor');
      setNotice(
        payload.party_name
          ? `已跳到增强对账单，并锁定「${payload.party_name}」。`
          : '已跳到增强对账单。',
      );
      return;
    }
    if (payload.page === 'contracts') {
      const keyword = payload.keyword || payload.party_name || '';
      setContractKeyword(keyword);
      setSelectedTab('contracts');
      refreshContracts(keyword);
      setNotice(keyword ? `已跳到购销合同，并按「${keyword}」筛选。` : '已跳到购销合同。');
      return;
    }
    // 2026-10-24：智能指令下拉的「分类节点」落点 —— "周广平"这类名字常以
    // 客户/供应商分类存在，点它就该去档案页看这个分类下的档案。
    if (payload.page === 'customers') {
      const keyword = payload.keyword || '';
      setCustomerSearch(keyword);
      setSelectedTab('customers');
      setNotice(keyword ? `已跳到客户档案，并按「${keyword}」筛选。` : '已跳到客户档案。');
      return;
    }
    if (payload.page === 'suppliers') {
      const keyword = payload.keyword || '';
      setSupplierSearch(keyword);
      setSelectedTab('suppliers');
      setNotice(keyword ? `已跳到供应商档案，并按「${keyword}」筛选。` : '已跳到供应商档案。');
      return;
    }
  }, []);

  // 点菜单项的统一入口。对账单两个菜单是「往来对账」的预设视图（菜单别名），
  // 点它们要顺手把往来类型锁上并说明一句，免得用户以为跳错了。
  const gotoMenu = useCallback((pageKey, label = '') => {
    if (!pageKey) return;
    // 用户主动点了菜单 —— 之后异步回来的登录落地页不许再把他顶走（见 userNavigatedRef 声明处）
    userNavigatedRef.current = true;
    const alias = LEDGER_ALIASES[pageKey];
    if (alias) {
      setLedgerParty((prev) => ({ ...prev, party_type: alias, party_id: '' }));
      setSelectedTab('ledger');
      setActiveMenuEntry({ pageKey, label: label });
      setNotice(
        pageKey === 'purchase-statement'
          ? '采购对账单就是按供应商看的往来对账，已切到供应商视图。'
          : '销售对账单就是按客户看的往来对账，已切到客户视图。',
      );
    } else {
      setSelectedTab(pageKey);
      setActiveMenuEntry({ pageKey, label: label });
    }
    // 手机端选完菜单把抽屉收起来，免得挡住内容
    setMenuOpen(false);
  }, []);

  // 递归渲染导航节点：支持「分组 → 子分组 → 菜单项」三级。
  // 判据只有一个 —— 有 children 就是可折叠的分组，没有就是菜单项（叶子）。
  const renderNavNodes = (nodes, depth = 0) => {
    return (nodes || []).map((node) => {
      const children = node.children || [];
      // 折叠标识带上层级，否则不同层级出现同名分组会一起折叠
      const collapseKey = `${depth}:${node.label}`;
      if (children.length > 0) {
        const isCollapsed = collapsedGroups.includes(collapseKey);
        const hasActive = (function subtreeHasActive(list) {
          return list.some((child) =>
            (child.children || []).length > 0 ? subtreeHasActive(child.children) : child.page_key === selectedTab,
          );
        })(children);
        return (
          <div className={`nav-group ${hasActive ? 'has-active' : ''}`} key={collapseKey}>
            <button
              type="button"
              className={`nav-group-title ${isCollapsed ? 'collapsed' : ''}`}
              onClick={() => toggleGroup(collapseKey)}
              aria-expanded={!isCollapsed}
            >
              <span>{node.label}</span>
              <span className="nav-group-arrow" aria-hidden="true" />
            </button>
            {!isCollapsed && <div className="nav-group-items">{renderNavNodes(children, depth + 1)}</div>}
          </div>
        );
      }
      const todo = tabs.find((tab) => tab.key === node.page_key)?.todo;
      return (
        <button
          key={`${collapseKey}:${node.page_key}`}
          className={`nav-item nav-depth-${depth} ${selectedTab === node.page_key ? 'active' : ''} ${todo ? 'is-todo' : ''}`}
          onClick={() => gotoMenu(node.page_key, node.label)}
          type="button"
          title={todo ? '框架位已按浩技云预留，功能建设中' : undefined}
        >
          <span>{node.label}</span>
          {todo && <span className="nav-todo">待建</span>}
        </button>
      );
    });
  };

  const activeTab = useMemo(() => tabs.find((tab) => tab.key === selectedTab), [selectedTab]);

  // —— 商品类别：拍平成「带缩进路径」的候选项（类别弹窗的「上级类别」下拉用）——
  // 这里原本还有一个 flattenCategories（只取 n.name，给表单 datalist 当候选）。
  // 2026-10-16 把商品弹窗抽成 components/product-edit/ProductEditModal.jsx 之后
  // 它已无任何调用点（候选改由组件内部的 collectCategoryNames 提供），
  // 故连同 appCtx 里的导出一起删除。
  const flattenCategoryOptions = (nodes, depth = 0, acc = []) => {
    (nodes || []).forEach((n) => {
      acc.push({ id: n.id, path: '　'.repeat(depth) + n.name });
      if (n.children?.length) flattenCategoryOptions(n.children, depth + 1, acc);
    });
    return acc;
  };

  // —— 左侧类别树：每个类别（含其全部子孙）下的商品数，树上显示角标 ——
  // "点进去才发现是空的"很烦，有了角标点之前就知道。
  const categoryCounts = useMemo(
    () => countProductsByCategory(products, productCategories),
    [products, productCategories],
  );

  // 左侧类别树。本体是独立组件 `src/components/product-category/ProductCategoryTree.jsx`
  // （纯展示，选中态由这里传入 —— 因为右侧列表的过滤发生在本文件，
  //   选中态要是留在组件里，filteredProducts 就看不到了）。
  // 这里只做 ctx → props 的转接，保持 ProductsPage 那边一行调用不变。
  /* 商品分类树：拖拽落点/高亮由 ProductsBoard 现场传入（它才有拖动中的 id 列表），
     所以这里把 options 透传下去 —— 树本身仍是"受控 + 无状态业务"的。 */
  const renderCategoryNodes = (options = {}) => (
    <ProductCategoryTree
      nodes={productCategories}
      /* 商品级搜索要用到商品名/SKU（2026-10-23）：与右侧列表同一份数据 */
      products={products}
      value={categoryFilter}
      onChange={setCategoryFilter}
      counts={categoryCounts}
      busy={productBusy}
      onAddChild={(node) => openCategoryModal('create', node)}
      onEdit={(node) => openCategoryModal('edit', node)}
      onDelete={removeCategory}
      // 拖拽排序/改层级：不传 onMove，组件里 canDrag=false —— 手柄和拖拽会整体消失
      onMove={moveCategory}
      {...options}
    />
  );

  // 档案搜索：主界面列表顶部的模糊检索（编码/名称/电话/邮箱）
  const filteredCustomers = useMemo(() => {
    const q = customerSearch.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter((row) =>
      [row.code, row.name, row.phone, row.email].some((v) => v != null && String(v).toLowerCase().includes(q)),
    );
  }, [customers, customerSearch]);

  const filteredSuppliers = useMemo(() => {
    const q = supplierSearch.trim().toLowerCase();
    if (!q) return suppliers;
    return suppliers.filter((row) =>
      [row.code, row.name, row.phone, row.email].some((v) => v != null && String(v).toLowerCase().includes(q)),
    );
  }, [suppliers, supplierSearch]);

  // 商品过滤：先按左侧类别树的选中项（**含该类别下的全部子孙**），再按搜索词。
  // 类别那一段是纯函数，放在 ./lib/productCategory.js 里，有 17 条 node --test 守着。
  const filteredProducts = useMemo(() => {
    const rows = filterProductsByCategory(products, productCategories, categoryFilter);
    const q = productSearch.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      [row.name, row.sku, row.bar_code, row.mnemonic, row.standards, row.serial_no, row.category].some(
        (v) => v != null && String(v).toLowerCase().includes(q),
      ),
    );
  }, [products, productSearch, categoryFilter, productCategories]);

  // 顶栏标题 / 分组名：**优先用菜单树里的名字**。
  // 管理员把「客户档案」改成「客户」之后，侧边栏变了顶栏却还写着旧名，
  // 会让人以为点错了页面。菜单树里找不到（或树还没回来）才退回内置定义。
  const currentMenuNode = useMemo(
    () => findMenuNode(visibleGroups, selectedTab),
    [visibleGroups, selectedTab, findMenuNode],
  );
  const currentMenuParent = useMemo(() => {
    const locate = (nodes, parentLabel) => {
      for (const node of nodes || []) {
        if (node.page_key === selectedTab) return parentLabel;
        const found = locate(node.children, node.children?.length ? node.label : parentLabel);
        if (found !== undefined && found !== null) return found;
      }
      return undefined;
    };
    const found = locate(visibleGroups, null);
    return found || null;
  }, [visibleGroups, selectedTab]);
  // 别名菜单落到 ledger 页时 activeMenuEntry 存的是别名 key，与 selectedTab 不同名，
  // 所以只做"是否还有效"的宽松校验：页面被别的路径切走后就不再沿用旧入口名。
  const activeEntryLabel =
    activeMenuEntry && (activeMenuEntry.pageKey === selectedTab || LEDGER_ALIASES[activeMenuEntry.pageKey])
      ? activeMenuEntry.label
      : '';
  const currentPageLabel =
    activeEntryLabel || currentMenuNode?.label || activeTab?.label || '运营概览';
  const currentGroupLabel =
    currentMenuParent || activeTab?.groupLabel || '本地 ERP 管理后台';
  // 当前页面该显示在顶栏右上角的快捷入口（见文件顶部的 pageActions）
  const currentActions = pageActions[selectedTab] || [];

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
        {/* 左下角版本 + 品牌（2026-10-24）：登录页此前**从来没有**渲染过这个元素
            （不是被暗黑模式 CSS 覆盖或删除）。补上的目的：
            远程排查"用户跑的是哪一版"时，不用问、截图里就能看到 vNN。 */}
        <div className="auth-corner" data-app-version={APP_VERSION_LABEL}>
          <span className="auth-corner-brand">寨卡 ERP 管理系统</span>
          <span className="auth-corner-ver">
            {APP_VERSION_LABEL} · 构建 {APP_BUILD_AT}
          </span>
        </div>
        <div className="auth-stage">
          <div className="auth-card">
            <div className="auth-brand">
              <div className="auth-logo" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2 4 6v6c0 5 3.4 8.4 8 10 4.6-1.6 8-5 8-10V6l-8-4Z" />
                  <path d="M9 12l2 2 4-4" />
                </svg>
              </div>
              <h1>寨卡 ERP 管理中心</h1>
              <p className="auth-tagline">安全登录，高效协作</p>
            </div>

            <form onSubmit={submitLogin} className="auth-form">
              <div className="auth-field">
                <label htmlFor="auth-account">手机号 / 邮箱</label>
                <div className="auth-control">
                  <svg className="auth-lead-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                  <input
                    id="auth-account"
                    value={loginForm.username}
                    onChange={handleLoginChange('username')}
                    placeholder="请输入手机号或邮箱"
                    autoComplete="username"
                  />
                </div>
              </div>

              <div className="auth-field">
                <label htmlFor="auth-password">密码</label>
                <div className="auth-control">
                  <svg className="auth-lead-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <input
                    id="auth-password"
                    type={showLoginPassword ? 'text' : 'password'}
                    value={loginForm.password}
                    onChange={handleLoginChange('password')}
                    placeholder="请输入密码"
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="auth-eye"
                    onClick={() => setShowLoginPassword((v) => !v)}
                    aria-label={showLoginPassword ? '隐藏密码' : '显示密码'}
                  >
                    {showLoginPassword ? (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                        <path d="M1 1l22 22" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12Z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <div className="auth-row">
                <label className="auth-remember">
                  <input type="checkbox" defaultChecked />
                  记住我
                </label>
                <a className="auth-link" href="#" onClick={(e) => e.preventDefault()}>忘记密码？</a>
              </div>

              <button className="auth-submit" type="submit" disabled={loginLoading}>
                {loginLoading && <span className="auth-spinner" aria-hidden="true" />}
                {loginLoading ? '登录中…' : '登录'}
              </button>

              {notice && <div className="auth-notice">{notice}</div>}
            </form>

            <div className="auth-divider">或使用以下方式登录</div>

            <div className="auth-socials">
              <button type="button" className="auth-social" onClick={() => setNotice('微信登录暂未开通')}>
                <svg viewBox="0 0 24 24" fill="#22c55e">
                  <path d="M9.5 4C5.9 4 3 6.4 3 9.4c0 1.7 1 3.2 2.4 4.2l-.6 2 2.3-1.2c.9.3 1.9.4 2.9.4h.5c-.1-.4-.2-.9-.2-1.3 0-3 2.9-5.4 6.5-5.4h.6C16.9 5.7 14.6 4 11.7 4h-2.2z" />
                  <path d="M21.5 13.6c0-2.4-2.4-4.4-5.3-4.4s-5.3 2-5.3 4.4 2.4 4.4 5.3 4.4c.8 0 1.5-.1 2.2-.4l1.9 1-.5-1.6c1-.8 1.7-2 1.7-3.4z" />
                </svg>
                微信登录
              </button>
              <button type="button" className="auth-social" onClick={() => setNotice('Google 登录暂未开通')}>
                <svg viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.5 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.9c-.3 1.4-1 2.5-2.1 3.3v2.7h3.4c2-1.8 3.3-4.5 3.3-7.9z" />
                  <path fill="#34A853" d="M12 23c2.9 0 5.3-1 7.1-2.6l-3.4-2.7c-1 .6-2.2 1-3.7 1-2.8 0-5.2-1.9-6.1-4.5H2.4v2.8C4.2 20.5 7.8 23 12 23z" />
                  <path fill="#FBBC05" d="M5.9 14.2c-.2-.6-.4-1.3-.4-2.2s.1-1.5.4-2.2V7H2.4C1.5 8.5 1 10.2 1 12s.5 3.5 1.4 5l3.5-2.8z" />
                  <path fill="#EA4335" d="M12 5.4c1.6 0 3 .5 4.1 1.6l3-3C17.3 2.2 14.9 1 12 1 7.8 1 4.2 3.5 2.4 7l3.5 2.8C6.8 7.3 9.2 5.4 12 5.4z" />
                </svg>
                Google
              </button>
            </div>

            <div className="auth-foot">
              还没有账号？<a className="auth-link" href="#" onClick={(e) => e.preventDefault()}>注册</a>
              <p className="auth-privacy">登录即表示同意《服务条款》与《隐私政策》</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 自动注入：打包 App 作用域标识符给页面组件（见 scripts/extract_pages.py）
  // 自动注入：打包 App 作用域标识符给页面组件（见 scripts/extract_pages.py）
  const appCtx = {
  ADJUSTMENT_STATUS_LABEL,
  ADJUST_TYPE_DIRECTION,
  ADJUST_TYPE_LABEL,
  API_BASE,
  agentGoto,
  BANK_ACCOUNT_TYPE_LABEL,
  CONTRACT_STATUS_LABEL,
  DOC_STATUS_LABELS,
  DOC_TYPE_LABEL,
  // 出库看板的状态表：出库单的 completed 是「已发货」，与 DOC_STATUS_LABELS 的「已转单」不同义。
  // 看板从 ctx 取它，所以必须在这里暴露，否则 AuditBadge 拿到 undefined → labels[status] 报错。
  OUTBOUND_STATUS_LABELS,
  FINISHED_GOODS_STATUS_LABEL,
  Fragment,
  LEDGER_ALIASES,
  LOG_STATUS_TONE,
  LOOKUP_TYPES,
  MATERIAL_ISSUE_STATUS_LABEL,
  MATERIAL_RETURN_STATUS_LABEL,
  MRP_STATUS_LABEL,
  NAV_THEMES,
  OPENING_TABS,
  OUTSOURCING_STATUS_LABEL,
  PARAM_VALUE_TYPE_LABEL,
  PLAN_TYPE_LABEL,
  PRODUCTION_PLAN_STATUS_LABEL,
  PROJECT_STATUS_LABEL,
  PROJECT_STATUS_TONE,
  PURCHASE_RETURN_STATUS_LABEL,
  QUOTATION_STATUS_LABEL,
  REPORT_DIMENSION_HEAD,
  REPORT_SHAPE_LABEL,
  SALES_RETURN_STATUS_LABEL,
  STOCKTAKING_STATUS_LABEL,
  STOCK_STATUS_LABEL,
  SYSTEM_TABS,
  TRANSFER_STATUS_LABEL,
  Tesseract,
  XLSX,
  accountLedger,
  activeCompany,
  activeDictType,
  activeEntryLabel,
  activeMenuEntry,
  activeTab,
  activeTemplate,
  activeTemplateType,
  addAdjustmentItem,
  addAssemblyItem,
  addContractItem,
  addFinishedGoodsItem,
  addInboundItem,
  addIssueItem,
  addMrpItem,
  addOpeningDraftRow,
  addOutboundItem,
  addOutsourcingItem,
  addPlanItem,
  addPurchaseOrderItem,
  // 2026-10-21 补回：批量选商品 + 复制行（OrderBoard 按命名约定取用）
  addProductsToPurchaseOrder,
  addProductsToSalesOrder,
  addPurchaseReturnItem,
  addQuotationItem,
  addReturnItem,
  addSalesOrderItem,
  addSalesReturnItem,
  addStocktakingItem,
  addTransferItem,
  adjustTypeLabel,
  adjustmentForm,
  adjustmentKeyword,
  adjustmentStatusLabel,
  adjustmentTypeFilter,
  adjustments,
  agentPrompt,
  agentResponse,
  aging,
  analysisRange,
  applyCompanySession,
  applyEntryQuery,
  applyLogQuery,
  applyTemplateDraft,
  approvePurchaseOrder,
  approveSalesOrder,
  archiveFocus,
  assemblyFilter,
  assemblyForm,
  assemblyItemAmount,
  assemblyItems,
  assemblyKeyword,
  assemblyMeta,
  assemblyNewItem,
  assemblyOrders,
  assemblyPreview,
  authHeaders,
  authToken,
  balanceDraft,
  bankAccountForm,
  bankAccountModalOpen,
  bankAccounts,
  bankTransferForm,
  bankTransferModalOpen,
  bankTransfers,
  batchDeleteCustomers,
  batchDeleteProducts,
  batchDeleteSuppliers,
  bomForm,
  bomTree,
  cards,
  categoryFilter,
  categoryModal,
  changeInvoiceDirection,
  chooseNavTheme,
  classifyInvoiceBatch,
  clearInventoryFocus,
  clearOpeningStock,
  closeInvoicePreview,
  collapsedGroups,
  companyForm,
  companySwitching,
  confirmDelete,
  confirmExcelImport,
  contractForm,
  contractKeyword,
  contractMeta,
  contractStatusLabel,
  contractToOrder,
  contracts,
  // 2026-10-21 补回：复制行（OrderBoard 按命名约定取用）
  copyPurchaseOrderItem,
  copySalesOrderItem,
  convertPurchaseOrder,
  convertSalesOrder,
  currentActions,
  currentGroupLabel,
  currentMenuNode,
  currentMenuParent,
  currentPageLabel,
  customerForm,
  customerModalOpen,
  customerSearch,
  customers,
  departmentForm,
  departmentLabel,
  departmentOptions,
  dictForm,
  dictItemForm,
  dictItems,
  dictList,
  docTypeLabel,
  financeTypeLabel,
  downloadBase64File,
  downloadExcelTemplate,
  downloadFromApi,
  downloadInvoiceQr,
  downloadInvoiceSource,
  draftAmount,
  dropTemplatePreview,
  editingEmployeeId,
  editingWarehouseId,
  employeeDeptFilter,
  employeeForm,
  employeeKeyword,
  employeeMeta,
  employeeModalOpen,
  employeeStatusFilter,
  employees,
  emptyAdjustmentForm,
  emptyAssemblyForm,
  emptyBankAccountForm,
  emptyBankTransferForm,
  emptyContractForm,
  emptyCustomerForm,
  emptyDepartmentForm,
  emptyDictItemForm,
  emptyDictionaryForm,
  emptyEmployeeForm,
  emptyEntryForm,
  emptyEntryQuery,
  emptyFinanceForm,
  emptyFinishedGoodsForm,
  emptyInboundForm,
  emptyInventoryForm,
  emptyLogQuery,
  emptyMaterialIssueForm,
  emptyMaterialReturnForm,
  emptyMenuForm,
  emptyOpeningDraft,
  emptyOrderItem,
  emptyOutboundForm,
  emptyOutsourcingForm,
  emptyParamForm,
  emptyPermissionDraft,
  emptyProductForm,
  emptyProductionPlanForm,
  emptyPurchaseOrderForm,
  emptyPurchaseReturnForm,
  emptyQuotationForm,
  emptyReportQuery,
  emptyRoleForm,
  emptySalesOrderForm,
  emptySalesReturnForm,
  emptyStockLogFilter,
  emptyStocktakingForm,
  emptySupplierForm,
  emptySystemUserForm,
  emptyTemplateDraft,
  emptyTransferForm,
  emptyWarehouseForm,
  entryDraft,
  entryForm,
  entryList,
  entryQuery,
  error,
  excelBusy,
  excelKinds,
  excelOutcome,
  excelPending,
  executiveDashboard,
  expandedInvoiceIds,
  exportDailyReport,
  exportExcelData,
  exportInvoiceDetailExcel,
  exportInvoiceDetailPdf,
  exportInvoiceQrZip,
  exportInvoiceReport,
  exportInvoiceReportHtml,
  exportInvoiceReportXlsx,
  exportInvoiceSources,
  exportReport,
  filteredCustomers,
  filteredProducts,
  filteredSuppliers,
  finance,
  financeAnalysis,
  financeBusy,
  financeDecision,
  financeForm,
  findMenuNode,
  finishedGoodsForm,
  finishedGoodsKeyword,
  finishedGoodsList,
  finishedGoodsStatusLabel,
  flattenCategoryOptions,
  flattenDepartments,
  flattenMenuTree,
  formatLogTime,
  formatMonth,
  getStoredToken,
  glAccountCode,
  glAccounts,
  glBalance,
  glDetail,
  glDetailBusy,
  glEntries,
  glEntryDetail,
  glRange,
  gotoMenu,
  handleAdjustmentChange,
  handleAdjustmentItemChange,
  handleAnalysisRangeChange,
  handleAssemblyFormChange,
  handleAssemblyItemChange,
  handleBalanceDraftChange,
  handleBankAccountFormChange,
  handleBankTransferFormChange,
  handleBomFormChange,
  handleCompanyChange,
  handleContractChange,
  handleContractItemChange,
  handleCustomerChange,
  handleDeepSeekInvoiceAnalysis,
  handleDeleteConfirm,
  handleDepartmentChange,
  handleDictItemChange,
  handleDictionaryChange,
  handleEmployeeChange,
  handleEntryDraftChange,
  handleEntryFormChange,
  handleExcelFilePicked,
  handleFinanceChange,
  handleFinishedGoodsChange,
  handleFinishedGoodsItemChange,
  handleInboundFormChange,
  handleInboundItemChange,
  handleInventoryChange,
  handleInvoiceAgentAnalysis,
  handleInvoiceUpload,
  handleIssueChange,
  handleIssueItemChange,
  handleLogDraftChange,
  handleLoginChange,
  handleLogout,
  handleMenuFormChange,
  handleMrpChange,
  handleMrpItemChange,
  handleOpeningDraftChange,
  handleOutboundFormChange,
  handleOutboundItemChange,
  handleOutsourcingChange,
  handleOutsourcingItemChange,
  handleParamDraftChange,
  handleParamFormChange,
  handlePlanChange,
  handlePlanItemChange,
  handleProductChange,
  handleProductionChange,
  handleProjectChange,
  handlePurchaseOrderFormChange,
  handlePurchaseOrderItemChange,
  handlePurchaseReturnChange,
  handlePurchaseReturnItemChange,
  handleQuotationChange,
  handleQuotationItemChange,
  handleReportQueryChange,
  handleReturnChange,
  handleReturnItemChange,
  handleRoleChange,
  handleSalesOrderFormChange,
  handleSalesOrderItemChange,
  handleSalesReturnChange,
  handleSalesReturnItemChange,
  handleSetInvoiceDirection,
  handleStocktakingChange,
  handleStocktakingItemChange,
  handleStocktakingProductPick,
  handleSupplierChange,
  handleSyncInvoicesToFinance,
  handleSystemUserChange,
  handleTemplateDraftChange,
  handleToggleCertified,
  handleToggleDeducted,
  handleTransferChange,
  handleTransferItemChange,
  handleWarehouseChange,
  inboundForm,
  inferInvoiceCategory,
  inventory,
  inventoryFocus,
  inventoryForm,
  inventoryKeyword,
  invoiceAgentReport,
  invoiceAggregate,
  invoiceBusy,
  invoiceDetail,
  invoiceDirectionCounts,
  invoiceEditForm,
  invoiceExportOpen,
  invoiceExportTargets,
  invoiceFiltered,
  invoiceItems,
  invoicePage,
  invoicePageAllSelected,
  invoicePageCount,
  invoicePageSize,
  invoicePageSomeSelected,
  invoicePaged,
  invoicePreview,
  invoiceQr,
  invoiceQuery,
  invoiceSafePage,
  invoiceSummary,
  isAuthenticated,
  isTemplateCustomized,
  issueSuggestionHint,
  jsQR,
  jumpToArchive,
  jumpToStock,
  leadershipBoard,
  ledgerAccountId,
  ledgerData,
  ledgerParty,
  ledgerRange,
  loadAging,
  loadAssemblyBomPreview,
  loadCompanySettings,
  loadContractMeta,
  loadExcelKinds,
  loadIssueSuggestion,
  loadLedger,
  loadLookups,
  loadMyPermissions,
  loadOpeningRowIntoDraft,
  loadProductCategories,
  loadQuotationMeta,
  loadStocktakingPlan,
  loadSystemMeta,
  loading,
  logBusy,
  logDraft,
  logPage,
  logPageNo,
  logQuery,
  loginForm,
  lookupItems,
  lookupValues,
  lookups,
  makeAddItem,
  makeOrderItemHandler,
  makeRemoveItem,
  makeSubmitOrder,
  makeSubmitStockDoc,
  materialIssueForm,
  materialIssueKeyword,
  materialIssueStatusLabel,
  materialIssues,
  materialReturnForm,
  materialReturnKeyword,
  materialReturnStatusLabel,
  materialReturns,
  menuAdmin,
  menuForm,
  menuGroups,
  menuOpen,
  menuTree,
  mobileDashboard,
  mobileQuickActions,
  money,
  mrpBusy,
  mrpForm,
  mrpResult,
  mrpStatusLabel,
  myCompanies,
  myPermissions,
  navTheme,
  normalizeInvoiceRecord,
  normalizeInvoiceRows,
  notice,
  openCategoryModal,
  openCustomerEdit,
  openGlEntry,
  openInvoiceEdit,
  openInvoicePreview,
  openInvoiceQr,
  openOrderPayment,
  openProductEdit,
  openProjectCost,
  openProjectEdit,
  openSupplierEdit,
  openingBalances,
  openingClearAsk,
  openingDraft,
  openingDraftRows,
  openingRows,
  openingSummary,
  openingTab,
  operationsBoard,
  outboundForm,
  outsourcingForm,
  outsourcingKeyword,
  outsourcingStatusLabel,
  outsourcings,
  overviewTrend,
  pageActions,
  paramDraft,
  paramForm,
  paramGroups,
  paramTotal,
  parseInvoiceText,
  parseStructuredInvoiceText,
  passwordDraft,
  passwordTarget,
  payables,
  pdfjsLib,
  permissionDraft,
  plain,
  planTypeLabel,
  previewPrintTemplate,
  printParty,
  printPdf,
  printPeriodQuery,
  printTemplates,
  productBusy,
  productById,
  productCategories,
  productEdit,
  productForm,
  productModalOpen,
  productSearch,
  productionForm,
  productionOrders,
  productionPlanForm,
  productionPlanKeyword,
  productionPlanStatusLabel,
  productionPlanTypeFilter,
  productionPlans,
  products,
  projectBusy,
  projectCost,
  projectEdit,
  projectForm,
  projectModalOpen,
  projects,
  purchaseOrderForm,
  purchaseOrderList,
  purchaseOrders,
  purchaseReturnForm,
  purchaseReturnKeyword,
  purchaseReturnStatusLabel,
  purchaseReturns,
  quotationForm,
  quotationKeyword,
  quotationMeta,
  quotationStatusLabel,
  quotationToOrder,
  quotations,
  readCompanyFromToken,
  readImageInvoiceText,
  readPdfInvoiceText,
  readQrFromImage,
  receivables,
  redetectInvoices,
  refreshAccountLedger,
  refreshAdjustments,
  refreshAssemblyMeta,
  refreshAssemblyOrders,
  refreshBankAccounts,
  refreshBankTransfers,
  refreshContracts,
  refreshDictItems,
  refreshDictionaries,
  refreshEmployeeMeta,
  refreshEmployees,
  refreshFinanceEntries,
  refreshFinance,
  refreshFinishedGoods,
  refreshGlAccounts,
  refreshGlBalance,
  refreshGlDetail,
  refreshGlEntries,
  refreshInventory,
  refreshInvoiceAggregate,
  refreshInvoices,
  refreshMaterialIssues,
  refreshMaterialReturns,
  refreshMenuAdmin,
  refreshOpeningBalances,
  refreshOpeningStock,
  refreshOperationLogs,
  refreshOutsourcings,
  refreshParams,
  refreshPartyBalances,
  refreshPrintTemplates,
  refreshProductionPlans,
  refreshPurchaseInboundList,
  refreshPurchaseOrderList,
  refreshPurchaseReturns,
  refreshQuotations,
  refreshReportCatalog,
  refreshReportData,
  refreshSalesOrderList,
  refreshSalesOutboundList,
  refreshSalesReturns,
  refreshStock,
  refreshStocktakings,
  refreshSuppliers,
  refreshSystemUsers,
  refreshTransfers,
  refreshWarehouses,
  reloadAfterImport,
  removeAdjustmentItem,
  removeAssemblyItem,
  removeCategory,
  removeContractItem,
  removeFinishedGoodsItem,
  removeInboundItem,
  removeIssueItem,
  removeMrpItem,
  removeOpeningDraftRow,
  removeOutboundItem,
  removeOutsourcingItem,
  removePlanItem,
  removeProject,
  removePurchaseOrderItem,
  removePurchaseReturnItem,
  removeQuotationItem,
  removeReturnItem,
  removeSalesOrderItem,
  removeSalesReturnItem,
  removeStocktakingItem,
  removeTransferItem,
  renderBomTree,
  renderCategoryNodes,
  renderGeneralLedgerPage,
  renderLedgerPage,
  renderNavNodes,
  renderPartyBalancePage,
  renderPartyLink,
  renderReportBody,
  renderReportChart,
  renderStockHint,
  renderStockLogsPage,
  renderTransferStockHint,
  reportBusy,
  reportCatalog,
  reportKey,
  reportQuery,
  reportResult,
  reportRowMeta,
  resetBankAccountForm,
  resetDepartmentForm,
  resetEmployeeForm,
  resetEntryQuery,
  resetLogQuery,
  resetMenuForm,
  resetMenus,
  resetParamToDefault,
  resetPrintTemplate,
  resetRoleForm,
  resetSystemUserForm,
  resetWarehouseForm,
  roleForm,
  runExcelImport,
  runMrp,
  salesOrderForm,
  // 2026-10-21 补回：出库单详情抽屉的物流/签收保存
  saveSalesOrderLogistics,
  salesOrderList,
  salesOrders,
  salesReturnForm,
  salesReturnKeyword,
  salesReturnStatusLabel,
  salesReturns,
  saveCompanyDefaults,
  saveOpeningBalances,
  saveOpeningStock,
  saveParams,
  savePrintTemplate,
  selectReport,
  selectedContract,
  selectedDeptId,
  selectedInvoiceIds,
  selectedPurchaseOrder,
  selectedQuotation,
  selectedRecommendation,
  selectedSalesOrder,
  selectedTab,
  serializeProductForm,
  setAccountLedger,
  setActiveCompany,
  setActiveDictType,
  setActiveMenuEntry,
  setActiveTemplateType,
  setAdjustmentForm,
  setAdjustmentKeyword,
  setAdjustmentTypeFilter,
  setAdjustments,
  setAgentPrompt,
  setAgentResponse,
  setAging,
  setAnalysisRange,
  setArchiveFocus,
  setAssemblyFilter,
  setAssemblyForm,
  setAssemblyItems,
  setAssemblyKeyword,
  setAssemblyMeta,
  setAssemblyNewItem,
  setAssemblyOrders,
  setAssemblyPreview,
  setAuthToken,
  setBalanceDraft,
  setBankAccountForm,
  setBankAccountModalOpen,
  setBankAccounts,
  setBankTransferForm,
  setBankTransferModalOpen,
  setBankTransfers,
  setBomForm,
  setBomTree,
  setCategoryModal,
  setCollapsedGroups,
  setCompanyForm,
  setCompanySwitching,
  setConfirmDelete,
  setContractForm,
  setContractKeyword,
  setContractMeta,
  setContracts,
  setCustomerForm,
  setCustomerModalOpen,
  setCustomerSearch,
  setCustomers,
  setDepartmentForm,
  setDictForm,
  setDictItemForm,
  setDictItems,
  setDictList,
  setEditingEmployeeId,
  setEditingWarehouseId,
  setEmployeeDeptFilter,
  setEmployeeForm,
  setEmployeeKeyword,
  setEmployeeMeta,
  setEmployeeModalOpen,
  setEmployeeStatusFilter,
  setEmployees,
  setEntryDraft,
  setEntryForm,
  setEntryList,
  setEntryQuery,
  setError,
  setExcelBusy,
  setExcelKinds,
  setExcelOutcome,
  setExcelPending,
  setExecutiveDashboard,
  setExpandedInvoiceIds,
  setFinance,
  setFinanceAnalysis,
  setFinanceBusy,
  setFinanceDecision,
  setFinanceForm,
  setFinishedGoodsForm,
  setFinishedGoodsKeyword,
  setFinishedGoodsList,
  setGlAccountCode,
  setGlAccounts,
  setGlBalance,
  setGlDetail,
  setGlDetailBusy,
  setGlEntries,
  setGlEntryDetail,
  setGlRange,
  setInboundForm,
  setInventory,
  setInventoryFocus,
  setInventoryForm,
  setInventoryKeyword,
  setInvoiceAgentReport,
  setInvoiceAggregate,
  setInvoiceBusy,
  setInvoiceDetail,
  setInvoiceEditForm,
  setInvoiceExportOpen,
  setInvoiceItems,
  setInvoicePage,
  setInvoicePageSize,
  setInvoicePreview,
  setInvoiceQr,
  setInvoiceQuery,
  setIsAuthenticated,
  setIssueSuggestionHint,
  setLedgerAccountId,
  setLedgerData,
  setLedgerParty,
  setLedgerRange,
  setLoading,
  setLogBusy,
  setLogDraft,
  setLogPage,
  setLogPageNo,
  setLogQuery,
  setLoginForm,
  setLookups,
  setMaterialIssueForm,
  setMaterialIssueKeyword,
  setMaterialIssues,
  setMaterialReturnForm,
  setMaterialReturnKeyword,
  setMaterialReturns,
  setMenuAdmin,
  setMenuForm,
  setMenuOpen,
  setMenuTree,
  setMobileDashboard,
  setMrpBusy,
  setMrpForm,
  setMrpResult,
  setMyCompanies,
  setMyPermissions,
  setNavTheme,
  setNotice,
  setOpeningBalances,
  setOpeningClearAsk,
  setOpeningDraft,
  setOpeningDraftRows,
  setOpeningRows,
  setOpeningSummary,
  setOpeningTab,
  setOperationsBoard,
  setOutboundForm,
  setOutsourcingForm,
  setOutsourcingKeyword,
  setOutsourcings,
  setParamDraft,
  setParamForm,
  setParamGroups,
  setParamTotal,
  setPasswordDraft,
  setPasswordTarget,
  setPayables,
  setPermissionDraft,
  setPrintParty,
  setPrintTemplates,
  setProductBusy,
  setProductCategories,
  setProductEdit,
  setProductForm,
  setProductModalOpen,
  setProductSearch,
  setProductionForm,
  setProductionOrders,
  setProductionPlanForm,
  setProductionPlanKeyword,
  setProductionPlanTypeFilter,
  setProductionPlans,
  setProducts,
  setProjectBusy,
  setProjectCost,
  setProjectEdit,
  setProjectForm,
  setProjectModalOpen,
  setProjects,
  setPurchaseOrderForm,
  setPurchaseOrderList,
  setPurchaseOrders,
  setPurchaseReturnForm,
  setPurchaseReturnKeyword,
  setPurchaseReturns,
  setQuotationForm,
  setQuotationKeyword,
  setQuotationMeta,
  setQuotations,
  setReceivables,
  setReportBusy,
  setReportCatalog,
  setReportKey,
  setReportQuery,
  setReportResult,
  setRoleForm,
  setSalesOrderForm,
  setSalesOrderList,
  setSalesOrders,
  setSalesReturnForm,
  setSalesReturnKeyword,
  setSalesReturns,
  setSelectedContract,
  setSelectedDeptId,
  setSelectedInvoiceIds,
  setSelectedPurchaseOrder,
  setSelectedQuotation,
  setSelectedRecommendation,
  setSelectedSalesOrder,
  setSelectedTab,
  setStockData,
  setStockLogFilter,
  setStocktakingForm,
  setStocktakingKeyword,
  setStocktakingPlanHint,
  setStocktakings,
  setSummary,
  setSupplierForm,
  setSupplierModalOpen,
  setSupplierSearch,
  setSuppliers,
  setSystemBusy,
  setSystemMeta,
  setSystemTab,
  setSystemUserDeptFilter,
  setSystemUserForm,
  setSystemUserKeyword,
  setSystemUserRoleFilter,
  setSystemUsers,
  setTemplateDraft,
  setTemplatePreviewUrl,
  setTransferForm,
  setTransferKeyword,
  setTransfers,
  setUserProfile,
  setWarehouseForm,
  setWarehouseModalOpen,
  setWarehouses,
  startEditBankAccount,
  startEditDepartment,
  startEditDictItem,
  startEditEmployee,
  startEditMenu,
  startEditRole,
  startEditSystemUser,
  startEditWarehouse,
  stockByProduct,
  stockByWarehouseProduct,
  stockData,
  stockLogFilter,
  stockStatusLabel,
  stockWarnEnabled,
  stocktakingForm,
  stocktakingKeyword,
  stocktakingPlanHint,
  stocktakingStatusLabel,
  stocktakings,
  submitAdjustment,
  submitAgentPrompt,
  submitAssemblyOrder,
  submitBankAccount,
  submitBankTransfer,
  submitBomNode,
  submitCategory,
  submitCompanySettings,
  submitContract,
  submitCustomer,
  submitDepartment,
  submitDictItem,
  submitDictionary,
  submitEmployee,
  submitFinance,
  submitFinanceEntry,
  submitFinishedGoods,
  submitInboundForm,
  submitInventory,
  submitInvoiceEdit,
  submitLogin,
  submitMaterialIssue,
  submitMaterialReturn,
  submitMenu,
  submitOutboundForm,
  submitOutsourcing,
  submitParam,
  submitProduct,
  submitProductEdit,
  submitProductionOrder,
  submitProductionPlan,
  submitProject,
  submitProjectEdit,
  submitPurchaseOrderForm,
  submitPurchaseReturn,
  submitQuotation,
  submitResetPassword,
  submitRole,
  submitSalesOrderForm,
  submitSalesReturn,
  submitStocktaking,
  submitSupplier,
  submitSystemUser,
  submitTransfer,
  submitWarehouse,
  summary,
  supplierForm,
  supplierModalOpen,
  supplierSearch,
  suppliers,
  switchCompany,
  systemBusy,
  systemMeta,
  systemTab,
  systemUserDeptFilter,
  systemUserForm,
  systemUserKeyword,
  systemUserRoleFilter,
  systemUsers,
  tabs,
  templateDraft,
  templatePreviewUrl,
  toggleDictItem,
  toggleGroup,
  toggleInvoiceExpand,
  toggleInvoiceSelect,
  toggleMenuEnabled,
  togglePermissionGroup,
  togglePermissionMenu,
  toggleSelectAllInvoices,
  toggleSystemUser,
  transferForm,
  transferKeyword,
  transferStatusLabel,
  transfers,
  updateSalesOrderStatus,
  useCallback,
  useEffect,
  useMemo,
  useState,
  // 单据明细行「单位」下拉的选项来源（基础单位恒在，辅助单位异步补齐）
  unitOptionsFor,
  userProfile,
  visibleGroups,
  // 销售退货：反审核只改状态不动账；作废走 /void 红冲（二次确认 + 必填原因）
  reverseSalesReturn,
  voidSalesReturn,
  // 拖拽归档：档案行拖到左侧分类节点上松手 → 批量改 category_id
  movePartnersToCategory,
  // 期初建账：编辑态（点「改这一项」后按钮要变「保存修改」）
  openingEditingId,
  cancelOpeningEdit,
  saveOpeningSingle,
  // 行内编辑（双击格子）
  patchPartner,
  patchProduct,
  // 商品版走 category 名称（见 moveProductsToCategory 注释）
  moveProductsToCategory,
  setCategoryFilter,
  // 草稿可编辑：载回上方表单，提交走 PATCH
  salesReturnEditingId,
  startEditSalesReturn,
  cancelEditSalesReturn,
  warehouseForm,
  warehouseModalOpen,
  warehouses
  };
  return (
    <div
      className={`app-shell ${menuOpen ? 'menu-open' : ''}`}
      data-nav-theme={navTheme === 'default' ? undefined : navTheme}
    >
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
          {/* 版本号（2026-10-18）：构建时由 vite.config.js 注入，每次 build 自动变。
              鼠标悬停能看到完整构建时间与提交哈希，排查"用户看到旧页面"时很有用。 */}
          <span
            className="brand-version"
            data-app-version={APP_VERSION_LABEL}
            title={`业务版本 v${APP_VERSION} ｜ 构建代号 ${APP_CACHE} ｜ 构建时间 ${APP_BUILD_AT} ｜ 提交 ${APP_HASH}`}
          >
            {APP_VERSION_LABEL}
          </span>
          <button
            className="sidebar-close"
            type="button"
            aria-label="收起菜单"
            onClick={() => setMenuOpen(false)}
          >
            ×
          </button>
        </div>
        <nav className="side-nav">{renderNavNodes(visibleGroups)}</nav>
        {/* 导航配色切换：一排小圆点，点了立刻换色并记住选择 */}
        <div className="nav-theme-picker">
          <span className="nav-theme-picker-label">导航配色</span>
          <div className="nav-theme-dots">
            {NAV_THEMES.map((theme) => (
              <button
                key={theme.key}
                type="button"
                className={`nav-theme-dot ${navTheme === theme.key ? 'selected' : ''}`}
                style={{ background: theme.swatch }}
                title={theme.label}
                aria-label={`导航配色：${theme.label}`}
                aria-pressed={navTheme === theme.key}
                onClick={() => chooseNavTheme(theme.key)}
              />
            ))}
          </div>
        </div>
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
            <p className="eyebrow">{currentGroupLabel}</p>
            <h1>{currentPageLabel}</h1>
          </div>
          <div className="topbar-right">
            {/* 多账套：当前公司名 + 切换。
                只有一家时不渲染下拉（没得切，摆一个空下拉只会让人以为坏了）。 */}
            {activeCompany.name && (
              <div className="company-switch">
                <span className="company-chip" title="当前账套">
                  <i className="company-dot" aria-hidden="true" />
                  {activeCompany.name}
                </span>
                {myCompanies.length > 1 && (
                  <select
                    className="company-select"
                    value={activeCompany.code}
                    disabled={companySwitching}
                    onChange={(event) => switchCompany(event.target.value)}
                    aria-label="切换账套"
                  >
                    {myCompanies.map((row) => (
                      <option key={row.code} value={row.code}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
            {/* 顶栏操作按当前页面查表（见 pageActions）：查不到就整块不渲染，
                不再像以前那样把「新建报价 / 新增订单」硬编码给全部页面。 */}
            {currentActions.length > 0 && (
              <div className="topbar-actions">
                {currentActions.map((action) => (
                  <button
                    key={`${action.to}-${action.label}`}
                    className={action.variant === 'primary' ? 'primary-btn' : 'secondary-btn'}
                    type="button"
                    onClick={() => {
                      setSelectedTab(action.to);
                      setNotice(`已切换到「${tabs.find((tab) => tab.key === action.to)?.label ?? action.to}」。`);
                    }}
                  >
                    {action.label}
                  </button>
                ))}
              </div>
            )}
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
            {selectedTab === 'mobile' && <MobilePage ctx={appCtx} />}

            {selectedTab === 'bom' && <BomPage ctx={appCtx} />}

            {selectedTab === 'overview' && <OverviewPage ctx={appCtx} />}

            {selectedTab === 'customers' && <CustomersPage ctx={appCtx} />}

            {/* —— 新增 / 编辑客户弹窗（UI 在 components/partners/PartnerModal.jsx） —— */}
            <PartnerModal
              open={customerModalOpen}
              kind="customer"
              mode={editingCustomerId != null ? 'edit' : 'create'}
              form={customerForm}
              fieldChange={handleCustomerChange}
              onSubmit={submitCustomer}
              onClose={closeCustomerModal}
              categoryOptions={partnerCategoryOptions.customer}
              /* 智能识别上传（2026-10-23）：客户开 attach（有 /customers/{id}/files 归档） */
              smartUpload
              authHeaders={authHeaders}
              onSmartFill={applyCustomerSmartFill}
              onSmartFiles={setCustomerSmartFiles}
            />

            {selectedTab === 'suppliers' && <SuppliersPage ctx={appCtx} />}

            {/* —— 新增 / 编辑供应商弹窗（UI 在 components/partners/PartnerModal.jsx） —— */}
            <PartnerModal
              open={supplierModalOpen}
              kind="supplier"
              mode={editingSupplierId != null ? 'edit' : 'create'}
              form={supplierForm}
              fieldChange={handleSupplierChange}
              onSubmit={submitSupplier}
              onClose={closeSupplierModal}
              categoryOptions={partnerCategoryOptions.supplier}
              /* 智能识别上传：供应商新增/编辑都开（2026-10-23）。
                 识别目标 = 名称/税号/开户行/账号/联系人/电话，核对后自动填入表单。
                 附件归档端点只有客户有（/customers/{id}/files），供应商关掉 attach 模式。 */
              smartUpload
              smartUploadAllowAttach={false}
              authHeaders={authHeaders}
              onSmartFill={applySupplierSmartFill}
            />

            {/* —— 订单收/付款弹窗（UI 在 components/docs/OrderPaymentDialog.jsx） ——
                挂在这一层而不是页面里：采购订单页、销售订单页共用同一份，
                和 PartnerModal 同级的全局弹窗，两个页面都能开。 */}
            <OrderPaymentDialog
              open={Boolean(orderPayDialog)}
              kind={orderPayDialog?.kind || 'sales'}
              order={orderPayDialog?.row || null}
              partyName={
                orderPayDialog
                  ? (orderPayDialog.kind === 'purchase'
                      ? suppliers.find((item) => item.id === orderPayDialog.row?.supplier_id)?.name
                      : customers.find((item) => item.id === orderPayDialog.row?.customer_id)?.name) || ''
                  : ''
              }
              onSubmit={submitOrderPayment}
              onClose={closeOrderPayment}
              busy={orderPayBusy}
              result={orderPayResult}
              error={orderPayError}
              invoiceStatus={orderPayInvoice}
              invoiceLoading={orderPayInvoiceLoading}
            />

            {/* 打印二次确认（全局唯一宿主）。UI 见 components/ui/PrintConfirmHost.jsx，
                调用口见 lib/printConfirm.js —— 任何模块 import 后即可 await confirmPrint()。 */}
            <PrintConfirmHost />

            {selectedTab === 'bank' && <BankPage ctx={appCtx} />}

            {/* —— 新增/编辑账户弹窗 —— */}
            {bankAccountModalOpen && (
              <div className="modal-backdrop" onClick={() => { resetBankAccountForm(); setBankAccountModalOpen(false); }}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>{bankAccountForm.id ? '编辑账户' : '新增账户'}</h3>
                    <button type="button" className="close-btn" onClick={() => { resetBankAccountForm(); setBankAccountModalOpen(false); }}>×</button>
                  </div>
                  <form className="erp-form" onSubmit={submitBankAccount}>
                    <div className="form-row two-col">
                      <label>
                        账户编码
                        <input value={bankAccountForm.code} onChange={handleBankAccountFormChange('code')} placeholder="如 CASH-01" required />
                      </label>
                      <label>
                        账户名称
                        <input value={bankAccountForm.name} onChange={handleBankAccountFormChange('name')} placeholder="如 库存现金" required />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        账户类型
                        <select value={bankAccountForm.account_type} onChange={handleBankAccountFormChange('account_type')}>
                          {Object.entries(BANK_ACCOUNT_TYPE_LABEL).map(([key, label]) => (
                            <option key={key} value={key}>{label}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        期初余额
                        <input type="number" step="any" value={bankAccountForm.init_balance} onChange={handleBankAccountFormChange('init_balance')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        开户行
                        <input value={bankAccountForm.bank_name} onChange={handleBankAccountFormChange('bank_name')} list="lookup-bank-name" />
                      </label>
                      <label>
                        银行账号
                        <input value={bankAccountForm.account_no} onChange={handleBankAccountFormChange('account_no')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        排序号
                        <input type="number" value={bankAccountForm.sort_order} onChange={handleBankAccountFormChange('sort_order')} />
                      </label>
                      <label className="checkbox-row">
                        <input type="checkbox" checked={bankAccountForm.is_active} onChange={handleBankAccountFormChange('is_active')} />
                        启用（停用后不出现在收支登记的下拉里）
                      </label>
                    </div>
                    <label>
                      备注
                      <input value={bankAccountForm.note} onChange={handleBankAccountFormChange('note')} />
                    </label>
                    <div className="form-actions">
                      <button className="primary-btn" type="submit" disabled={systemBusy}>
                        {bankAccountForm.id ? '保存修改' : '创建账户'}
                      </button>
                      <button type="button" className="secondary-btn" onClick={() => { resetBankAccountForm(); setBankAccountModalOpen(false); }}>取消</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {/* —— 账户转账弹窗 —— */}
            {bankTransferModalOpen && (
              <div className="modal-backdrop" onClick={() => setBankTransferModalOpen(false)}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>账户转账</h3>
                    <button type="button" className="close-btn" onClick={() => setBankTransferModalOpen(false)}>×</button>
                  </div>
                  <form className="erp-form" onSubmit={submitBankTransfer}>
                    <div className="form-row two-col">
                      <label>
                        转出账户
                        <select value={bankTransferForm.from_account_id} onChange={handleBankTransferFormChange('from_account_id')} required>
                          <option value="">— 请选择 —</option>
                          {bankAccounts.filter((row) => row.is_active).map((row) => (
                            <option key={row.id} value={row.id}>{row.name}（{money(row.current_balance)}）</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        转入账户
                        <select value={bankTransferForm.to_account_id} onChange={handleBankTransferFormChange('to_account_id')} required>
                          <option value="">— 请选择 —</option>
                          {bankAccounts.filter((row) => row.is_active).map((row) => (
                            <option key={row.id} value={row.id}>{row.name}（{money(row.current_balance)}）</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        转账金额
                        <input type="number" step="any" value={bankTransferForm.amount} onChange={handleBankTransferFormChange('amount')} required />
                      </label>
                      <label>
                        转账日期
                        <input type="date" value={bankTransferForm.transfer_date} onChange={handleBankTransferFormChange('transfer_date')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        经办人
                        <input value={bankTransferForm.handler} onChange={handleBankTransferFormChange('handler')} />
                      </label>
                      <label>
                        备注
                        <input value={bankTransferForm.note} onChange={handleBankTransferFormChange('note')} />
                      </label>
                    </div>
                    <div className="form-actions">
                      <button className="primary-btn" type="submit" disabled={systemBusy || bankAccounts.length < 2}>
                        确认转账
                      </button>
                      <button type="button" className="secondary-btn" onClick={() => setBankTransferModalOpen(false)}>取消</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {selectedTab === 'income-expense' && <IncomeExpensePage ctx={appCtx} />}

            {selectedTab === 'assembly' && <AssemblyPage ctx={appCtx} />}

            {selectedTab === 'staff' && <StaffPage ctx={appCtx} />}

            {selectedTab === 'opening-stock' && <OpeningStockPage ctx={appCtx} />}

            {/* —— 新增/编辑员工弹窗 —— */}
            {employeeModalOpen && (
              <div className="modal-backdrop" onClick={() => { resetEmployeeForm(); setEmployeeModalOpen(false); }}>
                <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>{editingEmployeeId != null ? '编辑员工' : '新增员工'}</h3>
                    <button type="button" className="close-btn" onClick={() => { resetEmployeeForm(); setEmployeeModalOpen(false); }}>×</button>
                  </div>
                  <form onSubmit={submitEmployee} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        工号
                        <input value={employeeForm.code} onChange={handleEmployeeChange('code')} placeholder="如 YG-0001" required />
                      </label>
                      <label>
                        姓名
                        <input value={employeeForm.name} onChange={handleEmployeeChange('name')} required />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        性别
                        <select value={employeeForm.gender} onChange={handleEmployeeChange('gender')}>
                          <option value="">未填</option>
                          {(employeeMeta.genders || []).map((g) => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        部门
                        <select value={employeeForm.department_id} onChange={handleEmployeeChange('department_id')}>
                          <option value="">未分配</option>
                          {(employeeMeta.departments || []).map((dept) => (
                            <option key={dept.id} value={dept.id}>{dept.label}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        岗位
                        <input value={employeeForm.position} onChange={handleEmployeeChange('position')} list="lookup-position" placeholder="如 车间主任" />
                      </label>
                      <label>
                        手机
                        <input value={employeeForm.phone} onChange={handleEmployeeChange('phone')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        身份证号
                        <input value={employeeForm.id_card} onChange={handleEmployeeChange('id_card')} />
                      </label>
                      <label>
                        基本工资
                        <input type="number" value={employeeForm.base_salary} onChange={handleEmployeeChange('base_salary')} placeholder="选填" />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        在职状态
                        <select value={employeeForm.status} onChange={handleEmployeeChange('status')}>
                          {(employeeMeta.statuses || []).map((item) => (
                            <option key={item.value} value={item.value}>{item.label}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        入职日期
                        <input type="date" value={employeeForm.hire_date} onChange={handleEmployeeChange('hire_date')} />
                      </label>
                    </div>
                    {employeeForm.status === 'left' && (
                      <label>
                        离职日期
                        <input type="date" value={employeeForm.leave_date} onChange={handleEmployeeChange('leave_date')} />
                      </label>
                    )}
                    <div className="form-row two-col">
                      <label>
                        开户行
                        <input value={employeeForm.bank_name} onChange={handleEmployeeChange('bank_name')} list="lookup-bank-name" />
                      </label>
                      <label>
                        银行账号
                        <input value={employeeForm.bank_account} onChange={handleEmployeeChange('bank_account')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        紧急联系人
                        <input value={employeeForm.emergency_contact} onChange={handleEmployeeChange('emergency_contact')} />
                      </label>
                      <label>
                        紧急联系电话
                        <input value={employeeForm.emergency_phone} onChange={handleEmployeeChange('emergency_phone')} />
                      </label>
                    </div>
                    <label>
                      备注
                      <textarea rows="2" value={employeeForm.note} onChange={handleEmployeeChange('note')} />
                    </label>
                    <div className="form-actions">
                      <button className="primary-btn" type="submit" disabled={systemBusy}>
                        {editingEmployeeId != null ? '保存修改' : '保存员工'}
                      </button>
                      <button type="button" className="secondary-btn" onClick={() => { resetEmployeeForm(); setEmployeeModalOpen(false); }}>取消</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {selectedTab === 'warehouses' && <WarehousesPage ctx={appCtx} />}

            {/* —— 新增/编辑仓库弹窗 —— */}
            {warehouseModalOpen && (
              <div className="modal-backdrop" onClick={() => { resetWarehouseForm(); setWarehouseModalOpen(false); }}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>{editingWarehouseId != null ? '编辑仓库' : '新增仓库'}</h3>
                    <button type="button" className="close-btn" onClick={() => { resetWarehouseForm(); setWarehouseModalOpen(false); }}>×</button>
                  </div>
                  <form onSubmit={submitWarehouse} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        仓库编码
                        <input value={warehouseForm.code} onChange={handleWarehouseChange('code')} placeholder="如 CK-001" required />
                      </label>
                      <label>
                        仓库名称
                        <input value={warehouseForm.name} onChange={handleWarehouseChange('name')} required />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        货位
                        <input value={warehouseForm.location} onChange={handleWarehouseChange('location')} placeholder="如 A区01号位" />
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
                        <input type="checkbox" checked={warehouseForm.is_active} onChange={handleWarehouseChange('is_active')} />
                        启用（停用后开单时不作为可选仓库）
                      </label>
                    </div>
                    <label>
                      备注
                      <textarea value={warehouseForm.note} onChange={handleWarehouseChange('note')} rows="2" />
                    </label>
                    <div className="form-actions">
                      <button className="primary-btn" type="submit">
                        {editingWarehouseId != null ? '保存修改' : '保存仓库'}
                      </button>
                      <button type="button" className="secondary-btn" onClick={() => { resetWarehouseForm(); setWarehouseModalOpen(false); }}>取消</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {selectedTab === 'products' && <ProductsPage ctx={appCtx} />}

            {/* —— 商品弹窗（新增 / 编辑）——
                弹窗本体已抽成独立组件 src/components/product-edit/ProductEditModal.jsx。
                这里原来是两段近 240 行的内联 JSX（新增一段、编辑一段），字段几乎相同却各写
                一遍，于是长期不同步 —— 实测后果：编辑弹窗既没有图片字段，它写的
                list="lookup-product-category" 也指不到只在新增弹窗里定义过的那个 datalist。
                现在两态只差 mode 一个参数，字段要改只有一处落点。 */}
            {productModalOpen && (
              <ProductEditModal
                mode="create"
                /* 智能识别上传：报价单/产品资料 → 商品字段；报价单明细可一键批量入库（2026-10-23） */
                smartUpload
                onSmartFill={applyProductSmartFill}
                onSmartBulkItems={applyProductBulkItems}
                form={productForm}
                onChange={handleProductChange}
                onSubmit={submitProduct}
                onCancel={() => setProductModalOpen(false)}
                busy={productBusy}
                categories={productCategories}
                suppliers={suppliers}
                apiBase={API_BASE}
                authHeaders={authHeaders}
                onError={setNotice}
              />
            )}

            {/* —— 编辑商品（弹窗）——
                历史：商品原本只有「新增 + 删除」，录错的条码/助记码只能删了重建；
                所以才有这个编辑弹窗。现在它与新增共用同一个组件，只传 mode="edit"。
                状态是 productEdit（不是 productForm），因此回调走 handleProductEditChange。 */}
            {productEdit && (
              <ProductEditModal
                mode="edit"
                /* 编辑商品也开智能识别（2026-10-23）：识别值经核对框逐项确认后才合并，
                   只覆盖认出的字段；报价单明细同样可以一键批量生成新商品。 */
                smartUpload
                onSmartFill={applyProductEditSmartFill}
                onSmartBulkItems={applyProductBulkItems}
                form={productEdit}
                onChange={handleProductEditChange}
                onSubmit={submitProductEdit}
                onCancel={() => setProductEdit(null)}
                busy={productBusy}
                categories={productCategories}
                suppliers={suppliers}
                apiBase={API_BASE}
                authHeaders={authHeaders}
                onError={setNotice}
              />
            )}

            {/* —— 类别新增 / 编辑（弹窗）—— */}
            {categoryModal && (
              <div className="modal-backdrop" onClick={() => setCategoryModal(null)}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>{categoryModal.mode === 'edit' ? '编辑类别' : '新增类别'}</h3>
                    <button type="button" className="close-btn" onClick={() => setCategoryModal(null)}>×</button>
                  </div>
                  <form className="erp-form" onSubmit={submitCategory}>
                    <label>
                      类别名称
                      <input
                        name="name"
                        required
                        autoFocus
                        defaultValue={categoryModal.mode === 'edit' ? (categoryModal.node?.name || '') : ''}
                      />
                    </label>
                    <label>
                      上级类别
                      {/* 类别树会越攒越多：改可搜索。`path` 自带全角空格缩进，原样当 label 即可。
                          值是 string（'' = 顶级）：原来靠 `<option value="">（无…）</option>`，
                          现在靠右侧 × 清空回顶级，所以 placeholder 要把这件事说清。 */}
                      <ErpSearchSelect
                        options={flattenCategoryOptions(productCategories)}
                        value={String(categoryParentDraft ?? '')}
                        onChange={(value) => setCategoryParentDraft(value)}
                        placeholder="搜索类别；留空即顶级类别"
                        emptyText="没有匹配的类别"
                        getOptionValue={(c) => String(c.id)}
                        getOptionLabel={(c) => c.path}
                        getSearchText={(c) => c.path}
                      />
                    </label>
                    <label>
                      备注
                      <input name="note" defaultValue={categoryModal.mode === 'edit' ? (categoryModal.node?.note || '') : ''} />
                    </label>
                    <div className="form-actions">
                      <button type="submit" className="primary-btn" disabled={productBusy === 'cat'}>
                        {productBusy === 'cat' ? '保存中…' : '保存'}
                      </button>
                      <button type="button" className="secondary-btn" onClick={() => setCategoryModal(null)}>取消</button>
                    </div>
                  </form>
                </div>
              </div>
            )}

            {/* 名称防呆：检测到相似名称时的黄色确认框（2026-10-22） */}
            {nameGuard && (
              <div className="modal-backdrop">
                <div className="modal-card name-guard-modal">
                  <div className="modal-header">
                    <h3>检测到相似名称</h3>
                  </div>
                  <p className="name-guard-lead">
                    你要新建的{nameGuard.label}「<strong>{nameGuard.name}</strong>」，与库里这些记录很像：
                  </p>
                  <ul className="name-guard-list">
                    {nameGuard.similar.map((hit) => (
                      <li key={hit.row.id}>
                        <strong>{hit.row.name}</strong>
                        {hit.row.code ? <span className="mono">（{hit.row.code}）</span> : null}
                        <span className="name-guard-reason">{hit.reason}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="name-guard-tip">
                    如果确实是另一个{nameGuard.label}，可以继续；如果是重复录入，建议先去列表里改那一张。
                  </p>
                  <div className="form-actions">
                    <button
                      type="button"
                      className="primary-btn"
                      onClick={() => {
                        const form = pendingFormRef.current;
                        skipNameGuardRef.current = true;
                        setNameGuard(null);
                        pendingFormRef.current = null;
                        // 重放这次提交：表单还挂在页面上，直接再触发一次 submit
                        if (form && typeof form.requestSubmit === 'function') {
                          form.requestSubmit();
                        }
                      }}
                    >
                      仍然新建
                    </button>
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() => {
                        setNameGuard(null);
                        pendingFormRef.current = null;
                      }}
                    >
                      返回修改
                    </button>
                  </div>
                </div>
              </div>
            )}

            {selectedTab === 'dataio' && <DataioPage ctx={appCtx} />}

            {selectedTab === 'purchase-order' && <PurchaseOrderPage ctx={appCtx} />}

            {selectedTab === 'purchase' && <PurchasePage ctx={appCtx} />}

            {selectedTab === 'sales-order' && <SalesOrderPage ctx={appCtx} />}

            {selectedTab === 'sales' && <SalesPage ctx={appCtx} />}

            {selectedTab === 'production' && <ProductionPage ctx={appCtx} />}

            {selectedTab === 'projects' && <ProjectsPage ctx={appCtx} />}

            {selectedTab === 'reports' && <ReportsPage ctx={appCtx} />}

            {selectedTab === 'invoices' && <InvoicesPage ctx={appCtx} />}

            {selectedTab === 'analysis' && <AnalysisPage ctx={appCtx} />}

            {selectedTab === 'finance' && <FinancePage ctx={appCtx} />}

            {selectedTab === 'three-way-match' && <ThreeWayMatchPage ctx={appCtx} />}

            {selectedTab === 'stock-logs' && renderStockLogsPage()}

            {selectedTab === 'receivable' && renderPartyBalancePage('customer')}

            {selectedTab === 'payable' && renderPartyBalancePage('supplier')}

            {selectedTab === 'ledger' && renderLedgerPage()}

            {selectedTab === 'general-ledger' && renderGeneralLedgerPage()}

            {selectedTab === 'contracts' && <ContractsPage ctx={appCtx} />}

            {/* 第 13 批：合同台账。组件自己取数（token 走 localStorage），
                所以这里**不传 ctx** —— 传了反而会诱使人往里加 ctx 依赖。
                Suspense 的 fallback 用一个空面板占位，避免切页时整屏闪一下 */}
            {selectedTab === 'contracts-ledger' && (
              <Suspense fallback={<section className="panel">正在加载合同台账…</section>}>
                <ContractsLedger />
              </Suspense>
            )}

            {/* 第 13 批第三步：增强对账单编辑器（自包含组件，不传 ctx） */}
            {selectedTab === 'statements-editor' && (
              <Suspense fallback={<section className="panel">正在加载对账单…</section>}>
                {/* key 带 nonce：从智能指令跳过来时即使已经停在这一页，也要按新单位重建。
                    `initialParty` 形如 `c:12` / `s:45`（与页面内部 partyId 同一套前缀）。 */}
                <StatementEditor
                  key={`stmt-${statementPreset.nonce}`}
                  initialScope={statementPreset.scope}
                  initialParty={statementPreset.party}
                />
              </Suspense>
            )}

            {selectedTab === 'quotation' && <QuotationPage ctx={appCtx} />}

            {selectedTab === 'purchase-return' && <PurchaseReturnPage ctx={appCtx} />}

            {selectedTab === 'sales-return' && <SalesReturnPage ctx={appCtx} />}

            {selectedTab === 'transfer' && <TransferPage ctx={appCtx} />}

            {selectedTab === 'stocktaking' && <StocktakingPage ctx={appCtx} />}

            {selectedTab === 'loss-overflow' && <LossOverflowPage ctx={appCtx} />}

            {selectedTab === 'production-plan' && <ProductionPlanPage ctx={appCtx} />}

            {selectedTab === 'mrp' && <MrpPage ctx={appCtx} />}

            {selectedTab === 'material-issue' && <MaterialIssuePage ctx={appCtx} />}

            {selectedTab === 'material-return' && <MaterialReturnPage ctx={appCtx} />}

            {selectedTab === 'finished-goods' && <FinishedGoodsPage ctx={appCtx} />}

            {selectedTab === 'outsourcing' && <OutsourcingPage ctx={appCtx} />}

            {selectedTab === 'users' && <UsersPage ctx={appCtx} />}

            {selectedTab === 'params' && <ParamsPage ctx={appCtx} />}

            {selectedTab === 'dictionaries' && <DictionariesPage ctx={appCtx} />}

            {selectedTab === 'print-templates' && <PrintTemplatesPage ctx={appCtx} />}

            {selectedTab === 'logs' && <LogsPage ctx={appCtx} />}

            {selectedTab === 'menus' && <MenusPage ctx={appCtx} />}

            {selectedTab === 'settings' && <SettingsPage ctx={appCtx} />}

            {selectedTab === 'inventory' && <InventoryPage ctx={appCtx} />}

            {selectedTab === 'stock-alert' && <StockAlertPage ctx={appCtx} />}

            {selectedTab === 'agent' && <AgentPage ctx={appCtx} />}

            {notice && (
              <div className={`notice-box${noticeTone ? ` notice-box--${noticeTone}` : ''}`}>{notice}</div>
            )}

            {/* 删单被拦（2026-10-18）：单据已登记收付款。只有一个「知道了」，
                没有强制删除 —— 真实资金记录不能因为删单而消失。 */}
            {deleteBlocked && (
              <div className="modal-backdrop" onClick={() => setDeleteBlocked(null)} data-delete-blocked>
                <div
                  className="modal-card delete-blocked"
                  role="dialog"
                  aria-modal="true"
                  aria-label="无法删除"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="modal-header">
                    <h3>无法删除</h3>
                    <button type="button" className="close-btn" onClick={() => setDeleteBlocked(null)} aria-label="关闭">×</button>
                  </div>
                  <p className="delete-blocked__message" data-delete-blocked-message>
                    {deleteBlocked.message}
                  </p>
                  {deleteBlocked.hint && (
                    <p className="delete-blocked__hint" data-delete-blocked-hint>{deleteBlocked.hint}</p>
                  )}
                  <div className="modal-actions">
                    <button type="button" className="primary-btn" onClick={() => setDeleteBlocked(null)} data-delete-blocked-ok>
                      知道了
                    </button>
                  </div>
                </div>
              </div>
            )}

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
                    <p className="confirm-hint">订单明细也会一并删除；已登记收付款的订单不允许删除。</p>
                  )}
                  {confirmDelete.kind === 'purchase-order' && (
                    <p className="confirm-hint">订单明细也会一并删除；已登记收付款的订单不允许删除。</p>
                  )}
                  {confirmDelete.kind === 'contract' && (
                    <p className="confirm-hint">
                      合同明细（标的物清单）与<strong>已上传的原件文件</strong>会一并删除，删除后无法恢复。
                      已生成单据的合同删不掉（会提示 409）—— 那说明它是某张单的溯源线索，请改为「已作废」。
                    </p>
                  )}
                  {confirmDelete.kind === 'system-user' && (
                    <p className="confirm-hint">该账号将无法登录，历史操作日志保留。</p>
                  )}
                  {confirmDelete.kind === 'system-role' && (
                    <p className="confirm-hint">删除后该角色的权限配置一并消失，无法恢复。</p>
                  )}
                  {confirmDelete.kind === 'system-dept' && (
                    <p className="confirm-hint">部门下有子部门或用户时不允许删除。</p>
                  )}
                  {confirmDelete.kind === 'system-dict' && (
                    <p className="confirm-hint">该字典下的全部字典项会一并删除，业务表单将失去这组候选。</p>
                  )}
                  {confirmDelete.kind === 'menu' && (
                    <p className="confirm-hint">
                      删除后这个菜单就从左侧导航消失了（页面本身和权限都不受影响）。
                      如果是内置菜单，可以用「恢复默认菜单」找回来。
                    </p>
                  )}
                  {confirmDelete.kind === 'menus-reset' && (
                    <p className="confirm-hint">
                      会将菜单**恢复成出厂状态**，你新建的分组与菜单、改过的名字和层级都会丢失。
                    </p>
                  )}
                  {confirmDelete.kind === 'system-dict-item' && (
                    <p className="confirm-hint">已填过该值的单据不受影响，只是新单据不再候选。</p>
                  )}
                  {confirmDelete.kind === 'bank-account' && (
                    <p className="confirm-hint">
                      有流水或转账的账户删不掉（会提示 409），请改用「停用」—— 停用只是不再出现在下拉里，历史流水照样在。
                    </p>
                  )}
                  {confirmDelete.kind === 'bank-transfer' && (
                    <p className="confirm-hint">
                      删转账会把「转出」和「转入」<strong>两条流水一起删掉</strong>，两个账户的余额同时复原。
                    </p>
                  )}
                  {confirmDelete.kind === 'finance-entry' && (
                    <p className="confirm-hint">
                      删除后该笔金额会从账户余额里扣回。<strong>单据自动生成的流水不能在这里删</strong>。
                    </p>
                  )}
                  {confirmDelete.kind === 'assembly-order' && (
                    <p className="confirm-hint">
                      删单会把这张单产生的库存变动<strong>全部冲销</strong>：成品与子件一起复原。
                    </p>
                  )}
                  {confirmDelete.kind === 'system-employee' && (
                    <p className="confirm-hint">员工档案删除后无法恢复；历史单据上的人名是字符串快照，不受影响。</p>
                  )}
                  {confirmDelete.kind === 'opening-line' && (
                    <p className="confirm-hint">
                      删掉这条期初会让对应「仓库 × 商品」的<strong>现存量同步减少</strong>，请确认这是你要的。
                    </p>
                  )}
                  {confirmDelete.kind === 'system-logs' && (
                    <p className="confirm-hint">
                      全部历史操作记录将被清除，<strong>无法恢复</strong>。清理完成后会留下这次清理动作本身的一条记录。
                    </p>
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

            {openingClearAsk && (
              <div className="modal-backdrop" onClick={() => setOpeningClearAsk(false)}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>清空全部期初</h3>
                    <button type="button" className="close-btn" onClick={() => setOpeningClearAsk(false)}>×</button>
                  </div>
                  <p className="confirm-text">
                    将删除全部 {openingSummary.lines || 0} 项期初库存，<strong>无法恢复</strong>。
                  </p>
                  <div className="confirm-blocked">
                    <p className="confirm-hint">现存量的期初基数会随之归零，之后所有库存数字都从 0 开始滚。</p>
                    <p className="confirm-hint">已经开过的单据与它们的库存流水不受影响，历史出库照旧留在账上。</p>
                    <p className="confirm-hint">如果只是想改某几项，回到列表用「改这一项」，别用清空。</p>
                  </div>
                  <div className="modal-actions">
                    <button type="button" className="secondary-btn" onClick={() => setOpeningClearAsk(false)}>取消</button>
                    <button type="button" className="danger-btn" onClick={clearOpeningStock}>确认清空</button>
                  </div>
                </div>
              </div>
            )}

            {passwordTarget && (
              <div className="modal-backdrop" onClick={() => setPasswordTarget(null)}>
                <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                  <div className="modal-header">
                    <h3>重置密码</h3>
                    <button type="button" className="close-btn" onClick={() => setPasswordTarget(null)}>×</button>
                  </div>
                  <p className="confirm-text">为「{passwordTarget.username}」设置新密码，旧密码将立即失效。</p>
                  <form onSubmit={submitResetPassword}>
                    <label>
                      新密码
                      <input
                        type="password"
                        value={passwordDraft.new_password}
                        onChange={(event) => setPasswordDraft({ new_password: event.target.value })}
                        placeholder="至少 6 位"
                        autoComplete="new-password"
                        required
                      />
                    </label>
                    <div className="modal-actions">
                      <button type="button" className="secondary-btn" onClick={() => setPasswordTarget(null)}>取消</button>
                      <button type="submit" className="primary-btn">确认重置</button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </>
        )}
      </main>

      {/* 数字字典候选：挂在各业务表单的输入框上（input list=...）。
          用 datalist 而不是 select —— 这些字段本来就允许自由填写，
          datalist 只补候选、不锁死输入。 */}
      <datalist id="lookup-payment-method">
        {lookupValues('payment_method').map((value) => <option key={value} value={value} />)}
      </datalist>
      <datalist id="lookup-product-unit">
        {lookupValues('product_unit').map((value) => <option key={value} value={value} />)}
      </datalist>
      <datalist id="lookup-position">
        {lookupValues('position').map((value) => <option key={value} value={value} />)}
      </datalist>
      <datalist id="lookup-bank-name">
        {lookupValues('bank_name').map((value) => <option key={value} value={value} />)}
      </datalist>
      {/* 开票税率：option 的 text 是说明，选中后写进输入框的是 value（13 / 9 / 6 …）。
          依据《增值税法》（2026-01-01 施行）第十、十一条，内容存在可维护的字典里，
          用户能按自己的业务增减 —— 代码里不写死税率。 */}
      <datalist id="lookup-tax-rate">
        {lookupItems('tax_rate').map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </datalist>
      {/* 日常收支的类别候选。收入、支出各一套 —— 表单会按当前类型切换 list 指向哪一个，
          所以两个 datalist 都得存在，少一个就会有一半输入框点开是空的。 */}
      <datalist id="lookup-income_category">
        {lookupValues('income_category').map((value) => <option key={value} value={value} />)}
      </datalist>
      <datalist id="lookup-expense_category">
        {lookupValues('expense_category').map((value) => <option key={value} value={value} />)}
      </datalist>
    </div>
  );
}

export default App;



