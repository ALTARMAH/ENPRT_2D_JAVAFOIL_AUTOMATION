@echo off
rem Open Aero Auto main application
cd /d "%~dp0\.."
if exist "aero_ui.py" (
    python aero_ui.py %*
    if errorlevel 1 python3 aero_ui.py %*
) else (
    python "%~dp0..\..\08_AERO_AUTO_APP\engineero_ui.py" %*
)
pause
