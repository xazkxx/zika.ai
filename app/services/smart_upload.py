"""多文件智能识别：把「营业执照 / 名片 / 开票信息 / Word 合同」认成档案字段。

## 这一层负责什么

用户把资料丢进来（图片、PDF、Word），到这里变成两类东西：

1. **纯文本**（`extract_text`）—— 只解决"怎么把字读出来"，按格式分派：
   · 图片  → RapidOCR（复用 `erp_invoice._ocr_image_bytes`，同一套模型，不再重复加载）
   · PDF   → 先读内嵌文本层（原生 PDF 直接就有字）；读不到再渲染成图走 OCR（扫描件）
   · .docx → python-docx：段落 + **表格**（报价单/合同明细都在表格里，表格另有一层结构化解析）
   · .doc  → OLE2 复合文档，按 UTF-16LE 抓中文片段（尽力而为，质量不如 .docx）
2. **字段**（`parse_party_fields`）—— 只解决"哪些字是客户名/税号/电话"，纯正则、可解释。

## 为什么不上大模型

* 档案字段是**结构化程度很高**的东西：执照上就那几行，正则足够，且**可解释**
  （每个值都带 evidence 原文片段，界面上直接高亮给用户核对）；
* 大模型要联网/要 key、结果不稳定、还有把"注册资本"认成"电话"这类幻觉，
  填错一个税号比让用户手敲更糟；
* 真需要兜底时，`parse_party_fields` 的返回结构就是给"再接一层 LLM 校验"留的接口。

## 防呆的三条约定

1. **不猜**：认不出来就**不返回这个键**（而不是返回空串），前端据此提示"税号没认到，请补录"；
2. **不覆盖已填**：合并多份文件的字段时，天真的 `dict.update` 会让第二份文件里的
   "地址：见附件" 盖掉第一份的完整地址 —— 这里只补空缺（`_merge`）；
3. **不静默**：每个文件单独报 `ok/engine/chars/error`，一个坏了不影响其它文件。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

# 单次最多几个文件：营业执照 + 名片 + 报价单，6 个已经足够，再多是误操作
MAX_FILES = 6
# 单个文件上限：与发票/合同原件同口径
MAX_FILE_BYTES = 20 * 1024 * 1024

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
WORD_SUFFIXES = {".docx", ".doc"}
PDF_SUFFIXES = {".pdf"}
ACCEPT_SUFFIXES = IMAGE_SUFFIXES | WORD_SUFFIXES | PDF_SUFFIXES

# 每种档案允许回填的字段（前端表单的 key，不是数据库列名）
PROFILE_FIELDS = {
    "customer": [
        "name", "contact", "phone", "email", "address", "businesser", "tax_no",
        # 2026-10-23：客户表单补了税号/开户行/账号/开票电话四列，识别结果直接能回填
        "bank_name", "bank_account", "invoice_phone",
    ],
    "supplier": [
        "name", "tax_no", "contact", "mobile", "phone", "email", "address",
        "bank_name", "bank_account", "invoice_phone",
    ],
    "product": [
        # 键名与前端 `emptyProductForm` 对齐：规格是 `standards`、型号是 `brand`
        "name", "standards", "brand", "unit", "sale_price", "purchase_price",
        "tax_rate", "manufacturer",
    ],
}

FIELD_LABELS = {
    "name": "名称",
    "contact": "联系人",
    "phone": "联系电话",
    "mobile": "手机",
    "email": "邮箱",
    "address": "地址",
    "businesser": "业务员",
    "tax_no": "纳税人识别号",
    "bank_name": "开户行",
    "bank_account": "银行账号",
    "invoice_phone": "开票电话",
    "standards": "规格",
    "brand": "型号",
    "unit": "单位",
    "manufacturer": "生产厂家",
    "sale_price": "销售价",
    "purchase_price": "采购价",
    "tax_rate": "税率",
}

# 名称里出现这些词就不再往下取（执照一行里常常"名称… 纳税人识别号…"连在一起）
_NAME_STOPS = (
    "纳税人识别号", "统一社会信用代码", "住所", "地址", "法定代表人", "法定代表",
    "类型", "成立日期", "注册资本", "营业期限", "经营范围", "登记机关", "联系电话",
)
# 地址里出现这些词就截断
_ADDRESS_STOPS = (
    "法定代表人", "法定代表", "成立日期", "注册资本", "营业期限", "经营范围",
    "登记机关", "电话", "邮编", "纳税人识别号", "统一社会信用代码",
)

_USCC_RE = re.compile(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}")
_MOBILE_RE = re.compile(r"1[3-9]\d{9}")
_LANDLINE_RE = re.compile(r"(?:0\d{2,3}[-\s]?)?\d{7,8}(?:[-转]\d{1,5})?")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_COMPANY_TAIL = ("有限公司", "有限责任公司", "股份有限公司", "分公司", "公司", "厂", "店", "中心", "合作社", "研究院", "事务所")


# --------------------------------------------------------------------------
# 一、文本抽取
# --------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """全角冒号/空格归一，但**保留换行** —— 名称/地址的边界就靠换行判断。"""
    return (
        (text or "")
        .replace("\u3000", " ")
        .replace("：", ":")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def _extract_pdf_text(payload: bytes) -> tuple[str, str]:
    """返回 (文本, 引擎)。文本层有字就用文本层，没有（扫描件）才 OCR 前 3 页。"""
    import fitz

    with fitz.open(stream=payload, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
        if len(text.strip()) >= 30:
            return text, "pdf-text"

        # 扫描件：渲染前 3 页再 OCR。3 页之外对"认档案字段"没有价值，
        # 全渲染会让 40 页的合同扫描件吃掉几十 MB 内存还拖慢十几秒。
        from app.api.v1.routes.erp_invoice import _ocr_image_bytes

        lines: list[str] = []
        engine = "fallback"
        for index, page in enumerate(doc):
            if index >= 3:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
            engine_name, page_lines = _ocr_image_bytes(pix.tobytes("png"))
            if page_lines:
                engine = engine_name
                lines.extend(page_lines)
        return "\n".join(lines), engine


def _extract_image_text(payload: bytes) -> tuple[str, str]:
    from app.api.v1.routes.erp_invoice import _ocr_image_bytes

    engine, lines = _ocr_image_bytes(payload)
    return "\n".join(lines), engine


def _extract_docx(payload: bytes) -> tuple[str, str]:
    """Word：段落 + 表格，表格按「单元格用 | 隔开、一行一条」摊平。

    表格必须进文本，否则报价单/合同里的商品明细在纯段落里根本看不见。
    结构化解析另有 `parse_docx_tables`，这里只管"让人也能读"。
    """
    import io

    from docx import Document

    document = Document(io.BytesIO(payload))
    chunks: list[str] = []
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if text:
            chunks.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            if any(cells):
                chunks.append(" | ".join(cells))
    return "\n".join(chunks), "python-docx"


def _extract_doc(payload: bytes) -> tuple[str, str]:
    """.doc（OLE2）：WPS/Word 97 格式，没有可靠的纯 Python 解析器。

    做法是从整个字节流里抓 UTF-16LE 的中文片段 —— 正文在 Word 97 里就是按这个存的。
    质量不如 .docx（可能混入格式串），但对"认公司名/税号"够用，且不需要装 Word。
    """
    try:
        import io

        import olefile

        stream = io.BytesIO(payload)
        if not olefile.isOleFile(stream):
            return "", "unsupported"
        with olefile.OleFileIO(stream) as ole:
            if not ole.exists("WordDocument"):
                return "", "unsupported"
            raw = ole.openstream("WordDocument").read()
        text = raw.decode("utf-16-le", errors="ignore")
        # 只留"像中文文本"的片段，滤掉二进制噪声
        pieces = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9:：,，.。;；、()（）\-/ ]{3,}", text)
        return "\n".join(piece.strip() for piece in pieces if piece.strip()), "olefile"
    except Exception:  # noqa: BLE001 —— .doc 解析失败不能连累其它文件
        return "", "unsupported"


def extract_text(filename: str, payload: bytes) -> dict[str, object]:
    """按后缀分派，返回 `{ok, engine, text, chars, error}`。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ACCEPT_SUFFIXES:
        return {
            "ok": False,
            "engine": "unsupported",
            "text": "",
            "chars": 0,
            "error": f"不支持的格式「{suffix or '无后缀'}」，请上传图片 / PDF / Word",
        }
    if not payload:
        return {"ok": False, "engine": "none", "text": "", "chars": 0, "error": "文件是空的"}
    if len(payload) > MAX_FILE_BYTES:
        return {
            "ok": False,
            "engine": "none",
            "text": "",
            "chars": 0,
            "error": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 上限",
        }

    try:
        if suffix in PDF_SUFFIXES:
            text, engine = _extract_pdf_text(payload)
        elif suffix in IMAGE_SUFFIXES:
            text, engine = _extract_image_text(payload)
        elif suffix == ".docx":
            text, engine = _extract_docx(payload)
        else:
            text, engine = _extract_doc(payload)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "engine": "error",
            "text": "",
            "chars": 0,
            "error": f"解析失败（{type(exc).__name__}）：文件可能已损坏",
        }

    text = _normalize(text)
    if not text.strip():
        return {
            "ok": False,
            "engine": engine,
            "text": "",
            "chars": 0,
            "error": "没读到文字（图片太糊或不是文字类文件），换一张清晰些的再试",
        }
    return {"ok": True, "engine": engine, "text": text, "chars": len(text), "error": None}


