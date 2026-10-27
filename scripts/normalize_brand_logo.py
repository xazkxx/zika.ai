"""一次性工具：把 data/brand 里的两张图规整成"真 PNG + 裁掉透明边"。

为什么必须做这一步：
1. 用户丢进来的 `logo_ui.png` / `logo_print.png` 内容其实是 **WebP**
   （扩展名骗人）。浏览器能靠嗅探显示，但
   - python-docx 的 `add_picture` 只认 png/jpeg/gif/bmp/tiff，喂 WebP 直接抛异常；
   - 静态服务按扩展名发 `image/png`，配 WebP 字节属于"标签与实际不符"。
   所以统一转成真 PNG。
2. 这两张图有 58%~86% 的透明留白。不裁的话，界面按 30px 高度渲染时，
   真正有内容的笔画只占几十个像素，中文副标题必糊。裁到 alpha 外接框后
   同样的显示高度能多出一倍有效分辨率。

用法（仓库根目录）：
    .venv\\Scripts\\python.exe scripts\\normalize_brand_logo.py
幂等：已经是"真 PNG 且无多余透明边"的图，重跑不会越裁越小（用的就是 getbbox）。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

BRAND_DIR = Path(__file__).resolve().parents[1] / "data" / "brand"

# 文件名 -> (裁边后保留的透明内边距比例, 是否允许放大)
TARGETS = [
    ("logo_ui.png", 0.02),
    ("logo_print.png", 0.01),
]


def normalize(path: Path, pad_ratio: float) -> None:
    original = Image.open(path)
    fmt, size = original.format, original.size
    image = original.convert("RGBA")

    bbox = image.getchannel("A").getbbox()
    if bbox:
        left, top, right, bottom = bbox
        pad_x = int((right - left) * pad_ratio)
        pad_y = int((bottom - top) * pad_ratio)
        image = image.crop(
            (
                max(left - pad_x, 0),
                max(top - pad_y, 0),
                min(right + pad_x, image.width),
                min(bottom + pad_y, image.height),
            )
        )

    # 真 PNG（RGBA）。optimize 不影响观感，只是让文件小一点。
    image.save(path, format="PNG", optimize=True)
    print(
        f"{path.name}: {fmt} {size[0]}x{size[1]} -> PNG {image.width}x{image.height}"
        f"  比例 {image.width / image.height:.2f}  {path.stat().st_size / 1024:.1f} KB"
    )


def main() -> None:
    for name, pad in TARGETS:
        candidate = BRAND_DIR / name
        if not candidate.is_file():
            print(f"跳过 {name}（文件不存在）")
            continue
        normalize(candidate, pad)


if __name__ == "__main__":
    main()
