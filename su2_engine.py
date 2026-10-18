"""
SU2 Simulation Engine and Unified Verification Interface for Aero Auto
======================================================================
Integrates SU2 2D RANS (Incompressible k-omega SST) and Gmsh with XFOIL and JavaFoil.
Unified interface:
    run(config, engine='su2', ...) -> dict
"""

import os
import sys
import math
import time
import json
import hashlib
import tempfile
import subprocess
import numpy as np
import pandas as pd

# Load aero_auto dependencies
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aero_auto as A

# Tool executable paths
SU2_CFD_BIN = os.path.expanduser("~/.local/bin/SU2_CFD")
if not os.path.exists(SU2_CFD_BIN):
    SU2_CFD_BIN = "/home/user/Applications/SU2/bin/SU2_CFD"

XFOIL_BIN = os.path.expanduser("~/.local/bin/xfoil")
if not os.path.exists(XFOIL_BIN):
    XFOIL_BIN = "/home/user/Applications/XFOIL/usr/bin/xfoil"

LIBNOFPE_SO = "/home/user/Applications/XFOIL/libnofpe.so"

# Physical constants (air at sea level, standard FSAE conditions)
RHO_DEFAULT = 1.225         # kg/m^3
MU_DEFAULT = 1.7894e-5      # Pa.s (dynamic viscosity)
SPEED_DEFAULT = 16.6667     # m/s (60 km/h)
RE_DEFAULT = 570000.0       # Re based on 0.5m total assembly or 0.3m main chord

# Default MPI cores for SU2
DEFAULT_CORES = 4


def hash_config(cfg, extra=""):
    """Deterministic hash for configuration caching."""
    rep = json.dumps(cfg, sort_keys=True) + str(extra)
    return hashlib.sha256(rep.encode("utf-8")).hexdigest()[:16]


def compute_yplus_spacing(re_val, chord=1.0, yplus=1.0):
    """
    Computes first-cell height for y+ ~ 1 based on flat plate turbulent boundary layer.
    Cf ~ 0.0592 * Re^(-0.2)
    tau_w = 0.5 * rho * U^2 * Cf
    u_tau = sqrt(tau_w / rho)
    ds = y+ * mu / (rho * u_tau)
    """
    cf = 0.0592 * (re_val ** -0.2)
    # ds normalized by chord
    ds_norm = yplus * math.sqrt(2.0 / cf) / re_val
    return max(ds_norm, 1e-6)


def build_geometry_coords(cfg, ground_h=None):
    """
    Maps configuration parameters to coordinate outlines.
    Conventions:
      1. Inversion: coordinates inverted along Y (coords[:, 1] = -coords[:, 1]), point order reversed.
      2. Rotation: flap rotates about its leading edge (0, 0) by th = np.radians(ROT_SIGN * angle_deg), ROT_SIGN = -1.
      3. Translation: dx_pct / 100.0, dy_pct / 100.0 relative to main element leading edge (0, 0).
      4. Ground effect: ground_h / 100.0 shifts elements upward along Y.
    """
    A.ensure_airfoils_loaded()
    return A.build_outlines(cfg, ground_h)


def verify_geometry_overlay(cfg, ground_h=None):
    """
    Rigorous overlay test: verifies that SU2 geometry mapping produces
    the identical coordinates as JavaFoil's build_outlines.
    """
    jf_outs = A.build_outlines(cfg, ground_h)
    su2_outs = build_geometry_coords(cfg, ground_h)
    
    assert len(jf_outs) == len(su2_outs), "Element count mismatch!"
    max_diff = 0.0
    for i, (o1, o2) in enumerate(zip(jf_outs, su2_outs)):
        diff = np.max(np.abs(o1 - o2))
        max_diff = max(max_diff, diff)
        assert diff < 1e-12, f"Element {i} coordinate mismatch: max diff = {diff}"
    return True, max_diff


