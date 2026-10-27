"""品牌 Logo 的唯一入口（v1.81.0，2026-10-26）

为什么单独一个模块
------------------
前端要 `/logo.png`、Word 要 `data/brand/logo_print.png`、PDF 也要同一张 ——
三处各自拼路径，早晚会出现"网页上有图、打印出来空白"这种鬼故事。
所以路径规则只写在这里：**没有文件就返回 None**，调用方一律"拿不到就整段跳过"。

两条设计约束
------------
1. **缺图不是错误**。用户在别的电脑上、或者还没把图放进来时，
   登录页 / 页眉必须和 1.80.0 长得一模一样（回退到原来的矢量 mark），
   绝不能因为少一张 png 就抛异常、打印空白页。
2. **不读包内资源**。打包后 `_MEIPASS` 是只读解包目录，用户换 Logo 要能生效，
   所以只认 exe 同目录的 `data/brand/`（与 `file_storage.storage_root()` 同一套判断）。

文件名约定（见 `data/brand/README.md`）：
    logo_ui.png     界面用（透明底、长边 ≥ 512）
    logo_print.png  打印用（红黑扁平、白底）
允许 jpg/jpeg 兜底：用户随手存成 .jpg 也能用，不至于因为后缀卡住。
"""

from __future__ import annotations

from pathlib import Path

from app.core.file_storage import storage_root

# 打印页眉里的视觉高度。1.15cm ≈ 32.6pt（比 12pt 正文高 2.7 倍，A4 上不抢戏）；
# 配合 `header_distance = 0.6cm`，页眉整体仍落在 1.8cm 的上边距里，
# 正文第一行不会因为加了 Logo 被顶下去（对账单那种紧凑版式尤其重要）。
PRINT_LOGO_HEIGHT_CM = 1.15
PRINT_LOGO_HEIGHT_PT = 32.6
HEADER_DISTANCE_CM = 0.6

UI_LOGO_NAMES = ("logo_ui.png", "logo_ui.jpg", "logo_ui.jpeg", "logo_ui.webp")
PRINT_LOGO_NAMES = ("logo_print.png", "logo_print.jpg", "logo_print.jpeg", "logo_print.webp")

# python-docx（add_picture）只认这几种格式的**内容**。这里按文件头判断，不看后缀 ——
# 用户给的两张图就是 "*.png 的名字 + WEBP 内容"，只看后缀会把它们当安全格式放过去。
_DOCX_SAFE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a",              # GIF
    b"GIF89a",
    b"II*\x00",             # TIFF (little endian)
    b"MM\x00*",             # TIFF (big endian)
)


def _is_docx_safe(path: Path) -> bool:
    """文件头是不是 python-docx 能直接吃的格式。"""
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
    except OSError:
        # 读不了就当不安全，交给下游 try/except 兜底
        return False
    if head.startswith(b"BM"):  # BMP
        return True
    return any(head.startswith(magic) for magic in _DOCX_SAFE_MAGIC)


def brand_dir() -> Path:
    """Logo 目录。只返回路径，**不创建**：读的地方不该顺手改磁盘。"""
    return storage_root() / "brand"


def _first_existing(names: tuple[str, ...]) -> Path | None:
    folder = brand_dir()
    for name in names:
        candidate = folder / name
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            # 权限/路径异常都当"没有这张图"，不让它变成 500
            continue
    return None


def ui_logo_path() -> Path | None:
    """界面 Logo（登录页、侧栏）。前端实际读的是构建时同步过去的 `/logo.png`。"""
    return _first_existing(UI_LOGO_NAMES)


def print_logo_path() -> Path | None:
    """打印 Logo（Word 页眉 / PDF 抬头）。None = 没放图，按原版式输出。"""
    return _first_existing(PRINT_LOGO_NAMES)


def print_logo_image() -> Path | None:
    """打印 Logo，但**保证是 python-docx / fitz 吃得下的格式**。没有图就是 None。

    为什么还要一层转码（v1.81.1 实测教训）
    --------------------------------------
    用户丢进来的 `logo_ui.png` / `logo_print.png` 内容其实是 **WebP**（只改了扩展名）。
    浏览器靠内容嗅探照样显示，但 python-docx 的 `add_picture` 只认
    png/jpeg/gif/bmp/tiff，喂 WebP 会抛 `UnrecognizedImageError`；
    而 `_page_header_logo` 的铁律是"出图失败就当没 Logo"——
    结果是**网页上有图、Word 页眉静默空白**，不报错、极难发现。

    所以凡是 docx / PDF 的调用方都走这个函数：**文件头**不在安全名单里，
    就用 Pillow 转一张 PNG 落到临时缓存再返回。缓存键 = 文件名 + mtime + 大小，
    用户换图后自然失效，不会拿旧图；转码失败或没装 Pillow 就退回原路径，
    让调用方自己的 try/except 去兜（宁可没 Logo 也不能让开单导出失败）。
    """
    path = print_logo_path()
    if path is None:
        return None
    # 关键：按**内容**判断，不能看后缀。用户给的 "*.png" 内容是 WebP，
    # 只看后缀会把它当安全格式原样交给 add_picture，然后静默失败。
    if _is_docx_safe(path):
        return path
    try:
        import hashlib
        import tempfile

        from PIL import Image

        stat = path.stat()
        key = hashlib.sha1(
            f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
        ).hexdigest()[:16]
        cache_dir = Path(tempfile.gettempdir()) / "erp_brand_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"{key}.png"
        if not target.is_file():
            with Image.open(path) as image:
                image.convert("RGBA").save(target, format="PNG", optimize=True)
        return target
    except Exception:  # noqa: BLE001 —— 转码失败不能连累出单/打印
        return path
