@echo off
echo ========================================================
echo   Set WiFi to Private Network and Allow Port 18900
echo ========================================================
echo.
echo [*] Switching WiFi network category to Private...
powershell -Command "Set-NetConnectionProfile -InterfaceAlias 'WLAN' -NetworkCategory Private -ErrorAction SilentlyContinue"

echo [*] Adding Windows Firewall rules for Port 18900 and 43210...
netsh advfirewall firewall delete rule name="MikuPet_TCP_18900" >nul 2>&1
netsh advfirewall firewall delete rule name="MikuPet_UDP_43210" >nul 2>&1
netsh advfirewall firewall add rule name="MikuPet_TCP_18900" dir=in action=allow protocol=TCP localport=18900 profile=any
netsh advfirewall firewall add rule name="MikuPet_UDP_43210" dir=in action=allow protocol=UDP localport=43210 profile=any

echo.
echo ========================================================
echo [OK] Done!
echo.
echo 1. Open your phone browser.
echo 2. Make sure you type the full URL with http:// (not https):
echo    http://192.168.1.85:18900
echo ========================================================
echo.
pause
