@echo off
chcp 65001 >nul
title Codex Pet Bridge
echo 正在启动 Codex Pet 状态同步（COM7）...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\codex_pet_bridge.ps1" -Port COM7
echo.
echo 桥接器已停止。按任意键关闭窗口。
pause >nul
