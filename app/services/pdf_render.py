"""通用单据 PDF 渲染器（pymupdf 手工排版）。

供 /api/v1/print/* 接口使用。中文字体优先嵌入系统宋体/黑体并子集化，
找不到时回退 pymupdf 内置 CJK 字体。

spec 结构（字段全部可选，按需给）：
{
    "company": "抬头公司名称",
    "header_text": "公司名下的附加抬头（地址/电话/税号，支持 \\n 多行）",
    "title": "采购入库单",                  # 主标题
    "subtitle": "合同编号：HT-2026-001",     # 副标题
    "doc_no": "CG20261010001",              # 右上角单号
    "period": "对账期间：2026-01-01 ~ 2026-10-10",
    "header_left":  [("供应商", "…"), ("联系人", "…")],
    "header_right": [("单据日期", "…"), ("仓库", "…")],
    "columns": [{"label": "序号", "width": 34, "align": "c"}, …],
    "rows": [["1", "不锈钢法兰", …], …],
    "totals": {"label": "合计", "chinese": "大写：…", "amount": "7,594.00"},
    "extra_rows": [("本次优惠", "¥100.00"), …],   # 合计后追加的无框右对齐行
    "summary": [("期初余额", "0.00"), …],          # 一行多格键值汇总块
    "paragraphs": ["经双方核对…"],                 # 正文段落（余额确认单）
    "notes": ["备注：…"],
    "signatures": ["制单", "审核", "仓管"],
    # —— 排版（打印模板库，2026-10-20）——
    "layout": {
        "width": 595.28, "height": 841.89,        # 页面尺寸（pt）
        "margin_left": 34.02, "margin_right": 28.35,
        "margin_top": 34.02, "margin_bottom": 34.02,
        "font_title": 16, "font_header": 10, "font_body": 9, "font_footer": 8,
    },
}

排版从哪来
----------
`spec["layout"]` 由 `app/models/print_template.py::layout_of()` 从打印模板换算，
**没传时用 DEFAULT_LAYOUT（＝改造前的固定值）** —— 保证未登记打印类型的单据
输出与改造前一模一样，不能因为"加了可配置"就把老单据印歪。
"""
from __future__ import annotations

import math
import os
from contextvars import ContextVar

import pymupdf as fitz

from app.services.brand_logo import PRINT_LOGO_HEIGHT_PT, print_logo_image

# 兜底排版：改造前的硬编码值。任何一处 template 缺失都回落到这里。
_BASE_LAYOUT: dict[str, float] = {
    "width": 595.28,
    "height": 841.89,
    "margin_left": 40.0,
    "margin_right": 40.0,
    "margin_top": 40.0,
    "margin_bottom": 40.0,
    "font_title": 17.0,
    "font_header": 9.0,
    "font_body": 8.5,
    "font_footer": 8.0,
}

# 用 ContextVar 而不是模块级可变全局：FastAPI 的同步路由跑在线程池里，
# 两个并发打印请求如果共享一个"当前排版"，会互相把对方的边距改掉。
_LAYOUT: ContextVar[dict[str, float]] = ContextVar("pdf_layout", default=_BASE_LAYOUT)

FOOTER_H = 26.0

_ALIGN = {"l": 0, "c": 1, "r": 2, "j": 3}  # 3 = TEXT_ALIGN_JUSTIFY（两端对齐，公文正文用）

