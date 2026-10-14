"""发票管理 —— 由原 `erp.py` 按业务域拆分而来
（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。

发票 OCR 识别 / 解析 / 进出项判定 / 原件与二维码 / 同步财务。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import zipfile

from app.core import file_storage
from app.core.company_info import load_company
from app.db.session import get_db
from app.models.finance import FinancialTransaction
from app.models.invoice import (
    DIRECTION_LABELS,
    DIRECTION_UNKNOWN,
    INVOICE_FLAG_LABELS,
    ISSUE_MODE_LABELS,
    Invoice,
    detect_direction,
)
from app.schemas import InvoiceCreate, InvoiceUpdate
from datetime import date, datetime
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pathlib import Path
from sqlalchemy import or_
from sqlalchemy.orm import Session
from urllib import request
from uuid import uuid4

from app.api.v1.routes.erp_common import (
    _attachment_response,
    _paginate,
    _wants_json,
)

router = APIRouter(prefix="", tags=["erp"])


# 导出原件 ZIP 时的目录名（按进销项分文件夹，拿出去一眼能分清）
INVOICE_DIRECTION_DIRS = {
    "input": "进项",
    "output": "销项",
    "unknown": "待判定",
}



# RapidOCR 引擎单例：模型加载较慢，进程内只加载一次
_rapid_engine = None



def _get_rapid_engine():
    global _rapid_engine
    if _rapid_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _rapid_engine = RapidOCR()
    return _rapid_engine



def _classify_invoice_record(item: dict[str, object]) -> str:
    note_text = f"{item.get('note') or ''} {item.get('customer_name') or ''} {item.get('status') or ''}".lower()
    if any(keyword in note_text for keyword in ["采购", "办公", "耗材", "设备", "供应商", "原材料", "材料"]):
        return "采购"
    if any(keyword in note_text for keyword in ["销售", "收入", "客户", "服务", "订单"]):
        return "销售"
    if any(keyword in note_text for keyword in ["交通", "差旅", "出差", "机票", "酒店"]):
        return "差旅"
    if any(keyword in note_text for keyword in ["税", "增值税", "手续费", "银行", "利息"]):
        return "税费"
    return "其他"



def _extract_party(merged: str, start_label: str, end_labels: tuple[str, ...]) -> tuple[str | None, str | None]:
    """截取 购买方/销售方 段落，提取名称与纳税人识别号。"""
    start = merged.find(start_label)
    if start < 0:
        return None, None
    segment = merged[start + len(start_label):]
    for end_label in end_labels:
        idx = segment.find(end_label)
        if idx >= 0:
            segment = segment[:idx]
            break
    name_match = re.search(r"名\s*称[:：]\s*([^\n]{2,40})", segment)
    tax_match = re.search(r"(?:纳税人识别号|税号|统一社会信用代码)[:：]?\s*([0-9A-Za-z]{15,20})", segment)
    name = name_match.group(1).strip() if name_match else None
    tax_no = tax_match.group(1).strip() if tax_match else None
    return name, tax_no



def _split_glued_number(token: str) -> tuple[float, float, float] | None:
    """把被 OCR 粘连的数字串（如 250.00100.00）拆成 数量/单价/金额。"""
    for i in range(1, len(token)):
        for j in range(i + 1, len(token)):
            qty_text, price_text, amount_text = token[:i], token[i:j], token[j:]
            if not all(re.fullmatch(r"\d+(?:\.\d{1,2})?", part) for part in (qty_text, price_text, amount_text)):
                continue
            qty, price, amount = float(qty_text), float(price_text), float(amount_text)
            if amount > 0 and abs(qty * price - amount) <= max(0.05, amount * 0.005):
                return qty, price, amount
    return None



def _parse_item_line(line: str) -> dict[str, object] | None:
    """解析一行明细：品名 + 数量 + 单价 + 金额。

    兼容两种 OCR 输出：
    1. 空格分隔列：*品名* 2 50.00 100.00（数字列前必须有空格，从行尾往前验证）
    2. 数字粘连：*品名*打印纸A4250.00100.00（逐个数字位尝试拆分）
    两种都要求 数量×单价≈金额 成立，避免误判普通行。
    """
    # 空格分隔格式：行末至少一个空格 + 数字列
    spaced = re.search(r"^(.*?)\s+((?:\d[\d,.]*%?)(?:\s+\d[\d,.]*%?)*)\s*$", line)
    if spaced:
        name_raw = spaced.group(1)
        tokens = spaced.group(2).split()
        numeric = [token.replace(",", "") for token in tokens if not token.endswith("%")]
        parsed: tuple[float, float, float] | None = None
        if len(numeric) == 1:
            parsed = _split_glued_number(numeric[0])
        elif len(numeric) >= 3:
            try:
                values = [float(token) for token in numeric]
            except ValueError:
                values = []
            # 从行尾往前找第一个满足 数量×单价≈金额 的相邻三元组
            for idx in range(len(values) - 1, 1, -1):
                qty, price, amount = values[idx - 2], values[idx - 1], values[idx]
                if amount > 0 and abs(qty * price - amount) <= max(0.05, amount * 0.005):
                    parsed = (qty, price, amount)
                    break
        if parsed is None:
            return None
        qty, price, amount = parsed
    else:
        # 数字粘连格式：从每个数字位开始尝试拆分，直到校验成立
        parsed = None
        name_raw = ""
        for digit in re.finditer(r"\d", line):
            split = _split_glued_number(line[digit.start():])
            if split:
                parsed = split
                name_raw = line[:digit.start()]
                break
        if parsed is None:
            return None
        qty, price, amount = parsed

    # 去掉增值税发票明细的 *分类* 前缀（如 *办公用品*打印纸）
    name = re.sub(r"^\*[^*]*\*", "", name_raw).strip(" *\t")
    if not name or len(name) > 40:
        return None

    return {
        "item_name": name,
        "quantity": qty,
        "unit_price": round(price, 2),
        "amount": round(amount, 2),
    }



def _extract_invoice_items(lines: list[str], total_amount: float) -> list[dict[str, object]]:
    """识别明细行，明细合计与发票总额一致才算解析成功。"""
    items: list[dict[str, object]] = []
    for line in lines:
        parsed = _parse_item_line(line)
        if parsed:
            items.append(parsed)
    if items and abs(sum(item["amount"] for item in items) - total_amount) <= max(0.05, total_amount * 0.005):
        return items
    return []



def _infer_invoice_type(text: str) -> str:
    """从发票文本判断类型：专用发票 → 专票，普通发票 → 普票，否则未知。

    数电票文本形如"电子发票（增值税专用发票）"或"电子发票（增值税普通发票）"，
    只写"电子发票"无法判断专普，归为未知。
    """
    if re.search(r"增值税专用发票|专用发票|专用票", text):
        return "专票"
    if re.search(r"增值税普通发票|普通发票|普通票", text):
        return "普票"
    return "未知"



def _extract_dzp_fields(lines: list[str]) -> dict[str, object]:
    """数电票兜底提取：版面是"标签集中在上半部、数值按顺序排在下半部"，
    常规"标签+值"正则匹配不到，这里按数值出现顺序提取。

    典型值序列：发票号 → 开票日期 → 销售方名称 → 销售方税号 →
    购买方名称 → 购买方税号 → 不含税合计¥x → 税额¥y → 价税合计¥z
    """
    # 过滤标签碎片行（购/买/方 等单字行），保留数值行
    fragment_words = {"购", "买", "方", "信", "息", "销", "售", "合", "计", "备", "注"}
    useful: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line in fragment_words:
            continue
        useful.append(line)

    result: dict[str, object] = {}

    # 发票号：首个 8~20 位纯数字行（明细区的小数带小数点会自然排除）
    for line in useful:
        if re.fullmatch(r"\d{8,20}", line):
            result["invoice_no"] = line
            break

    # 日期：XXXX年XX月XX日
    for line in useful:
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", line)
        if match:
            result["date"] = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            break

    # 名称-税号对：税号（15~20 位字母数字）紧邻的前一行含中文即为名称。
    # 数电票值序列里先销售方后购买方：第一对=销售方，第二对=购买方
    parties: list[tuple[str, str]] = []
    for index in range(1, len(useful)):
        line = useful[index]
        if not re.fullmatch(r"[0-9A-Z]{15,20}", line):
            continue
        # 已识别为发票号的行不是税号；"开票人"行是标签不是公司名
        if line == result.get("invoice_no") or "开票人" in useful[index - 1]:
            continue
        prev = re.sub(r"^(?:名称|项目名称|购买方名称|销售方名称)\s*[:：]?\s*", "", useful[index - 1])
        if re.search(r"[一-鿿]", prev):
            parties.append((prev, line))
    if len(parties) >= 1:
        result["seller_name"], result["seller_tax_no"] = parties[0]
    if len(parties) >= 2:
        result["buyer_name"], result["buyer_tax_no"] = parties[1]

    # 金额：¥/￥ 开头的行，最后三个依次是 不含税合计 / 税额 / 价税合计
    money: list[float] = []
    for line in useful:
        match = re.match(r"^[¥￥]\s*([0-9,]+\.?\d*)", line)
        if match:
            money.append(float(match.group(1).replace(",", "")))
    if len(money) >= 3:
        result["excl_tax_amount"] = round(money[-3], 2)
        result["tax_amount"] = round(money[-2], 2)
        result["total_amount"] = round(money[-1], 2)

    # 税率：首个 "n%" 行
    for line in useful:
        match = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)%", line)
        if match:
            result["tax_rate"] = float(match.group(1))
            break

    return result



def _extract_invoice_summary(lines: list[str]) -> dict[str, object]:
    merged = "\n".join(lines)
    # 清洗版：去掉所有空白（空格/换行/制表符），并把全角数字/冒号/括号/￥ 转半角，
    # 让"金\n额"、全角冒号、全半角混用这类 PDF/OCR 干扰都能匹配到
    clean = re.sub(r"\s+", "", merged).translate(
        str.maketrans("０１２３４５６７８９：（）￥", "0123456789:()¥")
    )
    # 发票号（清洗后 "Invoice No" 会变成 "InvoiceNo"，两种写法都兼容）
    invoice_match = re.search(
        r"(?:发票号码|发票编号|票号|InvoiceNo\.?|№|No\.)\s*[:：]?\s*([0-9A-Za-z-]{6,24})",
        clean,
        re.I,
    )
    # 日期（"开票日期/开具日期/发票日期"任一关键词 + 8 位数字或带连字符日期）
    date_match = re.search(
        r"(?:开票日期|开具日期|发票日期|日期|Date)\s*[:：]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{8})",
        clean,
        re.I,
    )
    # 金额：优先取"（小写）"后的数字（发票常写"价税合计(大写)￥123.45(小写)￥123.45"，
    # 大写写的是汉字数字无法直接转浮点）；否则取金额关键词后的第一个数字
    amount_match = re.search(r"[\(（]小写[\)）]\s*[:：]?\s*[¥￥]?\s*([0-9,]+\.?[0-9]*)", clean)
    if amount_match is None:
        amount_match = re.search(
            r"(?:价税合计|金额合计|合计金额|总金额|Amount|Total|￥|¥)\s*[:：]?\s*([0-9,]+\.?[0-9]*)",
            clean,
            re.I,
        )

    invoice_no = invoice_match.group(1).strip() if invoice_match else f"INV-{uuid4().hex[:8].upper()}"
    invoice_date = date_match.group(1).strip() if date_match else None
    total_amount = float(str(amount_match.group(1)).replace(",", "")) if amount_match else 0.0

    buyer_name, buyer_tax_no = _extract_party(merged, "购买方", ("销售方", "价税合计", "密码区"))
    seller_name, seller_tax_no = _extract_party(merged, "销售方", ("价税合计", "备注", "收款人", "开票人", "复核"))

    # 发票类型：专用发票 → 专票，普通发票 → 普票
    invoice_type = _infer_invoice_type(merged)

    # 发票代码
    invoice_code = None
    code_match = re.search(r"发票代码\s*[:：]?\s*([0-9A-Za-z-]{8,24})", merged)
    if code_match:
        invoice_code = code_match.group(1).strip()

    # 税额：只匹配以"税额/税金"开头的行（避免误吞"价税合计"“不含税额”）
    tax_amount = None
    tax_match = re.search(r"^税(?:额|金)(?:合计)?\s*[:：]?\s*([0-9,]+\.?\d*)", merged, re.M)
    if tax_match:
        tax_amount = round(float(tax_match.group(1).replace(",", "")), 2)

    # 税率
    tax_rate = None
    rate_match = re.search(r"(?:税率|征收率)\s*[:：]?\s*(\d{1,2}(?:\.\d+)?)\s*%", merged)
    if rate_match:
        tax_rate = float(rate_match.group(1))

    # 不含税额：优先用 合计-税额；缺税额时按税率反推
    excl_tax_amount = None
    if tax_amount is not None:
        excl_tax_amount = round(total_amount - tax_amount, 2)
    elif tax_rate is not None and total_amount > 0:
        excl_tax_amount = round(total_amount / (1 + tax_rate / 100), 2)
        tax_amount = round(total_amount - excl_tax_amount, 2)

    items = _extract_invoice_items(lines, total_amount)

    # 数电票兜底：标签与数值分离的版面常规正则匹配不到，
    # 按数值出现顺序提取，只补当前仍缺失的字段（不覆盖已有结果）
    dzp = _extract_dzp_fields(lines)
    if invoice_no.startswith("INV-"):
        invoice_no = dzp.get("invoice_no") or invoice_no
    if invoice_date is None:
        invoice_date = dzp.get("date") or date.today().isoformat()
    if total_amount == 0.0 and dzp.get("total_amount"):
        total_amount = float(dzp["total_amount"])
    if buyer_name is None:
        buyer_name = dzp.get("buyer_name")
    if buyer_tax_no is None:
        buyer_tax_no = dzp.get("buyer_tax_no")
    if seller_name is None:
        seller_name = dzp.get("seller_name")
    if seller_tax_no is None:
        seller_tax_no = dzp.get("seller_tax_no")
    if tax_amount is None:
        tax_amount = dzp.get("tax_amount")
    if tax_rate is None:
        tax_rate = dzp.get("tax_rate")
    if excl_tax_amount is None:
        excl_tax_amount = dzp.get("excl_tax_amount")
        if excl_tax_amount is None and tax_amount is not None and total_amount > 0:
            excl_tax_amount = round(total_amount - float(tax_amount), 2)

    return {
        "invoice_no": invoice_no,
        "invoice_date": invoice_date,
        "total_amount": round(total_amount, 2),
        "invoice_type": invoice_type,
        "invoice_code": invoice_code,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "excl_tax_amount": excl_tax_amount,
        "buyer_name": buyer_name,
        "buyer_tax_no": buyer_tax_no,
        "seller_name": seller_name,
        "seller_tax_no": seller_tax_no,
        "raw_text": merged,
        "items": items
        or ([
            {
                "invoice_no": invoice_no,
                "item_name": "发票扫描结果",
                "quantity": 1,
                "unit_price": round(total_amount, 2),
                "amount": round(total_amount, 2),
            }
        ] if total_amount else []),
    }



def _decode_qrcode(payload: bytes) -> str | None:
    """用 OpenCV 识别图片中的二维码（免 pyzbar 额外依赖）。"""
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    detector = cv2.QRCodeDetector()
    text, _, _ = detector.detectAndDecode(image)
    return text.strip() if text else None



def _extract_qr_fields(text: str) -> dict[str, object]:
    """从二维码内容提取发票号/金额/日期。

    兼容两种常见格式：
    1. 数电票查验 URL（http...?fphm=...&je=...&kprq=...）
    2. 老式税控二维码（逗号分隔：01,10,发票代码,发票号码,金额,开票日期,...）
    """
    invoice_no: str | None = None
    total_amount: float | None = None
    date_text: str | None = None

    if text.lower().startswith(("http://", "https://")):
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(text).query)
        for key in ("fphm", "invoiceNo", "invoice_no", "fpnumber", "number"):
            if params.get(key):
                invoice_no = str(params[key][0]).strip()
                break
        for key in ("je", "amount", "total", "totalAmount", "money"):
            if params.get(key):
                try:
                    total_amount = float(str(params[key][0]).replace(",", ""))
                    break
                except ValueError:
                    pass
        for key in ("kprq", "date", "issueDate", "invoiceDate"):
            if params.get(key):
                date_text = str(params[key][0]).strip()
                break
        # 无查询参数的数电票直链（如陕西 dppt 平台）：.../v/2_发票号_日期时间+校验码
        if invoice_no is None or date_text is None:
            path_match = re.search(r"[_/](\d{8,20})_(\d{8})\d{6}", text)
            if path_match:
                if invoice_no is None:
                    invoice_no = path_match.group(1)
                if date_text is None:
                    date_text = path_match.group(2)
    else:
        # 注意：不能过滤空段！税控码如 "01,31,,发票号,金额,日期,,校验码" 中
        # 空段（发票代码位置）有含义，过滤后第 4/5/6 段会整体错位
        parts = [part.strip() for part in text.split(",")]
        # 老式税控二维码固定结构：第 4 段=发票号码，第 5 段=金额，第 6 段=开票日期
        if len(parts) >= 6 and re.fullmatch(r"\d{8,20}", parts[3]):
            invoice_no = parts[3]
            try:
                total_amount = float(parts[4])
            except ValueError:
                pass
            date_text = parts[5]
        else:
            # 启发式兜底：长数字串=发票号、带小数的数字=金额、8 位数字=日期
            numbers = [part for part in parts if re.fullmatch(r"\d{8,20}", part)]
            if numbers:
                # 发票号一般是段里最长的数字（20 位数电票号），8 位串多为日期
                invoice_no = max(numbers, key=len)
            for part in parts:
                if total_amount is None and re.fullmatch(r"\d+(?:\.\d{1,2})?", part) and "." in part:
                    total_amount = float(part)
                elif date_text is None and re.fullmatch(r"\d{8}", part):
                    date_text = part

    # 日期统一成 YYYY-MM-DD（8 位数字如 20260924 → 2026-09-24）
    normalized_date: str | None = None
    if date_text:
        digits = re.sub(r"\D", "", date_text)
        if re.fullmatch(r"\d{8}", digits):
            normalized_date = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
        else:
            normalized_date = date_text

    return {
        "invoice_no": invoice_no,
        "total_amount": total_amount,
        "date": normalized_date,
    }



def _pdf_page_pngs(payload: bytes, dpi: int = 200, zoom: float | None = None) -> list[bytes]:
    """把 PDF 每页渲染成 PNG 图片字节（供二维码检测和 OCR 使用）。

    zoom 非空时用 fitz.Matrix(zoom, zoom) 放大渲染（扫描件 OCR 用 3 倍 ≈ 300 DPI，
    小字更清晰识别率更高）；否则按 dpi 渲染（二维码检测 200 DPI 已够且更快）。
    """
    import fitz

    pages: list[bytes] = []
    with fitz.open(stream=payload, filetype="pdf") as doc:
        for page in doc:
            if zoom is not None:
                pages.append(page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png"))
            else:
                pages.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    return pages



def _pdf_text_layer(payload: bytes) -> str:
    """提取 PDF 内嵌文本层（原生 PDF 发票可直接读到文字）。"""
    import fitz

    with fitz.open(stream=payload, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)



def _ocr_image_bytes(payload: bytes) -> tuple[str, list[str]]:
    """对单张图片字节做 OCR，返回 (引擎名, 文本行列表)。"""
    temp_dir = Path(tempfile.gettempdir()) / "erp_invoice_ocr"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / f"{uuid4()}.png"
    target_path.write_bytes(payload)

    lines: list[str] = []
    try:
        ocr_result, _ = _get_rapid_engine()(str(target_path))
        if ocr_result:
            for item in ocr_result:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                    text = str(item[1]).strip()
                    if text:
                        lines.append(text)
            if lines:
                return "rapidocr", lines
    except Exception:
        pass

    try:
        from paddleocr import PaddleOCR

        paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        paddle_result = paddle_ocr.ocr(str(target_path), cls=True)
        if paddle_result:
            for line in paddle_result[0]:
                if isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                    text = str(line[1][0]).strip()
                    if text:
                        lines.append(text)
                elif isinstance(line, str):
                    lines.append(line)
            if lines:
                return "paddleocr", lines
    except Exception:
        pass

    return "fallback", lines



def _parse_invoice_pipeline(payload: bytes, filename: str) -> dict[str, object]:
    """统一混合解析流水线：第一关二维码 → 第二关 PDF 文本层 → 第三关 OCR 兜底。"""
    extension = Path(filename).suffix.lower()
    is_pdf = extension == ".pdf"
    provider = "fallback"
    summary: dict[str, object] | None = None
    qr_fields: dict[str, object] | None = None

    # ---- 第一关：二维码拦截（最高优先级）----
    try:
        qr_text: str | None = None
        if is_pdf:
            for page_png in _pdf_page_pngs(payload):
                qr_text = _decode_qrcode(page_png)
                if qr_text:
                    break
            # 200 DPI 扫不到时放大 3 倍重扫，小二维码也能命中
            if not qr_text:
                for page_png in _pdf_page_pngs(payload, zoom=3):
                    qr_text = _decode_qrcode(page_png)
                    if qr_text:
                        break
        else:
            qr_text = _decode_qrcode(payload)
        if qr_text:
            qr_fields = _extract_qr_fields(qr_text)
            fields = qr_fields
            # 发票号和金额都提取到才拦截；只有发票号没有金额时交给后续关卡，
            # 避免金额为 0 的脏数据进入发票汇总
            if fields.get("invoice_no") and fields.get("total_amount"):
                provider = "qrcode"
                total = fields["total_amount"]
                total = round(float(total), 2) if total is not None else 0.0
                invoice_no = str(fields["invoice_no"] or f"INV-{uuid4().hex[:8].upper()}")
                summary = {
                    "invoice_no": invoice_no,
                    "invoice_date": fields["date"] or date.today().isoformat(),
                    "total_amount": total,
                    "invoice_type": "未知",
                    "invoice_code": None,
                    "tax_rate": None,
                    "tax_amount": None,
                    "excl_tax_amount": None,
                    "buyer_name": None,
                    "buyer_tax_no": None,
                    "seller_name": None,
                    "seller_tax_no": None,
                    "raw_text": qr_text,
                    "items": [
                        {
                            "invoice_no": invoice_no,
                            "item_name": "二维码解析结果",
                            "quantity": 1,
                            "unit_price": total,
                            "amount": total,
                        }
                    ]
                    if total
                    else [],
                }
                # 二维码里没有发票类型：PDF 顺带读文本层判断专票/普票
                if is_pdf:
                    try:
                        summary["invoice_type"] = _infer_invoice_type(_pdf_text_layer(payload))
                    except Exception:
                        pass
                # 二维码里没有税率/税额/明细/买卖双方：从文本层或 OCR 补充这些字段
                # （发票号/金额/日期仍以二维码为准，绝不覆盖）
                try:
                    extra_lines: list[str] = []
                    if is_pdf:
                        text = _pdf_text_layer(payload)
                        if len(text.strip()) > 20:
                            extra_lines = [line.strip() for line in text.splitlines() if line.strip()]
                        else:
                            for page_png in _pdf_page_pngs(payload, zoom=3):
                                _, page_lines = _ocr_image_bytes(page_png)
                                extra_lines.extend(page_lines)
                    else:
                        _, extra_lines = _ocr_image_bytes(payload)
                    if extra_lines:
                        extra = _extract_invoice_summary(extra_lines)
                        if summary["invoice_type"] in (None, "未知"):
                            summary["invoice_type"] = extra.get("invoice_type") or "未知"
                        for key in (
                            "invoice_code",
                            "tax_rate",
                            "tax_amount",
                            "buyer_name",
                            "buyer_tax_no",
                            "seller_name",
                            "seller_tax_no",
                        ):
                            if summary.get(key) is None:
                                summary[key] = extra.get(key)
                        # 不含税额：用二维码金额与补充的税额/税率重算，保证口径一致
                        if summary["tax_amount"] is not None:
                            summary["excl_tax_amount"] = round(
                                float(summary["total_amount"]) - float(summary["tax_amount"]), 2
                            )
                        elif summary["tax_rate"] is not None and summary["total_amount"]:
                            summary["excl_tax_amount"] = round(
                                float(summary["total_amount"]) / (1 + float(summary["tax_rate"]) / 100), 2
                            )
                        # 明细：文本层/OCR 提取到的替换二维码占位，发票号统一用二维码的
                        if extra.get("items"):
                            enriched = [{**line, "invoice_no": summary["invoice_no"]} for line in extra["items"]]
                            # 只有单条占位明细（未提取到真实明细）时，金额统一用二维码金额
                            if len(enriched) == 1 and "扫描结果" in str(enriched[0].get("item_name", "")):
                                enriched[0]["unit_price"] = summary["total_amount"]
                                enriched[0]["amount"] = summary["total_amount"]
                            summary["items"] = enriched
                except Exception:
                    pass
    except Exception:
        pass

    # ---- 第二关：PDF 文本层提取（原生 PDF）----
    # 智能分流：文本层字符数 > 20 才是原生 PDF，直接走正则；
    # 提取不到文字（或字数极少）视为扫描件，交给第三关 OCR
    if summary is None and is_pdf:
        try:
            text = _pdf_text_layer(payload)
            if len(text.strip()) > 20:
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                candidate = _extract_invoice_summary(lines)
                # 真实提取到发票号（非占位）或金额才算成功，否则交给下一关
                if not str(candidate["invoice_no"]).startswith("INV-") or candidate["total_amount"]:
                    provider = "pdf_text"
                    summary = candidate
        except Exception:
            pass

    # ---- 第三关：OCR 兜底（普通图片 / 扫描件 PDF）----
    # 扫描件 PDF 用 3 倍放大渲染（Matrix(3,3) ≈ 300 DPI）再送 OCR
    if summary is None:
        try:
            ocr_lines: list[str] = []
            engine = "fallback"
            if is_pdf:
                for page_png in _pdf_page_pngs(payload, zoom=3):
                    page_engine, page_lines = _ocr_image_bytes(page_png)
                    ocr_lines.extend(page_lines)
                    if page_engine != "fallback":
                        engine = page_engine
            else:
                engine, ocr_lines = _ocr_image_bytes(payload)
            provider = engine
            if ocr_lines:
                summary = _extract_invoice_summary(ocr_lines)
        except Exception:
            pass

    if summary is None:
        summary = {
            "invoice_no": f"INV-{uuid4().hex[:8].upper()}",
            "invoice_date": date.today().isoformat(),
            "total_amount": 0.0,
            "invoice_type": "未知",
            "invoice_code": None,
            "tax_rate": None,
            "tax_amount": None,
            "excl_tax_amount": None,
            "buyer_name": None,
            "buyer_tax_no": None,
            "seller_name": None,
            "seller_tax_no": None,
            "raw_text": f"发票文件：{filename}",
            "items": [],
        }

    # 二维码是机器编码数据，优先级高于 OCR 文字提取：第一关没拦截时，
    # 二维码里有值的字段无条件覆盖 OCR/文本层结果（包括 OCR 读错的发票号）
    if qr_fields and provider != "qrcode":
        if qr_fields.get("invoice_no"):
            summary["invoice_no"] = qr_fields["invoice_no"]
        if qr_fields.get("total_amount"):
            summary["total_amount"] = round(float(qr_fields["total_amount"]), 2)
        if qr_fields.get("date"):
            summary["invoice_date"] = qr_fields["date"]

    # ---- 第 12 批：按版式坐标补买卖方与明细 ----
    #
    # 为什么必须有这一步：数电票导出的 PDF 里，**标签块与值块是分离的**
    # （标签块有「名称：」但后面没值，值在另一个文本块里）。上面那套
    # "标签后紧跟值"的正则**永远匹配不到**，只能靠兜底猜 ——
    # 实测把购买方/销售方**整体搞反了**，而进销项判定正靠这两个字段，错了看不出来。
    #
    # 所以这里用**坐标**再读一遍：竖排单字定位左右栏 → 就近归列读明细。
    # 读到的字段**覆盖**上面的猜测结果（坐标是版式的客观事实，比猜准）。
    if is_pdf:
        try:
            from app.services.invoice_layout import extract_by_layout

            layout = extract_by_layout(payload)
        except Exception:
            layout = {}
        if layout:
            for key in ("buyer_name", "buyer_tax_no", "seller_name", "seller_tax_no"):
                if layout.get(key):
                    summary[key] = layout[key]
            if layout.get("items"):
                summary["items"] = layout["items"]
            # 自校验告警一路带到前端，让用户知道"这一张有对不上的地方"
            if layout.get("warnings"):
                summary["warnings"] = layout["warnings"]
            summary["layout_parsed"] = True

    summary["provider"] = provider
    summary["filename"] = filename
    summary["file_type"] = extension
    # 统一字段名 date（与 invoice_date 同义），便于调用方直接取用
    summary["date"] = summary["invoice_date"]
    return summary



@router.post("/invoices/parse")
async def parse_invoice_file(file: UploadFile = File(...)) -> dict[str, object]:
    """统一发票解析接口：支持图片（png/jpg/jpeg）与 PDF，走二维码→文本层→OCR 流水线。"""
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    filename = file.filename or "invoice"
    return _parse_invoice_pipeline(payload, filename)



@router.post("/invoices/ocr")
async def local_invoice_ocr(file: UploadFile = File(...)) -> dict[str, object]:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_name = file.filename or "invoice.png"
    extension = Path(file_name).suffix.lower()
    temp_dir = Path(tempfile.gettempdir()) / "erp_invoice_ocr"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / f"{uuid4()}-{file_name}"
    target_path.write_bytes(payload)

    provider = "fallback"
    lines: list[str] = []

    # 首选：RapidOCR（纯本地、免额外引擎、内置中文模型）
    try:
        ocr_result, _ = _get_rapid_engine()(str(target_path))
        if ocr_result:
            provider = "rapidocr"
            for item in ocr_result:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                    text = str(item[1]).strip()
                    if text:
                        lines.append(text)
    except Exception:
        lines = []

    # 备选：PaddleOCR（需另装 paddlepaddle 引擎）
    if not lines:
        try:
            from paddleocr import PaddleOCR

            paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            paddle_result = paddle_ocr.ocr(str(target_path), cls=True)
            if paddle_result:
                provider = "paddleocr"
                for line in paddle_result[0]:
                    if isinstance(line, (list, tuple)) and len(line) >= 2 and isinstance(line[1], (list, tuple)):
                        text = str(line[1][0]).strip()
                        if text:
                            lines.append(text)
                    elif isinstance(line, str):
                        lines.append(line)
        except Exception:
            pass

    if not lines:
        lines = [f"发票文件：{file_name}", "未能识别出文字：请确认图片清晰、内容为印刷体，并检查本地 OCR 引擎依赖。"]

    summary = _extract_invoice_summary(lines)
    summary["provider"] = provider
    summary["filename"] = file_name
    summary["file_type"] = extension
    return summary



def _invoice_to_dict(item: Invoice) -> dict[str, object]:
    """发票 → 前端结构。

    `has_source` 是**算出来的**而不是拿 `source_path` 直接当真：库里的路径可能指向
    一个已经被删掉的文件（手工清理过 data 目录、或从别的机器拷来的库）。
    界面按它决定"下载原件"按钮能不能点，所以必须反映磁盘实况。
    """
    return {
        "id": item.id,
        "invoice_no": item.invoice_no,
        "invoice_type": item.invoice_type,
        "issue_date": item.issue_date,
        "counterparty_name": item.counterparty_name,
        "invoice_code": item.invoice_code,
        "total_amount": float(item.total_amount or 0),
        "tax_rate": item.tax_rate,
        "tax_amount": item.tax_amount,
        "excl_tax_amount": item.excl_tax_amount,
        "deducted": bool(item.deducted),
        "category": item.category,
        "status": item.status,
        "buyer_name": item.buyer_name,
        "buyer_tax_no": item.buyer_tax_no,
        "seller_name": item.seller_name,
        "seller_tax_no": item.seller_tax_no,
        "items": item.items,
        "raw_text": item.raw_text,
        # 第 11 批：业务属性
        "direction": item.direction or DIRECTION_UNKNOWN,
        "direction_label": DIRECTION_LABELS.get(item.direction or DIRECTION_UNKNOWN, "待判定"),
        "invoice_flag": item.invoice_flag or "blue",
        "invoice_flag_label": INVOICE_FLAG_LABELS.get(item.invoice_flag or "blue", "蓝字"),
        "issue_mode": item.issue_mode or "manual",
        "issue_mode_label": ISSUE_MODE_LABELS.get(item.issue_mode or "manual", "手工开票"),
        "handler": item.handler,
        # 原件
        "source_name": item.source_name,
        "source_size": item.source_size,
        "source_mime": item.source_mime,
        "has_source": bool(item.source_path),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }



@router.post("/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    """保存发票。按发票号码去重：重复上传时删除旧记录，用新解析结果替换。

    `direction` 没传就**自动判定**（按本公司抬头比对买卖方，见 `detect_direction`）；
    判不出来留 `unknown`，界面显示「待判定」，用户可以手工改或稍后一键重判。
    """
    existing = db.query(Invoice).filter(Invoice.invoice_no == payload.invoice_no).first()
    if existing is not None:
        # 替换记录时把旧原件一并删掉，否则 data 目录里会越堆越多"没人认领"的文件
        file_storage.delete_file(existing.source_path)
        # 同步出来的财务流水同样要清：票据被替换了，旧流水就是孤儿
        _purge_invoice_finance(db, [existing.invoice_no])
        db.delete(existing)
        db.commit()

    data = payload.model_dump()
    items = data.pop("items", []) or []
    incoming_direction = (data.pop("direction", None) or "").strip()
    company = load_company()
    direction = incoming_direction or detect_direction(
        own_tax_no=company.get("own_tax_no"),
        own_name=company.get("own_name"),
        seller_tax_no=payload.seller_tax_no,
        seller_name=payload.seller_name,
        buyer_tax_no=payload.buyer_tax_no,
        buyer_name=payload.buyer_name,
    )
    if direction not in DIRECTION_LABELS:
        raise HTTPException(status_code=400, detail="发票方向只能是 进项 / 销项 / 待判定")
    invoice_flag = data.pop("invoice_flag", "blue") or "blue"
    if invoice_flag not in INVOICE_FLAG_LABELS:
        raise HTTPException(status_code=400, detail="红蓝字只能是 蓝字 / 红字")
    issue_mode = data.pop("issue_mode", "manual") or "manual"
    if issue_mode not in ISSUE_MODE_LABELS:
        raise HTTPException(status_code=400, detail="开票方式只能是 手工开票 / 对接开票")

    item = Invoice(
        **data,
        direction=direction,
        invoice_flag=invoice_flag,
        issue_mode=issue_mode,
        items_json=json.dumps(items, ensure_ascii=False),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _invoice_to_dict(item)



@router.post("/invoices/import", status_code=status.HTTP_201_CREATED)
async def import_invoice(
    file: UploadFile = File(...),
    save: bool = Query(True, description="是否把原始文件落盘留档"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """**一步到位**：上传发票原件 → OCR/二维码/PDF 文本层解析 → 落盘留档 → 入库。

    在 `/invoices/parse` 之外单开这条，是为了把"原文件必须留下来"这件事
    变成**默认行为**：`/invoices/parse` 只是"看一眼识别结果"（预览用），
    走它不会留下任何东西 —— 于是历史上一张原件都没存下来，
    "导出原始发票 PDF" 这件事就无从做起。

    落盘和入库是**同一步**完成，不存在"文件存了但记录没建"的中间态。
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的文件是空的")

    filename = file.filename or "invoice"
    summary = _parse_invoice_pipeline(payload, filename)
    provider = str(summary.get("provider") or "")
    if provider not in ("rapidocr", "paddleocr", "qrcode", "pdf_text"):
        # 识别不出内容就别落盘 —— 免得 data 目录塞满没用的废文件
        return {
            "saved": False,
            "provider": provider,
            "detail": summary.get("detail") or "未能从这份文件里识别出发票内容，请确认是清晰的发票原件。",
            "invoice": None,
        }

    invoice_no = str(summary.get("invoice_no") or "").strip()
    if not invoice_no:
        invoice_no = f"INV-{uuid4().hex[:10].upper()}"

    source_path = source_name = source_mime = None
    source_size = None
    if save:
        try:
            source_path = file_storage.save_bytes(payload, filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # 库里记的是**净化后**的名字，保证下载时给出来的文件名与磁盘一致
        source_name = file_storage.safe_filename(filename)
        source_size = len(payload)
        source_mime = file.content_type or "application/octet-stream"

    company = load_company()
    direction = detect_direction(
        own_tax_no=company.get("own_tax_no"),
        own_name=company.get("own_name"),
        seller_tax_no=summary.get("seller_tax_no"),
        seller_name=summary.get("seller_name"),
        buyer_tax_no=summary.get("buyer_tax_no"),
        buyer_name=summary.get("buyer_name"),
    )

    # 同号覆盖：重传同一张发票时替换，并把旧原件删掉
    existing = db.query(Invoice).filter(Invoice.invoice_no == invoice_no).first()
    if existing is not None:
        file_storage.delete_file(existing.source_path)
        db.delete(existing)
        db.commit()

    item = Invoice(
        invoice_no=invoice_no,
        invoice_type=str(summary.get("invoice_type") or "未知"),
        issue_date=summary.get("invoice_date") or summary.get("issue_date"),
        counterparty_name=summary.get("counterparty_name") or summary.get("seller_name"),
        invoice_code=summary.get("invoice_code"),
        total_amount=float(summary.get("total_amount") or 0.0),
        tax_rate=summary.get("tax_rate"),
        tax_amount=summary.get("tax_amount"),
        excl_tax_amount=summary.get("excl_tax_amount"),
        buyer_name=summary.get("buyer_name"),
        buyer_tax_no=summary.get("buyer_tax_no"),
        seller_name=summary.get("seller_name"),
        seller_tax_no=summary.get("seller_tax_no"),
        category=_classify_invoice_record(summary),
        status="已确认",
        items_json=json.dumps(summary.get("items") or [], ensure_ascii=False),
        raw_text=summary.get("raw_text"),
        direction=direction,
        invoice_flag="blue",
        issue_mode="manual",
        source_path=source_path,
        source_name=source_name,
        source_size=source_size,
        source_mime=source_mime,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"saved": bool(source_path), "provider": provider, "invoice": _invoice_to_dict(item)}



@router.get("/invoices")
def list_invoices(
    direction: str | None = Query(None, description="input / output / unknown"),
    invoice_flag: str | None = Query(None, description="blue / red"),
    accounted: str | None = Query(None, description="with=只看有原件的"),
    issue_date_from: str | None = Query(None),
    issue_date_to: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int | None = None,
) -> dict[str, object]:
    """发票列表（带筛选与合计）。

    返回结构与其它列表接口保持一致：`{items, summary}`，
    summary 按进项/销项分别给金额与张数 —— 这正是"进销项分开看"要的东西。
    """
    query = db.query(Invoice)
    if direction:
        if direction not in DIRECTION_LABELS:
            raise HTTPException(status_code=400, detail="direction 只能是 input / output / unknown")
        query = query.filter(Invoice.direction == direction)
    if invoice_flag:
        if invoice_flag not in INVOICE_FLAG_LABELS:
            raise HTTPException(status_code=400, detail="invoice_flag 只能是 blue / red")
        query = query.filter(Invoice.invoice_flag == invoice_flag)
    if issue_date_from:
        query = query.filter(Invoice.issue_date >= issue_date_from)
    if issue_date_to:
        query = query.filter(Invoice.issue_date <= issue_date_to)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Invoice.invoice_no.ilike(like),
                Invoice.counterparty_name.ilike(like),
                Invoice.seller_name.ilike(like),
                Invoice.buyer_name.ilike(like),
                Invoice.handler.ilike(like),
            )
        )

    rows = query.order_by(Invoice.issue_date.desc().nullslast(), Invoice.id.desc()).all()
    counted = {"input": [0, 0.0], "output": [0, 0.0], "unknown": [0, 0.0]}
    for row in rows:
        bucket = counted.setdefault(row.direction or DIRECTION_UNKNOWN, [0, 0.0])
        bucket[0] += 1
        bucket[1] += float(row.total_amount or 0.0)

    if accounted == "with":
        rows = [row for row in rows if row.source_path]
    # 这里 rows 已经是取好的列表（要先全量算合计），所以直接切片，不走 _paginate 的 query 版本
    page = rows[skip:] if not limit else rows[skip : skip + limit]
    return {
        "items": [_invoice_to_dict(row) for row in page],
        "summary": {
            "total": len(rows),
            "input_count": counted["input"][0],
            "input_amount": round(counted["input"][1], 2),
            "output_count": counted["output"][0],
            "output_amount": round(counted["output"][1], 2),
            "unknown_count": counted["unknown"][0],
            "unknown_amount": round(counted["unknown"][1], 2),
            # 有原件的张数：决定"批量导出原件"能导出多少
            "with_source": sum(1 for row in rows if row.source_path),
        },
    }



