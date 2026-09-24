@echo off
cd /d "%~dp0"

echo Starting the Khanna Travels backend and frontend servers...
echo (Two new windows will open - leave them both running.)
echo.

start "Khanna Travels - Backend" "%~dp0Start Backend.bat"
start "Khanna Travels - Frontend" "%~dp0Start Frontend.bat"

echo Waiting for the servers to come up...
timeout /t 3 /nobreak >nul

start "" "http://localhost:8766/index.html"

echo.
echo Done. This window can be closed - it does not need to stay open.
echo (The two server windows do need to stay open.)
pause
