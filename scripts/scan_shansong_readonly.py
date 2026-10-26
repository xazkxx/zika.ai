"""陕送票历史数据 —— 只读扫描 + 结构化解析（**绝不写库、绝不改原文件**）

v2 相比 v1 的两处关键修正（v1 会把"对账"目录那批表解析错位）：

  ① **"没有表头的表"要按位置解析。**
     `对账/*.xlsx` 那批是"只留着数据、表头行被删掉"的表：
     A 列是空的（或被填成序号 1..N），数据从 B 列开始，
     列序固定为 `日期 | 仓库 | 单号 | 客户/项目 | 商品名称 | 送货日期 | 规格 | 型号 | 单位 | … | 数量`。
     v1 把第一行数据当成了表头，于是 "客户名称 = 寨卡仓库"、"商品名称 = XS202509120004"，
     整张表往下错一列。这类表改用 `LAYOUT_BY_POSITION` 直接按位置取值。

  ② **表头行之前的"序号列"会让整块右移一格**（`蒲白750` 那张：A 列是序号 1/2/3…）。
     所以表头一旦识别出来，就用**表头里的列名**定位每一列，
     而不是假设"客户名称就一定是第 4 列"。

产出（全部落在 `artifacts/scan_shansong/`，与原始目录无关）：
  · scan.json         —— 原始结构化数据（含每个文件的 sheet / 表头 / 行数 / 提取片段）
  · file_index.csv    —— 文件清单（给人看）
  · rows.jsonl        —— 解析出来的**明细行**（导入脚本的输入格式预览，一行一条 JSON）

跑法：
  .venv\\Scripts\\python.exe scripts/scan_shansong_readonly.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:/Users/admi/Desktop/国网/陕送票")
OUT = Path(__file__).resolve().parent.parent / "artifacts" / "scan_shansong"
OUT.mkdir(parents=True, exist_ok=True)

EXCEL_EXT = {".xlsx", ".xlsm", ".xls"}
PDF_EXT = {".pdf"}
SCAN_ROWS = 40
MAX_ROWS = 20000

# ── 列名 → 语义（别名要覆盖这份数据里真实出现过的所有写法）──
# ⚠️ `party` 里**绝对不能**放"单位"：绝大多数表里"单位"是计量单位（个/套/台），
#    放进去会把整块错位（实测 `消材计划` 的 party 变成"个"、`金属制品采购价税明细`
#    的 party 变成"数量"）。"单位"只在"确实没有客户列"时才作为最后兜底。
COL_ALIASES = {
    "date": ["日期", "开单日期", "销售日期", "出库日期"],
    "warehouse": ["仓库", "发货仓库", "出货仓库"],
    "doc_no": ["单号", "单据号", "出库单号"],
    "party": ["客户名称", "客户/项目", "客户项目", "项目名称", "实际工程", "购方名称", "购买方"],
    "product": ["商品名称", "货物名称", "物料描述", "产品名称", "品名", "商品"],
    "spec": ["规格型号", "规格"],
    "model": ["型号"],
    "unit": ["计量单位", "单位"],
    "qty": ["商品数量", "数量", "出库数量"],
    "price": ["单价", "销售单价"],
    "amount": ["金额", "金额（元）", "销售金额", "价税合计", "含税金额"],
    "tax": ["税额", "税额（元）"],
    "seq": ["序号"],
}

# 没有表头那批表的固定列位置（0 基，B 列 = 1）
LAYOUT_BY_POSITION = {
    "date": 1, "warehouse": 2, "doc_no": 3, "party": 4,
    "product": 5, "deliver_date": 6, "spec": 7, "model": 8,
    # ⚠️ 10/11/12 是序列号/颜色/尺码，13 商品数量、14 单价、15 金额、16 单据备注、17 备注
    "unit": 9, "qty": 13, "price": 14, "amount": 15,
}

HEADER_HINTS = tuple({a for v in COL_ALIASES.values() for a in v})
MIN_HEADER_CELLS = 2


# ─────────────────────────────────────────────────────────────────────
# 通用
# ─────────────────────────────────────────────────────────────────────
def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def collect_files():
    excel, pdf, skipped = [], [], []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in EXCEL_EXT and suffix not in PDF_EXT:
            continue
        if path.name.startswith("~$") or path.stat().st_size == 0:
            skipped.append(path)
            continue
        (excel if suffix in EXCEL_EXT else pdf).append(path)
    return excel, pdf, skipped


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


NUM_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")


def to_number(value):
    """'1,234.50' / 1234.5 / '¥120' → float；不是数字返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    if not text or not NUM_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_date(value) -> str:
    text = cell_text(value)
    if not text:
        return ""
    m = re.match(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text


# ─────────────────────────────────────────────────────────────────────
# 表头识别
# ─────────────────────────────────────────────────────────────────────
def score_header(row: list) -> int:
    texts = [cell_text(c) for c in row]
    non_empty = [t for t in texts if t]
    if len(non_empty) < MIN_HEADER_CELLS:
        return 0
    hits = sum(1 for t in non_empty if any(h in t for h in HEADER_HINTS))
    # 必须命中至少 3 个业务列名，否则只是普通数据行
    if hits < 3:
        return 0
    numeric = sum(1 for t in non_empty if NUM_RE.match(t))
    if numeric >= len(non_empty) * 0.6:
        return 0
    return hits * 10 + len(non_empty)


def find_header(rows: list) -> tuple[int, list[str]]:
    best_at, best_score = -1, 0
    for index, row in enumerate(rows[:SCAN_ROWS]):
        score = score_header(row)
        if score > best_score:
            best_at, best_score = index, score
    if best_at < 0:
        return -1, []
    header = [cell_text(c) for c in rows[best_at]]
    while header and not header[-1]:
        header.pop()
    return best_at, header


def map_columns(header: list[str]) -> dict[str, int]:
    """列名 → 列下标。同名只取第一个。"""
    mapping = {}
    for key, aliases in COL_ALIASES.items():
        for index, name in enumerate(header):
            if not name:
                continue
            if any(alias == name or alias in name for alias in aliases):
                mapping.setdefault(key, index)
                break
    return mapping


def has_header_layout(mapping: dict[str, int]) -> bool:
    """认表头的前提：至少认出"客户/项目"和"商品"两列，否则当无表头处理。"""
    return "party" in mapping and "product" in mapping


def detect_position_shift(rows: list[list], start: int, mapping: dict[str, int]) -> int:
    """position 布局下判断这张表整体该不该右移一格。

    ⚠️ 踩过的坑：看到 A 列是"序号"就盲目 +1，会把**本来正确**的映射推歪
    —— `西安东750（包2）.xls / 蒲白750` 的 A 列虽然写着序号，但
    `LAYOUT_BY_POSITION`（date=1…qty=13）对它已经读得完全正确，
    加 1 之后 party 变成商品名、product 变成送货日期、金额全空。

    所以判据不能只看 A 列，要**比两种偏移哪种更像对账单**：
      · party 列里像公司/工程名的行数（含 公司/工程/分公司/千伏/项目 等字样）
      · 金额列非空的行数
    得分高的那个偏移胜出。得分相同则保持 0（不折腾原映射）。
    """
    sample = [r for r in rows[start:] if any(cell_text(c) for c in r)][:50]
    if not sample:
        return 0

    def score(shift: int) -> int:
        s = 0
        for row in sample:
            rec = row_to_record(row, mapping, shift)
            if not rec:
                continue
            if rec["amount"] is not None:
                s += 2
            if rec["price"] is not None:
                s += 1
            party = rec["party"] or ""
            if re.search(r"公司|工程|项目|分公司|千伏|变电站|供电|线路", party):
                s += 3
        return s

    base, shifted = score(0), score(1)
    return 1 if shifted > base else 0


# ─────────────────────────────────────────────────────────────────────
# 行 → 结构化明细
# ─────────────────────────────────────────────────────────────────────
def row_to_record(row: list, mapping: dict[str, int], shift: int = 0) -> dict | None:
    def pick(key):
        index = mapping.get(key)
        if index is None:
            return None
        index += shift
        return row[index] if index < len(row) else None

    party = cell_text(pick("party"))
    product = cell_text(pick("product"))
    if not party and not product:
        return None
    qty = to_number(pick("qty"))
    price = to_number(pick("price"))
    amount = to_number(pick("amount"))
    return {
        "date": normalize_date(pick("date")),
        "warehouse": cell_text(pick("warehouse")),
        "doc_no": cell_text(pick("doc_no")),
        "party": party,
        "product": product,
        "spec": cell_text(pick("spec")),
        "model": cell_text(pick("model")),
        "unit": cell_text(pick("unit")),
        "qty": qty,
        "price": price,
        "amount": amount,
        "amount_derived": amount is None and qty is not None and price is not None,
    }


# ─────────────────────────────────────────────────────────────────────
# Excel 读
# ─────────────────────────────────────────────────────────────────────
def read_xlsx_raw(path: Path) -> list[tuple[str, list[list]]]:
    from openpyxl import load_workbook

    # ⚠️ 不能用 read_only=True：三个「寨纬/华诺迈账户交易明细」文件没有 <dimension> 标签，
    # read_only 模式下 openpyxl 只吐出 1 行（实测 max_row 报 1，实际 20 行）。
    # 这批文件很小（最大几百 KB），普通模式完全够用。
    book = load_workbook(filename=str(path), data_only=True)
    try:
        out = []
        for ws in book.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append(list(row))
                if len(rows) > MAX_ROWS:
                    break
            out.append((ws.title, rows))
        return out
    finally:
        book.close()


def read_xls_raw(path: Path) -> list[tuple[str, list[list]]]:
    import xlrd

    book = xlrd.open_workbook(filename=str(path), on_demand=True)
    try:
        out = []
        for sheet in book.sheets():
            rows = []
            for r in range(min(sheet.nrows, MAX_ROWS)):
                rows.append([sheet.cell_value(r, c) for c in range(sheet.ncols)])
            out.append((sheet.name, rows))
        return out
    finally:
        book.release_resources()


# 这些 sheet 是"汇总/透视/模板"，明细行不是业务单据，只统计不进成交明细
SKIP_SHEET_HINTS = ("汇总", "总表", "hidden", "Sheet1", "项目信息导入")


# ─────────────────────────────────────────────────────────────────────
# 表分类
#
# 这批 Excel 混着六七种完全不同的表。导入前必须先把它们分开，
# 否则"银行流水"会被当成销售明细、"项目导入模板"会被当成客户档案。
#
#   sales_statement  销售对账单（真正的出库/销售明细）★ 只有这类要导入
#   purchase_detail  采购价税明细（进项，商品名是"金属制品套筒"等，非我方销售）
#   material_plan    消材计划（物料清单 + 各班组需求量，不是销售）
#   item_import      项目信息导入模板（商品档案的候选清单）
#   bank_flow        活期账户交易明细（银行流水，不是单据）
#   other            其它
# ─────────────────────────────────────────────────────────────────────
TABLE_KINDS = {
    "sales_statement": "销售对账单",
    "material_list": "物资领用清单",
    "purchase_detail": "采购价税明细",
    "material_plan": "消材计划",
    "item_import": "项目信息导入模板",
    "bank_flow": "银行流水",
    "other": "其它",
}


def classify_table(path_name: str, sheet: str, header: list[str], path: str = "") -> str:
    joined = "|".join(h for h in header if h)
    flat = f"{path}|{path_name}|{sheet}|{joined}"

    if "活期账户" in flat or "交易明细" in flat or "交易流水号" in joined:
        return "bank_flow"
    if "项目信息导入" in flat or ("商品和服务税收分类编码" in joined):
        return "item_import"
    if "采购价税明细" in flat or "采购价" in joined or "毛利率" in joined:
        return "purchase_detail"
    if "物料编码" in joined or "物料描述" in joined or "数量（小计）" in joined:
        return "material_plan"
    # ⚠️ "物资清单/采购明细" 必须排在"对账"前面：它们路径里也带「对账/」，
    #    但内容只有 商品+数量，没有单价金额，是领用清单不是销售凭证。
    if "物资清单" in flat or "采购明细" in flat:
        return "material_list"
    if "对账" in flat:
        return "sales_statement"
    if ("客户" in joined or "项目" in joined) and ("商品" in joined or "货物" in joined):
        return "sales_statement"
    return "other"


def classify_by_path(path: str, name: str) -> str:
    """没有表头（`对账/` 目录那批）时只能靠路径判类型。

    ⚠️ 这里必须把「物资清单」和「销售对账单」分开：
    `物资清单` 那批只有 商品+数量，**没有单价也没有金额**（实测 262 行 qty 有、price 全空），
    它是领用/备料清单，不是销售凭证。混进销售会让「金额」一列全空。
    """
    flat = f"{path}|{name}"
    if "活期账户" in flat or "交易明细" in flat:
        return "bank_flow"
    if "物资清单" in flat or "采购明细" in flat:
        return "material_list"
    if "对账" in flat:
        return "sales_statement"
    return "other"


def is_detail_sheet(name: str, mapping: dict[str, int]) -> bool:
    if not has_header_layout(mapping):
        return False
    if name.lower().startswith("hidden"):
        return False
    return True


def summarize_sheet(name: str, rows: list[list], path_name: str = "") -> tuple[dict, list[dict]]:
    header_at, header = find_header(rows)
    mapping = map_columns(header) if header_at >= 0 else {}
    layout = "header"

    # 只有"认表头 + 认出客户列 + 认出商品列"三者都成立，才走表头布局。
    # 否则一律回退到"无表头表"的固定列位置（对账目录那批）。
    if not has_header_layout(mapping):
        mapping = dict(LAYOUT_BY_POSITION)
        layout = "position"
        header_at = -1

    # 位置布局的表，必须真的是对账单的样子——A 列空/B 列日期。
    # 用"前 20 行里有几行 B 列长得像日期"来验证，否则整表不采信。
    if layout == "position":
        probe = 0
        hit = 0
        for row in rows[:20]:
            if not any(cell_text(c) for c in row):
                continue
            probe += 1
            if len(row) > 1 and re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", cell_text(row[1])):
                hit += 1
        if probe and hit / probe < 0.5:
            return {
                "sheet": name, "total_rows": len(rows), "layout": "skipped",
                "header_row": header_at, "header": header, "data_row_count": 0,
                "table_kind": "other", "table_kind_label": "其它",
                "skip_reason": "无表头且 B 列不像日期，放弃按位置解析",
                "sample_rows": [[cell_text(c) for c in r] for r in rows[:2]],
            }, []

    table_kind = classify_table(path_name, name, header)

    records = []
    start = header_at + 1 if header_at >= 0 else 0
    # position 布局整表统一裁决一次偏移（逐行判断会让同一张表前后不一致）
    shift = detect_position_shift(rows, start, mapping) if layout == "position" else 0
    for row in rows[start:]:
        if not any(cell_text(c) for c in row):
            continue
        record = row_to_record(row, mapping, shift)
        if record is None:
            continue
        if layout == "position" and not record["date"]:
            continue
        # 去掉"表头被当成数据行"的情况
        if record["party"] in ("客户名称", "项目名称", "客户", "数量") or \
           record["product"] in ("商品名称", "单价（元）", "商品", "物料描述"):
            continue
        records.append(record)

    sheet_info = {
        "sheet": name,
        "total_rows": len(rows),
        "layout": layout,
        "header_row": header_at,
        "header": header,
        "data_row_count": len(records),
        "table_kind": table_kind,
        "table_kind_label": TABLE_KINDS[table_kind],
        "is_detail": table_kind == "sales_statement" or (
            is_detail_sheet(name, map_columns(header)) if header_at >= 0 else False
        ),
        "sample_rows": [
            [cell_text(c) for c in r] for r in rows[start:start + 2]
        ],
    }
    return sheet_info, records


# ─────────────────────────────────────────────────────────────────────
# PDF —— 必须走**坐标**，不能走文本流
#
# 全电发票是绝对定位排版：`get_text("text")` 里 "发票号码：" 后面紧跟的是下一个
# 标签（"开票日期："），真正的值排在文本流很后面。所以只能拿 `get_text("words")`
# 的 (x0,y0,x1,y1,word)，再按几何位置取"标签右侧/下方的那个词"。
#
# 实测版式（595×397，101 张发票全部一致）：
#   发票号码：@x438,y32   → 值 @x482,y32
#   开票日期：@x438,y49   → 值 @x482,y49（"2025年12月05日"）
#   名称：@x33,y96  (购买方) → 值 @x57,y96   （x < 300 的一侧）
#   名称：@x318,y96 (销售方) → 值 @x340,y96  （x > 300 的一侧）
#   价税合计（大写）@x48,y280 → 大写值 @x178,y278
#   （小写）@x407,y280       → 小写值 @x441,y277  "¥5010.00"
#   明细行：项目名称 x≈13 / 规格型号 x≈119 / 单位 x≈198
#           数量 x≈272-290 / 单价 x≈293-361 / 金额 x≈397-434
#           税率 x≈467 / 税额 x≈553-583
#
# 三类文件靠标签区分：
#   有"发票号码" → 发票
#   有"凭证号"   → 银行回单（付款单/回单_xxxx.pdf）
#   words 为 0   → 扫描件，没有文字层，需 OCR（本轮跳过并标注）
# ─────────────────────────────────────────────────────────────────────
RE_TITLE = re.compile(r"电子发票[（(][^)）]{1,10}发票[）)]|增值税[^，。\n]{0,8}发票")
RE_MONEY = re.compile(r"^[¥￥]?\s*([\d,]+\.\d{2})$")
RE_TAXID = re.compile(r"^[0-9A-Z]{15,20}$")

Y_TOL = 4.0        # 同一基线的容差


def clean(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", text or "").strip()


def money(text: str):
    """'¥5010.00' / '4,960.40' → 5010.0；不是金额返回 None。"""
    m = RE_MONEY.match(clean(text))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def pdf_words(path: Path) -> tuple[list, float, float]:
    """返回 (words, 页面宽, 页面高)。words 元素 = (x0,y0,x1,y1,text)。"""
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        words: list = []
        width = height = 0.0
        for page in doc:
            rect = page.rect
            width, height = rect.width, rect.height
            for w in page.get_text("words"):
                words.append((float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])))
        return words, width, height
    finally:
        doc.close()


