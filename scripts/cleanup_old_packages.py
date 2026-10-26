"""封版清理：删掉 dist 下的旧包与旧的临时压缩包，顺带清理可再生的构建中间产物。

## 为什么是脚本而不是一串 rm

封版当天手抖删错一个文件夹，代价是"整个包没了、人已经关机"。
所以这里把**判据、白名单、保护名单**都写死在代码里，跑之前先预演一遍，
每一条被删的路径都能在日志里查到。

## 判据（只有三条）

1. `dist/` 下一级子目录，名字包含 `_旧_` 或 `_待删` → 删；
2. `dist/` 下一级压缩包（`.rar/.zip/.7z`）**且修改时间早于 `--keep-recent-hours`** → 删；
3. 根目录下**明确列在 DEBRIS_DIRS 里**的可再生产物 → 删。

## 保护名单（永不触碰）

- `dist/ERP管理系统`（正在使用的那一版，名字精确匹配，不做包含匹配）；
- `app/ frontend/ tests/ scripts/ docs/ backup/ data/ migration/ _contract_module/ certs/`；
- 任何 `.py`/`.jsx`/`.cjs` 源码（脚本只删目录，不删散落文件）。

## 跑法

    python scripts/cleanup_old_packages.py            # 预演，只打印
    python scripts/cleanup_old_packages.py --apply    # 真删
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# 正在使用的那一版：**精确**匹配名字（绝不用"包含 ERP"这种判据）
KEEP_PACKAGE = "ERP管理系统"

# 根目录下可再生的产物（删了下次构建/运行会自动重建）
DEBRIS_DIRS = [
    "build",            # PyInstaller 中间目录（下次打包自动重建）
    "__pycache__",      # 字节码缓存
    "_probe_boards",    # 早期探针脚本
    "_probe_tree",      # 早期探针脚本
    "artifacts",        # 探针截图
]

# 白名单：即使名字命中判据也绝不删
PROTECTED = {
    "app", "frontend", "tests", "scripts", "docs", "backup",
    "data", "migration", "_contract_module", "certs", "harmonyos",
    "test_invoices", "dist", "node_modules", ".git", ".venv",
}

ARCHIVE_SUFFIXES = {".rar", ".zip", ".7z"}


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def collect(keep_recent_hours: float) -> tuple[list[tuple[str, Path, int]], list[str]]:
    """返回 (待删清单, 被跳过的说明)。待删元素：(原因, 路径, 字节数)"""
    plan: list[tuple[str, Path, int]] = []
    notes: list[str] = []
    cutoff = time.time() - keep_recent_hours * 3600

    if not DIST.exists():
        return plan, [f"dist 目录不存在：{DIST}"]

    for entry in sorted(DIST.iterdir()):
        if entry.name in PROTECTED:
            continue
        if entry.is_dir():
            if entry.name == KEEP_PACKAGE:
                notes.append(f"保留最新包：{entry.name}（{human(dir_size(entry))}）")
                continue
            if "_旧_" in entry.name or "_待删" in entry.name:
                plan.append(("旧版本包", entry, dir_size(entry)))
            continue
        if entry.suffix.lower() in ARCHIVE_SUFFIXES:
            mtime = entry.stat().st_mtime
            if mtime >= cutoff:
                hours = (time.time() - mtime) / 3600
                notes.append(
                    f"跳过压缩包 {entry.name}：{hours * 60:.0f} 分钟前刚生成"
                    f"（可能在用它做移动硬盘备份，确认后再手动删）"
                )
                continue
            plan.append(("旧压缩包", entry, entry.stat().st_size))

    for name in DEBRIS_DIRS:
        path = ROOT / name
        if not path.exists() or name in PROTECTED:
            continue
        plan.append(("可再生构建产物", path, dir_size(path)))

    return plan, notes


def main() -> int:
    ap = argparse.ArgumentParser(description="清理旧打包与构建中间产物")
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只预演）")
    ap.add_argument(
        "--keep-recent-hours",
        type=float,
        default=3.0,
        help="压缩包在这个小时数内生成的一律跳过（防误删刚做的备份），默认 3",
    )
    args = ap.parse_args()

    plan, notes = collect(args.keep_recent_hours)
    for note in notes:
        print(f"  · {note}")

    if not plan:
        print("\n没有需要清理的内容。")
        return 0

    total = sum(size for _, _, size in plan)
    print(f"\n待清理 {len(plan)} 项，合计 {human(total)}：")
    for reason, path, size in plan:
        print(f"  [{reason}] {path}  ({human(size)})")

    if not args.apply:
        print("\n（预演模式：没有删除任何东西。确认无误后加 --apply）")
        return 0

    failed: list[tuple[Path, str]] = []
    for _, path, _ in plan:
        # 最后一道闸：绝不动正在使用的包与白名单目录
        if path.name == KEEP_PACKAGE or path.name.lstrip("./") in PROTECTED:
            failed.append((path, "命中保护名单，已跳过"))
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except Exception as exc:  # noqa: BLE001 —— 删不掉要如实说，不能假装成功
            failed.append((path, f"{type(exc).__name__}: {exc}"))

    print(f"\n✅ 已删除 {len(plan) - len(failed)} 项，释放约 {human(total)}")
    for path, why in failed:
        print(f"  ⚠️ 失败：{path} —— {why}")

    remaining = [entry.name for entry in DIST.iterdir() if entry.is_dir()]
    print(f"\ndist 下现在有 {len(remaining)} 个文件夹：{', '.join(sorted(remaining))}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
