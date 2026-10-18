@echo off
rem Open ENPRT Wing Configuration Launcher GUI
cd /d "%~dp0\.."
if exist "open_in_aero_auto.py" (
    python open_in_aero_auto.py %*
    if errorlevel 1 python3 open_in_aero_auto.py %*
) else (
    python "%~dp0..\..\08_AERO_AUTO_APP\engine\open_in_aero_auto.py" %*
)
pause
