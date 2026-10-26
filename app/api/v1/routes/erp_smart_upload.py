"""多文件智能识别上传（2026-10-23）。

## 一句话

「新增客户 / 供应商 / 商品」弹窗顶部的那个虚线框：把营业执照、名片、报价单丢进来，
后端读出文字 → 认出字段 → 前端弹核对框 → 用户点一下填进表单。

## 这个接口只做"读 + 认"，不写库

刻意的边界：
* **不写库**：识别只是"帮着填表"，档案还是用户点「保存」才落库。
  这样认错了最坏情况是"表单里有个值要改"，而不是"库里多了一条脏档案"。
* **不落盘**：识别用的字节只在内存里走一遍（OCR 需要临时 PNG 的，由
  `erp_invoice._ocr_image_bytes` 写到系统临时目录并复用同一套逻辑）。
  「仅上传作为附件」那条路的文件由**前端**在档案保存成功后再上传到附件库 ——
  那时候才有 `customer_id` 可以挂。
* **不猜**：认不出来的键不出现在 `fields` 里，靠 `warnings` 告诉用户"请手动补"。

## 为什么单独一个路由文件

`erp_invoice.py` 已经 2000 多行，而且那边是"发票"领域（三关解析、二维码、明细行）。
这里只复用它的 OCR 原语，业务语义完全不同，混在一起会让两边都不敢改。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.smart_upload import (
    ACCEPT_SUFFIXES,
    FIELD_LABELS,
    MAX_FILES,
    MAX_FILE_BYTES,
    PROFILE_FIELDS,
    analyze_files,
)

router = APIRouter(tags=["smart-upload"])

KINDS = ("customer", "supplier", "product")
MODES = ("parse", "attach")


@router.get("/smart-upload/meta", summary="智能识别支持的格式与字段")
def smart_upload_meta() -> dict[str, object]:
    """前端用它渲染"支持哪些格式/哪些字段"，避免两边各写一份清单。"""
    return {
        "kinds": list(KINDS),
        "modes": list(MODES),
        "accept": sorted(ACCEPT_SUFFIXES),
        "max_files": MAX_FILES,
        "max_file_mb": MAX_FILE_BYTES // (1024 * 1024),
        "fields": PROFILE_FIELDS,
        "field_labels": FIELD_LABELS,
    }


@router.post("/smart-upload/parse", summary="上传并识别档案信息（不写库）")
async def smart_upload_parse(
    files: list[UploadFile] = File(...),
    kind: str = Form("customer"),
    mode: str = Form("parse"),
) -> dict[str, object]:
    """`files` 可以一次多个；`kind` 决定回填哪些字段；`mode=attach` 只校验不识别。"""
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind 只能是 {' / '.join(KINDS)}")
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode 只能是 {' / '.join(MODES)}")
    if not files:
        raise HTTPException(status_code=400, detail="没有收到文件")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多 {MAX_FILES} 个文件")

    payloads: list[tuple[str, bytes]] = []
    for item in files:
        name = (item.filename or "").strip() or "未命名文件"
        payload = await item.read()
        if payload and len(payload) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"「{name}」超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 上限",
            )
        payloads.append((name, payload))

    result = analyze_files(payloads, kind=kind, mode=mode)
    # 一个文件都没读成功 → 让前端能一眼看出"全军覆没"，而不是拿到一堆空字段
    if not any(row["ok"] for row in result["files"]) and mode == "parse":
        result["message"] = "所有文件都没读出内容，请检查文件是否清晰"
    elif mode == "attach":
        result["message"] = f"已选中 {len(payloads)} 个文件，保存档案后自动归档"
    else:
        result["message"] = f"识别完成：认出 {len(result['fields'])} 个字段"
    return result
