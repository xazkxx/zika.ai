"""单据归档服务 —— P0-5（2026-10-26）。

把「作废 / 删除一张单据」这件事**先写进证据表，再动业务表**：
谁、什么时候、从哪个 IP、对哪张单、原来是什么状态、金额多少、
明细长什么样、原件在哪、为什么作废 —— 一次写全。

三条约束
--------
1. **先归档、后动账**：归档写失败就抛异常，宁可这次作废失败，
   也不能出现「单据没了、证据也没有」；
2. **原件永不删除**：发票的 PDF/图片从 `data/invoices` 移到
   `data/archive/invoices`，文件名加时间戳避免重名，路径记进 `files`；
3. **不提供修改/删除归档的接口** —— 审计表能改就等于没有。

为什么归档放在业务库（而不是日志库）
------------------------------------
单据快照含有客户价格、成本、明细，属于**账套数据**；放进公共 schema
会让 A 账套的明细从 B 账套的接口里漏出去。所以 `document_archives`
是账套表，随 `get_db()` 的 search_path 走。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session

from app.core import file_storage
from app.models.document_archive import DocumentArchive

# 归档后的原件目录（相对 storage_root），与在用目录 data/invoices 分开
ARCHIVE_SUBDIR = "archive/invoices"


def actor_of(request: Request | None, db: Session) -> dict[str, object]:
    """从请求里解析操作人（快照）。拿不到就记匿名 —— 不许因此失败。"""
    if request is None:
        return {"id": None, "name": "", "role": "", "ip": ""}
    try:
        from app.core.security import bearer_token, decode_access_token
        from app.models.user import User

        payload = decode_access_token(bearer_token(request.headers.get("authorization"))) or {}
        username = str(payload.get("sub") or "")
        user = db.query(User).filter(User.username == username).first() if username else None
        return {
            "id": user.id if user is not None else None,
            "name": username or (user.username if user is not None else ""),
            "role": (user.role if user is not None else str(payload.get("role") or "")),
            "ip": request.client.host if request.client else "",
        }
    except Exception:  # 审计信息拿不到，绝不能连累业务请求
        return {"id": None, "name": "", "role": "", "ip": ""}


def _jsonable(value: object) -> object:
    """把 Pydantic 模型 / 带 model_dump 的对象转成可 JSON 化的结构。

    为什么需要：单据 payload 有的是 dict（退货单），有的是 Pydantic 模型
    （`SalesOrderRead` / `PurchaseOrderRead`）。直接 `json.dumps(default=str)` 会把
    模型整个变成一串 repr 文本 —— 归档里看着"有内容"，实际谁也解析不出来。
    """
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return value


def archive_document(
    db: Session,
    *,
    doc_type: str,
    doc_id: int | None,
    doc_no: str | None,
    action: str = "void",
    status_before: str | None = None,
    status_after: str | None = None,
    total_amount: float = 0.0,
    reason: str = "",
    payload: object | None = None,
    files: list[str] | None = None,
    request: Request | None = None,
) -> DocumentArchive:
    """写一条归档记录（**不 commit**，由调用方与业务改动同一事务提交）。"""
    actor = actor_of(request, db)
    row = DocumentArchive(
        doc_type=doc_type,
        doc_id=doc_id,
        doc_no=(doc_no or "")[:64] or None,
        action=action,
        status_before=status_before,
        status_after=status_after,
        total_amount=float(total_amount or 0.0),
        reason=(reason or "").strip() or None,
        actor_id=actor["id"],  # type: ignore[arg-type]
        actor_name=str(actor["name"] or "")[:64],
        actor_role=str(actor["role"] or "")[:40],
        ip=str(actor["ip"] or "")[:64],
        payload=json.dumps(_jsonable(payload), ensure_ascii=False, default=str) if payload is not None else None,
        files=json.dumps(files or [], ensure_ascii=False) if files else None,
    )
    db.add(row)
    return row


def archive_file(rel_path: str | None, *, doc_no: str | None = None) -> str | None:
    """把原件移到归档目录（**移动，不删除**），返回归档后的相对路径。

    拿不到文件（路径不存在 / 越界 / 已被手工删掉）就返回 None ——
    归档记录照写，不能让"文件找不到"阻止单据作废。
    """
    source = file_storage.absolute_path(rel_path)
    if source is None or not source.is_file():
        return None
    target_dir = file_storage.storage_root() / ARCHIVE_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = file_storage.safe_filename(doc_no or "")[:40].replace(".", "_") or "invoice"
    target = target_dir / f"{prefix}-{stamp}-{source.name}"
    if target.exists():  # 同一秒内重名：加 uuid 尾巴，绝不覆盖已有原件
        target = target_dir / f"{prefix}-{stamp}-{Path(source.stem).name}-{id(source)}{source.suffix}"
    try:
        shutil.move(str(source), str(target))
    except OSError:
        return None
    return target.relative_to(file_storage.storage_root()).as_posix()
