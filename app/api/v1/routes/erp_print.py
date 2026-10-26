"""打印中心 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

各类单据的打印规格（print spec）与打印类型注册表。
"""

from __future__ import annotations

import base64
import json

from app.core.company_info import load_company
from app.db.session import get_db
from app.models.assembly import AssemblyOrder, AssemblyOrderItem
from app.models.contract import CONTRACT_TEMPLATES, Contract, ContractItem
from app.models.customer import Customer
from app.models.finished_goods import FINISHED_GOODS_STATUS, FinishedGoodsReceipt
from app.models.inventory_adjustment import ADJUSTMENT_STATUS, ADJUST_TYPES, InventoryAdjustment
from app.models.inventory_transfer import InventoryTransfer, TRANSFER_STATUS
from app.models.material_issue import MATERIAL_ISSUE_STATUS, MaterialIssue
from app.models.material_return import MATERIAL_RETURN_STATUS, MaterialReturn
from app.models.outsourcing import OutsourcingOrder
from app.models.print_template import STANDALONE_DOC_TYPES, resolve_print_spec, sort_doc_types
from app.models.production_plan import PLAN_TYPES, PRODUCTION_PLAN_STATUS, ProductionPlan
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.purchase_return import PurchaseReturn
from app.models.quotation import Quotation
from app.models.statement import (
    STATEMENT_DIRECTIONS,
    STATEMENT_INVOICE_STATUS,
    STATEMENT_SOURCE_TYPES,
    STATEMENT_STATUS,
    Statement,
)
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.sales_return import SalesReturn
from app.models.stocktaking import STOCKTAKING_STATUS, Stocktaking
from app.models.supplier import Supplier
from app.models.warehouse import Warehouse
from app.services.contract_template import build_gongkuang_document, document_to_print_spec
from app.services.pdf_render import render_document_pdf
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from urllib import request

from app.api.v1.routes.erp_common import (
    _A2_DEFAULTS,
    _A2_DEFAULT_COPIES,
    _A2_DEFAULT_INSPECTION_DAYS,
    _A2_DEFAULT_OBJECTION_DAYS,
    _A2_DEFAULT_PENALTY_RATE,
    _adjust_items,
    _contract_items,
    _finished_goods_items,
    _material_issue_items,
    _material_return_items,
    _outsourcing_items,
    _production_plan_items,
    _purchase_return_items,
    _quotation_items,
    _s,
    _sales_return_items,
    _stocktaking_items,
    _transfer_items,
    _wants_json,
    amount_to_chinese,
    resolve_contract_document_payload,
)

router = APIRouter(prefix="", tags=["erp"])




def _d(v) -> str:
    """日期字段取 YYYY-MM-DD，None 安全。"""
    return "" if v is None else str(v)[:10]



def _pdf_response(
    spec: dict,
    filename: str,
    db: Session,
    doc_type: str | None = None,
    as_json: bool = False,
) -> Response:
    """全部单据打印的唯一出口：在这里套上打印模板 + 系统参数。

    放在这里而不是各打印端点，是为了"新增一张单据就自动继承模板配置"。

    两点刻意的取舍：
    1. 复用调用方已有的 `db`，不另开 session。早先这里是 `SessionLocal()`，
       但那个名字在本模块没导入 —— `NameError` 正好被下面的 `except` 吞掉，
       参数静默失效、打印照常出纸，只有"页脚不听配置"这一个怪现象。
    2. 读配置失败不能把打印拖垮（打印是核心功能，不能因为一个页脚设置打不出单），
       所以仍然吞异常退回单据原样 —— 但配置读取函数是模块级导入，
       真出问题会在这里立刻暴露，而不是悄悄吞进 except。
    """
    try:
        spec = resolve_print_spec(db, doc_type, spec)
    except Exception:  # pragma: no cover - 防御性：数据库抖动时保证打印仍可用
        pass

    pdf = render_document_pdf(spec)
    if as_json:
        # JSON(base64) 传输：**这不是多此一举**。
        # Edge 的内置 PDF 阅读器会把 application/pdf 的响应从 JS 手里接管走，
        # 于是 `fetch()` 拿到的是一个空响应（实测状态 204、body 为空），
        # 而 `response.ok` 对 2xx 依然为真 —— 前端会静默下载一个 0 字节的空 PDF。
        # 换成 JSON 后浏览器没有任何理由接管，前端也能明确判断内容是否完整。
        # 请求方用 `Accept: application/json` 指定走这条通道（前端 printPdf 就是这么发的）。
        import base64

        return JSONResponse(
            {
                "filename": f"{filename}.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(pdf).decode("ascii"),
            }
        )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )



