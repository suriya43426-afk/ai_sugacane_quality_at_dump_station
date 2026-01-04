@echo off
echo Starting MDC NVR Snapshot Testing...
echo.

call ..\venv\Scripts\activate
python mdc_snapimage_testing.py

echo.
echo Testing Complete.
pause
