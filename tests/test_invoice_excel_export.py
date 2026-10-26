"""发票 Excel 导出（后端 openpyxl）回归测试。

背景（2026-10-26 热修）：导出原来在前端用 SheetJS 生成，用户实测
**WPS 能正常打开、Microsoft Office 报「文件已损坏」**（文件非 0 字节，数据也在）。
根因是 SheetJS CE 把所有字符串写成 `t="str"` —— ECMA-376 里那是**公式字符串**
（缓存值），不是普通文本。所以整条导出搬到后端 openpyxl（Excel 自己的写入器）。

这里钉住四件事，都是"能跑但随时会退化"的：

1. **产物是标准 xlsx**：zip 完整、`[Content_Types].xml` 覆盖每个 part、
   所有 XML 严格可解析、openpyxl 能原样读回 —— 这几条就是 Office 的开门条件。
2. **不再出现 `t="str"`**：那是这次修的根因，谁再换回前端库，这条会先炸。
3. **金额/数量是数字**：财务要整列 SUM，写成文本会算成 0（用户会当成"数不对"）。
4. **脏文本不炸导出**：openpyxl 遇到 XML 非法控制字符会抛 `IllegalCharacterError`，
   所以出口先洗字符（SheetJS 当年是静默写成 `_x000b_`，脏得看不出来）。
"""

import base64
import io
import re
import zipfile
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.invoice_export import XLSX_MEDIA

client = TestClient(app)

XLSX_SUFFIX = ".xlsx"
CREATED: list[int] = []


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _cleanup_created_invoices():
    """用例造的发票收尾删掉 —— 测试库也不留垃圾。"""
    yield
    if not CREATED:
        return
    headers = _headers()
    while CREATED:
        client.delete(f"/api/v1/invoices/{CREATED.pop()}", headers=headers)


def _make_invoice(suffix: str, **body) -> dict:
    payload = {
        "invoice_no": f"XLSX-TEST-{suffix}",
        "invoice_type": "专票",
        "issue_date": "2026-10-0" + suffix[-1:],
        "direction": "input",
        "total_amount": 1130.57,
        "excl_tax_amount": 1000.5,
        "tax_amount": 130.07,
        "tax_rate": 13,
        "category": "材料采购",
        "buyer_name": "测试购方乙有限公司",
        "buyer_tax_no": "91330100OWNTAX0001",
        "seller_name": "测试销方甲有限公司",
        "seller_tax_no": "91330100SELLTAX01",
        "items": [
            {
                "item_name": "A4 复印纸",
                "spec": "70g",
                "unit": "箱",
                "quantity": 10,
                "unit_price": 100.05,
                "amount": 1000.5,
                "tax_rate": 13,
                "tax_amount": 130.07,
            }
        ],
    }
    payload.update(body)
    resp = client.post("/api/v1/invoices", json=payload)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    CREATED.append(int(created["id"]))
    return created


def _parts(data: bytes) -> dict[str, bytes]:
    """解出 zip 里的每个 part（顺便证明它就是个合法 zip）。"""
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        assert bundle.testzip() is None, "zip 内部有坏条目"
        return {name: bundle.read(name) for name in bundle.namelist()}


def _assert_opc_complete(parts: dict[str, bytes]) -> None:
    """Office 的开门条件：必备 part 齐全，且每个 part 都声明了 content type。"""
    for required in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"):
        assert required in parts, f"缺必备 part {required}，Office 会判损坏：{sorted(parts)}"

    content_types = parts["[Content_Types].xml"].decode("utf-8")
    defaults = {ext.lower() for ext in re.findall(r'<Default Extension="([^"]+)"', content_types)}
    overrides = set(re.findall(r'<Override PartName="([^"]+)"', content_types))
    for name in parts:
        if name.endswith(".xml") and ("/" + name) in overrides:
            continue
        extension = name.rsplit(".", 1)[-1].lower()
        assert extension in defaults, f"part {name} 没有 content type 声明，Office 会判损坏"

    # 所有 XML 必须能被严格解析（有非法字符/标签闭合错误时这里先炸）
    for name, raw in parts.items():
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(raw)


def _load_workbook(data: bytes):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data))



def _export(layout: str, ids: list[int] | None = None, *, json_channel: bool = True):
    headers = _headers()
    if json_channel:
        headers = {**headers, "Accept": "application/json"}
    path = f"/api/v1/invoices/export/xlsx?layout={layout}"
    if ids:
        path += "&ids=" + ",".join(str(value) for value in ids)
    return client.get(path, headers=headers)


def _download(resp) -> bytes:
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["content_type"] == XLSX_MEDIA, payload
    assert payload["filename"].endswith(XLSX_SUFFIX), payload
    data = base64.b64decode(payload["content_base64"])
    assert payload["size"] == len(data)
    return data


# ---------------------------------------------------------------------------
# 1. 主路径：清单 + 明细，产物必须是 Office 能直接打开的包
# ---------------------------------------------------------------------------