# --------------------------------------------------------------------------
# 二、字段解析（纯正则，可解释）
# --------------------------------------------------------------------------
def _clean_value(value: str, stops: tuple[str, ...] = ()) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip(" :：|,，.。;；、")
    for stop in stops:
        index = value.find(stop)
        if index > 0:
            value = value[:index]
    return value.strip(" :：|,，.。;；、")


def _label_pattern(label: str) -> str:
    """把标签写成"字与字之间允许空格"的正则。

    营业执照上常写成「名　称」「住　所」「类　型」（中间是全角空格占位，
    为了两字/四字标签对齐），归一化之后就成了「名 称」。只按「名称」去找，
    会一路滑到「类型」那行，认出来的是"有限责任公司（…）"——第一次实测就是这么翻车的。
    """
    if re.search(r"[A-Za-z]", label):
        return re.escape(label)
    return r"\s*".join(re.escape(char) for char in label)


def _label_value(text: str, labels: tuple[str, ...], stops: tuple[str, ...] = (), limit: int = 80) -> str:
    """取「标签: 值」里的值 —— 同一行取到行尾，或者取标签后面紧跟的一段。

    ⚠️ 标签前面**不能是汉字**（`(?<![\u4e00-\u9fa5])`）：
    Word 报价单里摊平后的表头是「产品名称 | 规格型号 | …」，早先按"名称"去搜，
    直接把表头认成了公司名（"规格型号 | 单位 | 数量…"）。
    「注册地址」「经营地址」这类本身就以汉字开头的标签写在列表里会长一点、先命中，
    不受这条限制影响。
    """
    for label in labels:
        pattern = re.compile(
            rf"(?<![\u4e00-\u9fa5]){_label_pattern(label)}\s*[:：]?\s*([^\n]{{1,{limit}}})",
        )
        match = pattern.search(text)
        if match:
            value = _clean_value(match.group(1), stops)
            # 带 " | " 的是被摊平的表格行/表头，不可能是字段值
            if value and " | " not in value:
                return value
    return ""


