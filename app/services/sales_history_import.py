# -*- coding: utf-8 -*-
"""历史销售单导入 —— 把「对账单 Excel」直接变成系统里的销售出库单。

## 为什么单独一个模块，而不是塞进 `excel_io`

`excel_io` 是**一行一条记录**的通用导入器（一行=一个客户/商品/期初）。
历史销售单是**多行合成一张单**（同单据号的多行归一张），聚合逻辑、幂等判定、
单据状态机全都不同。混进去会把 `_import_archive` 的 `setattr` 直通模型那条路搅乱。

## 关键设计（都是踩过坑之后定下来的）

1. **一条明细都不许静默丢掉。**
   `_import_archive` 的做法是「单行失败就记一条错误、其余继续」，这在档案导入里没问题
   （少建一个客户不影响别的客户）。但单据导入**不能这样**：一张 18 行的单丢了 3 行，
   单据金额就少了，而状态照样是"成功"—— 这种半截数据比明确失败危险得多。
   所以这里：**任何一行有问题 → 整张单不导**，报出具体原因，等人工修表。

2. **一行一条库存流水 + 一张单一条应收流水。**
   销售出库在系统里的口径（见 `erp_sales.create_sales_order`）是：
   · 每个明细行写一条 `inventory_transactions`
   · 整张单写**一条** `financial_transactions`（金额=单头合计）
   第一版脚本「每行写一条应收」，收款登记按单冲减时会对不上 —— 一张单挂 18 条应收，
   出纳核销时不知道冲哪条。

3. **幂等靠「外部单号」列，不猜单号前缀。**
   `sales_orders` 没有能放外部单号的字段，只能种进备注：
   `历史导入|源单号=XS202507060001|来源=xxx.xls`。
   重复导入同一份表 → 同一外部单号已存在 → 跳过并计数，不会建第二张。
   拆单时外部单号带后缀（`XS202509030001-01`），保证拆出来的几张各自可幂等。

4. **状态必须落到 `submitted`，且流水必须一起写。**
   `erp_sales.unsubmit_sales_order` 有硬闸：「挂着流水的单不许退回草稿」。
   所以历史单只有两种合法形态：
   · 建**销售出库单**（`doc_type=outbound`）→ 写库存 + 写应收 + `submitted`，账实一致
   · 建**销售订单**（`doc_type=order`）→ 不碰库存不碰账，`submitted`
   不存在第三种"建了单但没流水"的形态。

## 跑法

    from app.services.sales_history_import import import_sales_history
    result = import_sales_history(db, rows, dry_run=True)   # 预检
    result = import_sales_history(db, rows, dry_run=False)  # 真导

`rows` 由 `parse_statement` / `parse_template` 产出（见下），也可以由前端上传后解析。
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.doc_no import build_partner_code, format_doc_no, next_seq, prefix_of
from app.core.money import ZERO, line_amount, money

NOTE_TAG = "历史导入"

# 源单号在备注里的位置：`历史导入|源单号=XXX|来源=YYY`
_RE_SRC_NO = re.compile(r"源单号=([^|]+)")
_RE_SRC_FILE = re.compile(r"来源=([^|]+)")


# ---------------------------------------------------------------------------
# 文本归一化
# ---------------------------------------------------------------------------
# 全角 → 半角，然后去掉所有空白和末尾标点。
# 为什么要做到这一步：源表里的客户名有 `蒲白750千伏输变电工程（线 路工程包1）`
# （中间断行的空格）、`西安渼陂110千伏输变电工程（线路工程)` （半角右括号），
# 而档案里存的是全角括号、无空格。不归一就是「同名客户被当成两个」，
# 于是凭空多建一个客户档案，两张单挂到两个客户身上，应收永远对不平。
_FULL_TO_HALF = {
    ord("（"): "(", ord("）"): ")", ord("，"): ",", ord("："): ":",
    ord("；"): ";", ord("　"): " ", ord("－"): "-", ord("Ｋ"): "K",
    ord("Ｖ"): "V", ord("．"): ".", ord("／"): "/",
}
_TAIL_PUNCT = "。.,，、;；:： "


def norm(text: Any) -> str:
    """名称归一：全角转半角 → 去全部空白 → 去尾部标点。"""
    if text is None:
        return ""
    raw = str(text).translate(_FULL_TO_HALF)
    raw = re.sub(r"\s+", "", raw)
    return raw.strip(_TAIL_PUNCT)


def fix_date(value: Any) -> str:
    """日期归一 —— 兼容 Excel 日期序列号。

    实坑：`.xls` 里有几行日期是裸序列号 `45883`（= 2025-08-14），扫描器没兜住。
    带着这种值建单，单据日期就是"公元 4096 年"，账龄报表当场崩。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
    text = text.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-")
    text = text.replace("日", "")
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text


