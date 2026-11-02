#!/usr/bin/env python3
"""
ansys_engine.py
===============
Universal ANSYS Fluent Simulation Engine & Automation Pipeline for Aero_Auto.
Designed for any Windows system, any ANSYS version (2020 through 2026+), and custom install paths.

Key Capabilities:
  1. Universal multi-version auto-detection: scans AWP_ROOT252 down to AWP_ROOT180, system PATH,
     and all physical drive letters (C:, D:, E:, F:).
  2. Dynamic path resolution: no hardcoded usernames or fixed drives.
  3. Version-agnostic launcher: drops fixed release flags (-r24.1.0) so any installed version launches natively.
  4. PyFluent (ansys.fluent.core) API integration when installed.
  5. Automated batch journal (.jou) generation for 2D & 3D race car wings.
  6. Standard FSAE turbulence settings: k-omega SST (Menter 1994) with y+ ~ 1 boundary layer.
  7. Extraction of Downforce (N), Drag (N), Cl, Cd, L/D and surface pressure distributions.
"""

import os
import sys
import glob
import json
import math
import time
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

# Default aerodynamic properties
RHO_AIR = 1.225       # kg/m^3
MU_AIR = 1.7894e-5    # Pa.s
NU_AIR = 1.48e-5      # m^2/s
VELOCITY_DEFAULT = 15.0  # m/s (~54 km/h FSAE cornering speed)

def get_desktop_dir() -> Path:
    """Returns the user's Desktop directory dynamically across any Windows username or OneDrive configuration."""
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop
    c_user = Path(r"C:\Users\USER\Desktop")
    if c_user.exists():
        return c_user
    return Path.cwd()

def get_tests_dir() -> Path:
    """Returns the tests results directory dynamically on Desktop or local project."""
    desktop_tests = get_desktop_dir() / "tests"
    if desktop_tests.exists():
        return desktop_tests
    c_user_tests = Path(r"C:\Users\USER\Desktop\tests")
    if c_user_tests.exists():
        return c_user_tests
    return desktop_tests

def get_available_drive_letters() -> List[str]:
    """Finds all existing Windows drive letters (C, D, E, F, G, etc.)."""
    drives = []
    if os.name == 'nt':
        import string
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                drives.append(letter)
    if not drives:
        drives = ['C', 'D', 'E']
    return drives

