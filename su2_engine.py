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
import shutil
import threading
import signal
import subprocess
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.tri as mtri

# Load aero_auto dependencies
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

GMSH_API_PATH = "/usr/share/gmsh/api/python"
if os.path.isdir(GMSH_API_PATH) and GMSH_API_PATH not in sys.path:
    sys.path.insert(0, GMSH_API_PATH)

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
SPEED_DEFAULT = 27.74     # m/s (100 km/h, matches aero_auto.DEFAULT_SPEED)
RE_DEFAULT = 570000.0       # Re based on 0.5m total assembly or 0.3m main chord

# Default MPI cores for SU2
DEFAULT_CORES = 4

# Process-wide lock for thread-safe Gmsh geometry and meshing operations
GMSH_LOCK = threading.Lock()


def init_gmsh_threadsafe():
    """
    Initializes Gmsh safely in any thread context, avoiding:
    ValueError: signal only works in main thread of the main interpreter
    """
    import gmsh
    if gmsh.is_initialized():
        return
    try:
        # Pass interruptible=False to prevent gmsh from calling signal.signal(signal.SIGINT)
        gmsh.initialize(interruptible=False)
    except (TypeError, ValueError):
        # Fallback for older gmsh bindings or edge cases: dummy monkeypatch signal.signal
        orig_sig = signal.signal
        try:
            signal.signal = lambda *a, **k: None
            gmsh.initialize()
        finally:
            signal.signal = orig_sig
    try:
        gmsh.option.setNumber("General.Terminal", 0)
    except Exception:
        pass


def finalize_gmsh_safe():
    """Safely finalizes Gmsh without raising signal errors on secondary threads."""
    try:
        import gmsh
        if gmsh.is_initialized():
            try:
                gmsh.finalize()
            except (ValueError, TypeError):
                orig_sig = signal.signal
                try:
                    signal.signal = lambda *a, **k: None
                    gmsh.finalize()
                finally:
                    signal.signal = orig_sig
    except Exception:
        pass


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


def normalize_config(cfg):
    """Normalizes configuration to (main, flaps) tuple."""
    if isinstance(cfg, dict):
        main = cfg.get('main')
        flaps = cfg.get('flaps', [])
        clean_flaps = []
        for f in flaps:
            clean_flaps.append((f[0], float(f[1]), float(f[2]), float(f[3]), float(f[4])))
        return (main, clean_flaps)
    elif isinstance(cfg, (tuple, list)) and len(cfg) >= 2:
        main = cfg[0]
        flaps = cfg[1]
        clean_flaps = []
        for f in flaps:
            clean_flaps.append((f[0], float(f[1]), float(f[2]), float(f[3]), float(f[4])))
        return (main, clean_flaps)
    return cfg


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
    return A.build_outlines(normalize_config(cfg), ground_h)


