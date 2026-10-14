"""把 D 盘开发版同步到 E 盘运行版，让两盘代码保持一致。

## 为什么需要这个脚本

项目强约束是「D 盘开发、E 盘运行，两盘必须完全一致」。此前靠手工 `cp`，
结果两盘逐渐漂移：E 盘缺多账套的 `tenant.py`/`company.py`、缺总账四个新文件、
`company.json`（公司抬头）还是空的 —— 而发票进销项判定正好依赖它。

## 三类目录，三种处理方式（这是本脚本的核心）

| 类别 | 目录 | 处理 | 理由 |
|---|---|---|---|
| **覆盖同步** | `app/` `scripts/` `tests/` `migration/` `frontend/src/` `frontend/dist/` | 逐文件覆盖 | 代码与构建产物，D 盘是唯一事实来源 |
| **增量合并** | `data/` `backup/` | 只补 D 有 E 无的，**绝不删 E 的东西** | E 盘是运行版：`backup/` 里有每日 21:37 的整库 pg_dump，`data/invoices/` 是用户上传的发票原件 |
| **不同步** | `.venv` `node_modules` `__pycache__` `.pytest_cache` `.workbuddy` `.git` `build/` `dist_new/` `dist_v2/` `_excel_templates/` `_print_check/` | 跳过 | 依赖、缓存、工作区数据、PyInstaller 中间产物 |

`company.json` 走覆盖同步：D 盘那份是用户填好的真实抬头，E 盘是空模板，
同步过去正好把公司信息补到运行版（发票进销项判定依赖它）。

## 用法

    python scripts/sync_to_e.py              # 同步并校验
    python scripts/sync_to_e.py --dry-run    # 只看会做什么
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

SRC = Path(r"D:\ERP软件")
DST = Path(r"E:\AI\ERP软件")

# 覆盖同步的目录（相对 SRC）
OVERWRITE_TREES = ["app", "scripts", "tests", "migration", "frontend/src", "frontend/dist"]
# 覆盖同步的单文件（相对 SRC）
OVERWRITE_FILES = [
    "README.md",
    "融合改造记录.md",
    "company.json",
    "desktop_app.py",
    "启动ERP.bat",
    "启动网页版.bat",
    "配置局域网访问.bat",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/vite.config.js",
    "erp.spec",
]
# 增量合并的目录（只补不删）
MERGE_TREES = ["data", "backup"]
# 同步根目录的 dist/（PyInstaller 打包产物）—— 单独一项，因为要先打包
DIST_DIR = "dist"

EXCLUDE_DIRS = {
    ".venv", "node_modules", "__pycache__", ".pytest_cache", ".workbuddy",
    ".git", "build", "dist_new", "dist_v2", "_excel_templates", "_print_check",
}
EXCLUDE_FILE_SUFFIXES = (".pyc",)


def _skip(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    return path.suffix in EXCLUDE_FILE_SUFFIXES


def copy_tree_overwrite(src_root: Path, dst_root: Path, label: str, dry: bool) -> tuple[int, int]:
    """逐文件覆盖同步一个目录树；返回 (复制数, 已一致数)。"""
    copied = same = 0
    if not src_root.exists():
        print(f"  ⚠️ 源不存在，跳过：{label}")
        return 0, 0
    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        if _skip(src):
            continue
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            same += 1
            continue
        copied += 1
        if dry:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return copied, same


def merge_tree(src_root: Path, dst_root: Path, label: str, dry: bool) -> tuple[int, int]:
    """增量合并：只补目标端缺失的文件，绝不覆盖、绝不删除。"""
    added = same = 0
    if not src_root.exists():
        return 0, 0
    for src in sorted(src_root.rglob("*")):
        if src.is_dir() or _skip(src):
            continue
        dst = dst_root / src.relative_to(src_root)
        if dst.exists():
            same += 1
            continue
        added += 1
        if dry:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return added, same


def verify() -> list[str]:
    """同步后校验：覆盖同步范围内的文件必须两边一致。"""
    mismatches: list[str] = []

    def check(src_root: Path, dst_root: Path, merge: bool = False) -> None:
        if not src_root.exists():
            return
        for src in sorted(src_root.rglob("*")):
            if src.is_dir() or _skip(src):
                continue
            dst = dst_root / src.relative_to(src_root)
            if not dst.exists():
                if merge:
                    continue
                mismatches.append(f"缺失 {dst}")
            elif not filecmp.cmp(src, dst, shallow=False):
                mismatches.append(f"不一致 {src.relative_to(SRC)}")

    for rel in OVERWRITE_TREES:
        check(SRC / rel, DST / rel)
    for rel in OVERWRITE_FILES:
        src, dst = SRC / rel, DST / rel
        if not src.exists():
            continue
        if not dst.exists() or not filecmp.cmp(src, dst, shallow=False):
            mismatches.append(f"不一致 {rel}")
    return mismatches


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DST.exists():
        print(f"❌ 目标盘不存在：{DST}")
        sys.exit(1)

    print(f"同步 {SRC} → {DST}\n")
    total_copied = total_same = 0

    print("── 覆盖同步（代码与构建产物）──")
    for rel in OVERWRITE_TREES:
        c, s = copy_tree_overwrite(SRC / rel, DST / rel, rel, args.dry_run)
        total_copied += c
        total_same += s
        print(f"  {rel:<16} 复制 {c:>4} 个 / 已一致 {s:>4} 个")
    for rel in OVERWRITE_FILES:
        src = SRC / rel
        if not src.exists():
            continue
        dst = DST / rel
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            total_same += 1
            continue
        total_copied += 1
        print(f"  {rel:<16} 复制")
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    print("\n── 增量合并（只补不删，保护运行版数据）──")
    for rel in MERGE_TREES:
        a, s = merge_tree(SRC / rel, DST / rel, rel, args.dry_run)
        total_copied += a
        total_same += s
        print(f"  {rel:<16} 新增 {a:>4} 个 / 已存在 {s:>4} 个")

    if (SRC / DIST_DIR).exists():
        c, s = copy_tree_overwrite(SRC / DIST_DIR, DST / DIST_DIR, DIST_DIR, args.dry_run)
        total_copied += c
        total_same += s
        print(f"\n── dist/（桌面 exe）── 复制 {c} 个 / 已一致 {s} 个")

    if args.dry_run:
        print(f"\n（dry-run）将复制 {total_copied} 个文件")
        return

    print(f"\n完成：复制 {total_copied} 个，已一致 {total_same} 个")
    bad = verify()
    if bad:
        print(f"\n❌ 校验发现 {len(bad)} 处不一致：")
        for b in bad[:20]:
            print("   ", b)
        sys.exit(1)
    print("✓ 校验通过：覆盖同步范围内两盘完全一致")


if __name__ == "__main__":
    main()
