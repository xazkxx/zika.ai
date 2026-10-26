"""合同模板库接口（2026-10-22）。

## 这一组接口解决什么

用户手里已经有自己的合同范本（Word / PDF / 扫描件），系统的内置范本再好也只是"一种"。
模板库让这些文件**上传一次、反复套用**：
    上传模板 → 新建合同时选它 → 生成单据 → 详情里「下载完整合同」拿到的就是
    "自己的模板 + 系统填好的数据"打包件。

## 三条设计约束

1. **文件落 `data/contract_templates/`**，路径只存相对 storage_root 的那一段 ——
   绝对路径换机器就失效（与发票原件、合同原件同一口径）。
2. **`mime_type` 必须自己判**（先看上传声明，再看后缀），因为后面要按它分派：
   图片/PDF → 可在线预览、可合成；Word → 走变量替换。
3. **删模板不删历史合同**：`contracts.template_id` 允许指向已删除的模板，
   读出来时模板字段为空即可 —— 历史合同不能因为"模板被清理"就打不开。
"""

from __future__ import annotations

import mimetypes
from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import file_storage
from app.db.session import get_db
from app.models.contract_template import ContractTemplate

router = APIRouter(tags=["contract-templates"])

TEMPLATE_SUBDIR = "contract_templates"

# 允许的模板类型：Word（可做变量替换）、PDF（可预览/合成）、图片（扫描件，可预览/合成）
ALLOWED_SUFFIXES = {".doc", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 单文件上限：模板是"范本"，不该有几十兆。太大一律拒（也避免一次上传卡住服务）
MAX_TEMPLATE_BYTES = 30 * 1024 * 1024


def _mime_of(filename: str, declared: str | None = None) -> str:
    """判定模板类型：优先看真实后缀（声明值可能是 application/octet-stream）。"""
    suffix = Path(filename or "").suffix.lower()
    guessed = mimetypes.guess_type(f"x{suffix}")[0]
    if guessed:
        return guessed
    return (declared or "application/octet-stream").strip() or "application/octet-stream"


def _serialize(row: ContractTemplate) -> dict[str, object]:
    kind = "word" if (row.file_name or "").lower().endswith((".doc", ".docx")) else (
        "pdf" if (row.mime_type or "") == "application/pdf" else (
            "image" if (row.mime_type or "").startswith("image/") else "other"
        )
    )
    return {
        "id": row.id,
        "name": row.name,
        "note": row.note,
        "file_name": row.file_name,
        "file_size": row.file_size,
        "mime_type": row.mime_type,
        # kind 是给前端用的：决定"能不能预览""能不能自动套数据"
        "kind": kind,
        "previewable": kind in ("pdf", "image"),
        "supports_variables": kind == "word",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/contract-templates", summary="模板库列表")
def list_contract_templates(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = db.query(ContractTemplate).order_by(ContractTemplate.id.desc()).all()
    out: list[dict[str, object]] = []
    ghost_ids: list[int] = []
    for row in rows:
        # 幽灵记录清扫（2026-10-24）：磁盘文件已经不在的记录，留在下拉里只会让用户
        # "选了却预览不了/下载报错"。这里静默清掉记录（与 scripts/cleanup_ghost_templates.py
        # 同一口径）；文件删除失败/正被占用时 exists 仍为 True，不会误删。
        if not file_storage.exists(row.file_path):
            ghost_ids.append(row.id)
            continue
        out.append(_serialize(row))
    if ghost_ids:
        db.query(ContractTemplate).filter(ContractTemplate.id.in_(ghost_ids)).delete(
            synchronize_session=False
        )
        db.commit()
    return out


@router.post("/contract-templates", status_code=status.HTTP_201_CREATED, summary="上传模板")
async def create_contract_template(
    file: UploadFile = File(...),
    name: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """上传一份合同模板。

    校验顺序刻意是"先看后缀再看大小再落盘"：
    后缀不认识的文件直接拒，不要先存进来再报错 —— 那样目录里会留一堆 .bin 垃圾。
    """
    filename = (file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模板格式「{suffix or '无后缀'}」，请上传 Word(.doc/.docx)、PDF 或图片",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="模板文件是空的，请重新选择")
    if len(payload) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=400, detail=f"模板超过 {MAX_TEMPLATE_BYTES // (1024 * 1024)}MB 上限"
        )

    try:
        rel_path = file_storage.save_bytes(payload, filename, subdir=TEMPLATE_SUBDIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    label = (name or "").strip() or Path(filename).stem
    row = ContractTemplate(
        name=label[:150],
        note=(note or "").strip()[:500] or None,
        file_path=rel_path,
        file_name=filename,
        file_size=len(payload),
        mime_type=_mime_of(filename, file.content_type),
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        # 记录没写成 → 刚落盘的文件就是孤儿，一起清掉
        file_storage.delete_file(rel_path)
        raise
    return _serialize(row)


@router.get("/contract-templates/{template_id}/file", summary="查看/下载模板原件")
def get_contract_template_file(
    template_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    raw = file_storage.read_bytes(row.file_path)
    if raw is None:
        raise HTTPException(status_code=404, detail="该模板文件已损坏或丢失，请重新上传")
    disposition = "attachment" if download else "inline"
    return Response(
        content=raw,
        media_type=row.mime_type or "application/octet-stream",
        headers={
            # 中文文件名必须 RFC 5987 百分号编码：响应头是 latin-1，直接塞中文会 500
            "Content-Disposition": (
                f"{disposition}; filename*=UTF-8''"
                f"{quote(file_storage.safe_filename(row.file_name or 'template'))}"
            ),
            "Cache-Control": "private, max-age=60",
        },
    )


@router.get("/contract-templates/{template_id}/variables", summary="提取 Word 模板里的变量标签")
def get_contract_template_variables(template_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    """扫描 Word 模板里的 {{变量}}，告诉用户"这个模板需要填哪些数据"。

    .docx 是 zip 包，直接解 word/document.xml 正则提取，去重保序。
    .doc（老二进制格式）解不了 —— 明确告诉用户转存 .docx；
    PDF/图片没有变量概念，回空列表。
    """
    import re
    import zipfile
    from io import BytesIO

    row = db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    name_lower = (row.file_name or "").lower()
    if not name_lower.endswith((".doc", ".docx")):
        return {"variables": [], "supported": False, "message": "该模板不是 Word 文档，没有可列出的变量"}

    raw = file_storage.read_bytes(row.file_path)
    if raw is None:
        raise HTTPException(status_code=404, detail="该模板文件已损坏或丢失，请重新上传")
    if not name_lower.endswith(".docx"):
        return {
            "variables": [],
            "supported": False,
            "message": "老版 .doc 格式无法在线解析变量，请用 Word 另存为 .docx 后重新上传",
        }
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(status_code=400, detail="模板文件损坏（不是有效的 .docx 包）") from exc

    # ⚠️ Word 常把 "{{变量}}" 拆进多个 <w:t> run（"{{" / "变量" / "}}"）。
    # 先剥掉全部 XML 标签把纯文本缝起来，再提变量 —— 否则一半变量都会漏。
    text = re.sub(r"<[^>]+>", "", xml)
    seen: list[str] = []
    for match in re.findall(r"\{\{([^{}]+)\}\}", text):
        var = match.strip()
        if var and var not in seen:
            seen.append(var)
    return {"variables": seen, "supported": True, "message": ""}


@router.delete("/contract-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="删除模板")
def delete_contract_template(template_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(ContractTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    file_storage.delete_file(row.file_path)
    db.delete(row)
    db.commit()
    # 历史合同上的 template_id 不做级联清理：合同本身是法律文件，
    # 不能因为"模板被删了"就把合同上的溯源字段抹掉。
    return Response(status_code=status.HTTP_204_NO_CONTENT)
