@echo off
setlocal
echo ========================================================
echo   [Miku Pet] Setting up Windows Silent Auto-Startup...
echo ========================================================
set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy /Y "G:\QtPrjt\superwuziqi\stm32\start_silent.vbs" "%TARGET_DIR%\MikuPetMonitor.vbs"
echo.
echo [SUCCESS] Miku Pet auto-startup has been installed!
echo Service will start quietly in background on Windows login.
echo Web Controller: http://localhost:18900
echo.
pause