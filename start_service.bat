@echo off
setlocal
cd /d "G:\QtPrjt\superwuziqi\stm32"
echo ========================================================
echo   [Miku Pet] 正在启动桌面宠物监控服务与 Web 控制台...
echo ========================================================
echo.
python miku_monitor.py --auto -i
pause