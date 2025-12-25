@echo off
setlocal
cd /d "%~dp0"

:START_LOOP
cls
echo ========================================================
echo       AI Orchestration - Auto Update Supervisor
echo ========================================================
echo [INFO] Checking for updates...
:: Fix: Remove stale lock file
if exist "%~dp0.git\index.lock" del "%~dp0.git\index.lock"

git pull
echo.


REM --- CHECK VCREDIST ---

REM --- CHECK VCREDIST ---
if exist "C:\Windows\System32\vcruntime140_1.dll" goto SKIP_VCREDIST

echo [WARNING] Microsoft Visual C++ Redistributable (vcruntime140_1.dll) not found.
echo [INFO] Downloading and installing VC++ Redistributable...
powershell -Command "Invoke-WebRequest -Uri https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile '%~dp0vc_redist.x64.exe'"

if not exist "%~dp0vc_redist.x64.exe" (
    echo [ERROR] Failed to download VC Redist. Please install manually from https://aka.ms/vs/17/release/vc_redist.x64.exe
    pause
    goto SKIP_VCREDIST
)

echo [INFO] Running installer...
"%~dp0vc_redist.x64.exe" /install /passive /norestart
del "%~dp0vc_redist.x64.exe"
echo [INFO] Installation complete. Resuming application...

:SKIP_VCREDIST
REM ----------------------

call "%~dp0ai_sugarcane\Scripts\activate.bat"
echo [INFO] Starting Application...
python "%~dp0source\ai_orchestration.py"

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%
echo [INFO] Application exited with code: %EXIT_CODE%

REM If Exit Code 100 -> Restart (Update)
REM If Exit Code 0   -> Exit normally
if "%EXIT_CODE%"=="100" (
    echo [INFO] Restarting for update...
    timeout /t 3
    goto START_LOOP
)

echo [INFO] Shutting down.
echo [INFO] Shutting down.
timeout /t 5
endlocal
