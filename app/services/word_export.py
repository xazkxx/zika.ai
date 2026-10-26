"""全单据 Word 导出（任务 E · 2026-10-19）—— 合同 / 报价单 / 入库单 / 对账单 → .docx

## 为什么单开一个服务

`doc_export.py` 那边出的是**台账 xlsx**（给会计做二次加工）；这里出的是**能盖章的
正式文件**（给客户/供应商看）。两者的排版诉求完全相反：Excel 要的是"一行一条、
方便筛选"，Word 要的是"抬头、编号、金额大写、签字栏，像一份真文件"。
所以不共用一个模块，也不共用一套字段口径。

## 四条排版铁律

1. **中文字体必须写 `w:eastAsia`**。python-docx 的 `run.font.name` 只设 ascii/hAnsi，
   Word 打开时中文会掉回"等线"，版式立刻散。所以每个 run 都过 `_cn_font()`。
2. **金额一律"小写 + 大写"两行都给**。财务看大写，业务看小写；只给一个就会被要求重开。
   大写复用 `erp_common.amount_to_chinese()`（对账单/合同一直是它，别写第二份）。
3. **表格必须有框线 + 表头跨页重复**。明细超过一页时，第二页没有表头就没法看了；
   框线靠 `Table Grid` 样式，重复靠 `w:tblHeader`。
4. **空字段不打印**。合同有 30 多个可空字段，全打出来就是一堆"："。只打有值的，
   并按固定顺序排列（先金额与结算，再交货，再质保与争议），保证同类文件长得一样。

## 一页纸的取舍

合同正文的完整条款（二十几条法律条文）**不在这里生成** —— 那是 PDF 模板
（`pdf_render.py` + `_A2_DEFAULTS`）的活。这里出的是"合同要素表 + 标的清单 +
关键条款摘要 + 签字栏"的**商务版合同**，用于快速流转和盖章存档。
两套文件并存：要打完整法律文本用「打印 PDF」，要发 Word 给客户改条款用这里。
"""

from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BODY_FONT = "宋体"
TITLE_FONT = "黑体"
HEADER_SHADE = "F2F2F2"  # 表头底色（浅灰，黑白打印机也分得清）
# 深色表头（2026-10-25）：与网页端/Excel/PDF 统一的 #1F4E78 深蓝 + 白字。
# 只有明确传 head_fill 的表格才用 —— 合同/报价单等老版式不能被悄悄改样。
HEAD_BLUE = "1F4E78"
RED_WARN = RGBColor(0xC7, 0x29, 0x29)  # 欠款/异常红

KIND_LABELS = {
    "contract": "购销合同",
    "quotation": "报价单",
    "inbound": "入库单",
    "statement": "对账单",
}


# ---------------------------------------------------------------------------
# 基础排版
# ---------------------------------------------------------------------------


def _cn_font(run, name: str = BODY_FONT, size: float | None = None, bold: bool | None = None, color: RGBColor | None = None) -> None:
    """给 run 设中英文字体。**eastAsia 必须单独设**，否则 Word 里中文掉字体。"""
    run.font.name = name
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def _para(
    container,
    text: str = "",
    size: float = 10.5,
    bold: bool = False,
    align: str | None = None,
    font: str = BODY_FONT,
    before: float = 0,
    after: float = 2,
    line: float | None = None,
    first_indent: float | None = None,
):
    paragraph = container.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    if line is not None:
        fmt.line_spacing = line
    if first_indent is not None:
        # 首行缩进（公文条款 = 2 字符 ≈ 字号 × 2 pt）
        fmt.first_line_indent = Pt(first_indent)
    if align == "center":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif align == "justify":
        # 两端对齐（标准公文）：右侧不再参差不齐
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    elif align == "left":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if text:
        _cn_font(paragraph.add_run(text), font, size, bold)
    return paragraph


def _hr(container, weight: int = 8) -> None:
    """一条横线（用段落下边框实现，比插表格干净）。"""
    paragraph = container.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(6)
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(weight))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    ppr.append(borders)


def _shade(cell, color: str = HEADER_SHADE) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcpr.append(shd)


def _cell(
    cell,
    text: str,
    size: float = 10.5,
    bold: bool = False,
    align: str = "left",
    font: str = BODY_FONT,
    color: RGBColor | None = None,
) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(1)
    paragraph.paragraph_format.space_after = Pt(1)
    if align == "center":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for index, line in enumerate(str(text).split("\n")):
        if index:
            paragraph = cell.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(1)
            if align == "center":
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif align == "right":
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _cn_font(paragraph.add_run(line), font, size, bold, color)


def _col_widths(table, widths: list[float]) -> None:
    """列宽（厘米）。必须逐格设 —— 只设 `column.width` 在 Word 里不生效。"""
    table.autofit = False
    for row in table.rows:
        for index, width in enumerate(widths):
            if index < len(row.cells):
                row.cells[index].width = Cm(width)


def _repeat_header(table) -> None:
    """表头跨页重复（明细超过一页时，第二页仍然有列名）。"""
    tr = table.rows[0]._tr
    trpr = tr.get_or_add_trPr()
    flag = OxmlElement("w:tblHeader")
    flag.set(qn("w:val"), "true")
    trpr.append(flag)


