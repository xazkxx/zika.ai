"""公司主体信息 —— 合同 / 单据打印的"我方"抬头。

## 第 1 期（多账套）后的存放位置

抬头从 `company.json` 搬进了 **`companies` 表的账套行**。原因：抬头原先是
**部署级**配置（一台机器一份），而**进销项判定靠本公司税号** ——
多公司下每家公司必须有自己的税号，否则"别人开给我们的票"会被判成销项。

`company.json` 退化为**兼容层**，只在两种情况还起作用：
- 升级到多账套之前（`companies` 表还没建）；
- 表在但一行都没有（极端情况）。

读取顺序：**当前账套的行 → company.json → 环境变量**。这样老部署升上来不会炸，
新部署则一切以数据库为准。

## 为什么不用环境变量做唯一来源

桌面版用户不会改环境变量；而且它同样是部署级的，解决不了"一个部署两套抬头"。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy.orm import Session

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

# 对外字段名 → companies 表的列名
#
# ⚠️ `own_name` 映射到 `own_name` 而**不是** `name`：`name` 是账套名（NOT NULL，
# 给菜单/顶栏显示用），抬头的名称是另一个字段。两者分开之后：
#   · 清空抬头不会把账套名一起抹掉（NOT NULL 也守得住）；
#   · 进销项在抬头为空时能老实返回"待判定"，而不是拿账套名去冒充抬头。
_FIELD_TO_COLUMN: dict[str, str] = {
    "own_name": "own_name",
    "own_tax_no": "tax_no",
    "own_legal_person": "legal_person",
    "own_address": "address",
    "own_contact": "contact",
    "own_phone": "phone",
    "own_bank_name": "bank_name",
    "own_bank_account": "bank_account",
}


def company_file() -> Path:
    if getattr(sys, "_MEIPASS", None):  # PyInstaller 打包：写在 exe 旁边（_MEIPASS 是只读解包目录）
        return Path(sys.executable).resolve().parent / "company.json"
    return Path(__file__).resolve().parent.parent.parent / "company.json"


def _env_default(field: str) -> str:
    # own_name -> ERP_COMPANY_NAME
    return os.environ.get("ERP_COMPANY_" + field[4:].upper(), "") or ""


def _from_json() -> dict[str, str]:
    try:
        data = json.loads(company_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return {field: str(data.get(field) or _env_default(field)) for field in COMPANY_FIELDS}


def _current_company_row(db: Session | None):
    """取当前账套的公司行。

    读的是 `companies`（全局表，在 public），所以**任何账套的会话都能读到它**，
    不必切回默认连接。账套表还没建 / 没有行时返回 None，由调用方回落 json。
    """
    from app.core import tenant
    from app.models.company import Company

    owns_session = db is None
    session = db
    if owns_session:
        from app.db.session import SessionLocal

        session = SessionLocal()
    try:
        schema = tenant.current_company_code()
        row = session.query(Company).filter(Company.schema_name == schema).first()
        if row is None:
            row = session.query(Company).order_by(Company.sort_order, Company.id).first()
        return row
    except Exception:
        # 表不存在（升级前的库）或任何读取问题 → 交给调用方回落 json，
        # 绝不因为"抬头读不到"就让打印/开票整个挂掉
        return None
    finally:
        if owns_session and session is not None:
            session.close()


def load_company(db: Session | None = None) -> dict[str, str]:
    row = _current_company_row(db)
    if row is not None:
        return {field: str(getattr(row, _FIELD_TO_COLUMN[field], "") or "") for field in COMPANY_FIELDS}
    return _from_json()


def save_company(payload: dict, db: Session | None = None) -> dict[str, str]:
    """保存抬头。**优先写账套表**，没有账套行时才回落 company.json。

    刻意**不碰 `companies.name`**（账套名）：账套名是显示用的标签，抬头是可清空的
    税务信息，两者不是一回事。合并成一个字段时，用户清空抬头会把 NOT NULL 的
    账套名写成 NULL，直接违反约束报错（这个坑真的踩过）。
    """
    clean = {field: str(payload.get(field) or "").strip() for field in COMPANY_FIELDS}
    row = _current_company_row(db)
    if row is None:
        company_file().write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        return clean

    owns_session = db is None
    session = db
    if owns_session:
        from app.db.session import SessionLocal

        session = SessionLocal()
    try:
        for field, column in _FIELD_TO_COLUMN.items():
            # 清空要真的清空（写 NULL）。不写空串是为了让"没填"和"填了空"在库里
            # 是同一种状态，查询与判定都少一个分支。
            setattr(row, column, clean[field] or None)
        # 账套名跟着抬头走（顶栏显示的就是它，两处不一致会让人以为切错账套了）。
        # 但**抬头被清空时不动账套名** —— `name` 是 NOT NULL，
        # 而且账套列表里总得有个标签能认人。这两件事分开处理是刻意的：
        # 合并成一个字段时，清空抬头会直接违反 NOT NULL 约束报错（踩过）。
        if clean["own_name"]:
            row.name = clean["own_name"]
        session.add(row)
        session.commit()
    finally:
        if owns_session:
            session.close()
    # json 也同步一份：换回旧版本 / 未升级的部署时，抬头不至于空掉
    try:
        company_file().write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return clean