@router.post("/invoices/redetect")
def redetect_invoices(db: Session = Depends(get_db)) -> dict[str, object]:
    """按当前公司抬头**重判**所有"待判定"的发票。

    为什么需要它：进销项靠本公司税号判定，而公司信息是后来才填的 ——
    填之前识别进来的发票全是「待判定」。补完公司信息后点一下这里就能批量纠正，
    不用一张张手工改。**只动 `unknown` 的行**，已经判定的（含手工改过的）一律不碰。
    """
    company = load_company()
    if not (company.get("own_tax_no") or company.get("own_name")):
        raise HTTPException(
            status_code=400,
            detail="还没有填写本公司名称与税号。请先到「系统设置 → 公司信息」补上，再回来重判。",
        )
    rows = db.query(Invoice).filter(Invoice.direction == DIRECTION_UNKNOWN).all()
    changed = 0
    for row in rows:
        decided = detect_direction(
            own_tax_no=company.get("own_tax_no"),
            own_name=company.get("own_name"),
            seller_tax_no=row.seller_tax_no,
            seller_name=row.seller_name,
            buyer_tax_no=row.buyer_tax_no,
            buyer_name=row.buyer_name,
        )
        if decided != DIRECTION_UNKNOWN:
            row.direction = decided
            changed += 1
    db.commit()
    return {"scanned": len(rows), "changed": changed, "message": f"重判完成：{changed} 张已确定方向"}



