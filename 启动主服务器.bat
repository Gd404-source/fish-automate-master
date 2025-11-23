@echo off
chcp 65001 >nul
title 启动主服务器
color 0A

REM 切换到脚本所在目录
cd /d "%~dp0"

echo.
echo ============================================================
echo       🖥️ 启动主服务器（发送指令的电脑）
echo ============================================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到Python
    echo 请先安装Python
    pause
    exit /b 1
)

echo ✅ Python已安装
echo.
echo ============================================================
echo 正在启动主服务器...
echo ============================================================
echo.
echo 启动后，请在浏览器中访问:
echo   http://127.0.0.1:5000
echo.
echo 或内网访问:
echo   http://192.168.0.254:5000
echo.
echo ============================================================
echo.
echo 按 Ctrl+C 可以停止服务器
echo.

REM 启动主服务器
python app_server.py

pause

