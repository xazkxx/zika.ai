# -*- coding: utf-8 -*-
"""
金额精度升级（第三阶段）· 接口级验收 —— 真后端、真库、可重复跑。

## 这一台在验什么

不是"能跑通"，而是"**分钱没有漂**"。四组：

  A. 销售出库：73.901 × 580
     · 行金额 = 42,862.58（不是 42,862.00，也不是 42,862.579999…）
     · 单价原样 73.901（**不许**被抹成 73.90 —— 那一抹单张少 6 毛）
     · JSON 里是**数字** 42862.58（pydantic 的 Decimal 默认会序列化成字符串
       "42862.58"，前端 `a + b` 会变字符串拼接、`.toFixed` 直接报错）
     · 落库后再读回来（GET 详情）仍然是同一个数

  B. 采购入库：同口径验证（采购侧走的是另一份路由代码）

  C. 收款冲减 + 红冲：这是"Decimal 与 float 混算"最容易炸的地方 ——
     DB 改 numeric 后读出来是 Decimal，路由里但凡有一个 `round(float(...))`
     漏网，这里就 500。所以这一组是**开关是否真的切完**的探针。

  D. 四舍五入是"业务四舍五入"而不是"银行家舍入"
     1.005 × 3：ROUND_HALF_UP → 3.02；Python 的 round() / JS 的 toFixed 都会给 3.01

## 跑法

    .venv/Scripts/python.exe scripts/verify_money_precision.py
    ERP_BASE=http://127.0.0.1:8010 .venv/Scripts/python.exe scripts/verify_money_precision.py

临时单据测完就删（删单会一并回退库存流水与财务流水），不会在库里留垃圾。
"""
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("ERP_BASE", "http://127.0.0.1:8011").rstrip("/")
API = BASE + "/api/v1"

RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  — " + str(extra)) if extra else ""))


class Client:
    """最小 HTTP 客户端：自己拼 Authorization，不依赖 requests。"""

    def __init__(self):
        self.token = ""

    def call(self, method, path, body=None, raw=False):
        url = API + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # 这台机器有 HTTP_PROXY=127.0.0.1:10679，不显式禁用连 localhost 都会走代理
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPRedirectHandler(),
        )
        try:
            with opener.open(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
                return resp.status, (text if raw else (json.loads(text) if text else None))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, (text if raw else json.loads(text))
            except json.JSONDecodeError:
                return exc.code, text

    def login(self):
        status, data = self.call(
            "POST", "/auth/login", {"username": "admin", "password": "Admin123"}
        )
        if status != 200:
            raise SystemExit(f"登录失败 HTTP {status}: {data}")
        self.token = data["access_token"]


def detail(resp):
    if isinstance(resp, dict):
        return str(resp.get("detail") or resp)[:200]
    return str(resp)[:200]


def items_of(resp):
    """列表接口返回 `{items, summary}`，别当数组用。"""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict) and isinstance(resp.get("items"), list):
        return resp["items"]
    return []


