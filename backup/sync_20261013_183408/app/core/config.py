import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    model_config = SettingsConfigDict(env_file=_env_file(), extra="ignore")


settings = Settings()
