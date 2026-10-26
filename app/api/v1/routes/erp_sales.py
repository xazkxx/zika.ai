"""销售管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

销售开单 / 销售订单 / 报价单 / 购销合同 / 销售退货。
"""

from __future__ import annotations

from app.core.company_info import load_company
from app.services.contract_template import build_gongkuang_document
from app.core import file_storage
# 状态机唯一权威（白名单 + 合法流转）：改造前这里接受任意字符串，
# "只有审核通过才能转单"在代码里没有任何约束。见 app/core/doc_status.py 顶部说明。
from app.core.doc_status import assert_transition, is_approved, status_label
from app.db.session import get_db
from app.models.contract import (
    CONTRACT_DIRECTIONS,
    CONTRACT_OCR_STATUS,
    CONTRACT_STATUS,
    CONTRACT_TEMPLATES,
    CONTRACT_TYPES,
    Contract,
    ContractItem,
    normalize_contract_type,
    normalize_direction,
)
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.invoice import Invoice
from app.models.product import Product
from app.models.quotation import (
    QUOTATION_PAYMENT_METHODS,
    QUOTATION_STATUS,
    QUOTATION_TRANSPORT_METHODS,
    Quotation,
    QuotationItem,
)
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.sales_return import SALES_RETURN_STATUS, SalesReturn, SalesReturnItem
from app.models.supplier import Supplier
from app.schemas import (
    ContractCreate,
    ContractRead,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    QuotationCreate,
    QuotationRead,
    SalesOrderCreate,
    SalesOrderItemCreate,
    SalesOrderRead,
    SalesReturnCreate,
    SalesReturnRead,
)
from datetime import datetime
import base64
import mimetypes
from urllib.parse import quote
import re
import time
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _A2_DEFAULTS,
    _A2_DEFAULT_COPIES,
    _A2_DEFAULT_INSPECTION_DAYS,
    _A2_DEFAULT_OBJECTION_DAYS,
    _A2_DEFAULT_PENALTY_RATE,
    _apply_stock,
    _attachment_response,
    _contract_items,
    _clean_order_lines,
    _next_doc_no,
    _paginate,
    _prev_debt_total,
    _quotation_items,
    _resolve_item_snapshot,
    _resolve_unit_factor,
    _resolve_warehouse_id,
    _assert_no_payment_flows,
    _assert_source_order_no_payment,
    _revert_finance,
    _revert_stock,
    _s,
    _sales_return_items,
    _wants_json,
    _write_finance,
    amount_to_chinese,
    resolve_contract_document_payload,
)

router = APIRouter(prefix="", tags=["erp"])

# ===========================================================================
# 第 13 批：合同原件（PDF / Word / 图片）
# ===========================================================================
# 落盘子目录（相对 file_storage.storage_root()）。与商品图片的 `products/`
# 平级，打包后都在 exe 同目录的 data/ 下。
CONTRACT_FILE_SUBDIR = "contracts"

# 新建合同时"先传原件、后建单"的临时目录。
# 为什么需要它：识别接口原本要求合同已存在（按 contract_id 读原件），
# 但用户要的是"在新建弹窗里先识别、再填表"。于是原件先落在 tmp/，
# 识别直接读 tmp/ 里的文件；点「保存合同」时再把文件**搬**进 contracts/
# 正式目录并挂到新合同上 —— 没保存就关弹窗的，文件留在 tmp/ 由 24h 清理。
CONTRACT_DRAFT_SUBDIR = "contracts/tmp"
CONTRACT_DRAFT_TTL_HOURS = 24

# 临时文件名由后端生成（`save_bytes` 产出 `<12位hex>-draft.<真实后缀>`），
# 前端拿到的 token 就是它的相对路径。用白名单正则校验，杜绝 `../` 越界。
_DRAFT_TOKEN_RE = re.compile(
    r"^contracts/tmp/[0-9a-f]{12}-draft\.(pdf|docx|doc|png|jpg|jpeg|bmp|webp|tif|tiff)$"
)

# 允许的**真实**格式（按文件头判断，不认扩展名 —— 扩展名是调用方说了算的）。
# Word 两种：docx 是 zip（PK\x03\x04），doc 是老式 OLE 复合文档。
CONTRACT_FILE_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
)

# 文件头魔数 → 规范后缀。顺序有意义：PDF 的 `%PDF` 必须最先判，
# 否则一个以 "PK" 开头但其实是别的东西的文件会被当成 docx。
_FILE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".docx"),          # OOXML（docx/xlsx/pptx 同族，这里只当 word 收）
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".doc"),  # 老式 Word（OLE2）
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