def _num(value: Any) -> Decimal | None:
    """把单元格值转成 Decimal；转不了返回 None（**不要**用 0 兜底）。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 解析：对账单 / 系统模板
# ---------------------------------------------------------------------------
# 对账单表头别名：源表头 → 内部字段
_STATEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "order_date": ("日期", "单据日期", "开单日期"),
    "warehouse": ("仓库", "出货仓库", "发货仓库"),
    "external_no": ("单号", "单据编号", "单据号"),
    "customer": ("客户名称", "客户", "往来单位"),
    "product": ("商品名称", "商品", "品名", "货物名称"),
    "spec": ("规格",),
    "model": ("型号",),
    "unit": ("单位",),
    "quantity": ("商品数量", "数量"),
    "unit_price": ("单价",),
    "amount": ("金额", "小计"),
    "doc_note": ("单据备注",),
    "line_note": ("备注",),
}


def parse_statement(rows: Iterable[Sequence[Any]]) -> list[dict[str, Any]]:  # noqa: F821
    """把「销售对账单」的二维表（含标题行、表头行）解析成明细行。

    容错点（都是实表里真出现过的）：
      · 第 1 行是标题「XX销售对账单」，表头在第 2 行 —— 前 10 行里找表头最像的那行
      · 序列号/颜色/尺码 三列永远空，跳过即可（按表头名取，不按列号，歪不了）
      · 金额偶尔是 `1980.504`（多打一位），按 4 位单价×数量算出来是 1980.54，
        差 0.04 —— 这种**不改数**，只标记出来给人看
    """
    from typing import Sequence  # noqa: F401  仅为类型标注

    rows = [list(r) for r in rows]
    header_idx, mapping = -1, {}
    for idx, row in enumerate(rows[:10]):
        found: dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            key = norm(cell)
            if not key:
                continue
            for field, aliases in _STATEMENT_ALIASES.items():
                if field in found:
                    continue
                if key in {norm(a) for a in aliases}:
                    found[field] = col_idx
                    break
        if len(found) > len(mapping):
            mapping, header_idx = found, idx
        # 够用了就停：客户+商品+数量+日期 四列齐 → 认定是表头
        if {"order_date", "customer", "product", "quantity"} <= set(found):
            mapping, header_idx = found, idx
            break

    if not mapping:
        raise ValueError("表头无法识别：这张表看起来不是销售对账单（找不到 日期/客户名称/商品名称/数量 这些列）")

    out: list[dict[str, Any]] = []
    for offset, row in enumerate(rows[header_idx + 1 :]):
        def pick(field: str) -> Any:
            idx = mapping.get(field)
            return row[idx] if idx is not None and idx < len(row) else None

        customer = str(pick("customer") or "").strip()
        product = str(pick("product") or "").strip()
        if not customer and not product:
            continue  # 空行 / 合计行

        qty = _num(pick("quantity"))
        price = _num(pick("unit_price"))
        amount = _num(pick("amount"))
        out.append(
            {
                "__row__": header_idx + 2 + offset,
                "order_date": fix_date(pick("order_date")),
                "warehouse": str(pick("warehouse") or "").strip(),
                "external_no": str(pick("external_no") or "").strip(),
                "customer": customer,
                "product": product,
                "spec": str(pick("spec") or "").strip(),
                "model": str(pick("model") or "").strip(),
                "unit": str(pick("unit") or "").strip(),
                "quantity": qty,
                "unit_price": price,
                "amount": amount,
                "doc_note": str(pick("doc_note") or "").strip(),
                "line_note": str(pick("line_note") or "").strip(),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 档案匹配
# ---------------------------------------------------------------------------
_WAREHOUSE_ALIASES = {
    # 源表里 17 行把「公司全名」填进了仓库列，实际指的是该公司的出货仓库
    "西安寨卡信息技术有限公司": "寨卡仓库",
}

# 客户别名：源表工程名（归一化后）→ 系统已有客户。
# 为什么需要：源表里「西延高铁西安段330千伏包1」和档案里的
# 「西延高铁西安段330千伏供电工程（临潼北开，耿镇牵）线路工程包1」(甲47000017)
# 是**同一个工程**（用户 2026-10-20 确认）。
# 不加这条映射的话，引擎会把它当缺失客户 → 新建第二个档案 → 同一工程两笔应收。
# 键必须是 norm() 之后的形态（全角转半角、去空格）。
_CUSTOMER_ALIASES = {
    "西延高铁西安段330千伏包1": "西延高铁西安段330千伏供电工程（临潼北开，耿镇牵）线路工程包1",
}


def _load_matchers(db: Session) -> dict[str, dict[str, Any]]:
    from app.models.customer import Customer
    from app.models.product import Product
    from app.models.warehouse import Warehouse

    def by_norm(items: Iterable[Any]) -> dict[str, Any]:
        return {norm(i.name): i for i in items}

    return {
        "customer": by_norm(db.query(Customer).all()),
        "product": by_norm(db.query(Product).all()),
        "warehouse": by_norm(db.query(Warehouse).all()),
    }


def _match_product(raw: str, matchers: dict[str, dict[str, Any]]) -> tuple[Any, str]:
    """商品匹配三轮：原文 → 去掉 `*类别*` 前缀 → 包含。"""
    text = norm(raw)
    hit = matchers["product"].get(text)
    if hit:
        return hit, "原文一致"
    m = re.match(r"^\*([^*]+)\*(.+)$", text)
    main = m.group(2) if m else text
    hit = matchers["product"].get(main)
    if hit:
        return hit, "去类别前缀后一致"
    for key, rec in matchers["product"].items():
        if len(key) >= 3 and (key in text or main in key):
            return rec, "模糊包含"
    return None, "档案里没有"


# ---------------------------------------------------------------------------
# 分组：一张目标单 = 一个（外部单号, 客户）
# ---------------------------------------------------------------------------
def group_lines(lines: list[dict[str, Any]], split_by_customer: bool) -> list[dict[str, Any]]:
    """把明细行组装成「待建单据」列表。

    ## 为什么要按客户拆（`split_by_customer=True` 是默认）

    系统 `sales_orders` **只有一个 `customer_id`**，而源数据里 14 张单跨 2~4 个工程
    （同一份清单抄给了多个工程，或一车货分送多个工点）。
    硬塞成一张单 → 另外几个工程的货就挂到了第一个工程名下，应收永远对不上。
    按工程拆开后，每个工程各挂各的应收，才对得上工程款结算。

    拆单后外部单号用 `-01 / -02` 后缀，保证幂等键唯一。
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        key = (line["external_no"], norm(line["customer"]) if split_by_customer else "")
        buckets[key].append(line)

    groups: list[dict[str, Any]] = []
    for (ext_no, _cust), items in buckets.items():
        first = items[0]
        groups.append(
            {
                "external_no": ext_no,
                "order_date": first["order_date"],
                "customer": first["customer"],
                "warehouse": first["warehouse"],
                "lines": items,
            }
        )
    # 拆完再补 -01/-02 后缀：只有真正被拆过的（同号多组）才加，单组保持原号
    by_ext: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in groups:
        by_ext[g["external_no"]].append(g)
    for ext_no, parts in by_ext.items():
        if len(parts) == 1:
            parts[0]["import_no"] = ext_no
            continue
        parts.sort(key=lambda g: (g["order_date"] or "", norm(g["customer"])))
        for i, g in enumerate(parts, 1):
            g["import_no"] = f"{ext_no}-{i:02d}"
    groups.sort(key=lambda g: (g["order_date"] or "", g["import_no"]))
    return groups