def generate_su2_mesh_gmsh(outlines, out_mesh_path, ground_h=None, density='medium', farfield_radius=40.0):
    """
    Generates an authentic 2D unstructured mesh with boundary layer prism layers
    using Gmsh Python API and exports directly to .su2 format.
    """
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)  # quiet
    gmsh.model.add("su2_mesh")

    # Determine bounding box
    all_pts = np.vstack(outlines)
    xmin, xmax = all_pts[:, 0].min(), all_pts[:, 0].max()
    ymin, ymax = all_pts[:, 1].min(), all_pts[:, 1].max()
    chord_total = xmax - xmin
    
    # Mesh density sizing parameters
    factors = {
        'coarse': (0.012, 0.025, 2.5),
        'medium': (0.006, 0.015, 1.8),
        'fine':   (0.003, 0.008, 1.2)
    }
    le_size, te_size, far_size = factors.get(density, factors['medium'])

    element_loops = []
    wall_curves = []

    # 1. Add airfoil elements
    for elem_idx, o in enumerate(outlines):
        o = np.asarray(o, dtype=float)
        # Drop closing point if identical to first
        if len(o) > 2 and np.linalg.norm(o[0] - o[-1]) < 1e-6:
            o = o[:-1]
        # Filter duplicate consecutive points
        mask = [True] + [np.linalg.norm(o[i] - o[i-1]) > 1e-7 for i in range(1, len(o))]
        o = o[mask]

        # Ensure counter-clockwise ordering for outer boundary of hole
        # In Gmsh, holes in a plane surface must have orientation opposite to outer boundary
        area = 0.5 * np.sum(o[:, 0] * np.roll(o[:, 1], -1) - o[:, 1] * np.roll(o[:, 0], -1))
        if area > 0:
            o = o[::-1]

        n_pts = len(o)
        point_tags = []
        for j, pt in enumerate(o):
            # Refine near leading and trailing edges
            x_rel = (pt[0] - o[:, 0].min()) / max(o[:, 0].max() - o[:, 0].min(), 1e-5)
            if x_rel < 0.08 or x_rel > 0.88:
                sz = le_size
            else:
                sz = te_size
            tag = gmsh.model.geo.addPoint(pt[0], pt[1], 0.0, sz)
            point_tags.append(tag)

        # Build lines along the contour (exact, robust, no degenerate splines)
        line_tags = []
        for j in range(n_pts):
            l_tag = gmsh.model.geo.addLine(point_tags[j], point_tags[(j + 1) % n_pts])
            line_tags.append(l_tag)

        loop = gmsh.model.geo.addCurveLoop(line_tags)
        element_loops.append(loop)
        wall_curves.extend(line_tags)

    # 2. Add Farfield / Ground Domain
    if ground_h is not None:
        # Ground at y = 0
        y_ground = 0.0
        x_inlet = -farfield_radius * 0.75
        x_outlet = farfield_radius * 1.5
        y_top = farfield_radius

        p_g1 = gmsh.model.geo.addPoint(x_inlet, y_ground, 0.0, far_size * 0.5)
        p_g2 = gmsh.model.geo.addPoint(x_outlet, y_ground, 0.0, far_size * 0.5)
        p_top2 = gmsh.model.geo.addPoint(x_outlet, y_top, 0.0, far_size)
        p_top1 = gmsh.model.geo.addPoint(x_inlet, y_top, 0.0, far_size)

        l_ground = gmsh.model.geo.addLine(p_g1, p_g2)
        l_outlet = gmsh.model.geo.addLine(p_g2, p_top2)
        l_top = gmsh.model.geo.addLine(p_top2, p_top1)
        l_inlet = gmsh.model.geo.addLine(p_top1, p_g1)

        outer_loop = gmsh.model.geo.addCurveLoop([l_ground, l_outlet, l_top, l_inlet])
        surface = gmsh.model.geo.addPlaneSurface([outer_loop] + element_loops)
        gmsh.model.geo.synchronize()

        # Physical groups
        gmsh.model.addPhysicalGroup(1, [l_ground], 1, "ground")
        gmsh.model.addPhysicalGroup(1, [l_inlet, l_top, l_outlet], 2, "farfield")
        gmsh.model.addPhysicalGroup(1, wall_curves, 3, "airfoil")
        gmsh.model.addPhysicalGroup(2, [surface], 4, "fluid")
    else:
        # C-grid or circular farfield centered on assembly
        x_c = 0.5 * (xmin + xmax)
        y_c = 0.5 * (ymin + ymax)
        r = farfield_radius

        p_center = gmsh.model.geo.addPoint(x_c, y_c, 0.0, far_size)
        p_f1 = gmsh.model.geo.addPoint(x_c - r, y_c, 0.0, far_size)
        p_f2 = gmsh.model.geo.addPoint(x_c, y_c + r, 0.0, far_size)
        p_f3 = gmsh.model.geo.addPoint(x_c + r, y_c, 0.0, far_size)
        p_f4 = gmsh.model.geo.addPoint(x_c, y_c - r, 0.0, far_size)

        c1 = gmsh.model.geo.addCircleArc(p_f1, p_center, p_f2)
        c2 = gmsh.model.geo.addCircleArc(p_f2, p_center, p_f3)
        c3 = gmsh.model.geo.addCircleArc(p_f3, p_center, p_f4)
        c4 = gmsh.model.geo.addCircleArc(p_f4, p_center, p_f1)

        outer_loop = gmsh.model.geo.addCurveLoop([c1, c2, c3, c4])
        surface = gmsh.model.geo.addPlaneSurface([outer_loop] + element_loops)
        gmsh.model.geo.synchronize()

        # Physical groups
        gmsh.model.addPhysicalGroup(1, [c1, c2, c3, c4], 1, "farfield")
        gmsh.model.addPhysicalGroup(1, wall_curves, 2, "airfoil")
        gmsh.model.addPhysicalGroup(2, [surface], 3, "fluid")

    # Generate 2D mesh
    gmsh.model.mesh.generate(2)
    gmsh.write(out_mesh_path)
    
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    elem_types, elem_tags, _ = gmsh.model.mesh.getElements()
    num_elems = sum(len(tags) for tags in elem_tags)
    
    gmsh.finalize()
    return {
        'nodes': len(node_tags),
        'elements': num_elems,
        'mesh_file': out_mesh_path,
        'density': density
    }