def find_label(words: list, needle: str):
    """找标签词（可同时命中多个，按出现顺序返回）。"""
    return [w for w in words if needle in w[4]]


def value_right_of(words: list, label, max_gap: float = 120.0):
    """标签**右侧、同一基线**最近的一个词。

    ⚠️ 不能要求 `w[0] >= label_x1`：标签词自带尾冒号，宽度比视觉右沿大，
    实测值起点 481.88 比标签右沿 483.41 还**靠左 1.53**。
    所以判据是"值起点在标签**起点**右侧、且纵向同基线"。
    """
    if label is None:
        return None
    lx0, ly0, lx1, ly1, ltx = label
    cy = (ly0 + ly1) / 2
    best = None
    for w in words:
        # ⚠️ 不能写 `w is label`：label 可能是元组副本，身份比较恒假
        if w[0] == lx0 and w[1] == ly0 and w[4] == ltx:
            continue
        if abs((w[1] + w[3]) / 2 - cy) > Y_TOL:
            continue
        if w[0] <= lx0 + 1.0:          # 必须在标签起点右侧
            continue
        gap = w[0] - lx1
        if gap > max_gap:
            continue
        if best is None or gap < best[0]:
            best = (gap, w)
    return best[1] if best else None


def value_below(words: list, label, max_dy: float = 26.0):
    """标签**正下方**（水平有交叠、y 更大）最近的一个词。"""
    if label is None:
        return None
    lx0, ly0, lx1, ly1, ltx = label
    best = None
    for w in words:
        if w[0] == lx0 and w[1] == ly0 and w[4] == ltx:
            continue
        dy = w[1] - ly1
        if dy < -2.0 or dy > max_dy:
            continue
        # 水平交叠：词的右沿必须越过标签左沿，且词的左沿不能越过标签右沿太远
        if w[2] <= lx0 or w[0] > lx1 + 20:
            continue
        if best is None or dy < best[0]:
            best = (dy, w)
    return best[1] if best else None


