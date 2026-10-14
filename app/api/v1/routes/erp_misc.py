"""综合接口 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

仪表盘 / 汇总 / 公司设置 / 智能助手 / 移动端 / 日报导出。
"""

from __future__ import annotations

import csv
import json
import os

from app.core.company_info import load_company, save_company
from app.db.session import get_db
from app.models.bom import BillOfMaterial
from app.models.customer import Customer
from app.models.finance import FinancialTransaction
from app.models.product import Product
from app.models.production import ProductionOrder
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder
from app.models.sales_order import SalesOrder
from app.models.supplier import Supplier
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, Request, Response, status
from io import StringIO
from sqlalchemy import func
from sqlalchemy.orm import Session
from urllib import request

router = APIRouter(prefix="", tags=["erp"])




@router.post("/agent/assistant")
def mobile_agent_assistant(payload: dict[str, object] | None = None) -> dict[str, object]:
    payload = payload or {}
    prompt = str(payload.get("prompt") or "请评估当前业务健康度")
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}

    sales_total = float(context.get("sales_total") or context.get("sales") or 0)
    purchase_total = float(context.get("purchase_total") or context.get("purchase") or 0)
    finance_total = float(context.get("finance_total") or context.get("finance") or 0)
    customers = int(context.get("customers") or 0)
    products = int(context.get("products") or 0)

    gross_profit = sales_total - purchase_total
    gross_margin_rate = (gross_profit / sales_total * 100) if sales_total else 0.0
    operating_health = "健康" if gross_margin_rate >= 20 and finance_total >= 0 else "关注" if gross_margin_rate >= 8 else "风险"

    summary = {
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "finance_total": finance_total,
        "customers": customers,
        "products": products,
        "gross_profit": gross_profit,
        "gross_margin_rate": round(gross_margin_rate, 2),
    }

    answer = (
        f"当前业务健康度为{operating_health}。"
        f"销售额为¥{sales_total:,.0f}，采购额为¥{purchase_total:,.0f}，毛利为¥{gross_profit:,.0f}，"
        f"毛利率为{gross_margin_rate:.1f}%；当前客户数{customers}，产品数{products}。"
        f"建议：{('继续扩张优质客户并控制采购成本。' if operating_health == '健康' else '加速回款并压缩非必要支出。' if operating_health == '关注' else '立即审查现金流和风险客户，降低坏账概率。') }"
    )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key and prompt:
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是ERP本地智能体助手，输出简洁、实用、中文结论。",
                },
                {
                    "role": "user",
                    "content": f"用户提问：{prompt}\n\n当前业务数据：{json.dumps(summary, ensure_ascii=False)}",
                },
            ],
            "temperature": 0.2,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=30) as response:
                content = json.loads(response.read().decode("utf-8"))
            answer = content.get("choices", [{}])[0].get("message", {}).get("content") or answer
        except Exception:
            pass

    return {
        "answer": answer,
        "summary": summary,
        "risk_level": operating_health,
    }



@router.get("/mobile/dashboard")
def mobile_dashboard(db: Session = Depends(get_db)) -> dict[str, object]:
    from app.api.v1.routes.erp_finance import finance_alerts
    from app.api.v1.routes.erp_inventory import list_inventory_alerts
    dashboard_summary = summary(db)
    inventory_alerts = list_inventory_alerts(db)
    payment_alerts = finance_alerts(db)
    total_sales = float(dashboard_summary.get("sales_total") or 0.0)
    total_purchase = float(dashboard_summary.get("purchase_total") or 0.0)
    net_profit = total_sales - total_purchase
    risk_count = len(inventory_alerts) + len(payment_alerts)

    if net_profit >= 0 and risk_count <= 2:
        status = "healthy"
    elif risk_count <= 5:
        status = "warning"
    else:
        status = "risk"

    recommendations: list[str] = []
    if inventory_alerts:
        recommendations.append(
            f"库存预警 {len(inventory_alerts)} 项（缺货 / 低库存 / 积压），请检查补货与存货周转。"
        )
    if payment_alerts:
        recommendations.append(f"付款提醒 {len(payment_alerts)} 项，建议及时跟进供应商付款。")
    if net_profit < 0:
        recommendations.append("当前净利润为负，建议压缩非必要支出并提升回款效率。")
    if not recommendations:
        recommendations.append("当前业务状态稳定，建议继续维持现有经营节奏。")

    return {
        "status": status,
        "risk_count": risk_count,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "sales_total": total_sales,
            "purchase_total": total_purchase,
            "net_profit": net_profit,
            "customers": int(dashboard_summary.get("customers") or 0),
            "products": int(dashboard_summary.get("products") or 0),
            "inventory_alerts": len(inventory_alerts),
            "payment_alerts": len(payment_alerts),
        },
        "kpis": [
            {"label": "销售额", "value": total_sales, "unit": "CNY"},
            {"label": "采购额", "value": total_purchase, "unit": "CNY"},
            {"label": "净利润", "value": net_profit, "unit": "CNY"},
            {"label": "风险项", "value": risk_count, "unit": "items"},
        ],
        "recommendations": recommendations,
    }