# OCR 常把两字标签拆成两行/插字（实测「名　称」被认成 "名和\n称陕西送变电…"），
# 结果公司名前面带着一个孤零零的「称」。这类残字只可能是标签碎片，剥掉。
_LABEL_FRAGMENTS = ("称", "名", "所", "址", "话")


def _tidy_name(value: str) -> str:
    """把公司名开头可能残留的标签碎片剥掉。

    只剥「称/名/所/址/话」这几个字，**不动 和/华/中** 之类真会出现在公司名里的字
    （"和平商贸有限公司"剥掉"和"就毁名字了）。剥的条件也收紧：
    剥完剩下的部分还得像个公司名（长度 ≥4 且带"公司/厂/店…"）。
    """
    cleaned = (value or "").strip()
    for _ in range(3):
        if len(cleaned) < 4:
            break
        if cleaned[0] not in _LABEL_FRAGMENTS:
            break
        rest = cleaned[1:].lstrip()
        if len(rest) >= 4 and any(tail in rest for tail in _COMPANY_TAIL):
            cleaned = rest
        else:
            break
    return cleaned.strip()


def _guess_company_name(text: str) -> str:
    """没有「名称:」标签时，挑最像公司全称的一行。

    判断标准：包含「有限公司/厂/店/中心…」且**长度最长** —— 执照上「名称」那行通常
    比「经营范围」里的碎片长，取最长能稳定命中。
    """
    best = ""
    for line in text.split("\n"):
        # 「供应商：深圳市凯歌电子有限公司」这种带标签的整行，先把标签切掉
        prefix = re.match(r"^[\u4e00-\u9fa5A-Za-z]{2,8}\s*[:：]\s*(.+)$", line.strip())
        if prefix:
            line = prefix.group(1)
        candidate = _clean_value(line, _NAME_STOPS)
        if len(candidate) < 4 or len(candidate) > 60:
            continue
        # 「类型  有限责任公司（非自然人投资…）」这类行也带"公司"两个字，
        # 但它不是名称。凡是本行是以其它字段名开头的，直接排除。
        if re.match(r"^\s*(类\s*型|经营范围|住\s*所|地\s*址|法定代表人|注册资本|成立日期|营业期限|登记机关)", candidate):
            continue
        if any(tail in candidate for tail in _COMPANY_TAIL):
            if len(candidate) > len(best):
                best = candidate
    return best


