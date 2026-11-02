@echo off
rem ENPRT FSUK 2027 Wing Configuration Launcher
rem 1-Click Interactive Desktop App & JavaFoil Bridge
cd /d "%~dp0"
python open_in_aero_auto.py %*
if %ERRORLEVEL% NEQ 0 (
    python3 open_in_aero_auto.py %*
)
pause
