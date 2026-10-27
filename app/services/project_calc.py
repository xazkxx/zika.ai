"""项目资金试算（沙盘推演）—— 纯计算内核（2026-10-26，v1.81.0）

为什么单独成一个 `services` 模块，而不是塞进路由
--------------------------------------------------
1. **它是计算器，不是业务**。没有单据生命周期、没有库存联动、没有财务流水，
   连 `Session` 都不 import —— 这个文件里**物理上写不了库**，「绝不写库」这条红线
   靠代码结构保证，而不是靠"我记得别 commit"。
2. **口径必须只有一份**。公式来自用户提供的《电线采购销售税额试算表_v6.xlsx》，
   逐格对照后落在这里（见每个函数的注释）；路由、单测、将来的前端本地预览
   都调这一个函数，不会出现"页面上和报表里差一分钱"。
3. 纯函数好测：`tests/test_project_calc.py` 直接喂 Excel 的锚点数，不连库、不起服务。

与 Excel 的三个刻意差异（都写在 `warnings` 里明示，不静默改数）
--------------------------------------------------------------
· 增值税留抵（销项 < 进项）时，附加税基数取 0 —— Excel 会算出负数附加税，
  那不是"退税"，是错的。增值税本身仍按 `ROUND(销项-进项)` 保留（负数=留抵）。
· 税前利润为负时，企业所得税记 0 —— 亏损只能结转，不能当退税。
· 进项按**行**计算后再汇总（对应成本表 J 列 `IF(专票, I*G, 0)` 逐行求和），
  而不是"成本不含税合计 × 税率"。全部专票时两者相等；混合专票/普票时只有逐行才对。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
RATIO = Decimal("0.0001")


# ---------------------------------------------------------------------------
# 默认参数：与 Excel v6 / 现行小微口径一致
# ---------------------------------------------------------------------------
DEFAULTS: dict[str, str | int | bool] = {
    "vat_rate": "0.13",            # 增值税率（一般计税）
    "surcharge_half": True,        # 六税两费减半
    "city_rate": "0.07",           # 城建税
    "edu_rate": "0.03",            # 教育费附加
    "ledu_rate": "0.02",           # 地方教育附加
    "water_rate": "0.00045",       # 水利基金（销售不含税 × 0.045%）
    "stamp_rate": "0.0003",        # 印花税（购销含税合计 × 0.03%）
    "income_rate": "0.05",         # 企业所得税（小微）
    # —— 资金占用（Excel 没有，本模块新增的核心）——
    "capital_daily_rate": "0.0002",  # 日资金成本 0.02% ≈ 年化 7.30%
    "pay_days": 30,                  # 付款周期：多久付给上游
    "collect_days": 60,              # 回款周期：多久收回下游货款
    "prepay": "0",                   # 下游预收款（抵减垫资）
    "prepay_supplier": "0",          # 上游已付定金（抵减垫资）
    "include_income_tax_in_advance": False,  # 所得税是否计入垫资（默认不计）
}

# 回款敏感性：固定付款周期，只动回款天数
SENSITIVITY_DAYS = (0, 30, 60, 90, 120)


def default_settings() -> dict:
    """给前端「恢复默认」按钮用；返回副本，别让人改到模块级常量。"""
    return dict(DEFAULTS)


def _dec(value, fallback: str = "0") -> Decimal:
    """宽松转 Decimal。空串/None/脏数据都落回 fallback —— 测算工具不能因为
    某一行漏填就整页 500。"""
    if value is None or value == "":
        return Decimal(fallback)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(fallback)


def _r2(value: Decimal) -> Decimal:
    """Excel `ROUND(x,2)` 的等价物：四舍五入到分（ROUND_HALF_UP，不是银行家舍入）。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> str:
    """金额一律出字符串：JS 的 Number 接 216431.88 再算一次会抖出 .8799999。"""
    return str(_r2(value))


def _ratio(value: Decimal) -> str:
    """比率出 4 位小数的**小数形式**（0.3094），前端自己乘 100 显示。"""
    if value == 0:
        return "0.0000"
    return str(value.quantize(RATIO, rounding=ROUND_HALF_UP))


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _qty_text(value: Decimal) -> str:
    """数量文本：`Decimal("50").normalize()` 会变成 `5E+1`，直接 str() 会吓到用户。"""
    return format(value.normalize(), "f")


def normalize_settings(raw: dict | None) -> dict:
    """把前端传来的参数收敛成一份**类型稳定**的配置（字符串金额里带逗号也认）。"""
    src = {**DEFAULTS, **(raw or {})}
    out: dict = {}
    for key in ("vat_rate", "city_rate", "edu_rate", "ledu_rate", "water_rate",
                "stamp_rate", "income_rate", "capital_daily_rate"):
        out[key] = str(_dec(src.get(key), str(DEFAULTS[key])))
    for key in ("prepay", "prepay_supplier"):
        out[key] = _money(_dec(src.get(key)))
    for key in ("pay_days", "collect_days"):
        out[key] = int(_dec(src.get(key), str(DEFAULTS[key])))
    out["surcharge_half"] = _flag(src.get("surcharge_half", DEFAULTS["surcharge_half"]))
    out["include_income_tax_in_advance"] = _flag(src.get("include_income_tax_in_advance"))
    return out


