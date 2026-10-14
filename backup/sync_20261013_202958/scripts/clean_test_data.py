"""清理 pytest 测试套件在正式库里留下的测试档案。

背景：测试直接连正式数据库（PostgreSQL），每跑一次 pytest 就会新建一批
测试档案。以前这些数据跑完就留在库里，累积之后会污染业务列表，也让依赖
分页的断言变得不稳定。

识别规则（两道，取并集）：
  1. 编码签名 —— 测试脚本用 uuid 生成编码，形态固定且与业务编码不重叠：
       products : SKU-<组>-<8位hex>   例如 SKU-PERF-dbd7c4f7
       customers: CUST-<组>-<8位hex>  例如 CUST-ORDER-3b5a6ba2
       suppliers: SUP-<8位hex>        例如 SUP-7639f1ac
     另外兼容演示脚本的 DEMO-* / ZZ-TEST-*。
  2. 名称黑名单 —— 测试脚本写死的档案名（含中文），如「测试产品」「分析客户A」。

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

# ── 规则 1：编码签名（主要依据，覆盖 uuid 生成的全部测试档案）────────────────
PRODUCT_CODE_RE = r"^(SKU(-[A-Z]+)?-[0-9a-f]{8}|DEMO-P\d+|SKU-[A-Z]+-\d+)$"
CUSTOMER_CODE_RE = r"^(CUST(-[A-Z]+)?-[0-9a-f]{8}|CUST-ANALYSIS-\d+|DEMO-C\d+|ZZ-TEST-.*)$"
SUPPLIER_CODE_RE = r"^(SUP(-[A-Z]+)?-[0-9a-f]{8}|DEMO-S\d+)$"

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

# 仓库：只删测试生成的（WH-8位hex），保护 WH-001 这类正式编码
WAREHOUSE_NAME_LIKE = ("主仓库%", "一号仓%", "停用仓%", "主仓%")
WAREHOUSE_CODE_RE = r"^WH-[0-9a-f]{8}$"
# 员工档案（基础资料收尾）：工号签名
EMPLOYEE_CODE_RE = r"^(EMP(-[A-Z]+)?-[0-9a-f]{8}|TEST-EMP-.*)$"
EMPLOYEE_NAME_LIKE = ("%测试员工%", "%验收员工%", "%导入员工%", "%校验员工%", "%引用检查员工%", "%部门占用员工%")


def collect_ids(conn):
    """返回 (product_ids, customer_ids, supplier_ids, warehouse_ids)。"""
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
        text("SELECT id FROM warehouses WHERE (name LIKE ANY(:n) AND code ~ :re)"),
        {"n": list(WAREHOUSE_NAME_LIKE), "re": WAREHOUSE_CODE_RE})]
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


# 依赖档案的从属表：档案被删后，这些行就成了「孤儿」（界面上只能显示成空壳）
ORPHAN_RULES = [
    ("sales_order_items", "sales_order_id", "sales_orders", "id"),
    ("purchase_order_items", "purchase_order_id", "purchase_orders", "id"),
    ("contract_items", "contract_id", "contracts", "id"),
    ("quotation_items", "quotation_id", "quotations", "id"),
    ("purchase_return_items", "purchase_return_id", "purchase_returns", "id"),
    ("sales_return_items", "sales_return_id", "sales_returns", "id"),
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
    wc = ",".join(map(str, w_ids)) or "NULL"
    ec = ",".join(map(str, e_ids)) or "NULL"

    # 先删"引用方"（明细、流水、单据），再删"被引用方"（档案），顺序不能颠倒
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
        ("archive", "warehouses", "id", wc),
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
    ] + FINANCE_DOC_TEST_STEPS
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

    if verbose:
        for label, n in applied:
            print(f"  {label:<34} 删除 {n:>5} 行")
        for label, reason in skipped:
            print(f"  {label:<34} 跳过（{reason}）")

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只预览）")
    args = parser.parse_args()

    with engine.connect() as conn:
        p_ids, c_ids, s_ids, w_ids = collect_ids(conn)
        e_ids = collect_employee_ids(conn)
        sys_counts = count_system_residue(conn)
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

    if orphans:
        print("\n孤儿记录（挂在已删除档案下面的单据/流水）：")
        for label, n in sorted(orphans.items()):
            print(f"  {label:<34} {n:>5} 条")

    has_work = any((p_ids, c_ids, s_ids, w_ids, e_ids)) or bool(orphans) or any(sys_counts.values())
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
            for t in ["products", "customers", "suppliers", "warehouses"]:
                n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                print(f"  {t:<14} {n}")

    # 未自动删除、但编码形态可疑的记录 —— 仅提示，绝不自动删
    with engine.connect() as conn:
        odd = list_unmatched(conn)
    if odd:
        print("\n" + "-" * 62)
        print("以下记录不符合测试签名，未自动删除，请人工确认是否要保留：")
        for table, rid, code, name in odd:
            print(f"  {table:<10} id={rid:<6} code={code!r:<20} name={name!r}")


if __name__ == "__main__":
    main()
