"""C1：迁移列定义（由 scripts/gen_migration_columns.py 生成，勿手改）。

来源：原 app/main.py 的 16 组 *_ADDITIONS。
生成器保证与运行期 dict 逐字相等；要改列定义，改生成源或迁移脚本后重跑生成器。
"""

from __future__ import annotations

PRODUCT_COLUMNS: dict[str, str] = {
    'mnemonic': 'VARCHAR(50)',
    'standards': 'VARCHAR(100)',
    'brand': 'VARCHAR(100)',
    'bar_code': 'VARCHAR(80)',
    'color': 'VARCHAR(50)',
    'size': 'VARCHAR(50)',
    'manufacturer': 'VARCHAR(150)',
    'manufacturer_id': 'INTEGER',
    'serial_no': 'VARCHAR(80)',
    'unit_weight': 'DOUBLE PRECISION',
    'stock_upper': 'INTEGER',
    'stock_lower': 'INTEGER',
    'pack_qty': 'INTEGER',
    'shelf_life': 'INTEGER',
    'warn_days': 'INTEGER',
    'image_url': 'VARCHAR(255)',
    'note': 'VARCHAR(255)',
    'tax_rate': 'DOUBLE PRECISION',
}

CUSTOMER_COLUMNS: dict[str, str] = {
    'businesser': 'VARCHAR(50)',
    'contact': 'VARCHAR(50)',
    'contact_phone': 'VARCHAR(30)',
    'tax_no': 'VARCHAR(50)',
    'bank_name': 'VARCHAR(150)',
    'bank_account': 'VARCHAR(80)',
    'invoice_phone': 'VARCHAR(30)',
    'level': 'VARCHAR(30)',
    'discount': 'DOUBLE PRECISION',
    'credit_limit': 'DOUBLE PRECISION',
    'init_receivable': 'DOUBLE PRECISION',
    'init_invoice_debt': 'DOUBLE PRECISION',
    'relation_date': 'VARCHAR(30)',
    'business_type': 'VARCHAR(50)',
    'main_products': 'VARCHAR(255)',
    'potential_amount': 'DOUBLE PRECISION',
    'note': 'VARCHAR(255)',
    'category_id': 'INTEGER',
}

SUPPLIER_COLUMNS: dict[str, str] = {
    'short_name': 'VARCHAR(80)',
    'contact': 'VARCHAR(50)',
    'main_contact': 'VARCHAR(50)',
    'mobile': 'VARCHAR(30)',
    'postcode': 'VARCHAR(20)',
    'bank_name': 'VARCHAR(150)',
    'bank_account': 'VARCHAR(80)',
    'invoice_phone': 'VARCHAR(30)',
    'init_payable': 'DOUBLE PRECISION',
    'init_invoice_debt': 'DOUBLE PRECISION',
    'note': 'VARCHAR(255)',
    'category_id': 'INTEGER',
    'tax_no': 'VARCHAR(50)',
}

INVOICE_COLUMNS: dict[str, str] = {
    'direction': "VARCHAR(10) NOT NULL DEFAULT 'unknown'",
    'invoice_flag': "VARCHAR(10) NOT NULL DEFAULT 'blue'",
    'issue_mode': "VARCHAR(10) NOT NULL DEFAULT 'manual'",
    'handler': 'VARCHAR(50)',
    'source_path': 'VARCHAR(255)',
    'source_name': 'VARCHAR(255)',
    'source_size': 'INTEGER',
    'source_mime': 'VARCHAR(80)',
    'customer_id': 'INTEGER',
    'contract_id': 'INTEGER',
    'deducted_at': 'TIMESTAMP WITH TIME ZONE',
    'supplier_id': 'INTEGER',
    'certified': 'BOOLEAN NOT NULL DEFAULT FALSE',
    'certified_at': 'TIMESTAMP WITH TIME ZONE',
}

PURCHASE_ORDER_COLUMNS: dict[str, str] = {
    'warehouse_id': 'INTEGER',
    'project_id': 'INTEGER',
    'businesser': 'VARCHAR(50)',
    'order_date': 'VARCHAR(20)',
    'delivery_date': 'VARCHAR(20)',
    'payment_method': 'VARCHAR(30)',
    'contact': 'VARCHAR(50)',
    'contact_phone': 'VARCHAR(30)',
    'address': 'VARCHAR(255)',
    'note': 'VARCHAR(255)',
    'payable_amount': 'DOUBLE PRECISION DEFAULT 0',
    'discount_amount': 'DOUBLE PRECISION DEFAULT 0',
    'paid_amount': 'DOUBLE PRECISION DEFAULT 0',
    'is_invoiced': 'BOOLEAN DEFAULT FALSE',
    'current_debt': 'DOUBLE PRECISION DEFAULT 0',
    'prev_debt': 'DOUBLE PRECISION DEFAULT 0',
    'total_debt': 'DOUBLE PRECISION DEFAULT 0',
    'doc_type': "VARCHAR(20) NOT NULL DEFAULT 'inbound'",
    'source_order_id': 'INTEGER',
    'shipped_at': 'TIMESTAMP WITH TIME ZONE',
    'self_purchase_paid': 'DOUBLE PRECISION',
    'self_purchase_supplier_id': 'INTEGER',
}

