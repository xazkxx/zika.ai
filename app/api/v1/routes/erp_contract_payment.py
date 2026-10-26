"""合同付款计划接口（2026-10-23）。

一组四个动作，全部围绕"这一期"：
    列计划  GET    /contracts/{id}/payment-plans
    加一期  POST   /contracts/{id}/payment-plans
    改一期  PATCH  /payment-plans/{plan_id}
    删一期  DELETE /payment-plans/{plan_id}
    传回单  POST   /payment-plans/{plan_id}/receipt
    看回单  GET    /payment-plans/{plan_id}/receipt
    一键三期 POST  /contracts/{id}/payment-plans/template   （30/40/30，最常用）

## 金额口径（和「三单匹配」保持同一套）

- `plan_amount` 由后端按 `plan_ratio × 合同总额` 算，前端只传比例或金额其中一种；
- `paid_amount` 是财务登记的实际付款，允许超过计划额（超付是真实存在的情况，
  不要在接口层拦掉，否则财务只能去改计划金额，历史就失真了）；
- 汇总的 `progress` = 已付合计 / 合同总额，**夹在 0~100**，
  但 `shortfall`（未付缺口）用真实差值，可以是负数（超付）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import file_storage
from app.db.session import get_db
from app.models.contract import Contract
from app.models.contract_payment import ContractPaymentPlan

router = APIRouter(tags=["contract-payments"])

RECEIPT_SUBDIR = "contract_receipts"
RECEIPT_MAX_BYTES = 20 * 1024 * 1024
RECEIPT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 最常用的付款节奏：预付 30% / 发货 40% / 尾款 30%
DEFAULT_SPLIT = [
    (1, "预付款", 30),
    (2, "发货款", 40),
    (3, "尾款", 30),
]


def _money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _serialize(plan: ContractPaymentPlan) -> dict[str, object]:
    plan_amount = _money(plan.plan_amount)
    paid = _money(plan.paid_amount)
    return {
        "id": plan.id,
        "contract_id": plan.contract_id,
        "period_no": plan.period_no,
        "name": plan.name,
        "plan_date": plan.plan_date,
        "plan_ratio": None if plan.plan_ratio is None else float(plan.plan_ratio),
        "plan_amount": plan_amount,
        "paid_amount": paid,
        # 单期差额：正数=还差这么多，负数=超付
        "shortfall": round(plan_amount - paid, 2),
        "paid_date": plan.paid_date,
        "has_receipt": bool(plan.receipt_path),
        "receipt_name": plan.receipt_name,
        "receipt_size": plan.receipt_size,
        "note": plan.note,
        "settled": paid >= plan_amount - 0.005,
    }


def _summary(contract: Contract, plans: list[ContractPaymentPlan]) -> dict[str, object]:
    total = _money(contract.total_amount)
    planned = round(sum(_money(p.plan_amount) for p in plans), 2)
    paid = round(sum(_money(p.paid_amount) for p in plans), 2)
    progress = round(paid / total * 100, 2) if total > 0 else None
    return {
        "contract_amount": total,
        "planned_amount": planned,
        "paid_amount": paid,
        # 进度条用（0~100，夹住；超付不显示成 120%）
        "progress": None if progress is None else max(0.0, min(100.0, progress)),
        "progress_raw": progress,
        # 缺口：与「三单匹配」同口径，允许负数表示超付
        "shortfall": round(total - paid, 2),
        "plan_count": len(plans),
        "settled_count": sum(1 for p in plans if _money(p.paid_amount) >= _money(p.plan_amount) - 0.005),
        "unplanned": round(total - planned, 2),
    }


def _contract_or_404(db: Session, contract_id: int) -> Contract:
    row = db.get(Contract, contract_id)
    if row is None:
        raise HTTPException(status_code=404, detail="合同不存在")
    return row


def _plan_or_404(db: Session, plan_id: int) -> ContractPaymentPlan:
    row = db.get(ContractPaymentPlan, plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="付款计划不存在")
    return row


def _plans(db: Session, contract_id: int) -> list[ContractPaymentPlan]:
    return (
        db.query(ContractPaymentPlan)
        .filter(ContractPaymentPlan.contract_id == contract_id)
        .order_by(ContractPaymentPlan.period_no, ContractPaymentPlan.id)
        .all()
    )


@router.get("/contracts/{contract_id}/payment-plans", summary="合同付款计划列表 + 汇总")
def list_payment_plans(contract_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    contract = _contract_or_404(db, contract_id)
    plans = _plans(db, contract_id)
    return {
        "contract_id": contract_id,
        "contract_no": contract.contract_no,
        "plans": [_serialize(plan) for plan in plans],
        "summary": _summary(contract, plans),
    }


@router.post(
    "/contracts/{contract_id}/payment-plans",
    status_code=status.HTTP_201_CREATED,
    summary="新增一期付款计划",
)
def create_payment_plan(
    contract_id: int, payload: dict, db: Session = Depends(get_db)
) -> dict[str, object]:
    """新增一期。

    金额与比例二选一即可：
      · 只给 `plan_ratio` → 按合同总额算金额（合同金额为 0 时明确报错，别静默存 0）；
      · 只给 `plan_amount` → 反算比例（保留 2 位）；
      · 两个都给 → 以金额为准（用户手填的数最权威）。
    """
    contract = _contract_or_404(db, contract_id)
    total = _money(contract.total_amount)

    ratio = payload.get("plan_ratio")
    amount = payload.get("plan_amount")
    if amount in (None, ""):
        if ratio in (None, ""):
            raise HTTPException(status_code=400, detail="请填写计划金额或计划比例")
        if total <= 0:
            raise HTTPException(
                status_code=400,
                detail="这张合同的金额是 0（可能明细还没录），没法按比例算金额，请直接填计划金额",
            )
        amount = round(total * float(ratio) / 100, 2)
        amount_is_derived = True
    else:
        amount = _money(amount)
        amount_is_derived = False
        if ratio in (None, "") and total > 0:
            ratio = round(amount / total * 100, 2)

    plans = _plans(db, contract_id)
    period_no = payload.get("period_no")
    if period_no in (None, ""):
        period_no = (max((p.period_no or 0) for p in plans) + 1) if plans else 1
    period_no = int(period_no)
    if any(int(p.period_no) == period_no for p in plans):
        raise HTTPException(status_code=409, detail=f"第 {period_no} 期已存在，请换一个期次")

    row = ContractPaymentPlan(
        contract_id=contract_id,
        period_no=period_no,
        name=(str(payload.get("name") or "").strip() or f"第 {period_no} 期")[:80],
        plan_date=(str(payload.get("plan_date") or "").strip() or None),
        plan_ratio=None if ratio in (None, "") else float(ratio),
        plan_amount=amount,
        paid_amount=_money(payload.get("paid_amount")),
        paid_date=(str(payload.get("paid_date") or "").strip() or None),
        note=(str(payload.get("note") or "").strip() or None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    current = _plans(db, contract_id)
    return {
        "plan": _serialize(row),
        "plans": [_serialize(item) for item in current],
        "summary": _summary(contract, current),
        "amount_derived": amount_is_derived,
    }


@router.post(
    "/contracts/{contract_id}/payment-plans/template",
    status_code=status.HTTP_201_CREATED,
    summary="一键生成三期（30% / 40% / 30%）",
)
def create_default_plans(
    contract_id: int,
    payload: dict | None = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """按 30/40/30 生成三期。已存在期次的合同一律拒绝 —— 不能把财务已登记的计划覆盖掉。"""
    contract = _contract_or_404(db, contract_id)
    if _plans(db, contract_id):
        raise HTTPException(
            status_code=409,
            detail="这张合同已经有付款计划了。要改用模板请先删掉现有期次（或逐期编辑）",
        )
    total = _money(contract.total_amount)
    if total <= 0:
        raise HTTPException(status_code=400, detail="合同金额为 0，无法按比例生成付款计划")

    body = payload or {}
    base_date = (str(body.get("plan_date") or "").strip() or None)
    rows = []
    for period_no, label, ratio in DEFAULT_SPLIT:
        rows.append(
            ContractPaymentPlan(
                contract_id=contract_id,
                period_no=period_no,
                name=f"{label} {ratio}%",
                plan_date=base_date,
                plan_ratio=ratio,
                plan_amount=round(total * ratio / 100, 2),
                paid_amount=0,
            )
        )
    db.add_all(rows)
    db.commit()
    current = _plans(db, contract_id)
    return {
        "plans": [_serialize(item) for item in current],
        "summary": _summary(contract, current),
    }


@router.patch("/payment-plans/{plan_id}", summary="修改一期（含登记实际付款）")
def update_payment_plan(plan_id: int, payload: dict, db: Session = Depends(get_db)) -> dict[str, object]:
    row = _plan_or_404(db, plan_id)
    contract = _contract_or_404(db, row.contract_id)

    if "plan_date" in payload:
        row.plan_date = (str(payload.get("plan_date") or "").strip() or None)
    if "name" in payload:
        row.name = (str(payload.get("name") or "").strip() or None)
    if "note" in payload:
        row.note = (str(payload.get("note") or "").strip() or None)
    if "paid_date" in payload:
        row.paid_date = (str(payload.get("paid_date") or "").strip() or None)
    if "paid_amount" in payload:
        row.paid_amount = _money(payload.get("paid_amount"))

    # 金额/比例：改了金额要重算比例，改了比例要重算金额（以"用户最后动的那一个"为准）
    if "plan_amount" in payload and payload.get("plan_amount") not in (None, ""):
        row.plan_amount = _money(payload.get("plan_amount"))
        total = _money(contract.total_amount)
        if total > 0:
            row.plan_ratio = round(row.plan_amount / total * 100, 2)
    elif "plan_ratio" in payload and payload.get("plan_ratio") not in (None, ""):
        ratio = float(payload.get("plan_ratio"))
        total = _money(contract.total_amount)
        if total <= 0:
            raise HTTPException(status_code=400, detail="合同金额为 0，无法按比例算金额")
        row.plan_ratio = ratio
        row.plan_amount = round(total * ratio / 100, 2)

    db.commit()
    db.refresh(row)
    current = _plans(db, row.contract_id)
    return {
        "plan": _serialize(row),
        "plans": [_serialize(item) for item in current],
        "summary": _summary(contract, current),
    }


@router.delete("/payment-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除一期")
def delete_payment_plan(plan_id: int, db: Session = Depends(get_db)) -> Response:
    row = _plan_or_404(db, plan_id)
    file_storage.delete_file(row.receipt_path)
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/payment-plans/{plan_id}/receipt", summary="上传付款回单")
async def upload_receipt(
    plan_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    row = _plan_or_404(db, plan_id)
    filename = (file.filename or "").strip()
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in RECEIPT_SUFFIXES:
        raise HTTPException(status_code=400, detail="回单只支持 PDF 或图片（png/jpg/webp/bmp）")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的文件是空的")
    if len(payload) > RECEIPT_MAX_BYTES:
        raise HTTPException(
            status_code=400, detail=f"回单超过 {RECEIPT_MAX_BYTES // (1024 * 1024)}MB 上限"
        )

    try:
        rel_path = file_storage.save_bytes(payload, filename, subdir=RECEIPT_SUBDIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 换回单时把旧的删掉，不然 data/contract_receipts 里会越攒越多孤儿文件
    old_path = row.receipt_path
    row.receipt_path = rel_path
    row.receipt_name = filename
    row.receipt_size = len(payload)
    try:
        db.commit()
    except Exception:
        file_storage.delete_file(rel_path)
        raise
    if old_path and old_path != rel_path:
        file_storage.delete_file(old_path)

    db.refresh(row)
    contract = _contract_or_404(db, row.contract_id)
    current = _plans(db, row.contract_id)
    return {
        "plan": _serialize(row),
        "plans": [_serialize(item) for item in current],
        "summary": _summary(contract, current),
    }


@router.get("/payment-plans/{plan_id}/receipt", summary="查看/下载付款回单")
def get_receipt(plan_id: int, download: bool = Query(False), db: Session = Depends(get_db)) -> Response:
    from urllib.parse import quote

    row = _plan_or_404(db, plan_id)
    if not row.receipt_path:
        raise HTTPException(status_code=404, detail="这一期还没有上传回单")
    raw = file_storage.read_bytes(row.receipt_path)
    if raw is None:
        raise HTTPException(status_code=404, detail="回单文件已丢失（可能被手工删除）")
    name = row.receipt_name or "receipt"
    disposition = "attachment" if download else "inline"
    return Response(
        content=raw,
        media_type="application/pdf" if name.lower().endswith(".pdf") else "image/*",
        headers={
            # 响应头只能 latin-1，中文文件名必须百分号编码
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"
        },
    )
