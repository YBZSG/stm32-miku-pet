@echo off
setlocal
echo ========================================================
echo   [Miku Pet] 正在停止监控服务...
echo ========================================================
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Miku*" 2>nul
echo.
echo [OK] 服务已停止。
pause