_FONT_FILES = {
    "song": (
        r"C:\Windows\Fonts\simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ),
    "hei": (
        r"C:\Windows\Fonts\simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
}
_resolved: dict[str, str | None] = {}


def _font_path(kind: str) -> str | None:
    if kind not in _resolved:
        _resolved[kind] = next(
            (p for p in _FONT_FILES.get(kind, ()) if os.path.exists(p)), None
        )
    return _resolved[kind]


def _L() -> dict[str, float]:
    return _LAYOUT.get()


def _merge_layout(raw: dict | None) -> dict[str, float]:
    """把传入的排版合并到兜底值上：缺哪项补哪项，脏值不认。"""
    layout = dict(_BASE_LAYOUT)
    for key, value in (raw or {}).items():
        if key not in layout:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            layout[key] = number
    # 可用宽度必须为正，否则整页排版会算出负数列宽
    if layout["width"] - layout["margin_left"] - layout["margin_right"] <= 40:
        layout["margin_left"] = layout["margin_right"] = 20.0
    return layout


def _hex_color(value) -> tuple[float, float, float] | None:
    """"#1F4E78" / "1F4E78" → 0-1 RGB（pymupdf 要 0-1 浮点）。脏值回 None。"""
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _text_width(s: str, size: float) -> float:
    return sum(size if ord(c) > 127 else size * 0.55 for c in s)


def _fit(s: str, width: float, size: float) -> str:
    s = "" if s is None else str(s)
    if _text_width(s, size) <= width:
        return s
    while s and _text_width(s + "…", size) > width:
        s = s[:-1]
    return s + "…"


class Canvas:
    """单页画布：注册字体、绘制文本/线条/矩形。"""

    def __init__(self, page: fitz.Page):
        self.page = page
        self.body = "china-s"  # 内置 CJK 回退
        self.bold = "china-s"
        song, hei = _font_path("song"), _font_path("hei")
        if song:
            page.insert_font(fontname="song", fontfile=song)
            self.body = "song"
        if hei:
            page.insert_font(fontname="hei", fontfile=hei)
            self.bold = "hei"

    def text(self, box, s, font=None, size=9.0, align="l", color=(0, 0, 0), lineheight=None):
        x0, y0, x1, y1 = box
        kwargs = {}
        if lineheight:
            kwargs["lineheight"] = lineheight
        self.page.insert_textbox(
            fitz.Rect(x0, y0, x1, y1),
            str(s),
            fontname=font or self.body,
            fontsize=size,
            align=_ALIGN[align],
            color=color,
            **kwargs,
        )

    def line(self, x0, y0, x1, y1, width=0.5, color=(0, 0, 0)):
        self.page.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1), color=color, width=width)

    def rect(self, x0, y0, x1, y1, width=0.5, fill=None, stroke=(0, 0, 0)):
        """画矩形。fill 给色时填充（打印模板的深色表头 / 浅灰汇总块就靠它）。"""
        self.page.draw_rect(
            fitz.Rect(x0, y0, x1, y1),
            color=None if fill and not stroke else stroke,
            fill=fill,
            width=width,
        )


def _new_page(doc: fitz.Document) -> Canvas:
    layout = _L()
    return Canvas(doc.new_page(width=layout["width"], height=layout["height"]))


def _fmt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:,.2f}"
    if isinstance(val, int) and not isinstance(val, bool):
        return f"{val:,}"
    return str(val)


