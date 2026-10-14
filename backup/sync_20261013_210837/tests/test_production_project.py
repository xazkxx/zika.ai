import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_production_and_project_endpoints_work():
    production_order_no = f"PO-{uuid.uuid4().hex[:8].upper()}"
    project_code = f"PRJ-{uuid.uuid4().hex[:8].upper()}"

    production = client.post(
        '/api/v1/production-orders',
        json={
            'product_id': 1,
            'order_no': production_order_no,
            'quantity': 120,
            'status': 'planned',
            'priority': 'high',
            'note': '月度生产计划',
        },
    )
    assert production.status_code == 201, production.text

    project = client.post(
        '/api/v1/projects',
        json={
            'code': project_code,
            'name': 'ERP 改造项目',
            'manager': '张经理',
            'status': 'in_progress',
            'progress': 35,
            'budget': 150000,
            'deadline': '2026-12-31',
            'note': '本地 ERP 迭代增强',
        },
    )
    assert project.status_code == 201, project.text

    production_list = client.get('/api/v1/production-orders')
    project_list = client.get('/api/v1/projects')

    assert production_list.status_code == 200, production_list.text
    assert project_list.status_code == 200, project_list.text
    assert len(production_list.json()) >= 1
    assert len(project_list.json()) >= 1


def test_operations_dashboard_endpoint_work():
    payload = client.get('/api/v1/dashboard/operations')

    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert 'production_orders' in body
    assert 'project_summary' in body
    assert 'high_priority_orders' in body
    assert 'milestones' in body
    assert 'cost_summary' in body
    assert 'gantt' in body
    assert isinstance(body['production_orders'], list)
    assert isinstance(body['project_summary'], dict)
    assert isinstance(body['milestones'], list)
    assert isinstance(body['cost_summary'], dict)
    assert isinstance(body['gantt'], list)


def test_bom_linkage_and_recommendation_payload_work():
    bom = client.post(
        '/api/v1/production-boms',
        json={
            'product_id': 1,
            'component_product_id': 2,
            'quantity': 3,
            'unit_cost': 18.5,
            'note': '主板组装 BOM',
        },
    )
    assert bom.status_code == 201, bom.text
    bom_body = bom.json()
    assert bom_body['product_id'] == 1
    assert bom_body['component_product_id'] == 2

    payload = client.get('/api/v1/dashboard/operations')
    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert 'production_flow' in body
    assert 'recommendations' in body
    assert 'bom_summary' in body
    assert 'work_orders' in body
    assert 'production_schedule' in body
    assert 'bom_alerts' in body
    assert 'line_board' in body
    assert 'auto_schedule' in body
    assert 'work_report_summary' in body
    assert isinstance(body['production_flow'], list)
    assert isinstance(body['recommendations'], list)
    assert isinstance(body['bom_summary'], dict)
    assert isinstance(body['work_orders'], list)
    assert isinstance(body['production_schedule'], list)
    assert isinstance(body['bom_alerts'], list)
    assert isinstance(body['line_board'], list)
    assert isinstance(body['auto_schedule'], list)
    assert isinstance(body['work_report_summary'], dict)


def test_daily_report_export_endpoint_returns_csv():
    response = client.get('/api/v1/reports/daily-export')

    assert response.status_code == 200, response.text
    assert 'text/csv' in response.headers.get('content-type', '')
    body = response.text
    assert 'report_date' in body.lower()
    assert 'sales_total' in body.lower()
    assert 'purchase_total' in body.lower()


