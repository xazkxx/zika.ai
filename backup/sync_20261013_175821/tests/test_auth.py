import uuid

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_register_and_login_user():
    username = f"user-{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"

    register_response = client.post(
        '/api/v1/auth/register',
        json={
            'username': username,
            'email': email,
            'full_name': '测试管理员',
            'password': 'Secret123',
            'role': 'admin',
        },
    )
    assert register_response.status_code == 201, register_response.text
    user_data = register_response.json()
    assert user_data['username'] == username
    assert user_data['email'] == email
    assert user_data['role'] == 'admin'
    assert 'hashed_password' not in user_data

    login_response = client.post(
        '/api/v1/auth/login',
        json={'username': username, 'password': 'Secret123'},
    )
    assert login_response.status_code == 200, login_response.text
    token_data = login_response.json()
    assert token_data['token_type'] == 'bearer'
    assert token_data['access_token']
    assert token_data['role'] == 'admin'
