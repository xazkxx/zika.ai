"""系统管理（第 5 批）—— 组织机构 / 角色 / 用户。

为什么单独一个路由文件而不是塞进 erp.py：
与 `reports.py` 同一理由 —— 这里没有任何"单据"语义：没有库存流水、没有财务
事件、没有打印与 Excel 注册表，与 erp.py 的业务函数**零共享**。硬塞进去只是
让那个已经 9000+ 行的文件更难读。

鉴权口径（本模块最重要的约定）：
- **写操作（建 / 改 / 删 / 重置密码 / 启停）一律 `require_roles("admin")`**；
- 读操作（部门树 / 角色 / 用户列表 / 权限目录）同样要求 admin ——
  "谁能看用户列表"本身就是管理权限的一部分；
- **唯一的例外是 `GET /system/me/permissions`**：任何登录用户都要能调，
  前端靠它过滤菜单。这是角色权限真正生效的地方。

覆盖范围：组织机构 / 角色 / 用户（第 1 轮）、参数设置 / 数字字典（第 2 轮）、
打印模板 / 操作日志（第 3 轮）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user, require_roles
from app.core.permissions import PERMISSION_CATALOG, all_menu_keys
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.employee import Employee
from app.models.operation_log import OperationLog
from app.models.organization import Department
from app.models.print_template import (
    TEMPLATE_EDITABLE_FIELDS,
    PrintTemplate,
    resolve_print_spec,
)
from app.models.role import Role
from app.models.system_config import (
    DEFAULT_PARAMS,
    PARAM_GROUPS,
    PARAM_VALUE_TYPES,
    DataDictionary,
    DataDictionaryItem,
    SystemParam,
    get_bool_param,
    get_param,
    param_default,
)
from app.models.user import User
from app.schemas import (
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    DictionaryCreate,
    DictionaryItemCreate,
    DictionaryItemRead,
    DictionaryItemUpdate,
    DictionaryRead,
    DictionaryUpdate,
    OperationLogPage,
    ParamBatchSave,
    PrintTemplateRead,
    PrintTemplateUpdate,
    PasswordReset,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    SystemParamCreate,
    SystemParamRead,
    SystemParamUpdate,
    SystemUserCreate,
    SystemUserRead,
    SystemUserUpdate,
)

router = APIRouter(prefix="/system", tags=["system"])

# 内置参数键集合：这些键在代码里有读取点，不允许删除（见 delete_param）
_BUILTIN_PARAM_KEYS = {str(spec["param_key"]) for spec in DEFAULT_PARAMS}


# ------------------------------------------------------------------
# 内部辅助
# ------------------------------------------------------------------
def _parse_permissions(raw: str | None) -> dict:
    """把 roles.permissions 的 JSON 文本解析成规范字典。坏数据不炸，退回最小权限。"""
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    menus = data.get("menus")
    return {
        "all": bool(data.get("all")),
        "menus": [str(key) for key in menus] if isinstance(menus, list) else [],
    }


def _normalize_permissions(payload: dict | None) -> str:
    """写入前归一：只保留已知字段、菜单键去重且**过滤掉目录里不存在的键**。"""
    data = payload if isinstance(payload, dict) else {}
    valid = set(all_menu_keys())
    menus = data.get("menus")
    clean_menus: list[str] = []
    if isinstance(menus, list):
        for key in menus:
            key = str(key)
            if key in valid and key not in clean_menus:
                clean_menus.append(key)
    return json.dumps({"all": bool(data.get("all")), "menus": clean_menus}, ensure_ascii=False)


def _user_counts_by_department(db: Session) -> dict[int, int]:
    rows = (
        db.query(User.department_id, func.count(User.id))
        .filter(User.department_id.isnot(None))
        .group_by(User.department_id)
        .all()
    )
    return {int(dept_id): int(count) for dept_id, count in rows}


def _user_counts_by_role(db: Session) -> dict[int, int]:
    rows = (
        db.query(User.role_id, func.count(User.id))
        .filter(User.role_id.isnot(None))
        .group_by(User.role_id)
        .all()
    )
    return {int(role_id): int(count) for role_id, count in rows}


def _department_tree(db: Session) -> list[dict]:
    """把扁平部门表组装成树（含每部门人数）。孤儿节点（父被删）自动提到顶层，不丢数据。"""
    departments = db.query(Department).order_by(Department.sort_order, Department.id).all()
    counts = _user_counts_by_department(db)
    nodes: dict[int, dict] = {}
    for dept in departments:
        nodes[dept.id] = {
            "id": dept.id,
            "code": dept.code,
            "name": dept.name,
            "parent_id": dept.parent_id,
            "leader": dept.leader,
            "phone": dept.phone,
            "level": dept.level,
            "sort_order": dept.sort_order,
            "is_active": dept.is_active,
            "note": dept.note,
            "user_count": counts.get(dept.id, 0),
            "children": [],
        }
    roots: list[dict] = []
    for node in nodes.values():
        parent = nodes.get(node["parent_id"]) if node["parent_id"] else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def _role_payload(role: Role, counts: dict[int, int]) -> dict:
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "permissions": _parse_permissions(role.permissions),
        "is_builtin": role.is_builtin,
        "sort_order": role.sort_order,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "user_count": counts.get(role.id, 0),
    }


def _user_payload(user: User, dept_names: dict[int, str], role_names: dict[int, str]) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "role_id": user.role_id,
        "role_name": role_names.get(user.role_id) if user.role_id else None,
        "department_id": user.department_id,
        "department_name": dept_names.get(user.department_id) if user.department_id else None,
        "phone": user.phone,
        "position": user.position,
        "remark": user.remark,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def _descendant_ids(db: Session, root_id: int) -> set[int]:
    """取出某部门的全部子孙 id（不含自身）。用于阻止把部门挪到自己子树下，形成环。"""
    children: dict[int, list[int]] = {}
    for dept_id, parent_id in db.query(Department.id, Department.parent_id).all():
        if parent_id is not None:
            children.setdefault(int(parent_id), []).append(int(dept_id))
    result: set[int] = set()
    stack = list(children.get(root_id, []))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def _next_department_code(db: Session) -> str:
    index = db.query(func.count(Department.id)).scalar() or 0
    for _ in range(1000):
        index += 1
        code = f"DEPT{index:03d}"
        if db.query(Department).filter(Department.code == code).first() is None:
            return code
    raise HTTPException(status_code=500, detail="部门编码生成失败")


# ------------------------------------------------------------------
# 元数据 / 当前用户权限
# ------------------------------------------------------------------
@router.get("/meta")
def system_meta(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> dict:
    """系统管理页开局要的全部下拉数据，一次取完。"""
    role_counts = _user_counts_by_role(db)
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    return {
        "departments": _department_tree(db),
        "roles": [_role_payload(role, role_counts) for role in roles],
        "permission_catalog": PERMISSION_CATALOG,
        "total_menus": len(all_menu_keys()),
    }


@router.get("/permissions")
def permission_catalog(_: User = Depends(require_roles("admin"))) -> dict:
    """权限点目录（角色权限树的唯一数据源）。"""
    return {"groups": PERMISSION_CATALOG, "total": len(all_menu_keys())}


@router.get("/me/permissions")
def my_permissions(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    """当前登录用户的可见菜单 + 界面偏好 —— 前端据此过滤导航、决定落地页。

    管理员（all=true）返回 `all_menu_keys()` 全集；普通用户按角色配置返回。
    角色被停用 / 角色丢失时退回 `["overview"]`，绝不放行全量菜单。

    `ui.default_page` / `ui.stock_warn_enabled` 顺带在这里下发：
    它们来自系统参数（`/system/params` 是管理员接口），普通用户读不到，
    但前端每个用户都需要 —— 放在这条人人可调的接口里最合适。
    """
    role = db.query(Role).filter(Role.code == current_user.role).first()
    if role is None or not role.is_active:
        menus = ["overview"]
        all_flag, role_name = False, None
    else:
        parsed = _parse_permissions(role.permissions)
        all_flag = parsed["all"]
        menus = all_menu_keys() if all_flag else parsed["menus"]
        role_name = role.name

    default_page = get_param(db, "system.default_page", "overview").strip() or "overview"
    # 落地页必须落在用户看得见的菜单里，否则登录后会被弹到一个空页面
    if default_page not in menus:
        default_page = "overview" if "overview" in menus else (menus[0] if menus else "")

    return {
        "role": current_user.role,
        "role_name": role_name,
        "all": all_flag,
        "menus": menus,
        "ui": {
            "default_page": default_page,
            "stock_warn_enabled": get_bool_param(db, "stock.warn_enabled", True),
        },
    }


# ------------------------------------------------------------------
# 组织机构
# ------------------------------------------------------------------
@router.get("/departments", response_model=list[DepartmentRead])
def list_departments(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[dict]:
    return _department_tree(db)


@router.get("/departments/options")
def department_options(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    """部门扁平选项（**任何登录用户可读**）。

    与 `lookups` 同一理由：业务表单（员工档案选部门、将来单据选领料车间）
    只需要一个下拉选项，不该为了拿选项而要求管理员权限。
    只返回 id / 编码 / 名称 / 层级，**不含用户数与负责人** —— 那些是管理信息。

    注意必须声明在 `/departments/{dept_id}` 之前，否则 "options" 会撞上路径参数。
    """
    rows = db.query(Department).order_by(Department.level, Department.sort_order, Department.id).all()
    return [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "parent_id": row.parent_id,
            "level": row.level or 0,
            # 前端直接拿 label 当下拉文案：层级用全角空格缩进，一眼看出归属
            "label": "　" * int(row.level or 0) + row.name,
            "is_active": row.is_active,
        }
        for row in rows
        if row.is_active
    ]


@router.post("/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="部门名称不能为空")

    parent: Department | None = None
    if payload.parent_id:
        parent = db.get(Department, int(payload.parent_id))
        if parent is None:
            raise HTTPException(status_code=400, detail="上级部门不存在")

    code = (payload.code or "").strip() or _next_department_code(db)
    if db.query(Department).filter(Department.code == code).first() is not None:
        raise HTTPException(status_code=400, detail=f"部门编码 {code} 已存在")

    dept = Department(
        code=code,
        name=name,
        parent_id=parent.id if parent else None,
        leader=payload.leader,
        phone=payload.phone,
        level=(parent.level + 1) if parent else 0,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        note=payload.note,
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    # 返回带 user_count/children 的结构，前端可直接挂到树上
    return {
        "id": dept.id,
        "code": dept.code,
        "name": dept.name,
        "parent_id": dept.parent_id,
        "leader": dept.leader,
        "phone": dept.phone,
        "level": dept.level,
        "sort_order": dept.sort_order,
        "is_active": dept.is_active,
        "note": dept.note,
        "user_count": 0,
        "children": [],
    }


@router.patch("/departments/{dept_id}", response_model=DepartmentRead)
def update_department(
    dept_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")

    data = payload.model_dump(exclude_unset=True)

    if "code" in data and data["code"]:
        new_code = str(data["code"]).strip()
        duplicated = db.query(Department).filter(Department.code == new_code, Department.id != dept_id).first()
        if duplicated is not None:
            raise HTTPException(status_code=400, detail=f"部门编码 {new_code} 已存在")
        dept.code = new_code

    if "name" in data and data["name"] is not None:
        name = str(data["name"]).strip()
        if not name:
            raise HTTPException(status_code=400, detail="部门名称不能为空")
        dept.name = name

    if "parent_id" in data:
        new_parent_id = data["parent_id"]
        if new_parent_id is not None:
            new_parent_id = int(new_parent_id)
            if new_parent_id == dept.id:
                raise HTTPException(status_code=400, detail="上级部门不能是自己")
            # 把部门挪到自己子孙下面会把树变成环，直接拒绝
            if new_parent_id in _descendant_ids(db, dept.id):
                raise HTTPException(status_code=400, detail="上级部门不能是自己的下级，会形成循环")
            parent = db.get(Department, new_parent_id)
            if parent is None:
                raise HTTPException(status_code=400, detail="上级部门不存在")
            dept.parent_id = new_parent_id
            dept.level = parent.level + 1
        else:
            dept.parent_id = None
            dept.level = 0

    for field in ("leader", "phone", "note", "sort_order", "is_active"):
        if field in data and data[field] is not None:
            setattr(dept, field, data[field])

    db.commit()
    db.refresh(dept)

    counts = _user_counts_by_department(db)
    return {
        "id": dept.id,
        "code": dept.code,
        "name": dept.name,
        "parent_id": dept.parent_id,
        "leader": dept.leader,
        "phone": dept.phone,
        "level": dept.level,
        "sort_order": dept.sort_order,
        "is_active": dept.is_active,
        "note": dept.note,
        "user_count": counts.get(dept.id, 0),
        "children": [],
    }


@router.delete("/departments/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    dept_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")

    child_count = db.query(Department).filter(Department.parent_id == dept_id).count()
    if child_count:
        raise HTTPException(status_code=409, detail=f"该部门下还有 {child_count} 个子部门，请先处理子部门")

    user_count = db.query(User).filter(User.department_id == dept_id).count()
    if user_count:
        raise HTTPException(status_code=409, detail=f"该部门下还有 {user_count} 个用户，请先调整这些用户的归属部门")

    # 员工档案也挂在部门上。不查这一下，删完部门会留下一批 department_id 指向
    # 不存在部门的员工 —— 列表里部门列空白，且没有任何入口能修回来。
    employee_count = db.query(Employee).filter(Employee.department_id == dept_id).count()
    if employee_count:
        raise HTTPException(
            status_code=409, detail=f"该部门下还有 {employee_count} 名员工，请先调整这些员工的归属部门"
        )

    db.delete(dept)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------
# 角色
# ------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleRead])
def list_roles(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[dict]:
    counts = _user_counts_by_role(db)
    roles = db.query(Role).order_by(Role.sort_order, Role.id).all()
    return [_role_payload(role, counts) for role in roles]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="角色编码不能为空")
    if db.query(Role).filter(Role.code == code).first() is not None:
        raise HTTPException(status_code=400, detail=f"角色编码 {code} 已存在")

    role = Role(
        code=code,
        name=payload.name,
        description=payload.description,
        permissions=_normalize_permissions(payload.permissions),
        is_builtin=False,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _role_payload(role, {})


@router.patch("/roles/{role_id}", response_model=RoleRead)
def update_role(
    role_id: int, payload: RoleUpdate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    data = payload.model_dump(exclude_unset=True)
    if "permissions" in data and data["permissions"] is not None:
        role.permissions = _normalize_permissions(data["permissions"])
    for field in ("name", "description", "sort_order", "is_active"):
        if field in data and data[field] is not None:
            setattr(role, field, data[field])

    db.commit()
    db.refresh(role)
    return _role_payload(role, _user_counts_by_role(db))


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_builtin:
        raise HTTPException(status_code=409, detail=f"「{role.name}」是内置角色，不允许删除")

    user_count = db.query(User).filter(User.role_id == role_id).count()
    if user_count:
        raise HTTPException(status_code=409, detail=f"还有 {user_count} 个用户使用该角色，请先调整这些用户的角色")

    db.delete(role)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------
# 用户
# ------------------------------------------------------------------
@router.get("/users", response_model=list[SystemUserRead])
def list_system_users(
    keyword: str | None = None,
    department_id: int | None = None,
    role_id: int | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[dict]:
    query = db.query(User)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            User.username.ilike(like) | User.full_name.ilike(like) | User.email.ilike(like)
        )
    if department_id:
        query = query.filter(User.department_id == int(department_id))
    if role_id:
        query = query.filter(User.role_id == int(role_id))
    if is_active is not None:
        query = query.filter(User.is_active.is_(bool(is_active)))

    dept_names = {dept.id: dept.name for dept in db.query(Department).all()}
    role_names = {role.id: role.name for role in db.query(Role).all()}
    users = query.order_by(User.id).all()
    return [_user_payload(user, dept_names, role_names) for user in users]


@router.post("/users", response_model=SystemUserRead, status_code=status.HTTP_201_CREATED)
def create_system_user(
    payload: SystemUserCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    username = (payload.username or "").strip()
    if db.query(User).filter(User.username == username).first() is not None:
        raise HTTPException(status_code=400, detail=f"用户名 {username} 已存在")

    email = (payload.email or "").strip() or f"{username}@erp.local"
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=400, detail=f"邮箱 {email} 已被占用")

    role_code, role_id = _resolve_role(db, payload.role_id, payload.role)
    if payload.department_id:
        if db.get(Department, int(payload.department_id)) is None:
            raise HTTPException(status_code=400, detail="所属部门不存在")

    user = User(
        username=username,
        email=email,
        full_name=payload.full_name,
        role=role_code,
        role_id=role_id,
        department_id=payload.department_id,
        phone=payload.phone,
        position=payload.position,
        remark=payload.remark,
        hashed_password=get_password_hash(payload.password),
        is_active=payload.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    dept_names = {dept.id: dept.name for dept in db.query(Department).all()}
    role_names = {role.id: role.name for role in db.query(Role).all()}
    return _user_payload(user, dept_names, role_names)


@router.patch("/users/{user_id}", response_model=SystemUserRead)
def update_system_user(
    user_id: int,
    payload: SystemUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"]:
        email = str(data["email"]).strip()
        duplicated = db.query(User).filter(User.email == email, User.id != user_id).first()
        if duplicated is not None:
            raise HTTPException(status_code=400, detail=f"邮箱 {email} 已被占用")
        user.email = email

    if "role_id" in data or "role" in data:
        role_code, role_id = _resolve_role(db, data.get("role_id"), data.get("role"))
        # 不允许把自己降级出 admin，否则最后一位管理员可能把自己锁在门外
        if user.id == current_user.id and role_code != "admin":
            raise HTTPException(status_code=400, detail="不能修改自己的管理员角色，请让其他管理员操作")
        user.role = role_code
        user.role_id = role_id

    if "department_id" in data:
        new_dept = data["department_id"]
        if new_dept:
            if db.get(Department, int(new_dept)) is None:
                raise HTTPException(status_code=400, detail="所属部门不存在")
            user.department_id = int(new_dept)
        else:
            user.department_id = None

    if "is_active" in data and data["is_active"] is not None:
        if user.id == current_user.id and not data["is_active"]:
            raise HTTPException(status_code=400, detail="不能停用当前登录的账号")
        user.is_active = bool(data["is_active"])

    for field in ("full_name", "phone", "position", "remark"):
        if field in data:
            setattr(user, field, data[field])

    db.commit()
    db.refresh(user)

    dept_names = {dept.id: dept.name for dept in db.query(Department).all()}
    role_names = {role.id: role.name for role in db.query(Role).all()}
    return _user_payload(user, dept_names, role_names)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_system_user(
    user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))
) -> Response:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")

    if user.role == "admin":
        admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
        if admins <= 1:
            raise HTTPException(status_code=409, detail="系统必须保留至少一个管理员账号")

    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/password")
def reset_user_password(
    user_id: int, payload: PasswordReset, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"id": user.id, "username": user.username, "message": "密码已重置"}


@router.post("/users/{user_id}/toggle", response_model=SystemUserRead)
def toggle_system_user(
    user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_roles("admin"))
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能停用当前登录的账号")
    if user.is_active:
        if user.role == "admin":
            admins = db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count()
            if admins <= 1:
                raise HTTPException(status_code=409, detail="系统必须保留至少一个启用状态的管理员账号")
        user.is_active = False
    else:
        user.is_active = True
    db.commit()
    db.refresh(user)

    dept_names = {dept.id: dept.name for dept in db.query(Department).all()}
    role_names = {role.id: role.name for role in db.query(Role).all()}
    return _user_payload(user, dept_names, role_names)


def _resolve_role(db: Session, role_id: int | None, role_code: str | None) -> tuple[str, int | None]:
    """把「角色 id 或角色 code」统一成 (code, id) 二元组。

    两者都给时以 role_id 为准（前端下拉传的就是 id）；
    都没给时退回默认的 staff；角色不存在直接报 400，不静默吞掉。
    """
    role: Role | None = None
    if role_id:
        role = db.get(Role, int(role_id))
        if role is None:
            raise HTTPException(status_code=400, detail="角色不存在")
    elif role_code:
        role = db.query(Role).filter(Role.code == str(role_code).strip()).first()
        if role is None:
            raise HTTPException(status_code=400, detail=f"角色 {role_code} 不存在")
    if role is None:
        return "staff", None
    return role.code, role.id


# ------------------------------------------------------------------
# 参数设置
# ------------------------------------------------------------------
def _param_default_value(param_key: str) -> str:
    """内置参数的出厂值；自定义参数没有默认值，返回空串。"""
    return param_default(param_key)


def _param_payload(row) -> dict:
    return {
        "id": row.id,
        "param_key": row.param_key,
        "param_value": row.param_value or "",
        "param_group": row.param_group,
        "label": row.label,
        "value_type": row.value_type,
        "description": row.description,
        "is_editable": row.is_editable,
        "sort_order": row.sort_order,
        "default_value": _param_default_value(row.param_key),
    }


def _validate_param_value(value_type: str, value: str) -> str:
    """按类型校验参数值。宁可 400 也不要把一个非法值写进去让程序在读的时候炸。"""
    text = "" if value is None else str(value)
    if value_type == "bool":
        lowered = text.strip().lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no", "on", "off", ""}:
            raise HTTPException(status_code=400, detail="开关型参数只能是 true / false")
        return "true" if lowered in {"true", "1", "yes", "on"} else "false"
    if value_type == "int":
        if text.strip() == "":
            return "0"
        try:
            return str(int(float(text)))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="整数型参数必须是数字") from exc
    if value_type == "decimal":
        if text.strip() == "":
            return "0"
        try:
            return str(round(float(text), 4))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="小数型参数必须是数字") from exc
    return text


@router.get("/params")
def list_params(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> dict:
    """按分组返回全部参数（含内置默认值，供前端「恢复默认」）。"""
    rows = db.query(SystemParam).order_by(SystemParam.param_group, SystemParam.sort_order, SystemParam.id).all()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.param_group, []).append(_param_payload(row))

    groups = []
    for group in PARAM_GROUPS:
        items = grouped.pop(group["group"], [])
        if items:
            groups.append({"group": group["group"], "label": group["label"], "items": items})
    # 管理员自建的分组（不在 PARAM_GROUPS 里）也要显示出来，不能吞掉
    for group_key, items in sorted(grouped.items()):
        groups.append({"group": group_key, "label": group_key, "items": items})

    return {
        "groups": groups,
        "total": len(rows),
        "value_types": [{"key": key, "label": label} for key, label in PARAM_VALUE_TYPES.items()],
    }


@router.put("/params")
def save_params(
    payload: ParamBatchSave, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    """批量保存参数值（页面上一次改好几个，一次提交）。

    只写已存在的键；不认识的键直接 400 —— 静默忽略会让用户以为保存成功了。
    """
    saved = 0
    unknown: list[str] = []
    locked: list[str] = []
    for item in payload.items:
        row = db.query(SystemParam).filter(SystemParam.param_key == item.param_key).first()
        if row is None:
            unknown.append(item.param_key)
            continue
        if not row.is_editable:
            locked.append(row.label or row.param_key)
            continue
        row.param_value = _validate_param_value(row.value_type, item.param_value)
        saved += 1

    if unknown:
        raise HTTPException(status_code=400, detail=f"未知参数：{'、'.join(unknown)}")
    if locked:
        raise HTTPException(status_code=400, detail=f"以下参数为系统只读项，不能修改：{'、'.join(locked)}")

    db.commit()
    return {"saved": saved, "message": f"已保存 {saved} 项参数"}


@router.post("/params", response_model=SystemParamRead, status_code=status.HTTP_201_CREATED)
def create_param(
    payload: SystemParamCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    key = payload.param_key.strip()
    if db.query(SystemParam).filter(SystemParam.param_key == key).first() is not None:
        raise HTTPException(status_code=400, detail=f"参数键 {key} 已存在")
    if payload.value_type not in PARAM_VALUE_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的类型：{payload.value_type}")

    row = SystemParam(
        param_key=key,
        param_value=_validate_param_value(payload.value_type, payload.param_value),
        param_group=(payload.param_group or "system").strip() or "system",
        label=payload.label.strip(),
        value_type=payload.value_type,
        description=payload.description,
        is_editable=True,
        sort_order=payload.sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _param_payload(row)


@router.patch("/params/{param_id}", response_model=SystemParamRead)
def update_param(
    param_id: int,
    payload: SystemParamUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    row = db.get(SystemParam, param_id)
    if row is None:
        raise HTTPException(status_code=404, detail="参数不存在")

    data = payload.model_dump(exclude_unset=True)
    value_type = data.get("value_type") or row.value_type
    if value_type not in PARAM_VALUE_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的类型：{value_type}")
    if "value_type" in data:
        row.value_type = value_type

    if "param_value" in data and data["param_value"] is not None:
        if not row.is_editable:
            raise HTTPException(status_code=400, detail="该参数为系统只读项，不能修改")
        row.param_value = _validate_param_value(value_type, data["param_value"])
    for field in ("label", "description", "param_group", "sort_order"):
        if field in data and data[field] is not None:
            setattr(row, field, data[field])

    db.commit()
    db.refresh(row)
    return _param_payload(row)


@router.delete("/params/{param_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_param(
    param_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    row = db.get(SystemParam, param_id)
    if row is None:
        raise HTTPException(status_code=404, detail="参数不存在")
    # 内置参数在代码里有读取点，删掉会让读取方永远走默认值且界面上看不到原因
    if _param_default_value(row.param_key) or row.param_key in _BUILTIN_PARAM_KEYS:
        raise HTTPException(status_code=409, detail=f"「{row.label}」是内置参数，不允许删除（可改值）")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------
# 数字字典
# ------------------------------------------------------------------
def _dict_payload(row, item_count: int) -> dict:
    return {
        "id": row.id,
        "dict_type": row.dict_type,
        "dict_name": row.dict_name,
        "description": row.description,
        "is_system": row.is_system,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "item_count": item_count,
    }


def _item_payload(row) -> dict:
    return {
        "id": row.id,
        "dict_type": row.dict_type,
        "item_value": row.item_value,
        "item_label": row.item_label,
        "sort_order": row.sort_order,
        "is_enabled": row.is_enabled,
        "remark": row.remark,
    }


@router.get("/dictionaries", response_model=list[DictionaryRead])
def list_dictionaries(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))) -> list[dict]:
    counts: dict[str, int] = {}
    for dict_type, count in (
        db.query(DataDictionaryItem.dict_type, func.count(DataDictionaryItem.id))
        .group_by(DataDictionaryItem.dict_type)
        .all()
    ):
        counts[str(dict_type)] = int(count)
    rows = db.query(DataDictionary).order_by(DataDictionary.id).all()
    return [_dict_payload(row, counts.get(row.dict_type, 0)) for row in rows]


@router.post("/dictionaries", response_model=DictionaryRead, status_code=status.HTTP_201_CREATED)
def create_dictionary(
    payload: DictionaryCreate, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    dict_type = payload.dict_type.strip()
    if db.query(DataDictionary).filter(DataDictionary.dict_type == dict_type).first() is not None:
        raise HTTPException(status_code=400, detail=f"字典编码 {dict_type} 已存在")
    row = DataDictionary(
        dict_type=dict_type,
        dict_name=payload.dict_name.strip(),
        description=payload.description,
        is_system=False,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _dict_payload(row, 0)


@router.patch("/dictionaries/{dict_id}", response_model=DictionaryRead)
def update_dictionary(
    dict_id: int,
    payload: DictionaryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    row = db.get(DataDictionary, dict_id)
    if row is None:
        raise HTTPException(status_code=404, detail="字典不存在")
    data = payload.model_dump(exclude_unset=True)
    for field in ("dict_name", "description", "is_active"):
        if field in data and data[field] is not None:
            setattr(row, field, data[field])
    db.commit()
    db.refresh(row)
    count = db.query(DataDictionaryItem).filter(DataDictionaryItem.dict_type == row.dict_type).count()
    return _dict_payload(row, count)


@router.delete("/dictionaries/{dict_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dictionary(
    dict_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    row = db.get(DataDictionary, dict_id)
    if row is None:
        raise HTTPException(status_code=404, detail="字典不存在")
    if row.is_system:
        raise HTTPException(status_code=409, detail=f"「{row.dict_name}」是内置字典，不允许删除（可停用或改项）")
    # 字典项跟着一起清掉，避免留下永远不会被读到的孤儿项
    db.query(DataDictionaryItem).filter(DataDictionaryItem.dict_type == row.dict_type).delete(
        synchronize_session=False
    )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/dictionaries/{dict_type}/items", response_model=list[DictionaryItemRead])
def list_dictionary_items(
    dict_type: str,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[dict]:
    query = db.query(DataDictionaryItem).filter(DataDictionaryItem.dict_type == dict_type)
    if enabled_only:
        query = query.filter(DataDictionaryItem.is_enabled.is_(True))
    rows = query.order_by(DataDictionaryItem.sort_order, DataDictionaryItem.id).all()
    return [_item_payload(row) for row in rows]


@router.post("/dictionaries/{dict_type}/items", response_model=DictionaryItemRead, status_code=status.HTTP_201_CREATED)
def create_dictionary_item(
    dict_type: str,
    payload: DictionaryItemCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    dic = db.query(DataDictionary).filter(DataDictionary.dict_type == dict_type).first()
    if dic is None:
        raise HTTPException(status_code=404, detail=f"字典 {dict_type} 不存在")

    value = payload.item_value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="字典项值不能为空")
    duplicated = (
        db.query(DataDictionaryItem)
        .filter(DataDictionaryItem.dict_type == dict_type, DataDictionaryItem.item_value == value)
        .first()
    )
    if duplicated is not None:
        raise HTTPException(status_code=400, detail=f"字典项「{value}」已存在")

    row = DataDictionaryItem(
        dict_type=dict_type,
        item_value=value,
        item_label=(payload.item_label or value).strip() or value,
        sort_order=payload.sort_order,
        is_enabled=payload.is_enabled,
        remark=payload.remark,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _item_payload(row)


@router.patch("/dictionary-items/{item_id}", response_model=DictionaryItemRead)
def update_dictionary_item(
    item_id: int,
    payload: DictionaryItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    row = db.get(DataDictionaryItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="字典项不存在")

    data = payload.model_dump(exclude_unset=True)
    if "item_value" in data and data["item_value"] is not None:
        value = str(data["item_value"]).strip()
        if not value:
            raise HTTPException(status_code=400, detail="字典项值不能为空")
        duplicated = (
            db.query(DataDictionaryItem)
            .filter(
                DataDictionaryItem.dict_type == row.dict_type,
                DataDictionaryItem.item_value == value,
                DataDictionaryItem.id != item_id,
            )
            .first()
        )
        if duplicated is not None:
            raise HTTPException(status_code=400, detail=f"字典项「{value}」已存在")
        row.item_value = value
    for field in ("item_label", "sort_order", "is_enabled", "remark"):
        if field in data:
            setattr(row, field, data[field])
    db.commit()
    db.refresh(row)
    return _item_payload(row)


@router.delete("/dictionary-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dictionary_item(
    item_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    row = db.get(DataDictionaryItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="字典项不存在")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/lookups")
def lookup_dictionaries(
    types: str = "", db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """给业务页面用的字典聚合读取口（**任何登录用户可读**）。

    业务表单（采购单的付款方式、商品档案的单位……）只需要候选列表，
    不该为了拿一列候选而要求管理员权限。所以这条是 system 路由里除
    `me/permissions` 之外第二条放开鉴权的接口。

    `types` 用逗号分隔，一次拿多个字典，省掉 N 次请求：
        GET /system/lookups?types=payment_method,product_unit
    只返回启用中的字典项；字典本身被停用时返回空列表。
    """
    wanted = [t.strip() for t in (types or "").split(",") if t.strip()]
    if not wanted:
        # 不传就返回全部启用中的字典（前端首屏一次性拉全，够用）
        wanted = [
            row.dict_type
            for row in db.query(DataDictionary).filter(DataDictionary.is_active.is_(True)).all()
        ]

    result: dict[str, list[dict]] = {}
    for dict_type in wanted:
        dic = db.query(DataDictionary).filter(DataDictionary.dict_type == dict_type).first()
        if dic is None or not dic.is_active:
            result[dict_type] = []
            continue
        rows = (
            db.query(DataDictionaryItem)
            .filter(DataDictionaryItem.dict_type == dict_type, DataDictionaryItem.is_enabled.is_(True))
            .order_by(DataDictionaryItem.sort_order, DataDictionaryItem.id)
            .all()
        )
        result[dict_type] = [{"value": row.item_value, "label": row.item_label} for row in rows]
    return result


# ------------------------------------------------------------------
# 打印模板
# ------------------------------------------------------------------
def _printable_registry() -> dict[str, str]:
    """{doc_type: 中文名}。延迟导入 erp，避免模块加载顺序上的耦合。"""
    from app.api.v1.routes.erp import printable_doc_types

    return dict(printable_doc_types())


def _template_payload(row: PrintTemplate, registry: dict[str, str]) -> dict:
    return {
        "id": row.id,
        "doc_type": row.doc_type,
        "doc_label": row.doc_label,
        "name": row.name or row.doc_label,
        "title": row.title or "",
        "header_text": row.header_text or "",
        "footer_text": row.footer_text or "",
        "show_company": row.show_company,
        "show_signatures": row.show_signatures,
        "note": row.note,
        "sort_order": row.sort_order,
        "registered": row.doc_type in registry,
        # 「恢复默认」要能看到出厂值：标题默认空（用单据自带的），模板名默认单据名
        "default_title": "",
        "default_name": registry.get(row.doc_type) or row.doc_label,
        "updated_at": row.updated_at,
    }


@router.get("/print-templates")
def list_print_templates(
    db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    """打印模板列表。

    模板**不是**新增出来的：一张单据的打印类型对应且仅对应一条模板，
    改的是外观项。所以这里没有 POST（新增），只有列表 / 修改 / 恢复默认。
    """
    registry = _printable_registry()
    rows = db.query(PrintTemplate).order_by(PrintTemplate.sort_order, PrintTemplate.id).all()
    items = [_template_payload(row, registry) for row in rows]
    return {
        "items": items,
        "total": len(items),
        # 注册表里有、但库里还没模板的类型（正常不会发生：启动时已播种）
        "missing": [key for key in registry if key not in {row.doc_type for row in rows}],
        "editable_fields": list(TEMPLATE_EDITABLE_FIELDS),
    }


@router.patch("/print-templates/{template_id}", response_model=PrintTemplateRead)
def update_print_template(
    template_id: int,
    payload: PrintTemplateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    row = db.get(PrintTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="打印模板不存在")

    data = payload.model_dump(exclude_unset=True)
    for field in TEMPLATE_EDITABLE_FIELDS:
        if field in data and data[field] is not None:
            value = data[field]
            setattr(row, field, value.strip() if isinstance(value, str) else value)
    if not (row.name or "").strip():
        row.name = row.doc_label
    db.commit()
    db.refresh(row)
    return _template_payload(row, _printable_registry())


@router.post("/print-templates/{template_id}/reset", response_model=PrintTemplateRead)
def reset_print_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> dict:
    """恢复默认：清空所有覆盖项，回到"单据自带标题 + 系统页脚"的出厂状态。"""
    row = db.get(PrintTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="打印模板不存在")
    row.name = row.doc_label
    row.title = ""
    row.header_text = ""
    row.footer_text = ""
    row.show_company = True
    row.show_signatures = True
    row.note = None
    db.commit()
    db.refresh(row)
    return _template_payload(row, _printable_registry())


# 模板预览用的样例数据。刻意用一眼能看出是假的名字，
# 避免预览图被误当成真单据发出去。
_SAMPLE_COLUMNS = [
    {"label": "序号", "width": 34, "align": "c"},
    {"label": "商品名称", "width": 150, "align": "l"},
    {"label": "规格", "width": 80, "align": "l"},
    {"label": "单位", "width": 40, "align": "c"},
    {"label": "数量", "width": 50, "align": "r"},
    {"label": "单价", "width": 60, "align": "r"},
    {"label": "金额", "width": 70, "align": "r"},
]


def _sample_print_spec(doc_label: str) -> dict:
    """给模板预览生成的样例 spec（不走数据库、不查任何单据）。"""
    from datetime import date

    from app.core.company_info import load_company

    rows = [
        ["1", "示例商品 A（样例数据）", "DN50", "件", 10, 25.00, 250.00],
        ["2", "示例商品 B（样例数据）", "M8×30", "盒", 4, 25.00, 100.00],
    ]
    return {
        "company": load_company()["own_name"],
        "title": doc_label or "单据打印",
        "doc_no": "示例单号-0000001",
        "header_left": [
            ("往来单位", "示例客户（样例数据）"),
            ("联系人", "张示例"),
            ("联系电话", "138-0000-0000"),
        ],
        "header_right": [
            ("单据日期", date.today().isoformat()),
            ("仓库", "成品仓"),
            ("业务员", "李示例"),
        ],
        "columns": _SAMPLE_COLUMNS,
        "rows": rows,
        "totals": {"label": "合计", "chinese": "大写：叁佰伍拾元整", "amount": "350.00"},
        "notes": ["本页为打印模板预览：使用样例数据生成，不是真实单据。"],
        "signatures": ["制单", "审核", "仓管", "客户签收"],
    }


@router.get("/print-templates/{template_id}/preview")
def preview_print_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))
) -> Response:
    """用样例数据把当前模板渲染成 PDF。

    有这个接口，"改了模板有没有效果"才不需要去找一张真单据打一遍 ——
    和参数设置页同一条思路：**改完立刻看得见**，否则用户只能猜。
    """
    from app.services.pdf_render import render_document_pdf

    row = db.get(PrintTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="打印模板不存在")

    spec = resolve_print_spec(db, row.doc_type, _sample_print_spec(row.doc_label))
    pdf = render_document_pdf(spec)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="template_{row.doc_type}_preview.pdf"'},
    )


# ------------------------------------------------------------------
# 操作日志
# ------------------------------------------------------------------
def _parse_day(value: str | None, *, end_of_day: bool = False):
    """YYYY-MM-DD → datetime；解析不了就返回 None（不报错，筛选条件作废）。"""
    from datetime import datetime, time, timedelta, timezone

    text = (value or "").strip()
    if not text:
        return None
    try:
        day = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        day = day + timedelta(days=1)
        return day.replace(tzinfo=timezone.utc)
    return day.replace(tzinfo=timezone.utc)


@router.get("/logs", response_model=OperationLogPage)
def list_operation_logs(
    keyword: str = "",
    method: str = "",
    username: str = "",
    status_code: int | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """操作日志分页查询（只读，管理员）。

    `keyword` 同时匹配动作名 / 路径 / 用户名 —— 一个框搜"谁对什么做了什么"。
    """
    query = db.query(OperationLog)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        query = query.filter(
            or_(
                OperationLog.action.ilike(like),
                OperationLog.path.ilike(like),
                OperationLog.username.ilike(like),
            )
        )
    if (method or "").strip():
        query = query.filter(OperationLog.method == method.strip().upper())
    if (username or "").strip():
        query = query.filter(OperationLog.username == username.strip())
    if status_code is not None:
        query = query.filter(OperationLog.status_code == int(status_code))
    start_at, end_at = _parse_day(start), _parse_day(end, end_of_day=True)
    if start_at is not None:
        query = query.filter(OperationLog.created_at >= start_at)
    if end_at is not None:
        query = query.filter(OperationLog.created_at < end_at)

    total = query.count()
    size = max(1, min(int(page_size or 20), 200))
    index = max(1, int(page or 1))
    rows = (
        query.order_by(OperationLog.id.desc()).offset((index - 1) * size).limit(size).all()
    )

    methods = [row[0] for row in db.query(OperationLog.method).distinct().order_by(OperationLog.method).all()]
    users = [
        row[0]
        for row in db.query(OperationLog.username)
        .distinct()
        .order_by(OperationLog.username)
        .limit(50)
        .all()
    ]

    return {
        "items": rows,
        "total": total,
        "page": index,
        "page_size": size,
        "pages": max(1, (total + size - 1) // size),
        "methods": [item for item in methods if item],
        "users": [item for item in users if item],
    }


@router.delete("/logs")
def clear_operation_logs(
    before_days: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> dict:
    """清理日志。`before_days=0` 清空全部，否则只删 N 天前的。

    注意：**这次清理动作本身也会被记一条日志**（中间件在响应之后写入），
    所以清空之后列表里还剩一条"删除操作日志" —— 这是有意为之：
    清理行为必须留痕，否则日志可以被无声抹掉就失去了意义。
    """
    query = db.query(OperationLog)
    if int(before_days or 0) > 0:
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=int(before_days))
        query = query.filter(OperationLog.created_at < cutoff)
    deleted = query.delete(synchronize_session=False)
    db.commit()
    return {
        "deleted": int(deleted),
        "message": f"已清理 {int(deleted)} 条操作日志" + ("" if not before_days else f"（{before_days} 天前）"),
    }
