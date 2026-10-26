# -*- coding: utf-8 -*-
"""给 erp_common.py 打 Decimal 补丁（CRLF 文件：先 LF 化，改完还原）。"""
import io, sys

P = r"E:/AI/ERP软件/app/api/v1/routes/erp_common.py"
raw = open(P, "rb").read()
crlf = raw.count(b"\r\n")
s = raw.replace(b"\r\n", b"\n").decode("utf-8")

def rep(old, new, tag):
    global s
    assert s.count(old) == 1, f"{tag}: 命中 {s.count(old)} 次\n---\n{old[:200]}"
    s = s.replace(old, new)
    print("OK", tag)

# 1) import
rep(
    "from urllib import request\n",
    "from urllib import request\n\nfrom decimal import Decimal\n\nfrom app.core.money import ZERO, dec, money, money_rate\n",
    "import",
)

# 2) _prev_debt_total 返回 Decimal
rep(
    '''def _prev_debt_total(db: Session, model, fk_field, fk_value: int) -> float:
    """取同一往来对象上一张单据的"累欠货款"，作为本单的"前次欠款"。"""
    last = db.query(model).filter(fk_field == fk_value).order_by(model.id.desc()).first()
    return float(last.total_debt or 0.0) if last is not None else 0.0''',
    '''def _prev_debt_total(db: Session, model, fk_field, fk_value: int) -> Decimal:
    """取同一往来对象上一张单据的"累欠货款"，作为本单的"前次欠款"。

    ⚠️ 返回 **Decimal**（不再 float）：`total_debt` 已是 `numeric(14,2)`，
    psycopg 读出来就是 Decimal；在这里 float 一下，调用方 `Decimal + float`
    立刻 TypeError。要保持"钱"的类型一路到底，交接点也是钱。
    """
    last = db.query(model).filter(fk_field == fk_value).order_by(model.id.desc()).first()
    return dec(last.total_debt) if last is not None else ZERO''',
    "_prev_debt_total",
)

# 3) _write_finance 入参收口
rep(
    "    transaction_type: str,\n    amount: float,\n",
    "    transaction_type: str,\n    amount: Decimal | float | None,\n",
    "_write_finance 签名",
)
rep(
    "        amount=float(amount or 0.0),\n",
    "        # 收口：金额列是 numeric(14,2)，无论调用方给 float 还是 Decimal 都量化到分\n"
    "        amount=money(amount),\n",
    "_write_finance 赋值",
)

# 4) _apply_stock 入参收口 + 单价按 4 位费率落库
rep(
    "    unit_price: float = 0.0,\n    unit_factor: int = 1,\n",
    "    unit_price: Decimal | float | None = 0,\n    unit_factor: int = 1,\n",
    "_apply_stock 签名",
)
rep(
    "        unit_price=float(unit_price or 0.0) / factor,\n",
    "        # 成本单价是 numeric(14,4) 的\"费率\"：先除 factor 再量化到 4 位，\n"
    "        # 不能先 float 除法（那会把 41.6667 存成 41.666666666664 这种尾巴）\n"
    "        unit_price=money_rate(dec(unit_price) / dec(factor)),\n",
    "_apply_stock 单价",
)

# 5) 文档里那段"IEEE754 精确恒等"的说明已不成立
rep(
    """    `unit_factor=1`（默认）与改动前**逐字节等价** —— IEEE754 下 `x*1` 与 `x/1.0`
    都是精确恒等（含 `inf`/`nan` 的传播规则也一致），所以全库既有调用点
    一行都不用改、也不需要传这个参数。""",
    """    `unit_factor=1`（默认）时单价不做任何比例换算（`x / 1` 恒等），只是
    按列精度量化到 4 位小数 —— 历史调用点一行都不用改、也不需要传这个参数。

    ⚠️ 单价列自 2026-10-19 起是 `numeric(14,4)`（见
    `docs/sql/2026-10-19_四流合一_金额精度升级.sql`）：传入的 float 在这里
    统一转成 Decimal 再落库，别指望数据库帮你收尾。""",
    "_apply_stock docstring",
)

# 6) amount_to_chinese 放宽注解（内部本来就 float() 化了）
rep(
    "def amount_to_chinese(amount: float) -> str:",
    "def amount_to_chinese(amount: Decimal | float | None) -> str:",
    "amount_to_chinese 签名",
)

out = s.replace("\n", "\r\n").encode("utf-8")
open(P, "wb").write(out)
chk = open(P, "rb").read()
print("CRLF", chk.count(b"\r\n"), "LF", chk.count(b"\n"), "原CRLF", crlf)
