# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：ERP 纯 Web 后端（后端 + 前端，无桌面窗口，无 pywebview）
#
# 用法：
#   正式包： pyinstaller --noconfirm erp.spec
#   调试包： set ERP_CONSOLE=1 && pyinstaller --noconfirm erp.spec
#            （调试包带控制台窗口，双击后能看到 Python 的原始报错；
#              正式包 console=False，双击不弹黑框，靠 erp_error.log + 弹窗留痕）
import os

from PyInstaller.utils.hooks import collect_all

# ---------------------------------------------------------------
# 资源清单（2026-10-19 逐个核对过，缺一项就是"双击没反应"）
# ---------------------------------------------------------------
# frontend/dist : 前端构建产物，后端 `CacheControlledStaticFiles` 挂在 "/" 上。
#                 app/main.py 用 sys._MEIPASS/frontend/dist 取，故这里必须打进去，
#                 且目标目录名要同为 frontend/dist。
# .env          : 数据库连接串（DATABASE_URL）。app/core/config.py 用 _MEIPASS 读。
# data/         : ★ 故意**不打包**。它装的是用户上传的合同/发票/客户归档原件
#                 （当前 22MB），属于运行期数据而非程序资源：
#                 `app/core/file_storage.storage_root()` 在打包后指向
#                 「exe 同目录/data」，首次上传自动建目录。
#                 换机器部署时把整个 data 文件夹拷到 exe 旁边即可，
#                 库里存的是相对路径，所以能原样认回。
# templates/    : 本项目**没有**这个目录（打印模板存在数据库表里，由
#                 `ensure_default_print_templates()` 初始化），无需打包。
datas = [('frontend/dist', 'frontend/dist'), ('.env', '.')]
binaries = []

# passlib 的哈希处理器是注册表动态加载，PyInstaller 静态分析会漏，
# 必须显式声明（本机实际安装：passlib 1.7.4 + bcrypt 5.0.0，密码用 pbkdf2-sha256）
hiddenimports = [
    'passlib.handlers.pbkdf2',
    'passlib.handlers.bcrypt',
    # uvicorn 的 loop/protocol/lifespan 实现是运行时按字符串挑选（`auto` 系列），
    # 静态分析经常只抓到一层。显式列出，避免换 Python/uvicorn 版本后
    # 出现 "ImportError: Cannot import module uvicorn.protocols.http.auto" 式静默崩溃。
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
]

# OCR 模型、onnxruntime DLL、PDF 解析原生库等非 Python 资源
# （已剥离 pywebview/clr_loader/pythonnet —— 纯 Web 后端不需要 .NET 桌面壳）
for pkg in ('rapidocr_onnxruntime', 'pymupdf'):
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
    # console=False → 双击不弹黑色命令行框（正式版观感）。
    # 排查启动问题时用 ERP_CONSOLE=1 打一版带控制台的，报错会直接印在屏幕上。
    console=os.environ.get('ERP_CONSOLE', '') == '1',
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
