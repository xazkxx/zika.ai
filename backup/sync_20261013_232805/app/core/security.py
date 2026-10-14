"""密码哈希与 JWT。

`decode_access_token` 是给**操作日志中间件**用的：中间件拿不到 FastAPI 的
依赖注入（`get_current_user` 只在路由里生效），但要记下"是谁干的"，
所以这里提供一个"解不出来就返回 None"的宽松版本 —— 日志不因为
一个过期 token 而报错。
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str, role: str = "staff", expires_delta: int | None = None) -> str:
    if expires_delta is None:
        expires_delta = settings.access_token_expire_minutes

    to_encode = {
        "sub": subject,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_delta),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str | None) -> dict | None:
    """解 JWT。任何问题（缺 token / 过期 / 签名不对 / 格式错）都返回 None。

    调用方是操作日志中间件，它只想知道"这条请求带了谁的 token"，
    解析失败按匿名记录即可，绝不抛异常。
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    return payload if isinstance(payload, dict) else None


def bearer_token(authorization: str | None) -> str | None:
    """从 `Authorization: Bearer xxx` 里抠出 token。没有则返回 None。"""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None
