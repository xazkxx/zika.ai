"""多账套（多公司）第 1 期回归测试。

这一期的唯一底线是：**账不能串**。串账的表现不是报错，而是"数字不对" ——
A 公司看到 B 公司的客户、报表合计对不上、税报错。所以本文件反复验证的就是隔离，
包括三个"本来会静默出错"的点：

1. `test_business_tables_are_isolated_between_companies` —— 两家公司的商品互不可见。
2. `test_unknown_company_schema_fails_loudly` —— 凭证指向不存在的账套时必须**当场报错**。
   PostgreSQL 会跳过 search_path 里不存在的 schema，于是请求会悄悄读到 public
   （第一个账套）的数据 —— 那不是降级，是串账，而且界面上一切正常。
3. `test_illegal_schema_name_is_rejected` —— schema 名会被拼进 SQL，必须挡住注入。

外加：老 token（没有账套声明）要能继续用（升级平滑）、账套清单与切换的权限边界、
全局表在各账套间共享、**公司抬头按账套隔离**（进销项判定靠它，串了就会
把"别人开给我们的票"判成销项）。

测试会建一个临时账套（schema 名带随机后缀），结束时删掉 schema 与账套行 ——
绝不能把测试账套留在用户的账套列表里。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import text

from app.core.config import settings
from app.core.company_info import load_company, save_company
from app.core.tenant import PUBLIC_SCHEMA, engine_for
import app.models  # noqa: F401  保证 Base.metadata 里表齐全
from app.main import app
from app.models.company import Company, UserCompany

client = TestClient(app)
ADMIN = {"username": "admin", "password": "Admin123"}


def _login(company: str | None = None) -> dict:
    body = dict(ADMIN)
    if company:
        body["company"] = company
    resp = client.post("/api/v1/auth/login", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _forged_token(company: str | None) -> str:
    """自己签一张 token（密钥就在本地，测试里拿得到）—— 用来模拟被篡改 / 过期的凭证。"""
    payload = {"sub": "admin", "role": "admin"}
    if company is not None:
        payload["company"] = company
    return jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _drop_schema(schema: str) -> None:
    if not schema or schema == PUBLIC_SCHEMA:
        return
    with engine_for(PUBLIC_SCHEMA).begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


@pytest.fixture()
def second_company():
    """建一个临时第二账套，用完连 schema 带记录一起删掉。"""
    from app.db.session import SessionLocal

    tag = uuid.uuid4().hex[:6]
    code = f"co_t{tag}"
    db = SessionLocal()
    try:
        company = Company(
            code=code,
            name=f"测试第二公司-{tag}",
            own_name=f"测试第二公司-{tag}",
            tax_no=f"91TEST{tag.upper()}",
            schema_name=code,
            is_active=True,
            sort_order=999,
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        company_id = company.id

        # 给 admin 开权限（用 API 之外的方式直接写关系表，避免依赖尚未实现的分配接口）
        admin = db.query(__import__("app.models.user", fromlist=["User"]).User).filter_by(username="admin").first()
        db.add(UserCompany(user_id=admin.id, company_id=company_id, is_default=False))
        db.commit()
    finally:
        db.close()

    # 建 schema 与业务表
    from app.db.base import Base
    from app.core.tenant import create_tenant_schema, create_tenant_tables

    create_tenant_schema(code)
    create_tenant_tables(code, Base.metadata)

    yield {"code": code, "id": company_id, "name": f"测试第二公司-{tag}"}

    db = SessionLocal()
    try:
        db.query(UserCompany).filter(UserCompany.company_id == company_id).delete()
        db.query(Company).filter(Company.id == company_id).delete()
        db.commit()
    finally:
        db.close()
    _drop_schema(code)


# ============================================================
# 1. ⭐ 业务数据隔离：这是整套设计的唯一底线
# ============================================================
def test_business_tables_are_isolated_between_companies(second_company):
    """在第二家公司建的商品，第一家公司**看不到**；反之亦然。"""
    first = _login(PUBLIC_SCHEMA)
    second = _login(second_company["code"])
    assert first["company"] == PUBLIC_SCHEMA
    assert second["company"] == second_company["code"]

    before_first = client.get("/api/v1/products", headers=_headers(first["access_token"])).json()
    before_second = client.get("/api/v1/products", headers=_headers(second["access_token"])).json()
    assert len(before_second) == 0, "新账套的商品应该是空的（账套不复制业务数据）"

    sku = f"SKU-MC-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/products",
        json={"sku": sku, "name": "第二家公司专属商品", "sale_price": 1},
        headers=_headers(second["access_token"]),
    )
    assert created.status_code == 201, created.text

    after_second = client.get("/api/v1/products", headers=_headers(second["access_token"])).json()
    after_first = client.get("/api/v1/products", headers=_headers(first["access_token"])).json()
    assert any(row["sku"] == sku for row in after_second), "本账套内应该看得到自己新建的商品"
    assert not any(row["sku"] == sku for row in after_first), (
        "★ 串账了：第一家公司的商品列表里出现了第二家公司的商品"
    )
    assert len(after_first) == len(before_first), "第一家的商品数量不该被第二家的写入改动"

    # 两个账套里的商品是**两条独立记录**（同一个 SKU 在两家各存一份，唯一约束互不干扰）
    same_sku = f"SKU-SAME-{uuid.uuid4().hex[:8]}"
    for token in (first["access_token"], second["access_token"]):
        resp = client.post(
            "/api/v1/products",
            json={"sku": same_sku, "name": "同名 SKU 商品", "sale_price": 2},
            headers=_headers(token),
        )
        assert resp.status_code == 201, f"同一个 SKU 在两个账套里应该各存一份：{resp.text}"


def test_company_headline_is_per_account(second_company):
    """公司抬头按账套隔离 —— 进销项判定靠它，串了就会把进项判成销项。

    这也是把抬头从部署级的 `company.json` 搬进账套表的原因：
    一个部署里有两家公司时，抬头不可能只有一份。
    """
    snapshot = load_company()
    try:
        second = _login(second_company["code"])
        resp = client.put(
            "/api/v1/settings/company",
            json={"own_name": "第二家公司抬头", "own_tax_no": "91SECOND0000000001"},
            headers=_headers(second["access_token"]),
        )
        assert resp.status_code == 200, resp.text

        # 第二家读到自己刚写的
        got = client.get("/api/v1/settings/company", headers=_headers(second["access_token"])).json()
        assert got["own_name"] == "第二家公司抬头"

        # 第一家必须还是原来的
        first = _login(PUBLIC_SCHEMA)
        other = client.get("/api/v1/settings/company", headers=_headers(first["access_token"])).json()
        assert other["own_name"] != "第二家公司抬头", "★ 串账了：改第二家的抬头，把第一家也改了"
    finally:
        save_company(snapshot)


# ============================================================
# 2. ⭐ 全局表必须共享
# ============================================================
def test_global_tables_are_shared_across_companies(second_company):
    """用户、菜单、数字字典这些是"系统怎么跑"的配置，各账套共用。

    不共用的话每建一家公司都要重新配一遍菜单和字典，那不叫多账套，叫多套系统。
    """
    second = _login(second_company["code"])
    token = _headers(second["access_token"])

    # 账号：同一个 admin 能进第二家
    me = client.get("/api/v1/auth/me", headers=token)
    assert me.status_code == 200 and me.json()["username"] == "admin"

    # 菜单：新账套里也要有导航（否则用户进去是白板）
    perms = client.get("/api/v1/system/me/permissions", headers=token)
    assert perms.status_code == 200
    assert perms.json().get("menu_tree"), "新账套没有菜单，说明全局表没共享"

    # 字典：税率候选在新账套里也能取到
    lookups = client.get("/api/v1/system/lookups?types=tax_rate", headers=token)
    assert lookups.status_code == 200
    assert len(lookups.json()["tax_rate"]) == 6, "数字字典没有跨账套共享"


# ============================================================
# 3. ⭐ 凭证里的账套不合法时，必须大声报错
# ============================================================
def test_unknown_company_schema_fails_loudly():
    """指向一个不存在的账套 → 401，**绝不能悄悄读 public**。

    PostgreSQL 会跳过 search_path 里不存在的 schema，于是请求会落到 public
    （第一个账套）。如果代码在这里"宽容"地回落到默认账套，用户会以为自己在看
    B 公司的账，实际看的是 A 公司的 —— 没有任何报错，只有数字不对。
    """
    resp = client.get("/api/v1/products", headers=_headers(_forged_token("co_not_exist_9x")))
    assert resp.status_code == 401, f"应当明确拒绝，实际 {resp.status_code}：{resp.text[:200]}"
    assert "不存在" in resp.json()["detail"]


def test_illegal_schema_name_is_rejected():
    """schema 名会被拼进 SQL，含引号/分号的必须挡住。"""
    resp = client.get(
        "/api/v1/products",
        headers=_headers(_forged_token("public; DROP TABLE products")),
    )
    assert resp.status_code == 401
    assert "不合法" in resp.json()["detail"]


def test_legacy_token_without_company_still_works():
    """升级前签发的 token（没有账套声明）必须能继续用，落到第一个账套。

    不这样做的话，升级的一瞬间所有在线用户会被踢下线 —— 一个纯粹自找的故障。
    """
    resp = client.get("/api/v1/products", headers=_headers(_forged_token(None)))
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# ============================================================
# 4. 账套清单与切换的权限边界
# ============================================================
def test_login_returns_the_users_companies(second_company):
    data = _login()
    codes = {row["code"] for row in data["companies"]}
    assert PUBLIC_SCHEMA in codes
    assert second_company["code"] in codes, "登录要带上该用户可进入的全部账套"
    assert data["company_name"], "登录要返回当前账套名，顶栏要显示它"


def test_switch_company_issues_a_new_token(second_company):
    """切账套＝换发新凭证（账套写在凭证里），换完之后读写的是新账套。"""
    first = _login(PUBLIC_SCHEMA)
    switched = client.post(
        "/api/v1/auth/switch-company",
        json={"company": second_company["code"]},
        headers=_headers(first["access_token"]),
    )
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["company"] == second_company["code"]
    assert body["access_token"] != first["access_token"], "切换必须换发 token"

    products = client.get("/api/v1/products", headers=_headers(body["access_token"])).json()
    assert products == [], "切到新账套后应当看到空商品表"


def test_cannot_switch_to_a_company_you_do_not_belong_to():
    """不是成员就不能切进去。

    这里用"不存在的账套号"来验证：无论是"不存在"还是"没权限"，都必须被拒 ——
    靠的是 `_resolve_target_company` 只在**本人清单**里找，而不是先查库再判断。
    """
    first = _login(PUBLIC_SCHEMA)
    resp = client.post(
        "/api/v1/auth/switch-company",
        json={"company": "co_someone_else"},
        headers=_headers(first["access_token"]),
    )
    assert resp.status_code == 403, resp.text


# ============================================================
# 5. 防退化：前端得把当前账套显示出来
# ============================================================
def test_frontend_shows_and_switches_the_company():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")
    assert "/auth/switch-company" in source, "前端没有切换账套的入口"
    assert "companies" in source, "前端没有读取账套清单"
