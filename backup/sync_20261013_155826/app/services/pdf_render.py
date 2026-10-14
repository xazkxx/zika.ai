"""通用单据 PDF 渲染器（pymupdf 手工排版）。

供 /api/v1/print/* 接口使用。中文字体优先嵌入系统宋体/黑体并子集化，
找不到时回退 pymupdf 内置 CJK 字体。

spec 结构（字段全部可选，按需给）：
{
    "company": "抬头公司名称",
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
}
"""
from __future__ import annotations

import math
import os

import pymupdf as fitz

A4_W, A4_H = 595.28, 841.89
MARGIN = 40.0
FOOTER_H = 26.0

_ALIGN = {"l": 0, "c": 1, "r": 2}

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

    def text(self, box, s, font=None, size=9.0, align="l", color=(0, 0, 0)):
        x0, y0, x1, y1 = box
        self.page.insert_textbox(
            fitz.Rect(x0, y0, x1, y1),
            str(s),
            fontname=font or self.body,
            fontsize=size,
            align=_ALIGN[align],
            color=color,
        )

    def line(self, x0, y0, x1, y1, width=0.5):
        self.page.draw_line(fitz.Point(x0, y0), fitz.Point(x1, y1), color=(0, 0, 0), width=width)

    def rect(self, x0, y0, x1, y1, width=0.5):
        self.page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=width)


def _new_page(doc: fitz.Document) -> Canvas:
    return Canvas(doc.new_page(width=A4_W, height=A4_H))


def _fmt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:,.2f}"
    if isinstance(val, int) and not isinstance(val, bool):
        return f"{val:,}"
    return str(val)


def _normalize_columns(columns: list[dict]) -> list[dict]:
    """列宽归一化到可用页宽。"""
    avail = A4_W - 2 * MARGIN
    total = sum(float(c.get("width", 60)) for c in columns) or 1.0
    out = []
    for c in columns:
        out.append(
            {
                "label": c.get("label", ""),
                "width": float(c.get("width", 60)) * avail / total,
                "align": c.get("align", "l"),
            }
        )
    return out


def _para_height(text: str, width: float, size: float = 10.0) -> float:
    """估算段落高度。支持 ``\n`` 硬换行 —— 合同条款是分条分行写的。"""
    per = max(1, int(width / size))
    lines = 0
    for seg in str(text).split("\n"):
        lines += max(1, math.ceil(len(seg) / per)) if seg else 1
    return lines * size * 1.55 + 4


def _render_head(cv: Canvas, spec: dict, y: float) -> float:
    if spec.get("company"):
        cv.text((MARGIN, y, A4_W - MARGIN, y + 14), spec["company"], font=cv.bold, size=10.5, align="c")
        y += 16
    if spec.get("title"):
        cv.text((MARGIN, y, A4_W - MARGIN, y + 26), spec["title"], font=cv.bold, size=17, align="c")
        y += 31
    if spec.get("subtitle"):
        cv.text((MARGIN, y, A4_W - MARGIN, y + 14), spec["subtitle"], size=9.5, align="c")
        y += 16

    right_parts = []
    if spec.get("period"):
        right_parts.append(str(spec["period"]))
    if spec.get("doc_no"):
        right_parts.append(f"单号：{spec['doc_no']}")
    if right_parts:
        cv.text((A4_W - MARGIN - 340, y, A4_W - MARGIN, y + 13), "    ".join(right_parts), size=9, align="r")
        y += 17

    left = spec.get("header_left") or []
    right = spec.get("header_right") or []
    if left or right:
        n = max(len(left), len(right))
        row_h, lab_w = 18.0, 70.0
        half = (A4_W - 2 * MARGIN) / 2 - 8
        lx0, rx0 = MARGIN, MARGIN + half + 16
        top = y
        for i in range(n):
            yy = top + i * row_h
            if i < len(left):
                cv.rect(lx0, yy, lx0 + lab_w, yy + row_h)
                cv.rect(lx0 + lab_w, yy, lx0 + half, yy + row_h)
                cv.text((lx0, yy, lx0 + lab_w, yy + row_h), left[i][0], size=9, align="c")
                cv.text(
                    (lx0 + lab_w + 3, yy, lx0 + half, yy + row_h),
                    _fit(left[i][1], half - lab_w - 8, 9),
                )
            if i < len(right):
                cv.rect(rx0, yy, rx0 + lab_w, yy + row_h)
                cv.rect(rx0 + lab_w, yy, rx0 + half, yy + row_h)
                cv.text((rx0, yy, rx0 + lab_w, yy + row_h), right[i][0], size=9, align="c")
                cv.text(
                    (rx0 + lab_w + 3, yy, rx0 + half, yy + row_h),
                    _fit(right[i][1], half - lab_w - 8, 9),
                )
        y = top + n * row_h + 6
    return y


