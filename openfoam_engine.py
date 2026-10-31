#!/usr/bin/env python3
"""
openfoam_engine.py
==================
OpenFOAM-13 Simulation Engine for Aero_Auto.
Implements automated 2D RANS (k-omega SST) simulation using:
  - Gmsh Python API for physical-scale 2D mesh generation + 1-cell 3D extrusion
  - gmshToFoam for OpenFOAM polyMesh generation
  - foamRun -solver incompressibleFluid (OpenFOAM-13 SIMPLE solver)
  - Extraction of true aerodynamic forces and coefficients (both assembly and mainplane reference)
"""

import os
import sys
import math
import time
import shutil
import hashlib
import subprocess
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

OPENFOAM_DIR = "/opt/OpenFOAM/OpenFOAM-13"
OPENFOAM_BASHRC = os.path.join(OPENFOAM_DIR, "etc", "bashrc")
FOAM_RUN_BIN = os.path.join(OPENFOAM_DIR, "platforms", "linux64GccDPInt32Opt", "bin", "foamRun")
GMSH_TO_FOAM_BIN = os.path.join(OPENFOAM_DIR, "platforms", "linux64GccDPInt32Opt", "bin", "gmshToFoam")

RUNS_DIR = os.path.join(HERE, "runs", "openfoam_runs")
os.makedirs(RUNS_DIR, exist_ok=True)

RHO_DEFAULT = 1.225
NU_DEFAULT = 1.48e-5

def hash_config(cfg, alpha, speed, chord_mm):
    key = f"{repr(cfg)}_{alpha:.2f}_{speed:.2f}_{chord_mm:.1f}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:12]

