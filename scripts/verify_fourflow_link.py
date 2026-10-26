# -*- coding: utf-8 -*-
"""
四流合一 · 第二阶段第 2/4 步的接口级验收（真后端、真库、可重复跑）。

验两件事：
  A. 发票挂单据（related_order_id）—— 方向相关、能挂能解、挂错被拦
  B. 物流签收 4 字段（PATCH /sales-orders/{id}/logistics）—— 能改能清、脏值被拦

设计纪律（跟前面的验收台一致）：
  · **不改业务数据**：临时发票造完就删；物流字段先读原值、写完再写回去
  · 每条断言都给"反证"留了口子：断言失败时打印实际值，不打印"应该是"
  · 用 trust_env=False：这台机器上有 HTTP_PROXY=127.0.0.1:10679，
    不关掉连 localhost 都会走代理（前面踩过）

跑法（后端先起好，8011 是临时验证口）：
    .venv/Scripts/python.exe scripts/verify_fourflow_link.py
    ERP_BASE=http://127.0.0.1:8010 .venv/Scripts/python.exe scripts/verify_fourflow_link.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("ERP_BASE", "http://127.0.0.1:8011").rstrip("/")
API = BASE + "/api/v1"

RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append((name, ok, extra))
    print(("PASS  " if ok else "FAIL  ") + name + (("  — " + str(extra)) if extra else ""))


class Client:
    """最小 HTTP 客户端：自己拼 Authorization，不依赖 requests（venv 里不一定有）。"""

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
        # 关键：这台机器配了全局代理，localhost 也会被转走 → 显式禁用
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
        return data


def detail(resp):
    """把后端 detail 压成一行字符串 —— 失败时人眼看这一行就够。"""
    if isinstance(resp, dict):
        return str(resp.get("detail") or resp)[:160]
    return str(resp)[:160]


def items_of(resp):
    """列表接口统一返回 `{items, summary}`，别当数组用。

    ⚠️ 这里踩过一次：`GET /invoices` 返回的是字典，脚本里直接 `for row in resp`
    会遍历键名，于是"列表里没有单号"这种假红。取列表一律走这个函数。
    """
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        rows = resp.get("items")
        if isinstance(rows, list):
            return rows
    return []


def main():
    c = Client()
    c.login()

    # ── 取基础数据 ────────────────────────────────────────────────
    _, orders = c.call("GET", "/sales-orders")
    orders = orders if isinstance(orders, list) else []
    outbound = next((o for o in orders if (o.get("doc_type") or "outbound") == "outbound"), None)
    order_doc = next((o for o in orders if (o.get("doc_type") or "") == "order"), None)
    # 库里可能一张出库单都没有 —— 跑过 pytest 就会这样：它的 session 级清理会按
    # 测试签名删掉测试客户，连带把它们名下的单据一起删（这是它的既有设计）。
    # 所以这里不能"没有就跳过"，否则这一组断言会静默失效；现场造一张最小的，
    # 测完删掉（delete 会回退库存与财务流水），保证脚本在任何数据状态下都能跑。
    auto_outbound = None
    if outbound is None:
        _, prods = c.call("GET", "/products")
        prods = items_of(prods)
        product = prods[0] if prods else None
        if product is not None:
            status, made = c.call("POST", "/sales-orders", {
                "customer_id": int(orders[0]["customer_id"]) if orders else 7039,
                "doc_type": "outbound",
                "order_date": "2026-10-19",
                "items": [{"product_id": int(product["id"]), "quantity": 1, "unit_price": 10.0}],
                "note": "四流合一验收临时单",
            })
            if status in (200, 201):
                auto_outbound = made.get("id")
                outbound = made
                print(f"  · 库里没有出库单，已临时造一张 id={auto_outbound}（测完删除）")
    check("基础数据：至少有一张销售出库单", outbound is not None,
          (outbound or {}).get("order_no") or "库里没有商品档案，造不出临时出库单")
    if outbound is None:
        return report()

    _, purchases = c.call("GET", "/purchase-orders")
    purchases = purchases if isinstance(purchases, list) else []
    sales_ids = {int(o["id"]) for o in orders}
    # 必须在"采购单里存在、销售单里不存在"的 id 上试错挂，
    # 否则命中的是销售单，测不到"方向错了"这件事
    wrong_id = next((int(p["id"]) for p in purchases if int(p["id"]) not in sales_ids), None)

    # ══ PART A：发票挂单据 ═════════════════════════════════════════
    print("\n── A. 发票 → 关联单据 ──")
    temp_no = "TEST-LINK-4FLOW"
    # 先清掉上次跑崩留下的同名临时票（幂等，重复跑不会因为唯一键报错）
    _, existed = c.call("GET", "/invoices?keyword=" + temp_no)
    for row in (existed if isinstance(existed, list) else []):
        if row.get("invoice_no") == temp_no:
            c.call("DELETE", "/invoices/%s" % row["id"])

    status, created = c.call("POST", "/invoices", {
        "invoice_no": temp_no,
        "invoice_type": "普票",
        "issue_date": "2026-10-19",
        "direction": "output",
        "total_amount": 100.0,
        "buyer_name": "验收临时抬头",
        "seller_name": "本公司",
        "status": "已确认",
    })
    check("A1 造一张销项临时票", status in (200, 201), f"HTTP {status} {detail(created)}")
    inv_id = (created or {}).get("id")
    if not inv_id:
        return report()
    check("A1b 新建时未挂单 → related_order_id 为 null", created.get("related_order_id") is None,
          created.get("related_order_id"))

    status, linked = c.call("PATCH", "/invoices/%s" % inv_id, {"related_order_id": int(outbound["id"])})
    check("A2 挂到真实销售单", status == 200, f"HTTP {status} {detail(linked)}")
    check("A2b 返回里带单号（不是只有 id）",
          bool((linked or {}).get("related_order_no")),
          f"related_order_no={(linked or {}).get('related_order_no')!r}")
    check("A2c 落库的 id 与选中一致",
          (linked or {}).get("related_order_id") == int(outbound["id"]),
          (linked or {}).get("related_order_id"))

    status, rows = c.call("GET", "/invoices?keyword=" + temp_no)
    row = next((r for r in (rows if isinstance(rows, list) else []) if r.get("id") == inv_id), None)
    check("A3 列表接口也带单号（批量取号没漏）", bool((row or {}).get("related_order_no")),
          f"{(row or {}).get('related_order_no')!r}")

    if wrong_id is not None:
        status, bad = c.call("PATCH", "/invoices/%s" % inv_id, {"related_order_id": wrong_id})
        check("A4 销项挂采购单 id → 被拦（404 销售单不存在）", status == 404,
              f"HTTP {status} {detail(bad)}")
    else:
        check("A4 销项挂采购单 id → 被拦", False, "库里没有只在采购侧存在的 id，跳过")

    status, moved = c.call("PATCH", "/invoices/%s" % inv_id, {"direction": "input"})
    check("A5 已挂单时改方向 → 被拦（先清空再改）", status == 400,
          f"HTTP {status} {detail(moved)}")
    check("A5b 拦截文案点明要先清空",
          "清空" in detail(moved), detail(moved))

    status, cleared = c.call("PATCH", "/invoices/%s" % inv_id, {"related_order_id": None})
    check("A6 解除关联（传 null）", status == 200 and cleared.get("related_order_id") is None,
          f"HTTP {status} related_order_no={(cleared or {}).get('related_order_no')!r}")

    status, _ = c.call("DELETE", "/invoices/%s" % inv_id)
    check("A7 删掉临时票（不留垃圾）", status in (200, 204), f"HTTP {status}")

    # ══ PART C：编辑弹窗的字段真的能存下来 ═════════════════════════
    # 这一组是被 A 组顺带撞出来的真 bug：`InvoiceUpdate` 少了 12 个字段，
    # pydantic 静默丢弃 → 接口 200、数据没动。弹窗是 OCR 之后唯一的补录入口，
    # 少了这些字段等于"这张票除了进销项，什么都改不了"。
    print("\n── C. 发票编辑：字段真落库 ──")
    temp_no2 = "TEST-EDIT-FLOW"
    _, existed2 = c.call("GET", "/invoices?keyword=" + temp_no2)
    for row in items_of(existed2):
        if row.get("invoice_no") == temp_no2:
            c.call("DELETE", "/invoices/%s" % row["id"])
    status, made = c.call("POST", "/invoices", {
        "invoice_no": temp_no2,
        "direction": "output",
        "issue_date": "2026-10-19",
        "total_amount": 100.0,
        "buyer_name": "旧抬头",
        "status": "已确认",
    })
    inv2 = (made or {}).get("id")
    check("C1 造第二张临时票", status in (200, 201) and bool(inv2), f"HTTP {status} {detail(made)}")
    if not inv2:
        return report()

    status, edited = c.call("PATCH", "/invoices/%s" % inv2, {
        "invoice_no": temp_no2 + "-B",
        "total_amount": 250.5,
        "buyer_name": "新抬头",
        "buyer_tax_no": "91610000TESTTAXNO",
        "issue_date": "2026-10-20",
    })
    check("C2 改号码/金额/抬头/税号/日期 → 200", status == 200, f"HTTP {status} {detail(edited)}")
    check("C2b 价税合计落库（不是只回显）", (edited or {}).get("total_amount") == 250.5,
          (edited or {}).get("total_amount"))
    check("C2c 发票号码落库", (edited or {}).get("invoice_no") == temp_no2 + "-B",
          (edited or {}).get("invoice_no"))
    check("C2d 抬头落库", (edited or {}).get("buyer_name") == "新抬头",
          (edited or {}).get("buyer_name"))
    check("C2e 税号落库", (edited or {}).get("buyer_tax_no") == "91610000TESTTAXNO",
          (edited or {}).get("buyer_tax_no"))
    check("C2f 开票日期落库", str((edited or {}).get("issue_date") or "").startswith("2026-10-20"),
          (edited or {}).get("issue_date"))

    _, reloaded = c.call("GET", "/invoices?keyword=" + temp_no2)
    hit = next((r for r in items_of(reloaded) if r.get("id") == inv2), None)
    check("C3 重新从列表读回来，仍是新值（真写进库了）",
          bool(hit) and hit.get("total_amount") == 250.5 and hit.get("buyer_name") == "新抬头",
          f"{(hit or {}).get('total_amount')} / {(hit or {}).get('buyer_name')}")

    _, pool = c.call("GET", "/invoices")
    other_no = next(
        (r.get("invoice_no") for r in items_of(pool) if r.get("id") != inv2 and r.get("invoice_no")),
        None,
    )
    if other_no:
        status, dup = c.call("PATCH", "/invoices/%s" % inv2, {"invoice_no": other_no})
        check("C4 号码改成另一张票已有的号 → 400（不是 500）", status == 400,
              f"HTTP {status} {detail(dup)}")
    status, empty = c.call("PATCH", "/invoices/%s" % inv2, {"invoice_no": "   "})
    check("C5 号码填空 → 400", status == 400, f"HTTP {status} {detail(empty)}")

    status, _ = c.call("DELETE", "/invoices/%s" % inv2)
    check("C6 删掉第二张临时票", status in (200, 204), f"HTTP {status}")

    # ══ PART B：物流 / 签收 ════════════════════════════════════════
    print("\n── B. 销售出库 → 物流签收 ──")
    oid = int(outbound["id"])
    before = {
        "logistics_company": outbound.get("logistics_company"),
        "logistics_no": outbound.get("logistics_no"),
        "signed_by": outbound.get("signed_by"),
        "signed_at": outbound.get("signed_at"),
    }

    status, saved = c.call("PATCH", "/sales-orders/%s/logistics" % oid, {
        "logistics_company": "顺丰速运",
        "logistics_no": "SF-TEST-0001",
        "signed_by": "验收人",
        "signed_at": "2026-10-19T15:30",
    })
    check("B1 登记物流 + 签收", status == 200, f"HTTP {status} {detail(saved)}")
    check("B1b 公司回显", (saved or {}).get("logistics_company") == "顺丰速运",
          (saved or {}).get("logistics_company"))
    check("B1c 单号回显", (saved or {}).get("logistics_no") == "SF-TEST-0001",
          (saved or {}).get("logistics_no"))
    check("B1d 签收人回显", (saved or {}).get("signed_by") == "验收人",
          (saved or {}).get("signed_by"))
    signed_at = str((saved or {}).get("signed_at") or "")
    check("B1e 签收时间回显（不再是 null = 已签收）",
          signed_at.startswith("2026-10-19"), signed_at)

    status, bad = c.call("PATCH", "/sales-orders/%s/logistics" % oid, {"signed_at": "昨天下午"})
    check("B2 签收时间乱填 → 400", status == 400, f"HTTP {status} {detail(bad)}")

    status, future = c.call("PATCH", "/sales-orders/%s/logistics" % oid, {"signed_at": "2099-01-01T00:00"})
    check("B3 签收时间填未来 → 400", status == 400, f"HTTP {status} {detail(future)}")

    status, too_long = c.call("PATCH", "/sales-orders/%s/logistics" % oid, {"signed_by": "x" * 60})
    check("B4 签收人超长 → 400", status == 400, f"HTTP {status} {detail(too_long)}")

    if order_doc is not None:
        status, wrong_doc = c.call("PATCH", "/sales-orders/%s/logistics" % int(order_doc["id"]),
                                   {"signed_by": "张三"})
        check("B5 对「销售订单」（只订货不发货）登记签收 → 400", status == 400,
              f"HTTP {status} {detail(wrong_doc)}")

    # 还原：把 4 个字段写回测试前的样子（新加的列，原本全是 null）
    restore = {}
    for key in ("logistics_company", "logistics_no", "signed_by"):
        restore[key] = before.get(key) or ""
    restore["signed_at"] = before.get("signed_at") or ""
    status, back = c.call("PATCH", "/sales-orders/%s/logistics" % oid, restore)
    check("B6 还原现场（4 字段清空）", status == 200, f"HTTP {status} {detail(back)}")
    check("B6b 签收时间已清回 null（重新变「未签收」）",
          (back or {}).get("signed_at") in (None, ""),
          (back or {}).get("signed_at"))
    check("B6c 物流公司已清空", (back or {}).get("logistics_company") in (None, ""),
          (back or {}).get("logistics_company"))

    if auto_outbound:
        status, _ = c.call("DELETE", "/sales-orders/%s" % auto_outbound)
        check("B7 删掉临时出库单（库存与流水一并回退）", status in (200, 204), f"HTTP {status}")

    return report()


def report():
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 62)
    print(f"结果：{passed}/{total} 条通过")
    failed = [n for n, ok, _ in RESULTS if not ok]
    if failed:
        print("失败项：")
        for name in failed:
            print("  · " + name)
    print("=" * 62)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
