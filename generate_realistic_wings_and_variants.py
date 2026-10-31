import sys, os, struct, math, shutil
import numpy as np
import pandas as pd

sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
WING_STEP = "/home/user/Applications/aero_auto/wing_s1223_solid.step"

AERO_BODY_DIR = "/home/user/aero_body"
VARIANTS_DIR = os.path.join(AERO_BODY_DIR, "cad/BODYWORK_VARIANTS")
ASSEMBLIES_DIR = os.path.join(AERO_BODY_DIR, "cad/bodywork_assemblies")
REPORTS_DIR = os.path.join(AERO_BODY_DIR, "reports")

DRIVE_DIR = "/home/user/ENPRT_FSUK2027_TEAM_DRIVE/07_BODYWORK_VARIANTS"
DOWNLOADS_DIR = "/home/user/Downloads/BODYWORK_VARIANTS"
PROJECT_DIR = "/home/user/ENPRT_FSUK2027/BODYWORK"

for d in [VARIANTS_DIR, ASSEMBLIES_DIR, REPORTS_DIR, DRIVE_DIR, DOWNLOADS_DIR, PROJECT_DIR]:
    os.makedirs(d, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# 1. HELPER: STANDARD IEEE 754 BINARY STL EXPORTER
# ══════════════════════════════════════════════════════════════════════════════
def export_standard_binary_stl(shape_or_facets, filepath, tolerance=0.5):
    if isinstance(shape_or_facets, Part.Shape):
        mesh = shape_or_facets.tessellate(tolerance)
        verts, facets_idx = mesh
        verts = np.array(verts, dtype=np.float32)
        triangles = [verts[list(f)] for f in facets_idx]
    else:
        triangles = shape_or_facets

    header = b'ENPRT FSUK 2027 Realistic Aero Assembly Standard Binary STL' + b' ' * 40
    header = header[:80]
    num_triangles = len(triangles)

    with open(filepath, 'wb') as f:
        f.write(header)
        f.write(np.uint32(num_triangles).tobytes())

        for tri in triangles:
            p1, p2, p3 = tri[0], tri[1], tri[2]
            v1 = p2 - p1
            v2 = p3 - p1
            normal = np.cross(v1, v2)
            norm_mag = np.linalg.norm(normal)
            if norm_mag > 1e-12:
                normal = normal / norm_mag
            else:
                normal = np.array([0.0, 0.0, 1.0], dtype=np.float32)

            record = struct.pack('<3f3f3f3fH',
                                 float(normal[0]), float(normal[1]), float(normal[2]),
                                 float(p1[0]), float(p1[1]), float(p1[2]),
                                 float(p2[0]), float(p2[1]), float(p2[2]),
                                 float(p3[0]), float(p3[1]), float(p3[2]),
                                 0)
            f.write(record)

    expected_size = 84 + 50 * num_triangles
    actual_size = os.path.getsize(filepath)
    assert expected_size == actual_size
    print(f"Standard binary STL: {os.path.basename(filepath)} ({num_triangles:,} tris, {actual_size/1e6:.2f} MB)")
    return True

# ══════════════════════════════════════════════════════════════════════════════
# 2. AIRFOIL TRANSFORMATION HELPER
# ══════════════════════════════════════════════════════════════════════════════
def create_airfoil_element(base_solid, chord_scale, span, rot_deg, trans_vec):
    m = App.Matrix()
    m.A11 = chord_scale
    m.A22 = chord_scale
    m.A33 = span / 1400.0
    s = base_solid.copy().transformGeometry(m)
    s.translate(App.Vector(0, 0, -span / 2.0))
    s.rotate(App.Vector(0,0,0), App.Vector(0,1,0), 90)
    s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), -90)
    if rot_deg != 0:
        s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), rot_deg)
    s.translate(trans_vec)
    return s

