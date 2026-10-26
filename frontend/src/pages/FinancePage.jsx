// 自动提取自 App.jsx（selectedTab='finance'）— 见 scripts/extract_pages.py
import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';
// 需求 2（2026-10-18）：财务流水的只读详情抽屉。挂在 ResizableLayout **外面** ——
// 它一旦成为布局的第 3 个子元素，Children.toArray 会把可拖拽分栏降级成普通网格。
import FinanceFlowDrawer from '../components/finance/FinanceFlowDrawer.jsx';
import ReverseFlowDialog from '../components/finance/ReverseFlowDialog.jsx';
export default function FinancePage({ ctx }) {
  const {
    ADJUSTMENT_STATUS_LABEL,
    ADJUST_TYPE_DIRECTION,
    ADJUST_TYPE_LABEL,
    API_BASE,
    BANK_ACCOUNT_TYPE_LABEL,
    CONTRACT_STATUS_LABEL,
    DOC_STATUS_LABELS,
    DOC_TYPE_LABEL,
    financeTypeLabel,
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

  /** 正在查看的流水（null = 抽屉关闭）。存整行快照，不存 id 再回头查 ——
      列表只有最近 8 条，翻页/刷新都会让 id 查不到，快照最稳。 */
  const [flowDetail, setFlowDetail] = useState(null);

  /** 红冲：要冲的那笔流水（null = 弹窗关闭）+ 提交态 + 失败原因 + 成功提示 */
  const [reverseTarget, setReverseTarget] = useState(null);
  const [reverseBusy, setReverseBusy] = useState(false);
  const [reverseError, setReverseError] = useState('');
  const [reverseNotice, setReverseNotice] = useState('');

  /**
   * 提交红冲。
   *
   * 三条关键处理：
   *  ① 只接受 receipt / payment（按钮本来也只在两类上出现，这里是第二道）；
   *  ② 409 的 detail 可能是**对象**（already_reversed / reversal_of_reversal），
   *     直接 `detail` 当字符串用会渲染成 [object Object] → 必须按结构取 message；
   *  ③ 成功后**重新拉一遍流水**：红冲会新增一条红字行、并改掉原行的冲销状态，
   *     只改本地 state 会出现"标签变了但列表顺序/合计没变"的错位。
   */
  const submitReverse = async (reason) => {
    if (!reverseTarget || reverseBusy) return;
    const type = reverseTarget.transaction_type;
    if (type !== 'receipt' && type !== 'payment') {
      setReverseError('只有收款 / 付款可以红冲');
      return;
    }
    setReverseBusy(true);
    setReverseError('');
    setReverseNotice('');
    try {
      const response = await fetch(`${API_BASE}/finance/${type}/${reverseTarget.id}/reverse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ reason: reason || '' }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        // 404 只有一个现实成因：8010 那个常驻进程还没重启（后端没有 --reload）。
        // 不把这句话说出来，用户只会看到"红冲失败"，根本想不到要去重启。
        if (response.status === 404) {
          throw new Error('红冲接口未生效：后端进程还是旧版本，请重启「启动ERP.bat」后再试');
        }
        const detail = data?.detail;
        const message =
          (typeof detail === 'string' && detail) ||
          (detail && typeof detail === 'object' && detail.message) ||
          '红冲失败，请稍后重试';
        throw new Error(message);
      }
      const reversalId = data?.reversal?.id;
      const orderInfo = data?.order;
      const orderText = orderInfo
        ? `；单据 #${orderInfo.id} 的已收/已付回退至 ¥${Number(orderInfo.amount || 0).toLocaleString('zh-CN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}`
        : '';
      setReverseTarget(null);
      setReverseNotice(`已红冲流水 #${reverseTarget.id}，生成红字流水 #${reversalId}${orderText}`);
      if (typeof refreshFinance === 'function') await refreshFinance();
    } catch (err) {
      setReverseError(err.message || '红冲失败');
    } finally {
      setReverseBusy(false);
    }
  };

  // 进入财务流水页先拉一次最新账：这个列表在 App 里只有登录时加载过一次，
  // 不刷就会出现「刚登记完收款，切到财务流水却看不到」。（订单页登记收付款后即刷新）
  useEffect(() => {
    if (typeof refreshFinance === 'function') refreshFinance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // ⚠️ 根节点必须是 Fragment：抽屉要挂在 ResizableLayout **外面**（在里面会变成第 3 个
  //    子元素，Children.toArray 一数 3 就把可拖拽分栏降级成普通网格）—— 而 return 只能有一个根。
  return (
            <>

              <ResizableLayout>
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
                        <input type="number" step="any" value={financeForm.amount} onChange={handleFinanceChange('amount')} required />
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
                        {/* 档案可能几百条：平铺下拉改可搜索 */}
                        <ErpSearchSelect
                          options={customers}
                          value={String(printParty.customer_id ?? '')}
                          onChange={(value) => setPrintParty((prev) => ({ ...prev, customer_id: value }))}
                          placeholder="搜索客户名称 / 编码"
                          emptyText="没有匹配的客户"
                          getOptionValue={(item) => String(item.id)}
                          getOptionLabel={(item) => `${item.name}（${item.code}）`}
                          getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                        />
                      </label>
                      <label>
                        供应商（对账单）
                        <ErpSearchSelect
                          options={suppliers}
                          value={String(printParty.supplier_id ?? '')}
                          onChange={(value) => setPrintParty((prev) => ({ ...prev, supplier_id: value }))}
                          placeholder="搜索供应商名称 / 编码"
                          emptyText="没有匹配的供应商"
                          getOptionValue={(item) => String(item.id)}
                          getOptionLabel={(item) => `${item.name}（${item.code}）`}
                          getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                        />
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

                  {reverseNotice ? (
                    <div className="reverse-notice" role="status" data-reverse-notice>
                      {reverseNotice}
                    </div>
                  ) : null}

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
                          <th style={{ width: 84 }}>状态</th>
                          <th style={{ width: 108, textAlign: 'right' }}>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {/* 行可点 + 行内「详情」按钮：两种习惯都照顾到。
                            ⭐ 按钮要 stopPropagation，否则点它会同时触发行的 onClick（开两次） */}
                        {finance.slice(0, 8).map((row) => {
                          const isReversal = Boolean(row.reversal_of_id);
                          const isReversed = Boolean(row.is_reversed);
                          // 可红冲 = 收款/付款 + 没被冲过 + 本身不是红字行 + 金额为正
                          const canReverse =
                            (row.transaction_type === 'receipt' || row.transaction_type === 'payment') &&
                            !isReversed &&
                            !isReversal &&
                            Number(row.amount || 0) > 0;
                          return (
                            <tr
                              key={row.id}
                              onClick={() => setFlowDetail(row)}
                              style={{ cursor: 'pointer' }}
                              title="点击查看这笔流水的详情"
                              data-flow-row={row.id}
                              data-flow-reversed={isReversed ? '1' : undefined}
                            >
                              <td>{financeTypeLabel(row.transaction_type)}</td>
                              <td className={Number(row.amount || 0) < 0 ? 'flow-amount--red' : undefined}>
                                ¥{Number(row.amount || 0).toLocaleString()}
                              </td>
                              <td>{row.currency}</td>
                              <td>{row.note || '—'}</td>
                              <td>
                                {isReversed ? (
                                  <span className="flow-tag flow-tag--reversed" data-flow-tag="reversed">
                                    已冲销
                                  </span>
                                ) : isReversal ? (
                                  <span className="flow-tag flow-tag--reversal" data-flow-tag="reversal">
                                    红冲
                                  </span>
                                ) : (
                                  <span className="flow-tag flow-tag--plain" data-flow-tag="normal">
                                    —
                                  </span>
                                )}
                              </td>
                              <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                <button
                                  type="button"
                                  className="link-btn"
                                  data-flow-detail={row.id}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setFlowDetail(row);
                                  }}
                                >
                                  详情
                                </button>
                                {canReverse ? (
                                  <button
                                    type="button"
                                    className="link-btn link-btn--danger"
                                    data-flow-reverse={row.id}
                                    style={{ marginLeft: 8 }}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      setReverseError('');
                                      setReverseNotice('');
                                      setReverseTarget(row);
                                    }}
                                  >
                                    红冲
                                  </button>
                                ) : null}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                  {finance.length > 8 && (
                    <div className="table-hint">共 {finance.length} 条，仅显示最近 8 条</div>
                  )}
                </section>
              </ResizableLayout>

              {/* 只读详情抽屉：挂在布局外面（见文件头的说明），open 由 flowDetail 决定 */}
              <FinanceFlowDrawer
                open={Boolean(flowDetail)}
                flow={flowDetail}
                customers={customers}
                suppliers={suppliers}
                bankAccounts={bankAccounts}
                typeLabel={financeTypeLabel}
                docTypeLabel={(key) => DOC_TYPE_LABEL[key] || key}
                onClose={() => setFlowDetail(null)}
              />

              {/* 红冲确认弹窗：同样挂在 ResizableLayout 之外 ——
                  分栏只认"恰好 2 个子元素"，多挂一个会把它静默降级成普通网格 */}
              <ReverseFlowDialog
                open={Boolean(reverseTarget)}
                flow={reverseTarget}
                typeLabel={financeTypeLabel}
                docTypeLabel={(key) => DOC_TYPE_LABEL[key] || key}
                busy={reverseBusy}
                error={reverseError}
                onCancel={() => {
                  if (reverseBusy) return;
                  setReverseTarget(null);
                  setReverseError('');
                }}
                onConfirm={submitReverse}
              />
            </>
  );
}
