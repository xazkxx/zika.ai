// 自动提取：App.jsx 模块级纯常量与纯函数（见 scripts/split_app_jsx.py）
// 这些定义彼此无 React 依赖，且不被 menuGroups / pageActions 反向依赖。


// 使用同源相对路径：开发时由 Vite 代理转发到后端；
// 手机/局域网访问时请求也走当前服务器，不会指向错误的 127.0.0.1。
export const API_BASE = '/api/v1';

// ---------------------------------------------------------------------------
// 版本号（2026-10-18）：由 vite.config.js 的 define 在**构建时**注入。
//   APP_VERSION  来自 package.json 的 version（唯一来源，别再手写第二份）
//   APP_BUILD    构建时间 YYYYMMDD-HHmm —— 每次 npm run build 自动变
//   APP_HASH     提交短哈希（不在 git 仓库里是 nogit）
// 为什么放 appLib：侧边栏、登录页、关于弹窗都要用，必须有一处唯一来源；
// 而 define 是编译期替换，dist 里不需要额外文件或请求。
// ⚠️ 每次发布仍要 bump public/sw.js 的 CACHE_VERSION，否则老壳缓存里还是旧号。
// ---------------------------------------------------------------------------
export const APP_VERSION =
  typeof __APP_VERSION__ === 'undefined' ? 'dev' : __APP_VERSION__;
export const APP_BUILD =
  typeof __APP_BUILD__ === 'undefined' ? 'dev' : __APP_BUILD__;
export const APP_BUILD_AT =
  typeof __APP_BUILD_AT__ === 'undefined' ? 'dev' : __APP_BUILD_AT__;
export const APP_HASH = typeof __APP_HASH__ === 'undefined' ? 'nogit' : __APP_HASH__;
// 构建代号（PWA 缓存版本，v72 → v102 …）：每次 build 自动 +1。
// 它才是"用户现在跑的是不是最新包"的第一判据 —— 业务版本号 1.75.0 几个月都不动一次。
export const APP_CACHE = typeof __APP_CACHE__ === 'undefined' ? 'v?' : __APP_CACHE__;
// 页面左下角的短标：v1.81.0 · vNNN
// 2026-10-26 调整：业务版本号从「悬停才看得见」提到正面 —— 打包交付时验收人一眼要能念出
// 版本号；构建时间/提交哈希仍在 title 里（左下角宽度放不下四段）。
export const APP_VERSION_LABEL = `${APP_VERSION} · ${APP_CACHE}`;
// 菜单按业务域分组。items 里的 key 与业务逻辑一一对应，改分组不会影响任何功能。
// 左侧菜单框架 —— 业务域对齐浩技云进销存（基础资料 / 采购 / 销售 / 库存 / 生产 / 财务 / 系统设置），
// 并保留本系统独有的模块（工作台、报表分析、项目管理、移动与智能）。
//
// 设计口径：
//   1. 分组名与功能名沿用浩技云的说法，员工从浩技云迁过来零学习成本；
//   2. 基础档案类保留本系统原有叫法（客户档案 / 商品档案…），比「客户管理」更准确；
//   3. `todo: true` = 框架位已按浩技云预留、功能待建设，点击显示「模块建设中」占位页；
//   4. key 一律沿用原有值，改的只是分组归属与显示名，不触及任何业务逻辑。


