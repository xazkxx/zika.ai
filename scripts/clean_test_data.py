"""清理 pytest 测试套件在正式库里留下的测试档案。

背景：测试直接连正式数据库（PostgreSQL），每跑一次 pytest 就会新建一批
测试档案。以前这些数据跑完就留在库里，累积之后会污染业务列表，也让依赖
分页的断言变得不稳定。

识别规则（两道，取并集）：
  1. 编码签名 —— 测试脚本用 uuid 生成编码，形态固定且与业务编码不重叠：
       products : SKU-<组>-<8位hex>   例如 SKU-PERF-dbd7c4f7
       customers: CUST-<组>-<8位hex>  例如 CUST-ORDER-3b5a6ba2
       suppliers: SUP-<8位hex>        例如 SUP-7639f1ac
       warehouses: WH-<8位hex> / WH-<组>-<8位hex>  例如 WH-PD-2a0b5599
     另外兼容演示脚本的 DEMO-* / ZZ-TEST-*。
  2. 名称黑名单 —— 测试脚本写死的档案名（含中文），如「测试产品」「分析客户A」。

删除前还有一道保护：
  3. 引用保护 —— **被真实业务数据引用过的仓库一律不删**。
     本库指向 `warehouses` 的外键是 0 个，裸删不会报错、只会静默留下孤儿引用，
     所以必须靠扫列名自己挡（见 `referenced_warehouse_ids`）。

非上述形态的记录不会被自动删除；脚本会把「疑似残留」单独列出来由人判断。

用法：
    .venv\\Scripts\\python.exe scripts\\clean_test_data.py            # 只看，不删
    .venv\\Scripts\\python.exe scripts\\clean_test_data.py --apply    # 执行清理

tests/conftest.py 会在每次 pytest 结束后自动调用同一套清理逻辑，所以正常
情况下你不需要手动跑这个脚本。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402
# 菜单树的深度上限：直接引用模型的常量，避免这里手抄一份后与实现漂移
from app.models.menu import MAX_MENU_DEPTH  # noqa: E402

# ── 规则 1：编码签名（主要依据，覆盖 uuid 生成的全部测试档案）────────────────
# 形态统一成「<前缀>(-<段>)* - <8 位 hex 尾巴>」，允许任意数量的中段：
#     SKU-1a2b3c4d / SKU-PD-1a2b3c4d / CUS-SRET-1a2b3c4d / SUP-ADJ-0f1e2d3c
# 早期写成 `CUST(-[A-Z]+)?-` 这种"最多一段中段"的固定形态，
# 于是 `CUS-SRET-<hex>`（销售退货夹具）既不被清理、又不被重名守卫放行，
# 一次中断的 pytest 就让它活到下一轮，把 test_sales_return.py 全组打成 409。
# 真实业务码是 CUS20261022001 / SKU-001 / WH-001，**不会**以「-8 位 hex」结尾。
_TEST_CODE_TAIL = r"-[0-9a-f]{8}$"
PRODUCT_CODE_RE = rf"^(?:SKU|DEMO-P)[A-Z0-9]*(?:-[A-Z0-9]{{1,10}})*{_TEST_CODE_TAIL}|^SKU-[A-Z]+-\d+$"
CUSTOMER_CODE_RE = rf"^(?:CUS|DEMO-C)[A-Z0-9]*(?:-[A-Z0-9]{{1,10}})*{_TEST_CODE_TAIL}|^CUST-ANALYSIS-\d+$|^ZZ-TEST-.*$"
SUPPLIER_CODE_RE = rf"^(?:SUP|DEMO-S)[A-Z0-9]*(?:-[A-Z0-9]{{1,10}})*{_TEST_CODE_TAIL}$"

# ── 规则 2：名称黑名单（兜底，覆盖没走 uuid 的固定命名）────────────────────
PRODUCT_NAME_LIKE = (
    "%测试产品%", "%测试商品%", "仅老字段商品%", "订单产品%",
    "状态更新产品%", "分析产品%", "%演示%", "探针%", "%--DEMO--%", "%模板验证%",
)
PRODUCT_NAME_EXACT = ("主机产品", "CPU模块")
CUSTOMER_NAME_LIKE = (
    "%测试客户%", "分析客户%", "订单客户%", "状态客户%", "%演示%", "探针%", "%--DEMO--%",
    "%模板验证%", "%日志验证%", "%过滤验证%",
)
SUPPLIER_NAME_LIKE = ("%测试供应商%", "订单供应商%", "%演示%", "探针%", "%--DEMO--%")

# ── 仓库 ──────────────────────────────────────────────────────────────
# 测试仓库的编码一律由 uuid 生成，形态与业务编码（CK-001 / WH-001）不重叠：
#     WH-<8位hex>          项目 / 组合 / 期初 / 报表 / 退货 / 销售退货 / 调拨
#     WH-<TAG>-<8位hex>    FG 成品入库 / ADJ 报损报溢 / LL 领料 / TL 退料 /
#                          WW 委外 / SCJH 生产计划 / PD 盘点 / MRP 物料需求
#
# ⚠️ 2026-10-15 修的历史洞：原来这里写成
#       WAREHOUSE_NAME_LIKE = ("主仓库%", "一号仓%", "停用仓%", "主仓%")
#       WAREHOUSE_CODE_RE   = r"^WH-[0-9a-f]{8}$"
#    两句都用「名称命中 AND 编码命中」，于是：
#      · 「项目测试仓-14f61a46」这类名字不在名单里 -> 每跑一轮 pytest 漏一行；
#      · 「WH-PD-<hex>」「WH-FG-<hex>」等带 TAG 的编码压根不匹配 -> 全漏。
#    累积到 118 个仓库里 115 个是残留（真实仓库只有 3 个）。
#    现在改成**两条独立信号取并集**，任一条成立即删：
#      ① 编码命中 uuid 签名（主要依据，本身已足够唯一）；
#      ② 名称命中黑名单 且 编码尾部是 8 位 hex（兜底，防止将来新写测试换了名字）。
WAREHOUSE_CODE_RE = r"^WH(-[A-Z]{2,5})?-[0-9a-f]{8}$"
WAREHOUSE_CODE_TAIL_RE = r"-[0-9a-f]{8}$"
WAREHOUSE_NAME_LIKE = (
    # 原有
    "主仓库%", "一号仓%", "停用仓%", "主仓%",
    # 测试仓（项目 / 组合 / 期初 / 报表 / MRP）
    "%测试仓%",
    # 各业务模块测试自建的仓库名，一一对应 tests/ 下的 _new_warehouse()
    "盘点主仓", "调拨主仓%", "退货主仓", "销售退货主仓", "成品主仓",
    "报损主仓", "领料主仓", "领料仓%", "退料主仓", "委外主仓", "生产车间仓",
)
# 员工档案（基础资料收尾）：工号签名
EMPLOYEE_CODE_RE = r"^(EMP(-[A-Z]+)?-[0-9a-f]{8}|TEST-EMP-.*)$"
EMPLOYEE_NAME_LIKE = ("%测试员工%", "%验收员工%", "%导入员工%", "%校验员工%", "%引用检查员工%", "%部门占用员工%")


def warehouse_reference_columns(conn):
    """找出所有「可能引用仓库」的列。

    ⚠️ 为什么不用外键来判断：本库**指向 `warehouses` 的外键是 0 个**（全库总共才 3 个外键），
    所以裸 `DELETE FROM warehouses` 不会报错，只会**静默**留下孤儿引用
    （2026-10-15 实测：`public.production_plans.warehouse_id` 就指着 `WH-FG-04de8033`）。
    删之前必须靠扫列名显式排除，否则「清理测试数据」会顺手破坏真实业务。
    """
    return [
        tuple(r)
        for r in conn.execute(
            text(
                "SELECT table_schema, table_name, column_name "
                "FROM information_schema.columns "
                "WHERE (column_name ILIKE '%warehouse%' OR column_name ILIKE '%_wh' "
                "       OR column_name ILIKE 'wh_%') "
                "  AND table_schema IN ('public', 'co_02', 'co_03') "
                "  AND data_type IN ('integer', 'bigint', 'smallint', 'numeric')"
            )
        )
    ]


def referenced_warehouse_ids(conn, ids):
    """返回被任何业务表引用到的仓库 id 集合（这些一律不删）。"""
    if not ids:
        return set()
    used: set[int] = set()
    for schema, table, column in warehouse_reference_columns(conn):
        try:
            rows = conn.execute(
                text(f'SELECT DISTINCT {column} FROM {schema}."{table}" WHERE {column} = ANY(:ids)'),
                {"ids": list(ids)},
            )
        except Exception:  # 表/列不适用就跳过，不影响其它列
            continue
        used.update(r[0] for r in rows if r[0] is not None)
    return used


def collect_ids(conn, report_protected: bool = True):
    """返回 (product_ids, customer_ids, supplier_ids, warehouse_ids)。

    `report_protected=False` 时不打印「已跳过被引用仓库」那行 —— pytest 的自动清理
    走这个分支，免得污染测试输出。
    """
    p_ids = [r[0] for r in conn.execute(
        text(
            "SELECT id FROM products WHERE sku ~ :re "
            "OR name LIKE ANY(:like) OR name = ANY(:exact)"
        ),
        {"re": PRODUCT_CODE_RE, "like": list(PRODUCT_NAME_LIKE), "exact": list(PRODUCT_NAME_EXACT)})]
    c_ids = [r[0] for r in conn.execute(
        text("SELECT id FROM customers WHERE code ~ :re OR name LIKE ANY(:like)"),
        {"re": CUSTOMER_CODE_RE, "like": list(CUSTOMER_NAME_LIKE)})]
    s_ids = [r[0] for r in conn.execute(
        text("SELECT id FROM suppliers WHERE code ~ :re OR name LIKE ANY(:like)"),
        {"re": SUPPLIER_CODE_RE, "like": list(SUPPLIER_NAME_LIKE)})]
    w_ids = [r[0] for r in conn.execute(
        text(
            "SELECT id FROM warehouses "
            "WHERE code ~ :re OR (name LIKE ANY(:n) AND code ~ :tail)"
        ),
        {"re": WAREHOUSE_CODE_RE, "n": list(WAREHOUSE_NAME_LIKE),
         "tail": WAREHOUSE_CODE_TAIL_RE})]
    # 被真实业务引用的仓库一律留下（本库没有外键兜底，只能自己挡）
    protected = referenced_warehouse_ids(conn, w_ids)
    if protected:
        if report_protected:
            print(f"  [clean] 有 {len(protected)} 个仓库被业务数据引用，已跳过："
                  f"{sorted(protected)}")
        w_ids = [w for w in w_ids if w not in protected]
    return p_ids, c_ids, s_ids, w_ids


def list_unmatched(conn, limit: int = 40):
    """列出不符合任何测试签名、但编码形态也不像业务编码的记录，供人工判断。"""
    rows = []
    queries = [
        ("products", "sku", "SELECT id, sku AS c, name FROM products WHERE sku !~ :re"),
        ("customers", "code", "SELECT id, code AS c, name FROM customers WHERE code !~ :re"),
        ("suppliers", "code", "SELECT id, code AS c, name FROM suppliers WHERE code !~ :re"),
    ]
    patterns = (PRODUCT_CODE_RE, CUSTOMER_CODE_RE, SUPPLIER_CODE_RE)
    for (table, _col, sql), _re in zip(queries, patterns):
        # 这里只做提示：把编码里含非业务字符（纯中文、含空格、以 TEST 开头等）的挑出来
        for r in conn.execute(text(sql), {"re": _re}):
            code = str(r.c or "")
            if any(ch.isspace() for ch in code) or any("\u4e00" <= ch <= "\u9fff" for ch in code) or "TEST" in code.upper():
                rows.append((table, r.id, code, r.name))
    return rows[:limit]


def list_suspicious_warehouses(conn, limit: int = 40):
    """列出「编码像机器生成、却没能被任何签名认出来」的仓库 —— 只提示，绝不自动删。

    为什么单独给仓库加这一条：仓库的清理规则一旦再漏，就会像 2026-10-15 那样
    静默堆积（当时 118 个仓库里 115 个是残留，跑了很久才被发现）。
    凡是编码尾部是 8 位 hex 的，都能被这条捞出来示众。
    """
    rows = []
    for r in conn.execute(
        text(
            "SELECT id, code, name FROM public.warehouses "
            "WHERE code ~ :tail ORDER BY id"
        ),
        {"tail": WAREHOUSE_CODE_TAIL_RE},
    ):
        rows.append(("warehouses", r.id, r.code, r.name))
    return rows[:limit]


# 依赖档案的从属表：档案被删后，这些行就成了「孤儿」（界面上只能显示成空壳）
ORPHAN_RULES = [
    ("sales_order_items", "sales_order_id", "sales_orders", "id"),
    ("purchase_order_items", "purchase_order_id", "purchase_orders", "id"),
    ("contract_items", "contract_id", "contracts", "id"),
    ("quotation_items", "quotation_id", "quotations", "id"),
    ("purchase_return_items", "purchase_return_id", "purchase_returns", "id"),
    ("sales_return_items", "sales_return_id", "sales_returns", "id"),
    ("assembly_order_items", "assembly_order_id", "assembly_orders", "id"),
    ("assembly_order_items", "product_id", "products", "id"),
    ("assembly_orders", "product_id", "products", "id"),
    ("inventory_transfer_items", "inventory_transfer_id", "inventory_transfers", "id"),
    ("inventory_transfer_items", "product_id", "products", "id"),
    ("inventory_transfers", "from_warehouse_id", "warehouses", "id"),
    ("inventory_transfers", "to_warehouse_id", "warehouses", "id"),
    ("stocktaking_items", "stocktaking_id", "stocktakings", "id"),
    ("stocktaking_items", "product_id", "products", "id"),
    ("stocktakings", "warehouse_id", "warehouses", "id"),
    ("inventory_adjustment_items", "inventory_adjustment_id", "inventory_adjustments", "id"),
    ("inventory_adjustment_items", "product_id", "products", "id"),
    ("inventory_adjustments", "warehouse_id", "warehouses", "id"),
    ("production_plan_items", "production_plan_id", "production_plans", "id"),
    ("production_plan_items", "product_id", "products", "id"),
    ("production_plans", "warehouse_id", "warehouses", "id"),
    ("material_issue_items", "material_issue_id", "material_issues", "id"),
    ("material_issue_items", "product_id", "products", "id"),
    ("material_issues", "warehouse_id", "warehouses", "id"),
    ("material_issues", "plan_id", "production_plans", "id"),
    ("material_return_items", "material_return_id", "material_returns", "id"),
    ("material_return_items", "product_id", "products", "id"),
    ("material_returns", "warehouse_id", "warehouses", "id"),
    ("material_returns", "plan_id", "production_plans", "id"),
    ("finished_goods_receipt_items", "finished_goods_receipt_id", "finished_goods_receipts", "id"),
    ("finished_goods_receipt_items", "product_id", "products", "id"),
    ("finished_goods_receipts", "warehouse_id", "warehouses", "id"),
    ("finished_goods_receipts", "plan_id", "production_plans", "id"),
    ("outsourcing_items", "outsourcing_order_id", "outsourcing_orders", "id"),
    ("outsourcing_items", "product_id", "products", "id"),
    ("outsourcing_orders", "supplier_id", "suppliers", "id"),
    ("outsourcing_orders", "product_id", "products", "id"),
    ("inventory_transactions", "product_id", "products", "id"),
    ("production_orders", "product_id", "products", "id"),
    ("production_boms", "product_id", "products", "id"),
    ("production_boms", "component_product_id", "products", "id"),
    ("sales_orders", "customer_id", "customers", "id"),
    ("purchase_orders", "supplier_id", "suppliers", "id"),
    ("purchase_returns", "supplier_id", "suppliers", "id"),
    ("sales_returns", "customer_id", "customers", "id"),
    ("quotations", "customer_id", "customers", "id"),
    ("financial_transactions", "customer_id", "customers", "id"),
    ("financial_transactions", "supplier_id", "suppliers", "id"),
]

# 销售订单（2026-10-21 补）：此前**没有**任何签名规则，所以 pytest 建的
# `SO-<8位hex>` / `SO-STATUS-<8位hex>` 单会长期躺在正式库里（实测漏过 2 张）。
# 业务单号格式恒为 `XS + 8位日期 + 3位流水`，与这两个形态绝不可能撞上。
SALES_ORDER_TEST_CONDITION = (
    "order_no ~ '^SO-([A-Z0-9]+-)?[0-9a-f]{8}$' "
    # 合同转单：备注里带测试合同号（contract_no 以 TEST- 开头）
    "OR note LIKE '由合同 TEST-%' "
    # 客户已不存在（pytest 先删客户再删单，或上一轮清理只删了档案）→ 单据只剩空壳
    "OR customer_id NOT IN (SELECT id FROM customers)"
)

# 合同（融合改造新增）：party_id 同时可能指向客户或供应商，按 id 匹配会误删真实合同，
# 所以只认合同号签名与相对方名称黑名单 —— 这两条都不会命中真实业务数据。
CONTRACT_TEST_CONDITION = (
    "contract_no LIKE 'TEST-%' OR title LIKE '%测试%' "
    "OR party_name LIKE '%测试客户%' OR party_name LIKE '%测试供应商%'"
)

# 报价单（融合改造新增）：报价单号签名 + 备注/客户名黑名单。
# 报价单号在测试里固定用 TEST-BJ... 前缀，与业务单号（BJ+日期+流水）不会重叠。
QUOTATION_TEST_CONDITION = (
    "quote_no LIKE 'TEST-%' OR note LIKE '%报价单测试%' "
    "OR customer_name LIKE '%测试客户%'"
)

# 采购退货单（融合改造新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-CGTH... 前缀，与业务单号（CGTH+日期+流水）不会重叠。
PURCHASE_RETURN_TEST_CONDITION = (
    "return_no LIKE 'TEST-%' OR note LIKE '%退货单测试%' "
    "OR supplier_name LIKE '%测试供应商%'"
)

# 销售退货单（融合改造新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-XSTH... 前缀，与业务单号（XSTH+日期+流水）不会重叠。
SALES_RETURN_TEST_CONDITION = (
    "return_no LIKE 'TEST-%' OR note LIKE '%销售退货测试%' "
    "OR customer_name LIKE '%测试客户%'"
)

# 库存调拨单（融合改造新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-DBD... 前缀，与业务单号（DBD+日期+流水）不会重叠。
INVENTORY_TRANSFER_TEST_CONDITION = (
    "transfer_no LIKE 'TEST-%' OR note LIKE '%调拨单测试%'"
)

# 库存盘点单（融合改造新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-PD... 前缀，与业务单号（PD+日期+流水）不会重叠。
STOCKTAKING_TEST_CONDITION = (
    "check_no LIKE 'TEST-%' OR note LIKE '%盘点单测试%'"
)

# 报损报溢单（融合改造新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-BS... / TEST-BY... 前缀，与业务单号不会重叠。
INVENTORY_ADJUSTMENT_TEST_CONDITION = (
    "adjust_no LIKE 'TEST-%' OR note LIKE '%报损报溢测试%'"
)

# 纯库存单据（调拨/盘点/报损报溢）产生的库存流水：这些单头一旦被清掉，
# 流水就成了孤儿。这里按单号签名兜底，四类 related_type 一起扫。
# 生产类（领料/退料/成品入库/委外加工）同样不写财务、只写库存流水，一并纳入。
INVENTORY_DOC_TEST_CONDITION = (
    "doc_no LIKE 'TEST-%' AND related_type IN "
    "('inv_check','inv_scrap','inv_overflow','inv_transfer',"
    "'production_issue','production_return','production_in','outsourcing')"
)

# 生产计划单（第 3 批生产类新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-SCJH... / TEST-WWJH... 前缀，与业务单号不会重叠。
PRODUCTION_PLAN_TEST_CONDITION = (
    "plan_no LIKE 'TEST-%' OR note LIKE '%生产计划测试%'"
)

# 生产领料单 / 生产退料单（第 3 批生产类新增）：单号签名 + 备注黑名单。
MATERIAL_ISSUE_TEST_CONDITION = (
    "issue_no LIKE 'TEST-%' OR note LIKE '%生产领料测试%'"
)
MATERIAL_RETURN_TEST_CONDITION = (
    "return_no LIKE 'TEST-%' OR note LIKE '%生产退料测试%'"
)

# 成品入库单（第 3 批生产类新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-CPRK... 前缀，与业务单号（CPRK+日期+流水）不会重叠。
FINISHED_GOODS_TEST_CONDITION = (
    "receipt_no LIKE 'TEST-%' OR note LIKE '%成品入库测试%'"
)

# 委外加工单（第 3 批生产类新增）：单号签名 + 备注黑名单。
# 测试里固定用 TEST-WWJG... 前缀，与业务单号（WWJG+日期+流水）不会重叠。
OUTSOURCING_TEST_CONDITION = (
    "order_no LIKE 'TEST-%' OR note LIKE '%委外加工测试%'"
)

# 系统管理（第 5 批）：测试账号 / 角色 / 部门的编码签名。
# 一律 TEST- 前缀 + 8 位 hex，与真实账号（admin）、真实角色（admin/sales/...）
# 和真实部门编码都不会撞。
SYSTEM_USER_TEST_CONDITION = "username LIKE 'TEST-USR-%'"
SYSTEM_ROLE_TEST_CONDITION = "code LIKE 'TEST-ROLE-%'"
SYSTEM_DEPT_TEST_CONDITION = "code LIKE 'TEST-DEPT-%'"

# 现金银行 / 日常收支（第 8 批）：账户编码一律 TEST-BANK- 前缀，沿用上面同一套约定。
#
# 转账单号**故意不参与识别** —— 它由后端按业务格式生成（TR+日期+3位流水），
# 真实用户手工转账长得一模一样，用单号签名去删会误杀真实单据。
# 所以转账与其两条流水一律按「挂在哪个账户名下」归属：测试账户名下的就是测试数据。
# 顺序上必须先清流水、再清转账、最后删账户（账户上有流水时接口会 409 拒绝删）。
BANK_ACCOUNT_TEST_CONDITION = "code LIKE 'TEST-BANK-%'"

# 发票批处理测试留下的支出流水：备注形如「发票 TEST-xxxx | 对方单位 | 专票 | 税率…」。
#
# 这是**本批才发现的历史欠账**：发票测试每跑一次就写一条 expense 流水，但历次
# 清理规则从没管过它，于是一路累积。抓到的现场是 55 条、合计 ¥55000，
# 且其中 53 条对应的发票主表记录早已被删（流水成了纯孤儿）。
# 危害不只是"看着脏"—— 它们 `related_type`/`period` 全空，会被判成「人工登记的
# 日常支出」，直接计入本批新做的「日常收支」页面合计，让用户看到凭空多出的
# 五万五。真实发票号来自 OCR，不可能是 TEST- 开头，所以这条签名不会误伤。
INVOICE_FLOW_TEST_CONDITION = "note LIKE '发票 TEST-%'"

# 菜单管理（第 10 批）：测试建的临时菜单节点。
#
# 为什么必须清：菜单树是**展示数据** —— 残留节点会直接出现在用户的左侧导航里，
# 点进去还可能是空白（测试只敢挂已有页面，但残留本身就很碍眼）。
#
# 自引用树要**从叶子往上删**：有子节点的分组接口层会 409 拒绝删除，
# 所以清理时循环"只删没有子节点的匹配项"，直到一轮下来删不动为止。
MENU_TEST_CONDITION = "(label LIKE '临时%' OR label LIKE '验收%' OR label LIKE '%TEST%')"

# 发票测试数据（第 11 批）：发票号里带 TEST 的。
#
# 真实发票号是 20 位数字串或平台给的编码，不可能含 TEST，所以这条签名不会误伤。
# 之前历次规则只清了发票**带出来的财务流水**，没清发票本身 ——
# 于是库里留了两条 invoice_no='TEST-xxxx' 的垃圾记录（还有 'invoice TEST-' 的流水）。
# 删记录时**必须连原件一起删**，否则 data/invoices 目录会积一堆没人认领的文件。
# 2026-10-21 扩展：pytest 用 `INV-ODT-<8hex>` / `INV-STATUS-<8hex>` 建票，
# 业务票号是纯数字（26612000001006203301），三者形态互不重叠。
INVOICE_TEST_CONDITION = (
    "invoice_no LIKE '%TEST%' OR invoice_no LIKE 'INV-ODT-%' "
    "OR invoice_no LIKE 'INV-STATUS-%' OR invoice_no LIKE 'E2E-INV-%' "
    # 单段签名：INV-<8位hex>（pytest 夹具）/ DBG-<hex>（一次性调试脚本）。
    # 用正则而不是 `LIKE 'INV-%'`，是为了不给"以后真有人工编 INV- 开头的票号"留坑。
    "OR invoice_no ~ '^(INV|DBG)-[0-9A-Za-z]{4,12}$'"
)

# 对账单测试数据（2026-10-22）：`tests/test_statement_generate.py` 每跑一次
# 就用真实客户生成一张草稿对账单，并从库里取下一个 DZ 号。
# 以前清理脚本完全不管 statements —— 三轮 pytest 下来库里多了 27 张
# 「对账测试客户xxxx」的对账单、58 张 `INV-<8hex>` 发票，
# 明细行还挂着，把「对账单台账」和发票列表都污染了。
# 判据只看**往来单位名称**：测试客户名一定含"测试客户"/"对账测试"，真实客户不会。
STATEMENT_TEST_CONDITION = (
    "party_name LIKE '%测试客户%' OR party_name LIKE '%测试供应商%' "
    "OR party_name LIKE '对账测试%' OR statement_no LIKE 'DZ-TEST%'"
)

# 操作日志（第 5 批第 3 轮）：只清测试账号留下的那部分。
#
# 为什么**不**整表清空：日志是真实操作留痕，admin 跑测试时确实调了接口，
# 那些记录是"真发生过的操作"，把它删掉等于伪造历史。
# 测试账号（TEST-USR-*）的日志才是纯测试噪音。
# 表本身有 5000 条上限会自我修剪（见 models/operation_log.py），
# 所以剩下的记录不会无限堆积。
LOG_TEST_CONDITION = "username LIKE 'TEST-USR-%'"

# 用户表上的"软引用"清理：users.department_id / users.role_id 指向的部门或角色
# 没了，要**解绑**（置 NULL）而不是删用户 —— 账号是真实资产，跟档案类孤儿
# （直接删行）不是一回事。
SYSTEM_UNBIND_STEPS = [
    "UPDATE users SET department_id = NULL WHERE department_id IS NOT NULL "
    "AND department_id NOT IN (SELECT id FROM departments)",
    "UPDATE users SET role_id = NULL WHERE role_id IS NOT NULL "
    "AND role_id NOT IN (SELECT id FROM roles)",
]

# 成品入库 / 委外加工产生的财务流水：成品入库写 cost（成本结转），
# 委外加工写 payable（加工费应付）。两者都带 related_type + related_order_id，
# 单头删掉后这两类流水必须一并扫掉，否则会留下指向已删单据的孤儿。
# 组合拆卸单产生的库存流水：单号签名是 ZH/CX + 日期 + 3 位，但更稳的判据是
# "related_type='assembly' 且 related_order_id 指向的单子已经不存在了"。
# 注意**必须**带 related_type 收窄 —— related_order_id 被采购、销售等共用，
# 只按 id 判断会把真实流水一起干掉。
ASSEMBLY_DOC_TEST_STEPS = [
    (
        "inventory_transactions",
        "related_type = 'assembly' "
        "AND related_order_id NOT IN (SELECT id FROM assembly_orders)",
    ),
]

FINANCE_DOC_TEST_STEPS = [
    (
        "financial_transactions",
        "related_type = 'production_in' "
        "AND related_order_id NOT IN (SELECT id FROM finished_goods_receipts)",
    ),
    (
        "financial_transactions",
        "related_type = 'outsourcing' "
        "AND related_order_id NOT IN (SELECT id FROM outsourcing_orders)",
    ),
]

# 孤儿财务流水：单据已删、流水还在（应收应付凭空多一笔）。这里按 related_type
# 反查各自的单据表，凡指向不存在的单据一律清掉。历史上删采购入库/销售开单不会
# 冲销财务，会在库里留下这类孤儿，一并在此扫净。
ORPHAN_FINANCE_STEPS = [
    (
        "financial_transactions",
        "related_type = 'purchase_in' "
        "AND related_order_id NOT IN (SELECT id FROM purchase_orders)",
    ),
    (
        "financial_transactions",
        "related_type = 'sales_out' "
        "AND related_order_id NOT IN (SELECT id FROM sales_orders)",
    ),
]


def run_orphan_cleanup(verbose: bool = True) -> int:
    """删除指向已不存在档案的孤儿记录。跑两轮，处理级联（如单据没了，明细也成孤儿）。"""
    total = 0
    applied: list[tuple[str, int]] = []
    for _round in range(2):
        for table, column, ref_table, ref_col in ORPHAN_RULES:
            sql = (
                f"DELETE FROM {table} WHERE {column} IS NOT NULL "
                f"AND {column} NOT IN (SELECT {ref_col} FROM {ref_table})"
            )
            try:
                with engine.begin() as conn:
                    n = conn.execute(text(sql)).rowcount
            except Exception as exc:
                if verbose:
                    print(f"  {table}.{column:<24} 跳过（{type(exc).__name__}: {str(exc).splitlines()[0][:70]}）")
                continue
            total += n
            if n:
                applied.append((f"{table}.{column}", n))
    if verbose:
        for label, n in applied:
            print(f"  {label:<34} 删除 {n:>5} 行  (孤儿)")
    return total


def collect_employee_ids(conn) -> list[int]:
    """按工号签名 / 姓名黑名单挑出测试员工。"""
    return [
        r[0]
        for r in conn.execute(
            text("SELECT id FROM employees WHERE code ~ :re OR name LIKE ANY(:like)"),
            {"re": EMPLOYEE_CODE_RE, "like": list(EMPLOYEE_NAME_LIKE)},
        )
    ]


def run_cleanup(verbose: bool = True) -> int:
    """删除测试残留，返回删除总行数。"""
    with engine.connect() as conn:
        p_ids, c_ids, s_ids, w_ids = collect_ids(conn)
        e_ids = collect_employee_ids(conn)

    if not any((p_ids, c_ids, s_ids, w_ids)):
        if verbose:
            print("  没有按签名识别到的测试档案，直接扫孤儿记录。")

    pc = ",".join(map(str, p_ids)) or "NULL"
    cc = ",".join(map(str, c_ids)) or "NULL"
    sc = ",".join(map(str, s_ids)) or "NULL"
    ec = ",".join(map(str, e_ids)) or "NULL"
    # w_ids 这里只用于下面的"有没有活干"判断；真正的删除在函数末尾延后做

    # 先删"引用方"（明细、流水、单据），再删"被引用方"（档案），顺序不能颠倒
    # ⚠️ warehouses 刻意不在这里 —— 它必须等到所有引用方都清干净之后再处理，
    #    原因见函数末尾那段「仓库延后处理」的注释。
    steps = [
        ("table", "sales_order_items", "product_id", pc),
        ("table", "purchase_order_items", "product_id", pc),
        ("table", "quotation_items", "product_id", pc),
        ("table", "inventory_transactions", "product_id", pc),
        ("table", "production_orders", "product_id", pc),
        ("table", "production_boms", "product_id", pc),
        ("table", "production_boms", "component_product_id", pc),
        ("table", "sales_orders", "customer_id", cc),
        ("table", "purchase_orders", "supplier_id", sc),
        ("table", "financial_transactions", "customer_id", cc),
        ("table", "financial_transactions", "supplier_id", sc),
        ("archive", "products", "id", pc),
        ("archive", "customers", "id", cc),
        ("archive", "suppliers", "id", sc),
    ]

    total = 0
    applied: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []

    # 关键：每条语句单独一个事务。PostgreSQL 里同一事务内某条语句报错会让整个
    # 事务进入 aborted 状态，后续语句全部失败（此前正是因此导致档案表删不掉）。
    for _, table, column, ids in steps:
        if ids in ("NULL", ""):
            continue
        sql = f"DELETE FROM {table} WHERE {column} IN ({ids})"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:  # 表/列不存在等情况：跳过并如实报告，不再静默吞掉
            skipped.append((f"{table}.{column}", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}.{column}", n))

    # 测试脚本产生的项目台账 / 注册账号 / 孤儿财务流水。签名或文案都很明确，
    # 与真实业务不重叠（真实业务里「销售收入」必然关联客户或单据，不会三者全空）。
    signature_steps = [
        ("projects", r"code ~ '^PRJ-[0-9A-Fa-f]{8}$'"),
        ("users", r"username ~ '^user-[0-9a-f]{8}$'"),
        (
            "financial_transactions",
            "related_type IS NULL AND customer_id IS NULL AND supplier_id IS NULL "
            "AND project_id IS NULL AND note IN ('测试收入','销售收入','采购支出')",
        ),
    ]
    for table, condition in signature_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 系统管理（第 5 批）：测试账号 / 角色 / 部门。
    # 顺序不能颠倒 —— 用户挂在角色与部门下，角色/部门上有用户时接口层会拒绝删除。
    # 「谁引用了谁」先解绑，再删被引用方，最后把悬空的引用置空（见 SYSTEM_UNBIND_STEPS）。
    system_steps = [
        # 测试账号的操作日志先清（无外键，但逻辑上属于这个账号的产物）
        ("operation_logs", LOG_TEST_CONDITION, "（测试账号）"),
        # 员工档案：挂在 departments 上，必须在部门被删之前清掉，
        # 否则会留下 department_id 指向不存在部门的员工
        ("employees", f"(id IN ({ec}) OR department_id NOT IN (SELECT id FROM departments))", "（签名）"),
        ("users", SYSTEM_USER_TEST_CONDITION, "（签名）"),
        ("roles", SYSTEM_ROLE_TEST_CONDITION, "（签名）"),
        ("departments", SYSTEM_DEPT_TEST_CONDITION, "（签名）"),
    ]
    for table, condition, note in system_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}{note}", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}{note}", n))

    # 解绑：部门 / 角色被清掉后，users 上残留的 id 指向了不存在的行（界面会显示空白）
    for sql in SYSTEM_UNBIND_STEPS:
        table = "users"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（解绑）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（解绑）", n))

    # 合同表（融合改造新增）：先删明细再删合同头
    contract_steps = [
        ("contract_items", f"contract_id IN (SELECT id FROM contracts WHERE {CONTRACT_TEST_CONDITION})"),
        ("contracts", CONTRACT_TEST_CONDITION),
    ]
    for table, condition in contract_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 报价单表（融合改造新增）：先删明细再删报价单头
    quotation_steps = [
        ("quotation_items", f"quotation_id IN (SELECT id FROM quotations WHERE {QUOTATION_TEST_CONDITION})"),
        ("quotations", QUOTATION_TEST_CONDITION),
    ]
    for table, condition in quotation_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 采购退货表（融合改造新增）：先删明细再删退货单头。
    # 退货单会产生 outbound 库存流水与 purchase_return 财务流水，删单头后
    # 这些流水会由孤儿扫描（ORPHAN_RULES 里 inventory_transactions.product_id
    # 与 financial_transactions.supplier_id）一并清掉。
    purchase_return_steps = [
        ("purchase_return_items", f"purchase_return_id IN (SELECT id FROM purchase_returns WHERE {PURCHASE_RETURN_TEST_CONDITION})"),
        ("purchase_returns", PURCHASE_RETURN_TEST_CONDITION),
    ]
    for table, condition in purchase_return_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 销售退货表（融合改造新增）：先删明细再删退货单头。
    # 退货单会产生 inbound 库存流水与 sales_return 财务流水，删单头后
    # 这些流水会由孤儿扫描（ORPHAN_RULES 里 inventory_transactions.product_id
    # 与 financial_transactions.customer_id）一并清掉。
    sales_return_steps = [
        ("sales_return_items", f"sales_return_id IN (SELECT id FROM sales_returns WHERE {SALES_RETURN_TEST_CONDITION})"),
        ("sales_returns", SALES_RETURN_TEST_CONDITION),
    ]
    for table, condition in sales_return_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 销售订单（2026-10-21 补）：先删明细、再删单头，最后扫它产生的流水。
    # 顺序有讲究：明细外键指向单头，流水按 doc_no 关联（单头删了 doc_no 还在，
    # 但已经没有单据可查，等于永久孤儿）。
    sales_order_steps = [
        ("sales_order_items", f"sales_order_id IN (SELECT id FROM sales_orders WHERE {SALES_ORDER_TEST_CONDITION})"),
        ("inventory_transactions", f"doc_no IN (SELECT order_no FROM sales_orders WHERE {SALES_ORDER_TEST_CONDITION})"),
        ("financial_transactions", f"doc_no IN (SELECT order_no FROM sales_orders WHERE {SALES_ORDER_TEST_CONDITION})"),
        ("sales_orders", SALES_ORDER_TEST_CONDITION),
    ]
    for table, condition in sales_order_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（销售订单签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（销售订单签名）", n))

    # 库存调拨表（融合改造新增）：先删明细再删调拨单头。调拨不写财务流水，
    # 但它会产生一对 inv_transfer 库存流水（调出 outbound / 调入 inbound），
    # 删单头后这些流水会由孤儿扫描（inventory_transactions.product_id）一并清掉。
    inventory_transfer_steps = [
        (
            "inventory_transfer_items",
            f"inventory_transfer_id IN (SELECT id FROM inventory_transfers WHERE {INVENTORY_TRANSFER_TEST_CONDITION})",
        ),
        ("inventory_transfers", INVENTORY_TRANSFER_TEST_CONDITION),
    ]
    for table, condition in inventory_transfer_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 盘点单 / 报损报溢单（融合改造新增）：先删明细再删单头。
    # 两者都是纯库存单据（不写财务流水），但会产生 inv_check / inv_scrap /
    # inv_overflow 库存流水。单头删掉后这些流水就成了孤儿，所以最后一条按
    # 单号签名（doc_no LIKE 'TEST-%'）把四类纯库存单据的流水一起扫干净 ——
    # 这条同时兜住了调拨历史遗留（调拨流水原先只能靠 product_id 孤儿规则清）。
    pure_stock_steps = [
        (
            "stocktaking_items",
            f"stocktaking_id IN (SELECT id FROM stocktakings WHERE {STOCKTAKING_TEST_CONDITION})",
        ),
        ("stocktakings", STOCKTAKING_TEST_CONDITION),
        (
            "inventory_adjustment_items",
            "inventory_adjustment_id IN "
            f"(SELECT id FROM inventory_adjustments WHERE {INVENTORY_ADJUSTMENT_TEST_CONDITION})",
        ),
        ("inventory_adjustments", INVENTORY_ADJUSTMENT_TEST_CONDITION),
        ("inventory_transactions", INVENTORY_DOC_TEST_CONDITION),
    ]
    for table, condition in pure_stock_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 生产计划单（第 3 批生产类新增）：先删明细再删计划头。计划单既不写库存
    # 也不写财务，所以除了自身两张表，没有需要连带清理的流水。
    production_plan_steps = [
        (
            "production_plan_items",
            "production_plan_id IN "
            f"(SELECT id FROM production_plans WHERE {PRODUCTION_PLAN_TEST_CONDITION})",
        ),
        ("production_plans", PRODUCTION_PLAN_TEST_CONDITION),
    ]
    for table, condition in production_plan_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 生产领料 / 退料单（第 3 批生产类新增）：先删明细再删单头。
    # 两者都是纯库存单据，会产生 production_issue / production_return 库存流水，
    # 单头删掉后再按单号签名把流水一并扫掉（INVENTORY_DOC_TEST_CONDITION 已含这两类）。
    material_steps = [
        (
            "material_issue_items",
            "material_issue_id IN "
            f"(SELECT id FROM material_issues WHERE {MATERIAL_ISSUE_TEST_CONDITION})",
        ),
        ("material_issues", MATERIAL_ISSUE_TEST_CONDITION),
        (
            "material_return_items",
            "material_return_id IN "
            f"(SELECT id FROM material_returns WHERE {MATERIAL_RETURN_TEST_CONDITION})",
        ),
        ("material_returns", MATERIAL_RETURN_TEST_CONDITION),
        ("inventory_transactions", INVENTORY_DOC_TEST_CONDITION),
    ]
    for table, condition in material_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 成品入库 / 委外加工单（第 3 批生产类新增，生产类收官）：先删明细再删单头。
    # 两者都**同时动库存与财务**：
    #   成品入库 → production_in 库存流水 + cost 成本结转流水
    #   委外加工 → outsourcing 两条库存流水（发料 outbound / 收成品 inbound）+ payable 加工费应付
    # 单头删掉后，库存流水按单号签名（INVENTORY_DOC_TEST_CONDITION 已含 production_in、
    # outsourcing 两类）扫净，财务流水按 FINANCE_DOC_TEST_STEPS 扫掉指向已删单据的孤儿。
    finished_outsourcing_steps = [
        (
            "finished_goods_receipt_items",
            "finished_goods_receipt_id IN "
            f"(SELECT id FROM finished_goods_receipts WHERE {FINISHED_GOODS_TEST_CONDITION})",
        ),
        ("finished_goods_receipts", FINISHED_GOODS_TEST_CONDITION),
        (
            "outsourcing_items",
            "outsourcing_order_id IN "
            f"(SELECT id FROM outsourcing_orders WHERE {OUTSOURCING_TEST_CONDITION})",
        ),
        ("outsourcing_orders", OUTSOURCING_TEST_CONDITION),
        ("inventory_transactions", INVENTORY_DOC_TEST_CONDITION),
    ] + FINANCE_DOC_TEST_STEPS + ASSEMBLY_DOC_TEST_STEPS
    for table, condition in finished_outsourcing_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（签名）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（签名）", n))

    # 现金银行 / 日常收支（第 8 批）+ 发票测试孤儿流水（历史欠账，本批补扫）。
    #
    # 这里的顺序是硬要求：
    #   1) 先删挂在测试账户名下的财务流水（既含人工登记的收支，也含转账的两条腿）
    #   2) 再删两端任一是测试账户的转账单
    #   3) 最后才删账户本身
    # 反过来的话，第 2、3 步的子查询就查不到账户了，流水会悬空留在库里。
    bank_accounts_sub = f"SELECT id FROM bank_accounts WHERE {BANK_ACCOUNT_TEST_CONDITION}"
    bank_steps = [
        (
            "financial_transactions",
            f"bank_account_id IN ({bank_accounts_sub})",
        ),
        (
            "bank_transfers",
            f"from_account_id IN ({bank_accounts_sub}) OR to_account_id IN ({bank_accounts_sub})",
        ),
        ("bank_accounts", BANK_ACCOUNT_TEST_CONDITION),
        # 发票测试流水：与本批的账户无关，独立按备注签名清
        ("financial_transactions", INVOICE_FLOW_TEST_CONDITION),
    ]
    for table, condition in bank_steps:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append((f"{table}（现金银行）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            continue
        total += n
        if n:
            applied.append((f"{table}（现金银行）", n))

    # 发票测试数据（第 11 批）：删行之前先把落盘的原件删掉，
    # 否则 data/invoices 里会留下再也对不上的文件。
    try:
        # 批量同步会给每张票写一条 expense 流水（备注「发票 INV-ODT-… | 对方单位」）。
        # 那条流水与"人工登记的日常支出"长得一模一样，会污染「日常收支」合计 —— 先删它。
        with engine.begin() as conn:
            n_flow = conn.execute(
                text(
                    # 发票同步出来的 expense 流水（备注「发票 <票号> | 对方单位 | …」）。
                    # ⚠️ 2026-10-22 补 `发票 INV-%`：pytest 夹具用 `INV-<8hex>` 建票，
                    #    票删了但同步流水还在，FT 会凭空多出 8 行（实测）。
                    #    真实票号是 20 位纯数字，不会以 `INV-` 开头，这条签名不会误伤。
                    "DELETE FROM financial_transactions WHERE note LIKE '发票 INV-%' "
                    "OR note LIKE '发票 DBG-%' OR note LIKE '发票 TEST-%'"
                )
            ).rowcount
        total += n_flow
        if n_flow:
            applied.append(("financial_transactions（发票流水）", n_flow))
        with engine.connect() as conn:
            test_files = [
                row[0]
                for row in conn.execute(
                    text(f"SELECT source_path FROM invoices WHERE {INVOICE_TEST_CONDITION} AND source_path IS NOT NULL")
                )
            ]
        from app.core import file_storage as _fs

        removed_files = sum(1 for rel in test_files if _fs.delete_file(rel))
        with engine.begin() as conn:
            n = conn.execute(text(f"DELETE FROM invoices WHERE {INVOICE_TEST_CONDITION}")).rowcount
        total += n
        if n:
            applied.append(("invoices（发票）", n))
        if removed_files and verbose:
            print(f"  {'invoices 原件':<34} 删除 {removed_files:>5} 个文件")
    except Exception as exc:
        skipped.append(("invoices（发票）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))

    # 单据归档台账（P0-5）：测试产生的归档行按**单号签名**清掉。
    #
    # 为什么必须清：归档表只增不减（真实业务就该如此）。测试每跑一轮都会作废几张
    # TEST-* / SO-<hex> / INV-<hex> 的测试单，不清的话这表会被测试噪音长期占着，
    # 以后真查生产记录还得先过滤一遍测试单号。
    # 只认测试签名：真实单号是 XS/CGTH/CGTH+DATE+流水、票号是 20 位数字，不会命中。
    try:
        with engine.begin() as conn:
            n = conn.execute(
                text(
                    "DELETE FROM document_archives WHERE doc_no LIKE 'TEST-%' "
                    "OR doc_no LIKE 'SO-%' OR doc_no LIKE 'INV-%' OR doc_no LIKE 'TMP-%'"
                )
            ).rowcount
        total += n
        if n:
            applied.append(("document_archives（归档台账）", n))
    except Exception as exc:
        skipped.append(
            ("document_archives（归档台账）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}")
        )

    # 孤儿发票 / 孤儿发票流水（2026-10-22）。
    #
    # ⚠️ 这里**不能**按票号签名删：`一键开票` 生成的 `KP-<单号>` 是**真实业务数据**，
    #    只是测试时它挂的单据被删了才悬空。所以判据是"指向的对方不存在"，
    #    与票号长什么样无关 —— 生产库里跑也只会删真正坏掉的记录。
    #    顺序不能反：先删孤儿发票，再删"票号已经不存在"的流水。
    try:
        with engine.begin() as conn:
            n_inv = conn.execute(
                text(
                    "DELETE FROM invoices i WHERE i.related_order_id IS NOT NULL AND ("
                    " (i.direction = 'output' AND NOT EXISTS "
                    "   (SELECT 1 FROM sales_orders o WHERE o.id = i.related_order_id))"
                    " OR (i.direction <> 'output' AND NOT EXISTS "
                    "   (SELECT 1 FROM purchase_orders o WHERE o.id = i.related_order_id))"
                    ")"
                )
            ).rowcount
            n_flow = conn.execute(
                text(
                    # 发票同步出来的流水，票号写在 note 里（「发票 <票号> | 对方 | …」）。
                    # 票没了这条流水就是纯噪音，会把「日常收支」的合计撑大。
                    "DELETE FROM financial_transactions f WHERE f.note LIKE '发票 %' "
                    "AND NOT EXISTS (SELECT 1 FROM invoices v "
                    f"  WHERE v.invoice_no = split_part(substr(f.note, {len('发票 ')} + 1), ' |', 1))"
                )
            ).rowcount
        total += n_inv + n_flow
        if n_inv:
            applied.append(("invoices（孤儿·挂单已删）", n_inv))
        if n_flow:
            applied.append(("financial_transactions（孤儿·发票流水）", n_flow))
    except Exception as exc:
        skipped.append(("invoices（孤儿）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))

    # 对账单测试数据：先删明细再删单头（statement_items.statement_id 是硬引用），
    # 事务顺序反过来会因外键/悬空明细留下"点开就报错"的空壳对账单。
    try:
        with engine.begin() as conn:
            n_items = conn.execute(
                text(
                    "DELETE FROM statement_items WHERE statement_id IN "
                    f"(SELECT id FROM statements WHERE {STATEMENT_TEST_CONDITION})"
                )
            ).rowcount
            n_stmt = conn.execute(
                text(f"DELETE FROM statements WHERE {STATEMENT_TEST_CONDITION}")
            ).rowcount
        total += n_items + n_stmt
        if n_stmt:
            applied.append(("statements（对账单）", n_stmt))
        if n_items:
            applied.append(("statement_items（对账明细）", n_items))
    except Exception as exc:
        skipped.append(("statements（对账单）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))

    # 菜单（第 10 批）：自引用树，从叶子往上删。最多循环 MAX_MENU_DEPTH 轮就够了，
    # 多留一轮是因为"删完叶子后父节点才变成叶子"这件事需要下一轮才看得到。
    for _round in range(MAX_MENU_DEPTH + 2):
        sql = (
            "DELETE FROM menus WHERE "
            f"{MENU_TEST_CONDITION} AND id NOT IN "
            "(SELECT parent_id FROM menus WHERE parent_id IS NOT NULL)"
        )
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            skipped.append(("menus（菜单）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
            break
        total += n
        if n:
            applied.append(("menus（菜单）", n))
        if not n:
            break

    if verbose:
        for label, n in applied:
            print(f"  {label:<34} 删除 {n:>5} 行")
        for label, reason in skipped:
            print(f"  {label:<34} 跳过（{reason}）")

    # 总账凭证（第 12 批）：凭证与财务流水「同生共死」，流水删掉后凭证必须一并清掉。
    #
    # 为什么靠 flow_id 而不是 related_type：人工收支（income/expense）的 related_type
    # 是空的，删掉后没有任何单据关联可判断；而凭证上现在挂了源流水的 flow_id，
    # 流水没了、flow_id 指向空就是孤儿，判据最干净。分录是凭证的明细，先删分录再删凭证。
    try:
        with engine.begin() as conn:
            n_lines = conn.execute(
                text(
                    "DELETE FROM journal_entry_lines WHERE entry_id IN "
                    "(SELECT id FROM journal_entries WHERE flow_id IS NOT NULL "
                    "AND flow_id NOT IN (SELECT id FROM financial_transactions))"
                )
            ).rowcount
            n_entries = conn.execute(
                text(
                    "DELETE FROM journal_entries WHERE flow_id IS NOT NULL "
                    "AND flow_id NOT IN (SELECT id FROM financial_transactions)"
                )
            ).rowcount
        total += n_entries
        if n_lines:
            applied.append(("journal_entry_lines（凭证分录）", n_lines))
        if n_entries:
            applied.append(("journal_entries（凭证）", n_entries))
    except Exception as exc:
        skipped.append(("journal_entries（凭证）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))

    # 档案删完后，原来挂在它们下面的单据/流水就成了孤儿，一并扫掉
    total += run_orphan_cleanup(verbose=verbose)

    # 孤儿财务流水（指向已删单据的应收应付）单独再扫一遍
    for table, condition in ORPHAN_FINANCE_STEPS:
        sql = f"DELETE FROM {table} WHERE {condition}"
        try:
            with engine.begin() as conn:
                n = conn.execute(text(sql)).rowcount
        except Exception as exc:
            if verbose:
                print(f"  {table}（孤儿财务）{'':<12} 跳过（{type(exc).__name__}: {str(exc).splitlines()[0][:70]}）")
            continue
        total += n
        if n and verbose:
            print(f"  {table}（孤儿财务）{'':<12} 删除 {n:>5} 行")

    # ── 仓库延后处理（2026-10-15 补）────────────────────────────────────────
    # 为什么不能跟 products/customers/suppliers 一起放进上面的 steps：
    # 测试造的单据（入库单、盘点单、调拨单…）在 steps 阶段**还挂在测试仓库上**，
    # 引用保护会把仓库判成「被业务引用」而豁免它；单据要到后面的孤儿清理才被删掉。
    # 结果是仓库被漏过这一轮，下一轮跑测试又漏一批 —— 库里的残留就是这么攒到 115 个的。
    # 典型症状（当时就是这么发现的）：全量 pytest 后漏 13 个，单跑某几个测试却正常。
    # 所以这里**等所有引用方都清完之后**，重新扫一遍候选、重新判引用，再删。
    with engine.connect() as conn:
        _, _, _, w_ids_late = collect_ids(conn, report_protected=False)
    if w_ids_late:
        wl = ",".join(map(str, w_ids_late))
        try:
            with engine.begin() as conn:
                n = conn.execute(text(f"DELETE FROM warehouses WHERE id IN ({wl})")).rowcount
        except Exception as exc:
            skipped.append(("warehouses（延后）", f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))
        else:
            total += n
            if n:
                applied.append(("warehouses（延后）", n))
                if verbose:
                    print(f"  {'warehouses（延后）':<34} 删除 {n:>5} 行")

    return total


def count_orphans(conn) -> dict[str, int]:
    """统计孤儿记录（不改数据）。"""
    result: dict[str, int] = {}
    for table, column, ref_table, ref_col in ORPHAN_RULES:
        try:
            n = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL "
                f"AND {column} NOT IN (SELECT {ref_col} FROM {ref_table})"
            )).scalar()
        except Exception:
            continue
        if n:
            result[f"{table}.{column}"] = n
    return result


def count_system_residue(conn) -> dict[str, int]:
    """测试账号 / 角色 / 部门 / 操作日志的残留计数。

    这几类以前不在预览的 has_work 判断里 —— 只剩它们时预览会误报"没有测试残留"，
    而 `--apply` 其实会照删。补上，让预览与实做一致。
    """
    checks = [
        ("用户", f"SELECT COUNT(*) FROM users WHERE {SYSTEM_USER_TEST_CONDITION}"),
        ("角色", f"SELECT COUNT(*) FROM roles WHERE {SYSTEM_ROLE_TEST_CONDITION}"),
        ("部门", f"SELECT COUNT(*) FROM departments WHERE {SYSTEM_DEPT_TEST_CONDITION}"),
        ("日志", f"SELECT COUNT(*) FROM operation_logs WHERE {LOG_TEST_CONDITION}"),
    ]
    result: dict[str, int] = {}
    for label, sql in checks:
        try:
            count = conn.execute(text(sql)).scalar() or 0
        except Exception:
            continue
        if count:
            result[label] = int(count)
    return result


def count_invoice_residue(conn) -> dict[str, int]:
    """测试残留的发票记录计数（第 11 批）。"""
    try:
        count = conn.execute(text(f"SELECT COUNT(*) FROM invoices WHERE {INVOICE_TEST_CONDITION}")).scalar() or 0
    except Exception:
        return {}
    return {"发票": int(count)} if count else {}


def count_menu_residue(conn) -> dict[str, int]:
    """测试残留的菜单节点计数（第 10 批）。

    菜单树是展示数据，残留会直接出现在用户侧边栏里，所以预览必须能看到它 ——
    预览与实做不一致就等于骗自己。
    """
    try:
        count = conn.execute(text(f"SELECT COUNT(*) FROM menus WHERE {MENU_TEST_CONDITION}")).scalar() or 0
    except Exception:
        return {}
    return {"菜单节点": int(count)} if count else {}


def count_cash_residue(conn) -> dict[str, int]:
    """现金银行 / 发票流水残留计数（第 8 批）。

    以前这几类不在预览里，只剩它们时预览会显示"没有测试残留"、`--apply` 却照删 ——
    预览和实做必须一致，否则等于骗自己。
    """
    sub = f"SELECT id FROM bank_accounts WHERE {BANK_ACCOUNT_TEST_CONDITION}"
    checks = [
        ("资金账户", f"SELECT COUNT(*) FROM bank_accounts WHERE {BANK_ACCOUNT_TEST_CONDITION}"),
        ("账户流水", f"SELECT COUNT(*) FROM financial_transactions WHERE bank_account_id IN ({sub})"),
        (
            "账户转账",
            f"SELECT COUNT(*) FROM bank_transfers "
            f"WHERE from_account_id IN ({sub}) OR to_account_id IN ({sub})",
        ),
        ("发票流水", f"SELECT COUNT(*) FROM financial_transactions WHERE {INVOICE_FLOW_TEST_CONDITION}"),
    ]
    result: dict[str, int] = {}
    for label, sql in checks:
        try:
            count = conn.execute(text(sql)).scalar() or 0
        except Exception:
            continue
        if count:
            result[label] = int(count)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只预览）")
    args = parser.parse_args()

    with engine.connect() as conn:
        p_ids, c_ids, s_ids, w_ids = collect_ids(conn)
        e_ids = collect_employee_ids(conn)
        sys_counts = count_system_residue(conn)
        cash_counts = count_cash_residue(conn)
        menu_counts = count_menu_residue(conn)
        invoice_counts = count_invoice_residue(conn)
        orphans = count_orphans(conn)

    print("=" * 62)
    print("测试残留扫描结果（按编码签名/名称识别）")
    print("=" * 62)
    print(f"  products   {len(p_ids):>4} 条")
    print(f"  customers  {len(c_ids):>4} 条")
    print(f"  suppliers  {len(s_ids):>4} 条")
    print(f"  warehouses {len(w_ids):>4} 条")
    print(f"  employees  {len(e_ids):>4} 条")
    for label, n in sys_counts.items():
        print(f"  {label:<11}{n:>4} 条")
    for label, n in cash_counts.items():
        print(f"  {label:<11}{n:>4} 条")
    for label, n in menu_counts.items():
        print(f"  {label:<11}{n:>4} 条")
    for label, n in invoice_counts.items():
        print(f"  {label:<11}{n:>4} 条")

    if orphans:
        print("\n孤儿记录（挂在已删除档案下面的单据/流水）：")
        for label, n in sorted(orphans.items()):
            print(f"  {label:<34} {n:>5} 条")

    has_work = (
        any((p_ids, c_ids, s_ids, w_ids, e_ids))
        or bool(orphans)
        or any(sys_counts.values())
        or any(cash_counts.values())
        or any(menu_counts.values())
        or any(invoice_counts.values())
    )
    if not has_work:
        print("\n没有测试残留，无需清理。")
    elif not args.apply:
        print("\n（预览模式，未做任何修改。加 --apply 执行清理）")
    else:
        print("\n执行清理：")
        total = run_cleanup(verbose=True)
        print(f"  {'合计':<34} 删除 {total:>5} 行")
        print("\n清理后关键表行数：")
        with engine.connect() as conn:
            for t in ["products", "customers", "suppliers", "warehouses", "bank_accounts", "bank_transfers"]:
                n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                print(f"  {t:<14} {n}")

    # 未自动删除、但编码形态可疑的记录 —— 仅提示，绝不自动删
    with engine.connect() as conn:
        odd = list_unmatched(conn)
        suspicious_wh = list_suspicious_warehouses(conn)
    if odd:
        print("\n" + "-" * 62)
        print("以下记录不符合测试签名，未自动删除，请人工确认是否要保留：")
        for table, rid, code, name in odd:
            print(f"  {table:<10} id={rid:<6} code={code!r:<20} name={name!r}")
    if suspicious_wh:
        print("\n" + "-" * 62)
        print("⚠️  下列仓库的编码尾部是 8 位 hex（机器生成形态），却没被任何签名认出来。")
        print("    没删它们是对的，但请确认原因：")
        print("      · 被真实业务引用（正常，见上面 [clean] 那行）")
        print("      · 清理规则又漏了 —— 那就该把名字或编码形态补进 clean_test_data.py")
        for table, rid, code, name in suspicious_wh:
            print(f"    {table:<10} id={rid:<6} code={code!r:<24} name={name!r}")


if __name__ == "__main__":
    main()
