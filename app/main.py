import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.api.v1.router import api_router
from app.core.security import get_password_hash
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.user import User


def _add_missing_columns(conn, table: str, additions: dict[str, str]) -> None:
    """给已存在的表补列（幂等）。新增列一律可空，不改动历史数据。"""
    inspector = inspect(conn)
    if not inspector.has_table(table):
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    for column_name, definition in additions.items():
        if column_name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {definition}"))


# 「浩技云进销存」融合改造：商品 / 客户 / 供应商档案补齐字段
PRODUCT_ADDITIONS = {
    "mnemonic": "VARCHAR(50)",
    "standards": "VARCHAR(100)",
    "brand": "VARCHAR(100)",
    "bar_code": "VARCHAR(80)",
    "color": "VARCHAR(50)",
    "size": "VARCHAR(50)",
    "manufacturer": "VARCHAR(150)",
    "serial_no": "VARCHAR(80)",
    "unit_weight": "DOUBLE PRECISION",
    "stock_upper": "INTEGER",
    "stock_lower": "INTEGER",
    "pack_qty": "INTEGER",
    "shelf_life": "INTEGER",
    "warn_days": "INTEGER",
    "image_url": "VARCHAR(255)",
    "note": "VARCHAR(255)",
}

CUSTOMER_ADDITIONS = {
    "businesser": "VARCHAR(50)",
    "contact": "VARCHAR(50)",
    "contact_phone": "VARCHAR(30)",
    "tax_no": "VARCHAR(50)",
    "bank_name": "VARCHAR(150)",
    "bank_account": "VARCHAR(80)",
    "level": "VARCHAR(30)",
    "discount": "DOUBLE PRECISION",
    "credit_limit": "DOUBLE PRECISION",
    "init_receivable": "DOUBLE PRECISION",
    "init_invoice_debt": "DOUBLE PRECISION",
    "relation_date": "VARCHAR(30)",
    "business_type": "VARCHAR(50)",
    "main_products": "VARCHAR(255)",
    "potential_amount": "DOUBLE PRECISION",
    "note": "VARCHAR(255)",
}

SUPPLIER_ADDITIONS = {
    "short_name": "VARCHAR(80)",
    "contact": "VARCHAR(50)",
    "main_contact": "VARCHAR(50)",
    "mobile": "VARCHAR(30)",
    "postcode": "VARCHAR(20)",
    "bank_name": "VARCHAR(150)",
    "bank_account": "VARCHAR(80)",
    "init_payable": "DOUBLE PRECISION",
    "init_invoice_debt": "DOUBLE PRECISION",
    "note": "VARCHAR(255)",
}

# 单据头：仓库绑定 + 业务信息 + 结算链 + 欠款链
PURCHASE_ORDER_ADDITIONS = {
    "warehouse_id": "INTEGER",
    "project_id": "INTEGER",
    "businesser": "VARCHAR(50)",
    "order_date": "VARCHAR(20)",
    "delivery_date": "VARCHAR(20)",
    "payment_method": "VARCHAR(30)",
    "contact": "VARCHAR(50)",
    "contact_phone": "VARCHAR(30)",
    "address": "VARCHAR(255)",
    "note": "VARCHAR(255)",
    "payable_amount": "DOUBLE PRECISION DEFAULT 0",
    "discount_amount": "DOUBLE PRECISION DEFAULT 0",
    "paid_amount": "DOUBLE PRECISION DEFAULT 0",
    "is_invoiced": "BOOLEAN DEFAULT FALSE",
    "current_debt": "DOUBLE PRECISION DEFAULT 0",
    "prev_debt": "DOUBLE PRECISION DEFAULT 0",
    "total_debt": "DOUBLE PRECISION DEFAULT 0",
    # 单据性质：order=采购订单 / inbound=采购入库单（历史数据全部视为入库单）
    "doc_type": "VARCHAR(20) NOT NULL DEFAULT 'inbound'",
    "source_order_id": "INTEGER",
}

