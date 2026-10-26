"""只读探查：全电发票 PDF 的坐标版式规律（不写库、不改原文件）

结论（595×397 页面，三张样本版式完全一致）：
  发票号码标签 x≈438,y≈32  → 值 x≈482,y≈32
  开票日期标签 x≈438,y≈49  → 值 x≈482,y≈49
  购买方"名称："x≈33,y≈96   → 值 x≈57,y≈96（右侧，且 x<300）
  销售方"名称："x≈318,y≈96  → 值 x≈340,y≈96（右侧，且 x>300）
  价税合计（小写）值：y≈277 的 "¥xxxx.xx"，x≈441
  ★ 明细行：项目名称 x≈13 / 规格型号 x≈119 / 单位 x≈198 / 数量 x≈282-297 之间
    实测数量在 x≈282-287，单价在 x≈297，金额在 x≈397-410，税率 x≈465-467，税额 x≈549-560
"""
import sys
from pathlib import Path

import pymupdf

ROOT = Path(r"C:/Users/admi/Desktop/国网/陕送票")


def line_of(label, x_max):
    """取标签右侧、同一基线的值词。"""
    pass


def probe(path: Path, show_lines=False):
    doc = pymupdf.open(str(path))
    page = doc[0]
    words = page.get_text("words")
    doc.close()
    return words


if __name__ == "__main__":
    for p in sorted(ROOT.rglob("*.pdf")):
        if p.name.startswith("~$"):
            continue
        try:
            words = probe(p)
        except Exception as exc:
            print("ERR", p, exc)
            continue
        texts = [w[4] for w in words]
        kinds = []
        if any("发票号码" in t for t in texts):
            kinds.append("发票")
        if any("凭证号" in t for t in texts):
            kinds.append("回单")
        if not words:
            kinds.append("扫描件")
        print(f"{len(words):5d} 词  {'/'.join(kinds) or '未知':6s}  {p.relative_to(ROOT)}")
