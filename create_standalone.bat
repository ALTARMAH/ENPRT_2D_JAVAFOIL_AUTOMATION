@echo off
REM Build a standalone Windows .exe with PyInstaller.
REM Requires: python, then `python -m pip install -r requirements.txt pyinstaller`
cd /d "%~dp0"
%PYTHON% py -m PyInstaller --noconfirm --clean --windowed --name aero_ui ^
  --icon assets/icon.ico ^
  --add-data "assets;assets" --add-data "docs;docs" ^
  launcher.py
echo built in dist\aero_ui\
pause