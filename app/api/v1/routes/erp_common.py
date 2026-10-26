"""公共辅助层 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

跨域共享的工具函数：分页 / 单号 / 会计期间 / 库存联动 / 财务写入 / 金额大写 / 档案引用检查等。
"""

from __future__ import annotations

import base64
import json
import re

from app.models.bom import BillOfMaterial
from app.models.contract import ContractItem
from app.models.finance import FinancialTransaction
from app.models.finished_goods import FinishedGoodsReceiptItem
from app.models.inventory import InventoryTransaction
from app.models.inventory_adjustment import InventoryAdjustmentItem
from app.models.inventory_transfer import InventoryTransferItem
from app.models.material_issue import MaterialIssueItem
from app.models.material_return import MaterialReturnItem
from app.models.outsourcing import OutsourcingItem
from app.models.product import Product
from app.models.product_unit import ProductUnit
from app.models.production_plan import ProductionPlanItem
from app.models.purchase_return import PurchaseReturnItem
from app.models.quotation import QuotationItem
from app.models.sales_return import SalesReturnItem
from app.models.stocktaking import StocktakingItem
from app.models.warehouse import Warehouse
from datetime import datetime
from fastapi import HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib import request


def _paginate(query, skip: int = 0, limit: int | None = None):
    """统一列表分页：limit 不传或 <= 0 时返回全部记录，不做任何截断。

    此前各列表接口默认 limit=100/500，导致「库里有 384 个商品，界面只显示 100 个」
    这类静默丢数据的问题。现在默认全量返回；调用方仍可显式传 skip/limit 做分页。
    """
    if skip and skip > 0:
        query = query.offset(skip)
    if limit is not None and limit > 0:
        query = query.limit(limit)
    return query



# ============================================================================
# 融合改造：单据公共逻辑（单号生成 / 结算链 / 欠款链 / 财务自动记账）
# ============================================================================


def _next_doc_no(db: Session, model, prefix: str, field: str = "order_no") -> str:
    """按 前缀 + 日期 + 3 位流水 生成单号，例如 CG20261010001。

    取当天同前缀的最大单号 +1；若当天还没有单子则从 001 开始。
    ``field`` 为单据号所在列名，默认 `order_no`（采购 / 销售单）；合同表用 `contract_no`。
    """
    today = datetime.now().strftime("%Y%m%d")
    column = getattr(model, field)
    pattern = f"{prefix}{today}%"
    last = (
        db.query(column)
        .filter(column.like(pattern))
        .order_by(column.desc())
        .first()
    )
    seq = 1
    if last and last[0]:
        tail = last[0][len(prefix) + 8 :]
        if tail.isdigit():
            seq = int(tail) + 1
    return f"{prefix}{today}{seq:03d}"



def _prev_debt_total(db: Session, model, fk_field, fk_value: int) -> float:
    """取同一往来对象上一张单据的"累欠货款"，作为本单的"前次欠款"。"""
    last = db.query(model).filter(fk_field == fk_value).order_by(model.id.desc()).first()
    return float(last.total_debt or 0.0) if last is not None else 0.0



def _normalize_period(value: str | None, fallback_date: str | None = None) -> str:
    """把 YYYY-MM-DD 归一成会计期间 YYYY-MM。"""
    raw = (value or fallback_date or "").strip()
    if len(raw) >= 7:
        return raw[:7]
    return datetime.now().strftime("%Y-%m")



