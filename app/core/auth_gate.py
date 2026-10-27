"""网关级鉴权 —— P0-1「方案 B」。

为什么是中间件而不是逐路由 `Depends(get_current_user)`
--------------------------------------------------------
2026-10-26 的 `scripts/audit_auth_routes.py` 扫出一份清单：**320 个 /api/v1 端点里
318 个没有任何身份校验**。也就是说，只要能访问到 8010 端口，不登录就能读全量客户、
改单、导出报表 —— 前端有个登录页，但登录页只是"前端的礼貌"，后端一律照单全收。

在这种比例下逐路由补 `Depends(...)` 是**改不完也验不完**的：
  · 320 个函数要一个个改，改漏的那一个不会报错，只会继续裸奔；
  · 以后新加的路由同样默认裸奔 —— 默认值是"不安全"，这个方向本身就是错的。

所以反过来做：**默认拒绝，白名单放行**。新增路由自动受保护，忘记加白名单的代价
是"访问被拒"（可发现、会报错），而不是"数据被读走"（静默、不可发现）。

白名单只有四类，都必须是**登录前就要能访问**的：
  · `/api/v1/health`            探活（桌面端启动时轮询它等后端就绪）
  · `/api/v1/auth/login`        登录本身
  · `/api/v1/auth/register`     自助注册（默认已关闭，见 settings.allow_self_register；
                                放行到这里是为了让路由自己返回 403 的中文说明，
                                而不是被网关拦成一个看不懂的 401）
  · `/api/v1/uploads/products/` 商品图片。前端是 `<img src="/api/v1/uploads/...">`，
    浏览器发这种请求**不会带 Authorization**，拦了就是整页缩略图全空。
    这里只放开只读的商品图目录，业务数据一律不放。

关于 `auth_mode="off"`
----------------------
存量测试有 61 个文件、几百条用例在 `TestClient(app)` 上直接打业务接口，都没有登录语义。
`tests/conftest.py` 会给这些 client 统一注入一张管理员 token，所以**测试跑的是 enforce**；
`off` 只是留一个应急开关（比如现场排障时要临时比对裸接口返回），默认值永远是 enforce。
"""

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.security import bearer_token, decode_access_token

API_PREFIX = "/api/v1"

# 精确匹配：登录前就要能访问的少数几个地址
PUBLIC_PATHS = frozenset(
    {
        f"{API_PREFIX}/health",
        f"{API_PREFIX}/auth/login",
        f"{API_PREFIX}/auth/register",
    }
)

# 前缀匹配：只放商品图（浏览器 <img> 带不了请求头）
PUBLIC_PREFIXES = (f"{API_PREFIX}/uploads/products/",)

_OFF_VALUES = frozenset({"off", "disabled", "open", "bypass"})
_off_warned = False


def auth_enforced() -> bool:
    """当前是否要求身份。`off` 时返回 False（会在控制台吼一次，避免悄悄裸奔）。"""
    global _off_warned
    if str(settings.auth_mode or "").strip().lower() in _OFF_VALUES:
        if not _off_warned:
            _off_warned = True
            print("[security] 警告：auth_mode=off，/api/v1 接口不校验身份 —— 仅限联调/排障")
        return False
    return True


def is_public_path(path: str) -> bool:
    # 末尾斜杠归一：`/api/v1/health/` 也要算白名单（否则探活会因为一个斜杠变成 401）
    normalized = path.rstrip("/") or "/"
    if normalized in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _load_user(username: str):
    """按用户名取用户。注意：`users` 是全局表（不随账套变），所以这里不受租户影响。"""
    from app.db.session import SessionLocal
    from app.models.user import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        db.close()


def resolve_request_identity(authorization: str | None):
    """校验请求头里的凭证，返回 (user, 错误响应)。

    除了签名与过期时间，**还要回库确认账号仍然存在且未停用**：
    停用是管理员的即时动作，如果只看签名，被停用的人手里的旧 token 还能继续用到过期
    （默认 60 分钟），「停用」按钮就等于没按。
    """
    token = bearer_token(authorization)
    if not token:
        return None, _unauthorized("未登录：请在请求头带上 Authorization: Bearer <token>")
    payload = decode_access_token(token)
    username = (payload or {}).get("sub")
    if not payload or not username:
        return None, _unauthorized("登录凭证无效或已过期，请重新登录")
    user = _load_user(str(username))
    if user is None:
        return None, _unauthorized("登录凭证对应的账号已不存在，请重新登录")
    if not user.is_active:
        return None, JSONResponse({"detail": "账号已停用，请联系管理员"}, status_code=403)
    return user, None


async def auth_gate_middleware(request, call_next):
    path = request.url.path

    # 只守 /api/v1：静态站（/、/assets/*）、/docs、/openapi.json 不归这里管
    if not path.startswith(API_PREFIX) or is_public_path(path) or not auth_enforced():
        return await call_next(request)

    # 预检请求不带 Authorization（浏览器规矩），拦了等于让跨域前端整体瘫痪
    if request.method.upper() == "OPTIONS":
        return await call_next(request)

    user, error = await run_in_threadpool(
        resolve_request_identity, request.headers.get("authorization")
    )
    if error is not None:
        return error

    # 交给下游复用，省得每个路由再解一次 token
    request.state.auth_user = user
    request.state.auth_username = user.username
    return await call_next(request)
