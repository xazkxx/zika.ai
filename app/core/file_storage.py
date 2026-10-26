"""上传文件的本地存储 —— 项目里第一处"用户上传的二进制要留下来"的地方。

## 为什么单开一个模块

在此之前**没有任何文件被持久化过**：发票上传是"读进内存 → OCR → 丢掉"，
原文件一个字节都不落盘。要做"导出原始发票 PDF"，就得先补这条链路。
把它收在一个模块里，是为了让下面三件容易出错的事只有一处实现：

1. **存到哪**：不能存在代码目录里 —— 开发时是源码目录，打包后 `_MEIPASS` 是**只读**的
   解包目录，写进去必然失败。这里照抄 `company_info.py` 的既有做法：
   打包后写到 **exe 同目录**的 `data/`，未打包写项目根的 `data/`。
2. **存什么名**：用户上传的文件名不可信（可能带路径分隔符、可能重名、可能超长）。
   统一 `uuid 前缀 + 净化后的原名`，既避免碰撞/覆盖，又保住原名的可读性，
   下载时还能用原名回给用户。
3. **存什么路径进库**：存**相对路径**（相对 storage_root）。存绝对路径的话，
   换个盘 / 换台机器 / 从 D 盘同步到 E 盘，库里的路径全部失效。
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

# 单个上传文件的大小上限。扫描件 PDF 通常几 MB，20MB 已经足够宽松；
# 设上限是为了避免有人一次塞进来几百 MB 把磁盘写满。
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# 文件名里允许保留的字符；其余一律换成下划线
_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")
# 允许**原样保留**后缀的名单。不在名单里的一律改写成 `.bin` ——
# 这是为了不让落盘文件名变成 `.exe` / `.bat` 这类"双击就能跑"的东西。
#
# 第 13 批加 `.doc` / `.docx`：合同原件大量是 Word。之前它们会被写成 `.bin`，
# 用户下载下来双击打不开 —— 而 `.doc` 只是**被保存**，本系统从不执行它，
# 加进白名单不会带来新的执行面。`.exe` / `.bat` / `.cmd` / `.ps1` / `.js` 仍然没有。
_ALLOWED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".ofd",
    ".doc", ".docx",
}


def storage_root() -> Path:
    """存储根目录。

    ⚠️ 打包后必须落在 **exe 同目录**：`sys._MEIPASS` 是 PyInstaller 的只读解包目录，
    往里写文件会失败（而且下次启动就被覆盖）。这与 `company_info.company_file()` 同一套判断。
    """
    if getattr(sys, "_MEIPASS", None):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent.parent.parent / "data"


def invoice_dir() -> Path:
    target = storage_root() / "invoices"
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_filename(filename: str) -> str:
    """把用户给的文件名净化成"能安全落盘"的样子。

    保留中文（发票扫描件常常就是中文名），去掉路径分隔符与控制字符，
    并限制长度 —— 超长文件名在 Windows 上会直接写失败。
    """
    raw = (filename or "").strip().replace("\\", "/").split("/")[-1]
    cleaned = _SAFE_NAME_RE.sub("_", raw).strip("._") or "upload"
    suffix = Path(cleaned).suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIXES:
        # 后缀不认识就换成 .bin，避免落成 .exe / .bat 这类可执行名
        cleaned = f"{Path(cleaned).stem}.bin"
    stem = Path(cleaned).stem[:80]
    return f"{stem}{Path(cleaned).suffix}"


def save_bytes(payload: bytes, filename: str, subdir: str = "invoices") -> str:
    """落盘并返回**相对 storage_root 的相对路径**。"""
    if not payload:
        raise ValueError("empty payload")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")

    name = safe_filename(filename)
    rel = Path(subdir) / f"{uuid.uuid4().hex[:12]}-{name}"
    target = storage_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return rel.as_posix()


def absolute_path(rel_path: str | None) -> Path | None:
    """相对路径 → 绝对路径。同时挡住 `../` 这种越界访问。"""
    if not rel_path:
        return None
    root = storage_root().resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None  # 越界，拒绝
    return candidate


def read_bytes(rel_path: str | None) -> bytes | None:
    target = absolute_path(rel_path)
    if target is None or not target.is_file():
        return None
    return target.read_bytes()


def exists(rel_path: str | None) -> bool:
    target = absolute_path(rel_path)
    return bool(target and target.is_file())


def delete_file(rel_path: str | None) -> bool:
    """删除一个文件。**删不到不算错** —— 记录该删还是要删，不能因为文件不在了就删不掉记录。"""
    target = absolute_path(rel_path)
    if target is None or not target.is_file():
        return False
    try:
        target.unlink()
        return True
    except OSError:
        return False
