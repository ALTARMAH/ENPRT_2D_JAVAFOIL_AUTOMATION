@echo off
title Push Updates to GitHub - ENPRT Aero Auto
color 0b
echo ======================================================================
echo   ENPRT FSAE - Push Updates to GitHub (origin/main)
echo ======================================================================
echo.
echo Repo: https://github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION.git
echo Branch: main
echo Latest Commit: 0a614be
echo.
echo Pushing changes now...
echo (If prompted, your browser will open to approve GitHub sign-in)
echo.

cd /d "C:\Users\USER\Desktop\ENPRT\04_AERO_AUTO_APP"
git push origin main

echo.
if %ERRORLEVEL% EQU 0 (
    color 0a
    echo ======================================================================
    echo   [SUCCESS] Successfully pushed all updates to GitHub!
    echo ======================================================================
) else (
    color 0c
    echo ======================================================================
    echo   [NOTE] If push was denied or failed, you can also push with a
    echo   GitHub Personal Access Token (classic token with 'repo' scope).
    echo ======================================================================
    echo.
    set /p token="Enter GitHub Token (or press Enter to exit): "
    if not "%token%"=="" (
        git push https://%token%@github.com/ALTARMAH/ENPRT_2D_JAVAFOIL_AUTOMATION.git main
    )
)
echo.
pause