# ---------------------------------------------------------------------------
# 幂等
# ---------------------------------------------------------------------------
def load_imported(db: Session) -> dict[str, str]:
    """已导入的源单号 → 系统单号（从备注里解析）。"""
    from app.models.sales_order import SalesOrder

    out: dict[str, str] = {}
    rows = (
        db.query(SalesOrder.order_no, SalesOrder.note)
        .filter(SalesOrder.note.like(f"{NOTE_TAG}%"))
        .all()
    )
    for order_no, note in rows:
        m = _RE_SRC_NO.search(str(note or ""))
        if m:
            out[m.group(1).strip()] = order_no
    return out


def build_note(import_no: str, source_file: str) -> str:
    return f"{NOTE_TAG}|源单号={import_no}|来源={source_file}"[:255]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def validate(
    db: Session,
    lines: list[dict[str, Any]],
    *,
    split_by_customer: bool = True,
    source_file: str = "",
) -> dict[str, Any]:
    """预检：把每一行判定成 ok / 待建客户 / 待建商品 / 待定仓库，并算出将建几张单。

    全程只读，不写库。
    """
    matchers = _load_matchers(db)
    checked: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for line in lines:
        row_no = line.get("__row__") or 0
        rec = dict(line)
        rec["status"] = "ok"
        rec["why"] = []
        rec["customer_id"] = None
        rec["product_id"] = None
        rec["warehouse_id"] = None

        # 日期
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rec.get("order_date") or ""):
            rec["status"] = "日期错误"
            rec["why"].append(f"单据日期「{rec.get('order_date')}」不是 2025-07-06 这种格式")

        # 客户（先按别名归一，再查档案）
        alias = _CUSTOMER_ALIASES.get(norm(rec.get("customer")))
        cust = matchers["customer"].get(norm(alias or rec.get("customer")))
        if cust is None:
            cust = matchers["customer"].get(norm(rec.get("customer")))
        if cust is not None:
            rec["customer"] = cust.name  # 回写成档案标准名，分组/幂等都按标准名走
            rec["customer_alias"] = bool(alias)
        else:
            if rec["status"] == "ok":
                rec["status"] = "待建客户"
            rec["why"].append("客户档案里没有这个名字")
        if cust is not None:
            rec["customer_id"] = cust.id
            rec["customer_name"] = cust.name

        # 商品
        prod, how = _match_product(rec.get("product") or "", matchers)
        if prod is None:
            if rec["status"] == "ok":
                rec["status"] = "待建商品"
            rec["why"].append(f"商品{how}")
        else:
            rec["product_id"] = prod.id
            rec["product_name"] = prod.name
            if how != "原文一致":
                issues.append(
                    {"level": "提示", "row": row_no,
                     "detail": f"商品「{rec['product']}」按「{how}」匹配到「{prod.name}」"}
                )

        # 仓库
        wh_name = _WAREHOUSE_ALIASES.get(rec.get("warehouse") or "", rec.get("warehouse") or "")
        wh = matchers["warehouse"].get(norm(wh_name))
        if wh is None:
            if rec["status"] == "ok":
                rec["status"] = "待定仓库"
            rec["why"].append(f"仓库「{rec.get('warehouse')}」不存在")
        else:
            rec["warehouse_id"] = wh.id
            rec["warehouse_name"] = wh.name

        # 数量 / 单价 / 金额
        qty = _num(rec.get("quantity"))
        price = _num(rec.get("unit_price"))
        amount = _num(rec.get("amount"))
        if qty is None or qty <= 0:
            rec["status"] = "数量错误" if rec["status"] != "ok" else "数量错误"
            rec["why"].append(f"数量「{rec.get('quantity')}」不是正数")
        if price is None or price < 0:
            rec["status"] = "单价错误"
            rec["why"].append(f"单价「{rec.get('unit_price')}」不是有效数字")
        if qty is not None and price is not None:
            calc = line_amount(price, qty)
            if amount is None:
                rec["amount"] = calc
                rec["amount_check"] = "按 数量×单价 补算"
            elif abs(money(calc) - money(amount)) > Decimal("0.01"):
                # ⚠️ 不改数，只报告：源表的金额是会计签过的，改了就没法和对方的账对
                rec["amount_check"] = f"与 数量×单价 差 {money(abs(money(calc) - money(amount)))}"
                issues.append(
                    {"level": "金额勾稽", "row": row_no,
                     "detail": f"{rec.get('product')}：{qty}×{price}={calc}，表里写 {amount}"
                               f"，差 {money(abs(money(calc) - money(amount)))}"}
                )
            else:
                rec["amount_check"] = "相符"

        # 外部单号
        if not (rec.get("external_no") or "").strip():
            rec["status"] = "缺单号"
            rec["why"].append("没有外部单号，无法判断重复导入")

        rec["why"] = "；".join(rec["why"])
        checked.append(rec)

    ok_lines = [r for r in checked if r["status"] == "ok"]
    groups = group_lines(ok_lines, split_by_customer)
    imported = load_imported(db)

    for g in groups:
        total = sum((money(line_amount(_num(l["unit_price"]) or ZERO, _num(l["quantity"]) or ZERO))
                     for l in g["lines"]), ZERO)
        g["total"] = money(total)
        g["imported_as"] = imported.get(g["import_no"])
        # 单头字段取首行（同一组内客户/仓库/日期已经一致，否则上面就分到不同组了）
        head = g["lines"][0]
        g["customer_id"] = head.get("customer_id")
        g["warehouse_id"] = head.get("warehouse_id")
        g["blocked_lines"] = [
            {"row": r["__row__"], "status": r["status"], "why": r["why"]}
            for r in checked
            if norm(r.get("external_no")) == norm(g["external_no"])
            and norm(r.get("customer")) == norm(g["customer"])
            and r["status"] != "ok"
        ]

    # 被挡下的行会让所属单据"不完整"，这些单不许导。
    # ⚠️ 键按 **单据号** 取（不再是「单据号+客户」），而且**好坏行都要**参与：
    #    一张源单只要有一行落不了地，整张源单就不许导 —— 包括它拆出来的其它工程子单。
    #    早先按「单据号+客户」取，实测 `test_待建客户会挡住整张单而不是丢行` 不过：
    #    XS 单里 A 工程在册、B 工程还没建档时，A 那半张被单独建出来，
    #    B 的货**静默丢掉**，而导入结果还报"成功 1 张"。宁可整单挡住让人补档案再导，
    #    也不许出现"金额少了一截、状态却是成功"的单。
    blocked_docs = {
        norm(r.get("external_no"))
        for r in checked
        if r["status"] != "ok" and (r.get("external_no") or "").strip()
    }
    for g in groups:
        g["incomplete"] = norm(g["external_no"]) in blocked_docs

    return {
        "source_file": source_file,
        "lines": checked,
        "line_total": len(checked),
        "ok_lines": len(ok_lines),
        "error_lines": len(checked) - len(ok_lines),
        "groups": groups,
        "new_groups": [g for g in groups if not g["imported_as"] and not g["incomplete"]],
        "skipped_groups": [g for g in groups if g["imported_as"]],
        "blocked_groups": [g for g in groups if g["incomplete"] and not g["imported_as"]],
        "total_amount": money(sum((_num(l.get("amount")) or ZERO for l in checked), ZERO)),
        "importable_amount": money(sum((g["total"] for g in groups
                                        if not g["imported_as"] and not g["incomplete"]), ZERO)),
        "miss_customers": sorted({r["customer"] for r in checked if r["status"] == "待建客户"}),
        "miss_products": sorted({r["product"] for r in checked if r["status"] == "待建商品"}),
        "miss_warehouses": sorted({r.get("warehouse") or "" for r in checked
                                   if r["status"] == "待定仓库"}),
        "issues": issues,
    }


