"""项目资金试算接口 —— **只读 + 纯计算**（v1.81.0，2026-10-26）

用户的红线原话：「绝对不能因为测算数据污染了真实的业务数据库」。
所以这个文件里**没有一处 `db.commit()` / `db.add()` / `db.delete()`**：

| 接口 | 做什么 | 碰不碰库 |
|---|---|---|
| `POST /compute` | 把前端填的数喂给 `project_calc.compute()` | 完全不碰（连 Session 都不取） |
| `GET /defaults` | 返回默认税率/费率 + 敏感性天数 | 完全不碰 |
| `GET /sources` | 列可选单据（销售单 / 采购单 / 合同） | 只 SELECT |
| `GET /prefill/{source}/{id}` | 从单据读一份**内存快照**回填表单 | 只 SELECT |

`prefill` 是"可以选现有单据、但绝不动它"的唯一实现方式：读出来的数进前端就变成
自由变量，后续所有编辑都只发生在浏览器里。

权限口径与「报表中心」一致：登录即可读，不新增权限点。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.contract import Contract, ContractItem
from app.models.customer import Customer
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem
from app.models.sales_order import SalesOrder, SalesOrderItem
from app.models.supplier import Supplier
from app.services.project_calc import SENSITIVITY_DAYS, compute, default_settings

router = APIRouter(prefix="/project-calc", tags=["project-calc"])

Source = Literal["sale", "purchase", "contract"]


class CalcLine(BaseModel):
    """测算明细行：一行 = 一个产品（同一产品可拆多行）。"""

    product_name: str = ""
    unit: str = ""
    qty: Decimal = Decimal("0")            # 销售数量
    cost_qty: Decimal | None = None        # 采购数量；空 = 取 qty（"进一批卖一批"）
    sale_price: Decimal = Decimal("0")     # 销售含税单价
    cost_price: Decimal = Decimal("0")     # 采购含税单价
    has_invoice: bool = True               # 是否取得专票（False → 进项按 0）


class CalcSettings(BaseModel):
    """可调参数，默认值与《税额试算表 v6》/ 现行小微口径一致。"""

    vat_rate: Decimal = Decimal("0.13")
    surcharge_half: bool = True            # 六税两费减半
    city_rate: Decimal = Decimal("0.07")
    edu_rate: Decimal = Decimal("0.03")
    ledu_rate: Decimal = Decimal("0.02")
    water_rate: Decimal = Decimal("0.00045")
    stamp_rate: Decimal = Decimal("0.0003")
    income_rate: Decimal = Decimal("0.05")
    # —— 资金占用（Excel 无，本模块新增）——
    capital_daily_rate: Decimal = Decimal("0.0002")   # 0.02%/日 ≈ 年化 7.30%
    pay_days: int = 30                    # 付款周期：多久付给上游
    collect_days: int = 60                # 回款周期：多久收回货款
    prepay: Decimal = Decimal("0")        # 下游预收（抵减垫资）
    prepay_supplier: Decimal = Decimal("0")  # 上游已付定金（抵减垫资）
    include_income_tax_in_advance: bool = False  # 所得税是否计入垫资（默认不计）


class CalcRequest(BaseModel):
    lines: list[CalcLine] = Field(default_factory=list)
    settings: CalcSettings = Field(default_factory=CalcSettings)
    label: str = ""


@router.get("/defaults")
def calc_defaults() -> dict:
    """默认参数 + 敏感性天数。前端「恢复默认」按钮与图表刻度都从这里取。"""
    return {"settings": default_settings(), "sensitivity_days": list(SENSITIVITY_DAYS)}


@router.post("/compute")
def compute_project(payload: CalcRequest) -> dict:
    """纯计算：入参不落库，出参全是两位小数字符串。

    这里刻意把 Decimal 全部转成字符串再交给算核 —— 让"精度"只在一个地方
    （`project_calc` 的 Decimal 上下文）负责，不在 Pydantic/JSON 之间来回转型。
    """
    body = {
        "lines": [
            {
                "product": line.product_name,
                "unit": line.unit,
                "qty": str(line.qty),
                "cost_qty": None if line.cost_qty is None else str(line.cost_qty),
                "sale_price": str(line.sale_price),
                "cost_price": str(line.cost_price),
                "has_invoice": line.has_invoice,
            }
            for line in payload.lines
        ],
        "settings": {
            key: (value if isinstance(value, bool) else str(value))
            for key, value in payload.settings.model_dump().items()
        },
    }
    result = compute(body)
    result["label"] = payload.label
    return result


def _money_str(value) -> str:
    """单据上的金额 → 两位小数字符串（单据里是 Numeric，可能是 None）。"""
    if value is None:
        return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _qty_str(value) -> str:
    """数量：整数就不带 `.0`，小数保留原样（"3119" 比 "3119.0" 看着舒服）。"""
    if value is None:
        return "0"
    number = Decimal(str(value))
    normalized = number.normalize()
    return str(normalized.quantize(Decimal("1"))) if normalized == normalized.to_integral() else str(normalized)


@router.get("/sources")
def list_sources(
    source: Source = "sale",
    keyword: str = "",
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """可选单据清单（给「从单据带出」下拉框用）。只读，最近 50 条。"""
    kw = (keyword or "").strip()
    like = f"%{kw}%"

    if source == "sale":
        stmt = select(SalesOrder, Customer.name).join(
            Customer, Customer.id == SalesOrder.customer_id, isouter=True
        )
        if kw:
            stmt = stmt.where(or_(SalesOrder.order_no.ilike(like), Customer.name.ilike(like)))
        rows = [
            {
                "id": order.id,
                "doc_no": order.order_no,
                "date": order.order_date or "",
                "party": party or "",
                "amount": _money_str(order.total_amount),
                "status": order.status,
                "tag": "开单" if order.doc_type == "outbound" else "订单",
            }
            for order, party in db.execute(stmt.order_by(SalesOrder.id.desc()).limit(limit)).all()
        ]
        return {"source": source, "rows": rows}

    if source == "purchase":
        stmt = select(PurchaseOrder, Supplier.name).join(
            Supplier, Supplier.id == PurchaseOrder.supplier_id, isouter=True
        )
        if kw:
            stmt = stmt.where(or_(PurchaseOrder.order_no.ilike(like), Supplier.name.ilike(like)))
        rows = [
            {
                "id": order.id,
                "doc_no": order.order_no,
                "date": order.order_date or "",
                "party": party or "",
                "amount": _money_str(order.total_amount),
                "status": order.status,
                "tag": "采购单",
            }
            for order, party in db.execute(stmt.order_by(PurchaseOrder.id.desc()).limit(limit)).all()
        ]
        return {"source": source, "rows": rows}

    stmt = select(Contract)
    if kw:
        stmt = stmt.where(or_(Contract.contract_no.ilike(like), Contract.party_name.ilike(like)))
    rows = [
        {
            "id": contract.id,
            "doc_no": contract.contract_no,
            "date": contract.sign_date or "",
            "party": contract.party_name or "",
            "amount": _money_str(contract.total_amount),
            "status": contract.status,
            "tag": "采购合同" if contract.direction == "in" else "销售合同",
        }
        for contract in db.execute(stmt.order_by(Contract.id.desc()).limit(limit)).scalars().all()
    ]
    return {"source": source, "rows": rows}


@router.get("/prefill/{source}/{doc_id}")
def prefill(source: Source, doc_id: int, db: Session = Depends(get_db)) -> dict:
    """从单据读一份**内存快照**回填表单。

    注意三条：
      1. 返回的是普通 dict，前端拿去做自由变量 —— 之后改数不会回写任何单据；
      2. 单据里的单价一律**当作含税单价**（本系统销售/采购金额都是价税合计口径），
         若某张单据录的是不含税价，页面上会提示你自己按票面核一遍，模块不猜；
      3. 一条明细都没有时也正常返回空 lines，让用户手填，不抛 500。
    """
    notes: list[str] = ["单价按单据原值视为含税单价，请按实际票面核对；测算结果不写回单据。"]

    if source == "sale":
        order = db.get(SalesOrder, doc_id)
        if order is None:
            raise HTTPException(status_code=404, detail="销售单不存在")
        party = db.get(Customer, order.customer_id)
        items = db.execute(
            select(SalesOrderItem).where(SalesOrderItem.sales_order_id == doc_id)
        ).scalars().all()
        return {
            "source": source,
            "label": f"销售单 {order.order_no}",
            "meta": {
                "doc_no": order.order_no,
                "date": order.order_date or "",
                "party": (party.name if party else "") or "",
                "amount": _money_str(order.total_amount),
            },
            "lines": [
                {
                    "product_name": item.product_name or "",
                    "unit": item.unit or "",
                    "qty": _qty_str(item.quantity),
                    "cost_qty": None,
                    "sale_price": _money_str(item.unit_price),
                    "cost_price": "0.00",
                    "has_invoice": True,
                }
                for item in items
            ],
            "notes": notes,
        }

    if source == "purchase":
        order = db.get(PurchaseOrder, doc_id)
        if order is None:
            raise HTTPException(status_code=404, detail="采购单不存在")
        party = db.get(Supplier, order.supplier_id)
        items = db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == doc_id)
        ).scalars().all()
        return {
            "source": source,
            "label": f"采购单 {order.order_no}",
            "meta": {
                "doc_no": order.order_no,
                "date": order.order_date or "",
                "party": (party.name if party else "") or "",
                "amount": _money_str(order.total_amount),
            },
            # 采购单先落「成本侧」：销售数量与卖价留给用户按实际合同填
            "lines": [
                {
                    "product_name": item.product_name or "",
                    "unit": item.unit or "",
                    "qty": _qty_str(item.quantity),
                    "cost_qty": _qty_str(item.quantity),
                    "sale_price": "0.00",
                    "cost_price": _money_str(item.unit_price),
                    "has_invoice": True,
                }
                for item in items
            ],
            "notes": notes + ["采购数量已落在「采购数量」列；销售数量/卖价请按实际合同补。"],
        }

    contract = db.get(Contract, doc_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    items = db.execute(
        select(ContractItem).where(ContractItem.contract_id == doc_id)
    ).scalars().all()
    buy_side = contract.direction == "in"
    return {
        "source": source,
        "label": f"合同 {contract.contract_no}",
        "meta": {
            "doc_no": contract.contract_no,
            "date": contract.sign_date or "",
            "party": contract.party_name or "",
            "amount": _money_str(contract.total_amount),
        },
        "lines": [
            {
                "product_name": item.product_name or "",
                "unit": item.unit or "",
                "qty": _qty_str(item.quantity),
                "cost_qty": _qty_str(item.quantity),
                "sale_price": "0.00" if buy_side else _money_str(item.unit_price),
                "cost_price": _money_str(item.unit_price) if buy_side else "0.00",
                "has_invoice": True,
            }
            for item in items
        ],
        "notes": notes + [
            "采购合同" if buy_side else "销售合同",
            "合同数量按合同原值落列；实际发货/收货数量请按结算单调整。",
        ],
    }