@router.get("/invoices/{invoice_id}/file")
def download_invoice_file(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """下载发票原件。

    ⚠️ **默认走 base64 JSON 通道**（`_pdf_response` 那次踩坑的同一类问题）：
    `application/pdf` 会被浏览器内置阅读器接管，`fetch()` 拿到空响应，
    前端会静默存下 0 字节空文件。所以这里也提供二进制通道给 curl / 外部脚本，
    但默认给 JSON。
    """
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="发票不存在")
    payload = file_storage.read_bytes(item.source_path)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="这张发票没有留档原件（早期导入的数据没有存原文件），无法下载。",
        )
    filename = item.source_name or f"{item.invoice_no}.pdf"
    media = item.source_mime or "application/octet-stream"
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": media,
                "content_base64": base64.b64encode(payload).decode("ascii"),
                "size": len(payload),
            }
        )
    return _attachment_response(payload, filename, media)



@router.get("/invoices/export/files")
def export_invoice_files(
    request: Request,
    direction: str | None = Query(None, description="只导出某个方向的原件"),
    ids: str | None = Query(None, description="逗号分隔的发票 id，只导这些；与界面上勾选的行对应"),
    db: Session = Depends(get_db),
) -> Response:
    """把原件打包成 ZIP 导出（"导出数据采用原始发票的 PDF 格式"）。

    只打包**真的还有原件**的发票；没有原件的（早期数据）跳过，
    并在响应头里如实告知跳过了多少张 —— 不报错、也不假装全都导出了。
    """
    query = db.query(Invoice)
    id_list = [int(part) for part in (ids or "").split(",") if part.strip().isdigit()]
    if id_list:
        query = query.filter(Invoice.id.in_(id_list))
    elif direction:
        if direction not in DIRECTION_LABELS:
            raise HTTPException(status_code=400, detail="direction 只能是 input / output / unknown")
        query = query.filter(Invoice.direction == direction)
    rows = query.order_by(Invoice.issue_date.asc().nullslast(), Invoice.id.asc()).all()

    buffer = io.BytesIO()
    included = skipped = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        used: set[str] = set()
        for row in rows:
            payload = file_storage.read_bytes(row.source_path)
            if payload is None:
                skipped += 1
                continue
            base = file_storage.safe_filename(row.source_name or f"{row.invoice_no}.pdf")
            arcname = f"{INVOICE_DIRECTION_DIRS.get(row.direction or DIRECTION_UNKNOWN, '待判定')}/{base}"
            # 同名去重：同一个名字塞两次，ZIP 里会出现重复条目
            if arcname in used:
                stem, dot, ext = arcname.rpartition(".")
                index = 2
                while arcname in used:
                    arcname = f"{stem}({index}){dot}{ext}"
                    index += 1
            used.add(arcname)
            bundle.writestr(arcname, payload)
            included += 1

    if included == 0:
        raise HTTPException(
            status_code=404,
            detail=f"没有可导出的原件（共 {len(rows)} 张发票，都没有留档原文件）。",
        )
    data = buffer.getvalue()
    filename = f"发票原件_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": "application/zip",
                "content_base64": base64.b64encode(data).decode("ascii"),
                "size": len(data),
                "included": included,
                "skipped": skipped,
            }
        )
    response = _attachment_response(data, filename, "application/zip")
    response.headers["X-Invoice-Included"] = str(included)
    response.headers["X-Invoice-Skipped"] = str(skipped)
    return response



