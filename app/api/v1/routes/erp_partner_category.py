"""客户 / 供应商分类树 —— 增删改查 + 拖拽落点（2026-10-17 · 第二阶段）

## 这一层只做"树的形状"，不碰业务字段

分类表本身很薄（id / name / parent_id / sort_order / note），真正容易出错的是
**树的三条不变量**，这个文件 90% 的代码都在守它们：

1. **不重名**：同一父级下不得同名。库里有两条部分唯一索引兜底（见模型注释），
   这里再显式查一次，只为返回中文 400 —— 撞索引只会吐一句英文
   `duplicate key value violates unique constraint`，用户看不懂。
2. **不成环**：不能把节点挂到它自己或它的任一后代下。没有这条，一次误拖
   就能让整棵树从 `GET` 里消失（构建时递归进死循环）。
3. **不留孤儿引用**：还有客户/供应商挂在上面时不准删（409），
   而不是把它们的 `category_id` 悄悄置空 —— 那等于无声地改用户的档案。

## 为什么 `/move` 要单独一个接口

拖拽的本质是"**放到谁下面、排在谁前面**"，而不是"把 sort_order 改成 37"。
如果让前端自己算序号，两个人的拖拽必然撞号（都写 15），顺序就随机了。
所以前端只发落点，服务端把**目标父级下的整段兄弟**重排成 10、20、30…，
留出空档方便将来手工插一条。

`/move` 与 `PATCH {parent_id}` 的区别：PATCH 只改层级、不动兄弟顺序；
`/move` 是拖拽专用，会重排。前端拖拽一律用 `/move`。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.customer import Customer
from app.models.partner_category import CustomerCategory, SupplierCategory
from app.models.supplier import Supplier
from app.schemas import (
    CustomerCategoryCreate,
    CustomerCategoryNode,
    CustomerCategoryRead,
    CustomerCategoryUpdate,
    PartnerCategoryMove,
    SupplierCategoryCreate,
    SupplierCategoryNode,
    SupplierCategoryRead,
    SupplierCategoryUpdate,
)

router = APIRouter(prefix="", tags=["erp"])

# 树的最大深度。真实组织架构不会到 20 层，这里只是**防"数据里有环"时把进程递归到崩**的
# 兜底：一旦数据被手工改出环，超过这个深度就停止下探，页面还能出来、用户看到的是
# "某几个节点不见了"，而不是整个接口 500、页面白屏。
MAX_TREE_DEPTH = 32


@dataclass(frozen=True)
class _Tree:
    """一棵分类树要用到的全部"元信息"。

    两张表的字段完全一样，逻辑一行不用分叉 —— 所以把差异收进这个 dataclass，
    底下所有 helper 只认它。想给客户侧单独加规则时，也只改这里。
    """

    key: str  # 'customer' / 'supplier'
    label: str  # 中文名，用于报错文案
    model: type  # CustomerCategory / SupplierCategory
    owner: type  # Customer / Supplier（档案表，用来数引用）
    owner_label: str  # '客户' / '供应商'


CUSTOMER_TREE = _Tree("customer", "客户", CustomerCategory, Customer, "客户")
SUPPLIER_TREE = _Tree("supplier", "供应商", SupplierCategory, Supplier, "供应商")


# ============================================================================
# 内部工具
# ============================================================================


def _commit(db: Session) -> None:
    """统一提交。把唯一索引冲突翻译成人话。

    为什么还要留这层：上面已经显式查过重名，但"查"和"写"之间仍可能被并发插一条。
    这时数据库的唯一索引会抛 `IntegrityError`，不接住就是 500 —— 用户看到的是
    "服务器错误"，而我们其实完全知道发生了什么。
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="同一上级下已有同名分类") from exc


def _counts_by_category(db: Session, tree: _Tree) -> dict[int, int]:
    """每个分类下**直接**挂了多少条档案（一条 SQL，N+1 在这里堵掉）。"""
    rows = (
        db.query(tree.owner.category_id, func.count(tree.owner.id))
        .filter(tree.owner.category_id.isnot(None))
        .group_by(tree.owner.category_id)
        .all()
    )
    return {int(category_id): int(total) for category_id, total in rows}