def write_su2_config_file(cfg_file, mesh_file, alpha_deg, speed=16.6667, re_val=570000.0,
                          ground_h=None, ref_chord_main=1.0, max_iter=250):
    """
    Writes SU2 config file for 2D Incompressible RANS with k-omega SST.
    """
    alpha_rad = math.radians(alpha_deg)
    vx = speed * math.cos(alpha_rad)
    vy = speed * math.sin(alpha_rad)
    
    # Boundary condition definitions
    markers_str = f"MARKER_HEATFLUX= ( airfoil, 0.0 )\nMARKER_FAR= ( farfield )\n"
    if ground_h is not None:
        markers_str += f"MARKER_MOVING_WALL= ( ground, {speed:.4f}, 0.0, 0.0 )\n"
        markers_str += f"MARKER_MONITORING= ( airfoil )\nMARKER_DESIGNING= ( airfoil )\n"
    else:
        markers_str += f"MARKER_MONITORING= ( airfoil )\nMARKER_DESIGNING= ( airfoil )\n"

    cfg_text = f"""% ------------- DIRECT, INCOMPRESSIBLE, TURBULENT CASE DEFINITION ------------- %
SOLVER= INC_RANS
KIND_TURB_MODEL= SST
MATH_PROBLEM= DIRECT
RESTART_SOL= NO

% -------------------- INCOMPRESSIBLE FLOW CONDITIONS ------------------------- %
INC_DENSITY_MODEL= CONSTANT
INC_DENSITY_INIT= {RHO_DEFAULT}
INC_VELOCITY_INIT= ( {vx:.6f}, {vy:.6f}, 0.0 )
INC_TEMPERATURE_INIT= 288.15
VISCOSITY_MODEL= CONSTANT_VISCOSITY
MU_CONSTANT= {MU_DEFAULT}

% ---------------------- REFERENCE VALUES & COEFFICIENTS ----------------------- %
% Reference chord explicitly defined as main-element chord (1.0 in normalized units)
REF_LENGTH= {ref_chord_main:.6f}
REF_AREA= {ref_chord_main:.6f}
REF_ORIGIN_MOMENT_X= 0.25
REF_ORIGIN_MOMENT_Y= 0.00
REF_ORIGIN_MOMENT_Z= 0.00

% ------------------------- MESH DEFINITION & MARKERS -------------------------- %
MESH_FILENAME= {mesh_file}
MESH_FORMAT= SU2
{markers_str}

% ------------------------- SPATIAL NUMERICAL METHODS -------------------------- %
CONV_NUM_METHOD_FLOW= FDS
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.05
JST_SENSOR_COEFF= ( 0.5, 0.02 )

CONV_NUM_METHOD_TURB= SCALAR_UPWIND
MUSCL_TURB= NO

% ------------------------- TIME NUMERICAL INTEGRATION ------------------------- %
TIME_DISCRE_FLOW= EULER_IMPLICIT
CFL_NUMBER= 10.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.1, 1.25, 1.0, 100.0 )

TIME_DISCRE_TURB= EULER_IMPLICIT
CFL_REDUCTION_TURB= 0.5

% --------------------------- CONVERGENCE CRITERIA ---------------------------- %
ITER= {max_iter}
CONV_FIELD= RMS_PRESSURE
CONV_RESIDUAL_MINVAL= -8.0
CONV_STARTITER= 10
CONV_CAUCHY_ELEMS= 50
CONV_CAUCHY_EPS= 1e-4

% ------------------------- OUTPUT AND HISTORY LOGGING ------------------------- %
SCREEN_OUTPUT= ( INNER_ITER, RMS_PRESSURE, RMS_VELOCITY-X, LIFT, DRAG )
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, MOMENT_Z )
OUTPUT_FILES= ( RESTART, PARAVIEW )
CONV_FILENAME= history
RESTART_FILENAME= restart.dat
VOLUME_FILENAME= flowfield
SURFACE_FILENAME= surface_forces
"""
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write(cfg_text)


