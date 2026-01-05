@echo off
echo ========================================
echo Running AWS Redshift Connection Test...
echo ========================================

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe test_redshift_connection.py
) else (
    echo [ERROR] Virtual environment not found. 
    echo Please run setup.bat or update.bat first.
)

pause
