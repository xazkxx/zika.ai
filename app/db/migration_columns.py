"""C1-3：迁移列定义（由 scripts/gen_migration_columns.py 生成，勿手改）。

来源：原 app/main.py 的 PRODUCT / CUSTOMER / SUPPLIER / INVOICE_ADDITIONS。
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
