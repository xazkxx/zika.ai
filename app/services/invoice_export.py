"""发票 Excel 导出：openpyxl 直出标准 xlsx（2026-10-26 从前端搬到后端）。

为什么搬（含 2026-10-26 当天的一次诊断修正）
-------------------------------------------
这批导出原来在前端用 SheetJS(CE) 现算现写。用户实测：文件有字节（非 0）、
**WPS 能正常打开，Microsoft Office 直接报「文件已损坏」**。

⚠️ 更正：最初的结论是"SheetJS CE 把字符串写成 `t="str"`（ECMA-376 里的公式字符串）
导致 Office 拒绝打开"，**这个结论后来被推翻了**。真凶是浏览器下载给文件打上的来源标记
（NTFS 备用数据流 `Zone.Identifier`：`ZoneId=3`，即 Mark-of-the-Web）：Office 2019 会把
带标记的文件先送进「受保护视图」沙箱，那台机器（装着火绒安全软件）沙箱起不来，Excel
报出来的却是"文件已损坏 / 格式或扩展名无效"；WPS 不做受保护视图，所以永远能开——这个
不对称就是全部症状。

证据链：同一批 openpyxl 产物，脚本直写盘（无标记）双击秒开，从浏览器下载（有标记）就报
损坏；10-18 的合同台账导出（一直是后端 openpyxl 出的）也是同一个症状，且用户 3 分钟内
连下 3 份。落盘侧的根治在 `frontend/src/lib/download.js` 的 `saveBlobSmart`（另存为直写
磁盘，不带标记），系统侧则把下载目录加进 Excel「受信任位置」兜底。

那为什么生成器还留在后端？因为这一刀顺带解决了几件真问题（与"损坏"无关，但都值得）：
· 金额写成**真数字**（显示靠 `#,##0.00` 格式），前端 SheetJS 那条路要自己维护列宽/格式；
· 冻结首行 + 自动筛选：几千行发票翻起来不折磨人；
· `_text()` 清洗 XML 非法字符（openpyxl 遇到脏字符直接抛，比静默写脏要好得多）；
· 生成逻辑只剩一处实现，测试能直接断言 OPC 包结构（见 tests/test_invoice_excel_export.py）。

表结构（沿用前端原样，不要自作聪明拍平）
----------------------------------------
· `ledger` 发票清单：**一张票一行** —— 归档、核对、勾对用。
· `ledger` 发票明细：**一条商品行一行** —— 单价/数量/金额/税率/税额只有拆到
  明细行才放得下；塞进清单会让一行变成一坨，谁也看不懂。
· `report` 发票报表：勾选导出用的单表视图（含分类、抵扣状态），一票一行。

⚠️ 金额一律 `float`：`Decimal` 塞给 openpyxl 会写成文本，Excel 里 SUM 全 0
   （用户会当成"导出的数不对"）。与 `doc_export._money()` 同一口径。

⚠️ 文本先过 `_text()`：openpyxl 碰到 XML 非法控制字符会**直接抛**
   `IllegalCharacterError`（SheetJS 那时是静默写成 `_x000b_`，看不出来但内容已脏）。
   OCR 与手工录入的字段不敢保证干净，所以导出口先洗一遍：非法字符剥掉、超长截断。
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Excel 单元格文本硬上限；超了写进去也是坏文件，不如截断
_CELL_LIMIT = 32767
# XML 1.0 不允许的控制字符（openpyxl 遇到会抛 IllegalCharacterError）
_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# ---------------------------------------------------------------------------
# 样式（与 doc_export / 网页端同一套：表头深蓝白字、浅灰细边框）
# ---------------------------------------------------------------------------

_MONEY_FMT = "#,##0.00"
_NUM_FMT = "#,##0.###"
_INT_FMT = "0"

_HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
_HEAD_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
_BODY_FONT = Font(name="微软雅黑", size=10)
_THIN = Side(style="thin", color="D3D3D3")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
_ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
_ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


def _col(key: str, label: str, width: int, kind: str = "text") -> dict[str, Any]:
    return {"key": key, "label": label, "width": width, "kind": kind}



# ---------------------------------------------------------------------------
# 列定义（列宽按中文实测，太窄会被压成一串 ####）
# ---------------------------------------------------------------------------

LEDGER_COLUMNS: list[dict[str, Any]] = [
    _col("index", "序号", 6, "int"),
    _col("issue_date", "发票日期", 12),
    _col("invoice_no", "发票号码", 22),
    _col("invoice_type", "发票类型", 10),
    _col("direction", "进销项", 8),
    _col("flag", "红蓝字", 8),
    _col("buyer_name", "购买方名称", 28),
    _col("buyer_tax_no", "购买方税号", 22),
    _col("seller_name", "销售方名称", 28),
    _col("seller_tax_no", "销售方税号", 22),
    _col("line_count", "明细品种数", 11, "int"),
    _col("quantity", "数量合计", 11, "num"),
    _col("excl_tax_amount", "不含税合计", 13, "money"),
    _col("tax_amount", "税额", 12, "money"),
    _col("total_amount", "价税合计", 13, "money"),
]

DETAIL_COLUMNS: list[dict[str, Any]] = [
    _col("index", "发票序号", 10, "int"),
    _col("invoice_no", "发票号码", 22),
    _col("issue_date", "发票日期", 12),
    _col("item_name", "品名", 26),
    _col("spec", "规格型号", 14),
    _col("unit", "单位", 8),
    _col("quantity", "数量", 10, "num"),
    _col("unit_price", "单价", 12, "money"),
    _col("amount", "金额", 13, "money"),
    _col("tax_rate", "税率", 8),
    _col("tax_amount", "税额", 11, "money"),
]

REPORT_COLUMNS: list[dict[str, Any]] = [
    _col("issue_date", "开票日期", 12),
    _col("invoice_no", "发票号码", 24),
    _col("seller_name", "销售方名称", 28),
    _col("buyer_name", "购买方名称", 28),
    _col("invoice_code", "发票代码", 16),
    _col("invoice_type", "发票类型", 10),
    _col("category", "分类", 12),
    _col("total_amount", "税价合计", 13, "money"),
    _col("tax_rate", "税率", 8),
    _col("excl_tax_amount", "不含税额", 13, "money"),
    _col("tax_amount", "税额", 12, "money"),
    _col("deducted", "已抵扣", 8),
]

# 布局 → 文件名前缀 / 工作表名 / 给前端导出菜单用的说明
LAYOUTS: dict[str, dict[str, Any]] = {
    "ledger": {
        "file_prefix": "发票清单",
        "sheets": ("发票清单", "发票明细"),
        "summary": "两张表：清单（一张票一行）+ 明细（一条商品一行）",
    },
    "report": {
        "file_prefix": "发票报表",
        "sheets": ("发票报表",),
        "summary": "单表：勾选导出的发票台账（含分类与抵扣状态）",
    },
}



# ---------------------------------------------------------------------------
# 取值与格式化
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    """None 安全 + 洗掉 XML 非法字符 + 截断到 Excel 上限。"""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _ILLEGAL_CHARS.sub("", text)
    return text[:_CELL_LIMIT]


def _money(value: Any) -> float:
    """Decimal / 字符串 / None → 两位小数 float（不能把 Decimal 直接给 openpyxl）。"""
    if value is None or value == "":
        return 0.0
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _rate_text(value: Any) -> str:
    """税率出表带百分号（与界面一致）：13 → "13%"，1.5 → "1.5%"，空 → ""。"""
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _cell_value(kind: str, raw: Any) -> Any:
    if kind == "money":
        return _money(raw)
    if kind == "num":
        return _num(raw)
    if kind == "int":
        return _int(raw)
    return _text(raw)


def _number_format(kind: str) -> str | None:
    if kind == "money":
        return _MONEY_FMT
    if kind == "num":
        return _NUM_FMT
    if kind == "int":
        return _INT_FMT
    return None


def _alignment(kind: str) -> Alignment:
    if kind in ("money", "num", "int"):
        return _ALIGN_RIGHT


# ---------------------------------------------------------------------------
# 行数据
# ---------------------------------------------------------------------------

def _ledger_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        lines = record.get("items")
        if not isinstance(lines, list):
            lines = []
        rows.append(
            {
                "index": index,
                "issue_date": record.get("issue_date") or "—",
                "invoice_no": record.get("invoice_no") or "—",
                "invoice_type": record.get("invoice_type") or "未知",
                "direction": record.get("direction_label") or "待判定",
                "flag": record.get("flag_label") or "蓝字",
                "buyer_name": record.get("buyer_name") or "—",
                "buyer_tax_no": record.get("buyer_tax_no") or "—",
                "seller_name": record.get("seller_name") or "—",
                "seller_tax_no": record.get("seller_tax_no") or "—",
                "line_count": len(lines),
                "quantity": sum(
                    _num(line.get("quantity")) for line in lines if isinstance(line, dict)
                ),
                "excl_tax_amount": record.get("excl_tax_amount"),
                "tax_amount": record.get("tax_amount"),
                "total_amount": record.get("total_amount"),
            }
        )
    return rows


def _detail_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        lines = record.get("items")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            rows.append(
                {
                    "index": index,
                    "invoice_no": record.get("invoice_no") or "—",
                    "issue_date": record.get("issue_date") or "—",
                    "item_name": line.get("item_name") or "—",
                    "spec": line.get("spec") or "",
                    "unit": line.get("unit") or "",
                    "quantity": line.get("quantity"),
                    "unit_price": line.get("unit_price"),
                    "amount": line.get("amount"),
                    "tax_rate": _rate_text(line.get("tax_rate")),
                    "tax_amount": line.get("tax_amount"),
                }
            )
    return rows


def _report_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        # 只有专票谈得上抵扣；普票一律 "—"（否则财务会以为普票漏勾了）
        is_special = (record.get("invoice_type") or "") == "专票"
        rows.append(
            {
                "issue_date": record.get("issue_date") or "—",
                "invoice_no": record.get("invoice_no") or "—",
                "seller_name": record.get("seller_name") or "—",
                "buyer_name": record.get("buyer_name") or "—",
                "invoice_code": record.get("invoice_code") or "—",
                "invoice_type": record.get("invoice_type") or "未知",
                "category": record.get("category") or "",
                "total_amount": record.get("total_amount"),
                "tax_rate": _rate_text(record.get("tax_rate")),
                "excl_tax_amount": record.get("excl_tax_amount"),
                "tax_amount": record.get("tax_amount"),
                "deducted": ("是" if record.get("deducted") else "否") if is_special else "—",
            }
        )
    return rows



# ---------------------------------------------------------------------------
# 写表
# ---------------------------------------------------------------------------

def _write_sheet(ws, columns: list[dict[str, Any]], records: list[dict[str, Any]]) -> None:
    """表头放第 1 行、数据紧随其后，冻结首行并开自动筛选。

    刻意不加"大标题 + 副标题"两行：这张表是给会计**直接排序/筛选/透视**用的，
    表头一旦不在第一行，Excel 的"按列筛选"和整列 SUM 都要手工修。
    """
    ws.append([column["label"] for column in columns])
    for index, column in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=index)
        cell.font = _HEAD_FONT
        cell.fill = _HEAD_FILL
        cell.border = _BORDER
        cell.alignment = _ALIGN_CENTER
        ws.column_dimensions[get_column_letter(index)].width = column["width"]
    ws.row_dimensions[1].height = 22

    for row_index, record in enumerate(records, start=2):
        for col_index, column in enumerate(columns, start=1):
            kind = column["kind"]
            cell = ws.cell(
                row=row_index,
                column=col_index,
                value=_cell_value(kind, record.get(column["key"])),
            )
            cell.font = _BODY_FONT
            cell.border = _BORDER
            cell.alignment = _alignment(kind)
            fmt = _number_format(kind)
            if fmt:
                cell.number_format = fmt

    last_column = get_column_letter(max(1, len(columns)))
    last_row = max(1, len(records) + 1)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{last_column}{last_row}"


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def build(layout: str, records: Iterable[dict[str, Any]]) -> bytes:
    """按布局生成 xlsx 字节流。

    `records` 由调用方从 ORM 转成扁平 dict（键见上面的列定义），本模块不碰数据库。
    """
    meta = LAYOUTS.get(layout)
    if meta is None:
        raise ValueError(f"不支持的发票导出格式：{layout}")
    rows = [record for record in records if isinstance(record, dict)]

    workbook = Workbook()
    # 删掉默认那张空 Sheet：留着会多出一页空白，用户会以为导出漏了数据
    workbook.remove(workbook.active)
    if layout == "report":
        _write_sheet(workbook.create_sheet(meta["sheets"][0]), REPORT_COLUMNS, _report_rows(rows))
    else:
        _write_sheet(workbook.create_sheet(meta["sheets"][0]), LEDGER_COLUMNS, _ledger_rows(rows))
        _write_sheet(workbook.create_sheet(meta["sheets"][1]), DETAIL_COLUMNS, _detail_rows(rows))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def filename(layout: str) -> str:
    meta = LAYOUTS.get(layout) or LAYOUTS["ledger"]
    return f"{meta['file_prefix']}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


def layouts() -> list[dict[str, Any]]:
    """给前端导出菜单渲染用的清单。"""
    return [
        {
            "layout": key,
            "label": meta["file_prefix"],
            "sheets": list(meta["sheets"]),
            "summary": meta["summary"],
        }
        for key, meta in LAYOUTS.items()
    ]

    return _ALIGN_LEFT