def _normalize_columns(columns: list[dict]) -> list[dict]:
    """列宽归一化到可用页宽：金额/表头保底，不够宽时优先压缩「摘要」类列。"""
    layout = _L()
    avail = layout["width"] - layout["margin_left"] - layout["margin_right"]
    fs_header = layout["font_header"]
    raw: list[dict] = []
    for c in columns:
        label = c.get("label", "")
        shrink = bool(c.get("shrink")) or any(hint in str(label) for hint in ("摘要", "备注", "说明"))
        min_width = c.get("min_width")
        try:
            min_w = float(min_width) if min_width not in (None, "") else None
        except (TypeError, ValueError):
            min_w = None
        if min_w is None:
            min_w = _text_width(str(label), fs_header) + 8.0
            if c.get("align") == "r":
                min_w = max(min_w, 56.0)
            elif c.get("align") == "c":
                min_w = max(min_w, 28.0)
            else:
                min_w = max(min_w, 40.0)
        raw.append(
            {
                "label": label,
                "width": float(c.get("width", 60)),
                "align": c.get("align", "l"),
                "min_width": min_w,
                "shrink": shrink,
                "wrap": bool(c.get("wrap")),
            }
        )
    total = sum(c["width"] for c in raw) or 1.0
    scale = avail / total
    for c in raw:
        c["width"] *= scale

    if not any(c["shrink"] for c in raw) and raw:
        raw[max(range(len(raw)), key=lambda i: raw[i]["width"])]["shrink"] = True

    shrinkers = [c for c in raw if c["shrink"]]
    others = [c for c in raw if not c["shrink"]]

    for c in others:
        if c["width"] < c["min_width"]:
            c["width"] = c["min_width"]

    used = sum(c["width"] for c in others)
    leftover = avail - used
    if leftover < 24.0 * max(1, len(shrinkers)):
        # 保底列已经把纸宽占满：摘要列吃剩余，其它列按保底（必要时再等比微缩保底列）
        floor = sum(c["min_width"] for c in others)
        leftover = max(36.0, avail - floor)
        for c in others:
            c["width"] = c["min_width"]
        if floor > avail - 36.0 and others:
            factor = max(0.72, (avail - 36.0) / floor)
            for c in others:
                c["width"] = c["min_width"] * factor
            leftover = max(36.0, avail - sum(c["width"] for c in others))
    if shrinkers:
        weight = sum(max(c["width"], 1.0) for c in shrinkers) or 1.0
        for c in shrinkers:
            c["width"] = leftover * (max(c["width"], 1.0) / weight)
    else:
        # 没有可压缩列：整体再缩一次贴齐纸宽
        current = sum(c["width"] for c in raw) or 1.0
        factor = avail / current
        for c in raw:
            c["width"] *= factor

    current = sum(c["width"] for c in raw) or 1.0
    if abs(current - avail) > 0.4:
        factor = avail / current
        for c in raw:
            c["width"] *= factor

    return [
        {
            "label": c["label"],
            "width": c["width"],
            "align": c["align"],
            # wrap=True 的列（合同货物名称/规格）允许换行，行高按内容算，
            # 绝不用 _fit 截成 "..."；其余列仍保持单行。
            "wrap": c["wrap"],
        }
        for c in raw
    ]


def _para_height(text: str, width: float, size: float = 10.0) -> float:
    """估算段落高度。支持 ``\n`` 硬换行 —— 合同条款是分条分行写的。"""
    per = max(1, int(width / size))
    lines = 0
    for seg in str(text).split("\n"):
        lines += max(1, math.ceil(len(seg) / per)) if seg else 1
    return lines * size * 1.55 + 4


