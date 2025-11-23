@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 打开GitHub Desktop - 选择文件夹
color 0B

echo.
echo ============================================================
echo       📂 打开GitHub Desktop - 选择文件夹
echo ============================================================
echo.

REM 查找GitHub Desktop
set "GITHUB_DESKTOP_PATH="
set "GITHUB_DESKTOP_FOUND=0"

if exist "%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe" (
    set "GITHUB_DESKTOP_PATH=%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"
    set "GITHUB_DESKTOP_FOUND=1"
    goto :found_desktop
)

if exist "%ProgramFiles%\GitHub Desktop\GitHubDesktop.exe" (
    set "GITHUB_DESKTOP_PATH=%ProgramFiles%\GitHub Desktop\GitHubDesktop.exe"
    set "GITHUB_DESKTOP_FOUND=1"
    goto :found_desktop
)

if exist "%ProgramFiles(x86)%\GitHub Desktop\GitHubDesktop.exe" (
    set "GITHUB_DESKTOP_PATH=%ProgramFiles(x86)%\GitHub Desktop\GitHubDesktop.exe"
    set "GITHUB_DESKTOP_FOUND=1"
    goto :found_desktop
)

where "GitHubDesktop.exe" >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%i in ('where "GitHubDesktop.exe" 2^>nul') do (
        if exist "%%i" (
            set "GITHUB_DESKTOP_PATH=%%i"
            set "GITHUB_DESKTOP_FOUND=1"
            goto :found_desktop
        )
    )
)

:found_desktop
if !GITHUB_DESKTOP_FOUND! equ 0 (
    echo.
    echo ============================================================
    echo ❌ 错误: 未找到GitHub Desktop
    echo ============================================================
    echo.
    echo 请先安装GitHub Desktop:
    echo   https://desktop.github.com/
    echo.
    pause
    exit /b 1
)

echo 📁 正在打开文件夹选择对话框...
echo.
echo 请在对话框中选择您要上传的文件夹
echo.

REM 使用VBScript显示文件夹选择对话框（更可靠）
set "SELECTED_FOLDER="
set "TEMP_VBS_SCRIPT=%TEMP%\folder_select_%RANDOM%.vbs"

REM 创建临时VBScript脚本
(
    echo Set objShell = CreateObject^("Shell.Application"^)
    echo Set objFolder = objShell.BrowseForFolder^(0, "请选择要上传到GitHub的文件夹", 0^)
    echo If Not objFolder Is Nothing Then
    echo     WScript.Echo objFolder.Self.Path
    echo End If
) > "!TEMP_VBS_SCRIPT!"

REM 执行VBScript脚本并获取结果
for /f "usebackq delims=" %%i in (`cscript //nologo "!TEMP_VBS_SCRIPT!" 2^>nul`) do (
    set "SELECTED_FOLDER=%%i"
)

REM 删除临时脚本
if exist "!TEMP_VBS_SCRIPT!" del "!TEMP_VBS_SCRIPT!" >nul 2>&1

REM 检查是否选择了文件夹
if "!SELECTED_FOLDER!"=="" (
    echo.
    echo ❌ 未选择文件夹，操作已取消
    echo.
    pause
    exit /b 0
)

REM 去除路径两端的空格
for /f "tokens=*" %%a in ("!SELECTED_FOLDER!") do set "SELECTED_FOLDER=%%a"

REM 检查文件夹是否存在
if "!SELECTED_FOLDER!"=="" (
    echo.
    echo ❌ 错误: 未选择有效的文件夹
    echo.
    pause
    exit /b 1
)

if not exist "!SELECTED_FOLDER!" (
    echo.
    echo ❌ 错误: 选择的文件夹不存在: !SELECTED_FOLDER!
    echo.
    pause
    exit /b 1
)

echo.
echo ✅ 已选择文件夹: !SELECTED_FOLDER!
echo.

REM 切换到选择的目录
cd /d "!SELECTED_FOLDER!"

REM 检查Git是否安装
where git >nul 2>&1
if !errorlevel! neq 0 (
    echo.
    echo ❌ 错误: 未找到Git，请先安装Git
    echo.
    pause
    exit /b 1
)

REM 检查是否是Git仓库，如果不是则初始化
if not exist ".git" (
    echo.
    echo 📦 检测到这不是Git仓库，正在初始化...
    echo.
    git init
    if !errorlevel! neq 0 (
        echo ❌ 错误: Git初始化失败
        echo.
        pause
        exit /b 1
    )
    echo ✅ Git仓库初始化成功
    echo.
)

