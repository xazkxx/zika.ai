"""登录 / 自助注册（P0-1 鉴权收口后的口径）。

这条文件以前断言的正是**后门本身**：不登录 `POST /api/v1/auth/register`，请求体里写
`role: "admin"`，就 201 建出一个管理员 —— 于是任何人拿到地址就能给自己开管理员账号，
整条鉴权链路形同虚设（`scripts/audit_auth_routes.py` 把它列为最高危项）。

现在断言的是收口后的行为：
  · 默认 `allow_self_register=False` → 403，且账号**确实没被建出来**；
  · 显式打开（仅首次部署/联调）→ 依然只能拿到 `staff`，请求体里的 role 被忽略。
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


client = TestClient(app)


def _payload(username):
    return {
        'username': username,
        'email': f'{username}@example.com',
        'full_name': '测试账号',
        'password': 'Secret123',
        'role': 'admin',
    }


def test_self_register_is_closed_by_default():
    username = f'user-{uuid.uuid4().hex[:8]}'

    register_response = client.post('/api/v1/auth/register', json=_payload(username))
    assert register_response.status_code == 403, register_response.text
    assert '自助注册已关闭' in register_response.json()['detail']

    # 光看状态码不够：要确认账号真的没落库（能用它登录就说明后门还开着）
    login_response = client.post(
        '/api/v1/auth/login', json={'username': username, 'password': 'Secret123'}
    )
    assert login_response.status_code == 401, login_response.text


def test_enabled_register_cannot_escalate_role(monkeypatch):
    username = f'user-{uuid.uuid4().hex[:8]}'
    monkeypatch.setattr(settings, 'allow_self_register', True)

    register_response = client.post('/api/v1/auth/register', json=_payload(username))
    assert register_response.status_code == 201, register_response.text
    user_data = register_response.json()
    assert user_data['username'] == username
    assert user_data['email'] == f'{username}@example.com'
    # 关键断言：请求体里写的是 admin，落库必须是 staff
    assert user_data['role'] == 'staff'
    assert 'hashed_password' not in user_data

    login_response = client.post(
        '/api/v1/auth/login', json={'username': username, 'password': 'Secret123'}
    )
    assert login_response.status_code == 200, login_response.text
    token_data = login_response.json()
    assert token_data['token_type'] == 'bearer'
    assert token_data['access_token']
    assert token_data['role'] == 'staff'