def test_inventory_alerts_endpoint_returns_low_stock_warning():
    product = client.post(
        '/api/v1/products',
        json={
            'sku': f"SKU-ALERT-{uuid.uuid4().hex[:8]}",
            'name': '预警测试产品',
            'category': '原材料',
            'unit': '件',
            'purchase_price': 12.5,
            'sale_price': 18,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()['id']

    client.post(
        '/api/v1/inventory',
        json={
            'product_id': product_id,
            'warehouse_id': 1,
            'transaction_type': 'inbound',
            'quantity': 15,
            'unit_price': 12.5,
        },
    )
    client.post(
        '/api/v1/inventory',
        json={
            'product_id': product_id,
            'warehouse_id': 1,
            'transaction_type': 'outbound',
            'quantity': 8,
            'unit_price': 12.5,
        },
    )

    response = client.get('/api/v1/inventory/alerts')
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert any(item['status'] == 'low_stock' for item in body)


def test_purchase_recommendations_endpoint_returns_actions():
    supplier = client.post(
        '/api/v1/suppliers',
        json={
            'code': f"SUP-RECO-{uuid.uuid4().hex[:8]}",
            'name': '补货供应商',
            'phone': '13900000002',
            'email': 'reco@example.com',
            'address': '深圳',
        },
    )
    assert supplier.status_code == 201, supplier.text

    product = client.post(
        '/api/v1/products',
        json={
            'sku': f"SKU-RECO-{uuid.uuid4().hex[:8]}",
            'name': '补货测试产品',
            'category': '原材料',
            'unit': '件',
            'purchase_price': 15,
            'sale_price': 22,
            # 库存下限：改造后预警按商品自带的上下限判定，不再用写死的 20
            'stock_lower': 20,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()['id']

    client.post(
        '/api/v1/inventory',
        json={
            'product_id': product_id,
            'warehouse_id': 1,
            'transaction_type': 'inbound',
            'quantity': 10,
            'unit_price': 15,
        },
    )

    response = client.get('/api/v1/purchase/recommendations')
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert any(item['product_id'] == product_id for item in body)


def test_finance_decision_support_endpoint_work():
    product = client.post(
        '/api/v1/products',
        json={
            'sku': f"SKU-DECISION-{uuid.uuid4().hex[:8]}",
            'name': '决策支持产品',
            'category': '测试',
            'unit': '件',
            'purchase_price': 15,
            'sale_price': 30,
        },
    )
    assert product.status_code == 201, product.text

    client.post(
        '/api/v1/finance',
        json={
            'transaction_type': 'income',
            'amount': 5000,
            'currency': 'CNY',
            'note': '销售收入',
        },
    )
    client.post(
        '/api/v1/finance',
        json={
            'transaction_type': 'expense',
            'amount': 3000,
            'currency': 'CNY',
            'note': '采购支出',
        },
    )

    response = client.get('/api/v1/finance/decision-support')
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'summary' in body
    assert 'recommendations' in body
    assert 'risk_level' in body
    assert isinstance(body['recommendations'], list)
    assert isinstance(body['summary'], dict)


def test_mobile_dashboard_endpoint_work():
    response = client.get('/api/v1/mobile/dashboard')

    assert response.status_code == 200, response.text
    body = response.json()
    assert 'status' in body
    assert 'summary' in body
    assert 'kpis' in body
    assert 'recommendations' in body
    assert isinstance(body['kpis'], list)
    assert isinstance(body['recommendations'], list)
    assert isinstance(body['summary'], dict)


def test_supplier_performance_and_finance_alerts_endpoints_work():
    supplier = client.post(
        '/api/v1/suppliers',
        json={
            'code': f"SUP-PERF-{uuid.uuid4().hex[:8]}",
            'name': '绩效供应商',
            'phone': '13900000003',
            'email': 'perf@example.com',
            'address': '广州',
        },
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = supplier.json()['id']

    product = client.post(
        '/api/v1/products',
        json={
            'sku': f"SKU-PERF-{uuid.uuid4().hex[:8]}",
            'name': '绩效测试产品',
            'category': '原材料',
            'unit': '件',
            'purchase_price': 30,
            'sale_price': 45,
        },
    )
    assert product.status_code == 201, product.text
    product_id = product.json()['id']

    purchase = client.post(
        '/api/v1/purchase-orders',
        json={
            'supplier_id': supplier_id,
            'order_no': f'PO-PERF-{uuid.uuid4().hex[:8].upper()}',
            'items': [{
                'product_id': product_id,
                'quantity': 4,
                'unit_price': 30,
            }],
        },
    )
    assert purchase.status_code == 201, purchase.text

    client.post(
        '/api/v1/finance',
        json={
            'transaction_type': 'expense',
            'supplier_id': supplier_id,
            'amount': 120,
            'currency': 'CNY',
            'note': '供应商付款提醒',
        },
    )

    supplier_performance = client.get('/api/v1/supplier/performance')
    finance_alerts = client.get('/api/v1/finance/alerts')

    assert supplier_performance.status_code == 200, supplier_performance.text
    supplier_body = supplier_performance.json()
    assert isinstance(supplier_body, list)
    assert any(item['supplier_id'] == supplier_id for item in supplier_body)

    assert finance_alerts.status_code == 200, finance_alerts.text
    alert_body = finance_alerts.json()
    assert isinstance(alert_body, list)
    assert any('payment' in item.get('type', '') or 'supplier' in item.get('type', '') for item in alert_body)


def test_executive_dashboard_endpoint_work():
    response = client.get('/api/v1/dashboard/executive')

    assert response.status_code == 200, response.text
    body = response.json()
    assert 'kpis' in body
    assert 'status' in body
    assert 'alerts' in body
    assert isinstance(body['kpis'], list)
    assert isinstance(body['status'], dict)
    assert isinstance(body['alerts'], list)