def _page_footer(section, company_name: str) -> None:
    """页脚：公司名 + 第 X 页 / 共 Y 页（PAGE/NUMPAGES 是域，不是文本）。"""
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if company_name:
        _cn_font(paragraph.add_run(f"{company_name}　　"), BODY_FONT, 8)
    _cn_font(paragraph.add_run("第 "), BODY_FONT, 8)
    for instruction in ("PAGE", "NUMPAGES"):
        run = paragraph.add_run()
        _cn_font(run, BODY_FONT, 8)
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = instruction
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(begin)
        run._r.append(instr)
        run._r.append(end)
        if instruction == "PAGE":
            _cn_font(paragraph.add_run(" 页 / 共 "), BODY_FONT, 8)
    _cn_font(paragraph.add_run(" 页"), BODY_FONT, 8)


def _new_document(company_name: str, *, orientation: str = "portrait"):
    doc = Document()
    section = doc.sections[0]
    if orientation == "landscape":
        # 横向 A4（2026-10-25）：对账单这类宽表必须横版才放得下列，
        # 等价于打印 CSS 的 `@page { size: A4 landscape; margin: 10mm; }`。
        # ⚠️ python-docx 换向必须同时交换宽高 + 显式设 orientation，缺一不可。
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Cm(29.7)
        section.page_height = Cm(21.0)
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)
        section.top_margin = Cm(1.6)
        section.bottom_margin = Cm(1.6)
    else:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)
        section.top_margin = Cm(1.8)
        section.bottom_margin = Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    # 2026-10-25 全局排版：固定 1.5 倍行距（正文段落再补首行缩进 2 字符）
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(2)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.element.rPr.rFonts.set(qn("w:ascii"), BODY_FONT)
    normal.element.rPr.rFonts.set(qn("w:hAnsi"), BODY_FONT)
    _page_footer(section, company_name)
    return doc


# ---------------------------------------------------------------------------
# 数值与文本
# ---------------------------------------------------------------------------


def _money(value) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _qty(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}"
    text = f"{number:,.4f}".rstrip("0").rstrip(".")
    return text


def _cn_amount(value) -> str:
    """人民币大写。复用对账单/合同一直在用的那份实现，不写第二份。"""
    from app.api.v1.routes.erp_common import amount_to_chinese

    return amount_to_chinese(value)


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def _today() -> str:
    return date.today().isoformat()


def _penalty_text(rate) -> str:
    """违约金日比例：0.0005 打印成「每日 0.05%（约万分之五）」，别让客户看小数点后四位。"""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return f"按逾期货款每日 {value * 100:.4g}%（约万分之{value * 10000:.4g}）计"


def _range_text(start, end) -> str:
    start_text, end_text = _s(start), _s(end)
    if start_text and end_text:
        return f"{start_text} 至 {end_text}"
    return start_text or end_text


# ---------------------------------------------------------------------------
# 版面组件
# ---------------------------------------------------------------------------


def _letterhead(doc, company: dict, title: str, subtitle: str = "") -> None:
    """抬头 + 大标题。公司名没设时给一句明确的占位（而不是留白）。"""
    name = _s(company.get("own_name")) or "（公司抬头未设置，请到「系统设置 → 公司信息」补全）"
    _para(doc, name, size=16, bold=True, align="center", font=TITLE_FONT, after=2)
    pieces = [
        _s(company.get("own_address")),
        f"电话：{_s(company['own_phone'])}" if _s(company.get("own_phone")) else "",
        f"税号：{_s(company['own_tax_no'])}" if _s(company.get("own_tax_no")) else "",
    ]
    line = "　".join(piece for piece in pieces if piece)
    if line:
        _para(doc, line, size=8, align="center", after=4)
    _hr(doc)
    _para(doc, title, size=20, bold=True, align="center", font=TITLE_FONT, before=4, after=2)
    if subtitle:
        _para(doc, subtitle, size=9, align="center", after=6)


def _meta_line(doc, items: list[tuple[str, str]], right_align_last: bool = False) -> None:
    """一行元信息（编号 / 日期 …），用制表位对齐成两列。"""
    text = "　　".join(f"{label}：{value}" for label, value in items if value)
    if text:
        _para(doc, text, size=10, after=4, align="right" if right_align_last else None)


def _party_block(doc, left_title: str, left: list[tuple[str, str]], right_title: str, right: list[tuple[str, str]]) -> None:
    """供方/需方（或 客户/报价方）对照块：两列，各自多行。"""
    table = doc.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _cell(table.cell(0, 0), left_title, size=9.5, bold=True, align="center")
    _cell(table.cell(0, 1), right_title, size=9.5, bold=True, align="center")
    _shade(table.cell(0, 0))
    _shade(table.cell(0, 1))

    def render(pairs: list[tuple[str, str]]) -> str:
        return "\n".join(f"{label}：{value}" for label, value in pairs if value) or "—"

    _cell(table.cell(1, 0), render(left), size=9)
    _cell(table.cell(1, 1), render(right), size=9)
    _col_widths(table, [8.3, 8.3])
    _para(doc, "", size=4, after=2)


