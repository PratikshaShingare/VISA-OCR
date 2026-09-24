@echo off
title Khanna Travels - Frontend Server
cd /d "%~dp0"

echo ============================================================
echo  Khanna Travels ^& Holidays - Frontend Server
echo  Serving the app at http://localhost:8766/index.html
echo.
echo  Keep this window open while staff are using the app.
echo  Closing this window stops the site from being served.
echo ============================================================
echo.

where python >nul 2>&1
if %errorlevel%==0 (
    python -m http.server 8766
) else (
    py -m http.server 8766
)

echo.
echo Frontend server stopped.
pause