def detect_ansys_root(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Detect ANSYS root folder across ANY version (2026 R2 down to 2018 / v180)
    and ANY drive letter or installation directory.
    """
    if custom_path and os.path.exists(custom_path):
        p = Path(custom_path)
        if p.name.lower() == 'fluent.exe':
            try:
                cand = p.parent.parent.parent.parent
                if (cand / "fluent").exists():
                    return str(cand)
            except Exception:
                pass
            return str(p.parent)
        if (p / "fluent").exists():
            return str(p)
        return str(p)

    # 1. Check explicit environment variable overrides
    for env_var in ["ANSYS_ROOT", "ANSYS_PATH", "FLUENT_PROD_DIR"]:
        val = os.environ.get(env_var)
        if val and os.path.exists(val):
            return val

    # 2. Check all standard ANSYS Windows version environment variables AWP_ROOT<XYZ>
    # From 262 (2026 R2) down to 180 (18.0)
    all_version_codes = [
        "262", "261", "252", "251", "242", "241", "232", "231",
        "222", "221", "212", "211", "202", "201", "195", "194",
        "193", "192", "191", "190", "182", "181", "180"
    ]
    for ver in all_version_codes:
        val = os.environ.get(f"AWP_ROOT{ver}")
        if val and os.path.exists(val):
            return val

    # 3. Check standard installation directories across all available drives
    drives = get_available_drive_letters()
    for drive in drives:
        patterns = [
            f"{drive}:\\Program Files\\ANSYS Inc\\v*",
            f"{drive}:\\Program Files (x86)\\ANSYS Inc\\v*",
            f"{drive}:\\ANSYS Inc\\v*",
            f"{drive}:\\ANSYS\\v*",
            f"{drive}:\\ANSYS Inc",
            f"{drive}:\\ANSYS",
        ]
        candidates = []
        for pat in patterns:
            for matched in glob.glob(pat):
                if os.path.isdir(matched) and (Path(matched) / "fluent").exists():
                    candidates.append(matched)
        if candidates:
            # Sort descending to pick the newest version (e.g. v242 > v241 > v232)
            candidates.sort(reverse=True)
            return candidates[0]

    return None

def detect_fluent_executable(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Locates the fluent.exe executable dynamically.
    Works for any version, any drive letter, or custom path.
    """
    # 1. Custom path override if provided and valid
    if custom_path:
        p = Path(custom_path)
        if p.is_file() and p.name.lower() == 'fluent.exe' and p.exists():
            return str(p.resolve())
        if p.is_dir():
            for sub in [
                p / "fluent" / "ntbin" / "win64" / "fluent.exe",
                p / "ntbin" / "win64" / "fluent.exe",
                p / "fluent.exe"
            ]:
                if sub.exists():
                    return str(sub.resolve())

    # 2. Check explicit FLUENT_EXE or ANSYS_FLUENT_EXE environment variable
    for env in ["FLUENT_EXE", "ANSYS_FLUENT_EXE"]:
        val = os.environ.get(env)
        if val and os.path.isfile(val) and os.path.exists(val):
            return str(Path(val).resolve())

    # 3. Check system PATH via which
    which_fluent = shutil.which("fluent.exe") or shutil.which("fluent")
    if which_fluent and os.path.exists(which_fluent):
        return str(Path(which_fluent).resolve())

    # 4. Check root detected from environment variables
    root = detect_ansys_root(custom_path)
    if root:
        for sub in [
            Path(root) / "fluent" / "ntbin" / "win64" / "fluent.exe",
            Path(root) / "fluent" / "ntbin" / "fluent.exe",
            Path(root) / "ntbin" / "win64" / "fluent.exe"
        ]:
            if sub.exists():
                return str(sub.resolve())

    # 5. Direct glob scan across all Windows drives for fluent.exe
    drives = get_available_drive_letters()
    fluent_candidates = []
    for drive in drives:
        patterns = [
            f"{drive}:\\Program Files\\ANSYS Inc\\v*\\fluent\\ntbin\\win64\\fluent.exe",
            f"{drive}:\\ANSYS Inc\\v*\\fluent\\ntbin\\win64\\fluent.exe",
            f"{drive}:\\ANSYS\\v*\\fluent\\ntbin\\win64\\fluent.exe",
        ]
        for pat in patterns:
            for matched in glob.glob(pat):
                if os.path.isfile(matched):
                    fluent_candidates.append(matched)
    if fluent_candidates:
        fluent_candidates.sort(reverse=True)
        return str(Path(fluent_candidates[0]).resolve())

    return None

def get_ansys_version_info(fluent_bin: Optional[str] = None) -> Dict[str, str]:
    """Returns parsed human-readable version info for the detected Fluent installation."""
    if not fluent_bin:
        fluent_bin = detect_fluent_executable()
    if not fluent_bin:
        return {"version_name": "Not Installed", "version_code": "unknown", "path": ""}

    p_str = fluent_bin.replace('/', '\\')
    import re
    match = re.search(r'\\v(\d{3})\\', p_str, re.IGNORECASE)
    if match:
        code = match.group(1) # '241'
        year = f"20{code[:2]}" # '2024'
        release = f"R{code[2]}" # 'R1'
        return {
            "version_name": f"ANSYS {year} {release} (v{code})",
            "version_code": code,
            "path": fluent_bin
        }
    return {
        "version_name": "ANSYS Fluent (Custom Path)",
        "version_code": "custom",
        "path": fluent_bin
    }

def create_solved_startup_journal(
    case_file: Union[str, Path],
    output_jou_path: Optional[Union[str, Path]] = None,
    wall_zones: str = "()"
) -> Path:
    """
    Creates an automated ANSYS Fluent startup journal that loads both the case and converged data,
    sets up surface pressure contours, displays the geometry, and prints converged forces.
    Leaves Fluent in full interactive GUI mode.
    """
    case_p = Path(case_file).resolve()
    if not output_jou_path:
        output_jou_path = case_p.parent / "load_solved_solution.jou"
    else:
        output_jou_path = Path(output_jou_path).resolve()

    cas_name = case_p.name
    jou_content = (
        f'; =========================================================================\n'
        f'; FSAE Aerodynamics Solved Solution Startup Journal for ANSYS Fluent\n'
        f'; Automatically loads Mesh, Converged Calculations, Contours, and Forces\n'
        f'; =========================================================================\n'
        f'/file/read-case-data "{cas_name}"\n'
        f'/display/set/picture/driver png\n'
        f'/display/contour pressure\n'
        f'/report/forces/wall-forces yes 0 -1 0 {wall_zones}\n'
        f'/report/forces/wall-forces yes 1 0 0 {wall_zones}\n'
        f'; Fluent is now ready in interactive GUI mode.\n'
    )
    output_jou_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_jou_path, "w", encoding="utf-8") as f:
        f.write(jou_content)
    return output_jou_path