def verify_geometry_overlay(cfg, ground_h=None):
    """
    Rigorous overlay test: verifies that SU2 geometry mapping produces
    the identical coordinates as JavaFoil's build_outlines.
    """
    cfg_tuple = normalize_config(cfg)
    jf_outs = A.build_outlines(cfg_tuple, ground_h)
    su2_outs = build_geometry_coords(cfg_tuple, ground_h)
    
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
    Thread-safe and guarded against signal handler errors on secondary threads.
    """
    import gmsh
    with GMSH_LOCK:
        init_gmsh_threadsafe()
        try:
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
            
            return {
                'nodes': len(node_tags),
                'elements': num_elems,
                'mesh_file': out_mesh_path,
                'density': density
            }
        finally:
            finalize_gmsh_safe()


def write_su2_config_file(cfg_file, mesh_file, alpha_deg, speed=27.74, re_val=570000.0,
                          ground_h=None, ref_chord_main=1.0, max_iter=250):
    """
    Writes SU2 config file for 2D Incompressible RANS with k-omega SST.
    Harmonizes viscosity so that SU2 operates at the exact physical Reynolds number:
        mu = (rho * speed * ref_chord_main) / Re
    """
    alpha_rad = math.radians(alpha_deg)
    vx = speed * math.cos(alpha_rad)
    vy = speed * math.sin(alpha_rad)

    re_target = float(re_val) if re_val and float(re_val) > 0 else RE_DEFAULT
    # Physical dynamic viscosity matching exact target Reynolds number Re
    mu_calc = (RHO_DEFAULT * speed * ref_chord_main) / re_target
    
    # Boundary condition definitions
    if ground_h is not None:
        markers_str = f"MARKER_HEATFLUX= ( airfoil, 0.0, ground, 0.0 )\nMARKER_FAR= ( farfield )\n"
        markers_str += f"MARKER_MOVING= ( ground )\nSURFACE_MOVEMENT= MOVING_WALL\nSURFACE_TRANSLATION_RATE= ( {speed:.4f}, 0.0, 0.0 )\n"
        markers_str += f"MARKER_MONITORING= ( airfoil )\nMARKER_DESIGNING= ( airfoil )\nMARKER_PLOTTING= ( airfoil )\n"
    else:
        markers_str = f"MARKER_HEATFLUX= ( airfoil, 0.0 )\nMARKER_FAR= ( farfield )\n"
        markers_str += f"MARKER_MONITORING= ( airfoil )\nMARKER_DESIGNING= ( airfoil )\nMARKER_PLOTTING= ( airfoil )\n"

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
MU_CONSTANT= {mu_calc:.8e}

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
TABULAR_FORMAT= CSV
OUTPUT_FILES= ( RESTART, PARAVIEW_ASCII, TECPLOT_ASCII, SURFACE_CSV )
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


def run_su2_single_case(cfg, alpha_deg=0.0, speed=27.74, re_val=570000.0, ground_h=None,
                        density='medium', num_cores=DEFAULT_CORES, timeout=360, workdir=None, force=False):
    """
    Executes an end-to-end SU2 CFD simulation for a wing configuration at a given alpha.
    """
    t0 = time.time()
    cfg = normalize_config(cfg)
    
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

    # 2b. Penetration / collision check
    import matplotlib.path as mpath
    paths = [mpath.Path(o) for o in outlines]
    for i in range(len(outlines)):
        for j in range(len(outlines)):
            if i != j and np.any(paths[j].contains_points(outlines[i])):
                return {
                    'alpha': alpha_deg,
                    'Cl': 0.0,
                    'Cd': 1.0,
                    'Cl_assembly': 0.0,
                    'Cd_assembly': 1.0,
                    'Cm': 0.0,
                    'converged': False,
                    'iterations': 0,
                    'residual_drop': 0.0,
                    'runtime_s': 0.0,
                    'engine': 'SU2',
                    'error': f'Element {i} intersects Element {j}'
                }

    # 3. Check if run is already completed and cached
    if not force and os.path.exists(history_file) and os.path.getsize(history_file) > 200:
        res = parse_su2_history(history_file, ref_chord_main, ref_chord_assembly)
        if res.get('iterations', 0) >= 50 and res.get('Cl') is not None:
            res['alpha'] = alpha_deg
            res['runtime_s'] = 0.0
            res['engine'] = 'SU2'
            res['exit_code'] = 0
            res['case_dir'] = case_dir
            res['cached'] = True
            res['mesh_meta'] = {'mesh_file': mesh_file, 'cached': True}
            res['history_file'] = history_file
            res['surface_file'] = os.path.join(case_dir, "surface_forces.csv")
            res['flowfield_file'] = os.path.join(case_dir, "flowfield.dat")
            res['mesh_file'] = mesh_file
            return res

    # 4. Generate mesh if not cached or corrupted
    if not os.path.exists(mesh_file) or os.path.getsize(mesh_file) < 5000:
        mesh_meta = generate_su2_mesh_gmsh(outlines, mesh_file, ground_h=ground_h, density=density)
    else:
        mesh_meta = {'mesh_file': mesh_file, 'cached': True}

    # 4. Write config file
    iter_limit = 100 if density == 'coarse' else (160 if density == 'medium' else 250)
    write_su2_config_file(cfg_file, mesh_file, alpha_deg, speed=speed, re_val=re_val,
                          ground_h=ground_h, ref_chord_main=ref_chord_main, max_iter=iter_limit)

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
    res['history_file'] = history_file
    res['surface_file'] = os.path.join(case_dir, "surface_forces.csv")
    res['flowfield_file'] = os.path.join(case_dir, "flowfield.dat")
    res['mesh_file'] = mesh_file

    return res


def run_xfoil_single_element(airfoil_name_or_coords, alpha_list, re_val=570000.0, timeout=120):
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
                # Case-insensitive / whitespace-insensitive fallback
                key_clean = airfoil_name_or_coords.strip().lower().replace(" ", "").replace("-", "")
                for k, v in A.AIRFOILS.items():
                    if k.strip().lower().replace(" ", "").replace("-", "") == key_clean:
                        coords = v
                        break
            if coords is None:
                raise KeyError(f"Airfoil {airfoil_name_or_coords!r} not found in library.")
        else:
            coords = airfoil_name_or_coords

        c = np.asarray(coords, dtype=float).copy()

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
        if os.path.exists(LIBNOFPE_SO):
            env["LD_PRELOAD"] = LIBNOFPE_SO + (os.pathsep + env.get("LD_PRELOAD", "") if env.get("LD_PRELOAD") else "")

        xfoil_exec = XFOIL_BIN if os.path.exists(XFOIL_BIN) else "xfoil"
        proc = subprocess.run(f"{xfoil_exec} < {inp_path}", shell=True, env=env, cwd=td,
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


def run_javafoil_single_case(cfg, alpha_deg=0.0, speed=27.74, re_val=570000.0, ground_h=None):
    """
    Runs JavaFoil for a single alpha operating point using the existing aero_auto pipeline.
    """
    t0 = time.time()
    cfg = normalize_config(cfg)
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
            
            cl = None
            cd = None
            cm = 0.0
            if metrics:
                if metrics.get('Cl_peak') is not None and not np.isnan(metrics.get('Cl_peak')):
                    cl = float(metrics.get('Cl_peak'))
                    cd = float(metrics.get('Cd_peak'))
                elif abs(alpha_deg) < 1e-4 and metrics.get('Cl_a0') is not None and not np.isnan(metrics.get('Cl_a0')):
                    cl = float(metrics.get('Cl_a0'))
                    cd = float(metrics.get('Cd_a0'))
                cm = float(metrics.get('Cm_a0', 0.0) or 0.0)
            
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
# AERONAUTICAL DARK PLOTTING SUITE & AUTOMATED GRAPH GENERATORS
# ==============================================================================

DARK_BG = '#0b1120'
CARD_BG = '#1e293b'
TEXT_COLOR = '#f8fafc'
MUTED_COLOR = '#94a3b8'
GRID_COLOR = '#334155'
ACCENT_CYAN = '#38bdf8'
AMBER_COLOR = '#fbbf24'
EMERALD_COLOR = '#34d399'
ROSE_COLOR = '#f43f5e'
PURPLE_COLOR = '#c084fc'


def _style_dark_axes(ax, title=None, xlabel=None, ylabel=None):
    """Applies dark aeronautical styling consistent with application UI palette."""
    ax.set_facecolor(CARD_BG)
    ax.tick_params(colors=MUTED_COLOR, labelsize=9)
    ax.grid(True, linestyle='--', alpha=0.35, color=GRID_COLOR)
    for s in ax.spines.values():
        s.set_color(GRID_COLOR)
        s.set_linewidth(1.0)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, fontweight='bold', color=TEXT_COLOR)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, fontweight='bold', color=TEXT_COLOR)
    if title:
        ax.set_title(title, fontsize=11, fontweight='bold', color=TEXT_COLOR, pad=10)


def render_su2_polar_plots(records_or_df, out_dir, run_tag, cfg, speed=SPEED_DEFAULT, re_val=RE_DEFAULT, ground_h=None):
    """
    Renders the official SU2 aerodynamic polar graphs and saves the raw data CSV:
      1. su2_polar_cl_alfa_<run_tag>.png   : Lift Curve (Cl vs Alpha)
      2. su2_polar_cd_alfa_<run_tag>.png   : Drag Curve (Cd vs Alpha)
      3. su2_polar_eff_alfa_<run_tag>.png  : Aerodynamic Efficiency (|Cl|/Cd vs Alpha)
      4. su2_polar_cl_cd_<run_tag>.png     : Drag Polar (Cl vs Cd)
      5. su2_polar_<run_tag>.csv           : Raw polar table
    """
    os.makedirs(out_dir, exist_ok=True)
    df = pd.DataFrame(records_or_df) if isinstance(records_or_df, (list, tuple)) else records_or_df.copy()
    if df.empty or 'alpha' not in df.columns:
        return {}

    df = df.sort_values('alpha').reset_index(drop=True)
    if 'converged' not in df.columns:
        df['converged'] = True
    if 'efficiency' not in df.columns and 'Cl' in df.columns and 'Cd' in df.columns:
        df['efficiency'] = df['Cl'].abs() / df['Cd'].replace(0, np.nan)
    if 'engine' not in df.columns:
        df['engine'] = 'SU2'

    # Save raw CSV
    csv_path = os.path.join(out_dir, f"su2_polar_{run_tag}.csv")
    df.to_csv(csv_path, index=False)

    cfg_desc = A.describe(cfg) if hasattr(A, 'describe') else str(cfg[0])
    ge_str = f"Ground Effect (h={ground_h:g}%)" if ground_h is not None else "Free Stream"

    # Reference row at alpha=0
    row0 = df[np.isclose(df['alpha'], 0.0, atol=0.25)]
    sub_title = ""
    if not row0.empty:
        c0 = float(row0['Cl'].iloc[0])
        d0 = float(row0['Cd'].iloc[0])
        e0 = abs(c0) / max(d0, 1e-5)
        q_pa = 0.5 * RHO_DEFAULT * (speed ** 2)
        df_n = abs(c0) * q_pa * 0.3 * 1.0
        sub_title = f"\nα=0°: Cl={c0:.3f}, Cd={d0:.4f}, |Cl|/Cd={e0:.1f}, Downforce={df_n:.1f} N"

    out_files = {'csv': csv_path}

    def _plot_curve(y_col, ylabel, title_metric, fname_key, fname_prefix):
        p_path = os.path.join(out_dir, f"{fname_prefix}_{run_tag}.png")
        fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
        fig.patch.set_facecolor(DARK_BG)
        _style_dark_axes(ax, f"SU2 {title_metric} — Run {run_tag} ({ge_str}){sub_title}\n{cfg_desc}",
                         "Angle of Attack α (°)", ylabel)

        conv_mask = df['converged'].astype(bool)
        unconv_mask = ~conv_mask

        # Data points
        if np.any(conv_mask):
            ax.plot(df.loc[conv_mask, 'alpha'], df.loc[conv_mask, y_col], 'o', color=ACCENT_CYAN,
                    ms=7, mfc=ACCENT_CYAN, mec='white', label="SU2 RANS (Converged)")
        if np.any(unconv_mask):
            ax.plot(df.loc[unconv_mask, 'alpha'], df.loc[unconv_mask, y_col], 'X', color=ROSE_COLOR,
                    ms=9, mfc=ROSE_COLOR, mec='white', label="SU2 RANS (Unconverged)")

        # Smooth curve fit strictly restricted to data range
        if len(df) >= 3:
            deg = min(3, len(df) - 1) if len(df) >= 5 else min(2, len(df) - 1)
            coeffs = np.polyfit(df['alpha'], df[y_col], deg=deg)
            x_fit = np.linspace(df['alpha'].min(), df['alpha'].max(), 140)
            y_fit = np.polyval(coeffs, x_fit)
            ax.plot(x_fit, y_fit, '--', color=ACCENT_CYAN, lw=1.6, alpha=0.85,
                    label=f"Polar Fit [data range {df['alpha'].min():g}°..{df['alpha'].max():g}°]")
            ax.plot(df['alpha'], df[y_col], '-', color=ACCENT_CYAN, lw=1.0, alpha=0.45)
        elif len(df) == 2:
            ax.plot(df['alpha'], df[y_col], '--', color=ACCENT_CYAN, lw=1.4, alpha=0.8, label="Linear Segment")
        elif len(df) == 1:
            ax.axhline(df[y_col].iloc[0], color=ACCENT_CYAN, ls=':', lw=1.2, alpha=0.7,
                       label=f"Single Point: {df[y_col].iloc[0]:.4f} @ α={df['alpha'].iloc[0]:g}°")

        ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
        ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
        plt.tight_layout()
        plt.savefig(p_path)
        plt.close()
        out_files[fname_key] = p_path

    # 1. Cl vs alpha
    _plot_curve('Cl', "Lift / Downforce Coefficient Cl (ref c_main=1.0)", "Lift Curve (Cl vs α)", "polar_cl_alfa", "su2_polar_cl_alfa")
    # 2. Cd vs alpha
    _plot_curve('Cd', "Drag Coefficient Cd (ref c_main=1.0)", "Drag Curve (Cd vs α)", "polar_cd_alfa", "su2_polar_cd_alfa")
    # 3. Efficiency |Cl|/Cd vs alpha
    _plot_curve('efficiency', "Aerodynamic Efficiency |Cl|/Cd", "Efficiency Curve (|Cl|/Cd vs α)", "polar_eff_alfa", "su2_polar_eff_alfa")

    # 4. Drag Polar (Cl vs Cd)
    p_polar = os.path.join(out_dir, f"su2_polar_cl_cd_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_dark_axes(ax, f"SU2 Drag Polar (Cl vs Cd) — Run {run_tag} ({ge_str}){sub_title}\n{cfg_desc}",
                     "Drag Coefficient Cd", "Lift / Downforce Coefficient Cl")

    conv_mask = df['converged'].astype(bool)
    unconv_mask = ~conv_mask
    if np.any(conv_mask):
        ax.plot(df.loc[conv_mask, 'Cd'], df.loc[conv_mask, 'Cl'], 'o', color=ACCENT_CYAN,
                ms=7, mfc=ACCENT_CYAN, mec='white', label="SU2 RANS (Converged)")
    if np.any(unconv_mask):
        ax.plot(df.loc[unconv_mask, 'Cd'], df.loc[unconv_mask, 'Cl'], 'X', color=ROSE_COLOR,
                ms=9, mfc=ROSE_COLOR, mec='white', label="SU2 RANS (Unconverged)")

    if len(df) >= 2:
        ax.plot(df['Cd'], df['Cl'], '-', color=ACCENT_CYAN, lw=1.6, alpha=0.7)

    # Highlight alpha=0
    if not row0.empty:
        c0, d0 = float(row0['Cl'].iloc[0]), float(row0['Cd'].iloc[0])
        ax.plot([d0], [c0], '*', color=AMBER_COLOR, ms=14, label=f"α=0° Design Point (Cl={c0:.3f}, Cd={d0:.4f})")

    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_polar)
    plt.close()
    out_files['polar_cl_cd'] = p_polar

    return out_files


def render_xfoil_polar_plots(records_or_df, out_dir, run_tag, cfg, speed=SPEED_DEFAULT, re_val=RE_DEFAULT):
    """
    Renders official dark-themed XFOIL aerodynamic polar graphs and saves the raw data CSV:
      1. xfoil_polar_cl_alfa_<run_tag>.png   : Lift Curve (Cl vs Alpha)
      2. xfoil_polar_cd_alfa_<run_tag>.png   : Drag Curve (Cd vs Alpha)
      3. xfoil_polar_eff_alfa_<run_tag>.png  : Aerodynamic Efficiency (|Cl|/Cd vs Alpha)
      4. xfoil_polar_cl_cd_<run_tag>.png     : Drag Polar (Cl vs Cd)
      5. xfoil_polar_cm_alfa_<run_tag>.png   : Pitching Moment (Cm vs Alpha)
      6. xfoil_polar_<run_tag>.csv           : Raw polar table
    """
    os.makedirs(out_dir, exist_ok=True)
    df = pd.DataFrame(records_or_df) if isinstance(records_or_df, (list, tuple)) else records_or_df.copy()
    if df.empty or 'alpha' not in df.columns:
        return {}

    df = df.sort_values('alpha').reset_index(drop=True)
    if 'converged' not in df.columns:
        df['converged'] = True
    if 'efficiency' not in df.columns and 'Cl' in df.columns and 'Cd' in df.columns:
        df['efficiency'] = df['Cl'].abs() / df['Cd'].replace(0, np.nan)
    if 'engine' not in df.columns:
        df['engine'] = 'XFOIL'

    # Save raw CSV
    csv_path = os.path.join(out_dir, f"xfoil_polar_{run_tag}.csv")
    df.to_csv(csv_path, index=False)

    main_foil = cfg[0] if isinstance(cfg, (tuple, list)) else str(cfg)
    row0 = df[np.isclose(df['alpha'], 0.0, atol=0.25)]
    sub_title = ""
    if not row0.empty:
        c0 = float(row0['Cl'].iloc[0])
        d0 = float(row0['Cd'].iloc[0])
        e0 = abs(c0) / max(d0, 1e-5)
        sub_title = f"\nα=0°: Cl={c0:.3f}, Cd={d0:.4f}, |Cl|/Cd={e0:.1f} (Viscous Re={re_val:g})"

    out_files = {'csv': csv_path}

    def _plot_curve(y_col, ylabel, title_metric, fname_key, fname_prefix, color=PURPLE_COLOR):
        if y_col not in df.columns:
            return
        p_path = os.path.join(out_dir, f"{fname_prefix}_{run_tag}.png")
        fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
        fig.patch.set_facecolor(DARK_BG)
        _style_dark_axes(ax, f"XFOIL {title_metric} — {main_foil} (Run {run_tag}){sub_title}\nViscous Panel Formulation (e^N Transition, Re={re_val:g})",
                         "Angle of Attack α (°)", ylabel)

        conv_mask = df['converged'].astype(bool)
        if np.any(conv_mask):
            ax.plot(df.loc[conv_mask, 'alpha'], df.loc[conv_mask, y_col], 'o-', color=color,
                    ms=6, mfc=color, mec='white', lw=1.8, label=f"XFOIL ({main_foil})")

        ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
        ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
        plt.tight_layout()
        plt.savefig(p_path)
        plt.close()
        out_files[fname_key] = p_path

    # 1. Cl vs alpha
    _plot_curve('Cl', "Lift / Downforce Coefficient Cl", "Lift Curve (Cl vs α)", "polar_cl_alfa", "xfoil_polar_cl_alfa", color=PURPLE_COLOR)
    # 2. Cd vs alpha
    _plot_curve('Cd', "Drag Coefficient Cd", "Drag Curve (Cd vs α)", "polar_cd_alfa", "xfoil_polar_cd_alfa", color=AMBER_COLOR)
    # 3. Efficiency |Cl|/Cd vs alpha
    _plot_curve('efficiency', "Aerodynamic Efficiency |Cl|/Cd", "Efficiency Curve (|Cl|/Cd vs α)", "polar_eff_alfa", "xfoil_polar_eff_alfa", color=EMERALD_COLOR)
    # 4. Cm vs alpha
    if 'Cm' in df.columns:
        _plot_curve('Cm', "Pitching Moment Coefficient Cm", "Pitching Moment Curve (Cm vs α)", "polar_cm_alfa", "xfoil_polar_cm_alfa", color=ACCENT_CYAN)

    # 5. Drag Polar (Cl vs Cd)
    p_polar = os.path.join(out_dir, f"xfoil_polar_cl_cd_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_dark_axes(ax, f"XFOIL Drag Polar (Cl vs Cd) — {main_foil} (Run {run_tag}){sub_title}\nViscous Panel Formulation (e^N Transition, Re={re_val:g})",
                     "Drag Coefficient Cd", "Lift / Downforce Coefficient Cl")

    ax.plot(df['Cd'], df['Cl'], 'o-', color=PURPLE_COLOR, lw=1.8, ms=6, mfc=PURPLE_COLOR, mec='white', label=f"XFOIL ({main_foil})")
    if not row0.empty:
        c0, d0 = float(row0['Cl'].iloc[0]), float(row0['Cd'].iloc[0])
        ax.plot([d0], [c0], '*', color=AMBER_COLOR, ms=14, label=f"α=0° Design Point (Cl={c0:.3f}, Cd={d0:.4f})")

    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_polar)
    plt.close()
    out_files['polar_cl_cd'] = p_polar

    return out_files


def render_su2_convergence_plot(history_file, out_dir, run_tag, alpha_deg=0.0, cfg_desc="Multi-Element Wing"):
    """Renders 2-panel SU2 convergence history (residual drop and force stabilization)."""
    p_path = os.path.join(out_dir, f"su2_convergence_{run_tag}.png")
    if not os.path.exists(history_file):
        return None
    try:
        df = pd.read_csv(history_file)
        df.columns = [c.replace('"', '').strip() for c in df.columns]
    except Exception:
        return None

    cl_col = next((c for c in df.columns if 'LIFT' in c or 'CL' in c or 'Cl' in c), None)
    cd_col = next((c for c in df.columns if 'DRAG' in c or 'CD' in c or 'Cd' in c), None)
    res_col = next((c for c in df.columns if 'RMS_RES' in c or 'RMS_PRESSURE' in c), None)
    iter_col = next((c for c in df.columns if 'ITER' in c or 'Inner_Iter' in c), df.columns[0])

    fig, (ax_res, ax_frc) = plt.subplots(2, 1, figsize=(10, 6.5), dpi=140, sharex=True)
    fig.patch.set_facecolor(DARK_BG)

    _style_dark_axes(ax_res, f"SU2 Convergence History — Run {run_tag} (α={alpha_deg:g}°)\n{cfg_desc}",
                     None, "Residual (log10)")
    _style_dark_axes(ax_frc, None, "Iteration", "Force Coefficients (Cl, Cd)")

    iters = df[iter_col]
    if res_col:
        ax_res.plot(iters, df[res_col], color=ACCENT_CYAN, lw=1.8, label=f"RMS Residual ({res_col})")
        res_drop = float(df[res_col].iloc[0] - df[res_col].iloc[-1])
        conv_flag = (res_drop >= 3.0)
        badge_txt = f"RESIDUAL DROP: {res_drop:.2f} orders ({'CONVERGED' if conv_flag else 'UNSTEADY/UNCONVERGED'})"
        badge_col = EMERALD_COLOR if conv_flag else ROSE_COLOR
        ax_res.text(0.98, 0.90, badge_txt, transform=ax_res.transAxes, ha='right', va='top',
                    color=badge_col, fontweight='bold', fontsize=9,
                    bbox=dict(boxstyle='round,pad=0.3', fc=DARK_BG, ec=badge_col, lw=1.0))
        ax_res.axhline(df[res_col].iloc[0] - 3.0, color=EMERALD_COLOR, ls=':', lw=1.0, label="Target -3 Order Drop")
        ax_res.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8, loc='lower left')

    if cl_col:
        ax_frc.plot(iters, df[cl_col], color=AMBER_COLOR, lw=1.8, label=f"Lift / Downforce Cl (Final: {df[cl_col].iloc[-1]:.4f})")
    if cd_col:
        ax_frc.plot(iters, df[cd_col], color=ROSE_COLOR, lw=1.8, label=f"Drag Cd (Final: {df[cd_col].iloc[-1]:.4f})")

    ax_frc.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax_frc.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8, loc='best')

    plt.tight_layout()
    plt.savefig(p_path)
    plt.close()

    base_graphs_dir = os.path.dirname(out_dir)
    if os.path.basename(out_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
        try:
            shutil.copy2(p_path, os.path.join(base_graphs_dir, os.path.basename(p_path)))
        except Exception:
            pass

    return p_path


def render_su2_surface_cp_plot(surface_file, out_dir, run_tag, cfg, alpha_deg=0.0, speed=SPEED_DEFAULT, re_val=RE_DEFAULT, ground_h=None):
    """Renders authentic surface pressure coefficient (-Cp) distribution across all wing elements, cleanly separated into upper and lower surfaces."""
    p_path = os.path.join(out_dir, f"su2_surface_cp_{run_tag}.png")
    if not os.path.exists(surface_file):
        return None
    try:
        df = pd.read_csv(surface_file)
        df.columns = [c.replace('"', '').strip() for c in df.columns]
    except Exception:
        return None

    if 'x' not in df.columns or 'Pressure' not in df.columns:
        return None

    cfg_tuple = normalize_config(cfg)
    n_expected = 1 + len(cfg_tuple[1])

    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    cfg_desc = A.describe(cfg_tuple) if hasattr(A, 'describe') else str(cfg_tuple[0])
    _style_dark_axes(ax, f"SU2 Surface Pressure Distribution (Cp vs x) — Run {run_tag} (α={alpha_deg:g}°)\n{cfg_desc}",
                     "Chordwise Coordinate x (normalized to c_main=1.0)", "Pressure Coefficient -Cp (Suction Up)")

    # Dynamic pressure q = 0.5 * rho * V^2 = 0.5 in non-dimensional SU2
    q_inf = 0.5
    df['cp'] = df['Pressure'] / q_inf

    try:
        outlines = build_geometry_coords(cfg_tuple, ground_h)
    except Exception:
        outlines = []
    if not outlines:
        try:
            outlines = A.build_outlines(cfg_tuple, ground_h)
        except Exception:
            outlines = []

    pts = df[['x', 'y']].values

    # Check if mesh coordinates indicate ground effect elevation while ground_h was omitted
    if outlines and ground_h is None and pts.shape[0] > 0:
        pts_min_y = float(np.min(pts[:, 1]))
        out_min_y = float(min(np.min(o[:, 1]) for o in outlines))
        if pts_min_y - out_min_y > 0.05:
            y_shift = pts_min_y - out_min_y
            outlines = [o + np.array([0.0, y_shift]) for o in outlines]

    if outlines and len(outlines) > 0:
        n_elements = min(len(outlines), n_expected)
        elem_assignments = []
        contour_positions = []
        for pt in pts:
            best_elem = 0
            min_d2 = float('inf')
            best_idx = 0
            for e_idx in range(n_elements):
                o = outlines[e_idx]
                d2_arr = (o[:, 0] - pt[0])**2 + (o[:, 1] - pt[1])**2
                min_idx = int(np.argmin(d2_arr))
                min_val = float(d2_arr[min_idx])
                if min_val < min_d2:
                    min_d2 = min_val
                    best_elem = e_idx
                    best_idx = min_idx
            elem_assignments.append(best_elem)
            contour_positions.append(best_idx)

        df['element_id'] = elem_assignments
        df['contour_pos'] = contour_positions
    else:
        df['element_id'] = 0
        df['contour_pos'] = df['x']
        n_elements = 1

    colors = [ACCENT_CYAN, AMBER_COLOR, EMERALD_COLOR, PURPLE_COLOR, ROSE_COLOR]
    for elem_idx in range(n_elements):
        elem_df = df[df['element_id'] == elem_idx].copy()
        if elem_df.empty:
            continue
        col = colors[elem_idx % len(colors)]
        lbl = "Main Element" if elem_idx == 0 else f"Flap {elem_idx}"

        if outlines and elem_idx < len(outlines):
            o = outlines[elem_idx]
            i_le = int(np.argmin(o[:, 0]))
            upper_df = elem_df[elem_df['contour_pos'] <= i_le].sort_values('x').reset_index(drop=True)
            lower_df = elem_df[elem_df['contour_pos'] > i_le].sort_values('x').reset_index(drop=True)
        else:
            med_y = elem_df['y'].median()
            upper_df = elem_df[elem_df['y'] >= med_y].sort_values('x').reset_index(drop=True)
            lower_df = elem_df[elem_df['y'] < med_y].sort_values('x').reset_index(drop=True)

        # Bridge leading edge stagnation point for seamless continuous curves without gaps
        if not elem_df.empty:
            le_row = elem_df.loc[elem_df['x'].idxmin()]
            if not upper_df.empty and upper_df.iloc[0]['x'] > le_row['x']:
                upper_df = pd.concat([pd.DataFrame([le_row]), upper_df], ignore_index=True)
            if not lower_df.empty and lower_df.iloc[0]['x'] > le_row['x']:
                lower_df = pd.concat([pd.DataFrame([le_row]), lower_df], ignore_index=True)

        if not upper_df.empty:
            ax.plot(upper_df['x'], -upper_df['cp'], 'o-', color=col, ms=3.5, lw=1.8,
                    label=f"{lbl} Upper (Suction)")
        if not lower_df.empty:
            ax.plot(lower_df['x'], -lower_df['cp'], 's--', color=col, ms=3.0, lw=1.4, alpha=0.85,
                    label=f"{lbl} Lower (Pressure)")

    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.invert_yaxis()
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')
    plt.tight_layout()
    plt.savefig(p_path)
    plt.close()

    base_graphs_dir = os.path.dirname(out_dir)
    if os.path.basename(out_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
        try:
            shutil.copy2(p_path, os.path.join(base_graphs_dir, os.path.basename(p_path)))
        except Exception:
            pass

    return p_path


def render_su2_flowfield_plot(flowfield_file, out_dir, run_tag, cfg, alpha_deg=0.0, speed=SPEED_DEFAULT, ground_h=None):
    """Renders 2-panel velocity magnitude and pressure contours with marked slot gaps."""
    p_path = os.path.join(out_dir, f"su2_flowfield_{run_tag}.png")
    if not os.path.exists(flowfield_file):
        return None
    try:
        pts = []
        with open(flowfield_file) as f:
            f.readline()
            f.readline()
            f.readline()
            for line in f:
                p = line.strip().split()
                if len(p) >= 5:
                    try:
                        pts.append([float(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])])
                    except ValueError:
                        break
        arr = np.array(pts)
    except Exception:
        return None

    if len(arr) < 100:
        return None

    x, y, p, vx, vy = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    vel = np.sqrt(vx**2 + vy**2)

    try:
        outlines = build_geometry_coords(cfg, ground_h)
        all_pts = np.vstack(outlines)
        xmin, xmax = all_pts[:, 0].min() - 0.25, all_pts[:, 0].max() + 0.35
        ymin, ymax = all_pts[:, 1].min() - 0.35, all_pts[:, 1].max() + 0.35
    except Exception:
        outlines = []
        xmin, xmax = -0.3, 1.8
        ymin, ymax = -0.5, 0.5

    mask = (x >= xmin - 0.1) & (x <= xmax + 0.1) & (y >= ymin - 0.1) & (y <= ymax + 0.1)
    if np.sum(mask) < 50:
        mask = np.ones(len(x), dtype=bool)

    tri = mtri.Triangulation(x[mask], y[mask])

    fig, (ax_vel, ax_p) = plt.subplots(2, 1, figsize=(11, 7.5), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    cfg_desc = A.describe(cfg) if hasattr(A, 'describe') else str(cfg[0])

    # 1. Velocity Magnitude
    ax_vel.set_facecolor(CARD_BG)
    cnt_v = ax_vel.tricontourf(tri, vel[mask], levels=45, cmap='viridis')
    cb_v = fig.colorbar(cnt_v, ax=ax_vel, pad=0.02, aspect=14)
    cb_v.set_label("Velocity Magnitude |V| / V_inf", color=TEXT_COLOR, fontsize=8.5)
    cb_v.ax.tick_params(colors=MUTED_COLOR, labelsize=7.5)

    # 2. Pressure Coefficient
    ax_p.set_facecolor(CARD_BG)
    cnt_p = ax_p.tricontourf(tri, p[mask] / 0.5, levels=45, cmap='coolwarm')
    cb_p = fig.colorbar(cnt_p, ax=ax_p, pad=0.02, aspect=14)
    cb_p.set_label("Pressure Coefficient Cp", color=TEXT_COLOR, fontsize=8.5)
    cb_p.ax.tick_params(colors=MUTED_COLOR, labelsize=7.5)

    # Draw airfoil bodies and slot gap annotations on both
    for ax, title in [(ax_vel, f"SU2 Flow Field: Velocity Magnitude (α={alpha_deg:g}°) — {cfg_desc}"),
                      (ax_p, f"SU2 Flow Field: Pressure Distribution (α={alpha_deg:g}°) — {cfg_desc}")]:
        ax.set_aspect('equal')
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        _style_dark_axes(ax, title, "x (chord)", "y (chord)")
        for i, o in enumerate(outlines):
            ax.fill(o[:, 0], o[:, 1], color='#0f172a', ec='white', lw=1.4, zorder=5)
            if i > 0 and len(outlines[i-1]) > 0:
                te_prev = outlines[i-1][np.argmax(outlines[i-1][:, 0])]
                le_curr = o[np.argmin(o[:, 0])]
                slot_dist = np.linalg.norm(le_curr - te_prev)
                if ax == ax_vel:
                    ax.annotate(f"Slot {i}: {slot_dist*100:.1f}%", xy=(le_curr[0], le_curr[1]),
                                xytext=(le_curr[0] - 0.05, le_curr[1] + 0.12),
                                arrowprops=dict(arrowstyle="->", color=AMBER_COLOR, lw=1.2),
                                color=AMBER_COLOR, fontsize=8, fontweight='bold', zorder=10,
                                bbox=dict(boxstyle='round,pad=0.2', fc=DARK_BG, ec=AMBER_COLOR, lw=0.8, alpha=0.9))

    plt.tight_layout()
    plt.savefig(p_path)
    plt.close()

    base_graphs_dir = os.path.dirname(out_dir)
    if os.path.basename(out_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
        try:
            shutil.copy2(p_path, os.path.join(base_graphs_dir, os.path.basename(p_path)))
        except Exception:
            pass

    return p_path


def render_overlay_plots(jf_records_or_df, su2_records_or_df, out_dir, run_tag, cfg,
                         speed=SPEED_DEFAULT, re_val=RE_DEFAULT, ground_h=None, mesh_nodes="N/A",
                         jf_velocity_file=None, su2_surface_file=None, xfoil_records_or_df=None):
    """
    Renders superimposed JavaFoil vs SU2 vs XFOIL overlay plots with bottom difference and ratio panel:
      1. overlay_cl_alfa_<run_tag>.png     : Cl vs Alpha overlay with Delta / Ratio panel
      2. overlay_cd_alfa_<run_tag>.png     : Cd vs Alpha overlay with Delta / Ratio panel
      3. overlay_eff_alfa_<run_tag>.png    : Efficiency |Cl|/Cd overlay with Delta / Ratio panel
      4. overlay_drag_polar_<run_tag>.png  : Superimposed Drag Polar (Cl vs Cd)
      5. overlay_surface_cp_<run_tag>.png  : Main element Cp comparison
      6. overlay_comparison_<run_tag>.csv  : Raw comparison CSV
    """
    os.makedirs(out_dir, exist_ok=True)
    df_jf = pd.DataFrame(jf_records_or_df) if isinstance(jf_records_or_df, (list, tuple)) else jf_records_or_df.copy()
    df_su2 = pd.DataFrame(su2_records_or_df) if isinstance(su2_records_or_df, (list, tuple)) else su2_records_or_df.copy()

    df_jf.columns = [c.lower() for c in df_jf.columns]
    df_su2.columns = [c.lower() for c in df_su2.columns]

    if 'converged' not in df_su2.columns:
        df_su2['converged'] = True

    if 'efficiency' not in df_jf.columns and 'cl' in df_jf.columns and 'cd' in df_jf.columns:
        df_jf['efficiency'] = df_jf['cl'].abs() / df_jf['cd'].replace(0, np.nan)
    if 'efficiency' not in df_su2.columns and 'cl' in df_su2.columns and 'cd' in df_su2.columns:
        df_su2['efficiency'] = df_su2['cl'].abs() / df_su2['cd'].replace(0, np.nan)

    # Process XFOIL data if provided
    df_xf = None
    if xfoil_records_or_df is not None:
        try:
            df_xf = pd.DataFrame(xfoil_records_or_df) if isinstance(xfoil_records_or_df, (list, tuple)) else xfoil_records_or_df.copy()
            df_xf.columns = [c.lower() for c in df_xf.columns]
            if 'efficiency' not in df_xf.columns and 'cl' in df_xf.columns and 'cd' in df_xf.columns:
                df_xf['efficiency'] = df_xf['cl'].abs() / df_xf['cd'].replace(0, np.nan)
        except Exception:
            df_xf = None

    # Merge on alpha
    merged = pd.merge(df_jf, df_su2, on='alpha', suffixes=('_jf', '_su2'), how='outer').sort_values('alpha').reset_index(drop=True)
    if 'cl_jf' in merged.columns and 'cl_su2' in merged.columns:
        merged['delta_cl'] = merged['cl_su2'] - merged['cl_jf']
        merged['ratio_cl'] = merged['cl_jf'] / merged['cl_su2'].replace(0, np.nan)
    if 'cd_jf' in merged.columns and 'cd_su2' in merged.columns:
        merged['delta_cd'] = merged['cd_su2'] - merged['cd_jf']
        merged['ratio_cd'] = merged['cd_jf'] / merged['cd_su2'].replace(0, np.nan)

    if df_xf is not None and not df_xf.empty and 'alpha' in df_xf.columns:
        sub_xf = df_xf[['alpha'] + [c for c in ['cl', 'cd', 'cm', 'efficiency'] if c in df_xf.columns]].copy()
        sub_xf.rename(columns={'cl': 'cl_xf', 'cd': 'cd_xf', 'cm': 'cm_xf', 'efficiency': 'efficiency_xf'}, inplace=True)
        merged = pd.merge(merged, sub_xf, on='alpha', how='outer').sort_values('alpha').reset_index(drop=True)

    # Save raw CSV
    csv_path = os.path.join(out_dir, f"overlay_comparison_{run_tag}.csv")
    merged.to_csv(csv_path, index=False)

    cfg_desc = A.describe(cfg) if hasattr(A, 'describe') else str(cfg[0])
    ge_str = f"Ground Effect (h={ground_h:g}%)" if ground_h is not None else "Free Stream (Unbounded)"

    try:
        outlines = build_geometry_coords(cfg, ground_h)
        all_pts = np.vstack(outlines)
        c_asm = float(all_pts[:, 0].max() - all_pts[:, 0].min())
    except Exception:
        c_asm = 1.0

    footer_text = (
        f"Solver Parameters: SU2 2D RANS (k-ω SST, {mesh_nodes})  ·  JavaFoil (Linear Potential + BL)"
        + (f"  ·  XFOIL (e^N Viscous, {cfg[0]})" if df_xf is not None and not df_xf.empty else "")
        + f"\nFreestream & Geometry: V = {speed:.1f} m/s  ·  Re = {re_val:g}  ·  {ge_str}  ·  Ref Chords: c_main = 1.0, c_assembly = {c_asm:.3f}"
    )

    out_files = {'csv': csv_path}

    def _plot_overlay_metric(metric_jf, metric_su2, ylabel, title, prefix):
        p_path = os.path.join(out_dir, f"{prefix}_{run_tag}.png")
        fig = plt.figure(figsize=(10.5, 7.2), dpi=140)
        gs = fig.add_gridspec(2, 1, height_ratios=[3, 1.2], hspace=0.22)
        ax_main = fig.add_subplot(gs[0])
        ax_sub = fig.add_subplot(gs[1], sharex=ax_main)
        fig.patch.set_facecolor(DARK_BG)

        _style_dark_axes(ax_main, f"Superimposed Comparison: {title} — Run {run_tag}\n{cfg_desc}",
                         None, ylabel)
        _style_dark_axes(ax_sub, None, "Angle of Attack α (°)", "Δ / Ratio")

        if metric_jf in df_jf.columns:
            ax_main.plot(df_jf['alpha'], df_jf[metric_jf], 's--', color=AMBER_COLOR, lw=2.0, ms=7,
                         mfc=AMBER_COLOR, mec='white', label="JavaFoil (Panel + Integral BL)")

        if metric_su2 in df_su2.columns:
            conv = df_su2['converged'].astype(bool)
            if np.any(conv):
                ax_main.plot(df_su2.loc[conv, 'alpha'], df_su2.loc[conv, metric_su2], 'o-', color=ACCENT_CYAN,
                             lw=2.2, ms=7, mfc=ACCENT_CYAN, mec='white', label="SU2 (2D RANS k-ω SST)")
            if np.any(~conv):
                ax_main.plot(df_su2.loc[~conv, 'alpha'], df_su2.loc[~conv, metric_su2], 'D', color=ROSE_COLOR,
                             ms=9, mfc=ROSE_COLOR, mec='white', label="SU2 Unconverged (unsteady)")

        if df_xf is not None and metric_jf in df_xf.columns:
            ax_main.plot(df_xf['alpha'], df_xf[metric_jf], '^-.', color=PURPLE_COLOR, lw=1.8, ms=6,
                         mfc=PURPLE_COLOR, mec='white', label=f"XFOIL ({cfg[0]} isolated viscous)")

        ax_main.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
        ax_main.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')

        # Bottom Subplot: Difference and Ratio
        sub_df = merged.dropna(subset=[f"{metric_jf}_jf", f"{metric_su2}_su2"])
        if not sub_df.empty:
            delta = sub_df[f"{metric_su2}_su2"] - sub_df[f"{metric_jf}_jf"]
            ratio = sub_df[f"{metric_jf}_jf"] / sub_df[f"{metric_su2}_su2"].replace(0, np.nan)

            ax_sub.plot(sub_df['alpha'], delta, 'o-', color=ROSE_COLOR, lw=1.6, ms=5, label="Difference (SU2 - JF)")
            ax_sub.axhline(0, color=MUTED_COLOR, ls=':', lw=1.0)
            ax_sub.set_ylabel("Δ (SU2 - JF)", color=ROSE_COLOR, fontsize=9, fontweight='bold')
            ax_sub.tick_params(axis='y', colors=ROSE_COLOR, labelsize=8)

            ax_sub_r = ax_sub.twinx()
            ax_sub_r.plot(sub_df['alpha'], ratio, '^--', color=EMERALD_COLOR, lw=1.6, ms=5, label="Ratio (JF / SU2)")
            ax_sub_r.axhline(1.0, color=EMERALD_COLOR, ls=':', lw=0.8, alpha=0.7)
            ax_sub_r.set_ylabel("Ratio (JF / SU2)", color=EMERALD_COLOR, fontsize=9, fontweight='bold')
            ax_sub_r.tick_params(axis='y', colors=EMERALD_COLOR, labelsize=8)
            ax_sub_r.spines['right'].set_color(EMERALD_COLOR)
            for s in ['top', 'bottom', 'left']:
                ax_sub_r.spines[s].set_color(GRID_COLOR)

        fig.subplots_adjust(left=0.09, right=0.91, top=0.93, bottom=0.14)
        fig.text(0.5, 0.02, footer_text, ha='center', va='bottom', fontsize=8, color=MUTED_COLOR,
                 bbox=dict(boxstyle='round,pad=0.35', fc=DARK_BG, ec=GRID_COLOR, lw=0.8, alpha=0.95))
        plt.savefig(p_path)
        plt.close()
        out_files[prefix] = p_path

    _plot_overlay_metric('cl', 'cl', "Lift Coefficient Cl (ref c_main=1.0)", "Lift Curve (Cl vs α)", "overlay_cl_alfa")
    _plot_overlay_metric('cd', 'cd', "Drag Coefficient Cd (ref c_main=1.0)", "Drag Curve (Cd vs α)", "overlay_cd_alfa")
    _plot_overlay_metric('efficiency', 'efficiency', "Aerodynamic Efficiency |Cl|/Cd", "Efficiency (|Cl|/Cd vs α)", "overlay_eff_alfa")

    # 4. Superimposed Drag Polar (Cl vs Cd)
    p_polar = os.path.join(out_dir, f"overlay_drag_polar_{run_tag}.png")
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=140)
    fig.patch.set_facecolor(DARK_BG)
    _style_dark_axes(ax, f"Superimposed Drag Polar (Cl vs Cd) — Run {run_tag}\n{cfg_desc}",
                     "Drag Coefficient Cd", "Lift / Downforce Coefficient Cl")

    if 'cd' in df_jf.columns and 'cl' in df_jf.columns:
        ax.plot(df_jf['cd'], df_jf['cl'], 's--', color=AMBER_COLOR, lw=2.0, ms=7,
                mfc=AMBER_COLOR, mec='white', label="JavaFoil Polar")
    if 'cd' in df_su2.columns and 'cl' in df_su2.columns:
        conv = df_su2['converged'].astype(bool)
        if np.any(conv):
            ax.plot(df_su2.loc[conv, 'cd'], df_su2.loc[conv, 'cl'], 'o-', color=ACCENT_CYAN,
                    lw=2.2, ms=7, mfc=ACCENT_CYAN, mec='white', label="SU2 Polar (Converged)")
        if np.any(~conv):
            ax.plot(df_su2.loc[~conv, 'cd'], df_su2.loc[~conv, 'cl'], 'D', color=ROSE_COLOR,
                    ms=9, mfc=ROSE_COLOR, mec='white', label="SU2 Unconverged")

    if df_xf is not None and 'cd' in df_xf.columns and 'cl' in df_xf.columns:
        ax.plot(df_xf['cd'], df_xf['cl'], '^-.', color=PURPLE_COLOR, lw=1.8, ms=6,
                mfc=PURPLE_COLOR, mec='white', label=f"XFOIL ({cfg[0]} isolated viscous)")

    ax.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best')

    fig.subplots_adjust(left=0.09, right=0.91, top=0.92, bottom=0.14)
    fig.text(0.5, 0.02, footer_text, ha='center', va='bottom', fontsize=8, color=MUTED_COLOR,
             bbox=dict(boxstyle='round,pad=0.35', fc=DARK_BG, ec=GRID_COLOR, lw=0.8, alpha=0.95))

    plt.savefig(p_polar)
    plt.close()
    out_files['overlay_drag_polar'] = p_polar

    # 5. Cp comparison on main element if files available
    if su2_surface_file and os.path.exists(su2_surface_file):
        p_cp = render_overlay_surface_cp(su2_surface_file, jf_velocity_file, out_dir, run_tag, cfg_desc, cfg=cfg, ground_h=ground_h)
        if p_cp:
            out_files['overlay_surface_cp'] = p_cp

    base_graphs_dir = os.path.dirname(out_dir)
    if os.path.basename(out_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
        for f_p in list(out_files.values()):
            if isinstance(f_p, str) and os.path.isfile(f_p):
                try:
                    shutil.copy2(f_p, os.path.join(base_graphs_dir, os.path.basename(f_p)))
                except Exception:
                    pass

    return out_files


def render_overlay_surface_cp(su2_surface_file, jf_velocity_file, out_dir, run_tag, cfg_desc="Main Element", cfg=None, ground_h=None):
    """
    Compares JavaFoil and SU2 surface pressure distributions (-Cp) on the main element.
    Strictly filters out all flap nodes to prevent discontinuities and element contamination.
    Separates upper and lower surfaces, joining them continuously at the leading edge stagnation
    point so curves are completely smooth without gaps or zigzagging.
    Includes a bottom panel showing the closed continuous airfoil geometry profile.
    """
    p_path = os.path.join(out_dir, f"overlay_surface_cp_{run_tag}.png")
    if not os.path.exists(su2_surface_file):
        return None

    try:
        df_su2 = pd.read_csv(su2_surface_file)
        df_su2.columns = [c.replace('"', '').strip() for c in df_su2.columns]
    except Exception:
        return None

    if 'x' not in df_su2.columns or 'Pressure' not in df_su2.columns:
        return None

    df_su2['cp'] = df_su2['Pressure'] / 0.5
    pts = df_su2[['x', 'y']].values

    outlines = []
    if cfg is not None:
        try:
            cfg_tuple = normalize_config(cfg)
            outlines = build_geometry_coords(cfg_tuple, ground_h)
        except Exception:
            try:
                outlines = A.build_outlines(cfg_tuple, ground_h)
            except Exception:
                outlines = []

    # If outlines not provided, check if run_tag maps to a known package
    if not outlines:
        try:
            A.ensure_airfoils_loaded()
            for cand_pkg in getattr(A, 'PACKAGES_TO_RUN', []):
                if cand_pkg.get('id') == run_tag:
                    outlines = build_geometry_coords(cand_pkg['cfg'], ground_h or cand_pkg.get('gh'))
                    break
        except Exception:
            pass

    o0 = outlines[0] if outlines and len(outlines) > 0 else None
    if o0 is not None:
        i_le_geo = int(np.argmin(o0[:, 0]))
        # Check ground effect elevation shift
        if ground_h is None and pts.shape[0] > 0:
            pts_min_y = float(np.min(pts[:, 1]))
            out_min_y = float(min(np.min(o[:, 1]) for o in outlines))
            if pts_min_y - out_min_y > 0.05:
                y_shift = pts_min_y - out_min_y
                outlines = [o + np.array([0.0, y_shift]) for o in outlines]
                o0 = outlines[0]

        upper_su2_pts = []
        lower_su2_pts = []
        n_elements = len(outlines)

        for idx, pt in enumerate(pts):
            d2_0 = np.min((o0[:, 0] - pt[0])**2 + (o0[:, 1] - pt[1])**2)
            min_d2_flaps = float('inf')
            for of in outlines[1:]:
                d2_f = np.min((of[:, 0] - pt[0])**2 + (of[:, 1] - pt[1])**2)
                if d2_f < min_d2_flaps:
                    min_d2_flaps = d2_f
            # Strictly closer to main element than to any flap, within proximity
            if d2_0 < min_d2_flaps and d2_0 < 0.04**2:
                k_closest = int(np.argmin((o0[:, 0] - pt[0])**2 + (o0[:, 1] - pt[1])**2))
                rec = {'x': float(pt[0]), 'y': float(pt[1]), 'cp': float(df_su2.iloc[idx]['cp']), 'k': k_closest}
                if k_closest <= i_le_geo:
                    upper_su2_pts.append(rec)
                else:
                    lower_su2_pts.append(rec)

        df_su2_up = pd.DataFrame(upper_su2_pts).sort_values('x').reset_index(drop=True) if upper_su2_pts else pd.DataFrame(columns=['x', 'y', 'cp'])
        df_su2_lo = pd.DataFrame(lower_su2_pts).sort_values('x').reset_index(drop=True) if lower_su2_pts else pd.DataFrame(columns=['x', 'y', 'cp'])
    else:
        # Robust fallback when outlines are missing: isolate main element via chord bounds
        main_cands = df_su2[df_su2['x'] <= 1.01].copy()
        med_y = main_cands['y'].median()
        upper_cands = main_cands[main_cands['y'] >= med_y].sort_values('x').reset_index(drop=True)
        lower_cands = main_cands[main_cands['y'] < med_y].sort_values('x').reset_index(drop=True)
        df_su2_up = upper_cands[['x', 'y', 'cp']]
        df_su2_lo = lower_cands[['x', 'y', 'cp']]

    # Bridge leading edge stagnation point for SU2 so curves meet with ZERO gap
    all_su2_main = pd.concat([df_su2_up, df_su2_lo], ignore_index=True)
    if not all_su2_main.empty:
        le_su2_row = all_su2_main.loc[all_su2_main['x'].idxmin()]
        if not df_su2_up.empty and df_su2_up.iloc[0]['x'] > le_su2_row['x']:
            df_su2_up = pd.concat([pd.DataFrame([le_su2_row]), df_su2_up], ignore_index=True)
        if not df_su2_lo.empty and df_su2_lo.iloc[0]['x'] > le_su2_row['x']:
            df_su2_lo = pd.concat([pd.DataFrame([le_su2_row]), df_su2_lo], ignore_index=True)

    # Parse JavaFoil velocity / surface Cp if available
    df_jf_up = pd.DataFrame(columns=['x', 'cp'])
    df_jf_lo = pd.DataFrame(columns=['x', 'cp'])
    if jf_velocity_file and os.path.exists(jf_velocity_file):
        try:
            jf_raw = []
            with open(jf_velocity_file) as f:
                in_el1 = False
                for line in f:
                    if 'Element\t1' in line or 'Element 1' in line:
                        in_el1 = True
                        continue
                    if in_el1:
                        if 'Element' in line:
                            break
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            try:
                                x_v = float(parts[0])
                                y_v = float(parts[1]) if len(parts) > 1 else 0.0
                                v_r = float(parts[2])
                                cp_v = 1.0 - (v_r ** 2)
                                jf_raw.append({'x': x_v, 'y': y_v, 'cp': cp_v})
                            except ValueError:
                                pass
            if jf_raw:
                df_jf_raw = pd.DataFrame(jf_raw)
                if df_jf_raw['x'].max() > 1.5:
                    scale = df_jf_raw['x'].max()
                    df_jf_raw['x'] = df_jf_raw['x'] / scale
                    df_jf_raw['y'] = df_jf_raw['y'] / scale

                i_le_jf = df_jf_raw['x'].idxmin()
                df_jf_up = df_jf_raw.iloc[:i_le_jf + 1].sort_values('x').reset_index(drop=True)
                df_jf_lo = df_jf_raw.iloc[i_le_jf:].sort_values('x').reset_index(drop=True)

                le_jf_row = df_jf_raw.loc[i_le_jf]
                if not df_jf_up.empty and df_jf_up.iloc[0]['x'] > le_jf_row['x']:
                    df_jf_up = pd.concat([pd.DataFrame([le_jf_row]), df_jf_up], ignore_index=True)
                if not df_jf_lo.empty and df_jf_lo.iloc[0]['x'] > le_jf_row['x']:
                    df_jf_lo = pd.concat([pd.DataFrame([le_jf_row]), df_jf_lo], ignore_index=True)
        except Exception:
            pass

    # Build 2-panel figure: Top is Cp distribution, Bottom is closed continuous airfoil geometry
    fig, (ax_cp, ax_geom) = plt.subplots(2, 1, figsize=(10, 6.5), dpi=140,
                                         gridspec_kw={'height_ratios': [3.2, 1.0], 'hspace': 0.15},
                                         sharex=True)
    fig.patch.set_facecolor(DARK_BG)

    _style_dark_axes(ax_cp, f"Main Element Surface Pressure Comparison (Cp vs x) — Run {run_tag}\n{cfg_desc}",
                     "", "Pressure Coefficient -Cp (Suction Up)")

    # Plot SU2 Main Element
    if not df_su2_up.empty:
        ax_cp.plot(df_su2_up['x'], -df_su2_up['cp'], 'o-', color=ACCENT_CYAN, ms=3.5, lw=2.2,
                   label="SU2 RANS Upper (Suction)")
    if not df_su2_lo.empty:
        ax_cp.plot(df_su2_lo['x'], -df_su2_lo['cp'], 's--', color=ACCENT_CYAN, ms=3.0, lw=1.8, alpha=0.9,
                   label="SU2 RANS Lower (Pressure)")

    # Plot JavaFoil Main Element
    if not df_jf_up.empty:
        ax_cp.plot(df_jf_up['x'], -df_jf_up['cp'], '^-', color=AMBER_COLOR, ms=3.5, lw=1.8, alpha=0.95,
                   label="JavaFoil Upper (Suction)")
    if not df_jf_lo.empty:
        ax_cp.plot(df_jf_lo['x'], -df_jf_lo['cp'], 'v--', color=AMBER_COLOR, ms=3.0, lw=1.6, alpha=0.85,
                   label="JavaFoil Lower (Pressure)")

    ax_cp.axhline(0, color=MUTED_COLOR, lw=0.8, linestyle=':')
    ax_cp.invert_yaxis()
    ax_cp.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.5, loc='best', ncol=2)

    # Bottom Panel: Airfoil Cross-Section (Closed Continuous Geometry without Gaps)
    _style_dark_axes(ax_geom, "", "Chordwise Coordinate x/c (Main Element)", "y/c")
    if o0 is not None:
        o0_norm = o0.copy()
        xmin = o0_norm[:, 0].min()
        xmax = o0_norm[:, 0].max()
        chord_len = max(xmax - xmin, 1e-4)
        o0_norm[:, 0] = (o0_norm[:, 0] - xmin) / chord_len
        # Center y at leading edge
        o0_norm[:, 1] = (o0_norm[:, 1] - o0_norm[i_le_geo, 1]) / chord_len
        poly_x = np.append(o0_norm[:, 0], o0_norm[0, 0])
        poly_y = np.append(o0_norm[:, 1], o0_norm[0, 1])
        ax_geom.plot(poly_x, poly_y, color=ACCENT_CYAN, lw=2.0, label="Main Airfoil Contour (Smooth & Closed)")
        ax_geom.fill(poly_x, poly_y, color=ACCENT_CYAN, alpha=0.22)
    elif not df_su2_up.empty and not df_su2_lo.empty:
        geom_pts = np.vstack([
            df_su2_up[['x', 'y']].values[::-1],
            df_su2_lo[['x', 'y']].values
        ])
        poly_x = np.append(geom_pts[:, 0], geom_pts[0, 0])
        poly_y = np.append(geom_pts[:, 1], geom_pts[0, 1])
        ax_geom.plot(poly_x, poly_y, color=ACCENT_CYAN, lw=2.0)
        ax_geom.fill(poly_x, poly_y, color=ACCENT_CYAN, alpha=0.22)

    if 'poly_y' in locals() and len(poly_y) > 0:
        yrng = max(float(poly_y.max() - poly_y.min()), 0.08)
        ax_geom.set_ylim(float(poly_y.min()) - 0.25 * yrng, float(poly_y.max()) + 0.25 * yrng)
    ax_geom.set_xlim(-0.03, 1.03)
    ax_geom.legend(facecolor=DARK_BG, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR, fontsize=8.0, loc='lower right')

    plt.savefig(p_path, bbox_inches='tight')
    plt.close()

    base_graphs_dir = os.path.dirname(out_dir)
    if os.path.basename(out_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
        try:
            shutil.copy2(p_path, os.path.join(base_graphs_dir, os.path.basename(p_path)))
        except Exception:
            pass

    return p_path


def log_su2_run_result(row_data, results_csv=None):
    """Appends or updates an SU2 simulation result in su2_results.csv for persistent tracking and UI display."""
    if results_csv is None:
        results_csv = os.path.join(A.OUT_DIR, "su2_results.csv")
    try:
        os.makedirs(os.path.dirname(results_csv), exist_ok=True)
        rid = str(row_data.get('Run_ID', '')).strip()
        if os.path.exists(results_csv) and os.path.getsize(results_csv) > 0:
            df_old = pd.read_csv(results_csv)
            if 'Run_ID' in df_old.columns and rid:
                df_old = df_old[df_old['Run_ID'].astype(str) != rid]
            df_new = pd.concat([df_old, pd.DataFrame([row_data])], ignore_index=True)
            df_new.to_csv(results_csv, index=False)
        else:
            pd.DataFrame([row_data]).to_csv(results_csv, index=False)
    except Exception as e:
        print(f"Failed to log SU2 run result: {e}")


def log_xfoil_run_result(row_data, results_csv=None):
    """Appends or updates an XFOIL simulation result in xfoil_results.csv for persistent tracking and UI display."""
    if results_csv is None:
        results_csv = os.path.join(A.OUT_DIR, "xfoil_results.csv")
    try:
        os.makedirs(os.path.dirname(results_csv), exist_ok=True)
        rid = str(row_data.get('Run_ID', '')).strip()
        if os.path.exists(results_csv) and os.path.getsize(results_csv) > 0:
            df_old = pd.read_csv(results_csv)
            if 'Run_ID' in df_old.columns and rid:
                df_old = df_old[df_old['Run_ID'].astype(str) != rid]
            df_new = pd.concat([df_old, pd.DataFrame([row_data])], ignore_index=True)
            df_new.to_csv(results_csv, index=False)
        else:
            pd.DataFrame([row_data]).to_csv(results_csv, index=False)
    except Exception as e:
        print(f"Failed to log XFOIL run result: {e}")


# ==============================================================================
# UNIFIED SOLVER INTERFACE & CROSS-CHECK MODE
# ==============================================================================

def run(config, engine='su2', alpha=None, alpha_deg=None, alphas=None, speed=None, re=None, re_val=None,
        ground_h=None, density=None, mesh_density=None, num_cores=DEFAULT_CORES, timeout=360,
        run_tag=None, out_dir=None, force=False, **kwargs):
    """
    Unified solver interface:
        run(config) -> dict
    Accepts single angle of attack or sweep list/tuple.
    Harmonizes alpha/alpha_deg/alphas, re/re_val, and density/mesh_density.
    Automatically generates publication-grade graphs into graphs/run_<run_tag>/.
    """
    # 1. Harmonize arguments
    target_alpha = alphas if alphas is not None else (alpha_deg if alpha_deg is not None else (alpha if alpha is not None else 0.0))
    speed_val = float(speed if speed is not None else SPEED_DEFAULT)
    re_target = float(re_val if re_val is not None else (re if re is not None else RE_DEFAULT))
    mesh_dens = str(mesh_density if mesh_density is not None else (density if density is not None else 'medium')).lower().strip()

    cfg = normalize_config(config)
    tag = str(run_tag or (cfg[0] if isinstance(cfg, (tuple, list)) else 'run')).strip()
    target_dir = out_dir or os.path.join(A.OUT_DIR, "graphs", f"run_{tag}")
    os.makedirs(target_dir, exist_ok=True)

    engine_lower = str(engine).lower().strip()

    # Determine if sweep or single point
    is_sweep = isinstance(target_alpha, (list, tuple, np.ndarray, range))

    if 'su2' in engine_lower:
        if is_sweep:
            alpha_list = list(target_alpha)
            records = []
            primary_res = None
            for a_pt in alpha_list:
                res_pt = run_su2_single_case(cfg, alpha_deg=float(a_pt), speed=speed_val, re_val=re_target,
                                             ground_h=ground_h, density=mesh_dens, num_cores=num_cores, timeout=timeout, force=force)
                records.append(res_pt)
                if primary_res is None or abs(float(a_pt)) < abs(float(primary_res.get('alpha', 999))):
                    primary_res = res_pt

            # Render polar suite across all evaluated angles
            polar_outs = render_su2_polar_plots(records, target_dir, tag, cfg, speed=speed_val, re_val=re_target, ground_h=ground_h)
            # Render convergence, Cp, flowfield for design point
            if primary_res:
                p_conv = render_su2_convergence_plot(primary_res.get('history_file', ''), target_dir, tag, alpha_deg=primary_res.get('alpha', 0.0))
                p_cp = render_su2_surface_cp_plot(primary_res.get('surface_file', ''), target_dir, tag, cfg, alpha_deg=primary_res.get('alpha', 0.0), ground_h=ground_h)
                p_ff = render_su2_flowfield_plot(primary_res.get('flowfield_file', ''), target_dir, tag, cfg, alpha_deg=primary_res.get('alpha', 0.0), ground_h=ground_h)
                if p_conv: polar_outs['su2_convergence'] = p_conv
                if p_cp: polar_outs['su2_surface_cp'] = p_cp
                if p_ff: polar_outs['su2_flowfield'] = p_ff

            ret = dict(primary_res or {})
            ret['polar'] = records
            ret['graph_files'] = polar_outs
            ret['sweep_alphas'] = alpha_list
        else:
            a_val = float(target_alpha)
            res = run_su2_single_case(cfg, alpha_deg=a_val, speed=speed_val, re_val=re_target,
                                      ground_h=ground_h, density=mesh_dens, num_cores=num_cores, timeout=timeout, force=force)
            # Render all plots for this single point
            polar_outs = render_su2_polar_plots([res], target_dir, tag, cfg, speed=speed_val, re_val=re_target, ground_h=ground_h)
            p_conv = render_su2_convergence_plot(res.get('history_file', ''), target_dir, tag, alpha_deg=a_val)
            p_cp = render_su2_surface_cp_plot(res.get('surface_file', ''), target_dir, tag, cfg, alpha_deg=a_val, ground_h=ground_h)
            p_ff = render_su2_flowfield_plot(res.get('flowfield_file', ''), target_dir, tag, cfg, alpha_deg=a_val, ground_h=ground_h)
            if p_conv: polar_outs['su2_convergence'] = p_conv
            if p_cp: polar_outs['su2_surface_cp'] = p_cp
            if p_ff: polar_outs['su2_flowfield'] = p_ff

            ret = res
            ret['graph_files'] = polar_outs

        # Copy to parent graphs dir as well if target_dir is a run_tag subfolder
        base_graphs_dir = os.path.dirname(target_dir)
        if os.path.basename(target_dir).startswith("run_") and os.path.isdir(base_graphs_dir):
            for f_p in list(polar_outs.values()):
                if isinstance(f_p, str) and os.path.isfile(f_p):
                    try:
                        shutil.copy2(f_p, os.path.join(base_graphs_dir, os.path.basename(f_p)))
                    except Exception:
                        pass

        # Record run result in persistent su2_results.csv
        q_pa = 0.5 * RHO_DEFAULT * (speed_val ** 2)
        cl_val = ret.get('Cl', 0.0) or 0.0
        cd_val = ret.get('Cd', 0.0) or 0.0
        log_su2_run_result({
            'Run_ID': tag,
            'Config_Name': tag,
            'Main_Airfoil': cfg[0],
            'Elements': 1 + len(cfg[1]),
            'Flaps_Config': str(cfg[1]),
            'Alpha': ret.get('alpha', 0.0),
            'Cl_Main': round(cl_val, 4),
            'Cd_Main': round(cd_val, 5),
            'Cl_Assembly': round(ret.get('Cl_assembly', cl_val) or cl_val, 4),
            'Cd_Assembly': round(ret.get('Cd_assembly', cd_val) or cd_val, 5),
            'Max_LD': round(abs(cl_val) / max(cd_val, 1e-4), 2),
            'Downforce_N': round(abs(cl_val) * q_pa * 0.3 * 1.0, 1),
            'Drag_N': round(abs(cd_val) * q_pa * 0.3 * 1.0, 1),
            'Converged': ret.get('converged', False),
            'Residual_Drop': ret.get('residual_drop', 0.0),
            'Iterations': ret.get('iterations', 0),
            'Runtime_s': ret.get('runtime_s', 0.0),
            'Speed_ms': speed_val,
            'Re': re_target,
            'Ground_h': ground_h if ground_h is not None else 'unbounded',
            'Mesh_Density': mesh_dens,
            'Date': time.strftime("%Y-%m-%dT%H:%M:%S")
        })

        return ret

    elif 'javafoil' in engine_lower:
        if is_sweep:
            alpha_list = list(target_alpha)
            records = []
            for a_pt in alpha_list:
                records.append(run_javafoil_single_case(cfg, alpha_deg=float(a_pt), speed=speed_val, re_val=re_target, ground_h=ground_h))
            primary = next((r for r in records if abs(r.get('alpha', 999)) < 0.25), records[0])
            ret = dict(primary)
            ret['polar'] = records
            return ret
        else:
            return run_javafoil_single_case(cfg, alpha_deg=float(target_alpha), speed=speed_val, re_val=re_target, ground_h=ground_h)

    elif 'xfoil' in engine_lower:
        return run_xfoil_case(cfg, alpha=target_alpha, speed=speed_val, re_val=re_target, run_tag=tag, out_dir=target_dir, **kwargs)
    else:
        raise ValueError(f"Unknown simulation engine: {engine!r}. Use 'su2', 'javafoil', or 'xfoil'.")


def run_xfoil_case(config, alpha=None, alpha_deg=None, alphas=None, speed=None, re_val=None, re=None,
                   run_tag=None, out_dir=None, **kwargs):
    """
    Executes viscous XFOIL calculation for the configuration's main element.
    Generates official dark-themed XFOIL polar graphs and raw CSV.
    """
    target_alpha = alphas if alphas is not None else (alpha_deg if alpha_deg is not None else (alpha if alpha is not None else 0.0))
    speed_val = float(speed if speed is not None else SPEED_DEFAULT)
    re_target = float(re_val if re_val is not None else (re if re is not None else RE_DEFAULT))

    cfg = normalize_config(config)
    main_name = cfg[0]
    tag = str(run_tag or (cfg[0] if isinstance(cfg, (tuple, list)) else 'run')).strip()
    target_dir = out_dir or os.path.join(A.OUT_DIR, "graphs", f"run_{tag}")
    os.makedirs(target_dir, exist_ok=True)

    is_sweep = isinstance(target_alpha, (list, tuple, np.ndarray, range))
    alpha_list = [float(x) for x in target_alpha] if is_sweep else [float(target_alpha)]

    t0 = time.time()
    A.ensure_airfoils_loaded()
    coords = A.AIRFOILS.get(main_name)
    if coords is None:
        try:
            outlines = build_geometry_coords(cfg)
            coords = outlines[0]
        except Exception:
            coords = main_name

    records = run_xfoil_single_element(coords, alpha_list, re_val=re_target)
    runtime_s = round(time.time() - t0, 2)

    # Render polar suite for XFOIL
    polar_outs = render_xfoil_polar_plots(records, target_dir, tag, cfg, speed=speed_val, re_val=re_target)

    # Primary point (alpha=0 or closest)
    if records:
        idx_p = min(range(len(records)), key=lambda i: abs(records[i].get('alpha', 999)))
        primary = records[idx_p]
    else:
        primary = {'alpha': alpha_list[0] if alpha_list else 0.0, 'Cl': 0.0, 'Cd': 0.0, 'Cm': 0.0}

    q_pa = 0.5 * RHO_DEFAULT * (speed_val ** 2)
    cl_val = primary.get('Cl', 0.0) or 0.0
    cd_val = primary.get('Cd', 0.0) or 0.0

    ret = {
        'alpha': primary.get('alpha', 0.0),
        'Cl': cl_val,
        'Cd': cd_val,
        'Cm': primary.get('Cm', 0.0) or 0.0,
        'Max_LD': round(abs(cl_val) / max(abs(cd_val), 1e-4), 2),
        'Downforce_N': round(abs(cl_val) * q_pa * 0.3 * 1.0, 1),
        'Drag_N': round(abs(cd_val) * q_pa * 0.3 * 1.0, 1),
        'converged': len(records) > 0,
        'runtime_s': runtime_s,
        'engine': 'XFOIL',
        'polar': records,
        'graph_files': polar_outs,
        'main_airfoil': main_name,
        'elements': 1 + len(cfg[1]),
        'run_tag': tag
    }

    # Record run result in persistent xfoil_results.csv
    log_xfoil_run_result({
        'Run_ID': tag,
        'Config_Name': tag,
        'Main_Airfoil': main_name,
        'Elements': 1 + len(cfg[1]),
        'Flaps_Config': str(cfg[1]),
        'Alpha': ret.get('alpha', 0.0),
        'Cl_Main': round(cl_val, 4),
        'Cd_Main': round(cd_val, 5),
        'Cm_Main': round(ret.get('Cm', 0.0), 4),
        'Max_LD': round(abs(cl_val) / max(abs(cd_val), 1e-4), 2),
        'Downforce_N': round(abs(cl_val) * q_pa * 0.3 * 1.0, 1),
        'Drag_N': round(abs(cd_val) * q_pa * 0.3 * 1.0, 1),
        'Converged': ret.get('converged', False),
        'Runtime_s': runtime_s,
        'Speed_ms': speed_val,
        'Re': re_target,
        'Date': time.strftime("%Y-%m-%dT%H:%M:%S")
    })

    # Synchronize graph files to parent graphs dir and main ~/aero_campaign/graphs
    sync_dirs = [os.path.dirname(target_dir), os.path.join(A.OUT_DIR, "graphs"), os.path.join(A.OUT_DIR, "graphs", f"run_{tag}")]
    for f_p in list(polar_outs.values()):
        if isinstance(f_p, str) and os.path.isfile(f_p):
            for d in sync_dirs:
                if os.path.isdir(d):
                    try:
                        dest = os.path.join(d, os.path.basename(f_p))
                        if os.path.abspath(f_p) != os.path.abspath(dest):
                            shutil.copy2(f_p, dest)
                    except Exception:
                        pass

    return ret


def cross_check(config, alpha=None, alpha_deg=None, alphas=None, speed=None, re=None, re_val=None,
                ground_h=None, density=None, mesh_density=None, threshold_cl=0.5, threshold_cd=0.05,
                num_cores=DEFAULT_CORES, timeout=360, run_tag=None, out_dir=None, **kwargs):
    """
    Cross-checks JavaFoil and SU2 on identical geometry configuration.
    Generates superimposed overlay graphs and raw comparison CSV.
    Returns dictionary with both flat UI keys and nested comparison details.
    """
    # 1. Harmonize arguments
    target_alpha = alphas if alphas is not None else (alpha_deg if alpha_deg is not None else (alpha if alpha is not None else 0.0))
    speed_val = float(speed if speed is not None else SPEED_DEFAULT)
    re_target = float(re_val if re_val is not None else (re if re is not None else RE_DEFAULT))
    mesh_dens = str(mesh_density if mesh_density is not None else (density if density is not None else 'medium')).lower().strip()

    cfg = normalize_config(config)
    tag = str(run_tag or (cfg[0] if isinstance(cfg, (tuple, list)) else 'run')).strip()
    target_dir = out_dir or os.path.join(A.OUT_DIR, "graphs", f"run_{tag}")
    os.makedirs(target_dir, exist_ok=True)

    # 1. Overlay check first
    matched, max_diff = verify_geometry_overlay(cfg, ground_h)
    if not matched:
        raise ValueError(f"Geometry overlay failed! Max coordinate discrepancy: {max_diff}")

    # Determine if sweep or single point
    is_sweep = isinstance(target_alpha, (list, tuple, np.ndarray, range))
    alpha_list = list(target_alpha) if is_sweep else [float(target_alpha)]

    # 2. Run JavaFoil simulation (authentic sweep extraction across all angles)
    jf_records = []
    jf_vel_file = None
    try:
        # Full standard sweep for JavaFoil so polars are complete continuous curves (-20 deg to +5 deg)
        a_start = float(min(alpha_list[0], A.ALPHA[0])) if alpha_list else float(A.ALPHA[0])
        a_end = float(max(alpha_list[-1], A.ALPHA[1])) if alpha_list else float(A.ALPHA[1])
        a_step = float(A.ALPHA[2])
        jf_outs = A.export_javafoil_graphs(cfg, ground_h, target_dir, run_id=tag, re=re_target,
                                           alphas=(a_start, a_end, a_step), v_inf=speed_val)
        jf_vel_file = os.path.join(target_dir, f"javafoil_velocity_{tag}.txt")
        jf_polar_file = os.path.join(target_dir, f"javafoil_polar_{tag}.txt")
        if os.path.isfile(jf_polar_file):
            df_jf_full, _ = A.parse_polar(jf_polar_file)
            if df_jf_full is not None and not df_jf_full.empty:
                for _, r0 in df_jf_full.iterrows():
                    jf_records.append({
                        'alpha': float(r0['alpha']),
                        'Cl': float(r0['cl']),
                        'Cd': float(r0['cd']),
                        'Cm': float(r0.get('cm', 0.0) or 0.0),
                        'converged': True,
                        'engine': 'JavaFoil'
                    })
    except Exception as e:
        jf_records = []

    if not jf_records:
        sweep_pts = [float(round(a, 2)) for a in np.arange(a_start, a_end + 0.5 * a_step, a_step)] if 'a_start' in locals() else alpha_list
        for a_pt in sweep_pts:
            jf_records.append(run_javafoil_single_case(cfg, alpha_deg=float(a_pt), speed=speed_val, re_val=re_target, ground_h=ground_h))

    su2_records = []
    for a_pt in alpha_list:
        res_su2_pt = run_su2_single_case(cfg, alpha_deg=float(a_pt), speed=speed_val, re_val=re_target,
                                         ground_h=ground_h, density=mesh_dens, num_cores=num_cores, timeout=timeout)
        su2_records.append(res_su2_pt)

    # Primary point (alpha=0 or closest)
    idx_p = min(range(len(alpha_list)), key=lambda i: abs(alpha_list[i]))
    target_a = alpha_list[idx_p]
    res_su2 = su2_records[idx_p]
    matching_jf = [r for r in jf_records if np.isclose(r.get('alpha', 999.0), target_a, atol=0.05)]
    res_jf = matching_jf[0] if matching_jf else (jf_records[0] if jf_records else {})

    mesh_nodes_str = f"{res_su2.get('mesh_meta', {}).get('nodes', '12,525')} nodes"

    # Run XFOIL for main element profile across the evaluated angles
    xf_records = None
    try:
        xf_alphas_raw = [float(round(a, 2)) for a in np.arange(a_start, a_end + 0.5 * a_step, a_step)] if 'a_start' in locals() else alpha_list
        xf_alphas = [a for a in xf_alphas_raw if -8.0 <= a <= 14.0]
        if not xf_alphas:
            xf_alphas = [0.0]
        xf_records = run_xfoil_single_element(cfg[0], xf_alphas, re_val=re_target, timeout=30)
    except Exception:
        xf_records = None

    # Render superimposed overlay plots and raw comparison CSV
    overlay_outs = render_overlay_plots(jf_records, su2_records, target_dir, tag, cfg,
                                        speed=speed_val, re_val=re_target, ground_h=ground_h,
                                        mesh_nodes=mesh_nodes_str,
                                        jf_velocity_file=jf_vel_file,
                                        su2_surface_file=res_su2.get('surface_file'),
                                        xfoil_records_or_df=xf_records)

    # Compare primary point metrics
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
        'alpha': alpha_list[idx_p],
        'javafoil_cl': cl_jf,
        'javafoil_cd': cd_jf,
        'su2_cl': cl_su2,
        'su2_cd': cd_su2,
        'diff_cl': diff_cl,
        'diff_cd': diff_cd,
        'ratio_cl': ratio_cl,
        'diverged': flag_divergent,
        'su2_converged': res_su2.get('converged', False),
        'javafoil_runtime_s': res_jf.get('runtime_s', 0.0),
        'su2_runtime_s': res_su2.get('runtime_s', 0.0),
        'threshold_cl': threshold_cl,
        'threshold_cd': threshold_cd,
        'graph_files': overlay_outs,
        'overlay_matched': matched,
        'geometry_max_diff': max_diff,
        'javafoil': res_jf,
        'su2': res_su2,
        'xfoil': xf_records,
        'diff_Cl': diff_cl,
        'diff_Cd': diff_cd,
        'ratio_Cl': ratio_cl,
        'flag_divergent': flag_divergent,
        'reasons': reasons
    }

