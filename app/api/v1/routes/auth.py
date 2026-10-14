from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas import Token, UserCreate, UserLogin, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        # 账号被管理员停用：即使密钥正确也不放行（401 会被理解成"密码错"，用 403 表意更准）
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")
    return user


def require_roles(*allowed_roles: str):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return current_user

    return dependency


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    existing = db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    item = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role or "staff",
        hashed_password=get_password_hash(payload.password),
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/login", response_model=Token)
def login_user(payload: UserLogin, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    # 把"试图登录的用户名"放到 request.state，供操作日志中间件读取。
    # 中间件拿不到请求体（读了会把流消耗掉），所以只能由路由主动交代；
    # 好处是**密码错、账号停用这些失败尝试也能记下是谁在试**，
    # 而中间件按 token 解析的话，登录请求永远记不到用户名。
    request.state.log_username = payload.username

    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password")
    # 停用账号不得登录（系统管理页的「停用」按钮靠这里真正生效）
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")

    # 记一笔最后登录时间，管理页上能看到谁在用、谁在挂
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    companies = _companies_of(db, user)
    active = _resolve_target_company(db, user, companies, getattr(payload, "company", None))
    token = create_access_token(subject=user.username, role=user.role, company=active["schema_name"])
    return _token_payload(token, user, active, companies)


# ============================================================
# 多账套（多公司）：账套清单与切换
# ============================================================
def _companies_of(db: Session, user: User) -> list[dict[str, object]]:
    """该用户能进入的账套清单。

    **没有任何归属记录时回落到默认账套**（而不是"什么都进不去"）：
    老部署升级上来时 `user_companies` 还是空的，如果这里返回空清单，
    所有历史账号会**立刻登不进去**。宁可先让它们进第一个账套，再由管理员分配。
    """
    from app.models.company import Company, UserCompany

    rows = (
        db.query(Company, UserCompany)
        .join(UserCompany, UserCompany.company_id == Company.id)
        .filter(UserCompany.user_id == user.id, Company.is_active.is_(True))
        .order_by(Company.sort_order, Company.id)
        .all()
    )
    if not rows:
        fallback = (
            db.query(Company)
            .filter(Company.is_active.is_(True))
            .order_by(Company.sort_order, Company.id)
            .first()
        )
        if fallback is None:
            return []
        return [
            {
                "id": fallback.id,
                "code": fallback.code,
                "name": fallback.name,
                "schema_name": fallback.schema_name,
                "tax_no": fallback.tax_no,
                "is_default": True,
            }
        ]
    return [
        {
            "id": company.id,
            "code": company.code,
            "name": company.name,
            "schema_name": company.schema_name,
            "tax_no": company.tax_no,
            "is_default": bool(link.is_default),
        }
        for company, link in rows
    ]


def _resolve_target_company(
    db: Session, user: User, companies: list[dict[str, object]], wanted: str | None
) -> dict[str, object]:
    """决定这次登录进哪个账套。

    `wanted` 可以是账套号（给人看的 code）也可以是 schema 名。
    **只在该用户的账套清单里找** —— 不在清单里就回落到他的默认账套，
    而不是报错：前端可能存着一个已经被取消权限的账套号，那种情况下
    "悄悄退回默认账套继续用"比"报错登不进去"对用户友好得多，
    而且**不会越权**（清单本身就是权限边界）。
    """
    if not companies:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="这个账号还没有被分配到任何账套，请联系管理员在「系统设置 → 账套管理」里分配。",
        )
    if wanted:
        for row in companies:
            if wanted in (row["code"], row["schema_name"]):
                return row
    for row in companies:
        if row.get("is_default"):
            return row
    return companies[0]


def _token_payload(
    token: str, user: User, active: dict[str, object], companies: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "company": active["schema_name"],
        "company_name": active["name"],
        "companies": companies,
    }


@router.get("/companies")
def list_my_companies(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[dict[str, object]]:
    """当前用户可进入的账套清单（前端做切换下拉用）。"""
    return _companies_of(db, current_user)


@router.post("/switch-company", response_model=Token)
def switch_company(
    payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict[str, object]:
    """切换当前账套 —— **换发一张新 token**。

    为什么不在请求头里传"我要看哪家"：那样服务端每次都得校验，
    而凭证里带 schema 就等于把校验结果固定下来，少一次可能的疏漏。
    切换本身要过 `_resolve_target_company` 的成员校验，所以换发出来的凭证是可信的。
    """
    wanted = str((payload or {}).get("company") or "").strip()
    companies = _companies_of(db, current_user)
    active = _resolve_target_company(db, current_user, companies, wanted)
    if wanted and active["schema_name"] != wanted and active["code"] != wanted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有这家公司的访问权限")
    token = create_access_token(
        subject=current_user.username, role=current_user.role, company=active["schema_name"]
    )
    return _token_payload(token, current_user, active, companies)


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/admin-check")
def admin_check(current_user: User = Depends(require_roles("admin"))) -> dict[str, str]:
    return {"status": "ok", "role": current_user.role}


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[User]:
    query = db.query(User)
    if skip and skip > 0:
        query = query.offset(skip)
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return query.all()