SALES_ORDER_ADDITIONS = {
    "warehouse_id": "INTEGER",
    "project_id": "INTEGER",
    "businesser": "VARCHAR(50)",
    "order_date": "VARCHAR(20)",
    "delivery_date": "VARCHAR(20)",
    "payment_method": "VARCHAR(30)",
    "contact": "VARCHAR(50)",
    "contact_phone": "VARCHAR(30)",
    "address": "VARCHAR(255)",
    "note": "VARCHAR(255)",
    "receivable_amount": "DOUBLE PRECISION DEFAULT 0",
    "discount_amount": "DOUBLE PRECISION DEFAULT 0",
    "received_amount": "DOUBLE PRECISION DEFAULT 0",
    "is_invoiced": "BOOLEAN DEFAULT FALSE",
    "current_debt": "DOUBLE PRECISION DEFAULT 0",
    "prev_debt": "DOUBLE PRECISION DEFAULT 0",
    "total_debt": "DOUBLE PRECISION DEFAULT 0",
    # 单据性质：order=销售订单 / outbound=销售开单（历史数据全部视为开单）
    "doc_type": "VARCHAR(20) NOT NULL DEFAULT 'outbound'",
    "source_order_id": "INTEGER",
}

# 单据明细快照：打印单据时不必回查商品档案
ORDER_ITEM_ADDITIONS = {
    "product_name": "VARCHAR(150)",
    "standards": "VARCHAR(100)",
    "unit": "VARCHAR(50)",
    "note": "VARCHAR(255)",
}

# 财务 × 全模块关联
FINANCE_ADDITIONS = {
    "bank_account_id": "INTEGER",
    "category": "VARCHAR(50)",
    "handler": "VARCHAR(50)",
    "related_type": "VARCHAR(40)",
    "doc_no": "VARCHAR(50)",
    "direction": "VARCHAR(10)",
    "product_id": "INTEGER",
    "warehouse_id": "INTEGER",
    "project_id": "INTEGER",
    "occurred_at": "VARCHAR(20)",
    "period": "VARCHAR(7)",
}

# 库存流水溯源：让每条出入库都能追到来源单据，删单时可冲销
INVENTORY_ADDITIONS = {
    "related_type": "VARCHAR(40)",
    "related_order_id": "INTEGER",
    "doc_no": "VARCHAR(50)",
    "note": "VARCHAR(255)",
}

# 第 11 批：发票补业务属性（进销项 / 红蓝字 / 开票方式）与原始文件
INVOICE_ADDITIONS = {
    "direction": "VARCHAR(10) NOT NULL DEFAULT 'unknown'",
    "invoice_flag": "VARCHAR(10) NOT NULL DEFAULT 'blue'",
    "issue_mode": "VARCHAR(10) NOT NULL DEFAULT 'manual'",
    "handler": "VARCHAR(50)",
    # 原始文件：存相对路径（绝对路径换盘就失效）
    "source_path": "VARCHAR(255)",
    "source_name": "VARCHAR(255)",
    "source_size": "INTEGER",
    "source_mime": "VARCHAR(80)",
}

# 系统管理第 1 轮：用户挂部门 / 挂角色 / 联系方式 / 最后登录时间
USER_ADDITIONS = {
    "department_id": "INTEGER",
    "role_id": "INTEGER",
    "phone": "VARCHAR(30)",
    "position": "VARCHAR(50)",
    "remark": "VARCHAR(255)",
    "last_login_at": "TIMESTAMP WITH TIME ZONE",
}

# 开票税点：商品档案带一个默认税率，开单/开票时按商品带出、可逐单改。
# 历史商品全为 NULL（＝未设置），这是正确的初始态 —— 见 Product.tax_rate 的注释。
PRODUCT_ADDITIONS = {
    "tax_rate": "DOUBLE PRECISION",
}

# 多账套：账套表的补列。
# 抬头名称 `own_name` 是与账套名 `name` 分开的一列 ——
# 合并成一个字段时，用户清空抬头会把 NOT NULL 的账套名写成 NULL。
COMPANY_ADDITIONS = {
    "own_name": "VARCHAR(150)",
}


