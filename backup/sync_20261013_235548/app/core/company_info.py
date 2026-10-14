"""公司主体信息 —— 合同 / 单据打印的"我方"抬头。

存放在项目根目录 `company.json`（PyInstaller 打包后写在 exe 同目录，保证可写），
优先级：company.json > 环境变量 ERP_COMPANY_* > 空字符串。

为什么不用环境变量做唯一来源：桌面版用户不会改环境变量；
为什么不入库：公司抬头是部署级配置，跟着程序走比跟着库走更稳
（两套部署共用同一个库，抬头却各自不同）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 字段名与合同表的 own_* 列一一对应
COMPANY_FIELDS: list[str] = [
    "own_name",
    "own_tax_no",
    "own_legal_person",
    "own_address",
    "own_contact",
    "own_phone",
    "own_bank_name",
    "own_bank_account",
]


def company_file() -> Path:
    if getattr(sys, "_MEIPASS", None):  # PyInstaller 打包：写在 exe 旁边（_MEIPASS 是只读解包目录）
        return Path(sys.executable).resolve().parent / "company.json"
    return Path(__file__).resolve().parent.parent.parent / "company.json"


def _env_default(field: str) -> str:
    # own_name -> ERP_COMPANY_NAME
    return os.environ.get("ERP_COMPANY_" + field[4:].upper(), "") or ""


def load_company() -> dict[str, str]:
    try:
        data = json.loads(company_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {field: str(data.get(field) or _env_default(field)) for field in COMPANY_FIELDS}


def save_company(payload: dict) -> dict[str, str]:
    clean = {field: str(payload.get(field) or "").strip() for field in COMPANY_FIELDS}
    company_file().write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean
