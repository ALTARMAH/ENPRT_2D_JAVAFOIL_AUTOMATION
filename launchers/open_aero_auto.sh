#!/usr/bin/env bash
# Open Aero Auto main application
HERE=""
if [ -f "/../aero_ui.py" ]; then
    cd "/.."
    exec python3 aero_ui.py ""
elif [ -f "/home/user/Applications/aero_auto/aero_ui.py" ]; then
    exec python3 /home/user/Applications/aero_auto/aero_ui.py ""
else
    echo "Error: aero_ui.py not found" >&2
    exit 1
fi