def parse_invoice_by_coords(words: list, width: float) -> dict:
    """按坐标从全电发票里抽要素。

    版式存在两代：
      A. 2025 全电票（101 张里的 99 张）：标签带**全角冒号**（`发票号码：`），
         值排在标签右侧。
      B. 旧版数电票（渭南开进来的票里有 2 张）：标签带**半角冒号**（`名称:`），
         且 `发票号码：2561...` 是**一个整词**（标签值连在一起），
         购买方/销售方靠 `购 买 方 信 息` / `销 售 方 信 息` 的分界 y 定位。
    所以两条路都要走，A 抽不到的字段用 B 补。
    """
    mid_x = (width or 595.0) / 2

    # —— 发票号码：先试"标签右侧"，再试"整词含号码" ——
    no = ""
    lab = find_label(words, "发票号码")
    if lab:
        v = value_right_of(words, lab[0])
        no = clean(v[4]) if v else ""
    if not no:
        for w in words:
            m = re.search(r"(?:发票号码|号码)[:：]?\s*(\d{8,20})", w[4])
            if m:
                no = m.group(1)
                break
    if not no:
        for w in words:
            if re.fullmatch(r"\d{20}", w[4]):
                no = w[4]
                break

    # —— 开票日期：同一路数 ——
    date = ""
    lab = find_label(words, "开票日期")
    if lab:
        v = value_right_of(words, lab[0])
        if v:
            date = _norm_invoice_date(v[4])
    if not date:
        for w in words:
            got = _norm_invoice_date(w[4])
            if got:
                date = got
                break

    # —— 购买方 / 销售方名称 ——
    buyer = seller = ""
    buyer_tax = seller_tax = ""

    # 路 A：两个"名称："标签，靠 x 分左右
    names = find_label(words, "名称：")
    if len(names) >= 2:
        names = sorted(names, key=lambda w: w[0])[:2]
        vb = value_right_of(words, names[0], max_gap=200)
        vs = value_right_of(words, names[1], max_gap=200)
        buyer = clean(vb[4]) if vb else ""
        seller = clean(vs[4]) if vs else ""

    # 路 B：按"购买方信息"/"销售方信息"的分界 y，取区间内最长的中文串
    if not buyer or not seller:
        y_buy = y_sell = None
        for w in words:
            if "购" == w[4] and y_buy is None:
                y_buy = w[1]
            if "销" == w[4] and y_sell is None and (y_buy is None or w[1] >= y_buy - 2):
                y_sell = w[1]
        if y_buy is not None and y_sell is not None:
            # 左右两侧各取一次，靠 x 分，不靠长度。
            # ⚠️ 不能只按长度取最长：购买方和销售方常常一样长（都是十几字公司名），
            #    实测 `西安华诺迈贸易有限公司` 与 `蒲城县迷彩劳保土产店` 会被判成同一个。
            def pick_side(y_from, y_to, left: bool):
                cands = []
                for w in words:
                    if not (y_from - 2 <= w[1] < y_to):
                        continue
                    if (w[0] < mid_x) != left:
                        continue
                    t = w[4]
                    # 旧版票的"名称:某某公司"是**一个整词**，不能因为它含"名称"就扔掉；
                    # 只排除纯粹的标签词和"信息/识别号"这类。
                    body = re.sub(r"^名称\s*[:：]\s*", "", t)
                    if body != t:
                        t = body
                    elif "名称" in t or "信息" in t:
                        continue
                    if t.startswith(("*", "购", "销")) or "识别号" in t or "信用代码" in t:
                        continue
                    if not re.search(r"[\u4e00-\u9fa5]{4,}", t):
                        continue
                    cands.append((len(t), clean(t)))
                return max(cands)[1] if cands else ""

            buyer = buyer or pick_side(y_buy, y_sell, True)
            seller = seller or pick_side(y_sell, y_sell + 90, False)

    # 路 C（最后兜底）：整词内联形态——`名称:西安华诺迈贸易有限公司`
    if not buyer or not seller:
        inline = []
        for w in words:
            m = re.match(r"^名称\s*[:：]\s*(.+)$", w[4])
            if m and len(m.group(1)) >= 4 and not m.group(1).startswith("*"):
                inline.append((w[0], clean(m.group(1))))
        inline.sort()
        if len(inline) >= 2:
            buyer = buyer or inline[0][1]
            seller = seller or inline[1][1]
        elif len(inline) == 1:
            if inline[0][0] < mid_x:
                buyer = buyer or inline[0][1]
            else:
                seller = seller or inline[0][1]

    # 兜底：销售方还是空的，或拿到的是商品名（`*塑料制品*给水管`）——
    # 旧版发票里"销售方名称"这一行偶尔整行丢失，那就退而取"销售方区域"里
    # x>mid_x、y 在购买方名称同一带的非商品词。
    if not seller or seller.startswith("*"):
        y_buy = None
        for w in words:
            if w[4] == "购":
                y_buy = w[1]
                break
        if y_buy is not None:
            cands = [
                w for w in words
                if w[0] >= mid_x and abs(w[1] - y_buy) < 20
                and re.search(r"[\u4e00-\u9fa5]{4,}", w[4])
                and not w[4].startswith(("*", "名称", "销", "售"))
                and "识别号" not in w[4] and "信用代码" not in w[4]
            ]
            if cands:
                seller = max(cands, key=lambda w: len(w[4]))[4]

    # 纳税人识别号：同一 y 带、x 分左右
    tax_words = [w for w in words if RE_TAXID.match(w[4])]
    # 路 C 的整词形态：`统一社会信用代码/纳税人识别号:91610131MACQ0JAT5J`
    if not tax_words:
        for w in words:
            m = re.search(r"识别号\s*[:：]\s*([0-9A-Z]{15,20})", w[4])
            if m:
                tax_words.append((w[0], w[1], w[2], w[3], m.group(1)))
    for w in sorted(tax_words, key=lambda w: w[0]):
        if w[0] < mid_x and not buyer_tax:
            buyer_tax = w[4]
        elif w[0] >= mid_x and not seller_tax:
            seller_tax = w[4]

    # —— 价税合计 ——
    total = None
    lab = find_label(words, "小写")
    if lab:
        v = value_right_of(words, lab[0], max_gap=130)
        if v:
            total = money(v[4])
    if total is None:
        # 路 C：整词内联 `（小写）¥4500.00`
        for w in words:
            m = re.search(r"[（(]小写[）)]\s*[¥￥]?\s*([\d,]+\.\d{2})", w[4])
            if m:
                total = float(m.group(1).replace(",", ""))
                break
    if total is None:
        lab = find_label(words, "价税合计")
        if lab:
            v = value_below(words, lab[0])
            if v:
                total = money(v[4])
    if total is None:
        # 兜底：y 在 265~300 之间的 ¥ 金额里取最大（合计行是价税合计）
        cands = [
            money(w[4]) for w in words
            if 265 <= w[1] <= 300 and money(w[4]) is not None
        ]
        if cands:
            total = max(cands)

    items = parse_invoice_items_by_coords(words)

    # 备注里常带工程名
    remark = ""
    rem = find_label(words, "备")
    if rem:
        y_rem = rem[0][1]
        cands = [
            w for w in words
            if abs(w[1] - y_rem) < 20 and w[0] < 320 and len(w[4]) > 8 and "备" not in w[4]
        ]
        remark = max(cands, key=lambda w: len(w[4]))[4] if cands else ""

    title = ""
    for w in words:
        if "电子发票" in w[4] or "增值税" in w[4]:
            title = clean(w[4])
            break

    return {
        "invoice_no": no,
        "invoice_date": date,
        "buyer": buyer,
        "seller": seller,
        "total": total,
        "buyer_tax_id": buyer_tax,
        "seller_tax_id": seller_tax,
        "title": title,
        "remark": remark,
        "items": items,
        "is_invoice": bool(no and (buyer or seller)),
    }


