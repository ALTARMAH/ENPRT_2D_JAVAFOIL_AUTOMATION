@echo off
REM ==============================================================================
REM Aero Auto Launcher - High-Downforce Multi-Element Aerodynamic Suite
REM ==============================================================================
cd /d "%~dp0"

if exist "aero_ui_standalone.exe" (
    start "" "aero_ui_standalone.exe"
    exit /b 0
)

if exist "aero_ui.exe" (
    start "" "aero_ui.exe"
    exit /b 0
)

if exist "dist_win\aero_ui_standalone.exe" (
    start "" "dist_win\aero_ui_standalone.exe"
    exit /b 0
)

if exist "dist\aero_ui_standalone.exe" (
    start "" "dist\aero_ui_standalone.exe"
    exit /b 0
)

if exist "dist_win\aero_ui\aero_ui.exe" (
    start "" "dist_win\aero_ui\aero_ui.exe"
    exit /b 0
)

REM Check if Python is available in PATH
set PY_CMD=
python --version >nul 2>&1 && set PY_CMD=python
if not defined PY_CMD (
    py --version >nul 2>&1 && set PY_CMD=py
)

if defined PY_CMD (
    start "" %PY_CMD% launcher.py ui %*
    exit /b 0
)

echo ==============================================================================
echo                      AERO AUTO v1.1 - LAUNCHER
echo ==============================================================================
echo Neither aero_ui_standalone.exe nor Python was detected on this system.
echo.
echo Option 1 (Recommended - Ready to Run):
echo   Download the standalone executable:
echo   https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION/releases/download/v1.1/aero_ui_standalone.exe
echo   Save aero_ui_standalone.exe into this folder and double-click it.
echo.
echo Option 2 (Run from Python source):
echo   1. Install Python 3.10+ from https://www.python.org/
echo   2. Run: pip install -r requirements.txt
echo   3. Double-click run_ui.bat
echo ==============================================================================
echo.
pause