REM 显示当前状态
echo ============================================================
echo 📋 当前仓库状态
echo ============================================================
echo.
git status --short
echo.

REM 询问用户是否要自动上传
echo ============================================================
echo 选择操作方式:
echo ============================================================
echo.
echo   1. 自动上传（添加所有文件、提交、强制推送覆盖远程）
echo   2. 打开GitHub Desktop手动操作
echo   0. 取消
echo.
set /p "ACTION=请选择 (1/2/0): "

if "!ACTION!"=="" (
    set "ACTION=0"
)

if "!ACTION!"=="0" (
    echo.
    echo 操作已取消
    echo.
    pause
    exit /b 0
)

if "!ACTION!"=="2" (
    echo.
    echo ============================================================
    echo 正在打开GitHub Desktop...
    echo ============================================================
    echo.
    start "" "!GITHUB_DESKTOP_PATH!" "!SELECTED_FOLDER!"
    echo ✅ GitHub Desktop已打开！
    echo.
    echo 窗口将在3秒后自动关闭...
    timeout /t 3 >nul
    exit /b 0
)

if not "!ACTION!"=="1" (
    echo.
    echo ❌ 无效的选择
    echo.
    pause
    exit /b 1
)

REM 自动上传流程
echo.
echo ============================================================
echo 🚀 开始自动上传流程
echo ============================================================
echo.

REM 1. 添加所有文件（包括删除的文件）
echo [1/4] 正在添加所有文件...
git add -A
if !errorlevel! neq 0 (
    echo ❌ 错误: 添加文件失败
    echo.
    pause
    exit /b 1
)
echo ✅ 文件添加完成
echo.

REM 2. 检查是否有更改需要提交
git diff --cached --quiet
if !errorlevel! equ 0 (
    echo ℹ️  没有需要提交的更改
    echo.
) else (
    REM 3. 提交更改
    echo [2/4] 正在提交更改...
    set "COMMIT_MSG=自动更新: %date% %time%"
    git commit -m "!COMMIT_MSG!"
    if !errorlevel! neq 0 (
        echo ❌ 错误: 提交失败
        echo.
        pause
        exit /b 1
    )
    echo ✅ 提交完成
    echo.
)

REM 4. 检查远程仓库
echo [3/4] 检查远程仓库配置...
git remote -v >nul 2>&1
if !errorlevel! neq 0 (
    echo ⚠️  未配置远程仓库
    echo.
    echo 请先配置远程仓库:
    echo   git remote add origin https://github.com/用户名/仓库名.git
    echo.
    echo 或者使用GitHub Desktop添加远程仓库
    echo.
    pause
    exit /b 1
)

REM 获取远程仓库信息
for /f "tokens=*" %%r in ('git remote get-url origin 2^>nul') do set "REMOTE_URL=%%r"
if "!REMOTE_URL!"=="" (
    echo ⚠️  未找到远程仓库URL
    echo.
    echo 请先配置远程仓库:
    echo   git remote add origin https://github.com/用户名/仓库名.git
    echo.
    pause
    exit /b 1
)

echo ✅ 远程仓库: !REMOTE_URL!
echo.

REM 5. 强制推送到远程（覆盖远程，删除远程不存在的文件）
echo [4/4] 正在强制推送到GitHub（覆盖远程仓库）...
echo.
echo ⚠️  警告: 这将用本地版本完全覆盖远程仓库！
echo.
set /p "CONFIRM=确认继续？(Y/N): "
if /i not "!CONFIRM!"=="Y" (
    echo.
    echo 操作已取消
    echo.
    pause
    exit /b 0
)

echo.
echo 正在推送...
git push origin --force --all
if !errorlevel! neq 0 (
    echo.
    echo ❌ 错误: 推送失败
    echo.
    echo 可能的原因:
    echo   1. 远程仓库不存在
    echo   2. 没有推送权限
    echo   3. 网络连接问题
    echo.
    echo 请检查远程仓库配置或使用GitHub Desktop手动推送
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo ✅ 上传完成！
echo ============================================================
echo.
echo 所有文件已成功上传到GitHub
echo 远程仓库已被本地版本完全覆盖
echo.
echo 窗口将在5秒后自动关闭...
timeout /t 5 >nul
endlocal
