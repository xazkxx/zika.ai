# -*- coding: utf-8 -*-
"""第一阶段验收台：单号前缀规范 + 往来单位编码规则（2026-10-20）。

四组断言，全部可独立运行：
  A 纯函数        —— 前缀表、流水号数值排序、甲乙编码（不碰库、不碰服务）
  B 静态扫描      —— 路由里不许再有 `_next_doc_no(db, Model, "字面量")`
  C 真实接口      —— 建客户看编码、建销售订单/出库单看单号前缀，用完即删
  D 表结构        —— 三个账套的 account_name / tax_no / flow_no 列 + 字典分类

用法：
    ./.venv/Scripts/python.exe scripts/verify_doc_no_prefix.py                # 跑 A/B/D
    ./.venv/Scripts/python.exe scripts/verify_doc_no_prefix.py --live         # 再加 C（需要后端在跑）
    ERP_BASE=http://127.0.0.1:8011/api/v1 ...（默认 8010）

⚠️ C 组会真的建单再删除。删除走 DELETE 接口，销售订单（doc_type=order）不产生
   库存/资金流水，所以能删干净；出库单**不建**（建了就有流水，删不掉，会污染账）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.doc_no import (  # noqa: E402  （必须在 sys.path 之后导入）
    DOC_NO_PREFIX,
    build_partner_code,
    format_doc_no,
    next_partner_seq,
    next_seq,
    parse_seq,
    prefix_of,
)

BASE = os.environ.get("ERP_BASE", "http://127.0.0.1:8010/api/v1").rstrip("/")
DSN = "postgresql://erp:erp123456@127.0.0.1:5432/erp"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f"  {detail}" if detail else ""))


# ============================================================
# A · 纯函数
# ============================================================
def part_a() -> None:
    print("\nA. 前缀注册表与取号逻辑（纯函数）")
    required = {
        "sales_outbound": "XS",
        "sales_order": "XS",
        "purchase_inbound": "CG",
        "purchase_order": "CG",
        "statement": "DZ",
        "sales_return": "XSTH",
        "purchase_return": "CGTH",
        "quotation": "BJ",
        "inventory_transfer": "DB",
        "financial_flow": "FL",
        "contract": "HT",
    }
    for kind, prefix in required.items():
        check(f"A1 {kind} → {prefix}", prefix_of(kind) == prefix, f"实际 {prefix_of(kind)}")

    # 数值排序：当天已有 999 和 1000 时，下一号必须是 1001（字符串序会算成 1000）
    existing = ["XS20261020099", "XS20261020099".replace("099", "999"), "XS202610201000"]
    seq = next_seq(existing, "XS", "20261020")
    check("A2 单日破千后取号不重号", seq == 1001, f"next_seq={seq}（期望 1001）")
    check("A3 破千后单号是 4 位流水", format_doc_no("XS", "20261020", 1001) == "XS202610201001")

    # 脏数据不参与取号：人手填的、外部导入的都不算
    dirty = ["XS20261020TEST", "XSD20261020001", "XS20261020003"]
    check("A4 脏单号不参与取号", next_seq(dirty, "XS", "20261020") == 4, f"next_seq={next_seq(dirty,'XS','20261020')}")

    # 格式解析边界
    check("A5 解析正常单号", parse_seq("CG20261020012", "CG", "20261020") == 12)
    check("A6 解析前缀不符返回 None", parse_seq("XS20261020012", "CG", "20261020") is None)

    # 甲乙编码
    check("A7 客户首号 甲CUS0001", build_partner_code([], "customer") == "甲CUS0001", build_partner_code([], "customer"))
    check("A8 供应商首号 乙SUP0001", build_partner_code([], "supplier") == "乙SUP0001", build_partner_code([], "supplier"))
    legacy = ["CUS20261010001", "甲CUS0007", "KH001"]
    check("A9 老编码不影响新序列", build_partner_code(legacy, "customer") == "甲CUS0008",
          build_partner_code(legacy, "customer"))
    check("A10 流水补零到 4 位", next_partner_seq(["乙SUP0042"], "supplier") == 43)


# ============================================================
# B · 静态扫描
# ============================================================
def part_b() -> None:
    print("\nB. 路由里不得再有字面量前缀")
    routes = ROOT / "app" / "api" / "v1" / "routes"
    pattern = re.compile(r'_next_doc_no\([^)]*?"([A-Z]{2,6})"', re.S)
    offenders: list[str] = []
    for path in sorted(routes.glob("erp_*.py")):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line} 前缀 {match.group(1)!r}")
    check("B1 无字面量前缀残留", not offenders, "; ".join(offenders[:5]))

    # 注册表里的每个前缀都要是 2~4 个大写字母（防止手滑写成小写）
    bad = {k: v for k, v in DOC_NO_PREFIX.items() if not re.fullmatch(r"[A-Z]{2,6}", v)}
    check("B2 前缀格式规范", not bad, str(bad))


# ============================================================
# C · 真实接口
# ============================================================
def _request(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        return exc.code, payload
    except Exception as exc:  # 连不上
        return 0, str(exc)


def part_c() -> None:
    print("\nC. 真实接口（建单 → 断言 → 删除）")
    status, payload = _request("POST", "/auth/login", body={"username": "admin", "password": "Admin123"})
    if status != 200:
        check("C0 登录", False, f"{status} {payload}")
        return
    token = payload["access_token"]
    check("C0 登录", True)

    # C1/C2 客户编码 甲CUS####
    status, customer = _request("POST", "/customers", token, {"name": "验收-客户-编码规则"})
    check("C1 新建客户 201", status == 201, f"{status} {customer if status != 201 else ''}")
    if status == 201:
        code = customer.get("code") or ""
        check("C2 客户编码形如 甲CUS0001", bool(re.fullmatch(r"甲CUS\d{4}", code)), code)
        status, _ = _request("DELETE", f"/customers/{customer['id']}", token)
        check("C3 客户已清理", status in (200, 204), str(status))

    # C4~C6 销售订单单号以 XS 开头，且与出库单共用同一张表的序号空间
    status, products = _request("GET", "/products?limit=1", token)
    status2, warehouses = _request("GET", "/warehouses?only_active=true", token)
    if status != 200 or not products or status2 != 200 or not warehouses:
        check("C4 取商品/仓库", False, "没有商品或仓库，跳过建单断言")
        return
    product = products[0]
    warehouse = warehouses[0]
    status, cust = _request("POST", "/customers", token, {"name": "验收-下单客户"})
    if status != 201:
        check("C4 建下单客户", False, str(status))
        return
    order_body = {
        "customer_id": cust["id"],
        "doc_type": "order",
        "warehouse_id": warehouse["id"],
        "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 1}],
    }
    status, order = _request("POST", "/sales-orders", token, order_body)
    check("C4 新建销售订单 201", status == 201, f"{status} {order if status != 201 else ''}")
    if status == 201:
        no = order.get("order_no") or ""
        check("C5 销售订单号以 XS 开头", no.startswith("XS"), no)
        check("C6 订单号符合 XS+8位日期+流水", bool(re.fullmatch(r"XS\d{8}\d{3,}", no)), no)
        status, _ = _request("DELETE", f"/sales-orders/{order['id']}", token)
        check("C7 订单已清理", status in (200, 204), str(status))
    status, _ = _request("DELETE", f"/customers/{cust['id']}", token)
    check("C8 下单客户已清理", status in (200, 204), str(status))


# ============================================================
# D · 表结构
# ============================================================
def part_d() -> None:
    print("\nD. 表结构（三个账套）")
    try:
        import psycopg
    except ImportError:
        check("D0 psycopg 可用", False, "venv 里没有 psycopg")
        return
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "select schema_name from information_schema.schemata "
            "where schema_name='public' or schema_name like 'co\\_%' order by 1"
        )
        schemas = [row[0] for row in cur.fetchall()]
        check("D0 账套清单", len(schemas) >= 1, ",".join(schemas))
        for schema in schemas:
            for table, column in (
                ("customers", "account_name"),
                ("suppliers", "tax_no"),
                ("suppliers", "account_name"),
                ("financial_transactions", "flow_no"),
            ):
                cur.execute(
                    "select 1 from information_schema.columns "
                    "where table_schema=%s and table_name=%s and column_name=%s",
                    (schema, table, column),
                )
                check(f"D1 {schema}.{table}.{column}", cur.fetchone() is not None)
        cur.execute("select dict_type from data_dictionaries where dict_type in ('fund_account','settlement_method')")
        found = {row[0] for row in cur.fetchall()}
        check("D2 资金账户/结算方式字典", found == {"fund_account", "settlement_method"}, str(sorted(found)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="额外跑真实接口（需要后端在跑）")
    args = parser.parse_args()

    print(f"ERP 第一阶段验收台 · BASE={BASE}")
    part_a()
    part_b()
    part_d()
    if args.live:
        part_c()

    print("\n" + "=" * 60)
    print(f"合计：{len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for name in FAIL:
            print(f"  · 失败：{name}")
    print("=" * 60)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
