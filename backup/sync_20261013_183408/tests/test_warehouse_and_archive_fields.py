"""融合改造回归测试：仓库档案 + 商品/客户/供应商档案补齐字段。

对应用户需求「保留自研 ERP 并融合浩技云进销存能力」的第 1 步：
- 新增 warehouses 表（此前库存流水只有裸 warehouse_id，没有可维护的仓库主数据）
- products / customers / suppliers 三张档案表补齐字段

原则：新字段全部可选，不传也能建记录，保证历史行为不变。
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------- 仓库档案 ----------


def test_create_and_get_warehouse():
    code = _uniq("WH")
    payload = {
        "code": code,
        "name": "主仓库",
        "location": "A区01号位",
        "manager": "张三",
        "phone": "13800000000",
        "note": "融合改造新增",
    }
    response = client.post("/api/v1/warehouses", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["code"] == code
    assert data["name"] == "主仓库"
    assert data["location"] == "A区01号位"
    assert data["is_active"] is True

    detail = client.get(f"/api/v1/warehouses/{data['id']}")
    assert detail.status_code == 200
    assert detail.json()["manager"] == "张三"


def test_warehouse_code_must_be_unique():
    code = _uniq("WH")
    body = {"code": code, "name": "一号仓"}
    assert client.post("/api/v1/warehouses", json=body).status_code == 201
    duplicate = client.post("/api/v1/warehouses", json=body)
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.json()["detail"]


def test_warehouse_list_and_active_filter():
    code = _uniq("WH")
    created = client.post(
        "/api/v1/warehouses",
        json={"code": code, "name": "停用仓", "is_active": False},
    )
    assert created.status_code == 201
    warehouse_id = created.json()["id"]

    listed = client.get("/api/v1/warehouses", params={"limit": 500})
    assert listed.status_code == 200
    assert any(item["code"] == code for item in listed.json())

    active_only = client.get("/api/v1/warehouses", params={"only_active": True, "limit": 500})
    assert active_only.status_code == 200
    assert all(item["code"] != code for item in active_only.json())

    # 停用后再启用
    patched = client.patch(
        f"/api/v1/warehouses/{warehouse_id}",
        json={"code": code, "name": "停用仓", "is_active": True},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is True


def test_warehouse_404_on_missing():
    assert client.get("/api/v1/warehouses/99999999").status_code == 404
    assert (
        client.patch("/api/v1/warehouses/99999999", json={"code": "X", "name": "X"}).status_code
        == 404
    )


# ---------- 商品档案新字段 ----------


def test_product_accepts_haojicloud_fields():
    sku = _uniq("SKU")
    payload = {
        "sku": sku,
        "name": "融合测试商品",
        "category": "五金件",
        "unit": "个",
        "purchase_price": 8.5,
        "sale_price": 12.0,
        "mnemonic": "RHCS",
        "standards": "10x10x2",
        "brand": "A型",
        "bar_code": "6901234567890",
        "color": "红",
        "size": "M",
        "manufacturer": "某厂",
        "serial_no": "SN-0001",
        "unit_weight": 0.35,
        "stock_upper": 500,
        "stock_lower": 20,
        "pack_qty": 24,
        "shelf_life": 365,
        "warn_days": 15,
        "image_url": "/uploads/x.png",
        "note": "测试备注",
    }
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    for field, expected in payload.items():
        assert data[field] == expected, f"{field} 不一致: {data.get(field)!r} != {expected!r}"

    listed = client.get("/api/v1/products", params={"limit": 500})
    assert listed.status_code == 200
    assert any(item["sku"] == sku and item["mnemonic"] == "RHCS" for item in listed.json())


def test_product_still_works_without_new_fields():
    """历史调用方式（只传老字段）必须继续可用。"""
    sku = _uniq("SKU")
    response = client.post(
        "/api/v1/products",
        json={"sku": sku, "name": "仅老字段商品", "purchase_price": 1.0, "sale_price": 2.0},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["mnemonic"] is None
    assert data["stock_upper"] is None


# ---------- 客户档案新字段 ----------


def test_customer_accepts_haojicloud_fields():
    code = _uniq("CUST")
    payload = {
        "code": code,
        "name": "融合测试客户",
        "phone": "13800000000",
        "address": "深圳市南山区",
        "businesser": "李四",
        "contact": "王五",
        "contact_phone": "13900000000",
        "tax_no": "91330100MA2XXXXX",
        "bank_name": "中国银行深圳分行",
        "bank_account": "6217000000000000",
        "level": "VIP",
        "discount": 0.95,
        "credit_limit": 50000.0,
        "init_receivable": 1200.0,
        "init_invoice_debt": 300.0,
        "relation_date": "2024-03-01",
        "business_type": "批发",
        "main_products": "五金件",
        "potential_amount": 800000.0,
    }
    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    for field, expected in payload.items():
        assert data[field] == expected, f"{field} 不一致: {data.get(field)!r} != {expected!r}"


# ---------- 供应商档案新字段 ----------


def test_supplier_accepts_haojicloud_fields():
    code = _uniq("SUP")
    payload = {
        "code": code,
        "name": "融合测试供应商",
        "short_name": "测试供",
        "contact": "赵六",
        "main_contact": "钱七",
        "mobile": "13700000000",
        "postcode": "518000",
        "bank_name": "工商银行",
        "bank_account": "6222000000000000",
        "init_payable": 8600.0,
        "init_invoice_debt": 500.0,
        "address": "东莞市长安镇",
    }
    response = client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    for field, expected in payload.items():
        assert data[field] == expected, f"{field} 不一致: {data.get(field)!r} != {expected!r}"