def test_ledger_export_is_office_ready_workbook():
    first = _make_invoice("A1")
    second = _make_invoice("A2", invoice_type="普票", direction="output", issue_date=None, items=[])

    resp = _export("ledger", [first["id"], second["id"]])
    data = _download(resp)
    assert data[:2] == b"PK", "不是 zip 容器，xlsx 必然打不开（会被当成损坏文件）"
    assert resp.json()["invoices"] == 2
    assert resp.json()["lines"] == 1

    parts = _parts(data)
    _assert_opc_complete(parts)
    # 根因回归：普通文本不能再写成 `t="str"`（那是公式字符串，Office 严格校验会拒绝）
    for name, raw in parts.items():
        if name.startswith("xl/worksheets/"):
            assert 't="str"' not in raw.decode("utf-8"), f"{name} 又用公式字符串承载普通文本了"

    workbook = _load_workbook(data)
    assert workbook.sheetnames == ["发票清单", "发票明细"]
    head = workbook["发票清单"]
    assert [cell.value for cell in head[1]][:4] == ["序号", "发票日期", "发票号码", "发票类型"]
    assert head.freeze_panes == "A2", "首行没冻结，长表翻两屏就看不到表头"
    assert str(head.auto_filter.ref).startswith("A1:")
    assert head.max_row == 3  # 表头 + 两张票

    # 金额列必须是**数字**：财务要整列 SUM，文本会算成 0
    money = head.cell(row=2, column=13).value
    assert isinstance(money, (int, float)) and abs(float(money) - 1000.5) < 1e-6, money
    assert head.cell(row=2, column=13).number_format == "#,##0.00"

    detail = workbook["发票明细"]
    assert detail.max_row == 2
    assert detail.cell(row=2, column=4).value == "A4 复印纸"


# ---------------------------------------------------------------------------
# 2. 脏文本：XML 非法控制字符不能把导出搞崩
# ---------------------------------------------------------------------------

def test_dirty_text_is_cleaned_instead_of_breaking_the_file():
    dirty = _make_invoice(
        "B1",
        seller_name="测试销方\x0b甲\x1f有限公司",
        items=[
            {
                "item_name": "A4\x07复印纸",
                "spec": "70g",
                "unit": "箱",
                "quantity": 2,
                "unit_price": 10.0,
                "amount": 20.0,
                "tax_rate": 13,
                "tax_amount": 2.6,
            }
        ],
    )

    resp = _export("ledger", [dirty["id"]])
    data = _download(resp)
    _assert_opc_complete(_parts(data))

    workbook = _load_workbook(data)
    seller = workbook["发票清单"].cell(row=2, column=9).value
    assert "\x0b" not in seller and "\x1f" not in seller, repr(seller)
    assert seller.startswith("测试销方") and seller.endswith("有限公司"), repr(seller)
    item_name = workbook["发票明细"].cell(row=2, column=4).value
    assert item_name == "A4复印纸", repr(item_name)


# ---------------------------------------------------------------------------
# 3. 报表布局 + 二进制通道
# ---------------------------------------------------------------------------

def test_report_export_serves_binary_and_marks_deduction():
    # ⚠️ 普票**不允许**标已抵扣（后端会 400），所以这里只用专票演示"是/否"，
    #    普票固定出 "—" —— 否则财务会以为普票漏勾了抵扣。
    deducted = _make_invoice("C1", invoice_type="专票", deducted=True)
    pending = _make_invoice("C3", invoice_type="专票", deducted=False)
    general = _make_invoice("C2", invoice_type="普票")

    ids = [deducted["id"], pending["id"], general["id"]]
    resp = _export("report", ids, json_channel=False)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(XLSX_MEDIA), resp.headers
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["X-Invoice-Invoices"] == "3"
    data = resp.content
    assert data[:2] == b"PK"

    _assert_opc_complete(_parts(data))
    workbook = _load_workbook(data)
    assert workbook.sheetnames == ["发票报表"]
    sheet = workbook["发票报表"]
    # 按发票号码找行：第 2 列号码、第 12 列已抵扣
    marks = {
        sheet.cell(row=row, column=2).value: sheet.cell(row=row, column=12).value
        for row in range(2, sheet.max_row + 1)
    }
    assert marks[deducted["invoice_no"]] == "是", marks
    assert marks[pending["invoice_no"]] == "否", marks
    assert marks[general["invoice_no"]] == "—", marks



# ---------------------------------------------------------------------------
# 4. 只导勾选的那些 + 报错要说人话
# ---------------------------------------------------------------------------

def test_export_only_contains_picked_invoices():
    keep = _make_invoice("D1")
    _make_invoice("D2")

    resp = _export("ledger", [keep["id"]])
    data = _download(resp)
    assert resp.json()["invoices"] == 1
    sheet = _load_workbook(data)["发票清单"]
    numbers = [sheet.cell(row=row, column=3).value for row in range(2, sheet.max_row + 1)]
    assert numbers == [keep["invoice_no"]], numbers


def test_bad_layout_and_empty_selection_say_why():
    headers = {**_headers(), "Accept": "application/json"}

    bad = client.get("/api/v1/invoices/export/xlsx?layout=csv", headers=headers)
    assert bad.status_code == 400
    assert "layout" in bad.json()["detail"]

    missing = client.get("/api/v1/invoices/export/xlsx?layout=ledger&ids=999999999", headers=headers)
    assert missing.status_code == 404
    assert "没有" in missing.json()["detail"]


# ---------------------------------------------------------------------------
# 5. 服务层兜底：库里存了奇形怪状的 records 也不能炸
# ---------------------------------------------------------------------------

def test_build_tolerates_odd_records():
    from app.services import invoice_export

    data = invoice_export.build(
        "ledger",
        [
            {"invoice_no": None, "items": "not-a-list"},
            {"items": [None, {"quantity": "abc", "item_name": None}]},
        ],
    )
    _assert_opc_complete(_parts(data))
    workbook = _load_workbook(data)
    assert workbook.sheetnames == ["发票清单", "发票明细"]
    assert workbook["发票清单"].max_row == 3

