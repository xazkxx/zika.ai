"""项目资金试算（`app/services/project_calc.py`）的口径回归（v1.81.0，2026-10-26）。

## 这份测试为什么重要

这个模块的每个数字都是要给老板拍板用的。所以断言不是"差不多"，而是**精确到分**：

1. **Excel 锚点**：直接拿《电线采购销售税额试算表_v6.xlsx》里两批的合计填进去，
   断言所得税 / 税金合计 / 税后净利与 Excel A41-A43 注记逐分一致
   （第 2 批 26,390.62 / 101,048.82 / 501,421.72）。差一分就说明口径漂了。
2. **`gross_profit` 必须是不含税毛利**（Excel D12 = D4 − D7）。这条踩过：写成
   `含税−含税` 会得到 861,270.25，比正解多 99,084.19 —— 正好是一个增值税，
   看着"很像对的"，实际把税当成利润了。
3. **「进 306 卖 50」**：采购数量与销售数量分开，压货的资金沉淀才算得出来。
4. **只读红线**：算核连 `Session` 都不 import；接口跑完四张表条数不变。

## 跑法

    python -m pytest tests/test_project_calc.py -v

纯函数部分不连库；末尾的接口级只读断言需要测试库（`TEST_DATABASE_URL`），
连不上会 `skip` 而不是假通过。
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from app.services.project_calc import compute, default_settings, normalize_lines

# —— Excel v6 的三组锚点（金额都是含税）——
BATCH1 = {"sale_incl": "785582.08", "cost_incl": "526782.37"}
BATCH2 = {"sale_incl": "1831985.94", "cost_incl": "1229515.40"}
TOTAL = {"sale_incl": "2617568.02", "cost_incl": "1756297.77"}


def _one(sale_incl: str, cost_incl: str, **extra) -> dict:
    """把"一整批"压成一行：数量 1，单价=金额。数学上与逐行相加完全等价。"""
    line = {"product": "合计", "qty": "1", "sale_price": sale_incl, "cost_price": cost_incl}
    line.update(extra)
    return compute({"lines": [line]})


# ---------------------------------------------------------------------------
# 1. Excel 锚点
# ---------------------------------------------------------------------------
def test_锚点_第2批与Excel注记逐分一致():
    result = _one(BATCH2["sale_incl"], BATCH2["cost_incl"])
    assert result["totals"]["income_tax"] == "26390.62"
    assert result["totals"]["tax_total"] == "101048.82"
    assert result["totals"]["net_profit"] == "501421.72"
    assert result["totals"]["vat_due"] == "69310.77"


def test_锚点_第1批():
    result = _one(BATCH1["sale_incl"], BATCH1["cost_incl"])
    assert result["totals"]["income_tax"] == "11336.51"
    assert result["totals"]["tax_total"] == "43406.02"
    assert result["totals"]["net_profit"] == "215393.69"


def test_锚点_两批合计():
    result = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])
    summary, totals = result["summary"], result["totals"]
    assert summary["sale_excl"] == "2316431.88"
    assert summary["cost_excl"] == "1554245.81"
    assert summary["gross_profit"] == "762186.06"      # 不含税毛利，不是 861270.25
    assert summary["gross_margin"] == "0.3290"
    assert totals["vat_due"] == "99084.19"
    assert totals["tax_total"] == "144454.84"
    assert totals["net_profit"] == "716815.41"
    assert totals["net_margin"] == "0.3094"


def test_毛利必须按不含税算_不能把增值税当利润():
    result = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])
    assert result["summary"]["gross_profit"] != "861270.25"
    assert result["summary"]["gross_profit"] == "762186.06"


def test_七个税种各自到分再求和():
    """先 ROUND 再相加，与"加完再 ROUND"会差几分钱，Excel 是前者。"""
    taxes = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])["taxes"]
    amounts = {tax["key"]: tax["amount"] for tax in taxes}
    assert amounts["vat"] == "99084.19"
    assert amounts["city"] == "3467.95"          # 99084.19 × 7% ÷ 2
    assert amounts["edu"] == "1486.26"
    assert amounts["ledu"] == "990.84"
    assert amounts["stamp"] == "656.08"          # (含税销售 + 含税成本) × 0.03% ÷ 2
    assert amounts["water"] == "1042.39"         # 不含税销售额 × 0.045%
    assert amounts["income"] == "37727.13"
    summed = sum(float(value) for value in amounts.values())
    assert round(summed, 2) == 144454.84


def test_所得税不进税前利润扣减项():
    """老口径"毛利 × 5%"会多算 267.37（第 2 批），这里锁死正确口径。"""
    result = _one(BATCH2["sale_incl"], BATCH2["cost_incl"])
    pretax = float(result["totals"]["pretax_profit"])
    gross = float(result["summary"]["gross_profit"])
    assert round(gross - pretax, 2) == 5347.43        # 只扣了五个流转税
    assert result["totals"]["income_tax"] == "26390.62"
    assert result["totals"]["income_tax"] != "26657.99"


# ---------------------------------------------------------------------------
# 2. 合计口径 / 未取专票 / 六税两费
# ---------------------------------------------------------------------------
def test_合计一律用合计口径重算():
    """Excel 的合计列不是 B+C 逐行相加，而是用合计金额重新除/乘。

    这里用同一组数验证：多行相加的结果 与 合成一行重算的结果**完全一致**，
    说明算核确实走"先汇总再算"，而不是"逐行算完再累加"。
    """
    split = compute(
        {
            "lines": [
                {"qty": "1", "sale_price": BATCH1["sale_incl"], "cost_price": BATCH1["cost_incl"]},
                {"qty": "1", "sale_price": BATCH2["sale_incl"], "cost_price": BATCH2["cost_incl"]},
            ]
        }
    )
    merged = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])
    for key in ("vat_due", "sell_taxes", "tax_total", "pretax_profit", "income_tax", "net_profit"):
        assert split["totals"][key] == merged["totals"][key], key


def test_未取专票_成本不含税照旧进项按0():
    with_invoice = _one("1130", "565")
    without = _one("1130", "565", has_invoice=False)
    # 成本不含税一分不动：仍是 565/1.13
    assert without["summary"]["cost_excl"] == with_invoice["summary"]["cost_excl"] == "500.00"
    assert with_invoice["summary"]["vat_in"] == "65.00"
    assert without["summary"]["vat_in"] == "0.00"
    # 进项为 0 → 增值税正好等于销项
    assert without["totals"]["vat_due"] == "130.00"
    assert float(without["totals"]["vat_due"]) > float(with_invoice["totals"]["vat_due"])
    assert any("未取得专票" in warning for warning in without["warnings"])


def test_六税两费减半开关():
    half = _one("1130", "565")["taxes"]
    full = compute(
        {
            "lines": [{"qty": "1", "sale_price": "1130", "cost_price": "565"}],
            "settings": {"surcharge_half": False},
        }
    )["taxes"]
    half_city = {tax["key"]: tax["amount"] for tax in half}["city"]
    full_city = {tax["key"]: tax["amount"] for tax in full}["city"]
    assert half_city == "2.28"      # 65 × 7% ÷ 2 = 2.275 → 2.28
    assert full_city == "4.55"
    # 减半差异只体现在分位四舍五入上：2.28 的两倍是 4.56，比全额 4.55 多一分，
    # 这正是"先 ROUND 再相加"的必然结果，不是 bug。
    assert abs(float(full_city) - float(half_city) * 2) <= 0.01


# ---------------------------------------------------------------------------
# 3. 资金占用（Excel 里没有，本模块的核心增量）
# ---------------------------------------------------------------------------
def test_资金占用_两批合计锚点():
    capital = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])["capital"]
    assert capital["advance"] == "1863025.48"      # 成本含税 + 流转税现金
    assert capital["occupy_days"] == 30            # 回款 60 − 付款 30
    assert capital["fee"] == "11178.15"
    assert capital["net_after_fee"] == "705637.26"
    assert capital["net_after_margin"] == "0.3046"
    assert capital["annual_rate"] == "0.0730"      # 0.02%/日 × 365


def test_敏感性_回款越慢净利越低():
    sensitivity = {row["collect_days"]: row for row in _one(TOTAL["sale_incl"], TOTAL["cost_incl"])["sensitivity"]}
    assert sensitivity[30]["days"] == 0 and sensitivity[30]["fee"] == "0.00"
    assert sensitivity[60]["fee"] == "11178.15"
    assert sensitivity[90]["fee"] == "22356.31" and sensitivity[90]["net_after_fee"] == "694459.10"
    assert sensitivity[120]["fee"] == "33534.46" and sensitivity[120]["net_after_fee"] == "683280.95"
    assert sensitivity[120]["margin"] == "0.2950"
    # 单调：回款越久，落袋越少
    ordered = [sensitivity[day]["net_after_fee"] for day in (30, 60, 90, 120)]
    assert ordered == sorted(ordered, reverse=True)


def test_负占用记0_不出现负数():
    capital = compute(
        {
            "lines": [{"qty": "1", "sale_price": TOTAL["sale_incl"], "cost_price": TOTAL["cost_incl"]}],
            "settings": {"collect_days": 15, "pay_days": 45},
        }
    )["capital"]
    assert capital["occupy_days"] == 0
    assert capital["fee"] == "0.00"
    assert capital["net_after_fee"] == "716815.41"


def test_预收与定金抵减垫资():
    base = _one(TOTAL["sale_incl"], TOTAL["cost_incl"])["capital"]["advance"]
    reduced = compute(
        {
            "lines": [{"qty": "1", "sale_price": TOTAL["sale_incl"], "cost_price": TOTAL["cost_incl"]}],
            "settings": {"prepay": "100000", "prepay_supplier": "63025.48"},
        }
    )["capital"]["advance"]
    assert base == "1863025.48"
    assert reduced == "1700000.00"


# ---------------------------------------------------------------------------
# 4. 边界：空行 / 进销数量分开 / 留抵
# ---------------------------------------------------------------------------
def test_空输入不报错且全为0():
    result = compute({})
    assert result["summary"]["sale_incl"] == "0.00"
    assert result["totals"]["net_profit"] == "0.00"
    assert result["capital"]["advance"] == "0.00"
    assert any("还没有填销售金额" in warning for warning in result["warnings"])


def test_进306卖50_压货垫资与留抵():
    """贸易常态：进一大批、卖一小批。多出来的库存只压钱不出利润。"""
    result = compute(
        {
            "lines": [
                {
                    "product": "4x50",
                    "unit": "米",
                    "qty": "50",
                    "cost_qty": "306",
                    "sale_price": "319.85",
                    "cost_price": "214.66",
                }
            ]
        }
    )
    assert result["summary"]["sale_qty"] == "50"
    assert result["summary"]["cost_qty"] == "306"
    assert result["summary"]["sale_incl"] == "15992.50"
    assert result["summary"]["cost_incl"] == "65685.96"
    # 进项远大于销项 → 增值税留抵，附加税基数按 0
    assert float(result["totals"]["vat_due"]) < 0
    taxes = {tax["key"]: tax["amount"] for tax in result["taxes"]}
    assert taxes["city"] == "0.00" and taxes["edu"] == "0.00"
    assert any("留抵" in warning for warning in result["warnings"])
    assert any("库存沉淀" in warning for warning in result["warnings"])


def test_cost_qty缺省等于qty():
    lines = normalize_lines([{"qty": "306", "sale_price": "233", "cost_price": "156.23"}])
    assert lines[0]["cost_qty"] == lines[0]["qty"]


# ---------------------------------------------------------------------------
# 5. 只读红线（用户的硬要求：绝不因为测算污染业务库）
# ---------------------------------------------------------------------------
def test_算核源码里没有任何写库能力():
    """结构上就写不了库：不 import 数据库模块，也没有 commit/add/delete/execute。

    用 AST 而不是字符串匹配：模块文档里解释"连 `Session` 都不 import"这句话本身
    就带着 `Session`，按文本查会误报。
    """
    import ast

    tree = ast.parse(pathlib.Path(inspect.getfile(compute)).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("sqlalchemy", "app.db")), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("sqlalchemy", "app.db")), node.module
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {"commit", "add", "delete", "flush", "execute", "execute_text"}


def test_接口跑完四张表条数不变():
    """接口级实测：compute + sources + prefill 前后，业务单据条数必须一模一样。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.main import app

    tables = ("sales_orders", "purchase_orders", "contracts", "financial_transactions")
    try:
        db = SessionLocal()
        try:
            before = {table: db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables}
            sale_id = db.execute(text("SELECT id FROM sales_orders ORDER BY id DESC LIMIT 1")).scalar()
        finally:
            db.close()
    except Exception as exc:  # 测试库没起：跳过，而不是假通过
        pytest.skip(f"测试库不可用：{exc}")

    client = TestClient(app)
    response = client.post(
        "/api/v1/project-calc/compute",
        json={
            "label": "只读红线",
            "lines": [{"qty": "1", "sale_price": TOTAL["sale_incl"], "cost_price": TOTAL["cost_incl"]}],
        },
    )
    assert response.status_code == 200
    assert response.json()["totals"]["net_profit"] == "716815.41"

    assert client.get("/api/v1/project-calc/defaults").status_code == 200
    assert client.get("/api/v1/project-calc/sources?source=sale").status_code == 200
    if sale_id:
        assert client.get(f"/api/v1/project-calc/prefill/sale/{sale_id}").status_code == 200

    db = SessionLocal()
    try:
        after = {table: db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables}
    finally:
        db.close()
    assert after == before
