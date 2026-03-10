@echo off
setlocal

cd /d "%~dp0"

set "APP_FILE=streamlit_app.py"
set "PORT=8501"

if not exist "%APP_FILE%" (
  echo [ERROR] Could not find %APP_FILE% in:
  echo   %CD%
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m streamlit --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Streamlit is not installed for "%PY%".
  echo Run this once:
  echo   %PY% -m pip install streamlit pandas pdfplumber openpyxl tqdm
  pause
  exit /b 1
)

echo Starting dashboard on http://localhost:%PORT% ...
start "" "http://localhost:%PORT%"
"%PY%" -m streamlit run "%APP_FILE%" --server.headless false --server.port %PORT%

if errorlevel 1 (
  echo.
  echo [ERROR] Dashboard exited with an error.
  pause
)

endlocal
