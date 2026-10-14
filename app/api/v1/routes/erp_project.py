"""项目管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

项目台账与成本归集。
"""

from __future__ import annotations

from app.db.session import get_db
from app.models.finance import DOC_TYPES, FinancialTransaction
from app.models.project import PROJECT_STATUS, Project
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import (
    _paginate,
)

router = APIRouter(prefix="", tags=["erp"])




@router.get("/projects")
def list_projects(db: Session = Depends(get_db), skip: int = 0, limit: int | None = None) -> list[ProjectRead]:
    items = _paginate(db.query(Project).order_by(Project.id.desc()), skip, limit).all()
    return items



@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    existing = db.query(Project).filter(Project.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project code already exists")
    item = Project(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)) -> Project:
    """改项目（进度 / 状态 / 预算 / 负责人 / 截止日期 / 备注）。

    在此之前项目**只有"新建"和"列表"** —— 建完之后进度永远停在 0、状态永远停在
    "计划中"，改不了。一个改不了的项目列表等于没有项目模块。
    """
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in PROJECT_STATUS:
        raise HTTPException(status_code=400, detail=f"项目状态只能是 {' / '.join(PROJECT_STATUS.values())}")
    if "progress" in data and data["progress"] is not None:
        if not 0 <= int(data["progress"]) <= 100:
            raise HTTPException(status_code=400, detail="进度必须是 0~100")
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item



@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> Response:
    """删项目。

    **已经有单据或流水挂在这个项目上时拒绝删除** —— 删掉项目，那些成本/收入就变成
    挂在空气上的数字，报表里再也归集不回来，而且看不出来。要做的是把项目置为"已关闭"。
    """
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    flows = db.query(FinancialTransaction).filter(FinancialTransaction.project_id == project_id).count()
    orders = db.query(SalesOrder).filter(SalesOrder.project_id == project_id).count() + db.query(
        PurchaseOrder
    ).filter(PurchaseOrder.project_id == project_id).count()
    if flows or orders:
        raise HTTPException(
            status_code=409,
            detail=(
                f"这个项目上已经挂了 {flows} 条财务流水、{orders} 张单据，不能删除。"
                "请把状态改成「已关闭」。"
            ),
        )
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/projects/{project_id}/cost")
def project_cost(project_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """项目成本归集：把挂在这个项目上的财务流水按性质汇总。

    这是项目模块**存在的意义** —— 一个项目赚不赚钱，只能从"收入 − 成本 − 费用"看出来，
    而这个数字必须来自财务流水（单据自动写的那些），不能靠人再录一遍。

    归集口径（与 `transaction_type` 对齐）：
      · 收入：`receivable`（赊销应收）/ `receipt`（收款）/ `income`
      · 成本：`cost`（生产成本结转）/ `payable`（赊购应付中属于成本的部分）
      · 费用：`expense`（日常支出）
    按 `related_type` 再分组，让用户看清"这笔钱是买货花的还是报销花的"。
    """
    from app.models.finance import DOC_TYPES

    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    rows = (
        db.query(FinancialTransaction)
        .filter(FinancialTransaction.project_id == project_id)
        .order_by(FinancialTransaction.id.asc())
        .all()
    )
    INCOME = {"receivable", "receipt", "income", "overflow"}
    COST = {"cost", "payable"}
    buckets = {"income": 0.0, "cost": 0.0, "expense": 0.0, "other": 0.0}
    by_source: dict[str, dict[str, object]] = {}
    for row in rows:
        amount = float(row.amount or 0.0)
        kind = str(row.transaction_type or "")
        if kind in INCOME:
            buckets["income"] += amount
        elif kind in COST:
            buckets["cost"] += amount
        elif kind == "expense":
            buckets["expense"] += amount
        else:
            buckets["other"] += amount
        key = str(row.related_type or kind or "手工")
        entry = by_source.setdefault(
            key,
            {"related_type": key, "label": DOC_TYPES.get(key, key), "count": 0, "amount": 0.0},
        )
        entry["count"] = int(entry["count"]) + 1
        entry["amount"] = round(float(entry["amount"]) + amount, 2)

    gross_profit = round(buckets["income"] - buckets["cost"] - buckets["expense"], 2)
    budget = float(item.budget or 0.0)
    return {
        "project": {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "manager": item.manager,
            "status": item.status,
            "progress": item.progress,
            "budget": budget,
            "deadline": item.deadline,
        },
        "summary": {
            "income": round(buckets["income"], 2),
            "cost": round(buckets["cost"], 2),
            "expense": round(buckets["expense"], 2),
            "other": round(buckets["other"], 2),
            "gross_profit": gross_profit,
            # 毛利率只在有收入时才有意义；没收入时返回 None，不要返回 0 让人误以为不赚钱
            "gross_margin_rate": round(gross_profit / buckets["income"] * 100, 2) if buckets["income"] else None,
            "budget_used": round(buckets["cost"] + buckets["expense"], 2),
            "budget_usage_rate": (
                round((buckets["cost"] + buckets["expense"]) / budget * 100, 2) if budget else None
            ),
            "flow_count": len(rows),
        },
        "by_source": sorted(by_source.values(), key=lambda x: -float(x["amount"])),
        "flows": [
            {
                "id": row.id,
                "transaction_type": row.transaction_type,
                "related_type": row.related_type,
                "related_type_label": DOC_TYPES.get(row.related_type or "", "") or None,
                "amount": float(row.amount or 0.0),
                "occurred_at": row.occurred_at,
                "doc_no": row.doc_no,
                "note": row.note,
            }
            for row in rows
        ],
    }
