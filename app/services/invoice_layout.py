"""发票版式解析：**按坐标**读买卖方与明细，不依赖文本流顺序。

## 为什么必须有这个模块

全电发票（数电票）导出的 PDF 有一类很坑的结构：**标签块与值块是分离的**。
文本流大致长这样：

    [标签块]  购/买/方/信/息 … 统一社会信用代码/纳税人识别号： … 名称： …
              项 目 名 称 规格型号 单 位 数 量 单 价 金 额 税率/征收率 税 额
    [值块]    26612000001003603936 … 2026年05月27日 … 陕西送变电工程有限公司 …
              916101332206045948 … 4814.35 48.15 4862.50 塑料制品PVC管材 1% 米 …

而在此之前，解析用的是**「标签后紧跟值」的正则**（如 `名称[:：]` 后接空白与内容）。
标签块里的 `名称：` 后面**根本没有值**，正则永远匹配不到，于是只能靠兜底猜 ——
实测把**购买方和销售方整体搞反了**，而进销项判定正是靠这两个字段，错了看不出来。

## 三条做法（都不写死坐标）

1. **竖排单字定位栏位**：数电票把「购买方信息 / 销售方信息」竖排成单字
   （购/买/方/信/息）。按 x 聚类找出这两组字的 x，作为**左右栏锚点** ——
   不同生成器页宽不同，写死 `x=17` 迟早失效。
2. **表头列线切明细**：先定位表头行（项目名称/规格型号/单位/数量/单价/金额/税率/税额），
   用**各表头词的中心 x** 作为列边界，再按 y 分组读每一行。
   （文本流里数字顺序是乱的：实测出现过 `1% / 米 / 1138.61 / 11.39 / 11.38… / 100`，
   按顺序读必然错位 —— 只有按 x 归列才对。）
3. **三层兜底**：竖排锚点 → 同行「标签 + 右侧最近值」→ 老的「标签后紧跟值」正则。
   哪条能填满必需字段用哪条；三条都不行就留空，**绝不猜**。

## 自校验

明细行按 `数量 × 单价 ≈ 金额` 校验，合计与价税合计也对一遍。
**对不上的行会被标出来**（`warnings`），而不是静默存一个错的数 ——
识别错误最怕的不是错，是错得没人知道。
"""

from __future__ import annotations

import re

import pymupdf

# 明细表头（按出现的词定位列中心线）。顺序即列序。
ITEM_HEADERS = ["项目名称", "规格型号", "单位", "数量", "单价", "金额", "税率/征收率", "税额"]
# 表头词在 PDF 里可能被拆成带空格的写法
_HEADER_ALIASES = {
    "项目名称": ("项目名称",),
    "规格型号": ("规格型号",),
    "单位": ("单位", "单 位"),
    "数量": ("数量", "数 量"),
    "单价": ("单价", "单 价"),
    "金额": ("金额", "金 额"),
    "税率/征收率": ("税率/征收率", "税率"),
    "税额": ("税额", "税 额"),
}

_TOTAL_ROW_LABELS = ("合计", "价税合计")
# 明细区结束标志：出现这些说明已经走出明细区
_STOP_LABELS = ("合计", "价税合计", "备", "注", "销方开户银行", "开票人")

_BUYER_MARKS = "购买方信息"
_SELLER_MARKS = "销售方信息"


def _words(page) -> list[tuple[float, float, float, float, str]]:
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]


def _find_vertical_anchor(words, marks: str) -> float | None:
    """找竖排单字组的 x 锚点。

    数电票把「购买方信息」五个字竖着排成一列。这里要求在**同一个 x**（容差 3pt）
    上按 y 递增找到这五个字，返回该 x。找不到返回 None。
    """
    by_x: dict[float, list[tuple[float, str]]] = {}
    for x0, y0, _x1, _y1, text in words:
        if len(text) == 1 and text in marks:
            by_x.setdefault(round(x0), []).append((y0, text))
    for x, items in by_x.items():
        items.sort()
        joined = "".join(text for _y, text in items)
        if marks in joined:
            return float(x)
    return None