def normalize_lines(raw_lines) -> list[dict]:
    """明细行归一：`cost_qty` 没填就按销售数量走（"一批进一批出"的老习惯）。"""
    lines: list[dict] = []
    for index, item in enumerate(raw_lines or []):
        item = item or {}
        qty = _dec(item.get("qty"))
        raw_cost_qty = item.get("cost_qty")
        cost_qty = qty if raw_cost_qty in (None, "") else _dec(raw_cost_qty)
        lines.append(
            {
                "index": index,
                "product": str(item.get("product") or "").strip(),
                "unit": str(item.get("unit") or "").strip(),
                "qty": qty,
                "sale_price": _dec(item.get("sale_price")),
                "cost_qty": cost_qty,
                "cost_price": _dec(item.get("cost_price")),
                "has_invoice": _flag(item.get("has_invoice", True)),  # Excel 默认 2=专票
            }
        )
    return lines


def compute(payload: dict | None) -> dict:
    """一次测算的全部结果。

    `payload = {"lines": [...], "settings": {...}}`；返回的金额一律是**两位小数字符串**。
    """
    payload = payload or {}
    settings = normalize_settings(payload.get("settings"))
    lines = normalize_lines(payload.get("lines"))

    vat_rate = _dec(settings["vat_rate"])
    city_rate = _dec(settings["city_rate"])
    edu_rate = _dec(settings["edu_rate"])
    ledu_rate = _dec(settings["ledu_rate"])
    water_rate = _dec(settings["water_rate"])
    stamp_rate = _dec(settings["stamp_rate"])
    income_rate = _dec(settings["income_rate"])
    daily_rate = _dec(settings["capital_daily_rate"])
    divisor = Decimal("2") if settings["surcharge_half"] else Decimal("1")

    # ---------------- 1. 进销两端（含税 → 不含税） ----------------
    sale_qty = Decimal("0")
    sale_incl = Decimal("0")
    cost_qty = Decimal("0")
    cost_incl = Decimal("0")
    vat_in = Decimal("0")          # 进项税额：只有专票才有
    no_invoice_rows = 0
    stock_rows = 0

    for line in lines:
        sale_qty += line["qty"]
        sale_incl += line["qty"] * line["sale_price"]
        cost_qty += line["cost_qty"]
        line_cost_incl = line["cost_qty"] * line["cost_price"]
        cost_incl += line_cost_incl
        if line["has_invoice"]:
            # 逐行反算，对齐成本表 J 列 `=IF(专票, I/1.13*0.13, 0)`
            vat_in += line_cost_incl / (Decimal("1") + vat_rate) * vat_rate
        else:
            no_invoice_rows += 1
        if line["cost_qty"] > line["qty"]:
            stock_rows += 1

    one_plus = Decimal("1") + vat_rate
    sale_excl = sale_incl / one_plus
    sale_out_vat = sale_excl * vat_rate
    cost_excl = cost_incl / one_plus

    vat_due = _r2(sale_out_vat - vat_in)              # 可负：负数=留抵
    vat_cash = max(vat_due, Decimal("0"))             # 附加税/垫资只认**实缴**
    credit_carry = -vat_due if vat_due < 0 else Decimal("0")

    # ---------------- 2. 六个税种（先各自 ROUND 到分，再求和） ----------------
    city = _r2(vat_cash * city_rate / divisor)
    edu = _r2(vat_cash * edu_rate / divisor)
    ledu = _r2(vat_cash * ledu_rate / divisor)
    stamp = _r2((sale_incl + cost_incl) * stamp_rate / divisor)
    water = _r2(sale_excl * water_rate)

    gross_profit = _r2(sale_excl - cost_excl)   # Excel D12：不含税毛利，不是含税差
    sell_taxes = city + edu + ledu + stamp + water    # 不含增值税、不含所得税
    pretax_profit = _r2(gross_profit - sell_taxes)
    income_tax = _r2(pretax_profit * income_rate) if pretax_profit > 0 else Decimal("0")
    net_profit = _r2(pretax_profit - income_tax)
    tax_total = _r2(vat_due + sell_taxes + income_tax)

    # ---------------- 3. 资金占用（Excel 没有，本模块新增） ----------------
    prepay = _dec(settings["prepay"])
    prepay_supplier = _dec(settings["prepay_supplier"])
    cash_tax = vat_cash + sell_taxes
    advance_gross = cost_incl + cash_tax
    if settings["include_income_tax_in_advance"]:
        advance_gross += income_tax
    advance_base = advance_gross - prepay - prepay_supplier
    advance = _r2(max(advance_base, Decimal("0")))
    occupy_days = max(int(settings["collect_days"]) - int(settings["pay_days"]), 0)
    occupy_fee = _r2(advance * occupy_days * daily_rate)
    net_after_fee = _r2(net_profit - occupy_fee)

    sensitivity = []
    day_points = sorted({*SENSITIVITY_DAYS, int(settings["collect_days"])})
    for point in day_points:
        days = max(point - int(settings["pay_days"]), 0)
        fee = _r2(advance * days * daily_rate)
        net = _r2(net_profit - fee)
        sensitivity.append(
            {
                "collect_days": point,
                "days": days,
                "fee": _money(fee),
                "net_after_fee": _money(net),
                "margin": _ratio(net / sale_excl if sale_excl else Decimal("0")),
            }
        )

    # ---------------- 4. 口径提示（说清"为什么和直觉不一样"） ----------------
    warnings: list[str] = []
    if sale_incl <= 0:
        warnings.append("还没有填销售金额，先把卖价和数量填上。")
    if credit_carry > 0:
        warnings.append(
            f"进项大于销项，增值税留抵 {_money(credit_carry)}，本期不缴；"
            "附加税基数按 0 计（Excel 直接算会得出负附加税，那是错的）。"
        )
    if no_invoice_rows:
        warnings.append(
            f"{no_invoice_rows} 行未取得专票：成本仍按含税价倒推不含税，但进项按 0 计，"
            "增值税会偏高 —— 这就是「不要专票」的真实代价。"
        )
    if pretax_profit <= 0:
        warnings.append("税前利润为负，企业所得税记 0（亏损只能结转，不能当退税）。")
    if advance_base < 0:
        warnings.append(
            f"预收 {_money(prepay)} + 定金 {_money(prepay_supplier)} 已覆盖成本与税费，"
            "本项目不需要垫资。"
        )
    if stock_rows:
        warnings.append(
            f"{stock_rows} 行采购数量大于销售数量：多出来的部分形成库存沉淀，"
            "只压资金、不产生本次利润。"
        )
    if int(settings["collect_days"]) < int(settings["pay_days"]):
        warnings.append("回款早于付款，资金占用按 0 天计（正现金流项目）。")

    return {
        "settings": settings,
        "summary": {
            "sale_qty": _qty_text(sale_qty),
            "sale_incl": _money(sale_incl),
            "sale_excl": _money(sale_excl),
            "sale_out_vat": _money(sale_out_vat),
            "cost_qty": _qty_text(cost_qty),
            "cost_incl": _money(cost_incl),
            "cost_excl": _money(cost_excl),
            "vat_in": _money(vat_in),
            "gross_profit": _money(gross_profit),
            "gross_margin": _ratio(gross_profit / sale_excl if sale_excl else Decimal("0")),
        },
        "taxes": [
            {"key": "vat", "label": "增值税", "base": _money(sale_excl),
             "rate": settings["vat_rate"], "amount": _money(vat_due), "note": "销项 - 进项"},
            {"key": "city", "label": "城建税", "base": _money(vat_cash),
             "rate": str(city_rate / divisor), "amount": _money(city), "note": "增值税 × 7%"},
            {"key": "edu", "label": "教育费附加", "base": _money(vat_cash),
             "rate": str(edu_rate / divisor), "amount": _money(edu), "note": "增值税 × 3%"},
            {"key": "ledu", "label": "地方教育附加", "base": _money(vat_cash),
             "rate": str(ledu_rate / divisor), "amount": _money(ledu), "note": "增值税 × 2%"},
            {"key": "stamp", "label": "印花税", "base": _money(sale_incl + cost_incl),
             "rate": str(stamp_rate / divisor), "amount": _money(stamp),
             "note": "购销含税 × 0.03%"},
            {"key": "water", "label": "水利基金", "base": _money(sale_excl),
             "rate": settings["water_rate"], "amount": _money(water),
             "note": "销售不含税 × 0.045%"},
            {"key": "income", "label": "企业所得税",
             "base": _money(max(pretax_profit, Decimal("0"))),
             "rate": settings["income_rate"], "amount": _money(income_tax),
             "note": "税前利润 × 5%"},
        ],
        "totals": {
            "vat_due": _money(vat_due),
            "sell_taxes": _money(sell_taxes),
            "tax_total": _money(tax_total),
            "pretax_profit": _money(pretax_profit),
            "income_tax": _money(income_tax),
            "net_profit": _money(net_profit),
            "net_margin": _ratio(net_profit / sale_excl if sale_excl else Decimal("0")),
        },
        "capital": {
            "advance": _money(advance),
            "advance_gross": _money(advance_gross),
            "occupy_days": occupy_days,
            "daily_rate": settings["capital_daily_rate"],
            "annual_rate": str(_dec(settings["capital_daily_rate"]) * Decimal("365")),
            "fee": _money(occupy_fee),
            "net_after_fee": _money(net_after_fee),
            "net_after_margin": _ratio(net_after_fee / sale_excl if sale_excl else Decimal("0")),
            "components": [
                {"key": "cost", "label": "货款（含税）", "amount": _money(cost_incl)},
                {"key": "tax", "label": "流转税现金", "amount": _money(cash_tax)},
                {"key": "prepay", "label": "预收抵扣", "amount": _money(-prepay)},
                {"key": "deposit", "label": "上游定金", "amount": _money(-prepay_supplier)},
            ],
        },
        "sensitivity": sensitivity,
        "warnings": warnings,
    }