def resolve_contract_document_payload(db: Session, payload: dict) -> dict:
    """把「新增购销合同」的表单态补全成合同正文需要的完整数据。

    表单里只传了 `party_id` 和 `items[].product_id`（商品名/规格/单位由后端从档案取），
    而合同正文必须写**全称**——所以这里统一补三样：

      1. `party_name` / `party_tax_no` 等由 `party_id` 反查（表单不重复传，避免两边不一致）；
      2. 明细的 `product_name / standards / unit` 由 `product_id` 反查；
      3. `amount` 缺省按 数量 × 单价 现算（前端有时不传金额）。

    补全后的 payload 会**原样返回给前端**，再打给 PDF 接口 ——
    保证"预览看到的"和"导出的"是同一份数据，不会各算一遍算岔。
    """
    from app.models.customer import Customer
    from app.models.product import Product
    from app.models.supplier import Supplier

    data = dict(payload or {})
    party_type = str(data.get("party_type") or "").strip()
    if not party_type:
        # 表单用的是 contract_type（sales/purchase），这里换算成往来单位类型
        party_type = "supplier" if str(data.get("contract_type") or "sales") == "purchase" else "customer"
        data["party_type"] = party_type
    if not data.get("direction"):
        data["direction"] = "in" if party_type == "supplier" else "out"

    party_id = data.get("party_id")
    # ⚠️ 2026-10-23：原来只有 `party_name` 为空才去反查档案 —— 而合同表单里
    # party_name 早就由下拉选好了，于是 **税号/开户行/账号从来没被带进正文**，
    # 打出来的合同抬头永远是空的。现在改成"按字段各自补空缺"，与名称无关。
    if party_id not in (None, ""):
        try:
            model = Supplier if party_type == "supplier" else Customer
            party = db.get(model, int(party_id))
        except (TypeError, ValueError):
            party = None
        if party is not None:
            data["party_name"] = data.get("party_name") or getattr(party, "name", None)
            data["party_tax_no"] = data.get("party_tax_no") or getattr(party, "tax_no", None)
            data["party_address"] = data.get("party_address") or getattr(party, "address", None)
            data["party_contact"] = data.get("party_contact") or getattr(party, "contact", None)
            # 抬头电话优先用**开票电话**（财务留的那个号），没填才退回业务电话
            data["party_phone"] = (
                data.get("party_phone")
                or getattr(party, "invoice_phone", None)
                or getattr(party, "phone", None)
            )
            # 开户行 / 账号：合同结算条款与落款都要用
            data["party_bank_name"] = data.get("party_bank_name") or getattr(party, "bank_name", None)
            data["party_bank_account"] = (
                data.get("party_bank_account") or getattr(party, "bank_account", None)
            )

    items: list[dict] = []
    for row in data.get("items") or []:
        item = dict(row)
        product_id = item.get("product_id")
        if product_id not in (None, "") and not item.get("product_name"):
            try:
                product = db.get(Product, int(product_id))
            except (TypeError, ValueError):
                product = None
            if product is not None:
                item["product_name"] = product.name
                item["standards"] = item.get("standards") or getattr(product, "standards", None)
                item["unit"] = item.get("unit") or getattr(product, "unit", None)
        if item.get("amount") in (None, "", 0):
            try:
                item["amount"] = round(
                    float(item.get("quantity") or 0) * float(item.get("unit_price") or 0), 2
                )
            except (TypeError, ValueError):
                item["amount"] = 0
        items.append(item)
    data["items"] = items
    return data


def _next_flow_no(db: Session, day: str) -> str:
    """生成资金流水号 `FL<yyyymmdd><3位序号>`（如 FL20261022001）。

    为什么要有它：对账时客户问"这笔钱对应哪张回单"，靠自增 id 说不清 ——
    流水号是可以抄到银行回单上、可以被对方核对的一串字符。
    ⚠️ 逐日递增、**按字符串前缀取最大值**（同日序号定长 3 位，字典序=数值序）；
    没有唯一索引，单机单用户足够；将来多人并发要改成序列或行锁。
    """
    prefix = f"FL{str(day or '').replace('-', '')[:8]}"
    last = (
        db.query(FinancialTransaction.flow_no)
        .filter(FinancialTransaction.flow_no.like(f"{prefix}%"))
        .order_by(FinancialTransaction.flow_no.desc())
        .first()
    )
    seq = 1
    if last and last[0]:
        tail = str(last[0])[len(prefix):]
        if tail.isdigit():
            seq = int(tail) + 1
    return f"{prefix}{seq:03d}"


