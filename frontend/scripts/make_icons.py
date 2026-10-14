"""生成 PWA 应用图标：1024 底图 → 512 / 192 / 180(苹果) 三张 PNG。

用法（在 frontend 目录下）：
    python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "icons"
BASE_SIZE = 1024

# 品牌色：蓝紫渐变，圆角方块 + 白色 ERP 字样
TOP = (37, 99, 235)      # #2563eb
BOTTOM = (30, 64, 175)   # #1e40af


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_base() -> Image.Image:
    img = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 垂直渐变圆角方块
    radius = int(BASE_SIZE * 0.22)
    for y in range(BASE_SIZE):
        t = y / BASE_SIZE
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (BASE_SIZE, y)], fill=color + (255,))
    mask = Image.new("L", (BASE_SIZE, BASE_SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, BASE_SIZE, BASE_SIZE], radius=radius, fill=255
    )
    rounded = Image.new("RGBA", (BASE_SIZE, BASE_SIZE), (0, 0, 0, 0))
    rounded.paste(img, (0, 0), mask)

    # 白色 ERP 文字
    d = ImageDraw.Draw(rounded)
    font = pick_font(int(BASE_SIZE * 0.30))
    text = "ERP"
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        ((BASE_SIZE - w) / 2 - bbox[0], (BASE_SIZE - h) / 2 - bbox[1]),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )
    return rounded


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = make_base()
    for name, size in (
        ("icon-512.png", 512),
        ("icon-192.png", 192),
        ("apple-touch-icon.png", 180),
    ):
        base.resize((size, size), Image.LANCZOS).save(OUT_DIR / name)
        print(f"已生成: public/icons/{name}")


if __name__ == "__main__":
    main()
