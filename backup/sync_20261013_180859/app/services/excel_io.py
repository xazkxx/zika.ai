"""Excel 导入导出：模板生成 / 上传解析 / 数据导出。

设计要点：

1. 模板与导出**共用同一份列定义**（``COLUMNS``）——导出的文件改完可以直接导回来。
2. 解析对表头做归一化匹配，中文表头、英文字段名都认，列顺序可以乱。
3. 单行出错只影响该行，结果逐行返回，不整批失败（批量导入最怕"一条错全批废"）。
4. 本模块只做纯粹的读写转换，不碰数据库——落库逻辑在路由层，便于测试与复用。

支持的数据类别：

- ``products``        商品档案
- ``customers``       客户档案
- ``suppliers``       供应商档案
- ``warehouses``      仓库档案
- ``opening-stock``   期初库存（仓库 × 商品）
"""

from __future__ import annotations

import io
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# 列定义：字段名 / 中文表头 / 类型 / 必填 / 说明 / 示例
# ---------------------------------------------------------------------------

COLUMNS: dict[str, list[dict[str, Any]]] = {
    "products": [
        {"field": "sku", "label": "商品编码", "type": "str", "required": True, "note": "唯一标识，不可重复", "sample": "SP-0001"},
        {"field": "name", "label": "商品名称", "type": "str", "required": True, "note": "必填", "sample": "不锈钢法兰 DN50"},
        {"field": "category", "label": "类别", "type": "str", "note": "如：原材料/成品/辅料", "sample": "原材料"},
        {"field": "unit", "label": "单位", "type": "str", "note": "如：件/个/米/公斤", "sample": "件"},
        {"field": "standards", "label": "规格", "type": "str", "note": "", "sample": "DN50 PN16"},
        {"field": "brand", "label": "型号", "type": "str", "note": "", "sample": "304"},
        {"field": "mnemonic", "label": "助记码", "type": "str", "note": "便于快速检索", "sample": "BXGFL"},
        {"field": "bar_code", "label": "条码", "type": "str", "note": "", "sample": "6901234567890"},
        {"field": "color", "label": "颜色", "type": "str", "note": "", "sample": ""},
        {"field": "size", "label": "尺码", "type": "str", "note": "", "sample": ""},
        {"field": "manufacturer", "label": "生产商", "type": "str", "note": "", "sample": ""},
        {"field": "serial_no", "label": "序列号", "type": "str", "note": "", "sample": ""},
        {"field": "unit_weight", "label": "单位重量", "type": "float", "note": "数字", "sample": 1.2},
        {"field": "purchase_price", "label": "采购价", "type": "float", "note": "数字，默认 0", "sample": 32.5},
        {"field": "sale_price", "label": "销售价", "type": "float", "note": "数字，默认 0", "sample": 45.0},
        {"field": "stock_upper", "label": "库存上限", "type": "int", "note": "超过则报积压", "sample": 500},
        {"field": "stock_lower", "label": "库存下限", "type": "int", "note": "低于则报缺货。不填则不参与预警", "sample": 50},
        {"field": "pack_qty", "label": "包装数", "type": "int", "note": "整数", "sample": 10},
        {"field": "shelf_life", "label": "保质期(天)", "type": "int", "note": "整数", "sample": 365},
        {"field": "warn_days", "label": "预警天数", "type": "int", "note": "整数", "sample": 30},
        {"field": "image_url", "label": "商品图片", "type": "str", "note": "图片地址", "sample": ""},
        {"field": "note", "label": "备注", "type": "str", "note": "", "sample": ""},
    ],
    "customers": [
        {"field": "code", "label": "客户编码", "type": "str", "required": True, "note": "唯一标识，不可重复", "sample": "KH-0001"},
        {"field": "name", "label": "客户名称", "type": "str", "required": True, "note": "必填", "sample": "西安某某机电有限公司"},
        {"field": "phone", "label": "电话", "type": "str", "note": "", "sample": "029-88886666"},
        {"field": "email", "label": "邮箱", "type": "str", "note": "", "sample": ""},
        {"field": "address", "label": "地址", "type": "str", "note": "", "sample": "西安市雁塔区科技路 1 号"},
        {"field": "contact", "label": "联系人", "type": "str", "note": "", "sample": "张经理"},
        {"field": "contact_phone", "label": "联系人电话", "type": "str", "note": "", "sample": "13800000000"},
        {"field": "businesser", "label": "业务员", "type": "str", "note": "归属业务员", "sample": "李四"},
        {"field": "tax_no", "label": "税号", "type": "str", "note": "", "sample": "91610113MA6XXXXXXX"},
        {"field": "bank_name", "label": "开户行", "type": "str", "note": "", "sample": "中国银行西安分行"},
        {"field": "bank_account", "label": "开户账号", "type": "str", "note": "", "sample": "123456789012345"},
        {"field": "level", "label": "客户级别", "type": "str", "note": "如：A/B/C", "sample": "A"},
        {"field": "discount", "label": "折扣", "type": "float", "note": "如 0.95 表示九五折", "sample": 1.0},
        {"field": "credit_limit", "label": "信用额度", "type": "float", "note": "数字", "sample": 200000},
        {"field": "init_receivable", "label": "期初应收", "type": "float", "note": "建账时已欠的货款", "sample": 0},
        {"field": "init_invoice_debt", "label": "期初欠票", "type": "float", "note": "已收款未开票金额", "sample": 0},
        {"field": "relation_date", "label": "建立关系时间", "type": "str", "note": "如 2026-01-01", "sample": ""},
        {"field": "business_type", "label": "业务类型", "type": "str", "note": "", "sample": ""},
        {"field": "main_products", "label": "主营产品", "type": "str", "note": "", "sample": ""},
        {"field": "potential_amount", "label": "潜在业务量/年", "type": "float", "note": "数字", "sample": 0},
        {"field": "note", "label": "备注", "type": "str", "note": "", "sample": ""},
    ],
    "suppliers": [
        {"field": "code", "label": "供应商编码", "type": "str", "required": True, "note": "唯一标识，不可重复", "sample": "GYS-0001"},
        {"field": "name", "label": "供应商名称", "type": "str", "required": True, "note": "必填", "sample": "陕西某某钢材有限公司"},
        {"field": "short_name", "label": "供应商简称", "type": "str", "note": "", "sample": "某某钢材"},
        {"field": "phone", "label": "电话", "type": "str", "note": "", "sample": "029-77775555"},
        {"field": "email", "label": "邮箱", "type": "str", "note": "", "sample": ""},
        {"field": "address", "label": "地址", "type": "str", "note": "", "sample": ""},
        {"field": "contact", "label": "联系人", "type": "str", "note": "", "sample": "王经理"},
        {"field": "main_contact", "label": "主要联系人", "type": "str", "note": "", "sample": ""},
        {"field": "mobile", "label": "手机号", "type": "str", "note": "", "sample": "13900000000"},
        {"field": "postcode", "label": "邮编", "type": "str", "note": "", "sample": ""},
        {"field": "bank_name", "label": "开户行", "type": "str", "note": "", "sample": ""},
        {"field": "bank_account", "label": "账号", "type": "str", "note": "", "sample": ""},
        {"field": "init_payable", "label": "期初应付", "type": "float", "note": "建账时已欠供应商的货款", "sample": 0},
        {"field": "init_invoice_debt", "label": "期初欠票", "type": "float", "note": "已付款未收票金额", "sample": 0},
        {"field": "note", "label": "备注", "type": "str", "note": "", "sample": ""},
    ],
    "warehouses": [
        {"field": "code", "label": "仓库编码", "type": "str", "required": True, "note": "唯一标识，不可重复", "sample": "CK-001"},
        {"field": "name", "label": "仓库名称", "type": "str", "required": True, "note": "必填", "sample": "主仓库"},
        {"field": "location", "label": "货位", "type": "str", "note": "", "sample": "A 区"},
        {"field": "manager", "label": "负责人", "type": "str", "note": "", "sample": "赵五"},
        {"field": "phone", "label": "电话", "type": "str", "note": "", "sample": ""},
        {"field": "is_active", "label": "是否启用", "type": "bool", "note": "填「是」或「否」，默认是", "sample": "是"},
        {"field": "note", "label": "备注", "type": "str", "note": "", "sample": ""},
    ],
    "opening-stock": [
        {"field": "warehouse_code", "label": "仓库编码", "type": "str", "required": True, "note": "必须是系统里已有的仓库编码", "sample": "CK-001"},
        {"field": "sku", "label": "商品编码", "type": "str", "required": True, "note": "必须是系统里已有的商品编码", "sample": "SP-0001"},
        {"field": "quantity", "label": "期初数量", "type": "int", "required": True, "note": "整数，可为 0", "sample": 100},
        {"field": "unit_price", "label": "成本单价", "type": "float", "note": "数字，用于计算库存金额", "sample": 32.5},
        {"field": "note", "label": "备注", "type": "str", "note": "", "sample": "2026 年期初"},
    ],
}