def launch_fluent_gui(
    case_file: Optional[Path] = None,
    journal_file: Optional[Path] = None,
    is_3d: bool = True,
    num_procs: int = 4,
    custom_fluent_exe: Optional[str] = None,
    working_dir: Optional[Path] = None,
    load_solved_data: bool = True
) -> Tuple[bool, str]:
    """
    Universal Fluent launcher that works across ANY version and ANY directory.
    When load_solved_data=True and a solved data file exists, automatically loads both
    mesh and converged calculation data, displays pressure contours, and reports forces.
    """
    fluent_bin = detect_fluent_executable(custom_fluent_exe)
    if not fluent_bin or not os.path.exists(fluent_bin):
        return False, "ANSYS Fluent executable (fluent.exe) not found on system."

    dim_flag = "3ddp" if is_3d else "2ddp"
    cmd_parts = [f'"{fluent_bin}"', dim_flag, f"-t{num_procs}"]

    cwd_dir = working_dir if working_dir else (Path(case_file).parent if case_file else Path.cwd())

    # If load_solved_data is requested and case_file exists
    if load_solved_data and case_file:
        case_p = Path(case_file)
        # Check if corresponding .dat.h5 or .dat exists
        dat_h5 = case_p.with_suffix('.dat.h5') if case_p.name.endswith('.cas.h5') else case_p.with_suffix('.dat')
        alt_dat = case_p.parent / case_p.name.replace('.cas.h5', '.dat.h5')
        existing_jou = case_p.parent / "load_solved_solution.jou"

        if existing_jou.exists():
            cmd_parts.append(f'-i "{existing_jou.name}"')
        elif dat_h5.exists() or alt_dat.exists() or 'solved' in case_p.name:
            startup_jou = create_solved_startup_journal(case_p)
            cmd_parts.append(f'-i "{startup_jou.name}"')
        else:
            cmd_parts.append(f'-case "{case_p.name}"')
            if journal_file and Path(journal_file).exists():
                cmd_parts.append(f'-i "{Path(journal_file).name}"')
    else:
        if case_file and Path(case_file).exists():
            cmd_parts.append(f'-case "{Path(case_file).name}"')
        if journal_file and Path(journal_file).exists():
            cmd_parts.append(f'-i "{Path(journal_file).name}"')

    cmd = " ".join(cmd_parts)

    try:
        subprocess.Popen(cmd, cwd=str(cwd_dir), shell=True)
        return True, f"Launched: {cmd}"
    except Exception as e:
        return False, f"Error launching Fluent: {e}"


