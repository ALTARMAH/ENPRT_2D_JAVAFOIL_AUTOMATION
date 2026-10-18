#!/usr/bin/env bash
# Open ENPRT FWB_hero config in Aero Auto
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/../open_in_aero_auto.py" ]; then
    cd "$HERE/.."
    exec python3 open_in_aero_auto.py "FWB_hero" "$@"
elif [ -f "/home/user/Applications/aero_auto/open_in_aero_auto.py" ]; then
    exec python3 /home/user/Applications/aero_auto/open_in_aero_auto.py "FWB_hero" "$@"
else
    echo "Error: open_in_aero_auto.py not found" >&2
    exit 1
fi
