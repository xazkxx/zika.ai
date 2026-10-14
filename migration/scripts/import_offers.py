# -*- coding: utf-8 -*-
"""导入浩技云历史报价单（6 份）到 quotations 表，作为历史凭证备查。

背景：浩技云「销售 → 报价单」列表接口（`emkOfferPriceController.do?datagrid`）
只返回**单头字段**，没有商品明细。因此导入的报价单：
  - 明细为空（总数与金额按浩技云原始值保留，不做重算）；
  - 单号、客户名、报价日期、业务员、付款/运输方式、数量、金额 全部按原样保留；
  - 客户按名称匹配我们库里的客户档案（匹配不到则只存名称快照，customer_id 留空）；
  - 出货仓库按名称模糊匹配（"寨卡"/"华诺迈"/"寨纬"），匹配不到留空。

幂等：按报价单号判重，已存在则跳过，可重复执行。

用法（项目根目录）：
    .venv\\Scripts\\python.exe migration\\scripts\\import_offers.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.api.v1.routes.erp import amount_to_chinese  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.quotation import Quotation  # noqa: E402
from app.models.warehouse import Warehouse  # noqa: E402

RAW = os.path.join(ROOT, 'migration', 'haoji_raw', 'raw_offers.json')

# 浩技云仓库名 → 我们库里的仓库名关键词
WAREHOUSE_KEYWORDS = [
    ('寨卡', '寨卡仓库'),
    ('华诺迈', '华诺迈仓库'),
    ('寨纬', '寨纬仓库'),
]


def _s(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _match_warehouse(db, storage_name: str | None) -> int | None:
    if not storage_name:
        return None
    for keyword, target in WAREHOUSE_KEYWORDS:
        if keyword in storage_name:
            row = db.query(Warehouse).filter(Warehouse.name == target).first()
            if row:
                return row.id
    return None


def main() -> None:
    rows = json.load(open(RAW, encoding='utf-8'))
    rows = rows if isinstance(rows, list) else rows.get('rows', rows)
    db = SessionLocal()
    created = skipped = 0
    try:
        for raw in rows:
            quote_no = _s(raw.get('a01a13a01')) or _s(raw.get('a01a13a01'))
            if not quote_no:
                continue
            if db.query(Quotation).filter(Quotation.quote_no == quote_no).first():
                print(f'  跳过（已存在）{quote_no}')
                skipped += 1
                continue

            customer_name = _s(raw.get('cusName'))
            customer = (
                db.query(Customer).filter(Customer.name == customer_name).first()
                if customer_name
                else None
            )
            storage_name = _s(raw.get('storageName'))
            warehouse_id = _match_warehouse(db, storage_name)

            total_quantity = float(raw.get('total') or 0.0)
            total_amount = float(raw.get('money') or 0.0)
            state = raw.get('state')

            item = Quotation(
                quote_no=quote_no,
                customer_id=customer.id if customer else None,
                customer_name=customer_name,
                customer_address=_s(raw.get('a01a13a07')),
                contact=_s(raw.get('a01a13a08')),
                contact_phone=_s(raw.get('a01a13a09')),
                fax=_s(raw.get('a01a13a12')),
                quote_date=_s(raw.get('a01a13a03')),
                valid_until=_s(raw.get('a01a13a13')),
                warehouse_id=warehouse_id,
                businesser=_s(raw.get('businesser')),
                payment_method=_s(raw.get('a01a13a06')),
                transport_method=_s(raw.get('a01a13a10')),
                delivery_place=_s(raw.get('a01a13a11')),
                total_quantity=total_quantity,
                total_amount=total_amount,
                amount_chinese=amount_to_chinese(total_amount),
                # state=1 浩技云视为已审核，这里落成「已报价」；state=0 落成草稿
                status='quoted' if state in (1, '1', True) else 'draft',
                note='浩技云历史导入（仅单头，明细未提供）',
            )
            db.add(item)
            db.commit()
            created += 1
            wh = f'仓库id={warehouse_id}' if warehouse_id else f'仓库未匹配({storage_name})'
            cus = f'客户id={customer.id}' if customer else f'客户未匹配({customer_name})'
            print(f'  导入 {quote_no} | ¥{total_amount:,.2f} | {cus} | {wh}')

        print(f'\n完成：新增 {created} 条，跳过 {skipped} 条')
        total = db.query(Quotation).count()
        print(f'quotations 表当前共 {total} 条')
    finally:
        db.close()


if __name__ == '__main__':
    main()
