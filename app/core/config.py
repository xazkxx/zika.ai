import os
import secrets
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 这个默认值以前**就是这么发出去的**：.env 里没有 SECRET_KEY 时，HS256 的签名密钥
# 就固定成了这串公开字符串 —— 任何人都能用它签出一张 `sub=admin, role=admin` 的
# token，等于没有登录。见下面 `_load_or_create_secret`：仍是默认值时自动换成
# 随机密钥并落盘，所以这里只当"是否被显式配置过"的哨兵用。
DEFAULT_SECRET_KEY = "change-me-in-production"


def _env_file() -> str:
    # PyInstaller 打包后资源解包到 _MEIPASS，.env 一起打在包里
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        bundled = Path(bundle) / ".env"
        if bundled.exists():
            return str(bundled)
    return ".env"


class Settings(BaseSettings):
    app_name: str = "ERP Core"
    database_url: str = "sqlite:///./erp.db"
    secret_key: str = DEFAULT_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # 网关鉴权（P0-1「方案 B」）：enforce = 生产口径，/api/v1 下除白名单外一律要 token；
    # off 只留给本地联调和存量测试（见 app/core/auth_gate.py 的模块注释）。
    auth_mode: str = "enforce"
    # 自助注册。默认关闭：这个接口当年就是后门 —— 谁都能 POST 一个 role=admin 的账号进去。
    # 真正建用户请走「系统设置 → 用户管理」(/system/users)，那条路有管理员校验。
    allow_self_register: bool = False

    model_config = SettingsConfigDict(env_file=_env_file(), extra="ignore")


def _secret_file() -> Path:
    """密钥落盘位置：默认用户目录（打包成 exe 后 _MEIPASS 只读，不能放那）。"""
    override = (os.environ.get("ERP_SECRET_FILE") or "").strip()
    if override:
        return Path(override)
    return Path.home() / ".erp_core" / "secret_key"


def _load_or_create_secret() -> str:
    """没配密钥时生成一把随机密钥并持久化。

    为什么要落盘而不是每次都随机：token 的签名密钥一变，所有人手上的凭证立刻失效
    （表现为"刚登录完又被打回登录页"）。落盘后只有第一次启动会写一次。

    读不走、写不进时退化成"本次进程内随机" —— 宁可让用户重启后重新登录一次，
    也不能退回那串公开的默认密钥。
    """
    path = _secret_file()
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        path.write_text(value, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:  # Windows 上 chmod 语义有限，失败不算问题
            pass
        print(f"[security] 已在 {path} 生成 JWT 密钥（此前用的是公开默认值，任何人可伪造凭证）")
        return value
    except OSError as exc:
        print(f"[security] 密钥文件不可用（{exc}），本次进程使用临时随机密钥；重启后需重新登录")
        return secrets.token_urlsafe(48)


settings = Settings()

if settings.secret_key == DEFAULT_SECRET_KEY:
    settings.secret_key = _load_or_create_secret()