def _as_int(value: object, field: str) -> int:
    """把前端传来的"看起来是数字"的东西转成 int，转不了就 400。

    前端 PATCH 走的是裸 dict（不是 schema），数字可能是字符串 `"3"`，
    直接 `int("abc")` 会抛 ValueError → 500。这里统一收口成 400 带字段名。
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} 必须是整数") from exc






# ===========================================================================
# 完结闸四字段（2026-10-22 恢复）
#
# 这两段代码曾经存在于 2026-10-20 的重构里，后来在 `*.bak-1020124407` 那份备份中，
# 主文件里**丢了**。表现极其隐蔽：
#   · 列表接口不返回 settled / uninvoiced_amount；
#   · 前端 `canComplete = Boolean(detailRow?.settled)` 恒为 false；
#   · 于是「标记为已完结」按钮永远是灰的，而且**没有任何报错** ——
#     用户只会觉得"这功能没做完"。
# 所以这里按原口径原样补回，并让前端继续只读后端算好的数（前端不许自己算）。
# ===========================================================================
def _invoiced_amounts_by_order(db: Session, order_ids) -> dict:
    """批量取「每张销售单已被销项发票开了多少票」（一次聚合，避免 N+1）。

    未挂单的发票（related_order_id 为空）不参与；金额取 `total_amount`（价税合计）。
    方向必须限定 output —— 否则一张误挂的进项票会把销售单的"已开票"抬上去。
    """
    ids = [int(i) for i in (order_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (
        db.query(Invoice.related_order_id, func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(
            Invoice.direction == "output",
            Invoice.related_order_id.in_(ids),
        )
        .group_by(Invoice.related_order_id)
        .all()
    )
    return {int(order_id): round(float(total or 0), 2) for order_id, total in rows}


def _apply_settlement_fields(payload: SalesOrderRead, invoiced=0.0) -> SalesOrderRead:
    """把「完结闸」四个字段按**唯一公式**补进出参。

        净额      = 应收金额(receivable_amount) − 优惠(discount_amount)
        应收余额  = 净额 − 已收(received_amount)
        未开票    = **总额** − 已开票      ← 与 `POST /status` 的 not_settled 闸逐字对齐
        可完结    = 应收余额 ≤ 0 且 未开票 ≤ 0

    ⚠️ 未开票这里刻意用 `total_amount`（不是净额）：服务端拦完结时算的就是
    `total_amount − 已开票`。两处差一个优惠额，就会出现"按钮亮了、点完结却被 409"。
    """
    receivable = float(payload.receivable_amount or 0) or float(payload.total_amount or 0)
    net = round(receivable - float(payload.discount_amount or 0), 2)
    outstanding = round(net - float(payload.received_amount or 0), 2)
    uninvoiced = round(max(0.0, float(payload.total_amount or 0) - float(invoiced or 0)), 2)
    payload.invoiced_amount = round(float(invoiced or 0), 2)
    payload.outstanding_amount = outstanding
    payload.uninvoiced_amount = uninvoiced
    payload.settled = outstanding <= 0.005 and uninvoiced <= 0.005
    return payload


def _build_sales_payload(item: SalesOrder, rows: list[SalesOrderItem], invoiced=0.0) -> SalesOrderRead:
    payload = SalesOrderRead(
        id=item.id,
        order_no=item.order_no,
        customer_id=item.customer_id,
        status=item.status,
        total_amount=item.total_amount,
        doc_type=item.doc_type or "outbound",
        source_order_id=item.source_order_id,
        created_at=item.created_at,
        warehouse_id=item.warehouse_id,
        # 手写映射**最容易漏字段**：加了 project_id 却没加在这里，
        # 结果是数据存进去了、接口却返回 None（前端显示不出单据属于哪个项目）
        project_id=item.project_id,
        businesser=item.businesser,
        order_date=item.order_date,
        delivery_date=item.delivery_date,
        payment_method=item.payment_method,
        contact=item.contact,
        contact_phone=item.contact_phone,
        address=item.address,
        note=item.note,
        logistics_company=item.logistics_company,
        logistics_no=item.logistics_no,
        signed_by=item.signed_by,
        signed_at=item.signed_at,
        discount_amount=item.discount_amount,
        received_amount=item.received_amount,
        is_invoiced=item.is_invoiced,
        receivable_amount=item.receivable_amount,
        current_debt=item.current_debt,
        prev_debt=item.prev_debt,
        total_debt=item.total_debt,
        items=[
            {
                "id": row.id,
                "sales_order_id": row.sales_order_id,
            # 3c 多单位换算快照。⚠️ 手写映射漏了它，Pydantic 会**静默填 1**，
            # 前端就永远看到 1（3b 在采购侧踩过同一个坑）。
            "unit_factor": row.unit_factor,
                "product_id": row.product_id,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "note": row.note,
            }
            for row in rows
        ],
    )
    # create/update 等调用方没传 invoiced 时默认 0 —— 新单一票未开，按 0 算是对的。
    return _apply_settlement_fields(payload, invoiced)



@router.get("/sales-orders")
def list_sales_orders(
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int | None = None,
    doc_type: str | None = None,
    customer_id: int | None = None,
) -> list[SalesOrderRead]:
    query = db.query(SalesOrder).order_by(SalesOrder.id.desc())
    # doc_type 过滤：order=销售订单页；outbound=开单管理页；不传=全量（兼容旧调用方）
    if doc_type:
        query = query.filter(SalesOrder.doc_type == doc_type)
    if customer_id:
        query = query.filter(SalesOrder.customer_id == customer_id)
    items = _paginate(query, skip, limit).all()
    invoiced_map = _invoiced_amounts_by_order(db, [item.id for item in items])
    result = []
    for item in items:
        order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == item.id).all()
        result.append(
            _build_sales_payload(item, order_items, invoiced=invoiced_map.get(int(item.id), 0.0))
        )
    return result



@router.post("/sales-orders", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED)
def create_sales_order(payload: SalesOrderCreate, db: Session = Depends(get_db)) -> SalesOrderRead:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    # 单据性质：order=销售订单（只订货）；outbound=销售开单（默认，真实出库+财务+库存）
    doc_type = (payload.doc_type or "outbound").strip()
    if doc_type not in ("order", "outbound"):
        raise HTTPException(status_code=400, detail="doc_type 仅支持 order / outbound")

    # 空行 / 半填行先过一遍：整行空白的部分静默丢弃，选了商品却没数量的直接 400。
    # 必须放在**取单号之前** —— 否则校验失败会白白消耗一个流水号。
    lines_in = _clean_order_lines(payload.items, "销售单")

    order_no = (payload.order_no or "").strip() or _next_doc_no(db, SalesOrder, "XSD" if doc_type == "order" else "XS")
    if db.query(SalesOrder).filter(SalesOrder.order_no == order_no).first():
        raise HTTPException(status_code=400, detail="销售开单号已存在")

    order_date = payload.order_date or datetime.now().strftime("%Y-%m-%d")

    # 注意：必须在插入本单之前取"前次欠款"，否则会把本单自己算成上一张单
    # 销售订单不产生欠款（还没出货结算），欠款链字段保持 0
    prev_debt = (
        round(_prev_debt_total(db, SalesOrder, SalesOrder.customer_id, payload.customer_id), 2)
        if doc_type == "outbound"
        else 0.0
    )

    # —— 3c：明细快照与换算率必须**在写单头之前**全部解析完 ——
    #    单头 `db.commit()` 之后才解析的话，任何一条 400 都会在库里留下一张
    #    「只有表头、没有明细」的孤儿单（3b 在采购侧踩过同一个坑）。
    #    快照与换算率各只算一遍，循环里按下标取，避免重复查库。
    snapshots = [_resolve_item_snapshot(db, line) for line in lines_in]
    unit_factors = [
        _resolve_unit_factor(db, line.product_id, snapshot[2])
        for line, snapshot in zip(lines_in, snapshots)
    ]

    item = SalesOrder(
        order_no=order_no,
        customer_id=payload.customer_id,
        status="draft",
        total_amount=0.0,
        doc_type=doc_type,
        warehouse_id=payload.warehouse_id,
        project_id=payload.project_id,
        businesser=payload.businesser or customer.businesser,
        order_date=order_date,
        delivery_date=payload.delivery_date,
        payment_method=payload.payment_method,
        contact=payload.contact or customer.contact,
        contact_phone=payload.contact_phone or customer.contact_phone or customer.phone,
        address=payload.address or customer.address,
        note=payload.note,
        logistics_company=payload.logistics_company,
        logistics_no=payload.logistics_no,
        signed_by=payload.signed_by,
        signed_at=payload.signed_at,
        is_invoiced=payload.is_invoiced,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[SalesOrderItem] = []
    for index, line in enumerate(lines_in):
        name, standards, unit = snapshots[index]
        row = SalesOrderItem(
            sales_order_id=item.id,
            product_id=line.product_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            amount=line.quantity * line.unit_price,
            product_name=name,
            standards=standards,
            unit=unit,
            # 3c 换算率快照：服务端从 unit 现场解析，绝不接受客户端传入
            unit_factor=unit_factors[index],
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    # 结算链：应收 → 优惠 → 实收
    # 实收金额不填 = 0，即本单全额挂账；之后由「收款登记」逐笔冲减。
    gross = round(total, 2)
    discount = round(float(payload.discount_amount or 0.0), 2)
    net = round(gross - discount, 2)
    received = round(float(payload.received_amount or 0.0), 2)

    # 欠款链：本次欠款 → 前次欠款 → 累欠货款
    current_debt = round(net - received, 2)

    item.total_amount = gross
    item.receivable_amount = gross
    item.discount_amount = discount
    item.received_amount = received
    item.current_debt = current_debt
    item.prev_debt = prev_debt
    item.total_debt = round(prev_debt + current_debt, 2)
    item.status = "submitted"

    # —— 销售订单（doc_type=order）：到此为止 ——
    # 订单只是"意向确认"，不动库存、不写财务、不产生欠款；
    # 真正的出库/结算由「转开单」或手工开销售单完成。
    if doc_type == "order":
        item.received_amount = 0.0
        item.current_debt = 0.0
        item.prev_debt = 0.0
        item.total_debt = 0.0
        db.commit()
        db.refresh(item)
        return _build_sales_payload(item, rows)

    # 财务联动：单据审核即产生应收，人工无需再录
    if gross > 0:
        _write_finance(
            db,
            transaction_type="receivable",
            direction="in",
            amount=gross,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            customer_id=payload.customer_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"销售开单 {item.order_no} 产生应收",
        )
    if received > 0:
        _write_finance(
            db,
            transaction_type="receipt",
            direction="in",
            amount=received,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            customer_id=payload.customer_id,
            warehouse_id=item.warehouse_id,
            project_id=item.project_id,
            occurred_at=order_date,
            note=f"销售开单 {item.order_no} 收款",
        )

    # 库存联动：销售出库即减少现存量，每条明细一条流水。
    # 库存不足不阻断开单（允许负库存），但现存量与预警会把它标出来。
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=row.quantity,
            transaction_type="outbound",
            unit_price=row.unit_price,
            related_type="sales_out",
            related_order_id=item.id,
            doc_no=item.order_no,
            # 3c：换算率交给 `_apply_stock` 统一做（数量 ×factor、单价 ÷factor），
            #     调用点**不要**自己再乘一遍 —— 那就是 100 倍的双重换算
            unit_factor=row.unit_factor,
            note=f"销售出库 {item.order_no}",
        )

    db.commit()
    db.refresh(item)
    return _build_sales_payload(item, rows)



@router.patch("/sales-orders/{order_id}/logistics", response_model=SalesOrderRead)
def update_sales_logistics(
    order_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> SalesOrderRead:
    """登记物流 + 签收（四流合一 · 物流流）。

    ## 为什么单独开一个接口，而不是复用"编辑单据"

    销售单目前**没有**通用的 PATCH（只有 `/status`）。为了补 4 个字段去开一个
    "任意字段都能改"的通用更新接口，等于把库存/金额/客户的写权限也一起放开 ——
    那些字段的改动必须走冲销/转单，不能顺手改。所以这里只认这 4 个键。

    ## 三条约束

    1. **只有出库单能签收**：`doc_type='order'` 是订货意向，货都没发，
       签收时间必然是无意义的假数据 → 400。
    2. **签收时间允许早于"现在"**（补录昨天的签收单是常态），但**不允许填未来时间** ——
       未来的签收时间是录入错误的强信号，且会让"已签收天数"变成负数。
    3. **传 null / 空串 = 清空该项**：签收单填错了要能撤回。
       `signed_at` 传空 = 这张单重新变回"未签收"。

    入参（都可选，只改传了的键）：
        {"logistics_company": "顺丰", "logistics_no": "SF123", 
         "signed_by": "张三", "signed_at": "2026-10-19T15:30"}
    """
    item = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="销售单不存在")
    if (item.doc_type or "outbound") != "outbound":
        raise HTTPException(
            status_code=400,
            detail=(
                f"{item.order_no} 是销售订单（只订货、不发货），不能登记签收。"
                "请对由它转出的销售出库单登记。"
            ),
        )

    def _text(key: str, limit: int) -> None:
        if key not in payload:
            return
        raw = payload.get(key)
        value = str(raw).strip() if raw is not None else ""
        if len(value) > limit:
            raise HTTPException(status_code=400, detail=f"{key} 最长 {limit} 个字符")
        setattr(item, key, value or None)

    _text("logistics_company", 100)
    _text("logistics_no", 100)
    _text("signed_by", 50)

    if "signed_at" in payload:
        raw = payload.get("signed_at")
        if raw in (None, ""):
            item.signed_at = None
        else:
            try:
                # 前端 <input type="datetime-local"> 给的是 "2026-10-19T15:30"，
                # 没有时区 —— `fromisoformat` 能直接吃（3.11+ 也吃 "Z" 结尾）。
                parsed = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="签收时间格式不对，应为 2026-10-19T15:30"
                ) from exc
            # 容忍 5 分钟时区/时钟误差，超过就算"未来时间"
            if parsed.timestamp() > datetime.now(parsed.tzinfo).timestamp() + 300:
                raise HTTPException(status_code=400, detail="签收时间不能晚于现在")
            item.signed_at = parsed

    db.commit()
    db.refresh(item)
    rows = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == item.id).all()
    return _build_sales_payload(item, rows)



@router.patch("/sales-orders/{order_id}/status")
def update_sales_order_status(order_id: int, payload: dict[str, object], db: Session = Depends(get_db)) -> SalesOrderRead:
    """改单据状态 —— **只能沿合法流转走**。

    改造前这里写的是 `str(payload.get("status") or "submitted")`，任何字符串都能落库
    （包括 `"approved "`、`"已审核"`、甚至 `"foo"`），于是"只有审核通过才能出库"
    在服务端没有半点约束。现在统一走 `app/core/doc_status.py`：

    · 未知状态码 → 400，detail 里列出这个 doc_type 允许的值
    · 非法流转   → 409，detail 里写清"当前是什么、能改成什么"
    · 同状态     → 幂等成功（前端双击不报错）
    """
    item = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Sales order not found")

    status_value = assert_transition(item.doc_type, item.status, payload.get("status"), item.order_no)

    # ── 完结闸（2026-10-20 上线，2026-10-21 恢复）──────────────────────────
    # 出库单转 completed 前必须「钱票两清」：还有欠款或还有未开票金额 → 409 not_settled。
    # 为什么必须拦在服务端：前端只是把按钮置灰，接口谁都能调；不拦就会出现
    # "单据已完结、钱还没收"的账，之后再也不能靠完结状态提醒催款。
    if status_value == "completed" and (item.doc_type or "outbound") == "outbound" and item.status != "completed":
        outstanding = round(float(item.current_debt or 0), 2)
        invoiced = round(
            float(
                db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
                .filter(Invoice.related_order_id == item.id)
                .scalar()
                or 0
            ),
            2,
        )
        total = round(float(item.total_amount or 0), 2)
        uninvoiced = round(max(0.0, total - invoiced), 2)
        if outstanding > 0.005 or uninvoiced > 0.005:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "not_settled",
                    "message": (
                        f"{item.order_no} 还不能完结：未收 ¥{outstanding:,.2f}、"
                        f"未开票 ¥{uninvoiced:,.2f}。请先登记收款并关联发票，再完结。"
                    ),
                    "hint": "钱票两清后才能完结；确实要结案请先做收款登记与开票。",
                    "outstanding_amount": outstanding,
                    "uninvoiced_amount": uninvoiced,
                },
            )

    if status_value != item.status:
        item.status = status_value
        db.commit()
        db.refresh(item)
    order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == item.id).all()
    return _build_sales_payload(item, order_items)



@router.delete("/sales-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_order(order_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Sales order not found")
    # 已转开单的订单不允许直接删（开单还引用着它），先删开单再回来删订单；
    # 用 source_order_id 反查比看 status 更准——开单删掉后订单自然就能删了
    if (
        item.doc_type == "order"
        and db.query(SalesOrder).filter(SalesOrder.source_order_id == order_id).first() is not None
    ):
        raise HTTPException(status_code=409, detail="该订单已转开单，请先删除对应的开单")
    # 已登记过收款/付款的单据禁止删除（2026-10-18）：这类流水是真实资金记录，
    # 删单不会连带冲销它们，只会把 related_order_id 变成指向空气的孤儿账。
    # 注意顺序：必须排在 _revert_stock / _revert_finance **之前**，否则先动了库存/应收再报错，
    # 请求虽然 500/409 了，session 里已经排队的删除仍可能在别处被 flush 出去。
    _assert_no_payment_flows(db, order_id, item.order_no or f"#{order_id}")
    # 删开单时，来源订单上也可能是收过款的（钱挂在订单上、不挂在开单上）。
    # 不拦的话：开单没了 → 订单停在 completed → 不能重新转单、又因收款不能删 = 死锁。
    if item.source_order_id:
        _assert_source_order_no_payment(db, db.get(SalesOrder, item.source_order_id), "销售开单")
    # 库存联动回滚：这张单产生的出库流水一并冲销，否则货扣了单没了，库存就再也对不上
    _revert_stock(db, "sales_out", order_id)
    # 财务联动回滚：只冲销"开单自己产生的"应收（related_type=sales_out）。
    # 收付款（related_type=receipt/payment）不在这里删 —— 上面那道闸口已经拦下了。
    _revert_finance(db, "sales_out", order_id)
    # 先删订单明细，再删订单本身，避免留下孤儿明细
    db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/sales-orders/{order_id}/to-outbound", response_model=SalesOrderRead)
def sales_order_to_outbound(order_id: int, db: Session = Depends(get_db)) -> SalesOrderRead:
    """销售订单 → 销售开单（一键转单）。

    生成一张新的开单（doc_type=outbound，写库存流水与应收财务流水），
    复制订单的头信息与明细；订单本身置 completed 并保留可追溯。

    ⚠️ **必须审核通过才允许转单**（2026-10-18 定的业务闸口）：
    改造前只挡 `completed`，等于"草稿能直接出货"——库存和应收都记了，
    但没有任何人确认过这张订单。历史 `submitted` 的订单同样拦下
    （`submitted` 在订单上归一为 `pending`），必须先点一次「审核」。
    """
    order = db.query(SalesOrder).filter(SalesOrder.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Sales order not found")
    if order.doc_type != "order":
        raise HTTPException(status_code=400, detail="只有销售订单才能转开单")
    if order.status == "completed":
        raise HTTPException(status_code=409, detail="该订单已转开单，不能重复转单")
    if not is_approved(order.doc_type, order.status):
        raise HTTPException(
            status_code=409,
            detail=f"订单 {order.order_no} 当前是「{status_label(order.status)}」，"
            "必须先审核通过（approved）才能转开单",
        )

    order_items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == order.id).all()
    payload = SalesOrderCreate(
        customer_id=order.customer_id,
        items=[
            SalesOrderItemCreate(
                product_id=row.product_id,
                quantity=row.quantity,
                unit_price=row.unit_price,
                product_name=row.product_name,
                standards=row.standards,
                unit=row.unit,
                note=row.note,
            )
            for row in order_items
        ],
        warehouse_id=order.warehouse_id,
        # 转单必须把项目一起带过去：订单上挂了项目、转出来的出库/入库单没挂，
        # 项目成本/收入就永远归集不到（闭环核查抓到的真实断点）
        project_id=order.project_id,
        businesser=order.businesser,
        order_date=order.order_date,
        delivery_date=order.delivery_date,
        payment_method=order.payment_method,
        contact=order.contact,
        contact_phone=order.contact_phone,
        address=order.address,
        note=order.note,
        discount_amount=order.discount_amount,
        received_amount=0.0,  # 结算在开单上另行登记，转单时不带收款
        is_invoiced=order.is_invoiced,
    )
    outbound = create_sales_order(payload, db)

    # 回填：开单回指来源订单，订单置 completed
    outbound_row = db.query(SalesOrder).filter(SalesOrder.id == outbound.id).first()
    outbound_row.source_order_id = order.id
    order.status = "completed"
    db.commit()
    db.refresh(outbound_row)
    order_items2 = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == outbound_row.id).all()
    return _build_sales_payload(outbound_row, order_items2)



def _quotation_payload(item: Quotation, rows: list[QuotationItem]) -> dict[str, object]:
    data = {column.name: getattr(item, column.name) for column in Quotation.__table__.columns}
    data["items"] = [
        {
            "id": row.id,
            "quotation_id": row.quotation_id,
            "product_id": row.product_id,
            "product_name": row.product_name,
            "standards": row.standards,
            "unit": row.unit,
            "quantity": row.quantity,
            "unit_price": row.unit_price,
            "amount": row.amount,
            "note": row.note,
        }
        for row in rows
    ]
    return data



def _payment_progress_map(db: Session, contract_ids: list[int]) -> dict[int, dict[str, object]]:
    """批量算「付款进度」，给合同列表加一列用。

    ⚠️ 必须一次 GROUP BY 全查出来：列表默认 100~200 行，逐行查付款计划就是 N+1
    （每行一次往返，列表会明显变慢）。
    """
    from app.models.contract_payment import ContractPaymentPlan

    if not contract_ids:
        return {}
    rows = (
        db.query(
            ContractPaymentPlan.contract_id,
            func.count(ContractPaymentPlan.id),
            func.coalesce(func.sum(ContractPaymentPlan.plan_amount), 0),
            func.coalesce(func.sum(ContractPaymentPlan.paid_amount), 0),
        )
        .filter(ContractPaymentPlan.contract_id.in_(contract_ids))
        .group_by(ContractPaymentPlan.contract_id)
        .all()
    )
    return {
        int(contract_id): {
            "payment_plan_count": int(count or 0),
            "payment_planned_amount": round(float(planned or 0), 2),
            "payment_paid_amount": round(float(paid or 0), 2),
        }
        for contract_id, count, planned, paid in rows
    }


def _with_payment_progress(payload: dict[str, object], progress: dict[str, object] | None) -> dict[str, object]:
    """把付款进度拼到合同 payload 上（列表与详情共用同一套字段名）。

    进度 = 已付 / 合同总额，夹在 0~100（超付不显示成 120%，但要保留真实缺口）；
    没有合同时长（总额 0）给 None，前端显示「—」而不是 0%。
    """
    total = float(payload.get("total_amount") or 0)
    data = progress or {}
    paid = float(data.get("payment_paid_amount") or 0)
    raw = round(paid / total * 100, 2) if total > 0 else None
    payload["payment_plan_count"] = int(data.get("payment_plan_count") or 0)
    payload["payment_planned_amount"] = float(data.get("payment_planned_amount") or 0)
    payload["payment_paid_amount"] = paid
    payload["payment_progress"] = None if raw is None else max(0.0, min(100.0, raw))
    payload["payment_progress_raw"] = raw
    payload["payment_shortfall"] = round(total - paid, 2)
    return payload


def _contract_payload(item: Contract, rows: list[ContractItem]) -> dict[str, object]:
    data = {column.name: getattr(item, column.name) for column in Contract.__table__.columns}
    data["items"] = [
        {
            "id": row.id,
            "contract_id": row.contract_id,
            "product_id": row.product_id,
            "product_name": row.product_name,
            "standards": row.standards,
            "unit": row.unit,
            "quantity": row.quantity,
            "unit_price": row.unit_price,
            "amount": row.amount,
            "note": row.note,
        }
        for row in rows
    ]
    return data



# ===========================================================================
# 新建合同的"智能优先"流程：无合同 ID 的临时上传 / 预识别
# ---------------------------------------------------------------------------
# 老流程：先保存合同 → 进详情 → 上传原件 → 识别 → 回填表单（等于建两次单）。
# 新流程：新建弹窗里直接上传 → 直接识别 → 按策略回填 → 点保存一次性落库。
#
# 三条约束（都是"宁可多一步"）：
#   ① 临时文件只落在 `contracts/tmp/`，24h 未保存自动清理；
#   ② token 必须是后端生成的相对路径（白名单正则），前端无法指定任意路径；
#   ③ 预识别**不落库**（没有合同记录可落），结果只回给前端；
#      保存时凭 `source_temp_token` 把文件搬进正式目录并写 ocr_json。
# ===========================================================================


def _draft_rel(token: object) -> str:
    """校验并返回临时文件的相对路径（token 就是后端给的 rel_path）。"""
    text = str(token or "").strip()
    if not _DRAFT_TOKEN_RE.match(text):
        raise HTTPException(status_code=400, detail="临时文件标识无效（请重新上传原件）")
    if not file_storage.exists(text):
        raise HTTPException(
            status_code=404,
            detail="临时文件已过期或不存在（超过 24 小时未保存会被清理），请重新上传原件",
        )
    return text


def _purge_stale_drafts() -> int:
    """顺手清掉超过 TTL 的临时文件。

    不引入定时任务：上传动作本身就是最自然的清理时机 —— 用这个功能的人
    一定会再上传，顺手把（自己或别人）遗留的垃圾带走。
    """
    root = file_storage.storage_root() / CONTRACT_DRAFT_SUBDIR
    if not root.is_dir():
        return 0
    cutoff = time.time() - CONTRACT_DRAFT_TTL_HOURS * 3600
    removed = 0
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _recognize_contract(raw_bytes: bytes, filename: str, direction: str):
    """识别 + 字段解析的**唯一**实现（详情页 `/ocr` 与新建草稿 `/ocr/recognize` 共用）。

    返回 `(result, fields_pack, raw_json, status_value)`：
    `result` 是引擎产物（lines / provider / engine / page_count），
    `fields_pack` 是候选字段（fields / party_candidates / items），
    `raw_json` 是原样存进 `ocr_json` 的整段 JSON，
    `status_value` 是 parsed / failed（认出文字就算 parsed）。
    """
    from app.services.contract_ocr import build_ocr_json, extract_text, parse_fields

    result = extract_text(raw_bytes, filename)
    fields_pack = parse_fields(result.get("lines") or [], direction=direction)
    status_value = "parsed" if (result.get("lines") or []) else "failed"
    raw_json = build_ocr_json(result, fields_pack, filename)
    return result, fields_pack, raw_json, status_value


def _ocr_result_payload(result: dict, fields_pack: dict, status_value: str) -> dict[str, object]:
    """两个识别接口共用的"结果长什么样"，避免两边字段名漂移。"""
    return {
        "ocr_status": status_value,
        "provider": result.get("provider"),
        "engine": result.get("engine"),
        "page_count": result.get("page_count"),
        "truncated": result.get("truncated"),
        "lines_count": len(result.get("lines") or []),
        "fields": fields_pack.get("fields") or {},
        "party_candidates": fields_pack.get("party_candidates") or [],
        "items": fields_pack.get("items") or [],
    }


@router.post("/contracts/ocr/upload", summary="新建合同时先上传原件（无需合同 ID）")
async def upload_contract_draft(file: UploadFile = File(...)) -> dict[str, object]:
    """把原件放进临时目录并返回 token；此时**还没有合同**。

    校验口径与 `/contracts/{id}/source` 完全一致（空文件 / 超限 / 按文件头嗅探格式），
    只是落盘位置不同 —— 用户在新建弹窗里选完文件就能识别，不用先造一条假合同。
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    if len(payload) > file_storage.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件 {len(payload) / 1024 / 1024:.1f}MB 超过 "
                f"{file_storage.MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限"
            ),
        )

    suffix = detect_contract_suffix(payload)
    if suffix is None:
        raise HTTPException(
            status_code=400,
            detail="认不出这个文件的格式（只支持 PDF / Word / 图片：png jpg bmp webp tif）",
        )

    original_name = (file.filename or f"contract{suffix}").strip() or f"contract{suffix}"
    try:
        rel_path = file_storage.save_bytes(payload, f"draft{suffix}", subdir=CONTRACT_DRAFT_SUBDIR)
    except ValueError as exc:  # 兜住 file_storage 自己的上限校验，别变成 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    removed = _purge_stale_drafts()
    return {
        "temp_token": rel_path,
        "file_name": original_name,
        "file_size": len(payload),
        "mime": mimetypes.guess_type(rel_path)[0] or "application/octet-stream",
        "expires_hours": CONTRACT_DRAFT_TTL_HOURS,
        "purged": removed,
        "message": "原件已暂存，可以点「开始识别」了",
    }


