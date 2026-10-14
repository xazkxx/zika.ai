@echo off
rem ============================================================
rem  ERP LAN access setup (ASCII only, avoid GBK/UTF-8 encoding issue)
rem  ERPNext: local 80  -> LAN 8000
rem  ERP:     local 8010 -> LAN 8010 (already 0.0.0.0:8010)
rem ============================================================

rem 1. remove old stale proxy rules (8000 pointed to empty 127.0.0.1:8000, 9000 leftover)
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8000
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=9000

rem 2. re-add 8000 -> 127.0.0.1:80  (ERPNext actually runs on port 80)
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8000 connectaddress=127.0.0.1 connectport=80

echo.
echo ===== Current portproxy rules =====
netsh interface portproxy show all
echo.
echo ERPNext (phone): http://192.168.3.7:8000
echo ERP     (phone): http://192.168.3.7:8010
echo.
pause
