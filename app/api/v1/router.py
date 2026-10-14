from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.erp import router as erp_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.ledger import router as ledger_router
from app.api.v1.routes.reports import router as reports_router
from app.api.v1.routes.system import router as system_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(erp_router)
# 报表中心（第 4 批）：纯只读聚合，与业务单据解耦，单开一个模块
api_router.include_router(reports_router)
# 总账 / 复式记账（财务能力 + 关联能力）：科目、凭证、科目余额表、明细账
api_router.include_router(ledger_router)
# 系统管理（第 5 批）：组织机构 / 角色 / 用户，与业务单据零共享，单开一个模块
api_router.include_router(system_router)
