"""采购退货单（对齐浩技云「采购管理 → 退货管理」）回归测试（第 2 批 · 第 2 个单据表）。

采购退货是采购入库的**反向**单据：货退回给供应商，库存减少（outbound 流水）、
应付冲减（purchase_return 财务流水，方向 out、金额记负数）。独立成表。

测试数据遵守 scripts/clean_test_data.py 的规则：退货单号用 `TEST-` 前缀、
备注含「退货单测试」，跑完由 conftest 自动清理。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _return_no() -> str:
    return f"TEST-CGTH{uuid.uuid4().hex[:8].upper()}"


def _new_product() -> int:
    resp = client.post(
        "/api/v1/products",
        json={
            "sku": f"SKU-PRET-{uuid.uuid4().hex[:8]}",
            "name": "退货单测试商品",
            "purchase_price": 5.0,
            "sale_price": 12.5,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_supplier() -> int:
    resp = client.post(
        "/api/v1/suppliers",
        json={
            "code": f"SUP-PRET-{uuid.uuid4().hex[:8]}",
            "name": "退货单测试供应商",
            "address": "西安市雁塔区测试路 2 号",
            "contact": "李经理",
            "phone": "15500000000",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_warehouse() -> int:
    resp = client.post(
        "/api/v1/warehouses",
        json={"code": f"WH-{uuid.uuid4().hex[:8]}", "name": "退货主仓"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _drop_warehouse(warehouse_id: int) -> None:
    """删测试仓库：用 force 强删，否则被库存流水引用时删不掉，会在库里堆积。"""
    client.delete(f"/api/v1/warehouses/{warehouse_id}", params={"force": "true"})


def _stock_for(product_id: int, warehouse_id: int) -> int:
    """该商品在指定仓库的现存量（退货前先入库垫底，退货后核对减少）。"""
    data = client.get("/api/v1/inventory/stock", params={"product_id": product_id}).json()
    rows = data.get("rows", [])
    for row in rows:
        if row.get("warehouse_id") == warehouse_id:
            return int(row.get("quantity") or 0)
    return 0


# ---------- 创建与金额 ----------


def test_create_return_auto_no_snapshot_and_totals():
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    return_id = None
    try:
        resp = client.post(
            "/api/v1/purchase-returns",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "businesser": "采购员",
                "return_reason": "质量不合格",
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        r = resp.json()
        return_id = r["id"]
        assert r["return_no"].startswith("CGTH"), r["return_no"]
        assert r["status"] == "submitted"
        assert r["total_amount"] == 15.0
        assert r["amount_chinese"], "金额大写不能为空"
        assert len(r["items"]) == 1
        assert r["items"][0]["amount"] == 15.0
        assert r["items"][0]["product_name"] == "退货单测试商品"
        assert r["supplier_name"] == "退货单测试供应商"
        assert r["contact"] == "李经理"
        assert r["contact_phone"] == "15500000000"
        assert r["return_date"], "退货日期缺省应自动填当天"
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_create_return_duplicate_no_rejected():
    supplier_id = _new_supplier()
    return_no = _return_no()
    ids = []
    try:
        first = client.post(
            "/api/v1/purchase-returns",
            json={"return_no": return_no, "supplier_id": supplier_id, "note": "退货单测试"},
        )
        assert first.status_code == 201, first.text
        ids.append(first.json()["id"])

        dup = client.post(
            "/api/v1/purchase-returns",
            json={"return_no": return_no, "supplier_id": supplier_id, "note": "退货单测试"},
        )
        assert dup.status_code == 400, dup.text
    finally:
        for rid in ids:
            client.delete(f"/api/v1/purchase-returns/{rid}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")


def test_create_return_supplier_not_found():
    resp = client.post(
        "/api/v1/purchase-returns",
        json={"supplier_id": 99999999, "note": "退货单测试"},
    )
    assert resp.status_code == 404, resp.text


def test_create_return_invalid_status():
    supplier_id = _new_supplier()
    try:
        resp = client.post(
            "/api/v1/purchase-returns",
            json={"supplier_id": supplier_id, "status": "nonsense", "note": "退货单测试"},
        )
        assert resp.status_code == 400, resp.text
    finally:
        client.delete(f"/api/v1/suppliers/{supplier_id}")


# ---------- 库存 / 财务联动 ----------


def test_return_decreases_stock_and_writes_negative_payable():
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    return_id = None
    try:
        # 先做一笔采购入库垫底 10 件
        inbound = client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 10, "unit_price": 5.0}],
            },
        )
        assert inbound.status_code == 201, inbound.text
        inbound_id = inbound.json()["id"]
        assert _stock_for(product_id, warehouse_id) == 10

        # 退 4 件
        resp = client.post(
            "/api/v1/purchase-returns",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert resp.status_code == 201, resp.text
        return_id = resp.json()["id"]

        # 库存 10 → 6
        assert _stock_for(product_id, warehouse_id) == 6

        # 财务：产生一条 purchase_return、金额为负的应付流水
        fin = client.get("/api/v1/finance").json()
        matched = [
            row for row in fin
            if row.get("related_type") == "purchase_return" and row.get("related_order_id") == return_id
        ]
        assert len(matched) == 1
        assert matched[0]["amount"] == -20.0
        assert matched[0]["direction"] == "out"
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        if "inbound_id" in dir():
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_delete_return_reverts_stock_and_finance():
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    return_id = None
    try:
        inbound = client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 10, "unit_price": 5.0}],
            },
        )
        inbound_id = inbound.json()["id"]
        assert _stock_for(product_id, warehouse_id) == 10

        ret = client.post(
            "/api/v1/purchase-returns",
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        ).json()
        return_id = ret["id"]
        assert _stock_for(product_id, warehouse_id) == 6

        # 删退货单：库存 6 → 10，财务冲减流水被删除
        assert client.delete(f"/api/v1/purchase-returns/{return_id}").status_code == 204
        return_id = None
        assert _stock_for(product_id, warehouse_id) == 10

        fin = client.get("/api/v1/finance").json()
        assert not any(
            row.get("related_type") == "purchase_return" for row in fin
        ), "删单后采购退货财务流水应被冲销"

        # 采购入库的应付流水仍应保留
        assert any(
            row.get("related_type") == "purchase_in" and row.get("related_order_id") == inbound_id
            for row in fin
        )
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        if "inbound_id" in dir():
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


# ---------- 列表 / 筛选 ----------


def test_return_list_and_filters():
    supplier_id = _new_supplier()
    return_no = _return_no()
    return_id = None
    try:
        created = client.post(
            "/api/v1/purchase-returns",
            json={"return_no": return_no, "supplier_id": supplier_id, "businesser": "关键字业务员", "note": "退货单测试"},
        ).json()
        return_id = created["id"]

        listed = client.get("/api/v1/purchase-returns")
        assert listed.status_code == 200
        assert any(row["id"] == return_id for row in listed.json())

        by_no = client.get("/api/v1/purchase-returns", params={"keyword": return_no}).json()
        assert [row["id"] for row in by_no] == [return_id]

        by_supplier = client.get("/api/v1/purchase-returns", params={"supplier_id": supplier_id}).json()
        assert any(row["id"] == return_id for row in by_supplier)

        by_status = client.get("/api/v1/purchase-returns", params={"status": "submitted"}).json()
        assert all(row["status"] == "submitted" for row in by_status)
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")


# ---------- 编辑 / 状态 / meta ----------


def test_update_return_replaces_items_and_recomputes():
    product_id = _new_product()
    supplier_id = _new_supplier()
    return_id = None
    try:
        r = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_price": 10.0}],
                "note": "退货单测试",
            },
        ).json()
        return_id = r["id"]

        patched = client.patch(
            f"/api/v1/purchase-returns/{return_id}",
            json={
                "return_reason": "改后退货原因",
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 8.0}],
            },
        )
        assert patched.status_code == 200, patched.text
        row = patched.json()
        assert row["return_reason"] == "改后退货原因"
        assert row["total_amount"] == 32.0
        assert len(row["items"]) == 1
        assert row["items"][0]["amount"] == 32.0
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_return_status_patch_and_invalid_value():
    supplier_id = _new_supplier()
    return_id = None
    try:
        r = client.post(
            "/api/v1/purchase-returns",
            json={"return_no": _return_no(), "supplier_id": supplier_id, "note": "退货单测试"},
        ).json()
        return_id = r["id"]

        bad = client.patch(f"/api/v1/purchase-returns/{return_id}/status", json={"status": "nonsense"})
        assert bad.status_code == 400, bad.text

        # 「改状态」这条路**不许**直接作废 —— 作废要撤库存/应付并留痕，只能走 /void。
        # 这是 P0-5 的口径（与销售退货一致）：状态机接口是廉价接口，红冲必须独立。
        blocked = client.patch(
            f"/api/v1/purchase-returns/{return_id}/status", json={"status": "cancelled"}
        )
        assert blocked.status_code == 400, blocked.text
        assert "作废" in blocked.json()["detail"]

        voided = client.post(
            f"/api/v1/purchase-returns/{return_id}/void", json={"reason": "供应商同意取消"}
        )
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "cancelled"
        assert "已作废" in (voided.json()["note"] or "")
        assert "供应商同意取消" in (voided.json()["note"] or "")

        # 已作废的单：状态与内容都不许再改
        locked = client.patch(
            f"/api/v1/purchase-returns/{return_id}/status", json={"status": "draft"}
        )
        assert locked.status_code == 409, locked.text
        locked_edit = client.patch(
            f"/api/v1/purchase-returns/{return_id}", json={"note": "改备注"}
        )
        assert locked_edit.status_code == 409, locked_edit.text
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")


def test_return_meta_dictionaries():
    meta = client.get("/api/v1/purchase-returns/meta")
    assert meta.status_code == 200, meta.text
    data = meta.json()
    assert {item["code"] for item in data["statuses"]} == {"draft", "submitted", "cancelled"}


# ---------- 打印 ----------


def test_return_print_pdf():
    product_id = _new_product()
    supplier_id = _new_supplier()
    return_id = None
    try:
        r = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 6.0}],
                "note": "退货单测试",
            },
        ).json()
        return_id = r["id"]

        pdf = client.get(f"/api/v1/print/purchase-return/{return_id}")
        assert pdf.status_code == 200, pdf.text
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF", "PDF 魔数校验失败"

        missing = client.get("/api/v1/print/purchase-return/99999999")
        assert missing.status_code == 404
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")




# ---------- P0-2：草稿不落账 / 对称性 / 红冲（2026-10-26） ----------


def _finance_rows(related_type: str, related_id: int) -> list[dict]:
    """这张单在财务流水里留下了几行 —— 判「有没有落过账」的硬证据。"""
    rows = client.get("/api/v1/finance").json()
    return [
        row
        for row in rows
        if row.get("related_type") == related_type and row.get("related_order_id") == related_id
    ]


def _new_customer() -> int:
    resp = client.post(
        "/api/v1/customers",
        json={"code": f"CUS-PRET-{uuid.uuid4().hex[:8]}", "name": "退货对称性测试客户"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_purchase_stock(product_id: int, supplier_id: int, warehouse_id: int, qty: int) -> int:
    """先做一笔采购入库垫底，否则退货扣不出库存。"""
    resp = client.post(
        "/api/v1/purchase-orders",
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "items": [{"product_id": product_id, "quantity": qty, "unit_price": 5.0}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_draft_purchase_return_does_not_touch_stock_or_payable():
    """P0-2 的核心断言：**草稿退货单不许落账**。

    修之前 `create_purchase_return` 无条件扣库存 + 冲应付：
    用户只是把单存成草稿、还没跟供应商谈完，库存已经少了、应付已经被冲了。
    销售侧早有这道守卫，采购侧漏抄 —— 这条测试就是那个缺口。
    """
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_purchase_stock(product_id, supplier_id, warehouse_id, 10)
        assert _stock_for(product_id, warehouse_id) == 10

        created = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "status": "draft",
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        return_id = body["id"]
        assert body["status"] == "draft"
        assert body["total_amount"] == 15.0

        # ① 草稿：库存一分不动、应付一行不写
        assert _stock_for(product_id, warehouse_id) == 10, "草稿退货单绝不能动库存"
        assert _finance_rows("purchase_return", return_id) == [], "草稿退货单绝不能冲应付"

        # ② 审核（草稿 → 已退货）：这一刻才落账
        approved = client.patch(
            f"/api/v1/purchase-returns/{return_id}/status", json={"status": "submitted"}
        )
        assert approved.status_code == 200, approved.text
        assert _stock_for(product_id, warehouse_id) == 7
        rows = _finance_rows("purchase_return", return_id)
        assert len(rows) == 1, f"应付冲减应恰好一行，实际 {len(rows)} 行"
        assert float(rows[0]["amount"]) == -15.0
        assert rows[0]["direction"] == "out"

        # ③ 反审核（已退货 → 草稿）：只改状态，账一个字都不许动
        reverted = client.patch(
            f"/api/v1/purchase-returns/{return_id}/status", json={"status": "draft"}
        )
        assert reverted.status_code == 200, reverted.text
        assert _stock_for(product_id, warehouse_id) == 7, "反审核不是作废，库存不能退回去"
        assert len(_finance_rows("purchase_return", return_id)) == 1

        # ④ 再审核：幂等，不许重复扣库存/重复冲应付
        again = client.patch(
            f"/api/v1/purchase-returns/{return_id}/status", json={"status": "submitted"}
        )
        assert again.status_code == 200, again.text
        assert _stock_for(product_id, warehouse_id) == 7, "重复审核不能二次扣库存"
        assert len(_finance_rows("purchase_return", return_id)) == 1, "重复审核不能二次冲应付"
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_purchase_and_sales_return_share_the_same_draft_rule():
    """对称性断言：**采退与销退对「草稿」的处理必须完全一致**。

    这条测试不验证某一边的实现，而是把两边放在同一组前置条件下比对：
      · 建草稿 → 两边库存都不许动、财务都不许落；
      · 提交   → 两边各落一笔金额为负的往来流水。
    任何一侧再漂移（比如以后又有人把采购侧守卫删掉），这条会立刻红。
    """
    product_id = _new_product()
    supplier_id = _new_supplier()
    customer_id = _new_customer()
    warehouse_id = _new_warehouse()
    inbound_id = None
    purchase_return_id = None
    sales_return_id = None
    try:
        inbound_id = _seed_purchase_stock(product_id, supplier_id, warehouse_id, 10)
        stock_before = _stock_for(product_id, warehouse_id)

        purchase = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "status": "draft",
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert purchase.status_code == 201, purchase.text
        purchase_return_id = purchase.json()["id"]

        sales = client.post(
            "/api/v1/sales-returns",
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "status": "draft",
                "items": [{"product_id": product_id, "quantity": 2, "unit_price": 12.5}],
                "note": "销售退货测试",
            },
        )
        assert sales.status_code == 201, sales.text
        sales_return_id = sales.json()["id"]

        # ① 草稿：两侧都不许动账
        assert _stock_for(product_id, warehouse_id) == stock_before
        assert _finance_rows("purchase_return", purchase_return_id) == []
        assert _finance_rows("sales_return", sales_return_id) == []

        # ② 提交：两侧各落一笔负数往来
        for url in (
            f"/api/v1/purchase-returns/{purchase_return_id}/status",
            f"/api/v1/sales-returns/{sales_return_id}/status",
        ):
            resp = client.patch(url, json={"status": "submitted"})
            assert resp.status_code == 200, resp.text

        # 采退 −2、销退 +2：净变动为 0，这才是两侧「一进一出」对得上
        assert _stock_for(product_id, warehouse_id) == stock_before

        purchase_rows = _finance_rows("purchase_return", purchase_return_id)
        sales_rows = _finance_rows("sales_return", sales_return_id)
        assert len(purchase_rows) == 1 and len(sales_rows) == 1
        assert float(purchase_rows[0]["amount"]) == -10.0
        assert float(sales_rows[0]["amount"]) == -25.0
    finally:
        if purchase_return_id:
            client.delete(f"/api/v1/purchase-returns/{purchase_return_id}")
        if sales_return_id:
            client.delete(f"/api/v1/sales-returns/{sales_return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/customers/{customer_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_update_posted_purchase_return_rewrites_ledger_exactly_once():
    """已落账的退货单改数量：单据、库存、应付必须**一起**变成新口径，且只留一份流水。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_purchase_stock(product_id, supplier_id, warehouse_id, 10)
        created = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 3, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert created.status_code == 201, created.text
        return_id = created.json()["id"]
        assert _stock_for(product_id, warehouse_id) == 7

        patched = client.patch(
            f"/api/v1/purchase-returns/{return_id}",
            json={"items": [{"product_id": product_id, "quantity": 5, "unit_price": 5.0}]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["total_amount"] == 25.0

        assert _stock_for(product_id, warehouse_id) == 5, "改单后库存必须跟着变成 −5"
        rows = _finance_rows("purchase_return", return_id)
        assert len(rows) == 1, f"改单只能留一份应付流水，实际 {len(rows)} 行"
        assert float(rows[0]["amount"]) == -25.0
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")


def test_void_purchase_return_reverts_ledger_and_keeps_the_document():
    """作废 = 红冲 + 留痕：账要撤回，**单据不许消失**（P0-5）。"""
    product_id = _new_product()
    supplier_id = _new_supplier()
    warehouse_id = _new_warehouse()
    inbound_id = None
    return_id = None
    try:
        inbound_id = _seed_purchase_stock(product_id, supplier_id, warehouse_id, 10)
        created = client.post(
            "/api/v1/purchase-returns",
            json={
                "return_no": _return_no(),
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "items": [{"product_id": product_id, "quantity": 4, "unit_price": 5.0}],
                "note": "退货单测试",
            },
        )
        assert created.status_code == 201, created.text
        return_id = created.json()["id"]
        assert _stock_for(product_id, warehouse_id) == 6

        voided = client.post(
            f"/api/v1/purchase-returns/{return_id}/void", json={"reason": "供应商换货"}
        )
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "cancelled"
        assert _stock_for(product_id, warehouse_id) == 10
        assert _finance_rows("purchase_return", return_id) == []

        # 幂等：再点一次不报错、也不再冲一次账
        again = client.post(f"/api/v1/purchase-returns/{return_id}/void")
        assert again.status_code == 200
        assert _stock_for(product_id, warehouse_id) == 10

        # 单据仍在（不是物理删除），而且能查到作废原因
        listed = client.get("/api/v1/purchase-returns", params={"page_size": 200}).json()
        rows = listed["items"] if isinstance(listed, dict) else listed
        matched = [row for row in rows if row["id"] == return_id]
        assert matched, "作废后单据必须仍然存在（P0-5：单据永久保留）"
        assert matched[0]["status"] == "cancelled"
        assert "供应商换货" in (matched[0].get("note") or "")
    finally:
        if return_id:
            client.delete(f"/api/v1/purchase-returns/{return_id}")
        if inbound_id:
            client.delete(f"/api/v1/purchase-orders/{inbound_id}")
        _drop_warehouse(warehouse_id)
        client.delete(f"/api/v1/suppliers/{supplier_id}")
        client.delete(f"/api/v1/products/{product_id}")

