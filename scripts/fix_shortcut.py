# -*- coding: utf-8 -*-
"""更新桌面快捷方式：从旧打包 exe 改为读源码的桌面窗口版。

双击 → E 盘运行盘的 pythonw.exe 运行 desktop_app.py（无控制台、读最新源码、
弹独立窗口 + 监听 0.0.0.0:8010）。不再依赖遗留打包 exe（前端拆分后 exe 已过时）。
"""
import os

TARGET = r"E:\AI\ERP软件\.venv\Scripts\pythonw.exe"
ARGS = "desktop_app.py"
WORKDIR = r"E:\AI\ERP软件"
ICON = r"E:\AI\ERP软件\dist\ERP管理系统\ERP管理系统.exe"  # 复用 exe 内嵌图标
LNK = r"C:\Users\admi\Desktop\ERP管理系统.lnk"

if not os.path.exists(TARGET):
    print("目标 pythonw.exe 不存在:", TARGET)
    raise SystemExit(1)
if not os.path.exists(WORKDIR):
    print("工作目录不存在:", WORKDIR)
    raise SystemExit(1)

try:
    import pythoncom
    from win32com.shell import shell

    shortcut = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
    )
    shortcut.SetPath(TARGET)
    shortcut.SetArguments(ARGS)
    shortcut.SetWorkingDirectory(WORKDIR)
    shortcut.SetDescription("ERP 管理系统（读源码启动，双击运行）")
    if os.path.exists(ICON):
        shortcut.SetIconLocation(ICON, 0)

    persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Save(LNK, True)
    print("OK: 快捷方式已指向", TARGET, "参数", ARGS)
    print("    工作目录:", WORKDIR)
except Exception as exc:
    print("FAIL:", type(exc).__name__, exc)
    raise SystemExit(2)
