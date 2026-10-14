# -*- coding: utf-8 -*-
"""更新桌面快捷方式指向 D 盘最新打包的 exe。"""
import os

TARGET = r"D:\ERP软件\dist\ERP管理系统\ERP管理系统.exe"
WORKDIR = r"D:\ERP软件\dist\ERP管理系统"
LNK = r"C:\Users\admi\Desktop\ERP管理系统.lnk"

if not os.path.exists(TARGET):
    print("目标 exe 不存在:", TARGET)
    raise SystemExit(1)

try:
    import pythoncom
    from win32com.shell import shell

    shortcut = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink,
    )
    shortcut.SetPath(TARGET)
    shortcut.SetWorkingDirectory(WORKDIR)
    shortcut.SetDescription("ERP 进销存管理系统（桌面版）")
    shortcut.SetIconLocation(TARGET, 0)

    persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Save(LNK, True)
    print("OK: 快捷方式已指向", TARGET)
except Exception as exc:
    print("FAIL:", type(exc).__name__, exc)
    raise SystemExit(2)
