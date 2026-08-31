@echo off
cd /d "D:\½²ÊéÉý¼¶Agent"
echo ============================================
echo   JiangShu Agent Web Server
echo   http://127.0.0.1:8000
echo ============================================

:: kill old process on port 8000 only
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    echo Cleaning old PID=%%a
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: start server in a new detached window
echo Starting server...
start "JiangShuAgent" /min python web_app.py
timeout /t 5 /nobreak >nul

:: open browser
start http://127.0.0.1:8000
echo Done. You can close this window.