def _write_finance(
    db: Session,
    *,
    transaction_type: str,
    amount: float,
    related_type: str | None = None,
    related_order_id: int | None = None,
    doc_no: str | None = None,
    direction: str | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    project_id: int | None = None,
    occurred_at: str | None = None,
    note: str | None = None,
    invoice_id: int | None = None,
    flow_no: str | None = None,
) -> FinancialTransaction:
    """业务单据审核后由系统自动写财务流水，人工不允许绕过。

    `invoice_id`（2026-10-22）：把"付款流水 → 进项发票"这颗钉子传下去。
    不传就是 None —— 历史调用方一个都不用改。
    """
    day = (occurred_at or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    record = FinancialTransaction(
        transaction_type=transaction_type,
        related_type=related_type,
        related_order_id=related_order_id,
        doc_no=doc_no,
        direction=direction,
        customer_id=customer_id,
        supplier_id=supplier_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        project_id=project_id,
        amount=float(amount or 0.0),
        occurred_at=day,
        period=_normalize_period(day),
        note=note,
        invoice_id=invoice_id,
        # 流水号：调用方没给就自动生成（历史调用方一个都不用改）
        flow_no=flow_no or _next_flow_no(db, day),
    )
    db.add(record)
    db.flush()  # 先拿 record.id，供凭证挂 flow_id 用
    # 自动过账：按过账规则把流水翻译成借贷双分录的凭证（总账 / 复式记账）。
    # 凭证和流水一起 commit（由调用方提交），保证账实同步、可追溯。
    from app.services.ledger import post_journal_entry

    post_journal_entry(db, record)
    return record



# ============================================================================
# 融合改造：库存联动（开单自动加减库存 / 删单冲销 / 现存量 / 上下限预警）
#
# 四条规矩：
#   1. 库存由业务单据驱动，不靠人工记账 —— 采购单入库、销售单出库。
#   2. 每条流水都带 related_type + related_order_id，删单时按这两个字段冲销。
#   3. 单据没填仓库时回退到默认启用仓库；系统里一个仓库都没有就不写流水，
#      保留"还没建仓库也能开单"的兼容性。
#   4. 允许负库存：库存不足不阻断开单（线下生意常有先卖后进货），
#      但现存量与预警会明确标出来，不让它悄悄发生。
# ============================================================================

INBOUND_TYPES = {"inbound", "in", "purchase", "采购入库", "盘盈", "报溢", "调拨入"}

OUTBOUND_TYPES = {"outbound", "out", "sales", "销售出库", "盘亏", "报损", "调拨出"}



def _stock_delta(transaction_type: str, quantity: int) -> int:
    """把一条流水的「类型 + 数量」折算成对现存量的增减。"""
    qty = int(quantity or 0)
    kind = (transaction_type or "").strip().lower()
    if kind in INBOUND_TYPES:
        return abs(qty)
    if kind in OUTBOUND_TYPES:
        return -abs(qty)
    # 未识别的类型按「有符号数量」处理，兼容历史数据
    return qty



def _default_warehouse(db: Session) -> Warehouse | None:
    """默认仓库：优先启用中的，其次任意一个。单据未指定仓库时用它兜底。"""
    active = (
        db.query(Warehouse)
        .filter(Warehouse.is_active.is_(True))
        .order_by(Warehouse.id)
        .first()
    )
    return active or db.query(Warehouse).order_by(Warehouse.id).first()



def _resolve_warehouse_id(db: Session, given: int | None) -> int | None:
    """确定这张单进出哪个仓库。返回 None 表示系统里还没有仓库可用。

    **传入的 id 必须存在**：以前这里是 `return int(given)` 直接放行，
    于是传一个不存在的仓库 id 也能开单成功 —— 写出的库存流水指向一个
    没有的仓库，现存量里显示成"仓库-99999999"，谁也看不懂，只能手工清库。
    宁可 400 也不能让这种脏流水落库。
    """
    if given:
        if db.get(Warehouse, int(given)) is None:
            raise HTTPException(status_code=400, detail="所选仓库不存在，请先在仓库档案里建好")
        return int(given)
    fallback = _default_warehouse(db)
    return fallback.id if fallback is not None else None



def _apply_stock(
    db: Session,
    *,
    product_id: int,
    warehouse_id: int | None,
    quantity: int,
    transaction_type: str,
    unit_price: float = 0.0,
    unit_factor: int = 1,
    related_type: str | None = None,
    related_order_id: int | None = None,
    doc_no: str | None = None,
    note: str | None = None,
) -> InventoryTransaction | None:
    """写一条库存流水。没有仓库或数量为 0 时跳过（返回 None）。

    `quantity` / `unit_price` 都是**录入单位**口径；`unit_factor` 是
    「1 个录入单位 = 几个基本单位」。落库前统一换算成**基本单位**：

        流水 quantity  = quantity   × unit_factor    （基本单位，整数）
        流水 unit_price = unit_price ÷ unit_factor    （每基本单位成本）

    `unit_factor=1`（默认）与改动前**逐字节等价** —— IEEE754 下 `x*1` 与 `x/1.0`
    都是精确恒等（含 `inf`/`nan` 的传播规则也一致），所以全库既有调用点
    一行都不用改、也不需要传这个参数。

    ⚠️ **unit_price 必须与 quantity 是同一个口径。** 如果你的单价来自
    `_resolve_cost_price()`（它在价格为空时回落到 `products.purchase_price`，
    那是**基本单位**口径），就**不要**同时传 `unit_factor > 1` ——
    那会把档案价又除一次 factor，单价少 factor 倍。正确做法是先把单价换算成
    录入口径，或者先把 `quantity` 换算成基本单位再传 `unit_factor=1`。
    **绝不要两种口径混用。**
    """
    factor = int(unit_factor or 1)
    # factor = 0 会把数量清零 —— 而下面 `qty == 0` 是直接 return None，
    # 于是"整笔静默消失"：不报错、不记日志，一路潜伏到盘点才发现。
    # factor < 0 更糟 —— 它会**翻转出入库方向**（入库变出库）。
    # 两者都是"静默写出一条错流水"，宁可 400。理论上不可达（DB 有 CHECK(factor>=2)），
    # 但它是最后一道闸，成本一行。
    if factor < 1:
        raise HTTPException(status_code=400, detail="换算率必须是 ≥1 的整数")
    qty = int(quantity or 0) * factor
    if warehouse_id is None or qty == 0:
        return None
    record = InventoryTransaction(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=transaction_type,
        quantity=qty,
        unit_price=float(unit_price or 0.0) / factor,
        related_type=related_type,
        related_order_id=related_order_id,
        doc_no=doc_no,
        note=note,
    )
    db.add(record)
    return record



def _resolve_unit_factor(db: Session, product_id: int | None, unit_name: str | None) -> int:
    """把「录入单位名」解析成「1 个该单位 = 几个基本单位」。

    **服务端解析，绝不接受客户端传进来的 factor** —— 客户端能把自己那 3 箱
    说成 3000 盒，库存就凭空放大 1000 倍。客户端只负责说"我要用哪个单位"。

    返回 1 的三种情况（都表示"不需要换算"）：

      · `unit_name` 为空             —— 老客户端 / 未改的前端根本不发这个字段
      · `unit_name == products.unit` —— 用户选的就是基本单位
      · 商品不存在                   —— **保持旧行为**：旧代码对不存在的 product_id
        是放行的（`_resolve_item_snapshot` 会优雅降级），不要在这次改动里新引入一个 400

    其余情况：必须能在 `product_units` 里查到 `(product_id, unit_name)` 且
    `is_enabled = true`；查不到就 400。（**静默按 1 算**会让 3 箱入库变成 3 盒 ——
    少 factor 倍、无报错、无日志，所以这里宁可报错。）
    """
    name = (unit_name or "").strip()
    if not name or not product_id:
        return 1
    product = db.get(Product, int(product_id))
    if product is None:
        return 1
    # `products.unit` 本身就是基本单位 —— 它不在 product_units 里占行（见该模型 docstring）
    if name == (product.unit or "").strip():
        return 1
    row = (
        db.query(ProductUnit)
        .filter(
            ProductUnit.product_id == int(product_id),
            ProductUnit.unit_name == name,
            ProductUnit.is_enabled.is_(True),
        )
        .first()
    )
    if row is None or not row.factor:
        raise HTTPException(
            status_code=400,
            detail=(
                f"商品「{product.name}」没有辅助单位「{name}」，"
                f"请先在商品档案里配置，或改用基本单位「{product.unit or '—'}」。"
            ),
        )
    return int(row.factor)



def _revert_stock(db: Session, related_type: str, related_order_id: int) -> int:
    """删单时冲销该单产生的全部库存流水，返回冲销条数。"""
    rows = (
        db.query(InventoryTransaction)
        .filter(
            InventoryTransaction.related_type == related_type,
            InventoryTransaction.related_order_id == related_order_id,
        )
        .all()
    )
    for row in rows:
        db.delete(row)
    return len(rows)



def _revert_finance(db: Session, related_type: str, related_order_id: int) -> int:
    """删单时冲销该单产生的全部财务流水，返回冲销条数。

    与 `_revert_stock` 配对：凡是"审核即写财务"的单据（采购入库、销售开单、
    成品入库、委外加工等），删单时都必须把账一起抹掉，否则流水里会留下
    指向已删单据的孤儿（应收应付凭空多出一笔，对账时无从追溯）。
    """
    rows = (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.related_type == related_type,
            FinancialTransaction.related_order_id == related_order_id,
        )
        .all()
    )
    for row in rows:
        db.delete(row)
    return len(rows)