def _items_table(
    doc,
    headers: list[str],
    rows: list[list[str]],
    widths: list[float],
    aligns: list[str],
    *,
    head_fill: str | None = None,
    head_text_color: RGBColor | None = None,
    red_positive_cols: set[int] | None = None,
    thin_border: bool = False,
) -> None:
    """明细表：表头底色 + 框线 + 跨页重复。行数不足时补一行空行（手写补录用）。

    head_fill 给色时用深色表头 + 白字（对账单与网页端对齐用）；
    red_positive_cols 里各列的数值 > 0 时标红（欠款提醒），不传保持黑字。
    thin_border=True：0.5pt 细实线 + 单元格水平/垂直居中（合同公文要求）。
    """
    red_cols = red_positive_cols or set()
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    if thin_border:
        _thin_borders(table)
    for index, header in enumerate(headers):
        _cell(
            table.rows[0].cells[index],
            header,
            size=10.5,
            bold=True,
            align="center",
            color=head_text_color,
        )
        _shade(table.rows[0].cells[index], head_fill or HEADER_SHADE)
    _repeat_header(table)

    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            color = None
            if index in red_cols:
                try:
                    if float(str(value).replace(",", "").replace("¥", "")) > 0.005:
                        color = RED_WARN
                except ValueError:
                    pass
            _cell(
                cells[index],
                value,
                size=10.5,
                align=aligns[index] if index < len(aligns) else "left",
                color=color,
            )

    if not rows:
        cells = table.add_row().cells
        _cell(cells[0], "（无明细）", size=10.5, align="center")
        for index in range(1, len(headers)):
            _cell(cells[index], "", size=10.5)

    if thin_border:
        # 表内文字水平垂直居中（金额列已按 aligns 右对齐，这里补垂直居中）
        for row in table.rows:
            for cell in row.cells:
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    _col_widths(table, widths)
    return table


def _total_row(
    table,
    label: str,
    amount,
    span: int,
    note: str = "",
) -> None:
    """合计行：前 span 列合并写"合计（大写）"，最后一列写小写金额。"""
    cells = table.add_row().cells
    merged = cells[0]
    for index in range(1, span):
        merged = merged.merge(cells[index])
    amount_text = f"¥{_money(amount)}"
    text = f"{label}：{_cn_amount(amount)}" + (f"（{note}）" if note else "")
    _cell(merged, text, size=10.5, bold=True)
    _cell(cells[-1], amount_text, size=10.5, bold=True, align="right")


def _terms(doc, title: str, pairs: list[tuple[str, str]], official: bool = False) -> None:
    """条款摘要：只打印有值的项，一条一行。

    official=True（合同用，2026-10-25）：标准公文排版 ——
    宋体 12pt（小四）+ 1.5 倍行距 + 两端对齐 + 首行缩进 2 字符（24pt），
    段前段后收紧（标题前 8pt 后 4pt，行间不留空）。
    """
    items = [(label, value) for label, value in pairs if value]
    if not items:
        return
    _para(doc, title, size=12, bold=True, font=TITLE_FONT, before=8, after=3)
    for index, (label, value) in enumerate(items, start=1):
        if official:
            _para(
                doc,
                f"{index}. {label}：{value}",
                size=10.5,
                align="justify",
                line=1.5,
                first_indent=21,
                after=0,
            )
        else:
            _para(doc, f"{index}. {label}：{value}", size=9.5, after=1.5)


# 细实线边框（0.5pt = sz 4，单位是 1/8 pt）：表格线不许再用 Word 默认粗线
def _thin_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), "404040")
        borders.append(element)
    tbl_pr.append(borders)


