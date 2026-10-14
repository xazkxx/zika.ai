"""操作日志 —— 系统管理第 5 批第 3 轮。

**只记写操作**（POST / PUT / PATCH / DELETE）。理由：
- 查询类的 GET 占了请求量的绝大多数，把它们也写进库，日志会变成"访问日志"，
  真正要追的"谁改了这张单"反而被淹没；
- 本地 ERP 的日志是给老板/管理员看的"操作留痕"，不是运维审计系统。

**三条不可动摇的约定**：

1. **写日志绝不允许影响业务请求**：中间件里所有异常都被吞掉
   （见 `app/main.py` 的 `_operation_log_middleware`）。日志写失败时宁可少一条记录，
   也不能让一张已经入库的销售单返回 500。
2. **不阻塞事件循环**：落库走 `run_in_threadpool`。日志是同步 IO，
   直接在 async 中间件里 await 会卡住整个进程。
3. **表会自我修剪**：超过 `MAX_OPERATION_LOGS` 就按 id 删最老的一批。
   否则这个表是唯一一张只增不减的表，几年后把库撑大。

动作名（`action`）由 method + url 翻译成人话（"新增客户""重置密码"），
不依赖业务代码手工登记 —— 手工登记这种事，一定会有人忘。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db.base import Base

# 会记日志的 HTTP 方法（清单一处定义，中间件与本模块共用）
OPERATION_LOG_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 表容量上限：超过就删最老的。5000 条对"追最近谁改了什么"足够，
# 又不会让日志表无限膨胀。
MAX_OPERATION_LOGS = 5000
# 每 N 条检查一次容量，避免每次写日志都 count(*) 一遍
PRUNE_EVERY = 200

_METHOD_VERBS = {"POST": "新增", "PUT": "修改", "PATCH": "修改", "DELETE": "删除"}

# url 片段 → 业务对象中文名。没登记的片段会原样出现在动作名里（不隐瞒）。
_PATH_LABELS: dict[str, str] = {
    "customers": "客户",
    "suppliers": "供应商",
    "products": "商品",
    "warehouses": "仓库",
    "users": "用户",
    "roles": "角色",
    "departments": "部门",
    "params": "参数",
    "dictionaries": "字典",
    "dictionary-items": "字典项",
    "print-templates": "打印模板",
    "logs": "操作日志",
    "purchase-orders": "采购单",
    "sales-orders": "销售单",
    "purchase-returns": "采购退货单",
    "sales-returns": "销售退货单",
    "quotations": "报价单",
    "contracts": "合同",
    "production-orders": "生产单",
    "production-plans": "生产计划",
    "material-issues": "生产领料单",
    "material-returns": "生产退料单",
    "finished-goods": "成品入库单",
    "outsourcings": "委外加工单",
    "inventory-transfers": "调拨单",
    "stocktakings": "盘点单",
    "inventory-adjustments": "库存调整单",
    "financial-transactions": "财务流水",
    "finance": "财务单据",
    "invoices": "发票",
    "boms": "BOM",
    "projects": "项目",
    "reports": "报表",
    "excel": "导入导出",
    "auth": "登录",
    "system": "系统设置",
    "settings": "公司信息",
    "company": "公司信息",
    "inventory": "库存",
    "stock-logs": "库存流水",
    "mobile": "移动端",
    "agent": "智能助手",
    "search": "搜索",
    "lookups": "字典候选",
    "items": "明细",
}

# 子资源：挂在主对象后面的明细/子表（`/sales-orders/3/items`）。
# 它们不能当 target_type —— "新增明细"看不出是给哪张单加的，
# 主对象才是要追的那个东西。
_SUB_RESOURCES = frozenset({"items", "lines", "entries", "details"})

# 末段路径 → 动作名覆盖。这些 POST 不是"新增"，光看方法会翻译错。
_ACTION_OVERRIDES: dict[str, str] = {
    "login": "登录",
    "logout": "退出登录",
    "password": "重置密码",
    "toggle": "启用或停用",
    "reset": "恢复默认",
    "preview": "预览",
    "receipt": "登记收款",
    "payment": "登记付款",
    "import": "导入",
    "export": "导出",
    "convert": "转单",
    "confirm": "确认",
    "approve": "审核",
    "cancel": "作废",
    "batch": "批量处理",
    "refresh": "刷新",
    "run": "执行",
}


class OperationLog(Base):
    """一条操作留痕。字段刻意冗余（username/role 存快照），
    这样即使用户后来被改名或删除，历史日志仍然读得懂。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 快照：不跟随用户改名/删除而失效
    username: Mapped[str] = mapped_column(String(50), default="", nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="", nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 人话动作名，如"新增客户""重置密码"
    action: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # 机器可读的对象类型（url 片段）与对象 id，方便后续按单据筛选
    target_type: Mapped[str] = mapped_column(String(40), default="", nullable=False, index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 失败时记原因（HTTP 状态之外的信息），成功时留空
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False, index=True
    )


def _pick_resource(words: list[str]) -> str | None:
    """从右往左找第一个"能当主对象"的片段（跳过子资源）。"""
    return next((word for word in reversed(words) if word in _PATH_LABELS and word not in _SUB_RESOURCES), None)


def describe_operation(method: str, path: str) -> tuple[str, str, int | None]:
    """把 method + url 翻成 (动作名, 对象类型, 对象 id)。

    例：
        POST   /api/v1/customers               → ("新增客户", "customers", None)
        PATCH  /api/v1/system/users/7          → ("修改用户", "users", 7)
        DELETE /api/v1/sales-orders/12         → ("删除销售单", "sales-orders", 12)
        POST   /api/v1/system/users/7/password → ("重置密码", "users", 7)
        POST   /api/v1/sales-orders/3/items    → ("新增销售单（items）", "sales-orders", 3)

    关于 `target_id`：**只对 url 里带 id 的操作有值**（改 / 删 / 子资源）。
    新增操作的对象 id 在响应体里，中间件读不到（要读就得消费响应流，
    那会干扰 PDF 下载这类流式响应）。这是刻意的取舍：宁可少一个字段，
    也不去动业务响应。追新增的记录靠"时间 + 操作人 + 动作"定位。
    """
    method = (method or "").upper()
    segments = [seg for seg in path.split("?")[0].split("/") if seg]
    if segments[:2] == ["api", "v1"]:
        segments = segments[2:]

    numbers = [int(seg) for seg in segments if seg.isdigit()]
    target_id = numbers[-1] if numbers else None
    words = [seg for seg in segments if not seg.isdigit()]
    if not words:
        return _METHOD_VERBS.get(method, method), "", target_id

    override = _ACTION_OVERRIDES.get(words[-1])
    if override:
        parent = _pick_resource(words[:-1]) or (words[-2] if len(words) >= 2 else "")
        return override, parent, target_id

    resource = _pick_resource(words)
    if resource is None:
        return f"{_METHOD_VERBS.get(method, method)} {words[-1]}".strip(), words[-1], target_id

    label = _PATH_LABELS[resource]
    # 末段是子资源（items / …）时补注，避免"新增销售单"掩盖了改的是明细
    tail = words[-1] if words[-1] != resource else ""
    action = f"{_METHOD_VERBS.get(method, method)}{label}" + (f"（{tail}）" if tail else "")
    return action, resource, target_id


def prune_operation_logs(db: Session, limit: int = MAX_OPERATION_LOGS) -> int:
    """超过 `limit` 就删最老的一批（按 id，不依赖时间精度），返回删除条数。

    `limit` 是参数而不是直接读全局常量，是为了让这条规则能被单独测到
    （测试用内存库 + 很小的 limit 跑，不需要动真库、也不需要造 5000 条数据）。
    """
    total = db.query(func.count(OperationLog.id)).scalar() or 0
    if total <= limit:
        return 0
    cutoff = (
        db.query(OperationLog.id)
        .order_by(OperationLog.id.desc())
        .offset(limit - 1)
        .limit(1)
        .scalar()
    )
    if cutoff is None:
        return 0
    return int(
        db.query(OperationLog).filter(OperationLog.id < cutoff).delete(synchronize_session=False)
    )


_prune_ticker = 0


def record_operation(
    db: Session,
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    user_id: int | None = None,
    username: str = "",
    role: str = "",
    ip: str = "",
    user_agent: str = "",
    detail: str | None = None,
) -> OperationLog:
    """写一条日志（含概率性修剪）。调用方负责 commit 的异常处理。"""
    global _prune_ticker

    action, target_type, target_id = describe_operation(method, path)
    row = OperationLog(
        user_id=user_id,
        username=username or "",
        role=role or "",
        method=(method or "").upper(),
        path=path[:255],
        action=action,
        target_type=target_type,
        target_id=target_id,
        status_code=int(status_code),
        duration_ms=int(max(0.0, duration_ms)),
        ip=(ip or "")[:64],
        user_agent=(user_agent or "")[:255],
        detail=detail,
    )
    db.add(row)

    _prune_ticker += 1
    if _prune_ticker % PRUNE_EVERY == 0:
        prune_operation_logs(db)

    db.commit()
    return row
