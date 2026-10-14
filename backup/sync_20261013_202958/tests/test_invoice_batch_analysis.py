from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_invoice_batch_analysis_classifies_and_summarizes_entries():
    response = client.post(
        '/api/v1/invoices/analyze',
        json={
            'invoices': [
                {
                    'invoice_no': 'FP-001',
                    'customer_name': 'A公司',
                    'amount': 1200.0,
                    'date': '2026-09-01',
                    'status': '已开票',
                    'note': '采购办公用品',
                },
                {
                    'invoice_no': 'FP-002',
                    'customer_name': 'B客户',
                    'amount': 8600.0,
                    'date': '2026-09-05',
                    'status': '已付款',
                    'note': '销售服务收入',
                },
            ]
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert 'items' in payload
    assert len(payload['items']) >= 2
    assert payload['summary']['total_amount'] >= 9800.0
    assert 'by_category' in payload['summary']