def _render_head(cv: Canvas, spec: dict, y: float) -> float:
    L = _L()
    left, right_x = L["margin_left"], L["width"] - L["margin_right"]
    inner = right_x - left
    fs_header, fs_title, fs_body = L["font_header"], L["font_title"], L["font_body"]

    # 页眉 Logo（v1.81.0）：**有文件才画**，画完把 y 往下推，后面所有抬头内容顺延。
    # 居中对齐而不是靠左：公司名、标题都是居中的，Logo 靠左会在视觉上"掉"出信纸中轴。
    # 高度用 PRINT_LOGO_HEIGHT_PT（≈32.6pt），等比缩放靠 keep_proportion —— 用户给
    # 横版或方版都不会被拉扁。图片读不了就静默跳过，不能让开单打印 500。
    logo = print_logo_image()
    if logo is not None:
        try:
            pix = fitz.Pixmap(str(logo))
            logo_h = PRINT_LOGO_HEIGHT_PT
            logo_w = logo_h * pix.width / max(pix.height, 1)
            mid = L["width"] / 2
            cv.page.insert_image(
                fitz.Rect(mid - logo_w / 2, y, mid + logo_w / 2, y + logo_h),
                filename=str(logo),
                keep_proportion=True,
            )
            y += logo_h + 6
        except Exception:
            pass

    if spec.get("company"):
        h = max(fs_header * 1.4, 14.0)
        cv.text((left, y, right_x, y + h), spec["company"], font=cv.bold, size=fs_header + 0.5, align="c")
        y += h + 2
    # 抬头附加文字（打印模板的 header_text）：公司名与标题之间，居中，可多行。
    # 这是"信纸抬头"那一行（地址 / 电话 / 税号），排在公司名下面最自然。
    header_text = str(spec.get("header_text") or "").strip()
    if header_text:
        h = _para_height(header_text, inner, size=fs_body)
        cv.text((left, y, right_x, y + h), header_text, size=fs_body, align="c")
        y += h
    if spec.get("title"):
        h = fs_title * 1.55
        cv.text((left, y, right_x, y + h), spec["title"], font=cv.bold, size=fs_title, align="c")
        y += h + 5
    if spec.get("subtitle"):
        h = fs_body * 1.5
        cv.text((left, y, right_x, y + h), spec["subtitle"], size=fs_body + 0.5, align="c")
        y += h + 2

    right_parts = []
    if spec.get("period"):
        right_parts.append(str(spec["period"]))
    if spec.get("doc_no"):
        right_parts.append(f"单号：{spec['doc_no']}")
    if right_parts:
        h = fs_body * 1.45
        cv.text((right_x - 340, y, right_x, y + h), "    ".join(right_parts), size=fs_body + 0.5, align="r")
        y += h + 3

    head_left = spec.get("header_left") or []
    head_right = spec.get("header_right") or []
    if head_left or head_right:
        # 往来单位信息 = **纯文本两栏**（2026-10-25 用户定版）：不要框线表格，
        # 标签加粗、数值常规，一行一条 —— 像正式函件的抬头，不像台账。
        n = max(len(head_left), len(head_right))
        row_h = max(fs_body * 2.1, 19.0)
        half = inner / 2 - 8
        label_w = 78.0
        lx0, rx0 = left, left + half + 16
        top = y
        for i in range(n):
            yy = top + i * row_h
            if i < len(head_left):
                cv.text((lx0, yy, lx0 + label_w, yy + row_h), f"{head_left[i][0]}：", font=cv.bold, size=fs_body + 0.5)
                cv.text(
                    (lx0 + label_w, yy, lx0 + half, yy + row_h),
                    _fit(head_left[i][1], half - label_w - 8, fs_body + 0.5),
                    size=fs_body + 0.5,
                )
            if i < len(head_right):
                cv.text((rx0, yy, rx0 + label_w, yy + row_h), f"{head_right[i][0]}：", font=cv.bold, size=fs_body + 0.5)
                cv.text(
                    (rx0 + label_w, yy, rx0 + half, yy + row_h),
                    _fit(head_right[i][1], half - label_w - 8, fs_body + 0.5),
                    size=fs_body + 0.5,
                )
        y = top + n * row_h + 10
    return y