def _normalize_phone(raw: str) -> str:
    value = re.sub(r"[^\d\-转]", "", raw or "")
    return value.strip("-")


def parse_party_fields(text: str, kind: str = "customer") -> tuple[dict[str, str], dict[str, str], list[str]]:
    """从文本里抠出客户/供应商字段。

    返回 `(fields, evidence, warnings)`：
      · `fields` 只放**认出来的**键（认不出就不出现）；
      · `evidence` 是每个值的原文片段，前端核对弹窗用它做高亮；
      · `warnings` 是可读的提醒（"没认到税号"这种），不是错误。
    """
    allowed = PROFILE_FIELDS.get(kind, PROFILE_FIELDS["customer"])
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}

    name = _label_value(
        text,
        ("企业名称", "公司名称", "单位名称", "客户名称", "供应商名称", "购方名称", "名称"),
        _NAME_STOPS,
    )
    if not name or len(name) < 2:
        name = _guess_company_name(text)
    if name:
        name = _tidy_name(name)
        fields["name"] = name
        evidence["name"] = name

    uscc = _label_value(text, ("纳税人识别号", "统一社会信用代码", "税号", "识别号"), (), 30)
    if not uscc:
        match = _USCC_RE.search(text.replace(" ", ""))
        uscc = match.group(0) if match else ""
    uscc = re.sub(r"[^0-9A-Za-z]", "", uscc).upper()
    if len(uscc) >= 15:
        fields["tax_no"] = uscc[:20]
        evidence["tax_no"] = uscc

    address = _label_value(text, ("住所", "注册地址", "经营地址", "地址", "地 址"), _ADDRESS_STOPS, 120)
    if address:
        fields["address"] = address
        evidence["address"] = address

    contact = _label_value(text, ("联系人", "法定代表人", "法定代表", "法人代表", "负责人", "承办人"), (), 12)
    if contact and re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", contact):
        fields["contact"] = contact
        evidence["contact"] = contact

    # ⚠️ 电话必须在"去掉税号"之后的文本里找：18 位统一社会信用代码里随便一段
    # 都能凑出 `1[3-9]\d{9}`（实测 9144030071526726X9 → 认出一个假的手机号
    # 14403007152）。先把税号和 15 位以上的长数字串抹掉，再认电话。
    phone_text = text.replace(fields.get("tax_no", ""), " ") if fields.get("tax_no") else text
    phone_text = re.sub(r"\d{15,}", " ", phone_text)

    mobile = ""
    mobile_match = _MOBILE_RE.search(phone_text)
    if mobile_match:
        mobile = mobile_match.group(0)
    if mobile:
        fields["mobile"] = mobile
        evidence["mobile"] = mobile

    phone = _label_value(phone_text, ("联系电话", "电话", "座机", "Tel", "TEL", "tel"), (), 30)
    phone = _normalize_phone(phone)
    if not phone and not mobile:
        landline = _LANDLINE_RE.search(phone_text)
        phone = _normalize_phone(landline.group(0)) if landline else ""
    if phone and len(re.sub(r"\D", "", phone)) >= 7:
        fields["phone"] = phone
        evidence["phone"] = phone

    invoice_phone = _label_value(
        phone_text, ("开票电话", "开票电话/传真", "开票信息电话", "财务电话"), (), 30
    )
    invoice_phone = _normalize_phone(invoice_phone)
    if invoice_phone and len(re.sub(r"\D", "", invoice_phone)) >= 7:
        fields["invoice_phone"] = invoice_phone
        evidence["invoice_phone"] = invoice_phone

    email_match = _EMAIL_RE.search(text)
    if email_match:
        fields["email"] = email_match.group(0)
        evidence["email"] = email_match.group(0)

    businesser = _label_value(text, ("业务员", "销售员", "客户经理", "跟进人"), (), 10)
    if businesser and re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", businesser):
        fields["businesser"] = businesser
        evidence["businesser"] = businesser

    bank_name = _label_value(text, ("开户行名称", "开户行", "开户银行"), _ADDRESS_STOPS, 60)
    if bank_name:
        fields["bank_name"] = bank_name
        evidence["bank_name"] = bank_name

    bank_account = _label_value(text, ("银行账号", "开户账号", "帐号", "账号"), (), 40)
    bank_account = re.sub(r"\s", "", bank_account)
    if len(re.sub(r"\D", "", bank_account)) >= 8:
        fields["bank_account"] = bank_account
        evidence["bank_account"] = bank_account

    if kind == "customer":
        # 客户表单没有 mobile 字段：手机直接当联系电话用（手机比座机更能找到人）
        if "mobile" in fields and "phone" not in fields:
            fields["phone"] = fields.pop("mobile")
            evidence["phone"] = evidence.pop("mobile")
        # 2026-10-23：客户表单已有开户行/账号，识别到就留着（以前会在这里被丢掉）
    elif kind == "supplier":
        # 供应商表单两个都有：手机进 mobile，座机进 phone，别互相顶掉
        if "mobile" in fields and "phone" not in fields:
            pass

    # 只留该 kind 允许的键（防止以后加了解析器把无关键塞进表单）
    fields = {key: value for key, value in fields.items() if key in allowed}
    evidence = {key: value for key, value in evidence.items() if key in fields}

    warnings: list[str] = []
    if "name" not in fields:
        warnings.append("没认出单位名称，请手动填写第一条")
    if kind in ("customer", "supplier") and "tax_no" not in fields:
        warnings.append("没认出纳税人识别号（开票、对账都要用），建议手动补上")
    if not ({"phone", "mobile"} & set(fields)):
        warnings.append("没认出电话，请手动补上")
    if "address" not in fields:
        warnings.append("没认出地址")

    return fields, evidence, warnings


