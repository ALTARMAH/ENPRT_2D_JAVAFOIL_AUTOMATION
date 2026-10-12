#!/usr/bin/env python3
"""
launcher.py - cross-platform command entry point for the aero_auto toolchain.

Runs either the interactive GUI or one of the headless tools by importing the
bundled modules (they must live in this folder next to this file).

  python launcher.py ui                           interactive design/GUI shell
  python launcher.py campaign [planner args...]   full aero_auto campaign planner
  python launcher.py report  [report args...]     HTML-folder report generator
  python launcher.py targets [targets args...]    target report (CL*A vs CD*A)
  python launcher.py field   [field  args...]     potential-flow field PNG

Environment overrides (optional):
  AERO_JAVA_DIR   JavaFoil folder that contains javafoil.jar
  AERO_AIRFOILS   folder with the .dat profiles
  AERO_OUT        campaign output folder (default ~/aero_campaign)
"""
import argparse
import io
import os
import sys
import time

# Ensure streams are never None (e.g. in PyInstaller windowed mode)
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stdout = io.StringIO()
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stderr = io.StringIO()


def _crash_handler(exc_type, exc_value, exc_tb):
    import traceback
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        crash_dir = os.path.join(os.path.expanduser("~"), ".aero_auto")
        os.makedirs(crash_dir, exist_ok=True)
        with open(os.path.join(crash_dir, "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fatal Error:\n{err_msg}\n")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "AeroAuto Error",
            f"An unexpected error occurred:\n\n{exc_type.__name__}: {exc_value}\n\nDetails saved to ~/.aero_auto/crash.log"
        )
        root.destroy()
    except Exception:
        pass


sys.excepthook = _crash_handler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aero_auto as A  # noqa: E402


def _apply_env():
    jd = os.environ.get("AERO_JAVA_DIR")
    if jd:
        A.JAVA_DIR = os.path.expanduser(jd)
        jar = os.path.join(A.JAVA_DIR, A.JAVAFOIL_JAR)
        if not os.path.exists(jar):
            print(f"(warning: javafoil jar not found at {jar})", file=sys.stderr)
    af = os.environ.get("AERO_AIRFOILS")
    if af:
        A.AIRFOIL_DIR = os.path.expanduser(af)
    out = os.environ.get("AERO_OUT")
    if out:
        A.OUT_DIR = os.path.expanduser(out)


def launcher():
    p = argparse.ArgumentParser(prog="aero", description="aero_auto toolchain entry point")
    p.add_argument("tool", nargs="?", default="ui", choices=["ui", "campaign", "report", "targets", "field"])
    p.add_argument("--version", action="version", version=f"aero_auto {A.VERSION}")
    args, rest = p.parse_known_args()
    _apply_env()
    if args.tool == "ui":
        import aero_ui
        aero_ui.main()
    elif args.tool == "campaign":
        sys.argv = ["aero_auto.py"] + rest
        A.main()
    elif args.tool == "report":
        import aero_report
        sys.argv = ["aero_report.py"] + rest
        aero_report.main()
    elif args.tool == "targets":
        import aero_targets
        sys.argv = ["aero_targets.py"] + rest
        aero_targets.main()
    elif args.tool == "field":
        import render_field
        render_field.main(rest)
    return 0


if __name__ == "__main__":
    sys.exit(launcher())