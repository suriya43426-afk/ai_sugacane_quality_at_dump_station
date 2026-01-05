@echo off
cd /d "%~dp0"
echo Starting Image Filter...
echo Using Python from: ..\venv\Scripts\python.exe

if exist "..\venv\Scripts\python.exe" (
    @echo off
    ..\venv\Scripts\python.exe ai_image_filter.py
) else (
    echo [ERROR] Virtual environment not found at ..\venv
    echo Please run setup.bat or update.bat in the main folder first.
    pause
    exit /b
)

pause
