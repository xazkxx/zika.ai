// 自动提取自 App.jsx（selectedTab='invoices'）— 见 scripts/extract_pages.py
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';

export default function InvoicesPage({ ctx }) {
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

  // 2026-10-21：顶部三个统计块并进方向 Tab（省掉一行纵向空间）。
  // 全部 = 三类相加；进项/销项/待判定各自带张数与金额。
  const invoiceDirTabs = [
    {
      value: 'all',
      label: '全部',
      count: invoiceDirectionCounts.input.count + invoiceDirectionCounts.output.count + invoiceDirectionCounts.unknown.count,
      amount: invoiceDirectionCounts.input.amount + invoiceDirectionCounts.output.amount + invoiceDirectionCounts.unknown.amount,
    },
    { value: 'input', label: '进项', ...invoiceDirectionCounts.input },
    { value: 'output', label: '销项', ...invoiceDirectionCounts.output },
    { value: 'unknown', label: '待判定', ...invoiceDirectionCounts.unknown },
  ];

  return (

              <div className="system-stack">
                <section className="panel">
                  <div className="section-header">
                    <h2>发票管理</h2>
                    <div className="param-toolbar">
                      {/* 「一键重判」按钮 2026-10-21 按用户要求隐藏（后端 /invoices 重判接口保留，
                          需要时把这段 JSX 放回来即可）。
                      <button type="button" className="secondary-btn small-btn" onClick={redetectInvoices}>
                        一键重判
                      </button>
                      */}
                      <label className="upload-btn">
                        <input type="file" multiple accept=".png,.jpg,.jpeg,.pdf" onChange={handleInvoiceUpload} />
                        <span>上传发票</span>
                      </label>
                      {/* 右上角导出：勾选了导勾选的，没勾选导当前筛选的全部 */}
                      <div className="export-menu-wrap">
                        <button
                          type="button"
                          className="primary-btn small-btn"
                          onClick={() => setInvoiceExportOpen((prev) => !prev)}
                          aria-expanded={invoiceExportOpen}
                        >
                          导出 ▾
                        </button>
                        {invoiceExportOpen && (
                          <>
                            <div className="menu-scrim" onClick={() => setInvoiceExportOpen(false)} />
                            <div className="export-menu">
                              <div className="export-menu-head">
                                {selectedInvoiceIds.length > 0
                                  ? `导出已勾选的 ${selectedInvoiceIds.length} 张`
                                  : `导出当前筛选的 ${invoiceFiltered.length} 张`}
                              </div>
                              <button
                                type="button"
                                onClick={() => {
                                  setInvoiceExportOpen(false);
                                  exportInvoiceDetailExcel();
                                }}
                              >
                                <strong>Excel 明细表</strong>
                                <small>发票清单 + 逐条明细（单价 / 数量 / 金额）</small>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setInvoiceExportOpen(false);
                                  exportInvoiceDetailPdf();
                                }}
                              >
                                <strong>PDF 清单</strong>
                                <small>生成打印页，选「另存为 PDF」</small>
                              </button>
                              <button
                                type="button"
                                disabled={invoiceBusy === 'qr-zip'}
                                onClick={() => {
                                  setInvoiceExportOpen(false);
                                  exportInvoiceQrZip();
                                }}
                              >
                                <strong>二维码</strong>
                                <small>打包成 ZIP，按进销项分文件夹</small>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setInvoiceExportOpen(false);
                                  exportInvoiceSources();
                                }}
                              >
                                <strong>发票原件</strong>
                                <small>导出的就是上传留档的原始 PDF</small>
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <p className="settings-hint">
                    进销项按<strong>本公司税号</strong>与发票的销售方/购买方自动判定
                    （我方是购买方 = 进项，我方是销售方 = 销项）。判不出的显示「待判定」——
                    先在「系统设置 → 公司信息」填上本公司名称与税号，再点<strong>一键重判</strong>即可批量确定。
                    <br />
                    <strong>点发票号码</strong>看真实票面，「编辑」可逐字段改，
                    「二维码」下载的是<strong>原件里那一张</strong>（不是重画的）。
                  </p>

                  <div className="log-filters">
                    {/* 方向 Tab 自带张数与金额（原来的三块统计已并入这里） */}
                    <div className="inv-tabs" role="tablist" aria-label="按进销项筛选">
                      {invoiceDirTabs.map((tab) => {
                        const active = invoiceQuery.direction === tab.value;
                        return (
                          <button
                            key={tab.value}
                            type="button"
                            role="tab"
                            aria-selected={active}
                            data-inv-tab={tab.value}
                            className={`inv-tab${active ? ' is-active' : ''}`}
                            onClick={() => setInvoiceQuery((prev) => ({ ...prev, direction: tab.value }))}
                          >
                            <span className="inv-tab__label">{tab.label}</span>
                            <span className="inv-tab__num">{tab.count}</span>
                            {tab.amount > 0 && (
                              <span className="inv-tab__amt">¥{Number(tab.amount).toLocaleString()}</span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                    <input
                      value={invoiceQuery.keyword}
                      onChange={(event) => setInvoiceQuery((prev) => ({ ...prev, keyword: event.target.value }))}
                      placeholder="搜发票号码 / 抬头 / 税号 / 经手人"
                    />
                    {/* 进项专项筛选（2026-10-26）：财务日常就按"哪家供应商 / 认证到哪一步"找票。
                        供应商按**档案 id** 过滤（票面抬头是文本，同一家常有多个写法）；
                        认证状态下拉只对进项专票生效 —— 否则选「未认证」会把全库普票都列出来。 */}
                    <ErpSearchSelect
                      options={suppliers || []}
                      value={String(invoiceQuery.supplier_id ?? '')}
                      onChange={(value) => setInvoiceQuery((prev) => ({ ...prev, supplier_id: value }))}
                      placeholder="全部供应商"
                      emptyText="没有匹配的供应商"
                      getOptionValue={(o) => String(o.id)}
                      getOptionLabel={(o) => o.name || o.code || String(o.id)}
                      getSearchText={(o) => `${o.name || ''} ${o.code || ''} ${o.tax_no || ''}`}
                    />
                    <select
                      value={invoiceQuery.deduction_state || ''}
                      onChange={(event) =>
                        setInvoiceQuery((prev) => ({ ...prev, deduction_state: event.target.value }))
                      }
                      aria-label="按认证状态筛选"
                      title="认证 / 抵扣只对进项专票存在"
                    >
                      <option value="">全部认证状态</option>
                      <option value="uncertified">未认证</option>
                      <option value="certified">已认证待抵扣</option>
                      <option value="deducted">已抵扣</option>
                    </select>
                  </div>

                  {selectedInvoiceIds.length > 0 && (
                    <div className="batch-delete-bar">
                      <span>已勾选 {selectedInvoiceIds.length} 张发票</span>
                      {/* 批量定性（2026-10-24）：勾选的「待判定」发票一键进/销项，
                          判完自动跑匹配引擎。没有待判定的就隐藏，避免误点。 */}
                      {selectedInvoiceIds.some((id) => {
                        const row = invoiceItems.find((inv) => inv.id === id);
                        return row && row.direction === 'unknown';
                      }) && (
                        <>
                          <button
                            type="button"
                            className="secondary-btn"
                            disabled={invoiceBusy.startsWith('dir-')}
                            onClick={() => {
                              selectedInvoiceIds
                                .map((id) => invoiceItems.find((inv) => inv.id === id))
                                .filter((row) => row && row.direction === 'unknown')
                                .forEach((row) => handleSetInvoiceDirection(row, 'input'));
                            }}
                          >
                            判定进项（{selectedInvoiceIds.filter((id) => invoiceItems.find((inv) => inv.id === id)?.direction === 'unknown').length} 张待判定）
                          </button>
                          <button
                            type="button"
                            className="secondary-btn"
                            disabled={invoiceBusy.startsWith('dir-')}
                            onClick={() => {
                              selectedInvoiceIds
                                .map((id) => invoiceItems.find((inv) => inv.id === id))
                                .filter((row) => row && row.direction === 'unknown')
                                .forEach((row) => handleSetInvoiceDirection(row, 'output'));
                            }}
                          >
                            判定销项
                          </button>
                        </>
                      )}
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
                      <button type="button" className="link-btn" onClick={() => setSelectedInvoiceIds([])}>
                        取消勾选
                      </button>
                    </div>
                  )}

                  <div className="table-wrap">
                    <table className="data-table invoice-table">
                      {/* 2026-10-21：14 列必须给明确宽度。
                          之前靠 table-layout:fixed 平均分配 → 每列只有 90px，
                          日期/票号/抬头全被截断；而「操作」列又是 sticky right:0，
                          表宽只比容器宽 135px 时它会整块压在「二维码」列上，
                          看起来就是"表头表体串列、两个金额挤在一起"。
                          2026-10-24：新增「抵扣状态」列（专票认证抵扣）→ 15 列。 */}
                      <colgroup>
                        <col style={{ width: 40 }} />
                        <col style={{ width: 62 }} />
                        <col style={{ width: 108 }} />
                        <col style={{ width: 178 }} />
                        <col style={{ width: 76 }} />
                        <col style={{ width: 96 }} />
                        <col style={{ width: 196 }} />
                        <col style={{ width: 168 }} />
                        <col style={{ width: 196 }} />
                        <col style={{ width: 168 }} />
                        <col style={{ width: 76 }} />
                        <col style={{ width: 108 }} />
                        <col style={{ width: 108 }} />
                        <col style={{ width: 104 }} />
                        <col style={{ width: 148 }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th className="select-col">
                            <input
                              type="checkbox"
                              checked={invoicePageAllSelected}
                              ref={(node) => {
                                if (node) node.indeterminate = invoicePageSomeSelected && !invoicePageAllSelected;
                              }}
                              onChange={toggleSelectAllInvoices}
                              aria-label="全选本页发票"
                            />
                          </th>
                          <th className="num">序号</th>
                          <th>发票日期</th>
                          <th>发票号码</th>
                          <th>类型</th>
                          <th>认证 / 抵扣</th>
                          <th>购买方名称</th>
                          <th>购买方税号</th>
                          <th>销售方名称</th>
                          <th>销售方税号</th>
                          <th className="num">数量</th>
                          <th className="num">合计</th>
                          <th className="num">总价</th>
                          <th>二维码</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {invoicePaged.length === 0 && (
                          <tr>
                            <td colSpan="15" className="table-empty">
                              没有符合条件的发票。点右上角「上传发票」批量识别，或调整筛选条件。
                            </td>
                          </tr>
                        )}
                        {invoicePaged.map((item, index) => {
                          const expanded = expandedInvoiceIds.includes(item.id);
                          const lines = Array.isArray(item.items) ? item.items : [];
                          const quantity = lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0);
                          const lineAmount = lines.reduce((sum, line) => sum + Number(line.amount || 0), 0);
                          const exclTax =
                            item.excl_tax_amount != null ? Number(item.excl_tax_amount) : lineAmount;
                          const serial = (invoiceSafePage - 1) * invoicePageSize + index + 1;
                          return (
                            <Fragment key={item.id}>
                              <tr className={expanded ? 'invoice-row-expanded' : ''}>
                                <td className="select-col">
                                  <input
                                    type="checkbox"
                                    checked={selectedInvoiceIds.includes(item.id)}
                                    onChange={() => toggleInvoiceSelect(item.id)}
                                    aria-label={`勾选发票 ${item.invoice_no}`}
                                  />
                                </td>
                                <td className="num invoice-serial">
                                  <button
                                    type="button"
                                    className="caret-btn"
                                    onClick={() => toggleInvoiceExpand(item.id)}
                                    disabled={lines.length === 0}
                                    title={lines.length === 0 ? '这张发票没有解析出明细' : '展开 / 收起明细'}
                                    aria-label="展开明细"
                                  >
                                    {lines.length === 0 ? '·' : expanded ? '▾' : '▸'}
                                  </button>
                                  <span>{serial}</span>
                                </td>
                                <td className="nowrap">{item.date}</td>
                                <td>
                                  <button
                                    type="button"
                                    className="link-btn mono invoice-no-btn"
                                    onClick={() => openInvoicePreview(item)}
                                    title={item.has_source ? '查看真实发票' : '没有留档原件'}
                                  >
                                    {item.invoice_no}
                                  </button>
                                  <div className="cell-sub">
                                    <span className={`status-badge ${item.direction === 'input' ? 'ok' : item.direction === 'output' ? 'warn' : 'muted'}`}>
                                      {item.direction_label}
                                    </span>
                                    {item.invoice_flag === 'red' && <span className="status-badge danger">红字</span>}
                                    {/* OCR 认出来的进项票一律是「草稿」（后端 import 时落的）：
                                        票号/税号/金额认错一项就会传导到认证抵扣和申报，
                                        人工核对过再改成「已确认」是进项票的合规底线。 */}
                                    {item.status === '草稿' && <span className="status-badge warn">草稿待核对</span>}
                                  </div>
                                </td>
                                <td className="nowrap">{item.invoice_type || '未知'}</td>
                                <td className="nowrap">
                                  {/* 认证 / 抵扣（2026-10-26）：进项专票的三态。
                                      未认证 → 已认证待抵扣 → 已抵扣，销项票与普票没有这两步，显示 —。
                                      判"专票"用含不含"专票"两字，与条码里的「电子专票」写法解耦。 */}
                                  {String(item.invoice_type || '').includes('专票') ? (
                                    item.deducted ? (
                                      <span
                                        className="status-badge ok"
                                        title={item.deducted_at ? `抵扣时间：${new Date(item.deducted_at).toLocaleString('zh-CN')}` : undefined}
                                      >
                                        已抵扣
                                      </span>
                                    ) : item.certified ? (
                                      <span
                                        className="status-badge warn"
                                        title={item.certified_at ? `认证时间：${new Date(item.certified_at).toLocaleString('zh-CN')}` : undefined}
                                      >
                                        已认证待抵扣
                                      </span>
                                    ) : (
                                      <span className="status-badge muted">未认证</span>
                                    )
                                  ) : (
                                    '—'
                                  )}
                                </td>
                                <td className="cell-party">{item.buyer_name || '—'}</td>
                                <td className="cell-tax mono">{item.buyer_tax_no || '—'}</td>
                                <td className="cell-party">{item.seller_name || '—'}</td>
                                <td className="cell-tax mono">{item.seller_tax_no || '—'}</td>
                                <td className="num">{lines.length === 0 ? '—' : quantity}</td>
                                <td className="num">{money(exclTax)}</td>
                                <td className="num strong">{money(item.amount)}</td>
                                <td>
                                  <button
                                    type="button"
                                    className="link-btn"
                                    disabled={!item.has_source || invoiceBusy === `qr-${item.id}`}
                                    onClick={() => openInvoiceQr(item)}
                                  >
                                    {invoiceBusy === `qr-${item.id}` ? '读取中…' : '查看'}
                                  </button>
                                  <button
                                    type="button"
                                    className="link-btn"
                                    disabled={!item.has_source}
                                    onClick={() => downloadInvoiceQr(item)}
                                  >
                                    下载
                                  </button>
                                </td>
                                <td className="row-actions nowrap">
                                  {/* 状态流转（2026-10-24）：待判定的票给一键进/销项，
                                      判完自动跑匹配引擎；专票给标记/取消抵扣。 */}
                                  {item.direction === 'unknown' && (
                                    <>
                                      <button
                                        type="button"
                                        className="link-btn"
                                        disabled={invoiceBusy === `dir-${item.id}`}
                                        onClick={() => handleSetInvoiceDirection(item, 'input')}
                                      >
                                        {invoiceBusy === `dir-${item.id}` ? '判定中…' : '判定进项'}
                                      </button>
                                      <button
                                        type="button"
                                        className="link-btn"
                                        disabled={invoiceBusy === `dir-${item.id}`}
                                        onClick={() => handleSetInvoiceDirection(item, 'output')}
                                      >
                                        判定销项
                                      </button>
                                    </>
                                  )}
                                  {/* 认证 → 抵扣是一条单向链（2026-10-26）：
                                      已抵扣的票不再给「取消认证」入口 —— 后端也会 400，
                                      与其让人点一下看报错，不如干脆不提供这个按钮。 */}
                                  {String(item.invoice_type || '').includes('专票') && (
                                    <>
                                      {!item.deducted && (
                                        <button
                                          type="button"
                                          className="link-btn"
                                          disabled={invoiceBusy === `certify-${item.id}`}
                                          onClick={() => handleToggleCertified(item)}
                                        >
                                          {invoiceBusy === `certify-${item.id}`
                                            ? '处理中…'
                                            : item.certified
                                              ? '取消认证'
                                              : '认证'}
                                        </button>
                                      )}
                                      <button
                                        type="button"
                                        className="link-btn"
                                        disabled={invoiceBusy === `deduct-${item.id}`}
                                        onClick={() => handleToggleDeducted(item)}
                                      >
                                        {item.deducted ? '取消抵扣' : '标记抵扣'}
                                      </button>
                                    </>
                                  )}
                                  <button type="button" className="link-btn" onClick={() => openInvoicePreview(item)}>
                                    查看
                                  </button>
                                  <button type="button" className="link-btn" onClick={() => openInvoiceEdit(item)}>
                                    编辑
                                  </button>
                                  <button
                                    type="button"
                                    className="link-btn danger"
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
                              {expanded && (
                                <tr className="invoice-detail-row">
                                  <td colSpan="15">
                                    {lines.length === 0 ? (
                                      <div className="detail-empty">
                                        这张发票没有解析出明细（可能是票面上就没有明细行，或识别时未取到）。
                                      </div>
                                    ) : (
                                      <table className="invoice-line-table">
                                        <thead>
                                          <tr>
                                            <th>品名</th>
                                            <th>规格型号</th>
                                            <th>单位</th>
                                            <th className="num">单价</th>
                                            <th className="num">数量</th>
                                            <th className="num">金额</th>
                                            <th className="num">税率</th>
                                            <th className="num">税额</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {lines.map((line, lineIndex) => (
                                            <tr key={`${item.id}-line-${lineIndex}`}>
                                              <td>{line.item_name || '—'}</td>
                                              <td>{line.spec || '—'}</td>
                                              <td>{line.unit || '—'}</td>
                                              <td className="num">
                                                {line.unit_price != null
                                                  ? Number(line.unit_price).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
                                                  : '—'}
                                              </td>
                                              <td className="num">{line.quantity ?? '—'}</td>
                                              <td className="num">{money(line.amount)}</td>
                                              <td className="num">{line.tax_rate != null ? `${line.tax_rate}%` : '—'}</td>
                                              <td className="num">{money(line.tax_amount)}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    )}
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* 左下角全选 + 右下角分页 —— 用户明确要求全选框放在表格左下角 */}
                  <div className="invoice-table-footer">
                    <label className="select-all-box">
                      <input
                        type="checkbox"
                        checked={invoicePageAllSelected}
                        onChange={toggleSelectAllInvoices}
                      />
                      全选本页（{invoicePaged.length} 张）
                    </label>
                    <span className="footer-hint">
                      已勾选 {selectedInvoiceIds.length} 张 · 当前筛选共 {invoiceFiltered.length} 张
                    </span>
                    <div className="pager">
                      <label className="page-size">
                        每页
                        <select
                          value={invoicePageSize}
                          onChange={(event) => setInvoicePageSize(Number(event.target.value))}
                        >
                          {[10, 20, 50, 100].map((size) => (
                            <option key={size} value={size}>
                              {size}
                            </option>
                          ))}
                        </select>
                        条
                      </label>
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        disabled={invoiceSafePage <= 1}
                        onClick={() => setInvoicePage((prev) => Math.max(1, prev - 1))}
                      >
                        上一页
                      </button>
                      <span className="page-indicator">
                        {invoiceSafePage} / {invoicePageCount}
                      </span>
                      <button
                        type="button"
                        className="secondary-btn small-btn"
                        disabled={invoiceSafePage >= invoicePageCount}
                        onClick={() => setInvoicePage((prev) => Math.min(invoicePageCount, prev + 1))}
                      >
                        下一页
                      </button>
                    </div>
                  </div>
                </section>

<section className="panel">
                  <div className="section-header">
                    <h2>发票分析</h2>
                    <span className="status-badge">OCR 识别 · 财务关联 · 智能分析</span>
                  </div>

                  <div className="invoice-action-row">
                    {/* v1.78.0 单主按钮：原来三颗全是蓝的（智能分类 / 智能体 / 同步财务），
                        并排放在一起每颗都在喊"点我"，结果哪颗都不突出。
                        只留 AI 分析为主入口，另外两颗降为次级 —— 动作没删、位置没变。 */}
                    <button type="button" className="primary-btn small-btn" onClick={handleDeepSeekInvoiceAnalysis}>智能分类分析</button>
                    <button type="button" className="secondary-btn small-btn" onClick={handleInvoiceAgentAnalysis}>智能体分析</button>
                    <button type="button" className="secondary-btn small-btn" onClick={handleSyncInvoicesToFinance}>同步到财务</button>
                    <button type="button" className="secondary-btn small-btn" onClick={exportInvoiceReportXlsx}>导出勾选（旧版 Excel）</button>
                    <button type="button" className="secondary-btn small-btn" onClick={exportInvoiceReportHtml}>导出美观表格</button>
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

                        {/* 进项认证台账（2026-10-26）：三态分桶 + 本月已认证进项税额。
                            「本月已认证」按**认证时间**落月，与驾驶舱 KPI 是同一份代码
                            （`app/services/invoice_tax.py` 一处算法两处用），
                            所以这里的数和首页那张卡片永远一致。 */}
                        <div className="chart-card">
                          <div className="chart-card-title">进项专票认证台账</div>
                          {(() => {
                            const tax = invoiceAggregate.input_tax || {};
                            const month = tax.month || '';
                            return (
                              <div className="deduct-legend">
                                <div className="deduct-line">
                                  <i className="legend-dot" style={{ background: '#0ea5e9' }} />
                                  本月已认证进项税额 ¥{Number(tax.certified_this_month_tax || 0).toLocaleString()}
                                  （{tax.certified_this_month_count || 0} 张{month ? ` · ${month}` : ''}）
                                </div>
                                <div className="deduct-line">
                                  <i className="legend-dot" style={{ background: '#16a34a' }} />
                                  已抵扣 {tax.deducted_count || 0} 张 ¥{Number(tax.deducted_tax || 0).toLocaleString()}
                                </div>
                                <div className="deduct-line">
                                  <i className="legend-dot" style={{ background: '#f59e0b' }} />
                                  已认证待抵扣 {tax.certified_pending_count || 0} 张 ¥
                                  {Number(tax.certified_pending_tax || 0).toLocaleString()}
                                </div>
                                <div className="deduct-line red-text">
                                  <i className="legend-dot" style={{ background: '#dc2626' }} />
                                  未认证 {tax.uncertified_count || 0} 张 ¥{Number(tax.uncertified_tax || 0).toLocaleString()}
                                </div>
                              </div>
                            );
                          })()}
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
                    </>
                  ) : (
                    <div className="empty-state">还没有发票数据。先在上一栏「上传发票」导入原件。</div>
                  )}

                  {/* ——— 看真实发票：PDF 走 iframe、图片走 img ——— */}
                  {invoicePreview && (
                    <div className="modal-backdrop" onClick={closeInvoicePreview}>
                      <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>
                            发票原件 · <span className="mono">{invoicePreview.item.invoice_no}</span>
                          </h3>
                          <button type="button" className="close-btn" onClick={closeInvoicePreview}>×</button>
                        </div>
                        <div className="preview-meta">
                          <span>{invoicePreview.item.source_name || '原件'}</span>
                          <span>{(invoicePreview.size / 1024).toFixed(0)} KB</span>
                          <button
                            type="button"
                            className="secondary-btn small-btn"
                            onClick={() => downloadInvoiceSource(invoicePreview.item)}
                          >
                            下载原件
                          </button>
                        </div>
                        {String(invoicePreview.mime).startsWith('image/') ? (
                          <img className="invoice-preview-img" src={invoicePreview.url} alt={invoicePreview.item.invoice_no} />
                        ) : (
                          <iframe className="pdf-preview" src={invoicePreview.url} title="发票原件预览" />
                        )}
                        {!String(invoicePreview.mime).includes('pdf') && !String(invoicePreview.mime).startsWith('image/') && (
                          <p className="settings-hint">
                            这个格式浏览器不能直接预览，请点「下载原件」用本地程序打开。
                          </p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* ——— 二维码 ——— */}
                  {invoiceQr && (
                    <div className="modal-backdrop" onClick={() => setInvoiceQr(null)}>
                      <div className="modal-card modal-narrow" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>发票二维码</h3>
                          <button type="button" className="close-btn" onClick={() => setInvoiceQr(null)}>×</button>
                        </div>
                        <img className="invoice-qr-img" src={invoiceQr.dataUrl} alt="发票二维码" />
                        <p className="settings-hint center">
                          发票号码 <span className="mono">{invoiceQr.item.invoice_no}</span>
                          <br />
                          {invoiceQr.origin === 'embedded'
                            ? '取自原件里那一张二维码原图。'
                            : invoiceQr.origin === 'cropped'
                              ? '从原件图片上裁出来的二维码区域。'
                              : '原件上的二维码解不出来，这张是按其内容重画的。'}
                        </p>
                        <div className="modal-actions">
                          <button
                            type="button"
                            className="primary-btn small-btn"
                            onClick={() => downloadInvoiceQr(invoiceQr.item)}
                          >
                            下载二维码
                          </button>
                          <button type="button" className="secondary-btn small-btn" onClick={() => setInvoiceQr(null)}>
                            关闭
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ——— 编辑 ——— */}
                  {invoiceEditForm && (
                    <div className="modal-backdrop" onClick={() => setInvoiceEditForm(null)}>
                      <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>编辑发票</h3>
                          <button type="button" className="close-btn" onClick={() => setInvoiceEditForm(null)}>×</button>
                        </div>
                        <form className="invoice-edit-form" onSubmit={submitInvoiceEdit}>
                          <label>
                            <span>发票号码</span>
                            <input
                              value={invoiceEditForm.invoice_no}
                              required
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, invoice_no: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>开票日期</span>
                            <input
                              type="date"
                              value={invoiceEditForm.issue_date || ''}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, issue_date: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>发票类型</span>
                            <select
                              value={invoiceEditForm.invoice_type}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, invoice_type: event.target.value }))}
                            >
                              {['专票', '普票', '电子专票', '电子普票', '未知'].map((type) => (
                                <option key={type} value={type}>{type}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>进销项</span>
                            <select
                              value={invoiceEditForm.direction}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, direction: event.target.value }))}
                            >
                              <option value="input">进项</option>
                              <option value="output">销项</option>
                              <option value="unknown">待判定</option>
                            </select>
                          </label>
                          <label>
                            <span>红蓝字</span>
                            <select
                              value={invoiceEditForm.invoice_flag}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, invoice_flag: event.target.value }))}
                            >
                              <option value="blue">蓝字</option>
                              <option value="red">红字</option>
                            </select>
                          </label>
                          <label>
                            <span>开票方式</span>
                            <select
                              value={invoiceEditForm.issue_mode}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, issue_mode: event.target.value }))}
                            >
                              <option value="manual">手工开票</option>
                              <option value="api">对接开票</option>
                            </select>
                          </label>
                          <label className="span-2">
                            <span>购买方名称</span>
                            <input
                              value={invoiceEditForm.buyer_name}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, buyer_name: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>购买方税号</span>
                            <input
                              value={invoiceEditForm.buyer_tax_no}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, buyer_tax_no: event.target.value }))}
                            />
                          </label>
                          <label className="span-2">
                            <span>{invoiceEditForm.direction === 'input' ? '关联入库单（进项）' : '关联出库单（销项）'}</span>
                            {/* 方向决定这张票能挂哪张单据（2026-10-26）：
                                进项 → 采购入库单，销项 → 销售出库单。混在一个下拉里，
                                迟早有人把入库单挂到销项票上 —— 对账单照样算得出来，但是算错的。
                                待判定的票不给下拉：后端一律拒绝挂单，先定性再挂。 */}
                            {invoiceEditForm.direction === 'unknown' ? (
                              <input value="请先把进销项定性，再关联单据" readOnly />
                            ) : invoiceEditForm.direction === 'input' ? (
                              <ErpSearchSelect
                                options={(() => {
                                  const all = purchaseOrders || [];
                                  // 优先只给 doc_type=inbound 的入库单；本页还没拉到入库单时
                                  // 退回全部采购单，总比给一个空下拉、让人以为"没有可挂的单"好。
                                  const inbound = all.filter((o) => (o.doc_type || 'inbound') === 'inbound');
                                  return inbound.length > 0 ? inbound : all;
                                })()}
                                value={String(invoiceEditForm.related_order_id ?? '')}
                                onChange={(value) =>
                                  setInvoiceEditForm((prev) => ({ ...prev, related_order_id: value }))
                                }
                                placeholder="搜索入库单号 / 供应商；留空表示不关联"
                                emptyText="没有匹配的采购入库单"
                                getOptionValue={(o) => String(o.id)}
                                getOptionLabel={(o) =>
                                  `${o.order_no || o.id} · ${o.supplier_name || o.supplier_id || ''} · ¥${Number(
                                    o.total_amount || 0,
                                  ).toLocaleString()}`
                                }
                                getSearchText={(o) => `${o.order_no || ''} ${o.supplier_name || ''}`}
                              />
                            ) : (
                              <ErpSearchSelect
                                options={(salesOrders || []).filter((o) => (o.doc_type || 'outbound') === 'outbound')}
                                value={String(invoiceEditForm.related_order_id ?? '')}
                                onChange={(value) =>
                                  setInvoiceEditForm((prev) => ({ ...prev, related_order_id: value }))
                                }
                                placeholder="搜索出库单号 / 客户名；留空表示不关联"
                                emptyText="没有匹配的销售出库单"
                                getOptionValue={(o) => String(o.id)}
                                getOptionLabel={(o) =>
                                  `${o.order_no || o.id} · ${o.customer_name || o.customer_id || ''} · ¥${Number(
                                    o.total_amount || 0,
                                  ).toLocaleString()}`
                                }
                                getSearchText={(o) => `${o.order_no || ''} ${o.customer_name || ''}`}
                              />
                            )}
                          </label>
                          <label className="span-2">
                            <span>销售方名称</span>
                            <input
                              value={invoiceEditForm.seller_name}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, seller_name: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>销售方税号</span>
                            <input
                              value={invoiceEditForm.seller_tax_no}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, seller_tax_no: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>发票代码</span>
                            <input
                              value={invoiceEditForm.invoice_code}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, invoice_code: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>价税合计</span>
                            <input
                              type="number"
                              step="any"
                              value={invoiceEditForm.total_amount}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, total_amount: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>不含税额</span>
                            <input
                              type="number"
                              step="any"
                              value={invoiceEditForm.excl_tax_amount ?? ''}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, excl_tax_amount: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>税额</span>
                            <input
                              type="number"
                              step="any"
                              value={invoiceEditForm.tax_amount ?? ''}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, tax_amount: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>税率 %</span>
                            <input
                              type="number"
                              step="any"
                              list="lookup-tax-rate"
                              value={invoiceEditForm.tax_rate ?? ''}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, tax_rate: event.target.value }))}
                            />
                          </label>
                          {(() => {
                            // 金额三要素一致性实时提示（2026-10-27）：与后端校验同一套口径，
                            // 让用户在点「保存」之前就看到「不含税 + 税额 ≠ 价税合计」，
                            // 而不是点了保存才被 400 拦下。
                            const num = (v) => {
                              if (v === '' || v === null || v === undefined) return null;
                              const n = Number(v);
                              return Number.isNaN(n) ? null : n;
                            };
                            const total = num(invoiceEditForm.total_amount);
                            const excl = num(invoiceEditForm.excl_tax_amount);
                            const tax = num(invoiceEditForm.tax_amount);
                            if (excl === null || tax === null || total === null) return null;
                            const sum = excl + tax;
                            const diff = Math.abs(total - sum);
                            if (diff <= 0.01) {
                              return <p className="invoice-amount-hint is-ok">金额一致：不含税 + 税额 = {money(sum)}</p>;
                            }
                            return (
                              <p className="invoice-amount-hint is-warn" role="alert">
                                金额不一致：不含税 + 税额 = {money(sum)}，价税合计 = {money(total)}，相差 {money(diff)} 元 —— 保存会被拦截。
                              </p>
                            );
                          })()}
                          <label>
                            <span>分类</span>
                            <input
                              value={invoiceEditForm.category}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, category: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>状态</span>
                            <input
                              value={invoiceEditForm.status}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, status: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>经手人</span>
                            <input
                              value={invoiceEditForm.handler}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, handler: event.target.value }))}
                            />
                          </label>
                          <label className="checkbox-field">
                            <input
                              type="checkbox"
                              checked={invoiceEditForm.certified}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, certified: event.target.checked }))}
                            />
                            <span>进项专票已认证</span>
                          </label>
                          <label className="checkbox-field">
                            <input
                              type="checkbox"
                              checked={invoiceEditForm.deducted}
                              onChange={(event) => setInvoiceEditForm((prev) => ({ ...prev, deducted: event.target.checked }))}
                            />
                            <span>专票已抵扣</span>
                          </label>
                          <div className="form-actions span-2">
                            <button type="submit" className="primary-btn" disabled={invoiceBusy === 'edit'}>
                              {invoiceBusy === 'edit' ? '保存中…' : '保存'}
                            </button>
                            <button type="button" className="secondary-btn" onClick={() => setInvoiceEditForm(null)}>
                              取消
                            </button>
                          </div>
                        </form>
                      </div>
                    </div>
                  )}
                </section>
              </div>
            
  );
}