@router.get("/print/statement/{party_type}/{party_id}")
def print_statement(
    party_type: str,
    party_id: int,
    request: Request,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """B1 客户对账单 / B2 供应商对账单（PDF）。"""
    from app.api.v1.routes.erp_finance import finance_reconciliation
    if party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")
    data = finance_reconciliation(party_type, party_id, from_date, to_date, db)
    s = data["summary"]
    spec = {
        "title": data["title"],
        "doc_no": f"DZ{datetime.now().strftime('%Y%m%d')}-{party_id:04d}",
        "period": f"对账期间：{_s(from_date) or '（起始）'} 至 {_s(to_date) or datetime.now().strftime('%Y-%m-%d')}",
        "header_left": [
            ("单位名称", _s(data["party"]["name"])),
            ("单位编码", _s(data["party"]["code"])),
            ("地址", _s(data["party"]["address"])),
            ("联系电话", _s(data["party"]["contact_phone"]) or _s(data["party"]["phone"])),
        ],
        "header_right": [
            ("联系人", _s(data["party"]["contact"])),
            ("税号", _s(data["party"]["tax_no"])),
            ("开户银行", _s(data["party"]["bank_name"])),
            ("银行账号", _s(data["party"]["bank_account"])),
        ],
        "columns": [
            {"label": "日期", "width": 58, "align": "c"},
            {"label": "单据号", "width": 92, "align": "l"},
            {"label": "摘要", "width": 175, "align": "l"},
            {"label": "增加", "width": 62, "align": "r"},
            {"label": "减少", "width": 62, "align": "r"},
            {"label": "余额", "width": 66, "align": "r"},
        ],
        "rows": [
            [row["date"], _s(row["doc_no"]), _s(row["summary"]), row["increase"], row["decrease"], row["balance"]]
            for row in data["rows"]
        ],
        "summary": [
            ("期初余额", f"{float(s['opening_balance']):,.2f}"),
            ("本期增加", f"{float(s['increase_total']):,.2f}"),
            ("本期减少", f"{float(s['decrease_total']):,.2f}"),
            ("期末余额", f"{float(s['closing_balance']):,.2f}"),
        ],
        "notes": [
            f"期末余额（大写）：{s['closing_balance_upper']}",
            "说明：如对上述往来无异议，请盖章确认回传；如有异议，请于 5 个工作日内与我司联系核对。",
        ],
        "signatures": ["制单", "审核", ("客户" if party_type == "customer" else "供应商") + "确认（盖章）"],
    }
    return _pdf_response(spec, f"statement_{party_type}_{party_id}", db, "statement", _wants_json(request))



@router.get("/print/balance-confirm/{party_type}/{party_id}")
def print_balance_confirm(
    party_type: str,
    party_id: int,
    request: Request,
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Response:
    """B3 往来余额确认单（PDF）。"""
    from app.api.v1.routes.erp_finance import finance_reconciliation
    if party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="party_type 必须是 customer 或 supplier")
    data = finance_reconciliation(party_type, party_id, from_date, to_date, db)
    s = data["summary"]
    to = _s(to_date) or datetime.now().strftime("%Y-%m-%d")
    spec = {
        "title": "往来余额确认单",
        "doc_no": f"QR{datetime.now().strftime('%Y%m%d')}-{party_id:04d}",
        "period": f"对账期间：{_s(from_date) or '（起始）'} 至 {to}",
        "header_left": [
            ("单位名称", _s(data["party"]["name"])),
            ("单位编码", _s(data["party"]["code"])),
            ("地址", _s(data["party"]["address"])),
        ],
        "header_right": [
            ("联系人", _s(data["party"]["contact"])),
            ("联系电话", _s(data["party"]["contact_phone"]) or _s(data["party"]["phone"])),
            ("确认日期", to),
        ],
        "paragraphs": [
            f"兹确认：截至 {to}，贵我双方业务往来款项余额如下表所示。经双方核对账目一致，请贵司核对后盖章确认回传。",
        ],
        "summary": [
            ("期初余额", f"{float(s['opening_balance']):,.2f}"),
            ("本期增加", f"{float(s['increase_total']):,.2f}"),
            ("本期减少", f"{float(s['decrease_total']):,.2f}"),
            ("期末余额", f"{float(s['closing_balance']):,.2f}"),
        ],
        "notes": [
            f"期末余额（大写）：{s['closing_balance_upper']}",
            "本确认单一式两份，双方各执一份；如有异议请于 5 个工作日内书面提出，逾期视为确认无误。",
        ],
        "signatures": ["我方（盖章）", ("客户" if party_type == "customer" else "供应商") + "（盖章）", "确认日期"],
    }
    return _pdf_response(spec, f"balance_confirm_{party_type}_{party_id}", db, "balance-confirm", _wants_json(request))



def _order_rows(rows: list, *, with_price: bool) -> list[list]:
    """明细快照 → 打印行。送货单不显示价格。"""
    out = []
    for i, r in enumerate(rows, start=1):
        line = [str(i), _s(r.product_name), _s(r.standards), _s(r.unit), r.quantity]
        if with_price:
            line += [r.unit_price, r.amount]
        line.append(_s(r.note))
        out.append(line)
    return out



def _purchase_print_spec(db: Session, order_id: int, *, inbound: bool) -> dict:
    item = db.get(PurchaseOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购单不存在")
    rows = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).all()
    supplier = db.get(Supplier, item.supplier_id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "采购入库单" if inbound else "采购订单",
        "doc_no": item.order_no,
        "header_left": [
            ("供应商", _s(supplier.name) if supplier else ""),
            ("联系人", _s(item.contact) or _s(supplier.contact) if supplier else ""),
            ("联系电话", _s(item.contact_phone) or (_s(supplier.phone) if supplier else "")),
            ("收货地址", _s(item.address)),
        ],
        "header_right": [
            ("单据日期", _s(item.order_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("付款方式", _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 132, "align": "l"},
            {"label": "规格", "width": 82, "align": "l"},
            {"label": "单位", "width": 38, "align": "c"},
            {"label": "数量", "width": 52, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 45, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"},
        "extra_rows": [
            ("优惠金额", f"{float(item.discount_amount or 0.0):,.2f}"),
            ("实付金额", f"{float(item.paid_amount or 0.0):,.2f}"),
            ("累计欠款", f"{float(item.total_debt or 0.0):,.2f}"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "仓管", "供应商签收"],
    }



def _sales_print_spec(db: Session, order_id: int, *, delivery: bool) -> dict:
    item = db.get(SalesOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售单不存在")
    rows = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).all()
    customer = db.get(Customer, item.customer_id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    spec: dict = {
        "title": "送货单" if delivery else "销售开单",
        "doc_no": item.order_no,
        "header_left": [
            ("客户名称", _s(customer.name) if customer else ""),
            ("联系人", _s(item.contact) or (_s(customer.contact) if customer else "")),
            ("联系电话", _s(item.contact_phone) or (_s(customer.phone) if customer else "")),
            ("送货地址" if delivery else "收货地址", _s(item.address)),
        ],
        "header_right": [
            ("单据日期", _s(item.order_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("送货日期" if delivery else "付款方式", _s(item.delivery_date) if delivery else _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 150, "align": "l"},
            {"label": "规格", "width": 95, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
        ],
        "rows": _order_rows(rows, with_price=not delivery),
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "司机/送货", "客户签收"],
    }
    if delivery:
        spec["columns"] += [
            {"label": "签收数量", "width": 70, "align": "c"},
            {"label": "备注", "width": 71, "align": "l"},
        ]
    else:
        spec["columns"] += [
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 65, "align": "r"},
            {"label": "备注", "width": 33, "align": "l"},
        ]
        spec["totals"] = {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"}
        spec["extra_rows"] = [
            ("优惠金额", f"{float(item.discount_amount or 0.0):,.2f}"),
            ("实收金额", f"{float(item.received_amount or 0.0):,.2f}"),
            ("累计欠款", f"{float(item.total_debt or 0.0):,.2f}"),
        ]
    return spec



_PRINT_KINDS = {
    "purchase-order": ("采购订单", _purchase_print_spec, {"inbound": False}),
    "purchase-inbound": ("采购入库单", _purchase_print_spec, {"inbound": True}),
    "sales-order": ("销售开单", _sales_print_spec, {"delivery": False}),
    "delivery-note": ("送货单", _sales_print_spec, {"delivery": True}),
}



@router.get("/print/{doc_type}/{doc_id}")
def print_order(doc_type: str, doc_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    """单据打印：purchase-order / purchase-inbound / sales-order / delivery-note → PDF。"""
    entry = _PRINT_KINDS.get(doc_type)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知的打印类型：{doc_type}")
    _, builder, kwargs = entry
    spec = builder(db, doc_id, **kwargs)
    filename = str(spec.get("doc_no") or f"{doc_type}_{doc_id}").replace("/", "-") or f"{doc_type}_{doc_id}"
    return _pdf_response(spec, filename, db, doc_type, _wants_json(request))



def _contract_parties(c: Contract) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (甲方=需方, 乙方=供方) 两组主体信息。

    销售合同我方是卖方（乙方）；采购合同我方是买方（甲方）。
    """
    own = {
        "name": _s(c.own_name),
        "tax_no": _s(c.own_tax_no),
        "legal": _s(c.own_legal_person),
        "address": _s(c.own_address),
        "contact": _s(c.own_contact),
        "phone": _s(c.own_phone),
        "bank": _s(c.own_bank_name),
        "account": _s(c.own_bank_account),
    }
    party = {
        "name": _s(c.party_name),
        "tax_no": _s(c.party_tax_no),
        "legal": _s(c.party_legal_person),
        "address": _s(c.party_address),
        "contact": _s(c.party_contact),
        "phone": _s(c.party_phone),
        "bank": _s(c.party_bank_name),
        "account": _s(c.party_bank_account),
    }
    if c.contract_type == "purchase":
        return own, party  # 我方采购 = 甲方（需方）
    return party, own



def _a2_paragraphs(c: Contract) -> list[str]:
    """A2 标准版的条款正文 —— 变量从合同字段取值，缺项用行业常规表述兜底。"""
    total = float(c.total_amount or 0.0)
    chinese = c.amount_chinese or amount_to_chinese(total)
    tax_note = "含税价" if c.is_tax_included else "不含税价"
    rate = f"，增值税税率 {c.tax_rate:g}%" if c.tax_rate else ""
    penalty = float(c.penalty_rate or _A2_DEFAULT_PENALTY_RATE)
    penalty_desc = f"万分之{round(penalty * 10000)}" if penalty else "万分之五"
    inspection_days = c.inspection_days or _A2_DEFAULT_INSPECTION_DAYS
    objection_days = c.objection_days or _A2_DEFAULT_OBJECTION_DAYS
    copies = c.copies or _A2_DEFAULT_COPIES
    buyer, seller = _contract_parties(c)

    def pick(field: str) -> str:
        return _s(getattr(c, field)) or _A2_DEFAULTS[field]

    paras = [
        "第一条 合同标的\n"
        "1.1 本合同标的为本合同明细表所列货物（以下简称“货物”），其名称、规格型号、单位、"
        "数量、单价及金额均以明细表所列为准。\n"
        f"1.2 本合同总价为人民币（大写）{chinese}（¥{total:,.2f}），为{tax_note}{rate}。",

        "第二条 质量标准\n"
        f"2.1 货物质量应符合：{pick('quality_standard')}。\n"
        "2.2 乙方应随货提供产品合格证、质保书等质量证明文件。",

        "第三条 交付与运输\n"
        f"3.1 交货时间：{_s(c.delivery_date) or '双方另行约定'}；"
        f"交货地点：{_s(c.delivery_place) or '甲方指定地点'}；"
        f"交货方式：{pick('delivery_method')}。\n"
        f"3.2 运输与风险承担：{pick('freight_bearer')}。",

        "第四条 包装\n"
        f"4.1 {pick('package_standard')}。",

        "第五条 验收\n"
        f"5.1 甲方应在收到货物后 {inspection_days} 日内完成验收。\n"
        f"5.2 甲方对数量、外观有异议的，应于收货后 3 日内书面提出；对内在质量有异议的，"
        f"应于收货后 {objection_days} 日内书面提出。逾期未提出异议的，视为验收合格。",

        "第六条 质保与售后\n"
        f"6.1 {pick('warranty_terms')}。",

        "第七条 价款支付与发票\n"
        f"7.1 付款方式与节点：{pick('payment_terms')}。\n"
        f"7.2 发票要求：{pick('invoice_requirement')}。",

        "第八条 违约责任\n"
        f"8.1 乙方逾期交货的，每逾期一日应按逾期部分货款的{penalty_desc}向甲方支付违约金；"
        "逾期超过 30 日的，甲方有权解除合同。\n"
        f"8.2 甲方逾期付款的，每逾期一日应按逾期金额的{penalty_desc}向乙方支付违约金。\n"
        "8.3 违约方应赔偿因其违约给对方造成的直接经济损失。",

        "第九条 不可抗力\n"
        "9.1 因不可抗力致使本合同不能履行或不能完全履行的，遇不可抗力的一方应及时通知对方，"
        "并于 15 日内提供有效证明，双方协商解决，互不承担违约责任。",

        "第十条 争议解决\n"
        f"10.1 因本合同发生的争议，双方应友好协商解决；协商不成的，{pick('dispute_resolution')}。",

        "第十一条 其他约定\n"
        f"11.1 本合同一式 {copies} 份，双方各执 {max(1, copies // 2)} 份，具有同等法律效力。\n"
        "11.2 本合同自双方签字并盖章之日起生效。\n"
        f"11.3 双方确认的送达地址：{_s(c.service_address) or '以合同首部载明的地址为准'}；"
        "一方地址变更应书面通知对方，否则原地址仍视为有效送达地址。\n"
        "11.4 本合同未尽事宜，双方另行签订补充协议，补充协议与本合同具有同等法律效力。",
    ]

    if _s(c.other_terms):
        paras.append(f"第十二条 补充约定\n{_s(c.other_terms)}")

    return paras



def _contract_print_spec(db: Session, contract_id: int) -> dict[str, object]:
    c = db.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    rows = _contract_items(db, c.id)
    buyer, seller = _contract_parties(c)
    total = float(c.total_amount or 0.0)

    def party_block(label: str, p: dict[str, str]) -> list[tuple[str, str]]:
        return [
            (label, p["name"]),
            ("统一社会信用代码", p["tax_no"]),
            ("地址", p["address"]),
            ("法定代表人", p["legal"]),
            ("联系人 / 电话", f"{p['contact']} {p['phone']}".strip()),
        ]

    valid = ""
    if _s(c.valid_from) or _s(c.valid_to):
        valid = f"{_s(c.valid_from) or '—'} ~ {_s(c.valid_to) or '—'}"

    spec: dict[str, object] = {
        "company": _s(c.own_name) or load_company()["own_name"],
        "title": _s(c.title) or "购销合同",
        "subtitle": f"（{CONTRACT_TEMPLATES.get(c.template, '标准版')}）",
        "period": f"合同编号：{c.contract_no}",
        # 公文排版（2026-10-25）：与 contract_template.document_to_print_spec 同一套规范
        "layout": {
            "font_title": 16,
            "font_header": 10,
            "font_body": 10.5,
            "margin_left": 48,
            "margin_right": 48,
        },
        "paragraph_style": {"size": 10.5, "lineheight": 1.5, "indent": True, "justify": True},
        "header_left": party_block("甲方（需方）", buyer),
        "header_right": party_block("乙方（供方）", seller),
        "columns": [
            {"label": "序号", "width": 32, "min_width": 30, "align": "c"},
            # 货物名称/规格允许折行，绝不 _fit 成 "..."; 金额列给足 min_width。
            {"label": "货物名称", "width": 170, "min_width": 150, "wrap": True, "align": "l"},
            {"label": "规格型号", "width": 110, "min_width": 90, "wrap": True, "align": "l"},
            {"label": "单位", "width": 42, "min_width": 38, "align": "c"},
            {"label": "数量", "width": 52, "min_width": 48, "align": "r"},
            {"label": "单价", "width": 62, "min_width": 58, "align": "r"},
            {"label": "金额", "width": 82, "min_width": 78, "align": "r"},
            {"label": "备注", "width": 48, "min_width": 40, "wrap": True, "align": "l"},
        ],
        "rows": [
            [
                index,
                _s(row.product_name),
                _s(row.standards),
                _s(row.unit),
                f"{float(row.quantity or 0):g}",
                f"{float(row.unit_price or 0):,.2f}",
                f"{float(row.amount or 0):,.2f}",
                _s(row.note),
            ]
            for index, row in enumerate(rows, 1)
        ],
        "totals": {
            "label": "合计",
            "chinese": f"大写：{c.amount_chinese or amount_to_chinese(total)}",
            "amount": f"{total:,.2f}",
        },
        "extra_rows": [
            ("签订日期", _s(c.sign_date)),
            ("签订地点", _s(c.sign_place)),
            ("有效期限", valid),
            ("关联单据", _s(c.order_no)),
        ],
        "paragraphs": _a2_paragraphs(c),
        "notes": [
            f"说明：本合同共 {len(rows)} 项标的物，总价 ¥{total:,.2f}（大写见上）。"
            "本合同经双方签字盖章后生效，一式两份，双方各执一份留存。",
            "本模板为标准版条文框架，具体条款以双方协商一致后签署的正式文本为准。",
        ],
        # 标准公文签章栏网格：开户行 / 账号 / 盖章处一应俱全
        "sign_grid": [
            ["甲方（需方·盖章）", "乙方（供方·盖章）"],
            [f"单位名称：{buyer['name'] or '＿＿＿＿＿＿'}", f"单位名称：{seller['name'] or '＿＿＿＿＿＿'}"],
            [f"法定代表人：{buyer['legal'] or '＿＿＿＿＿＿'}", f"法定代表人：{seller['legal'] or '＿＿＿＿＿＿'}"],
            [f"开户银行：{buyer['bank'] or '＿＿＿＿＿＿'}", f"开户银行：{seller['bank'] or '＿＿＿＿＿＿'}"],
            [f"银行账号：{buyer['account'] or '＿＿＿＿＿＿'}", f"银行账号：{seller['account'] or '＿＿＿＿＿＿'}"],
            ["（盖章处）", "（盖章处）"],
            [f"签订日期：{_s(c.sign_date) or '＿＿＿＿＿＿'}", f"签订日期：{_s(c.sign_date) or '＿＿＿＿＿＿'}"],
        ],
    }
    return spec



def print_contract(contract_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    """A2 购销合同（标准版）PDF。

    不单独挂路由 —— 合同打印走 `/print/contract/{id}`，由统一的 print_order
    入口按 `_PRINT_KINDS` 分发（路由在文件末尾登记，避开与 `/print/{doc_type}/{doc_id}`
    的通配冲突）。
    """
    spec = _contract_print_spec(db, contract_id)
    filename = str(spec.get("period") or "contract").replace("合同编号：", "contract_")
    return _pdf_response(spec, filename, db, "contract", _wants_json(request))



# ===========================================================================
# 《工矿产品购销合同》正文：预览 + PDF（2026-10-22）
# ===========================================================================
# 与上面 A2 打印的区别：
#   · A2 = 系统里"这张合同"的打印件，条款取的是库里存的字段；
#   · 这里 = **按标准范本自动生成正文**，可以在**还没保存**的时候先看效果，
#     所以入参是"一份 payload"，不要求合同已存在。
# 两者共用同一个 PDF 出口（`_pdf_response`），纸张/页脚/字体完全一致。


def _contract_payload_from_db(db: Session, contract_id: int) -> dict:
    """把库里的合同摊成与前端表单同构的 payload，让生成器只认一种入参。"""
    row = db.get(Contract, contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    items = db.query(ContractItem).filter(ContractItem.contract_id == contract_id).order_by(
        ContractItem.id
    ).all()
    payload = {
        "contract_id": row.id,
        "direction": row.direction,
        "title": row.title,
        "contract_no": row.contract_no,
        "party_name": row.party_name,
        "party_tax_no": row.party_tax_no,
        "party_legal_person": row.party_legal_person,
        "party_address": row.party_address,
        "party_contact": row.party_contact,
        "party_phone": row.party_phone,
        "party_bank_name": row.party_bank_name,
        "party_bank_account": row.party_bank_account,
        "own_name": row.own_name,
        "own_tax_no": row.own_tax_no,
        "own_legal_person": row.own_legal_person,
        "own_address": row.own_address,
        "own_contact": row.own_contact,
        "own_phone": row.own_phone,
        "own_bank_name": row.own_bank_name,
        "own_bank_account": row.own_bank_account,
        "sign_date": row.sign_date,
        "sign_place": row.sign_place,
        "tax_rate": row.tax_rate,
        "is_tax_included": row.is_tax_included,
        "payment_terms": row.payment_terms,
        "invoice_requirement": row.invoice_requirement,
        "quality_standard": row.quality_standard,
        "package_standard": row.package_standard,
        "delivery_date": row.delivery_date,
        "delivery_place": row.delivery_place,
        "delivery_method": row.delivery_method,
        "freight_bearer": row.freight_bearer,
        "inspection_days": row.inspection_days,
        "objection_days": row.objection_days,
        "penalty_rate": row.penalty_rate,
        "dispute_resolution": row.dispute_resolution,
        "copies": row.copies,
        "items": [
            {
                "product_name": item.product_name,
                "standards": item.standards,
                "unit": item.unit,
                "quantity": float(item.quantity or 0),
                "unit_price": float(item.unit_price or 0),
                "amount": float(item.amount or 0),
                "note": item.note,
            }
            for item in items
        ],
    }
    return payload


def _contract_document_payload(db: Session, payload: dict) -> dict:
    """支持两种入参：`{contract_id: N}`（已存合同）或整份表单 payload（还没保存）。"""
    contract_id = payload.get("contract_id")
    if contract_id not in (None, ""):
        try:
            return _contract_payload_from_db(db, int(contract_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="contract_id 必须是整数") from exc
    return payload


@router.post("/print/contract-document/pdf", summary="按内置范本生成合同正文 PDF")
def print_contract_document(payload: dict, request: Request, db: Session = Depends(get_db)):
    """用标准范本把表单数据渲染成合同正文 PDF。

    请求体就是合同表单（或 `{"contract_id": N}`），**不要求先保存合同** ——
    用户要的就是"填完先看看正文长什么样"。
    """
    data = _contract_document_payload(db, payload)
    data = resolve_contract_document_payload(db, data)
    document = build_gongkuang_document(data, data.get("items") or [])
    spec = document_to_print_spec(document)
    raw_no = str(document.get("contract_no") or "").strip()
    # 还没编号的草稿不要生成 "未编号 · 草稿.pdf" 这种文件名 —— 存到硬盘上谁也不知道这是哪单
    if not raw_no or raw_no.startswith("（"):
        raw_no = f"draft_{datetime.now().strftime('%Y%m%d%H%M')}"
    filename = raw_no.replace("（", "").replace("）", "").replace(" ", "").replace("·", "")
    # 文件名别再带 "gongkuang"：内置范本默认已经是《产品买卖合同（简易版）》，
    # 存到硬盘上的名字要对得上用户看到的那份合同。
    return _pdf_response(spec, f"contract_{filename}", db, "contract", _wants_json(request))


# 合同打印登记进统一打印入口（放在末尾登记，规避函数定义顺序问题）
_PRINT_KINDS["contract"] = ("购销合同", _contract_print_spec, {})



def _quotation_print_spec(db: Session, quotation_id: int) -> dict:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    rows = _quotation_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "报价单",
        "doc_no": item.quote_no,
        "header_left": [
            ("客户名称", _s(item.customer_name)),
            ("联系人", _s(item.contact)),
            ("联系电话", _s(item.contact_phone)),
            ("客户地址", _s(item.customer_address)),
        ],
        "header_right": [
            ("报价日期", _s(item.quote_date) or _d(item.created_at)),
            ("报价效期", _s(item.valid_until)),
            ("出货仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 150, "align": "l"},
            {"label": "规格", "width": 95, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 65, "align": "r"},
            {"label": "备注", "width": 33, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"},
        "extra_rows": [
            ("付款方式", _s(item.payment_method)),
            ("运输方式", _s(item.transport_method)),
            ("交货地点", _s(item.delivery_place)),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "客户确认"],
    }



# 报价单打印登记进统一打印入口
_PRINT_KINDS["quotation"] = ("报价单", _quotation_print_spec, {})



def _purchase_return_print_spec(db: Session, return_id: int) -> dict:
    item = db.get(PurchaseReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="采购退货单不存在")
    rows = _purchase_return_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "采购退货单",
        "doc_no": item.return_no,
        "header_left": [
            ("供应商", _s(item.supplier_name)),
            ("联系人", _s(item.contact)),
            ("联系电话", _s(item.contact_phone)),
            ("供应商地址", _s(item.address)),
        ],
        "header_right": [
            ("退货日期", _s(item.return_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("退款方式", _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 150, "align": "l"},
            {"label": "规格", "width": 95, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 65, "align": "r"},
            {"label": "备注", "width": 33, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"},
        "extra_rows": [
            ("退货原因", _s(item.return_reason)),
            ("来源单号", _s(item.source_order_no)),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "仓管", "供应商签收"],
    }



# 采购退货打印登记进统一打印入口
_PRINT_KINDS["purchase-return"] = ("采购退货单", _purchase_return_print_spec, {})



def _sales_return_print_spec(db: Session, return_id: int) -> dict:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    rows = _sales_return_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    net = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "销售退货单",
        "doc_no": item.return_no,
        "header_left": [
            ("客户", _s(item.customer_name)),
            ("联系人", _s(item.contact)),
            ("联系电话", _s(item.contact_phone)),
            ("客户地址", _s(item.address)),
        ],
        "header_right": [
            ("退货日期", _s(item.return_date) or _d(item.created_at)),
            ("仓库", _s(warehouse.name) if warehouse else ""),
            ("业务员", _s(item.businesser)),
            ("退款方式", _s(item.payment_method)),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 150, "align": "l"},
            {"label": "规格", "width": 95, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 65, "align": "r"},
            {"label": "备注", "width": 33, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {"label": "合计", "chinese": f"大写：{amount_to_chinese(net)}", "amount": f"{net:,.2f}"},
        "extra_rows": [
            ("退货原因", _s(item.return_reason)),
            ("来源单号", _s(item.source_order_no)),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "仓管", "客户签收"],
    }



# 销售退货打印登记进统一打印入口
_PRINT_KINDS["sales-return"] = ("销售退货单", _sales_return_print_spec, {})



def _transfer_print_spec(db: Session, transfer_id: int) -> dict:
    item = db.get(InventoryTransfer, transfer_id)
    if item is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    rows = _transfer_items(db, item.id)
    from_wh = db.get(Warehouse, item.from_warehouse_id) if item.from_warehouse_id else None
    to_wh = db.get(Warehouse, item.to_warehouse_id) if item.to_warehouse_id else None
    total_qty = round(float(item.total_quantity or 0.0), 2)
    return {
        "title": "库存调拨单",
        "doc_no": item.transfer_no,
        "header_left": [
            ("调出仓库", _s(from_wh.name) if from_wh else ""),
            ("调入仓库", _s(to_wh.name) if to_wh else ""),
            ("经办人", _s(item.handler)),
        ],
        "header_right": [
            ("调拨日期", _s(item.transfer_date) or _d(item.created_at)),
            ("调拨原因", _s(item.reason)),
            ("状态", TRANSFER_STATUS.get(item.status, _s(item.status))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 160, "align": "l"},
            {"label": "规格", "width": 100, "align": "l"},
            {"label": "单位", "width": 45, "align": "c"},
            {"label": "数量", "width": 60, "align": "c"},
            {"label": "备注", "width": 133, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=False),
        "totals": {"label": "合计", "chinese": f"共 {len(rows)} 种商品", "amount": f"{total_qty:,.2f}"},
        "extra_rows": [
            ("调出仓库", _s(from_wh.name) if from_wh else ""),
            ("调入仓库", _s(to_wh.name) if to_wh else ""),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "调出仓管", "调入仓管"],
    }



# 调拨单打印登记进统一打印入口
_PRINT_KINDS["inventory-transfer"] = ("库存调拨单", _transfer_print_spec, {})



def _stocktaking_print_spec(db: Session, check_id: int) -> dict:
    item = db.get(Stocktaking, check_id)
    if item is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    rows = _stocktaking_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    printable = [
        [
            str(i),
            _s(row.product_name),
            _s(row.standards),
            _s(row.unit),
            f"{float(row.book_quantity or 0):,.2f}",
            f"{float(row.actual_quantity or 0):,.2f}",
            f"{float(row.diff_quantity or 0):+,.2f}",
            _s(row.note),
        ]
        for i, row in enumerate(rows, start=1)
    ]
    return {
        "title": "库存盘点单",
        "doc_no": item.check_no,
        "header_left": [
            ("盘点仓库", _s(warehouse.name) if warehouse else ""),
            ("盘点人", _s(item.handler)),
            ("盘点范围", _s(item.scope)),
        ],
        "header_right": [
            ("盘点日期", _s(item.check_date) or _d(item.created_at)),
            ("状态", STOCKTAKING_STATUS.get(item.status, _s(item.status))),
            ("盘点行数", f"{len(rows)} 行"),
        ],
        "columns": [
            {"label": "序号", "width": 32, "align": "c"},
            {"label": "商品名称", "width": 130, "align": "l"},
            {"label": "规格", "width": 82, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "账面数", "width": 60, "align": "r"},
            {"label": "实盘数", "width": 60, "align": "r"},
            {"label": "盈亏", "width": 60, "align": "r"},
            {"label": "备注", "width": 71, "align": "l"},
        ],
        "rows": printable,
        "totals": {
            "label": "合计",
            "chinese": f"盘盈 {float(item.total_profit or 0):,.2f} · 盘亏 {float(item.total_loss or 0):,.2f}",
            "amount": f"{float(item.total_amount or 0):+,.2f}",
        },
        "extra_rows": [
            ("盘盈行数", f"{item.profit_lines} 行"),
            ("盘亏行数", f"{item.loss_lines} 行"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "盘点人", "审核", "仓管"],
    }



# 盘点单打印登记进统一打印入口
_PRINT_KINDS["stocktaking"] = ("库存盘点单", _stocktaking_print_spec, {})



def _adjust_print_spec(db: Session, adjust_id: int, *, adjust_type: str) -> dict:
    item = db.get(InventoryAdjustment, adjust_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报损报溢单不存在")
    rows = _adjust_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    spec = ADJUST_TYPES[adjust_type]
    total_amount = round(float(item.total_amount or 0.0), 2)
    return {
        "title": f"库存{spec['label']}单",
        "doc_no": item.adjust_no,
        "header_left": [
            ("发生仓库", _s(warehouse.name) if warehouse else ""),
            ("经办人", _s(item.handler)),
            ("{0}原因".format(spec["label"]), _s(item.reason)),
        ],
        "header_right": [
            ("单据日期", _s(item.adjust_date) or _d(item.created_at)),
            ("库存方向", "减少（出库）" if spec["direction"] == "outbound" else "增加（入库）"),
            ("状态", ADJUSTMENT_STATUS.get(item.status, _s(item.status))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 55, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 68, "align": "r"},
            {"label": "备注", "width": 41, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "合计",
            "chinese": f"大写：{amount_to_chinese(total_amount)}",
            "amount": f"{total_amount:,.2f}",
        },
        "extra_rows": [
            ("合计数量", f"{float(item.total_quantity or 0):,.2f}"),
            ("说明", "报损/报溢只调整现存量，不生成应收应付与财务流水"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "仓管", "负责人"],
    }



def _scrap_print_spec(db: Session, adjust_id: int) -> dict:
    return _adjust_print_spec(db, adjust_id, adjust_type="scrap")



def _overflow_print_spec(db: Session, adjust_id: int) -> dict:
    return _adjust_print_spec(db, adjust_id, adjust_type="overflow")



# 报损单 / 报溢单打印登记进统一打印入口
_PRINT_KINDS["inventory-scrap"] = ("库存报损单", _scrap_print_spec, {})

_PRINT_KINDS["inventory-overflow"] = ("库存报溢单", _overflow_print_spec, {})



def _production_plan_print_spec(db: Session, plan_id: int) -> dict:
    item = db.get(ProductionPlan, plan_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产计划单不存在")
    rows = _production_plan_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    total_amount = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "生产计划单",
        "doc_no": item.plan_no,
        "header_left": [
            ("生产仓库", _s(warehouse.name) if warehouse else ""),
            ("计划员", _s(item.handler)),
            ("车间 / 产线", _s(item.workshop)),
        ],
        "header_right": [
            ("计划日期", _s(item.plan_date) or _d(item.created_at)),
            ("计划完工", _s(item.delivery_date)),
            ("计划类型", PLAN_TYPES.get(item.plan_type, {}).get("label", _s(item.plan_type))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "产品名称", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "计划数量", "width": 60, "align": "c"},
            {"label": "计划单价", "width": 62, "align": "r"},
            {"label": "计划金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 42, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "合计",
            "chinese": f"大写：{amount_to_chinese(total_amount)}",
            "amount": f"{total_amount:,.2f}",
        },
        "extra_rows": [
            ("计划总量", f"{float(item.total_quantity or 0):,.2f}"),
            ("状态", PRODUCTION_PLAN_STATUS.get(item.status, _s(item.status))),
            ("来源订单", _s(item.source_order_no)),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "车间", "负责人"],
    }



_PRODUCTION_PLAN_PRINT = _production_plan_print_spec


# 生产计划打印登记进统一打印入口
_PRINT_KINDS["production-plan"] = ("生产计划单", _production_plan_print_spec, {})



def _material_issue_print_spec(db: Session, issue_id: int) -> dict:
    item = db.get(MaterialIssue, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产领料单不存在")
    rows = _material_issue_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    total_amount = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "生产领料单",
        "doc_no": item.issue_no,
        "header_left": [
            ("领料仓库", _s(warehouse.name) if warehouse else ""),
            ("领料车间", _s(item.workshop)),
            ("领料人", _s(item.handler)),
        ],
        "header_right": [
            ("单据日期", _s(item.issue_date) or _d(item.created_at)),
            ("关联计划", _s(item.plan_no)),
            ("状态", MATERIAL_ISSUE_STATUS.get(item.status, _s(item.status))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "材料名称", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "领料数量", "width": 60, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 42, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "合计",
            "chinese": f"大写：{amount_to_chinese(total_amount)}",
            "amount": f"{total_amount:,.2f}",
        },
        "extra_rows": [
            ("合计数量", f"{float(item.total_quantity or 0):,.2f}"),
            ("说明", "生产领料只把材料发到车间（减少原料库存），不生成应收应付与财务流水"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "领料人", "仓管"],
    }



_PRINT_KINDS["material-issue"] = ("生产领料单", _material_issue_print_spec, {})



def _material_return_print_spec(db: Session, return_id: int) -> dict:
    item = db.get(MaterialReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="生产退料单不存在")
    rows = _material_return_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    total_amount = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "生产退料单",
        "doc_no": item.return_no,
        "header_left": [
            ("退料仓库", _s(warehouse.name) if warehouse else ""),
            ("退料车间", _s(item.workshop)),
            ("退料人", _s(item.handler)),
        ],
        "header_right": [
            ("单据日期", _s(item.return_date) or _d(item.created_at)),
            ("关联计划", _s(item.plan_no)),
            ("状态", MATERIAL_RETURN_STATUS.get(item.status, _s(item.status))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "材料名称", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "退料数量", "width": 60, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 42, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "合计",
            "chinese": f"大写：{amount_to_chinese(total_amount)}",
            "amount": f"{total_amount:,.2f}",
        },
        "extra_rows": [
            ("合计数量", f"{float(item.total_quantity or 0):,.2f}"),
            ("退料原因", _s(item.reason)),
            ("说明", "生产退料把车间余料退回仓库（增加原料库存），不生成应收应付与财务流水"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "退料人", "仓管"],
    }



_PRINT_KINDS["material-return"] = ("生产退料单", _material_return_print_spec, {})



def _finished_goods_print_spec(db: Session, receipt_id: int) -> dict:
    item = db.get(FinishedGoodsReceipt, receipt_id)
    if item is None:
        raise HTTPException(status_code=404, detail="成品入库单不存在")
    rows = _finished_goods_items(db, item.id)
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    total_amount = round(float(item.total_amount or 0.0), 2)
    return {
        "title": "成品入库单",
        "doc_no": item.receipt_no,
        "header_left": [
            ("入库仓库", _s(warehouse.name) if warehouse else ""),
            ("生产车间", _s(item.workshop)),
            ("交库人", _s(item.handler)),
        ],
        "header_right": [
            ("单据日期", _s(item.receipt_date) or _d(item.created_at)),
            ("关联计划", _s(item.plan_no)),
            ("状态", FINISHED_GOODS_STATUS.get(item.status, _s(item.status))),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "成品名称", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "入库数量", "width": 60, "align": "c"},
            {"label": "单位成本", "width": 62, "align": "r"},
            {"label": "入库成本", "width": 70, "align": "r"},
            {"label": "备注", "width": 42, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "合计",
            "chinese": f"大写：{amount_to_chinese(total_amount)}",
            "amount": f"{total_amount:,.2f}",
        },
        "extra_rows": [
            ("合计数量", f"{float(item.total_quantity or 0):,.2f}"),
            ("说明", "成品入库增加成品库存，并结转生产成本（成本口径流水，不影响应收应付）"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "检验", "交库人", "仓管"],
    }



_PRINT_KINDS["finished-goods"] = ("成品入库单", _finished_goods_print_spec, {})



def _outsourcing_print_spec(db: Session, order_id: int) -> dict:
    item = db.get(OutsourcingOrder, order_id)
    if item is None:
        raise HTTPException(status_code=404, detail="委外加工单不存在")
    rows = _outsourcing_items(db, item.id)
    supplier = db.get(Supplier, item.supplier_id) if item.supplier_id else None
    warehouse = db.get(Warehouse, item.warehouse_id) if item.warehouse_id else None
    fee = round(float(item.process_fee or 0.0), 2)
    return {
        "title": "委外加工单",
        "doc_no": item.order_no,
        "header_left": [
            ("外协厂", _s(supplier.name) if supplier else ""),
            ("发料/收料仓", _s(warehouse.name) if warehouse else ""),
            ("经办人", _s(item.handler)),
        ],
        "header_right": [
            ("单据日期", _s(item.order_date) or _d(item.created_at)),
            ("加工产出", f"{_s(item.product_name)} × {float(item.quantity or 0):,.2f}"),
            ("加工费", f"{fee:,.2f}"),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "发出材料", "width": 148, "align": "l"},
            {"label": "规格", "width": 92, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "发出数量", "width": 60, "align": "c"},
            {"label": "单价", "width": 62, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 42, "align": "l"},
        ],
        "rows": _order_rows(rows, with_price=True),
        "totals": {
            "label": "发出材料合计",
            "chinese": f"大写：{amount_to_chinese(item.total_amount or 0.0)}",
            "amount": f"{float(item.total_amount or 0):,.2f}",
        },
        "extra_rows": [
            ("加工费（应付）", f"{fee:,.2f}"),
            ("收回成品", f"{_s(item.product_name)} {float(item.quantity or 0):,.2f} {_s(item.unit)}"),
            ("说明", "发出材料减少原料库存、收回成品增加成品库存，加工费产生应付"),
        ],
        "notes": [f"备注：{_s(item.note)}"] if item.note else [],
        "signatures": ["制单", "审核", "外协厂", "仓管"],
    }



_PRINT_KINDS["outsourcing"] = ("委外加工单", _outsourcing_print_spec, {})



def _assembly_print_spec(db: Session, order_id: int) -> dict:
    """组合拆卸单打印 spec（B4 模板）。"""
    order = db.get(AssemblyOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="组合拆卸单不存在")
    items = (
        db.query(AssemblyOrderItem)
        .filter(AssemblyOrderItem.assembly_order_id == order_id)
        .order_by(AssemblyOrderItem.id)
        .all()
    )
    warehouse = db.get(Warehouse, order.warehouse_id) if order.warehouse_id else None
    doc_type = order.doc_type or "combo"
    direction = "组合" if doc_type == "combo" else "拆卸"
    pairs = (
        [("成品入库", "子件出库")]
        if doc_type == "combo"
        else [("成品出库", "子件入库")]
    )

    rows = []
    for index, row in enumerate(items, start=1):
        quantity = float(row.quantity or 0.0)
        price = float(row.unit_price or 0.0)
        rows.append(
            [
                index,
                _s(row.product_name),
                _s(row.standards),
                _s(row.unit),
                f"{quantity:,.2f}".rstrip("0").rstrip("."),
                f"{price:,.2f}",
                f"{quantity * price:,.2f}",
                _s(row.note),
            ]
        )

    return {
        "company": load_company()["own_name"],
        "title": f"{direction}单",
        "doc_no": order.order_no,
        "header_left": [
            ("仓库", _s(getattr(warehouse, "name", None))),
            ("经办人", _s(order.handler)),
        ],
        "header_right": [
            ("单据日期", _s(order.order_date)),
            ("成品", f"{_s(order.product_name)} × {int(order.quantity or 0)}"),
        ],
        "columns": [
            {"label": "序号", "width": 34, "align": "c"},
            {"label": "商品名称", "width": 140, "align": "l"},
            {"label": "规格", "width": 78, "align": "l"},
            {"label": "单位", "width": 40, "align": "c"},
            {"label": "数量", "width": 60, "align": "r"},
            {"label": "单价", "width": 60, "align": "r"},
            {"label": "金额", "width": 70, "align": "r"},
            {"label": "备注", "width": 52, "align": "l"},
        ],
        "rows": rows,
        "totals": {
            "label": "子件合计",
            "chinese": f"大写：{amount_to_chinese(float(order.total_quantity or 0))}",
            "amount": f"{float(order.total_quantity or 0):,.2f}".rstrip("0").rstrip("."),
        },
        "extra_rows": [
            ("库存方向", f"{pairs[0][0]} / {pairs[0][1]}"),
            ("成品数量", f"{int(order.quantity or 0)} {_s(order.unit)}"),
        ],
        "notes": [
            f"说明：{direction}在同一仓库内完成形态转换，不产生应收应付，只写库存流水。",
            f"备注：{_s(order.note)}" if order.note else "",
        ],
        "signatures": ["制单", "审核", "仓管"],
    }



_PRINT_KINDS["assembly"] = ("组合拆卸单", _assembly_print_spec, {})



def _money(v) -> str:
    """金额显示：千分位 + 两位小数。空值一律显示 0.00 而不是空白 ——
    对账单上空格会让人以为是"漏印"，印 0.00 才明确是"这一项没有"。"""
    try:
        return f"{float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"



def _statement_record_print_spec(db: Session, statement_id: int) -> dict:
    """增强版对账单（`statements` 表）PDF。

    与上面的 `print_statement` 是**两条不同的路径**，别合并：

    · `print_statement`（`/print/statement/{party_type}/{party_id}`）= **实时聚合**，
      从合同/发票/收付款现算一遍流水账，适合"临时看看这个客户欠多少"。
    · 本函数（`/print/statement-record/{id}`）= **打印一张已定稿的对账单**，
      金额一律读头部快照字段，**绝不重算**。

    第二条路径必有的原因：对账单一旦发给对方就是法律凭证。若打印时重算，
    对方手里的 PDF 会随着我方事后改单悄悄变数，对账就永远扯不清。
    """
    row = db.get(Statement, statement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="对账单不存在")

    items = sorted(row.items, key=lambda x: (x.line_no or 0, x.id or 0))
    direction_label = STATEMENT_DIRECTIONS.get(row.direction, row.direction)
    party_caption = "客户名称" if row.party_type == "customer" else "供应商名称"

    rows: list[list] = []
    for idx, it in enumerate(items, start=1):
        rows.append(
            [
                str(idx),
                _s(it.business_date),
                STATEMENT_SOURCE_TYPES.get(it.source_type or "", _s(it.source_type)),
                _s(it.contract_no),
                _s(it.summary) or _s(it.source_no),
                _money(it.contract_amount),
                _money(it.invoiced_amount),
                _money(it.uninvoiced_amount),
                _money(it.received_amount),
                _money(it.outstanding_amount),
            ]
        )

    return {
        "title": "对账单",
        "subtitle": direction_label,
        "doc_no": _s(row.statement_no),
        "period": f"账期：{_s(row.period_start) or '（起始）'} 至 {_s(row.period_end) or '（截止）'}",
        # 横向打印（2026-10-25）：对账单是宽表单据，竖版挤成两页还没法看。
        # 等价于网页打印的 `@page { size: A4 landscape; margin: 10mm; }`。
        "orientation": "landscape",
        # 深色表头 + 浅灰汇总块：严格复刻网页端「增强对账单」的观感
        "table_head_fill": "#1F4E78",
        "red_positive_columns": [9],  # 剩余未收/付 > 0 → 红字（欠款提醒）
        # 行高加大（2026-10-25 用户反馈表格太挤）：26pt ≈ 默认的 1.4 倍
        "row_height": 26,
        "header_left": [
            (party_caption, _s(row.party_name)),
            ("对方税号", _s(row.party_tax_no)),
            ("账期", f"{_s(row.period_start) or '（起始）'} ~ {_s(row.period_end) or '（截止）'}"),
            ("制单日期", _s(row.statement_date) or _d(row.created_at)),
        ],
        "header_right": [
            ("款项方向", direction_label),
            ("单据状态", STATEMENT_STATUS.get(row.status, _s(row.status))),
            ("明细行数", str(row.item_count or len(items))),
            ("确认时间", _s(row.confirmed_at)[:16] if row.confirmed_at else ""),
        ],
        "columns": [
            {"label": "序号", "width": 34, "min_width": 28, "align": "c"},
            {"label": "业务日期", "width": 68, "min_width": 58, "align": "c"},
            {"label": "来源", "width": 48, "min_width": 40, "align": "c"},
            {"label": "合同编号", "width": 96, "min_width": 78, "align": "l"},
            {"label": "摘要", "width": 132, "align": "l", "shrink": True},
            {"label": "合同金额", "width": 72, "min_width": 62, "align": "r"},
            {"label": "已开票", "width": 68, "min_width": 58, "align": "r"},
            {"label": "未开票", "width": 68, "min_width": 58, "align": "r"},
            {"label": "已收/付", "width": 68, "min_width": 58, "align": "r"},
            {"label": "剩余未收/付", "width": 82, "min_width": 72, "align": "r"},
        ],
        "rows": rows,
        # 表下合计行放"应收/应付余额"——这是对方最关心的一个数
        "totals": {
            "label": "应收/应付余额",
            "chinese": f"大写：{amount_to_chinese(float(row.receivable_balance or 0))}",
            "amount": _money(row.receivable_balance),
        },
        "extra_rows": [
            ("未开票金额", _money(row.uninvoiced_amount)),
            ("剩余未收/付", _money(row.outstanding_amount)),
            ("预收/预付发生额", _money(row.prepaid_received)),
            ("预收/预付已核销", _money(row.prepaid_applied)),
            ("预收/预付余额", _money(row.prepaid_balance)),
        ],
        # 汇总块一行 5 格（再宽就挤成两三个字，反而看不清）
        "summary": [
            ("期初余额", _money(row.opening_balance)),
            ("本期合同额", _money(row.contract_amount)),
            ("本期已开票", _money(row.invoiced_amount)),
            ("本期已收/付", _money(row.received_amount)),
            ("应收/应付余额", _money(row.receivable_balance)),
        ],
        "notes": [
            "说明：未开票金额 = 合同金额 − 已开票；剩余未收/付 = max(0, 合同金额 − 已收/付 − 预收已核销)；"
            "应收/应付余额 = 期初余额 + 本期已开票 − 本期已收/付 − 预收已核销。",
            f"备注：{_s(row.note)}" if row.note else "",
            "如对上述往来无异议，请盖章确认回传；如有异议，请于 5 个工作日内与我司联系核对。",
        ],
        "signatures": ["制单", "审核", ("客户" if row.party_type == "customer" else "供应商") + "确认（盖章）"],
    }



# 对账单（已定稿的单据）登记进统一打印入口：
# 路径是 /print/statement-record/{id}，与旧的实时聚合 /print/statement/{party_type}/{party_id}
# 段数不同（2 段 vs 3 段），FastAPI 不会互相吃掉。
_PRINT_KINDS["statement-record"] = ("对账单（单据）", _statement_record_print_spec, {})



# ============================================================================
# 打印类型注册表对外出口（打印模板表靠它播种，见 app/models/print_template.py）
# ============================================================================
def printable_doc_types() -> list[tuple[str, str]]:
    """全部可控打印的单据类型：[(doc_type, 中文名), ...]，按业务顺序。

    这是**唯一**的打印类型清单。打印模板表在启动时按它播种，
    所以新增一张单据的打印就自动多一条模板记录，不需要在两处维护。
    `DOC_TYPE_ORDER` 只负责排序：出现未归类的类型会排到末尾，
    测试会断言"注册表里的类型必须都已归类"，避免有人加了打印却漏了归类。
    """
    kinds = [(key, str(entry[0])) for key, entry in _PRINT_KINDS.items()]
    return sort_doc_types(kinds + list(STANDALONE_DOC_TYPES))



def is_printable_doc_type(doc_type: str) -> bool:
    return doc_type in _PRINT_KINDS or doc_type in {key for key, _ in STANDALONE_DOC_TYPES}
