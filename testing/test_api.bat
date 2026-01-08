@echo off
echo ========================================
echo Running Serverless API Test...
echo ========================================

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe test_api_serverless.py
) else (
    echo [ERROR] Virtual environment not found. 
    echo Please run setup.bat or update.bat first.
)

pause
