import uuid

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_customer_and_product():
    customer_code = f"CUST-{uuid.uuid4().hex[:8]}"
    product_sku = f"SKU-{uuid.uuid4().hex[:8]}"

    customer_payload = {
        "code": customer_code,
        "name": "测试客户",
        "phone": "13800000000",
        "email": "test@example.com",
        "address": "深圳",
    }
    customer_response = client.post('/api/v1/customers', json=customer_payload)
    assert customer_response.status_code == 201, customer_response.text
    customer_data = customer_response.json()
    assert customer_data['code'] == customer_code
    assert customer_data['name'] == '测试客户'

    product_payload = {
        "sku": product_sku,
        "name": "测试产品",
        "category": "办公耗材",
        "unit": "件",
        "purchase_price": 10.5,
        "sale_price": 15.0,
    }
    product_response = client.post('/api/v1/products', json=product_payload)
    assert product_response.status_code == 201, product_response.text
    product_data = product_response.json()
    assert product_data['sku'] == product_sku
    assert product_data['name'] == '测试产品'


def test_create_purchase_and_sales_orders():
    customer_code = f"CUST-ORDER-{uuid.uuid4().hex[:8]}"
    supplier_code = f"SUP-{uuid.uuid4().hex[:8]}"
    product_sku = f"SKU-ORDER-{uuid.uuid4().hex[:8]}"

    customer = client.post('/api/v1/customers', json={
        'code': customer_code,
        'name': '订单客户',
        'phone': '13900000000',
    })
    assert customer.status_code == 201, customer.text

    supplier = client.post('/api/v1/suppliers', json={
        'code': supplier_code,
        'name': '订单供应商',
        'phone': '13800000001',
    })
    assert supplier.status_code == 201, supplier.text

    product = client.post('/api/v1/products', json={
        'sku': product_sku,
        'name': '订单产品',
        'category': '测试',
        'unit': '件',
        'purchase_price': 25,
        'sale_price': 40,
    })
    assert product.status_code == 201, product.text
    product_id = product.json()['id']
    customer_id = customer.json()['id']
    supplier_id = supplier.json()['id']

    purchase_payload = {
        'supplier_id': supplier_id,
        'order_no': f'PO-{uuid.uuid4().hex[:8]}',
        'items': [{
            'product_id': product_id,
            'quantity': 2,
            'unit_price': 25,
        }],
    }
    purchase_response = client.post('/api/v1/purchase-orders', json=purchase_payload)
    assert purchase_response.status_code == 201, purchase_response.text
    assert purchase_response.json()['total_amount'] == 50

    sales_payload = {
        'customer_id': customer_id,
        'order_no': f'SO-{uuid.uuid4().hex[:8]}',
        'items': [{
            'product_id': product_id,
            'quantity': 3,
            'unit_price': 40,
        }],
    }
    sales_response = client.post('/api/v1/sales-orders', json=sales_payload)
    assert sales_response.status_code == 201, sales_response.text
    assert sales_response.json()['total_amount'] == 120


def test_update_sales_order_status():
    product = client.post('/api/v1/products', json={
        'sku': f"SKU-STATUS-{uuid.uuid4().hex[:8]}",
        'name': '状态更新产品',
        'category': '测试',
        'unit': '件',
        'purchase_price': 8,
        'sale_price': 16,
    })
    assert product.status_code == 201, product.text
    product_id = product.json()['id']

    customer = client.post('/api/v1/customers', json={
        'code': f"CUST-STATUS-{uuid.uuid4().hex[:8]}",
        'name': '状态客户',
        'phone': '13900000002',
    })
    assert customer.status_code == 201, customer.text

    order = client.post('/api/v1/sales-orders', json={
        'customer_id': customer.json()['id'],
        'order_no': f'SO-STATUS-{uuid.uuid4().hex[:8]}',
        'items': [{
            'product_id': product_id,
            'quantity': 2,
            'unit_price': 16,
        }],
    })
    assert order.status_code == 201, order.text
    order_id = order.json()['id']

    update_response = client.patch(f'/api/v1/sales-orders/{order_id}/status', json={'status': 'completed'})
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()['status'] == 'completed'


def test_create_inventory_and_finance_records():
    product = client.post('/api/v1/products', json={
        'sku': f"SKU-FIN-{uuid.uuid4().hex[:8]}",
        'name': '财务测试产品',
        'category': '测试',
        'unit': '件',
        'purchase_price': 10,
        'sale_price': 20,
    })
    assert product.status_code == 201, product.text
    product_id = product.json()['id']

    inventory_response = client.post('/api/v1/inventory', json={
        'product_id': product_id,
        'warehouse_id': 1,
        'transaction_type': 'inbound',
        'quantity': 10,
        'unit_price': 12,
    })
    assert inventory_response.status_code == 201, inventory_response.text
    assert inventory_response.json()['quantity'] == 10

    finance_response = client.post('/api/v1/finance', json={
        'transaction_type': 'income',
        'amount': 200,
        'currency': 'CNY',
        'note': '测试收入',
    })
    assert finance_response.status_code == 201, finance_response.text
    assert finance_response.json()['amount'] == 200
