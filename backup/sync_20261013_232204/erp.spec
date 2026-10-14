# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：ERP 桌面版（后端 + 前端 + 桌面窗口壳）
from PyInstaller.utils.hooks import collect_all

datas = [('frontend/dist', 'frontend/dist'), ('.env', '.')]
binaries = []

# passlib 的哈希处理器是注册表动态加载，PyInstaller 静态分析会漏，
# 必须显式声明（本机实际安装：passlib 1.7.4 + bcrypt 5.0.0，密码用 pbkdf2-sha256）
hiddenimports = [
    'passlib.handlers.pbkdf2',
    'passlib.handlers.bcrypt',
]

# OCR 模型、.NET 运行时（pywebview 用）、onnxruntime DLL、PDF 解析原生库等非 Python 资源
for pkg in ('rapidocr_onnxruntime', 'clr_loader', 'pythonnet', 'pywebview', 'pymupdf'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ERP管理系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='ERP管理系统',
)
