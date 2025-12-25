@echo off
if not exist "venv" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b
)

echo [INFO] Starting AI Sugarcane Production System...
call venv\Scripts\activate.bat
python source\run_realtime.py
pause
