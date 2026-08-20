@echo off
chcp 65001 >nul
title Codex Pet Bluetooth Bridge
echo 请先在 Windows 蓝牙设置中配对 HC-05，并查看它的“传出 COM 端口”。
set /p PET_BT_COM=请输入蓝牙 COM 端口（例如 COM8）：
if "%PET_BT_COM%"=="" exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\codex_pet_bridge.ps1" -Port %PET_BT_COM% -Baud 9600
echo.
echo 蓝牙桥接器已停止。按任意键关闭窗口。
pause >nul
