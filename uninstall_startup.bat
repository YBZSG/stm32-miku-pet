@echo off
setlocal
echo ========================================================
echo   [Miku Pet] Removing Windows Auto-Startup...
echo ========================================================
set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%TARGET_DIR%\MikuPetMonitor.vbs" (
    del /F /Q "%TARGET_DIR%\MikuPetMonitor.vbs"
    echo [OK] Startup shortcut removed.
)
taskkill /F /IM pythonw.exe 2>nul
echo [OK] Background service stopped.
echo.
pause