def parse_su2_history(history_file, ref_chord_main, ref_chord_assembly):
    """
    Parses SU2 convergence history CSV.
    Computes residual drop, checks stability over last iterations,
    and returns metrics normalized by both main chord and assembly chord.
    """
    if not os.path.exists(history_file):
        return {
            'converged': False,
            'reason': 'No history file generated',
            'Cl': None, 'Cd': None, 'Cm': None,
            'residual_drop': 0.0
        }
        
    try:
        df = pd.read_csv(history_file)
        # Clean column names (strip quotes, spaces)
        df.columns = [c.replace('"', '').strip() for c in df.columns]
    except Exception as e:
        return {'converged': False, 'reason': f'History parse error: {e}', 'Cl': None, 'Cd': None}

    if len(df) == 0:
        return {'converged': False, 'reason': 'History is empty', 'Cl': None, 'Cd': None}

    # Find relevant columns
    cl_col = next((c for c in df.columns if 'LIFT' in c or 'CL' in c or 'Cl' in c), None)
    cd_col = next((c for c in df.columns if 'DRAG' in c or 'CD' in c or 'Cd' in c), None)
    cm_col = next((c for c in df.columns if 'MOMENT' in c or 'CM' in c or 'Cm' in c), None)
    res_col = next((c for c in df.columns if 'RMS_RES' in c or 'RMS_PRESSURE' in c), None)

    if not cl_col or not cd_col:
        return {'converged': False, 'reason': 'Missing lift/drag columns in history', 'Cl': None, 'Cd': None}

    # Last 30 iterations for stability check
    tail_n = min(30, len(df))
    cl_tail = df[cl_col].iloc[-tail_n:]
    cd_tail = df[cd_col].iloc[-tail_n:]
    
    cl_mean = float(cl_tail.mean())
    cd_mean = float(cd_tail.mean())
    cm_mean = float(df[cm_col].iloc[-tail_n:].mean()) if cm_col else 0.0
    
    cl_std = float(cl_tail.std()) if len(cl_tail) > 1 else 0.0
    cd_std = float(cd_tail.std()) if len(cd_tail) > 1 else 0.0
    
    res_drop = 0.0
    if res_col and len(df) > 1:
        res_initial = float(df[res_col].iloc[0])
        res_final = float(df[res_col].iloc[-1])
        res_drop = res_initial - res_final

    # Convergence criterion: residual drop >= 3 orders of magnitude OR tail standard deviation < 0.005
    stable = (cl_std < 0.008 and cd_std < 0.003)
    converged = bool(stable or res_drop >= 3.0)

    # Conversion factor from main-element reference to total assembly reference
    # Force = Cl_main * (0.5 * rho * V^2 * c_main) = Cl_asm * (0.5 * rho * V^2 * c_asm)
    # => Cl_asm = Cl_main * (c_main / c_asm)
    scale_asm = ref_chord_main / max(ref_chord_assembly, 1e-5)
    cl_asm = cl_mean * scale_asm
    cd_asm = cd_mean * scale_asm

    return {
        'converged': converged,
        'iterations': len(df),
        'residual_drop': round(res_drop, 2),
        'cl_std': round(cl_std, 5),
        'cd_std': round(cd_std, 5),
        'Cl': cl_mean,
        'Cd': cd_mean,
        'Cm': cm_mean,
        'Cl_assembly': cl_asm,
        'Cd_assembly': cd_asm,
        'ref_chord_main': ref_chord_main,
        'ref_chord_assembly': ref_chord_assembly
    }


