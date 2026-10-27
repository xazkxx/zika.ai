"""把 `dist/ERP管理系统` 打成交付用 zip。

## 为什么不用 Compress-Archive / .NET CreateFromDirectory

PowerShell 5.1 的 `Compress-Archive` 与 .NET Framework 的
`ZipFile.CreateFromDirectory` 都拿 `Path.DirectorySeparatorChar` 当条目分隔符，
在 Windows 上写出来是 `ERP管理系统\\_internal\\xxx.dll`。**ZIP 规范要求 `/`** ——
Explorer / WinRAR 能容错，但 7-Zip 的"解压到指定目录"、跨平台工具、以及
`zipfile` 自行拼路径的脚本都会把这串当**一个文件名**，直接解出畸形结果
（v1.81.0 那版 zip 就是这个毛病：条目里全是反斜杠，还没顶层目录）。

Python 的 `zipfile` 写 `/`，且能保留顶层文件夹 —— 解压时不会和 `dist` 下别的
版本混在一起，也不会把 `data/` 铺到用户随手选的目录里。

## 跑法

    python scripts/make_release_zip.py                 # 版本取自 frontend/package.json
    python scripts/make_release_zip.py --version 1.81.1
    python scripts/make_release_zip.py --skip-checks   # 跳过"关键文件在不在"的体检

## 出包前会体检

`ERP管理系统.exe`、`_internal/frontend/dist/index.html`、
`_internal/frontend/dist/version.json`、`_internal/frontend/dist/logo.png`、
`data/brand/logo_print.png`。少一个就拒绝出包 —— 缺 Logo 的包发出去以后
用户只会看到"Word 页眉空白"，而不会有任何报错。
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
APP_DIR = DIST / 'ERP管理系统'
APP_NAME = 'ERP管理系统'

# 出包体检：这些文件缺了，包能跑但功能会静默残废
REQUIRED = [
    f'{APP_NAME}/{APP_NAME}.exe',
    f'{APP_NAME}/_internal/frontend/dist/index.html',
    f'{APP_NAME}/_internal/frontend/dist/version.json',
    f'{APP_NAME}/_internal/frontend/dist/logo.png',
    f'{APP_NAME}/data/brand/logo_print.png',
]


def app_version(explicit: str | None) -> str:
    """版本号只认 frontend/package.json（vite 打前端时就用的它），避免三处各写一个。"""
    if explicit:
        return explicit.strip()
    pkg = json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))
    return str(pkg['version'])


def build(version: str, skip_checks: bool) -> Path:
    if not APP_DIR.is_dir():
        raise SystemExit(f'找不到待打包目录：{APP_DIR}')

    missing = [name for name in REQUIRED if not (APP_DIR.parent / name).exists()]
    if missing and not skip_checks:
        raise SystemExit(
            '拒绝出包，以下文件缺失：\n'
            + '\n'.join(f'  · {name}' for name in missing)
            + '\n（确认无误可加 --skip-checks）'
        )

    stamp = _stamp(APP_DIR / '_internal' / 'frontend' / 'dist' / 'version.json')
    target = DIST / f'{APP_NAME}_v{version}_{stamp}.zip'
    if target.exists():
        target.unlink()

    files = 0
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(APP_DIR.rglob('*')):
            if not path.is_file():
                continue
            # posix 相对路径 → 条目里就是 `/`
            archive.write(path, path.relative_to(DIST).as_posix())
            files += 1

    size_mb = target.stat().st_size / 1024 / 1024
    print(f'✅ {target.name}  {size_mb:.1f} MB  {files} 个文件')
    return target


def _stamp(version_json: Path) -> str:
    """文件名里的日期取 build 里的 YYYYMMDD（和 version.json 的 build 同源）。"""
    try:
        payload = json.loads(version_json.read_text(encoding='utf-8'))
        return str(payload.get('build', ''))[:8] or 'unknown'
    except Exception:  # 读不到就用 unknown，不能因为个文件名把出包挡住
        return 'unknown'


def main() -> int:
    parser = argparse.ArgumentParser(description='打包 dist/ERP管理系统 为交付 zip')
    parser.add_argument('--version', help='不传则读 frontend/package.json')
    parser.add_argument('--skip-checks', action='store_true', help='跳过关键文件体检')
    args = parser.parse_args()
    build(app_version(args.version), args.skip_checks)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