def _sign_block(doc, left: tuple[str, str], right: tuple[str, str], extra: list[str] | None = None, fields: list[tuple[str, str, str]] | None = None) -> None:
    """签字栏：左右两栏（盖章 / 代表 / 日期），下方可再跟一行补充说明。

    fields 给出时用**标准公文签章网格**（2026-10-25）：0.5pt 细实线表格，
    每行 (标签, 甲方值, 乙方值)，含开户行/账号/盖章处 —— 像图 2 那样整整齐齐。
    """
    if fields:
        table = doc.add_table(rows=len(fields) + 1, cols=2)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _thin_borders(table)
        _cell(table.rows[0].cells[0], left[0] if "盖章" in left[0] else left[0] + "（盖章）", size=10.5, bold=True, align="center", font=TITLE_FONT)
        _shade(table.rows[0].cells[0])
        _cell(table.rows[0].cells[1], right[0] if "盖章" in right[0] else right[0] + "（盖章）", size=10.5, bold=True, align="center", font=TITLE_FONT)
        _shade(table.rows[0].cells[1])
        for r_index, (label, l_value, r_value) in enumerate(fields, start=1):
            _cell(table.cell(r_index, 0), f"{label}：{l_value or '＿＿＿＿＿＿'}", size=10.5, align="left")
            _cell(table.cell(r_index, 1), f"{label}：{r_value or '＿＿＿＿＿＿'}", size=10.5, align="left")
        # 盖章行加高：印章有地方放
        table.rows[1].height = Cm(1.6)
        _col_widths(table, [8.3, 8.3])
    else:
        table = doc.add_table(rows=3, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        blank = {"left": "left", "right": "right"}
        rows = [
            (f"{left[0]}（盖章）：", f"{right[0]}（盖章）："),
            (f"{left[1]}：", f"{right[1]}："),
            ("日期：　　年　　月　　日", "日期：　　年　　月　　日"),
        ]
        for r_index, (l_text, r_text) in enumerate(rows):
            _cell(table.cell(r_index, 0), l_text, size=9.5, align=blank["left"])
            _cell(table.cell(r_index, 1), r_text, size=9.5, align=blank["left"])
        _col_widths(table, [8.3, 8.3])
    for line in extra or []:
        _para(doc, line, size=8.5, before=4, after=0)


# ---------------------------------------------------------------------------
# ① 购销合同
# ---------------------------------------------------------------------------


def build_contract(contract, items, company: dict) -> bytes:
    is_inbound = _s(getattr(contract, "direction", "out")) == "in"
    title = _s(getattr(contract, "title", "")) or ("采购合同" if is_inbound else "销售合同")
    own_title = "需方（甲方）" if is_inbound else "供方（甲方）"
    party_title = "供方（乙方）" if is_inbound else "需方（乙方）"
    # 采购合同：我方是需方，对方是供方 —— 签字栏顺序跟着换，别让客户签错边
    left_label, right_label = (own_title, party_title) if not is_inbound else (party_title, own_title)

    doc = _new_document(_s(company.get("own_name")))
    _letterhead(doc, company, title)
    _meta_line(
        doc,
        [
            ("合同编号", _s(getattr(contract, "contract_no", ""))),
            ("签订日期", _s(getattr(contract, "sign_date", "")) or _today()),
            ("签订地点", _s(getattr(contract, "sign_place", ""))),
        ],
        right_align_last=True,
    )

    own = company
    party = {
        "name": _s(getattr(contract, "party_name", "")),
        "tax_no": _s(getattr(contract, "party_tax_no", "")),
        "legal": _s(getattr(contract, "party_legal_person", "")),
        "address": _s(getattr(contract, "party_address", "")),
        "contact": _s(getattr(contract, "party_contact", "")),
        "phone": _s(getattr(contract, "party_phone", "")),
        "bank": _s(getattr(contract, "party_bank_name", "")),
        "account": _s(getattr(contract, "party_bank_account", "")),
    }
    own_pairs = [
        ("名称", _s(own.get("own_name"))),
        ("税号", _s(own.get("own_tax_no"))),
        ("法定代表人", _s(own.get("own_legal_person"))),
        ("地址", _s(own.get("own_address"))),
        ("联系人", _s(own.get("own_contact"))),
        ("电话", _s(own.get("own_phone"))),
        ("开户行", _s(own.get("own_bank_name"))),
        ("账号", _s(own.get("own_bank_account"))),
    ]
    party_pairs = [
        ("名称", party["name"]),
        ("税号", party["tax_no"]),
        ("法定代表人", party["legal"]),
        ("地址", party["address"]),
        ("联系人", party["contact"]),
        ("电话", party["phone"]),
        ("开户行", party["bank"]),
        ("账号", party["account"]),
    ]
    _party_block(doc, left_label, own_pairs if not is_inbound else party_pairs, right_label, party_pairs if not is_inbound else own_pairs)

    _para(doc, "一、标的物清单", size=11, bold=True, font=TITLE_FONT, before=6, after=3)
    rows = []
    for index, item in enumerate(items, start=1):
        rows.append(
            [
                str(index),
                _s(getattr(item, "product_name", "")) or "—",
                _s(getattr(item, "standards", "")) or "—",
                _s(getattr(item, "unit", "")) or "—",
                _qty(getattr(item, "quantity", 0)),
                _money(getattr(item, "unit_price", 0)),
                _money(getattr(item, "amount", 0)),
            ]
        )
    table = _items_table(
        doc,
        ["序号", "货物名称", "规格型号", "单位", "数量", "单价（元）", "金额（元）"],
        rows,
        # 货物名称 5.0cm、金额 2.5cm：Word 自动换行，不截断（2026-10-25）
        [1.0, 5.0, 2.8, 1.0, 1.5, 2.2, 2.5],
        ["center", "left", "left", "center", "right", "right", "right"],
        thin_border=True,
    )
    _total_row(table, "合计（人民币大写）", getattr(contract, "total_amount", 0), 6)

    amount_note = []
    if _s(getattr(contract, "amount_chinese", "")):
        # 库里已经有大写（OCR 或人工填的），与大写算法结果并列给出，方便核对
        amount_note.append(("金额大写（库内记录）", _s(getattr(contract, "amount_chinese", ""))))
    tax_rate = getattr(contract, "tax_rate", None)
    amount_note.append(
        ("是否含税", ("含税价" if getattr(contract, "is_tax_included", True) else "不含税价") + (f"，税率 {_qty(tax_rate)}%" if tax_rate else ""))
    )

    _terms(
        doc,
        "二、结算与开票",
        amount_note
        + [
            ("付款节点", _s(getattr(contract, "payment_terms", ""))),
            ("开票要求", _s(getattr(contract, "invoice_requirement", ""))),
        ],
        official=True,
    )
    _terms(
        doc,
        "三、交货与验收",
        [
            ("交货时间", _s(getattr(contract, "delivery_date", ""))),
            ("交货地点", _s(getattr(contract, "delivery_place", ""))),
            ("交货方式", _s(getattr(contract, "delivery_method", ""))),
            ("运输与风险", _s(getattr(contract, "freight_bearer", ""))),
            (
                "验收期限",
                f"{getattr(contract, 'inspection_days')} 天" if getattr(contract, "inspection_days", None) else "",
            ),
            (
                "质量异议期限",
                f"{getattr(contract, 'objection_days')} 天" if getattr(contract, "objection_days", None) else "",
            ),
        ],
        official=True,
    )
    _terms(
        doc,
        "四、质量、质保与违约责任",
        [
            ("质量标准", _s(getattr(contract, "quality_standard", ""))),
            ("包装标准", _s(getattr(contract, "package_standard", ""))),
            ("质保与售后", _s(getattr(contract, "warranty_terms", ""))),
            ("违约金", _penalty_text(getattr(contract, "penalty_rate", None))),
            ("争议解决", _s(getattr(contract, "dispute_resolution", ""))),
            ("送达地址", _s(getattr(contract, "service_address", ""))),
        ],
        official=True,
    )
    _terms(
        doc,
        "五、其他约定",
        [
            ("合同有效期", _range_text(getattr(contract, "valid_from", ""), getattr(contract, "valid_to", ""))),
            ("合同份数", f"一式 {getattr(contract, 'copies')} 份" if getattr(contract, "copies", None) else ""),
            ("补充条款", _s(getattr(contract, "other_terms", ""))),
            ("备注", _s(getattr(contract, "note", ""))),
        ],
        official=True,
    )

    _para(doc, "", size=6, after=4)
    # 标准公文签章网格：甲乙双方整整齐齐两列，含开户行/账号/盖章处
    _sign_block(
        doc,
        (left_label, "法定代表人或授权代表"),
        (right_label, "法定代表人或授权代表"),
        fields=[
            ("单位名称", _s(own.get("own_name")) if not is_inbound else _s(party.get("name")), _s(party.get("name")) if not is_inbound else _s(own.get("own_name"))),
            ("法定代表人", _s(own.get("own_legal_person")) if not is_inbound else _s(party.get("legal")), _s(party.get("legal")) if not is_inbound else _s(own.get("own_legal_person"))),
            ("委托代理人", "", ""),
            ("开户银行", _s(own.get("own_bank_name")) if not is_inbound else _s(party.get("bank")), _s(party.get("bank")) if not is_inbound else _s(own.get("own_bank_name"))),
            ("银行账号", _s(own.get("own_bank_account")) if not is_inbound else _s(party.get("account")), _s(party.get("account")) if not is_inbound else _s(own.get("own_bank_account"))),
            ("联系电话", _s(own.get("own_phone")) if not is_inbound else _s(party.get("phone")), _s(party.get("phone")) if not is_inbound else _s(own.get("own_phone"))),
            ("签订日期", _s(getattr(contract, "sign_date", "")) or _today(), _s(getattr(contract, "sign_date", "")) or _today()),
        ],
    )
    return _save(doc)


# ---------------------------------------------------------------------------
# ①b 合同正文 Word（表单草稿链路 · 2026-10-25）
# ---------------------------------------------------------------------------
def build_contract_document(document: dict, company: dict) -> bytes:
    """把 build_gongkuang_document 的文档结构排成正式 Word。

    业务流转：先出这份 Word 给客户确认修改 → 确认无误再生成 PDF 盖章版。
    排版与 build_contract 同一套公文规范：宋体 12pt 正文、1.5 倍行距、
    条款首行缩进两字符且两端对齐、明细表细实线、签章网格。
    """
    buyer = document.get("parties", {}).get("buyer", {})
    seller = document.get("parties", {}).get("seller", {})

    doc = _new_document(_s(company.get("own_name")))
    # 标题：黑体 16pt 居中；编号/日期一行小字居中
    _para(doc, _s(document.get("title")) or "购销合同", size=16, bold=True, font=TITLE_FONT, align="center", after=4)
    meta = "　".join(
        part
        for part in [
            f"合同编号：{_s(document.get('contract_no')) or ''}",
            f"签订日期：{_s(document.get('sign_date')) or ''}",
            f"签订地点：{_s(document.get('sign_place')) or ''}",
        ]
        if not part.endswith("：")
    )
    if meta:
        _para(doc, meta, size=10.5, align="center", after=8)

    # 甲乙双方信息：两列表格，左甲方右乙方
    info_rows = [
        ("单位名称", "name"),
        ("统一社会信用代码", "tax_no"),
        ("法定代表人", "legal"),
        ("地址", "address"),
        ("联系人", "contact"),
        ("联系电话", "phone"),
        ("开户银行", "bank_name"),
        ("银行账号", "bank_account"),
    ]
    info = doc.add_table(rows=len(info_rows) + 1, cols=2)
    info.style = "Table Grid"
    info.alignment = WD_TABLE_ALIGNMENT.CENTER
    _thin_borders(info)
    _cell(info.rows[0].cells[0], "甲方（购货单位）", size=10.5, bold=True, align="center", font=TITLE_FONT)
    _shade(info.rows[0].cells[0])
    _cell(info.rows[0].cells[1], "乙方（供货单位）", size=10.5, bold=True, align="center", font=TITLE_FONT)
    _shade(info.rows[0].cells[1])
    for r_index, (label, key) in enumerate(info_rows, start=1):
        _cell(info.cell(r_index, 0), f"{label}：{_s(buyer.get(key))}", size=10.5)
        _cell(info.cell(r_index, 1), f"{label}：{_s(seller.get(key))}", size=10.5)
    _col_widths(info, [8.3, 8.3])

    _para(doc, "一、标的物明细", size=12, bold=True, font=TITLE_FONT, before=8, after=3)
    rows = [
        [
            str(item.get("no", index)),
            _s(item.get("product_name")) or "—",
            _s(item.get("standards")) or "—",
            _s(item.get("unit")) or "—",
            _qty(item.get("quantity", 0)),
            _money(item.get("unit_price", 0)),
            _money(item.get("amount", 0)),
        ]
        for index, item in enumerate(document.get("items") or [], start=1)
    ]
    table = _items_table(
        doc,
        ["序号", "货物名称", "规格型号", "单位", "数量", "单价（元）", "金额（元）"],
        rows,
        # 货物名称 5.0cm、金额 2.5cm：Word 自动换行，不截断（2026-10-25）
        [1.0, 5.0, 2.8, 1.0, 1.5, 2.2, 2.5],
        ["center", "left", "left", "center", "right", "right", "right"],
        thin_border=True,
    )
    totals = document.get("totals", {})
    _total_row(table, "合计（人民币大写）", totals.get("amount", 0), 6)
    _para(
        doc,
        f"总价：{totals.get('amount_text', '')}（{totals.get('chinese', '')}，{totals.get('tax_note', '')}）",
        size=10.5,
        align="justify",
        line=1.5,
        first_indent=21,
        before=3,
        after=0,
    )

    # 条款正文：标准公文 —— 黑体小标题 + 宋体 10.5pt / 1.5 倍行距 / 首行缩进 2 字符 / 两端对齐
    section_no = 0
    for clause in document.get("clauses") or []:
        section_no += 1
        cn_no = "一二三四五六七八九十"[min(section_no - 1, 9)]
        suffix = "、" if section_no < 10 else "、"
        _para(doc, f"{cn_no}{suffix}{clause.get('heading', '')}", size=12, bold=True, font=TITLE_FONT, before=8, after=3)
        for text in clause.get("paragraphs") or []:
            _para(doc, str(text), size=10.5, align="justify", line=1.5, first_indent=21, after=0)

    notes = document.get("notes") or []
    if notes:
        for text in notes:
            _para(doc, str(text), size=10, before=2, after=0)

    sig = (document.get("signatures") or [{}, {}])[:2]
    s0, s1 = (sig + [{}, {}])[:2]
    _para(doc, "", size=8, after=4)
    _sign_block(
        doc,
        (s0.get("role") or "甲方（购货单位）", "法定代表人或授权代表"),
        (s1.get("role") or "乙方（供货单位）", "法定代表人或授权代表"),
        fields=[
            ("单位名称", _s(s0.get("name")), _s(s1.get("name"))),
            ("法定代表人", _s(s0.get("legal")), _s(s1.get("legal"))),
            ("委托代理人", "", ""),
            ("开户银行", _s(s0.get("bank_name")), _s(s1.get("bank_name"))),
            ("银行账号", _s(s0.get("bank_account")), _s(s1.get("bank_account"))),
            ("盖章处", "（加盖公章）", "（加盖公章）"),
            ("签订日期", _s(s0.get("date")), _s(s1.get("date"))),
        ],
    )
    return _save(doc)


# ---------------------------------------------------------------------------
# ② 报价单
# ---------------------------------------------------------------------------


def build_quotation(quotation, items, company: dict) -> bytes:
    doc = _new_document(_s(company.get("own_name")))
    _letterhead(doc, company, "报 价 单")
    _meta_line(
        doc,
        [
            ("报价单号", _s(getattr(quotation, "quote_no", ""))),
            ("报价日期", _s(getattr(quotation, "quote_date", "")) or _today()),
            ("报价有效期", _s(getattr(quotation, "valid_until", ""))),
        ],
        right_align_last=True,
    )

    customer_pairs = [
        ("客户名称", _s(getattr(quotation, "customer_name", ""))),
        ("客户地址", _s(getattr(quotation, "customer_address", ""))),
        ("联系人", _s(getattr(quotation, "contact", ""))),
        ("联系电话", _s(getattr(quotation, "contact_phone", ""))),
        ("传真", _s(getattr(quotation, "fax", ""))),
    ]
    seller_pairs = [
        ("报价单位", _s(company.get("own_name"))),
        ("联系人", _s(company.get("own_contact"))),
        ("联系电话", _s(company.get("own_phone"))),
        ("地址", _s(company.get("own_address"))),
        ("税号", _s(company.get("own_tax_no"))),
    ]
    _party_block(doc, "客户", customer_pairs, "报价单位", seller_pairs)

    base_note = [
        ("业务员", _s(getattr(quotation, "businesser", ""))),
        ("付款方式", _s(getattr(quotation, "payment_method", ""))),
        ("运输方式", _s(getattr(quotation, "transport_method", ""))),
        ("交货地点", _s(getattr(quotation, "delivery_place", ""))),
    ]
    base_text = "　".join(f"{label}：{value}" for label, value in base_note if value)
    if base_text:
        _para(doc, base_text, size=9.5, before=2, after=3)

    rows = []
    for index, item in enumerate(items, start=1):
        rows.append(
            [
                str(index),
                _s(getattr(item, "product_name", "")) or "—",
                _s(getattr(item, "standards", "")) or "—",
                _s(getattr(item, "unit", "")) or "—",
                _qty(getattr(item, "quantity", 0)),
                _money(getattr(item, "unit_price", 0)),
                _money(getattr(item, "amount", 0)),
            ]
        )
    table = _items_table(
        doc,
        ["序号", "商品名称", "规格型号", "单位", "数量", "单价（元）", "金额（元）"],
        rows,
        [1.1, 4.2, 3.4, 1.1, 1.7, 2.2, 2.5],
        ["center", "left", "left", "center", "right", "right", "right"],
    )
    _total_row(table, "合计（人民币大写）", getattr(quotation, "total_amount", 0), 6)
    _para(
        doc,
        f"商品数量合计：{_qty(getattr(quotation, 'total_quantity', 0))}",
        size=9,
        align="right",
        before=2,
        after=4,
    )

    _terms(
        doc,
        "报价说明",
        [
            ("价格有效期", _s(getattr(quotation, "valid_until", "")) or "以报价单标注为准"),
            ("付款方式", _s(getattr(quotation, "payment_method", ""))),
            ("备注", _s(getattr(quotation, "note", ""))),
        ],
    )
    _para(
        doc,
        "以上报价含税单价以人民币计；如有变动以双方另行确认的书面文件为准。",
        size=8.5,
        before=4,
        after=2,
    )
    _sign_block(doc, ("报价单位", "经办人"), ("客户确认", "经办人"))
    return _save(doc)


# ---------------------------------------------------------------------------
# ③ 入库单
# ---------------------------------------------------------------------------


def build_inbound(order, items, company: dict, supplier: dict | None = None, warehouse_name: str = "") -> bytes:
    """采购入库单（doc_type='inbound'）/ 采购订单（doc_type='order'）共用一个版式。"""
    doc_type = _s(getattr(order, "doc_type", "inbound")) or "inbound"
    title = "采购订单" if doc_type == "order" else "采 购 入 库 单"
    supplier = supplier or {}

    doc = _new_document(_s(company.get("own_name")))
    _letterhead(doc, company, title)
    _meta_line(
        doc,
        [
            ("单号", _s(getattr(order, "order_no", ""))),
            ("开单日期", _s(getattr(order, "order_date", "")) or _today()),
            ("仓库", warehouse_name),
        ],
        right_align_last=True,
    )

    info_pairs = [
        ("供应商", _s(supplier.get("name"))),
        ("联系人", _s(getattr(order, "contact", "")) or _s(supplier.get("contact"))),
        ("联系电话", _s(getattr(order, "contact_phone", "")) or _s(supplier.get("phone"))),
        ("收货地址", _s(getattr(order, "address", "")) or _s(supplier.get("address"))),
    ]
    info2_pairs = [
        ("业务员", _s(getattr(order, "businesser", ""))),
        ("付款方式", _s(getattr(order, "payment_method", ""))),
        ("送货日期", _s(getattr(order, "delivery_date", ""))),
        ("备注", _s(getattr(order, "note", ""))),
    ]
    _party_block(doc, "供应商信息", info_pairs, "本单信息", info2_pairs)

    rows = []
    for index, item in enumerate(items, start=1):
        rows.append(
            [
                str(index),
                _s(getattr(item, "product_name", "")) or "—",
                _s(getattr(item, "standards", "")) or "—",
                _s(getattr(item, "unit", "")) or "—",
                _qty(getattr(item, "quantity", 0)),
                _money(getattr(item, "unit_price", 0)),
                _money(getattr(item, "amount", 0)),
            ]
        )
    table = _items_table(
        doc,
        ["序号", "商品名称", "规格型号", "单位", "数量", "单价（元）", "金额（元）"],
        rows,
        [1.1, 4.2, 3.4, 1.1, 1.7, 2.2, 2.5],
        ["center", "left", "left", "center", "right", "right", "right"],
    )
    _total_row(table, "合计（人民币大写）", getattr(order, "total_amount", 0), 6)

    settle = [
        ("应付金额", f"¥{_money(getattr(order, 'payable_amount', 0))}" if getattr(order, "payable_amount", None) else ""),
        ("优惠金额", f"¥{_money(getattr(order, 'discount_amount', 0))}" if getattr(order, "discount_amount", None) else ""),
        ("实付金额", f"¥{_money(getattr(order, 'paid_amount', 0))}" if getattr(order, "paid_amount", None) else ""),
        ("本次欠款", f"¥{_money(getattr(order, 'current_debt', 0))}" if getattr(order, "current_debt", None) else ""),
        ("累欠货款", f"¥{_money(getattr(order, 'total_debt', 0))}" if getattr(order, "total_debt", None) else ""),
    ]
    settle_text = "　　".join(f"{label}：{value}" for label, value in settle if value)
    if settle_text:
        _para(doc, settle_text, size=9.5, before=6, after=2)

    _sign_block(
        doc,
        ("仓库保管", "收货人"),
        ("供应商", "送货人"),
        extra=["本单一式三联：第一联存根（财务）、第二联仓库、第三联供应商。"],
    )
    return _save(doc)


# ---------------------------------------------------------------------------
# ④ 对账单
# ---------------------------------------------------------------------------


def build_statement(statement, items, company: dict) -> bytes:
    direction = _s(getattr(statement, "direction", "out")) or "out"
    is_payable = direction == "in"
    title = "供应商对账单（应付）" if is_payable else "客户对账单（应收）"
    party_label = "供应商" if is_payable else "客户"

    # 横向 A4（2026-10-25）：对账单是宽表单据，横版才与网页端预览一个观感。
    doc = _new_document(_s(company.get("own_name")), orientation="landscape")
    _letterhead(doc, company, title)
    _meta_line(
        doc,
        [
            ("对账单号", _s(getattr(statement, "statement_no", ""))),
            ("账期", _period(statement)),
            ("制单日期", _s(getattr(statement, "statement_date", "")) or _today()),
        ],
        right_align_last=True,
    )

    left_pairs = [
        ("对账单位", _s(getattr(statement, "party_name", ""))),
        ("税号", _s(getattr(statement, "party_tax_no", ""))),
    ]
    right_pairs = [
        ("我方单位", _s(company.get("own_name"))),
        ("税号", _s(company.get("own_tax_no"))),
        ("联系人", _s(company.get("own_contact"))),
        ("电话", _s(company.get("own_phone"))),
    ]
    _party_block(doc, party_label, left_pairs, "我方", right_pairs)

    # 顶部汇总卡片（网页端同款五卡）：期初 / 本期新增 / 已开票 / 已收付 / 期末应收
    cards = [
        ("期初余额", getattr(statement, "opening_balance", 0)),
        ("本期新增", getattr(statement, "contract_amount", 0)),
        ("本期已开票", getattr(statement, "invoiced_amount", 0)),
        (f"本期已{'付' if is_payable else '收'}", getattr(statement, "received_amount", 0)),
        ("期末应收" if not is_payable else "期末应付", getattr(statement, "receivable_balance", 0)),
    ]
    card_table = doc.add_table(rows=2, cols=len(cards))
    card_table.style = "Table Grid"
    card_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index, (label, value) in enumerate(cards):
        _cell(card_table.rows[0].cells[index], label, size=9, bold=True, align="center", color=RGBColor(0x1F, 0x3A, 0x5F))
        _shade(card_table.rows[0].cells[index])
        _cell(card_table.rows[1].cells[index], _money(value), size=10.5, bold=True, align="center")
        _shade(card_table.rows[1].cells[index], "F7FAFD")
    _col_widths(card_table, [5.3] * len(cards))

    _para(doc, "", size=4, after=2)

    rows = []
    for index, item in enumerate(items, start=1):
        rows.append(
            [
                str(index) if not _s(getattr(item, "line_no", "")) else _s(getattr(item, "line_no", "")),
                _s(getattr(item, "business_date", "")) or "—",
                _source_label(getattr(item, "source_type", "")),
                _s(getattr(item, "contract_no", "")) or "—",
                _s(getattr(item, "summary", "")) or "—",
                _s(getattr(item, "source_no", "")) or "—",
                _money(getattr(item, "contract_amount", 0)),
                _money(getattr(item, "invoiced_amount", 0)),
                _money(getattr(item, "uninvoiced_amount", 0)),
                _money(getattr(item, "received_amount", 0)),
                _money(getattr(item, "outstanding_amount", 0)),
            ]
        )
    table = _items_table(
        doc,
        [
            "序号", "业务日期", "来源", "合同编号", "摘要", "单据编号",
            "合同金额", "已开票", "未开票", "已收" if not is_payable else "已付", "剩余未收/付",
        ],
        rows,
        # 横版可用宽 ≈ 26.7cm，逐列分：日期/来源窄，摘要最宽，金额列等宽右对齐
        [1.1, 2.1, 1.3, 2.6, 4.6, 2.6, 2.4, 2.4, 2.4, 2.4, 2.8],
        ["center", "center", "center", "left", "left", "left",
         "right", "right", "right", "right", "right"],
        head_fill=HEAD_BLUE,
        head_text_color=RGBColor(0xFF, 0xFF, 0xFF),
        red_positive_cols={10},
    )
    _total_row(table, "应收/应付余额", getattr(statement, "receivable_balance", 0), 10)

    summary = [
        ("本期未开票", getattr(statement, "uninvoiced_amount", 0)),
        ("本期预收/付", getattr(statement, "prepaid_received", 0)),
        ("预收/付已核销", getattr(statement, "prepaid_applied", 0)),
        ("预收/付余额", getattr(statement, "prepaid_balance", 0)),
        ("剩余未结", getattr(statement, "outstanding_amount", 0)),
    ]
    table2 = doc.add_table(rows=0, cols=4)
    table2.style = "Table Grid"
    table2.alignment = WD_TABLE_ALIGNMENT.CENTER
    for index in range(0, len(summary), 2):
        pair = summary[index: index + 2]
        cells = table2.add_row().cells
        _cell(cells[0], pair[0][0], size=9, bold=True, align="center")
        _shade(cells[0])
        _cell(cells[1], _money(pair[0][1]), size=9, align="right")
        if len(pair) > 1:
            _cell(cells[2], pair[1][0], size=9, bold=True, align="center")
            _shade(cells[2])
            _cell(cells[3], _money(pair[1][1]), size=9, align="right")
        else:
            _cell(cells[2], "", size=9)
            _cell(cells[3], "", size=9)
    _col_widths(table2, [4.0, 4.3, 4.0, 4.3])

    _para(
        doc,
        f"本期{party_label}合计（大写）：{_cn_amount(getattr(statement, 'receivable_balance', 0))}",
        size=9.5,
        bold=True,
        before=6,
        after=3,
    )
    _terms(
        doc,
        "对账说明",
        [
            ("状态", _statement_status(getattr(statement, "status", ""))),
            ("明细条数", f"{getattr(statement, 'item_count', 0)} 条" if getattr(statement, "item_count", None) else ""),
            ("备注", _s(getattr(statement, "note", ""))),
        ],
    )
    _para(
        doc,
        "请核对以上账目，确认无误后盖章回传；如有异议，请于收到本对账单后 5 个工作日内书面提出。",
        size=9,
        before=4,
        after=2,
    )
    _sign_block(doc, ("我方", "经办人"), (party_label, "经办人"))
    return _save(doc)


def _period(statement) -> str:
    start = _s(getattr(statement, "period_start", ""))
    end = _s(getattr(statement, "period_end", ""))
    if start and end:
        return f"{start} 至 {end}"
    return start or end


_SOURCE_LABELS = {
    "contract": "合同",
    "order": "订单",
    "inbound": "入库",
    "outbound": "出库",
    "invoice": "发票",
    "receipt": "收款",
    "payment": "付款",
    "opening": "期初",
}

_STATEMENT_STATUS_LABELS = {
    "draft": "草稿",
    "confirmed": "已确认",
    "sent": "已发送",
    "void": "作废",
}


def _source_label(value) -> str:
    key = _s(value)
    return _SOURCE_LABELS.get(key, key or "—")


def _statement_status(value) -> str:
    key = _s(value)
    return _STATEMENT_STATUS_LABELS.get(key, key)


def _save(doc) -> bytes:
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
