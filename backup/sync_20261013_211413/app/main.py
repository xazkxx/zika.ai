import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

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

# 系统管理第 1 轮：用户挂部门 / 挂角色 / 联系方式 / 最后登录时间
USER_ADDITIONS = {
    "department_id": "INTEGER",
    "role_id": "INTEGER",
    "phone": "VARCHAR(30)",
    "position": "VARCHAR(50)",
    "remark": "VARCHAR(255)",
    "last_login_at": "TIMESTAMP WITH TIME ZONE",
}


def ensure_database_schema() -> None:
    with engine.begin() as conn:
        if not inspect(conn).has_table("users"):
            return

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

        # 系统管理第 1 轮：用户表补列（部门 / 角色 / 联系方式）
        _add_missing_columns(conn, "users", USER_ADDITIONS)


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


def ensure_default_departments() -> None:
    """种下根部门（公司）。历史库为空时至少要有一层，否则新建用户无处可挂。"""
    from app.models.organization import Department

    db = SessionLocal()
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
            for index, value in enumerate(spec.get("items") or [], start=1):
                value = str(value)
                if value in existing:
                    continue
                db.add(
                    DataDictionaryItem(
                        dict_type=dict_type,
                        item_value=value,
                        item_label=value,
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
    app.middleware("http")(_operation_log_middleware)
    Base.metadata.create_all(bind=engine)
    ensure_database_schema()
    ensure_default_admin_user()
    ensure_default_departments()
    ensure_default_roles()
    ensure_default_params()
    ensure_default_dictionaries()
    ensure_default_print_templates()

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