TITLES: dict[str, str] = {
    "products": "商品档案导入模板",
    "customers": "客户档案导入模板",
    "suppliers": "供应商档案导入模板",
    "warehouses": "仓库档案导入模板",
    "opening-stock": "期初库存导入模板",
}

# 去重键：导入时按这些字段判断"新增还是更新"
KEY_FIELDS: dict[str, list[str]] = {
    "products": ["sku"],
    "customers": ["code"],
    "suppliers": ["code"],
    "warehouses": ["code"],
    "opening-stock": ["warehouse_code", "sku"],
}

# 只读字段（导入时不接受，导出时带出）
READONLY_FIELDS: dict[str, list[str]] = {
    "products": ["id"],
    "customers": ["id"],
    "suppliers": ["id"],
    "warehouses": ["id"],
    "opening-stock": [],
}

_HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
_SAMPLE_FILL = PatternFill("solid", fgColor="FFF7E6")
_SAMPLE_FONT = Font(name="微软雅黑", size=9, color="9A6B00")
_BODY_FONT = Font(name="微软雅黑", size=10)
_REQUIRED_FONT = Font(name="微软雅黑", size=10, bold=True, color="C0392B")
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


# ---------------------------------------------------------------------------
# 归一化与类型转换
# ---------------------------------------------------------------------------

