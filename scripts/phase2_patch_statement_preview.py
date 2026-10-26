# -*- coding: utf-8 -*-
"""第二阶段 P2-2：对账单「三步走」后端支撑。

用户要的三步是：选客户/日期 → 点「搜索预览」看到明细 → 勾选 → 「生成对账单」→ 下载/打印。
现状只有一步「生成草稿」= 直接落库，用户没法在落库前挑行。

做法：把 generate 里**取数**那段抽成 `_collect_lines()`，
   · generate 继续用它（行为不变）
   · 新增 `POST /statements/preview`：同样取数，但**不落库**，只回明细
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "routes" / "erp_statement.py"
raw = TARGET.read_bytes().decode("utf-8")
text = raw.replace("\r\n", "\n")

START = "    lines: list[dict[str, object]] = []\n\n    # —— ① 合同 ——"
END = "    if not lines:\n        raise HTTPException("
assert text.count(START) == 1, text.count(START)
assert text.count(END) == 1, text.count(END)

i_start = text.index(START)
i_end = text.index(END)
body = text[i_start:i_end]

# 把取数块从 generate 里摘掉，换成调用
text = text[:i_start] + "    lines = _collect_lines(\n" \
    "        db,\n" \
    "        direction=direction,\n" \
    "        party_type=party_type,\n" \
    "        party_id=party_id,\n" \
    "        party_name=party_name,\n" \
    "        period_start=period_start,\n" \
    "        period_end=period_end,\n" \
    "        include_contracts=bool(payload.get(\"include_contracts\", True)),\n" \
    "        include_invoices=bool(payload.get(\"include_invoices\", True)),\n" \
    "        include_payments=bool(payload.get(\"include_payments\", True)),\n" \
    "    )\n\n" + text[i_end:]

# 去掉 body 里已经搬到函数签名上的三处开关判断，改成直接看参数
body = body.replace("    lines: list[dict[str, object]] = []\n\n", "")
body = body.replace('    if payload.get("include_contracts", True):', "    if include_contracts:")
body = body.replace('    if payload.get("include_invoices", True):', "    if include_invoices:")
body = body.replace('    if payload.get("include_payments", True):', "    if include_payments:")

HELPER = '''def _collect_lines(
    db: Session,
    *,
    direction: str,
    party_type: str,
    party_id: int,
    party_name: str,
    period_start: str,
    period_end: str,
    include_contracts: bool = True,
    include_invoices: bool = True,
    include_payments: bool = True,
) -> list[dict[str, object]]:
    """把「合同 + 发票 + 收付款」汇总成对账单明细行（**纯取数，不落库**）。

    抽出来是为了两处复用：
      · `POST /statements/generate` —— 取完数直接建草稿（老行为）
      · `POST /statements/preview`  —— 取完数只回给前端看，用户勾完再建单
    两边口径必须一模一样，否则"预览 10 行、生成 8 行"，用户会以为系统吃了他两行。
    """
''' + body.rstrip("\n") + "\n\n\n"

# 插到 generate 的路由装饰器之前
ANCHOR = '@router.post("/statements/generate", summary="按往来单位 + 期间自动生成对账单草稿")'
assert text.count(ANCHOR) == 1
text = text.replace(ANCHOR, HELPER + ANCHOR)

PREVIEW = '''@router.post("/statements/preview", summary="生成前先看一眼：只取数不落库")
def preview_statement(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    """对账单「三步走」的第二步（第一步是选单位与账期）。

    和 `/generate` 的唯一区别：**不建单、不写库**。
    返回的 `items` 结构与单据明细完全一致，前端勾完直接喂给 `POST /statements`，
    不用再取一次数 —— 否则用户在预览里改过的数字会被第二次取数覆盖掉。
    """
    direction = normalize_direction(direction=payload.get("direction") or "out")
    party_type = str(payload.get("party_type") or ("customer" if direction == "out" else "supplier"))
    if direction == "out" and party_type != "customer":
        raise HTTPException(status_code=400, detail="应收（out）对账单的往来单位必须是客户")
    if direction == "in" and party_type != "supplier":
        raise HTTPException(status_code=400, detail="应付（in）对账单的往来单位必须是供应商")

    party_id = payload.get("party_id")
    if party_id in (None, ""):
        raise HTTPException(status_code=400, detail="缺少 party_id（要对哪个客户/供应商）")
    try:
        party_id = int(party_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="party_id 必须是整数") from exc

    period_start = str(payload.get("period_start") or "").strip()
    period_end = str(payload.get("period_end") or "").strip()
    if not period_start or not period_end:
        raise HTTPException(status_code=400, detail="缺少对账区间（period_start / period_end）")
    if period_start > period_end:
        raise HTTPException(status_code=400, detail="对账区间的开始日期不能晚于结束日期")

    model = Customer if party_type == "customer" else Supplier
    party = db.get(model, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="对方单位档案不存在")

    party_name = getattr(party, "name", None) or ""
    opening = payload.get("opening_balance")
    if opening in (None, ""):
        opening = getattr(party, "init_receivable" if party_type == "customer" else "init_payable", 0) or 0

    lines = _collect_lines(
        db,
        direction=direction,
        party_type=party_type,
        party_id=party_id,
        party_name=party_name,
        period_start=period_start,
        period_end=period_end,
        include_contracts=bool(payload.get("include_contracts", True)),
        include_invoices=bool(payload.get("include_invoices", True)),
        include_payments=bool(payload.get("include_payments", True)),
    )

    items: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        line["line_no"] = index
        items.append(StatementItemCreate(**line).model_dump())

    return {
        "direction": direction,
        "party_type": party_type,
        "party_id": party_id,
        "party_name": party_name,
        "party_tax_no": getattr(party, "tax_no", None),
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": float(opening or 0),
        "items": items,
        "line_count": len(items),
    }


'''

ANCHOR2 = '@router.post("/statements", response_model=StatementRead, status_code=status.HTTP_201_CREATED)'
assert text.count(ANCHOR2) == 1
text = text.replace(ANCHOR2, PREVIEW + ANCHOR2)

TARGET.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK erp_statement.py：_collect_lines + /statements/preview")