def _render_table(doc: fitz.Document, cv: Canvas, spec: dict, y: float) -> tuple[Canvas, float]:
    columns = _normalize_columns(spec.get("columns") or [])
    if not columns:
        return cv, y
    L = _L()
    left = L["margin_left"]
    rows = spec.get("rows") or []
    fs_body, fs_header = L["font_body"], L["font_header"]
    # 行高跟着字号走：9pt 表体 ≈ 20pt 行高，与改造前的 20 一致
    row_h = float(spec.get("row_height") or max(fs_body * 2.2, 18.0))
    hdr_h = max(fs_header * 2.2, 20.0)
    xs = [left]
    for c in columns:
        xs.append(xs[-1] + c["width"])

    # 深色表头（2026-10-25）：与网页端一致，#1F4E78 深蓝底 + 白字。
    # spec 不给 table_head_fill 时保持黑框白底 —— 老单据打印不能被悄悄改样。
    head_fill = _hex_color(spec.get("table_head_fill"))
    head_text_color = (1, 1, 1) if head_fill else (0, 0, 0)

    def _vcenter(y0: float, box_h: float, size: float) -> float:
        """insert_textbox 是顶对齐 —— 行加高后文字会贴着上框线，
        这里按行高把文本框往下挪半格，做出垂直居中。"""
        return y0 + max(0.0, (box_h - size * 1.5) / 2)

    def draw_header(yy: float) -> float:
        if head_fill:
            cv.rect(xs[0], yy, xs[-1], yy + hdr_h, width=0.0, fill=head_fill, stroke=None)
        else:
            cv.rect(xs[0], yy, xs[-1], yy + hdr_h, width=0.8)
        ty = _vcenter(yy, hdr_h, fs_header)
        for i, col in enumerate(columns):
            if not head_fill and i:
                cv.line(xs[i], yy, xs[i], yy + hdr_h)
            cv.text(
                (xs[i], ty, xs[i + 1], ty + fs_header * 1.5),
                _fit(col["label"], col["width"] - 4, fs_header),
                font=cv.bold,
                size=fs_header,
                align="c",
                color=head_text_color,
            )
        return yy + hdr_h

    def page_left(yy: float, height: float = 0) -> bool:
        return yy + max(height, row_h) > L["height"] - L["margin_bottom"] - FOOTER_H

    if page_left(y + hdr_h):
        cv = _new_page(doc)
        y = L["margin_top"] + 12
    y = draw_header(y)

    # 表体框线用浅灰（#D3D3D3），不再是大黑粗格 —— 与网页端观感一致
    _grid = (0.827, 0.827, 0.827)

    # 指定列的数值 > 0 时标红（如「剩余未收/付」欠款提醒），对齐网页端状态色
    red_idx = {int(i) for i in (spec.get("red_positive_columns") or []) if str(i).lstrip("-").isdigit()}

    for row in rows:
        # 先按内容算这一行需要多高：wrap 列（货物名称/规格）可折行，
        # 行高跟着最长的那格走，避免折行文字压到下一行。
        cells = [_fmt(row[i]) if i < len(row) else "" for i in range(len(columns))]
        current_h = row_h
        for i, col in enumerate(columns):
            if col.get("wrap"):
                current_h = max(current_h, _para_height(cells[i], col["width"] - 6, fs_body))
        if page_left(y, current_h):
            cv = _new_page(doc)
            y = L["margin_top"] + 12
            y = draw_header(y)
        cv.rect(xs[0], y, xs[-1], y + current_h, width=0.4, stroke=_grid)
        for i, col in enumerate(columns):
            if i:
                cv.line(xs[i], y, xs[i], y + current_h, color=_grid)
            cell = cells[i]
            is_red = False
            if i in red_idx:
                try:
                    is_red = float(str(cell).replace(",", "").replace("¥", "")) > 0.005
                except ValueError:
                    is_red = False
            if col.get("wrap"):
                ty = y + 2
                box_h = max(fs_body * 1.5, current_h - 4)
                value = cell
            else:
                ty = _vcenter(y, current_h, fs_body)
                box_h = fs_body * 1.5
                value = _fit(cell, col["width"] - 6, fs_body)
            cv.text(
                (xs[i] + 2, ty, xs[i + 1] - 2, ty + box_h),
                value,
                size=fs_body,
                align=col["align"],
                color=(0.78, 0.16, 0.16) if is_red else (0, 0, 0),
            )
        y += current_h

    totals = spec.get("totals")
    if totals:
        total_h = max(fs_body * 2.4, 22.0)
        if y + total_h > L["height"] - L["margin_bottom"] - FOOTER_H:
            cv = _new_page(doc)
            y = L["margin_top"] + 12
            y = draw_header(y)
        total_fill = _hex_color(spec.get("total_fill")) or (0.929, 0.945, 0.969)  # #EDF1F7 浅灰蓝
        cv.rect(xs[0], y, xs[-1], y + total_h, width=0.8, fill=total_fill, stroke=(0, 0, 0))
        label_w = min(90.0, xs[1] - xs[0] + (xs[2] - xs[1] if len(xs) > 2 else 0))
        amount_w = min(95.0, xs[-1] - xs[-2])
        ty = _vcenter(y, total_h, fs_body)
        cv.text((xs[0], ty, xs[0] + label_w, ty + fs_body * 1.5), totals.get("label", "合计"), font=cv.bold, size=fs_body + 0.5, align="c")
        cv.text(
            (xs[0] + label_w, ty, xs[-1] - amount_w, ty + fs_body * 1.5),
            totals.get("chinese", ""),
            size=fs_body,
        )
        cv.text((xs[-1] - amount_w, ty, xs[-1], ty + fs_body * 1.5), totals.get("amount", ""), size=fs_body + 0.5, align="r")
        y += total_h
    return cv, y


