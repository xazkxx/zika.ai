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
    "状态更新产品%", "分析产品%", "%演示%", "探针%", "%--DEMO--%",
)
PRODUCT_NAME_EXACT = ("主机产品", "CPU模块")
CUSTOMER_NAME_LIKE = (
    "%测试客户%", "分析客户%", "订单客户%", "状态客户%", "%演示%", "探针%", "%--DEMO--%",
)
SUPPLIER_NAME_LIKE = ("%测试供应商%", "订单供应商%", "%演示%", "探针%", "%--DEMO--%")

# 仓库：只删测试生成的（WH-8位hex），保护 WH-001 这类正式编码
WAREHOUSE_NAME_LIKE = ("主仓库%", "一号仓%", "停用仓%", "主仓%")
WAREHOUSE_CODE_RE = r"^WH-[0-9a-f]{8}$"


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


def run_cleanup(verbose: bool = True) -> int:
    """删除测试残留，返回删除总行数。"""
    with engine.connect() as conn:
        p_ids, c_ids, s_ids, w_ids = collect_ids(conn)

    if not any((p_ids, c_ids, s_ids, w_ids)):
        if verbose:
            print("  没有按签名识别到的测试档案，直接扫孤儿记录。")

    pc = ",".join(map(str, p_ids)) or "NULL"
    cc = ",".join(map(str, c_ids)) or "NULL"
    sc = ",".join(map(str, s_ids)) or "NULL"
    wc = ",".join(map(str, w_ids)) or "NULL"

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

    if verbose:
        for label, n in applied:
            print(f"  {label:<34} 删除 {n:>5} 行")
        for label, reason in skipped:
            print(f"  {label:<34} 跳过（{reason}）")

    # 档案删完后，原来挂在它们下面的单据/流水就成了孤儿，一并扫掉
    total += run_orphan_cleanup(verbose=verbose)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认只预览）")
    args = parser.parse_args()

    with engine.connect() as conn:
        p_ids, c_ids, s_ids, w_ids = collect_ids(conn)
        orphans = count_orphans(conn)

    print("=" * 62)
    print("测试残留扫描结果（按编码签名/名称识别）")
    print("=" * 62)
    print(f"  products   {len(p_ids):>4} 条")
    print(f"  customers  {len(c_ids):>4} 条")
    print(f"  suppliers  {len(s_ids):>4} 条")
    print(f"  warehouses {len(w_ids):>4} 条")

    if orphans:
        print("\n孤儿记录（挂在已删除档案下面的单据/流水）：")
        for label, n in sorted(orphans.items()):
            print(f"  {label:<34} {n:>5} 条")

    has_work = any((p_ids, c_ids, s_ids, w_ids)) or bool(orphans)
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
