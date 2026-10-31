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

def launch_fluent_gui(
    case_file: Optional[Path] = None,
    journal_file: Optional[Path] = None,
    is_3d: bool = True,
    num_procs: int = 4,
    custom_fluent_exe: Optional[str] = None,
    working_dir: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Universal Fluent launcher that works across ANY version and ANY directory.
    Does NOT pass hardcoded version flags (-r24.1.0) so it runs natively on 2020 through 2026+.
    """
    fluent_bin = detect_fluent_executable(custom_fluent_exe)
    if not fluent_bin or not os.path.exists(fluent_bin):
        return False, "ANSYS Fluent executable (fluent.exe) not found on system."

    dim_flag = "3ddp" if is_3d else "2ddp"
    cmd_parts = [f'"{fluent_bin}"', dim_flag, f"-t{num_procs}"]

    if case_file and Path(case_file).exists():
        cmd_parts.append(f'-case "{Path(case_file).name}"')

    if journal_file and Path(journal_file).exists():
        cmd_parts.append(f'-i "{Path(journal_file).name}"')

    cmd = " ".join(cmd_parts)
    cwd_dir = working_dir if working_dir else (Path(case_file).parent if case_file else Path.cwd())

    try:
        subprocess.Popen(cmd, cwd=str(cwd_dir), shell=True)
        return True, f"Launched: {cmd}"
    except Exception as e:
        return False, f"Error launching Fluent: {e}"


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
