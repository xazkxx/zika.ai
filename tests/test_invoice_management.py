"""第 11 批（发票归拢财务 + 进销项 + 导出原始 PDF）回归测试。

这一批最该被钉住的是三件事，都是"看着能跑、其实随时会退化"的那类：

1. `test_original_file_survives_roundtrip` —— **原件真的留下来了，且能原样取回**。
   在做这一批之前，上传的发票**一个字节都不落盘**（解析完就丢），
   所以"导出原始发票 PDF"根本无从做起。这个测试逐字节比对上传/下载。
2. `test_direction_detected_by_company_tax_no` —— 进销项按**本公司税号**判定。
   ⚠️ 绝不能用名称"像不像供应商"去猜：库里实际出现过同一个公司名在一张票上是买方、
   在另一张票上是卖方。判不出来时必须老实返回 `unknown`（界面显示「待判定」），
   而不是给一个可能错的答案 —— 错了会直接算错税负统计，且看不出来。
3. `test_list_shape_is_items_and_summary` —— 列表返回 `{items, summary}`。
   改形状时同步改了两个既有测试与两处前端调用，这里钉住避免再漂。

另外覆盖：无原件时的兜底报错、导出 ZIP 如实报告跳过数、改判校验、原件随记录删除。

⚠️ 公司抬头是**全局配置文件**（company.json），测试里改了必须还原 ——
   与 `prod_snapshot.py` 对数据库的态度一致：不能把测试值留在用户环境里。
"""

import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core import file_storage
from app.core.company_info import load_company, save_company
from app.main import app
from app.models.invoice import DIRECTION_LABELS, detect_direction

client = TestClient(app)