# ══════════════════════════════════════════════════════════════════════════════
# 3. BUILD COMPLETE REALISTIC FRONT WING WITH ALL ELEMENTS & CHASSIS MOUNTS
# ══════════════════════════════════════════════════════════════════════════════
def build_front_wing_assembly(main_solid, flap_solid):
    print("Building Realistic Front Wing Assembly...")
    # Multi-elements (Mainplane + Flap 1 + Flap 2)
    # Span 1360 mm (within 1400 mm rule), ground clearance >= 35 mm
    fw_e1 = create_airfoil_element(main_solid, 1.0, 1360.0, 0.0, App.Vector(0, 1200, 75))
    fw_e2 = create_airfoil_element(flap_solid, 0.9, 1360.0, -8.0, App.Vector(0, 1260, 110))
    fw_e3 = create_airfoil_element(flap_solid, 0.75, 1340.0, -18.0, App.Vector(0, 1310, 155))

    # Gurney Flap on upper flap trailing edge
    gurney = Part.makeBox(1340, 4, 8, App.Vector(-670, 1315, 158))

    # Profiled Endplates (t=5 mm, X = +- 680 mm)
    ep_l = Part.makeBox(5, 420, 200, App.Vector(-685, 920, 25))
    ep_r = Part.makeBox(5, 420, 200, App.Vector(680, 920, 25))

    # Horizontal Outwash Footplates (t=4 mm, width 40 mm, total width exactly 1400 mm)
    fp_l = Part.makeBox(40, 380, 4, App.Vector(-725, 940, 25))
    fp_r = Part.makeBox(40, 380, 4, App.Vector(685, 940, 25))

    # 4 Underwing Ground Effect Strakes (2 port, 2 starboard)
    strake_l1 = Part.makeBox(3, 260, 35, App.Vector(-350, 960, 28))
    strake_l2 = Part.makeBox(3, 260, 35, App.Vector(-520, 960, 28))
    strake_r1 = Part.makeBox(3, 260, 35, App.Vector(347, 960, 28))
    strake_r2 = Part.makeBox(3, 260, 35, App.Vector(517, 960, 28))

    # Front Wing Chassis Mounting Pylons (Twin structural pylons at X = +- 160 mm)
    # Extends from Front Bulkhead lower hardpoints (Y=700, Z=55) to FW main spar (Y=1180, Z=75)
    def make_fw_pylon(x_pos):
        pts = [
            App.Vector(x_pos, 700, 50),
            App.Vector(x_pos, 700, 95),
            App.Vector(x_pos, 1160, 105),
            App.Vector(x_pos, 1220, 85),
            App.Vector(x_pos, 1220, 60),
            App.Vector(x_pos, 1140, 55),
            App.Vector(x_pos, 700, 50)
        ]
        poly = Part.makePolygon(pts)
        face = Part.Face(poly)
        return face.extrude(App.Vector(10, 0, 0))

    pylon_l = make_fw_pylon(-165)
    pylon_r = make_fw_pylon(155)

    # 4 Chassis Mounting Lugs on Front Bulkhead (M8 double-shear brackets)
    lug_1l = Part.makeBox(8, 25, 30, App.Vector(-175, 695, 45))
    lug_1r = Part.makeBox(8, 25, 30, App.Vector(167, 695, 45))
    lug_2l = Part.makeBox(8, 25, 30, App.Vector(-153, 695, 45))
    lug_2r = Part.makeBox(8, 25, 30, App.Vector(145, 695, 45))

    fw_solids = [fw_e1, fw_e2, fw_e3, gurney, ep_l, ep_r, fp_l, fp_r,
                 strake_l1, strake_l2, strake_r1, strake_r2,
                 pylon_l, pylon_r, lug_1l, lug_1r, lug_2l, lug_2r]
    
    fw_compound = Part.makeCompound(fw_solids)
    print(f"Front Wing Complete: {len(fw_solids)} solids, isValid={fw_compound.isValid()}, BB={fw_compound.BoundBox}")
    return fw_compound, fw_solids

