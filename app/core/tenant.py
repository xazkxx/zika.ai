"""账套路由 —— 把一次请求的数据库会话，接到正确的账套 schema 上。

## 一句话原理

每个账套一个 **engine**，连接参数里带
`options=-c search_path=<账套schema>,public`。
于是不限定名的表名先落到账套 schema、找不到再落到 public。
业务代码写 `db.query(Product)` 就够了，**一行都不用改**。

## 为什么用 engine 隔离而不是每次 `SET search_path`

`SET search_path` 是**会话级**的，而连接是**池化复用**的 —— 一旦某次忘了设置，
上一个请求的 search_path 会残留下来，下一个请求就**悄悄读到了别人家的账**。
这类 bug 不报错、只是数字不对，正是 ERP 最不能出的错。

用 `connect_args` 把 search_path 固定在**连接建立时**，池里的每条连接天生绑定
它所属的账套 engine，**不存在残留**。

## 当前账套怎么传

JWT 里带 **schema 名**（`company` 声明，签名的，客户端改不了），不是给人看的账套号 ——
因为"账套号 → schema"如果查错，后果是**静默读到 public**（＝串账），
所以凭证里直接带最终要用的 schema，中间不留转换环节。
切账套必须**换发 token**，而换发接口会先校验"这个人是否真属于那家账套"，
所以 token 里的 schema 是可信的，不必每次请求再查库。
老 token 没有这个声明时回落到 `public`（＝第一个账套＝现状），保证升级平滑。

另外 `session_factory_for()` 在首次建连接前会**确认 schema 真的存在**，
不存在就报错。这是刻意的：不存在时 PG 会把 search_path 里找不到的 schema 跳过、
悄悄用 public —— 那就变成"以为在读 A 公司、其实读的是 B 公司"，而且不报错。
宁可让它当场炸掉。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import bearer_token, decode_access_token
from app.models.company import GLOBAL_TABLES, PUBLIC_SCHEMA

# 默认账套＝第一个账套＝现有部署（表都在 public）
DEFAULT_COMPANY_CODE = PUBLIC_SCHEMA

# 连接池按 schema 缓存。**必须缓存**：每次 create_engine 都会新建一个连接池，
# 不缓存的话每个请求都会新建池、连接数瞬间打满。
_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker] = {}

# 当前请求的账套号。由 get_db() 设置，供 load_company() 这类"想知道自己在哪本账上"
# 的工具函数读取。用 ContextVar 而不是全局变量：并发请求之间不会互相串。
_current_company: ContextVar[str] = ContextVar("erp_current_company", default=DEFAULT_COMPANY_CODE)


def engine_for(schema_name: str) -> Engine:
    """取（或建）某个账套的**运行时** engine：`search_path=<schema>,public`。

    带 public 是必须的：用户、菜单、数字字典这些全局表只存在于 public，
    账套 schema 里没有它们，不带 public 就一张都读不到。
    """
    schema = (schema_name or PUBLIC_SCHEMA).strip() or PUBLIC_SCHEMA
    cached = _engines.get(schema)
    if cached is not None:
        return cached

    if schema == PUBLIC_SCHEMA:
        # 第一个账套就是现状：用默认连接，search_path 保持 PG 默认
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=not settings.database_url.startswith("sqlite"),
        )
    else:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=not settings.database_url.startswith("sqlite"),
            # 用 connect_args 固化 search_path：连接一建立就定死，池化复用不会串
            connect_args={"options": f"-c search_path={schema},public"},
        )
    _engines[schema] = engine
    return engine


# 建表 / 补列专用的 engine 缓存（与运行时分开，理由见 ddl_engine_for）
_ddl_engines: dict[str, Engine] = {}


def ddl_engine_for(schema_name: str) -> Engine:
    """**建表与补列专用** engine：`search_path=<schema>`，**不带 public**。

    ⚠️ 这个函数的存在本身就是踩坑换来的。SQLAlchemy 的 `has_table` 是**按 search_path
    解析**的，而不是按 `current_schema()` 精确查。所以如果建表时 search_path 里带着
    public，在账套 schema 还没有 `products` 时 `has_table("products")` 会**返回 True**
    （找到的是 public 里那张），于是 `create_all(checkfirst=True)` 认为"全都已存在"，
    **一张表都不建，而且不报任何错**。症状要到用户访问业务页才爆：relation 不存在。

    实测确认过：`search_path=co_test01,public` 时 `has_table("products")` == True，
    而 `information_schema` 里 co_test01 的表数是 0。

    把 public 去掉之后，`has_table` 只会在账套 schema 里找，建表与补列都落在正确的
    schema 上。运行时仍然用 `engine_for()`（带 public）—— 那里需要能读到全局表。
    """
    schema = (schema_name or PUBLIC_SCHEMA).strip() or PUBLIC_SCHEMA
    cached = _ddl_engines.get(schema)
    if cached is not None:
        return cached
    if schema == PUBLIC_SCHEMA:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=not settings.database_url.startswith("sqlite"),
        )
    else:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=not settings.database_url.startswith("sqlite"),
            connect_args={"options": f"-c search_path={schema}"},
        )
    _ddl_engines[schema] = engine
    return engine


def session_factory_for(schema_name: str) -> sessionmaker:
    schema = (schema_name or PUBLIC_SCHEMA).strip() or PUBLIC_SCHEMA
    factory = _session_factories.get(schema)
    if factory is None:
        _assert_schema_usable(schema)
        factory = sessionmaker(autocommit=False, autoflush=False, bind=engine_for(schema))
        _session_factories[schema] = factory
    return factory


class UnknownCompanySchema(RuntimeError):
    """凭证里的账套 schema 不存在。

    必须**当场报错**而不是回落默认账套：PG 会跳过 search_path 里不存在的 schema，
    于是请求会悄悄读到 public（第一个账套）的数据 —— 那不是降级，那是串账，
    而且界面上看起来一切正常。
    """


def _assert_schema_usable(schema: str) -> None:
    if schema == PUBLIC_SCHEMA:
        return
    if not schema.replace("_", "").isalnum():
        raise UnknownCompanySchema(f"账套 schema 名不合法：{schema}")
    try:
        names = inspect(engine_for(PUBLIC_SCHEMA)).get_schema_names()
    except Exception as exc:  # 连不上库是另一个问题，不要伪装成"账套不存在"
        raise UnknownCompanySchema(f"无法校验账套 schema（{exc}）") from exc
    if schema not in names:
        raise UnknownCompanySchema(
            f"账套 schema「{schema}」不存在。可能账套已被删除，或凭证来自另一套环境；请重新登录。"
        )


def set_current_company(code: str) -> None:
    _current_company.set((code or DEFAULT_COMPANY_CODE).strip() or DEFAULT_COMPANY_CODE)


def current_company_code() -> str:
    return _current_company.get()


def company_code_from_request(request: Any) -> str:
    """从请求的 Bearer token 里取账套 **schema 名**。

    解析失败 / 老 token 没有该声明 → 默认账套（＝现状），
    这样"升级后还没重新登录的会话"依然能正常用。
    """
    try:
        token = bearer_token(request.headers.get("authorization"))
    except Exception:
        return DEFAULT_COMPANY_CODE
    payload = decode_access_token(token)
    if not payload:
        return DEFAULT_COMPANY_CODE
    code = payload.get("company")
    return str(code).strip() if code else DEFAULT_COMPANY_CODE


def tenant_tables(metadata) -> list:
    """需要在**账套 schema** 里建的表（＝全部表减去全局表）。

    建库脚本用它 `create_all(tables=...)`，避免把全局表也复制进每个账套
    —— 复制进去的话，菜单/字典会被 search_path 遮住，管理员改一套另一套不生效。
    """
    return [table for name, table in metadata.tables.items() if name not in GLOBAL_TABLES]


def schema_exists(engine: Engine, schema: str) -> bool:
    return schema in inspect(engine).get_schema_names()


def create_tenant_schema(schema: str) -> None:
    """建账套 schema（幂等）。只建 schema，不建表 —— 建表交给 create_all。"""
    from sqlalchemy import text

    schema = (schema or "").strip()
    if not schema or schema == PUBLIC_SCHEMA:
        return
    # schema 名会拼进 SQL，只允许字母数字下划线，杜绝注入
    if not schema.replace("_", "").isalnum():
        raise ValueError(f"账套 schema 名不合法：{schema}")
    engine = engine_for(schema)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def create_tenant_tables(schema: str, metadata) -> None:
    """在账套 schema 里建业务表 + 补列（幂等）。

    ⚠️ 建表与补列**必须用 `ddl_engine_for`（search_path 不带 public）**，
    否则 `create_all` 的 checkfirst 会误判"表已存在"而一张都不建。详见 `ddl_engine_for`。
    """
    from app.main import ensure_schema_in  # 延迟导入：main 会 import 本模块

    ddl = ddl_engine_for(schema)
    metadata.create_all(ddl, tables=tenant_tables(metadata))
    ensure_schema_in(ddl)
