"""一次性清理测试脏数据脚本。

清理规则：
1. invoices：total_amount <= 0，或 counterparty_name 为空 / '未知客户'
2. production_boms：product_id 或 component_product_id 为空（含 0）
3. sales_orders：total_amount <= 0（连同其明细一起删除）

注意：清理的是 ERP 当前正在使用的数据库（.env 配置的 PostgreSQL）。
旧文件 erp.db（SQLite）已在切库后废弃，不再被系统使用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import or_

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.bom import BillOfMaterial
from app.models.invoice import Invoice
from app.models.sales_order import SalesOrder, SalesOrderItem


def main() -> None:
    # 打印当前连接的数据库（去掉密码），确认清的是正在用的库
    db_url = settings.database_url
    print(f"连接数据库：{db_url.split('@')[-1] if '@' in db_url else db_url}")

    db = SessionLocal()
    try:
        # 1. 发票：金额<=0 或对方名称为空/未知客户
        invoice_query = db.query(Invoice).filter(
            or_(
                Invoice.total_amount <= 0,
                Invoice.counterparty_name.is_(None),
                Invoice.counterparty_name == "",
                Invoice.counterparty_name == "未知客户",
            )
        )
        invoice_deleted = invoice_query.delete(synchronize_session=False)

        # 2. BOM 物料清单：product_id 或 component_product_id 为空（含 0）。
        #    先收集脏行 id，连同引用它们的子节点一起删，避免外键冲突。
        bom_query = db.query(BillOfMaterial).filter(
            or_(
                BillOfMaterial.product_id.is_(None),
                BillOfMaterial.product_id == 0,
                BillOfMaterial.component_product_id.is_(None),
                BillOfMaterial.component_product_id == 0,
            )
        )
        to_delete = {row.id for row in bom_query.with_entities(BillOfMaterial.id).all()}
        while True:
            children = {
                row.id
                for row in db.query(BillOfMaterial.id)
                .filter(BillOfMaterial.parent_id.in_(to_delete))
                .all()
            }
            new_children = children - to_delete
            if not new_children:
                break
            to_delete |= new_children
        if to_delete:
            db.query(BillOfMaterial).filter(BillOfMaterial.id.in_(to_delete)).delete(synchronize_session=False)

        # 3. 销售订单：金额<=0（先删订单明细，再删订单本身，避免留下孤儿明细）
        sales_query = db.query(SalesOrder).filter(SalesOrder.total_amount <= 0)
        sales_ids = [row.id for row in sales_query.with_entities(SalesOrder.id).all()]
        if sales_ids:
            db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id.in_(sales_ids)).delete(
                synchronize_session=False
            )
        sales_deleted = sales_query.delete(synchronize_session=False)

        db.commit()

        print("清理完成：")
        print(f"  - 发票：删除 {invoice_deleted} 条")
        print(f"  - BOM 物料清单：删除 {len(to_delete)} 条")
        print(f"  - 销售订单：删除 {sales_deleted} 条")
    finally:
        db.close()


if __name__ == "__main__":
    main()