@router.get("/invoices/export/qrcodes")
def export_invoice_qrcodes(
    request: Request,
    ids: str | None = Query(None, description="逗号分隔的发票 id，只导这些；不传则按 direction 全导"),
    direction: str | None = Query(None, description="只导出某个方向的二维码"),
    db: Session = Depends(get_db),
) -> Response:
    """批量导出**二维码**为 ZIP（"点开后可选导出方式 excel / PDF / 二维码"里的二维码）。

    二维码从**原件**里取（PDF 解内嵌图、图片裁二维码区），取不到的跳过并如实计数：
    实测 12 张真票里有 1 张 PDF 本身就没有二维码，那不是 bug，是那张票确实没有。
    """
    if direction and direction not in DIRECTION_LABELS:
        raise HTTPException(status_code=400, detail="direction 只能是 input / output / unknown")
    query = db.query(Invoice)
    id_list = [int(part) for part in (ids or "").split(",") if part.strip().isdigit()]
    if id_list:
        query = query.filter(Invoice.id.in_(id_list))
    elif direction:
        query = query.filter(Invoice.direction == direction)
    rows = query.order_by(Invoice.issue_date.asc().nullslast(), Invoice.id.asc()).all()
    if not rows:
        raise HTTPException(status_code=404, detail="没有符合条件的发票。")

    # 二维码来之不易（每张都要解一次 PDF），结果缓存下来 —— 一张票的明细页里
    # 可能同时请求"行内小图"和"导出"，重复解码同一份 PDF 纯属浪费。
    from app.services.invoice_layout import resolve_qr_png

    buffer = io.BytesIO()
    included = skipped = no_source = regenerated = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for row in rows:
            payload = file_storage.read_bytes(row.source_path)
            if payload is None:
                no_source += 1
                continue
            png, origin = resolve_qr_png(payload)
            if not png:
                skipped += 1
                continue
            if origin == "regenerated":
                regenerated += 1
            folder = INVOICE_DIRECTION_DIRS.get(row.direction or DIRECTION_UNKNOWN, "待判定")
            bundle.writestr(f"{folder}/{file_storage.safe_filename(row.invoice_no)}.png", png)
            included += 1

    if included == 0:
        raise HTTPException(status_code=404, detail=f"这 {len(rows)} 张发票里没有可导出的二维码。")
    data = buffer.getvalue()
    filename = f"发票二维码_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    meta = {
        "included": included,
        "skipped": skipped,
        "no_source": no_source,
        "regenerated": regenerated,
    }
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": "application/zip",
                "content_base64": base64.b64encode(data).decode("ascii"),
                "size": len(data),
                **meta,
            }
        )
    response = _attachment_response(data, filename, "application/zip")
    for key, value in meta.items():
        response.headers[f"X-Invoice-{key}"] = str(value)
    return response



