from fastapi import APIRouter

from app.api.v1.routes.agent import router as agent_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.erp import router as erp_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.ledger import router as ledger_router
from app.api.v1.routes.project_calc import router as project_calc_router
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
# 项目资金试算（v1.81.0）：纯计算 + 只读取数，既不建表也不写库。
# 与「报表中心」同口径（登录即可读），所以不新增权限点，只多一个菜单键。
api_router.include_router(project_calc_router)
# 智能体接口（第 4 批）：经营概览（给小程序/外部智能体）+ 智能指令派发（给系统内搜索框）。
# ⚠️ 2026-10-23 修：这个 router 一直被 import 了却**没 include** —— /agent/summary
#    在文档里写"已实现"，实际访问是 404。挂上不影响任何既有路径（前缀 /agent，
#    目前全库没有任何前端/测试依赖它，`/agent/assistant` 是 erp_misc 里的另一个接口）。
api_router.include_router(agent_router)
