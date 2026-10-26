# -*- coding: utf-8 -*-
"""智能体接口（第四阶段预留 · 2026-10-20）。

给微信小程序 / 智能体调用留的**只读**汇总口。骨架原则：

1. **带鉴权**：全部走 `get_current_user`（OAuth2 Bearer token）——
   这组接口是给"外人"调的，绝不能像业务接口那样无 token 也放行；
2. **只读**：只有 GET，不改任何数据。写操作将来要么走既有业务接口、
   要么单开带审批的命令口，这里永远不给；
3. **口径复用**：金额尽量用与报表/完结闸同一套模型查询，避免智能体
   说出第二套数。Decimal 一律 `float()` 收口（裸 dict 出参 → jsonable_encoder）。

已实现：
  GET /api/v1/agent/summary        经营概览（档案数、今日销售、应收/应付、订单状态分布）
预留（返回 501，先占路径好让调用方对接）：
  GET /api/v1/agent/stock-alerts   库存预警明细
  GET /api/v1/agent/orders         单据查询（按单号/往来单位，只返回摘要不返回明细金额细节）
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.inventory import InventoryTransaction
from app.models.product import Product
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier
from app.models.user import User

router = APIRouter(prefix="/agent", tags=["agent"])


def _f(value) -> float:
    """裸 dict 出参的 Decimal 收口（详见 MEMORY §4 三条 JSON 出参路）。"""
    return float(value or 0)


@router.get("/summary")
def agent_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """经营概览：智能体开场白要的那几个数。

    口径注释（与报表中心一致）：
      · 销售只算 doc_type=outbound（order 是订货意向，没发货不进账）；
      · 应收余额 = 财务流水 receivable 方向累计 − 已收，这里用流水表粗算，
        精确到单的口径在 `erp_sales._apply_settlement_fields`（完结闸）。
    """
    today = date.today()
    # ⚠️ order_date 是 String 列（varchar），过滤必须用 isoformat 字符串，
    # 传 date 对象会报 "character varying = date" 类型错（实测 500 抓到）
    today_str = today.isoformat()
    counts = {
        "customers": db.query(func.count(Customer.id)).scalar() or 0,
        "suppliers": db.query(func.count(Supplier.id)).scalar() or 0,
        "products": db.query(func.count(Product.id)).scalar() or 0,
    }

    today_sales = (
        db.query(func.coalesce(func.sum(SalesOrder.total_amount), 0))
        .filter(SalesOrder.doc_type == "outbound", SalesOrder.order_date == today)
        .scalar()
    )
    today_sales_count = (
        db.query(func.count(SalesOrder.id))
        .filter(SalesOrder.doc_type == "outbound", SalesOrder.order_date == today)
        .scalar()
    )

    # 应收/应付粗口径（实测 2026-10-20）：
    #   开单记 receivable/payable（开单应收/应付），收款/付款是独立的
    #   transaction_type='receipt'/'payment' —— 不是方向对冲，别用 direction 查"已收"。
    receivable = (
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0))
        .filter(FinancialTransaction.transaction_type == "receivable")
        .scalar()
    )
    received = (
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0))
        .filter(FinancialTransaction.transaction_type == "receipt")
        .scalar()
    )
    payable = (
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0))
        .filter(FinancialTransaction.transaction_type == "payable")
        .scalar()
    )
    paid = (
        db.query(func.coalesce(func.sum(FinancialTransaction.amount), 0))
        .filter(FinancialTransaction.transaction_type == "payment")
        .scalar()
    )

    order_status_rows = (
        db.query(SalesOrder.status, func.count(SalesOrder.id))
        .filter(SalesOrder.doc_type.in_(("order", "outbound")))
        .group_by(SalesOrder.status)
        .all()
    )
    purchase_status_rows = (
        db.query(PurchaseOrder.status, func.count(PurchaseOrder.id))
        .group_by(PurchaseOrder.status)
        .all()
    )

    return {
        "generated_for": current_user.username,
        "generated_at": today.isoformat(),
        "counts": counts,
        "today": {
            "sales_amount": _f(today_sales),
            "sales_orders": int(today_sales_count or 0),
        },
        "receivable": {
            "total": _f(receivable),
            "received": _f(received),
            "outstanding": _f(receivable) - _f(received),
        },
        "payable": {
            "total": _f(payable),
            "paid": _f(paid),
            "outstanding": _f(payable) - _f(paid),
        },
        "sales_orders_by_status": {row[0]: int(row[1] or 0) for row in order_status_rows},
        "purchase_orders_by_status": {row[0]: int(row[1] or 0) for row in purchase_status_rows},
    }


@router.get("/stock-alerts")
def agent_stock_alerts(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """库存预警明细（骨架）：先返回 501 占位，第二阶段接 erp_stock_alert 的现成查询。"""
    raise HTTPException(status_code=501, detail="库存预警明细接口建设中，第二阶段开放")


@router.get("/orders")
def agent_orders(
    keyword: str = Query("", description="单号 / 往来单位名称"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """单据查询（骨架）：先返回 501 占位。上线时只返回单据摘要，不返回金额明细。"""
    raise HTTPException(status_code=501, detail="单据查询接口建设中，第二阶段开放")


# ===========================================================================
# 智能指令派发（2026-10-23）
# ===========================================================================
# 与上面三个"给外部智能体调的 GET"不同，这一条是**给本系统自己的搜索框**用的：
# 用户在输入框里打一句人话（"给我周广平的对账单"），这里解析意图 + 认人 + 取数，
# 返回前端能直接渲染成卡片的结构。
#
# 三个约定：
#   · **只读**：不生成、不改任何数据；"生成对账单/合同"的落库动作仍然由用户
#     在对应页面上点确认（`action` 只是意图标签，不是执行结果）；
#   · **带鉴权**：与上面三个接口一致，走 `get_current_user`；
#   · **口径复用**：对账单金额复用 `erp_statement._build_fusion_rows`，
#     与对账单页面同一套引擎（详见 services/agent_command.py 的模块注释）。

class AgentDispatchIn(BaseModel):
    """一条自然语言指令。`include_candidates` 用于"没认出来时要不要给候选"。"""

    text: str = Field(..., min_length=1, max_length=200)
    include_candidates: bool = True


@router.post("/dispatch", summary="智能指令：自然语言 → 意图 + 数据")
def agent_dispatch(
    payload: AgentDispatchIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """把一句话变成 `{type, party, matched_data, goto, message}`。

    解析走规则（`services/agent_command.parse_command`），接本地大模型的替换点
    也写在那个模块末尾 —— 换解析器不影响这里的数据装配。
    """
    from app.services.agent_command import dispatch as run_dispatch

    result = run_dispatch(db, payload.text)
    if not payload.include_candidates:
        result["candidates"] = []
    return result


@router.get("/suggest", summary="智能指令：输入即提示（认人不下结论）")
def agent_suggest(
    q: str = Query("", max_length=100, description="输入框里的半截话，如 zgp / 周 / 湖南华邦"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """实时下拉的数据源：只认人不取数，毫秒级返回。

    前端每敲一个字（180ms 防抖）都会来一次，所以这条**必须轻**：
    复用 `resolve_parties` 的字面 + 拼音首字母 + 联系人三层匹配，
    最多回 6 条 `{type, id, name, code, contact, matched_by}`。
    """
    from app.services.agent_command import suggest_parties

    return {"query": q, "suggestions": suggest_parties(db, q)}