def _normalize(value: Any) -> str:
    """表头归一化：去星号、空白、全角空格，便于宽松匹配。"""
    if value is None:
        return ""
    text = str(value)
    for ch in ("*", "＊", " ", "\u3000", "\n", "\r", "\t"):
        text = text.replace(ch, "")
    return text


def _header_index(kind: str, header_row: Iterable[Any]) -> dict[str, int]:
    """把工作表首行映射为 {字段名: 列下标}，中英文表头都认。"""
    specs = COLUMNS[kind]
    by_label = {_normalize(col["label"]): col["field"] for col in specs}
    by_field = {col["field"]: col["field"] for col in specs}
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(header_row):
        key = _normalize(raw)
        if not key:
            continue
        field = by_label.get(key) or by_field.get(key)
        if field and field not in mapping:
            mapping[field] = idx
    return mapping


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("¥", "").replace("元", "")
    if not text:
        return None
    return float(text)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"「{value}」不是整数")
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    return int(float(text))


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("是", "y", "yes", "true", "1", "启用", "√", "v"):
        return True
    if text in ("否", "n", "no", "false", "0", "停用", "×", "x"):
        return False
    raise ValueError(f"「{value}」无法识别为是/否")


_CONVERTERS = {"str": _to_str, "float": _to_float, "int": _to_int, "bool": _to_bool}


def _coerce(col: dict[str, Any], raw: Any) -> Any:
    converter = _CONVERTERS[col["type"]]
    value = converter(raw)
    if value is None and col.get("required"):
        raise ValueError("必填项不能为空")
    return value


# ---------------------------------------------------------------------------
# 模板生成
# ---------------------------------------------------------------------------

def build_template(kind: str) -> bytes:
    """生成导入模板 xlsx（字节流）：导入模板页 + 填写说明页。"""
    if kind not in COLUMNS:
        raise KeyError(kind)
    specs = COLUMNS[kind]

    wb = Workbook()
    ws = wb.active
    ws.title = "导入数据"

    # 标题行
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(specs), 1))
    title_cell = ws.cell(row=1, column=1, value=f"{TITLES[kind]}（第 3 行是示例，示例行不会导入；请从第 4 行起填写）")
    title_cell.font = Font(name="微软雅黑", size=12, bold=True, color="1F3A5F")
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    # 表头 + 示例
    for idx, col in enumerate(specs, start=1):
        head = ws.cell(row=2, column=idx, value=f"{col['label']}*" if col.get("required") else col["label"])
        head.fill = _HEADER_FILL
        head.font = _HEADER_FONT
        head.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        head.border = _BORDER
        sample = ws.cell(row=3, column=idx, value=col.get("sample"))
        sample.fill = _SAMPLE_FILL
        sample.font = _SAMPLE_FONT
        sample.alignment = Alignment(horizontal="left", vertical="center")
        sample.border = _BORDER
        width = max(10, min(28, len(str(col["label"])) * 2 + 6))
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.row_dimensions[2].height = 22
    ws.row_dimensions[3].height = 18
    ws.freeze_panes = "A3"

    # 说明页
    ws2 = wb.create_sheet("填写说明")
    ws2.append(["字段名", "中文表头", "是否必填", "类型", "说明", "示例"])
    for cell in ws2[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
    for col in specs:
        ws2.append([
            col["field"],
            col["label"],
            "必填" if col.get("required") else "选填",
            col["type"],
            col.get("note", ""),
            "" if col.get("sample") is None else str(col["sample"]),
        ])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row, max_col=6):
        for cell in row:
            cell.font = _BODY_FONT
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            cell.border = _BORDER
    for idx, width in enumerate([16, 16, 10, 8, 44, 22], start=1):
        ws2.column_dimensions[get_column_letter(idx)].width = width
    ws2.freeze_panes = "A2"

    return _save(wb)


