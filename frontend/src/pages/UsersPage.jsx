// 自动提取自 App.jsx（selectedTab='users'）— 见 scripts/extract_pages.py
export default function UsersPage({ ctx }) {
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
  return (

              <div className="system-center">
                <aside className="panel dept-panel">
                  <div className="section-header">
                    <h2>组织机构</h2>
                    <span className="status-badge">{departmentOptions.length} 个部门</span>
                  </div>
                  <p className="settings-hint">
                    部门是树形结构，用户挂在部门下。点部门名筛选右侧用户；「新增下级」会在当前选中部门下建子部门。
                  </p>

                  <div className="dept-tree">
                    {departmentOptions.length === 0 && <div className="empty-state">暂无部门数据。</div>}
                    {departmentOptions.map((node) => (
                      <div
                        key={node.id}
                        className={`dept-node ${String(node.id) === selectedDeptId ? 'active' : ''} ${node.is_active ? '' : 'inactive'}`}
                        style={{ paddingLeft: `${8 + node.depth * 16}px` }}
                      >
                        <button
                          type="button"
                          className="dept-node-btn"
                          onClick={() => {
                            setSelectedDeptId(String(node.id));
                            setSystemUserDeptFilter(String(node.id));
                            refreshSystemUsers({ department_id: String(node.id) });
                          }}
                        >
                          <span className="dept-name">{node.name}</span>
                          <span className="dept-count">{node.user_count}</span>
                        </button>
                        <span className="dept-actions">
                          <button type="button" className="link-btn" onClick={() => startEditDepartment(node)}>改</button>
                          <button
                            type="button"
                            className="link-btn danger"
                            onClick={() => setConfirmDelete({
                              id: node.id,
                              endpoint: `/system/departments/${node.id}`,
                              label: `部门「${node.name}」`,
                              kind: 'system-dept',
                            })}
                          >
                            删
                          </button>
                        </span>
                      </div>
                    ))}
                  </div>

                  <form className="erp-form dept-form" onSubmit={submitDepartment}>
                    <div className="form-title">
                      {departmentForm.id ? '编辑部门' : '新增部门'}
                      {departmentForm.parent_id && (
                        <span className="form-subtitle">
                          上级：{departmentOptions.find((item) => String(item.id) === departmentForm.parent_id)?.name || '—'}
                        </span>
                      )}
                    </div>
                    <div className="form-row two-col">
                      <label>
                        部门名称
                        <input value={departmentForm.name} onChange={handleDepartmentChange('name')} required />
                      </label>
                      <label>
                        部门编码
                        <input
                          value={departmentForm.code}
                          onChange={handleDepartmentChange('code')}
                          placeholder={departmentForm.id ? '' : '留空自动生成'}
                          disabled={Boolean(departmentForm.id)}
                        />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        上级部门
                        <select value={departmentForm.parent_id} onChange={handleDepartmentChange('parent_id')}>
                          <option value="">（顶层）</option>
                          {departmentOptions
                            .filter((item) => String(item.id) !== departmentForm.id)
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {'　'.repeat(item.depth)}{item.name}
                              </option>
                            ))}
                        </select>
                      </label>
                      <label>
                        负责人
                        <input value={departmentForm.leader} onChange={handleDepartmentChange('leader')} />
                      </label>
                    </div>
                    <div className="form-row two-col">
                      <label>
                        联系电话
                        <input value={departmentForm.phone} onChange={handleDepartmentChange('phone')} />
                      </label>
                      <label>
                        排序号
                        <input type="number" value={departmentForm.sort_order} onChange={handleDepartmentChange('sort_order')} />
                      </label>
                    </div>
                    <label>
                      备注
                      <input value={departmentForm.note} onChange={handleDepartmentChange('note')} />
                    </label>
                    <label className="checkbox-row">
                      <input type="checkbox" checked={departmentForm.is_active} onChange={handleDepartmentChange('is_active')} />
                      启用
                    </label>
                    <div className="form-actions">
                      <button className="primary-btn" type="submit" disabled={systemBusy}>保存部门</button>
                      <button type="button" className="secondary-btn" onClick={() => resetDepartmentForm(null)}>清空</button>
                    </div>
                  </form>
                </aside>

                <div className="system-body">
                  <div className="system-tabs">
                    {SYSTEM_TABS.map((tab) => (
                      <button
                        key={tab.key}
                        type="button"
                        className={`system-tab ${systemTab === tab.key ? 'active' : ''}`}
                        onClick={() => setSystemTab(tab.key)}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {systemTab === 'users' && (
                    <div className="system-stack">
                      <section className="panel form-panel">
                        <div className="section-header">
                          <h2>{systemUserForm.id ? `编辑用户：${systemUserForm.username}` : '新增用户'}</h2>
                          <span className="status-badge">共 {systemUsers.length} 人</span>
                        </div>

                        <form onSubmit={submitSystemUser} className="erp-form">
                          <div className="form-row two-col">
                            <label>
                              用户名
                              <input
                                value={systemUserForm.username}
                                onChange={handleSystemUserChange('username')}
                                disabled={Boolean(systemUserForm.id)}
                                required
                              />
                            </label>
                            <label>
                              姓名
                              <input value={systemUserForm.full_name} onChange={handleSystemUserChange('full_name')} />
                            </label>
                          </div>

                          <div className="form-row two-col">
                            <label>
                              {systemUserForm.id ? '重置密码（留空则不改）' : '初始密码'}
                              <input
                                type="password"
                                value={systemUserForm.password}
                                onChange={handleSystemUserChange('password')}
                                placeholder="至少 6 位"
                                autoComplete="new-password"
                              />
                            </label>
                            <label>
                              邮箱
                              <input value={systemUserForm.email} onChange={handleSystemUserChange('email')} placeholder="留空自动生成" />
                            </label>
                          </div>

                          <div className="form-row two-col">
                            <label>
                              所属部门
                              <select value={systemUserForm.department_id} onChange={handleSystemUserChange('department_id')}>
                                <option value="">未分配</option>
                                {departmentOptions.map((item) => (
                                  <option key={item.id} value={item.id}>
                                    {'　'.repeat(item.depth)}{item.name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label>
                              角色
                              <select value={systemUserForm.role_id} onChange={handleSystemUserChange('role_id')}>
                                <option value="">普通员工（默认）</option>
                                {systemMeta.roles.map((role) => (
                                  <option key={role.id} value={role.id}>{role.name}</option>
                                ))}
                              </select>
                            </label>
                          </div>

                          <div className="form-row two-col">
                            <label>
                              手机号
                              <input value={systemUserForm.phone} onChange={handleSystemUserChange('phone')} />
                            </label>
                            <label>
                              岗位
                              <input list="lookup-position" value={systemUserForm.position} onChange={handleSystemUserChange('position')} />
                            </label>
                          </div>

                          <label>
                            备注
                            <input value={systemUserForm.remark} onChange={handleSystemUserChange('remark')} />
                          </label>

                          <label className="checkbox-row">
                            <input type="checkbox" checked={systemUserForm.is_active} onChange={handleSystemUserChange('is_active')} />
                            启用该账号
                          </label>

                          <div className="form-actions">
                            <button className="primary-btn" type="submit" disabled={systemBusy}>
                              {systemUserForm.id ? '保存修改' : '创建用户'}
                            </button>
                            <button type="button" className="secondary-btn" onClick={resetSystemUserForm}>清空</button>
                          </div>
                        </form>
                      </section>

                      <section className="panel table-panel">
                        <div className="section-header">
                          <h2>用户列表</h2>
                          <div className="contract-search">
                            <input
                              value={systemUserKeyword}
                              onChange={(event) => {
                                setSystemUserKeyword(event.target.value);
                                refreshSystemUsers({ keyword: event.target.value });
                              }}
                              placeholder="按用户名 / 姓名 / 邮箱搜索"
                            />
                            <select
                              value={systemUserDeptFilter}
                              onChange={(event) => {
                                setSystemUserDeptFilter(event.target.value);
                                refreshSystemUsers({ department_id: event.target.value });
                              }}
                            >
                              <option value="">全部部门</option>
                              {departmentOptions.map((item) => (
                                <option key={item.id} value={item.id}>
                                  {'　'.repeat(item.depth)}{item.name}
                                </option>
                              ))}
                            </select>
                            <select
                              value={systemUserRoleFilter}
                              onChange={(event) => {
                                setSystemUserRoleFilter(event.target.value);
                                refreshSystemUsers({ role_id: event.target.value });
                              }}
                            >
                              <option value="">全部角色</option>
                              {systemMeta.roles.map((role) => (
                                <option key={role.id} value={role.id}>{role.name}</option>
                              ))}
                            </select>
                            <button
                              type="button"
                              className="secondary-btn small-btn"
                              onClick={() => {
                                setSystemUserKeyword('');
                                setSystemUserDeptFilter('');
                                setSystemUserRoleFilter('');
                                refreshSystemUsers({ keyword: '', department_id: '', role_id: '' });
                              }}
                            >
                              重置
                            </button>
                          </div>
                        </div>

                        <div className="table-wrap">
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th>用户名</th>
                                <th>姓名</th>
                                <th>所属部门</th>
                                <th>角色</th>
                                <th>联系方式</th>
                                <th>状态</th>
                                <th>最后登录</th>
                                <th>操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {systemUsers.length === 0 && (
                                <tr><td colSpan="8" className="table-empty">没有符合条件的用户。</td></tr>
                              )}
                              {systemUsers.map((row) => (
                                <tr key={row.id}>
                                  <td>{row.username}</td>
                                  <td>{row.full_name || '—'}</td>
                                  <td>{row.department_name || '未分配'}</td>
                                  <td>{row.role_name || row.role}</td>
                                  <td>
                                    <div className="cell-stack">
                                      <span>{row.phone || '—'}</span>
                                      <span className="cell-sub">{row.email || ''}</span>
                                    </div>
                                  </td>
                                  <td>
                                    <span className={`status-badge ${row.is_active ? 'ok' : 'muted'}`}>
                                      {row.is_active ? '启用' : '已停用'}
                                    </span>
                                  </td>
                                  <td>{row.last_login_at ? String(row.last_login_at).slice(0, 16).replace('T', ' ') : '从未登录'}</td>
                                  <td className="row-actions">
                                    <button type="button" className="link-btn" onClick={() => startEditSystemUser(row)}>编辑</button>
                                    <button type="button" className="link-btn" onClick={() => { setPasswordTarget(row); setPasswordDraft({ new_password: '' }); }}>重置密码</button>
                                    <button type="button" className="link-btn" onClick={() => toggleSystemUser(row)}>
                                      {row.is_active ? '停用' : '启用'}
                                    </button>
                                    <button
                                      type="button"
                                      className="link-btn danger"
                                      onClick={() => setConfirmDelete({
                                        id: row.id,
                                        endpoint: `/system/users/${row.id}`,
                                        label: `用户「${row.username}」`,
                                        kind: 'system-user',
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
                    </div>
                  )}

                  {systemTab === 'roles' && (
                    <div className="system-stack">
                      <section className="panel form-panel">
                        <div className="section-header">
                          <h2>{roleForm.id ? `编辑角色：${roleForm.name}` : '新增角色'}</h2>
                          <span className="status-badge">共 {systemMeta.roles.length} 个角色</span>
                        </div>

                        <form onSubmit={submitRole} className="erp-form">
                          <div className="form-row two-col">
                            <label>
                              角色编码
                              <input
                                value={roleForm.code}
                                onChange={handleRoleChange('code')}
                                placeholder="英文/数字，如 sales2"
                                required
                                disabled={Boolean(roleForm.id)}
                              />
                            </label>
                            <label>
                              角色名称
                              <input value={roleForm.name} onChange={handleRoleChange('name')} required />
                            </label>
                          </div>

                          <div className="form-row two-col">
                            <label>
                              说明
                              <input value={roleForm.description} onChange={handleRoleChange('description')} />
                            </label>
                            <label>
                              排序号
                              <input type="number" value={roleForm.sort_order} onChange={handleRoleChange('sort_order')} />
                            </label>
                          </div>

                          <label className="checkbox-row">
                            <input type="checkbox" checked={roleForm.is_active} onChange={handleRoleChange('is_active')} />
                            启用该角色（停用后该角色用户只能看工作台）
                          </label>

                          <div className="permission-header">
                            <strong>菜单权限</strong>
                            <span className="cell-sub">
                              已选 {permissionDraft.all ? systemMeta.total_menus : permissionDraft.menus.length} / {systemMeta.total_menus}
                            </span>
                            <label className="checkbox-row inline">
                              <input
                                type="checkbox"
                                checked={permissionDraft.all}
                                onChange={(event) => setPermissionDraft((prev) => ({ ...prev, all: event.target.checked }))}
                              />
                              超级管理员（拥有全部菜单，含以后新增的）
                            </label>
                          </div>

                          {permissionDraft.all ? (
                            <p className="settings-hint">该角色是超级管理员，菜单权限无需逐项勾选。</p>
                          ) : (
                            <div className="permission-tree">
                              {(systemMeta.permission_catalog || []).map((group) => {
                                const keys = (group.items || []).map((item) => item.key);
                                const checkedCount = keys.filter((key) => permissionDraft.menus.includes(key)).length;
                                return (
                                  <div className="permission-group" key={group.group}>
                                    <label className="permission-group-title">
                                      <input
                                        type="checkbox"
                                        checked={keys.length > 0 && checkedCount === keys.length}
                                        ref={(el) => {
                                          if (el) el.indeterminate = checkedCount > 0 && checkedCount < keys.length;
                                        }}
                                        onChange={() => togglePermissionGroup(group)}
                                      />
                                      {group.label}
                                      <span className="cell-sub">{checkedCount}/{keys.length}</span>
                                    </label>
                                    <div className="permission-items">
                                      {(group.items || []).map((item) => (
                                        <label className="permission-item" key={item.key}>
                                          <input
                                            type="checkbox"
                                            checked={permissionDraft.menus.includes(item.key)}
                                            onChange={() => togglePermissionMenu(item.key)}
                                          />
                                          {item.label}
                                        </label>
                                      ))}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          <div className="form-actions">
                            <button className="primary-btn" type="submit" disabled={systemBusy}>
                              {roleForm.id ? '保存角色' : '创建角色'}
                            </button>
                            <button type="button" className="secondary-btn" onClick={resetRoleForm}>清空</button>
                          </div>
                        </form>
                      </section>

                      <section className="panel table-panel">
                        <div className="section-header">
                          <h2>角色列表</h2>
                          <span className="status-badge">内置角色不可删除</span>
                        </div>

                        <div className="table-wrap">
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th>编码</th>
                                <th>名称</th>
                                <th>说明</th>
                                <th>菜单权限</th>
                                <th>用户数</th>
                                <th>类型</th>
                                <th>状态</th>
                                <th>操作</th>
                              </tr>
                            </thead>
                            <tbody>
                              {systemMeta.roles.map((role) => (
                                <tr key={role.id}>
                                  <td>{role.code}</td>
                                  <td>{role.name}</td>
                                  <td className="cell-sub">{role.description || '—'}</td>
                                  <td>
                                    {role.permissions?.all
                                      ? `全部 ${systemMeta.total_menus} 项`
                                      : `${(role.permissions?.menus || []).length} 项`}
                                  </td>
                                  <td>{role.user_count}</td>
                                  <td>{role.is_builtin ? '内置' : '自定义'}</td>
                                  <td>
                                    <span className={`status-badge ${role.is_active ? 'ok' : 'muted'}`}>
                                      {role.is_active ? '启用' : '已停用'}
                                    </span>
                                  </td>
                                  <td className="row-actions">
                                    <button type="button" className="link-btn" onClick={() => startEditRole(role)}>编辑权限</button>
                                    {!role.is_builtin && (
                                      <button
                                        type="button"
                                        className="link-btn danger"
                                        onClick={() => setConfirmDelete({
                                          id: role.id,
                                          endpoint: `/system/roles/${role.id}`,
                                          label: `角色「${role.name}」`,
                                          kind: 'system-role',
                                        })}
                                      >
                                        删除
                                      </button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </section>
                    </div>
                  )}
                </div>
              </div>
            
  );
}
