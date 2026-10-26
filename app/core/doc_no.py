# -*- coding: utf-8 -*-
"""单据号前缀与往来单位编码的**唯一权威**（第一阶段 · 2026-10-20）。

为什么要有这个模块
------------------
改造前前缀散落在 19 个路由里各写各的字符串字面量：销售订单 `XSD`、销售出库 `XS`，
采购订单 `CGD`、采购入库 `CG`，调拨单 `DBD`…… 同一个业务两种前缀，客户对账时
"这张到底是订单还是出库单"要看单号猜，猜错就是一场电话。

现在：**任何新单据的号，前缀只能从本文件取**。路由里出现裸字符串前缀即为违规
（`scripts/verify_doc_no_prefix.py` 会扫）。

两条硬规则
----------
1. **历史单据不追溯**。这里只影响"以后新生成"的号，库里已有的 `XSD20261010001`
   原样保留，查询/打印/对账都不受影响。
2. **同表共用前缀不冲突**。销售订单与销售出库同在 `sales_orders` 表，前缀都是 `XS`
   之后仍由 `_next_doc_no` 按"当天最大号 +1"取号 —— 同一张表内序号连续，不会重号。
   反过来，如果订单和出库单分两个前缀，顺序号才会出现"各自从 001 开始"的跳号。

前缀清单（用户 2026-10-20 指定）
-------------------------------
| 业务 | key | 前缀 |
|---|---|---|
| 销售出库 / 销售订单 | sales_outbound / sales_order | **XS** |
| 采购入库 / 采购订单 | purchase_inbound / purchase_order | **CG** |
| 对账单 | statement | **DZ** |
| 销售退货 | sales_return | **XSTH** |
| 采购退货 | purchase_return | **CGTH** |
| 报价单 | quotation | **BJ** |
| 调拨单 | inventory_transfer | **DB** |
| 财务流水 | financial_flow | **FL** |
| 合同 | contract | **HT** |

用户清单之外的单据（生产、盘点、报损报溢、装配、银行转账）**保持原有前缀不动**，
只是搬进本表登记，避免"改了没要求的东西"。
"""

from __future__ import annotations

from collections.abc import Iterable

# ============================================================
# 一、单据号前缀
# ============================================================
DOC_NO_PREFIX: dict[str, str] = {
    # —— 用户指定统一的前缀 ——
    "sales_order": "XS",
    "sales_outbound": "XS",
    "purchase_order": "CG",
    "purchase_inbound": "CG",
    "statement": "DZ",
    "sales_return": "XSTH",
    "purchase_return": "CGTH",
    "quotation": "BJ",
    "inventory_transfer": "DB",
    "financial_flow": "FL",
    "contract": "HT",
    # —— 用户清单之外：沿用历史前缀，仅登记备查 ——
    "stocktaking": "PD",          # 盘点单
    "inventory_scrap": "BS",      # 报损单
    "inventory_overflow": "BY",   # 报溢单
    "assembly_combo": "ZH",       # 组合单
    "assembly_split": "CX",       # 拆卸单
    "production_plan_self": "SCJH",    # 自制生产计划
    "production_plan_outsource": "WWJH",  # 委外生产计划
    "material_issue": "SCLL",     # 生产领料
    "material_return": "SCTL",    # 生产退料
    "finished_goods": "CPRK",     # 成品入库
    "outsourcing": "WWJG",        # 委外加工
    "bank_transfer": "TR",        # 银行转账单
}

# 中文名：给错误提示与文档用（不是前端标签，别拿它渲染列表）
DOC_NO_LABELS: dict[str, str] = {
    "sales_order": "销售订单",
    "sales_outbound": "销售出库单",
    "purchase_order": "采购订单",
    "purchase_inbound": "采购入库单",
    "statement": "对账单",
    "sales_return": "销售退货单",
    "purchase_return": "采购退货单",
    "quotation": "报价单",
    "inventory_transfer": "调拨单",
    "financial_flow": "财务流水",
    "contract": "合同",
    "stocktaking": "盘点单",
    "inventory_scrap": "报损单",
    "inventory_overflow": "报溢单",
    "assembly_combo": "组合单",
    "assembly_split": "拆卸单",
    "production_plan_self": "自制生产计划",
    "production_plan_outsource": "委外生产计划",
    "material_issue": "生产领料单",
    "material_return": "生产退料单",
    "finished_goods": "成品入库单",
    "outsourcing": "委外加工单",
    "bank_transfer": "银行转账单",
}

