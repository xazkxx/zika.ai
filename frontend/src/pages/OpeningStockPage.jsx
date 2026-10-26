// 自动提取自 App.jsx（selectedTab='opening-stock'）— 见 scripts/extract_pages.py
// 商品选择改可搜索下拉：库里 260+ 商品，原生 <select> 只能滚。
// 纯本地 filter（products 已在 ctx 里），不发请求。
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';
export default function OpeningStockPage({ ctx }) {
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
    openingEditingId,
    cancelOpeningEdit,
    saveOpeningSingle,
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

  /* 点「改这一项」时，表单在页面上方、表格在下方 —— 用户视线在表格上，
     数据填好了也看不见，于是反馈成"点了没反应"（2026-10-22 报障）。
     这里在进入编辑态时把表单滚进视野并闪一下，明确指向"改这里"。 */
  useEffect(() => {
    if (!openingEditingId) return undefined;
    const el = document.querySelector('[data-opening-form="1"]');
    if (!el) return undefined;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('is-editing');
    const timer = setTimeout(() => el.classList.remove('is-editing'), 1600);
    return () => clearTimeout(timer);
  }, [openingEditingId]);

  return (

              <div className="system-stack">
                <section className="panel">
                  <div className="section-header">
                    <h2>期初建账</h2>
                    <div className="system-tabs">
                      {OPENING_TABS.map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          className={`system-tab ${openingTab === tab.key ? 'active' : ''}`}
                          onClick={() => setOpeningTab(tab.key)}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <p className="settings-hint">
                    建账是<strong>一次性</strong>动作：把启用系统那一刻的库存与往来余额录进来，
                    之后所有数字都从这里往后滚。期初库存直接计入现存量，
                    所以已经开过单的仓库 × 商品再改期初，等于凭空挪动历史起点 —— 表格里会标出来。
                  </p>
                </section>

                {openingTab === 'stock' && (
                  <>
                    <section className="panel">
                      <div className="section-header">
                        <h2>库存期初</h2>
                        <div className="param-toolbar">
                          <button
                            type="button"
                            className="danger-outline-btn small-btn"
                            onClick={() => setOpeningClearAsk(true)}
                            disabled={systemBusy || openingSummary.lines === 0}
                          >
                            清空全部期初
                          </button>
                        </div>
                      </div>

                      <div className="stat-row">
                        <div className="stat-card">
                          <span className="stat-label">期初行数</span>
                          <strong className="stat-value">{openingSummary.lines || 0}</strong>
                        </div>
                        <div className="stat-card">
                          <span className="stat-label">期初总数量</span>
                          <strong className="stat-value">{openingSummary.total_quantity || 0}</strong>
                        </div>
                        <div className="stat-card">
                          <span className="stat-label">期初总金额</span>
                          <strong className="stat-value">{money(openingSummary.total_amount || 0)}</strong>
                        </div>
                        <div className="stat-card">
                          <span className="stat-label">已发生业务</span>
                          <strong className="stat-value">{openingSummary.business_lines || 0}</strong>
                        </div>
                      </div>

                      <div className="opening-entry" data-opening-form="1">
                        <label>
                          仓库
                          <select value={openingDraft.warehouse_id} onChange={handleOpeningDraftChange('warehouse_id')}>
                            <option value="">请选择</option>
                            {warehouses.map((wh) => (
                              <option key={wh.id} value={wh.id}>{wh.name}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          商品
                          {/* 原先显示成「商品名（SKU）」两段式；ErpSearchSelect 的元信息位
                              正好承担 SKU + 助记码，收起态仍只显示商品名，不再挤括号。 */}
                          <ErpSearchSelect
                            options={products}
                            value={String(openingDraft.product_id ?? '')}
                            onChange={handleOpeningDraftChange('product_id')}
                            placeholder="搜索商品名称 / SKU / 助记码"
                          />
                        </label>
                        <label>
                          期初数量
                          <input type="number" value={openingDraft.quantity} onChange={handleOpeningDraftChange('quantity')} placeholder="0" />
                        </label>
                        <label>
                          成本单价
                          <input type="number" value={openingDraft.unit_price} onChange={handleOpeningDraftChange('unit_price')} placeholder="0" />
                        </label>
                        <label>
                          备注
                          <input value={openingDraft.note} onChange={handleOpeningDraftChange('note')} placeholder="选填" />
                        </label>
                        {openingEditingId ? (
                          <>
                            {/* 编辑态：直接按 (仓库×商品) upsert 落库，不用再走"加入清单→保存全部"两步 */}
                            <button
                              type="button"
                              className="primary-btn"
                              data-opening-save-edit="1"
                              onClick={saveOpeningSingle}
                              disabled={systemBusy}
                            >
                              保存修改
                            </button>
                            <button type="button" className="secondary-btn" onClick={cancelOpeningEdit}>
                              取消编辑
                            </button>
                          </>
                        ) : (
                          <button type="button" className="secondary-btn" onClick={addOpeningDraftRow}>加入清单</button>
                        )}
                      </div>

                      <div className="table-wrap">
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>仓库</th>
                              <th>商品</th>
                              <th>数量</th>
                              <th>单价</th>
                              <th>金额</th>
                              <th>备注</th>
                              <th>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {openingDraftRows.length === 0 && (
                              <tr><td colSpan="7" className="table-empty">待保存清单为空：在上面选好仓库与商品，点「加入清单」。</td></tr>
                            )}
                            {openingDraftRows.map((row, index) => {
                              const wh = warehouses.find((w) => String(w.id) === row.warehouse_id);
                              const pd = products.find((p) => String(p.id) === row.product_id);
                              return (
                                <tr key={`${row.warehouse_id}-${row.product_id}`}>
                                  <td>{wh ? wh.name : row.warehouse_id}</td>
                                  <td>{pd ? `${pd.name}（${pd.sku}）` : row.product_id}</td>
                                  <td className="num">{row.quantity}</td>
                                  <td className="num">{row.unit_price}</td>
                                  <td className="num">{money(draftAmount(row))}</td>
                                  <td className="cell-sub">{row.note || '—'}</td>
                                  <td className="row-actions">
                                    <button type="button" className="link-btn danger" onClick={() => removeOpeningDraftRow(index)}>移除</button>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>

                      <div className="form-actions">
                        <button type="button" className="primary-btn" onClick={saveOpeningStock} disabled={systemBusy || openingDraftRows.length === 0}>
                          保存全部（{openingDraftRows.length} 项）
                        </button>
                        <button type="button" className="secondary-btn" onClick={() => setOpeningDraftRows([])} disabled={openingDraftRows.length === 0}>
                          清空清单
                        </button>
                      </div>
                    </section>

                    <section className="panel table-panel">
                      <div className="section-header">
                        <h2>已建账期初</h2>
                        <div className="param-toolbar">
                          <span className="status-badge">共 {openingRows.length} 项</span>
                          <button type="button" className="secondary-btn small-btn" onClick={refreshOpeningStock}>重新载入</button>
                        </div>
                      </div>

                      <div className="table-wrap">
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>仓库</th>
                              <th>商品</th>
                              <th>期初数量</th>
                              <th>成本单价</th>
                              <th>期初金额</th>
                              <th>现存量</th>
                              <th>状态</th>
                              <th>备注</th>
                              <th>操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {openingRows.length === 0 && (
                              <tr><td colSpan="9" className="table-empty">还没有期初数据。也可以到「导入导出」页用「期初库存」类别批量导入。</td></tr>
                            )}
                            {openingRows.map((row) => (
                              <tr key={row.id}>
                                <td>{row.warehouse_name}</td>
                                <td>
                                  <div className="cell-stack">
                                    <span>{row.product_name}</span>
                                    <span className="cell-sub mono">{row.sku}</span>
                                  </div>
                                </td>
                                <td className="num">{row.quantity}</td>
                                <td className="num">{plain(row.unit_price)}</td>
                                <td className="num">{money(row.amount)}</td>
                                <td className="num">{row.current_stock}</td>
                                <td>
                                  {row.has_business
                                    ? <span className="status-badge warn" title="该仓库×商品已经发生过出入库，改期初会让现存量跟着跳">已发生业务</span>
                                    : <span className="status-badge ok">未发生业务</span>}
                                </td>
                                <td className="cell-sub">{row.note || '—'}</td>
                                <td className="row-actions">
                                  <button type="button" className="link-btn" onClick={() => loadOpeningRowIntoDraft(row)}>改这一项</button>
                                  <button
                                    type="button"
                                    className="link-btn danger"
                                    onClick={() => setConfirmDelete({
                                      id: row.id,
                                      endpoint: `/opening-stock/${row.id}`,
                                      label: `${row.warehouse_name} / ${row.product_name} 的期初`,
                                      kind: 'opening-line',
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
                    </section>
                  </>
                )}

                {(openingTab === 'receivable' || openingTab === 'payable') && (
                  <section className="panel table-panel">
                    <div className="section-header">
                      <h2>{openingTab === 'receivable' ? '期初应收' : '期初应付'}</h2>
                      <div className="param-toolbar">
                        <span className="status-badge">
                          合计 {money(openingTab === 'receivable'
                            ? (openingBalances.summary?.receivable_total || 0)
                            : (openingBalances.summary?.payable_total || 0))}
                        </span>
                        <button type="button" className="primary-btn small-btn" onClick={saveOpeningBalances} disabled={systemBusy}>
                          保存全部
                        </button>
                        <button type="button" className="secondary-btn small-btn" onClick={refreshOpeningBalances}>重新载入</button>
                      </div>
                    </div>

                    <p className="settings-hint">
                      这里只改<strong>期初金额</strong>，不动档案的其它字段。允许填负数 ——
                      {openingTab === 'receivable' ? '客户的预收款，期初就是负的。' : '给供应商的预付款，期初就是负的。'}
                      改动只影响「当前余额」的起点，已经发生的单据金额不动。
                    </p>

                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>编码</th>
                            <th>名称</th>
                            <th>{openingTab === 'receivable' ? '期初应收' : '期初应付'}</th>
                            <th>期初欠票</th>
                            <th>期间发生额</th>
                            <th>当前余额</th>
                          </tr>
                        </thead>
                        <tbody>
                          {((openingTab === 'receivable' ? openingBalances.receivables : openingBalances.payables) || []).length === 0 && (
                            <tr><td colSpan="6" className="table-empty">还没有{openingTab === 'receivable' ? '客户' : '供应商'}档案。</td></tr>
                          )}
                          {((openingTab === 'receivable' ? openingBalances.receivables : openingBalances.payables) || []).map((row) => {
                            const entity = openingTab === 'receivable' ? 'customer' : 'supplier';
                            const draft = balanceDraft[`${entity}-${row.id}`] || {};
                            return (
                              <tr key={row.id}>
                                <td className="mono">{row.code}</td>
                                <td>{row.name}</td>
                                <td>
                                  <input
                                    className="cell-input"
                                    type="number"
                                    value={draft.init_amount ?? ''}
                                    onChange={handleBalanceDraftChange(entity, row.id, 'init_amount')}
                                  />
                                </td>
                                <td>
                                  <input
                                    className="cell-input"
                                    type="number"
                                    value={draft.init_invoice_debt ?? ''}
                                    onChange={handleBalanceDraftChange(entity, row.id, 'init_invoice_debt')}
                                  />
                                </td>
                                <td className="num cell-sub">{plain(row.occurred_amount)}</td>
                                <td className="num">{money(row.current_balance)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}
              </div>
            
  );
}
