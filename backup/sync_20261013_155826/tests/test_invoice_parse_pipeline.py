"""统一发票解析接口 /invoices/parse 测试：二维码 → PDF 文本层 → OCR 三关流水线。"""
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_qr_png(text: str) -> bytes:
    import qrcode

    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image().save(buffer, format="PNG")
    return buffer.getvalue()


def _make_text_pdf() -> bytes:
    """带文本层的原生 PDF 发票（用 PyMuPDF 内置 CJK 字体保证中文可提取）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = (
        "增值税普通发票\n"
        "发票号码: 20000001\n"
        "开票日期: 2026-09-24\n"
        "购买方\n"
        "名称: 广州测试采购有限公司\n"
        "销售方\n"
        "名称: 测试商贸有限公司\n"
        "合计金额: 888.00\n"
    )
    page.insert_textbox(fitz.Rect(50, 50, 545, 400), text, fontname="china-s", fontsize=12)
    return doc.tobytes()


def _make_scanned_pdf() -> bytes | None:
    """无文本层的扫描件 PDF：把发票文字画成图片再嵌入 PDF。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 30)
    except OSError:
        return None
    lines = [
        "增值税专用发票",
        "发票号码: INV-2026-0002",
        "开票日期: 2026-09-25",
        "合计金额: 456.78",
        "税率: 13%",
        "税额: 52.55",
    ]
    img = Image.new("RGB", (1100, 820), "white")
    draw = ImageDraw.Draw(img)
    for index, text in enumerate(lines):
        draw.text((40, 40 + index * 60), text, font=font, fill="black")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return doc.tobytes()


def test_parse_pdf_text_layer():
    """第二关：原生 PDF 直接从文本层提取。"""
    pdf = _make_text_pdf()
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("invoice.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "pdf_text"
    assert "20000001" in (payload.get("invoice_no") or "")
    assert payload.get("total_amount") == 888.0
    assert payload.get("date") == "2026-09-24"


def test_parse_qrcode_first_gate():
    """第一关：图片二维码直接拦截，提取发票号/金额/日期。"""
    png = _make_qr_png("01,10,123456789012,20000008,1234.56,20260924,abc123def456,xyz789")
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("qr.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "qrcode"
    assert payload.get("invoice_no") == "20000008"
    assert payload.get("total_amount") == 1234.56
    assert payload.get("date") == "2026-09-24"


def test_parse_qrcode_with_empty_segments():
    """真实数电票税控码带空段（01,31,,发票号,金额,日期,,校验码）：不能错位。"""
    png = _make_qr_png("01,31,,26612000000979180051,4875.00,20260525,,4C58")
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("qr.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "qrcode"
    assert payload.get("invoice_no") == "26612000000979180051"
    assert payload.get("total_amount") == 4875.0
    assert payload.get("date") == "2026-05-25"


def test_pdf_qrcode_infers_invoice_type():
    """PDF 二维码拦截后，顺带读文本层判断专票/普票类型。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(50, 50, 545, 200),
        "电子发票（增值税专用发票）\n发票号码: 20000008",
        fontname="china-s",
        fontsize=12,
    )
    qr_png = _make_qr_png("01,31,,26612000000979180051,4875.00,20260525,,4C58")
    page.insert_image(fitz.Rect(150, 450, 450, 750), stream=qr_png)
    pdf = doc.tobytes()

    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("invoice.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "qrcode"
    assert payload.get("invoice_type") == "专票"
    assert payload.get("invoice_no") == "26612000000979180051"
    assert payload.get("total_amount") == 4875.0


def test_qr_fields_fix_result_without_amount():
    """数电票直链二维码（无金额）：不拦截，但用二维码的发票号/日期修正最终结果。"""
    png = _make_qr_png("https://dppt.shaanxi.chinatax.gov.cn:8443/v/2_26612000000178941271_2026012620183200R23C56E")
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("qr.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] != "qrcode"
    assert payload.get("invoice_no") == "26612000000178941271"
    assert payload.get("date") == "2026-01-26"


def test_qrcode_fields_override_text_layer():
    """二维码数据优先级高于文字提取：文本层发票号是错值时，以二维码为准。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(50, 50, 545, 200),
        "增值税普通发票\n发票号码: 88888888\n合计金额: 100.00",
        fontname="china-s",
        fontsize=12,
    )
    # 二维码只有发票号+日期（无金额）→ 第一关不拦截，最后用二维码字段覆盖文本层结果
    qr_png = _make_qr_png("https://dppt.shaanxi.chinatax.gov.cn:8443/v/2_26612000000178941271_2026012620183200R23C56E")
    page.insert_image(fitz.Rect(150, 450, 450, 750), stream=qr_png)
    pdf = doc.tobytes()

    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("invoice.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "pdf_text"
    assert payload.get("invoice_no") == "26612000000178941271"  # 二维码覆盖了文本层的 88888888
    assert payload.get("date") == "2026-01-26"  # 日期也来自二维码
    assert payload.get("total_amount") == 100.0  # 二维码无金额，保留文本层提取值


def test_parse_scanned_pdf_ocr_fallback():
    """第三关：扫描件 PDF 无文本层无二维码，走 OCR 兜底。"""
    pdf = _make_scanned_pdf()
    if pdf is None:
        pytest.skip("本机无中文字体，跳过扫描件 OCR 测试")
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("scan.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "rapidocr"
    assert "INV-2026-0002" in (payload.get("invoice_no") or "")
    assert payload.get("total_amount") == 456.78


def test_parse_rejects_empty_file():
    response = client.post(
        "/api/v1/invoices/parse",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