def _norm_invoice_date(text: str) -> str:
    m = re.search(r"(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})", clean(text or ""))
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


# 明细列的 x 区间（左边界，取最近的列头）
ITEM_COLUMNS = [
    ("product", -1e9, 110.0),
    ("spec", 110.0, 190.0),
    ("unit", 190.0, 262.0),
    ("qty", 262.0, 292.0),
    ("price", 292.0, 396.0),
    ("amount", 396.0, 440.0),
    ("tax_rate", 440.0, 545.0),
    ("tax", 545.0, 1e9),
]
ITEM_ROW_Y_MIN = 152.0   # 表头行下方
ITEM_ROW_Y_MAX = 258.0   # 合计行上方


def column_of(x: float) -> str:
    for key, lo, hi in ITEM_COLUMNS:
        if lo <= x < hi:
            return key
    return ""


def parse_invoice_items_by_coords(words: list) -> list[dict]:
    """把 y ∈ [152,258] 区间内的词按行聚类成明细行。

    注意：全电发票一行里"项目名称"可能跨两行排版（*风动电动工具* / 风动和电 /
    动工具零件），所以按 **product 列的 y** 作为行锚点，其它列找 y 最近的。
    """
    body = [w for w in words if ITEM_ROW_Y_MIN <= w[1] <= ITEM_ROW_Y_MAX]
    if not body:
        return []

    anchors = sorted(
        [w for w in body if column_of((w[0] + w[2]) / 2) == "product"],
        key=lambda w: w[1],
    )
    # product 列内 y 相差 < 8 的算同一行（全电票里品名可能折成 2 行，行距约 13pt；
    # 新版旧版明细行距都是 12pt，所以阈值取 8 才不会把相邻两行粘在一起。
    # 早期用 14 导致旧版发票 6 行明细被粘成 2 条，实测踩过。）
    rows: list[list] = []
    for w in anchors:
        if rows and abs(w[1] - rows[-1][-1][1]) < 8:
            rows[-1].append(w)
        else:
            rows.append([w])

    out = []
    for group in rows:
        y_top = min(w[1] for w in group)
        y_bot = max(w[3] for w in group)
        y_mid = (y_top + y_bot) / 2
        name = "".join(w[4] for w in sorted(group, key=lambda w: (w[1], w[0])))
        record = {"product_raw": name, "spec": "", "unit": "", "qty": None,
                  "price": None, "amount": None, "tax_rate": "", "tax": None}
        for w in body:
            col = column_of((w[0] + w[2]) / 2)
            if not col or col == "product":
                continue
            if not (y_top - 4 <= (w[1] + w[3]) / 2 <= y_bot + 4):
                continue
            if col in ("spec", "unit", "tax_rate"):
                record[col] = (record[col] + " " + w[4]).strip()
            else:
                val = money(w[4]) if col in ("amount", "tax") else to_number(w[4])
                if val is not None:
                    record[col] = val
        # "*风动电动工具*风动和电动工具零件" → 类别 + 品名
        m = re.match(r"^\*([^*]+)\*(.+)$", name)
        if m:
            record["category"] = m.group(1)
            record["product"] = m.group(2)
        else:
            record["category"] = ""
            record["product"] = name
        out.append(record)
    return out


