// 自动提取自 App.jsx（selectedTab='projects'）— 见 scripts/extract_pages.py
import ResizableLayout from '../components/resizable-layout/ResizableLayout.jsx';
export default function ProjectsPage({ ctx }) {
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

              <ResizableLayout>
                <section className="panel table-panel">
                  <div className="section-header">
                    <h2>项目列表</h2>
                    <span className="status-badge">{projects.length} 个</span>
                    <button type="button" className="primary-btn small-btn" onClick={() => setProjectModalOpen(true)}>新增项目</button>
                  </div>

                  {projects.length === 0 ? (
                    <div className="empty-state">暂无项目数据</div>
                  ) : (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>编码</th>
                          <th>名称</th>
                          <th>负责人</th>
                          <th>状态</th>
                          <th>进度</th>
                          <th className="num">预算</th>
                          <th>截止</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {projects.slice(0, 8).map((row) => (
                          <tr key={row.id}>
                            <td className="mono">{row.code}</td>
                            <td>{row.name}</td>
                            <td>{row.manager || '—'}</td>
                            <td>
                              <span className={`status-badge ${PROJECT_STATUS_TONE[row.status] || 'muted'}`}>
                                {PROJECT_STATUS_LABEL[row.status] || row.status}
                              </span>
                            </td>
                            <td>{row.progress}%</td>
                            <td className="num">{money(row.budget)}</td>
                            <td className="cell-sub">{row.deadline || '—'}</td>
                            <td className="row-actions nowrap">
                              <button
                                type="button"
                                className="link-btn"
                                disabled={projectBusy === `cost-${row.id}`}
                                onClick={() => openProjectCost(row)}
                              >
                                成本归集
                              </button>
                              <button type="button" className="link-btn" onClick={() => openProjectEdit(row)}>
                                编辑
                              </button>
                              <button
                                type="button"
                                className="link-btn danger"
                                disabled={projectBusy === `del-${row.id}`}
                                onClick={() => removeProject(row)}
                              >
                                删除
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {projects.length > 8 && (
                    <div className="table-hint">共 {projects.length} 条，仅显示最近 8 条</div>
                  )}

                  {/* ——— 项目成本归集：一个项目赚不赚钱，只能从这里看 ——— */}
                  {projectCost && (
                    <div className="modal-backdrop" onClick={() => setProjectCost(null)}>
                      <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>项目成本归集 · {projectCost.project.name}</h3>
                          <button type="button" className="close-btn" onClick={() => setProjectCost(null)}>×</button>
                        </div>
                        <p className="settings-hint">
                          数字全部来自**单据自动写的财务流水**，不需要在这个项目上再录一遍。
                          挂项目的方式：销售单 / 采购单选这个项目，或日常支出登记时指定项目。
                        </p>
                        <div className="invoice-summary-row">
                          <div className="metric-card">
                            <span>项目收入</span>
                            <strong className="green-text">{money(projectCost.summary.income)}</strong>
                          </div>
                          <div className="metric-card">
                            <span>采购成本</span>
                            <strong>{money(projectCost.summary.cost)}</strong>
                          </div>
                          <div className="metric-card">
                            <span>费用</span>
                            <strong>{money(projectCost.summary.expense)}</strong>
                          </div>
                          <div className="metric-card">
                            <span>毛利</span>
                            <strong className={Number(projectCost.summary.gross_profit) >= 0 ? 'red-text' : 'green-text'}>
                              {money(projectCost.summary.gross_profit)}
                            </strong>
                          </div>
                        </div>
                        <div className="invoice-summary-row">
                          <div className="metric-card">
                            <span>毛利率</span>
                            <strong>
                              {projectCost.summary.gross_margin_rate == null
                                ? '—（还没有收入）'
                                : `${projectCost.summary.gross_margin_rate}%`}
                            </strong>
                          </div>
                          <div className="metric-card">
                            <span>预算 / 已用</span>
                            <strong>
                              {money(projectCost.project.budget)} / {money(projectCost.summary.budget_used)}
                            </strong>
                          </div>
                          <div className="metric-card">
                            <span>预算执行率</span>
                            <strong>
                              {projectCost.summary.budget_usage_rate == null
                                ? '—（没设预算）'
                                : `${projectCost.summary.budget_usage_rate}%`}
                            </strong>
                          </div>
                          <div className="metric-card">
                            <span>流水条数</span>
                            <strong>{projectCost.summary.flow_count}</strong>
                          </div>
                        </div>

                        <div className="table-wrap">
                          <table className="data-table">
                            <thead>
                              <tr><th>来源</th><th className="num">条数</th><th className="num">金额</th></tr>
                            </thead>
                            <tbody>
                              {projectCost.by_source.length === 0 && (
                                <tr><td colSpan="3" className="table-empty">这个项目上还没有挂任何单据或流水。</td></tr>
                              )}
                              {projectCost.by_source.map((row) => (
                                <tr key={row.related_type}>
                                  <td>{row.label}</td>
                                  <td className="num">{row.count}</td>
                                  <td className="num">{money(row.amount)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>

                        <details className="raw-text-box">
                          <summary>明细流水（{projectCost.flows.length} 条）</summary>
                          <table className="detail-table">
                            <thead>
                              <tr><th>日期</th><th>来源</th><th>单号</th><th className="num">金额</th><th>说明</th></tr>
                            </thead>
                            <tbody>
                              {projectCost.flows.map((row) => (
                                <tr key={row.id}>
                                  <td>{row.occurred_at || '—'}</td>
                                  <td>{row.related_type_label || row.transaction_type}</td>
                                  <td className="mono">{row.doc_no || '—'}</td>
                                  <td className="num">{money(row.amount)}</td>
                                  <td>{row.note || '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </details>
                      </div>
                    </div>
                  )}

                  {/* ——— 新增项目弹窗 ——— */}
                  {projectModalOpen && (
                    <div className="modal-backdrop" onClick={() => setProjectModalOpen(false)}>
                      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>新增项目</h3>
                          <button type="button" className="close-btn" onClick={() => setProjectModalOpen(false)}>×</button>
                        </div>
                        <form onSubmit={submitProject} className="erp-form">
                          <div className="form-row two-col">
                            <label>
                              项目编码
                              <input value={projectForm.code} onChange={handleProjectChange('code')} required />
                            </label>
                            <label>
                              项目名称
                              <input value={projectForm.name} onChange={handleProjectChange('name')} required />
                            </label>
                          </div>
                          <div className="form-row two-col">
                            <label>
                              负责人
                              <input value={projectForm.manager} onChange={handleProjectChange('manager')} />
                            </label>
                            <label>
                              状态
                              <select value={projectForm.status} onChange={handleProjectChange('status')}>
                                {Object.entries(PROJECT_STATUS_LABEL).map(([value, label]) => (
                                  <option key={value} value={value}>{label}</option>
                                ))}
                              </select>
                            </label>
                          </div>
                          <div className="form-row two-col">
                            <label>
                              进度 %
                              <input type="number" min="0" max="100" value={projectForm.progress} onChange={handleProjectChange('progress')} />
                            </label>
                            <label>
                              预算
                              <input type="number" step="any" value={projectForm.budget} onChange={handleProjectChange('budget')} />
                            </label>
                          </div>
                          <label>
                            截止日期
                            <input type="date" value={projectForm.deadline} onChange={handleProjectChange('deadline')} />
                          </label>
                          <label>
                            备注
                            <textarea value={projectForm.note} onChange={handleProjectChange('note')} rows="3" />
                          </label>
                          <div className="form-actions">
                            <button className="primary-btn" type="submit">保存项目</button>
                            <button type="button" className="secondary-btn" onClick={() => setProjectModalOpen(false)}>取消</button>
                          </div>
                        </form>
                      </div>
                    </div>
                  )}

                  {/* ——— 编辑项目 ——— */}
                  {projectEdit && (
                    <div className="modal-backdrop" onClick={() => setProjectEdit(null)}>
                      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
                        <div className="modal-header">
                          <h3>编辑项目 · {projectEdit.code}</h3>
                          <button type="button" className="close-btn" onClick={() => setProjectEdit(null)}>×</button>
                        </div>
                        <form className="invoice-edit-form" onSubmit={submitProjectEdit}>
                          <label className="span-2">
                            <span>项目名称</span>
                            <input
                              value={projectEdit.name}
                              required
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, name: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>负责人</span>
                            <input
                              value={projectEdit.manager}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, manager: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>状态</span>
                            <select
                              value={projectEdit.status}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, status: event.target.value }))}
                            >
                              {Object.entries(PROJECT_STATUS_LABEL).map(([value, label]) => (
                                <option key={value} value={value}>{label}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>进度 %</span>
                            <input
                              type="number" min="0" max="100"
                              value={projectEdit.progress}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, progress: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>预算</span>
                            <input
                              type="number" step="any"
                              value={projectEdit.budget}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, budget: event.target.value }))}
                            />
                          </label>
                          <label>
                            <span>截止日期</span>
                            <input
                              type="date"
                              value={projectEdit.deadline || ''}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, deadline: event.target.value }))}
                            />
                          </label>
                          <label className="span-2">
                            <span>备注</span>
                            <input
                              value={projectEdit.note}
                              onChange={(event) => setProjectEdit((prev) => ({ ...prev, note: event.target.value }))}
                            />
                          </label>
                          <div className="form-actions span-2">
                            <button type="submit" className="primary-btn" disabled={projectBusy === 'edit'}>
                              {projectBusy === 'edit' ? '保存中…' : '保存'}
                            </button>
                            <button type="button" className="secondary-btn" onClick={() => setProjectEdit(null)}>
                              取消
                            </button>
                          </div>
                        </form>
                      </div>
                    </div>
                  )}
                </section>
              </ResizableLayout>
            
  );
}
