@echo off
echo ========================================================
echo       AI Sugarcane Quality Detection - UPDATE
echo ========================================================

:: Remove git lock if exists
if exist ".git\index.lock" del ".git\index.lock"

echo [INFO] Pulling latest code from GitHub...
git pull origin main

if exist "venv" (
    echo [INFO] Updating requirements...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)

echo.
echo [SUCCESS] Update complete.
pause
