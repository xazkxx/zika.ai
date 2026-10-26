# -*- coding: utf-8 -*-
"""导出对齐冒烟：取库里真实对账单，走 PDF / Word / Excel 三条链路验证样式。"""
import io
import sys

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
token = {"Authorization": f"Bearer {r.json()['access_token']}"}

# 找一张有明细的对账单
rows = client.get("/api/v1/statements?limit=50", headers=token).json()
rows = rows if isinstance(rows, list) else rows.get("items") or []
if not rows:
    print("NO_STATEMENT")
    sys.exit(0)
sid = rows[0]["id"]
print(f"statement id={sid} no={rows[0].get('statement_no')}")

ok = True

# ---- PDF：必须是 A4 横版 + 深蓝表头填充 ----
resp = client.get(f"/api/v1/print/statement-record/{sid}", headers={**token, "Accept": "application/json"})
assert resp.status_code == 200, resp.text
import base64
pdf = base64.b64decode(resp.json()["content_base64"])
import pymupdf as fitz
doc = fitz.open(stream=pdf, filetype="pdf")
page = doc[0]
w, h = page.rect.width, page.rect.height
landscape = w > h
print(f"PDF: {len(doc)} pages, page={w:.1f}x{h:.1f} landscape={landscape}")
if not landscape:
    ok = False
# 找深蓝填充色（#1F4E78 → 0.122 0.306 0.471）
found_fill = False
for p in doc:
    for dr in p.get_drawings():
        f = dr.get("fill")
        if f and abs(f[0] - 31/255) < 0.02 and abs(f[1] - 78/255) < 0.02 and abs(f[2] - 120/255) < 0.02:
            found_fill = True
            break
    if found_fill:
        break
print(f"PDF dark header fill found: {found_fill}")
if not found_fill:
    ok = False
doc.close()

# ---- Word：横版 section ----
resp = client.get(f"/api/v1/exports/word/statement/{sid}", headers=token)
assert resp.status_code == 200, resp.text
from docx import Document as WDoc
wd = WDoc(io.BytesIO(resp.content))
sec = wd.sections[0]
print(f"WORD: orientation={sec.orientation}, page={sec.page_width.cm:.1f}x{sec.page_height.cm:.1f}cm, tables={len(wd.tables)}")
if sec.page_width.cm <= sec.page_height.cm:
    ok = False
# 汇总卡片（期初余额…）应在前 3 张表里
all_head = "".join(c.text for t in wd.tables[:3] for c in t.rows[0].cells)
print(f"WORD first tables head: {all_head[:60]}")
if "期初余额" not in all_head:
    ok = False

# ---- Excel：深蓝表头 + 汇总卡片条 ----
resp = client.get("/api/v1/exports/statements", headers=token)
assert resp.status_code == 200, resp.text
from openpyxl import load_workbook
wb = load_workbook(io.BytesIO(resp.content))
ws = wb["对账单"]
# 表头在第 5 行（汇总卡占 3-4 行）
head_fill = None
for row in range(3, 8):
    v = ws.cell(row=row, column=1).value
    if v == "对账单号":
        head_fill = ws.cell(row=row, column=1).fill.fgColor.rgb
        print(f"EXCEL header at row {row}, fill={head_fill}")
        break
if head_fill != "001F4E78" and head_fill != "FF1F4E78":
    ok = False
    print(f"EXCEL head fill unexpected: {head_fill}")
card_labels = [ws.cell(row=3, column=c).value for c in range(1, 8)]
print(f"EXCEL cards row3: {card_labels}")
if "期初余额" not in [v for v in card_labels if v]:
    ok = False

print("SMOKE_OK" if ok else "SMOKE_FAIL")
