# -*- coding: utf-8 -*-
"""统一的数据库连接串解析 —— scripts/ 下所有运维脚本共用。

为什么要有这个文件
------------------
2026-10-26 安全整改：此前十几个脚本各自把 `erp:erp123456` 写死在默认值里，
换密码就得逐个改，而且明文进了 Git 历史。现在**密码只有一处**：项目根 `.env`。

优先级：显式环境变量 > 项目根 .env > 直接报错（不再有内置默认密码）
这样迁移/验收脚本可以用 ERP_DSN、ERP_DB_URL 之类临时覆盖，也不必再写死。

用法（按文档里的跑法 `python scripts\\xxx.py` 时，scripts/ 已在 sys.path[0]）：
    from db_config import database_url, psycopg_dsn, libpq_dsn

    database_url()  -> postgresql+psycopg://...   （SQLAlchemy）
    psycopg_dsn()   -> postgresql://...           （psycopg / psql 命令行）
    libpq_dsn()     -> host=... port=... dbname=... user=... password=...  （libpq）
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

_loaded = False


def _load_env() -> None:
    """只加载一次项目根 .env；已存在的环境变量优先（override=False）。"""
    global _loaded
    if _loaded:
        return
    if ENV_FILE.exists():
        from dotenv import load_dotenv

        load_dotenv(ENV_FILE, override=False)
    _loaded = True


def _raw_url() -> str:
    _load_env()
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL 未配置：请在 %s 里写明 "
            "postgresql+psycopg://用户:密码@127.0.0.1:5432/erp（脚本内不再保留默认密码）" % ENV_FILE
        )
    return url


def database_url() -> str:
    """SQLAlchemy 用的连接串。"""
    return _raw_url()


def psycopg_dsn() -> str:
    """psycopg.connect / psql 用的连接串。"""
    return _raw_url().replace("postgresql+psycopg://", "postgresql://", 1)


def libpq_dsn() -> str:
    """libpq 的 key=value 形式（psql -d "host=..." 那种）。"""
    parsed = urllib.parse.urlsplit(psycopg_dsn())
    if not parsed.password:
        raise RuntimeError("DATABASE_URL 里没有密码，无法生成 libpq 连接串")
    db = (parsed.path or "/erp").lstrip("/") or "erp"
    return (
        "host=%s port=%s dbname=%s user=%s password=%s"
        % (
            parsed.hostname or "127.0.0.1",
            parsed.port or 5432,
            db,
            urllib.parse.unquote(parsed.username or "erp"),
            urllib.parse.unquote(parsed.password),
        )
    )