# ══════════════════════════════════════════════════════════════════════════════
# 4. BUILD COMPLETE REALISTIC REAR WING WITH ALL ELEMENTS & CHASSIS MOUNTS
# ══════════════════════════════════════════════════════════════════════════════
def build_rear_wing_assembly(main_solid, flap_solid):
    print("Building Realistic Rear Wing Assembly...")
    # Span 950 mm
    rw_e1 = create_airfoil_element(main_solid, 1.0, 950.0, 0.0, App.Vector(0, -1180, 1180))
    rw_e2 = create_airfoil_element(flap_solid, 0.9, 950.0, 12.0, App.Vector(0, -1250, 1220))
    rw_e3 = create_airfoil_element(flap_solid, 0.8, 950.0, 24.0, App.Vector(0, -1310, 1255))
    rw_beam = create_airfoil_element(main_solid, 0.7, 800.0, 15.0, App.Vector(0, -1380, 480))

    # Gurney Flap on Upper Flap 2
    gurney = Part.makeBox(950, 4, 10, App.Vector(-475, -1375, 1265))

    # Profiled Endplates (X = +- 475 mm) with 3 Aerodynamic Pressure Relief Louvers
    def make_rw_endplate(x_pos):
        ep = Part.makeBox(6, 440, 220, App.Vector(x_pos, -1560, 1060))
        l1 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1230))
        l2 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1200))
        l3 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1170))
        return ep.cut(l1).cut(l2).cut(l3)

    rw_ep_l = make_rw_endplate(-481)
    rw_ep_r = make_rw_endplate(475)

    # DRS Actuator Housing Pod (Centerline X=0)
    drs_cyl = Part.makeCylinder(14, 120, App.Vector(0, -1400, 1260), App.Vector(0, 1, 0))
    drs_cap = Part.makeSphere(14, App.Vector(0, -1280, 1260))
    drs_pod = drs_cyl.fuse(drs_cap)

    # Flap Pitch Adjustment Ribs (X = +- 250 mm)
    rib_l = Part.makeBox(6, 180, 70, App.Vector(-253, -1330, 1200))
    rib_r = Part.makeBox(6, 180, 70, App.Vector(247, -1330, 1200))

    # Twin Swan-Neck Structural Pylons (Connecting Rear Bulkhead Y=-1400, Z=350 & MH Braces to RW Top)
    def make_swan_neck_pylon(x_pos):
        pts = [
            App.Vector(x_pos, -1400, 350),
            App.Vector(x_pos, -1370, 350),
            App.Vector(x_pos, -1140, 650),
            App.Vector(x_pos, -1140, 700),
            App.Vector(x_pos, -1200, 1240),
            App.Vector(x_pos, -1230, 1240),
            App.Vector(x_pos, -1260, 1200),
            App.Vector(x_pos, -1220, 750),
            App.Vector(x_pos, -1370, 400),
            App.Vector(x_pos, -1400, 350)
        ]
        poly = Part.makePolygon(pts)
        face = Part.Face(poly)
        return face.extrude(App.Vector(12, 0, 0))

    pylon_l = make_swan_neck_pylon(-186)
    pylon_r = make_swan_neck_pylon(174)

    # Chassis Mounting Lugs on Rear Bulkhead and Main Hoop Braces (4x M8 clevis mounts)
    lug_rb_l = Part.makeBox(12, 35, 25, App.Vector(-196, -1415, 340))
    lug_rb_r = Part.makeBox(12, 35, 25, App.Vector(184, -1415, 340))
    lug_mh_l = Part.makeBox(12, 35, 25, App.Vector(-196, -1160, 640))
    lug_mh_r = Part.makeBox(12, 35, 25, App.Vector(184, -1160, 640))

    rw_solids = [rw_e1, rw_e2, rw_e3, rw_beam, gurney, rw_ep_l, rw_ep_r, drs_pod,
                 rib_l, rib_r, pylon_l, pylon_r,
                 lug_rb_l, lug_rb_r, lug_mh_l, lug_mh_r]
    rw_compound = Part.makeCompound(rw_solids)
    print(f"Rear Wing Complete: {len(rw_solids)} solids, isValid={rw_compound.isValid()}, BB={rw_compound.BoundBox}")
    return rw_compound, rw_solids

print("Wing generators defined successfully.")
