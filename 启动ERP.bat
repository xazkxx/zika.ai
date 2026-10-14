@echo off
rem ERP desktop launcher (double-click to start)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" desktop_app.py
