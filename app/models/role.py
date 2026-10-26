"""角色与权限 —— 系统管理第 1 轮。

权限模型（刻意做得简单、够用）：
- 权限的**最小单位是菜单**（前端 menuGroups 的 item.key），不做按钮级 / 字段级权限；
- 角色 = 一组菜单 key（`permissions` JSON：`{"all": false, "menus": ["purchase", ...]}`）。
  用 JSON 而不是拆关联表：权限点是"配置"，不是"业务实体"，
  不需要被其它单据外键引用，也不参与报表聚合。拆表只会换来 3 个 JOIN 和一堆维护成本。
- `all: true` 表示超级管理员，永远拥有全部菜单（**菜单新增时不必回来改数据**）。
- `users.role` 保存角色 code 快照，登录签发的 JWT 里带的仍是它，
  因此既有的 `require_roles("admin")` 全部继续有效，鉴权链路一行没动。

内置角色（is_builtin=True）不允许删除，也不允许改 code —— 它们是代码里
`require_roles(...)` 依赖的锚点。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.permissions import all_menu_keys, system_menu_keys
from app.db.base import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 权限点 JSON 文本，见模块 docstring
    permissions: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    # 内置角色：可改显示名与权限，但不可删除、不可改 code
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# 经营主管：除「系统设置」分组外的全部菜单。
# 用"全集减系统组"求出来，而不是手抄 45 个 key —— 将来加业务菜单，主管自动跟着有。
_MANAGER_MENUS = [key for key in all_menu_keys() if key not in system_menu_keys()]


# ⚠️ 2026-10-18：「销售出库（多单位）」(`sales-units`) 已**整体下架**。
#    它和「开单管理」做同一件事（都写 doc_type=outbound、都扣库存与应收），
#    只是表单是另一套、编号与辅助单位算法不共享 —— 两套并存只会让"到底哪张单出的货"
#    说不清，而且它是唯一一个能删「已转单开单」的界面入口（Bug 1 的现场）。
#
#    下架动作是**四处一起改**，漏一处就会出现"菜单还在/点了白屏"：
#      代码：`app/core/permissions.py` 的 PERMISSION_CATALOG（不再播种）
#            `frontend/src/App.jsx` 的 menuGroups / 分发区 / import
#            `app/main.py` 的 MENU_RETIRED_KEYS（启动时删掉库里已有行 + 角色里残留的 key）
#      数据：启动迁移自动完成，**不需要**手动跑脚本，也不要用 POST /menus/reset
#            （reset 会把默认树整棵重播，管理员自建的菜单会被清掉）
#
#    组件源码 `frontend/src/components/sales-units/` 保留但不再被引用（只作参考实现）；
#    真要用回来，必须先把 Bug 1 的删单闸口接进它的 handleDelete。
BUILTIN_ROLES: list[dict[str, object]] = [
    {
        "code": "admin",
        "name": "系统管理员",
        "description": "拥有全部权限，可管理用户、角色与系统参数（all=true，菜单新增自动到手）",
        "permissions": {"all": True, "menus": []},
        "sort_order": 10,
    },
    {
        "code": "manager",
        "name": "经营主管",
        "description": "可见全部业务菜单，不能进系统设置",
        "permissions": {"all": False, "menus": _MANAGER_MENUS},
        "sort_order": 20,
    },
    {
        "code": "sales",
        "name": "销售员",
        "description": "销售开单、报价、客户档案与销售相关报表",
        "permissions": {
            "all": False,
            "menus": [
                "overview", "customers", "products", "warehouses",
                "sales", "sales-order", "quotation", "sales-return", "contracts",
                # 第 13 批：合同台账与「购销合同」同权限口径（谁能看购销合同，谁就能看台账）
                "contracts-ledger",
                # 增强对账单：销售员要能自己生成应收对账单去催款
                "statements-editor",
                "inventory", "stock-logs", "reports", "mobile",
            ],
        },
        "sort_order": 30,
    },
    {
        "code": "purchase",
        "name": "采购员",
        "description": "采购入库、采购订单、供应商档案与采购相关报表",
        "permissions": {
            "all": False,
            "menus": [
                "overview", "suppliers", "products", "warehouses",
                "purchase", "purchase-order", "purchase-return",
                "inventory", "stock-logs", "reports", "mobile",
            ],
        },
        "sort_order": 40,
    },
    {
        "code": "warehouse",
        "name": "仓管员",
        "description": "库存、调拨、盘点、报损报溢与出入库单据",
        "permissions": {
            "all": False,
            "menus": [
                "overview", "products", "warehouses",
                "purchase", "sales",
                "inventory", "stock-logs", "transfer", "stocktaking", "loss-overflow", "stock-alert",
                "reports", "mobile",
            ],
        },
        "sort_order": 50,
    },
    {
        "code": "finance",
        "name": "财务",
        "description": "财务流水、应收应付、往来对账与财务类报表",
        "permissions": {
            "all": False,
            "menus": [
                "overview", "customers", "suppliers", "finance",
                "receivable", "payable", "ledger", "general-ledger", "reports",
                # 对账是财务的核心动作：应收/应付对账单都能在这里出
                "statements-editor",
            ],
        },
        "sort_order": 60,
    },
    {
        "code": "staff",
        "name": "普通员工",
        "description": "默认角色：只看工作台与报表",
        "permissions": {"all": False, "menus": ["overview", "reports"]},
        "sort_order": 70,
    },
]