def _alloc_order_no(db: Session, order_date: str) -> str:
    """按 `doc_no` 规则取号：XS + 年月日 + 3 位流水。

    ⚠️ 绝不能用 `ORDER BY order_no DESC LIMIT 1`（字符串序会撞号），
       统一走 `next_seq` 按数值取最大。
    """
    from app.models.sales_order import SalesOrder

    period = (order_date or "").replace("-", "")[:8]
    if len(period) != 8:
        period = datetime.now().strftime("%Y%m%d")
    prefix = prefix_of("sales_outbound")
    existing = [
        r[0]
        for r in db.query(SalesOrder.order_no)
        .filter(SalesOrder.order_no.like(f"{prefix}{period}%"))
        .all()
    ]
    return format_doc_no(prefix, period, next_seq(existing, prefix, period))


def _ensure_customers(db: Session, names: list[str]) -> dict[str, int]:
    """批量建客户档案（编码走 `build_partner_code`，不自己拼）。"""
    from app.models.customer import Customer

    codes = [c[0] for c in db.query(Customer.code).all()]
    out: dict[str, int] = {}
    for name in names:
        code = build_partner_code(codes, "customer")
        codes.append(code)
        cust = Customer(code=code, name=name)
        db.add(cust)
        db.flush()
        out[name] = cust.id
    return out