def ensure_schema_in(target_engine=None) -> None:
    """补列迁移（幂等）。按**传入的 engine** 跑，这样多账套下每个 schema 都能各跑一遍。

    账套 schema 里的表与 public 是各自独立的一份副本 —— 只在 public 上补列，
    新账套的表就会缺列，而且报错发生在业务查询里，很难联想到迁移。
    """
    target = target_engine if target_engine is not None else engine
    with target.begin() as conn:
        # ⚠️ 这里必须查**账套自己的表**（products），不能查 users。
        # SQLAlchemy 的 has_table 是按 schema 精确查的，不走 search_path ——
        # 而 users 是全局表、只存在于 public。账套 schema 里查 users 恒为 False，
        # 整个补列迁移会被这一行悄悄跳过，症状是"新账套的业务查询报缺列"。
        if not inspect(conn).has_table("products"):
            return

        # users 只在 public 有；账套 schema 里没有它是正常的，不要当成异常
        if inspect(conn).has_table("users"):
            columns = [column["name"] for column in inspect(conn).get_columns("users")]
            if "role" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'staff'"))
                conn.execute(text("UPDATE users SET role = 'staff' WHERE role IS NULL"))

        if inspect(conn).has_table("production_orders"):
            production_columns = [column["name"] for column in inspect(conn).get_columns("production_orders")]
            if "bom_id" not in production_columns:
                conn.execute(text("ALTER TABLE production_orders ADD COLUMN bom_id INTEGER"))

        if inspect(conn).has_table("production_boms"):
            bom_columns = [column["name"] for column in inspect(conn).get_columns("production_boms")]
            bom_additions = {
                "parent_id": "INTEGER",
                "name": "VARCHAR(150)",
                "code": "VARCHAR(80)",
                "bom_type": "VARCHAR(50) DEFAULT 'component'",
                "level": "INTEGER NOT NULL DEFAULT 0",
                "description": "VARCHAR(255)",
            }
            for column_name, definition in bom_additions.items():
                if column_name not in bom_columns:
                    conn.execute(text(f"ALTER TABLE production_boms ADD COLUMN {column_name} {definition}"))

        # 融合改造：三张档案表补列
        _add_missing_columns(conn, "products", PRODUCT_ADDITIONS)
        _add_missing_columns(conn, "customers", CUSTOMER_ADDITIONS)
        _add_missing_columns(conn, "suppliers", SUPPLIER_ADDITIONS)

        # 融合改造：单据结算链 / 欠款链 / 仓库绑定
        _add_missing_columns(conn, "purchase_orders", PURCHASE_ORDER_ADDITIONS)
        _add_missing_columns(conn, "sales_orders", SALES_ORDER_ADDITIONS)
        _add_missing_columns(conn, "purchase_order_items", ORDER_ITEM_ADDITIONS)
        _add_missing_columns(conn, "sales_order_items", ORDER_ITEM_ADDITIONS)

        # 融合改造：财务 × 全模块关联
        _add_missing_columns(conn, "financial_transactions", FINANCE_ADDITIONS)

        # 融合改造：库存流水溯源（开单联动库存 / 删单冲销）
        _add_missing_columns(conn, "inventory_transactions", INVENTORY_ADDITIONS)

        # 第 11 批：发票的业务属性与原始文件
        _add_missing_columns(conn, "invoices", INVOICE_ADDITIONS)

        # 第 12 批：总账凭证的 flow_id（凭证 ↔ 流水同生共死）。
        # 总账表在更早一轮里可能已经 create_all 建出来了，这里补上 flow_id 列
        # （幂等，只补缺，不影响已存在的凭证行）。
        _add_missing_columns(conn, "journal_entries", {"flow_id": "INTEGER"})

        # 系统管理第 1 轮：用户表补列（部门 / 角色 / 联系方式）
        _add_missing_columns(conn, "users", USER_ADDITIONS)

        # 开票税点：商品档案的默认税率
        _add_missing_columns(conn, "products", PRODUCT_ADDITIONS)

        # 多账套：账套表的补列（全局表，只在 public）
        _add_missing_columns(conn, "companies", COMPANY_ADDITIONS)


# ===========================================================================
# 多账套（多公司）第 1 期：账套注册、用户归属、各账套 schema 初始化
# ===========================================================================
def ensure_default_company() -> None:
    """把**现有这套部署**注册成第一个账套（幂等）。

    第一条记录的 schema 固定是 `public` —— 历史数据全在 public，沿用它意味着
    升级时**一个字节的业务数据都不用搬**，这是整套多账套设计里风险最低的一点。

    抬头从 `company.json` 搬进来（json 保留作兼容层，换回旧版本时抬头不至于空掉）。
    调用 `load_company()` 是刻意的：此刻 `companies` 表刚建好还是空的，
    它会自动回落到 json —— 正好拿到"升级前的抬头"。
    """
    from app.core.company_info import load_company
    from app.models.company import PUBLIC_SCHEMA, Company

    db = SessionLocal()
    try:
        existing = db.query(Company).filter(Company.schema_name == PUBLIC_SCHEMA).first()
        if existing is not None:
            # 补一次抬头名称：`own_name` 这一列是后加的，已存在的账套行会是 NULL。
            # 只在 json 里**确实有抬头**时才补 —— 用户主动清空抬头时
            # `save_company` 会把 json 也写成空，所以不会在这里被"复活"。
            if not existing.own_name:
                legacy_name = load_company().get("own_name")
                if legacy_name:
                    existing.own_name = legacy_name
                    db.commit()
            return
        legacy = load_company()
        db.add(
            Company(
                code=PUBLIC_SCHEMA,
                name=legacy.get("own_name") or "本公司",
                own_name=legacy.get("own_name") or None,
                tax_no=legacy.get("own_tax_no") or None,
                schema_name=PUBLIC_SCHEMA,
                legal_person=legacy.get("own_legal_person") or None,
                address=legacy.get("own_address") or None,
                contact=legacy.get("own_contact") or None,
                phone=legacy.get("own_phone") or None,
                bank_name=legacy.get("own_bank_name") or None,
                bank_account=legacy.get("own_bank_account") or None,
                is_active=True,
                sort_order=10,
                note="第一个账套：由升级前的那套数据自动注册（schema = public）",
            )
        )
        db.commit()
    finally:
        db.close()