def parse_receipt_by_coords(words: list) -> dict:
    """银行回单：凭证号 / 付款人 / 收款人 / 金额。"""
    texts = [w[4] for w in words]
    joined = " ".join(texts)
    no = ""
    for w in words:
        m = re.match(r"凭证号[:：]?\s*(\d+)", w[4])
        if m:
            no = m.group(1)
            break
    amount = None
    for w in words:
        val = money(w[4])
        if val is not None and val > 0:
            amount = max(amount or 0, val)
    return {
        "receipt_no": no,
        "total": amount,
        "is_receipt": True,
        "head": joined[:160],
    }


def parse_pdf(path: Path) -> dict:
    """PDF → 结构化。返回的 kind ∈ {invoice, receipt, scanned, other}。"""
    words, width, height = pdf_words(path)
    base = {
        "kind": "other", "is_invoice": False, "is_receipt": False,
        "invoice_no": "", "invoice_date": "", "buyer": "", "seller": "",
        "total": None, "buyer_tax_id": "", "seller_tax_id": "",
        "title": "", "remark": "", "items": [], "head": "",
    }
    if not words:
        # 无文字层 → 扫描件，需 OCR
        base["kind"] = "scanned"
        base["head"] = "（无文字层，需 OCR）"
        return base

    texts = [w[4] for w in words]
    base["head"] = " ".join(texts)[:200]

    if any("发票号码" in t for t in texts):
        base["kind"] = "invoice"
        base.update(parse_invoice_by_coords(words, width))
        return base

    if any("凭证号" in t for t in texts):
        base["kind"] = "receipt"
        base.update(parse_receipt_by_coords(words))
        return base

    # 合同 / 报价单等
    for w in words:
        if "合同" in w[4]:
            base["title"] = clean(w[4])
            break
    return base


