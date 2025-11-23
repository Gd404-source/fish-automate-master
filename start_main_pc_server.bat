@echo off
chcp 65001 >nul
REM 切换到脚本所在目录
cd /d "%~dp0"
echo Starting the Main pc screen shot...
python main.py
pause