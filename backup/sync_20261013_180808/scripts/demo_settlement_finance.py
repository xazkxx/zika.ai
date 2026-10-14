"""端到端演练脚本：验证「单据结算链 + 欠款链 + 财务联动 + 对账单」。

用法（先启动后端，例如端口 8010）：
    .venv\\Scripts\\python.exe scripts\\demo_settlement_finance.py
    .venv\\Scripts\\python.exe scripts\\demo_settlement_finance.py --port 8010

脚本会自动创建演示数据、跑完整流程、打印对账单，最后清理演示数据，
不会触碰库里已有的真实数据。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# 允许直接以 scripts/xxx.py 方式运行：把项目根目录加进模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import bindparam, text  # noqa: E402

from app.db.session import engine  # noqa: E402

# 本机若设有 HTTP 代理，会让 127.0.0.1 的回环请求被代理劫持返回 502，这里显式绕开
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

TAG = "【演示】"
# 演示数据统一用这个前缀，方便反复运行时清理，绝不误伤真实数据
CODE_PREFIX = "DEMO-"


def cleanup_demo_data() -> None:
    """按编码前缀清理演示数据。开头和结尾各调一次，保证脚本可重复运行、不留残渣。"""
    with engine.begin() as conn:
        customer_ids = [r[0] for r in conn.execute(text("SELECT id FROM customers WHERE code LIKE 'DEMO-%'"))]
        supplier_ids = [r[0] for r in conn.execute(text("SELECT id FROM suppliers WHERE code LIKE 'DEMO-%'"))]

        order_ids: list[int] = []
        if customer_ids:
            order_ids = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM sales_orders WHERE customer_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": customer_ids},
                )
            ]
        purchase_ids: list[int] = []
        if supplier_ids:
            purchase_ids = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM purchase_orders WHERE supplier_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": supplier_ids},
                )
            ]

        for table, column, values in (
            ("sales_order_items", "sales_order_id", order_ids),
            ("purchase_order_items", "purchase_order_id", purchase_ids),
            ("sales_orders", "id", order_ids),
            ("purchase_orders", "id", purchase_ids),
        ):
            if values:
                conn.execute(
                    text(f"DELETE FROM {table} WHERE {column} IN :ids").bindparams(bindparam("ids", expanding=True)),
                    {"ids": values},
                )

        conn.execute(
            text(
                "DELETE FROM financial_transactions WHERE customer_id IN :ids OR supplier_id IN :sids"
            ).bindparams(bindparam("ids", expanding=True), bindparam("sids", expanding=True)),
            {"ids": customer_ids or [-1], "sids": supplier_ids or [-1]},
        )
        conn.execute(text("DELETE FROM products WHERE sku LIKE 'DEMO-%'"))
        conn.execute(text("DELETE FROM customers WHERE code LIKE 'DEMO-%'"))
        conn.execute(text("DELETE FROM suppliers WHERE code LIKE 'DEMO-%'"))
        conn.execute(text("DELETE FROM warehouses WHERE code LIKE 'DEMO-%'"))


def make_caller(port: int):
    base = f"http://127.0.0.1:{port}/api/v1"

    def call(method: str, path: str, body=None):
        request = urllib.request.Request(
            base + path,
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with _opener.open(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    return call


def line(width: int = 78) -> None:
    print("   " + "─" * width)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    call = make_caller(args.port)

    cleanup_demo_data()  # 清掉上次异常退出可能留下的残渣

    customer = call(
        "POST",
        "/customers",
        {
            "code": "DEMO-C001",
            "name": TAG + "某某贸易公司",
            "init_receivable": 2000.0,
            "contact": "王经理",
            "contact_phone": "13800001111",
            "address": "深圳市宝安区新安街道",
        },
    )
    supplier = call("POST", "/suppliers", {"code": "DEMO-S001", "name": TAG + "某某纸业", "contact": "李经理"})
    warehouse = call(
        "POST", "/warehouses", {"code": "DEMO-W001", "name": TAG + "主仓", "location": "A区01", "manager": "张三"}
    )
    paper = call(
        "POST",
        "/products",
        {
            "sku": "DEMO-P001",
            "name": TAG + "A4打印纸",
            "unit": "箱",
            "standards": "80g/500张",
            "sale_price": 120.0,
            "purchase_price": 90.0,
            "stock_lower": 10,
            "stock_upper": 500,
        },
    )
    pen = call(
        "POST",
        "/products",
        {"sku": "DEMO-P002", "name": TAG + "中性笔", "unit": "盒", "standards": "0.5mm黑", "sale_price": 60.0},
    )

    print("① 单号自动生成 + 结算链 + 欠款链")
    line()
    sales_1 = call(
        "POST",
        "/sales-orders",
        {
            "customer_id": customer["id"],
            "warehouse_id": warehouse["id"],
            "businesser": "赵销售",
            "order_date": "2026-10-01",
            "delivery_date": "2026-10-03",
            "payment_method": "月结30天",
            "items": [
                {"product_id": paper["id"], "quantity": 10, "unit_price": 120.0},
                {"product_id": pen["id"], "quantity": 20, "unit_price": 60.0},
            ],
            "discount_amount": 150.0,
        },
    )
    print(
        f"   {sales_1['order_no']}  应收={sales_1['receivable_amount']:>8.2f}  优惠={sales_1['discount_amount']:>7.2f}"
        f"  实收={sales_1['received_amount']:>7.2f}  本次欠={sales_1['current_debt']:>8.2f}"
        f"  前次欠={sales_1['prev_debt']:>7.2f}  累欠={sales_1['total_debt']:>8.2f}"
    )
    sales_2 = call(
        "POST",
        "/sales-orders",
        {
            "customer_id": customer["id"],
            "warehouse_id": warehouse["id"],
            "businesser": "赵销售",
            "order_date": "2026-10-08",
            "items": [{"product_id": pen["id"], "quantity": 5, "unit_price": 60.0}],
        },
    )
    print(
        f"   {sales_2['order_no']}  应收={sales_2['receivable_amount']:>8.2f}  优惠={sales_2['discount_amount']:>7.2f}"
        f"  实收={sales_2['received_amount']:>7.2f}  本次欠={sales_2['current_debt']:>8.2f}"
        f"  前次欠={sales_2['prev_debt']:>7.2f}  累欠={sales_2['total_debt']:>8.2f}"
    )
    purchase = call(
        "POST",
        "/purchase-orders",
        {
            "supplier_id": supplier["id"],
            "warehouse_id": warehouse["id"],
            "businesser": "采购员甲",
            "order_date": "2026-10-02",
            "payment_method": "货到付款",
            "items": [{"product_id": paper["id"], "quantity": 50, "unit_price": 90.0}],
        },
    )
    print(f"   {purchase['order_no']}  应付={purchase['payable_amount']:>8.2f}  累欠={purchase['total_debt']:>8.2f}")
    print(
        f"   明细快照自动补齐 → {sales_1['items'][0]['product_name']} / "
        f"{sales_1['items'][0]['standards']} / {sales_1['items'][0]['unit']}"
    )

    print()
    print("② 收款登记（自动冲减应收 + 重算整条欠款链）")
    line()
    call(
        "POST",
        "/finance/receipt",
        {
            "party_id": customer["id"],
            "amount": 2500.0,
            "order_id": sales_1["id"],
            "occurred_at": "2026-10-10",
            "note": "银行转账收款",
        },
    )
    orders = {row["id"]: row for row in call("GET", "/sales-orders?limit=500")}
    print(
        f"   收 2500 后：{orders[sales_1['id']]['order_no']} 实收={orders[sales_1['id']]['received_amount']:.2f}"
        f" 累欠={orders[sales_1['id']]['total_debt']:.2f}"
    )
    print(
        f"               {orders[sales_2['id']]['order_no']} 前次欠款自动跟降到 "
        f"{orders[sales_2['id']]['prev_debt']:.2f}，累欠={orders[sales_2['id']]['total_debt']:.2f}"
    )

    print()
    print("③ 客户对账单 B1（模板数据已备好，可直接打印）")
    line()
    recon = call(
        "GET", f"/finance/reconciliation/customer/{customer['id']}?from_date=2026-10-01&to_date=2026-10-31"
    )
    summary = recon["summary"]
    print(f"   {recon['title']}　　对账期间：{recon['period']['from']} 至 {recon['period']['to']}")
    print(f"   往来单位：{recon['party']['name']}　联系人：{recon['party']['contact']} {recon['party']['contact_phone']}")
    header = f"   {'日期':<12}{'单据号':<15}{'摘要':<24}{'增加':>11}{'减少':>11}{'余额':>11}"
    print(header)
    print("   " + "-" * 76)
    for row in recon["rows"]:
        print(
            f"   {row['date']:<12}{row['doc_no']:<15}{(row['summary'] or '')[:22]:<24}"
            f"{row['increase']:>11.2f}{row['decrease']:>11.2f}{row['balance']:>11.2f}"
        )
    print(
        f"   期初 {summary['opening_balance']:.2f} ＋ 本期增加 {summary['increase_total']:.2f}"
        f" － 本期减少 {summary['decrease_total']:.2f} ＝ 期末 {summary['closing_balance']:.2f}"
    )
    print(f"   合计金额（大写）：{summary['closing_balance_upper']}")

    print()
    print("④ 供应商对账单 B2 / 账龄 / 期间利润")
    line()
    recon_supplier = call("GET", f"/finance/reconciliation/supplier/{supplier['id']}")
    print(
        f"   {recon_supplier['title']}　{recon_supplier['party']['name']}　期末应付 "
        f"{recon_supplier['summary']['closing_balance']:.2f}"
        f"（{recon_supplier['summary']['closing_balance_upper']}）"
    )
    aging = call("GET", "/finance/aging?party_type=customer")
    print(f"   账龄（截至 {aging['as_of']}）：" + "　".join(f"{k} {v:.2f}" for k, v in aging["buckets"].items()))
    period = call("GET", "/finance/period-summary?period=2026-10")
    print(
        f"   2026-10 期间：销售={period['sales_amount']:.2f} 收款={period['receipt_amount']:.2f}"
        f" 采购={period['cost_amount']:.2f} 付款={period['payment_amount']:.2f} 毛利={period['gross_profit']:.2f}"
    )

    print()
    print("⑤ 单据自动生成的财务流水（人工一行没录）")
    line()
    records = [
        row
        for row in call("GET", "/finance?limit=500")
        if row.get("related_type") in ("sales_out", "purchase_in")
    ]
    for row in records[-4:]:
        print(
            f"   [{row['period']}] {row['transaction_type']:<11} {row['direction']:<4}"
            f"{row['amount']:>10.2f}  {row['doc_no']:<15} ← {row['related_type']}"
        )

    cleanup_demo_data()

    print()
    print("（演示数据已清理，库里已有真实数据未被触碰）")


if __name__ == "__main__":
    main()
