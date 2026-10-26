// 自动提取自 App.jsx（selectedTab='contracts'）— 见 scripts/extract_pages.py
import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';
import { saveBlob } from '../lib/download.js';
import ContractTemplateDrawer from '../components/contracts/ContractTemplateDrawer.jsx';
import ContractPaymentPlans from '../components/contracts/ContractPaymentPlans.jsx';
/**
 * 购销合同页的分栏默认宽度（2026-10-23）。
 *
 * ⚠️ 必须**在模块顶层**播种，不能放 useEffect：effect 在首次渲染之后才跑，
 *    那时 ResizableLayout 的 useState 已经按 null 算成 50/50，改 storage 也来不及。
 * 为什么单独一个键：全站共用一个 `erp:mgrid:left` 时，别处把左栏拖窄会带到这里，
 *    而这里右栏要放 7 列表格 + 三颗操作按钮，太窄就"每列都是省略号"。
 */
const CONTRACT_SPLIT_KEY = 'erp:mgrid:left:contracts';

export default function ContractsPage({ ctx }) {
  const {
    ADJUSTMENT_STATUS_LABEL,
    ADJUST_TYPE_DIRECTION,
    ADJUST_TYPE_LABEL,
    API_BASE,
    BANK_ACCOUNT_TYPE_LABEL,
    CONTRACT_STATUS_LABEL,
    DOC_STATUS_LABELS,
    DOC_TYPE_LABEL,
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
    bomForm,
    bomTree,
    cards,
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
    handleStocktakingChange,
    handleStocktakingItemChange,
    handleStocktakingProductPick,
    handleSupplierChange,
    handleSyncInvoicesToFinance,
    handleSystemUserChange,
    handleTemplateDraftChange,
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
    openGlEntry,
    openInvoiceEdit,
    openInvoicePreview,
    openInvoiceQr,
    openProductEdit,
    openProjectCost,
    openProjectEdit,
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
    userProfile,
    visibleGroups,
    warehouseForm,
    warehouseModalOpen,
    warehouses
  } = ctx;

  // —— 《工矿产品购销合同》正文预览（2026-10-22）——
  // 与本页「保存合同」的区别：这里**不写库**，只是把表单数据填进标准范本给人看。
  // 保存后想要同一份正文，用列表里的「打印」即可（那是库里这张合同的打印件）。
  const [contractDoc, setContractDoc] = useState(null);
  const [contractDocBusy, setContractDocBusy] = useState('');

  // 合同详情弹窗：直接内嵌最终打印 PDF（不再展示缩减版 HTML 明细表）
  const [detailPdfUrl, setDetailPdfUrl] = useState('');
  const [detailPdfBusy, setDetailPdfBusy] = useState(false);
  const [detailPdfError, setDetailPdfError] = useState('');

  // 「合同正文预览」弹窗也直接展示最终 PDF，不再渲染 HTML 表格。
  const [docPdfUrl, setDocPdfUrl] = useState('');
  const [docPdfBusy, setDocPdfBusy] = useState(false);
  const [docPdfError, setDocPdfError] = useState('');

  useEffect(() => {
    if (!contractDoc?.payload) {
      setDocPdfUrl('');
      setDocPdfError('');
      setDocPdfBusy(false);
      return undefined;
    }
    let alive = true;
    let objectUrl = '';
    setDocPdfBusy(true);
    setDocPdfError('');
    (async () => {
      try {
        const response = await fetch(`${API_BASE}/print/contract-document/pdf`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
          body: JSON.stringify(contractDoc.payload),
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(typeof data.detail === 'string' ? data.detail : 'PDF 预览生成失败');
        }
        const body = await response.json();
        const binary = atob(body.content_base64 || '');
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        objectUrl = URL.createObjectURL(
          new Blob([bytes], { type: body.content_type || 'application/pdf' }),
        );
        if (alive) setDocPdfUrl(objectUrl);
        else URL.revokeObjectURL(objectUrl);
      } catch (err) {
        if (alive) setDocPdfError(err.message || 'PDF 预览生成失败');
      } finally {
        if (alive) setDocPdfBusy(false);
      }
    })();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [contractDoc?.payload]);

  useEffect(() => {
    if (!selectedContract?.id) {
      setDetailPdfUrl('');
      setDetailPdfError('');
      setDetailPdfBusy(false);
      return undefined;
    }
    let alive = true;
    let objectUrl = '';
    setDetailPdfBusy(true);
    setDetailPdfError('');
    (async () => {
      try {
        const response = await fetch(`${API_BASE}/print/contract/${selectedContract.id}`, {
          headers: { Accept: 'application/json', ...authHeaders() },
        });
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(typeof data.detail === 'string' ? data.detail : 'PDF 预览生成失败');
        }
        const payload = await response.json();
        const binary = atob(payload.content_base64 || '');
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
        objectUrl = URL.createObjectURL(
          new Blob([bytes], { type: payload.content_type || 'application/pdf' }),
        );
        if (alive) setDetailPdfUrl(objectUrl);
        else URL.revokeObjectURL(objectUrl);
      } catch (err) {
        if (alive) setDetailPdfError(err.message || 'PDF 预览生成失败');
      } finally {
        if (alive) setDetailPdfBusy(false);
      }
    })();
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selectedContract?.id]);

  // —— 合同模板库（2026-10-22）——
  // templates：抽屉与表单下拉共用的一份列表；drawerOpen 控制抽屉显隐。
  // 上传/删除后 onChanged 会重新拉一次，保证下拉里马上能看到新模板。
  const [templates, setTemplates] = useState([]);
  const [templateDrawerOpen, setTemplateDrawerOpen] = useState(false);

  const loadTemplates = async () => {
    try {
      const response = await fetch(`${API_BASE}/contract-templates`, { headers: authHeaders() });
      if (!response.ok) return;
      const data = await response.json();
      setTemplates(Array.isArray(data) ? data : []);
    } catch {
      /* 模板库读不到不影响开单，静默 */
    }
  };

  useEffect(() => {
    loadTemplates();
    // 只在进页面时拉一次；上传/删除后由抽屉回调刷新
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 当前选中的模板对象（null = 未选/已删除）。名字带 picked 是为了避开 ctx 里的 activeTemplate */
  const pickedTemplate = templates.find((item) => String(item.id) === String(contractForm.template_id)) || null;

  /** 预览模板：文件接口要 Bearer，iframe/img 带不了请求头 → fetch 成 blob 再开新窗口 */
  const previewSelectedTemplate = async () => {
    if (!pickedTemplate) return;
    // Word 模板浏览器放不了 → 弹「模板变量清单」，告诉用户这份模板要填哪些数据
    if (pickedTemplate.kind === 'word') {
      await showTemplateVariables();
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/contract-templates/${pickedTemplate.id}/file`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`模板打不开（HTTP ${response.status}）`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      // 新窗口用完即弃；不 revoke 也能自动回收（页面关闭时），这里保留是为了同页刷新不泄漏
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setNotice(err.message || '预览模板失败');
    }
  };

  // —— Word 模板变量清单（2026-10-25）：后端解包 docx 提取 {{变量}}，
  //    弹窗里列清楚 + 常用变量的中文说明，"这个模板需要填哪些数据"一目了然 ——
  const [tplVars, setTplVars] = useState(null); // {loading, items, message, name}
  const VAR_HINTS = {
    party_name: '对方单位名称（客户/供应商）',
    total_amount: '合同总金额',
    amount_chinese: '合同总金额（大写）',
    delivery_place: '交货地点',
    delivery_date: '交货时间',
    delivery_method: '交货方式',
    payment_terms: '付款方式/节点',
    sign_date: '签订日期',
    contract_no: '合同编号',
    own_name: '我方单位名称',
    quality_standard: '质量标准',
    penalty_rate: '违约金费率',
  };
  const showTemplateVariables = async () => {
    if (!pickedTemplate) return;
    setTplVars({ loading: true, items: [], message: '', name: pickedTemplate.name });
    try {
      const response = await fetch(`${API_BASE}/contract-templates/${pickedTemplate.id}/variables`, {
        headers: authHeaders(),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '读不出模板变量');
      setTplVars({
        loading: false,
        items: Array.isArray(data.variables) ? data.variables : [],
        message: data.message || '',
        name: pickedTemplate.name,
      });
    } catch (err) {
      setTplVars({ loading: false, items: [], message: err.message || '读不出模板变量', name: pickedTemplate.name });
    }
  };

  // —— 内嵌模板预览（2026-10-25）：选中模板后，表单下方立刻能看到它长什么样。
  //   PDF/图片模板（previewable）→ fetch 成 blob objectURL 塞进 iframe 原样展示；
  //   Word 模板浏览器放不了 → 显示「变量替换」说明卡（生成完整合同时系统替换变量）。
  //   模板切换/清空时 revoke 旧 blob，避免反复切换积累内存。 ——
  const [tplPreview, setTplPreview] = useState({ url: '', busy: false, error: '' });
  const pickedTemplateId = pickedTemplate?.id ?? null;
  useEffect(() => {
    let cancelled = false;
    setTplPreview((prev) => {
      if (prev.url) URL.revokeObjectURL(prev.url);
      return { url: '', busy: false, error: '' };
    });
    if (!pickedTemplateId) return undefined;
    const template = templates.find((item) => item.id === pickedTemplateId);
    if (!template || !template.previewable) return undefined; // Word → 只出说明卡
    setTplPreview({ url: '', busy: true, error: '' });
    (async () => {
      try {
        const response = await fetch(`${API_BASE}/contract-templates/${pickedTemplateId}/file`, {
          headers: authHeaders(),
        });
        if (!response.ok) throw new Error(`模板文件打不开（HTTP ${response.status}）`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        setTplPreview({ url, busy: false, error: '' });
      } catch (err) {
        if (!cancelled) setTplPreview({ url: '', busy: false, error: err.message || '预览失败' });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedTemplateId]);

  /** 下载完整合同（正文 + 模板原件）：Word 出 docx，其余出合成 PDF */
  const [fullContractBusy, setFullContractBusy] = useState('');
  const downloadFullContract = async (contractId, contractNo) => {
    if (!contractId) return;
    setFullContractBusy(String(contractId));
    try {
      const response = await fetch(`${API_BASE}/contracts/${contractId}/full-contract`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成完整合同失败');
      }
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const isWord = blob.type.includes('wordprocessingml');
      const replaced = response.headers.get('X-Template-Vars-Replaced');
      saveBlob(blob, `${contractNo || '合同'}_完整合同.${isWord ? 'docx' : 'pdf'}`);
      setNotice(
        isWord && replaced
          ? `已下载完整合同（Word 模板，替换了 ${replaced} 处变量）`
          : '已下载完整合同（正文 + 模板）',
      );
    } catch (err) {
      setNotice(err.message || '生成完整合同失败');
    } finally {
      setFullContractBusy('');
    }
  };

  /** 下载**填好数据的 Word**（供客户修改确认；不是模板原件） */
  const downloadContractWord = async (contract) => {
    if (!contract?.id) return;
    try {
      const response = await fetch(`${API_BASE}/exports/word/contract/${contract.id}`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 Word 失败');
      }
      const blob = await response.blob();
      saveBlob(blob, `购销合同-${contract.contract_no || contract.id}.docx`);
      setNotice('Word 已下载：请先与客户确认修改，确认无误后再下载/打印 PDF 盖章');
    } catch (err) {
      setNotice(err.message || '生成 Word 失败');
    }
  };

  /** 表单 → 正文生成接口的入参。字段映射与 `App.jsx::submitContract` 保持一致，
   *  少了任何一个，正文里就会出现"该有数据的地方是空的"。 */
  const buildContractDocPayload = () => {
    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    return {
      contract_type: contractForm.contract_type,
      party_type: contractForm.contract_type === 'sales' ? 'customer' : 'supplier',
      party_id: num(contractForm.party_id),
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
      // 选中了模板库范本就带上 —— 后端"下载完整合同"链路按它做变量替换
      template_id: contractForm.template_id ? Number(contractForm.template_id) : null,
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
      penalty_rate:
        contractForm.penalty_rate === '' || contractForm.penalty_rate === null
          ? null
          : Number(contractForm.penalty_rate) / 10000,
      dispute_resolution: contractForm.dispute_resolution || null,
      copies: num(contractForm.copies),
      items: contractForm.items
        .filter((row) => row.product_id)
        .map((row) => ({
          product_id: Number(row.product_id),
          quantity: Number(row.quantity) || 0,
          unit_price: Number(row.unit_price) || 0,
        })),
    };
  };

  const openContractDoc = async () => {
    if (!contractForm.party_id) {
      const msg = contractForm.contract_type === 'sales' ? '请先选择客户再生成正文。' : '请先选择供应商再生成正文。';
      window.alert(msg);
      setNotice(msg);
      return;
    }
    const payload = buildContractDocPayload();
    if (!payload.items.length) {
      const msg = '至少要有一行合同明细（商品不能为空）。';
      window.alert(msg);
      setNotice(msg);
      return;
    }
    setContractDocBusy('preview');
    try {
      const response = await fetch(`${API_BASE}/contracts/document/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成合同正文失败');
      }
      const data = await response.json();
      // 后端把补全过的 payload 一起返回（客户全称、商品名/规格/单位都已从档案取好），
      // 导出 PDF 时原样回传 —— 预览看到的与导出的必然是同一份。
      setContractDoc({ document: data.document, payload: data.payload });
    } catch (err) {
      setNotice(err.message || '生成合同正文失败');
    } finally {
      setContractDocBusy('');
    }
  };

  // —— 业务流转（2026-10-25）：先 Word 确认，后 PDF 盖章 ——
  // 主按钮 = 导出 Word（客户可改）；PDF 是次按钮，点它先防呆确认。
  const exportContractDocWord = async () => {
    if (!contractDoc) return;
    setContractDocBusy('word');
    try {
      const response = await fetch(`${API_BASE}/exports/word/contract-document`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(contractDoc.payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 Word 失败');
      }
      const blob = await response.blob();
      const no = String(contractDoc.document.contract_no || '').replace(/[\\/:*?"<>|]/g, '');
      saveBlob(blob, `合同正文-${no || '草稿'}.docx`);
      setNotice('Word 版已下载：请先与客户确认修改，确认无误后再生成 PDF 盖章版');
    } catch (err) {
      setNotice(err.message || '生成 Word 失败');
    } finally {
      setContractDocBusy('');
    }
  };

  const exportContractDoc = async () => {
    if (!contractDoc) return;
    // 防呆提示（2026-10-25）：PDF 是拿去盖章的，别让用户跳过 Word 确认那一步
    const okToSeal = window.confirm(
      '建议先下载 Word 版与客户确认。若已确认无误，是否直接生成最终 PDF（盖章版）？',
    );
    if (!okToSeal) return;
    setContractDocBusy('pdf');
    try {
      const response = await fetch(`${API_BASE}/print/contract-document/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
        body: JSON.stringify(contractDoc.payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 PDF 失败');
      }
      const body = await response.json();
      const binary = atob(body.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      saveBlob(new Blob([bytes], { type: body.content_type || 'application/pdf' }), body.filename);
      setNotice('合同正文 PDF 已生成并开始下载');
    } catch (err) {
      setNotice(err.message || '生成 PDF 失败');
    } finally {
      setContractDocBusy('');
    }
  };

  return (
    <>
              <ResizableLayout storageKey={CONTRACT_SPLIT_KEY}>
                <section className="panel form-panel contracts-form-panel">
                  <div className="section-header">
                    <h2>新增购销合同</h2>
                    <div className="contract-head-actions">
                      <span className="status-badge">模板 A2 · 标准版</span>
                      {/* 模板库入口（2026-10-22）：上传自己的范本，下方下拉里就能选 */}
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        data-contract-template-manage
                        onClick={() => setTemplateDrawerOpen(true)}
                        title="上传/管理自己的合同范本（Word / PDF / 图片）"
                      >
                        📁 模板管理
                      </button>
                    </div>
                  </div>

                  <form onSubmit={submitContract} className="erp-form">
                    {/* 选择合同模板：数据源就是模板库 */}
                    <div className="contract-template-pick" data-contract-template-pick>
                      <label>
                        选择合同模板
                        <select
                          value={String(contractForm.template_id ?? '')}
                          onChange={handleContractChange('template_id')}
                          data-contract-template-select
                        >
                          <option value="">不使用模板（系统内置《产品买卖合同（简易版）》）</option>
                          {templates.map((item) => (
                            <option key={item.id} value={String(item.id)}>
                              {item.name}
                              {item.kind === 'word' ? '（Word · 变量替换）' : ''}
                              {item.previewable ? '（可预览）' : ''}
                            </option>
                          ))}
                        </select>
                      </label>
                      {pickedTemplate && pickedTemplate.previewable ? (
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          data-contract-template-preview
                          onClick={previewSelectedTemplate}
                          title="对照模板填表（新窗口打开）"
                        >
                          预览模板
                        </button>
                      ) : null}
                      {pickedTemplate && pickedTemplate.kind === 'word' ? (
                        <span className="contract-template-tip">
                          Word 模板：生成单据后可下载「完整合同」，系统会把变量替换成真实数据
                        </span>
                      ) : null}
                    </div>

                    {/* —— 内嵌模板预览（2026-10-25）：选中模板立刻看得见 —— */}
                    {pickedTemplate ? (
                      <div className="contract-template-preview" data-contract-template-preview-panel>
                        <div className="ctp__head">
                          <strong>{pickedTemplate.name}</strong>
                          <span className={`ctp__kind ${pickedTemplate.kind === 'word' ? 'is-word' : 'is-view'}`}>
                            {pickedTemplate.kind === 'word' ? 'Word · 变量替换' : 'PDF/图片 · 原样预览'}
                          </span>
                          <button
                            type="button"
                            className="link-btn ctp__open"
                            onClick={previewSelectedTemplate}
                          >
                            {pickedTemplate.kind === 'word' ? '查看模板变量' : '新窗口打开'}
                          </button>
                        </div>
                        {pickedTemplate.kind === 'word' ? (
                          <div className="ctp__word-tip" data-ctp-word-tip>
                            📄 这是一份 <b>Word 模板</b>，浏览器里不能直接排版预览。
                            模板里写好的变量（{'{{party_name}}'}、{'{{total_amount}}'} 等）会在
                            <b> 生成完整合同时自动替换</b>成表单里的真实数据 ——
                            左侧表单照常填，填完点下面的按钮即可。
                          </div>
                        ) : tplPreview.busy ? (
                          <div className="ctp__loading">模板加载中…</div>
                        ) : tplPreview.error ? (
                          <div className="ctp__error">{tplPreview.error}</div>
                        ) : tplPreview.url ? (
                          <iframe
                            className="ctp__frame"
                            data-ctp-frame
                            src={tplPreview.url}
                            title={`模板预览：${pickedTemplate.name}`}
                          />
                        ) : null}
                        <div className="ctp__cta">
                          <button
                            type="button"
                            className="primary-btn small-btn"
                            data-ctp-generate
                            disabled={contractDocBusy === 'preview'}
                            onClick={openContractDoc}
                          >
                            {contractDocBusy === 'preview' ? '生成中…' : '填表完成后，点击这里生成完整合同 →'}
                          </button>
                        </div>
                      </div>
                    ) : null}
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
                          list="lookup-bank-name"
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
                        {/* 档案可能几百条：平铺下拉改可搜索。切换合同类型时
                            handleContractChange 已把 party_id 清空，不会串档案。
                            ⚠️ 原生 required 失效 —— 必填由 submitContract 的 party_id 守卫兜住。 */}
                        <ErpSearchSelect
                          options={contractForm.contract_type === 'sales' ? customers : suppliers}
                          value={String(contractForm.party_id ?? '')}
                          onChange={(value) => handleContractChange('party_id')({ target: { value } })}
                          placeholder={`搜索${contractForm.contract_type === 'sales' ? '客户' : '供应商'}名称 / 编码`}
                          emptyText="没有匹配的往来单位"
                          getOptionValue={(item) => String(item.id)}
                          getOptionLabel={(item) => `${item.name}（${item.code}）`}
                          getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                        />
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
                                                    <ErpSearchSelect
                            options={products}
                            value={String(row.product_id ?? '')}
                            onChange={handleContractItemChange(index, 'product_id')}
                            placeholder="搜索商品名称 / SKU"
                            emptyText="没有匹配的商品"
                            getOptionValue={(item) => String(item.id)}
                            getOptionLabel={(item) => item.name + (item.standards ? ' / ' + item.standards : '')}
                            getSearchText={(item) => [item.name, item.sku, item.mnemonic, item.code, item.bar_code].filter(Boolean).join(' ')}
                          />
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={row.quantity}
                            onChange={handleContractItemChange(index, 'quantity')}
                            placeholder="数量"
                          />
                          <input
                            type="number"
                            step="any"
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

                    <div className="contract-form-actions">
                      <button className="primary-btn" type="submit">保存合同</button>
                      {/* 按内置《产品买卖合同（简易版）》生成正文：只预览、不落库、不占合同号 */}
                      <button
                        className="secondary-btn"
                        type="button"
                        data-contract-doc
                        onClick={openContractDoc}
                        disabled={contractDocBusy === 'preview'}
                        title="把上面的客户、明细、金额、交货与付款条件自动填进《产品买卖合同（简易版）》"
                      >
                        {contractDocBusy === 'preview' ? '生成中…' : '生成合同正文'}
                      </button>
                    </div>
                    <p className="table-hint">
                      条款变量留空时由系统按行业常规表述兜底；「生成合同正文」可先预览标准范本，满意后再保存。
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
                    /* 横向滚动容器（2026-10-23）：操作列有三个按钮，窄屏下表格总宽会超过面板，
                       不套 overflow-x 的话按钮会直接飘到面板外面去（截图里"删除"飞出边框）。 */
                    <div className="table-scroll contract-list-scroll">
                    <table className="data-table contract-list-table">
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
                            <td title={row.contract_no}>{row.contract_no}</td>
                            <td>{row.contract_type === 'sales' ? '销售' : '采购'}</td>
                            <td title={row.party_name || ''}>{row.party_name || '—'}</td>
                            {/* 金额 + 付款进度（2026-10-23）：
                                不新增列 —— 右侧面板只有 700px，7 列已经排满，
                                再挤一列会让每列都变成省略号。进度条放在金额下面同样一眼可见。 */}
                            <td className="contract-amount-cell" title={
                              `已付 ¥${Number(row.payment_paid_amount || 0).toLocaleString()} / 总额 ¥${Number(row.total_amount || 0).toLocaleString()}`
                            }>
                              <span className="contract-amount-line">
                                ¥{Number(row.total_amount || 0).toLocaleString()}
                              </span>
                              {row.payment_progress === null || row.payment_progress === undefined ? (
                                <span className="contract-progress is-none" data-contract-progress={row.id}>
                                  未设付款计划
                                </span>
                              ) : (
                                <span className="contract-progress" data-contract-progress={row.id}>
                                  <span className="contract-progress__bar">
                                    <i
                                      className={Number(row.payment_progress) >= 100 ? 'is-full' : ''}
                                      style={{ width: `${Math.max(0, Math.min(100, Number(row.payment_progress)))}%` }}
                                    />
                                  </span>
                                  <em>{Number(row.payment_progress)}%</em>
                                </span>
                              )}
                            </td>
                            <td>{contractStatusLabel(row.status)}</td>
                            <td>{row.sign_date || '—'}</td>
                            <td className="contract-actions-cell">
                              <div className="contract-row-actions">
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/contract/${row.id}`, `购销合同_${row.contract_no}.pdf`);
                                }}
                              >
                                打印
                              </button>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  contractToOrder(row);
                                }}
                                disabled={Boolean(row.order_id)}
                                title={row.order_id ? `已生成单据 ${row.order_no}` : '按这张合同生成销售/采购单据'}
                              >
                                {row.order_id ? '已转单' : '生成单据'}
                              </button>
                              <button
                                type="button"
                                className="danger-btn"
                                data-contract-delete={row.id}
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
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  )}
                </section>

                {selectedContract && (
                  <div className="modal-overlay" onClick={() => setSelectedContract(null)}>
                    <div
                      className="modal-card contract-detail-modal"
                      data-contract-detail-modal
                      onClick={(event) => event.stopPropagation()}
                    >
                      <div className="modal-header">
                        <h3>合同 {selectedContract.contract_no}</h3>
                        <button type="button" className="close-btn" onClick={() => setSelectedContract(null)}>×</button>
                      </div>
                      <div className="contract-detail">
                        <div className="contract-pdf-wrap">
                          {detailPdfBusy ? (
                            <p className="contract-pdf-hint">正在生成最终打印 PDF 预览…</p>
                          ) : detailPdfError ? (
                            <p className="contract-pdf-hint contract-pdf-hint--error">{detailPdfError}</p>
                          ) : detailPdfUrl ? (
                            <iframe className="contract-pdf-frame" src={detailPdfUrl} title="合同 PDF 预览" />
                          ) : (
                            <p className="contract-pdf-hint">暂无 PDF 预览。请确认合同已保存且后端已启动。</p>
                          )}
                        </div>

                        {/* 付款计划（多期次）：录计划、记实付、传回单 */}
                        <ContractPaymentPlans
                          contractId={selectedContract.id}
                          authHeaders={authHeaders}
                          onSummary={(summary) => {
                            // ① 回写当前选中合同 → 弹窗头部的进度条跟着变
                            setSelectedContract((prev) =>
                              prev
                                ? {
                                    ...prev,
                                    payment_paid_amount: summary?.paid_amount ?? 0,
                                    payment_progress: summary?.progress ?? null,
                                    payment_shortfall: summary?.shortfall ?? 0,
                                  }
                                : prev,
                            );
                            // ② 同步列表那一行：列表数据是进页面时拉的，
                            //    不同步的话关掉弹窗看到的还是旧的 "0%"（实测踩过）。
                            setContracts((prev) =>
                              (prev || []).map((item) =>
                                String(item.id) === String(selectedContract?.id)
                                  ? {
                                      ...item,
                                      payment_paid_amount: summary?.paid_amount ?? 0,
                                      payment_progress: summary?.progress ?? null,
                                      payment_shortfall: summary?.shortfall ?? 0,
                                      payment_plan_count: summary?.plan_count ?? item.payment_plan_count,
                                      payment_planned_amount:
                                        summary?.planned_amount ?? item.payment_planned_amount,
                                    }
                                  : item,
                              ),
                            );
                          }}
                        />
                      </div>
                      <div className="modal-actions">
                        <button
                          type="button"
                          className="primary-btn"
                          onClick={() => downloadContractWord(selectedContract)}
                        >
                          下载 Word
                        </button>
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => printPdf(`/print/contract/${selectedContract.id}`, `购销合同_${selectedContract.contract_no}.pdf`)}
                        >
                          下载 / 打印 PDF
                        </button>
                        <button type="button" className="secondary-btn" onClick={() => setSelectedContract(null)}>关闭</button>
                      </div>
                    </div>
                  </div>
                )}
              </ResizableLayout>

      {/* 《工矿产品购销合同》正文预览。挂在 ResizableLayout **外面**：
          那个布局只认前两个子元素当左右栏，塞第三个进去会把左右两栏撑坏；
          而且正文是"一张长纸"，必须自己滚。 */}
      {contractDoc ? (
        <div
          className="modal-overlay cledger__doc-overlay"
          onClick={() => {
            if (!contractDocBusy) setContractDoc(null);
          }}
        >
          <div
            className="modal-card cledger__doc"
            data-contract-doc-preview
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h3>
                {contractDoc.document.title}
                <span className="cledger__doc-no">合同编号:{contractDoc.document.contract_no}</span>
              </h3>
            </div>

            <div className="modal-body cledger__doc-body">
              {docPdfBusy ? (
                <p className="contract-pdf-hint">正在生成最终打印 PDF 预览…</p>
              ) : docPdfError ? (
                <p className="contract-pdf-hint contract-pdf-hint--error">{docPdfError}</p>
              ) : docPdfUrl ? (
                <iframe className="contract-pdf-frame" src={docPdfUrl} title="合同正文 PDF 预览" />
              ) : (
                <p className="contract-pdf-hint">暂无 PDF 预览。</p>
              )}
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="primary-btn"
                data-contract-doc-word
                onClick={exportContractDocWord}
                disabled={contractDocBusy === 'word'}
              >
                {contractDocBusy === 'word' ? '生成中…' : '下载 Word'}
              </button>
              <button
                type="button"
                className="secondary-btn"
                data-contract-doc-pdf
                onClick={exportContractDoc}
                disabled={contractDocBusy === 'pdf'}
              >
                {contractDocBusy === 'pdf' ? '生成中…' : '下载 / 打印 PDF'}
              </button>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setContractDoc(null)}
                disabled={Boolean(contractDocBusy)}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Word 模板变量清单弹窗（2026-10-25）：「查看模板变量」点了就出 */}
      {tplVars ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setTplVars(null)}>
          <div className="modal-card ctp-vars" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h3>模板变量 · {tplVars.name}</h3>
              <button type="button" className="close-btn" onClick={() => setTplVars(null)} aria-label="关闭">
                ×
              </button>
            </div>
            <div className="modal-body">
              {tplVars.loading ? (
                <p className="cledger__muted">正在读取模板变量…</p>
              ) : tplVars.message && !tplVars.items.length ? (
                <p className="ctp-vars__msg">{tplVars.message}</p>
              ) : tplVars.items.length ? (
                <>
                  <p className="ctp-vars__lead">
                    这份 Word 模板需要填以下数据。生成完整合同时，系统会把这些变量自动替换成左侧表单里的真实内容：
                  </p>
                  <ul className="ctp-vars__list">
                    {tplVars.items.map((v) => (
                      <li key={v}>
                        <code>{`{{${v}}}`}</code>
                        <span>{VAR_HINTS[v] || '对应合同表单同名字段'}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="ctp-vars__msg">这份模板里没有找到 {'{{变量}}'} 标签 —— 生成完整合同时会直接附上模板原件。</p>
              )}
            </div>
            <div className="modal-actions">
              <button type="button" className="primary-btn" onClick={() => setTplVars(null)}>
                知道了
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* 合同模板库抽屉：同样挂在 ResizableLayout 外面（它只认前两个子元素当左右栏） */}
      <ContractTemplateDrawer
        open={templateDrawerOpen}
        onClose={() => setTemplateDrawerOpen(false)}
        authHeaders={authHeaders}
        onChanged={loadTemplates}
      />
    </>
  );
}