# ─────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    if not ROOT.exists():
        print(f"目录不存在：{ROOT}", file=sys.stderr)
        return 2

    excel, pdf, skipped = collect_files()
    print(f"Excel {len(excel)} / PDF {len(pdf)} / 跳过 {len(skipped)}")

    errors: list[dict] = []
    excel_records, all_rows = [], []

    for path in excel:
        st = path.stat()
        rec = {
            "path": rel(path), "name": path.name, "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "sha1": sha1_of(path), "sheets": [],
        }
        try:
            raw = read_xls_raw(path) if path.suffix.lower() == ".xls" else read_xlsx_raw(path)
            for sheet_name, rows in raw:
                info, records = summarize_sheet(sheet_name, rows, rec["name"])
                rec["sheets"].append(info)
                for item in records:
                    all_rows.append({
                        "source": rec["path"], "sheet": sheet_name,
                        "layout": info["layout"],
                        "table_kind": info["table_kind"],
                        "table_kind_label": info["table_kind_label"],
                        **item,
                    })
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
            errors.append({"file": rel(path), "stage": "excel", "error": rec["error"]})
        excel_records.append(rec)
        print("  x", rel(path)[:90])

    pdf_records = []
    for path in pdf:
        st = path.stat()
        rec = {
            "path": rel(path), "name": path.name, "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "sha1": sha1_of(path),
            "kind": "other", "is_invoice": False, "is_receipt": False,
            "invoice_no": "", "invoice_date": "", "buyer": "", "seller": "",
            "total": None, "buyer_tax_id": "", "seller_tax_id": "",
            "title": "", "remark": "", "items": [], "head": "",
        }
        try:
            rec.update(parse_pdf(path))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
            errors.append({"file": rel(path), "stage": "pdf", "error": rec["error"]})
        pdf_records.append(rec)
        print(f"  p [{rec['kind']:7s}] {rel(path)[:80]}")

    sha_counter = Counter(r.get("sha1", "") for r in excel_records + pdf_records)
    dupes = {h: c for h, c in sha_counter.items() if h and c > 1}

    payload = {
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(ROOT),
        "counts": {
            "excel": len(excel), "pdf": len(pdf),
            "skipped_lock_or_empty": len(skipped),
            "detail_rows": len(all_rows),
            "invoice_pdf": sum(1 for r in pdf_records if r.get("kind") == "invoice"),
            "receipt_pdf": sum(1 for r in pdf_records if r.get("kind") == "receipt"),
            "scanned_pdf": sum(1 for r in pdf_records if r.get("kind") == "scanned"),
            "other_pdf": sum(1 for r in pdf_records if r.get("kind") == "other"),
            "invoice_item_rows": sum(len(r.get("items") or []) for r in pdf_records),
            "invoice_with_total": sum(
                1 for r in pdf_records if r.get("kind") == "invoice" and r.get("total")
            ),
            "invoices_parsed": sum(1 for r in pdf_records if r.get("is_invoice")),
        },
        "skipped": [rel(p) for p in skipped],
        "excel": excel_records,
        "pdf": pdf_records,
        "duplicate_content_groups": {
            h: [r["path"] for r in excel_records + pdf_records if r.get("sha1") == h]
            for h in dupes
        },
        "errors": errors,
    }
    (OUT / "scan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUT / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (OUT / "file_index.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "类型", "相对路径", "文件名", "大小KB", "修改时间",
            "sheet数", "明细行合计", "表头列",
            "发票号码", "开票日期", "购买方", "销售方", "价税合计（元）", "明细条数",
            "指纹前10", "重复",
        ])
        for rec in excel_records:
            sheets = rec.get("sheets") or []
            writer.writerow([
                "Excel", rec["path"], rec["name"], round(rec["size"] / 1024, 1), rec["mtime"],
                len(sheets),
                sum(s["data_row_count"] for s in sheets),
                " | ".join(
                    f"[{s['sheet']}] " + "/".join(s["header"][:14])
                    for s in sheets if s["header"]
                )[:400],
                "", "", "", "", "", "",
                rec["sha1"][:10], "重复" if rec["sha1"] in dupes else "",
            ])
        for rec in pdf_records:
            kind_label = {
                "invoice": "PDF-发票", "receipt": "PDF-银行回单",
                "scanned": "PDF-扫描件(需OCR)", "other": "PDF-其他",
            }.get(rec.get("kind"), "PDF")
            writer.writerow([
                kind_label, rec["path"], rec["name"], round(rec["size"] / 1024, 1), rec["mtime"],
                "", "", "",
                rec.get("invoice_no", ""), rec.get("invoice_date", ""),
                rec.get("buyer", ""), rec.get("seller", ""),
                "" if rec.get("total") is None else f"{rec['total']:.2f}",
                len(rec.get("items") or []),
                rec["sha1"][:10], "重复" if rec["sha1"] in dupes else "",
            ])

    print(f"\n明细行 {len(all_rows)} 条 → {OUT / 'rows.jsonl'}")
    print(f"文件清单 → {OUT / 'file_index.csv'}")
    print(f"原始结构 → {OUT / 'scan.json'}")
    if errors:
        print(f"⚠️ {len(errors)} 个文件解析失败")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