SALES_ORDER_COLUMNS: dict[str, str] = {
    'warehouse_id': 'INTEGER',
    'project_id': 'INTEGER',
    'businesser': 'VARCHAR(50)',
    'order_date': 'VARCHAR(20)',
    'delivery_date': 'VARCHAR(20)',
    'payment_method': 'VARCHAR(30)',
    'contact': 'VARCHAR(50)',
    'contact_phone': 'VARCHAR(30)',
    'address': 'VARCHAR(255)',
    'note': 'VARCHAR(255)',
    'receivable_amount': 'DOUBLE PRECISION DEFAULT 0',
    'discount_amount': 'DOUBLE PRECISION DEFAULT 0',
    'received_amount': 'DOUBLE PRECISION DEFAULT 0',
    'is_invoiced': 'BOOLEAN DEFAULT FALSE',
    'current_debt': 'DOUBLE PRECISION DEFAULT 0',
    'prev_debt': 'DOUBLE PRECISION DEFAULT 0',
    'total_debt': 'DOUBLE PRECISION DEFAULT 0',
    'doc_type': "VARCHAR(20) NOT NULL DEFAULT 'outbound'",
    'source_order_id': 'INTEGER',
    'logistics_company': 'VARCHAR(100)',
    'logistics_no': 'VARCHAR(100)',
    'signed_by': 'VARCHAR(50)',
    'signed_at': 'TIMESTAMP WITH TIME ZONE',
}

PURCHASE_ITEM_COLUMNS: dict[str, str] = {
    'product_name': 'VARCHAR(150)',
    'standards': 'VARCHAR(100)',
    'unit': 'VARCHAR(50)',
    'note': 'VARCHAR(255)',
    'unit_factor': 'INTEGER NOT NULL DEFAULT 1',
}

SALES_ITEM_COLUMNS: dict[str, str] = {
    'product_name': 'VARCHAR(150)',
    'standards': 'VARCHAR(100)',
    'unit': 'VARCHAR(50)',
    'note': 'VARCHAR(255)',
    'unit_factor': 'INTEGER NOT NULL DEFAULT 1',
}

PURCHASE_RETURN_ITEM_COLUMNS: dict[str, str] = {
    'unit_factor': 'INTEGER NOT NULL DEFAULT 1',
}

SALES_RETURN_ITEM_COLUMNS: dict[str, str] = {
    'unit_factor': 'INTEGER NOT NULL DEFAULT 1',
}

FINANCE_COLUMNS: dict[str, str] = {
    'bank_account_id': 'INTEGER',
    'category': 'VARCHAR(50)',
    'handler': 'VARCHAR(50)',
    'related_type': 'VARCHAR(40)',
    'doc_no': 'VARCHAR(50)',
    'direction': 'VARCHAR(10)',
    'product_id': 'INTEGER',
    'warehouse_id': 'INTEGER',
    'project_id': 'INTEGER',
    'occurred_at': 'VARCHAR(20)',
    'period': 'VARCHAR(7)',
    'reversal_of_id': 'INTEGER',
    'applied_amount': 'DOUBLE PRECISION',
    'invoice_id': 'INTEGER',
    'flow_no': 'VARCHAR(40)',
}

INVENTORY_COLUMNS: dict[str, str] = {
    'related_type': 'VARCHAR(40)',
    'related_order_id': 'INTEGER',
    'doc_no': 'VARCHAR(50)',
    'note': 'VARCHAR(255)',
}

USER_COLUMNS: dict[str, str] = {
    'department_id': 'INTEGER',
    'role_id': 'INTEGER',
    'phone': 'VARCHAR(30)',
    'position': 'VARCHAR(50)',
    'remark': 'VARCHAR(255)',
    'last_login_at': 'TIMESTAMP WITH TIME ZONE',
}

COMPANY_COLUMNS: dict[str, str] = {
    'own_name': 'VARCHAR(150)',
}

CONTRACT_COLUMNS: dict[str, str] = {
    'direction': "VARCHAR(10) NOT NULL DEFAULT 'out'",
    'source_file_path': 'VARCHAR(500)',
    'source_file_name': 'VARCHAR(255)',
    'source_file_size': 'INTEGER',
    'source_file_mime': 'VARCHAR(100)',
    'template_id': 'INTEGER',
    'ocr_json': 'TEXT',
    'ocr_status': "VARCHAR(20) NOT NULL DEFAULT 'none'",
    'updated_at': 'TIMESTAMP WITH TIME ZONE',
}

QUOTATION_COLUMNS: dict[str, str] = {
    'contract_id': 'INTEGER',
}