def _order_payment_flows(db: Session, order_id: int) -> list[FinancialTransaction]:
    """这张单据上挂着的**真实资金**流水（收款 / 付款）。

    ⚠️ 两个字段都要看，只认一个会漏（2026-10-18 实测踩坑）：
      · `transaction_type` = 业务类型（这是谁的钱：receipt / payment），
        `_register_payment` 写的就是它；
      · `related_type` = 来源单据类型，历史上沿用它标记收付款来源。
      目前两者都等于 receipt/payment，但 `POST /finance` 手工登记只写
      transaction_type、related_type 留空 —— 只按 related_type 过滤就会放过这类流水，
      用户"带收款的单据还能删"就是这么漏出去的。
    """
    return (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.related_order_id == order_id,
            or_(
                FinancialTransaction.transaction_type.in_(("receipt", "payment")),
                FinancialTransaction.related_type.in_(("receipt", "payment")),
            ),
        )
        .all()
    )


def _payment_flow_amounts(rows: list[FinancialTransaction]) -> tuple[float, float]:
    """把流水拆成（收款合计, 付款合计）。"""
    receipt_amount = round(
        sum(
            float(row.amount or 0)
            for row in rows
            if (row.transaction_type or row.related_type) == "receipt"
        ),
        2,
    )
    payment_amount = round(
        sum(
            float(row.amount or 0)
            for row in rows
            if (row.transaction_type or row.related_type) == "payment"
        ),
        2,
    )
    return receipt_amount, payment_amount


