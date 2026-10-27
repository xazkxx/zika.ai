"""网关级鉴权（P0-1「方案 B」）的回归门禁。

被守的对象是 `app/core/auth_gate.py` 里的中间件：**`/api/v1` 默认拒绝匿名请求**，
只有 health / login / register / 商品图白名单放行。

为什么必须有这组用例：收口以后，绝大部分业务用例是靠 conftest 注入的管理员 token
才跑得起来的 —— 那种情况下"鉴权坏了"和"鉴权正常"在测试结果上**看起来一模一样**。
所以这里刻意用**假 token** 把 conftest 注入的默认值抵掉，专门验"匿名到底会不会被拒"。

判定口径以行为为准，不看实现：
  · 匿名 / 坏 token → 401（且带 `WWW-Authenticate: Bearer`）
  · 好 token 但账号被停用 → 403（不能是 401：用户没输错密码，是账号被停）
  · 白名单 → 不返回 401
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User


# conftest 已给 TestClient 默认注入管理员 token；逐请求传的 headers 会覆盖它
client = TestClient(app)

ANON = {'Authorization': 'Bearer '}  # 等价于"没带凭证"（网关解不出 token）
FAKE = {'Authorization': 'Bearer not-a-real-token'}


def test_anonymous_business_endpoint_is_rejected():
    """/products 是**没有任何路由级鉴权**的老接口，正好用来验网关本身。"""
    response = client.get('/api/v1/products', headers=FAKE)
    assert response.status_code == 401, response.text
    assert response.headers.get('www-authenticate') == 'Bearer'
    assert '登录凭证' in response.json()['detail']


def test_missing_token_is_rejected():
    response = client.get('/api/v1/products', headers=ANON)
    assert response.status_code == 401, response.text


def test_valid_token_passes_gate():
    # 默认 token 就是 conftest 注入的那张（admin）
    me = client.get('/api/v1/auth/me')
    assert me.status_code == 200, me.text
    assert me.json()['username'] == 'admin'

    products = client.get('/api/v1/products')
    assert products.status_code == 200, products.text


def test_health_and_login_are_public():
    health = client.get('/api/v1/health', headers=ANON)
    assert health.status_code == 200, health.text

    # 末尾多个斜杠也得算白名单（探活地址写错一个斜杠不该变成 401）
    assert client.get('/api/v1/health/', headers=ANON).status_code != 401

    login = client.post(
        '/api/v1/auth/login',
        json={'username': 'admin', 'password': 'Admin123'},
        headers=ANON,
    )
    assert login.status_code == 200, login.text


def test_register_endpoint_is_reachable_without_token():
    """放行 register 是为了让路由自己回 403 的中文说明，而不是被网关拦成 401。"""
    response = client.post(
        '/api/v1/auth/register',
        json={'username': f'x-{uuid.uuid4().hex[:8]}', 'email': 'x@example.com', 'password': 'Secret123'},
        headers=ANON,
    )
    assert response.status_code == 403, response.text
    assert '自助注册已关闭' in response.json()['detail']


def test_product_image_prefix_is_public():
    """商品图是 `<img src>` 直接引的，浏览器带不了请求头 —— 拦了就是整页缩略图全空。

    这里只要求"不是 401"：文件不存在时 404 才是对的。
    """
    response = client.get('/api/v1/uploads/products/__not_exists__.png', headers=ANON)
    assert response.status_code != 401, response.text


def test_deactivated_account_token_is_rejected_with_403():
    username = f'gate-{uuid.uuid4().hex[:8]}'
    db = SessionLocal()
    try:
        db.add(
            User(
                username=username,
                email=f'{username}@example.com',
                role='staff',
                hashed_password='not-used',
                is_active=False,
            )
        )
        db.commit()
    finally:
        db.close()

    try:
        token = create_access_token(subject=username, role='staff')
        response = client.get('/api/v1/products', headers={'Authorization': f'Bearer {token}'})
        assert response.status_code == 403, response.text
        assert '停用' in response.json()['detail']
    finally:
        db = SessionLocal()
        try:
            db.query(User).filter(User.username == username).delete()
            db.commit()
        finally:
            db.close()


def test_auth_mode_off_bypasses_gate(monkeypatch):
    """应急开关：`auth_mode=off` 时网关不拦（现场排障用，默认永远不是 off）。"""
    monkeypatch.setattr(settings, 'auth_mode', 'off')
    response = client.get('/api/v1/products', headers=FAKE)
    assert response.status_code == 200, response.text