def _create_order(
    db: Session,
    group: dict[str, Any],
    *,
    doc_type: str,
    source_file: str,
) -> dict[str, Any]:
    """把一组明细建成一张单。**单张一个事务**，由调用方 commit/rollback。"""
    from app.api.v1.routes.erp_common import _apply_stock, _write_finance
    from app.models.sales_order import SalesOrder, SalesOrderItem

    order_date = group["order_date"] or datetime.now().strftime("%Y-%m-%d")
    order_no = _alloc_order_no(db, order_date)
    note = build_note(group["import_no"], source_file or "历史数据")

    order = SalesOrder(
        order_no=order_no,
        customer_id=group["customer_id"],
        status="draft",
        total_amount=ZERO,
        doc_type=doc_type,
        warehouse_id=group["warehouse_id"],
        order_date=order_date,
        note=note,
    )
    db.add(order)
    db.flush()

    total = ZERO
    items: list[SalesOrderItem] = []
    for line in group["lines"]:
        qty = int(_num(line["quantity"]) or 0)
        price = _num(line["unit_price"]) or ZERO
        amt = line_amount(price, qty)
        items.append(
            SalesOrderItem(
                sales_order_id=order.id,
                product_id=line["product_id"],
                quantity=qty,
                unit_price=price,
                amount=amt,
                product_name=line.get("product_name") or line["product"],
                standards=line.get("spec") or line.get("model") or None,
                unit=line.get("unit") or None,
                unit_factor=1,
                note=line.get("line_note") or None,
            )
        )
        total += amt
    db.add_all(items)
    total = money(total)

    order.total_amount = total
    order.receivable_amount = total if doc_type == "outbound" else ZERO
    order.discount_amount = ZERO
    order.received_amount = ZERO
    order.current_debt = total if doc_type == "outbound" else ZERO

    if doc_type == "outbound":
        # 库存：**每行一条**流水（与 create_sales_order 口径一致）
        for row in items:
            _apply_stock(
                db,
                product_id=row.product_id,
                warehouse_id=order.warehouse_id,
                quantity=row.quantity,
                transaction_type="outbound",
                unit_price=row.unit_price,
                related_type="sales_out",
                related_order_id=order.id,
                doc_no=order_no,
                unit_factor=1,
                note=f"历史导入出库 {order_no}",
            )
        # 应收：**整单一条**（不是每行一条）。
        # 收款登记按单冲减，一单挂 18 条应收会让出纳没法核销。
        if total > ZERO:
            _write_finance(
                db,
                transaction_type="receivable",
                direction="in",
                amount=total,
                related_type="sales_out",
                related_order_id=order.id,
                doc_no=order_no,
                customer_id=order.customer_id,
                warehouse_id=order.warehouse_id,
                occurred_at=order_date,
                note=f"历史导入应收 {order_no}",
            )

    order.status = "submitted"
    db.flush()
    return {"order_no": order_no, "lines": len(items), "total": total}