@router.get("/dashboard/operations")
def dashboard_operations(db: Session = Depends(get_db)) -> dict[str, object]:
    from app.api.v1.routes.erp_finance import finance_alerts
    from app.api.v1.routes.erp_inventory import list_inventory_alerts
    from app.api.v1.routes.erp_purchase import purchase_recommendations, supplier_performance
    production_orders = db.query(ProductionOrder).all()
    projects = db.query(Project).all()
    bom_items = db.query(BillOfMaterial).all()

    status_breakdown = {
        "planned": sum(1 for item in production_orders if item.status == "planned"),
        "in_progress": sum(1 for item in production_orders if item.status == "in_progress"),
        "completed": sum(1 for item in production_orders if item.status == "completed"),
    }
    high_priority_orders = [
        {
            "id": item.id,
            "order_no": item.order_no,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "priority": item.priority,
            "status": item.status,
        }
        for item in production_orders
        if item.priority == "high"
    ]
    project_summary = {
        "total": len(projects),
        "in_progress": sum(1 for item in projects if item.status == "in_progress"),
        "completed": sum(1 for item in projects if item.status == "completed"),
        "avg_progress": round(sum(item.progress for item in projects) / len(projects), 1) if projects else 0.0,
        "budget_total": round(sum(float(item.budget or 0.0) for item in projects), 2),
    }

    milestones = [
        {
            "project_name": item.name,
            "phase": "需求评审" if item.status == "planned" else "执行阶段" if item.status == "in_progress" else "验收交付",
            "deadline": item.deadline or (item.created_at.date().isoformat() if item.created_at else "2026-12-31"),
            "status": item.status,
            "progress": item.progress,
        }
        for item in projects[:6]
    ]

    total_production_cost = sum((item.quantity * 38.0) + (item.quantity * 12.0) for item in production_orders)
    labour_cost = sum(item.quantity * 12.0 for item in production_orders)
    material_cost = sum(item.quantity * 38.0 for item in production_orders)
    cost_summary = {
        "material_cost": round(material_cost, 2),
        "labor_cost": round(labour_cost, 2),
        "overhead_cost": round(total_production_cost * 0.1, 2),
        "total_cost": round(total_production_cost * 1.1, 2),
    }

    production_flow = []
    for item in production_orders[:10]:
        stage_names = ["需求确认", "BOM审核", "物料准备", "生产执行", "质检入库"]
        threshold = 0 if item.status == "planned" else 2 if item.status == "in_progress" else len(stage_names)
        steps = []
        for index, stage in enumerate(stage_names):
            steps.append(
                {
                    "name": stage,
                    "status": "done" if index < threshold else "active" if index == threshold and item.status != "completed" else "pending",
                }
            )
        if item.status == "completed":
            steps[-1]["status"] = "done"
        production_flow.append({
            "order_no": item.order_no,
            "status": item.status,
            "steps": steps,
        })

    bom_summary = {
        "total_items": len(bom_items),
        "total_quantity": sum(int(item.quantity) for item in bom_items),
        "total_cost": round(sum(float(item.unit_cost) * int(item.quantity) for item in bom_items), 2),
    }

    recommendations = []
    if status_breakdown["planned"]:
        recommendations.append(
            {
                "title": "优先完成计划排产",
                "description": "当前有多个计划中订单，建议先确认 BOM 与物料准备，避免后续停线。",
                "priority": "high",
            }
        )
    if high_priority_orders:
        recommendations.append(
            {
                "title": "高优先级订单前置",
                "description": "高优先级订单存在交付风险，建议提前排入当日产线并安排检验窗口。",
                "priority": "high",
            }
        )
    if bom_summary["total_items"]:
        recommendations.append(
            {
                "title": "BOM关联复核",
                "description": "已关联 BOM 明细，可重点检查关键部件用量和单位成本，避免成本失控。",
                "priority": "medium",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "title": "稳定生产节奏",
                "description": "当前生产状态平稳，建议维持现有排产与质检节奏，并关注交付拐点。",
                "priority": "low",
            }
        )

    work_orders = [
        {
            "id": item.id,
            "order_no": item.order_no,
            "product_id": item.product_id,
            "line_name": "A线" if item.id % 3 == 0 else "B线" if item.id % 3 == 1 else "C线",
            "quantity": item.quantity,
            "status": item.status,
            "planned_start": (item.created_at.date().isoformat() if item.created_at else "2026-09-01"),
            "planned_end": (item.created_at.date().isoformat() if item.created_at else "2026-09-02"),
        }
        for item in production_orders[:8]
    ]

    production_schedule = [
        {
            "date": "2026-09-24",
            "line_name": "A线",
            "order_no": work_order["order_no"],
            "duration_days": 2,
            "status": work_order["status"],
        }
        for work_order in work_orders[:3]
    ]

    bom_alerts = [
        {
            "component_id": item.component_product_id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_cost": round(float(item.unit_cost or 0.0), 2),
            "level": "warning" if item.quantity >= 3 else "info",
            "message": "关键部件用量较高，建议提前补料" if item.quantity >= 3 else "材料可持续供应",
        }
        for item in bom_items[:5]
    ]

    if not bom_alerts:
        bom_alerts.append(
            {
                "component_id": 0,
                "product_id": 0,
                "quantity": 0,
                "unit_cost": 0.0,
                "level": "info",
                "message": "暂无 BOM 缺料预警，当前物料状态正常",
            }
        )

    line_board = [
        {
            "line_name": "A线",
            "utilization": 82,
            "output": 320,
            "status": "正常",
            "pending_orders": 2,
        },
        {
            "line_name": "B线",
            "utilization": 68,
            "output": 260,
            "status": "待补料",
            "pending_orders": 1,
        },
        {
            "line_name": "C线",
            "utilization": 74,
            "output": 290,
            "status": "正常",
            "pending_orders": 3,
        },
    ]

    auto_schedule = [
        {
            "order_no": item.order_no,
            "line_name": "A线" if idx % 3 == 0 else "B线" if idx % 3 == 1 else "C线",
            "start_date": "2026-09-24",
            "end_date": "2026-09-26",
            "load_rate": 85 if item.priority == "high" else 70 if item.priority == "normal" else 55,
        }
        for idx, item in enumerate(production_orders[:5])
    ]

    inventory_alerts = list_inventory_alerts(db)
    purchase_recommendation_list = purchase_recommendations(db)
    supplier_performance_data = supplier_performance(db)
    payment_alerts = finance_alerts(db)

    work_report_summary = {
        "total_work_orders": len(work_orders),
        "completed_today": sum(1 for item in work_orders if item["status"] == "completed"),
        "progress_rate": round((sum(1 for item in work_orders if item["status"] == "completed") / len(work_orders)) * 100, 1) if work_orders else 0.0,
        "avg_output": 280,
        "oee": 86.4,
    }

    gantt = [
        {
            "id": item.id,
            "title": item.order_no,
            "start": item.created_at.date().isoformat() if item.created_at else "2026-09-01",
            "end": (item.created_at.date().isoformat() if item.created_at else "2026-09-01"),
            "progress": 25 if item.status == "planned" else 60 if item.status == "in_progress" else 100,
            "status": item.status,
        }
        for item in production_orders[:8]
    ]

    return {
        "production_orders": [
            {
                "id": item.id,
                "order_no": item.order_no,
                "product_id": item.product_id,
                "bom_id": item.bom_id,
                "quantity": item.quantity,
                "status": item.status,
                "priority": item.priority,
                "note": item.note,
            }
            for item in production_orders
        ],
        "project_summary": project_summary,
        "high_priority_orders": high_priority_orders,
        "status_breakdown": status_breakdown,
        "milestones": milestones,
        "cost_summary": cost_summary,
        "gantt": gantt,
        "production_flow": production_flow,
        "recommendations": recommendations,
        "bom_summary": bom_summary,
        "work_orders": work_orders,
        "production_schedule": production_schedule,
        "bom_alerts": bom_alerts,
        "line_board": line_board,
        "auto_schedule": auto_schedule,
        "inventory_alerts": inventory_alerts,
        "purchase_recommendations": purchase_recommendation_list,
        "supplier_performance": supplier_performance_data,
        "payment_alerts": payment_alerts,
        "work_report_summary": work_report_summary,
    }



