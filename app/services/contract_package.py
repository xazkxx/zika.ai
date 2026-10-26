"""合同打包：把「系统填好的合同正文」与「用户上传的模板原件」合成一份完整合同。

## 三种模板，三条路径

| 模板类型 | 做法 | 为什么 |
|---|---|---|
| Word (.doc/.docx) | **变量替换**：`{{party_name}}` 之类占位符换成真值，原样返回 .docx | 用户要能继续在 Word 里改；转成 PDF 就改不动了 |
| PDF | **合并**：系统生成的正文在前，模板页在后（PyMuPDF `insert_pdf`） | 不引入额外依赖；模板常常是扫描件，重排会失真 |
| 图片 | **追加页**：把图片按比例铺到 A4 新页 | 扫描件/照片模板最常见的形态 |

## 为什么"正文在前、模板在后"

正文是**系统算出来的**（金额、明细、条款都有据可查），模板是**用户自己的格式**。
放前面，收到文件的人第一眼看到的是对得上的数；模板作为附件性质的补充在后面。

## 没有模板时

直接返回系统按《工矿产品购销合同》范本生成的 PDF —— 与「生成合同正文」预览的是同一份。
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from docx import Document

from app.services.contract_template import build_gongkuang_document, document_to_print_spec
from app.services.pdf_render import render_document_pdf


def _contract_payload(contract, items) -> dict:
    """ORM 合同 → 生成器认的 payload（与 `erp_print._contract_payload_from_db` 同口径）。"""
    return {
        "direction": getattr(contract, "direction", "out"),
        "title": getattr(contract, "title", None),
        "contract_no": getattr(contract, "contract_no", None),
        "sign_date": getattr(contract, "sign_date", None),
        "sign_place": getattr(contract, "sign_place", None),
        "party_name": contract.party_name,
        "party_tax_no": getattr(contract, "party_tax_no", None),
        "party_legal_person": getattr(contract, "party_legal_person", None),
        "party_address": getattr(contract, "party_address", None),
        "party_contact": getattr(contract, "party_contact", None),
        "party_phone": getattr(contract, "party_phone", None),
        "party_bank_name": getattr(contract, "party_bank_name", None),
        "party_bank_account": getattr(contract, "party_bank_account", None),
        "own_name": getattr(contract, "own_name", None),
        "own_tax_no": getattr(contract, "own_tax_no", None),
        "own_legal_person": getattr(contract, "own_legal_person", None),
        "own_address": getattr(contract, "own_address", None),
        "own_contact": getattr(contract, "own_contact", None),
        "own_phone": getattr(contract, "own_phone", None),
        "own_bank_name": getattr(contract, "own_bank_name", None),
        "own_bank_account": getattr(contract, "own_bank_account", None),
        "tax_rate": getattr(contract, "tax_rate", None),
        "is_tax_included": getattr(contract, "is_tax_included", True),
        "payment_terms": getattr(contract, "payment_terms", None),
        "invoice_requirement": getattr(contract, "invoice_requirement", None),
        "quality_standard": getattr(contract, "quality_standard", None),
        "package_standard": getattr(contract, "package_standard", None),
        "delivery_date": getattr(contract, "delivery_date", None),
        "delivery_place": getattr(contract, "delivery_place", None),
        "delivery_method": getattr(contract, "delivery_method", None),
        "freight_bearer": getattr(contract, "freight_bearer", None),
        "inspection_days": getattr(contract, "inspection_days", None),
        "objection_days": getattr(contract, "objection_days", None),
        "penalty_rate": getattr(contract, "penalty_rate", None),
        "dispute_resolution": getattr(contract, "dispute_resolution", None),
        "copies": getattr(contract, "copies", None),
        "items": [
            {
                "product_name": row.product_name,
                "standards": row.standards,
                "unit": row.unit,
                "quantity": float(row.quantity or 0),
                "unit_price": float(row.unit_price or 0),
                "amount": float(row.amount or 0),
                "note": row.note,
            }
            for row in items
        ],
    }


def is_word(filename: str | None) -> bool:
    """是不是 Word 模板（.doc/.docx）。"""
    return str(filename or "").lower().endswith((".doc", ".docx"))


def build_document(contract, items) -> dict:
    payload = _contract_payload(contract, items)
    return build_gongkuang_document(payload, payload["items"])


def render_body_pdf(contract, items) -> bytes:
    """系统生成的合同正文（《工矿产品购销合同》范本）。"""
    return render_document_pdf(document_to_print_spec(build_document(contract, items)))


def merge_pdf_after(body: bytes, template: bytes) -> bytes:
    """把模板 PDF 的页**追加**到正文后面。

    ⚠️ 用 `insert_pdf` 而不是逐页重绘：扫描件模板里有图片、印章、手写批注，
    重绘等于全部丢掉。
    """
    out = fitz.open(stream=body, filetype="pdf")
    try:
        extra = fitz.open(stream=template, filetype="pdf")
        try:
            out.insert_pdf(extra)
        finally:
            extra.close()
        return out.tobytes()
    finally:
        out.close()


def append_image_page(body: bytes, image: bytes) -> bytes:
    """把图片模板作为新的一页追加（等比缩放，居中，A4 竖版）。"""
    out = fitz.open(stream=body, filetype="pdf")
    try:
        width, height = fitz.paper_size("a4")
        page = out.new_page(width=width, height=height)
        margin = 36  # 0.5 inch
        box = fitz.Rect(margin, margin, width - margin, height - margin)
        page.insert_image(box, stream=image, keep_proportion=True)
        return out.tobytes()
    finally:
        out.close()


# Word 模板支持的变量名（模板里写 {{party_name}} 这样即可）
DOCX_VARIABLES = [
    "contract_no",
    "sign_date",
    "sign_place",
    "party_name",
    "party_tax_no",
    "party_legal_person",
    "party_address",
    "party_bank_name",
    "party_bank_account",
    "own_name",
    "own_tax_no",
    "own_legal_person",
    "own_address",
    "own_bank_name",
    "own_bank_account",
    "total_amount",
    "total_chinese",
    "delivery_date",
    "delivery_place",
    "payment_terms",
    "items_table",
]


def _docx_variable_map(document: dict) -> dict[str, str]:
    buyer = document["parties"]["buyer"]
    seller = document["parties"]["seller"]
    totals = document["totals"]
    rows = document["items"]
    items_text = "\n".join(
        f"{row['no']}. {row['product_name']} {row['standards'] or ''} "
        f"{row['quantity']:g}{row['unit'] or ''} × {row['unit_price']:,.2f} = {row['amount']:,.2f}"
        for row in rows
    )
    return {
        "contract_no": document.get("contract_no") or "",
        "sign_date": document.get("sign_date") or "",
        "sign_place": document.get("sign_place") or "",
        "party_name": buyer.get("name") or "",
        "party_tax_no": buyer.get("tax_no") or "",
        "party_legal_person": buyer.get("legal") or "",
        "party_address": buyer.get("address") or "",
        "party_bank_name": buyer.get("bank_name") or "",
        "party_bank_account": buyer.get("bank_account") or "",
        "own_name": seller.get("name") or "",
        "own_tax_no": seller.get("tax_no") or "",
        "own_legal_person": seller.get("legal") or "",
        "own_address": seller.get("address") or "",
        "own_bank_name": seller.get("bank_name") or "",
        "own_bank_account": seller.get("bank_account") or "",
        "total_amount": f"{totals['amount']:,.2f}",
        "total_chinese": totals["chinese"],
        "delivery_date": document.get("delivery_date") or "",
        "delivery_place": document.get("delivery_place") or "",
        "payment_terms": document.get("payment_terms") or "",
        "items_table": items_text,
    }


def _replace_in_paragraph(paragraph, mapping: dict[str, str]) -> None:
    """在一个段落里替换 `{{key}}`。

    ⚠️ 必须**按 run 拼接**处理：Word 会把 `{{party_name}}` 拆成好几个 run
    （拼写检查、字体变化都会切开），直接改 `paragraph.text` 会丢掉所有格式。
    这里的折中：先把整段文本算出来，若含占位符则把第一个 run 设成结果、其余清空 ——
    格式以第一个 run 为准。合同模板里占位符通常在同一格式内，这个取舍够用。
    """
    if "{{" not in paragraph.text:
        return
    text = paragraph.text
    for key, value in mapping.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    if not paragraph.runs:
        paragraph.add_run(text)
        return
    paragraph.runs[0].text = text
    for run in paragraph.runs[1:]:
        run.text = ""


def fill_docx_template(template_bytes: bytes, document: dict) -> tuple[bytes, int]:
    """把数据填进 Word 模板，返回 (新 docx 字节, 替换到的占位符个数)。

    占位符可以是 `{{party_name}}`；也兼容 `｛｛party_name｝｝`（全角括号，中文输入法常见）。
    一个都没替换到时不报错 —— 返回模板副本 + **在模板原件前面**插入一页
    『表单数据汇总页』（客户/金额/明细），保证"带模板也一定带得上数据"，
    而不是悄悄交回一份空白范本。
    """
    mapping = _docx_variable_map(document)
    doc = Document(io.BytesIO(template_bytes))

    replaced = 0
    for paragraph in doc.paragraphs:
        before = paragraph.text
        _replace_in_paragraph(paragraph, mapping)
        if paragraph.text != before:
            replaced += 1
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    before = paragraph.text
                    _replace_in_paragraph(paragraph, mapping)
                    if paragraph.text != before:
                        replaced += 1
    # 全角括号版本：整体文本替换（只在没替换到时兜一次底）
    if replaced == 0:
        for paragraph in doc.paragraphs:
            text = paragraph.text
            for key, value in mapping.items():
                text = text.replace(f"｛｛{key}｝｝", str(value))
            if text != paragraph.text and paragraph.runs:
                paragraph.runs[0].text = text
                for run in paragraph.runs[1:]:
                    run.text = ""
                replaced += 1

    if replaced == 0:
        # 模板里没写占位符：把关键数据做成『表单数据汇总页』**插到模板原件前面**，
        # 而不是附在末尾（2026-10-24 用户要求）—— 这样哪怕模板里一个变量都没有，
        # 打开文件第一页也是对得上的数据，模板原件从第二页开始，而不是"只给一个空壳原件"。
        from docx.enum.text import WD_BREAK

        lines = [
            "表单数据汇总页（系统自动生成）",
            "",
            f"客户（需方）：{mapping['party_name']}",
            f"我方（供方）：{mapping['own_name']}",
            f"合同编号：{mapping['contract_no']}",
            f"签订日期：{mapping['sign_date']}    签订地点：{mapping['sign_place']}",
            f"交货时间：{mapping['delivery_date']}    交货地点：{mapping['delivery_place']}",
            f"付款方式：{mapping['payment_terms']}",
            f"合同总价：¥{mapping['total_amount']}（大写：{mapping['total_chinese']}）",
            "",
            "标的物明细：",
        ]
        lines.extend(mapping["items_table"].splitlines())

        body = doc.element.body
        inserted = [doc.add_paragraph(line) for line in lines]
        page_break = doc.add_paragraph()
        page_break.add_run().add_break(WD_BREAK.PAGE)
        inserted.append(page_break)
        # add_paragraph 是追加到末尾；这里再把这批段落整体搬到正文最前面，
        # 保证模板原件（无论以段落还是表格开头）都从第二页开始。
        for index, para in enumerate(inserted):
            body.insert(index, para._p)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue(), replaced
