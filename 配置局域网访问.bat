@echo off
rem ============================================================
rem  ERP LAN access setup (ASCII only, avoid encoding issue)
rem  What it does:
rem    1) auto-elevate to administrator
rem    2) open Windows firewall for TCP 8010 (ERP web backend)
rem    3) keep ERPNext portproxy (8000 -> 80)
rem    4) print phone access URL (dynamic LAN IP)
rem ============================================================

rem --- auto-elevate to admin ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

rem --- firewall: allow TCP 8010 inbound (idempotent) ---
netsh advfirewall firewall delete rule name="ERP-8010" >nul 2>&1
netsh advfirewall firewall add rule name="ERP-8010" dir=in action=allow protocol=TCP localport=8010

rem --- ERPNext portproxy (keep existing behavior) ---
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8000 >nul 2>&1
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=9000 >nul 2>&1
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8000 connectaddress=127.0.0.1 connectport=80

rem --- detect LAN IP (first IPv4) ---
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    if not defined LAN_IP set "LAN_IP=%%a"
)
set "LAN_IP=%LAN_IP: =%"

echo.
echo ============================================
echo  ERP phone access is ready.
echo  Phone must be on the SAME WiFi/router.
echo.
echo  ERP URL:  http://%LAN_IP%:8010
echo  Login:    admin / Admin123
echo ============================================
echo.
echo  If the IP above looks wrong, run "ipconfig" and
echo  use the IPv4 address of your WLAN/Wi-Fi adapter.
echo.
pause