def render_document_pdf(spec: dict) -> bytes:
    layout = dict(spec.get("layout") or {})
    # 横向打印（2026-10-25）：宽表单据（对账单等）强制 A4 横版。
    # 等价于前端打印 CSS 的 `@page { size: A4 landscape; margin: 10mm; }`
    # —— 10mm ≈ 28.35pt。模板自带 layout 时以模板为准（setdefault 不覆盖）。
    if str(spec.get("orientation") or "").strip().lower() in ("landscape", "horizontal", "横版"):
        # 宽表单据必须盖掉模板/默认的竖版纸张尺寸，setdefault 会让旧 A4 竖版继续挤列。
        layout["width"] = 841.89
        layout["height"] = 595.28
        for key in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
            layout.setdefault(key, 28.35)
    token = _LAYOUT.set(_merge_layout(layout))
    try:
        return _render(spec)
    finally:
        _LAYOUT.reset(token)


def _render(spec: dict) -> bytes:
    L = _L()
    left, right_x = L["margin_left"], L["width"] - L["margin_right"]
    fs_body, fs_footer = L["font_body"], L["font_footer"]

    doc = fitz.open()
    cv = _new_page(doc)
    bodies: list[str] = [cv.body]
    y = _render_head(cv, spec, L["margin_top"] + 4)

    cv, y = _render_table(doc, cv, spec, y)
    bodies[-1] = cv.body

    width = right_x - left
    bottom_limit = L["height"] - L["margin_bottom"] - FOOTER_H

    # 合计后的追加键值行（右对齐）—— 与明细表之间留一口气，别贴在一起
    y += 4
    for label, value in spec.get("extra_rows") or []:
        h = fs_body * 1.8
        if y + h > bottom_limit:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = L["margin_top"] + 12
        cv.text((right_x - 300, y, right_x, y + h), f"{label}：{value}", size=fs_body + 0.5, align="r")
        y += h

    # 汇总块：一行多格（上标签下数值），浅灰底网格 —— 复刻网页端顶部汇总卡片
    summary = spec.get("summary") or []
    if summary:
        block_h = max(fs_body * 3.8, 34.0)
        if y + block_h + 6 > bottom_limit:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = L["margin_top"] + 12
        y += 6
        n = len(summary)
        w = width / n
        card_fill = _hex_color(spec.get("summary_fill")) or (0.949, 0.965, 0.976)  # #F2F6F9
        cv.rect(left, y, right_x, y + block_h, width=0.0, fill=card_fill, stroke=None)
        cv.rect(left, y, right_x, y + block_h, width=0.6, stroke=(0.7, 0.76, 0.82))
        for i, (k, v) in enumerate(summary):
            x0 = left + i * w
            if i:
                cv.line(x0, y, x0, y + block_h, color=(0.7, 0.76, 0.82))
            cv.text((x0, y + 3, x0 + w, y + block_h / 2), k, size=fs_body, align="c", color=(0.35, 0.42, 0.5))
            is_last = i == n - 1
            cv.text(
                (x0 + 2, y + block_h / 2 - 1, x0 + w - 2, y + block_h - 1),
                _fit(v, w - 6, fs_body + 0.5),
                size=fs_body + 0.5,
                align="c",
                font=cv.bold if is_last else None,
                color=(0.12, 0.3, 0.47) if is_last else (0.06, 0.09, 0.16),
            )
        y += block_h + 8

    # 正文段落（余额确认单 / 合同条款）。
    # 公文段落（2026-10-25）：spec 给 paragraph_style 时按标准公文排版 ——
    #   两端对齐（justify）+ 1.5 倍行距 + 首行缩进两个全角字符；
    # 不给时保持旧样式，其他单据一行不变。
    pstyle = spec.get("paragraph_style") or {}
    for para in spec.get("paragraphs") or []:
        p_size = float(pstyle.get("size") or fs_body + 1)
        p_lh = float(pstyle.get("lineheight") or 1.2)
        body_text = str(para)
        if pstyle.get("indent"):
            body_text = "　　" + body_text  # 首行缩进 2 字符（全角空格）
        per_line = max(1, int(width / p_size))
        lines = 0
        for seg in body_text.split("\n"):
            lines += max(1, math.ceil(len(seg) / per_line)) if seg else 1
        h = lines * p_size * 1.2 * p_lh + 6
        if y + h > bottom_limit:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = L["margin_top"] + 12
        cv.page.insert_textbox(
            fitz.Rect(left, y, right_x, y + h + 4),
            body_text,
            fontname=cv.body,
            fontsize=p_size,
            align=_ALIGN["j"] if pstyle.get("justify") else _ALIGN["l"],
            lineheight=p_lh,
        )
        y += h

    # 备注
    for note in spec.get("notes") or []:
        h = _para_height(note, width, size=fs_body)
        if y + h > bottom_limit:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = L["margin_top"] + 12
        cv.text((left, y, right_x, y + h), note, size=max(6.0, fs_body - 0.5))
        y += h

    # 签章栏。两种形态：
    #   spec["sign_grid"] = 标准公文签章网格（两列 = 甲乙方，含开户行/账号/盖章处，
    #     含"盖章"字样的行自动加高留给印章）—— 合同用；
    #   spec["signatures"] = 旧的"谁签字：＿＿＿"横排 —— 其他单据沿用。
    grid = spec.get("sign_grid") or []
    sigs = spec.get("signatures") or []
    if grid:
        n_cols = max(len(row) for row in grid)
        col_w = width / n_cols
        base_h = max(fs_body * 2.2, 20.0)
        for row in grid:
            row_h = base_h * 1.8 if any("盖章" in str(cell) for cell in row) else base_h
            if y + row_h > bottom_limit:
                cv = _new_page(doc)
                bodies.append(cv.body)
                y = L["margin_top"] + 12
            for i, cell in enumerate(row):
                x0 = left + i * col_w
                cv.rect(x0, y, x0 + col_w, y + row_h, width=0.6, stroke=(0.72, 0.76, 0.82))
                cv.text(
                    (x0 + 6, y + 5, x0 + col_w - 6, y + row_h - 3),
                    _fit(cell, col_w - 12, fs_body),
                    size=fs_body,
                    font=cv.bold if ("：" not in str(cell) and "（盖章）" in str(cell)) else None,
                )
            y += row_h
        y += 10
    elif sigs:
        sig_h = max(fs_body * 1.6, 14.0)
        if y + sig_h + 14 > bottom_limit:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = L["margin_top"] + 12
        y += 14
        slot = width / len(sigs)
        for i, s in enumerate(sigs):
            cv.text((left + i * slot, y, left + (i + 1) * slot, y + sig_h), f"{s}：＿＿＿＿＿＿＿＿", size=fs_body + 0.5)
        y += sig_h + 6

    # 页脚页码（渲染完才知道总页数）。
    # 系统参数 print.footer_text 非空时，自定义文案靠左、页码靠右；
    # 否则维持原来的"页码居中"。
    footer_text = str(spec.get("footer_text") or "").strip()
    footer_h = max(fs_footer * 1.8, 14.0)
    fy0 = L["height"] - max(footer_h + 6, L["margin_bottom"] / 2 + 4)
    fy1 = fy0 + footer_h
    total = doc.page_count
    for i in range(total):
        font = bodies[i] if i < len(bodies) else "china-s"
        if footer_text:
            doc[i].insert_textbox(
                fitz.Rect(left, fy0, right_x - 90, fy1),
                footer_text,
                fontname=font,
                fontsize=fs_footer,
                align=0,
            )
            doc[i].insert_textbox(
                fitz.Rect(right_x - 90, fy0, right_x, fy1),
                f"第 {i + 1} 页 / 共 {total} 页",
                fontname=font,
                fontsize=fs_footer,
                align=2,
            )
        else:
            doc[i].insert_textbox(
                fitz.Rect(left, fy0, right_x, fy1),
                f"第 {i + 1} 页 / 共 {total} 页",
                fontname=font,
                fontsize=fs_footer,
                align=1,
            )

    doc.subset_fonts()
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return bytes(data)