@router.get("/dashboard/executive")
def executive_dashboard(db: Session = Depends(get_db)) -> dict[str, object]:
    from app.api.v1.routes.erp_finance import finance_alerts
    from app.api.v1.routes.erp_inventory import list_inventory_alerts
    summary_data = summary(db)
    operations_data = dashboard_operations(db)
    payment_alerts = finance_alerts(db)
    inventory_alerts = list_inventory_alerts(db)

    kpis = [
        {"label": "销售额", "value": float(summary_data.get("sales_total") or 0.0), "unit": "CNY"},
        {"label": "采购额", "value": float(summary_data.get("purchase_total") or 0.0), "unit": "CNY"},
        {"label": "净利润", "value": float((summary_data.get("sales_total") or 0.0) - (summary_data.get("purchase_total") or 0.0)), "unit": "CNY"},
        {"label": "生产订单", "value": int(len(operations_data.get("production_orders") or [])), "unit": "orders"},
        {"label": "库存预警", "value": int(len(inventory_alerts)), "unit": "items"},
        {"label": "付款提醒", "value": int(len(payment_alerts)), "unit": "alerts"},
    ]

    status = {
        "health": "healthy" if len(payment_alerts) <= 2 and len(inventory_alerts) <= 3 else "watch",
        "production": operations_data.get("work_report_summary", {}).get("progress_rate", 0),
        "margin": round((float(summary_data.get("sales_total") or 0.0) - float(summary_data.get("purchase_total") or 0.0)) / float(summary_data.get("sales_total") or 1.0) * 100, 2) if (summary_data.get("sales_total") or 0.0) else 0.0,
        "risk_count": int(len(payment_alerts) + len(inventory_alerts)),
    }

    alerts = [
        {"title": "库存风险", "message": f"当前库存预警 {len(inventory_alerts)} 项，建议关注补货与积压。", "severity": "warning" if inventory_alerts else "info"},
        {"title": "付款提醒", "message": f"当前需要跟进 {len(payment_alerts)} 个付款事项。", "severity": "warning" if payment_alerts else "info"},
        {"title": "生产进度", "message": f"工单完成率 {operations_data.get('work_report_summary', {}).get('progress_rate', 0)}%，整体运行正常。", "severity": "info"},
    ]

    return {"kpis": kpis, "status": status, "alerts": alerts}



