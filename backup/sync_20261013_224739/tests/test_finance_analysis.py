import uuid

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_finance_analysis_includes_customer_and_monthly_summary():
    customer_code = f'CUST-ANALYSIS-{uuid.uuid4().hex[:8]}'
    customer = client.post('/api/v1/customers', json={
        'code': customer_code,
        'name': '分析客户A',
        'phone': '13800000001',
        'email': 'analysis-a@example.com',
        'address': '北京',
    })
    assert customer.status_code == 201, customer.text

    finance = client.post('/api/v1/finance', json={
        'transaction_type': 'income',
        'amount': 1500.0,
        'currency': 'CNY',
        'note': '订单收入',
        'customer_id': customer.json()['id'],
    })
    assert finance.status_code == 201, finance.text

    analysis = client.get('/api/v1/finance/analysis')
    assert analysis.status_code == 200, analysis.text

    payload = analysis.json()
    assert payload['total_revenue'] >= 1500.0
    assert 'by_customer' in payload
    assert 'monthly_trend' in payload
    assert any(item['customer_name'] == '分析客户A' for item in payload['by_customer'])
