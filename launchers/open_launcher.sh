#!/usr/bin/env bash
# Open ENPRT Wing Configuration Launcher GUI
HERE=""
if [ -f "/../open_in_aero_auto.py" ]; then
    cd "/.."
    exec python3 open_in_aero_auto.py ""
elif [ -f "/home/user/Applications/aero_auto/open_in_aero_auto.py" ]; then
    exec python3 /home/user/Applications/aero_auto/open_in_aero_auto.py ""
else
    echo "Error: open_in_aero_auto.py not found" >&2
    exit 1
fi