# --------------------------------------------------------------------------
# 二点五、商品字段（产品彩页 / 报价单首行 / 商品标签）
# --------------------------------------------------------------------------
_MONEY_RE = re.compile(r"([0-9]+(?:\.[0-9]{1,4})?)")


def _money_text(raw: str) -> str:
    """把「¥1,280.00 元」洗成 "1280.00"；洗不出数字就返回空串。"""
    cleaned = (raw or "").replace(",", "").replace("，", "")
    match = _MONEY_RE.search(cleaned)
    return match.group(1) if match else ""


def parse_product_fields(text: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """从产品资料/报价单里认商品字段。

    与客户不同，商品的"名字"经常和规格写在同一行（"电缆 YJV-3x35"），
    所以规格允许**从名称行里切**：先按标签取；取不到再按"中文名 + 型号样式"拆一次。
    """
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}

    name = _label_value(text, ("产品名称", "商品名称", "品名", "物料名称", "货物名称"), _NAME_STOPS, 40)
    if not name:
        # 没有标签：取第一行"像商品名"的短行（跳过"报价单/产品资料"这类标题）
        for line in text.split("\n"):
            candidate = _clean_value(line)
            # 跳过"抬头类"标题行：报价单/产品资料/目录/清单/说明…（它们是文档标题，不是商品名）
            if 2 <= len(candidate) <= 30 and not re.search(
                r"(报价单|产品资料|产品目录|价目表|目录|清单|序号|说明|资料|表$)", candidate
            ):
                name = candidate
                break
    if name:
        fields["name"] = name
        evidence["name"] = name

    spec = _label_value(text, ("规格型号", "规格", "尺寸"), (), 40)
    if spec:
        fields["standards"] = spec
        evidence["standards"] = spec

    # 型号：只在明确写了「型号」标签时取，避免把规格型号整串塞进 brand
    brand = _label_value(text, ("型号",), (), 30)
    brand = brand.strip()
    if brand and brand != spec:
        fields["brand"] = brand
        evidence["brand"] = brand

    unit = _label_value(text, ("单位", "计量单位"), (), 8)
    if unit and len(unit) <= 6:
        fields["unit"] = unit
        evidence["unit"] = unit

    sale = _money_text(_label_value(text, ("销售价", "零售价", "报价", "单价", "销售单价"), (), 20))
    if sale:
        fields["sale_price"] = sale
        evidence["sale_price"] = sale

    purchase = _money_text(_label_value(text, ("采购价", "成本价", "进价", "采购单价"), (), 20))
    if purchase:
        fields["purchase_price"] = purchase
        evidence["purchase_price"] = purchase

    tax_match = re.search(r"(?:增值税)?税率\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", text)
    if tax_match:
        fields["tax_rate"] = tax_match.group(1)
        evidence["tax_rate"] = f"{tax_match.group(1)}%"

    manufacturer = _label_value(text, ("生产厂家", "生产商", "制造商", "厂家", "品牌"), ("规格",), 40)
    if manufacturer:
        fields["manufacturer"] = manufacturer
        evidence["manufacturer"] = manufacturer

    fields = {key: value for key, value in fields.items() if key in PROFILE_FIELDS["product"]}
    evidence = {key: value for key, value in evidence.items() if key in fields}

    warnings: list[str] = []
    if "name" not in fields:
        warnings.append("没认出产品名称，请手动填写")
    if "unit" not in fields:
        warnings.append("没认出单位（件/台/米…），建议补上")
    if "sale_price" not in fields:
        warnings.append("没认出销售价")
    return fields, evidence, warnings


