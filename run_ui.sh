#!/usr/bin/env bash
# aero_auto toolchain - Linux/macOS launcher (double-click or ./run_ui.sh)
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "python not found - install it, then: python -m pip install -r requirements.txt" >&2
    exit 1
fi
exec "$PY" launcher.py ui "$@"