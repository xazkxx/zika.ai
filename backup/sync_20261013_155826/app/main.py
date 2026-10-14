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
    Base.metadata.create_all(bind=engine)
    ensure_database_schema()
    ensure_default_admin_user()

    # 桌面端/生产模式：后端直接托管前端构建产物（frontend/dist），
    # 这样桌面窗口只需访问 http://127.0.0.1:8000 一个端口。
    # PyInstaller 打包后资源解包到 _MEIPASS，路径需相应切换。
    if getattr(sys, "_MEIPASS", None):
        frontend_dist = Path(sys._MEIPASS) / "frontend" / "dist"
    else:
        frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


app = create_app()