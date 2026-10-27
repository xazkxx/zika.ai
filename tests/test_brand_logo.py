"""品牌 Logo 取图逻辑的回归（v1.81.1）。

只测 `app/services/brand_logo.py`，不碰数据库、不起 app —— 它本身是纯路径/转码逻辑。

背景（2026-10-26 实测踩中）：
用户丢进来的 `logo_ui.png` / `logo_print.png` **内容是 WebP**（只改了扩展名）。
浏览器靠内容嗅探照样显示，但 python-docx 的 `add_picture` 只认 png/jpeg/gif/bmp/tiff，
喂 WebP 会抛 `UnrecognizedImageError`，而调用方是"失败就当没 Logo" ——
结果是网页有图、Word 页眉静默空白，不报错。这三条用例把这个行为钉住。
"""
from __future__ import annotations

import pytest
from PIL import Image

from app.services import brand_logo


@pytest.fixture()
def brand_dir(tmp_path, monkeypatch):
    """把 Logo 目录指向临时目录（`print_logo_image` 内部走 `brand_dir()`）。"""
    monkeypatch.setattr(brand_logo, 'brand_dir', lambda: tmp_path)
    return tmp_path


def test_missing_logo_returns_none(brand_dir):
    """没放图必须返回 None，调用方才好"整段跳过"，绝不能抛异常。"""
    assert brand_logo.print_logo_path() is None
    assert brand_logo.print_logo_image() is None


def test_real_png_is_returned_untouched(brand_dir):
    """真 PNG 不该被无谓转码（否则每张图多一次 IO + 一份临时文件）。"""
    path = brand_dir / 'logo_print.png'
    Image.new('RGBA', (80, 40), (200, 30, 30, 255)).save(path, format='PNG')

    assert brand_logo.print_logo_path() == path
    assert brand_logo.print_logo_image() == path


def test_webp_disguised_as_png_is_transcoded(brand_dir):
    """**核心用例**：扩展名 .png 但内容是 WebP 时，必须交出真 PNG。"""
    path = brand_dir / 'logo_print.png'
    Image.new('RGBA', (120, 60), (20, 20, 20, 255)).save(path, format='WEBP')
    # 前提确认：确实是"假 PNG"，否则这条用例就失去意义了
    assert path.read_bytes()[8:12] == b'WEBP'

    result = brand_logo.print_logo_image()

    assert result is not None
    assert result != path, 'WebP 必须走转码分支，不能原样返回'
    assert result.suffix == '.png'
    assert result.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    with Image.open(result) as image:
        assert image.size == (120, 60), '转码不能改变像素尺寸'


def test_webp_source_is_discovered(brand_dir):
    """用户直接丢 `logo_print.webp` 也要能找到（v1.81.1 起列入文件名白名单）。"""
    path = brand_dir / 'logo_print.webp'
    Image.new('RGBA', (40, 20), (0, 0, 0, 255)).save(path, format='WEBP')

    assert brand_logo.print_logo_path() == path
    assert brand_logo.print_logo_image().suffix == '.png'
