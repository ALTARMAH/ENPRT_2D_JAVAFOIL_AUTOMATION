@echo off
rem Open ENPRT RW_incidence3 config in Aero Auto
cd /d "%~dp0\.."
if exist "open_in_aero_auto.py" (
    python open_in_aero_auto.py RW_incidence3 %*
    if errorlevel 1 python3 open_in_aero_auto.py RW_incidence3 %*
) else (
    python "%~dp0..\..\08_AERO_AUTO_APP\engine\open_in_aero_auto.py" RW_incidence3 %*
)
pause
