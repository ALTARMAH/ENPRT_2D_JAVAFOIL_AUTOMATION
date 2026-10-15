@echo off
REM aero_auto toolchain - Windows launcher (double-click run_ui.bat)
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py
where %PY% >nul 2>nul && (
  %PY% launcher.py ui %*
  exit /b 0
)

if exist "aero_ui_standalone.exe" (
  start "" "aero_ui_standalone.exe"
  exit /b 0
)

if exist "aero_ui.exe" (
  start "" "aero_ui.exe"
  exit /b 0
)

echo Python is not installed and no standalone executable was found.
echo Please download aero_ui_standalone.exe from:
echo https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.1/aero_ui_standalone.exe
echo Or install Python 3.10+ from python.org and run:
echo   python -m pip install -r requirements.txt
pause
exit /b 1