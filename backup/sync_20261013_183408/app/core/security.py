from datetime import datetime, timedelta, timezone

from jose import jwt
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
