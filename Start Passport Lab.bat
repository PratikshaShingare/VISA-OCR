@echo off
REM Khanna Travels - Passport Lab (local test bench for comparing passport extraction engines)
REM Opens http://localhost:8501 . Nothing is saved; the website is not changed.
cd /d "%~dp0backend\python"
echo Checking Streamlit is installed...
python -m pip show streamlit >nul 2>&1
if errorlevel 1 (
  echo Installing Passport Lab requirements ^(first run only^)...
  python -m pip install -r requirements.txt -r requirements-lab.txt
)
python -m streamlit run passport_lab\app.py --server.port 8501 --browser.gatherUsageStats false
pause