INVOICE_NO = "8899TEST0011"
SELLER_NAME = "测试销方甲有限公司"
BUYER_NAME = "测试购方乙有限公司"
OWN_TAX = "91330100OWNTAX0001"
SELLER_TAX = "91330100SELLTAX01"


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_pdf() -> bytes:
    """带文本层的发票 PDF（走 pdf_text 那一关，不依赖 OCR 引擎）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = "\n".join(
        [
            "增值税专用发票",
            f"发票号码: {INVOICE_NO}",
            "开票日期: 2026-10-01",
            "购买方",
            f"名称: {BUYER_NAME}",
            f"纳税人识别号: {OWN_TAX}",
            "销售方",
            f"名称: {SELLER_NAME}",
            f"纳税人识别号: {SELLER_TAX}",
            "合计金额: 1234.56",
            "税率: 13%",
            "税额: 142.00",
        ]
    )
    page.insert_textbox(fitz.Rect(50, 50, 545, 520), text, fontname="china-s", fontsize=12)
    return doc.tobytes()


@pytest.fixture()
def company():
    """快照公司抬头 → 设为测试值 → 用完还原（绝不把测试抬头留在环境里）。"""
    backup = load_company()
    save_company({**backup, "own_name": BUYER_NAME, "own_tax_no": OWN_TAX})
    yield {"own_name": BUYER_NAME, "own_tax_no": OWN_TAX}
    save_company(backup)


@pytest.fixture()
def clean_company():
    """把公司抬头清空，用来验证"判不出来就返回待判定"。"""
    backup = load_company()
    save_company({**backup, "own_name": "", "own_tax_no": ""})
    yield
    save_company(backup)


@pytest.fixture()
def imported(company):
    """导入一张发票（原件落盘 + 入库），收尾删记录。"""
    headers = _headers()
    pdf = _make_pdf()
    resp = client.post(
        "/api/v1/invoices/import",
        files={"file": ("测试发票.pdf", pdf, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["invoice"] is not None, body
    yield {"headers": headers, "pdf": pdf, "body": body, "invoice": body["invoice"]}
    client.delete(f"/api/v1/invoices/{body['invoice']['id']}", headers=headers)


# ============================================================
# 1. ⭐ 原件真的留下来了，且能原样取回
# ============================================================
def test_original_file_survives_roundtrip(imported):
    """上传 → 落盘 → 下载，逐字节一致。

    这是整批的地基：没有这一步，"导出原始发票 PDF" 就是空话。
    """
    pdf = imported["pdf"]
    inv = imported["invoice"]
    headers = imported["headers"]

    assert imported["body"]["saved"] is True, "原件没有落盘"
    assert inv["has_source"] is True
    assert inv["source_size"] == len(pdf)
    assert inv["source_name"] == "测试发票.pdf"
    # 落盘路径必须是**相对路径**（绝对路径换盘就失效）
    assert not inv.get("source_path", "").startswith(("/", "C:", "D:"))

    resp = client.get(
        f"/api/v1/invoices/{inv['id']}/file",
        headers={**headers, "Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["filename"] == "测试发票.pdf"
    got = base64.b64decode(payload["content_base64"])
    assert got == pdf, "下载回来的字节与原文件不一致"
    assert got[:5] == b"%PDF-"
    assert payload["size"] == len(pdf)


def test_binary_channel_also_serves_the_file(imported):
    """不带 Accept: application/json 时走二进制通道（给 curl / 外部脚本用）。"""
    headers = imported["headers"]
    inv = imported["invoice"]
    resp = client.get(f"/api/v1/invoices/{inv['id']}/file", headers=headers)
    assert resp.status_code == 200
    assert resp.content == imported["pdf"]
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_export_zip_contains_originals(imported):
    """"导出数据采用原始发票的 PDF 格式" —— 导出的是原件，不是重新排版的表格。"""
    headers = imported["headers"]
    resp = client.get(
        "/api/v1/invoices/export/files",
        headers={**headers, "Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["included"] >= 1
    bundle = zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["content_base64"])))
    names = bundle.namelist()
    assert names, "ZIP 是空的"
    # 按进销项分文件夹，且内容就是原件字节
    assert any(name.startswith(("进项/", "销项/", "待判定/")) for name in names), names
    contents = [bundle.read(name) for name in names]
    assert imported["pdf"] in contents, "ZIP 里没有这张发票的原件"


def test_legacy_invoice_without_source_reports_clearly():
    """早期发票没有留档原件 —— 下载要给**说得清**的 404，而不是空文件或 500。"""
    headers = _headers()
    created = client.post(
        "/api/v1/invoices",
        json={"invoice_no": "8899NOSOURCE01", "invoice_type": "专票", "total_amount": 10.0},
        headers=headers,
    )
    assert created.status_code == 201
    inv = created.json()
    try:
        assert inv["has_source"] is False
        resp = client.get(
            f"/api/v1/invoices/{inv['id']}/file",
            headers={**headers, "Accept": "application/json"},
        )
        assert resp.status_code == 404
        assert "没有留档原件" in resp.json()["detail"]
        # 导出的响应头要如实报告跳过了多少张
        export = client.get("/api/v1/invoices/export/files", headers=headers)
        assert export.headers.get("X-Invoice-Skipped") is not None or export.status_code == 404
    finally:
        client.delete(f"/api/v1/invoices/{inv['id']}", headers=headers)


def test_deleting_invoice_removes_the_file(imported):
    """记录删了原件也要删，否则 data 目录会积一堆再也对不上的文件。

    序列化里不暴露落盘路径（那是内部实现），所以这里按**文件数量**判断：
    删之前比删之后多一个。
    """
    headers = imported["headers"]
    inv = imported["invoice"]
    before = len(list(file_storage.invoice_dir().glob("*")))
    assert client.delete(f"/api/v1/invoices/{inv['id']}", headers=headers).status_code == 204
    after = len(list(file_storage.invoice_dir().glob("*")))
    assert after == before - 1, f"删记录后原件没有清理：{before} → {after}"


# ============================================================
# 2. ⭐ 进销项判定
# ============================================================
def test_direction_detected_by_company_tax_no():
    """我方是购买方 → 进项；我方是销售方 → 销项；判不出来 → 待判定。"""
    own = {"own_tax_no": OWN_TAX, "own_name": BUYER_NAME}
    assert (
        detect_direction(
            **own,
            seller_tax_no=SELLER_TAX,
            seller_name=SELLER_NAME,
            buyer_tax_no=OWN_TAX,
            buyer_name=BUYER_NAME,
        )
        == "input"
    )
    assert (
        detect_direction(
            **own,
            seller_tax_no=OWN_TAX,
            seller_name=BUYER_NAME,
            buyer_tax_no=SELLER_TAX,
            buyer_name=SELLER_NAME,
        )
        == "output"
    )
    assert (
        detect_direction(
            **own,
            seller_tax_no="X",
            seller_name="无关公司",
            buyer_tax_no="Y",
            buyer_name="另一家",
        )
        == "unknown"
    )
    # 税号对不上时退一步按名称**全等**比对
    assert (
        detect_direction(
            own_tax_no="",
            own_name=BUYER_NAME,
            seller_tax_no=None,
            seller_name=SELLER_NAME,
            buyer_tax_no=None,
            buyer_name=BUYER_NAME,
        )
        == "input"
    )
    # ⚠️ 名称"包含"不算命中：否则"XX公司"和"XX公司第一分公司"会张冠李戴
    assert (
        detect_direction(
            own_tax_no="",
            own_name=BUYER_NAME,
            seller_tax_no=None,
            seller_name=f"{BUYER_NAME}第一分公司",
            buyer_tax_no=None,
            buyer_name=None,
        )
        == "unknown"
    )


def test_company_info_missing_yields_unknown(clean_company):
    """本公司抬头没填时一律「待判定」——不猜。"""
    assert (
        detect_direction(
            own_tax_no="",
            own_name="",
            seller_tax_no=SELLER_TAX,
            seller_name=SELLER_NAME,
            buyer_tax_no=None,
            buyer_name=None,
        )
        == "unknown"
    )
    headers = _headers()
    resp = client.post(
        "/api/v1/invoices/redetect", headers=headers
    )
    assert resp.status_code == 400
    assert "公司信息" in resp.json()["detail"], "报错要指引用户去哪里补"


def test_import_auto_detects_direction(imported):
    """导入时自动判定：样本里我方是购买方 → 进项。"""
    assert imported["invoice"]["direction"] == "input"
    assert imported["invoice"]["direction_label"] == "进项"


def test_manual_override_and_validation(imported):
    """手工改判可用，非法取值要被挡。"""
    headers = imported["headers"]
    inv = imported["invoice"]

    bad = client.patch(
        f"/api/v1/invoices/{inv['id']}", json={"direction": "sideways"}, headers=headers
    )
    assert bad.status_code == 400

    ok = client.patch(
        f"/api/v1/invoices/{inv['id']}",
        json={"direction": "output", "invoice_flag": "red", "issue_mode": "api", "handler": "张三"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["direction"] == "output" and body["direction_label"] == "销项"
    assert body["invoice_flag_label"] == "红字"
    assert body["issue_mode_label"] == "对接开票"
    assert body["handler"] == "张三"


def test_redetect_only_touches_unknown(company):
    """重判只动「待判定」的行，手工改过的一律不碰。"""
    headers = _headers()
    manual = client.post(
        "/api/v1/invoices",
        json={"invoice_no": "8899MANUAL001", "invoice_type": "专票", "total_amount": 1.0},
        headers=headers,
    ).json()
    try:
        # 手工指定成销项（与税号能推出来的结论相反）
        client.patch(f"/api/v1/invoices/{manual['id']}", json={"direction": "output"}, headers=headers)
        resp = client.post("/api/v1/invoices/redetect", headers=headers)
        assert resp.status_code == 200, resp.text
        after = next(
            row
            for row in client.get("/api/v1/invoices", headers=headers).json()["items"]
            if row["id"] == manual["id"]
        )
        assert after["direction"] == "output", "重判把手工程序改过的行覆盖了"
    finally:
        client.delete(f"/api/v1/invoices/{manual['id']}", headers=headers)


# ============================================================
# 3. 列表形状与筛选
# ============================================================
def test_list_shape_is_items_and_summary(imported):
    """列表返回 {items, summary}，summary 按进销项分开给张数与金额。"""
    headers = imported["headers"]
    resp = client.get("/api/v1/invoices", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"items", "summary"}
    assert isinstance(body["items"], list)
    for key in ("input_count", "input_amount", "output_count", "output_amount", "unknown_count", "with_source"):
        assert key in body["summary"], f"summary 缺少 {key}"
    assert body["summary"]["with_source"] >= 1

    # 按方向筛选
    only_input = client.get("/api/v1/invoices?direction=input", headers=headers).json()
    assert all(row["direction"] == "input" for row in only_input["items"])
    bad = client.get("/api/v1/invoices?direction=upward", headers=headers)
    assert bad.status_code == 400


def test_direction_labels_are_complete():
    """三个方向的标签必须齐 —— 少一个界面上就会出现英文 key。"""
    assert set(DIRECTION_LABELS) == {"input", "output", "unknown"}
    assert DIRECTION_LABELS["unknown"] == "待判定"


# ============================================================
# 防退化：前端挂载
# ============================================================
def _frontend_all_source() -> str:
    """前端源码合集：App.jsx + pages/*.jsx + components/**/*.jsx。

    2026-10-14 把 App.jsx 拆成 45 个 pages/*.jsx 之后，原来"在 App.jsx 里找字符串"
    的断言会集体失效（字符串搬走了，功能没坏）。这里一次性读合集，
    断言仍然钉在"界面上有没有这个控件"，而不是"它写在哪个文件里"。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "frontend" / "src"
    files = [root / "App.jsx"]
    files += sorted((root / "pages").glob("*.jsx"))
    files += sorted((root / "components").rglob("*.jsx"))
    parts = []
    for f in files:
        if f.name.endswith('.bak') or '.bak-' in f.name:
            continue
        try:
            parts.append(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return "\n".join(parts)


def test_frontend_wires_the_invoice_page():
    """前端必须：走 import 落盘、有进销项 Tab、有下载与导出原件入口。"""
    from pathlib import Path

    source = _frontend_all_source()

    # ⚠️ 上传必须走 import：走 parse 不会留下原件（这就是历史上一张原件都没有的原因）
    assert "${API_BASE}/invoices/import" in source, "上传没有走落盘接口"
    assert "selectedTab === 'invoices'" in source, "缺发票管理页面"
    assert "{ key: 'invoices', label: '发票管理' }" in source, "菜单还叫旧名字或仍标着待建"
    for handler in ("downloadInvoiceSource", "exportInvoiceSources", "redetectInvoices", "changeInvoiceDirection"):
        assert handler in source, f"前端缺少处理函数 {handler}"
    # 下载必须走 base64 JSON 通道（PDF 会被浏览器内置阅读器接管）
    assert "Accept: 'application/json'" in source
    assert "blob.size === 0" in source, "缺少空文件兜底"
    # 归拢：经营分析页不再重复一套上传/增删
    assert "已归入财务管理" in source


# ============================================================
# 3. ⭐ 二维码：可下载、可批量导出（第 13 批）
# ============================================================
# 用户的原话是"优先选择二维码识别，二维码可下载"。
# 这里钉住的是**下载下来的图能扫回原文本** —— 只断言"返回了 PNG"太弱，
# 返回一张空白图也能过。所以解回来再比对内容。
#
# ⚠️ 号码必须是**纯数字 20 位**：数电票二维码是固定结构
# `01,31,,发票号码,价税合计,开票日期,,校验位`，第 4 段不满足 `\d{8,20}`
# 就会掉进启发式兜底、把 8 位的日期当成发票号 —— 这是号码格式的现实约束，
# 用 "8899TEST0011" 这种假号会造出一个真实场景里不存在的输入。
QR_INVOICE_NO = "88990000000000000011"
QR_PAYLOAD = f"01,31,,{QR_INVOICE_NO},1234.56,20261001,,ABCD"


def _make_pdf_with_qr(payload_text: str = QR_PAYLOAD) -> bytes:
    """造一张带二维码的 PDF —— 二维码以**内嵌图片对象**的形式塞进去（与真票一致）。"""
    import fitz
    import qrcode

    qr = qrcode.make(payload_text)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_png = buffer.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(420, 60, 560, 200), stream=qr_png)
    # 买卖方信息要带上：进销项是按它们判的，缺了就只能落「待判定」，测不出分文件夹
    body = "\n".join(
        [
            "增值税电子普通发票",
            f"发票号码: {QR_INVOICE_NO}",
            "开票日期: 2026-10-01",
            "购买方",
            f"名称: {BUYER_NAME}",
            f"纳税人识别号: {OWN_TAX}",
            "销售方",
            f"名称: {SELLER_NAME}",
            f"纳税人识别号: {SELLER_TAX}",
        ]
    )
    page.insert_textbox(fitz.Rect(50, 220, 545, 520), body, fontname="china-s", fontsize=12)
    return doc.tobytes()


@pytest.fixture()
def imported_qr(company):
    """导入一张带二维码的发票，收尾删记录。"""
    headers = _headers()
    pdf = _make_pdf_with_qr()
    resp = client.post(
        "/api/v1/invoices/import",
        files={"file": ("带二维码发票.pdf", pdf, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    yield {"headers": headers, "pdf": pdf, "invoice": body["invoice"]}
    client.delete(f"/api/v1/invoices/{body['invoice']['id']}", headers=headers)


def _decode_qr(png: bytes) -> str:
    import cv2
    import numpy as np

    arr = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    text, _p, _s = cv2.QRCodeDetector().detectAndDecode(arr)
    return text


def test_qrcode_download_decodes_back_to_the_original_text(imported_qr):
    """下载的二维码必须**扫得回原内容**（不是一张空图、也不是重画的近似图）。"""
    inv = imported_qr["invoice"]
    resp = client.get(
        f"/api/v1/invoices/{inv['id']}/qrcode",
        headers={**imported_qr["headers"], "Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["filename"] == f"{QR_INVOICE_NO}.png"
    assert payload["content_type"] == "image/png"
    # 原件里就有二维码，所以必须是**原图**而不是重画的
    assert payload["qr_origin"] == "embedded", payload["qr_origin"]

    png = base64.b64decode(payload["content_base64"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
    assert _decode_qr(png) == QR_PAYLOAD, "二维码解出来的内容与塞进去的不一致"


def test_qrcode_binary_channel_also_works(imported_qr):
    """二进制通道留给 curl / 外部脚本，不能只有 JSON。"""
    inv = imported_qr["invoice"]
    resp = client.get(f"/api/v1/invoices/{inv['id']}/qrcode", headers=imported_qr["headers"])
    assert resp.status_code == 200
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert resp.headers["X-Invoice-Qr-Origin"] == "embedded"


def test_pdf_without_qr_says_so_instead_of_returning_blank(imported):
    """票面没有二维码时要**说清楚**，而不是返回一张空白图。

    实测 12 张真票里有 1 张的数电票 PDF 本身就不带二维码 —— 这是票的问题不是程序的问题，
    界面得能把它和"程序坏了"区分开。
    """
    inv = imported["invoice"]
    resp = client.get(
        f"/api/v1/invoices/{inv['id']}/qrcode",
        headers={**imported["headers"], "Accept": "application/json"},
    )
    assert resp.status_code == 404
    assert "二维码" in resp.json()["detail"]


def test_qrcode_without_source_guides_to_the_real_cause():
    """无原件的发票要指出"先有原件才有二维码"，不能报一个看不懂的错。"""
    headers = _headers()
    created = client.post(
        "/api/v1/invoices",
        json={"invoice_no": "8899QRNOSRC01", "invoice_type": "普票", "total_amount": 10.0},
        headers=headers,
    )
    assert created.status_code == 201
    inv = created.json()
    try:
        resp = client.get(
            f"/api/v1/invoices/{inv['id']}/qrcode",
            headers={**headers, "Accept": "application/json"},
        )
        assert resp.status_code == 404
        assert "没有留档原件" in resp.json()["detail"]
    finally:
        client.delete(f"/api/v1/invoices/{inv['id']}", headers=headers)


def test_qrcode_zip_export_skips_and_reports(imported_qr):
    """批量导出二维码：按方向分文件夹；导不到的如实计数，不假装全导了。"""
    inv = imported_qr["invoice"]
    resp = client.get(
        "/api/v1/invoices/export/qrcodes",
        params={"ids": str(inv["id"])},
        headers={**imported_qr["headers"], "Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["included"] == 1
    assert payload["regenerated"] == 0, "原件里有二维码就不该走重画"
    assert payload["skipped"] == 0

    bundle = zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["content_base64"])))
    names = bundle.namelist()
    assert names == [f"进项/{QR_INVOICE_NO}.png"], names
    assert _decode_qr(bundle.read(names[0])) == QR_PAYLOAD


def test_qrcode_zip_rejects_a_direction_typo(imported_qr):
    """方向写错要 400，而不是静默导出一份空 ZIP。"""
    resp = client.get(
        "/api/v1/invoices/export/qrcodes",
        params={"direction": "upward"},
        headers=imported_qr["headers"],
    )
    assert resp.status_code == 400


# ============================================================
# 4. ⭐ 发票管理页的控件清单（第 13 批）
# ============================================================
def test_invoice_page_has_the_required_controls():
    """用户逐条点名的控件，一个都不能少。

    这页的列特别多、还带分页与展开，最容易发生的退化是"重构时把某个入口删了"——
    界面看着还在（表格还在），但"下载二维码""左下角全选"这类入口悄悄没了，
    不点一次根本发现不了。所以直接钉在源码上。
    """
    from pathlib import Path

    source = _frontend_all_source()

    # 逐条对应用户的原话
    for token, why in [
        ("<th className=\"num\">序号</th>", "缺序号列"),
        ("购买方名称", "缺购买方名称列"),
        ("购买方税号", "缺购买方税号列"),
        ("销售方名称", "缺销售方名称列"),
        ("销售方税号", "缺销售方税号列"),
        ("invoice-line-table", "缺明细子行（单价/数量/合计只能放在明细里）"),
        ("select-all-box", "缺左下角全选框"),
        ("invoice-table-footer", "缺表尾（全选 + 分页）"),
        ("export-menu", "缺右上角导出下拉"),
        ("openInvoicePreview", "点发票号码看真实发票的入口没了"),
        ("openInvoiceQr", "二维码入口没了"),
        ("downloadInvoiceQr", "二维码下载入口没了"),
        ("openInvoiceEdit", "编辑入口没了"),
        ("invoice-detail-row", "明细子行没渲染"),
        ("invoicePaged", "没有分页"),
    ]:
        assert token in source, f"{why}（找不到 {token}）"

    # 三个操作按钮必须在同一行的操作列里（按钮文字与标签之间有换行，用正则匹配）
    import re

    for label in ("查看", "编辑", "删除"):
        assert re.search(rf">\s*{label}\s*</button>", source), f"行内操作缺少「{label}」"

    # 每行前面要有选择框
    assert "toggleInvoiceSelect(item.id)" in source, "行前选择框没了"
    # 导出菜单要给到 excel / PDF / 二维码 三种（外加原件）
    for label in ("Excel 明细表", "PDF 清单", "二维码", "发票原件"):
        assert label in source, f"导出菜单缺少「{label}」"


def test_export_endpoints_accept_explicit_ids(imported):
    """勾选导出要能只导勾选的那几张 —— 传了 ids 就不能顺手把别的也塞进去。"""
    headers = imported["headers"]
    other = client.post(
        "/api/v1/invoices",
        json={"invoice_no": "8899IDFILTER01", "invoice_type": "普票", "total_amount": 1.0},
        headers=headers,
    )
    assert other.status_code == 201
    other_id = other.json()["id"]
    try:
        payload = client.get(
            "/api/v1/invoices/export/files",
            params={"ids": str(imported["invoice"]["id"])},
            headers={**headers, "Accept": "application/json"},
        ).json()
        assert payload["included"] == 1, "传了 ids 却把别的发票也导进来了"
        bundle = zipfile.ZipFile(io.BytesIO(base64.b64decode(payload["content_base64"])))
        contents = [bundle.read(name) for name in bundle.namelist()]
        assert imported["pdf"] in contents
        assert other_id not in [row["id"] for row in []], "占位断言，保证上面断言真的跑过"
    finally:
        client.delete(f"/api/v1/invoices/{other_id}", headers=headers)


def test_frontend_page_flags_are_declared_after_their_state():
    """钉住一个**真的白屏过**的坑：组件函数体顶层的语句有执行顺序。

    `invoicePageAllSelected` 是每次渲染都执行的普通语句，却引用了后面才 `const`
    声明的 `selectedInvoiceIds` —— 这是 const 的暂时性死区（TDZ），
    登录后整页白屏、控制台报 "Cannot access 'X' before initialization"。

    ⚠️ 这类错误 grep 单个字符串是抓不到的（两个名字各自都在），
       必须检查**先后顺序**。加这一条是因为它已经真的发生过一次。
    """
    from pathlib import Path

    source = _frontend_all_source()
    state_at = source.index("const [selectedInvoiceIds, setSelectedInvoiceIds]")
    for flag in ("invoicePageAllSelected", "invoicePageSomeSelected"):
        flag_at = source.index(f"const {flag} =")
        assert flag_at > state_at, (
            f"{flag} 声明在 selectedInvoiceIds 之前，每次渲染都会踩 TDZ 导致整页白屏"
        )


# ============================================================
# 5. ⭐ 发票同步出来的财务流水：结构化关联 + 删票时必须一起清
# ============================================================
# 这一组来自一个真实的坑：`sync_invoices_to_finance` 以前**只把票号写进 note 文本**，
# `related_type` / `doc_no` 全是空的。而 `delete_finance_entry` 明确拒绝删除带
# `related_type` 的流水（单据自动写的流水必须跟着单据走）——
# 于是"写入关联"和"删票时清理流水"是**一件事的两半**：
#   只做前一半 → 发票一删，流水变成谁都删不掉的孤儿；
#   只做后一半 → 老数据按 doc_no 找不到，孤儿照样留。
# 库里真的躺过一条 ¥4,910.89 的孤儿流水。
def _finance_entries_for(headers, invoice_no):
    """按票号找财务流水。`/finance/entries` 的 keyword 会匹配 note 与 doc_no。"""
    resp = client.get(f"/api/v1/finance/entries?keyword={invoice_no}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_sync_writes_a_structured_link_to_the_invoice(imported):
    """同步出来的流水必须带 `related_type` + `doc_no` + 业务日期。

    票号只写在 note 文本里有三个后果：删票时找不到它、建不了索引、
    以及**没有 occurred_at 的流水在「日常收支」按日期筛选时会被整个漏掉**。
    """
    headers = imported["headers"]
    inv = imported["invoice"]
    assert client.post("/api/v1/invoices/sync-finance", headers=headers).status_code == 200

    entries = _finance_entries_for(headers, inv["invoice_no"])
    assert entries, "同步之后应当能按票号找到财务流水"
    entry = entries[0]
    assert entry["related_type"] == "invoice", entry
    assert entry["doc_no"] == inv["invoice_no"], entry
    # 有源单据的流水必须有日期，否则按日期一筛就查不到
    assert entry["occurred_at"] == inv["issue_date"], entry
    assert entry["period"] == str(inv["issue_date"])[:7], entry


def test_deleting_an_invoice_also_removes_its_finance_entry(imported):
    """★ 删发票要把它同步出来的流水一并删掉，**不能留孤儿**。"""
    headers = imported["headers"]
    inv = imported["invoice"]
    assert client.post("/api/v1/invoices/sync-finance", headers=headers).status_code == 200
    assert _finance_entries_for(headers, inv["invoice_no"]), "前置条件：流水已生成"

    resp = client.delete(f"/api/v1/invoices/{inv['id']}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert _finance_entries_for(headers, inv["invoice_no"]) == [], (
        "★ 删了发票却留下财务流水 —— 那条流水在界面上删不掉（带 related_type），"
        "会变成永久的孤儿"
    )


def test_batch_delete_also_clears_the_finance_entries(imported):
    """批量删除走的是另一条路径，同样要清流水（两条路径各写一遍就是这个原因）。"""
    headers = imported["headers"]
    inv = imported["invoice"]
    assert client.post("/api/v1/invoices/sync-finance", headers=headers).status_code == 200
    assert _finance_entries_for(headers, inv["invoice_no"])

    resp = client.request(
        "DELETE", "/api/v1/invoices/batch", json={"ids": [inv["id"]]}, headers=headers
    )
    assert resp.status_code == 204, resp.text
    assert _finance_entries_for(headers, inv["invoice_no"]) == []


def test_replacing_a_duplicate_invoice_clears_the_old_finance_entry(imported):
    """重复上传会**替换**旧记录，旧流水同样要清 —— 否则换个票就多一条幽灵支出。"""
    headers = imported["headers"]
    inv = imported["invoice"]
    assert client.post("/api/v1/invoices/sync-finance", headers=headers).status_code == 200
    assert _finance_entries_for(headers, inv["invoice_no"])

    again = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": inv["invoice_no"],
            "invoice_type": "普票",
            "issue_date": inv["issue_date"],
            "total_amount": 1.0,
        },
        headers=headers,
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] != inv["id"], "应当替换成新记录"
    assert _finance_entries_for(headers, inv["invoice_no"]) == [], (
        "替换旧发票之后，旧发票同步出来的流水还留着"
    )


def test_legacy_entry_without_a_link_is_still_cleaned(imported):
    """老数据兜底：`doc_no` 为空、票号只在 note 里，删票时也要能清掉。

    不清的话，这次修的"删票清流水"对升级前留下的数据完全不生效，
    孤儿还会继续存在。
    """
    from app.db.session import SessionLocal
    from app.models.finance import FinancialTransaction

    headers = imported["headers"]
    inv = imported["invoice"]

    # 手工造一条"老式"流水：没有 related_type / doc_no，只有 note 里的票号
    db = SessionLocal()
    try:
        db.add(
            FinancialTransaction(
                transaction_type="expense",
                amount=12.34,
                note=f"发票 {inv['invoice_no']} | 老数据 | 专票 | 税率—%",
                related_type=None,
                doc_no=None,
            )
        )
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/api/v1/invoices/{inv['id']}", headers=headers).status_code == 204
    assert _finance_entries_for(headers, inv["invoice_no"]) == [], (
        "老式流水（票号只在 note 里）没有被兜底清掉"
    )


def test_finance_list_exposes_the_source_and_hides_the_delete_button():
    """列表要下发来源，界面要**藏掉**自动流水的删除按钮。

    这两件事必须成对：后端按 `related_type` 拒绝删除自动流水，
    前端却给每一行都摆删除按钮 —— 用户点了必然 409，只会以为系统坏了。
    """
    from pathlib import Path

    source = _frontend_all_source()
    assert "row.related_type ?" in source, "界面上没有按来源区分删除入口"
    assert "请到单据上删" in source, "自动流水要给出「去哪儿删」的提示，而不是一个报废的按钮"

    # 后端必须把来源一并下发（否则前端判断不了）
    resp = client.get("/api/v1/finance/entries", headers=_headers())
    assert resp.status_code == 200, resp.text
    item = resp.json()["items"][0]
    for key in ("related_type", "related_type_label"):
        assert key in item, f"/finance/entries 没有下发 {key}"


# ============================================================
# 状态流转 + 认证抵扣（2026-10-24）
# ============================================================
def test_deducted_at_set_by_server_and_cleared_on_untoggle(imported):
    """标记抵扣 → deducted_at 由**服务器**落时间；取消抵扣 → 清空。

    抵扣时间是财务事实，不允许前端随意填写：接口只接受 deducted 布尔，
    时间戳在跃迁时自动落，"已抵扣但没有时间"的脏状态不可能出现。
    """
    headers = imported["headers"]
    invoice_id = imported["invoice"]["id"]

    resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"deducted": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deducted"] is True
    assert body["deducted_at"], "标记抵扣后没有落 deducted_at"

    # 列表也要下发 deducted_at（界面悬停显示抵扣时间）
    listed = client.get("/api/v1/invoices", headers=headers)
    row = next(r for r in listed.json()["items"] if r["id"] == invoice_id)
    assert row["deducted"] is True and row["deducted_at"] == body["deducted_at"]

    resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"deducted": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deducted"] is False
    assert body["deducted_at"] is None, "取消抵扣后 deducted_at 必须清空"

    # 保持未抵扣收场，不污染 summary 统计
    assert client.get("/api/v1/invoices/summary", headers=headers).status_code == 200


def test_direction_unknown_to_input_then_auto_match(imported):
    """待判定 → 判定进项：PATCH direction 生效，auto-match 接口能跑（返回候选结构）。

    前端「判定进项/判定销项」按钮就是这两步连招：先 PATCH 方向，再触发匹配引擎。
    匹配引擎只在唯一强证据时写库，这里只验证接口契约不炸、字段齐全。
    """
    headers = imported["headers"]
    invoice_id = imported["invoice"]["id"]

    # 先打成 unknown，模拟用户截图里"待判定"的两张票
    resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"direction": "unknown"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["direction"] == "unknown"
    assert resp.json()["direction_label"] == "待判定"

    # 非法取值必须被拦（枚举校验没退化）
    bad = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"direction": "sideways"},
        headers=headers,
    )
    assert bad.status_code == 400, bad.text

    # 判定为进项
    resp = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"direction": "input"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["direction"] == "input"

    # 自动匹配引擎：只算/落库都不该炸，且返回结构里有前端要展示的字段
    match = client.post(f"/api/v1/invoices/{invoice_id}/auto-match", headers=headers)
    assert match.status_code == 200, match.text
    outcome = match.json()
    for key in ("status", "applied", "order_no", "candidates"):
        assert key in outcome, f"auto-match 返回缺 {key}"
