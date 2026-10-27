"""全单据 Excel 导出（第 13 批 · 第三阶段）。

与 `excel_io` 的分工，别混：

· `excel_io` 是「**档案批量建账 / 数据迁移**」—— 有模板、有示例行、能导回来，
  所以 `COLUMNS` 里的每一列都必须可解析、可校验、可写回模型。
· 本模块是「**单据台账导出**」—— 只出不进。导出的表是给人看/给会计存档的，
  所以允许出现模型里没有的派生列（方向中文名、状态中文名、关联单号快照）。

两类单据的表格形状天然不同，所以每个 kind 都是「**一个工作簿、两张工作表**」：

    主表（一行一份单据） +  明细（一行一个商品/一个业务事实）

合同与报价单的明细是商品行；对账单的明细是「合同/发票/收款」业务行。
硬把它们拍平进一张宽表会让金额列互相串味（合同金额 vs 开票金额是什么关系？
拍平后 Excel 里就再也说不清了），所以坚持两张表。

⚠️ 金额出表一律 `float`：`Decimal` 直接塞给 openpyxl 会写成一串文本，
在 Excel 里求和全是 0（用户会当成"导出的数不对"）。转换统一走 `_money()`。
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties

# ---------------------------------------------------------------------------
# 类别 → 标题 / 工作表名 / 日期字段（用于 from_date–to_date 过滤）
# ---------------------------------------------------------------------------

DOC_KINDS: dict[str, dict[str, Any]] = {
    "contracts": {
        "label": "合同台账",
        "file_prefix": "合同台账",
        "sheets": ("合同", "合同明细"),
        "date_field": "sign_date",
        "summary": "合同主表 + 商品明细；含进/出方向、原件与 OCR 识别状态。",
    },
    "quotations": {
        "label": "报价单台账",
        "file_prefix": "报价单台账",
        "sheets": ("报价单", "报价明细"),
        "date_field": "quote_date",
        "summary": "报价单主表 + 商品明细；含效期与关联合同。",
    },
    "statements": {
        "label": "对账单台账",
        "file_prefix": "对账单台账",
        "sheets": ("对账单", "对账明细"),
        "date_field": "period_end",
        "summary": "对账单头部（10 个金额快照）+ 业务明细行；金额口径见对账单说明。",
    },
}


def _col(field: str, label: str, width: int = 14, kind: str = "str", warn: str | None = None) -> dict[str, Any]:
    """列定义。kind: str / money / num / int / date / bool

    warn: 数值 > 0 时的异常提示色（对齐网页端）——
      "red" = 红色加粗字体（欠款类）；"fill" = 黄底（未开票类）。
    """
    return {"field": field, "label": label, "width": width, "kind": kind, "warn": warn}


# ---------------------------------------------------------------------------
# 列定义
# ---------------------------------------------------------------------------

HEADER_COLUMNS: dict[str, list[dict[str, Any]]] = {
    "contracts": [
        _col("contract_no", "合同编号", 18),
        _col("direction_label", "方向", 10),
        _col("type_label", "合同类型", 12),
        _col("title", "合同标题", 22),
        _col("party_type_label", "往来类型", 10),
        _col("party_name", "往来单位", 26),
        _col("party_contact", "对方联系人", 12),
        _col("party_phone", "联系电话", 16),
        _col("sign_date", "签订日期", 12, "date"),
        _col("valid_from", "有效期起", 12, "date"),
        _col("valid_to", "有效期止", 12, "date"),
        _col("total_amount", "合同金额", 14, "money"),
        _col("tax_rate", "税率%", 9, "num"),
        _col("tax_included_label", "含税价", 9),
        _col("status_label", "状态", 10),
        _col("ocr_label", "原件识别", 12),
        _col("source_file_name", "原件文件", 24),
        _col("order_no", "关联单据号", 16),
        _col("payment_terms", "付款条款", 28),
        _col("note", "备注", 20),
        _col("created_at", "创建时间", 18, "date"),
    ],
    "quotations": [
        _col("quote_no", "报价单号", 18),
        _col("customer_name", "客户名称", 26),
        _col("contact", "联系人", 12),
        _col("contact_phone", "联系电话", 16),
        _col("customer_address", "客户地址", 28),
        _col("quote_date", "报价日期", 12, "date"),
        _col("valid_until", "报价效期", 12, "date"),
        _col("businesser", "业务员", 10),
        _col("payment_method", "付款方式", 14),
        _col("transport_method", "运输方式", 14),
        _col("delivery_place", "交货地点", 20),
        _col("total_quantity", "数量合计", 11, "num"),
        _col("total_amount", "报价金额", 14, "money"),
        _col("status_label", "状态", 10),
        _col("contract_no", "关联合同", 18),
        _col("order_no", "转单号", 16),
        _col("note", "备注", 20),
        _col("created_at", "创建时间", 18, "date"),
    ],
    "statements": [
        _col("statement_no", "对账单号", 18),
        _col("direction_label", "方向", 10),
        _col("party_type_label", "往来类型", 10),
        _col("party_name", "往来单位", 26),
        _col("party_tax_no", "对方税号", 22),
        _col("period_start", "账期起", 12, "date"),
        _col("period_end", "账期止", 12, "date"),
        _col("statement_date", "制单日期", 12, "date"),
        _col("opening_balance", "期初余额", 14, "money"),
        _col("contract_amount", "合同金额", 14, "money"),
        _col("invoiced_amount", "已开票", 14, "money"),
        _col("uninvoiced_amount", "未开票", 14, "money"),
        _col("received_amount", "已收/已付", 14, "money"),
        _col("prepaid_received", "本期预收/付", 14, "money"),
        _col("prepaid_applied", "预收已核销", 14, "money"),
        _col("prepaid_balance", "预收余额", 14, "money"),
        _col("receivable_balance", "应收/应付余额", 16, "money"),
        _col("outstanding_amount", "剩余未收/付", 15, "money", warn="red"),
        _col("item_count", "明细行数", 10, "int"),
        _col("status_label", "状态", 10),
        _col("confirmed_at", "确认时间", 18, "date"),
        _col("note", "备注", 20),
    ],
}

DETAIL_COLUMNS: dict[str, list[dict[str, Any]]] = {
    "contracts": [
        _col("contract_no", "合同编号", 18),
        _col("line_no", "行号", 7, "int"),
        _col("product_name", "商品名称", 26),
        _col("standards", "规格型号", 18),
        _col("unit", "单位", 8),
        _col("quantity", "数量", 11, "num"),
        _col("unit_price", "单价", 12, "money"),
        _col("amount", "金额", 14, "money"),
        _col("note", "备注", 22),
    ],
    "quotations": [
        _col("quote_no", "报价单号", 18),
        _col("line_no", "行号", 7, "int"),
        _col("product_name", "商品名称", 26),
        _col("standards", "规格型号", 18),
        _col("unit", "单位", 8),
        _col("quantity", "数量", 11, "num"),
        _col("unit_price", "单价", 12, "money"),
        _col("amount", "金额", 14, "money"),
        _col("note", "备注", 22),
    ],
    "statements": [
        _col("statement_no", "对账单号", 18),
        _col("line_no", "行号", 7, "int"),
        _col("business_date", "业务日期", 12, "date"),
        _col("source_type_label", "来源", 10),
        _col("source_no", "来源单号", 18),
        _col("contract_no", "合同编号", 18),
        _col("summary", "摘要", 30),
        _col("contract_amount", "合同金额", 14, "money"),
        _col("invoiced_amount", "已开票", 14, "money"),
        _col("uninvoiced_amount", "未开票", 14, "money", warn="fill"),
        _col("received_amount", "已收/已付", 14, "money"),
        _col("prepaid_received", "本期预收/付", 14, "money"),
        _col("prepaid_applied", "预收核销", 13, "money"),
        _col("outstanding_amount", "剩余未收/付", 15, "money", warn="red"),
        _col("invoice_status_label", "发票状态", 11),
        _col("invoice_count", "发票张数", 10, "int"),
        _col("note", "备注", 22),
    ],
}

# 主表末尾要不要打一行合计（只对这些字段求和）
TOTAL_FIELDS: dict[str, tuple[str, ...]] = {
    "contracts": ("total_amount",),
    "quotations": ("total_quantity", "total_amount"),
    "statements": (
        "opening_balance",
        "contract_amount",
        "invoiced_amount",
        "uninvoiced_amount",
        "received_amount",
        "prepaid_received",
        "prepaid_applied",
        "prepaid_balance",
        "receivable_balance",
        "outstanding_amount",
    ),
}

# ---------------------------------------------------------------------------
# 样式（2026-10-25 与网页端「增强对账单」对齐：
#   表头 #1F4E78 深蓝白字、边框 #D3D3D3 浅灰细线、异常数值红字/黄底）
# ---------------------------------------------------------------------------

_TITLE_FONT = Font(name="微软雅黑", size=13, bold=True, color="1F3A5F")
_SUB_FONT = Font(name="微软雅黑", size=9, color="6B7280")
_HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
_HEAD_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
_TOTAL_FILL = PatternFill("solid", fgColor="EDF1F7")
_TOTAL_FONT = Font(name="微软雅黑", size=10, bold=True)
_BODY_FONT = Font(name="微软雅黑", size=10)
_THIN = Side(style="thin", color="D3D3D3")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
# 异常状态色：欠款红字、未开票黄底（与网页端一致）
_RED_FONT = Font(name="微软雅黑", size=10, bold=True, color="C72929")
_WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
_CARD_FILL = PatternFill("solid", fgColor="F2F6F9")
_CARD_LABEL_FONT = Font(name="微软雅黑", size=9, color="5A6B80")
_CARD_VALUE_FONT = Font(name="微软雅黑", size=11, bold=True, color="1F3A5F")
# 斑马纹 / 公司抬头（2026-10-26）：与网页端明细表同一套配色
_ZEBRA_FILL = PatternFill("solid", fgColor="F7F9FC")
_COMPANY_FONT = Font(name="微软雅黑", size=14, bold=True, color="1F3A5F")

_MONEY_FMT = "#,##0.00"
_NUM_FMT = "#,##0.###"
_INT_FMT = "0"


# ---------------------------------------------------------------------------
# 取值与格式化
# ---------------------------------------------------------------------------

def _money(value: Any) -> float:
    """Decimal / 字符串 / None → 两位小数 float。

    ⚠️ 必须过 float：openpyxl 收到 Decimal 会按文本写入，Excel 里 SUM 全 0。
    """
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


def _cell_value(col: dict[str, Any], raw: Any) -> Any:
    kind = col["kind"]
    if kind == "money":
        return _money(raw)
    if kind == "num":
        return _num(raw)
    if kind == "int":
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0
    if kind == "date":
        if raw is None or raw == "":
            return ""
        if isinstance(raw, datetime):
            return raw.strftime("%Y-%m-%d %H:%M")
        return str(raw)[:16]
    return "" if raw is None else str(raw)


def _number_format(kind: str) -> str | None:
    if kind == "money":
        return _MONEY_FMT
    if kind == "num":
        return _NUM_FMT
    if kind == "int":
        return _INT_FMT
    return None


# ---------------------------------------------------------------------------
# 列宽自适应 / 状态着色 / 打印设置（2026-10-26 导出精装）
# ---------------------------------------------------------------------------

# 列宽上下限：8 是"再窄就看不清表头"，46 是"再宽就一屏放不下两列"。
# 备注/摘要这类长文本靠 Excel 的自动换行兜底，不靠无限加宽。
_MIN_COL_WIDTH = 8
_MAX_COL_WIDTH = 46


def _display_width(value: Any) -> int:
    """估算一个值在 Excel 里占几个"字符宽"。中文/全角按 2 算。

    openpyxl 没有真正的 auto-fit（那需要字体度量），但中文按 2 倍估已经够用：
    宁可略宽一点也不要截断 —— 摘要被切一半的表，会计得逐格点开看。
    """
    if value is None or value == "":
        return 0
    text = str(value)
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def _autofit_columns(ws, columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """按表头 + 内容实测宽度设置列宽（含 2 个字符的左右留白）。"""
    for idx, col in enumerate(columns, start=1):
        needed = _display_width(col["label"]) + 2
        for row in rows:
            needed = max(needed, _display_width(_cell_value(col, row.get(col["field"]))) + 2)
        ws.column_dimensions[get_column_letter(idx)].width = max(
            _MIN_COL_WIDTH, min(needed, _MAX_COL_WIDTH)
        )


# 状态 → 颜色。刻意用"包含"匹配而不是等值：后端字典改一个字（已发送 → 已发出）
# 颜色不该跟着丢掉。顺序有意义：先判作废，再看确认/发送，最后才是草稿。
_STATUS_TONES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("作废", "已删", "拒绝", "冲销"), "C72929"),
    (("确认",), "1F4E78"),
    (("发送", "发出"), "15803D"),
    (("草稿", "待"), "B45309"),
)


def _status_font(value: Any) -> Font | None:
    text = "" if value is None else str(value)
    if not text:
        return None
    for words, color in _STATUS_TONES:
        if any(word in text for word in words):
            return Font(name="微软雅黑", size=10, bold=True, color=color)
    return None


def _print_setup(ws, head_row: int, company: str = "") -> None:
    """打印设置：A4 横版 / 按一页宽缩放 / 表头重复 / 页脚页码 / 页眉打印时间。

    "打印时间"用 Excel 的 &D &T 域，而不是导出那一刻的时间 ——
    文件可能周一导出、周五才打，纸上要反映真正的打印时间。
    """
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9  # 9 = A4（PAPERSIZE_A4）
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f"{head_row}:{head_row}"
    ws.print_options.horizontalCentered = True
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5, header=0.2, footer=0.2)
    ws.oddHeader.right.text = "打印时间：&D &T"
    ws.oddHeader.right.size = 9
    ws.oddHeader.right.color = "808080"
    ws.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    ws.oddFooter.center.size = 9
    ws.oddFooter.center.color = "808080"
    if company:
        ws.oddFooter.left.text = company
        ws.oddFooter.left.size = 9
        ws.oddFooter.left.color = "808080"


def _write_summary_cards(ws, start_row: int, cards: list[tuple[str, float]], span: int) -> int:
    """顶部汇总卡片条（2026-10-25）：网页端「期初/本期新增/已开票/已收款/期末应收」
    五卡在 Excel 里的等价物 —— 浅灰底网格，标签一行、数值一行。
    返回卡片块占用的行数（2 行）。"""
    if not cards or span <= 0:
        return 0
    seg = max(2, span // len(cards))
    for index, (label, value) in enumerate(cards):
        c0 = index * seg + 1
        c1 = (index + 1) * seg if index < len(cards) - 1 else max(span, c0)
        if c1 > span:
            c1 = span
        ws.merge_cells(start_row=start_row, start_column=c0, end_row=start_row, end_column=c1)
        ws.merge_cells(start_row=start_row + 1, start_column=c0, end_row=start_row + 1, end_column=c1)
        lc = ws.cell(row=start_row, column=c0, value=label)
        lc.font = _CARD_LABEL_FONT
        lc.alignment = Alignment(horizontal="center", vertical="center")
        vc = ws.cell(row=start_row + 1, column=c0, value=round(float(value or 0), 2))
        vc.font = _CARD_VALUE_FONT
        vc.number_format = _MONEY_FMT
        vc.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(c0, c1 + 1):
            ws.cell(row=start_row, column=col).fill = _CARD_FILL
            ws.cell(row=start_row + 1, column=col).fill = _CARD_FILL
    ws.row_dimensions[start_row].height = 16
    ws.row_dimensions[start_row + 1].height = 20
    return 2


def _write_sheet(
    ws,
    *,
    title: str,
    subtitle: str,
    columns: list[dict[str, Any]],
    rows: Iterable[dict[str, Any]],
    total_fields: tuple[str, ...] = (),
    summary_cards: list[tuple[str, float]] | None = None,
    company: str = "",
) -> int:
    """把一组行写成一张表，返回数据行数（不含标题/表头/合计）。

    2026-10-26 导出精装（与网页端同一套视觉语言）：
      · 抬头三行：公司名 / 单据名 / 共 N 条 + 时间（公司名取自当前账套，不写制表人）；
      · 深蓝表头 #1F4E78 + 白字；数据区斑马纹 #F7F9FC；
      · 列宽**按内容自适应**（中文按 2 字宽算），不再是一排固定像素；
      · 冻结表头 + 打印标题行重复 + A4 横版按宽缩放一页 + 页脚页码；
      · 状态列按语义着色（作废红 / 已确认蓝 / 已发送绿 / 草稿橙）。
    """
    span = len(columns)

    row = 1
    # 公司抬头：只放"当前账套公司名"，不放制表人/审核人 —— 那些是内部流转信息，
    # 对账单是发给对方核对的，抬头越干净越好（2026-10-26 用户拍板）。
    if company:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(span, 1))
        ccell = ws.cell(row=row, column=1, value=company)
        ccell.font = _COMPANY_FONT
        ccell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[row].height = 26
        row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(span, 1))
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = _TITLE_FONT
    cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 24
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(span, 1))
    sub = ws.cell(row=row, column=1, value=subtitle)
    sub.font = _SUB_FONT
    sub.alignment = Alignment(horizontal="left", vertical="center")
    row += 1

    # 顶部汇总卡片（对账单）：插在副标题与表头之间，浅灰底网格
    head_row = row
    if summary_cards:
        head_row += _write_summary_cards(ws, row, summary_cards, max(span, 1))

    for idx, col in enumerate(columns, start=1):
        hc = ws.cell(row=head_row, column=idx, value=col["label"])
        hc.fill = _HEAD_FILL
        hc.font = _HEAD_FONT
        hc.border = _BORDER
        hc.alignment = Alignment(horizontal="center", vertical="center")
        # 列宽不在这里写死：数据落完后按内容自适应（见 _autofit_columns），
    ws.row_dimensions[head_row].height = 22

    data = list(rows)
    r = head_row + 1
    for position, data_row in enumerate(data):
        # 斑马纹（2026-10-26）：第 2、4、6… 行上浅底。整行一起上色而不是逐列判断，
        # 否则空单元格会留白，看起来像"表格被打断"。
        zebra = position % 2 == 1
        for idx, col in enumerate(columns, start=1):
            value = _cell_value(col, data_row.get(col["field"]))
            dc = ws.cell(row=r, column=idx, value=value)
            dc.font = _BODY_FONT
            dc.border = _BORDER
            if zebra:
                dc.fill = _ZEBRA_FILL
            fmt = _number_format(col["kind"])
            if fmt:
                dc.number_format = fmt
            if col["kind"] in ("money", "num", "int"):
                dc.alignment = Alignment(horizontal="right", vertical="center")
            else:
                dc.alignment = Alignment(horizontal="left", vertical="center")
            # 状态着色（2026-10-26）：扫一眼就知道哪张已作废、哪张还没发出去
            if col["field"] == "status_label":
                tone = _status_font(value)
                if tone is not None:
                    dc.font = tone
            # 异常状态色（2026-10-25）：数值 > 0 → 红字（欠款）/ 黄底（未开票）
            warn = col.get("warn")
            if warn and col["kind"] in ("money", "num") and _num(data_row.get(col["field"])) > 0.005:
                if warn == "red":
                    dc.font = _RED_FONT
                elif warn == "fill":
                    dc.fill = _WARN_FILL
        r += 1

    # 合计行：只给"金额/数量"列求和，其余留空（合计行里混进编号是外行做法）
    if data and total_fields:
        for idx, col in enumerate(columns, start=1):
            tc = ws.cell(row=r, column=idx)
            tc.fill = _TOTAL_FILL
            tc.font = _TOTAL_FONT
            tc.border = _BORDER
            if col["field"] in total_fields:
                tc.value = round(sum(_num(row.get(col["field"])) for row in data), 2)
                tc.number_format = _MONEY_FMT if col["kind"] == "money" else _NUM_FMT
                tc.alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=r, column=1, value="合计").alignment = Alignment(horizontal="left", vertical="center")
        r += 1

    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    if data:
        ws.auto_filter.ref = f"A{head_row}:{get_column_letter(max(span, 1))}{head_row + len(data)}"
    _autofit_columns(ws, columns, data)
    _print_setup(ws, head_row, company)
    return len(data)


def build(
    kind: str,
    headers: list[dict[str, Any]],
    details: list[dict[str, Any]],
    *,
    subtitle: str = "",
    company: str = "",
) -> bytes:
    """生成 xlsx 字节流。调用方负责把 ORM 对象转成 dict（键见上面的列定义）。

    `company` 是抬头公司名（当前账套的 own_name）。为空时**不加抬头行** ——
    老调用方/测试不传就还是原来的两行头，行为向后兼容。
    """
    meta = DOC_KINDS.get(kind)
    if meta is None:
        raise ValueError(f"不支持的单据导出类别：{kind}")
    head_sheet, detail_sheet = meta["sheets"]

    # 顶部汇总卡片（2026-10-25，目前只有对账单要）：把网页端顶部的
    # 「期初余额 / 本期新增 / 已开票 / 已收款 / 期末应收」五卡在导出文件
    # 最上方用浅灰底网格复刻一遍 —— 数值 = 本批导出单据的合计。
    cards: list[tuple[str, float]] | None = None
    if kind == "statements" and headers:
        cards = [
            ("期初余额", sum(_num(row.get("opening_balance")) for row in headers)),
            ("本期新增", sum(_num(row.get("contract_amount")) for row in headers)),
            ("本期已开票", sum(_num(row.get("invoiced_amount")) for row in headers)),
            ("本期已收/付", sum(_num(row.get("received_amount")) for row in headers)),
            ("期末应收/应付", sum(_num(row.get("receivable_balance")) for row in headers)),
        ]

    wb = Workbook()
    ws = wb.active
    ws.title = head_sheet

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    head_sub = f"共 {len(headers)} 条　导出时间：{stamp}" + (f"　{subtitle}" if subtitle else "")
    _write_sheet(
        ws,
        title=f"{meta['label']}（{head_sheet}）",
        subtitle=head_sub,
        columns=HEADER_COLUMNS[kind],
        rows=headers,
        total_fields=TOTAL_FIELDS.get(kind, ()),
        summary_cards=cards,
        company=company,
    )

    ws2 = wb.create_sheet(detail_sheet)
    detail_sub = f"共 {len(details)} 行　导出时间：{stamp}" + (f"　{subtitle}" if subtitle else "")
    _write_sheet(
        ws2,
        title=f"{meta['label']}（{detail_sheet}）",
        subtitle=detail_sub,
        columns=DETAIL_COLUMNS[kind],
        rows=details,
        company=company,
    )

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def kinds() -> list[dict[str, Any]]:
    """给前端渲染导出入口用的清单。"""
    out: list[dict[str, Any]] = []
    for kind, meta in DOC_KINDS.items():
        out.append(
            {
                "kind": kind,
                "label": meta["label"],
                "sheets": list(meta["sheets"]),
                "date_field": meta["date_field"],
                "summary": meta["summary"],
                "header_columns": [c["label"] for c in HEADER_COLUMNS[kind]],
                "detail_columns": [c["label"] for c in DETAIL_COLUMNS[kind]],
            }
        )
    return out


def filename(kind: str) -> str:
    meta = DOC_KINDS[kind]
    return f"{meta['file_prefix']}_{datetime.now().strftime('%Y%m%d')}.xlsx"
