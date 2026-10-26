"""附件归档与备份（2026-10-23）。

## 为什么需要这一块

附件（合同原件、付款回单、模板、发票扫描件、客户资料）散在 `data/` 的几个子目录里，
时间一长没人知道"到底占了多少、还剩多少、怎么整体拷走"。
这里给三件事：**看清楚**、**算得准**、**一键打包**。

## 三个口径

1. **只统计白名单目录**（`ATTACHMENT_DIRS`）。`data/` 里还有数据库导出、
   日志之类的非附件内容，一起算进去会让用户误以为"附件占了 20G"。
2. **备份里排除 `backups/` 自身**：不然备份会嵌套备份，每点一次体积翻倍。
3. **磁盘剩余**用 `shutil.disk_usage(data_root)` —— 统计的是 data 所在分区，
   而不是某个文件的挂载点，换盘符也不会算错。
"""

from __future__ import annotations

import base64
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core import file_storage

router = APIRouter(tags=["storage"])

# 只统计/打包这些子目录（相对 data/）
ATTACHMENT_DIRS = [
    ("contracts", "合同原件"),
    ("contract_templates", "合同模板"),
    ("contract_receipts", "付款回单"),
    ("customer-files", "客户资料"),
    ("invoices", "发票扫描件"),
    ("products", "商品图片"),
]

BACKUP_DIR = "backups"

# 在线下载（base64 通道）的体积上限：超过这个大小就把用户指到磁盘目录去
BASE64_MAX_BYTES = 200 * 1024 * 1024


def _root() -> Path:
    return file_storage.storage_root()


def _dir_stats(root: Path, name: str) -> dict[str, object]:
    """一个目录的文件数与体积。读不到的单个文件跳过，不因为一个坏文件让整页报错。"""
    folder = root / name
    files = 0
    size = 0
    if folder.is_dir():
        for item in folder.rglob("*"):
            try:
                if item.is_file():
                    files += 1
                    size += item.stat().st_size
            except OSError:
                continue
    return {"name": name, "files": files, "bytes": size, "exists": folder.is_dir()}


def _backup_files(root: Path) -> list[dict[str, object]]:
    folder = root / BACKUP_DIR
    if not folder.is_dir():
        return []
    rows = []
    for item in sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = item.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": item.name,
                "bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return rows


@router.get("/system/attachment-storage", summary="附件归档概览")
def attachment_storage() -> dict[str, object]:
    root = _root()
    dirs = [{"label": label, **_dir_stats(root, name)} for name, label in ATTACHMENT_DIRS]
    total_files = sum(int(item["files"]) for item in dirs)
    total_bytes = sum(int(item["bytes"]) for item in dirs)

    try:
        usage = shutil.disk_usage(str(root))
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        disk = {"total": 0, "used": 0, "free": 0}

    return {
        "root": str(root),
        "dirs": dirs,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "disk": disk,
        "backups": _backup_files(root),
        "backup_dir": str(root / BACKUP_DIR),
    }


@router.post("/system/attachment-backup", summary="一键备份所有附件")
def attachment_backup() -> dict[str, object]:
    """把所有附件目录打成一个 zip 放到 `data/backups/`。

    ⚠️ 不用 `shutil.make_archive`：它会把 `data/backups` 自身也打进去
    （如果备份目录就在 data 下），第二次备份体积直接翻倍。
    这里显式遍历白名单目录，天然排除 backups。
    """
    root = _root()
    target_dir = root / BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"附件备份_{stamp}.zip"
    target = target_dir / name

    added = 0
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for dir_name, _label in ATTACHMENT_DIRS:
                folder = root / dir_name
                if not folder.is_dir():
                    continue
                for item in folder.rglob("*"):
                    if not item.is_file():
                        continue
                    try:
                        archive.write(item, arcname=str(item.relative_to(root)).replace("\\", "/"))
                        added += 1
                    except (OSError, ValueError):
                        # 单个文件被占用/名字非法：跳过，但备份继续 —— 不能因为一个文件整包失败
                        continue
    except Exception as exc:  # noqa: BLE001
        if target.exists():
            target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"备份失败：{type(exc).__name__}") from exc

    stat = target.stat()
    return {
        "name": name,
        "bytes": stat.st_size,
        "files": added,
        "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "path": str(target),
        "message": f"已备份 {added} 个文件，压缩后 {round(stat.st_size / 1024 / 1024, 2)} MB",
    }


@router.get("/system/attachment-backup/{name}", summary="下载备份包")
def download_backup(name: str, as_: str = Query("file", alias="as")) -> object:
    """下载备份包。`?as=base64` 走"JSON 里塞 base64"的通道。

    ## 为什么默认还要留一个 base64 通道（2026-10-23 实测）

    前端是 `fetch + blob` 下载（要带 Authorization 头，不能用 `<a href>` 直链）。
    但 **Chrome 对 `.zip` 直链的 fetch 会回一个空的 204**：
    同一条 URL 用 curl 是 200 + 19MB，浏览器里 `response.status` 是 204、body 0 字节，
    用户点「下载」只会得到一个 0 字节的 zip。加一个 `Range: bytes=0-1023` 头反而能拿到全量，
    说明是浏览器对"可执行/压缩包类下载"的拦截策略，不是服务端的问题
    （CSV 导出、内联 PNG 都正常，只有 .zip 被吃）。

    处理方式和打印 PDF 完全一致：**别指望二进制直链，改成 base64 走 JSON**。
    代价是传输体积 +33%，但备份包下载是低频操作，换来"点了就真能拿到文件"。

    ⚠️ 200MB 以上的包不做 base64（字符串化会把浏览器内存顶爆），
    直接告诉用户去 `data/backups/` 里拷 —— 那个目录本来就是给人看的。
    """
    # 只允许下载 backups 目录下的 .zip，挡掉 ../ 之类的路径穿越
    safe = Path(name).name
    if not safe.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只能下载 .zip 备份包")
    target = _root() / BACKUP_DIR / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail="备份包不存在")

    mode = str(as_ or "file").lower()
    if mode == "base64":
        size = target.stat().st_size
        if size > BASE64_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"备份包 {round(size / 1024 / 1024, 1)}MB 超过在线下载上限"
                    f"（{BASE64_MAX_BYTES // (1024 * 1024)}MB），"
                    f"请直接在 {target.parent} 里拷贝"
                ),
            )
        return {
            "filename": safe,
            "bytes": size,
            "content_base64": base64.b64encode(target.read_bytes()).decode("ascii"),
        }

    return FileResponse(
        path=str(target),
        media_type="application/zip",
        filename=safe,
    )