// ---------------------------------------------------------------------------
// 顶栏操作：**按页面**配置的跨页快捷入口。
//
// 此前顶栏把「新建报价 / 新增订单」两个按钮**硬编码**在模板里，于是客户档案、
// 现金银行、报表中心、操作日志……所有约 50 个页面的右上角都挂着同一对按钮，
// 跟当前页面毫无关系。这里改成按菜单 key 查表：只渲染当前页真正该有的入口，
// 查不到就**一个按钮都不显示**（宁可空着，也不要放个无关的按钮）。
//
// 收录标准（严格照这条卡，否则又会变成噪音）：
//   只放「在这个页面上干完活，最可能接着点的那一步」——即业务上的下一步动作。
//   **不放"能跳到哪"**：侧边栏本来就能到的地方，放进来只是重复，等于把
//   "全站挂同一对按钮"的老毛病换个形式再犯一遍。
//   所以系统设置类（用户角色/参数/字典/打印模板/操作日志/公司信息）一律不配。
//
// 两个约定：
// 1. 为什么不写进上面的 menuGroups：那份结构被 tests/test_system_users.py 用正则
//    逐行解析，与后端 PERMISSION_CATALOG 做一致性比对，往里塞字段会破坏那条断言。
// 2. 这些是页面级的**导航**入口，与页面内部的「保存/开单」是两种职责 ——
//    后者仍留在各自表单里。
//
// 字段：label 按钮文字 / to 目标菜单 key / variant primary(实心,主操作) | secondary(描边)
// 顺序约定：次要动作在左、主要动作在右（与参考图一致）。

// 左侧导航配色主题清单：`key` 与 styles.css 的 [data-nav-theme=...] 一一对应，
// `swatch` 是切换器上那个小圆点的预览渐变（与主题块里的 brand-mark 保持一致）。
// 新增一套风格 = 这里加一行 + styles.css 加一个同名主题块，两处都是纯数据。
export const NAV_THEMES = [
  { key: 'default', label: '深空蓝', swatch: 'linear-gradient(135deg, #2563eb, #4f46e5)' },
  { key: 'graphite', label: '石墨黑', swatch: 'linear-gradient(135deg, #52525b, #18181b)' },
  { key: 'indigo', label: '靛蓝', swatch: 'linear-gradient(135deg, #6366f1, #8b5cf6)' },
  { key: 'pine', label: '青松绿', swatch: 'linear-gradient(135deg, #0d9488, #059669)' },
  { key: 'burgundy', label: '勃艮第红', swatch: 'linear-gradient(135deg, #be123c, #7f1d1d)' },
  { key: 'light', label: '珍珠白', swatch: 'linear-gradient(135deg, #f8fafc, #cbd5e1)' },
];

export const emptyCustomerForm = {
  code: '',
  name: '',
  // 所属分类：'' = 未分类（提交时归 null）；数字字符串 = customer_categories.id
  category_id: '',
  // —— 开票信息（2026-10-23）——
  // 客户级别 level 已从表单移除（业务上没人维护，占着一行还容易被填成"重要客户"这种自由文本）；
  // 换成开票真正要用到的四列：税号、开户行、账号、开票电话。
  tax_no: '',
  bank_name: '',
  bank_account: '',
  invoice_phone: '',
  businesser: '',
  contact: '',
  phone: '',
  email: '',
  address: '',
};

export const emptyProductForm = {
  sku: '',
  name: '',
  category: '',
  unit: '',
  purchase_price: '',
  sale_price: '',
  // 默认税率留空：货物 13 / 农产品 9 / 服务 6 各档不同，预设一个会让人开错票
  tax_rate: '',
  // —— 对齐浩技云商品档案的字段：后端早就存了，前端表单/列表此前一直没接 ——
  mnemonic: '',      // 助记码
  standards: '',     // 规格
  brand: '',         // 型号
  bar_code: '',      // 条码
  color: '',         // 颜色
  size: '',          // 尺码
  manufacturer: '',  // 生产商
  serial_no: '',     // 序列号
  unit_weight: '',   // 单位重量
  stock_upper: '',   // 库存上限
  stock_lower: '',   // 库存下限
  pack_qty: '',      // 包装数（**只读**：由辅助单位里勾了「默认」的那一行同步过来）
  shelf_life: '',    // 保质期（天）
  warn_days: '',     // 预警天数
  image_url: '',     // 商品图片
  note: '',          // 备注
  // 辅助单位（第三阶段 3a）：`[]` = 已加载且为空；编辑态先置 undefined 表示"还没拉到"，
  // 此时提交会**整个略过** units 键，后端就不会碰已有的辅助单位（详见 lib/productUnits.js）。
  units: [],
};