# 单号流水位数：正常 3 位（XS20261020001），超过 999 自动升到 4 位（1000）。
# ⚠️ 不要为了"整齐"强行截断回 3 位 —— 那是重号。
SEQ_WIDTH = 3


def prefix_of(kind: str) -> str:
    """取前缀。key 写错时给一个能看懂的报错，而不是 KeyError。

    路由里一律写 `prefix_of("sales_outbound")`，**不要**写 `"XS"`：
    字符串散落是这次改造要根治的病，再写死一个就等于没改。
    """
    try:
        return DOC_NO_PREFIX[kind]
    except KeyError as exc:  # pragma: no cover - 只在开发者写错 key 时触发
        raise KeyError(
            f"未知的单据类型 {kind!r}：请在 app/core/doc_no.py 的 DOC_NO_PREFIX 里登记"
        ) from exc


def label_of(kind: str) -> str:
    return DOC_NO_LABELS.get(kind, kind)


# ============================================================
# 二、单号拼装（纯函数，不碰数据库，方便单测）
# ============================================================
def parse_seq(value: str, prefix: str, period: str) -> int | None:
    """从 `XS20261020007` 里取出 7；格式不符返回 None。

    只认 `前缀 + 8 位日期 + 纯数字`。历史单号里混进别的格式（人手填的、
    从别的系统导进来的）一律跳过，不参与取最大号 —— 否则一个脏数据就能把
    当天流水号顶到天上。
    """
    head = f"{prefix}{period}"
    if not value or not value.startswith(head):
        return None
    tail = value[len(head):]
    if not tail.isdigit():
        return None
    return int(tail)


def next_seq(existing: Iterable[str], prefix: str, period: str) -> int:
    """当天已存在的同前缀单号里，取最大流水 +1；一张都没有则从 1 开始。

    ⚠️ 这里按**数值**取最大，不是按字符串排序取最后一条。
    改造前 `_next_doc_no` 用 `ORDER BY order_no DESC LIMIT 1`，一旦某天超过 999 单
    写出 `...1000`，字符串序里 `...999` 反而更大 → 算出来还是 1000 → 撞号 400。
    单日千单在批发场景并不罕见（一次导入就上千行）。
    """
    best = 0
    for value in existing:
        seq = parse_seq(str(value or ""), prefix, period)
        if seq is not None and seq > best:
            best = seq
    return best + 1


def format_doc_no(prefix: str, period: str, seq: int, width: int = SEQ_WIDTH) -> str:
    """拼单号：`XS` + `20261020` + `001`。

    `width` 只是**最小宽度**：seq=1000 时自然变成 `1000`（4 位），不会被截断。
    """
    return f"{prefix}{period}{seq:0{width}d}"


# ============================================================
# 三、客户 / 供应商编码规则（2026-10-20 新增）
# ============================================================
# 客户以「甲」开头、供应商以「乙」开头，后面是固定业务码 + 4 位流水：
#   甲CUS0001、乙SUP0001
# 为什么不用日期：往来单位编码是**长期身份**，一年后新建的客户还叫 0002 更自然；
# 日期只适合"每天重新排队"的单据号。
PARTNER_CODE_RULES: dict[str, dict[str, str]] = {
    "customer": {"lead": "甲", "base": "CUS"},
    "supplier": {"lead": "乙", "base": "SUP"},
}

PARTNER_SEQ_WIDTH = 4


def partner_code_head(kind: str) -> str:
    rule = PARTNER_CODE_RULES.get(kind)
    if rule is None:  # pragma: no cover
        raise KeyError(f"未知的往来单位类型 {kind!r}：只能是 customer / supplier")
    return f"{rule['lead']}{rule['base']}"


def next_partner_seq(existing: Iterable[str], kind: str) -> int:
    """已有编码里取最大流水 +1。

    只认「甲CUS + 纯数字」，历史编码（`CUS20261010001`、手填的 `KH001`）不参与，
    因此新规则可以从 0001 重新起步，不会与老编码冲突 —— 两者字面段不同。
    """
    head = partner_code_head(kind)
    best = 0
    for value in existing:
        text = str(value or "")
        if not text.startswith(head):
            continue
        tail = text[len(head):]
        if tail.isdigit() and int(tail) > best:
            best = int(tail)
    return best + 1


def format_partner_code(kind: str, seq: int, width: int = PARTNER_SEQ_WIDTH) -> str:
    return f"{partner_code_head(kind)}{seq:0{width}d}"


def build_partner_code(existing: Iterable[str], kind: str) -> str:
    return format_partner_code(kind, next_partner_seq(existing, kind))