@router.post("/contracts/ocr/recognize", summary="无合同 ID 的预识别（新建流程）")
def recognize_contract_draft(payload: dict[str, object] | None = None) -> dict[str, object]:
    """对临时文件跑一次 OCR，**不落库**（没有合同记录可落）。

    `direction` 决定"对方单位"认哪个角色：销售（out）认甲方/需方/买方，
    采购（in）认乙方/供方/卖方。传错方向不会报错，只是对方单位可能为空 ——
    所有识别结果都只是候选，前端必须让人核对后再决定怎么填。
    """
    data = payload or {}
    rel_path = _draft_rel(data.get("temp_token"))
    direction = str(data.get("direction") or "out").strip().lower()
    if direction not in ("in", "out"):
        raise HTTPException(status_code=400, detail="direction 只能是 in（采购）或 out（销售）")

    raw_bytes = file_storage.read_bytes(rel_path)
    if not raw_bytes:
        raise HTTPException(status_code=404, detail="临时文件读取失败，请重新上传原件")

    filename = str(data.get("file_name") or Path(rel_path).name)
    try:
        result, fields_pack, raw_json, status_value = _recognize_contract(
            raw_bytes, filename, direction
        )
    except ValueError as exc:
        # 用户传了 Word 之类：这是"不该识别"，不是"识别失败"
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # 引擎崩了：文件还在，可以让用户重试
        raise HTTPException(status_code=502, detail=f"识别引擎异常：{exc}") from exc

    return {
        "temp_token": rel_path,
        "ocr_json": raw_json[:200_000],
        **_ocr_result_payload(result, fields_pack, status_value),
        "message": (
            "识别完成，请核对后选择填充方式"
            if status_value == "parsed"
            else "没有认出任何文字（原件可能是空白扫描件或图片太模糊），请换一份更清晰的原件"
        ),
    }


@router.delete("/contracts/ocr/upload", summary="丢弃新建流程里暂存的原件")
def delete_contract_draft(
    token: str = Query(..., description="上传接口返回的 temp_token"),
) -> dict[str, object]:
    """用户换文件 / 关弹窗时清掉临时文件（删不掉不算错）。"""
    text = str(token or "").strip()
    if not _DRAFT_TOKEN_RE.match(text):
        # 校验不过就当"没有这个文件"，不泄露目录结构
        return {"removed": False, "message": "临时文件不存在"}
    removed = file_storage.delete_file(text)
    return {"removed": removed, "message": "已丢弃" if removed else "临时文件已不存在"}


@router.get("/contracts/meta")
def contract_meta() -> dict[str, object]:
    """合同页面的字典：模板版本 / 合同类型 / 方向 / 状态 / OCR 状态 / 条款默认值。"""
    return {
        "templates": [{"code": code, "label": label} for code, label in CONTRACT_TEMPLATES.items()],
        "types": [{"code": code, "label": label} for code, label in CONTRACT_TYPES.items()],
        # 第 13 批：双向合同。direction 是**权威字段**，types 保留给老前端。
        "directions": [
            {"code": code, "label": label} for code, label in CONTRACT_DIRECTIONS.items()
        ],
        "ocr_statuses": [
            {"code": code, "label": label} for code, label in CONTRACT_OCR_STATUS.items()
        ],
        "statuses": [{"code": code, "label": label} for code, label in CONTRACT_STATUS.items()],
        "defaults": dict(_A2_DEFAULTS),
        "default_own": load_company(),
        "inspection_days": _A2_DEFAULT_INSPECTION_DAYS,
        "objection_days": _A2_DEFAULT_OBJECTION_DAYS,
        "penalty_rate": _A2_DEFAULT_PENALTY_RATE,
        "copies": _A2_DEFAULT_COPIES,
        # 原件上传的约束，前端 `accept` 与提示文案直接用这里，避免两处各写一份
        "file": {
            "max_bytes": file_storage.MAX_UPLOAD_BYTES,
            "accept": list(CONTRACT_FILE_SUFFIXES),
            "accept_attr": ",".join(CONTRACT_FILE_SUFFIXES),
        },
    }



