@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  if errorlevel 1 goto :error
)
echo Installing build requirements...
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :error
echo Packaging Windows executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name StayInPath --icon "assets\stay-in-path.ico" --add-data "assets;assets" main.py
if errorlevel 1 goto :error
echo.
echo Created: dist\StayInPath.exe
echo Share this file via GitHub Releases. Users do not need Python.
pause
exit /b 0
:error
echo Build failed. See errors above.
pause
exit /b 1
