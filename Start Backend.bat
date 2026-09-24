@echo off
title Khanna Travels - Backend (OCR + Documents)
cd /d "%~dp0backend\python"

echo ============================================================
echo  Khanna Travels ^& Holidays - Backend Server
echo  Handles passport OCR, document generation, and Excel export.
echo  Running at http://localhost:8000
echo.
echo  Keep this window open while staff are using the app.
echo  Closing this window stops the backend.
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel%==0 (
    python -m uvicorn app:app --reload --port 8000
) else (
    py -m uvicorn app:app --reload --port 8000
)

echo.
echo Backend stopped.
pause