def import_sales_history(
    db: Session,
    lines: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    doc_type: str = "outbound",
    split_by_customer: bool = True,
    auto_create_customers: bool = False,
    source_file: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """导入历史销售单。`dry_run=True` 时全部回滚，只返回预检结果。

    返回：
      inspected  预检结果（逐行状态、将建的单）
      created    成功建单数
      skipped    已导过而跳过的单数
      failed     失败清单 [{外部单号, 原因}]
    """
    if doc_type not in ("outbound", "order"):
        raise ValueError("doc_type 只能是 outbound（销售出库单）或 order（销售订单）")

    result = validate(db, lines, split_by_customer=split_by_customer, source_file=source_file)
    created, skipped, failed = 0, 0, []
    created_orders: list[dict[str, Any]] = []
    grand = ZERO

    # 待建客户：先建出来，再把 id 回填到行上（同一个事务里，失败一起回滚）
    if auto_create_customers and result["miss_customers"]:
        id_map = _ensure_customers(db, result["miss_customers"])
        for line in result["lines"]:
            if line["status"] == "待建客户":
                line["customer_id"] = id_map.get(line["customer"])
                line["status"] = "ok"
                line["customer_name"] = line["customer"]
        # 重新校验一遍（客户建好了，之前被挡的行可能就通了）
        result = validate(db, lines, split_by_customer=split_by_customer, source_file=source_file)
        if auto_create_customers:
            for line in result["lines"]:
                if line["customer_id"] is None and line["customer"] in id_map:
                    line["customer_id"] = id_map[line["customer"]]

    todo = result["new_groups"]
    if limit:
        todo = todo[:limit]

    for group in todo:
        if group["customer_id"] is None or group["warehouse_id"] is None:
            failed.append({"外部单号": group["import_no"], "原因": "客户或仓库未落到档案"})
            continue
        try:
            with db.begin_nested():
                out = _create_order(db, group, doc_type=doc_type, source_file=source_file or "历史数据")
            created += 1
            grand += out["total"]
            created_orders.append({"外部单号": group["import_no"], **out})
        except Exception as exc:  # 单张失败不拖垮其他单
            failed.append({"外部单号": group["import_no"], "原因": f"{type(exc).__name__}: {exc}"})

    skipped = len(result["skipped_groups"])

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "dry_run": dry_run,
        "doc_type": doc_type,
        "inspected": {
            "source_file": result["source_file"],
            "line_total": result["line_total"],
            "ok_lines": result["ok_lines"],
            "error_lines": result["error_lines"],
            "groups": len(result["groups"]),
            "new_groups": len(result["new_groups"]),
            "blocked_groups": len(result["blocked_groups"]),
            "total_amount": str(result["total_amount"]),
            "importable_amount": str(result["importable_amount"]),
            "miss_customers": result["miss_customers"],
            "miss_products": result["miss_products"],
            "miss_warehouses": result["miss_warehouses"],
            "issues": result["issues"][:200],
        },
        "lines": result["lines"],
        "groups": result["groups"],
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "created_orders": created_orders,
        "imported_amount": str(money(grand)),
    }
