@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Starting dashboard...
echo Folder: %CD%
echo Python: !PYTHON_EXE!

"!PYTHON_EXE!" -m streamlit run app.py --server.headless false --browser.gatherUsageStats false

if errorlevel 1 (
    echo.
    echo Failed to start dashboard. Press any key to close.
    pause >nul
)