@router.get("/invoices/{invoice_id}/qrcode")
def download_invoice_qrcode(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """单张发票的二维码 PNG（"二维码可下载"）。

    与原件下载同样走 base64 JSON 通道：`image/png` 不给浏览器接管的机会，
    但二进制通道也留着给 curl / 外部脚本。
    """
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="发票不存在")
    payload = file_storage.read_bytes(item.source_path)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="这张发票没有留档原件，二维码要先有原件才能解出来。",
        )
    from app.services.invoice_layout import resolve_qr_png

    png, origin = resolve_qr_png(payload)
    if not png:
        raise HTTPException(
            status_code=404,
            detail="这张发票的原件上没有二维码（部分数电票票面确实不带二维码）。",
        )
    filename = f"{file_storage.safe_filename(item.invoice_no or str(item.id))}.png"
    if _wants_json(request):
        return JSONResponse(
            {
                "filename": filename,
                "content_type": "image/png",
                "content_base64": base64.b64encode(png).decode("ascii"),
                "size": len(png),
                "invoice_no": item.invoice_no,
                # 如实标注来源：原图 / 图上裁的 / 用文本重画的
                "qr_origin": origin,
            }
        )
    response = _attachment_response(png, filename, "image/png")
    response.headers["X-Invoice-Qr-Origin"] = origin
    return response



