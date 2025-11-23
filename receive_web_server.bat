@echo off
chcp 65001 >nul
REM 检查是否以管理员身份运行，如果不是则重新以管理员身份启动当前脚本
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 请求管理员权限...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /B
)

REM 切换目录到当前批处理文件所在目录
cd /d "%~dp0"

REM 以下为管理员权限下执行的代码
@REM echo Updating repository...
@REM git pull origin master
echo Starting the web service...
python run_v2.py
pause