# --------------------------------------------------------------------------
# 三、商品明细（报价单 / 合同表格）
# --------------------------------------------------------------------------
_ITEM_HEADER_WORDS = ("品名", "产品名称", "商品名称", "名称", "货物名称")
_ITEM_COLUMN_WORDS = {
    "spec": ("规格", "型号", "规格型号"),
    "unit": ("单位",),
    "quantity": ("数量", "数 量"),
    "unit_price": ("单价", "含税单价"),
    "amount": ("金额", "小计", "总价"),
}


def _match_column(header: str) -> str | None:
    for key, words in _ITEM_COLUMN_WORDS.items():
        if any(word in header for word in words):
            return key
    if any(word in header for word in _ITEM_HEADER_WORDS):
        return "name"
    return None


def parse_docx_tables(payload: bytes) -> list[dict[str, object]]:
    """从 Word 表格里认出商品明细行（报价单最常见的载体）。

    只认**表头能对上**的表格：找不到"名称/品名"列就当它不是明细表，
    宁可返回空也不要把合同条款表当成商品灌进去。
    """
    import io

    from docx import Document

    rows: list[dict[str, object]] = []
    try:
        document = Document(io.BytesIO(payload))
    except Exception:  # noqa: BLE001
        return rows

    def num(value: str) -> float | None:
        cleaned = re.sub(r"[^\d.\-]", "", (value or "").replace(",", ""))
        try:
            return float(cleaned) if cleaned not in ("", "-", ".") else None
        except ValueError:
            return None

    for table in document.tables:
        if not table.rows:
            continue
        header_cells = [(cell.text or "").strip() for cell in table.rows[0].cells]
        mapping: dict[int, str] = {}
        for index, header in enumerate(header_cells):
            key = _match_column(header)
            if key and key not in mapping.values():
                mapping[index] = key
        if "name" not in mapping.values() or len(mapping) < 2:
            continue
        name_index = [index for index, key in mapping.items() if key == "name"][0]
        for row in table.rows[1:]:
            cells = [(cell.text or "").strip() for cell in row.cells]
            if len(cells) <= name_index:
                continue
            name = cells[name_index]
            if not name or any(word in name for word in ("合计", "小计", "总计")):
                continue
            item: dict[str, object] = {"name": name}
            for index, key in mapping.items():
                if key == "name" or index >= len(cells):
                    continue
                value = cells[index]
                if key in ("quantity", "unit_price", "amount"):
                    parsed = num(value)
                    if parsed is not None:
                        item[key] = parsed
                elif value:
                    item[key] = value
            if item.get("name"):
                rows.append(item)
            if len(rows) >= 200:
                break
    return rows


