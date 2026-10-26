# -*- coding: utf-8 -*-
"""幽灵模板记录清扫（2026-10-24）。

背景：合同模板库出现过"数据库里有记录、磁盘文件却没了"的幽灵记录
（用户反馈 4 条 word 模板文件全部丢失）。这种记录在下拉里能选中，
但预览/下载/生成完整合同全都会失败。

用法：
    python scripts/cleanup_ghost_templates.py           # 仅报告
    python scripts/cleanup_ghost_templates.py --delete  # 报告并删除幽灵记录

注意：列表接口 GET /api/v1/contract-templates 现在也会自动清扫
（与这里同口径），本脚本主要用于离线核对与手工兜底。
"""
from __future__ import annotations

import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.core import file_storage  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.contract_template import ContractTemplate  # noqa: E402


def main() -> None:
    do_delete = "--delete" in sys.argv
    db = SessionLocal()
    try:
        rows = db.query(ContractTemplate).order_by(ContractTemplate.id).all()
        ghosts = [r for r in rows if not file_storage.exists(r.file_path)]
        print(f"模板记录共 {len(rows)} 条，幽灵记录 {len(ghosts)} 条：")
        for row in ghosts:
            print(
                f"  [ghost] id={row.id} name={row.name!r} "
                f"file_name={row.file_name!r} file_path={row.file_path!r}"
            )
        if ghosts and do_delete:
            db.query(ContractTemplate).filter(
                ContractTemplate.id.in_([r.id for r in ghosts])
            ).delete(synchronize_session=False)
            db.commit()
            print(f"已删除 {len(ghosts)} 条幽灵记录。")
        elif ghosts:
            print("（未删除。确认无误后加 --delete 再执行）")
        else:
            print("没有幽灵记录，库是干净的。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