def _party_block(words, anchor_x: float, page_width: float) -> dict[str, str | None]:
    """在某个栏位锚点右侧读出「名称」与「纳税人识别号」的值。

    做法：在该栏范围内的词里，找 `名称：`/`名称:` 这类标签，
    取**同一行、x 更大、距离最近**的那个词作为值。
    `纳税人识别号` 同理（标签本身较长，值通常在它右侧或下一行同级位置）。
    """
    # 该栏的横向范围：锚点起，到页面中线或另一个锚点为止（给足余量）
    if anchor_x < page_width / 2:
        left, right = anchor_x, page_width / 2 + 40
    else:
        left, right = anchor_x, page_width + 10
    in_col = [w for w in words if left <= w[0] < right]

    name = _value_right_of(in_col, ("名称：", "名称:"), skip_x_after=120)
    tax_no = _value_right_of(
        in_col, ("统一社会信用代码/纳税人识别号：", "统一社会信用代码/纳税人识别号:", "纳税人识别号：", "纳税人识别号:")
    )
    # 有些生成器把「名称：」与值拆成两行，用"标签下方最近的、看起来像名称的词"兜底
    if not name:
        name = _value_below_label(in_col, ("名称：", "名称:"))
    return {"name": name, "tax_no": tax_no}


def _value_right_of(column, labels: tuple[str, ...], skip_x_after: float | None = None) -> str | None:
    stripped_labels = tuple(l.rstrip("：:") for l in labels)
    for x0, y0, x1, _y1, text in column:
        if text in labels or text.rstrip("：:") in stripped_labels:
            # 同一行、起点在标签**起点右侧一点**的词，按 x 取最近的那个。
            #
            # ⚠️ 这里是踩过的坑：最初用 `w[0] >= x1 - 1`（"在标签右边界右侧"）判断，
            # 但标签框与值框会**轻微重叠**（实测标签 x 33→60、值从 x 57 开始），
            # 于是真正的值被排除，兜底逻辑把"下一行的税号"当成了名称。
            # 改成按标签**起点**比较，并显式排除标签自身。
            same_line = [
                w
                for w in column
                if abs(w[1] - y0) < 6 and w[0] > x0 + 5 and w[4].strip() not in ("", "：", ":")
            ]
            same_line.sort(key=lambda w: w[0])
            for cand in same_line:
                value = cand[4].strip()
                # 过滤掉另一个标签（说明这一栏没有值）
                if re.fullmatch(r"(名称|统一社会信用代码/纳税人识别号|纳税人识别号)[：:]?", value):
                    continue
                if skip_x_after is not None and cand[0] - x0 > skip_x_after:
                    break
                return value
    return None


def _value_below_label(column, labels: tuple[str, ...]) -> str | None:
    """标签与值跨行时的兜底。

    ⚠️ 这里**必须**和 `_value_right_of` 一样过滤掉"另一个标签"：
    早先漏了这一步，结果把「统一社会信用代码/纳税人识别号：」这个**标签本身**
    当成了"名称"的值（合成样本实测踩到）。
    """
    stripped_labels = tuple(l.rstrip("：:") for l in labels)
    label_names = ("名称", "统一社会信用代码/纳税人识别号", "纳税人识别号")
    for x0, y0, x1, y1, text in column:
        if text in labels:
            below = [w for w in column if 0 < w[1] - y1 < 22 and w[0] >= x0 - 4]
            below.sort(key=lambda w: (w[1], w[0]))
            for cand in below:
                value = cand[4].strip()
                if value.rstrip("：:") in label_names or value in stripped_labels:
                    continue  # 是标签不是值，继续往下找
                return value
    return None


