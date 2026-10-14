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
def test_frontend_wires_the_invoice_page():
    """前端必须：走 import 落盘、有进销项 Tab、有下载与导出原件入口。"""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"
    ).read_text(encoding="utf-8")

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
