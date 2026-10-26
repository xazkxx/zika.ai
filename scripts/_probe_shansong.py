"""反证：把关键逻辑改坏，确认报告/扫描结果真的会变（防止"不看内容也全绿"）

用法：
  .venv\\Scripts\\python.exe scripts/_probe_shansong.py apply    # 改坏
  .venv\\Scripts\\python.exe scripts/_probe_shansong.py restore  # 还原
"""
import sys
from pathlib import Path

SCAN = Path("scripts/scan_shansong_readonly.py")
REPORT = Path("scripts/shansong_health_report.py")

PATCHES = [
    (
        "PROBE-A: 把明细行聚类阈值改回 14（旧版票明细会粘连）",
        SCAN,
        "if rows and abs(w[1] - rows[-1][-1][1]) < 8:",
        "if rows and abs(w[1] - rows[-1][-1][1]) < 14:",
    ),
    (
        "PROBE-B: 去掉'物资清单'优先分类（会混进销售对账单）",
        SCAN,
        'if "物资清单" in flat or "采购明细" in flat:\n        return "material_list"',
        'if False:\n        return "material_list"',
    ),
    (
        "PROBE-C: 购买方/销售方不按 x 分左右（会取同一个名字）",
        SCAN,
        "if (w[0] < mid_x) != left:",
        "if False:",
    ),
    (
        "PROBE-D: 商品比对不拆前缀（缺失商品数会暴涨）",
        REPORT,
        '        if hit is None:\n            hit = db_main.get(name.lower())      # ② 去前缀比',
        '        if hit is None:\n            hit = None                            # ② 去前缀比',
    ),
]

mode = sys.argv[1] if len(sys.argv) > 1 else "apply"

for label, path, old, new in PATCHES:
    text = path.read_text(encoding="utf-8")
    if mode == "apply":
        if old not in text:
            print(f"  SKIP  {label}（锚点未找到）")
            continue
        text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        print(f"  OK    {label}")
    else:
        if new not in text:
            print(f"  SKIP  {label}（已还原或锚点未找到）")
            continue
        text = text.replace(new, old, 1)
        path.write_text(text, encoding="utf-8")
        print(f"  OK    {label}")

print(f"\n反证模式：{mode}")
