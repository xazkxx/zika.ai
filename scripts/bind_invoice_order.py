# -*- coding: utf-8 -*-
"""把一张**销项发票**挂到指定的销售出库单上（`invoices.related_order_id`）。

## 为什么需要它

出库单的「完结」闸是**双条件**：欠款 = 0 **且** 未开票 = 0。
未开票金额 = 单据总额 − 该单已关联发票的合计，而"已关联"的判据就是
`invoices.related_order_id = 出库单 id`。

后端 `PATCH /invoices/{id}` 支持 `related_order_id`，但发票录入表单里
还没把这个字段露出来 —— 所以走完收款后，需要这一步把发票挂上去，
完结按钮才会放行。

## 用法

    # 先看看这张发票/这张单现在什么状态（不改任何东西）
    python scripts/bind_invoice_order.py --invoice 123 --order 456 --dry-run

    # 真挂
    python scripts/bind_invoice_order.py --invoice 123 --order 456

    # 解除关联
    python scripts/bind_invoice_order.py --invoice 123 --order 0

⚠️ 只会动 `related_order_id` 这一个字段，发票金额/方向/号码一律不碰；
   若发票方向不是销项、或发票购买方与该单客户不一致，后端会 400，脚本原样报错。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = {"url": "http://127.0.0.1:8010"}
USERNAME = "admin"
PASSWORD = "Admin123"


def _request(path: str, method: str = "GET", token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE["url"] + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:200]}


def main() -> int:
    ap = argparse.ArgumentParser(description="把销项发票挂到销售出库单上")
    ap.add_argument("--invoice", type=int, required=True, help="发票 id")
    ap.add_argument("--order", type=int, required=True, help="销售出库单 id（0 = 解除关联）")
    ap.add_argument("--dry-run", action="store_true", help="只看不改")
    ap.add_argument("--base", default=BASE["url"], help="后端地址，默认 8010")
    args = ap.parse_args()

    BASE["url"] = args.base

    status, data = _request(
        "/api/v1/auth/login",
        method="POST",
        body={"username": USERNAME, "password": PASSWORD},
    )
    if status != 200 or not data.get("access_token"):
        print(f"❌ 登录失败：{status} {data}")
        return 1
    token = data["access_token"]

    # ⚠️ 后端没有 `GET /invoices/{id}`（只有列表 / 文件 / 二维码），
    #    所以从列表里按 id 找 —— 别按"看起来该有"的接口写，否则永远 404。
    status, listing = _request("/api/v1/invoices", token=token)
    if status != 200:
        print(f"❌ 取发票列表失败：{status} {listing}")
        return 1
    rows = listing if isinstance(listing, list) else listing.get("items") or []
    inv = next((x for x in rows if int(x.get("id", 0)) == args.invoice), None)
    if inv is None:
        print(f"❌ 发票 #{args.invoice} 不存在（列表里共 {len(rows)} 张）")
        return 1
    print(
        f"发票 #{inv.get('id')}  号码={inv.get('invoice_no')}  "
        f"方向={inv.get('direction')}  金额={inv.get('total_amount')}  "
        f"当前关联单据={inv.get('related_order_id')}"
    )

    if args.order:
        # 同理：没有 GET /sales-orders/{id}，从列表里按 id 找
        status, orders = _request("/api/v1/sales-orders", token=token)
        if status != 200:
            print(f"❌ 取销售单列表失败：{status} {orders}")
            return 1
        order_rows = orders if isinstance(orders, list) else orders.get("items") or []
        order = next((x for x in order_rows if int(x.get("id", 0)) == args.order), None)
        if order is None:
            print(f"❌ 销售单 #{args.order} 不存在（列表里共 {len(order_rows)} 张）")
            return 1
        print(
            f"出库单 #{order.get('id')}  {order.get('order_no')}  "
            f"客户={order.get('customer_name') or order.get('customer_id')}  "
            f"总额={order.get('total_amount')}  已收={order.get('received_amount')}"
        )

    if args.dry_run:
        print("（--dry-run：什么都没改）")
        return 0

    payload = {"related_order_id": args.order or None}
    status, res = _request(
        f"/api/v1/invoices/{args.invoice}", method="PATCH", token=token, body=payload
    )
    if status != 200:
        print(f"❌ 关联失败：{status} {res}")
        return 1
    print(f"✅ 已关联：发票 #{args.invoice} → 出库单 #{args.order or '（无）'}")
    print(f"   现在可以去开单管理点「标记为已完结」了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