def _assert_no_payment_flows(db: Session, order_id: int, order_no: str) -> None:
    """单据上一旦登记过收付款，就**禁止删除**（2026-10-18）。

    背景：`_revert_finance` 只冲销"单据自己产生的"流水（related_type 是
    sales_out / purchase_in 这种），而 `receipt` / `payment` 是**人工登记的真实资金
    记录** —— 删单时它们不会被一起删掉，`related_order_id` 就指向了一张不存在的单据，
    变成无主账（孤儿流水）。

    这是财务数据里最不能出现的东西：钱在账上，单据没了，对账时无从追溯，
    而且 `_recalc_debt_chain` 之后的重算也失去了依据。

    所以这里在删单**之前**先拦一道，返回 409 + 结构化 detail（前端据此弹专门的
    拦截提示，不走"强制删除"那条二次确认 —— 这个场景不存在"确认一下就能删"）。

    ⚠️ 别改成"顺手把流水也删了"：那是把真实资金记录抹掉，比留孤儿更糟。
    """
    rows = _order_payment_flows(db, order_id)
    if not rows:
        return

    receipt_amount, payment_amount = _payment_flow_amounts(rows)
    parts = []
    if receipt_amount:
        parts.append(f"收款 ¥{receipt_amount:.2f}")
    if payment_amount:
        parts.append(f"付款 ¥{payment_amount:.2f}")

    raise HTTPException(
        status_code=409,
        detail={
            "code": "has_payment_flow",
            "message": (
                f"单据 {order_no} 存在资金流水 {len(rows)} 笔（{'、'.join(parts)}），无法删除。"
            ),
            "hint": (
                "收付款是真实资金记录，删单会让这笔钱变成无主账（孤儿流水），"
                "财务上不允许。请保留该单据；金额登错就再登记一笔冲销/退款，而不是删单。"
            ),
            "flow_count": len(rows),
            "receipt_amount": receipt_amount,
            "payment_amount": payment_amount,
        },
    )


def _assert_source_order_no_payment(db: Session, source_order, doc_label: str = "开单") -> None:
    """删开单（销售开单 / 采购入库）前，先看它**来源订单**上有没有资金流水。

    为什么删开单也要拦（2026-10-18 用户实测踩到：订单 #4230 / 开单 #4231）：
    开单删掉后，订单会停在 `completed` —— 既不能重新转单（`to-outbound` 挡 completed），
    又因为收了款不能删（`has_payment_flow`），变成一张谁都动不了的死锁单。
    表面看"删成功了"，实际是把一张带 1000 元收款的订单推进了死角。
    """
    if source_order is None:
        return
    rows = _order_payment_flows(db, source_order.id)
    if not rows:
        return

    receipt_amount, payment_amount = _payment_flow_amounts(rows)
    parts = []
    if receipt_amount:
        parts.append(f"收款 ¥{receipt_amount:.2f}")
    if payment_amount:
        parts.append(f"付款 ¥{payment_amount:.2f}")

    raise HTTPException(
        status_code=409,
        detail={
            "code": "has_source_payment_flow",
            "message": (
                f"该{doc_label}由订单 {source_order.order_no} 转入，而该订单已登记资金流水 "
                f"{len(rows)} 笔（{'、'.join(parts)}），无法删除。"
            ),
            "hint": (
                f"删掉这张{doc_label}后，订单会停在「已完成」——既不能重新转单、又因为收了款不能删，"
                "单据就彻底动不了了。请先在财务流水里处理这笔收付款（冲销/退款），再来删单。"
            ),
            "flow_count": len(rows),
            "receipt_amount": receipt_amount,
            "payment_amount": payment_amount,
            "source_order_id": source_order.id,
            "source_order_no": source_order.order_no,
        },
    )



def _net_stock_map(db: Session) -> dict[tuple[int, int], int]:
    """全库净库存：(product_id, warehouse_id) -> 现存量。"""
    result: dict[tuple[int, int], int] = {}
    for row in db.query(InventoryTransaction).all():
        key = (row.product_id, row.warehouse_id)
        result[key] = result.get(key, 0) + _stock_delta(row.transaction_type, row.quantity)
    return result



def _clean_order_lines(items, label: str = "单据"):
    """剔除整行空白的明细行；半填行直接 400，绝不静默落库。

    背景（2026-10-17 空行边界测试）：
      前端每张单据默认渲染若干空明细行。如果原样提交，后端会为每一行
      写一条「商品 0 / 数量 0」的垃圾记录 —— 污染明细表、合计与打印，
      而且没有任何报错。`quantity` 是 NOT NULL INTEGER，空值只能用 0
      表达，和「真的填了 0」无法区分，所以口径只能定在 `product_id`：

        ① product_id 缺失 / 0  → 这行压根不构成一条明细，**静默丢弃**；
        ② product_id 有值但 quantity <= 0 → **400**，绝不按 0 入账。
           （`_apply_stock` 对 qty==0 是直接 return，会变成
             "单据开出来了、库存一分没动" 的幽灵单，比报错更可怕。）

      兜底：全部行都被丢掉时也 400 —— 否则会留下一张「只有表头、
      没有明细」的空单。
    """
    kept = []
    for index, line in enumerate(items or [], start=1):
        try:
            product_id = int(getattr(line, "product_id", 0) or 0)
        except (TypeError, ValueError):
            product_id = 0
        if product_id <= 0:
            continue
        raw_qty = getattr(line, "quantity", 0)
        try:
            quantity = int(raw_qty or 0)
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"第 {index} 行选了商品但数量是「{raw_qty if raw_qty not in (None, '') else '空'}」，"
                    f"{label}的数量必须大于 0；用不到的明细行请把商品留空。"
                ),
            )
        kept.append(line)
    if not kept:
        raise HTTPException(
            status_code=400,
            detail=f"{label}至少要有一行有效商品明细（当前明细行都是空的）。",
        )
    return kept