def _render_table(doc: fitz.Document, cv: Canvas, spec: dict, y: float) -> tuple[Canvas, float]:
    columns = _normalize_columns(spec.get("columns") or [])
    if not columns:
        return cv, y
    rows = spec.get("rows") or []
    row_h = float(spec.get("row_height") or 20)
    hdr_h = 22.0
    xs = [MARGIN]
    for c in columns:
        xs.append(xs[-1] + c["width"])

    def draw_header(yy: float) -> float:
        cv.rect(xs[0], yy, xs[-1], yy + hdr_h, width=0.8)
        for i, col in enumerate(columns):
            if i:
                cv.line(xs[i], yy, xs[i], yy + hdr_h)
            cv.text((xs[i], yy, xs[i + 1], yy + hdr_h), col["label"], font=cv.bold, size=9, align="c")
        return yy + hdr_h

    def page_left(yy: float) -> bool:
        return yy + row_h > A4_H - MARGIN - FOOTER_H

    if page_left(y + hdr_h):
        cv = _new_page(doc)
        y = MARGIN + 12
    y = draw_header(y)

    for row in rows:
        if page_left(y):
            cv = _new_page(doc)
            y = MARGIN + 12
            y = draw_header(y)
        cv.rect(xs[0], y, xs[-1], y + row_h, width=0.4)
        for i, col in enumerate(columns):
            if i:
                cv.line(xs[i], y, xs[i], y + row_h)
            cell = _fmt(row[i]) if i < len(row) else ""
            cv.text(
                (xs[i] + 2, y, xs[i + 1] - 2, y + row_h),
                _fit(cell, col["width"] - 6, 8.5),
                size=8.5,
                align=col["align"],
            )
        y += row_h

    totals = spec.get("totals")
    if totals:
        if y + 22 > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            y = MARGIN + 12
            y = draw_header(y)
        cv.rect(xs[0], y, xs[-1], y + 22, width=0.8)
        label_w = min(90.0, xs[1] - xs[0] + (xs[2] - xs[1] if len(xs) > 2 else 0))
        amount_w = min(95.0, xs[-1] - xs[-2])
        cv.text((xs[0], y, xs[0] + label_w, y + 22), totals.get("label", "合计"), font=cv.bold, size=9, align="c")
        cv.text(
            (xs[0] + label_w, y, xs[-1] - amount_w, y + 22),
            totals.get("chinese", ""),
            size=8.5,
        )
        cv.text((xs[-1] - amount_w, y, xs[-1], y + 22), totals.get("amount", ""), size=9, align="r")
        y += 22
    return cv, y


def render_document_pdf(spec: dict) -> bytes:
    doc = fitz.open()
    cv = _new_page(doc)
    bodies: list[str] = [cv.body]
    y = _render_head(cv, spec, MARGIN + 4)

    cv, y = _render_table(doc, cv, spec, y)
    bodies[-1] = cv.body

    width = A4_W - 2 * MARGIN

    # 合计后的追加键值行（右对齐）
    for label, value in spec.get("extra_rows") or []:
        if y + 16 > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = MARGIN + 12
        cv.text((A4_W - MARGIN - 300, y, A4_W - MARGIN, y + 14), f"{label}：{value}", size=9, align="r")
        y += 16

    # 汇总块：一行多格（上标签下数值）
    summary = spec.get("summary") or []
    if summary:
        if y + 40 > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = MARGIN + 12
        y += 6
        n = len(summary)
        w = width / n
        cv.rect(MARGIN, y, A4_W - MARGIN, y + 34, width=0.8)
        for i, (k, v) in enumerate(summary):
            x0 = MARGIN + i * w
            if i:
                cv.line(x0, y, x0, y + 34)
            cv.text((x0, y + 3, x0 + w, y + 17), k, size=8.5, align="c")
            is_last = i == n - 1
            cv.text(
                (x0 + 2, y + 16, x0 + w - 2, y + 33),
                _fit(v, w - 6, 9),
                size=9,
                align="c",
                font=cv.bold if is_last else None,
            )
        y += 42

    # 正文段落（余额确认单）
    for para in spec.get("paragraphs") or []:
        h = _para_height(para, width)
        if y + h > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = MARGIN + 12
        cv.text((MARGIN, y, A4_W - MARGIN, y + h), para, size=10, align="l")
        y += h + 6

    # 备注
    for note in spec.get("notes") or []:
        h = _para_height(note, width, size=8.5)
        if y + h > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = MARGIN + 12
        cv.text((MARGIN, y, A4_W - MARGIN, y + h), note, size=8.5)
        y += h

    # 签名栏
    sigs = spec.get("signatures") or []
    if sigs:
        if y + 34 > A4_H - MARGIN - FOOTER_H:
            cv = _new_page(doc)
            bodies.append(cv.body)
            y = MARGIN + 12
        y += 14
        slot = width / len(sigs)
        for i, s in enumerate(sigs):
            cv.text((MARGIN + i * slot, y, MARGIN + (i + 1) * slot, y + 14), f"{s}：＿＿＿＿＿＿＿＿", size=9)
        y += 20

    # 页脚页码（渲染完才知道总页数）
    total = doc.page_count
    for i in range(total):
        doc[i].insert_textbox(
            fitz.Rect(MARGIN, A4_H - 22, A4_W - MARGIN, A4_H - 8),
            f"第 {i + 1} 页 / 共 {total} 页",
            fontname=bodies[i] if i < len(bodies) else "china-s",
            fontsize=8,
            align=1,
        )

    doc.subset_fonts()
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return bytes(data)