_ITEM_LINE_RE = re.compile(
    # 「1  电缆 …」这种"序号 + 空格"，序号后面**不一定**有点/顿号；
    # 早先写成 `\d+[.、)]` 时，序号 1 后面是空格 → 整组不匹配 → 一行都认不出来。
    r"^\s*(?:\d{1,3}\s*[.、)]?\s+)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-]{2,30}?)\s+"
    r"(?P<spec>[^\s]{0,20})\s+"
    r"(?P<unit>个|件|台|套|米|米数|kg|KG|吨|箱|卷|根|块|只|批|组|张|包|桶)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<price>\d+(?:\.\d+)?)"
)


def parse_items_from_text(text: str) -> list[dict[str, object]]:
    """纯文本兜底：只认「名称 规格 单位 数量 单价」这种一行一行的写法。

    刻意保守：格式对不上就不认（宁可少认，也不要往明细表里灌垃圾行）。
    """
    rows: list[dict[str, object]] = []
    for line in (text or "").split("\n"):
        match = _ITEM_LINE_RE.match(line)
        if not match:
            continue
        rows.append(
            {
                "name": match.group("name").strip(),
                "spec": match.group("spec").strip(),
                "unit": match.group("unit"),
                "quantity": float(match.group("qty")),
                "unit_price": float(match.group("price")),
            }
        )
        if len(rows) >= 200:
            break
    return rows


