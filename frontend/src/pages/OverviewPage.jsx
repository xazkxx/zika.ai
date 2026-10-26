import SmartCommandBar from '../components/agent/SmartCommandBar.jsx';
// 自动提取自 App.jsx（selectedTab='overview'）— 见 scripts/extract_pages.py
export default function OverviewPage({ ctx }) {
  const {
    ADJUSTMENT_STATUS_LABEL,
    agentGoto,
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
  return (

              <>
                {/* 🤖 智能指令搜索框（2026-10-23）：工作台最顶部。
                    结果以悬浮卡片呈现，不替代「购销合同」「增强对账单」页面 ——
                    按钮只会"预览 / 导出 / 跳转并预填筛选"。 */}
                <SmartCommandBar apiBase={API_BASE} authHeaders={authHeaders} onGoto={agentGoto} />

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

                {/* KPI 卡片组：运营指标（对齐参考图的运营展板，不再是档案统计） */}
                <section className="kpi-grid">
                  {(() => {
                    const kpiMeta = {
                      '销售额': { icon: '💰', tone: 'blue', sub: '累计销售额', target: 'sales' },
                      '采购额': { icon: '🛒', tone: 'cyan', sub: '累计采购额', target: 'purchase' },
                      '净利润': { icon: '📈', tone: 'teal', sub: '销售 − 采购', target: 'reports' },
                      '生产订单': { icon: '🏭', tone: 'green', sub: '在产订单', target: 'production' },
                      '库存预警': { icon: '⚠️', tone: 'sky', sub: '需补货 / 关注', target: 'inventory' },
                      '付款提醒': { icon: '💳', tone: 'emerald', sub: '待跟进付款', target: 'payable' },
                      '商品数': { icon: '📦', tone: 'blue', sub: '商品档案', target: 'products' },
                      '客户数': { icon: '👥', tone: 'cyan', sub: '客户档案', target: 'customers' },
                      '供应商数': { icon: '🚚', tone: 'teal', sub: '供应商档案', target: 'suppliers' },
                    };
                    const kpis = executiveDashboard.kpis?.length
                      ? executiveDashboard.kpis
                      : [
                          { label: '销售额', value: Number(summary?.sales_total ?? 0), unit: 'CNY' },
                          { label: '采购额', value: Number(summary?.purchase_total ?? 0), unit: 'CNY' },
                          { label: '净利润', value: Number((summary?.sales_total ?? 0) - (summary?.purchase_total ?? 0)), unit: 'CNY' },
                          { label: '商品数', value: Number(summary?.products ?? 0), unit: 'items' },
                          { label: '客户数', value: Number(summary?.customers ?? 0), unit: 'items' },
                          { label: '供应商数', value: Number(summary?.suppliers ?? 0), unit: 'items' },
                        ];
                    return kpis.map((kpi) => {
                      const meta = kpiMeta[kpi.label] || { icon: '📊', tone: 'blue', sub: '' };
                      const raw = Number(kpi.value || 0);
                      const value = kpi.unit === 'CNY' ? `¥${raw.toLocaleString()}` : raw.toLocaleString();
                      return (
                        <button
                          type="button"
                          className={`kpi-card kpi-${meta.tone}`}
                          key={kpi.label}
                          onClick={() => { if (meta.target) setSelectedTab(meta.target); }}
                          title={meta.target ? `打开「${kpi.label}」` : undefined}
                        >
                          <div className="kpi-icon">{meta.icon}</div>
                          <div className="kpi-meta">
                            <span className="kpi-label">{kpi.label}</span>
                            <strong className="kpi-value">{value}</strong>
                            <span className="kpi-sub">{meta.sub}</span>
                          </div>
                        </button>
                      );
                    });
                  })()}
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
                                  <stop offset="0%" stopColor="#14b8a6" stopOpacity="0.28" />
                                  <stop offset="100%" stopColor="#14b8a6" stopOpacity="0" />
                                </linearGradient>
                                <linearGradient id="trendLine" x1="0" y1="0" x2="1" y2="0">
                                  <stop offset="0%" stopColor="#2563eb" />
                                  <stop offset="100%" stopColor="#14b8a6" />
                                </linearGradient>
                              </defs>
                              <polygon points={areaPoints} fill="url(#trendArea)" />
                              <polyline points={points} fill="none" stroke="url(#trendLine)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                              {values.map((v, i) => {
                                const x = (i / Math.max(values.length - 1, 1)) * 100;
                                const y = 100 - ((v - minValue) / range) * 92 - 4;
                                return <circle key={i} cx={x} cy={y} r="1.6" fill="#14b8a6" vectorEffect="non-scaling-stroke" />;
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

                {/* 常用报表快捷入口（对齐参考图的报表导航） */}
                <section className="panel dash-panel">
                  <div className="section-header">
                    <h2>常用报表</h2>
                    <button type="button" className="link-btn" onClick={() => setSelectedTab('reports')}>报表中心 →</button>
                  </div>
                  <div className="quick-report-grid">
                    {[
                      { label: '销售订单执行表', icon: '🧾', tone: 'blue' },
                      { label: '采购订单执行表', icon: '🛒', tone: 'cyan' },
                      { label: '库存余额表', icon: '📦', tone: 'teal' },
                      { label: '应收应付明细表', icon: '💰', tone: 'green' },
                      { label: '生产工单进度表', icon: '🏭', tone: 'sky' },
                      { label: '经营日报', icon: '📊', tone: 'emerald' },
                    ].map((report) => (
                      <button
                        key={report.label}
                        type="button"
                        className={`quick-report-card qr-${report.tone}`}
                        onClick={() => setSelectedTab('reports')}
                      >
                        <span className="qr-icon">{report.icon}</span>
                        <span className="qr-label">{report.label}</span>
                      </button>
                    ))}
                  </div>
                </section>

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
            
  );
}