def is_number(value):
    """JSON 里必须是数字（int/float）。字符串 "42862.58" 会被前端当字符串拼。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ── 直连库的小工具：只读，用来确认"落库之后还是不是那个数"──────────────
from db_config import psycopg_dsn  # noqa: E402

DSN = os.environ.get("ERP_DSN") or psycopg_dsn()
DEC = __import__("decimal").Decimal


def db_scalar(sql, params=()):
    """查一个标量。psycopg 返回 Decimal（numeric 列），原样返回不做 float()。"""
    try:
        import psycopg
    except ImportError:
        return "<没有 psycopg，跳过直查>"
    try:
        with psycopg.connect(DSN, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:  # noqa: BLE001 —— 直查只是辅助证据，不能让它把验收台打崩
        return f"<直查失败：{exc}>"


def db_exec(sql, params=()):
    """执行一条写 SQL（只给"清临时数据"用）。"""
    try:
        import psycopg
    except ImportError:
        return False
    with psycopg.connect(DSN, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    return True


def flow_ids_of(order_id):
    """这张单上挂着的**资金**流水 id（收款/付款）。

    ⚠️ 红冲**故意不解锁删单**（`_assert_no_payment_flows` 只认"有没有流水"，
    不看正负、也不看是否已冲销）。所以验收台自己造的临时收款，得自己清干净，
    否则最后一步 DELETE 永远 409 —— 那是**正确行为**，不是 bug。
    """
    try:
        import psycopg
    except ImportError:
        return []
    with psycopg.connect(DSN, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from financial_transactions"
                " where related_order_id=%s"
                "   and (transaction_type in ('receipt','payment')"
                "        or related_type in ('receipt','payment'))",
                (order_id,),
            )
            return [row[0] for row in cur.fetchall()]


def purge_flows(ids):
    """按文档顺序硬清流水：凭证行 → 凭证 → 流水（顺序错了会撞外键）。"""
    if not ids:
        return
    db_exec(
        "delete from journal_entry_lines where entry_id in"
        " (select id from journal_entries where flow_id = any(%s))",
        (ids,),
    )
    db_exec("delete from journal_entries where flow_id = any(%s)", (ids,))
    db_exec("delete from financial_transactions where id = any(%s)", (ids,))


def find_order(c, order_id):
    """**没有 `GET /sales-orders/{id}` 这个接口** —— 详情就在列表里（items 一起返回）。

    第一版脚本按 REST 直觉去 GET 详情，拿到 404，然后 C3~C7 全被这一条拖红：
    一条假红能牵出七条。这里改成从列表里挑。
    """
    _, rows = c.call("GET", "/sales-orders")
    for row in items_of(rows):
        if int(row.get("id") or 0) == int(order_id):
            return row
    return {}


def main():
    c = Client()
    c.login()

    # ── 基础数据 ────────────────────────────────────────────────
    _, customers = c.call("GET", "/customers")
    customers = items_of(customers)
    _, suppliers = c.call("GET", "/suppliers")
    suppliers = items_of(suppliers)
    _, products = c.call("GET", "/products")
    products = items_of(products)
    _, warehouses = c.call("GET", "/warehouses")
    warehouses = items_of(warehouses)

    if not (customers and suppliers and products):
        raise SystemExit("库里缺客户/供应商/商品档案，先补基础数据再跑这台验收")
    customer_id = int(customers[0]["id"])
    supplier_id = int(suppliers[0]["id"])
    product = products[0]
    product_id = int(product["id"])
    warehouse_id = int(warehouses[0]["id"]) if warehouses else None

    # ══ PART A：销售出库 73.901 × 580 ════════════════════════════
    print("\n── A. 销售出库：单价 73.901 × 数量 580 ──")
    status, order = c.call("POST", "/sales-orders", {
        "customer_id": customer_id,
        "doc_type": "outbound",
        "order_date": "2026-10-19",
        "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": 580, "unit_price": 73.901}],
        "note": "精度验收临时单（测完删除）",
    })
    check("A1 建一张出库单", status in (200, 201), f"HTTP {status} {detail(order)}")
    if status not in (200, 201):
        return report()

    order_id = order.get("id")
    line = (order.get("items") or [{}])[0]
    # 关键数：73.901 × 580 = 42862.58（抹成 73.90 就是 42862.00，单张差 6 毛）
    check("A2 行金额 = 42862.58", line.get("amount") == 42862.58, line.get("amount"))
    check("A3 行金额在 JSON 里是数字（不是字符串）", is_number(line.get("amount")),
          f'{type(line.get("amount")).__name__} {line.get("amount")!r}')
    check("A4 单价保留 4 位（73.901 没被抹成 73.90）", line.get("unit_price") == 73.901,
          line.get("unit_price"))
    check("A5 单头合计 = 42862.58", order.get("total_amount") == 42862.58,
          order.get("total_amount"))
    check("A6 单头合计是数字", is_number(order.get("total_amount")),
          f'{type(order.get("total_amount")).__name__} {order.get("total_amount")!r}')

    status, again = c.call("GET", f"/sales-orders/{order_id}")
    line2 = (again.get("items") or [{}])[0]
    check("A7 从库里读回来仍是 42862.58 / 73.901",
          status == 200 and line2.get("amount") == 42862.58 and line2.get("unit_price") == 73.901,
          f"HTTP {status} amount={line2.get('amount')} price={line2.get('unit_price')}")

    # 财务流水 / 库存流水都去库里直查 —— 这两个东西**没有列表接口**，
    # 而且这里要看的正是"落库之后还是不是那个数"，走 API 反而多绕一层。
    check("A8 应收流水 = 42862.58",
          db_scalar(
              "select amount from financial_transactions"
              " where related_type='sales_out' and related_order_id=%s"
              " order by id desc limit 1",
              (order_id,),
          ) == DEC("42862.58"),
          db_scalar(
              "select amount from financial_transactions"
              " where related_type='sales_out' and related_order_id=%s"
              " order by id desc limit 1",
              (order_id,),
          ))
    check("A9 库存流水单价 = 73.9010（没有被 41.6666… 那种尾巴污染）",
          db_scalar(
              "select unit_price from inventory_transactions"
              " where related_type='sales_out' and related_order_id=%s"
              " order by id desc limit 1",
              (order_id,),
          ) == DEC("73.9010"),
          db_scalar(
              "select unit_price from inventory_transactions"
              " where related_type='sales_out' and related_order_id=%s"
              " order by id desc limit 1",
              (order_id,),
          ))

    # ══ PART C：收款冲减 + 红冲（混算探针）════════════════════════
    print("\n── C. 收款 1000 → 冲减 → 红冲（Decimal 混算探针）──")
    status, receipt = c.call("POST", "/finance/receipt", {
        "party_id": customer_id,
        "amount": 1000.0,
        "order_id": int(order_id),
        "occurred_at": "2026-10-19",
        "note": "精度验收临时收款（测完红冲）",
    })
    check("C1 登记收款 1000", status in (200, 201), f"HTTP {status} {detail(receipt)}")
    receipt_id = (receipt or {}).get("id")
    check("C2 冲抵金额 = 1000.00", (receipt or {}).get("applied_amount") == 1000.0,
          (receipt or {}).get("applied_amount"))

    _, after = c.call("GET", f"/sales-orders/{order_id}")
    check("C3 单据实收 = 1000.00（Decimal + float 没炸）", after.get("received_amount") == 1000.0,
          after.get("received_amount"))
    check("C4 本次欠款 = 42862.58 − 1000 = 41862.58",
          after.get("current_debt") == 41862.58, after.get("current_debt"))

    if receipt_id:
        status, reversed_ = c.call("POST", f"/finance/receipt/{receipt_id}/reverse", {"reason": "精度验收红冲"})
        check("C5 红冲成功（不 500）", status in (200, 201), f"HTTP {status} {detail(reversed_)}")
        _, back = c.call("GET", f"/sales-orders/{order_id}")
        check("C6 红冲后实收归零", back.get("received_amount") == 0, back.get("received_amount"))
        check("C7 红冲后欠款回到 42862.58", back.get("current_debt") == 42862.58,
              back.get("current_debt"))
    else:
        check("C5 红冲", False, "收款没建成，红冲无从验起")

    # ══ PART D：业务四舍五入（不是银行家舍入）═══════════════════
    print("\n── D. 1.005 × 3 必须进位到 3.02 ──")
    status, round_doc = c.call("POST", "/sales-orders", {
        "customer_id": customer_id,
        "doc_type": "outbound",
        "order_date": "2026-10-19",
        "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": 3, "unit_price": 1.005}],
        "note": "精度验收四舍五入（测完删除）",
    })
    check("D1 建单成功", status in (200, 201), f"HTTP {status} {detail(round_doc)}")
    if status in (200, 201):
        amt = ((round_doc.get("items") or [{}])[0]).get("amount")
        check("D2 1.005 × 3 = 3.02（ROUND_HALF_UP，不是 3.01）", amt == 3.02, amt)
        c.call("DELETE", f"/sales-orders/{round_doc.get('id')}")

    # ══ PART B：采购入库同口径 ═══════════════════════════════════
    print("\n── B. 采购入库：单价 73.901 × 数量 580 ──")
    status, inbound = c.call("POST", "/purchase-orders", {
        "supplier_id": supplier_id,
        "doc_type": "inbound",
        "order_date": "2026-10-19",
        "warehouse_id": warehouse_id,
        "items": [{"product_id": product_id, "quantity": 580, "unit_price": 73.901}],
        "note": "精度验收临时采购单（测完删除）",
    })
    check("B1 建一张采购入库单", status in (200, 201), f"HTTP {status} {detail(inbound)}")
    if status in (200, 201):
        iline = (inbound.get("items") or [{}])[0]
        check("B2 行金额 = 42862.58", iline.get("amount") == 42862.58, iline.get("amount"))
        check("B3 单价 = 73.901", iline.get("unit_price") == 73.901, iline.get("unit_price"))
        check("B4 应付 = 42862.58", inbound.get("total_amount") == 42862.58,
              inbound.get("total_amount"))
        check("B5 本次欠款 = 42862.58（未付款全挂账）",
              inbound.get("current_debt") == 42862.58, inbound.get("current_debt"))
        c.call("DELETE", f"/purchase-orders/{inbound.get('id')}")

    # ══ 收尾 ════════════════════════════════════════════════════
    print("\n── 收尾：删除临时销售单 ──")
    status, _ = c.call("DELETE", f"/sales-orders/{order_id}")
    check("Z1 临时单已删除（库存/财务流水一并回退）", status in (200, 204), f"HTTP {status}")
    _, gone = c.call("GET", f"/sales-orders/{order_id}")
    check("Z2 删完确实查不到了", gone is None or not isinstance(gone, dict) or not gone.get("id"),
          "还能查到" if isinstance(gone, dict) and gone.get("id") else "")

    return report()


def report():
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 64)
    print(f"结论：{passed}/{total} 通过")
    if passed != total:
        print("失败项：")
        for name, ok, extra in RESULTS:
            if not ok:
                print(f"  ✗ {name}  — {extra}")
    print("=" * 64)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
