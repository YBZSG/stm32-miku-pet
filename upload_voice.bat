@echo off
cd /d "%~dp0"
echo ========================================================
echo        Miku Voice Pack Uploader (Auto Port)
echo ========================================================
echo.
python miku_pet\tools\upload_voice.py
echo.
pause