@router.get("/contracts")
def list_contracts(
    db: Session = Depends(get_db),
    contract_type: str | None = Query(None),
    direction: str | None = Query(None, description="in 采购 / out 销售；不给则全部"),
    status_value: str | None = Query(None, alias="status"),
    party_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[ContractRead]:
    query = db.query(Contract).order_by(Contract.id.desc())
    if contract_type:
        query = query.filter(Contract.contract_type == contract_type)
    if direction:
        # direction 优先；同时把老数据里 contract_type 与之等价的行一起捞出来 ——
        # 补列后老行的 direction 由 DEFAULT/回填保证一致，这里只是双保险，
        # 避免"某一行 direction 是空的"让它在按方向筛选时凭空消失。
        wanted = normalize_direction(direction=direction)
        query = query.filter(
            or_(
                Contract.direction == wanted,
                Contract.contract_type == normalize_contract_type(direction=wanted),
            )
        )
    if status_value:
        query = query.filter(Contract.status == status_value)
    if party_id:
        query = query.filter(Contract.party_id == party_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Contract.contract_no.ilike(like),
                Contract.title.ilike(like),
                Contract.party_name.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    progress_map = _payment_progress_map(db, [int(item.id) for item in items])
    return [
        _with_payment_progress(
            _contract_payload(item, _contract_items(db, item.id)),
            progress_map.get(int(item.id)),
        )
        for item in items
    ]



@router.get("/contracts/{contract_id}", response_model=ContractRead)
def get_contract(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    payload = _contract_payload(item, _contract_items(db, item.id))
    return _with_payment_progress(payload, _payment_progress_map(db, [int(item.id)]).get(int(item.id)))



@router.post("/contracts/document/preview", summary="按内置范本生成正文（不落库）")
def preview_contract_document(payload: dict, db: Session = Depends(get_db)) -> dict[str, object]:
    """把「新增购销合同」表单里的数据填进内置范本，返回结构化正文给前端预览。

    内置范本有两个变体（`contract_template.TEMPLATE_NAMES`）：
      · `simple`（默认）《产品买卖合同（简易版）》，措辞对齐客户实际在用的那份；
      · `detail`《工矿产品购销合同》，条款更细，老合同沿用。
    传 `{"template": "detail"}` 可切换。

    三个刻意的取舍：
      · **不写库**：用户常常只是"填完想看看正文长什么样"，看一眼就占一个合同号是浪费；
      · **不要求先保存**：表单里没填的项按行业常规兜底（见 `contract_template.DEFAULTS`），
        正文永远是一份能直接拿去谈的完整文本；
      · 已保存的合同也能看：传 `{"contract_id": N}` 就从库里取（前端详情页以后可直接复用）。
    """
    contract_id = payload.get("contract_id")
    if contract_id not in (None, ""):
        try:
            contract_id = int(contract_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="contract_id 必须是整数") from exc
        item = db.get(Contract, contract_id)
        if item is None:
            raise HTTPException(status_code=404, detail="合同不存在")
        rows = (
            db.query(ContractItem)
            .filter(ContractItem.contract_id == contract_id)
            .order_by(ContractItem.id)
            .all()
        )
        data = {
            **{field: getattr(item, field, None) for field in (
                "direction", "title", "contract_no", "sign_date", "sign_place",
                "party_name", "party_tax_no", "party_legal_person", "party_address",
                "party_contact", "party_phone", "party_bank_name", "party_bank_account",
                "own_name", "own_tax_no", "own_legal_person", "own_address",
                "own_contact", "own_phone", "own_bank_name", "own_bank_account",
                "tax_rate", "is_tax_included", "payment_terms", "invoice_requirement",
                "quality_standard", "package_standard", "delivery_date", "delivery_place",
                "delivery_method", "freight_bearer", "inspection_days", "objection_days",
                "penalty_rate", "dispute_resolution", "copies",
            )},
            "items": [
                {
                    "product_name": row.product_name,
                    "standards": row.standards,
                    "unit": row.unit,
                    "quantity": float(row.quantity or 0),
                    "unit_price": float(row.unit_price or 0),
                    "amount": float(row.amount or 0),
                    "note": row.note,
                }
                for row in rows
            ],
        }
    else:
        data = payload

    data = resolve_contract_document_payload(db, data)
    document = build_gongkuang_document(data, data.get("items") or [])
    return {
        "document": document,
        # 补全后的 payload 原样带回去：前端把它整份打给 /print/contract-document/pdf，
        # 导出的就是刚才预览的那一份（各算一遍迟早会不一样）。
        "payload": data,
        "message": f"已按《{document['template_name']}》范本生成正文（{len(document['clauses'])} 条，{len(document['items'])} 项标的物）",
    }


@router.post("/contracts", response_model=ContractRead, status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.contract_type not in CONTRACT_TYPES:
        raise HTTPException(status_code=400, detail="contract_type 只能是 sales 或 purchase")

    contract_no = (payload.contract_no or "").strip() or _next_doc_no(db, Contract, "HT", field="contract_no")
    if db.query(Contract).filter(Contract.contract_no == contract_no).first():
        raise HTTPException(status_code=400, detail="合同编号已存在")

    # 对方单位：能从档案带出的自动带出，其余留白由用户填
    # 第 13 批：方向决定对方单位类型 —— out（销售）对客户，in（采购）对供应商。
    # Schema 已经把 direction 与 contract_type 对齐，这里只需要校验 party_type 没被写反。
    expected_party_type = "customer" if payload.direction == "out" else "supplier"
    if payload.party_type and payload.party_type != expected_party_type:
        raise HTTPException(
            status_code=400,
            detail=(
                "销售合同（direction=out）的对方单位必须是客户，"
                "采购合同（direction=in）的对方单位必须是供应商"
            ),
        )
    party_type = payload.party_type or expected_party_type
    party = None
    if payload.party_id:
        model = Customer if party_type == "customer" else Supplier
        party = db.get(model, payload.party_id)
        if party is None:
            raise HTTPException(status_code=404, detail="对方单位档案不存在")

    # 选了模板就必须真实存在：否则库里留下一个指向空的 template_id，
    # 以后「下载完整合同」会静默退化成"只有正文"，没人知道模板其实没挂上。
    if payload.template_id:
        from app.models.contract_template import ContractTemplate

        if db.get(ContractTemplate, int(payload.template_id)) is None:
            raise HTTPException(status_code=404, detail="所选合同模板不存在（可能已被删除）")

    # ⚠️ 客户端的 source_file_path 一律**不信**：那是服务器上的相对路径，
    # 允许它直接写，等于给了"把合同原件指向任意文件"的后门。
    # 原件的唯一入口是 source_temp_token（后端生成 → 白名单校验 → 后端搬文件）。
    data: dict[str, object] = payload.model_dump(
        exclude={
            "items",
            "status",
            "source_temp_token",
            "source_file_path",
            "source_file_name",
            "source_file_size",
            "source_file_mime",
        }
    )
    data["contract_no"] = contract_no
    data["contract_type"] = payload.contract_type
    data["party_type"] = party_type
    data["status"] = payload.status or "draft"
    data["title"] = (payload.title or "").strip() or CONTRACT_TYPES[payload.contract_type]
    data["sign_date"] = payload.sign_date or datetime.now().strftime("%Y-%m-%d")

    if party is not None:
        data["party_name"] = payload.party_name or party.name
        data["party_address"] = payload.party_address or getattr(party, "address", None)
        data["party_bank_name"] = payload.party_bank_name or getattr(party, "bank_name", None)
        data["party_bank_account"] = payload.party_bank_account or getattr(party, "bank_account", None)
        data["party_tax_no"] = payload.party_tax_no or getattr(party, "tax_no", None)
        # 抬头电话优先取**开票电话**（2026-10-23）：合同落款/抬头与开票信息保持一致，
        # 财务留的座机比业务手机更该出现在合同上；没填才退回联系人电话/手机。
        if party_type == "customer":
            data["party_contact"] = payload.party_contact or party.contact
            data["party_phone"] = (
                payload.party_phone
                or getattr(party, "invoice_phone", None)
                or party.contact_phone
                or party.phone
            )
        else:
            data["party_contact"] = payload.party_contact or party.main_contact or party.contact
            data["party_phone"] = (
                payload.party_phone
                or getattr(party, "invoice_phone", None)
                or party.mobile
                or party.phone
            )

    # 我方主体 / 条款变量：没填的用默认值兜底，保证打印出来是完整合同
    for key, value in {**load_company(), **_A2_DEFAULTS}.items():
        if not data.get(key):
            data[key] = value
    if not data.get("inspection_days"):
        data["inspection_days"] = _A2_DEFAULT_INSPECTION_DAYS
    if not data.get("objection_days"):
        data["objection_days"] = _A2_DEFAULT_OBJECTION_DAYS
    if not data.get("penalty_rate"):
        data["penalty_rate"] = _A2_DEFAULT_PENALTY_RATE
    if not data.get("copies"):
        data["copies"] = _A2_DEFAULT_COPIES

    # 新建流程的临时原件：搬进正式目录，与合同一起落库。
    # 搬完立刻删临时文件 —— 它已经"转正"了，留着只会被 24h 清理当成垃圾。
    draft_saved_rel: str | None = None
    if payload.source_temp_token:
        tmp_rel = _draft_rel(payload.source_temp_token)
        raw = file_storage.read_bytes(tmp_rel)
        if not raw:
            raise HTTPException(status_code=404, detail="临时原件已失效，请重新上传原件")
        origin_name = (payload.source_file_name or "").strip() or f"draft{Path(tmp_rel).suffix}"
        try:
            draft_saved_rel = file_storage.save_bytes(
                raw, origin_name, subdir=CONTRACT_FILE_SUBDIR
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        data["source_file_path"] = draft_saved_rel
        data["source_file_name"] = origin_name
        data["source_file_size"] = len(raw)
        data["source_file_mime"] = (
            mimetypes.guess_type(draft_saved_rel)[0] or "application/octet-stream"
        )
        file_storage.delete_file(tmp_rel)

    item = Contract(**data)
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except Exception:
        # 合同没建成，刚搬进正式目录的原件就是孤儿 → 一并清掉
        if draft_saved_rel:
            file_storage.delete_file(draft_saved_rel)
        raise

    total = 0.0
    rows: list[ContractItem] = []
    for line in payload.items:
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = ContractItem(
            contract_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    item.total_amount = round(total, 2)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)
    return _contract_payload(item, rows)



@router.patch("/contracts/{contract_id}", response_model=ContractRead)
def update_contract(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")

    text_fields = [
        "title", "party_name", "party_tax_no", "party_legal_person", "party_address",
        "party_contact", "party_phone", "party_bank_name", "party_bank_account",
        "own_name", "own_tax_no", "own_legal_person", "own_address", "own_contact",
        "own_phone", "own_bank_name", "own_bank_account",
        "sign_date", "sign_place", "valid_from", "valid_to",
        "payment_terms", "invoice_requirement", "quality_standard", "package_standard",
        "delivery_date", "delivery_place", "delivery_method", "freight_bearer",
        "warranty_terms", "dispute_resolution", "service_address", "other_terms", "note",
    ]
    number_fields = ["tax_rate", "penalty_rate", "inspection_days", "objection_days", "copies", "warehouse_id"]

    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    for field in number_fields:
        if field in payload:
            raw = payload.get(field)
            if raw in ("", None):
                setattr(item, field, None)
            else:
                try:
                    setattr(item, field, float(raw) if field in ("tax_rate", "penalty_rate") else int(raw))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=f"{field} 取值非法") from exc
    if "is_tax_included" in payload:
        item.is_tax_included = bool(payload.get("is_tax_included"))
    if payload.get("status"):
        if str(payload["status"]) not in CONTRACT_STATUS:
            raise HTTPException(status_code=400, detail="合同状态非法")
        item.status = str(payload["status"])

    rows = _contract_items(db, item.id)
    # 传了明细就整单替换（合同明细是标的物清单，逐行改容易改乱）
    if isinstance(payload.get("items"), list):
        db.query(ContractItem).filter(ContractItem.contract_id == item.id).delete()
        rows = []
        total = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = ContractItem(
                contract_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)

    db.commit()
    db.refresh(item)
    return _contract_payload(item, rows)



@router.patch("/contracts/{contract_id}/status", response_model=ContractRead)
def update_contract_status(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in CONTRACT_STATUS:
        raise HTTPException(status_code=400, detail="合同状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _contract_payload(item, _contract_items(db, item.id))



@router.get("/contracts/{contract_id}/references")
def contract_references(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """删除前的引用检查：已转单的合同不能直接删，否则单据溯源断链。"""
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    refs: list[dict[str, object]] = []
    if item.order_id:
        refs.append({
            "type": "order",
            "label": f"已生成{'销售开单' if item.contract_type == 'sales' else '采购入库单'}",
            "doc_no": _s(item.order_no),
            "count": 1,
        })
    return {"contract_id": contract_id, "contract_no": item.contract_no, "references": refs}



@router.get("/contracts/{contract_id}/full-contract", summary="下载/打印完整合同（正文 + 模板原件）")
def download_full_contract(contract_id: int, db: Session = Depends(get_db)) -> Response:
    """把"系统填好的正文"和"用户上传的模板"打包成一份完整合同。

    三种模板各走一条路（见 `services/contract_package`）：
      · Word → 变量替换后返回 .docx（用户还能继续在 Word 里改）；
      · PDF  → 模板页追加在正文之后，返回合并后的 PDF；
      · 图片 → 追加一页 A4，返回 PDF。
    没选模板 → 直接返回按《工矿产品购销合同》范本生成的 PDF。

    ⚠️ 这里**不写库、不改合同**：下载/打印是只读动作。
       模板被删了也照样能出正文 PDF（历史合同不能因为模板清理就打不开）。
    """
    from app.models.contract_template import ContractTemplate
    from app.services import contract_package

    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    rows = (
        db.query(ContractItem)
        .filter(ContractItem.contract_id == contract_id)
        .order_by(ContractItem.id)
        .all()
    )

    template = (
        db.get(ContractTemplate, int(item.template_id))
        if getattr(item, "template_id", None)
        else None
    )
    template_bytes = file_storage.read_bytes(template.file_path) if template else None

    # Word 模板：直接产 .docx（变量替换），不转 PDF —— 转了就改不动了
    if template is not None and template_bytes and contract_package.is_word(template.file_name):
        document = contract_package.build_document(item, rows)
        filled, replaced = contract_package.fill_docx_template(template_bytes, document)
        filename = f"{item.contract_no or 'contract'}_完整合同.docx"
        # ⚠️ 响应头是 latin-1 编码的，中文必须百分号编码（RFC 5987），否则 500
        encoded_name = quote(filename)
        return Response(
            content=filled,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
                # 让前端能告知"替换到几个变量"，避免用户以为模板没生效
                "X-Template-Vars-Replaced": str(replaced),
            },
        )

    # 其余情况：先出正文 PDF，再按模板类型合成
    body = contract_package.render_body_pdf(item, rows)
    if template is not None and template_bytes:
        try:
            if (template.mime_type or "") == "application/pdf":
                body = contract_package.merge_pdf_after(body, template_bytes)
            elif (template.mime_type or "").startswith("image/"):
                body = contract_package.append_image_page(body, template_bytes)
        except Exception as exc:  # noqa: BLE001 —— 模板坏了不能连正文都下载不了
            raise HTTPException(
                status_code=422,
                detail=f"模板合成失败（{type(exc).__name__}），请检查模板文件是否损坏，或先下载正文 PDF",
            ) from exc

    filename = f"{item.contract_no or 'contract'}_完整合同.pdf"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.delete("/contracts/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(
    contract_id: int, force: bool = Query(False), db: Session = Depends(get_db)
) -> Response:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    if item.order_id and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"合同 {item.contract_no} 已生成单据 {item.order_no}，删除会断开单据溯源",
                "references": [{"type": "order", "doc_no": item.order_no}],
                "hint": "如需保留单据，请改为把合同状态置为「已作废」；确要删除可加 force=true",
            },
        )
    # 原件也一起清掉：记录删了、文件还留在 data/contracts 里，只会越攒越多，
    # 而且以后谁也说不清"这份 PDF 是哪张合同的"（文件名只有 uuid 前缀）。
    file_storage.delete_file(item.source_file_path)
    db.query(ContractItem).filter(ContractItem.contract_id == contract_id).delete()

    # 付款计划也要一起清（2026-10-23）：不级联删的话，库里会攒下一堆
    # "合同都不存在了、计划还挂着"的孤儿行 —— 三单匹配按合同聚合时会被它们带偏，
    # 回单文件也会永远留在 data/contract_receipts 里没人认领。
    from app.models.contract_payment import ContractPaymentPlan

    plans = (
        db.query(ContractPaymentPlan)
        .filter(ContractPaymentPlan.contract_id == contract_id)
        .all()
    )
    for plan in plans:
        file_storage.delete_file(plan.receipt_path)
        db.delete(plan)
    db.flush()

    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/contracts/{contract_id}/to-order")
def contract_to_order(
    contract_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """一键转单：销售合同 → 销售开单；采购合同 → 采购入库单。

    这是合同与财务 / 库存的**唯一**连接点 —— 合同本身不入账，
    转成单据后由单据产生应收应付并联动库存。
    """
    from app.api.v1.routes.erp_purchase import create_purchase_order
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    if item.order_id:
        raise HTTPException(status_code=409, detail=f"该合同已生成单据 {item.order_no}，不能重复转单")
    if item.status == "void":
        raise HTTPException(status_code=400, detail="已作废的合同不能转单")

    rows = _contract_items(db, item.id)
    if not rows:
        raise HTTPException(status_code=400, detail="合同没有明细，无法转单")
    if not item.party_id:
        raise HTTPException(status_code=400, detail="合同未关联客户 / 供应商档案，无法转单")

    payload = payload or {}
    note = f"由合同 {item.contract_no} 生成"
    if item.contract_type == "sales":
        order_payload = SalesOrderCreate(
            customer_id=item.party_id,
            items=[
                SalesOrderItemCreate(
                    product_id=row.product_id or 0,
                    quantity=int(row.quantity or 0),
                    unit_price=float(row.unit_price or 0.0),
                    product_name=row.product_name,
                    standards=row.standards,
                    unit=row.unit,
                    note=row.note,
                )
                for row in rows
            ],
            warehouse_id=item.warehouse_id,
            order_date=item.sign_date,
            delivery_date=item.delivery_date,
            contact=item.party_contact,
            contact_phone=item.party_phone,
            address=item.party_address,
            note=note,
        )
        order = create_sales_order(order_payload, db)
        order_type, order_label = "sales_order", "销售开单"
    else:
        order_payload = PurchaseOrderCreate(
            supplier_id=item.party_id,
            items=[
                PurchaseOrderItemCreate(
                    product_id=row.product_id or 0,
                    quantity=int(row.quantity or 0),
                    unit_price=float(row.unit_price or 0.0),
                    product_name=row.product_name,
                    standards=row.standards,
                    unit=row.unit,
                    note=row.note,
                )
                for row in rows
            ],
            warehouse_id=item.warehouse_id,
            order_date=item.sign_date,
            delivery_date=item.delivery_date,
            contact=item.party_contact,
            contact_phone=item.party_phone,
            address=item.party_address,
            note=note,
        )
        order = create_purchase_order(order_payload, db)
        order_type, order_label = "purchase_order", "采购入库单"

    item.order_id = order.id
    item.order_no = order.order_no
    if item.status in ("draft", "signed"):
        item.status = "executing"
    db.commit()
    db.refresh(item)

    return {
        "contract_id": item.id,
        "contract_no": item.contract_no,
        "order_type": order_type,
        "order_label": order_label,
        "order_id": order.id,
        "order_no": order.order_no,
        "order_amount": float(order.total_amount or 0.0),
        "message": f"已按合同 {item.contract_no} 生成{order_label} {order.order_no}",
    }



# —————————————————————— 合同原件上传 / 下载 / OCR 回写 ——————————————————————


def detect_contract_suffix(payload: bytes) -> str | None:
    """按**文件头**认出真实格式，返回规范后缀；认不出就返回 None。

    只信字节不信扩展名：把 `某木马.exe` 改名成 `合同.pdf` 传上来，
    存成 .pdf 不致命（本系统从不执行它），但"下载回来打不开"会让用户以为系统坏了。
    认不出就直接拒绝，并告诉他支持哪几种。
    """
    if not payload:
        return None
    for magic, suffix in _FILE_SIGNATURES:
        if payload.startswith(magic):
            return suffix
    # RIFF....WEBP / BMP 的魔数太短，单独判
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith(b"BM") and payload[6:8] == b"\x00\x00":
        return ".bmp"
    # TIFF 两种字节序
    if payload[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    return None


def _contract_or_404(db: Session, contract_id: int) -> Contract:
    item = db.get(Contract, contract_id)
    if item is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return item


@router.post("/contracts/{contract_id}/source", summary="上传合同原件")
async def upload_contract_source(
    contract_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """把合同原件（扫描件 PDF / Word / 照片）挂到合同上，**替换**原来那份。

    ⚠️ 先落新文件、后删旧文件：反过来的话，新文件写失败（磁盘满、权限）
    就会连唯一一份原件都没了。宁可短时间多占一份空间。
    """
    item = _contract_or_404(db, contract_id)

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    if len(payload) > file_storage.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件 {len(payload) / 1024 / 1024:.1f}MB 超过 "
                f"{file_storage.MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限"
            ),
        )

    suffix = detect_contract_suffix(payload)
    if suffix is None:
        raise HTTPException(
            status_code=400,
            detail="认不出这个文件的格式（只支持 PDF / Word / 图片：png jpg bmp webp tif）",
        )

    # 落盘名用**嗅探出的**后缀；用户原名单独存进 source_file_name，下载时还原
    original_name = (file.filename or f"contract{suffix}").strip() or f"contract{suffix}"
    stem = Path(file_storage.safe_filename(original_name)).stem or "contract"
    try:
        rel_path = file_storage.save_bytes(
            payload, f"{stem}{suffix}", subdir=CONTRACT_FILE_SUBDIR
        )
    except ValueError as exc:  # 兜住 file_storage 自己的上限校验，别变成 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    old_path = item.source_file_path
    item.source_file_path = rel_path
    item.source_file_name = original_name
    item.source_file_size = len(payload)
    item.source_file_mime = mimetypes.guess_type(rel_path)[0] or "application/octet-stream"
    db.commit()
    db.refresh(item)

    if old_path and old_path != rel_path:
        file_storage.delete_file(old_path)

    return {
        "contract_id": item.id,
        "contract_no": item.contract_no,
        "source_file_path": item.source_file_path,
        "source_file_name": item.source_file_name,
        "source_file_size": item.source_file_size,
        "source_file_mime": item.source_file_mime,
        "replaced": bool(old_path and old_path != rel_path),
        "message": "合同原件已上传",
    }


@router.get("/contracts/{contract_id}/source", summary="下载合同原件")
def download_contract_source(
    contract_id: int, request: Request, db: Session = Depends(get_db)
) -> Response:
    """下载合同原件。

    默认走**二进制附件**（这是给"点一下就下载"用的，不是给 `fetch` 用的）；
    `Accept: application/json` 时改走 base64 JSON —— 与发票原件下载同一套约定，
    原因见 `erp_invoice.download_invoice_file`：`application/pdf` 会被浏览器内置
    阅读器接管，前端 `fetch` 会拿到空响应并存下 0 字节文件。
    """
    item = _contract_or_404(db, contract_id)
    if not item.source_file_path:
        raise HTTPException(
            status_code=404,
            detail="这份合同没有上传原件（可以点「上传原件」补一份 PDF / Word / 照片）",
        )
    payload = file_storage.read_bytes(item.source_file_path)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"原件文件已丢失（记录里的路径是 {item.source_file_path}），请重新上传",
        )

    filename = item.source_file_name or f"{item.contract_no}{Path(item.source_file_path).suffix}"
    media = item.source_file_mime or "application/octet-stream"
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": media,
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "size": len(payload),
            }
        )
    return _attachment_response(payload, filename, media)


@router.delete("/contracts/{contract_id}/source", summary="删除合同原件")
def delete_contract_source(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """只删原件、不删合同。合同本身还在，只是回到"没有扫描件"的状态。"""
    item = _contract_or_404(db, contract_id)
    path = item.source_file_path
    if not path:
        raise HTTPException(status_code=404, detail="这份合同没有上传原件")
    item.source_file_path = None
    item.source_file_name = None
    item.source_file_size = None
    item.source_file_mime = None
    db.commit()
    removed = file_storage.delete_file(path)
    return {
        "contract_id": item.id,
        # 键名与客户文件归档那条删除接口保持一致（`file_removed`），
        # 前端处理"文件没删掉"的提示可以共用一份代码。
        "file_removed": removed,
        "message": "原件已删除" + ("" if removed else "（磁盘上的文件已不存在，记录已清空）"),
    }


def _save_contract_ocr(db: Session, item: Contract, raw: str, status_value: str) -> None:
    """OCR 结果落库的**唯一**入口（run / write-back 两条路都走它）。

    ⚠️ 这里只存不解析：`ocr_json` 存引擎吐出的整段 JSON（字符串），不做结构化 ——
    识别一定有错，人工核对时要能看到"当时到底认成了什么"，
    只存清洗后的字段就永远说不清某一分钱是怎么来的；
    也不改合同的任何业务字段 —— 核对是人的动作，见 `/ocr/review`。
    """
    item.ocr_json = raw
    item.ocr_status = status_value
    db.commit()
    db.refresh(item)


@router.patch("/contracts/{contract_id}/ocr", summary="回写 OCR 识别结果")
def write_contract_ocr(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """把 OCR 引擎的**原始输出**原样存下来，并把状态推进到 `parsed` / `failed`。

    入参：`{"ocr_json": "<json 字符串>", "ocr_status": "parsed|failed", "message": "..."}`
    `ocr_status` 只允许 parsed / failed / pending（不允许直接置 reviewed，
    那是必须走人工核对接口的状态）。
    """
    item = _contract_or_404(db, contract_id)

    raw = payload.get("ocr_json")
    if raw is None:
        raise HTTPException(status_code=400, detail="缺少 ocr_json")
    if not isinstance(raw, str):
        # 允许前端直接传对象，这里统一转成字符串存 —— 库里的列是 Text
        import json as _json

        raw = _json.dumps(raw, ensure_ascii=False)
    if len(raw) > 200_000:
        raise HTTPException(status_code=400, detail="OCR 结果过大（超过 200KB），请检查是否传错了字段")

    status_value = str(payload.get("ocr_status") or "parsed").strip().lower()
    if status_value not in ("pending", "parsed", "failed"):
        raise HTTPException(
            status_code=400,
            detail="ocr_status 只能是 pending / parsed / failed（reviewed 请走 /ocr/review）",
        )

    _save_contract_ocr(db, item, raw, status_value)
    return {
        "contract_id": item.id,
        "ocr_status": item.ocr_status,
        "ocr_json_size": len(raw),
        "message": "OCR 结果已保存，请人工核对",
    }


@router.post("/contracts/{contract_id}/ocr", summary="对合同原件执行 OCR 识别")
def run_contract_ocr(
    contract_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """读原件 → 文本层优先、扫描件逐页 OCR → 字段候选提取 → 结果落库。

    与 `PATCH …/ocr`（人工回写）共用一张表一列：本接口是**机器**写，
    那条是**人**写；两者的产物都只能到 `parsed`/`failed`，到 `reviewed`
    必须走 `/ocr/review`（有人看着原件逐项核过才算数）。

    返回里的 `fields` / `party_candidates` / `items` 全是**候选**：
    识别一定有错，前端拿它们回填表单，但必须人工核对后（review）才允许被当成"已核对"。
    """
    item = _contract_or_404(db, contract_id)
    if not item.source_file_path:
        raise HTTPException(status_code=409, detail="这份合同还没有上传原件，请先上传 PDF 或图片")

    raw_bytes = file_storage.read_bytes(item.source_file_path)
    if not raw_bytes:
        raise HTTPException(
            status_code=404,
            detail=f"原件文件已丢失（记录里的路径是 {item.source_file_path}），请重新上传",
        )

    filename = item.source_file_name or f"{item.contract_no}{Path(item.source_file_path).suffix}"

    import json as _json

    try:
        result, fields_pack, raw_json, status_value = _recognize_contract(
            raw_bytes, filename, item.direction
        )
    except ValueError as exc:
        # 用户传了 Word 之类：这是"不该识别"，不是"识别失败"，不用留痕
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # 引擎崩了也要留痕，否则"识别中"会永远挂着
        failed_json = _json.dumps(
            {"error": f"识别引擎异常：{exc}"[:300], "recognized_at": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False,
        )
        _save_contract_ocr(db, item, failed_json, "failed")
        raise HTTPException(status_code=502, detail=f"识别引擎异常：{exc}") from exc

    _save_contract_ocr(db, item, raw_json[:200_000], status_value)

    return {
        "contract_id": item.id,
        **_ocr_result_payload(result, fields_pack, status_value),
        "message": (
            "识别完成，请人工核对"
            if status_value == "parsed"
            else "没有认出任何文字（原件可能是空白扫描件或图片太模糊），状态已置为「识别失败」"
        ),
    }


# 人工核对时可以一次性覆盖的字段。
# **刻意不含** total_amount / status / contract_no：
#   金额由明细重算、单号是唯一键、状态有独立的状态机 —— 让核对接口去改它们，
#   等于给"绕过业务规则"开了一个后门。
_OCR_REVIEW_FIELDS = (
    "title", "sign_date", "sign_place", "valid_from", "valid_to",
    "party_name", "party_tax_no", "party_legal_person", "party_address",
    "party_contact", "party_phone", "party_bank_name", "party_bank_account",
    "payment_terms", "invoice_requirement", "quality_standard", "delivery_date",
    "delivery_place", "delivery_method", "other_terms", "note",
)


@router.post("/contracts/{contract_id}/ocr/review", summary="OCR 结果人工核对")
def review_contract_ocr(
    contract_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """人工核对：把确认过的字段写回合同，并把 `ocr_status` 置为 `reviewed`。

    这是**唯一**能把状态推进到 `reviewed` 的入口 —— 它代表"有人看着原件逐项核过了"，
    不是"程序跑完了"。前端应当把 `ocr_json` 与表单并排展示，让用户确认后再提交。

    入参：`{"fields": {...}, "note": "..."}`；
    也可以直接把字段放在顶层（后端两种都认，见下方合并逻辑）。
    """
    item = _contract_or_404(db, contract_id)

    fields = payload.get("fields")
    if not isinstance(fields, dict):
        # 兼容"直接把字段摊在顶层"的写法
        fields = {key: value for key, value in payload.items() if key in _OCR_REVIEW_FIELDS}

    applied: list[str] = []
    for key in _OCR_REVIEW_FIELDS:
        if key in fields:
            value = fields[key]
            setattr(item, key, None if value in ("", None) else value)
            applied.append(key)

    if not applied and not payload.get("confirm_empty"):
        # 一个字段都没改就点"核对完成"，多半是前端把字段名写错了 ——
        # 静默置 reviewed 会让"已核对"变成一句谎话。确认无改动请显式传 confirm_empty=true。
        raise HTTPException(
            status_code=400,
            detail="没有可写入的字段（可用字段见接口文档）；若确认原件内容无需修改，请传 confirm_empty=true",
        )

    if payload.get("note") not in (None, ""):
        item.note = str(payload["note"])[:255]

    item.ocr_status = "reviewed"
    db.commit()
    db.refresh(item)
    return {
        "contract_id": item.id,
        "ocr_status": item.ocr_status,
        "applied_fields": applied,
        "message": f"已核对，写入 {len(applied)} 个字段",
    }





# —————————————————————— 销售报价单（对齐浩技云「销售 → 报价单」）——————————————————————


@router.get("/quotations/meta")
def quotation_meta() -> dict[str, object]:
    """报价单页面字典：状态 / 常用付款方式 / 常用运输方式。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in QUOTATION_STATUS.items()],
        "payment_methods": list(QUOTATION_PAYMENT_METHODS),
        "transport_methods": list(QUOTATION_TRANSPORT_METHODS),
    }



@router.get("/quotations")
def list_quotations(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    customer_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[QuotationRead]:
    query = db.query(Quotation).order_by(Quotation.id.desc())
    if status_value:
        query = query.filter(Quotation.status == status_value)
    if customer_id:
        query = query.filter(Quotation.customer_id == customer_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Quotation.quote_no.ilike(like),
                Quotation.customer_name.ilike(like),
                Quotation.businesser.ilike(like),
                Quotation.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_quotation_payload(item, _quotation_items(db, item.id)) for item in items]



@router.get("/quotations/{quotation_id}", response_model=QuotationRead)
def get_quotation(quotation_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    return _quotation_payload(item, _quotation_items(db, item.id))



@router.post("/quotations", response_model=QuotationRead, status_code=status.HTTP_201_CREATED)
def create_quotation(payload: QuotationCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.status and payload.status not in QUOTATION_STATUS:
        raise HTTPException(status_code=400, detail="报价单状态非法")

    quote_no = (payload.quote_no or "").strip() or _next_doc_no(db, Quotation, "BJ", field="quote_no")
    if db.query(Quotation).filter(Quotation.quote_no == quote_no).first():
        raise HTTPException(status_code=400, detail="报价单号已存在")

    data: dict[str, object] = payload.model_dump(exclude={"items", "status"})
    data["quote_no"] = quote_no
    data["status"] = payload.status or "draft"
    data["quote_date"] = payload.quote_date or datetime.now().strftime("%Y-%m-%d")
    # 第 13 批：可选关联合同 —— 先校验合同在不在，别等落库后才在列表里显示一个死链
    if payload.contract_id:
        if db.get(Contract, payload.contract_id) is None:
            raise HTTPException(status_code=404, detail="要关联的合同不存在")

    # 客户快照：能从档案带出的自动带出，其余留白由用户填（报价单是发给客户的历史凭证，
    # 不能让客户档案改地址把旧报价一起改掉）
    if payload.customer_id:
        customer = db.get(Customer, payload.customer_id)
        if customer is None:
            raise HTTPException(status_code=404, detail="客户档案不存在")
        data["customer_name"] = payload.customer_name or customer.name
        data["customer_address"] = payload.customer_address or getattr(customer, "address", None)
        data["contact"] = payload.contact or getattr(customer, "contact", None)
        data["contact_phone"] = (
            payload.contact_phone
            or getattr(customer, "contact_phone", None)
            or getattr(customer, "phone", None)
        )

    item = Quotation(**data)
    db.add(item)
    db.commit()
    db.refresh(item)

    total_amount = 0.0
    total_quantity = 0.0
    rows: list[QuotationItem] = []
    for line in payload.items:
        quantity = float(line.quantity or 0.0)
        unit_price = float(line.unit_price or 0.0)
        name, standards, unit = _resolve_item_snapshot(db, line)
        row = QuotationItem(
            quotation_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total_amount += row.amount
        total_quantity += quantity
        rows.append(row)
    db.add_all(rows)

    item.total_amount = round(total_amount, 2)
    item.total_quantity = round(total_quantity, 2)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)
    return _quotation_payload(item, rows)



@router.patch("/quotations/{quotation_id}", response_model=QuotationRead)
def update_quotation(
    quotation_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")

    text_fields = [
        "customer_name", "customer_address", "contact", "contact_phone", "fax",
        "quote_date", "valid_until", "businesser", "payment_method",
        "transport_method", "delivery_place", "note",
    ]
    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    if "warehouse_id" in payload:
        raw = payload.get("warehouse_id")
        item.warehouse_id = int(raw) if raw not in ("", None) else None
    if "customer_id" in payload:
        raw = payload.get("customer_id")
        item.customer_id = int(raw) if raw not in ("", None) else None
    # 第 13 批：可选关联合同。传 null 表示解除关联（存量表没有外键，
    # 所以"解除关联"必须在应用层显式做，见 DESIGN-PHASE1.md 决策矩阵）。
    if "contract_id" in payload:
        raw = payload.get("contract_id")
        if raw in ("", None):
            item.contract_id = None
        else:
            contract_id = _as_int(raw, "contract_id")
            if db.get(Contract, contract_id) is None:
                raise HTTPException(status_code=404, detail="要关联的合同不存在")
            item.contract_id = contract_id
    if payload.get("status"):
        if str(payload["status"]) not in QUOTATION_STATUS:
            raise HTTPException(status_code=400, detail="报价单状态非法")
        item.status = str(payload["status"])

    rows = _quotation_items(db, item.id)
    # 传了明细就整单替换（明细是报价商品清单，逐行改容易改乱）
    if isinstance(payload.get("items"), list):
        db.query(QuotationItem).filter(QuotationItem.quotation_id == item.id).delete()
        rows = []
        total_amount = 0.0
        total_quantity = 0.0
        for line in payload["items"]:
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            product = db.get(Product, int(product_id)) if product_id else None
            quantity = float(line_data.get("quantity") or 0.0)
            unit_price = float(line_data.get("unit_price") or 0.0)
            row = QuotationItem(
                quotation_id=item.id,
                product_id=int(product_id) if product_id else None,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=line_data.get("unit") or (product.unit if product else None),
                quantity=quantity,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total_amount += row.amount
            total_quantity += quantity
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total_amount, 2)
        item.total_quantity = round(total_quantity, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)

    db.commit()
    db.refresh(item)
    return _quotation_payload(item, rows)



@router.patch("/quotations/{quotation_id}/status", response_model=QuotationRead)
def update_quotation_status(
    quotation_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in QUOTATION_STATUS:
        raise HTTPException(status_code=400, detail="报价单状态非法")
    item.status = status_value
    db.commit()
    db.refresh(item)
    return _quotation_payload(item, _quotation_items(db, item.id))



@router.get("/quotations/{quotation_id}/references")
def quotation_references(quotation_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """删除前的引用检查：已转单的报价单不能直接删，否则订单溯源断链。"""
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    refs: list[dict[str, object]] = []
    if item.order_id:
        refs.append({
            "type": "order",
            "label": "已生成销售订单",
            "doc_no": _s(item.order_no),
            "count": 1,
        })
    return {"quotation_id": quotation_id, "quote_no": item.quote_no, "references": refs}



@router.delete("/quotations/{quotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quotation(
    quotation_id: int, force: bool = Query(False), db: Session = Depends(get_db)
) -> Response:
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    if item.order_id and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"报价单 {item.quote_no} 已生成销售订单 {item.order_no}，删除会断开订单溯源",
                "references": [{"type": "order", "doc_no": item.order_no}],
                "hint": "如需保留订单，请改为把报价单状态置为「已作废」；确要删除可加 force=true",
            },
        )
    db.query(QuotationItem).filter(QuotationItem.quotation_id == quotation_id).delete()
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.post("/quotations/{quotation_id}/to-order")
def quotation_to_order(
    quotation_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """一键转单：报价单 → 销售订单（`doc_type='order'`）。

    与购销合同同一条链路 —— 报价单本身不产生应收、不动库存，
    转成销售订单后由订单去转开单，才联动库存与财务。
    """
    item = db.get(Quotation, quotation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="报价单不存在")
    if item.order_id:
        raise HTTPException(status_code=409, detail=f"该报价单已生成销售订单 {item.order_no}，不能重复转单")
    if item.status == "void":
        raise HTTPException(status_code=400, detail="已作废的报价单不能转单")

    rows = _quotation_items(db, item.id)
    if not rows:
        raise HTTPException(status_code=400, detail="报价单没有明细，无法转单")
    if not item.customer_id:
        raise HTTPException(status_code=400, detail="报价单未关联客户档案，无法转单")

    order_payload = SalesOrderCreate(
        customer_id=item.customer_id,
        doc_type="order",
        items=[
            SalesOrderItemCreate(
                product_id=row.product_id or 0,
                quantity=int(row.quantity or 0),
                unit_price=float(row.unit_price or 0.0),
                product_name=row.product_name,
                standards=row.standards,
                unit=row.unit,
                note=row.note,
            )
            for row in rows
        ],
        warehouse_id=item.warehouse_id,
        order_date=item.quote_date,
        contact=item.contact,
        contact_phone=item.contact_phone,
        address=item.customer_address,
        payment_method=item.payment_method,
        note=f"由报价单 {item.quote_no} 生成",
    )
    order = create_sales_order(order_payload, db)

    item.order_id = order.id
    item.order_no = order.order_no
    if item.status in ("draft", "quoted"):
        item.status = "accepted"
    db.commit()
    db.refresh(item)

    return {
        "quotation_id": item.id,
        "quote_no": item.quote_no,
        "order_type": "sales_order",
        "order_label": "销售订单",
        "order_id": order.id,
        "order_no": order.order_no,
        "order_amount": float(order.total_amount or 0.0),
        "message": f"已按报价单 {item.quote_no} 生成销售订单 {order.order_no}",
    }



def _sales_return_payload(item: SalesReturn, rows: list[SalesReturnItem]) -> dict[str, object]:
    return {
        "id": item.id,
        "return_no": item.return_no,
        "customer_id": item.customer_id,
        "customer_name": item.customer_name,
        "contact": item.contact,
        "contact_phone": item.contact_phone,
        "address": item.address,
        "warehouse_id": item.warehouse_id,
        "businesser": item.businesser,
        "return_date": item.return_date,
        "return_reason": item.return_reason,
        "payment_method": item.payment_method,
        "note": item.note,
        "source_order_id": item.source_order_id,
        "source_order_no": item.source_order_no,
        "status": item.status,
        "total_amount": item.total_amount,
        "amount_chinese": item.amount_chinese,
        "created_at": item.created_at,
        "items": [
            {
                "id": row.id,
                "sales_return_id": row.sales_return_id,
                # 3c 多单位换算快照（漏了它 Pydantic 会静默填 1）
                "unit_factor": row.unit_factor,
                "product_id": row.product_id,
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": row.quantity,
                "unit_price": row.unit_price,
                "amount": row.amount,
                "note": row.note,
            }
            for row in rows
        ],
    }



def _sales_return_quantity(value: object, index: int) -> float:
    """校验销售退货明细的数量是整数，返回 float（该列类型本来就是 double precision）。

    ⚠️ 这是 3c 顺手补上的一个**静默错数据**口子（与采购退货 7.6 同类）：
    `SalesReturnItem.quantity` 是 `double precision`，而写库存流水那一侧过去用的是
    `int(row.quantity or 0)` —— 于是「退 3.5 件」会**静默**变成入库 3，
    少的 0.5 既没报错也没有日志。接了多单位换算之后更糟：
    `int(3.5) * 10 = 30`，而单据的意思是 35 —— 一次丢 5 件。

    库存的硬规则是「绝不存小数」，所以这里**不截断、也不四舍五入**，
    直接把不合法的数量挡在门外。
    """
    try:
        qty = float(value or 0.0)
    except (TypeError, ValueError):
        # PATCH 那条路的 payload 是**裸 dict**（不像 POST 有 Pydantic 挡在前面），
        # 所以 "abc" 这种脏值会走到这里 —— 不能让它冒成 500
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量不是合法数字",
        ) from None
    # is_integer() 对 inf / nan 都返回 False，所以这一句同时把它们挡掉
    if not qty.is_integer():
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量必须是整数（库存按整数计量），当前填的是 {qty}",
        )
    # ⚠️ 只判"整数"不够：`float(None or 0.0)` 就是 0.0，而 0.0 是"合法整数"。
    #    0 件退货会让金额变 0，还会因为 `_apply_stock` 对 qty==0 直接 return None
    #    而顺手把原来的库存流水冲销掉。退货单上一行"退 0 件"本来就没有业务含义。
    if qty <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货数量必须大于 0",
        )
    return qty


def _sales_return_unit_price(
    raw: object,
    index: int,
    *,
    product: Product | None,
    factor: int,
    fallback: float | None,
) -> float:
    """解析销售退货明细行的单价 —— **绝不允许把一个 0 写进单据**。

    ⚠️ 与采购退货（3b 的价格补丁）是同一个财务口子：单价一旦被静默写成 0，
    金额、应收冲减、财务流水**全部变成 0**，而**库存照样加** ——
    单据、库存、财务三个数字从此永久对不上，而且一声不响。

    调用点的 `raw` 来源不同，但"非正数"的形态一样：
      · POST：Pydantic 的 `unit_price: float = 0.0` —— **字段缺失就是 0.0**
      · PATCH：裸 dict 的 `.get("unit_price")` —— 缺失是 None
    所以这里**刻意不去区分**"显式填了 0"和"根本没填"：两者都是"没提供有效价格"。

    兜底顺序由调用方通过 `fallback` 决定（None = 没有可继承的来源）：
      · PATCH：回查这张单**原来的同商品明细单价**
      · POST ：没有原单可查，回落到 `products.sale_price × factor`
        —— 档案**售价**是**基本单位**口径，必须乘 factor 才等于"每录入单位"的价；
        不乘的话「1 箱」会按「1 盒」的价记账，少 factor 倍

    兜底也拿不到 >0 的数就 **400**。宁可挡在门外，也不要往库里写一个 0。
    """
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货单价不是合法数字",
        ) from None
    if value > 0:
        return value
    if value < 0:
        raise HTTPException(
            status_code=400,
            detail=f"第 {index + 1} 行的退货单价不能是负数（当前填的是 {value}）",
        )
    if fallback is not None and fallback > 0:
        return float(fallback)
    if product is not None:
        hint = f"商品「{product.name}」的档案里也没有售价"
    else:
        hint = "该商品档案不存在，无法回查售价"
    raise HTTPException(
        status_code=400,
        detail=(
            f"第 {index + 1} 行的退货单价必须大于 0（留空或填 0 都不允许）。"
            f"{hint}，请在明细里显式填写单价。"
        ),
    )


def _sales_return_apply_stock(db: Session, item: SalesReturn, rows: list[SalesReturnItem]) -> None:
    """把销售退货明细写成 inbound 库存流水。

    ⚠️ **调用方负责先冲销旧的**（`_revert_stock(db, "sales_return", item.id)`）。
    退货是**增加**现存量，方向与销售出库相反。单据没填仓库时回退到默认仓库，
    并把结果回填到单据上，保证单据与流水指向同一个仓。

    POST 与 PATCH 都走这一个函数 —— 两份各写一遍的话，
    将来改了一处忘一处，同一张单"新建"和"改一下"就会算出不同的库存。
    """
    stock_warehouse_id = _resolve_warehouse_id(db, item.warehouse_id)
    if stock_warehouse_id is not None and item.warehouse_id is None:
        item.warehouse_id = stock_warehouse_id
    for row in rows:
        _apply_stock(
            db,
            product_id=row.product_id,
            warehouse_id=stock_warehouse_id,
            quantity=row.quantity,
            transaction_type="inbound",
            unit_price=row.unit_price,
            related_type="sales_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            # 3c：交给 `_apply_stock` 统一换算，调用点不要再乘一遍
            unit_factor=row.unit_factor,
            note=f"销售退货 {item.return_no}",
        )


@router.get("/sales-returns/meta")
def sales_return_meta() -> dict[str, object]:
    """销售退货页字典：状态。"""
    return {
        "statuses": [{"code": code, "label": label} for code, label in SALES_RETURN_STATUS.items()],
    }



@router.get("/sales-returns")
def list_sales_returns(
    db: Session = Depends(get_db),
    status_value: str | None = Query(None, alias="status"),
    customer_id: int | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = db.query(SalesReturn).order_by(SalesReturn.id.desc())
    if status_value:
        query = query.filter(SalesReturn.status == status_value)
    if customer_id:
        query = query.filter(SalesReturn.customer_id == customer_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                SalesReturn.return_no.ilike(like),
                SalesReturn.customer_name.ilike(like),
                SalesReturn.businesser.ilike(like),
                SalesReturn.note.ilike(like),
            )
        )
    items = _paginate(query, skip, limit).all()
    return [_sales_return_payload(item, _sales_return_items(db, item.id)) for item in items]



@router.get("/sales-returns/{return_id}", response_model=SalesReturnRead)
def get_sales_return(return_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    return _sales_return_payload(item, _sales_return_items(db, item.id))



@router.post("/sales-returns", response_model=SalesReturnRead, status_code=status.HTTP_201_CREATED)
def create_sales_return(payload: SalesReturnCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户档案不存在")

    if payload.status and payload.status not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")

    return_no = (payload.return_no or "").strip() or _next_doc_no(db, SalesReturn, "XSTH", field="return_no")
    if db.query(SalesReturn).filter(SalesReturn.return_no == return_no).first():
        raise HTTPException(status_code=400, detail="销售退货单号已存在")

    return_date = payload.return_date or datetime.now().strftime("%Y-%m-%d")

    # —— 3c：明细快照、数量、换算率、单价**必须在写单头之前**全部解析完 ——
    #    单头 commit 之后才解析的话，任何一条 400 都会留下一张「只有表头」的孤儿退货单。
    #    单价校验尤其重要：拿不到有效价格就 400，绝不把 0 写进单据。
    snapshots = [_resolve_item_snapshot(db, line) for line in payload.items]
    products = [
        db.get(Product, line.product_id) if line.product_id else None
        for line in payload.items
    ]
    quantities = [
        _sales_return_quantity(line.quantity, index)
        for index, line in enumerate(payload.items)
    ]
    unit_factors = [
        _resolve_unit_factor(db, line.product_id, snapshot[2])
        for line, snapshot in zip(payload.items, snapshots)
    ]
    # 建退货单通常没有"原单"可回查（source_order_id 是选填的），所以兜底用
    # **档案售价 × 换算率** —— 档案售价是**基本单位**口径，乘 factor 才是"每录入单位"的价。
    unit_prices = [
        _sales_return_unit_price(
            line.unit_price,
            index,
            product=products[index],
            factor=unit_factors[index],
            fallback=(
                float(products[index].sale_price or 0.0) * unit_factors[index]
                if products[index] is not None
                else None
            ),
        )
        for index, line in enumerate(payload.items)
    ]

    item = SalesReturn(
        return_no=return_no,
        customer_id=payload.customer_id,
        customer_name=payload.customer_name or customer.name,
        contact=payload.contact or customer.contact,
        contact_phone=payload.contact_phone or customer.contact_phone or customer.phone,
        address=payload.address or customer.address,
        warehouse_id=payload.warehouse_id,
        businesser=payload.businesser or customer.businesser,
        return_date=return_date,
        return_reason=payload.return_reason,
        payment_method=payload.payment_method,
        note=payload.note,
        source_order_id=payload.source_order_id,
        source_order_no=payload.source_order_no,
        status=payload.status or "submitted",
        total_amount=0.0,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    total = 0.0
    rows: list[SalesReturnItem] = []
    for index, line in enumerate(payload.items):
        name, standards, unit = snapshots[index]
        quantity = quantities[index]
        unit_price = unit_prices[index]
        row = SalesReturnItem(
            sales_return_id=item.id,
            product_id=line.product_id,
            product_name=name or line.product_name,
            standards=standards,
            unit=unit,
            quantity=quantity,
            # 3c 换算率快照：服务端从 unit 现场解析，绝不接受客户端传入
            unit_factor=unit_factors[index],
            unit_price=unit_price,
            amount=round(quantity * unit_price, 2),
            note=line.note,
        )
        total += row.amount
        rows.append(row)
    db.add_all(rows)

    item.total_amount = round(total, 2)
    item.amount_chinese = amount_to_chinese(item.total_amount)
    db.commit()
    db.refresh(item)

    # —— 库存联动（退货增加现存量）+ 财务联动（冲减应收，金额记负数、方向 in）——
    # 统一走 `_sales_return_apply_ledger`：只有 submitted 才落账，且幂等。
    # 早先这里是无条件落账，于是「存成草稿」也会动库存和应收（单据还只是草稿）。
    _sales_return_apply_ledger(db, item, rows)

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, rows)



def _sales_return_posted(db: Session, return_id: int) -> bool:
    """这张退货单**账上是否已经落过账** —— 只看流水，不看状态。

    为什么不信状态：「已退货」但流水被人为清掉的历史单，状态仍是 submitted，
    按状态判断就会在改备注时又落一遍账（库存凭空多一批）。
    """
    return (
        db.query(InventoryTransaction.id)
        .filter(
            InventoryTransaction.related_type == "sales_return",
            InventoryTransaction.related_order_id == return_id,
        )
        .first()
        is not None
    )


def _sales_return_apply_ledger(
    db: Session, item: SalesReturn, rows: list[SalesReturnItem]
) -> None:
    """按**当前**状态决定要不要落账 —— 落账 = 加库存 + 冲减应收。

    ⚠️ 2026-10-20 业务口径（v72 修复，2026-10-21 从会话日志恢复）：

      只有 `submitted`（已退货）才落账。**本函数只负责「加」，永远不负责「撤」** ——
      「撤」（红冲）必须走独立的 `POST /sales-returns/{id}/void`，
      由用户在二次确认弹窗里明确点了「确认红冲」才执行。

    为什么把「加」和「撤」彻底拆开：
        早先两者塞进一个 `_sync_sales_return_ledger`，于是「反审核」= 既改状态
        又冲库存冲应收。用户点「反审核」的本意是「我要回去改一下这张单」，
        而不是「我要把这张单作废」—— 两个动作混在一个按钮里，真实账上就是灾难：
        一张单在草稿里改两次，库存被出入两次、应收被冲减两次，且没有任何二次确认。

    幂等保护：已经落过账的单不重复落账。判断依据是流水本身而不是状态/标记位，
        因为流水才是账的唯一真相源。
    """
    if item.status != "submitted":
        return
    if _sales_return_posted(db, item.id):
        return
    _sales_return_apply_stock(db, item, rows)
    total = float(item.total_amount or 0.0)
    if total > 0:
        _write_finance(
            db,
            transaction_type="receivable",
            direction="in",
            amount=-total,
            related_type="sales_return",
            related_order_id=item.id,
            doc_no=item.return_no,
            customer_id=item.customer_id,
            warehouse_id=item.warehouse_id,
            occurred_at=item.return_date,
            note=f"销售退货 {item.return_no} 冲减应收",
        )


def _sales_return_red_flush(
    db: Session, item: SalesReturn, rows: list[SalesReturnItem]
) -> None:
    """红冲：把这张退货单的库存增量与应收冲减**全部撤回**，然后按当前明细重新落一笔。

    调用者只有两个：
      · `POST /sales-returns/{id}/void`  —— 用户点「作废 / 红冲」并二次确认后
      · `update_sales_return` 里「改的是一张**已落账**的单」的情况

    第二条为什么要重写而不是拦死：
        已退货的单如果允许直接改数量，单据与账本就必须一起动，否则
        「单据说退 5 件、流水还是 3 件」——这种静默不一致比拦死更危险。
        但反过来，**只是点「反审核」退回草稿时，一个字都不许动账**，
        所以这个函数不在状态变更路径上被调用。
    """
    _revert_stock(db, "sales_return", item.id)
    _revert_finance(db, "sales_return", item.id)
    db.flush()
    # 重新落账按"当前明细 + 当前状态"算，且此时流水已清空，幂等判断不会误拦
    _sales_return_apply_ledger(db, item, rows)


@router.patch("/sales-returns/{return_id}", response_model=SalesReturnRead)
def update_sales_return(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    if item.status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="这张退货单已作废（红冲），不能再修改。要重新退货请新建一张。",
        )

    # 这张单此刻**账上是否已经落过账** —— 只看流水，不看状态
    posted_before = _sales_return_posted(db, item.id)

    text_fields = [
        "customer_name", "contact", "contact_phone", "address", "businesser",
        "return_date", "return_reason", "payment_method", "note",
        "source_order_no",
    ]
    for field in text_fields:
        if field in payload:
            setattr(item, field, payload.get(field))
    for int_field in ("warehouse_id", "source_order_id", "customer_id"):
        if int_field in payload:
            raw = payload.get(int_field)
            setattr(item, int_field, int(raw) if raw not in ("", None) else None)

    # ⚠️ 状态先存起来，等明细处理完再一次性收口（见文件末尾的四条路径）。
    #    边改边落账会出现"回滚一次、再加一次"的重账。
    target_status = item.status
    if payload.get("status"):
        if str(payload["status"]) not in SALES_RETURN_STATUS:
            raise HTTPException(status_code=400, detail="销售退货状态非法")
        target_status = str(payload["status"])
    # 「作废」只能走 POST /{id}/void（带二次确认 + 红冲流水），这里不许直写
    if target_status == "cancelled" and item.status != "cancelled":
        raise HTTPException(
            status_code=400,
            detail="作废（红冲）请用「作废」按钮，它会撤回库存与应收并留痕；普通编辑不能直接把状态改成已取消。",
        )

    rows = _sales_return_items(db, item.id)
    content_changed = False
    # 传了明细就整单替换并重算金额/大写
    if isinstance(payload.get("items"), list):
        # ⚠️ 替换之前先把**这张单原来的同商品单价**记下来。
        #    PATCH 走的是**裸 dict**（不像 POST 有 Pydantic 挡在前面），
        #    `line_data.get("unit_price")` 缺失就是 None；不兜底就等于静默按 0 记账 ——
        #    金额/应收/财务流水全变 0，而库存照样动，三个数字永久对不上。
        previous_prices: dict[int, float] = {}
        for old in db.query(SalesReturnItem).filter(
            SalesReturnItem.sales_return_id == item.id
        ).all():
            old_price = float(old.unit_price or 0.0)
            if old.product_id is not None and old_price > 0:
                previous_prices.setdefault(int(old.product_id), old_price)

        db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == item.id).delete()
        rows = []
        total = 0.0
        for index, line in enumerate(payload["items"]):
            line_data = line if isinstance(line, dict) else {}
            product_id = line_data.get("product_id")
            pid = int(product_id) if product_id else None
            product = db.get(Product, pid) if pid else None
            unit = line_data.get("unit") or (product.unit if product else None)
            # 和 POST 一样：**按 unit 现场解析**换算率，绝不信客户端传的 factor
            factor = _resolve_unit_factor(db, pid, unit)
            quantity = _sales_return_quantity(line_data.get("quantity"), index)
            # 单价缺失 → 回查这张单原来的同商品单价；查不到（新加的行）→ 400
            unit_price = _sales_return_unit_price(
                line_data.get("unit_price"),
                index,
                product=product,
                factor=factor,
                fallback=previous_prices.get(pid) if pid else None,
            )
            row = SalesReturnItem(
                sales_return_id=item.id,
                product_id=pid,
                product_name=line_data.get("product_name") or (product.name if product else None),
                standards=line_data.get("standards") or (product.standards if product else None),
                unit=unit,
                quantity=quantity,
                # 3c：漏写这一列 = PATCH 一次就把换算率悄悄打回 1，库存按 1 倍扣
                unit_factor=factor,
                unit_price=unit_price,
                amount=round(quantity * unit_price, 2),
                note=line_data.get("note"),
            )
            total += row.amount
            rows.append(row)
        db.add_all(rows)
        item.total_amount = round(total, 2)
        item.amount_chinese = amount_to_chinese(item.total_amount)
        content_changed = True

    item.status = target_status

    # —— 账实联动收口（2026-10-20 重构后的四条路径）——
    #  ① 这张单**改完之后仍是草稿** → 不管改了什么，账一分不动。
    #     "草稿里改明细"只改单据，实体库存/应收保持上一版；等审核或作废才动账。
    #     （早先漏了这一条，会把上一版账红冲掉 → 库存凭空少一批，肉眼查不出来）
    #  ② 明细/仓库/客户被改过，且这张单**账上已经落过** → 红冲旧的、按新明细重落。
    #     （已落账的单必须账随单动，否则「单据说 5、流水 3」永久对不上）
    #  ③ 明细/仓库/客户被改过，但这张单还没落账 → 什么都不用做，等审核时才落。
    #  ④ 只是改状态（反审核）→ **一个字都不碰账**。
    #     反审核的本意是「退回去让我改」，不是「作废」；冲销是独立按钮的事。
    ledger_inputs_changed = content_changed or any(
        key in payload for key in ("warehouse_id", "customer_id", "return_date")
    )
    will_post = target_status == "submitted"
    if not will_post:
        # ① 草稿 / 其它非落账状态：账保持原样，一次都不许冲
        pass
    elif posted_before and ledger_inputs_changed:
        # ② 已落账单被改：先冲后落
        _sales_return_red_flush(db, item, rows)
    elif not posted_before:
        # ③ 从未落账（草稿→审核）：这一刻才真正加库存、冲应收
        _sales_return_apply_ledger(db, item, rows)
    # ④ posted_before 且没改任何账务输入 → 只改了备注之类，什么都不做

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, rows)



@router.patch("/sales-returns/{return_id}/status", response_model=SalesReturnRead)
def update_sales_return_status(
    return_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """改销售退货状态 —— **只改状态，绝不动账**（2026-10-20 重构）。

    这是「反审核」按钮走的那条路。用户点它的意思是
    「这张单我要退回去改一下」，不是「这张单作废了」——
    所以库存与应收一律原样保留，交由用户改完再审核。

    真正的冲销（红冲）必须在 `POST /sales-returns/{id}/void` 里做，
    那条路带二次确认弹窗，而且会把单据落到 `cancelled`。
    """
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    status_value = str(payload.get("status") or "").strip()
    if status_value not in SALES_RETURN_STATUS:
        raise HTTPException(status_code=400, detail="销售退货状态非法")
    if item.status == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="这张退货单已作废（红冲），状态不能再改。要重新退货请新建一张。",
        )
    if status_value == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="作废（红冲）请用「作废」按钮，它会撤回库存与应收并留痕。",
        )

    item.status = status_value
    # 草稿 → 已退货：这一刻才落账（幂等，落过就跳过）
    if status_value == "submitted":
        _sales_return_apply_ledger(db, item, _sales_return_items(db, item.id))

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))


@router.post("/sales-returns/{return_id}/void", response_model=SalesReturnRead)
def void_sales_return(
    return_id: int, payload: dict[str, object] | None = None, db: Session = Depends(get_db)
) -> dict[str, object]:
    """作废（红冲）销售退货单 —— 撤库存、撤应收，单据落 `cancelled`。

    **这是唯一会「反向冲账」的入口**，前端必须二次确认才调它。

    为什么要独立成一个接口，而不是在 PATCH status 里传 cancelled：
      ① 冲账是不可逆的账务动作，出现在「改状态」这种廉价接口里，
         任何一个手滑的前端调用都能把账冲掉；
      ② 需要一个地方写「谁、什么时候、为什么」冲的 —— `payload.reason`
         会写进单据备注，事后对账才有人可问；
      ③ 幂等：已经作废过的单再点一次直接回当前内容，不会二次冲账。

    已登记的收款流水**不拦**：退货单冲减的是应收（负数流水），
    作废它等于恢复应收，本身不会造成"钱凭空多出来"；
    真正的钱（receipt/payment）从来不属于退货单。
    """
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")

    if item.status == "cancelled":
        # 幂等：重复点不报错、不再冲一次账
        return _sales_return_payload(item, _sales_return_items(db, item.id))

    reason = ""
    if isinstance(payload, dict):
        reason = str(payload.get("reason") or "").strip()

    was_posted = _sales_return_posted(db, item.id)

    if was_posted:
        _revert_stock(db, "sales_return", item.id)
        _revert_finance(db, "sales_return", item.id)
        db.flush()

    item.status = "cancelled"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = f"[已作废 {stamp}]"
    if reason:
        note += f" 作废原因：{reason}"
    if was_posted:
        note += " 库存与应收已红冲撤回；"
    else:
        note += " 本单未落过账，无库存/应收需要撤回；"
    item.note = f"{item.note}\n{note}" if item.note else note

    db.commit()
    db.refresh(item)
    return _sales_return_payload(item, _sales_return_items(db, item.id))



@router.delete("/sales-returns/{return_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_return(return_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(SalesReturn, return_id)
    if item is None:
        raise HTTPException(status_code=404, detail="销售退货单不存在")
    # 库存联动回滚：冲销这张退货单产生的 inbound 流水（退货入库的动作撤销，库存减回去）
    _revert_stock(db, "sales_return", return_id)
    # 财务联动回滚：冲销这张单产生的应收冲减流水
    db.query(FinancialTransaction).filter(
        FinancialTransaction.related_type == "sales_return",
        FinancialTransaction.related_order_id == return_id,
    ).delete(synchronize_session=False)
    db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == return_id).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
