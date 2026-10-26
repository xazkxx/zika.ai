"""封版 v51 源码全量备份（排除依赖/构建产物/备份目录）。"""
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {"node_modules", ".venv", "venv", "dist", "build", "backup", "data",
                "__pycache__", ".git", ".pytest_cache", "out", ".workbuddy", "certs"}
EXCLUDE_EXT = {".pyc", ".pyo", ".log", ".db", ".dump", ".zip", ".png", ".jpg", ".jpeg"}
OUT = ROOT / "backup" / "源码全量_20261019_封版v51.zip"

files = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
    for fn in filenames:
        f = Path(dirpath) / fn
        if f.suffix.lower() in EXCLUDE_EXT:
            continue
        files.append(f)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(files):
        z.write(f, f.relative_to(ROOT).as_posix())

# 回读校验：条目数 + 关键文件必须都在
with zipfile.ZipFile(OUT) as z:
    names = z.namelist()
    must = [
        "app/api/v1/routes/erp_word.py",
        "app/services/word_export.py",
        "frontend/src/components/contracts/ContractsLedger.jsx",
        "frontend/src/lib/wordExport.js",
        "frontend/src/styles.css",
        "frontend/public/sw.js",
        "erp.spec",
        "desktop_app.py",
        "ERP终极封版说明.md",
        "docs/使用说明_合同OCR识别.md",
    ]
    missing = [m for m in must if m not in names]
    print(f"{len(files)} files -> {OUT.name}  {OUT.stat().st_size/1024/1024:.2f} MB")
    print(f"zip 内条目 {len(names)}；关键文件缺失: {missing or '无'}")
    print("sw 版本:", "v51" if "erp-pwa-v51" in z.read("frontend/public/sw.js").decode("utf-8") else "??")