@router.patch("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, payload: InvoiceUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    data = payload.model_dump(exclude_unset=True)
    # 枚举值必须校验：写进一个拼错的方向，界面上会显示成一串英文，且筛选永远命中不到
    for field, allowed in (
        ("direction", DIRECTION_LABELS),
        ("invoice_flag", INVOICE_FLAG_LABELS),
        ("issue_mode", ISSUE_MODE_LABELS),
    ):
        if field in data and data[field] is not None and data[field] not in allowed:
            raise HTTPException(status_code=400, detail=f"{field} 取值非法：{data[field]}")
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return _invoice_to_dict(item)



@router.delete("/invoices/batch", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoices_batch(payload: dict[str, object], db: Session = Depends(get_db)) -> Response:
    """批量删除发票：body 传 {"ids": [1, 2, 3]}。原件与同步出来的财务流水一并删掉。"""
    ids = [int(i) for i in (payload.get("ids") or [])]
    if not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    rows = db.query(Invoice).filter(Invoice.id.in_(ids)).all()
    for row in rows:
        file_storage.delete_file(row.source_path)
    # 流水不清掉就会变成谁都删不掉的孤儿（delete_finance_entry 拒绝删带 related_type 的）
    _purge_invoice_finance(db, [row.invoice_no for row in rows])
    db.query(Invoice).filter(Invoice.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)) -> Response:
    item = db.get(Invoice, invoice_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # 记录删了原件也要删 —— 否则 data 目录会积一堆再也对不上的文件
    file_storage.delete_file(item.source_path)
    _purge_invoice_finance(db, [item.invoice_no])
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get("/invoices/summary")
def invoices_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    """发票汇总：类别对比、专票抵扣、普票/专票月度金额，供汇总页图表与分组表使用。"""
    items = db.query(Invoice).order_by(Invoice.issue_date.asc(), Invoice.id.asc()).all()
    total_amount = sum(float(item.total_amount or 0) for item in items)
    total_tax = sum(float(item.tax_amount or 0) for item in items)
    by_type: dict[str, dict[str, object]] = {}
    monthly: dict[str, dict[str, dict[str, object]]] = {}
    deducted_count = 0
    deducted_amount = 0.0
    undeducted_count = 0
    undeducted_amount = 0.0

    for item in items:
        invoice_type = item.invoice_type or "未知"
        amount = float(item.total_amount or 0)
        entry = by_type.setdefault(invoice_type, {"type": invoice_type, "count": 0, "amount": 0.0})
        entry["count"] = int(entry["count"]) + 1
        entry["amount"] = float(entry["amount"]) + amount

        month = (item.issue_date or "")[:7]
        if len(month) == 7:
            month_entry = monthly.setdefault(month, {})
            type_entry = month_entry.setdefault(invoice_type, {"count": 0, "amount": 0.0, "tax": 0.0})
            type_entry["count"] = int(type_entry["count"]) + 1
            type_entry["amount"] = float(type_entry["amount"]) + amount
            type_entry["tax"] = float(type_entry["tax"]) + float(item.tax_amount or 0)

        if invoice_type == "专票":
            if item.deducted:
                deducted_count += 1
                deducted_amount += amount
            else:
                undeducted_count += 1
                undeducted_amount += amount

    return {
        "total_count": len(items),
        "total_amount": round(total_amount, 2),
        "total_tax": round(total_tax, 2),
        "by_type": sorted(by_type.values(), key=lambda x: float(x["amount"]), reverse=True),
        "deduction": {
            "deducted_count": deducted_count,
            "deducted_amount": round(deducted_amount, 2),
            "undeducted_count": undeducted_count,
            "undeducted_amount": round(undeducted_amount, 2),
        },
        "monthly": {month: data for month, data in sorted(monthly.items())},
    }



def _purge_invoice_finance(db: Session, invoice_nos: list[str]) -> int:
    """删发票时，把它同步出来的财务流水一并删掉，返回删了几条。

    为什么必须成对做：`delete_finance_entry` **不允许**删除带 `related_type` 的流水
    （单据自动写的流水必须跟着单据走，单独删会让账与单据对不上）。所以写入关联字段
    和"删票时清理流水"是**一件事的两半** —— 只做前一半，发票一删流水就变成
    谁都删不掉的孤儿。历史上真出过这个事（一条 ¥4,910.89 的孤儿流水）。

    对更早的、没有 `doc_no` 的历史流水用 note 文本兜底：不兜底的话那些孤儿永远清不掉。
    """
    nos = [str(no).strip() for no in invoice_nos if str(no).strip()]
    if not nos:
        return 0
    removed = 0
    for row in (
        db.query(FinancialTransaction)
        .filter(
            FinancialTransaction.related_type == "invoice",
            FinancialTransaction.doc_no.in_(nos),
        )
        .all()
    ):
        db.delete(row)
        removed += 1
    # 历史流水兜底：那时还没写 doc_no，票号只在 note 里
    for no in nos:
        for row in (
            db.query(FinancialTransaction)
            .filter(
                FinancialTransaction.related_type.is_(None),
                FinancialTransaction.note.ilike(f"%发票 {no}%"),
            )
            .all()
        ):
            db.delete(row)
            removed += 1
    return removed



@router.post("/invoices/sync-finance")
def sync_invoices_to_finance(db: Session = Depends(get_db)) -> dict[str, object]:
    """发票 → 财务关联：每张发票生成一条支出流水（按发票号码幂等去重）。"""
    items = db.query(Invoice).order_by(Invoice.id.asc()).all()
    existing_notes = [
        str(note)
        for (note,) in db.query(FinancialTransaction.note).filter(FinancialTransaction.note.isnot(None)).all()
    ]
    created = 0
    synced_amount = 0.0
    for item in items:
        marker = f"发票 {item.invoice_no}"
        if any(marker in note for note in existing_notes):
            continue
        counterparty = item.counterparty_name or item.seller_name or "对方单位"
        tax_text = f" 税额¥{float(item.tax_amount or 0):,.2f}" if item.tax_amount else ""
        issue_date = item.issue_date or None
        db.add(
            FinancialTransaction(
                transaction_type="expense",
                amount=float(item.total_amount or 0),
                note=f"{marker} | {counterparty} | {item.invoice_type} | 税率{item.tax_rate or '—'}%{tax_text}",
                # —— 结构化关联（这里以前是空的，只把票号写进 note）——
                # 票号只存在于 note 文本里有两个后果：
                #   1. 删发票时**找不到**这条流水，它就成了永久孤儿；
                #   2. 关键字搜索要靠 LIKE 扫全文，也建不了索引。
                related_type="invoice",
                doc_no=item.invoice_no,
                direction="out",
                # 有源单据的流水必须有业务日期：没有 occurred_at 的流水
                # 在「日常收支」按日期筛选时会被整个漏掉。
                occurred_at=issue_date,
                period=(issue_date or "")[:7] or None,
            )
        )
        created += 1
        synced_amount += float(item.total_amount or 0)
    db.commit()
    return {
        "created": created,
        "synced_amount": round(synced_amount, 2),
        "message": f"已同步 {created} 张发票到财务，金额合计 ¥{synced_amount:,.2f}",
    }



def _local_invoice_analysis(summary: dict[str, object]) -> str:
    """无 DeepSeek Key 时的本地规则分析兜底。"""
    lines_out: list[str] = []
    total = float(summary.get("total_amount") or 0)
    total_tax = float(summary.get("total_tax") or 0)
    lines_out.append(f"本期共 {summary.get('total_count', 0)} 张发票，价税合计 ¥{total:,.2f}，税额 ¥{total_tax:,.2f}。")
    by_type = {str(item.get("type")): item for item in summary.get("by_type") or []}
    for type_name in ("专票", "普票", "未知"):
        entry = by_type.get(type_name)
        if entry:
            pct = (float(entry.get("amount") or 0) / total * 100) if total else 0
            lines_out.append(f"{type_name} {entry.get('count', 0)} 张、金额 ¥{float(entry.get('amount') or 0):,.2f}（占比 {pct:.1f}%）。")
    deduction = summary.get("deduction") or {}
    if deduction.get("undeducted_count"):
        lines_out.append(f"⚠ 有 {deduction['undeducted_count']} 张专票共 ¥{float(deduction['undeducted_amount'] or 0):,.2f} 尚未抵扣，建议及时认证抵扣。")
    monthly = summary.get("monthly") or {}
    months = sorted(monthly.keys())
    if len(months) >= 2:
        last_month, prev_month = months[-1], months[-2]
        last_amount = sum(float(v.get("amount") or 0) for v in monthly[last_month].values())
        prev_amount = sum(float(v.get("amount") or 0) for v in monthly[prev_month].values())
        if prev_amount > 0:
            change = (last_amount - prev_amount) / prev_amount * 100
            direction = "上升" if change >= 0 else "下降"
            lines_out.append(f"月度趋势：{last_month} 较 {prev_month} 金额{abs(change):.1f}%{direction}。")
    lines_out.append("建议：定期核对未抵扣专票，普票占比过高时关注采购类目结构。")
    return "\n".join(lines_out)



@router.post("/invoices/agent-analysis")
def invoice_agent_analysis(payload: dict[str, object] | None = None) -> dict[str, object]:
    """智能体分析：DeepSeek 对发票汇总做趋势/异常/税务分析；未配置 Key 时本地规则兜底。"""
    payload = payload or {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是企业财务智能体。根据发票汇总数据输出分析，分四段：1)总体概况 2)趋势分析 3)异常与风险 4)税务建议（抵扣提醒）。用简洁中文，每段用标题开头。注意：total_amount 是价税合计（已含税），total_tax 已包含在其中，两者不要相加。",
                },
                {
                    "role": "user",
                    "content": f"发票汇总数据：{json.dumps(summary, ensure_ascii=False)}",
                },
            ],
            "temperature": 0.3,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=60) as response:
                raw = response.read().decode("utf-8")
                content = json.loads(raw)
            message = content.get("choices", [{}])[0].get("message", {}).get("content") or ""
            if message.strip():
                return {"provider": "deepseek", "analysis": message.strip()}
        except Exception:
            pass

    return {"provider": "local", "analysis": _local_invoice_analysis(summary)}



