#!/usr/bin/env bash
# Build a standalone single-folder app with PyInstaller (linux/macos).
# Requires: venv with `pip install -r requirements.txt pyinstaller`
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" -m PyInstaller --noconfirm --clean \
  --windowed --name aero_ui \
  --icon assets/icon.png \
  --add-data "assets:assets" --add-data "docs:docs" \
  launcher.py
echo "built in dist/aero_ui/"