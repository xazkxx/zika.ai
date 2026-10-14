@echo off
rem ============================================================
rem  ERP 网页版启动器：双击后，浏览器打开 http://127.0.0.1:8010
rem  纯后端启动（不弹桌面窗口），适合只想用浏览器/手机访问的场景
rem ============================================================
cd /d "%~dp0"

rem 先看 8010 端口是否已经有服务在跑（比如桌面版已经开着）
netstat -ano | findstr ":8010" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
  echo 检测到后端已在运行，直接打开网页...
  start "" http://127.0.0.1:8010
  exit /b 0
)

echo 正在启动 ERP 后端服务（首次启动约需十几秒）...
start "" ".venv\Scripts\pythonw.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8010

rem 等 3 秒再打开浏览器（后端还在起，页面可能先显示"无法连接"，刷新即可）
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8010
