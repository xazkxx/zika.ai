// 自动提取自 App.jsx（selectedTab='inventory'）— 见 scripts/extract_pages.py
import { useMemo, useState } from 'react';

import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';
export default function InventoryPage({ ctx }) {
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

  /* ── 负库存口径（2026-10-22）───────────────────────────────────────────
     后端 `summary.total_quantity` 是把所有行的 quantity 直接相加 —— 负数也照加，
     于是"库存总量 -24,760"，看着像系统算错。
     这里拆开：在库合计只累加正数；负数单独计数，界面上红字告警。 */
  const stockAgg = useMemo(() => {
    const rows = stockData?.rows || [];
    let positive = 0;
    let negative = 0;
    let negativeCount = 0;
    let positiveValue = 0;
    rows.forEach((row) => {
      const q = Number(row.quantity) || 0;
      const price = Number(row.purchase_price) || 0;
      if (q > 0) {
        positive += q;
        // 金额也只在正库存上累加：负库存 × 单价是负数，会把"库存金额"打成负的
        positiveValue += q * price;
      } else if (q < 0) {
        negative += q;
        negativeCount += 1;
      }
    });
    return { positive, negative, negativeCount, positiveValue: Math.round(positiveValue * 100) / 100 };
  }, [stockData]);

  /** 库存流水只存 product_id，界面上要显示名字 —— 用商品档案建映射 */
  const productNameById = useMemo(() => {
    const map = new Map();
    (products || []).forEach((item) => map.set(Number(item.id), item.name || item.sku || `#${item.id}`));
    return map;
  }, [products]);

  /** 点开的那条流水（null = 抽屉关着） */
  const [ledgerRow, setLedgerRow] = useState(null);

  return (
    <>
              <ResizableLayout>
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
                                                <ErpSearchSelect
                          options={products}
                          value={String(inventoryForm.product_id ?? '')}
                          onChange={handleInventoryChange('product_id')}
                          placeholder="搜索商品名称 / SKU / 助记码"
                          emptyText="没有匹配的商品"
                          getOptionValue={(item) => String(item.id)}
                          getOptionLabel={(item) => item.name}
                          getSearchText={(item) => [item.name, item.sku, item.mnemonic, item.code, item.bar_code].filter(Boolean).join(' ')}
                        />
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
                      <input type="number" step="any" value={inventoryForm.unit_price} onChange={handleInventoryChange('unit_price')} />
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
                    {/* 2026-10-22：原来是 `summary.total_quantity` 直接求和 —— 把负库存
                        也当正数加进去，于是"库存总量 -24,760"，看着像系统算错了。
                        现在拆成两个口径：在库合计只看正数；负数单独计数、红字告警。 */}
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">在库合计</span>
                      <strong>{Number(stockAgg.positive).toLocaleString()}</strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">负库存商品</span>
                      <strong className={stockAgg.negativeCount ? 'num-negative' : undefined}>
                        {stockAgg.negativeCount}
                        {stockAgg.negativeCount ? `（${Number(stockAgg.negative).toLocaleString()}）` : ''}
                      </strong>
                    </div>
                    <div className="stock-kpi">
                      <span className="stock-kpi-label">库存金额（成本·正库存）</span>
                      <strong>¥{Number(stockAgg.positiveValue).toLocaleString()}</strong>
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

                  {stockAgg.negativeCount > 0 && (
                    <p className="stock-neg-note">
                      ⚠️ 有 <strong>{stockAgg.negativeCount}</strong> 个商品现存量是负数（合计{' '}
                      <strong>{Number(stockAgg.negative).toLocaleString()}</strong>）。
                      这类行多半是<strong>只有出库流水、没有对应的采购入库或期初库存</strong>
                      （历史导入的销售单就是这种情况）。请到「基础资料 → 商品期初库存」按实际盘点数补录，
                      或补一张采购入库单；补齐后数字会自动转正。
                    </p>
                  )}

                  {(stockData.rows || []).length === 0 ? (
                    <div className="empty-state">暂无库存数据，开一张采购单就会自动入库</div>
                  ) : (
                    <table className="data-table inv-stock-table">
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
                          <tr
                            key={`${row.warehouse_id}-${row.product_id}`}
                            className={row.quantity < 0 ? 'stock-row--neg' : undefined}
                          >
                            <td>{row.warehouse_name}</td>
                            <td title={row.product_name}>{row.product_name}</td>
                            <td>{row.standards || '—'}</td>
                            <td className={row.quantity < 0 ? 'stock-qty--neg' : undefined}>
                              {row.quantity}{row.unit ? ` ${row.unit}` : ''}
                              {row.quantity < 0 && (
                                <span
                                  className="stock-neg-badge"
                                  title="负库存：出库多于入库。常见原因——只有销售出库流水、没有采购入库或期初库存；也可能单据重复出库。"
                                >
                                  ⚠
                                </span>
                              )}
                            </td>
                            <td>{row.stock_lower ?? '—'}</td>
                            <td>{row.stock_upper ?? '—'}</td>
                            <td>
                              {/* 库存预警开关来自系统参数 stock.warn_enabled（登录时随权限一起下发） */}
                              {stockWarnEnabled
                                ? <span className={`stock-tag ${row.status}`}>{stockStatusLabel(row.status)}</span>
                                : <span className="cell-sub">—</span>}
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
                          <th>时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inventory.map((row) => (
                          <tr
                            key={row.id}
                            className="inv-ledger-row"
                            title="点击查看这条流水详情"
                            onClick={() => setLedgerRow(row)}
                          >
                            <td>{row.doc_no || '手工登记'}</td>
                            <td>{productNameById.get(Number(row.product_id)) || `#${row.product_id}`}</td>
                            <td>
                              <span className={row.transaction_type === 'inbound' ? 'stock-tag normal' : 'stock-tag shortage'}>
                                {row.transaction_type === 'inbound' ? '入库' : '出库'}
                              </span>
                            </td>
                            <td className={row.transaction_type === 'outbound' ? 'stock-qty--neg' : undefined}>
                              {row.quantity}
                            </td>
                            <td>¥{Number(row.unit_price || 0).toLocaleString()}</td>
                            <td className="cell-sub">{(row.created_at || '').replace('T', ' ').slice(0, 16) || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </ResizableLayout>

      {/* 库存流水详情抽屉（2026-10-22）：以前流水表只有 5 列干数据、点不动，
          连"这条出库对应哪张单"都看不出来（产品列显示的还是 product_id）。
          现在点任意一行都能看到完整信息，并能跳到对应的商品档案。 */}
      {ledgerRow && (
        <>
          <div className="inv-drawer__mask" onClick={() => setLedgerRow(null)} />
          <aside className="inv-drawer" role="dialog" aria-label="库存流水详情">
            <div className="inv-drawer__head">
              <h3>
                {ledgerRow.transaction_type === 'inbound' ? '入库' : '出库'}流水 #{ledgerRow.id}
              </h3>
              <button type="button" className="secondary-btn small-btn" onClick={() => setLedgerRow(null)}>
                关闭
              </button>
            </div>
            <div className="inv-drawer__body">
              <div className="inv-drawer__row">
                <span>商品</span>
                <span>{productNameById.get(Number(ledgerRow.product_id)) || `#${ledgerRow.product_id}`}</span>
              </div>
              <div className="inv-drawer__row">
                <span>数量</span>
                <span className={ledgerRow.transaction_type === 'outbound' ? 'stock-qty--neg' : undefined}>
                  {ledgerRow.transaction_type === 'outbound' ? '-' : '+'}
                  {Math.abs(Number(ledgerRow.quantity) || 0)}
                </span>
              </div>
              <div className="inv-drawer__row">
                <span>单价</span>
                <span>¥{Number(ledgerRow.unit_price || 0).toLocaleString()}</span>
              </div>
              <div className="inv-drawer__row">
                <span>来源单号</span>
                <span>{ledgerRow.doc_no || '手工登记'}</span>
              </div>
              <div className="inv-drawer__row">
                <span>关联类型</span>
                <span>{ledgerRow.related_type || '—'}</span>
              </div>
              <div className="inv-drawer__row">
                <span>发生时间</span>
                <span>{(ledgerRow.created_at || '').replace('T', ' ').slice(0, 19) || '—'}</span>
              </div>
              <div className="inv-drawer__row">
                <span>备注</span>
                <span>{ledgerRow.note || '—'}</span>
              </div>
              <p className="stock-neg-note" style={{ marginTop: 14 }}>
                流水是账的真相源，<strong>不提供直接改数量/单价</strong>（改了会与单据对不上）。
                要更正数量，请到对应单据做「反审核 → 改单 → 重新审核」；
                手工登记的收发货请到「库存管理 → 手工出入库」重开一条。
              </p>
            </div>
          </aside>
        </>
      )}
    </>
  );
}
