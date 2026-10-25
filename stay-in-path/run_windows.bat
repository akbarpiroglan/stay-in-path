@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating Python virtual environment...
  py -m venv .venv
  if errorlevel 1 goto :error
)
echo [2/2] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" main.py
exit /b %errorlevel%
:error
echo.
echo Setup failed. Ensure Python 3.10-3.15 is installed and the py launcher is available.
pause
exit /b 1
