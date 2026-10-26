"""权限点目录 —— 系统管理第 5 批的"唯一事实来源"。

设计说明（为什么单开一个 core 模块而不是塞进 routes/system.py）：

1. **两侧都要用**：内置角色的默认权限（`app/models/role.py` 的 `BUILTIN_ROLES`）
   和角色管理接口返回的权限树（`app/api/v1/routes/system.py`）都依赖这份目录。
   放在 `core/` 下，models 与 routes 都能 import，且不会形成循环依赖
   （models 层绝不能 import routes 层）。
2. **和前端菜单是一对双胞胎**：前端的 `menuGroups`（App.jsx）才是菜单渲染的事实来源，
   这里这份目录是它的后端镜像，用来给"角色 → 可见菜单"打勾。
   两边一旦漂移，角色勾了看不到、或看到了勾不上，都是静默故障，
   所以 `tests/test_system_users.py` 里有一条**一致性断言**用正则从 App.jsx 抽取
   `menuGroups` 的 key 集合与本目录比对 —— 加菜单只改前端会被测试挡住。
3. **权限粒度只到菜单**：刻意不做按钮级 / 字段级权限。理由见 `models/role.py`
   的 docstring —— 那需要一整套元数据引擎，收益远小于复杂度。
"""

from __future__ import annotations

# 分组顺序与前端 menuGroups 完全一致，前端角色权限树直接按此渲染
PERMISSION_CATALOG: list[dict[str, object]] = [
    {
        "group": "workspace",
        "label": "工作台",
        "items": [{"key": "overview", "label": "运营概览"}],
    },
    {
        "group": "basic",
        "label": "基础资料",
        "items": [
            {"key": "customers", "label": "客户档案"},
            {"key": "suppliers", "label": "供应商档案"},
            {"key": "products", "label": "商品档案"},
            {"key": "warehouses", "label": "仓库档案"},
            {"key": "staff", "label": "员工档案"},
            {"key": "opening-stock", "label": "商品期初库存"},
        ],
    },
    {
        "group": "purchase",
        "label": "采购管理",
        "items": [
            {"key": "purchase", "label": "采购入库"},
            {"key": "purchase-order", "label": "采购订单"},
            {"key": "purchase-return", "label": "采购退货"},
            {"key": "purchase-statement", "label": "采购对账单"},
        ],
    },
    {
        "group": "sales",
        "label": "销售管理",
        "items": [
            {"key": "sales", "label": "开单管理"},
            {"key": "sales-order", "label": "销售订单"},
            {"key": "quotation", "label": "报价单"},
            {"key": "sales-return", "label": "销售退货"},
            {"key": "contracts", "label": "购销合同"},
            # 第 13 批（第三阶段）：合同台账 —— 进/出双向台账、导出、原件与 OCR 展示。
            # **必须追加在组末**：`default_menu_specs()` 用 items 下标 ×10 当 sort_order，
            # 插在中间会与既有行撞号；`_backfill_builtin_menus` 只补不改不重编号，
            # 所以新菜单只能落在分组末尾（想调整顺序由管理员在「菜单管理」里拖）。
            {"key": "contracts-ledger", "label": "合同台账"},
            # 第 13 批（第三阶段第三步）：增强版对账单编辑器。
            # 与老页面「销售对账单」（sales-statement，实时聚合、只读）是两套东西：
            # 这个操作 statements/statement_items 真表，能存草稿、勾选核对、打印。
            {"key": "statements-editor", "label": "增强对账单"},
        ],
    },
    {
        "group": "inventory",
        "label": "库存管理",
        "items": [
            {"key": "inventory", "label": "库存管理"},
            {"key": "stock-logs", "label": "变动查询"},
            {"key": "transfer", "label": "调拨管理"},
            {"key": "stocktaking", "label": "盘点管理"},
            {"key": "assembly", "label": "组合拆卸"},
            {"key": "loss-overflow", "label": "报损报溢"},
            {"key": "stock-alert", "label": "库存预警"},
        ],
    },
    {
        "group": "manufacture",
        "label": "生产管理",
        "items": [
            {"key": "production", "label": "生产单"},
            {"key": "bom", "label": "BOM 清单"},
            {"key": "production-plan", "label": "生产计划"},
            {"key": "mrp", "label": "MRP 运算"},
            {"key": "material-issue", "label": "生产领料"},
            {"key": "material-return", "label": "生产退料"},
            {"key": "finished-goods", "label": "成品入库"},
            {"key": "outsourcing", "label": "委外加工"},
        ],
    },
    {
        "group": "finance",
        "label": "财务管理",
        "items": [
            {"key": "finance", "label": "财务流水"},
            {"key": "receivable", "label": "应收账款"},
            {"key": "payable", "label": "应付账款"},
            {"key": "ledger", "label": "往来对账"},
            {"key": "general-ledger", "label": "总账"},
            {"key": "bank", "label": "现金银行"},
            {"key": "income-expense", "label": "日常收支"},
            {"key": "payroll", "label": "工资管理"},
            {"key": "invoices", "label": "开票管理"},
            {"key": "three-way-match", "label": "三单匹配"},
        ],
    },
    {
        "group": "analysis",
        "label": "报表分析",
        "items": [
            {"key": "reports", "label": "报表中心"},
            {"key": "analysis", "label": "经营分析"},
        ],
    },
    {
        "group": "project",
        "label": "项目管理",
        "items": [{"key": "projects", "label": "项目台账"}],
    },
    {
        "group": "mobile",
        "label": "移动与智能",
        "items": [
            {"key": "agent", "label": "智能助手"},
            {"key": "mobile", "label": "移动端预览"},
        ],
    },
    {
        "group": "system",
        "label": "系统设置",
        "items": [
            {"key": "settings", "label": "公司信息"},
            {"key": "users", "label": "用户角色"},
            {"key": "params", "label": "参数设置"},
            {"key": "dictionaries", "label": "数字字典"},
            {"key": "print-templates", "label": "打印模板"},
            {"key": "logs", "label": "操作日志"},
            {"key": "menus", "label": "菜单管理"},
        ],
    },
]

# 系统设置分组下的菜单：内置角色（除管理员外）默认不给这些
SYSTEM_GROUP_KEY = "system"


def all_menu_keys() -> list[str]:
    """全部权限点（菜单键）的扁平列表。"""
    return [item["key"] for group in PERMISSION_CATALOG for item in group["items"]]  # type: ignore[index]


def system_menu_keys() -> list[str]:
    """系统设置分组下的菜单键。"""
    for group in PERMISSION_CATALOG:
        if group["group"] == SYSTEM_GROUP_KEY:
            return [item["key"] for item in group["items"]]  # type: ignore[index]
    return []


def menu_labels() -> dict[str, str]:
    """菜单键 → 中文名。用于操作日志里把 url 翻成人话。"""
    return {
        item["key"]: item["label"]  # type: ignore[index]
        for group in PERMISSION_CATALOG
        for item in group["items"]  # type: ignore[index]
    }