def _build_tree(nodes: list, counts: dict[int, int]) -> list[dict]:
    """扁平节点 → 嵌套树，顺带算出 `count`（直接）与 `total`（含子孙）。

    `total` 用后序累加算在**一次遍历**里（先递归子节点、再把自己的 count 加上去），
    不做"每个节点扫一遍全表"那种 O(n²) 的傻事。

    ⚠️ `depth` 与 `seen` 是防"数据里有环"的：树是用户拖出来的，
    正常路径挡得住环，但手工改库 / 导入脚本仍可能造出来。一旦成环，
    没有这两个守卫就是 `RecursionError` → 接口 500 → 整个客户档案页打不开。
    """
    by_parent: dict[int | None, list] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    seen: set[int] = set()

    def walk(parent_id: int | None, depth: int) -> list[dict]:
        if depth > MAX_TREE_DEPTH:
            return []
        result: list[dict] = []
        for node in by_parent.get(parent_id, []):
            if node.id in seen:  # 环：这个节点已经在祖先链上出现过了
                continue
            seen.add(node.id)
            children = walk(node.id, depth + 1)
            direct = counts.get(node.id, 0)
            result.append(
                {
                    "id": node.id,
                    "name": node.name,
                    "parent_id": node.parent_id,
                    "sort_order": node.sort_order,
                    "note": node.note,
                    "created_at": node.created_at,
                    "count": direct,
                    "total": direct + sum(child["total"] for child in children),
                    "children": children,
                }
            )
        return result

    return walk(None, 0)


def _load_tree(db: Session, tree: _Tree) -> list[dict]:
    nodes = (
        db.query(tree.model)
        .order_by(tree.model.sort_order, tree.model.id)
        .all()
    )
    return _build_tree(nodes, _counts_by_category(db, tree))


def _assert_name_unique(
    db: Session, tree: _Tree, name: str, parent_id: int | None, exclude_id: int | None = None
) -> None:
    """同一父级下不重名（`parent_id` 为 NULL 时也要挡 —— 顶级最容易撞名）。"""
    query = db.query(tree.model).filter(tree.model.name == name)
    # `== None` 在 SQLAlchemy 里会翻成 IS NULL，这里刻意用 is_(None) 让意图明确
    query = query.filter(
        tree.model.parent_id.is_(None) if parent_id is None else tree.model.parent_id == parent_id
    )
    if exclude_id is not None:
        query = query.filter(tree.model.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=400, detail=f"同一上级下已有同名{tree.label}分类")


def _is_descendant(db: Session, tree: _Tree, ancestor_id: int, node_id: int) -> bool:
    """`node_id` 是否在 `ancestor_id` 的子孙链上（沿 parent_id 向上走）。

    向上走而不是向下扫：向上最多走树的深度（几十步），向下要把整棵子树捞出来。
    顺带用 `seen` 挡住数据里已有的环，否则这里自己就会死循环。
    """
    current: int | None = node_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        row = db.get(tree.model, current)
        current = row.parent_id if row else None
    return False


def _assert_parent_ok(
    db: Session, tree: _Tree, parent_id: int | None, moving_id: int | None = None
) -> None:
    """校验目标父级：必须存在、不能是自己、不能是自己的后代。"""
    if parent_id is None:
        return  # 移到顶级永远合法
    if db.get(tree.model, parent_id) is None:
        raise HTTPException(status_code=400, detail="上级分类不存在")
    if moving_id is not None:
        if parent_id == moving_id:
            raise HTTPException(status_code=400, detail="不能把分类挂到它自己下面")
        if _is_descendant(db, tree, moving_id, parent_id):
            raise HTTPException(status_code=400, detail="不能把分类挂到它自己的下级下面")


def _get_or_404(db: Session, tree: _Tree, category_id: int):
    node = db.get(tree.model, category_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{tree.label}分类不存在")
    return node


def _create(db: Session, tree: _Tree, payload) -> object:
    data = payload.model_dump()
    data["name"] = (data.get("name") or "").strip()
    if not data["name"]:
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    _assert_parent_ok(db, tree, data.get("parent_id"))
    _assert_name_unique(db, tree, data["name"], data.get("parent_id"))
    node = tree.model(**data)
    db.add(node)
    _commit(db)
    db.refresh(node)
    return node


def _update(db: Session, tree: _Tree, category_id: int, payload):
    node = _get_or_404(db, tree, category_id)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名称不能为空")
        data["name"] = name

    # 改名或换父级才需要重查重名；只改 sort_order / note 时不必白查一次
    if "name" in data or "parent_id" in data:
        parent_id = data["parent_id"] if "parent_id" in data else node.parent_id
        _assert_parent_ok(db, tree, parent_id, moving_id=node.id)
        _assert_name_unique(db, tree, data.get("name", node.name), parent_id, exclude_id=node.id)

    for field, value in data.items():
        setattr(node, field, value)
    _commit(db)
    db.refresh(node)
    return node


def _delete(db: Session, tree: _Tree, category_id: int) -> None:
    """删分类：有子分类、或仍有档案挂在上面，一律 409（不级联、不置空）。"""
    node = _get_or_404(db, tree, category_id)

    child = db.query(tree.model).filter(tree.model.parent_id == category_id).first()
    if child is not None:
        raise HTTPException(
            status_code=409,
            detail=f"「{node.name}」下还有子分类，请先删除或移走子分类",
        )

    used = (
        db.query(func.count(tree.owner.id))
        .filter(tree.owner.category_id == category_id)
        .scalar()
    )
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {used} 个{tree.owner_label}属于「{node.name}」，请先把它们改到别的分类",
        )

    db.delete(node)
    _commit(db)


