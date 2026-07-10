@echo off
cd /d "D:\讲书升级Agent"
echo 正在启动讲书升级Agent Web 服务...
echo.

:: 强制杀掉所有旧进程（兼容 cmd.exe 和双击启动）
echo [1/3] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001') do (
    taskkill /f /pid %%a >nul 2>&1
)
:: 二次清理残余
taskkill /f /fi "IMAGENAME eq python.exe" 2>nul
timeout /t 2 /nobreak >nul

:: 启动服务
echo [2/3] 启动服务...
start /min python web_app.py

timeout /t 3 /nobreak >nul

:: 打开浏览器
echo [3/3] 正在打开浏览器...
start http://127.0.0.1:8001

echo.
echo 服务已启动！
echo 如果浏览器未自动打开，请手动访问 http://127.0.0.1:8001
echo. 按任意键关闭此窗口
pause >nul