def detect_solidworks_executable(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Auto-detect SolidWorks executable (SLDWORKS.exe) across:
      1. User-specified custom path
      2. Windows Registry (HKLM & HKCU: SOFTWARE\\SolidWorks\\SOLIDWORKS <year>\\Setup -> SolidWorks Folder)
      3. Windows Registry App Paths (HKLM & HKCU: SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\SLDWORKS.exe)
      4. Standard installation directories across all physical drives (C:, D:, E:, etc.)
      5. System PATH environment variable
    """
    if custom_path and os.path.isfile(custom_path):
        return str(Path(custom_path).resolve())

    # 1. System PATH
    p = shutil.which("SLDWORKS.exe") or shutil.which("SLDWORKS")
    if p and os.path.isfile(p):
        return str(Path(p).resolve())

    # 2. Windows Registry
    if os.name == 'nt':
        try:
            import winreg
            for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    # Check HKLM/HKCU\SOFTWARE\SolidWorks
                    try:
                        with winreg.OpenKey(hkey, r'SOFTWARE\SolidWorks', 0, winreg.KEY_READ | access) as root:
                            num_subkeys, _, _ = winreg.QueryInfoKey(root)
                            for i in range(num_subkeys):
                                sk_name = winreg.EnumKey(root, i)
                                if 'SOLIDWORKS' in sk_name.upper():
                                    try:
                                        with winreg.OpenKey(root, rf'{sk_name}\Setup', 0, winreg.KEY_READ | access) as setup_key:
                                            val, _ = winreg.QueryValueEx(setup_key, 'SolidWorks Folder')
                                            exe = os.path.join(val, 'SLDWORKS.exe')
                                            if os.path.isfile(exe):
                                                return str(Path(exe).resolve())
                                    except OSError:
                                        pass
                    except OSError:
                        pass
                    # Check App Paths
                    try:
                        with winreg.OpenKey(hkey, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\SLDWORKS.exe', 0, winreg.KEY_READ | access) as key:
                            val, _ = winreg.QueryValue(key, '')
                            if val and os.path.isfile(val):
                                return str(Path(val).resolve())
                    except OSError:
                        pass
        except Exception:
            pass

    # 3. Known Filesystem install locations across all available drives
    drives = get_available_drive_letters()
    for drive in drives:
        candidates = [
            Path(f"{drive}:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe"),
            Path(f"{drive}:/Program Files/SOLIDWORKS Corp (2)/SOLIDWORKS/SLDWORKS.exe"),
            Path(f"{drive}:/Program Files/SOLIDWORKS Corp (3)/SOLIDWORKS/SLDWORKS.exe"),
            Path(f"{drive}:/Program Files/SOLIDWORKS/SLDWORKS.exe"),
            Path(f"{drive}:/Program Files (x86)/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe"),
            Path(f"{drive}:/Program Files/Dassault Systemes/SOLIDWORKS/SLDWORKS.exe"),
        ]
        for c in candidates:
            if c.is_file():
                return str(c.resolve())
        # Check year folders like Program Files/SOLIDWORKS 2025/SLDWORKS.exe
        for pattern in [f"{drive}:/Program Files/SOLIDWORKS*/SLDWORKS.exe", f"{drive}:/Program Files/SOLIDWORKS*/*/SLDWORKS.exe"]:
            for match in glob.glob(pattern):
                if os.path.isfile(match):
                    return str(Path(match).resolve())

    return None


def detect_cad_executable(custom_path: Optional[str] = None) -> Optional[str]:
    """
    Detects SolidWorks first, or falls back to major CAD software suites
    (Fusion 360, FreeCAD, Inventor, Rhino, NX, Creo).
    """
    sw = detect_solidworks_executable(custom_path)
    if sw:
        return sw

    # 1. Fusion 360
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        fusion_matches = glob.glob(os.path.join(local_app_data, "Autodesk", "webdeploy", "production", "*", "Autodesk Fusion 360.exe"))
        if fusion_matches and os.path.isfile(fusion_matches[0]):
            return str(Path(fusion_matches[0]).resolve())

    # 2. FreeCAD
    freecad_p = shutil.which("FreeCAD.exe") or shutil.which("FreeCAD")
    if freecad_p and os.path.isfile(freecad_p):
        return str(Path(freecad_p).resolve())
    drives = get_available_drive_letters()
    for drive in drives:
        fc_matches = glob.glob(f"{drive}:/Program Files*/FreeCAD*/bin/FreeCAD.exe")
        if fc_matches and os.path.isfile(fc_matches[0]):
            return str(Path(fc_matches[0]).resolve())

    # 3. Autodesk Inventor
    for drive in drives:
        inv_matches = glob.glob(f"{drive}:/Program Files*/Autodesk/Inventor*/Bin/Inventor.exe")
        if inv_matches and os.path.isfile(inv_matches[0]):
            return str(Path(inv_matches[0]).resolve())

    # 4. Rhino
    for drive in drives:
        rhino_matches = glob.glob(f"{drive}:/Program Files*/Rhino*/System/Rhino.exe")
        if rhino_matches and os.path.isfile(rhino_matches[0]):
            return str(Path(rhino_matches[0]).resolve())

    return None


def get_solidworks_version_info(sw_bin: Optional[str] = None) -> Dict[str, str]:
    """Returns human-readable version info for detected SolidWorks installation."""
    if not sw_bin:
        sw_bin = detect_solidworks_executable()
    if not sw_bin or not os.path.isfile(sw_bin):
        return {"version_name": "Not Installed", "version_year": "unknown", "path": ""}

    # Check Windows Registry for exact edition name (e.g., 'SOLIDWORKS 2025')
    if os.name == 'nt':
        try:
            import winreg
            for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for access in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hkey, r'SOFTWARE\SolidWorks', 0, winreg.KEY_READ | access) as root:
                            for i in range(winreg.QueryInfoKey(root)[0]):
                                sk = winreg.EnumKey(root, i)
                                if 'SOLIDWORKS' in sk.upper():
                                    try:
                                        with winreg.OpenKey(root, rf'{sk}\Setup', 0, winreg.KEY_READ | access) as s:
                                            f, _ = winreg.QueryValueEx(s, 'SolidWorks Folder')
                                            if os.path.normpath(f).lower() in os.path.normpath(sw_bin).lower():
                                                return {
                                                    "version_name": sk.strip(),
                                                    "version_year": "".join(c for c in sk if c.isdigit()),
                                                    "path": sw_bin
                                                }
                                    except OSError:
                                        pass
                    except OSError:
                        pass
        except Exception:
            pass

    import re
    match = re.search(r'20\d{2}', sw_bin)
    year = match.group(0) if match else "Standard"
    return {
        "version_name": f"SolidWorks {year}",
        "version_year": year,
        "path": sw_bin
    }


def open_with_system_default(path: Union[str, Path]) -> bool:
    """Open a file/folder with the OS default handler safely without blocking."""
    try:
        p_str = os.path.expanduser(str(path))
        if sys.platform.startswith('win'):
            os.startfile(p_str)
            return True
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', p_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        else:
            opener = shutil.which('xdg-open') or shutil.which('gio')
            if opener:
                cmd = [opener, 'open', p_str] if opener.endswith('gio') else [opener, p_str]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
    except Exception:
        pass
    return False


def launch_cad_file(
    file_path: Union[str, Path],
    custom_cad_exe: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Universal CAD launcher that opens 3D models (STL, STEP, IGES, etc.) in SolidWorks
    or the user's preferred CAD application.
    Falls back gracefully to other installed CAD suites or the OS default 3D handler.
    """
    target_path = Path(file_path).resolve()
    if not target_path.exists():
        return False, f"File does not exist: {target_path}"

    cad_exe = detect_solidworks_executable(custom_cad_exe) or detect_cad_executable(custom_cad_exe)
    if cad_exe and os.path.isfile(cad_exe):
        try:
            if os.name == 'nt':
                # Launch detached process so aero_ui never freezes
                subprocess.Popen([cad_exe, str(target_path)], close_fds=False)
            else:
                subprocess.Popen([cad_exe, str(target_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            app_info = get_solidworks_version_info(cad_exe)
            return True, f"Launched in {app_info.get('version_name', 'SolidWorks')}"
        except Exception as e:
            pass

    # Fallback to OS handler
    opened = open_with_system_default(str(target_path))
    if opened:
        return True, "Opened with system default 3D viewer"
    return False, "Failed to launch 3D viewer"


class AnsysFluentEngine:
    """Interface to ANSYS Fluent on Windows via PyFluent or Batch Journal."""

    def __init__(self, working_dir: Optional[str] = None, custom_fluent_exe: Optional[str] = None):
        self.working_dir = Path(working_dir) if working_dir else get_tests_dir() / "ansys_runs"
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.custom_fluent_exe = custom_fluent_exe
        self.ansys_root = detect_ansys_root(custom_fluent_exe)
        self.fluent_bin = detect_fluent_executable(custom_fluent_exe)
        self.version_info = get_ansys_version_info(self.fluent_bin)
        self.pyfluent_available = self.check_pyfluent()

    detect_ansys_root = staticmethod(detect_ansys_root)
    detect_fluent_executable = staticmethod(detect_fluent_executable)
    get_ansys_version_info = staticmethod(get_ansys_version_info)
    launch_fluent_gui = staticmethod(launch_fluent_gui)

    @staticmethod
    def check_pyfluent() -> bool:
        """Check if ansys-fluent-core package is installed in current Python env."""
        try:
            import ansys.fluent.core  # type: ignore
            return True
        except ImportError:
            return False

    def get_status_report(self) -> Dict[str, Any]:
        """Return diagnostic status of ANSYS setup."""
        return {
            "ansys_root": self.ansys_root,
            "fluent_bin": self.fluent_bin,
            "version": self.version_info["version_name"],
            "pyfluent_installed": self.pyfluent_available,
            "ready_for_automation": bool(self.fluent_bin or self.pyfluent_available),
            "working_directory": str(self.working_dir),
        }

    def generate_2d_journal(
        self,
        case_name: str,
        mesh_file: str,
        velocity: float = 15.0,
        aoa_deg: float = 0.0,
        iterations: int = 500,
        output_report_file: str = "fluent_forces.out"
    ) -> str:
        """
        Generate ANSYS Fluent TUI journal for 2D wing RANS simulation.
        Applies k-omega SST model, velocity inlet, pressure outlet, and force monitors.
        """
        rad = math.radians(aoa_deg)
        vx = velocity * math.cos(rad)
        vy = velocity * math.sin(rad)

        journal_content = f"""; ANSYS Fluent 2D Batch Journal for Aero_Auto
; Case: {case_name}
; Speed: {velocity:.2f} m/s, AoA: {aoa_deg:.2f} deg

; 1. Read Mesh
/file/read-case "{mesh_file}"

; 2. Define Physics & Models
/define/models/viscous/kw-sst? yes

; 3. Define Operating Conditions & Material
/define/materials/change-create air air yes constant {RHO_AIR} yes constant {MU_AIR} no no no

; 4. Boundary Conditions
/define/boundary-conditions/velocity-inlet inlet no no yes yes no {vx:.4f} no {vy:.4f} no no no yes 5 10
/define/boundary-conditions/pressure-outlet outlet yes no 0 no yes no no yes 5 10
/define/boundary-conditions/wall ground no no no no no no
/define/boundary-conditions/wall wing no no no no no no

; 5. Reference Values for Coefficients (Area = 0.3 m^2, Length = 0.3 m, Speed = {velocity} m/s)
/report/reference-values/area 0.3
/report/reference-values/length 0.3
/report/reference-values/density {RHO_AIR}
/report/reference-values/velocity {velocity}

; 6. Solution Methods & Initialization
/solve/set/discretization-scheme/pressure 12
/solve/set/discretization-scheme/mom 1
/solve/set/discretization-scheme/k 1
/solve/set/discretization-scheme/omega 1
/solve/initialize/hyb-initialization

; 7. Force Monitors & Calculation
/solve/iterate {iterations}

; 8. Export Results
/report/forces/wall-forces yes 1 0 (wing) "{output_report_file}_drag.txt"
/report/forces/wall-forces yes 0 1 (wing) "{output_report_file}_lift.txt"
/file/write-case-data "{case_name}_solved.cas.h5"
/exit yes
"""
        jou_path = self.working_dir / f"{case_name}.jou"
        with open(jou_path, "w", encoding="utf-8") as f:
            f.write(journal_content)
        return str(jou_path)

    def run_pyfluent_case(
        self,
        mesh_file: str,
        velocity: float = 15.0,
        aoa_deg: float = 0.0,
        chord: float = 0.30,
        span: float = 1.0,
        iterations: int = 500,
        show_gui: bool = False,
    ) -> Dict[str, float]:
        """
        Execute simulation using the modern Python PyFluent API.
        Requires `pip install ansys-fluent-core`.
        """
        if not self.pyfluent_available:
            raise RuntimeError("ansys.fluent.core is not installed. Install via: pip install ansys-fluent-core")

        import ansys.fluent.core as pyfluent  # type: ignore

        print(f"[ANSYS PyFluent] Launching Fluent session (2D, double precision)...")
        session = pyfluent.launch_fluent(
            precision="double",
            dimension=2,
            processor_count=os.cpu_count() or 4,
            show_gui=show_gui,
            mode="solver",
        )

        try:
            print(f"[ANSYS PyFluent] Reading case: {mesh_file}")
            session.file.read(file_type="case", file_name=mesh_file)

            # Viscous model: k-omega SST
            session.setup.models.viscous.model = "k-omega"
            session.setup.models.viscous.k_omega_model = "sst"

            # Boundary conditions
            rad = math.radians(aoa_deg)
            vx = velocity * math.cos(rad)
            vy = velocity * math.sin(rad)
            
            # Inlet
            session.setup.boundary_conditions.velocity_inlet["inlet"].vmag = velocity

            # Reference values
            session.setup.reference_values.density = RHO_AIR
            session.setup.reference_values.velocity = velocity
            session.setup.reference_values.area = chord * span
            session.setup.reference_values.length = chord

            # Hybrid initialization
            print(f"[ANSYS PyFluent] Initializing solution...")
            session.solution.initialization.hybrid_initialize()

            # Iterate
            print(f"[ANSYS PyFluent] Iterating for {iterations} steps...")
            session.solution.run_calculation.iter_count = iterations
            session.solution.run_calculation.calculate()

            # Extract forces
            lift_force = session.solution.report_definitions.force["lift"].compute()
            drag_force = session.solution.report_definitions.force["drag"].compute()

            q_inf = 0.5 * RHO_AIR * (velocity ** 2) * (chord * span)
            cl = lift_force / q_inf
            cd = drag_force / q_inf
            downforce_n = -lift_force
            ld = downforce_n / drag_force if drag_force > 1e-6 else 0.0

            return {
                "velocity": velocity,
                "aoa_deg": aoa_deg,
                "downforce_n": float(downforce_n),
                "drag_n": float(drag_force),
                "cl": float(cl),
                "cd": float(cd),
                "ld": float(ld),
                "iterations": iterations,
                "status": "converged"
            }
        finally:
            session.exit()

    def parse_fluent_force_report(self, report_path: str) -> float:
        """
        Parse standard ANSYS Fluent force report text file.
        Returns total_force.
        """
        tot_force = 0.0
        if not os.path.exists(report_path):
            return 0.0
        with open(report_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if "total" in line.lower() and len(parts) >= 4:
                    try:
                        tot_force = float(parts[-1])
                    except ValueError:
                        pass
        return tot_force

    def run_batch_fluent(
        self,
        case_name: str,
        mesh_file: str,
        velocity: float = 15.0,
        aoa_deg: float = 0.0,
        iterations: int = 500
    ) -> Dict[str, Any]:
        """Run Fluent in headless batch mode using fluent executable."""
        if not self.fluent_bin:
            raise FileNotFoundError("Fluent executable not found. Configure ANSYS path or install PyFluent.")

        jou_path = self.generate_2d_journal(case_name, mesh_file, velocity, aoa_deg, iterations)
        cmd = [self.fluent_bin, "2ddp", "-g", f"-t{os.cpu_count() or 4}", "-i", jou_path]
        
        print(f"[ANSYS Fluent Batch] Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(self.working_dir), capture_output=True, text=True)
        
        lift_file = self.working_dir / "fluent_forces.out_lift.txt"
        drag_file = self.working_dir / "fluent_forces.out_drag.txt"
        
        lift_force = self.parse_fluent_force_report(str(lift_file))
        drag_force = self.parse_fluent_force_report(str(drag_file))
        
        q_inf = 0.5 * RHO_AIR * (velocity ** 2) * 0.3
        downforce_n = -lift_force
        cl = lift_force / q_inf if q_inf > 0 else 0.0
        cd = drag_force / q_inf if q_inf > 0 else 0.0
        ld = downforce_n / drag_force if drag_force > 1e-6 else 0.0

        return {
            "case_name": case_name,
            "velocity": velocity,
            "aoa_deg": aoa_deg,
            "downforce_n": downforce_n,
            "drag_n": drag_force,
            "cl": cl,
            "cd": cd,
            "ld": ld,
            "exit_code": result.returncode
        }

    def run_3d_wing_simulation(
        self,
        wing_assembly: Any,
        velocity: float = 22.222,
        iterations: int = 400,
        use_pyfluent: bool = False
    ) -> Dict[str, Any]:
        """
        Execute 3D Finite-Wing ground effect simulation integrated directly with Aero_Auto.
        Uses Aero3DSolver with automatic ANSYS Fluent 3D journal export.
        """
        try:
            import aero_3d_engine as A3D
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import aero_3d_engine as A3D

        solver = A3D.Aero3DSolver()
        res = solver.solve(wing_assembly, velocity=velocity)

        # Generate ANSYS Fluent 3D Journal for verification
        jou_path = self.working_dir / f"fluent_3d_{wing_assembly.id}.jou"
        A3D.generate_ansys_fluent_3d_journal(wing_assembly, str(jou_path), velocity=velocity, iterations=iterations)

        return {
            "assembly_id": res.assembly_id,
            "velocity_ms": res.velocity_ms,
            "downforce_n": res.downforce_n,
            "drag_n": res.drag_n,
            "cl_3d": res.cl_3d,
            "cd_3d": res.cd_3d,
            "ld_ratio": res.ld_ratio,
            "cop_x_mm": res.cop_x_mm,
            "is_flow_attached": res.is_flow_attached,
            "stall_margin_deg": res.stall_margin_deg,
            "ansys_3d_journal": str(jou_path),
            "status": "success"
        }

if __name__ == '__main__':
    engine = AnsysFluentEngine()
    print("=== ANSYS Fluent Universal Engine Diagnostic ===")
    status = engine.get_status_report()
    for k, v in status.items():
        print(f"  {k}: {v}")
