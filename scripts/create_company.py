"""新建一个账套（多公司）。

    python scripts/create_company.py --code co_02 --name "陕西某某贸易有限公司" --tax-no 91610...  --user admin

做什么：注册账套 → 建 schema → 建该账套的业务表 → 补列 → 把指定用户加进这个账套。
幂等：重复执行只会补缺失的部分，不会重建、更不会清数据。

**不做**什么（刻意的）：不复制第一家公司的业务数据。新账套的客户/商品/仓库都是空的
——"新建一家公司"本来就该是干净的一本账。要搬基础资料请用「导入导出」页，
那样档案的编码/唯一约束冲突能被人看见并处理，比脚本直接 INSERT 安全。

⚠️ 建完要让用户**重新登录**才能进新账套：账套是写在 JWT 里的（见 app/core/tenant.py），
   老 token 里带的是原来那一家。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect  # noqa: E402

from app.core import tenant  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401  必须导入：不然 Base.metadata 里没有表
from app.models.company import GLOBAL_TABLES, PUBLIC_SCHEMA, Company, UserCompany  # noqa: E402
from app.models.user import User  # noqa: E402


def _validate_code(code: str) -> str:
    code = (code or "").strip()
    if not code:
        raise SystemExit("账套号不能为空")
    if code == PUBLIC_SCHEMA:
        raise SystemExit(f"「{PUBLIC_SCHEMA}」是第一个账套保留的，请换一个账套号")
    if not code.replace("_", "").isalnum():
        raise SystemExit("账套号只能用字母、数字、下划线（它同时会作为 schema 名）")
    if len(code) > 40:
        raise SystemExit("账套号太长（最多 40 字符）")
    return code


def create_company(code: str, name: str, tax_no: str = "", grant_users: list[str] | None = None) -> None:
    code = _validate_code(code)
    name = (name or "").strip()
    if not name:
        raise SystemExit("公司名称不能为空")

    db = SessionLocal()
    try:
        existing = db.query(Company).filter(Company.code == code).first()
        if existing is not None:
            print(f"账套「{code}」已存在（id={existing.id}, schema={existing.schema_name}），只补缺失的部分。")
            company = existing
        else:
            company = Company(
                code=code,
                name=name,
                tax_no=(tax_no or "").strip() or None,
                schema_name=code,  # schema 与账套号一致；之后改账套号不会动 schema
                is_active=True,
                sort_order=100,
                note="由 scripts/create_company.py 创建",
            )
            db.add(company)
            db.commit()
            db.refresh(company)
            print(f"✓ 已注册账套「{name}」（code={code}, id={company.id}）")
    finally:
        db.close()

    # —— 建 schema 与业务表 ——
    schema = code
    tenant.create_tenant_schema(schema)
    print(f"✓ schema「{schema}」就绪")
    tenant.create_tenant_tables(schema, Base.metadata)

    engine = tenant.engine_for(schema)
    tables = inspect(engine).get_table_names(schema=schema)
    # 用 GLOBAL_TABLES 而不是"手工减掉两张表"：全局表清单是会变的，
    # 写死的话新增一张全局表就会把它的副本也建进账套里，之后 search_path
    # 会把账套里那份遮住 global 那份 —— 管理员改一套、另一套不生效。
    local_tables = [t for t in tables if t not in GLOBAL_TABLES]
    print(f"✓ 业务表 {len(local_tables)} 张已建好（用户/菜单/字典等全局表共用 public）")

    # —— 把用户加进这个账套 ——
    if grant_users:
        db = SessionLocal()
        try:
            for username in grant_users:
                user = db.query(User).filter(User.username == username).first()
                if user is None:
                    print(f"! 用户「{username}」不存在，跳过")
                    continue
                link = (
                    db.query(UserCompany)
                    .filter(UserCompany.user_id == user.id, UserCompany.company_id == company.id)
                    .first()
                )
                if link is None:
                    db.add(UserCompany(user_id=user.id, company_id=company.id, is_default=False))
                    print(f"✓ 已把「{username}」加入账套「{company.name}」")
                else:
                    print(f"· 「{username}」本来就在这个账套里")
            db.commit()
        finally:
            db.close()

    print()
    print("下一步：")
    print("  1. 让相关用户**重新登录**（账套写在登录凭证里，老会话进不了新账套）")
    print(f"  2. 登录后到「系统设置 → 公司信息」把「{name}」的税号等抬头补全")
    print("     —— 进销项判定靠本公司税号，不补的话发票会一直是「待判定」")


def main() -> None:
    parser = argparse.ArgumentParser(description="新建一个账套（多公司）")
    parser.add_argument("--code", required=True, help="账套号，同时作为 schema 名，如 co_02")
    parser.add_argument("--name", required=True, help="公司名称")
    parser.add_argument("--tax-no", default="", help="本公司纳税人识别号（进销项判定用）")
    parser.add_argument(
        "--user",
        action="append",
        default=[],
        help="把该用户加入这个账套，可重复指定，如 --user admin --user zhangsan",
    )
    args = parser.parse_args()
    create_company(args.code, args.name, args.tax_no, args.user)


if __name__ == "__main__":
    main()