def generate_openfoam_mesh(outlines_m, case_dir, density='coarse', farfield_radius_m=8.0, span_depth_m=0.05):
    """
    Generates a 3D 1-cell extruded mesh for OpenFOAM using Gmsh with physical dimensions in meters,
    converts it with gmshToFoam, and sets 'empty' boundary conditions
    on front and back patches.
    """
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 0)
    gmsh.model.add("openfoam_airfoil")

    all_pts = np.vstack(outlines_m)
    xmin, xmax = all_pts[:, 0].min(), all_pts[:, 0].max()
    ymin, ymax = all_pts[:, 1].min(), all_pts[:, 1].max()
    chord_total_m = xmax - xmin
    x_c = 0.5 * (xmin + xmax)
    y_c = 0.5 * (ymin + ymax)

    # Scale mesh element sizes proportionally to physical chord
    scale = chord_total_m / 0.5
    factors = {
        'coarse': (0.003 * scale, 0.006 * scale, 0.8 * scale),
        'medium': (0.0015 * scale, 0.003 * scale, 0.5 * scale),
        'fine':   (0.0008 * scale, 0.0015 * scale, 0.3 * scale)
    }
    le_size, te_size, far_size = factors.get(density, factors['coarse'])

    element_loops = []

    for elem_idx, o in enumerate(outlines_m):
        o = np.asarray(o, dtype=float)
        if len(o) > 2 and np.linalg.norm(o[0] - o[-1]) < 1e-6:
            o = o[:-1]
        mask = [True] + [np.linalg.norm(o[i] - o[i-1]) > 1e-7 for i in range(1, len(o))]
        o = o[mask]

        # Ensure counter-clockwise ordering for outer boundary of hole
        area = 0.5 * np.sum(o[:, 0] * np.roll(o[:, 1], -1) - o[:, 1] * np.roll(o[:, 0], -1))
        if area > 0:
            o = o[::-1]

        n_pts = len(o)
        point_tags = []
        for i in range(n_pts):
            pt = o[i]
            x_norm = (pt[0] - o[:, 0].min()) / max(o[:, 0].max() - o[:, 0].min(), 1e-6)
            if x_norm < 0.08:
                cl_size = le_size
            elif x_norm > 0.85:
                cl_size = te_size
            else:
                cl_size = 0.5 * (le_size + te_size)
            p_tag = gmsh.model.geo.addPoint(pt[0], pt[1], 0.0, cl_size)
            point_tags.append(p_tag)

        curve_tags = []
        for i in range(n_pts):
            p1 = point_tags[i]
            p2 = point_tags[(i + 1) % n_pts]
            line_tag = gmsh.model.geo.addLine(p1, p2)
            curve_tags.append(line_tag)

        loop_tag = gmsh.model.geo.addCurveLoop(curve_tags)
        element_loops.append(loop_tag)

    # Farfield circle boundary
    r = farfield_radius_m
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

    # Extrude 1 cell in Z for 2D OpenFOAM
    dz = span_depth_m
    ext = gmsh.model.geo.extrude([(2, surface)], 0, 0, dz, [1], recombine=True)
    gmsh.model.geo.synchronize()

    back_surface = ext[0][1]
    fluid_volume = ext[1][1]
    side_surfs = [e[1] for e in ext[2:] if e[0] == 2]

    wing_surfs = []
    inlet_surfs = []
    outlet_surfs = []

    for surf in side_surfs:
        bbox = gmsh.model.getBoundingBox(2, surf)
        cx = 0.5 * (bbox[0] + bbox[3])
        cy = 0.5 * (bbox[1] + bbox[4])
        dist = np.hypot(cx - x_c, cy - y_c)
        if dist < 0.4 * r:
            wing_surfs.append(surf)
        elif cx <= x_c:
            inlet_surfs.append(surf)
        else:
            outlet_surfs.append(surf)

    # Physical Groups
    gmsh.model.addPhysicalGroup(3, [fluid_volume], 1, "fluid")
    gmsh.model.addPhysicalGroup(2, [surface], 2, "front")
    gmsh.model.addPhysicalGroup(2, [back_surface], 3, "back")
    gmsh.model.addPhysicalGroup(2, wing_surfs, 4, "wing")
    gmsh.model.addPhysicalGroup(2, inlet_surfs, 5, "inlet")
    gmsh.model.addPhysicalGroup(2, outlet_surfs, 6, "outlet")

    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.model.mesh.generate(3)

    msh_path = os.path.join(case_dir, "mesh.msh")
    gmsh.write(msh_path)
    gmsh.finalize()

    # Run gmshToFoam
    cmd = f"source {OPENFOAM_BASHRC} && {GMSH_TO_FOAM_BIN} {msh_path} -case {case_dir}"
    res = subprocess.run(cmd, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gmshToFoam failed: {res.stderr}")

    # Patch boundary file to make front and back empty
    boundary_path = os.path.join(case_dir, "constant", "polyMesh", "boundary")
    with open(boundary_path, "r") as f:
        content = f.read()

    content = content.replace("front\n    {\n        type            patch;", "front\n    {\n        type            empty;")
    content = content.replace("back\n    {\n        type            patch;", "back\n    {\n        type            empty;")
    content = content.replace("wing\n    {\n        type            patch;", "wing\n    {\n        type            wall;")
    
    with open(boundary_path, "w") as f:
        f.write(content)

    return dz, chord_total_m

def setup_openfoam_case(case_dir, speed_ms, alpha_deg, chord_m, span_depth_m=0.05, max_iters=250):
    os.makedirs(os.path.join(case_dir, "0"), exist_ok=True)
    os.makedirs(os.path.join(case_dir, "constant"), exist_ok=True)
    os.makedirs(os.path.join(case_dir, "system"), exist_ok=True)

    th = math.radians(alpha_deg)
    ux = speed_ms * math.cos(th)
    uy = speed_ms * math.sin(th)

    k_val = 0.01 * (speed_ms ** 2)
    omega_val = (k_val ** 0.5) / (0.09 * 0.1 * chord_m)

    # 1. 0/U
    with open(os.path.join(case_dir, "0", "U"), "w") as f:
        f.write(f"""/* OpenFOAM Field */
FoamFile {{ format ascii; class volVectorField; location "0"; object U; }}
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({ux:.4f} {uy:.4f} 0);
boundaryField
{{
    inlet {{ type fixedValue; value uniform ({ux:.4f} {uy:.4f} 0); }}
    outlet {{ type inletOutlet; inletValue uniform ({ux:.4f} {uy:.4f} 0); value uniform ({ux:.4f} {uy:.4f} 0); }}
    wing {{ type noSlip; }}
    front {{ type empty; }}
    back {{ type empty; }}
}}
""")

    # 2. 0/p
    with open(os.path.join(case_dir, "0", "p"), "w") as f:
        f.write("""/* OpenFOAM Field */
FoamFile { format ascii; class volScalarField; location "0"; object p; }
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
    inlet { type zeroGradient; }
    outlet { type fixedValue; value uniform 0; }
    wing { type zeroGradient; }
    front { type empty; }
    back { type empty; }
}
""")

    # 3. 0/k
    with open(os.path.join(case_dir, "0", "k"), "w") as f:
        f.write(f"""/* OpenFOAM Field */
FoamFile {{ format ascii; class volScalarField; location "0"; object k; }}
dimensions [0 2 -2 0 0 0 0];
internalField uniform {k_val:.4f};
boundaryField
{{
    inlet {{ type fixedValue; value uniform {k_val:.4f}; }}
    outlet {{ type inletOutlet; inletValue uniform {k_val:.4f}; value uniform {k_val:.4f}; }}
    wing {{ type kqRWallFunction; value uniform {k_val:.4f}; }}
    front {{ type empty; }}
    back {{ type empty; }}
}}
""")

    # 4. 0/omega
    with open(os.path.join(case_dir, "0", "omega"), "w") as f:
        f.write(f"""/* OpenFOAM Field */
FoamFile {{ format ascii; class volScalarField; location "0"; object omega; }}
dimensions [0 0 -1 0 0 0 0];
internalField uniform {omega_val:.4f};
boundaryField
{{
    inlet {{ type fixedValue; value uniform {omega_val:.4f}; }}
    outlet {{ type inletOutlet; inletValue uniform {omega_val:.4f}; value uniform {omega_val:.4f}; }}
    wing {{ type omegaWallFunction; value uniform {omega_val:.4f}; }}
    front {{ type empty; }}
    back {{ type empty; }}
}}
""")

    # 5. 0/nut
    with open(os.path.join(case_dir, "0", "nut"), "w") as f:
        f.write("""/* OpenFOAM Field */
FoamFile { format ascii; class volScalarField; location "0"; object nut; }
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
    wing { type nutkWallFunction; value uniform 0; }
    "(inlet|outlet)" { type calculated; value uniform 0; }
    "(front|back)" { type empty; }
}
""")

    # 6. constant/momentumTransport
    with open(os.path.join(case_dir, "constant", "momentumTransport"), "w") as f:
        f.write("""/* OpenFOAM Dict */
FoamFile { format ascii; class dictionary; location "constant"; object momentumTransport; }
simulationType RAS;
RAS
{
    model kOmegaSST;
    turbulence on;
    printCoeffs on;
}
""")

    # 7. constant/physicalProperties
    with open(os.path.join(case_dir, "constant", "physicalProperties"), "w") as f:
        f.write(f"""/* OpenFOAM Dict */
FoamFile {{ format ascii; class dictionary; location "constant"; object physicalProperties; }}
viscosityModel constant;
nu {NU_DEFAULT:e};
""")

    # 8. system/controlDict
    aref = chord_m * span_depth_m
    with open(os.path.join(case_dir, "system", "controlDict"), "w") as f:
        f.write(f"""/* OpenFOAM Dict */
FoamFile {{ format ascii; class dictionary; location "system"; object controlDict; }}
solver incompressibleFluid;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {max_iters};
deltaT 1;
writeControl timeStep;
writeInterval {max_iters};
purgeWrite 0;
writeFormat ascii;
writePrecision 6;
writeCompression off;
timeFormat general;
timePrecision 6;
runTimeModifiable true;

functions
{{
    forces
    {{
        type forces;
        libs ("libforces.so");
        writeControl timeStep;
        writeInterval 1;
        patches (wing);
        rho rhoInf;
        log true;
        rhoInf {RHO_DEFAULT};
        CofR (0 0 0);
    }}

    forceCoeffs
    {{
        type forceCoeffs;
        libs ("libforces.so");
        writeControl timeStep;
        writeInterval 1;
        patches (wing);
        rho rhoInf;
        log true;
        rhoInf {RHO_DEFAULT};
        liftDir (0 1 0);
        dragDir (1 0 0);
        CofR (0 0 0);
        pitchAxis (0 0 1);
        magUInf {speed_ms:.4f};
        lRef {chord_m:.4f};
        Aref {aref:.6f};
    }}
}}
""")

    # 9. system/fvSchemes
    with open(os.path.join(case_dir, "system", "fvSchemes"), "w") as f:
        f.write("""/* OpenFOAM Dict */
FoamFile { format ascii; class dictionary; location "system"; object fvSchemes; }
ddtSchemes { default steadyState; }
gradSchemes
{
    default Gauss linear;
    grad(p) Gauss linear;
    grad(U) Gauss linear;
}
divSchemes
{
    default none;
    div(phi,U) bounded Gauss linearUpwind grad(U);
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
""")

    # 10. system/fvSolution
    with open(os.path.join(case_dir, "system", "fvSolution"), "w") as f:
        f.write("""/* OpenFOAM Dict */
FoamFile { format ascii; class dictionary; location "system"; object fvSolution; }
solvers
{
    p
    {
        solver GAMG;
        tolerance 1e-6;
        relTol 0.05;
        smoother GaussSeidel;
    }
    U
    {
        solver smoothSolver;
        smoother GaussSeidel;
        tolerance 1e-7;
        relTol 0.05;
        nSweeps 1;
    }
    k
    {
        solver smoothSolver;
        smoother GaussSeidel;
        tolerance 1e-7;
        relTol 0.05;
        nSweeps 1;
    }
    omega
    {
        solver smoothSolver;
        smoother GaussSeidel;
        tolerance 1e-7;
        relTol 0.05;
        nSweeps 1;
    }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p 1e-4;
        U 1e-4;
        "(k|omega)" 1e-4;
    }
}
relaxationFactors
{
    fields { p 0.3; }
    equations { "(U|k|omega)" 0.7; }
}
""")

def parse_openfoam_forces(case_dir):
    """Parses postProcessing forceCoeffs or forces log."""
    coeff_file = os.path.join(case_dir, "postProcessing", "forceCoeffs", "0", "coefficient.dat")
    if os.path.exists(coeff_file):
        try:
            lines = [line.strip() for line in open(coeff_file) if line.strip() and not line.startswith('#')]
            if lines:
                last_line = lines[-1].split()
                cd = float(last_line[1])
                cl = float(last_line[3])
                cm = float(last_line[5])
                return {'Cl': cl, 'Cd': cd, 'Cm': cm, 'source': 'forceCoeffs'}
        except Exception as e:
            print(f"Warning parsing coefficient.dat: {e}")

    forces_file = os.path.join(case_dir, "postProcessing", "forces", "0", "forces.dat")
    if os.path.exists(forces_file):
        try:
            lines = [line.strip() for line in open(forces_file) if line.strip() and not line.startswith('#')]
            if lines:
                last_line = lines[-1].replace('(', ' ').replace(')', ' ').split()
                fx_p = float(last_line[1])
                fy_p = float(last_line[2])
                fx_v = float(last_line[4])
                fy_v = float(last_line[5])
                fx = fx_p + fx_v
                fy = fy_p + fy_v
                return {'Fx': fx, 'Fy': fy, 'source': 'forces'}
        except Exception as e:
            print(f"Warning parsing forces.dat: {e}")

    return None

def run_openfoam_single_case(cfg, main_chord_mm=300.0, span_mm=600.0, alpha_deg=0.0, speed=22.22, density='coarse', max_iters=250):
    """
    Executes a complete OpenFOAM-13 simulation with physical coordinate scaling.
    """
    t0 = time.time()
    tag = hash_config(cfg, alpha_deg, speed, main_chord_mm)
    case_dir = os.path.join(RUNS_DIR, f"case_{tag}")
    os.makedirs(case_dir, exist_ok=True)

    A.ensure_airfoils_loaded()
    norm_cfg = su2.normalize_config(cfg)
    raw_outlines = A.build_outlines(norm_cfg, ground_h=None)

    # Scale outlines to physical meters
    c_main_m = main_chord_mm / 1000.0
    outlines_m = [o * c_main_m for o in raw_outlines]

    all_pts_m = np.vstack(outlines_m)
    c_asm_m = float(all_pts_m[:, 0].max() - all_pts_m[:, 0].min())

    # Write minimal controlDict for gmshToFoam
    os.makedirs(os.path.join(case_dir, "system"), exist_ok=True)
    os.makedirs(os.path.join(case_dir, "constant"), exist_ok=True)
    with open(os.path.join(case_dir, "system", "controlDict"), "w") as f:
        f.write('FoamFile { format ascii; class dictionary; location "system"; object controlDict; }\napplication foamRun;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime 100;\ndeltaT 1;\nwriteControl timeStep;\nwriteInterval 100;\n')

    # Mesh in physical meters
    dz, chord_proj_m = generate_openfoam_mesh(outlines_m, case_dir, density=density, span_depth_m=0.05)

    # Setup OpenFOAM case with assembly reference chord
    setup_openfoam_case(case_dir, speed_ms=speed, alpha_deg=alpha_deg,
                        chord_m=c_asm_m, span_depth_m=dz, max_iters=max_iters)

    # Execute OpenFOAM
    cmd = f"source {OPENFOAM_BASHRC} && {FOAM_RUN_BIN} -solver incompressibleFluid -case {case_dir} > {case_dir}/log.foamRun 2>&1"
    res = subprocess.run(cmd, shell=True, executable="/bin/bash")
    elapsed = time.time() - t0

    parsed = parse_openfoam_forces(case_dir)
    if not parsed:
        return {'status': 'Failed', 'runtime_s': elapsed, 'error': 'Could not parse forces'}

    q = 0.5 * RHO_DEFAULT * (speed ** 2)
    span_m = span_mm / 1000.0

    if 'Cl' in parsed:
        cl_asm = abs(parsed['Cl'])
        cd_asm = abs(parsed['Cd'])
    else:
        aref_slice = c_asm_m * dz
        cl_asm = abs(parsed['Fy']) / (q * aref_slice)
        cd_asm = abs(parsed['Fx']) / (q * aref_slice)

    # Mainplane reference coefficients
    cl_main = cl_asm * (c_asm_m / c_main_m)
    cd_main = cd_asm * (c_asm_m / c_main_m)

    # Physical forces on actual wing span
    planform_area_actual = c_asm_m * span_m
    lift_actual_n = cl_asm * q * planform_area_actual
    drag_actual_n = cd_asm * q * planform_area_actual

    ld = cl_asm / cd_asm if cd_asm > 1e-4 else 0.0

    return {
        'status': 'Success',
        'engine': 'OpenFOAM-13',
        'solver': 'incompressibleFluid (SIMPLE)',
        'turbulence': 'k-omega SST',
        'alpha': alpha_deg,
        'speed_ms': speed,
        'main_chord_mm': main_chord_mm,
        'assembly_chord_mm': round(c_asm_m * 1000.0, 1),
        'span_mm': span_mm,
        'actual_planform_area_m2': round(planform_area_actual, 4),
        'Cl_assembly': round(cl_asm, 3),
        'Cd_assembly': round(cd_asm, 4),
        'Cl_main': round(cl_main, 3),
        'Cd_main': round(cd_main, 4),
        'LD': round(ld, 2),
        'Lift_Actual_N': round(lift_actual_n, 2),
        'Drag_Actual_N': round(drag_actual_n, 2),
        'case_dir': case_dir,
        'runtime_s': round(elapsed, 2)
    }

if __name__ == '__main__':
    print("Testing scaled OpenFOAM engine on TOP 1...")
    top1_cfg = ('s1223', [
        ('s1223', 35.0, -24.0, 98.0, 4.5),
        ('e423', 30.0, -15.0, 128.0, 14.5)
    ])
    res = run_openfoam_single_case(top1_cfg, main_chord_mm=300.0, span_mm=600.0, alpha_deg=0.0, speed=25.0, density='coarse', max_iters=200)
    print("Scaled OpenFOAM Result:")
    for k, v in res.items():
        print(f"  {k}: {v}")
