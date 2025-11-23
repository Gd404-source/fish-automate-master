@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title GitHub Update
color 0B

echo.
echo ============================================================
echo       GitHub Update Script
echo ============================================================
echo.

cd /d "%~dp0"

set "github_username="
set "repo_name="
set "branch_name="

if exist "repo_config.txt" (
    for /f "usebackq tokens=1,2 delims==" %%a in ("repo_config.txt") do (
        if "%%a"=="github_username" set "github_username=%%b"
        if "%%a"=="repo_name" set "repo_name=%%b"
        if "%%a"=="branch_name" set "branch_name=%%b"
    )
)

if "!github_username!"=="" set "github_username=oioioi92"
if "!repo_name!"=="" set "repo_name=fish-automate"
if "!branch_name!"=="" set "branch_name=master"

echo Repository Information:
echo   Username: !github_username!
echo   Repository: !repo_name!
echo   Branch: !branch_name!
echo ============================================================
echo.

set "GIT_PATH="
set "GIT_FOUND=0"

if exist "C:\Program Files\Git\cmd\git.exe" (
    set "GIT_PATH=C:\Program Files\Git\cmd\git.exe"
    set "GIT_FOUND=1"
    goto found_git
)

if exist "C:\Program Files (x86)\Git\cmd\git.exe" (
    set "GIT_PATH=C:\Program Files (x86)\Git\cmd\git.exe"
    set "GIT_FOUND=1"
    goto found_git
)

where git >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%i in ('where git 2^>nul') do (
        if exist "%%i" (
            set "GIT_PATH=%%i"
            set "GIT_FOUND=1"
            goto found_git
        )
    )
)

:found_git
if !GIT_FOUND! equ 0 (
    echo Git not found. Opening browser for manual download...
    echo.
    set "REPO_URL=https://github.com/!github_username!/!repo_name!"
    start "" "!REPO_URL!"
    echo.
    echo ============================================================
    echo Download Instructions:
    echo ============================================================
    echo.
    echo 1. Browser opened to GitHub repository
    echo 2. Login to GitHub if prompted
    echo 3. Click the green "Code" button
    echo 4. Select "Download ZIP"
    echo 5. Extract ZIP to current folder
    echo 6. Keep reinstall.bat and repo_config.txt
    echo.
    echo Repository URL: !REPO_URL!
    echo.
    pause
    exit /b 0
)

echo Git found: !GIT_PATH!
echo.

"!GIT_PATH!" status >nul 2>&1
if !errorlevel! equ 0 (
    echo Git repository detected. Updating...
    echo.
    
    for /f "tokens=*" %%i in ('"!GIT_PATH!" branch --show-current 2^>nul') do (
        set "CURRENT_BRANCH=%%i"
    )
    if "!CURRENT_BRANCH!"=="" set "CURRENT_BRANCH=!branch_name!"
    
    "!GIT_PATH!" remote remove origin >nul 2>&1
    "!GIT_PATH!" remote add origin https://github.com/!github_username!/!repo_name!.git >nul 2>&1
    if !errorlevel! neq 0 (
        "!GIT_PATH!" remote set-url origin https://github.com/!github_username!/!repo_name!.git >nul 2>&1
    )
    
    echo Connecting to GitHub...
    "!GIT_PATH!" pull origin !branch_name!
    if !errorlevel! neq 0 (
        echo.
        echo Update failed. Opening browser for manual download...
        set "REPO_URL=https://github.com/!github_username!/!repo_name!"
        start "" "!REPO_URL!"
        echo.
        echo Browser opened. Please login and download ZIP file.
        pause
        exit /b 1
    )
    
    echo.
    echo ============================================================
    echo Update successful!
    echo ============================================================
    echo.
    timeout /t 3 >nul
    exit /b 0
)

echo No Git repository detected. Downloading...
echo.

set "SCRIPT_NAME=%~nx0"

for /f "delims=" %%I in ('dir /b /a 2^>nul') do (
    if /I not "%%I"=="!SCRIPT_NAME!" (
        if /I not "%%I"=="repo_config.txt" (
            if /I not "%%I"==".git" (
        if exist "%%I\*" (
                    rd /s /q "%%I" 2>nul
        ) else (
                    del /f /q "%%I" 2>nul
        )
    )
)
    )
)

echo Initializing Git repository...
"!GIT_PATH!" init >nul 2>&1
"!GIT_PATH!" remote add origin https://github.com/!github_username!/!repo_name!.git >nul 2>&1

echo.
echo Connecting to GitHub...
"!GIT_PATH!" pull origin !branch_name!
if !errorlevel! neq 0 (
    echo.
    echo Download failed. Opening browser for manual download...
    set "REPO_URL=https://github.com/!github_username!/!repo_name!"
    start "" "!REPO_URL!"
    echo.
    echo Browser opened. Please login and download ZIP file.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Download complete!
echo ============================================================
echo.
timeout /t 3 >nul
endlocal
