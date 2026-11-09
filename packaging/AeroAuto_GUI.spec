# -*- mode: python ; coding: utf-8 -*-
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC))
app_root = os.path.abspath(os.path.join(spec_dir, '..'))
launcher_script = os.path.join(app_root, 'launcher.py')

a = Analysis(
    [launcher_script],
    pathex=[app_root],
    binaries=[],
    datas=[(os.path.join(app_root, 'assets'), 'assets'), (os.path.join(app_root, 'docs'), 'docs')],
    hiddenimports=['PIL', 'PIL.ImageTk', 'ansys_engine', 'aero_auto_wings_suite', 'aero_3d_engine', 'scipy', 'matplotlib', 'gmsh'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AeroAuto_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(app_root, 'assets', 'icon.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AeroAuto_GUI',
)
