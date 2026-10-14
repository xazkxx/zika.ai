"""数据库会话。

`SessionLocal` / `engine` 绑的是**默认连接**（search_path 默认，即 `public`）——
也就是第一个账套，同时是全局表（用户/账套/菜单/字典/日志）的落脚处。
后台任务、播种脚本、测试直连用的都是它。

`get_db()` 是**请求级**的：它按当前请求所属的账套，把会话接到对应的 schema 上。
业务路由用的都是它，所以一行业务代码都不用改就能支持多账套。

⚠️ 不要把 `SessionLocal` 用在业务路由里 —— 那会固定读第一个账套，
   在多账套下就是**串账**。业务一律用 `get_db()`。
"""

from collections.abc import Generator

from fastapi import HTTPException, Request, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import tenant
from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=not settings.database_url.startswith("sqlite"), connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(request: Request) -> Generator[Session, None, None]:
    """请求级会话：按 token 里的账套 schema 接到对应的库。

    没有 request 的场景（后台任务、脚本、测试）请直接用 `SessionLocal`。
    老 token 里没有账套声明时回落到默认账套 —— 升级后未重新登录的会话照常可用。
    """
    code = tenant.company_code_from_request(request)
    tenant.set_current_company(code)
    try:
        factory = tenant.session_factory_for(code)
    except tenant.UnknownCompanySchema as exc:
        # 凭证指向一个不存在的账套（被删了 / 来自另一套环境 / 被篡改）。
        # 用 401 而不是 500：前端看到 401 会清掉 token 重新登录，看到 500 只会白屏。
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    db = factory()
    try:
        yield db
    finally:
        db.close()