def _resolve_item_snapshot(db: Session, line) -> tuple[str | None, str | None, str | None]:
    """明细行缺快照时，从商品档案补齐名称/规格/单位。"""
    if line.product_name and line.unit:
        return line.product_name, line.standards, line.unit
    if getattr(line, "product_id", None) is None:
        return line.product_name, line.standards, line.unit
    product = db.get(Product, line.product_id)
    if product is None:
        return line.product_name, line.standards, line.unit
    return (
        line.product_name or product.name,
        line.standards if line.standards is not None else product.standards,
        line.unit or product.unit,
    )



_CN_NUM = "零壹贰叁肆伍陆柒捌玖"

_CN_UNITS = ["", "拾", "佰", "仟"]

_CN_BIG = ["", "万", "亿", "兆"]



def _four_to_chinese(n: int) -> str:
    """0-9999 转中文数字（内部零压缩）。"""
    s = ""
    zero = False
    for pos in range(3, -1, -1):
        d = (n // (10**pos)) % 10
        if d == 0:
            zero = True
        else:
            if zero and s:
                s += "零"
            zero = False
            s += _CN_NUM[d] + _CN_UNITS[pos]
    return s



def _integer_to_chinese(n: int) -> str:
    """整数转中文大写。"""
    if n == 0:
        return "零"
    sections = []
    while n > 0:
        sections.append(n % 10000)
        n //= 10000
    out = ""
    for idx in range(len(sections) - 1, -1, -1):
        sec = sections[idx]
        if sec == 0:
            if out and not out.endswith("零"):
                out += "零"
            continue
        if out and sec < 1000 and not out.endswith("零"):
            out += "零"
        out += _four_to_chinese(sec) + _CN_BIG[idx]
    return out.rstrip("零") or "零"



def amount_to_chinese(amount: float) -> str:
    """金额转财务大写，例如 42640.00 → 肆万贰仟陆佰肆拾元整。对账单与合同必备。"""
    total_fen = int(round(abs(float(amount or 0.0)) * 100))
    yuan, rem = divmod(total_fen, 100)
    jiao, fen = divmod(rem, 10)

    result = _integer_to_chinese(yuan) + "元"
    if jiao == 0 and fen == 0:
        result += "整"
    else:
        if jiao:
            result += _CN_NUM[jiao] + "角"
        elif fen:
            result += "零"
        if fen:
            result += _CN_NUM[fen] + "分"
    if float(amount or 0.0) < 0:
        result = "负" + result
    return result



# 往来账方向：不同业务类型对余额的影响
_BALANCE_INCREASE = {
    "customer": {"receivable", "income", "sales_return"},
    "supplier": {"payable", "expense", "purchase_return"},
}

_BALANCE_DECREASE = {
    "customer": {"receipt", "sales_out"},
    "supplier": {"payment", "purchase_in"},
}



def _signed_amount(party_type: str, record: FinancialTransaction) -> float:
    """按往来账口径给出带符号金额：增加为正，减少为负。"""
    amount = float(record.amount or 0.0)
    if record.transaction_type in _BALANCE_INCREASE.get(party_type, set()):
        return amount
    if record.transaction_type in _BALANCE_DECREASE.get(party_type, set()):
        return -amount
    return 0.0



# ============================================================================
# 融合改造：打印模板（后端 pymupdf 直出 PDF，嵌入中文字体）
# ============================================================================


def _s(v) -> str:
    """None 安全转字符串。"""
    return "" if v is None else str(v)



def _wants_json(request: Request) -> bool:
    """请求方是否要 JSON(base64) 形式的 PDF。见 `_pdf_response` 里的说明。"""
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept



def _attachment_response(content: bytes, filename: str, media_type: str) -> Response:
    """带中文文件名的下载响应（ASCII 兜底 + RFC 5987，避免 header 编码错误）。"""
    from urllib.parse import quote

    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "download"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": disposition,
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


# A2 标准版的条款默认值：合同没填的变量用这里的行业常规表述兜底，
# 保证打印出来的是一份**完整可用**的合同，而不是一堆空白占位。
_A2_DEFAULTS = {
    "quality_standard": "国家标准、行业标准或双方书面确认的技术规格",
    "package_standard": "符合运输要求的出厂包装，包装物由乙方提供并承担费用",
    "delivery_method": "乙方送货至甲方指定地点",
    "freight_bearer": "运输费用由乙方承担；货物毁损、灭失的风险自甲方验收合格之日起转移",
    "warranty_terms": "质保期 12 个月，自验收合格之日起算；质保期内非人为损坏由乙方负责免费修理或更换",
    "payment_terms": "货到验收合格并收到合规发票后 30 日内付清全款",
    "invoice_requirement": "乙方开具与合同金额一致的增值税专用发票",
    "dispute_resolution": "提交合同签订地人民法院诉讼解决",
}

_A2_DEFAULT_INSPECTION_DAYS = 7

_A2_DEFAULT_OBJECTION_DAYS = 15

_A2_DEFAULT_PENALTY_RATE = 0.0005  # 万分之五

_A2_DEFAULT_COPIES = 2



def _contract_items(db: Session, contract_id: int) -> list[ContractItem]:
    return (
        db.query(ContractItem)
        .filter(ContractItem.contract_id == contract_id)
        .order_by(ContractItem.id)
        .all()
    )



def _quotation_items(db: Session, quotation_id: int) -> list[QuotationItem]:
    return (
        db.query(QuotationItem)
        .filter(QuotationItem.quotation_id == quotation_id)
        .order_by(QuotationItem.id)
        .all()
    )



# ============================================================================
# 采购退货（对齐浩技云「采购管理 → 退货管理」）
#
# 退货是采购入库的**反向**单据：货退回给供应商，库存减少（outbound），
# 应付冲减（purchase_return 财务流水，方向 out、金额记负数）。
# 独立成表，不塞进 purchase_orders —— 入库与退货的库存/财务方向相反。
# ============================================================================


def _purchase_return_items(db: Session, return_id: int) -> list[PurchaseReturnItem]:
    return db.query(PurchaseReturnItem).filter(PurchaseReturnItem.purchase_return_id == return_id).all()



# ============================================================================
# 销售退货（对齐浩技云「销售管理 → 销售退货」）
#
# 退货是销售开单（出库）的**反向**单据：客户把货退回来，库存增加（inbound），
# 应收冲减（sales_return 财务流水，金额记负数、方向 in）。
# 独立成表，与 sales_orders 分开 —— 出库与退货的库存/财务方向相反。
# ============================================================================


def _sales_return_items(db: Session, return_id: int) -> list[SalesReturnItem]:
    return db.query(SalesReturnItem).filter(SalesReturnItem.sales_return_id == return_id).all()


# ============================================================================
# 库存调拨（对齐浩技云「库存管理 → 调拨管理」）
#
# 调拨是同一企业内部的库存位置转移：货物从调出仓库搬到调入仓库，总量与资产
# 总额都不变。因此它**只写库存流水、不写财务流水**（不产生应收应付与成本）。
# 每条明细生成两条方向相反的流水（调出 outbound / 调入 inbound），共用
# related_type="inv_transfer"，删单时 _revert_stock 一次把两条都冲掉。
# ============================================================================


def _transfer_items(db: Session, transfer_id: int) -> list[InventoryTransferItem]:
    return (
        db.query(InventoryTransferItem)
        .filter(InventoryTransferItem.inventory_transfer_id == transfer_id)
        .all()
    )



# ============================================================================
# 库存盘点（对齐浩技云「库存管理 → 盘点管理」）
#
# 盘点是**账实核对**：账面数由系统按现存量带出、实盘数由人录入，差额就是盈亏。
# 盈亏方向由**明细行自己**决定（diff > 0 盘盈 inbound、diff < 0 盘亏 outbound），
# 所以一张盘点单会同时写两类流水，共用 related_type="inv_check" + 本单 id，
# 删单时 _revert_stock 一次全冲，账实同时回到盘点前。
#
# 与调拨同属**纯库存单据**：只调整现存量、不写财务流水（盘盈盘亏的账务处理
# 由用户走日常收支，系统不擅自记账）。
# ============================================================================


def _stocktaking_items(db: Session, check_id: int) -> list[StocktakingItem]:
    return (
        db.query(StocktakingItem)
        .filter(StocktakingItem.stocktaking_id == check_id)
        .all()
    )



def _resolve_cost_price(db: Session, product_id: int | None, given: float | None) -> float:
    """明细未填成本单价时，从商品档案带出进价 —— 盘点/报损报溢只录数量时也能算盈亏金额。"""
    price = float(given or 0.0)
    if price or not product_id:
        return price
    product = db.get(Product, int(product_id))
    return float(getattr(product, "purchase_price", 0.0) or 0.0) if product else 0.0



# ============================================================================
# 库存报损报溢（对齐浩技云「库存管理 → 报损报溢」）
#
# 报损与报溢是同一张表的两个方向，用 adjust_type 区分：
#   scrap    报损 → 库存减少（outbound）
#   overflow 报溢 → 库存增加（inbound）
# 明细数量恒正，方向完全由单据头决定，避免一张单里正负混排。
#
# 与调拨、盘点同属**纯库存单据**：只写库存流水、不写财务流水。
# ============================================================================


def _adjust_items(db: Session, adjust_id: int) -> list[InventoryAdjustmentItem]:
    return (
        db.query(InventoryAdjustmentItem)
        .filter(InventoryAdjustmentItem.inventory_adjustment_id == adjust_id)
        .all()
    )



# ============================================================================
# 第 3 批 · 生产类之一：生产计划（对齐浩技云「生产管理 → 生产计划」）
#
# 生产计划是**排产意图**而非业务发生 —— 只说明"什么时候、在哪个车间仓、生产
# 多少件什么产品"，**既不写库存流水、也不写财务流水**（与报价单同属前置单据，
# 测试用反向断言锁死）。它是整条生产链路的起点：
#   MRP 运算按它展开物料需求 → 生产领料 → 生产退料 → 成品入库 → 委外加工。
# ============================================================================


def _production_plan_items(db: Session, plan_id: int) -> list[ProductionPlanItem]:
    return (
        db.query(ProductionPlanItem)
        .filter(ProductionPlanItem.production_plan_id == plan_id)
        .order_by(ProductionPlanItem.id)
        .all()
    )



# ============================================================================
# 第 3 批 · 生产类之二：MRP 运算（物料需求计划）
#
# MRP 不是单据，是**计算引擎**：把"要生产多少成品"按 BOM 逐层展开成"需要多少
# 原材料"，再拿现存量一减，得出每种物料的**净需求（缺料）**。
#
# 三个入口：
#   GET  /mrp/requirements      单成品试算（product_id + quantity）
#   POST /mrp/run               多成品批量运算（body: items[]）
#   GET  /production-plans/{id}/mrp   按生产计划整单运算
#
# 运算不写任何单据、不动库存财务 —— 它只给建议，采不采纳由人决定。
# ============================================================================


def _bom_children_map(db: Session) -> dict[int, list[tuple[int, int]]]:
    """BOM 树 → {父件商品 id: [(子件商品 id, 单位用量)]}。

    现有 BOM 表是 `production_boms`（parent_id 自引用树），一行表达
    "product_id 由 component_product_id 组成、单位用量 quantity"。
    """
    result: dict[int, list[tuple[int, int]]] = {}
    for row in db.query(BillOfMaterial).all():
        if row.product_id is None or row.component_product_id is None:
            continue
        per = int(row.quantity or 1)
        if per <= 0:
            per = 1
        result.setdefault(int(row.product_id), []).append((int(row.component_product_id), per))
    return result



def _on_hand_by_product(db: Session, warehouse_id: int | None) -> dict[int, int]:
    """现存量：指定仓库则只看该仓，否则全库合计。"""
    result: dict[int, int] = {}
    for (pid, wid), qty in _net_stock_map(db).items():
        if warehouse_id is not None and wid != warehouse_id:
            continue
        result[pid] = result.get(pid, 0) + int(qty)
    return result



# ============================================================================
# 第 3 批 · 生产类之三：生产领料 / 生产退料
#
# 领料 = 把原材料从仓库发到车间（原材料现存量减少 outbound）；
# 退料 = 车间把余料退回仓库（原材料现存量增加 inbound）。
# 两者**完全镜像**，只是库存方向相反，都属于**纯库存单据**：
# 只动库存、不写财务流水（材料成本归集落在下游的成品入库环节）。
# ============================================================================


def _material_issue_items(db: Session, issue_id: int) -> list[MaterialIssueItem]:
    return (
        db.query(MaterialIssueItem)
        .filter(MaterialIssueItem.material_issue_id == issue_id)
        .order_by(MaterialIssueItem.id)
        .all()
    )



# —————————————————————— 生产退料（领料的反向单据）——————————————————————


def _material_return_items(db: Session, return_id: int) -> list[MaterialReturnItem]:
    return (
        db.query(MaterialReturnItem)
        .filter(MaterialReturnItem.material_return_id == return_id)
        .order_by(MaterialReturnItem.id)
        .all()
    )



def _finished_goods_items(db: Session, receipt_id: int) -> list[FinishedGoodsReceiptItem]:
    return (
        db.query(FinishedGoodsReceiptItem)
        .filter(FinishedGoodsReceiptItem.finished_goods_receipt_id == receipt_id)
        .order_by(FinishedGoodsReceiptItem.id)
        .all()
    )



# ============================================================================
# 第 3 批 · 生产类之六：委外加工（生产类收官）
#
# 委外加工 = 把材料发给外协厂加工、加工完收回成品，一张单两个方向：
#   发出材料 outbound（原材料减少）+ 收回成品 inbound（成品增加），
#   两类流水共用 related_type="outsourcing" + 本单 id，删单一次全冲。
# 同时按加工费产生**应付**（payable，挂外协厂）—— 既动库存也动财务。
# ============================================================================


def _outsourcing_items(db: Session, order_id: int) -> list[OutsourcingItem]:
    return (
        db.query(OutsourcingItem)
        .filter(OutsourcingItem.outsourcing_order_id == order_id)
        .order_by(OutsourcingItem.id)
        .all()
    )
