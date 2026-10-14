"""逐个调用 /invoices/parse 实测 test_invoices 目录里的发票文件。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
folder = Path(__file__).resolve().parent
content_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}

for path in sorted(folder.iterdir()):
    if path.suffix.lower() not in content_types:
        continue
    with path.open("rb") as fh:
        response = client.post(
            "/api/v1/invoices/parse",
            files={"file": (path.name, fh, content_types[path.suffix.lower()])},
        )
    print("=" * 60)
    print(f"文件: {path.name}")
    print(f"HTTP: {response.status_code}")
    if response.status_code == 200:
        payload = response.json()
        print(f"provider   : {payload.get('provider')}")
        print(f"invoice_no : {payload.get('invoice_no')}")
        print(f"total_amount: {payload.get('total_amount')}")
        print(f"date       : {payload.get('date')}")
        print(f"类型       : {payload.get('invoice_type')}")
    else:
        print(f"错误: {response.text[:200]}")
