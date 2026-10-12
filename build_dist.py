#!/usr/bin/env python3
"""
build_dist.py - assemble the distributable aero_auto archives.

  python3 build_dist.py

Produces, into dist/:

  aero_auto_linux_<v>.tar.gz        source kit  (run with ./run_ui.sh)
  aero_auto_windows_<v>.zip         source kit  (run with run_ui.bat)
  aero_auto_linux_app_<v>.tar.gz    standalone app folder (dist_linux/aero_ui)
  aero_auto_windows_app_<v>.zip     standalone app folder (dist_win/aero_ui)

The source kits carry the modules, launch scripts, packaging scripts,
requirements and the docs/ folder (markdown + both PDFs). The standalone
archives are only produced when the matching PyInstaller output exists
(create_standalone.sh / create_standalone.bat).
"""
import os
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.1"
NAME = "aero_auto"
DIST = os.path.join(HERE, "dist")

SOURCE_FILES = [
    "aero_auto.py", "aero_ui.py", "aero_targets.py", "aero_report.py",
    "flowfield.py", "render_field.py", "launcher.py", "_sim_worker.py",
    "run_sim_terminal.py", "make_icon.py",
    "requirements.txt", "pyproject.toml", "aero_ui.spec",
    "run_ui.sh", "run_ui.bat",
    "create_standalone.sh", "create_standalone.bat", "build_dist.py",
    "README_WINDOWS.txt", "run_ui_debug.bat",
]
SOURCE_DIRS = ["assets", "docs"]
SKIP_DIRS = {"__pycache__", "build", "dist", "build_linux", "build_win",
             "dist_linux", "dist_win", "workers", ".git"}
SKIP_FILES = {".DS_Store"}


def _wanted(names):
    names[:] = [n for n in names
                if n not in SKIP_DIRS and not n.endswith((".pyc", ".pyo"))]
    return names


def _iter_source():
    for f in SOURCE_FILES:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            yield p, f"{NAME}_{VERSION}/{f}"
        else:
            print(f"  [warn] missing {f}")
    for d in SOURCE_DIRS:
        root = os.path.join(HERE, d)
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            _wanted(dirs)
            for n in files:
                if n in SKIP_FILES:
                    continue
                p = os.path.join(dirpath, n)
                yield p, f"{NAME}_{VERSION}/{os.path.relpath(p, HERE)}"


def _iter_tree(app_dir, arc_prefix):
    for dirpath, dirs, files in os.walk(app_dir):
        _wanted(dirs)
        for n in files:
            p = os.path.join(dirpath, n)
            yield p, os.path.join(arc_prefix, os.path.relpath(p, app_dir))


def _archive(items, out, kind, size_mb=False):
    if kind == "tar":
        with tarfile.open(out, "w:gz") as tf:
            for p, a in items:
                tf.add(p, a)
    else:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, a in items:
                zf.write(p, a)
    size = os.path.getsize(out)
    shown = f"{size / 1024 / 1024:.1f} MB" if size_mb else f"{size / 1024:.0f} KB"
    print(f"  {os.path.relpath(out, HERE)}  ({shown})")


def main():
    os.makedirs(DIST, exist_ok=True)
    print(f"building {NAME} {VERSION}")

    print("source kits:")
    _archive(_iter_source(), os.path.join(DIST, f"{NAME}_linux_{VERSION}.tar.gz"),
             "tar")
    _archive(_iter_source(), os.path.join(DIST, f"{NAME}_windows_{VERSION}.zip"),
             "zip")

    print("standalone apps:")
    for platform, kind in (("linux", "tar"), ("windows", "zip")):
        app_dir = os.path.join(HERE, f"dist_{'linux' if kind == 'tar' else 'win'}",
                               "aero_ui")
        if not os.path.isdir(app_dir):
            print(f"  [skip] {os.path.relpath(app_dir, HERE)} not built")
            continue
        # Ensure docs/ folder is directly visible at root level next to executable
        docs_src = os.path.join(HERE, "docs")
        docs_dst = os.path.join(app_dir, "docs")
        if os.path.isdir(docs_src):
            import shutil
            shutil.copytree(docs_src, docs_dst, dirs_exist_ok=True)
        # Ensure assets/ folder (including JavaFoil & airfoils) is directly visible at root level
        assets_src = os.path.join(HERE, "assets")
        assets_dst = os.path.join(app_dir, "assets")
        if os.path.isdir(assets_src):
            import shutil
            shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)
        # Copy README_WINDOWS.txt
        readme_src = os.path.join(HERE, "README_WINDOWS.txt")
        if os.path.isfile(readme_src):
            import shutil
            shutil.copy2(readme_src, os.path.join(app_dir, "README_WINDOWS.txt"))
        # Copy run_ui_debug.bat
        debug_bat = os.path.join(HERE, "run_ui_debug.bat")
        if os.path.isfile(debug_bat):
            import shutil
            shutil.copy2(debug_bat, os.path.join(app_dir, "run_ui_debug.bat"))
        ext = "tar.gz" if kind == "tar" else "zip"
        out = os.path.join(DIST, f"{NAME}_{platform}_app_{VERSION}.{ext}")
        _archive(_iter_tree(app_dir, "aero_ui"), out, kind, size_mb=True)

    standalone_exe = os.path.join(HERE, "dist_win", "aero_ui_standalone.exe")
    if os.path.isfile(standalone_exe):
        shutil.copy2(standalone_exe, os.path.join(DIST, "aero_ui_standalone.exe"))
        print(f"  dist/aero_ui_standalone.exe  ({os.path.getsize(standalone_exe) / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
