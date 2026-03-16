@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0budget_dashboard"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=..\venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Starting SolarBudget Dashboard...
echo Root:   %~dp0
echo App:    %CD%
echo Python: !PYTHON_EXE!
echo.

"!PYTHON_EXE!" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false

if errorlevel 1 (
    echo.
    echo Failed to start. Check that dependencies are installed:
    echo   pip install -r requirements.txt
    echo.
    pause >nul
)
