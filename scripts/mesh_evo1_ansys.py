#!/usr/bin/env python3
"""
mesh_evo1_ansys.py
==================
Generates high-fidelity ANSYS Fluent mesh for ENPRT-FW-EVO1 in ground effect.
Uses Gmsh to generate refined boundary layer mesh, exports to Nastran BDF,
and converts via ANSYS fe.exe utility into native Fluent Rampant .msh format.
"""

import os
import sys
import math
import subprocess
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import aero_3d_engine as E

OUTPUT_DIR = APP_DIR / "runs" / "ansys_runs" / "evo1_fluent_case"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generate_evo1_mesh(ground_clearance_mm: float = 40.0):
    import gmsh
    print("==================================================================")
    print("   GENERATING HIGH-FIDELITY ANSYS FLUENT MESH: ENPRT-FW-EVO1      ")
    print("==================================================================")

    # 1. Geometry Setup
    c0, a0 = 300.0, 1.5   # Mainplane: S1223
    c1, a1 = 130.0, 19.0  # Flap 1: S1223
    c2, a2 = 105.0, 33.0  # Flap 2: E423 with 6mm Gurney

    # Load normalized airfoils
    coords_s1223 = E.load_airfoil_dat("s1223")
    coords_e423 = E.load_airfoil_dat("e423")

    def transform_element(coords, chord, aoa_deg, x_le, z_le, gurney_mm=0.0):
        pts = coords.copy()
        pts[:, 0] *= chord
        pts[:, 1] *= chord
        pts[:, 1] = -pts[:, 1]  # Invert for downforce
        
        # Add Gurney flap if requested (downward tab at TE)
        if gurney_mm > 0.0:
            te_pt = pts[-1].copy()
            gurney_pts = [
                [te_pt[0], te_pt[1] - gurney_mm],
                [te_pt[0] - 1.5, te_pt[1] - gurney_mm],
                [te_pt[0] - 1.5, te_pt[1]]
            ]
            pts = np.vstack([pts, gurney_pts])

        rad = math.radians(aoa_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        rot_x = pts[:, 0] * ca + pts[:, 1] * sa
        rot_z = -pts[:, 0] * sa + pts[:, 1] * ca
        return np.column_stack([rot_x + x_le, rot_z + z_le])

    pts0 = transform_element(coords_s1223, c0, a0, 0.0, 0.0)
    te0_x, te0_z = pts0[-1, 0], pts0[-1, 1]

    f1_x = te0_x - 2.5
    f1_z = te0_z + 6.5
    pts1 = transform_element(coords_s1223, c1, a1, f1_x, f1_z)
    te1_x, te1_z = pts1[-1, 0], pts1[-1, 1]

    f2_x = te1_x - 2.0
    f2_z = te1_z + 6.0
    pts2 = transform_element(coords_e423, c2, a2, f2_x, f2_z, gurney_mm=6.0)

    # Shift all elements so lowest point is exactly ground_clearance_mm
    all_pts = np.vstack([pts0, pts1, pts2])
    min_z = float(np.min(all_pts[:, 1]))
    dz = ground_clearance_mm - min_z
    pts0[:, 1] += dz
    pts1[:, 1] += dz
    pts2[:, 1] += dz

    # Scale to METERS for ANSYS Fluent
    pts0_m = pts0 / 1000.0
    pts1_m = pts1 / 1000.0
    pts2_m = pts2 / 1000.0

    print(f"  Mainplane: chord={c0}mm, AoA={a0}°, Z_LE={pts0[0,1]:.1f}mm")
    print(f"  Flap 1:    chord={c1}mm, AoA={a1}°, Z_LE={pts1[0,1]:.1f}mm")
    print(f"  Flap 2:    chord={c2}mm, AoA={a2}°, Z_LE={pts2[0,1]:.1f}mm (with 6mm Gurney)")
    print(f"  Min Ground Clearance: {np.min(np.vstack([pts0, pts1, pts2])[:, 1]):.1f} mm")

    # 2. GMSH Model Construction
    gmsh.initialize()
    gmsh.option.setNumber("General.Verbosity", 2)
    gmsh.model.add("ENPRT_FW_EVO1")

    # Computational domain dimensions (meters)
    # Ground at Y = 0
    x_inlet = -1.2
    x_outlet = 2.5
    y_ground = 0.0
    y_top = 1.6

    # Cell sizing (optimized for fast meshing and clean resolution)
    lc_far = 0.15
    lc_ground = 0.04
    lc_wing = 0.008
    lc_le_te = 0.003

    def clean_points(pts_m):
        clean = [pts_m[0]]
        for p in pts_m[1:]:
            if np.linalg.norm(p - clean[-1]) > 5e-4:
                clean.append(p)
        if np.linalg.norm(clean[0] - clean[-1]) < 5e-4:
            clean = clean[:-1]
        return np.array(clean)

    def create_airfoil_loop(pts_m, tag_prefix):
        pts_m = clean_points(pts_m)
        point_tags = []
        n = len(pts_m)
        for i, pt in enumerate(pts_m):
            # Refine LE and TE
            is_le_te = (i < 5) or (i > n - 6) or (abs(i - n//2) < 5)
            lc = lc_le_te if is_le_te else lc_wing
            p_tag = gmsh.model.geo.addPoint(float(pt[0]), float(pt[1]), 0.0, lc)
            point_tags.append(p_tag)

        line_tags = []
        for i in range(len(point_tags) - 1):
            l_tag = gmsh.model.geo.addLine(point_tags[i], point_tags[i + 1])
            line_tags.append(l_tag)
        # Close loop
        l_close = gmsh.model.geo.addLine(point_tags[-1], point_tags[0])
        line_tags.append(l_close)

        loop_tag = gmsh.model.geo.addCurveLoop(line_tags)
        return loop_tag, line_tags

    print("\n  -> Creating CAD curves and multi-element loops in Gmsh...")
    loop_main, lines_main = create_airfoil_loop(pts0_m, "main")
    loop_flap1, lines_flap1 = create_airfoil_loop(pts1_m, "flap1")
    loop_flap2, lines_flap2 = create_airfoil_loop(pts2_m, "flap2")

    # Domain Outer Boundaries
    p_inlet_bottom = gmsh.model.geo.addPoint(x_inlet, y_ground, 0.0, lc_ground)
    p_outlet_bottom = gmsh.model.geo.addPoint(x_outlet, y_ground, 0.0, lc_ground)
    p_outlet_top = gmsh.model.geo.addPoint(x_outlet, y_top, 0.0, lc_far)
    p_inlet_top = gmsh.model.geo.addPoint(x_inlet, y_top, 0.0, lc_far)

    l_ground = gmsh.model.geo.addLine(p_inlet_bottom, p_outlet_bottom)
    l_outlet = gmsh.model.geo.addLine(p_outlet_bottom, p_outlet_top)
    l_top = gmsh.model.geo.addLine(p_outlet_top, p_inlet_top)
    l_inlet = gmsh.model.geo.addLine(p_inlet_top, p_inlet_bottom)

    domain_loop = gmsh.model.geo.addCurveLoop([l_ground, l_outlet, l_top, l_inlet])

    # Plane surface with 3 holes (the 3 wing elements)
    surf_fluid = gmsh.model.geo.addPlaneSurface([domain_loop, loop_main, loop_flap1, loop_flap2])

    gmsh.model.geo.synchronize()

    # Physical Groups (for Fluent boundary zones)
    # 1: ground, 2: outlet, 3: top, 4: inlet, 5: wing_main, 6: wing_flap1, 7: wing_flap2, 10: fluid
    gmsh.model.addPhysicalGroup(1, [l_ground], 1, name="ground")
    gmsh.model.addPhysicalGroup(1, [l_outlet], 2, name="outlet")
    gmsh.model.addPhysicalGroup(1, [l_top], 3, name="top")
    gmsh.model.addPhysicalGroup(1, [l_inlet], 4, name="inlet")
    gmsh.model.addPhysicalGroup(1, lines_main, 5, name="wing_main")
    gmsh.model.addPhysicalGroup(1, lines_flap1, 6, name="wing_flap1")
    gmsh.model.addPhysicalGroup(1, lines_flap2, 7, name="wing_flap2")
    gmsh.model.addPhysicalGroup(2, [surf_fluid], 10, name="fluid")

    print("  -> Generating 2D unstructured Delaunay mesh with refined boundary layers...")
    gmsh.model.mesh.generate(2)
    gmsh.model.mesh.optimize("Laplace2D")

    # Export to Nastran BDF format
    bdf_file = OUTPUT_DIR / "enprt_fw_evo1.bdf"
    msh_file = OUTPUT_DIR / "enprt_fw_evo1.msh"
    gmsh.write(str(bdf_file))
    gmsh.finalize()
    print(f"  -> Exported intermediate BDF mesh: {bdf_file}")

    # Convert to Native ANSYS Fluent Mesh using fe.exe
    fe_exe = Path(r"C:\Program Files\ANSYS Inc\v241\fluent\fluent24.1.0\utility\fe2ram\win64\fe.exe")
    if not fe_exe.exists():
        raise FileNotFoundError(f"fe.exe not found at {fe_exe}")

    print("  -> Converting to native ANSYS Fluent .msh format using fe2ram...")
    cmd = [str(fe_exe), "-d2", "-tNASTRAN", "-zID", "-oRAMPANT", str(bdf_file), str(msh_file)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and not msh_file.exists():
        print(f"fe.exe stderr: {res.stderr}")
        raise RuntimeError("Failed to generate Fluent .msh file")

    print(f"  -> SUCCESS! Native ANSYS Fluent Mesh generated: {msh_file} ({msh_file.stat().st_size / 1024:.1f} KB)")
    return str(msh_file)


if __name__ == "__main__":
    generate_evo1_mesh()