# ---------------------------------------------------------------------------
# 解析上传文件
# ---------------------------------------------------------------------------

def parse_rows(kind: str, content: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """解析上传的 xlsx，返回 (有效行, 错误列表)。

    有效行：``{"__row__": 原始行号, 字段名: 值, ...}``（仅含填写了的字段）。
    错误列表：``[{"row": 行号, "message": "原因"}]``。
    """
    if kind not in COLUMNS:
        raise KeyError(kind)
    specs = COLUMNS[kind]

    try:
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:  # 损坏文件 / 非 xlsx
        raise ValueError(f"无法读取 Excel 文件：{exc}") from exc

    ws = wb["导入数据"] if "导入数据" in wb.sheetnames else wb[wb.sheetnames[0]]

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return [], [{"row": 0, "message": "文件是空的"}]

    # 在前 10 行里寻找表头行（兼容用户在顶部加标题/空行的情况），取匹配字段最多的一行
    required_fields = {c["field"] for c in specs if c.get("required")}
    header_idx = -1
    mapping: dict[str, int] = {}
    for idx, candidate in enumerate(all_rows[:10]):
        found = _header_index(kind, candidate)
        if len(found) > len(mapping):
            mapping, header_idx = found, idx
        if required_fields and required_fields <= set(found):
            mapping, header_idx = found, idx
            break

    if not mapping:
        return [], [{"row": 1, "message": "表头无法识别，请从「模板下载」重新获取标准模板"}]

    missing_required = [
        c["label"] for c in specs if c.get("required") and c["field"] not in mapping
    ]
    if missing_required:
        return [], [{"row": header_idx + 1, "message": "缺少必填列：" + "、".join(missing_required)}]

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    row_no = header_idx + 1
    for raw_row in all_rows[header_idx + 1:]:
        row_no += 1
        if raw_row is None or all(v is None or str(v).strip() == "" for v in raw_row):
            continue
        try:
            record: dict[str, Any] = {"__row__": row_no}
            for field, idx in mapping.items():
                raw = raw_row[idx] if idx < len(raw_row) else None
                col = next(c for c in specs if c["field"] == field)
                record[field] = _coerce(col, raw)
            # 与模板示例行完全相同 → 视为未修改的示例，跳过
            if is_sample_row(kind, record):
                continue
            # 必填列未在 mapping 中已提前拦截；这里再确认一次实际值
            blanks = [
                c["label"] for c in specs
                if c.get("required") and not record.get(c["field"])
            ]
            if blanks:
                raise ValueError("必填项为空：" + "、".join(blanks))
            rows.append(record)
        except ValueError as exc:
            errors.append({"row": row_no, "message": str(exc)})
        except Exception as exc:  # 兜底，避免单行异常打断整批
            errors.append({"row": row_no, "message": f"{type(exc).__name__}: {exc}"})

    if not rows and not errors:
        errors.append({"row": header_idx + 2, "message": "没有读到任何数据行"})
    return rows, errors


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def export_rows(kind: str, rows: Iterable[dict[str, Any]]) -> bytes:
    """把记录导出为 xlsx（列定义与模板一致，可直接改完再导回来）。"""
    if kind not in COLUMNS:
        raise KeyError(kind)
    specs = COLUMNS[kind]

    wb = Workbook()
    ws = wb.active
    ws.title = "数据"

    for idx, col in enumerate(specs, start=1):
        head = ws.cell(row=1, column=idx, value=col["label"])
        head.fill = _HEADER_FILL
        head.font = _HEADER_FONT
        head.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        head.border = _BORDER
        ws.column_dimensions[get_column_letter(idx)].width = max(10, min(28, len(str(col["label"])) * 2 + 6))
    ws.row_dimensions[1].height = 22

    for r, record in enumerate(rows, start=2):
        for idx, col in enumerate(specs, start=1):
            value = record.get(col["field"])
            cell = ws.cell(row=r, column=idx, value=value)
            cell.font = _BODY_FONT
            cell.border = _BORDER
            cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = "A2"
    return _save(wb)


def _save(wb: Workbook) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _sig(value: Any) -> str:
    """把值归一为可比较的字符串签名（用于识别模板示例行）。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def is_sample_row(kind: str, record: dict[str, Any]) -> bool:
    """判断某行是否与模板示例行完全一致——一致则跳过，避免把示例当数据导入。"""
    specs = COLUMNS[kind]
    for col in specs:
        sample = _sig(col.get("sample"))
        actual = _sig(record.get(col["field"]))
        if sample != actual:
            return False
    return True


def xlsx_media_type() -> str:
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
