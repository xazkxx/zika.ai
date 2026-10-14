"""多账套（多公司）—— 第 1 期：账套底座。

## 为什么是「一账套一个 schema」而不是「一个账套一个数据库」

原计划是一公司一个数据库（物理隔离最彻底）。实测发现本项目的 PG 角色 `erp`
**没有 CREATEDB 权限**（`rolcreatedb=false`，也不是超级用户），建库要先找 DBA 授权。
改用**同一个数据库内一账套一个 schema**，隔离强度基本相当，还额外拿到两个好处：

1. **不需要额外权限** —— 建 schema 只要数据库上的 CREATE 权限，现在就够；
2. **合并报表可以直接跨 schema 汇总**（`co_01.sales_orders UNION ALL co_02.sales_orders`），
   而跨库得上 FDW 或应用层拼接。用户明确要了"老板看集团总数"，这一条很关键。

底层机制和多库完全一样：**每个账套一个 engine**，连接时带
`options=-c search_path=<账套 schema>,public`。不限定名的表名自动落到账套 schema，
`public` 兜底（放全局共享表）。已实测：账套 schema 与 public 有同名表时账套优先，
**不会串账**。

## 哪些表是全局的、哪些是账套的

- **全局表（`GLOBAL_TABLES`，放 public，所有账套共用）**：用户 / 账套 / 角色 / 菜单 /
  系统参数 / 数字字典 / 打印模板 / 操作日志。
  这些是"系统怎么跑"的配置与审计，不是"某家公司的业务"。账号可共用正是靠这一条。
- **账套表**：其余全部业务表（客户、供应商、商品、仓库、库存、单据、财务、发票…）。
  各账套在**自己的 schema 里各有一份**，同名不同 schema，唯一约束天然互不干扰。

> ⚠️ 一个刻意的决定：**第一个账套就是 `public`**。
> 现有部署的表全在 public，把它当作账套 1 意味着**升级时业务数据一个字节都不用搬**
> —— 这是这套设计里风险最低的一点。新账套才用 `co_xx` 这样的独立 schema。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 第一个账套的 schema 名。历史数据都在 public，沿用它＝升级零搬迁。
PUBLIC_SCHEMA = "public"


class Company(Base):
    """账套（一家公司一本账）。

    **这个类同时承担两个角色**，因为它们在业务上是同一件事：
    1. 账套注册表的一行（哪个账套、用哪个 schema）；
    2. 这家公司的抬头（名称 / 税号 / 地址 / 开户行），也就是原来 `company.json` 里那 8 个字段。

    为什么把抬头从 `company.json` 搬进来：抬头原先是**部署级**配置（一台机器一份），
    而进销项判定要靠本公司税号 —— 多公司下每家公司必须有自己的税号，
    否则"别人开给我们的票"会被判成销项。
    """

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 账套号：给人看的标识（也用作 schema 名）。第一个账套固定是 "public"。
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    # **账套名**：菜单/顶栏上显示的那个名字，必填、不随抬头变。
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # **发票抬头里的购方/销方名称**。与账套名分开是刻意的：
    # 现实中两者经常不一样（账套叫"西安总部"、抬头是"陕西某某科技有限公司"），
    # 而且抬头**必须能被清空** —— 抬头的税号一旦为空，进销项就应老实返回"待判定"，
    # 不能猜。把两者合并成一个字段时，清空抬头会连带把 NOT NULL 的账套名写成 NULL。
    own_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # 本公司纳税人识别号：**进销项判定靠它**，多账套下每套各不相同。
    tax_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 物理 schema。与 code 分开是为了允许"账套号改得了、已经建好的表不用搬"。
    schema_name: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)

    # —— 抬头（对齐原 company.json 的字段名，迁移时可直接搬）——
    legal_person: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(60), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserCompany(Base):
    """用户 ↔ 账套（多对多）：一个人可以同时管几家公司。

    用户自己放在 `users`（全局表，账号可共用），归属关系放这里。
    写成多对多而不是在 users 上加一个 `company_id`，是因为用户明确选了
    "独立账簿、账号可共用" —— 一个人管多家是常态，不是例外。

    `department_id` / `position` 存在**关系上**而不是用户上：
    同一个会计在 A 公司是财务部、在 B 公司可能挂综合部，两家的工号岗位都可能不同。
    """

    __tablename__ = "user_companies"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 该用户在这家公司里挂的部门 / 岗位（指向账套库里的 departments）
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 登录后默认进哪家。每个用户只应有一条 is_default=True（接口层保证唯一）。
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# 全局表清单：这些表**不进**账套 schema，留在 public 供所有账套共用。
#
# 判据：它是"系统怎么跑"的配置/审计，还是"某家公司的业务"？
# 前者全局，后者账套。
#
# ⚠️ 这张清单是路由正确性的关键。往里面多写一张业务表，那张表就变成全局共享
#    —— 两家公司会看到彼此的客户/单据，而且**不报错**。少写一张全局表，
#    则每个账套各有一份，管理员要在每套里各配一遍菜单与字典。
#    改这张清单前先想清楚它属于哪一类。
# ---------------------------------------------------------------------------
GLOBAL_TABLES: frozenset[str] = frozenset(
    {
        "users",  # 账号集中，可共用（用户明确要求）
        "companies",  # 账套注册表本身
        "user_companies",  # 用户 ↔ 账套
        "roles",  # 角色定义（权限点是代码里的固定清单，角色本身全局）
        "menus",  # 导航菜单结构：是界面骨架，不是某家公司的业务
        "system_params",  # 系统参数（打印页脚 / 默认落地页 / 库存预警开关）
        "data_dictionaries",  # 数字字典（含税率、付款方式……）
        "data_dictionary_items",
        "print_templates",  # 打印模板外观
        "operation_logs",  # 操作日志：审计要跨公司看"谁在什么时候做了什么"
    }
)
