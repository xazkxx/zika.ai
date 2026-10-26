// 自动提取自 App.jsx（selectedTab='quotation'）— 见 scripts/extract_pages.py
import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';
import ErpSearchSelect from '../components/ui/ErpSearchSelect.jsx';
import { exportWord } from '../lib/wordExport.js';
export default function QuotationPage({ ctx }) {
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

  // ---- 导出 Word（任务 E · 2026-10-19）----
  // 纯读导出，不改任何业务字段；失败只走全局提示，不打断正在填的报价单。
  const [wordBusy, setWordBusy] = useState(false);
  const exportQuotationWord = async (row) => {
    if (!row?.id || wordBusy) return;
    setWordBusy(true);
    try {
      const name = await exportWord(
        'quotation',
        row.id,
        `报价单-${row.quote_no || row.id}.docx`,
      );
      setNotice(`已导出 ${name}`);
    } catch (err) {
      setNotice(err.message || '导出失败');
    } finally {
      setWordBusy(false);
    }
  };

  return (

              <ResizableLayout>
                <section className="panel form-panel">
                  <div className="section-header">
                    <h2>新增销售报价单</h2>
                    <span className="status-badge">只报价 · 不动库存</span>
                  </div>

                  <form onSubmit={submitQuotation} className="erp-form">
                    <div className="form-row two-col">
                      <label>
                        客户
                        {/* 客户档案可能几百条：平铺下拉改可搜索。
                            地址/联系人/电话的联动仍由 handleQuotationChange('customer_id')
                            负责（App.jsx），适配器只是把裸值包回 event 形状。 */}
                        <ErpSearchSelect
                          options={customers}
                          value={String(quotationForm.customer_id ?? '')}
                          onChange={(value) => handleQuotationChange('customer_id')({ target: { value } })}
                          placeholder="搜索客户名称 / 编码"
                          emptyText="没有匹配的客户"
                          getOptionValue={(item) => String(item.id)}
                          getOptionLabel={(item) => `${item.name}（${item.code}）`}
                          getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                        />
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
                                                    <ErpSearchSelect
                            options={products}
                            value={String(line.product_id ?? '')}
                            onChange={handleQuotationItemChange(index, 'product_id')}
                            placeholder="搜索商品名称 / SKU / 助记码"
                            emptyText="没有匹配的商品"
                            getOptionValue={(item) => String(item.id)}
                            getOptionLabel={(item) => item.name}
                            getSearchText={(item) => [item.name, item.sku, item.mnemonic, item.code, item.bar_code].filter(Boolean).join(' ')}
                          />
                          {renderStockHint(line.product_id)}
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={line.quantity}
                            onChange={handleQuotationItemChange(index, 'quantity')}
                            placeholder="数量"
                          />
                          <input
                            type="number"
                            min="0"
                            step="any"
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
                                data-word-export="quotation"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  exportQuotationWord(row);
                                }}
                                disabled={wordBusy}
                              >
                                Word
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
              </ResizableLayout>
            
  );
}
