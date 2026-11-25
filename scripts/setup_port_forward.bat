@echo off
REM Imua Port Forwarding Setup for WSL2
REM Run this once as Administrator to make Imua accessible from the LAN
REM
REM The WSL guest runs Imua on its internal IP (172.x.x.x).
REM Without this proxy, only the Windows host can reach it.
REM
REM Usage: Right-click → "Run as administrator"

REM Set these first: WSL_IP from `wsl hostname -I`, WINDOWS_IP from `ipconfig`
set WSL_IP=SET_ME
set WINDOWS_IP=SET_ME
if "%WSL_IP%"=="SET_ME" (echo Edit WSL_IP and WINDOWS_IP in this file first. & pause & exit /b 1)
set PORT=47280

echo Setting up port proxy: %WINDOWS_IP%:%PORT% → %WSL_IP%:%PORT%
netsh interface portproxy add v4tov4 listenaddress=%WINDOWS_IP% listenport=%PORT% connectaddress=%WSL_IP% connectport=%PORT%

echo.
echo Current proxies:
netsh interface portproxy show all

echo.
echo Done! Imua hub available at http://%WINDOWS_IP%:%PORT%
echo To remove later: netsh interface portproxy delete v4tov4 listenaddress=%WINDOWS_IP% listenport=%PORT%
pause
