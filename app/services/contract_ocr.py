"""合同原件 OCR 识别（任务 B · 2026-10-19）

为什么引擎链路要"借用"发票那套（`erp_invoice.py`）：
  发票导入已经把 rapidocr → paddleocr 的两级回退、PDF 文本层优先、
  渲染参数（扫描件 3 倍 ≈ 300 DPI 小字更清晰）都趟平了，而且一直在生产上跑。
  在这里**惰性 import** 复用，不复制一份代码 —— 两份引擎代码迟早改岔。
  （放在函数内部 import 而不是模块顶部：避免路由模块之间的加载顺序耦合。）

三关流水线（与发票一致，只是没有二维码这一关 —— 合同扫描件上没有码）：
  ① PDF 有文本层（≥20 个有效字符）→ 直接用文本，**不跑 OCR**（又快又准）；
  ② PDF 是扫描件（没文本层）→ 每页渲染成 PNG 逐页 OCR；
  ③ 图片（png/jpg/jpeg/bmp）→ 直接 OCR。
  Word（doc/docx）不支持：转 PDF 的事交给用户，服务端解析 Word 是另一个坑。

产出（`build_ocr_json`）原样落库 —— 识别一定有错，人工核对时要能看到
"当时到底认成了什么"，只存清洗后的字段就永远说不清某一分钱是怎么来的。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

# PDF 最多识别多少页：合同一般 2-5 页，识别一页约 1-2 秒，
# 不设上限的话一本 200 页的标书能让这个接口跑到天荒地老。
MAX_PAGES = 10

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}

# 有效文本的最小长度：低于它就当"没有文本层"（纯扫描件里也常混着页码水印）。
_MIN_TEXT_LAYER_CHARS = 20

# ---------------------------------------------------------------------------
# 字段提取（正则按国内合同的常见排版写，宁可漏、不可错 —— 漏了用户手填，
# 错了用户可能直接信了。所有提取结果都只是"候选"，必须人工核对后才落库。）
# ---------------------------------------------------------------------------

# 合同编号
_RE_CONTRACT_NO = re.compile(
    r"(?:合同编号|合同号|编号|协议编号)\s*[:：]?\s*([A-Za-z0-9\-_/（）()]{4,40})"
)
# 金额：只在带"金额/总价/合计"字样的地方附近找数字，裸数字绝不认
# （页码、日期、电话、铜价都会撞上）。
#
# 窗口 60 个字 + 允许跨行，是被真实合同逼出来的：它写的是
#     （1）本合同暂定含税总价：人民币（大写）贰佰陆拾壹万柒仟伍佰陆拾捌元贰分
#     （￥2617568.02元）。
# 阿拉伯数字落在**下一行**，窗口窄了就只能认到"暂定总价的30%作为预付款"里的那个 30。
_RE_AMOUNT = re.compile(
    r"(?:合同含税总价|含税总价|合同总金额|合同金额|总金额|合同总价|总价款|总价|金额合计|合计金额|价款合计|合计)"
    r"[^0-9]{0,60}?"
    r"([0-9][0-9,，]*(?:\.[0-9]{1,2})?)"
)
# 兜底：带货币符号的金额（￥/¥）。合同里"钱"几乎都带符号，这是最后一道网。
_RE_AMOUNT_SYMBOL = re.compile(r"[¥￥]\s*([0-9][0-9,，]*(?:\.[0-9]{1,2})?)")
# 签订日期
_RE_SIGN_DATE = re.compile(
    r"(?:签订日期|签署日期|签订时间|签约日期|合同签订时间)\s*[:：]?\s*"
    r"([0-9]{4}\s*[年\-/.]\s*[0-9]{1,2}\s*[月\-/.]\s*[0-9]{1,2})"
)
# 付款条款
_RE_PAYMENT = re.compile(
    r"(?:付款方式|付款条款|结算方式|付款条件|支付方式)\s*[:：]?\s*(\S.{3,60})"
)
# "付款方式"后面跟的不一定是条款，也可能只是章节标题（真实合同里
# "第六条付款方式及发票规范" 就被抓成了付款条款"及发票规范"）。
# 要求抓到的内容里至少有一个"像条款"的字眼，否则宁可空着。
_PAYMENT_HINTS = ("付", "款", "天", "日", "月", "%", "％", "账", "承兑", "结算", "批", "期")
# 往来对象候选：角色 → 名称。销售合同（out）对方是 甲方/需方/买方；
# 采购合同（in）对方是 乙方/供方/卖方。两边的都收，交给前端按方向挑。
#
# ⚠️ **冒号是硬条件**（不是可选）：去掉冒号后，正文里"乙方需在2个工作日内…"
# "甲方有权拒收…"全都会被当成"角色 + 名称"，回填进去的就是一句话。
# 中间允许一段括注："甲方（采购方/盖章）：湖南华邦建设有限公司" —— 真实合同的
# 盖章页就是这么写的，不容括注就抓不到真正的公司名。
_RE_PARTY = re.compile(
    r"(甲方|乙方|需方|供方|买方|卖方|购方|供货方|采购方|销售方)"
    r"(?:[（(][^）)\n]{0,14}[）)])?"
    r"\s*[:：]\s*"
    r"([^\s，。；;：()（）]{2,40})"
)
COUNTERPARTY_ROLES_OUT = ("甲方", "需方", "买方", "购方", "采购方")
COUNTERPARTY_ROLES_IN = ("乙方", "供方", "卖方", "供货方", "销售方")

# 角色后面跟的未必是名字。真实合同里"乙方需在2个工作日内出具调价确认单"会被
# 抓成对方单位 —— 一旦回填进去，用户就得自己去改一个看起来像公司名的句子。
# 所以候选还要过下面这道筛子（宁可漏、不可错：漏了用户手填，错了用户直接信了）。
_PARTY_BAD_LEAD = (
    "需", "应", "须", "在", "已", "可", "有", "无", "将", "未", "并", "且", "或",
    "如", "若", "按", "由", "向", "对", "承", "负", "全", "赔", "支", "开", "提",
    "视", "逾", "每", "各", "双", "本", "该", "其", "此", "收", "付", "签",
)
_PARTY_ORG_HINTS = (
    "公司", "集团", "厂", "中心", "研究院", "设计院", "事务所", "商行", "经营部",
    "合作社", "学院", "大学", "医院", "银行", "供应商", "经销商", "项目部", "工程处",
)
# 不像名字的"名字"：条款句子的零件。带这些字眼的基本就是把一句话当成了公司名。
# ⚠️ 刻意**不**用"含数字"来判 —— 客户档案里真的会有"…有限公司2024""某某工程处3队"，
# 用数字一票否决会误杀正常公司名，而误杀比漏填更烦人。
_PARTY_SENTENCE_HINTS = (
    "的", "需", "应", "须", "在", "并", "且", "或", "如", "若", "日内", "工作日",
    "有权", "全额", "承担", "视为", "逾期", "签字", "支付", "开具", "提供", "拒收",
    "返工", "赔偿", "违约", "损失", "确认单", "质量", "负责", "对账", "验收", "指令",
)
_PARTY_STAMP_HINTS = ("盖章", "签章", "公章", "单位名称", "名称：", "名称:")

# 明细行（同版式）：名称 数量 单价 金额 —— 文本层 PDF 常是这种
_RE_ITEM = re.compile(
    r"^(?P<name>\S.{1,38}?)\s+(?P<qty>[0-9]+(?:\.[0-9]+)?)\s+"
    r"(?P<price>[0-9][0-9,，]*(?:\.[0-9]{1,2})?)\s+"
    r"(?P<amount>[0-9][0-9,，]*(?:\.[0-9]{1,2})?)\s*$"
)

# 纯数字（数量）：整段只有数字与小数点，不允许千分位（"1,000"更可能是金额）
_RE_QTY = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_RE_MONEY = re.compile(r"^[0-9][0-9,，]*(?:\.[0-9]{1,2})?$")

_REVIEWABLE = (
    "title", "sign_date", "party_name", "payment_terms", "note",
)

# 明细行（带序号、每格一行）用的零件 —— 见 parse_fields 的"形态 ③"。
# 真实扫描件的表格经常被 OCR 拆成"一个单元格一行"，靠这组规则重组回一行货。
_RE_SEQ_NO = re.compile(r"^[0-9]{1,3}$")
_RE_NUM_FLEX = re.compile(r"^[0-9][0-9,，]*(?:\.[0-9]{1,4})?$")  # 单价格式宽松（73.901 这种也认）
_ITEM_UNITS = {
    "米", "台", "个", "套", "件", "只", "支", "根", "箱", "卷", "吨", "公斤", "千克",
    "kg", "m", "㎡", "平方米", "立方米", "组", "块", "包", "桶", "张", "片", "批", "项", "条", "盘",
}


def _normalize_money(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", "").replace("，", ""))
    except (TypeError, ValueError):
        return None
    return round(value, 2) if value > 0 else None


_RE_DATE_PARTS = re.compile(r"^\s*([0-9]{4})\s*[年\-/.]\s*([0-9]{1,2})\s*[月\-/.]\s*([0-9]{1,2})")


def _normalize_date(raw: str | None) -> str | None:
    """"2026年9月16日" → 2026-09-16。

    以前按"去掉所有非数字后必须正好 8 位"判断，OCR 出来的 "2026年9月16日" 去掉
    非数字只有 7 位（月是个位数），于是原样返回 → 表单里填不进 date 输入框。
    改成按年月日三组解析，个位数补零。
    """
    if not raw:
        return None
    match = _RE_DATE_PARTS.match(raw)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return raw


def _looks_like_money(raw: str, tail: str = "", near_symbol: bool = False) -> bool:
    """这个数字"像不像钱"。不像就丢掉 —— 宁可漏、不可错。

    · 紧跟 % 的一律不算（"暂定总价的30%作为预付款" 里的 30 是比例，不是金额）；
    · 前面紧挨着 ￥/¥ 的直接采信（合同里写钱的惯用写法）；
    · 其余要求"至少 4 位数 / 两位小数 / 带千分位"之一 —— 页数、份数、台数都过不了。
    """
    if tail[:1] in ("%", "％"):
        return False
    if near_symbol:
        return True
    body, _, decimals = raw.partition(".")
    if len(decimals) == 2:
        return True
    if "," in body or "，" in body:
        return True
    return len(body) >= 4


def _extract_amount(text: str) -> float | None:
    """金额候选：先按"金额/总价/合计"附近的数字找，再退回"带货币符号的最大数"。"""
    for match in _RE_AMOUNT.finditer(text):
        raw = match.group(1)
        near_symbol = text[max(0, match.start(1) - 1): match.start(1)] in ("¥", "￥")
        if not _looks_like_money(raw, text[match.end(): match.end() + 1], near_symbol):
            continue
        value = _normalize_money(raw)
        if value:
            return value

    # 兜底：整份文件里带货币符号的数，取最大的那个（合同总价通常是全篇最大的一笔）
    hits = [v for v in (_normalize_money(m.group(1)) for m in _RE_AMOUNT_SYMBOL.finditer(text)) if v]
    return max(hits) if hits else None


def _match_seq_item(lines: list[str], index: int) -> tuple[dict[str, object], int] | None:
    """形态 ③：序号打头、每个单元格独占一行的表格行（真实合同附件一就是这种）。

    OCR 把表格按检测块切出来，于是一行货会变成：
        1 / ZRC-YJY23-0.6/1kV-3x25 / 米 / 4654 / 100.81 / 469169.74
    6 行分别是 序号 / 品名 / 单位 / 数量 / 单价 / 金额（没有单位列时 5 行）。

    ⚠️ 唯一敢认的依据是 **数量 × 单价 ≈ 金额**（允许 0.5% 或 1 元的误差 ——
    合同里的单价常被四舍五入到分，乘出来差几毛很正常）。没有这条校验，
    页码、日期、条款编号都会被拼成"明细行"，那比不认更糟。
    """
    total = len(lines)
    if index >= total or not _RE_SEQ_NO.match(lines[index].strip()):
        return None

    for span in (5, 4):  # 5 = 带单位列；4 = 没有单位列（不含序号那行）
        end = index + 1 + span
        if end > total:
            continue
        chunk = [line.strip() for line in lines[index + 1: end]]
        if span == 5:
            name, unit, qty, price, amount = chunk
            if unit.lower() not in _ITEM_UNITS:
                continue
        else:
            name, qty, price, amount = chunk
            unit = ""
        if not _RE_NUM_FLEX.match(qty) or not _RE_NUM_FLEX.match(price) or not _RE_NUM_FLEX.match(amount):
            continue
        if not 2 <= len(name) <= 40:
            continue
        if any(word in name for word in ("名称", "数量", "单价", "金额", "序号", "单位", "合计")):
            continue

        def _num(raw: str) -> float | None:
            try:
                return float(raw.replace(",", "").replace("，", ""))
            except ValueError:
                return None

        quantity, unit_price, money = _num(qty), _num(price), _num(amount)
        if not quantity or not unit_price or not money or quantity <= 0:
            continue
        if abs(quantity * unit_price - money) > max(1.0, money * 0.005):
            continue

        return (
            {
                "product_name": name,
                "unit": unit,
                "quantity": quantity,
                "unit_price": round(unit_price, 4),
                "amount": round(money, 2),
            },
            span + 1,
        )
    return None


def _party_name_score(name: str, line: str) -> int:
    """给往来对象候选打分，返回 0 表示"这不是个名字"，直接丢。

    带公司字样的名字**直接采信**（"…有限公司2024"这种带数字也算公司名）；
    不带的才走禁用规则。反过来做就会误杀正常公司名，而那比漏掉更麻烦。
    """
    if not name or not 2 <= len(name) <= 30:
        return 0
    if any(hint in name for hint in _PARTY_ORG_HINTS):
        score = 3
    else:
        if len(name) > 24:  # 一句话而不是一个名字
            return 0
        if name[0] in _PARTY_BAD_LEAD:  # 「需…」「应…」「在…」
            return 0
        if any(hint in name for hint in _PARTY_SENTENCE_HINTS):  # 「…出具调价确认单」
            return 0
        score = 1
    if any(hint in line for hint in _PARTY_STAMP_HINTS):  # 出现在盖章/单位名称那行
        score += 2
    return score


def _clean_text_layer(text: str) -> list[str]:
    """文本层也要按"行"切出来 —— 字段提取和明细匹配都吃行，不吃整坨。"""
    lines = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line:
            lines.append(line)
    return lines


def extract_text(payload: bytes, filename: str) -> dict[str, object]:
    """三关流水线。返回 {provider, engine, page_count, truncated, lines}。

    ⚠️ 引擎抛异常会往上抛，由路由层决定怎么留痕（状态置 failed），这里不吞。
    """
    suffix = Path(filename or "").suffix.lower()

    if suffix == ".pdf":
        # ⚠️⚠️ 三个函数**必须一起 import**：Python 把函数体内的任何 import 都当成
        # 「局部名字绑定」，哪怕它在另一个分支里。之前这里只导入了前两个，
        # 扫描件分支却调用 `_ocr_image_bytes` → 必然抛
        # `UnboundLocalError: cannot access local variable '_ocr_image_bytes'`，
        # 而且带文本层的 PDF 提前返回了、测不出来 —— 只有真实扫描件才会踩。
        from app.api.v1.routes.erp_invoice import (
            _ocr_image_bytes,
            _pdf_page_pngs,
            _pdf_text_layer,
        )

        text_layer = _pdf_text_layer(payload)
        lines = _clean_text_layer(text_layer)
        if sum(1 for line in lines for ch in line if "\u4e00" <= ch <= "\u9fff") >= _MIN_TEXT_LAYER_CHARS:
            return {"provider": "pdf_text", "engine": "pdf_text", "page_count": 0, "truncated": False, "lines": lines}

        # 只渲染需要识别的前 MAX_PAGES 页（+1 页仅用来判断"后面还有没有"）。
        # 不做这个上限时，几十页的合同会一次性把所有页按 zoom=3 渲成几十 MB 的 PNG，
        # 内存和耗时都不可控 —— 真实大合同会直接把服务拖住。
        pages = _pdf_page_pngs(payload, zoom=3, max_pages=MAX_PAGES + 1)
        truncated = len(pages) > MAX_PAGES
        all_lines: list[str] = []
        engine = ""
        for index, page_png in enumerate(pages[:MAX_PAGES]):
            page_engine, page_lines = _ocr_image_bytes(page_png)
            engine = engine or page_engine
            all_lines.append(f"—— 第 {index + 1} 页 ——")
            all_lines.extend(page_lines)
        return {
            "provider": "ocr",
            "engine": engine or "fallback",
            "page_count": min(len(pages), MAX_PAGES),
            "truncated": truncated,
            "lines": all_lines,
        }

    if suffix in IMAGE_SUFFIXES:
        from app.api.v1.routes.erp_invoice import _ocr_image_bytes

        engine, lines = _ocr_image_bytes(payload)
        return {"provider": "ocr", "engine": engine or "fallback", "page_count": 1, "truncated": False, "lines": lines}

    raise ValueError("只支持 PDF / PNG / JPG / BMP 原件；Word 文档请先另存为 PDF 再上传识别")


def parse_fields(lines: list[str], direction: str = "out") -> dict[str, object]:
    """从识别文本行里提取候选字段。所有结果都是**候选**，不是结论。"""
    text = "\n".join(lines)
    fields: dict[str, object] = {}

    match = _RE_CONTRACT_NO.search(text)
    if match:
        fields["contract_no"] = match.group(1).strip("（）()")

    # 标题：含"合同"且不太长的第一行 —— 太长的多半是条款，太短的可能是页眉
    for line in lines:
        stripped = line.strip("—-：: ")
        if "合同" in stripped and 6 <= len(stripped) <= 40 and not stripped.startswith("——"):
            fields["title"] = stripped
            break

    amount = _extract_amount(text)
    if amount:
        fields["total_amount"] = amount

    match = _RE_SIGN_DATE.search(text)
    if match:
        fields["sign_date"] = _normalize_date(match.group(1))

    match = _RE_PAYMENT.search(text)
    if match:
        payment = match.group(1).strip(" ：:，,。；;")
        # 只有"像条款"的才收（见 _PAYMENT_HINTS 的注释：章节标题也会被正则撞上）
        if len(payment) >= 4 and any(hint in payment for hint in _PAYMENT_HINTS):
            fields["payment_terms"] = payment

    # 往来对象候选：按角色分组。counterparty = 合同"对方"（销售的对方是客户）
    counterpart_roles = COUNTERPARTY_ROLES_OUT if direction == "out" else COUNTERPARTY_ROLES_IN
    seen: set[str] = set()
    party_candidates: list[dict[str, str]] = []
    best_score = 0
    for match in _RE_PARTY.finditer(text):
        role, name = match.group(1), match.group(2).strip()
        key = f"{role}:{name}"
        if key in seen or not name:
            continue
        seen.add(key)
        # 取这一条匹配所在的行，用来判断它是不是"盖章 / 单位名称"那种正式写法
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line = text[line_start: line_end if line_end != -1 else len(text)]
        score = _party_name_score(name, line)
        if score <= 0:
            continue
        party_candidates.append(
            {"role": role, "name": name, "is_counterparty": role in counterpart_roles}
        )
        # 取**分数最高**的那个，而不是第一个 —— 真实合同里"乙方需在2个工作日内…"
        # 这类句子出现得比盖章页早得多，按先到先得会一路填错。
        if role in counterpart_roles and score > best_score:
            fields["party_name"] = name
            best_score = score

    # 明细行。OCR 引擎对表格的输出有两种形态，都要认：
    #   ① 文本层 PDF：一行四列「名称 数量 单价 金额」→ _RE_ITEM；
    #   ② 扫描件 OCR：rapidocr 按检测块输出，**每个单元格一行** →
    #      「名称 / 数量 / 单价 / 金额」连续 4 行一组。实测（2026-10-19）：
    #      画出来的表格被拆成 '高压柜' '3' '150000.00' '450000.00' 四行。
    def _to_money(raw: str) -> float | None:
        return _normalize_money(raw)

    items: list[dict[str, object]] = []
    index = 0
    total_lines = len(lines)
    while index < total_lines:
        line = lines[index]
        if line.startswith("——"):
            index += 1
            continue

        # 形态 ①：同一行四列
        match = _RE_ITEM.match(line)
        if match:
            quantity = float(match.group("qty"))
            price = _to_money(match.group("price"))
            amount = _to_money(match.group("amount"))
            if price and amount and quantity > 0:
                items.append(
                    {
                        "product_name": match.group("name").strip(),
                        "quantity": quantity,
                        "unit_price": price,
                        "amount": amount,
                    }
                )
            index += 1
            continue

        # 形态 ③：序号打头的逐单元格表格（扫描件真实排版，见 _match_seq_item）
        matched = _match_seq_item(lines, index)
        if matched:
            item, step = matched
            items.append(item)
            index += step
            continue

        # 形态 ②：连续 4 行 = 名称 / 数量 / 单价 / 金额
        if (
            index + 3 < total_lines
            and not _RE_QTY.match(line)
            and not _RE_MONEY.match(line)
            and _RE_QTY.match(lines[index + 1] or "")
            and _RE_MONEY.match(lines[index + 2] or "")
            and _RE_MONEY.match(lines[index + 3] or "")
        ):
            name = line.strip()
            quantity = float(lines[index + 1])
            price = _to_money(lines[index + 2])
            amount = _to_money(lines[index + 3])
            # 名称要像"品名"：2-40 个字符、不是表头、不是日期/编号行
            if (
                price
                and amount
                and quantity > 0
                and 2 <= len(name) <= 40
                and not any(word in name for word in ("名称", "数量", "单价", "金额", "编号", "日期"))
                and not _RE_SIGN_DATE.search(name)
            ):
                items.append(
                    {
                        "product_name": name,
                        "quantity": quantity,
                        "unit_price": price,
                        "amount": amount,
                    }
                )
            index += 4
            continue

        index += 1

    return {
        "fields": fields,
        "party_candidates": party_candidates[:8],
        "items": items[:20],
    }


def build_ocr_json(result: dict[str, object], fields_pack: dict[str, object], filename: str) -> str:
    """引擎原始输出 + 提取候选，整体 JSON 化落库（人工核对时要能看到全貌）。"""
    import json

    return json.dumps(
        {
            "recognized_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "source_file": filename,
            "provider": result.get("provider"),
            "engine": result.get("engine"),
            "page_count": result.get("page_count"),
            "truncated": result.get("truncated"),
            "lines": result.get("lines") or [],
            "fields": fields_pack.get("fields") or {},
            "party_candidates": fields_pack.get("party_candidates") or [],
            "items": fields_pack.get("items") or [],
        },
        ensure_ascii=False,
    )
