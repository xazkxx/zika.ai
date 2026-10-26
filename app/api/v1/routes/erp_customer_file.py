"""客户文件归档（第 13 批 · 第二阶段 · 模块 2 的路由层）。

一个客户下面挂 N 个文件：合同扫描件、营业执照、资质证书、发票、对账单、其他。

## 三个刻意的设计选择

1. **数据库记录与磁盘文件分开管**
   `original_name` 是给用户看的原名，`stored_name` 是落盘名（uuid 前缀 + 扩展名）。
   同名文件不会互相覆盖，中文名/特殊字符也不会把路径搞坏。

2. **上传时按内容算 sha256 去重**
   同一份 PDF 反复拖进同一个客户，不会变成 3 条记录 3 个文件。
   命中已有文件时返回 **200 + `duplicate: true`**（而不是 201），前端可以据此提示
   "这份文件已经在库里了"，而不是又建一条。

3. **删除客户前必须先删文件（外键 RESTRICT，不可绕过）**
   见 `app/models/customer_file.py` 文件头的取舍表。路由侧的两道防线：
   · `erp_archive._delete_archive` 里先 `count_customer_files()` → 409 带中文原因；
   · 万一漏了，数据库会抛 `IntegrityError`，那里也兜成 409（不是 500）。

## 为什么不鉴权

与全仓业务路由保持一致（`/customers`、`/contracts`、`/invoices` 同样只 `Depends(get_db)`）：
本系统是**本机 / 内网单机部署**，安全边界在防火墙，不在接口上。
单独给文件接口加鉴权而不给列表接口加，只是让前端多写一套 fetch，并不能提高安全性。
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.v1.routes.erp_common import _attachment_response, _paginate, _wants_json
from app.core import file_storage
from app.db.session import get_db
from app.models.customer import Customer
from app.models.customer_file import (
    CUSTOMER_FILE_CATEGORIES,
    CUSTOMER_FILE_MIME_WHITELIST,
    CustomerFile,
    count_customer_files,
)

router = APIRouter(prefix="", tags=["erp"])

# 归档文件的落盘子目录前缀：每个客户一个子目录，便于人工翻 data/ 时按客户找
CUSTOMER_FILE_SUBDIR = "customer-files"

# 按**文件头**认格式（不认扩展名，扩展名是调用方说了算的）。
# 比合同原件多放了 xls/xlsx —— 客户常常把对账单、报价表当 Excel 发过来。
_ALLOWED_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".docx"),  # OOXML 族（docx/xlsx 都是 zip，靠扩展名再细分）
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".doc"),  # 老式 Office（doc/xls）
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)

# 允许的后缀（落盘用）。与 `_ALLOWED_SIGNATURES` 配合：zip 族按原扩展名区分 docx/xlsx。
ALLOWED_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
)


def detect_suffix(payload: bytes, original_name: str) -> str | None:
    """按文件头认出真实格式；认不出返回 None。

    zip 族（docx/xlsx）的魔数完全一样，只能靠原名后缀区分 ——
    这是唯一一处"必须参考扩展名"的地方，而且**仅在文件头已经确认是 zip 之后**。
    """
    if not payload:
        return None
    declared = Path(original_name or "").suffix.lower()
    for magic, suffix in _ALLOWED_SIGNATURES:
        if payload.startswith(magic):
            if suffix == ".docx":
                # 同样是 PK 开头：xlsx 归 xlsx，其余一律当 docx
                return ".xlsx" if declared in (".xlsx", ".xls") else ".docx"
            return suffix
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith(b"BM") and payload[6:8] == b"\x00\x00":
        return ".bmp"
    if payload[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    return None


def _customer_or_404(db: Session, customer_id: int) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


def _file_or_404(db: Session, file_id: int) -> CustomerFile:
    row = db.get(CustomerFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="归档文件不存在")
    return row


def _file_payload(row: CustomerFile) -> dict[str, object]:
    """单条归档文件的出参。

    `download_url` 直接给前端拼好的地址（`<a href>` 点一下就下载）——
    让每个调用方自己拼 `/customer-files/{id}/download` 是重复劳动，也容易写错。
    """
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "original_name": row.original_name,
        "stored_name": row.stored_name,
        "file_size": row.file_size,
        "mime_type": row.mime_type,
        "checksum": row.checksum,
        "category": row.category,
        "category_label": CUSTOMER_FILE_CATEGORIES.get(row.category, row.category),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "uploaded_by": row.uploaded_by,
        "note": row.note,
        "download_url": f"/api/v1/customer-files/{row.id}/download",
        # 文件可能被人在磁盘上手工删掉 —— 列表里要能看出"这条记录已经找不到文件了"
        "file_exists": file_storage.exists(row.file_path),
    }


@router.get("/customer-files/meta")
def customer_file_meta() -> dict[str, object]:
    """客户文件抽屉的字典：分类、允许的格式、大小上限。"""
    return {
        "categories": [
            {"code": code, "label": label} for code, label in CUSTOMER_FILE_CATEGORIES.items()
        ],
        "mime_whitelist": list(CUSTOMER_FILE_MIME_WHITELIST),
        "accept": list(ALLOWED_SUFFIXES),
        "accept_attr": ",".join(ALLOWED_SUFFIXES),
        "max_bytes": file_storage.MAX_UPLOAD_BYTES,
        "max_mb": file_storage.MAX_UPLOAD_BYTES // 1024 // 1024,
    }


@router.get("/customers/{customer_id}/files")
def list_customer_files(
    customer_id: int,
    db: Session = Depends(get_db),
    category: str | None = Query(None),
    keyword: str | None = Query(None),
    skip: int = 0,
    limit: int | None = None,
) -> list[dict[str, object]]:
    _customer_or_404(db, customer_id)

    query = db.query(CustomerFile).filter(CustomerFile.customer_id == customer_id)
    if category:
        if category not in CUSTOMER_FILE_CATEGORIES:
            raise HTTPException(status_code=400, detail="分类只能是 contract/qualification/invoice/statement/other")
        query = query.filter(CustomerFile.category == category)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(or_(CustomerFile.original_name.ilike(like), CustomerFile.note.ilike(like)))
    query = query.order_by(CustomerFile.uploaded_at.desc(), CustomerFile.id.desc())
    return [_file_payload(row) for row in _paginate(query, skip, limit).all()]


@router.get("/customers/{customer_id}/files/stats")
def customer_file_stats(customer_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """按分类计数 —— 客户列表上的角标、抽屉里的 tab 徽标都靠它。

    单开一个接口而不是塞进列表响应：列表会被分页/筛选，拿它算总数一定算错。
    """
    _customer_or_404(db, customer_id)
    rows = (
        db.query(CustomerFile.category, CustomerFile.id)
        .filter(CustomerFile.customer_id == customer_id)
        .all()
    )
    by_category = {code: 0 for code in CUSTOMER_FILE_CATEGORIES}
    for category, _id in rows:
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "customer_id": customer_id,
        "total": len(rows),
        "by_category": by_category,
        "labels": CUSTOMER_FILE_CATEGORIES,
    }


@router.post(
    "/customers/{customer_id}/files",
    status_code=status.HTTP_201_CREATED,
    summary="上传客户归档文件",
)
async def upload_customer_file(
    customer_id: int,
    file: UploadFile = File(...),
    category: str = Form("other"),
    note: str = Form(""),
    uploaded_by: str = Form(""),
    db: Session = Depends(get_db),
):
    """上传一个文件并挂到客户下。

    · 内容是唯一判据：按文件头认格式，不认扩展名；
    · 同一个客户下同一份内容（sha256 相同）**不会**产生第二条记录，
      返回 200 + `duplicate: true` + 已有记录的 id。
    """
    _customer_or_404(db, customer_id)

    if category and category not in CUSTOMER_FILE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail="分类只能是 contract（合同）/ qualification（资质）/ invoice（发票）/ statement（对账单）/ other（其他）",
        )
    category = category or "other"

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    if len(payload) > file_storage.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"文件 {len(payload) / 1024 / 1024:.1f}MB 超过 "
                f"{file_storage.MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限"
            ),
        )

    original_name = (file.filename or "").strip() or "未命名文件"
    suffix = detect_suffix(payload, original_name)
    if suffix is None:
        raise HTTPException(
            status_code=400,
            detail="认不出这个文件的格式（只支持 PDF / Word / Excel / 图片：png jpg bmp webp tif）",
        )

    checksum = hashlib.sha256(payload).hexdigest()
    existing = (
        db.query(CustomerFile)
        .filter(CustomerFile.customer_id == customer_id, CustomerFile.checksum == checksum)
        .first()
    )
    if existing is not None:
        # 内容一模一样 → 不重复落盘、不重复建记录。返回 200 而不是 201，
        # 前端据此提示"这份文件已经在库里了"，而不是又跳出一条新记录。
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                **_file_payload(existing),
                "duplicate": True,
                "message": f"这份文件与已有记录「{existing.original_name}」内容相同，未重复上传",
            },
        )

    stem = Path(file_storage.safe_filename(original_name)).stem or "file"
    try:
        rel_path = file_storage.save_bytes(
            payload, f"{stem}{suffix}", subdir=f"{CUSTOMER_FILE_SUBDIR}/{customer_id}"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = CustomerFile(
        customer_id=customer_id,
        original_name=original_name[:255],
        stored_name=Path(rel_path).name,
        file_path=rel_path,
        file_size=len(payload),
        mime_type=mimetypes.guess_type(rel_path)[0] or file.content_type or "application/octet-stream",
        checksum=checksum,
        category=category,
        uploaded_by=(uploaded_by or None),
        note=(note or None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**_file_payload(row), "duplicate": False, "message": "已归档"}


@router.get("/customer-files/{file_id}/download", summary="下载客户归档文件")
def download_customer_file(file_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    """下载归档文件。默认二进制附件，`Accept: application/json` 时走 base64 JSON。"""
    row = _file_or_404(db, file_id)
    if not row.file_path:
        raise HTTPException(status_code=404, detail="这条记录没有对应的磁盘文件（可能是补录的记录）")

    payload = file_storage.read_bytes(row.file_path)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"文件已丢失（记录里的路径是 {row.file_path}），请重新上传",
        )

    filename = row.original_name or row.stored_name
    media = row.mime_type or "application/octet-stream"
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": media,
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "size": len(payload),
            }
        )
    return _attachment_response(payload, filename, media)


@router.patch("/customer-files/{file_id}", summary="修改归档文件信息")
def update_customer_file(
    file_id: int, payload: dict[str, object], db: Session = Depends(get_db)
) -> dict[str, object]:
    """改名 / 改分类 / 改备注。**不换文件内容** —— 换内容请重新上传（那是另一份文件）。"""
    row = _file_or_404(db, file_id)

    changed: list[str] = []
    if "original_name" in payload:
        name = str(payload.get("original_name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        row.original_name = name[:255]
        changed.append("original_name")
    if "category" in payload:
        category = str(payload.get("category") or "").strip().lower()
        if category not in CUSTOMER_FILE_CATEGORIES:
            raise HTTPException(status_code=400, detail="分类只能是 contract/qualification/invoice/statement/other")
        row.category = category
        changed.append("category")
    if "note" in payload:
        note = payload.get("note")
        row.note = None if note in ("", None) else str(note)[:255]
        changed.append("note")

    if not changed:
        raise HTTPException(status_code=400, detail="没有可修改的字段（支持 original_name / category / note）")

    db.commit()
    db.refresh(row)
    return {**_file_payload(row), "changed": changed, "message": "已更新"}


@router.delete("/customer-files/{file_id}", summary="删除归档文件")
def delete_customer_file(
    file_id: int,
    purge: bool = Query(True, description="是否同时删除磁盘文件；false 只删记录（用于误删恢复）"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """删除归档文件。

    `purge=true`（默认）连磁盘文件一起删 —— 用户点"删除"期待的就是这个。
    真要"只删记录、文件留在磁盘上"，传 `purge=false`：
    这样误删之后还能从 `data/customer-files/<客户id>/` 手工捞回来。
    """
    row = _file_or_404(db, file_id)
    path = row.file_path
    name = row.original_name
    customer_id = row.customer_id
    db.delete(row)
    db.commit()

    removed = file_storage.delete_file(path) if purge else False
    if removed:
        _prune_empty_customer_dir(customer_id)
    return {
        "id": file_id,
        "original_name": name,
        "record_deleted": True,
        "file_removed": removed,
        "purged": bool(purge),
        "message": "已删除" if purge else "记录已删除，磁盘文件已保留",
    }


def _prune_empty_customer_dir(customer_id: int) -> None:
    """删掉最后一个文件后顺手清掉空目录。

    `rmdir` 只在**目录为空**时成功，所以不需要先判断有没有别的文件：
    还有文件就抛 OSError，这里吞掉即可。不清的话，反复增删会在
    `data/customer-files/` 下留一堆空目录（实测跑一轮测试就留下 9 个）。
    """
    target = file_storage.storage_root() / CUSTOMER_FILE_SUBDIR / str(customer_id)
    try:
        target.rmdir()
    except OSError:
        pass


@router.get("/customers/{customer_id}/files/count", summary="客户归档文件数")
def customer_file_count(customer_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """只需要一个数字时用它（客户列表行上的角标）—— 比拉整个列表便宜得多。"""
    _customer_or_404(db, customer_id)
    n = count_customer_files(db, customer_id)
    return {"customer_id": customer_id, "count": n}
