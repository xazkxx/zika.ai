"""动态菜单树 —— 让管理员在界面上自己增删改菜单与层级。

## 为什么要有这张表

在此之前全站菜单是写死在 `frontend/src/App.jsx` 的 `menuGroups` 常量里的：
**两级固定**（分组 → 菜单项），且前端常量、后端 `PERMISSION_CATALOG`、
角色权限的扁平数组、两级权限树、一致性测试正则五处绑死。用户的实际诉求是
「能往下建下级菜单」，这条路走不通。于是把**菜单的展示结构**搬进数据库，
管理员可以自由增删、改名、换父级、调顺序、隐藏。

## 三条边界（这张表只负责"怎么展示"，不负责别的）

1. **不负责权限**。权限点仍然是**页面**（`PERMISSION_CATALOG` 里那份固定清单），
   角色拿到的还是页面 key 数组。菜单树只决定"有权限的页面摆在侧边栏的什么位置"。
   这样权限模型一行没动，`all_menu_keys()` / 角色权限树 / 一致性测试全部保持原样。
2. **不负责页面本身**。菜单项只是个"壳" —— 每个 `page_key` 背后必须有前端的
   `selectedTab === 'xxx'` 渲染分支，否则点进去是空白。所以**新建菜单只能从
   已有页面里选**（接口层校验 `page_key in all_menu_keys()`），
   这也是「动态菜单做不出新业务页面」这条硬约束的落地方式。
3. **分组不是权限**。`page_key` 为空的节点只是容器，可见性取决于它下面
   有没有可见的菜单项 —— 空分组在侧边栏里自然消失。

## 节点形状

- `page_key` **有值** = 菜单项（叶子）：点它切到那个页面，**不允许挂子节点**。
- `page_key` **为空** = 分组（容器）：自己不指向页面，靠子节点构成一颗子树。

这样只用"有没有 page_key"一个判据就区分了两类节点，不需要额外的 type 字段，
也不会出现"既是菜单项又能展开"这种会让侧边栏行为含糊的节点。

深度上限默认 8 层（可用环境变量 `ERP_MAX_MENU_DEPTH` 覆盖）：左侧导航是纵向空间，
再深下去每行只剩几十像素、实际已经点不中，而且每多一层"这个菜单位置对不对"的
排查成本就翻一倍。**留一条上限而不是设成无限**，出问题时报错是"最多 8 层"（可理解），
而不是界面先崩掉。要更深自行调环境变量，不必改代码。

## 播种与"恢复默认"

`ensure_default_menus()` 只在表**为空**时按 `PERMISSION_CATALOG` 播种，
之后一律不动 —— 管理员改过的东西不能被每次重启冲掉（与角色/字典/参数同一套约定）。
想回到出厂状态用 `POST /system/menus/reset`（需管理员，且界面上会二次确认）。
"""

import os
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 左侧导航的最大层级。默认 8 层，可用环境变量 ERP_MAX_MENU_DEPTH 覆盖。
# 2026-10-16：从写死的 3 改成可配置 —— 菜单树重构要支持向下多层建，
# 但保留一条上限（理由见文件头注释）。
MAX_MENU_DEPTH = int(os.environ.get("ERP_MAX_MENU_DEPTH", "8"))

# 显示名长度上限（与 String(50) 对齐，接口层给出更友好的报错）
MAX_MENU_LABEL = 20


class Menu(Base):
    """菜单节点（自引用树）。"""

    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 父节点：NULL = 顶层分组。自引用模式与 departments / production_boms 一致
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    # 有值 = 菜单项（叶子，指向某个页面）；为空 = 分组（容器）
    page_key: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 播种出来的内置节点。只用来在界面上区分「内置/自定义」并提示删除影响，
    # **不参与删除拦截** —— 删掉内置菜单只是把它从侧边栏拿掉，页面与权限都还在
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_leaf(self) -> bool:
        """菜单项（叶子）—— 判据只有一个：挂没挂页面。"""
        return bool(self.page_key)

    @property
    def kind_label(self) -> str:
        return "菜单项" if self.is_leaf else "分组"


# ---------------------------------------------------------------------------
# 纯函数：默认种子与树组装（播种、路由、测试三处共用）
# ---------------------------------------------------------------------------
def default_menu_specs() -> list[tuple[str | None, str, str | None, int]]:
    """按 `PERMISSION_CATALOG`（可授权页面清单）生成默认菜单树。

    返回 `[(父分组名, 显示名, 页面key, 排序号), ...]`，**按父分组名而不是 id 关联** ——
    播种时 id 还没生成，用名字连两次插入最直白（分组名在本项目里是唯一的）。

    默认树就是原样复刻改造前的两级结构（分组 → 菜单项），
    这样"上了动态菜单"这件事**对现有用户的观感是零变化**，
    多出来的层级由管理员自己按需去建。
    """
    # 延迟导入：core 层不依赖 models，这个方向是安全的（role.py 也是这么用的）
    from app.core.permissions import PERMISSION_CATALOG

    specs: list[tuple[str | None, str, str | None, int]] = []
    for group_index, group in enumerate(PERMISSION_CATALOG, start=1):
        group_label = str(group["label"])
        specs.append((None, group_label, None, group_index * 10))
        for item_index, item in enumerate(group["items"], start=1):  # type: ignore[union-attr]
            specs.append(
                (group_label, str(item["label"]), str(item["key"]), item_index * 10)  # type: ignore[index]
            )
    return specs


def build_menu_tree(rows: list["Menu"]) -> list[dict[str, object]]:
    """把扁平的菜单行组装成嵌套树。

    `rows` 里出现了、但父节点不在其中的节点，会被**当作顶层**挂上去而不是丢弃 ——
    宁可多显示一个菜单，也不要让它凭空消失（那是最难排查的一类问题：
    界面上什么都没有，数据库里明明有这条记录）。
    """
    by_id: dict[int, dict[str, object]] = {}
    for row in rows:
        by_id[row.id] = {
            "id": row.id,
            "parent_id": row.parent_id,
            "label": row.label,
            "page_key": row.page_key or "",
            "sort_order": row.sort_order,
            "is_enabled": bool(row.is_enabled),
            "is_builtin": bool(row.is_builtin),
            "kind": "menu" if row.page_key else "group",
            "note": row.note or "",
            "children": [],
        }

    order = {row.id: (row.sort_order, row.id) for row in rows}
    for row in rows:
        node = by_id[row.id]
        parent = by_id.get(row.parent_id) if row.parent_id else None
        if parent is None:
            continue  # 下面统一收顶层
        parent["children"].append(node)  # type: ignore[union-attr]

    def sort_children(node: dict[str, object]) -> None:
        children = node["children"]
        children.sort(key=lambda child: order[child["id"]])  # type: ignore[index]
        for child in children:
            sort_children(child)

    roots = [
        by_id[row.id]
        for row in rows
        if not row.parent_id or row.parent_id not in by_id
    ]
    roots.sort(key=lambda node: order[node["id"]])  # type: ignore[index]
    for root in roots:
        sort_children(root)
    return roots
