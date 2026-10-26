# -*- coding: utf-8 -*-
"""金额 / 费率的安全算术（Decimal 口径）—— 全站唯一入口。

## 为什么要有这个文件

数据库改成 `numeric(14,2)` 之后，psycopg 交给 Python 的是 `Decimal`，不再是 `float`。
于是两种写法会当场炸：

    Decimal("100.00") * 0.13        → TypeError: unsupported operand type(s)
    sum([Decimal("1"), Decimal("2")], 0.0)  → TypeError（第二个参数是起始值）

而更隐蔽的一类是"不炸但算错"：把 `Decimal` 转成 `float` 再累加，两位小数就开始漂。

所以约定三条：

1. **凡是"钱"，一律用本模块的函数**，不要在业务代码里手写 `+ - * /`。
2. **入库前 `money()`，出库（写 JSON）前 `as_float()`**。
   DB 里永远是两位小数的 Decimal，JSON 里永远是 float（浏览器只认 number）。
3. **单价（费率）用 `money_rate()`**：4 位，绝不截断成 2 位。
   `73.901 × 580 = 42,862.578 → 42,862.58`；把单价抹成 `73.90` 就变成 `42,862.00`。

## 两个容易踩的细节

* `Decimal(0.1)` 会得到 `0.1000000000000000055511151231257827...`（float 的二进制尾巴）。
  必须先 `str()` 再转：`Decimal(str(0.1))` == `Decimal("0.1")`。本模块的 `dec()` 已经这么做了。
* `round(Decimal, 2)` 用的是**银行家舍入**（2.675 → 2.67）。业务上要"四舍五入"，
  所以统一走 `quantize(..., ROUND_HALF_UP)`（2.675 → 2.68）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Optional

__all__ = [
    "CENT",
    "RATE_STEP",
    "ZERO",
    "dec",
    "money",
    "money_rate",
    "line_amount",
    "sum_money",
    "tax_from_total",
    "as_float",
]

CENT = Decimal("0.01")
RATE_STEP = Decimal("0.0001")
ZERO = Decimal("0.00")


def dec(value: object) -> Decimal:
    """任意输入 → Decimal。None / 空串 / 非法值一律当 0。

    ⚠️ 必须走 `str()` 中转：`Decimal(0.1)` 是 0.1000000000000000055…，
    而 `Decimal(str(0.1))` 才是干净的 0.1。
    """
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        # 保持原值，不在这里量化 —— 量化交给 money()/money_rate()，免得把 4 位单价压成 2 位
        return value
    if isinstance(value, bool):  # bool 是 int 的子类，先拦掉，避免 True 变成 1 元
        return ZERO
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return ZERO


def money(value: object) -> Decimal:
    """金额：量化到 2 位，四舍五入（2.675 → 2.68，不是银行家的 2.67）。"""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_rate(value: object) -> Decimal:
    """单价 / 单位成本：量化到 4 位。**不要用 money() 处理单价。**"""
    return dec(value).quantize(RATE_STEP, rounding=ROUND_HALF_UP)


def line_amount(unit_price: object, quantity: object) -> Decimal:
    """行金额 = 单价(4 位) × 数量 → 2 位。

    顺序很重要：先按 4 位锁定单价，再乘，最后才收 2 位。
    先收 2 位再乘，就是 `73.90 × 580` 那个经典错。
    """
    return money(money_rate(unit_price) * dec(quantity))


def sum_money(values: Iterable[object]) -> Decimal:
    """金额合计：逐项量化后累加（**不是**"合计单价 × 合计数量"）。

    起始值是 Decimal，不是 0.0 —— 用 0.0 起步会直接 TypeError。
    """
    total = ZERO
    for value in values:
        total += money(value)
    return money(total)


def tax_from_total(total: object, tax_rate: object) -> tuple[Decimal, Decimal]:
    """价税合计 → (不含税额, 税额)。

    税率是"百分比"（13 表示 13%），所以除数是 `1 + rate/100`。
    返回两个 Decimal，调用方不用再 round。
    """
    gross = money(total)
    rate = dec(tax_rate)
    if rate <= 0:
        return gross, ZERO
    net = money(gross / (Decimal(1) + rate / Decimal(100)))
    return net, money(gross - net)


def as_float(value: object) -> Optional[float]:
    """出库（写进 JSON / Pydantic 返回）用：Decimal → float。

    `None` 保持 `None`（不要变成 0.0：前端靠"有没有值"区分"没填"和"填了 0"）。

    ⚠️ 这里**不量化**：单价是 4 位，若在这一层统一收成 2 位，
    `73.901` 会变 `73.9`，前端再乘数量就少钱。要 2 位请在业务层先 `money()`。
    """
    if value is None:
        return None
    return float(dec(value))
