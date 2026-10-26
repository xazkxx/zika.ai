@echo off
rem ---------------------------------------------------------------
rem  Test instance for acceptance: source code + port 8019.
rem  Why a bat: the packaged exe on 8010 is a snapshot; this one always
rem  runs the CURRENT source, and pythonw detaches it from any shell.
rem  Stop it: Task Manager -> pythonw.exe  (or: taskkill /F /IM pythonw.exe)
rem ---------------------------------------------------------------
cd /d "%~dp0"
set ERP_PORT=8019
set ERP_NO_BROWSER=1
start "" ".venv\Scripts\pythonw.exe" desktop_app.py
