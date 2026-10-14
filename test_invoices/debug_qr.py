"""打印每个发票文件识别到的二维码原文，定位发票号解析错误。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.api.v1.routes.erp import _decode_qrcode, _pdf_page_pngs

folder = Path(__file__).resolve().parent
for path in sorted(folder.iterdir()):
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
        continue
    qr_text = None
    if path.suffix.lower() == ".pdf":
        for page_png in _pdf_page_pngs(path.read_bytes()):
            qr_text = _decode_qrcode(page_png)
            if qr_text:
                break
    else:
        qr_text = _decode_qrcode(path.read_bytes())
    print("=" * 60)
    print(f"文件: {path.name}")
    print(f"二维码原文: {qr_text!r}" if qr_text else "二维码: 未识别到")