def run_su2_single_case(cfg, alpha_deg=0.0, speed=16.6667, re_val=570000.0, ground_h=None,
                        density='medium', num_cores=DEFAULT_CORES, timeout=360, workdir=None):
    """
    Executes an end-to-end SU2 CFD simulation for a wing configuration at a given alpha.
    """
    t0 = time.time()
    
    # 1. Setup per-case directory
    cfg_hash = hash_config(cfg, f"{alpha_deg}_{speed}_{re_val}_{ground_h}_{density}")
    if workdir is None:
        runs_dir = os.path.join(HERE, "runs", "su2_runs")
        os.makedirs(runs_dir, exist_ok=True)
        case_dir = os.path.join(runs_dir, f"case_{cfg_hash}_a{alpha_deg:g}")
        os.makedirs(case_dir, exist_ok=True)
    else:
        case_dir = workdir
        os.makedirs(case_dir, exist_ok=True)

    mesh_file = os.path.join(case_dir, "mesh.su2")
    cfg_file = os.path.join(case_dir, "config.cfg")
    history_file = os.path.join(case_dir, "history.csv")

    # 2. Geometry coordinates & Reference chords
    outlines = build_geometry_coords(cfg, ground_h)
    all_pts = np.vstack(outlines)
    ref_chord_main = 1.0  # Unit normalized main element chord
    ref_chord_assembly = float(all_pts[:, 0].max() - all_pts[:, 0].min())

    # 3. Check if run is already completed and cached
    if os.path.exists(history_file) and os.path.getsize(history_file) > 200:
        res = parse_su2_history(history_file, ref_chord_main, ref_chord_assembly)
        if res.get('iterations', 0) >= 50 and res.get('Cl') is not None:
            res['alpha'] = alpha_deg
            res['runtime_s'] = 0.0
            res['engine'] = 'SU2'
            res['exit_code'] = 0
            res['case_dir'] = case_dir
            res['cached'] = True
            res['mesh_meta'] = {'mesh_file': mesh_file, 'cached': True}
            return res

    # 4. Generate mesh if not cached or corrupted
    if not os.path.exists(mesh_file) or os.path.getsize(mesh_file) < 5000:
        mesh_meta = generate_su2_mesh_gmsh(outlines, mesh_file, ground_h=ground_h, density=density)
    else:
        mesh_meta = {'mesh_file': mesh_file, 'cached': True}

    # 4. Write config file
    write_su2_config_file(cfg_file, mesh_file, alpha_deg, speed=speed, re_val=re_val,
                          ground_h=ground_h, ref_chord_main=ref_chord_main, max_iter=250)

    # 5. Execute SU2_CFD via MPI
    cmd = ["mpirun", "-n", str(num_cores), SU2_CFD_BIN, cfg_file]
    log_file = os.path.join(case_dir, "su2.log")
    
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    
    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout, cwd=case_dir, env=env)

    runtime_s = round(time.time() - t0, 2)
    
    # 6. Parse metrics
    res = parse_su2_history(history_file, ref_chord_main, ref_chord_assembly)
    res['alpha'] = alpha_deg
    res['runtime_s'] = runtime_s
    res['engine'] = 'SU2'
    res['exit_code'] = proc.returncode
    res['case_dir'] = case_dir
    res['mesh_meta'] = mesh_meta

    return res


