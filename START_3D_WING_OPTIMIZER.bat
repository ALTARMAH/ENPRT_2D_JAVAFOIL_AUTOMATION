@echo off
setlocal
cd /d "%~dp0"
title ENPRT FSAE - Aero_Auto 3D Wing Optimizer & ANSYS Engine
echo =======================================================================
echo          ENPRT FSAE - AERO_AUTO 3D GROUND-EFFECT WING OPTIMIZER         
echo =======================================================================
echo.
echo Running 3D multi-element finite wing check, regulatory verification,
echo and iterative optimization sweep...
echo.

python aero_auto.py --wings-suite

echo.
echo =======================================================================
echo  Finished! Check C:\Users\USER\Desktop\tests for:
echo   - SUMMARY_AND_3D_ANALYSIS (Master comparative polars and CAD STLs)
echo   - 01_EVO1_3ELEMENT through 08_MY_PROFILE_BASELINE (Individual polars)
echo   - Front wings 3D Verified & Optimized.xlsx
echo   - TOP_3_WINGS_3D_ANALYSIS_REPORT.md
echo =======================================================================
pause
