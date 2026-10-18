@echo off
rem Open ENPRT FWB_stable config in Aero Auto
cd /d "%~dp0\.."
if exist "open_in_aero_auto.py" (
    python open_in_aero_auto.py FWB_stable %*
    if errorlevel 1 python3 open_in_aero_auto.py FWB_stable %*
) else (
    python "%~dp0..\..\08_AERO_AUTO_APP\engine\open_in_aero_auto.py" FWB_stable %*
)
pause