def ensure_user_company_links() -> None:
    """给还没有任何账套归属的用户补上默认账套（幂等）。

    升级上来的库 `user_companies` 是空的。不补也能登录（`_companies_of` 有回落分支），
    但"归属"在管理页上就是一片空白，管理员会以为功能坏了。
    """
    from app.models.company import Company, UserCompany

    db = SessionLocal()
    try:
        default = db.query(Company).order_by(Company.sort_order, Company.id).first()
        if default is None:
            return
        changed = False
        for user in db.query(User).all():
            exists = db.query(UserCompany).filter(UserCompany.user_id == user.id).first()
            if exists is None:
                db.add(UserCompany(user_id=user.id, company_id=default.id, is_default=True))
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def ensure_all_tenant_schemas() -> None:
    """给每个**新账套**的 schema 建表 + 补列（幂等）。

    第一个账套（public）已经由上面的 `create_all` + `ensure_schema_in()` 处理过，
    这里跳过它。

    ⚠️ 单个账套初始化失败**不能拖垮整个服务**：第一个账套是现有生产数据，
    它必须能起来。失败的那一套打日志，修好重启即可。
    """
    from app.core import tenant as tenant_router
    from app.models.company import PUBLIC_SCHEMA, Company

    db = SessionLocal()
    try:
        schemas = [
            row.schema_name
            for row in db.query(Company).filter(Company.is_active.is_(True)).all()
            if row.schema_name and row.schema_name != PUBLIC_SCHEMA
        ]
    finally:
        db.close()

    for schema in schemas:
        try:
            tenant_router.create_tenant_schema(schema)
            tenant_router.create_tenant_tables(schema, Base.metadata)
            # 每个账套都要有自己的根部门：部门是账套表，
            # 新账套没有这一层的话「员工档案」连可选部门都没有
            ensure_default_departments(tenant_router.engine_for(schema))
        except Exception as exc:  # noqa: BLE001 —— 打印出来，不阻断启动
            print(f"[多账套] 账套 schema「{schema}」初始化失败：{exc}")


