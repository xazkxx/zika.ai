from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_agent_assistant_returns_business_summary():
    response = client.post(
        '/api/v1/agent/assistant',
        json={
            'prompt': '请评估当前业务健康度',
            'context': {
                'customers': 10,
                'products': 9,
                'sales_total': 20000,
                'purchase_total': 12000,
                'finance_total': 15000,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert 'answer' in payload
    assert 'summary' in payload
    assert 'risk_level' in payload
