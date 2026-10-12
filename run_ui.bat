@echo off
REM aero_auto toolchain - Windows launcher (double-click run_ui.bat)
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
where %PY% >nul 2>nul || (
  echo python not found. Install Python 3.10+ from python.org, then run:
  echo   python -m pip install -r requirements.txt
  pause
  exit /b 1
)
%PY% launcher.py ui %*
pause