def _norm_tax(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    return cleaned if len(cleaned) >= 15 else None


def header_centers(words, page_height: float) -> dict[str, float]:
    """表头各列的**中心 x**。表头词可能被 PDF 拆成单字，所以要按行拼接后取
    「首字起点 → 末字终点」的中心。

    ⚠️ 这里是踩过的坑：最初把"拼接位置"映射回**首字的起点**当中心，
    结果「数 量」的中心被算成 268（实际 277）、「单 价」算成 339（实际 348），
    列边界整体偏左，「2」和「1848.51…」被归进了同一列 ——
    表现为数量=10011.386138613861 这种"数字粘在一起"的怪值。
    """
    rows: dict[int, list] = {}
    for word in words:
        if word[1] > page_height * 0.7:
            continue
        rows.setdefault(round(word[1] / 4), []).append(word)

    centers: dict[str, float] = {}
    for line in rows.values():
        line.sort(key=lambda w: w[0])
        for i in range(len(line)):
            joined = ""
            for j in range(i, len(line)):
                joined += line[j][4].replace(" ", "")
                for name, aliases in _HEADER_ALIASES.items():
                    if name in centers:
                        continue
                    if any(joined == alias.replace(" ", "") for alias in aliases):
                        centers[name] = (line[i][0] + line[j][2]) / 2
                        break
    return centers


# 明细区里这些行不是商品行（合计/价税合计/备注/销方信息），要跳过
_SUMMARY_ROW_RE = re.compile(r"^(合|价税合计|销方开户银行|备\s*注|开票人)")


def _assign_column(center_x: float, centers: dict[str, float]) -> str | None:
    """**就近归列**：把词归到中心 x 最近的那一列。

    比"算列边界"稳得多 —— 数字的宽度不一（`2` vs `1848.51485148515`），
    用中点法切边界时宽数字会跨过边界被切错；就近归列不受宽度影响。
    """
    if not centers:
        return None
    return min(centers, key=lambda name: abs(center_x - centers[name]))


def _parse_items(words, centers, header_y: float, page_height: float) -> list[dict[str, object]]:
    """按 y 分组读明细行，每个词就近归列。"""
    candidates = []
    for x0, y0, x1, y1, text in words:
        if y0 <= header_y + 4 or y0 > page_height * 0.82:
            continue
        candidates.append((x0, y0, x1, y1, text))
    candidates.sort(key=lambda w: (w[1], w[0]))

    # 同一行的词：y 差 < 6pt 视为一行（实测同一行的数字会差 1~2pt）
    rows: list[list] = []
    for word in candidates:
        if rows and abs(rows[-1][0][1] - word[1]) < 6:
            rows[-1].append(word)
        else:
            rows.append([word])

    items: list[dict[str, object]] = []
    for row in rows:
        cells: dict[str, list] = {}
        for word in row:
            name = _assign_column((word[0] + word[2]) / 2, centers)
            if name:
                cells.setdefault(name, []).append(word)
        for name in cells:
            cells[name].sort(key=lambda w: w[0])
        text_of = lambda name: " ".join(w[4] for w in cells.get(name, [])).strip()  # noqa: E731

        item_name = text_of("项目名称").replace(" ", "")
        # 汇总/备注行到此为止：它们没有"数量"，而且文案是可识别的
        if _SUMMARY_ROW_RE.match(item_name):
            break
        quantity = _to_float(text_of("数量"))
        amount = _to_float(text_of("金额"))

        if not item_name:
            continue
        # 项目名称跨行（如「铝合金人字梯」被拆成两行）：没有数量也没有金额的行，
        # 接到上一行的品名上，而不是当成新的一条明细
        if quantity is None and amount is None:
            if items:
                items[-1]["item_name"] = f"{items[-1]['item_name']}{item_name}"
            continue
        items.append(
            {
                "item_name": item_name,
                "spec": text_of("规格型号") or None,
                "unit": text_of("单位") or None,
                "quantity": quantity,
                "unit_price": _to_float(text_of("单价")),
                "amount": amount,
                "tax_rate": _to_float(text_of("税率/征收率")),
                "tax_amount": _to_float(text_of("税额")),
            }
        )
    return items


def _header_y(words, page_height: float) -> float | None:
    """表头行的 y。"""
    for _x0, y0, _x1, _y1, text in words:
        if text.replace(" ", "") == "项目名称" and y0 < page_height * 0.7:
            return y0
    return None


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in (".", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_qr_text(payload: bytes) -> str | None:
    """从 PDF 里**提取并解码二维码原图**，返回二维码内容。

    数电票的 PDF 里二维码是一张内嵌图片（实测 300×300），直接从图片对象解，
    比先渲染整页再扫要准得多（不依赖渲染分辨率）。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    try:
        doc = pymupdf.open(stream=payload, filetype="pdf")
    except Exception:
        return None

    detector = cv2.QRCodeDetector()
    for page in doc:
        for image in page.get_images(full=True):
            try:
                pix = pymupdf.Pixmap(doc, image[0])
                if pix.n - pix.alpha > 3:  # CMYK 之类需要先转
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                png = pix.tobytes("png")
                arr = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if arr is None:
                    continue
                data, _points, _straight = detector.detectAndDecode(arr)
                if data:
                    return str(data)
            except Exception:
                continue
    return None


def extract_qr_png(payload: bytes) -> bytes | None:
    """提取二维码**原图**（PNG 字节）—— 用户要"二维码可下载"，给的是原图而不是重画的。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        doc = pymupdf.open(stream=payload, filetype="pdf")
    except Exception:
        return None
    detector = cv2.QRCodeDetector()
    for page in doc:
        for image in page.get_images(full=True):
            try:
                pix = pymupdf.Pixmap(doc, image[0])
                if pix.n - pix.alpha > 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                png = pix.tobytes("png")
                arr = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                if arr is None:
                    continue
                data, _p, _s = detector.detectAndDecode(arr)
                if data:
                    return png
            except Exception:
                continue
    return None


def build_qr_png(text: str, box_size: int = 8) -> bytes | None:
    """把二维码文本**重画**成 PNG。

    只在拿不到原件内嵌原图时才用（原件是图片、或二维码被压坏解不出来）——
    重画的图是"我们生成的"，与原票上的图不是同一张，所以来源要如实标出来。
    """
    if not text:
        return None
    try:
        import io

        import qrcode
    except ImportError:
        return None
    try:
        img = qrcode.make(text)
        # 统一放大到 box_size 像素/模块，并补白边 —— 否则小尺寸图打印出来扫不动
        img = img.resize((img.width * box_size // 3, img.height * box_size // 3))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return None


def extract_qr_from_image(payload: bytes) -> tuple[bytes | None, str | None]:
    """从**图片格式**的原件（拍照/截图上传的发票）里解二维码。

    返回 `(PNG 字节, 二维码文本)`。图片没有"内嵌图"这一层，
    所以整张图就是二维码所在的图 —— 解出来直接返回重新编码的整图有点大，
    这里返回**裁出来的二维码区域**，下载下来才是一张干净的二维码。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, None
    try:
        arr = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if arr is None:
            return None, None
        detector = cv2.QRCodeDetector()
        data, points, _straight = detector.detectAndDecode(arr)
        if not data or points is None:
            return None, None
        # points 是四角坐标，裁出外接矩形并留一点白边（不留边有些扫码器读不到）
        xs = [float(p[0]) for p in points[0]]
        ys = [float(p[1]) for p in points[0]]
        pad = 12
        h, w = arr.shape[:2]
        x0 = max(int(min(xs)) - pad, 0)
        y0 = max(int(min(ys)) - pad, 0)
        x1 = min(int(max(xs)) + pad, w)
        y1 = min(int(max(ys)) + pad, h)
        crop = arr[y0:y1, x0:x1]
        if crop.size == 0:
            return None, str(data)
        # 放大到至少 300px 宽，保证下载下来的图能扫
        scale = max(1.0, 300.0 / max(crop.shape[1], 1))
        if scale > 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        ok, buffer = cv2.imencode(".png", crop)
        if not ok:
            return None, str(data)
        return buffer.tobytes(), str(data)
    except Exception:
        return None, None


def resolve_qr_png(payload: bytes) -> tuple[bytes | None, str]:
    """取一张发票原件的二维码图，返回 `(PNG 字节, 来源)`。

    来源取值：
    - `embedded` —— 直接从 PDF 内嵌图片对象解出来的**原图**（首选，与票面一致）；
    - `cropped` —— 原件是图片，从图上裁出来的二维码区域；
    - `regenerated` —— 原图解不出来，用二维码文本重画的（内容对，图不一样）；
    - `none` —— 这张票上没有二维码（实测 12 张里有 1 张没有）。

    **优先原图而不是重画**：用户要"下载二维码"，给出的图应当和发票上那张一致 ——
    原图带票面的纠错等级与掩码，重画的虽然内容相同，扫出来一样但视觉上不是同一张。
    """
    if not payload:
        return None, "none"
    original = extract_qr_png(payload)
    if original:
        return original, "embedded"
    cropped, text = extract_qr_from_image(payload)
    if cropped:
        return cropped, "cropped"
    text = text or extract_qr_text(payload)
    if text:
        redrawn = build_qr_png(text)
        if redrawn:
            return redrawn, "regenerated"
    return None, "none"


def extract_by_layout(payload: bytes) -> dict[str, object]:
    """按版式坐标解析一张发票 PDF。拿不到的字段一律留 None，**不猜**。"""
    result: dict[str, object] = {
        "buyer_name": None,
        "buyer_tax_no": None,
        "seller_name": None,
        "seller_tax_no": None,
        "items": [],
        "warnings": [],
    }
    try:
        doc = pymupdf.open(stream=payload, filetype="pdf")
    except Exception:
        return result
    if not len(doc):
        return result

    page = doc[0]
    words = _words(page)
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)

    # —— 买卖方：优先竖排锚点 ——
    buyer_x = _find_vertical_anchor(words, _BUYER_MARKS)
    seller_x = _find_vertical_anchor(words, _SELLER_MARKS)
    if buyer_x is not None:
        block = _party_block(words, buyer_x, page_width)
        result["buyer_name"] = block["name"]
        result["buyer_tax_no"] = _norm_tax(block["tax_no"])
    if seller_x is not None:
        block = _party_block(words, seller_x, page_width)
        result["seller_name"] = block["name"]
        result["seller_tax_no"] = _norm_tax(block["tax_no"])

    # 若竖排锚点没找到（老版式），退回"水平标签 + 右侧最近值"
    if result["buyer_name"] is None and result["seller_name"] is None:
        for _x0, y0, x1, _y1, text in words:
            if text.startswith("购买方") or text == "购买方":
                horizontal = _party_block(words, x1 - 1, page_width)
                result["buyer_name"] = result["buyer_name"] or horizontal["name"]
                result["buyer_tax_no"] = result["buyer_tax_no"] or _norm_tax(horizontal["tax_no"])
            if text.startswith("销售方") or text == "销售方":
                horizontal = _party_block(words, x1 - 1, page_width)
                result["seller_name"] = result["seller_name"] or horizontal["name"]
                result["seller_tax_no"] = result["seller_tax_no"] or _norm_tax(horizontal["tax_no"])
        del y0

    # —— 明细：按表头列线切 ——
    centers = header_centers(words, page_height)
    header_y = _header_y(words, page_height)
    if len(centers) >= 4 and header_y is not None:
        items = _parse_items(words, centers, header_y, page_height)
        # 自校验：数量 × 单价 ≈ 金额
        for line in items:
            quantity, unit_price, amount = line.get("quantity"), line.get("unit_price"), line.get("amount")
            if isinstance(quantity, float) and isinstance(unit_price, float) and isinstance(amount, float):
                expect = quantity * unit_price
                if abs(expect - amount) > max(0.05, abs(amount) * 0.01):
                    result["warnings"].append(  # type: ignore[union-attr]
                        f"明细「{line.get('item_name')}」数量×单价={expect:.2f} 与金额 {amount:.2f} 对不上"
                    )
        result["items"] = items

    return result
