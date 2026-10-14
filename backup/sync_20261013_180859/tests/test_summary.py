from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_summary_uses_database_values():
    response = client.get('/api/v1/summary')
    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload['customers'], int)
    assert isinstance(payload['suppliers'], int)
    assert isinstance(payload['products'], int)
    assert isinstance(payload['sales_total'], (int, float))
    assert isinstance(payload['purchase_total'], (int, float))
    assert isinstance(payload['finance_total'], (int, float))