def _move(db: Session, tree: _Tree, category_id: int, payload: PartnerCategoryMove):
    """拖拽落点：改父级 + 把**目标父级下的兄弟**整段重排成 10/20/30…"""
    node = _get_or_404(db, tree, category_id)
    target_parent = payload.parent_id

    _assert_parent_ok(db, tree, target_parent, moving_id=node.id)
    _assert_name_unique(db, tree, node.name, target_parent, exclude_id=node.id)

    siblings = [
        row
        for row in db.query(tree.model)
        .filter(
            tree.model.parent_id.is_(None)
            if target_parent is None
            else tree.model.parent_id == target_parent
        )
        .order_by(tree.model.sort_order, tree.model.id)
        .all()
        if row.id != node.id
    ]

    # 先定顺序：插到 `before_id` 前面；`before_id` 不在目标父级下就当"排最后"
    ordered: list = list(siblings)
    insert_at = next(
        (index for index, row in enumerate(siblings) if row.id == payload.before_id),
        len(siblings),
    )
    ordered.insert(insert_at, node)

    node.parent_id = target_parent
    for index, row in enumerate(ordered):
        row.sort_order = (index + 1) * 10

    _commit(db)
    db.refresh(node)
    return node


# ============================================================================
# 客户分类
# ============================================================================


@router.get("/customer-categories", response_model=list[CustomerCategoryNode])
def list_customer_categories(db: Session = Depends(get_db)) -> list[dict]:
    """客户分类树（无限极）。节点自带 `count`（直接）与 `total`（含子孙）。"""
    return _load_tree(db, CUSTOMER_TREE)


@router.post(
    "/customer-categories",
    response_model=CustomerCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_category(payload: CustomerCategoryCreate, db: Session = Depends(get_db)):
    """新建客户分类。不传 `parent_id` 就是顶级。"""
    return _create(db, CUSTOMER_TREE, payload)


@router.patch("/customer-categories/{category_id}", response_model=CustomerCategoryRead)
def update_customer_category(
    category_id: int, payload: CustomerCategoryUpdate, db: Session = Depends(get_db)
):
    """改名 / 改上级 / 改排序 / 改备注。**只改传了的字段**（`exclude_unset`）。"""
    return _update(db, CUSTOMER_TREE, category_id, payload)


@router.delete("/customer-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer_category(category_id: int, db: Session = Depends(get_db)) -> Response:
    """删分类。有子分类或仍有客户挂在上面 → 409。"""
    _delete(db, CUSTOMER_TREE, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/customer-categories/{category_id}/move", response_model=CustomerCategoryRead)
def move_customer_category(
    category_id: int, payload: PartnerCategoryMove, db: Session = Depends(get_db)
):
    """拖拽：移到 `parent_id` 下，排在 `before_id` 前面。`before_id` 为 null = 排最后。"""
    return _move(db, CUSTOMER_TREE, category_id, payload)


# ============================================================================
# 供应商分类（与客户侧逐行同构，故只在有差异处注释）
# ============================================================================


@router.get("/supplier-categories", response_model=list[SupplierCategoryNode])
def list_supplier_categories(db: Session = Depends(get_db)) -> list[dict]:
    """供应商分类树（无限极）。"""
    return _load_tree(db, SUPPLIER_TREE)


@router.post(
    "/supplier-categories",
    response_model=SupplierCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier_category(payload: SupplierCategoryCreate, db: Session = Depends(get_db)):
    """新建供应商分类。"""
    return _create(db, SUPPLIER_TREE, payload)


@router.patch("/supplier-categories/{category_id}", response_model=SupplierCategoryRead)
def update_supplier_category(
    category_id: int, payload: SupplierCategoryUpdate, db: Session = Depends(get_db)
):
    """改名 / 改上级 / 改排序 / 改备注。"""
    return _update(db, SUPPLIER_TREE, category_id, payload)


@router.delete("/supplier-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier_category(category_id: int, db: Session = Depends(get_db)) -> Response:
    """删分类。有子分类或仍有供应商挂在上面 → 409。"""
    _delete(db, SUPPLIER_TREE, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/supplier-categories/{category_id}/move", response_model=SupplierCategoryRead)
def move_supplier_category(
    category_id: int, payload: PartnerCategoryMove, db: Session = Depends(get_db)
):
    """拖拽：移到 `parent_id` 下，排在 `before_id` 前面。"""
    return _move(db, SUPPLIER_TREE, category_id, payload)