def ensure_default_admin_user() -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if user is None:
            db.add(
                User(
                    username="admin",
                    email="admin@example.com",
                    full_name="管理员",
                    role="admin",
                    hashed_password=get_password_hash("Admin123"),
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()


def ensure_default_departments(target_engine=None) -> None:
    """种下根部门（公司）。历史库为空时至少要有一层，否则新建用户无处可挂。

    `target_engine` 让这个方法也能给**账套 schema** 用：多账套下每个账套的部门树
    是各自独立的（部门是账套表，不是全局表），新账套起来时如果没有这一层，
    「员工档案」页连一个可选部门都没有，用户会以为功能坏了。
    """
    from app.models.organization import Department

    factory = (
        sessionmaker(autocommit=False, autoflush=False, bind=target_engine)
        if target_engine is not None
        else SessionLocal
    )
    db = factory()
    try:
        if db.query(Department).count() > 0:
            return
        db.add(
            Department(
                code="HQ",
                name="总公司",
                parent_id=None,
                level=0,
                sort_order=0,
                is_active=True,
                note="系统初始化创建；可改名或在其下新建部门",
            )
        )
        db.commit()
    finally:
        db.close()


def ensure_default_roles() -> None:
    """播种内置角色（幂等）。

    已存在的角色**只补不覆盖** —— 管理员改过的权限不能被重启冲掉；
    只有 `is_builtin` 标记缺失时才补上。
    """
    from app.models.organization import Department
    from app.models.role import BUILTIN_ROLES, Role

    db = SessionLocal()
    try:
        changed = False
        for spec in BUILTIN_ROLES:
            role = db.query(Role).filter(Role.code == spec["code"]).first()
            if role is None:
                db.add(
                    Role(
                        code=str(spec["code"]),
                        name=str(spec["name"]),
                        description=str(spec.get("description") or ""),
                        permissions=__import__("json").dumps(spec["permissions"], ensure_ascii=False),
                        is_builtin=True,
                        sort_order=int(spec.get("sort_order") or 0),
                        is_active=True,
                    )
                )
                changed = True
            elif not role.is_builtin:
                role.is_builtin = True
                changed = True
        if changed:
            db.commit()

        # admin 用户补挂角色 id 与根部门（历史数据没这两列）
        admin = db.query(User).filter(User.username == "admin").first()
        if admin is not None:
            touched = False
            if admin.role_id is None:
                admin_role = db.query(Role).filter(Role.code == "admin").first()
                if admin_role is not None:
                    admin.role_id = admin_role.id
                    touched = True
            if admin.department_id is None:
                dept = db.query(Department).order_by(Department.level, Department.id).first()
                if dept is not None:
                    admin.department_id = dept.id
                    touched = True
            if touched:
                db.commit()
    finally:
        db.close()


def ensure_default_params() -> None:
    """播种内置系统参数（幂等，只补不覆盖）。

    管理员改过的值不能被重启冲掉 —— 所以已存在的键只校正"展示用"的元数据
    （label / 分组 / 排序 / 说明），**不碰 param_value**。
    """
    from app.models.system_config import DEFAULT_PARAMS, SystemParam

    db = SessionLocal()
    try:
        changed = False
        for spec in DEFAULT_PARAMS:
            row = db.query(SystemParam).filter(SystemParam.param_key == spec["param_key"]).first()
            if row is None:
                db.add(
                    SystemParam(
                        param_key=str(spec["param_key"]),
                        param_value=str(spec["param_value"]),
                        param_group=str(spec["param_group"]),
                        label=str(spec["label"]),
                        value_type=str(spec["value_type"]),
                        description=str(spec.get("description") or ""),
                        is_editable=True,
                        sort_order=int(spec.get("sort_order") or 0),
                    )
                )
                changed = True
            else:
                for field in ("param_group", "label", "value_type", "description", "sort_order"):
                    value = spec.get(field)
                    if value is None:
                        continue
                    if field == "sort_order":
                        value = int(value)
                    elif field == "description":
                        value = str(value)
                    if getattr(row, field) != value:
                        setattr(row, field, value)
                        changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def ensure_default_dictionaries() -> None:
    """播种内置字典与字典项（幂等）。

    已存在的字典项**只补不覆盖**：管理员改过的 label / 排序不会被重启还原。
    字典类型本身只补 is_system 标记与名称。
    """
    from app.models.system_config import DEFAULT_DICTIONARIES, DataDictionary, DataDictionaryItem

    db = SessionLocal()
    try:
        changed = False
        for spec in DEFAULT_DICTIONARIES:
            dict_type = str(spec["dict_type"])
            dic = db.query(DataDictionary).filter(DataDictionary.dict_type == dict_type).first()
            if dic is None:
                db.add(
                    DataDictionary(
                        dict_type=dict_type,
                        dict_name=str(spec["dict_name"]),
                        description=str(spec.get("description") or ""),
                        is_system=True,
                        is_active=True,
                    )
                )
                changed = True
            elif not dic.is_system:
                dic.is_system = True
                changed = True

            existing = {
                row.item_value
                for row in db.query(DataDictionaryItem).filter(DataDictionaryItem.dict_type == dict_type).all()
            }
            for index, raw in enumerate(spec.get("items") or [], start=1):
                # 字典项支持两种写法：纯字符串（值=显示名），或 {value, label}
                # ——税率这类"值要精确、说明要给人看"的字段必须用后者。
                if isinstance(raw, dict):
                    value = str(raw.get("value") or "")
                    label = str(raw.get("label") or value)
                else:
                    value = str(raw)
                    label = value
                if not value or value in existing:
                    continue
                db.add(
                    DataDictionaryItem(
                        dict_type=dict_type,
                        item_value=value,
                        item_label=label,
                        sort_order=index * 10,
                        is_enabled=True,
                    )
                )
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def ensure_default_print_templates() -> None:
    """按打印注册表播种模板（幂等，只补不覆盖）。

    `doc_label` 与 `sort_order` 跟注册表同步（它们来自代码，是"事实"）；
    用户能改的外观项（name / title / header_text / footer_text / show_*）
    **一个字都不碰** —— 重启不能把管理员调好的模板还原掉。

    刻意不删除"注册表里已经没有"的历史模板：万一某个打印入口只是临时下线，
    配置还在；列表接口会用 `registered=false` 标出来。
    """
    from app.api.v1.routes.erp import printable_doc_types
    from app.models.print_template import PrintTemplate

    db = SessionLocal()
    try:
        changed = False
        existing = {row.doc_type: row for row in db.query(PrintTemplate).all()}
        for index, (doc_type, label) in enumerate(printable_doc_types(), start=1):
            order = index * 10
            row = existing.get(doc_type)
            if row is None:
                db.add(
                    PrintTemplate(
                        doc_type=doc_type,
                        doc_label=label,
                        name=label,
                        sort_order=order,
                    )
                )
                changed = True
                continue
            if row.doc_label != label or row.sort_order != order:
                row.doc_label = label
                row.sort_order = order
                changed = True
            if not (row.name or "").strip():
                row.name = label
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


# 内置菜单的一次性改名迁移： (页面key, 旧名, 新名)。
# 只在 label 仍等于旧名时生效 —— 管理员改过的名字不会被重启打回。
MENU_LABEL_MIGRATIONS: list[tuple[str, str, str]] = [
    # 第 11 批：发票归拢到财务模块，名字跟业务口径统一（原来叫「开票管理」）
    ("invoices", "开票管理", "发票管理"),
]


def _backfill_builtin_menus(db) -> None:
    """把 `default_menu_specs()` 里缺失的内置节点补进 menus 表（幂等，只补不覆盖）。

    触发场景：`PERMISSION_CATALOG` 新增了菜单项（如「总账」），而生产库早已播种过，
    走不到"表为空才全量播种"那条路。这里按页面 key 与内置标记逐项核对：
    - 顶层分组（parent 为 None）按**名字**去重：同名已存在就不动，缺则补。
    - 菜单项按「父分组 + page_key」去重：已存在（无论 label 被管理员改成啥）就不动。
    - 分组 id 复用同名已有分组的 id，保证补进来的菜单项挂到正确的父级下。

    与"改名迁移 / 全量播种"同一条铁律：管理员自己加过、改过、删过的节点一律不碰
    （我们只补「完全不存在」的内置节点，绝不覆盖、绝不复活被删的）。
    """
    from app.models import Menu, default_menu_specs

    # 现存分组：label → id（顶层、page_key 为空）
    existing_groups: dict[str, int] = {}
    for row in db.query(Menu).filter(Menu.page_key.is_(None)).all():
        existing_groups.setdefault(row.label, row.id)

    # 现存菜单项： (parent_id, page_key) → 存在与否（叶子、page_key 非空）
    existing_items: set[tuple[int, str]] = {
        (row.parent_id, row.page_key)
        for row in db.query(Menu).filter(Menu.page_key.isnot(None), Menu.is_builtin.is_(True)).all()
        if row.parent_id is not None
    }

    added = False
    group_ids: dict[str, int] = dict(existing_groups)
    # 先确保分组都在
    for parent_label, label, page_key, sort_order in default_menu_specs():
        if parent_label is not None:
            continue
        if label in group_ids:
            continue
        row = Menu(label=label, page_key=None, sort_order=sort_order, is_builtin=True)
        db.add(row)
        db.flush()
        group_ids[label] = row.id
        added = True
    # 再补菜单项
    for parent_label, label, page_key, sort_order in default_menu_specs():
        if parent_label is None:
            continue
        parent_id = group_ids.get(parent_label)
        if parent_id is None:
            continue
        if (parent_id, page_key) in existing_items:
            continue
        db.add(
            Menu(
                parent_id=parent_id,
                label=label,
                page_key=page_key,
                sort_order=sort_order,
                is_builtin=True,
            )
        )
        added = True
    if added:
        db.commit()


def ensure_default_menus() -> None:
    """播种默认菜单树（**只在表为空时**，之后一律不动）。

    与角色 / 字典 / 参数同一套约定：菜单一旦被管理员改过，重启不能把它还原。
    想回到出厂状态走 `POST /system/menus/reset`（管理员操作 + 界面二次确认）。

    默认树按 `PERMISSION_CATALOG` 生成，**原样复刻改造前的两级结构** ——
    这样"换成动态菜单"对现有用户的观感是零变化，子层级由管理员自己按需去建。
    """
    from app.models import Menu, default_menu_specs

    db = SessionLocal()
    try:
        # 内置菜单的**改名迁移**（每次启动都跑，幂等）。
        #
        # 为什么需要它：菜单名从这一批起存在数据库里（管理员可改），
        # 所以光改代码里的 `menuGroups` 只影响"全新安装"的种子，
        # 已经播种过的库仍然显示旧名字 —— 表现为"代码里改名了，界面上没变"。
        #
        # 边界：**只在 label 还等于旧值时改名**。管理员自己改过的名字一律不动，
        # 否则每次重启都会把他的命名打回去。
        for page_key, old_label, new_label in MENU_LABEL_MIGRATIONS:
            row = (
                db.query(Menu)
                .filter(Menu.page_key == page_key, Menu.label == old_label)
                .first()
            )
            if row is not None:
                row.label = new_label
                db.commit()

        # 内置菜单的**缺则补**迁移（每次启动都跑，幂等）。
        #
        # 为什么需要它：`PERMISSION_CATALOG` 新增菜单项（例如「总账」）后，
        # 已经播种过的生产库不会再有"表为空"的时机，光靠下面的全量播种补不进去。
        # 这里按「页面 key + 内置标记」把缺失的内置菜单项补上，
        # 分组与排序号对齐 `default_menu_specs()`，管理员自己加/改过的节点一律不动。
        _backfill_builtin_menus(db)

        if db.query(Menu).count() > 0:
            return
        group_ids: dict[str, int] = {}
        # 第一遍插分组（parent 为 None），拿到 id 后再挂菜单项
        for parent_label, label, page_key, sort_order in default_menu_specs():
            if parent_label is not None:
                continue
            row = Menu(label=label, page_key=None, sort_order=sort_order, is_builtin=True)
            db.add(row)
            db.flush()
            group_ids[label] = row.id
        for parent_label, label, page_key, sort_order in default_menu_specs():
            if parent_label is None:
                continue
            db.add(
                Menu(
                    parent_id=group_ids.get(parent_label),
                    label=label,
                    page_key=page_key,
                    sort_order=sort_order,
                    is_builtin=True,
                )
            )
        db.commit()
    finally:
        db.close()


def ensure_default_product_categories() -> None:
    """把存量商品的扁平 `category` 字符串播种成顶级类别节点（幂等，只在缺失时补）。

    浩技云 5.0 左侧是**多级类别树**，而老系统里 `products.category` 是扁平字符串。
    升级后用户打开类别树应该是「非空」的 —— 把已有字符串去重后补成顶级节点，
    层级关系（客户/板块 → 商品类别）由用户后续自己调，这里不臆测。
    """
    from app.models import Product, ProductCategory

    db = SessionLocal()
    try:
        existing_names = {
            r[0] for r in db.query(Product.category).filter(Product.category.isnot(None)).distinct().all()
        }
        existing_names.discard("")
        if not existing_names:
            return
        top_names = {
            r[0]
            for r in db.query(ProductCategory.name)
            .filter(ProductCategory.parent_id.is_(None))
            .distinct()
            .all()
        }
        missing = sorted(existing_names - top_names)
        if not missing:
            return
        max_sort = db.query(ProductCategory.sort_order).filter(ProductCategory.parent_id.is_(None)).order_by(
            ProductCategory.sort_order.desc()
        ).first()
        base = (max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0
        for i, name in enumerate(missing):
            db.add(ProductCategory(name=name, parent_id=None, sort_order=base + i))
        db.commit()
    finally:
        db.close()


def ensure_default_accounts() -> None:
    """幂等播种内置会计科目（中国会计准则常用科目，覆盖总账/复式记账）。"""
    from app.services.ledger import ensure_default_accounts as _seed

    db = SessionLocal()
    try:
        _seed(db)
    finally:
        db.close()


def _write_operation_log(request, status_code: int, duration_ms: float) -> None:
    """落一条操作日志。**任何异常都不能冒泡出去** —— 见下面的中间件说明。"""
    from app.core.security import bearer_token, decode_access_token
    from app.models.operation_log import OPERATION_LOG_METHODS, record_operation
    from app.models.user import User

    if request.method not in OPERATION_LOG_METHODS:
        return
    if not request.url.path.startswith("/api/v1"):
        return

    db = SessionLocal()
    try:
        payload = decode_access_token(bearer_token(request.headers.get("authorization")))
        username = str(payload.get("sub") or "") if payload else ""
        # 登录请求（以及任何还没拿到 token 的写请求）由路由主动交代"是谁" ——
        # 见 auth.py::login_user 里的 request.state.log_username。
        declared = getattr(request.state, "log_username", "")
        if declared:
            username = str(declared)
            payload = None  # 名字来自请求体时，token 里的角色快照不可信，改查库
        # token 里有 username 与角色快照，但 id 要查库；查不到就按匿名记
        user = db.query(User).filter(User.username == username).first() if username else None
        record_operation(
            db,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            user_id=user.id if user else None,
            username=username,
            role=user.role if user else (str(payload.get("role") or "") if payload else ""),
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
    finally:
        db.close()


async def _tenant_context_middleware(request, call_next):
    """把当前请求的账套写进上下文变量。

    为什么 `get_db` 里已经做了、这里还要再做一遍：**有些路由压根不依赖数据库**，
    比如「公司信息」的读写（`load_company` / `save_company` 自己开会话）和打印抬头。
    那些路由不会被注入 `get_db`，上下文变量就一直是默认值 —— 于是它们去读写的是
    **第一个账套**的数据。实测确实串账了：在第二家账套里改抬头，把第一家的也改了。

    这个错误特别值得记一笔：**它不报错，只是改错了账**。所以放在中间件里做，
    而不是指望每个路由都记得声明 db 依赖。
    """
    from app.core import tenant as tenant_router

    tenant_router.set_current_company(tenant_router.company_code_from_request(request))
    return await call_next(request)


async def _operation_log_middleware(request, call_next):
    """操作日志中间件（只记写操作）。

    三条约束，都是"日志不能反过来影响业务"：
    1. 失败不冒泡：中间的写库异常全部吞掉。宁可少一条日志，也不能让一张
       已经入库的销售单返回 500。
    2. 不阻塞事件循环：日志是同步 IO，放到线程池里执行。
    3. 只记 `/api/v1` 下的写方法 —— 查询请求占了绝大多数，记下来只会
       把"谁改了这张单"淹没在访问日志里。
    """
    import time

    from starlette.concurrency import run_in_threadpool

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration = (time.perf_counter() - started) * 1000
        try:
            await run_in_threadpool(_write_operation_log, request, 500, duration)
        except Exception:  # pragma: no cover - 日志失败绝不影响原始异常
            pass
        raise

    duration = (time.perf_counter() - started) * 1000
    try:
        await run_in_threadpool(_write_operation_log, request, response.status_code, duration)
    except Exception:  # pragma: no cover - 同上
        pass
    return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="ERP 核心系统",
        version="0.1.0",
        description="本地 ERP 基础版本，支持采购、销售、库存、财务和报表基础能力。",
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 开发环境直接允许所有
        allow_credentials=False, # 这里必须是 False，因为 "*" 和 True 不能共存
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.include_router(api_router, prefix="/api/v1")
    app.middleware("http")(_tenant_context_middleware)
    app.middleware("http")(_operation_log_middleware)
    Base.metadata.create_all(bind=engine)
    ensure_schema_in()
    ensure_default_admin_user()
    ensure_default_departments()
    ensure_default_roles()
    ensure_default_params()
    ensure_default_dictionaries()
    ensure_default_print_templates()
    ensure_default_menus()
    ensure_default_product_categories()
    ensure_default_accounts()
    # 多账套：上面那些处理的是第一个账套（＝现状，schema=public）与全局表；
    # 这两步把"现有部署"注册成账套 1，并给新账套建表。
    # 顺序很重要：必须先有账套记录，才知道要给哪些 schema 建表。
    ensure_default_company()
    ensure_user_company_links()
    ensure_all_tenant_schemas()

    # 桌面端/生产模式：后端直接托管前端构建产物（frontend/dist），
    # 这样桌面窗口只需访问 http://127.0.0.1:8010 一个端口（端口见 desktop_app.py）。
    # PyInstaller 打包后资源解包到 _MEIPASS，路径需相应切换。
    if getattr(sys, "_MEIPASS", None):
        frontend_dist = Path(sys._MEIPASS) / "frontend" / "dist"
    else:
        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()