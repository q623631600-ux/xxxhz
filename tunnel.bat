@echo off
title 讲书升级Agent 公网隧道
echo ================================================
echo   Starting public tunnel for http://localhost:8000
echo ================================================
echo.
echo   Copy the https://xxx.trycloudflare.com URL below
echo   and send it to the interviewer.
echo.
echo   WARNING: Close this window = link stops working.
echo   Each restart = a NEW random URL.
echo.
set HTTPS_PROXY=http://127.0.0.1:7897
set HTTP_PROXY=http://127.0.0.1:7897
D:\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate
echo.
echo Tunnel closed.
pause
