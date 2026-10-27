"""发票去重替换与批量删除测试（自建临时数据，测完清理）。"""
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create(invoice_no: str, amount: float) -> int:
    response = client.post(
        "/api/v1/invoices",
        json={"invoice_no": invoice_no, "total_amount": amount, "invoice_type": "普票"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _batch_delete(ids: list[int]):
    # 本版本 TestClient 的 delete() 不支持传 body，用通用 request() 代替
    return client.request("DELETE", "/api/v1/invoices/batch", json={"ids": ids})


def test_create_invoice_replaces_duplicate():
    """同发票号重复上传：旧记录被删除，新解析结果替换入库。"""
    invoice_no = f"TMP-DUP-{uuid.uuid4().hex[:8]}"
    first_id = _create(invoice_no, 100.0)
    second_id = _create(invoice_no, 200.0)

    assert first_id != second_id, "重复上传应替换旧记录（新 id）"

    items = client.get("/api/v1/invoices").json()["items"]
    matches = [item for item in items if item["invoice_no"] == invoice_no]
    assert len(matches) == 1, "库里只应有一条该发票号记录"
    assert float(matches[0]["total_amount"]) == 200.0

    # 清理
    assert client.delete(f"/api/v1/invoices/{second_id}").status_code == 204


def test_delete_invoices_batch():
    """批量删除：一次删多条；空 ids 返回 400。"""
    no_a = f"TMP-BAT-{uuid.uuid4().hex[:8]}"
    no_b = f"TMP-BAT-{uuid.uuid4().hex[:8]}"
    id_a = _create(no_a, 10.0)
    id_b = _create(no_b, 20.0)

    response = _batch_delete([id_a, id_b])
    assert response.status_code == 204, response.text

    # P0-5：批量删除 = 批量作废 —— 再删一次是幂等 204（旧契约的 404 已不再适用）
    assert client.delete(f"/api/v1/invoices/{id_a}").status_code == 204
    assert client.delete(f"/api/v1/invoices/{id_b}").status_code == 204

    # 作废票不进"有效发票"列表（但不等于没记录：记录与原件都在归档里）
    items = client.get("/api/v1/invoices").json()["items"]
    assert all(item["id"] not in (id_a, id_b) for item in items), "作废发票不该出现在有效发票列表"

    # 空 ids 应 400
    assert _batch_delete([]).status_code == 400
