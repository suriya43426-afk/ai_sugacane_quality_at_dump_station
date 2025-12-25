@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =========================================
REM AI Sugarcane - One-Click Setup
REM =========================================

set "BASE_DIR=%~dp0"
set "VENV_NAME=ai_sugarcane"
set "VENV_DIR=%BASE_DIR%%VENV_NAME%"
set "REQ_FILE=%BASE_DIR%requirements.txt"
set "LOG=%BASE_DIR%_install.log"

echo =========================================
echo   AI Sugarcane Setup
echo   Environment: %VENV_NAME%
echo   Location:    %BASE_DIR%
echo =========================================
echo.

echo [INFO] Setup started at %date% %time% > "%LOG%"

REM ---------------------------------------
REM 1. Validation
REM ---------------------------------------
if not exist "%REQ_FILE%" (
    echo [ERROR] 'requirements.txt' not found!
    echo [ERROR] 'requirements.txt' not found!>> "%LOG%"
    goto FAIL
)

REM ---------------------------------------
REM 2. Find Python (Prefer py launcher 3.10+)
REM ---------------------------------------
set "PY_CMD="
where py >nul 2>&1
if "%errorlevel%"=="0" (
    echo [INFO] Found 'py' launcher...
    set "PY_CMD=py -3.10"
    REM Attempt 3.12 or 3.11 if 3.10 not explicit (py usually picks latest)
    set "PY_CMD=py"
) else (
    where python >nul 2>&1
    if "%errorlevel%"=="0" (
        echo [INFO] Found 'python' in PATH...
        set "PY_CMD=python"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] No Python found!
    echo [TIP]   Please install Python 3.10+
    echo [TIP]   IMPORTANT: Check the box "Add Python to PATH" during installation.
    echo [ERROR] No Python found>> "%LOG%"
    goto FAIL
)

%PY_CMD% --version >> "%LOG%" 2>&1
echo [INFO] Using: %PY_CMD%

REM ---------------------------------------
REM 3. Create Virtual Environment
REM ---------------------------------------
if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [INFO] Environment '%VENV_NAME%' already exists.
    echo [INFO] Environment already exists>> "%LOG%"
) else (
    echo [INFO] Creating environment '%VENV_NAME%'...
    echo [INFO] Creating venv...>> "%LOG%"
    %PY_CMD% -m venv "%VENV_DIR%" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to create venv. Check permissions or Python install.
        goto FAIL
    )
)

REM ---------------------------------------
REM 4. Install Dependencies
REM ---------------------------------------
echo [INFO] Upgrading pip...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1

echo [INFO] Installing libraries from requirements.txt...
echo [INFO] This may take a few minutes (downloading torch/easyocr/etc)...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%REQ_FILE%" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    goto FAIL
)

REM ---------------------------------------
REM 5. Config Setup (Auto-create if missing)
REM ---------------------------------------
set "CONFIG_FILE=%BASE_DIR%config.txt"
if not exist "%CONFIG_FILE%" (
    echo [INFO] Creating default config.txt...
    echo [DEFAULT] > "%CONFIG_FILE%"
    echo factory=Sxx >> "%CONFIG_FILE%"
    echo total_lanes=1 >> "%CONFIG_FILE%"
    echo [NVR1] >> "%CONFIG_FILE%"
    echo camera_ip=192.168.1.100 >> "%CONFIG_FILE%"
    echo camera_username=admin >> "%CONFIG_FILE%"
    echo camera_password=password >> "%CONFIG_FILE%"
)

REM ---------------------------------------
REM 6. Create Shortcut
REM ---------------------------------------
echo [INFO] Creating Desktop Shortcut...
"%VENV_DIR%\Scripts\python.exe" "%BASE_DIR%source\utils\create_shortcut.py" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [WARNING] Failed to create shortcut. See log for details.
) else (
    echo [INFO] Shortcut created.
)

REM ---------------------------------------
REM 7. Security & Lockdown (Hide internals)
REM ---------------------------------------
echo [INFO] Applying security (hiding system files)...
if not exist "%BASE_DIR%results" mkdir "%BASE_DIR%results"

REM Hide everything first
attrib +h "%BASE_DIR%*.*"
for /d %%d in ("%BASE_DIR%*") do attrib +h "%%d"

REM Unhide only what user needs
attrib -h "%BASE_DIR%ai_orchestration.bat"
attrib -h "%BASE_DIR%update.bat"
attrib -h "%BASE_DIR%results"
attrib -h "%BASE_DIR%DEPLOYMENT_GUIDE.md"

REM Ensure config is hidden (already handled by *.* but explicit check)
if exist "%CONFIG_FILE%" attrib +h "%CONFIG_FILE%"

echo [INFO] Lockdown complete. User edit restricted.

echo.
echo =========================================
echo [SUCCESS] Setup Completed!
echo To run the system, use: ai_orchestration.bat
echo =========================================
echo.
echo [INFO] Setup finished successfully>> "%LOG%"

pause
exit /b 0

:FAIL
echo.
echo [ERROR] Setup FAILED!
echo Check log file for details: %LOG%
echo -----------------------------------------
powershell -NoProfile -Command "Get-Content -Tail 20 '%LOG%'" 2>nul
echo -----------------------------------------
pause
exit /b 1
