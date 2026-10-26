@echo off
REM ===========================================================================
REM  Menu-tree backup launcher  (pure ASCII - do NOT add Chinese here,
REM  cmd.exe reads .bat as ANSI/GBK and non-ASCII literals get corrupted)
REM
REM  Double-click to write  backup\menu_tree\menu_tree.sql
REM ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PY=%~dp0.venv\Scripts\python.exe

if not exist "%PY%" (
  echo [x] venv python not found: %PY%
  pause
  exit /b 1
)

"%PY%" "%~dp0scripts\backup_menu_tree.py" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo [OK] done.) else (echo [FAIL] exit code %RC%)

REM Pause only for a bare double-click (no args) so the window stays readable.
REM With arguments (scripted/CI use) do not block.
if "%~1"=="" pause
exit /b %RC%