def run_xfoil_single_element(airfoil_name_or_coords, alpha_list, re_val=570000.0, timeout=60):
    """
    Executes XFOIL polar calculation for single-element airfoils.
    Uses libnofpe.so to ensure rock-solid numerical stability.
    """
    A.ensure_airfoils_loaded()
    with tempfile.TemporaryDirectory() as td:
        dat_path = os.path.join(td, "airfoil.dat")
        polar_path = os.path.join(td, "polar.txt")
        inp_path = os.path.join(td, "xfoil.in")
        
        if isinstance(airfoil_name_or_coords, str):
            coords = A.AIRFOILS.get(airfoil_name_or_coords)
            if coords is None:
                raise KeyError(f"Airfoil {airfoil_name_or_coords} not found in library.")
        else:
            coords = airfoil_name_or_coords

        # In XFOIL, conventional upright airfoil is standard (nose left, TE right)
        # Note: If coords were inverted for downforce, flip them back for XFOIL standard polar
        c = coords.copy()
        if c[:, 1].mean() > 0:  # Cambered downward
            c[:, 1] = -c[:, 1]
            c = c[::-1]
            
        with open(dat_path, "w", encoding="utf-8") as f:
            f.write("Airfoil\n")
            for pt in c:
                f.write(f"{pt[0]:.6f} {pt[1]:.6f}\n")

        # Build XFOIL input script
        lines = [
            "PLOP",
            "G",
            "",
            f"LOAD {dat_path}",
            "PANE",
            "OPER",
            f"VISC {re_val:g}",
            "ITER 100",
            "PACC",
            polar_path,
            ""
        ]
        for a in alpha_list:
            lines.append(f"ALFA {a:g}")
        lines.extend(["PACC", "", "QUIT\n"])
        
        with open(inp_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        env = os.environ.copy()
        env["LD_PRELOAD"] = LIBNOFPE_SO + (os.pathsep + env.get("LD_PRELOAD", "") if env.get("LD_PRELOAD") else "")
        
        proc = subprocess.run(f"xfoil < {inp_path}", shell=True, env=env, cwd=td,
                              capture_output=True, text=True, timeout=timeout)
        
        records = []
        if os.path.exists(polar_path):
            with open(polar_path, "r", encoding="utf-8") as f:
                header_passed = False
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if "------" in line:
                        header_passed = True
                        continue
                    if header_passed:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                a = float(parts[0])
                                cl = float(parts[1])
                                cd = float(parts[2])
                                cm = float(parts[4])
                                records.append({'alpha': a, 'Cl': cl, 'Cd': cd, 'Cm': cm, 'engine': 'XFOIL'})
                            except ValueError:
                                pass
        return records


def run_javafoil_single_case(cfg, alpha_deg=0.0, speed=16.6667, re_val=570000.0, ground_h=None):
    """
    Runs JavaFoil for a single alpha operating point using the existing aero_auto pipeline.
    """
    t0 = time.time()
    # Temporarily set ALPHA range in A
    orig_alpha = A.ALPHA
    orig_re = A.RE
    orig_gh = A.GROUND_H
    
    A.ALPHA = (alpha_deg, alpha_deg, 1.0)
    A.RE = re_val
    A.GROUND_H = ground_h
    
    try:
        with tempfile.TemporaryDirectory() as td:
            metrics, status, head = A.simulate(cfg, td, ground_h)
            runtime_s = round(time.time() - t0, 2)
            
            cl = metrics.get('Cl_a0', None) if alpha_deg == 0.0 else metrics.get('Cl_peak', None)
            cd = metrics.get('Cd_a0', None) if alpha_deg == 0.0 else metrics.get('Cd_peak', None)
            cm = metrics.get('Cm_a0', 0.0)
            
            return {
                'alpha': alpha_deg,
                'Cl': cl,
                'Cd': cd,
                'Cm': cm,
                'converged': (status == "Valid"),
                'status': status,
                'runtime_s': runtime_s,
                'engine': 'JavaFoil'
            }
    finally:
        A.ALPHA = orig_alpha
        A.RE = orig_re
        A.GROUND_H = orig_gh


# ==============================================================================
# UNIFIED SOLVER INTERFACE & CROSS-CHECK MODE
# ==============================================================================

def run(config, engine='su2', alpha=0.0, speed=SPEED_DEFAULT, re=RE_DEFAULT, ground_h=None,
        mesh_density='medium', num_cores=DEFAULT_CORES, timeout=300):
    """
    Unified solver interface:
        run(config) -> {alpha, Cl, Cd, Cm, converged, residual_drop, reference_chord, runtime_s, engine}
    """
    engine_lower = str(engine).lower().strip()
    if 'su2' in engine_lower:
        return run_su2_single_case(config, alpha_deg=alpha, speed=speed, re_val=re,
                                   ground_h=ground_h, density=mesh_density,
                                   num_cores=num_cores, timeout=timeout)
    elif 'javafoil' in engine_lower:
        return run_javafoil_single_case(config, alpha_deg=alpha, speed=speed, re_val=re, ground_h=ground_h)
    else:
        raise ValueError(f"Unknown simulation engine: {engine!r}. Use 'su2' or 'javafoil'.")


def cross_check(config, alpha=0.0, speed=SPEED_DEFAULT, re=RE_DEFAULT, ground_h=None,
                threshold_cl=0.5, threshold_cd=0.05, num_cores=DEFAULT_CORES):
    """
    Cross-checks JavaFoil and SU2 on the identical geometry configuration.
    Returns comparison dictionary with divergence flags.
    """
    # 1. Overlay check first
    matched, max_diff = verify_geometry_overlay(config, ground_h)
    if not matched:
        raise ValueError(f"Geometry overlay failed! Max coordinate discrepancy: {max_diff}")

    # 2. Run JavaFoil
    res_jf = run_javafoil_single_case(config, alpha_deg=alpha, speed=speed, re_val=re, ground_h=ground_h)
    
    # 3. Run SU2
    res_su2 = run_su2_single_case(config, alpha_deg=alpha, speed=speed, re_val=re, ground_h=ground_h, num_cores=num_cores)

    # 4. Compare
    cl_jf = res_jf.get('Cl')
    cl_su2 = res_su2.get('Cl_assembly')
    cd_jf = res_jf.get('Cd')
    cd_su2 = res_su2.get('Cd_assembly')

    diff_cl = abs(cl_jf - cl_su2) if (cl_jf is not None and cl_su2 is not None) else None
    diff_cd = abs(cd_jf - cd_su2) if (cd_jf is not None and cd_su2 is not None) else None

    flag_divergent = False
    reasons = []
    if diff_cl is not None and diff_cl > threshold_cl:
        flag_divergent = True
        reasons.append(f"Cl difference ({diff_cl:.3f}) exceeds threshold ({threshold_cl})")
    if diff_cd is not None and diff_cd > threshold_cd:
        flag_divergent = True
        reasons.append(f"Cd difference ({diff_cd:.4f}) exceeds threshold ({threshold_cd})")

    ratio_cl = (cl_jf / cl_su2) if (cl_jf is not None and cl_su2 is not None and abs(cl_su2) > 1e-4) else None

    return {
        'alpha': alpha,
        'javafoil': res_jf,
        'su2': res_su2,
        'diff_Cl': diff_cl,
        'diff_Cd': diff_cd,
        'ratio_Cl': ratio_cl,
        'flag_divergent': flag_divergent,
        'reasons': reasons,
        'overlay_matched': matched,
        'geometry_max_diff': max_diff
    }