@router.post("/invoices/analyze")
def analyze_invoices(payload: dict[str, object]) -> dict[str, object]:
    raw_invoices = payload.get("invoices") or []
    if not isinstance(raw_invoices, list):
        raise HTTPException(status_code=400, detail="invoices must be a list")

    normalized: list[dict[str, object]] = []
    total_amount = 0.0
    category_totals: dict[str, float] = {}

    for index, item in enumerate(raw_invoices):
        if not isinstance(item, dict):
            continue
        amount_value = item.get("amount") or item.get("total") or item.get("invoice_amount") or 0
        amount = float(amount_value or 0)
        customer_name = item.get("customer_name") or item.get("customer") or item.get("company") or "未知客户"
        note = item.get("note") or item.get("remark") or ""
        category = item.get("category") or _classify_invoice_record(item)
        record = {
            "id": item.get("id") or item.get("invoice_no") or f"INV-{index + 1}",
            "invoice_no": item.get("invoice_no") or item.get("id") or f"INV-{index + 1}",
            "customer_name": str(customer_name),
            "amount": amount,
            "date": item.get("date") or item.get("invoice_date") or item.get("issue_date") or "—",
            "status": item.get("status") or item.get("payment_status") or "已确认",
            "category": str(category),
            "note": str(note),
        }
        normalized.append(record)
        total_amount += amount
        category_totals[str(category)] = category_totals.get(str(category), 0.0) + amount

    summary = {
        "total_amount": float(total_amount),
        "count": len(normalized),
        "by_category": {category: float(amount) for category, amount in sorted(category_totals.items())},
    }

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if api_key:
        prompt = json.dumps(normalized, ensure_ascii=False)
        deepseek_payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "你是发票智能分类助手。请把发票按采购、销售、差旅、税费、其他分类，并输出 JSON：{'items':[...], 'summary': {'total_amount':..., 'count':..., 'by_category': {...}}}。", 
                },
                {
                    "role": "user",
                    "content": f"请分析以下发票列表并返回分类结果：{prompt}",
                },
            ],
            "temperature": 0.1,
        }
        request_obj = request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps(deepseek_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(request_obj, timeout=30) as response:
                raw = response.read().decode("utf-8")
                content = json.loads(raw)
            choice = content.get("choices", [{}])[0]
            message = choice.get("message", {}).get("content") or ""
            cleaned = message.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            parsed_response = json.loads(cleaned)
            if isinstance(parsed_response.get("items"), list):
                return {
                    "provider": "deepseek",
                    "items": parsed_response["items"],
                    "summary": parsed_response.get("summary", summary),
                }
        except Exception:
            pass

    return {
        "provider": "local",
        "items": normalized,
        "summary": summary,
    }
