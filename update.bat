@echo off
setlocal
title AI Installer - Update System

echo ========================================================
echo       AI Sugarcane System - Auto Update
echo ========================================================
echo.

:: Check if git is installed
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed on this system!
    echo Please install Git for Windows first.
    echo.
    pause
    exit /b
)

echo [INFO] Pulling latest code from repository...
:: Fix: Remove stale git lock file if previous run crashed
if exist "%~dp0.git\index.lock" (
    echo [WARNING] Removing stale git index.lock...
    del "%~dp0.git\index.lock"
)

:: Detect current branch
for /f "tokens=*" %%i in ('git branch --show-current') do set CUR_BRANCH=%%i
if "%CUR_BRANCH%"=="" set CUR_BRANCH=main

echo [INFO] Current Branch: %CUR_BRANCH%
echo [INFO] Fetching origin...
git fetch origin

if %errorlevel% neq 0 (
    echo [ERROR] Failed to fetch. Check internet connection.
    pause
    exit /b
)

echo [INFO] Resetting local changes to match remote/%CUR_BRANCH%...
git reset --hard origin/%CUR_BRANCH%
if %errorlevel% neq 0 (
    echo [ERROR] Failed to reset. Git status might be corrupt.
    pause
    exit /b
)

echo.
echo [SUCCESS] System updated successfully!
echo You can now run the application.
echo.
pause
