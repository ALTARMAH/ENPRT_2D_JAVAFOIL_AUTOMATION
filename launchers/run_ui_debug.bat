@echo off
REM aero_auto - Windows Debug Launcher with live console output
cd /d "%~dp0"
echo ========================================================
echo  Launching AeroAuto in Diagnostic Console Mode
echo ========================================================
echo.
aero_ui_debug.exe
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================================
    echo Process exited with status code: %ERRORLEVEL%
    echo If an error occurred, check ~/.aero_auto/crash.log
    echo ========================================================
    pause
)