@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, float | int]:
    customer_count = db.query(Customer).count()
    supplier_count = db.query(Supplier).count()
    product_count = db.query(Product).count()
    sales_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(SalesOrder.total_amount), 0))
        .scalar()
        or 0
    )
    purchase_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(PurchaseOrder.total_amount), 0))
        .scalar()
        or 0
    )
    finance_total = (
        db.query(__import__("sqlalchemy").sql.func.coalesce(__import__("sqlalchemy").sql.func.sum(FinancialTransaction.amount), 0))
        .scalar()
        or 0
    )
    return {
        "customers": customer_count,
        "suppliers": supplier_count,
        "products": product_count,
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "finance_total": finance_total,
    }



@router.get("/reports/daily-export")
def export_daily_report(db: Session = Depends(get_db)) -> Response:
    today = date.today().isoformat()
    summary_data = summary(db)
    operations_data = dashboard_operations(db)
    work_report_summary = operations_data.get("work_report_summary") or {}

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "report_date",
        "sales_total",
        "purchase_total",
        "finance_total",
        "customers",
        "suppliers",
        "products",
        "production_orders",
        "completed_orders",
        "avg_progress",
        "material_cost",
        "labor_cost",
        "total_cost",
        "progress_rate",
        "oee",
    ])
    writer.writerow([
        today,
        float(summary_data.get("sales_total") or 0.0),
        float(summary_data.get("purchase_total") or 0.0),
        float(summary_data.get("finance_total") or 0.0),
        int(summary_data.get("customers") or 0),
        int(summary_data.get("suppliers") or 0),
        int(summary_data.get("products") or 0),
        int(len(operations_data.get("production_orders") or [])),
        int(work_report_summary.get("completed_today") or 0),
        float(operations_data.get("project_summary", {}).get("avg_progress") or 0.0),
        float(operations_data.get("cost_summary", {}).get("material_cost") or 0.0),
        float(operations_data.get("cost_summary", {}).get("labor_cost") or 0.0),
        float(operations_data.get("cost_summary", {}).get("total_cost") or 0.0),
        float(work_report_summary.get("progress_rate") or 0.0),
        float(work_report_summary.get("oee") or 0.0),
    ])

    csv_content = buffer.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="erp_daily_report_{today}.csv"'},
    )



@router.get("/settings/company")
def get_company_settings() -> dict[str, str]:
    """我方公司信息（合同 / 单据打印抬头），存 company.json。"""
    return load_company()



@router.put("/settings/company")
def update_company_settings(payload: dict[str, object]) -> dict[str, str]:
    """保存我方公司信息为默认抬头。后续新建合同自动带出。"""
    return save_company(payload)
