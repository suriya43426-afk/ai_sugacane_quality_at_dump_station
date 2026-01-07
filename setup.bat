@echo off
echo ========================================================
echo       AI Sugarcane Quality Detection - SETUP
echo ========================================================

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    pause
    exit /b
)

:: Create Virtual Environment
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

:: Activate and Install
echo [INFO] Installing requirements...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Check Models
if not exist "models\objectdetection.pt" (
    echo [WARNING] License plate model missing at models\objectdetection.pt
)
if not exist "models\classification.pt" (
    echo [WARNING] Sugarcane classification model missing at models\classification.pt
)

echo.
echo [SUCCESS] Setup complete. You can now run the system using run_realtime.bat or directly.
pause