// 采购/销售订单（doc_type=order）：只订货不动库存财务，多行明细
export const emptyOrderItem = { product_id: '', quantity: '1', unit_price: '0' };
export const emptyPurchaseOrderForm = {
  supplier_id: '',
  warehouse_id: '',
  // 归集到哪个项目（可空）：项目成本/收入靠它从财务流水里归集
  project_id: '',
  delivery_date: '',
  payment_method: '',
  // 选客/选供应商时自动带出的三项快照（只回填空字段，手填不覆盖）
  contact: '',
  contact_phone: '',
  address: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
export const emptySalesOrderForm = {
  customer_id: '',
  warehouse_id: '',
  // 归集到哪个项目（可空）：项目成本/收入靠它从财务流水里归集
  project_id: '',
  delivery_date: '',
  payment_method: '',
  // 选客/选供应商时自动带出的三项快照（只回填空字段，手填不覆盖）
  contact: '',
  contact_phone: '',
  address: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
// 采购入库单（doc_type=inbound）：真实入库，写库存 + 应付
export const emptyInboundForm = {
  supplier_id: '',
  warehouse_id: '',
  order_date: '',
  payment_method: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
// 销售开单 / 出库单（doc_type=outbound）：真实出库，写库存 + 应收
export const emptyOutboundForm = {
  customer_id: '',
  warehouse_id: '',
  order_date: '',
  payment_method: '',
  // 物流 / 签收（四流合一的物流流）：开单时可先填物流公司+单号，
  // 签收人与签收时间一般到货后补（详情抽屉里的「物流 / 签收」区块也能改）。
  logistics_company: '',
  logistics_no: '',
  signed_by: '',
  signed_at: '',
  note: '',
  items: [{ ...emptyOrderItem }],
};
export const DOC_STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  completed: '已转单',
  cancelled: '已取消',
};

/**
 * 销售**出库单**专用状态标签（2026-10-20 出库看板上线时新增）。
 *
 * 出库单的 completed 在业务语义上是「已发货」，与订单的「已转单」不同；
 * 其余模块继续用 DOC_STATUS_LABELS，互不影响。
 */
export const OUTBOUND_STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  completed: '已发货',
  cancelled: '已取消',
};

/**
 * 销售/采购**订单**专用的状态标签（2026-10-18 单步审核上线时新增）。
 *
 * ⚠️ 刻意不复用上面的 `DOC_STATUS_LABELS`：那张表被生产单/盘点/调拨/组合拆卸等
 *   十几个模块共用，把 `submitted` 的中文从"已提交"改成"待审核"会全站变字。
 *   同一批单据里出库单仍然用 `submitted=已提交`，订单用 `pending=待审核` —— 两者
 *   在数据库里都是 `submitted`，由后端 `app/core/doc_status.py` 按 doc_type 归一。
 *
 * 后端是唯一权威：未知状态在这里会回退成原始英文码（不静默吞掉）。
 */
export const ORDER_STATUS_LABELS = {
  draft: '草稿',
  pending: '待审核',
  submitted: '待审核',
  approved: '已审核',
  shipped: '已发货',
  completed: '已转单',
  cancelled: '已取消',
};

/** 订单状态的语义分组，供按钮显隐判断（与后端 flow 一一对应） */
export const ORDER_STATUS_GROUP = {
  draft: 'pending',
  pending: 'pending',
  submitted: 'pending',
  approved: 'approved',
  shipped: 'shipped',
  completed: 'completed',
  cancelled: 'cancelled',
};

export const orderStatusLabel = (status) =>
  ORDER_STATUS_LABELS[String(status || '').trim()] || status || '—';

export const orderStatusGroup = (status) =>
  ORDER_STATUS_GROUP[String(status || '').trim()] || '';

export const emptySupplierForm = {
  code: '',
  name: '',
  // 纳税人识别号（2026-10-22）：进项票"税号优先、名称兜底"的匹配依据。
  // 留空 = 只用名称匹配（老供应商不必补录）。
  tax_no: '',
  // 所属分类：'' = 未分类（提交时归 null）；口径同 emptyCustomerForm.category_id
  category_id: '',
  short_name: '',
  contact: '',
  mobile: '',
  phone: '',
  // —— 开票信息（2026-10-23）：开户行/账号本来就在库里，这次一并放上表单 ——
  bank_name: '',
  bank_account: '',
  invoice_phone: '',
  email: '',
  address: '',
};

// 仓库档案：进销存的采购入库 / 销售出库 / 调拨都要选仓库，是库存模块的主数据。
export const emptyWarehouseForm = {
  code: '',
  name: '',
  location: '',
  manager: '',
  phone: '',
  is_active: true,
  note: '',
};

// —— 基础资料收尾：员工档案 / 期初建账 ——
export const emptyEmployeeForm = {
  code: '',
  name: '',
  gender: '',
  department_id: '',
  position: '',
  phone: '',
  id_card: '',
  hire_date: '',
  leave_date: '',
  status: 'active',
  base_salary: '',
  bank_name: '',
  bank_account: '',
  emergency_contact: '',
  emergency_phone: '',
  note: '',
};

// 采购 / 销售对账单**不另建页面**：
// 后端按往来单位出账（`/finance/reconciliation`）与对账单打印早就做好了，
// 前端「往来对账」页也已经是"期初 → 逐笔 → 期末 + 打印"。
// 这两个菜单是**预设视图入口**：点进去就是往来对账页，只把往来类型锁定成
// 供应商 / 客户。再造两个页面只会让同一份账有两处实现，迟早对不上。
export const LEDGER_ALIASES = { 'purchase-statement': 'supplier' };

// 对账单两个菜单（采购对账单 / 销售对账单）指向 statements 页并锁定方向：
// payable=应付（采购侧），receivable=应收（销售侧）。与 LEDGER_ALIASES 是两套入口，别混用。
export const STATEMENT_ALIASES = { 'purchase-statement': 'payable' };

// 对账单三态视图（2026-10-20 融合后）：全部 / 应收 / 应付。
// StatementEditor 用它渲染页签与标题，statementScope() 把 code 归一成完整配置。
export const STATEMENT_SCOPES = [
  { code: 'all', label: '全部', partyType: '', partyLabel: '', title: '对账单台账' },
  { code: 'out', label: '应收', partyType: 'customer', partyLabel: '客户', title: '应收对账单' },
  { code: 'in', label: '应付', partyType: 'supplier', partyLabel: '供应商', title: '应付对账单' },
];

export const isStatementScope = (value) => STATEMENT_SCOPES.some((item) => item.code === value);

export function statementScope(value) {
  return STATEMENT_SCOPES.find((item) => item.code === value) || STATEMENT_SCOPES[0];
}

// —— 现金银行 / 日常收支（财务管理收尾）——
export const BANK_ACCOUNT_TYPE_LABEL = { cash: '现金', bank: '银行', other: '其他' };

export const emptyBankAccountForm = {
  id: '',
  code: '',
  name: '',
  account_type: 'bank',
  bank_name: '',
  account_no: '',
  init_balance: '0',
  sort_order: '0',
  is_active: true,
  note: '',
};

export const emptyBankTransferForm = {
  from_account_id: '',
  to_account_id: '',
  amount: '',
  transfer_date: '',
  handler: '',
  note: '',
};

export const emptyEntryForm = {
  transaction_type: 'expense',
  category: '',
  bank_account_id: '',
  amount: '',
  occurred_at: '',
  handler: '',
  note: '',
};

export const emptyEntryQuery = { entry_type: '', from: '', to: '', bank_account_id: '', keyword: '' };

// —— 组合拆卸（库存管理）——
export const emptyAssemblyForm = {
  doc_type: 'combo',
  warehouse_id: '',
  product_id: '',
  quantity: '1',
  order_date: '',
  handler: '',
  note: '',
};

// 期初建账页的三个 Tab
export const OPENING_TABS = [
  { key: 'stock', label: '库存期初' },
  { key: 'receivable', label: '应收期初' },
  { key: 'payable', label: '应付期初' },
];

// 期初录入草稿的一行（还没保存进库）
export const emptyOpeningDraft = { warehouse_id: '', product_id: '', quantity: '', unit_price: '', note: '' };

// 购销合同（模板 A2 · 标准版）表单。条款变量留空则由后端用行业常规表述兜底，
// 所以这里只给必填项与几个常用默认值，用户想改再改。
export const emptyContractForm = {
  contract_type: 'sales',
  party_id: '',
  // 模板库（上传的 Word/PDF/图片）选中的那一份；'' = 用系统内置《产品买卖合同（简易版）》
  template_id: '',
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
export const CONTRACT_STATUS_LABEL = {
  draft: '草稿',
  signed: '已签订',
  executing: '执行中',
  finished: '已完成',
  void: '已作废',
};
export const contractStatusLabel = (status) => CONTRACT_STATUS_LABEL[status] || status;

// 销售报价单表单（对齐浩技云「销售 → 报价单」）。报价单是商务意向文件，
// 不产生应收、不动库存；客户确认后一键转成销售订单再走单据链路。
export const emptyQuotationForm = {
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
export const QUOTATION_STATUS_LABEL = {
  draft: '草稿',
  quoted: '已报价',
  accepted: '已接受',
  rejected: '已拒绝',
  void: '已作废',
};
export const quotationStatusLabel = (status) => QUOTATION_STATUS_LABEL[status] || status;

// 采购退货单表单（对齐浩技云「采购管理 → 退货管理」）。退货是采购入库的反向单据：
// 货退回给供应商，库存减少、应付冲减。选供应商自动带出联系人/电话/地址快照。
export const emptyPurchaseReturnForm = {
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
export const PURCHASE_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退货',
  cancelled: '已取消',
};
export const purchaseReturnStatusLabel = (status) => PURCHASE_RETURN_STATUS_LABEL[status] || status;

// 销售退货单表单（对齐浩技云「销售管理 → 销售退货」）。退货是销售开单（出库）的反向单据：
// 客户把货退回来，库存增加、应收冲减。选客户自动带出联系人/电话/地址快照。
export const emptySalesReturnForm = {
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
export const SALES_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退货',
  cancelled: '已取消',
};
export const salesReturnStatusLabel = (status) => SALES_RETURN_STATUS_LABEL[status] || status;

// 库存调拨单表单（对齐浩技云「库存管理 → 调拨管理」）。调拨是同一企业内部的库存
// 位置转移：货物从调出仓库搬到调入仓库，总量与资产总额都不变，所以只写库存流水、
// 不写财务流水。明细只录数量（成本单价可选，仅打印参考）。
export const emptyTransferForm = {
  from_warehouse_id: '',
  to_warehouse_id: '',
  transfer_date: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

// 调拨单状态 → 中文标签
export const TRANSFER_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已调拨',
  cancelled: '已取消',
};
export const transferStatusLabel = (status) => TRANSFER_STATUS_LABEL[status] || status;

// 库存盘点单表单（对齐浩技云「库存管理 → 盘点管理」）。盘点是账实核对：
// 账面数由系统按现存量带出（「带出账面库存」按钮调 /stocktakings/plan），
// 人只填实盘数，盈亏由后端统一算（实盘 - 账面）。
export const emptyStocktakingForm = {
  warehouse_id: '',
  check_date: '',
  handler: '',
  scope: '',
  note: '',
  items: [],
};

export const STOCKTAKING_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已调整',
  cancelled: '已取消',
};
export const stocktakingStatusLabel = (status) => STOCKTAKING_STATUS_LABEL[status] || status;

// 报损报溢单表单（对齐浩技云「库存管理 → 报损报溢」）。报损与报溢是同一张表的
// 两个方向，用 adjust_type 区分：报损减库存、报溢加库存；明细数量恒正。
export const emptyAdjustmentForm = {
  adjust_type: 'scrap',
  warehouse_id: '',
  adjust_date: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

export const ADJUSTMENT_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已生效',
  cancelled: '已取消',
};
export const adjustmentStatusLabel = (status) => ADJUSTMENT_STATUS_LABEL[status] || status;

// 报损报溢类型 → 中文标签 + 库存方向
export const ADJUST_TYPE_LABEL = { scrap: '报损', overflow: '报溢' };
export const ADJUST_TYPE_DIRECTION = { scrap: '减少库存', overflow: '增加库存' };
export const adjustTypeLabel = (type) => ADJUST_TYPE_LABEL[type] || type;

// 生产计划单表单（对齐浩技云「生产管理 → 生产计划」）。计划只是排产意图，
// 不写库存、不写财务，是整条生产链路的起点：MRP → 领料 → 退料 → 成品入库。
export const emptyProductionPlanForm = {
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

export const PLAN_TYPE_LABEL = { self: '自制', outsource: '委外' };
export const planTypeLabel = (type) => PLAN_TYPE_LABEL[type] || type;

export const PRODUCTION_PLAN_STATUS_LABEL = {
  draft: '草稿',
  planned: '已计划',
  released: '已下达',
  closed: '已关闭',
  cancelled: '已取消',
};
export const productionPlanStatusLabel = (status) => PRODUCTION_PLAN_STATUS_LABEL[status] || status;

// MRP 物料行状态 → 中文标签（product=顶层产出，不参与缺料判定）
export const MRP_STATUS_LABEL = {
  product: '产出',
  sufficient: '库存充足',
  partial: '部分缺料',
  shortage: '缺料',
};
export const mrpStatusLabel = (status) => MRP_STATUS_LABEL[status] || status;

// 生产领料单表单（对齐浩技云「生产管理 → 生产领料」）。领料把原材料从仓库
// 发到车间：原材料库存减少，属纯库存单据，不写财务。可按生产计划一键带出底稿。
export const emptyMaterialIssueForm = {
  plan_id: '',
  warehouse_id: '',
  issue_date: '',
  workshop: '',
  handler: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

export const MATERIAL_ISSUE_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已领料',
  cancelled: '已取消',
};
export const materialIssueStatusLabel = (status) => MATERIAL_ISSUE_STATUS_LABEL[status] || status;

// 生产退料单表单（领料的反向单据）：车间余料退回仓库，原材料库存增加。
export const emptyMaterialReturnForm = {
  plan_id: '',
  warehouse_id: '',
  return_date: '',
  workshop: '',
  handler: '',
  reason: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

export const MATERIAL_RETURN_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已退料',
  cancelled: '已取消',
};
export const materialReturnStatusLabel = (status) => MATERIAL_RETURN_STATUS_LABEL[status] || status;

// 成品入库单表单（对齐浩技云「生产管理 → 成品入库」）。成品入库是生产链路
// 的收口：车间把成品交回仓库，成品库存增加，并结转生产成本（写财务成本流水）。
export const emptyFinishedGoodsForm = {
  plan_id: '',
  warehouse_id: '',
  receipt_date: '',
  workshop: '',
  handler: '',
  note: '',
  items: [{ product_id: '', quantity: '1', unit_price: '0' }],
};

export const FINISHED_GOODS_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已入库',
  cancelled: '已取消',
};
export const finishedGoodsStatusLabel = (status) => FINISHED_GOODS_STATUS_LABEL[status] || status;

// 委外加工单表单（对齐浩技云「生产管理 → 委外加工」）。一张单两个方向：
// 发料（原材料出库）+ 收成品（成品入库），并按加工费产生应付。
export const emptyOutsourcingForm = {
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

export const OUTSOURCING_STATUS_LABEL = {
  draft: '草稿',
  submitted: '已收发',
  cancelled: '已取消',
};
export const outsourcingStatusLabel = (status) => OUTSOURCING_STATUS_LABEL[status] || status;

// ——— 报表中心（第 4 批）———
// 16 张报表**不写死在前端**：目录由后端 /reports/catalog 下发（唯一事实来源），
// 页面按目录渲染菜单，再按 report.shape 选渲染器。加一张报表只需改后端目录。
export const REPORT_SHAPE_LABEL = {
  crosstab: '交叉表',
  detail: '明细表',
  flow: '收发存',
  overview: '大盘',
};

// 报表查询条件。留空 = 用后端给的默认区间（日报 30 天、月报 12 个月…）。
export const emptyReportQuery = {
  date_from: '',
  date_to: '',
  dimension: '',
  period: '',
  keyword: '',
};

export const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
export const plain = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 });

export const emptyInventoryForm = {
  product_id: '',
  warehouse_id: '',
  transaction_type: 'inbound',
  quantity: '1',
  unit_price: '0',
};

// 现存量状态 → 中文标签与样式类（阈值来自商品档案的库存上下限）
export const STOCK_STATUS_LABEL = {
  shortage: '缺货',
  low_stock: '低库存',
  overstock: '积压',
  normal: '正常',
};
export const stockStatusLabel = (status) => STOCK_STATUS_LABEL[status] || '正常';

// 单据来源 → 中文标签。库存流水/财务流水共用后端 DOC_TYPES 的 key，
// 再补一个库存专用的 opening（期初建账）。
export const DOC_TYPE_LABEL = {
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
export const docTypeLabel = (type) => DOC_TYPE_LABEL[type] || type || '手工登记';

// 财务流水「业务类型」→ 中文。取值与 app/models/finance.py:25-26 的 transaction_type 注释一一对应。
// ⚠️ 和 DOC_TYPE_LABEL 不是一张表：那张是**来源单据**（related_type），这张是**业务类型**
//    （transaction_type），同一个 receipt 在两列里都可能出现，含义不同别混用。
export const FINANCE_TYPE_LABEL = {
  receivable: '应收',
  payable: '应付',
  receipt: '收款',
  payment: '付款',
  cost: '成本',
  expense: '费用',
  income: '收入',
  scrap: '报损',
  overflow: '报溢',
};
export const financeTypeLabel = (type) => FINANCE_TYPE_LABEL[String(type || '').trim()] || type || '—';

// 项目状态：取值必须与后端 PROJECT_STATUS 一致（不一致的那个选项一保存就 400）
export const PROJECT_STATUS_LABEL = {
  planned: '计划中',
  in_progress: '进行中',
  delayed: '延期',
  completed: '已完成',
  closed: '已关闭',
};
export const PROJECT_STATUS_TONE = {
  planned: 'muted',
  in_progress: 'ok',
  delayed: 'warn',
  completed: 'ok',
  closed: 'muted',
};

// 变动查询页的筛选条件
export const emptyStockLogFilter = { type: '', warehouse_id: '', keyword: '' };

export const emptyFinanceForm = {
  transaction_type: 'income',
  amount: '0',
  currency: 'CNY',
  note: '',
  related_order_id: '',
  customer_id: '',
  supplier_id: '',
};

// —— 系统管理（第 5 批）：用户 / 角色 / 组织机构 ——
// 三个表单都用 id 区分「新增」与「编辑」：id 非空即编辑态
export const emptySystemUserForm = {
  id: '',
  username: '',
  password: '',
  full_name: '',
  email: '',
  role_id: '',
  department_id: '',
  phone: '',
  position: '',
  remark: '',
  is_active: true,
};

export const emptyRoleForm = {
  id: '',
  code: '',
  name: '',
  description: '',
  sort_order: '0',
  is_active: true,
};

export const emptyDepartmentForm = {
  id: '',
  code: '',
  name: '',
  parent_id: '',
  leader: '',
  phone: '',
  sort_order: '0',
  is_active: true,
  note: '',
};

// 角色权限草稿：all=true 是超级管理员（勾不勾都拥有全部菜单），menus 是勾中的菜单键
export const emptyPermissionDraft = { all: false, menus: [] };

// 菜单管理（第 10 批）：新增/编辑一个菜单节点。
// page_key 留空 = 分组（容器，可继续往里加下级）；选了页面 = 菜单项（叶子，点它跳那个页面）。
export const emptyMenuForm = {
  id: null,
  label: '',
  parent_id: '',
  page_key: '',
  sort_order: 0,
  is_enabled: true,
  note: '',
};

export const SYSTEM_TABS = [
  { key: 'users', label: '用户管理' },
  { key: 'roles', label: '角色管理' },
];

// —— 系统管理（第 5 批第 2 轮）：参数设置 / 数字字典 ——
export const PARAM_VALUE_TYPE_LABEL = { string: '文本', bool: '开关', int: '整数', decimal: '小数' };

export const emptyParamForm = {
  param_key: '',
  label: '',
  param_value: '',
  param_group: 'system',
  value_type: 'string',
  description: '',
  sort_order: '0',
};

export const emptyDictionaryForm = { dict_type: '', dict_name: '', description: '', is_active: true };

export const emptyDictItemForm = {
  id: '',
  item_value: '',
  item_label: '',
  sort_order: '0',
  is_enabled: true,
  remark: '',
};

// 业务表单要用到的字典（对应后端 /system/lookups 的 types 参数）：
//   payment_method → 采购/销售/报价/退货单的「付款方式」候选
//   product_unit   → 商品档案「单位」候选
//   position       → 用户岗位候选
//   bank_name      → 客户/供应商「开户银行」候选
export const LOOKUP_TYPES = ['payment_method', 'product_unit', 'position', 'bank_name', 'income_category', 'expense_category', 'tax_rate'];

// —— 系统管理（第 5 批第 3 轮）：打印模板 / 操作日志 ——
// 打印模板草稿：只有渲染器真正支持的项，改完点「保存」才对真单据生效
export const emptyTemplateDraft = {
  name: '',
  title: '',
  header_text: '',
  footer_text: '',
  show_company: true,
  show_signatures: true,
  note: '',
};

export const emptyLogQuery = { keyword: '', method: '', username: '', start: '', end: '' };

export const LOG_STATUS_TONE = (code) => (code >= 500 ? 'danger' : code >= 400 ? 'warn' : 'ok');

// 日志时间显示到分钟：跟用户表格里的「最后登录」保持同一写法
export const formatLogTime = (value) => (value ? String(value).slice(0, 16).replace('T', ' ') : '—');

// 模板是否被改过默认外观：列在左栏一眼看出"哪些单据动过"
export const isTemplateCustomized = (row) =>
  Boolean(
    (row.title || '') ||
    (row.header_text || '') ||
    (row.footer_text || '') ||
    (row.note || '') ||
    (row.name && row.name !== row.default_name) ||
    row.show_company === false ||
    row.show_signatures === false
  );

// 从 JWT 里解出账套号（schema 名）。
// 只解 payload、**不校验签名** —— 前端本来就不该拿它当权限凭据，
// 这里只是为了"刷新页面后知道自己在哪套账"，真正的校验在服务端每次请求都做。
export const readCompanyFromToken = (token) => {
  try {
    const payload = token.split('.')[1];
    if (!payload) return '';
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const decoded = JSON.parse(decodeURIComponent(escape(atob(normalized))));
    return typeof decoded.company === 'string' ? decoded.company : '';
  } catch {
    return '';
  }
};