# --------------------------------------------------------------------------
# 四、整包入口
# --------------------------------------------------------------------------
def _merge(target: dict[str, str], source: dict[str, str]) -> None:
    """只补空缺 —— 第二份文件里更短/更含糊的值不许盖掉第一次认到的。"""
    for key, value in source.items():
        if not target.get(key) and value:
            target[key] = value


def analyze_files(files: list[tuple[str, bytes]], kind: str = "customer", mode: str = "parse") -> dict[str, object]:
    """`files` 是 `[(文件名, 字节)]`，返回接口要吐的那一坨。

    `mode="attach"` 只做校验（“仅上传作为附件”时不必白跑一遍 OCR）。
    """
    started = time.perf_counter()
    report: list[dict[str, object]] = []
    fields: dict[str, str] = {}
    evidence: dict[str, str] = {}
    warnings: list[str] = []
    items: list[dict[str, object]] = []

    if len(files) > MAX_FILES:
        warnings.append(f"一次最多识别 {MAX_FILES} 个文件，超出的部分已忽略")

    for filename, payload in files[:MAX_FILES]:
        result = extract_text(filename, payload)
        text = str(result["text"] or "")
        report.append(
            {
                "name": filename,
                "ok": bool(result["ok"]),
                "engine": result["engine"],
                "chars": int(result["chars"] or 0),
                "error": result["error"],
                # 预览只给前 400 字：够用户确认"读的是这份资料"，也不会把整页塞进响应
                "preview": text[:400],
            }
        )
        if not result["ok"] or mode != "parse":
            continue

        if kind in ("customer", "supplier"):
            file_fields, file_evidence, file_warnings = parse_party_fields(text, kind)
            _merge(fields, file_fields)
            _merge(evidence, file_evidence)
            warnings.extend(file_warnings)
        elif kind == "product":
            file_fields, file_evidence, file_warnings = parse_product_fields(text)
            _merge(fields, file_fields)
            _merge(evidence, file_evidence)
            warnings.extend(file_warnings)

        # 商品明细：Word 优先（表格最准），其余格式退回按行正则
        if Path(filename).suffix.lower() == ".docx" and not items:
            items = parse_docx_tables(payload)
        if not items:
            items = parse_items_from_text(text)

    # 文件名本身也常是线索：「西安XX公司营业执照.jpg」这种
    if mode == "parse" and not fields.get("name"):
        for filename, _payload in files[:MAX_FILES]:
            stem = Path(filename).stem
            stem = re.sub(r"(营业执照|副本|正本|扫描件|复印件|开票信息|名片|\d{6,})", "", stem)
            stem = _clean_value(stem, _NAME_STOPS)
            stem = _tidy_name(stem)
            if len(stem) >= 4 and any(tail in stem for tail in _COMPANY_TAIL):
                fields["name"] = stem
                evidence["name"] = stem
                warnings.append("单位名称是从文件名推断的，请核对")
                break

    # 商品：正文没认出名称、但表格里认出了明细行 → 用第一行兜底
    # （报价单最常见的形态就是"抬头是产品资料，明细全在表里"）
    if kind == "product" and items:
        first = items[0]
        for key, value in (
            ("name", first.get("name")),
            ("standards", first.get("spec")),
            ("unit", first.get("unit")),
        ):
            if not fields.get(key) and value:
                fields[key] = str(value)
                evidence[key] = str(value)
        if not fields.get("sale_price") and first.get("unit_price") not in (None, ""):
            fields["sale_price"] = str(first["unit_price"])
            evidence["sale_price"] = str(first["unit_price"])

    # 去重（不同文件重复报同一个 warning 会把核对弹窗撑爆）
    deduped: list[str] = []
    for warning in warnings:
        if warning not in deduped:
            deduped.append(warning)

    return {
        "kind": kind,
        "mode": mode,
        "files": report,
        "fields": fields,
        "evidence": evidence,
        "field_labels": {key: FIELD_LABELS.get(key, key) for key in fields},
        "items": items,
        "warnings": deduped,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
