@echo off
title ShifoNazorat - Bot + Tunnel Launcher
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo =====================================================
echo   ShifoNazorat - Bot va Tunnel ishga tushmoqda...
echo =====================================================
echo.

:: Check if cloudflared exists
if not exist "cloudflared.exe" (
    echo [XATO] cloudflared.exe topilmadi!
    echo Iltimos, cloudflared.exe ni shu papkaga yuklab oling:
    echo https://github.com/cloudflare/cloudflared/releases/latest
    pause
    exit /b 1
)

:: Start cloudflare tunnel in background, log to temp file
echo [1/3] Cloudflare Tunnel ishga tushmoqda...
start /B "" "cloudflared.exe" tunnel --url http://localhost:8000 > tunnel_log.txt 2>&1

:: Wait a few seconds for tunnel to establish
echo [2/3] Tunnel ulanishi kutilmoqda (8 soniya)...
timeout /t 8 /nobreak >nul

:: Extract the tunnel URL from log
echo [3/3] Tunnel URL aniqlanmoqda...
set TUNNEL_URL=
for /f "tokens=*" %%a in ('findstr /i "trycloudflare.com" tunnel_log.txt') do (
    set LINE=%%a
)

:: Parse the URL from the line
for /f "tokens=2 delims=| " %%b in ('findstr /i "https://.*trycloudflare.com" tunnel_log.txt') do (
    set TUNNEL_URL=%%b
)

if "%TUNNEL_URL%"=="" (
    :: Try second parse method
    for /f "tokens=*" %%c in ('findstr /i "https://" tunnel_log.txt ^| findstr /i "trycloudflare"') do (
        for /f "tokens=1 delims= " %%d in ("%%c") do (
            echo %%d | findstr /i "https://" >nul && set TUNNEL_URL=%%d
        )
    )
)

echo.
if not "%TUNNEL_URL%"=="" (
    echo =====================================================
    echo   TUNNEL MANZILI TOPILDI:
    echo   %TUNNEL_URL%
    echo =====================================================
    echo.
    echo .env fayliga WEBAPP_URL yozilmoqda...
    :: Update WEBAPP_URL in .env file using Python (safer)
    python -c "
import re, sys
url = '%TUNNEL_URL%'.strip()
with open('.env', 'r', encoding='utf-8') as f:
    content = f.read()
content = re.sub(r'WEBAPP_URL=.*', f'WEBAPP_URL={url}', content)
with open('.env', 'w', encoding='utf-8') as f:
    f.write(content)
print('WEBAPP_URL yangilandi:', url)
"
) else (
    echo [OGOHLANTIRISH] Tunnel URL aniqlanmadi.
    echo tunnel_log.txt faylini tekshiring.
    echo Bot localhost:8000 bilan ishga tushadi.
)

echo.
echo =====================================================
echo   Bot ishga tushmoqda...
echo =====================================================
python bot.py

echo.
echo =====================================================
echo   Bot to'xtatildi.
echo =====================================================
pause
