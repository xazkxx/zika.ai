"""P0-5：删除 = 作废 + 归档（2026-10-26）。

这张测试盯的是**证据链**，不是状态码：

  1. 单据 DELETE 之后，单据**还在**（`status=cancelled`）、明细还在；
  2. `document_archives` 里有一条 `void` 记录：单号、作废前状态、金额、原因、整单快照；
  3. 发票 DELETE 之后 `status=已作废`、从「有效发票」列表消失，但归档里查得到；
  4. 发票原件是被**移动**到归档目录，内容一个字节都不差（不是删除）。

改造前的实现里，这三样东西都是"删掉就没了"，所以这几条断言在旧代码上会全红。
"""

import uuid

from fastapi.testclient import TestClient

from app.core import file_storage
from app.main import app
from app.services.doc_archive import archive_file

client = TestClient(app)

ADMIN = {"username": "admin", "password": "Admin123"}


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _admin_headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _archive_rows(doc_type: str, doc_no: str) -> list[dict]:
    resp = client.get(
        "/api/v1/system/document-archives",
        params={"doc_type": doc_type, "doc_no": doc_no},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_delete_sales_order_voids_and_archives_full_snapshot():
    customer = client.post(
        "/api/v1/customers",
        json={"code": f"CUS-P05-{_hex()}", "name": "归档验证客户"},
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-P05-{_hex()}", "name": "归档验证商品", "sale_price": 10.0},
    ).json()
    order_no = f"SO-{_hex()}"
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "order_no": order_no,
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 3, "unit_price": 10.0}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    status_before = order.json()["status"]

    deleted = client.delete(f"/api/v1/sales-orders/{order_id}?reason=客户取消订单")
    assert deleted.status_code == 204

    # ① 单据与明细都还在，只是落了 cancelled
    listed = client.get("/api/v1/sales-orders", params={"page_size": 500}).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    matched = [row for row in rows if row["id"] == order_id]
    assert matched, "P0-5：作废后单据必须仍然存在"
    assert matched[0]["status"] == "cancelled"
    assert matched[0]["items"], "P0-5：明细不许跟着消失"

    # ② 归档台账里有完整快照（这是"可追责"的核心）
    archived = _archive_rows("sales_order", order_no)
    assert archived, "作废必须写归档台账"
    top = archived[0]
    assert top["action"] == "void"
    assert top["status_before"] == status_before
    assert top["status_after"] == "cancelled"
    assert float(top["total_amount"]) == 30.0
    assert "客户取消订单" in (top["reason"] or "")
    assert top["payload"] and '"items"' in top["payload"], "快照必须含明细"

    # 收尾（订单已作废但仍在，主数据要 force 才能删）
    client.delete(f"/api/v1/products/{product['id']}?force=true")
    client.delete(f"/api/v1/customers/{customer['id']}?force=true")


def test_delete_invoice_hides_it_from_active_list_but_keeps_evidence():
    invoice_no = f"TEST-P05-{_hex()}"
    created = client.post(
        "/api/v1/invoices",
        json={"invoice_no": invoice_no, "invoice_type": "普票", "total_amount": 88.8},
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]

    deleted = client.delete(f"/api/v1/invoices/{invoice_id}?reason=重复录入")
    assert deleted.status_code == 204

    # ① 有效发票列表里不再出现（统计口径不能被作废票污染）
    items = client.get("/api/v1/invoices").json()["items"]
    assert all(item["id"] != invoice_id for item in items)

    # ② 归档里查得到，而且带上作废原因
    archived = _archive_rows("invoice", invoice_no)
    assert archived, "作废发票必须写归档台账"
    top = archived[0]
    assert top["action"] == "void"
    assert top["status_after"] == "已作废"
    assert float(top["total_amount"]) == 88.8
    assert "重复录入" in (top["reason"] or "")

    # ③ 作废票是历史凭证：不许再改金额
    patched = client.patch(f"/api/v1/invoices/{invoice_id}", json={"total_amount": 1.0})
    assert patched.status_code == 409, patched.text


def test_archive_file_moves_original_and_keeps_every_byte():
    """发票原件：归档 = 移动，不是删除。内容必须逐字节一致。"""
    payload = b"%PDF-1.4 archive probe " + uuid.uuid4().hex.encode()
    rel = file_storage.save_bytes(payload, "归档验证.pdf")
    archived = archive_file(rel, doc_no=f"TEST-P05-FILE-{_hex()}")
    try:
        assert archived, "有原件时必须真的搬走并返回归档路径"
        assert archived.startswith("archive/invoices/")
        assert file_storage.read_bytes(rel) is None, "原位置不该再有文件（是移动）"
        assert file_storage.read_bytes(archived) == payload, "原件内容必须一个字节都不差"
    finally:
        target = file_storage.absolute_path(archived) if archived else None
        if target is not None and target.is_file():
            target.unlink()
