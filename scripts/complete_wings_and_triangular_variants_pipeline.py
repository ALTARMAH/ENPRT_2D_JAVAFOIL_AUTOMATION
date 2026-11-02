import sys, os, struct, math, shutil, glob
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

print("="*75)
print("FSAE REALISTIC WINGS & TRIANGULAR BODYWORK VARIANTS FULL PIPELINE")
print("="*75)

# Paths
CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
WING_STEP = "/home/user/Applications/aero_auto/wing_s1223_solid.step"

AERO_BODY_DIR = "/home/user/aero_body"
VARIANTS_DIR = os.path.join(AERO_BODY_DIR, "cad/BODYWORK_VARIANTS")
ASSEMBLIES_DIR = os.path.join(AERO_BODY_DIR, "cad/bodywork_assemblies")
REPORTS_DIR = os.path.join(AERO_BODY_DIR, "reports")

DRIVE_DIR = "/home/user/ENPRT_FSUK2027_TEAM_DRIVE/07_BODYWORK_VARIANTS"
DOWNLOADS_DIR = "/home/user/Downloads/BODYWORK_VARIANTS"
PROJECT_DIR = "/home/user/ENPRT_FSUK2027/BODYWORK"
BRAIN_DIR = "/home/user/.gemini/antigravity-cli/brain/b1fb5f26-5ea7-4d9a-bbe1-02ad8ed045c5"

for d in [VARIANTS_DIR, ASSEMBLIES_DIR, REPORTS_DIR, DRIVE_DIR, DOWNLOADS_DIR, PROJECT_DIR]:
    os.makedirs(d, exist_ok=True)

# ----------------------------------------------------------------------
# 1. STANDARD IEEE 754 BINARY STL EXPORTER
# ----------------------------------------------------------------------
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
    print(f"STL OK: {os.path.basename(filepath)} ({num_triangles:,} tris, {actual_size/1e6:.2f} MB)")
    return True

# ----------------------------------------------------------------------
# 2. AIRFOIL TRANSFORMATION HELPER
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# 3. BUILD REALISTIC FRONT WING WITH GROUND CLEARANCE >= 35 MM
# ----------------------------------------------------------------------
print("\n>>> Reconstructing Realistic Front Wing (Ground Clearance >= 35 mm)...")
doc_w = App.newDocument("WingSource")
Import.insert(WING_STEP, doc_w.Name)
base_solids = doc_w.Objects[0].Shape.Solids
main_solid = base_solids[0]
flap_solid = base_solids[1] if len(base_solids) > 1 else base_solids[0]

# Shifted Z by +45.2 mm so min Z is 35.1 mm
fw_e1 = create_airfoil_element(main_solid, 1.0, 1360.0, 0.0, App.Vector(0, 1200, 120.2))
fw_e2 = create_airfoil_element(flap_solid, 0.9, 1360.0, -8.0, App.Vector(0, 1260, 155.2))
fw_e3 = create_airfoil_element(flap_solid, 0.75, 1340.0, -18.0, App.Vector(0, 1310, 200.2))

# Gurney Flap
fw_gurney = Part.makeBox(1340, 4, 8, App.Vector(-670, 1315, 203.2))

# Profiled Endplates (X = +- 680 mm)
fw_ep_l = Part.makeBox(5, 420, 200, App.Vector(-685, 920, 35.0))
fw_ep_r = Part.makeBox(5, 420, 200, App.Vector(680, 920, 35.0))

# Outwash Footplates (Z = 35.0 mm)
fw_fp_l = Part.makeBox(40, 380, 4, App.Vector(-725, 940, 35.0))
fw_fp_r = Part.makeBox(40, 380, 4, App.Vector(685, 940, 35.0))

# Underwing Strakes
strake_l1 = Part.makeBox(3, 260, 35, App.Vector(-350, 960, 36.0))
strake_l2 = Part.makeBox(3, 260, 35, App.Vector(-520, 960, 36.0))
strake_r1 = Part.makeBox(3, 260, 35, App.Vector(347, 960, 36.0))
strake_r2 = Part.makeBox(3, 260, 35, App.Vector(517, 960, 36.0))

# Front Wing Structural Mounting Pylons (Connecting Front Bulkhead lower tubes to FW main spar)
def make_fw_pylon(x_pos):
    pts = [
        App.Vector(x_pos, 700, 50),
        App.Vector(x_pos, 700, 100),
        App.Vector(x_pos, 1160, 145),
        App.Vector(x_pos, 1220, 130),
        App.Vector(x_pos, 1220, 75),
        App.Vector(x_pos, 1140, 65),
        App.Vector(x_pos, 700, 50)
    ]
    poly = Part.makePolygon(pts)
    face = Part.Face(poly)
    return face.extrude(App.Vector(10, 0, 0))

fw_pylon_l = make_fw_pylon(-165)
fw_pylon_r = make_fw_pylon(155)

# Chassis Mounting Double-Shear Lugs on Front Bulkhead (4x M8 brackets)
fw_lug_1l = Part.makeBox(8, 25, 30, App.Vector(-175, 695, 45))
fw_lug_1r = Part.makeBox(8, 25, 30, App.Vector(167, 695, 45))
fw_lug_2l = Part.makeBox(8, 25, 30, App.Vector(-153, 695, 45))
fw_lug_2r = Part.makeBox(8, 25, 30, App.Vector(145, 695, 45))

fw_elements = [fw_e1, fw_e2, fw_e3, fw_gurney, fw_ep_l, fw_ep_r, fw_fp_l, fw_fp_r,
               strake_l1, strake_l2, strake_r1, strake_r2,
               fw_pylon_l, fw_pylon_r, fw_lug_1l, fw_lug_1r, fw_lug_2l, fw_lug_2r]
fw_assembly = Part.makeCompound(fw_elements)
print(f"Front Wing Complete: {len(fw_elements)} solids, isValid={fw_assembly.isValid()}, BB={fw_assembly.BoundBox}")

# ----------------------------------------------------------------------
# 4. BUILD REALISTIC REAR WING
# ----------------------------------------------------------------------
print("\n>>> Reconstructing Realistic Rear Wing Assembly...")
rw_e1 = create_airfoil_element(main_solid, 1.0, 950.0, 0.0, App.Vector(0, -1180, 1180))
rw_e2 = create_airfoil_element(flap_solid, 0.9, 950.0, 12.0, App.Vector(0, -1250, 1220))
rw_e3 = create_airfoil_element(flap_solid, 0.8, 950.0, 24.0, App.Vector(0, -1310, 1255))
rw_beam = create_airfoil_element(main_solid, 0.7, 800.0, 15.0, App.Vector(0, -1380, 480))

rw_gurney = Part.makeBox(950, 4, 10, App.Vector(-475, -1375, 1265))

def make_rw_endplate(x_pos):
    ep = Part.makeBox(6, 440, 220, App.Vector(x_pos, -1560, 1060))
    l1 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1230))
    l2 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1200))
    l3 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1170))
    return ep.cut(l1).cut(l2).cut(l3)

rw_ep_l = make_rw_endplate(-481)
rw_ep_r = make_rw_endplate(475)

drs_cyl = Part.makeCylinder(14, 120, App.Vector(0, -1400, 1260), App.Vector(0, 1, 0))
drs_cap = Part.makeSphere(14, App.Vector(0, -1280, 1260))
drs_pod = drs_cyl.fuse(drs_cap)

rw_rib_l = Part.makeBox(6, 180, 70, App.Vector(-253, -1330, 1200))
rw_rib_r = Part.makeBox(6, 180, 70, App.Vector(247, -1330, 1200))

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

rw_pylon_l = make_swan_neck_pylon(-186)
rw_pylon_r = make_swan_neck_pylon(174)

rw_lug_rb_l = Part.makeBox(12, 35, 25, App.Vector(-196, -1415, 340))
rw_lug_rb_r = Part.makeBox(12, 35, 25, App.Vector(184, -1415, 340))
rw_lug_mh_l = Part.makeBox(12, 35, 25, App.Vector(-196, -1160, 640))
rw_lug_mh_r = Part.makeBox(12, 35, 25, App.Vector(184, -1160, 640))

rw_elements = [rw_e1, rw_e2, rw_e3, rw_beam, rw_gurney, rw_ep_l, rw_ep_r, drs_pod,
               rw_rib_l, rw_rib_r, rw_pylon_l, rw_pylon_r,
               rw_lug_rb_l, rw_lug_rb_r, rw_lug_mh_l, rw_lug_mh_r]
rw_assembly = Part.makeCompound(rw_elements)
print(f"Rear Wing Complete: {len(rw_elements)} solids, isValid={rw_assembly.isValid()}, BB={rw_assembly.BoundBox}")
App.closeDocument(doc_w.Name)

# ----------------------------------------------------------------------
# 5. LOAD CHASSIS
# ----------------------------------------------------------------------
print("\n>>> Loading Chassis...")
doc_ch = App.newDocument("ChassisSource")
Import.insert(CHASSIS_STEP, doc_ch.Name)
chassis_shape = doc_ch.Objects[0].Shape.copy()
App.closeDocument(doc_ch.Name)
print(f"Chassis Loaded: {len(chassis_shape.Solids)} solids")

# ----------------------------------------------------------------------
# 6. NODES, STANDOFFS, AND TRIANGULAR PLATES
# ----------------------------------------------------------------------
NODES_INFILL = {
    'NOSE_TIP': App.Vector(0.0, 1150.0, 180.0),
    'FB_TL': App.Vector(-225.0, 700.0, 370.0),
    'FB_TR': App.Vector( 225.0, 700.0, 370.0),
    'FB_BL': App.Vector(-225.0, 700.0,  50.0),
    'FB_BR': App.Vector( 225.0, 700.0,  50.0),
    'FN_ML': App.Vector(-275.0, 200.0, 200.0),
    'FN_MR': App.Vector( 275.0, 200.0, 200.0),
    'FN_BL': App.Vector(-225.0, 200.0,  50.0),
    'FN_BR': App.Vector( 225.0, 200.0,  50.0),
    'FH_TL': App.Vector(-200.0,   0.0, 590.0),
    'FH_TR': App.Vector( 200.0,   0.0, 590.0),
    'FH_SL': App.Vector(-250.0,   0.0, 544.0),
    'FH_SR': App.Vector( 250.0,   0.0, 544.0),
    'FH_ML': App.Vector(-275.0,   0.0, 200.0),
    'FH_MR': App.Vector( 275.0,   0.0, 200.0),
    'FH_BL': App.Vector(-225.0,   0.0,  50.0),
    'FH_BR': App.Vector( 225.0,   0.0,  50.0),
    'MH_TOP': App.Vector(  0.0, -875.0, 1258.0),
    'MH_BL': App.Vector(-148.0, -875.0, 1070.0),
    'MH_BR': App.Vector( 148.0, -875.0, 1070.0),
    'SIS_TL': App.Vector(-357.0, -875.0, 358.0),
    'SIS_TR': App.Vector( 357.0, -875.0, 358.0),
    'SIS_BL': App.Vector(-280.0, -875.0,  32.0),
    'SIS_BR': App.Vector( 280.0, -875.0,  32.0),
    'EM_ML': App.Vector(-300.0, -1200.0, 200.0),
    'EM_MR': App.Vector( 300.0, -1200.0, 200.0),
    'EM_BL': App.Vector(-250.0, -1200.0,  50.0),
    'EM_BR': App.Vector( 250.0, -1200.0,  50.0),
    'RB_TL': App.Vector(-225.0, -1400.0, 350.0),
    'RB_TR': App.Vector( 225.0, -1400.0, 350.0),
    'RB_ML': App.Vector(-300.0, -1400.0, 200.0),
    'RB_MR': App.Vector( 300.0, -1400.0, 200.0),
    'RB_BL': App.Vector(-250.0, -1400.0,  50.0),
    'RB_BR': App.Vector( 250.0, -1400.0,  50.0),
}

NODES_OVER = {}
STANDOFF_BOBBINS = []
STANDOFF_SCHEDULE = []

for k, pt in NODES_INFILL.items():
    vx = 1.0 if pt.x > 10 else (-1.0 if pt.x < -10 else 0.0)
    vy = 0.5 if pt.y > 600 else (-0.5 if pt.y < -1000 else 0.0)
    vz = 1.0 if pt.z > 300 else (-0.3 if pt.z < 100 else 0.0)
    vec = App.Vector(vx, vy, vz)
    if vec.Length < 1e-3: vec = App.Vector(0, 0, 1)
    vec.normalize()
    
    offset_dist = 22.0
    p_outer = pt + vec * offset_dist
    NODES_OVER[k] = p_outer
    
    # Solid cylindrical standoff (Dia 18mm, height 22mm)
    bobbin = Part.makeCylinder(9.0, offset_dist, pt, vec)
    STANDOFF_BOBBINS.append(bobbin)
    
    STANDOFF_SCHEDULE.append({
        'Standoff_ID': f"ST_{k}",
        'Chassis_Node': k,
        'Chassis_X': round(pt.x, 1),
        'Chassis_Y': round(pt.y, 1),
        'Chassis_Z': round(pt.z, 1),
        'Outer_X': round(p_outer.x, 1),
        'Outer_Y': round(p_outer.y, 1),
        'Outer_Z': round(p_outer.z, 1),
        'Standoff_Length_mm': offset_dist,
        'Thread_Spec': 'M5x0.8',
        'Material': 'AISI 4130 Steel',
        'Torque_Nm': 4.5
    })

standoff_compound = Part.makeCompound(STANDOFF_BOBBINS)
df_standoffs = pd.DataFrame(STANDOFF_SCHEDULE)

PLATE_TOPOLOGY = [
    ('P01_Nose_Top_Rake',        ['NOSE_TIP', 'FB_TL', 'FB_TR'],       'Nosecone', 'Top aerodynamic wedge rake'),
    ('P02_Nose_Left_Cheek',      ['NOSE_TIP', 'FB_BL', 'FB_TL'],       'Nosecone', 'Port-side nose deflector'),
    ('P03_Nose_Right_Cheek',     ['NOSE_TIP', 'FB_TR', 'FB_BR'],       'Nosecone', 'Starboard-side nose deflector'),
    ('P04_Nose_Underbody_Tray',  ['NOSE_TIP', 'FB_BR', 'FB_BL'],       'Nosecone', 'Forward undertray splitter rake'),
    ('P05_FrontDeck_Left',       ['FB_TL', 'FB_TR', 'FH_TL'],          'Front Deck', 'Upper hood intake ramp (Port)'),
    ('P06_FrontDeck_Right',      ['FB_TR', 'FH_TR', 'FH_TL'],          'Front Deck', 'Upper hood intake ramp (Starboard)'),
    ('P07_FrontDeck_Shoulder_L', ['FB_TL', 'FH_TL', 'FH_SL'],          'Front Deck', 'Port hood-to-cockpit shoulder'),
    ('P08_FrontDeck_Shoulder_R', ['FB_TR', 'FH_SR', 'FH_TR'],          'Front Deck', 'Starboard hood-to-cockpit shoulder'),
    ('P09_FrontFlank_Upper_L',   ['FB_TL', 'FH_SL', 'FN_ML'],          'Front Flank L', 'Upper port suspension bypass'),
    ('P10_FrontFlank_Fwd_L',     ['FB_TL', 'FN_ML', 'FB_BL'],          'Front Flank L', 'Forward port damper cove'),
    ('P11_FrontFlank_Mid_L',     ['FB_BL', 'FN_ML', 'FN_BL'],          'Front Flank L', 'Mid port lower chassis cove'),
    ('P12_FrontFlank_AftUp_L',   ['FN_ML', 'FH_SL', 'FH_ML'],          'Front Flank L', 'Aft port upper bulkhead cover'),
    ('P13_FrontFlank_AftLo_L',   ['FN_ML', 'FH_ML', 'FN_BL'],          'Front Flank L', 'Aft port mid chassis cover'),
    ('P14_FrontFlank_BotAft_L',  ['FN_BL', 'FH_ML', 'FH_BL'],          'Front Flank L', 'Lower port front hoop cove'),
    ('P15_FrontFlank_Upper_R',   ['FB_TR', 'FN_MR', 'FH_SR'],          'Front Flank R', 'Upper stbd suspension bypass'),
    ('P16_FrontFlank_Fwd_R',     ['FB_TR', 'FB_BR', 'FN_MR'],          'Front Flank R', 'Forward stbd damper cove'),
    ('P17_FrontFlank_Mid_R',     ['FB_BR', 'FN_BR', 'FN_MR'],          'Front Flank R', 'Mid stbd lower chassis cove'),
    ('P18_FrontFlank_AftUp_R',   ['FN_MR', 'FH_MR', 'FH_SR'],          'Front Flank R', 'Aft stbd upper bulkhead cover'),
    ('P19_FrontFlank_AftLo_R',   ['FN_MR', 'FH_MR', 'FN_BR'],          'Front Flank R', 'Aft stbd mid chassis cover'),
    ('P20_FrontFlank_BotAft_R',  ['FN_BR', 'FH_MR', 'FH_BR'],          'Front Flank R', 'Lower stbd front hoop cove'),
    ('P21_SIS_Upper_L',          ['FH_ML', 'SIS_TL', 'SIS_BL'],        'Sidepod L', 'Main port driver side impact plate'),
    ('P22_SIS_Lower_L',          ['FH_ML', 'SIS_BL', 'FH_BL'],        'Sidepod L', 'Lower port rocker air-fence'),
    ('P23_Cockpit_Deflector_L',  ['FH_SL', 'SIS_TL', 'FH_ML'],        'Cockpit L', 'Port cockpit boundary layer deflector'),
    ('P24_SIS_Upper_R',          ['FH_MR', 'SIS_BR', 'SIS_TR'],        'Sidepod R', 'Main stbd driver side impact plate'),
    ('P25_SIS_Lower_R',          ['FH_MR', 'SIS_BR', 'FH_BR'],        'Sidepod R', 'Lower stbd rocker air-fence'),
    ('P26_Cockpit_Deflector_R',  ['FH_SR', 'FH_MR', 'SIS_TR'],        'Cockpit R', 'Starboard cockpit deflector'),
    ('P27_EngineDeck_Top_L',     ['MH_BL', 'MH_BR', 'RB_TL'],          'Engine Cowl', 'Fastback port spine to rear bulkhead'),
    ('P28_EngineDeck_Top_R',     ['MH_BR', 'RB_TR', 'RB_TL'],          'Engine Cowl', 'Fastback stbd spine to rear bulkhead'),
    ('P29_EngineFlank_Upper_L',  ['MH_BL', 'RB_TL', 'EM_ML'],          'Engine Flank L', 'Upper port roll-hoop wake fairing'),
    ('P30_EngineFlank_Upper_R',  ['MH_BR', 'EM_MR', 'RB_TR'],          'Engine Flank R', 'Upper stbd roll-hoop wake fairing'),
    ('P31_EngineFlank_Side_L',   ['SIS_TL', 'EM_ML', 'SIS_BL'],        'Engine Flank L', 'Forward port powertrain air shield'),
    ('P32_EngineFlank_Side_R',   ['SIS_TR', 'SIS_BR', 'EM_MR'],        'Engine Flank R', 'Forward stbd powertrain air shield'),
    ('P33_EngineFlank_Mid_L',    ['EM_ML', 'RB_ML', 'SIS_BL'],         'Engine Flank L', 'Mid port engine bay taper panel'),
    ('P34_EngineFlank_Mid_R',    ['EM_MR', 'SIS_BR', 'RB_MR'],         'Engine Flank R', 'Mid stbd engine bay taper panel'),
    ('P35_EngineFlank_Lower_L',  ['SIS_BL', 'RB_ML', 'RB_BL'],         'Engine Flank L', 'Lower port engine bay diffuser ramp'),
    ('P36_EngineFlank_Lower_R',  ['SIS_BR', 'RB_BR', 'RB_MR'],         'Engine Flank R', 'Lower stbd engine bay diffuser ramp'),
    ('P37_EngineFlank_Corner_L', ['RB_TL', 'RB_ML', 'EM_ML'],          'Engine Flank L', 'Aft port rear corner end-closure'),
    ('P38_EngineFlank_Corner_R', ['RB_TR', 'EM_MR', 'RB_MR'],          'Engine Flank R', 'Aft stbd rear corner end-closure'),
    ('P39_RearBulkhead_Top',     ['RB_TL', 'RB_TR', 'RB_BL'],          'Rear Transom', 'Upper rear bulkhead wake transom'),
    ('P40_RearBulkhead_Bottom',  ['RB_TR', 'RB_BR', 'RB_BL'],          'Rear Transom', 'Lower rear bulkhead wake transom'),
    ('P41_Floor_Front_L',        ['FB_BL', 'FB_BR', 'FH_BL'],          'Floor Pan', 'Port front footwell flat bottom'),
    ('P42_Floor_Front_R',        ['FB_BR', 'FH_BR', 'FH_BL'],          'Floor Pan', 'Starboard front footwell flat bottom'),
    ('P43_Floor_Mid_L',          ['FH_BL', 'FH_BR', 'SIS_BL'],         'Floor Pan', 'Port cockpit seat flat undertray'),
    ('P44_Floor_Mid_R',          ['FH_BR', 'SIS_BR', 'SIS_BL'],         'Floor Pan', 'Starboard cockpit seat flat undertray'),
    ('P45_Floor_Rear_L',         ['SIS_BL', 'SIS_BR', 'RB_BL'],         'Floor Pan', 'Port engine bay underbody tray'),
    ('P46_Floor_Rear_R',         ['SIS_BR', 'RB_BR', 'RB_BL'],         'Floor Pan', 'Starboard engine bay underbody tray'),
]

def generate_triangular_plates(node_dict, thickness=1.5):
    solids = []
    surfaces = []
    records = []
    
    for idx, (p_id, keys, zone, desc) in enumerate(PLATE_TOPOLOGY, start=1):
        v1 = node_dict[keys[0]]
        v2 = node_dict[keys[1]]
        v3 = node_dict[keys[2]]
        
        l12 = (v2 - v1).Length
        l23 = (v3 - v2).Length
        l31 = (v1 - v3).Length
        
        s_half = (l12 + l23 + l31) / 2.0
        area_val = math.sqrt(max(0.0, s_half * (s_half - l12) * (s_half - l23) * (s_half - l31)))
        area_m2 = area_val / 1e6
        
        poly = Part.makePolygon([v1, v2, v3, v1])
        face = Part.Face(poly)
        surfaces.append(face)
        
        norm = (v2 - v1).cross(v3 - v1)
        if norm.Length > 1e-6: norm.normalize()
        else: norm = App.Vector(0,0,1)
        
        solid = face.extrude(norm * thickness)
        solids.append(solid)
        
        mass_cf = area_m2 * (thickness / 1000.0) * 1550.0
        mass_al = area_m2 * (thickness / 1000.0) * 2700.0
        
        records.append({
            'Plate_ID': f"P{idx:02d}",
            'Name': p_id,
            'Zone': zone,
            'Description': desc,
            'Node_V1': keys[0],
            'Node_V2': keys[1],
            'Node_V3': keys[2],
            'Edge_L1_mm': round(l12, 1),
            'Edge_L2_mm': round(l23, 1),
            'Edge_L3_mm': round(l31, 1),
            'Area_m2': round(area_m2, 4),
            'Thickness_mm': thickness,
            'Mass_CF_kg': round(mass_cf, 3),
            'Mass_Al_kg': round(mass_al, 3)
        })
        
    return Part.makeCompound(solids), Part.makeCompound(surfaces), pd.DataFrame(records)

print("\n>>> Building Variant A1 (Infill Triangular Plates)...")
v_a1_solid, v_a1_surf, df_a1 = generate_triangular_plates(NODES_INFILL, thickness=1.5)

print("\n>>> Building Variant A2 (Over-the-Chassis Triangular Fairing)...")
v_a2_solid, v_a2_surf, df_a2 = generate_triangular_plates(NODES_OVER, thickness=1.5)

# ----------------------------------------------------------------------
# 7. BUILD VARIANT A3 (AERO-DUCT INTEGRATED TRIANGULAR FAIRING)
# ----------------------------------------------------------------------
print("\n>>> Building Variant A3 (Aero-Duct Integrated Triangular Fairing)...")
# Variant A3 has faceted sidepod radiator scoops and under-nose splitter channel
NODES_A3 = dict(NODES_OVER)
# Push sidepod upper & lower nodes outward by +40 mm to form radiator NACA/scoop inlet
NODES_A3['FH_ML'] = App.Vector(-330.0, 0.0, 220.0)
NODES_A3['FH_MR'] = App.Vector( 330.0, 0.0, 220.0)
NODES_A3['SIS_TL'] = App.Vector(-410.0, -875.0, 380.0)
NODES_A3['SIS_TR'] = App.Vector( 410.0, -875.0, 380.0)
# Lift nose tip by +30 mm to create under-nose diffuser feeder tunnel
NODES_A3['NOSE_TIP'] = App.Vector(0.0, 1160.0, 210.0)

v_a3_solid, v_a3_surf, df_a3 = generate_triangular_plates(NODES_A3, thickness=1.5)
print(f"Variant A3: {len(v_a3_solid.Solids)} solids, isValid={v_a3_solid.isValid()}")

# ----------------------------------------------------------------------
# 8. EXPORT 2D DXFS AND NESTED SHEETS FOR VARIANT A2
# ----------------------------------------------------------------------
print("\n>>> Generating 2D DXF Flat Patterns for Variant A2 (Over-the-Chassis)...")
dxf_v2_dir = os.path.join(VARIANTS_DIR, "02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS/CUTTING_PATTERNS_DXF")
os.makedirs(dxf_v2_dir, exist_ok=True)

def write_dxf_triangle(filepath, p1, p2, p3, plate_id):
    with open(filepath, 'w') as f:
        f.write("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n2\n")
        f.write("0\nLAYER\n2\nCUT_CONTOUR\n70\n0\n62\n7\n6\nCONTINUOUS\n0\n")
        f.write("0\nLAYER\n2\nTEXT_LABELS\n70\n0\n62\n1\n6\nCONTINUOUS\n0\n")
        f.write("0\nENDTAB\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nENTITIES\n")
        f.write("0\nPOLYLINE\n8\nCUT_CONTOUR\n66\n1\n70\n1\n")
        for pt in [p1, p2, p3]:
            f.write(f"0\nVERTEX\n8\nCUT_CONTOUR\n10\n{pt[0]:.4f}\n20\n{pt[1]:.4f}\n30\n0.0\n")
        f.write("0\nSEQEND\n")
        cx = (p1[0] + p2[0] + p3[0]) / 3.0
        cy = (p1[1] + p2[1] + p3[1]) / 3.0
        f.write(f"0\nTEXT\n8\nTEXT_LABELS\n10\n{cx:.4f}\n20\n{cy:.4f}\n30\n0.0\n40\n14.0\n1\n{plate_id}\n")
        f.write("0\nENDSEC\n0\nEOF\n")

for idx, r in df_a2.iterrows():
    p_id = r['Plate_ID']
    l1, l2, l3 = r['Edge_L1_mm'], r['Edge_L2_mm'], r['Edge_L3_mm']
    p1 = (0.0, 0.0)
    p2 = (l1, 0.0)
    x3 = (l1**2 + l3**2 - l2**2) / (2.0 * l1) if l1 > 1e-4 else 0.0
    y3 = math.sqrt(max(0.0, l3**2 - x3**2))
    p3 = (x3, y3)
    dxf_path = os.path.join(dxf_v2_dir, f"{p_id}_{r['Name']}.dxf")
    write_dxf_triangle(dxf_path, p1, p2, p3, p_id)

print(f"Generated {len(df_a2)} individual 1:1 DXFs in {dxf_v2_dir}")

# ----------------------------------------------------------------------
# 9. EXPORT ALL MASTER ASSEMBLIES (STEP, STL, FCStd)
# ----------------------------------------------------------------------
print("\n" + "="*70)
print("EXPORTING FULL VEHICLE ASSEMBLIES")
print("="*70)

# Master Assembly 1: Variant A1 (Infill)
a1_full = Part.makeCompound([chassis_shape, v_a1_solid, fw_assembly, rw_assembly])
a1_step = os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A1.step")
a1_full.exportStep(a1_step)
export_standard_binary_stl(a1_full, os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A1.stl"))

# Master Assembly 2: Variant A2 (Over-the-Chassis with 34 Standoff Bobbins)
a2_full = Part.makeCompound([chassis_shape, standoff_compound, v_a2_solid, fw_assembly, rw_assembly])
a2_step = os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A2.step")
a2_full.exportStep(a2_step)
export_standard_binary_stl(a2_full, os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A2.stl"))

# Master Assembly 3: Variant A3 (Aero-Duct Triangular)
a3_full = Part.makeCompound([chassis_shape, standoff_compound, v_a3_solid, fw_assembly, rw_assembly])
a3_step = os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A3.step")
a3_full.exportStep(a3_step)
export_standard_binary_stl(a3_full, os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A3.stl"))

# Default Full Vehicle Assembly (A2 Over-the-Chassis Hero)
def_step = os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Aero_Assembly.step")
def_stl = os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Aero_Assembly.stl")
a2_full.exportStep(def_step)
export_standard_binary_stl(a2_full, def_stl)

# FreeCAD Native Document for Full Vehicle Assembly
doc_full = App.newDocument("FSAE_Full_Vehicle_Aero_Package")
fc_ch = doc_full.addObject("Part::Feature", "Chassis_Spaceframe"); fc_ch.Shape = chassis_shape
fc_st = doc_full.addObject("Part::Feature", "Chassis_Standoff_Mounts"); fc_st.Shape = standoff_compound
fc_bd = doc_full.addObject("Part::Feature", "Bodywork_Over_Chassis_Faceted"); fc_bd.Shape = v_a2_solid
fc_fw = doc_full.addObject("Part::Feature", "Front_Wing_Assembly_MultiElem"); fc_fw.Shape = fw_assembly
fc_rw = doc_full.addObject("Part::Feature", "Rear_Wing_Assembly_MultiElem"); fc_rw.Shape = rw_assembly

grp1 = doc_full.addObject("App::DocumentObjectGroup", "Structure_Chassis_And_Mounts")
grp1.addObject(fc_ch); grp1.addObject(fc_st)
grp2 = doc_full.addObject("App::DocumentObjectGroup", "Aerodynamics_Package")
grp2.addObject(fc_bd); grp2.addObject(fc_fw); grp2.addObject(fc_rw)

doc_full.recompute()
doc_full.saveAs(os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Aero_Assembly.FCStd"))
App.closeDocument(doc_full.Name)

# ----------------------------------------------------------------------
# 10. SAVE VARIANT FOLDERS & STANDALONE FILES
# ----------------------------------------------------------------------
print("\n>>> Populating Variant Directories...")

# 00_WINGS_AERODYNAMIC_PACKAGE
dir_w = os.path.join(VARIANTS_DIR, "00_WINGS_AERODYNAMIC_PACKAGE")
os.makedirs(dir_w, exist_ok=True)
fw_assembly.exportStep(os.path.join(dir_w, "Front_Wing_Assembly_Realistic_MultiElement.STEP"))
export_standard_binary_stl(fw_assembly, os.path.join(dir_w, "Front_Wing_Assembly_Realistic_MultiElement.stl"))
rw_assembly.exportStep(os.path.join(dir_w, "Rear_Wing_Assembly_Realistic_MultiElement.STEP"))
export_standard_binary_stl(rw_assembly, os.path.join(dir_w, "Rear_Wing_Assembly_Realistic_MultiElement.stl"))
w_all = Part.makeCompound([fw_assembly, rw_assembly])
w_all.exportStep(os.path.join(dir_w, "Full_Wings_Aerodynamic_Package.STEP"))
export_standard_binary_stl(w_all, os.path.join(dir_w, "Full_Wings_Aerodynamic_Package.stl"))

doc_w_save = App.newDocument("Full_Wings_Aerodynamic_Package")
o1 = doc_w_save.addObject("Part::Feature", "Front_Wing_Assembly"); o1.Shape = fw_assembly
o2 = doc_w_save.addObject("Part::Feature", "Rear_Wing_Assembly"); o2.Shape = rw_assembly
doc_w_save.recompute(); doc_w_save.saveAs(os.path.join(dir_w, "Full_Wings_Aerodynamic_Package.FCStd")); App.closeDocument(doc_w_save.Name)

# 01_VARIANT_A1_TRIANGULAR_INFILL
dir_1 = os.path.join(VARIANTS_DIR, "01_VARIANT_A1_TRIANGULAR_INFILL")
os.makedirs(dir_1, exist_ok=True)
v_a1_solid.exportStep(os.path.join(dir_1, "Bodywork_Variant_A1_Triangular_Infill_Solid.STEP"))
v_a1_surf.exportStep(os.path.join(dir_1, "Bodywork_Variant_A1_Triangular_Infill_Surface.STEP"))
export_standard_binary_stl(v_a1_solid, os.path.join(dir_1, "Bodywork_Variant_A1_Triangular_Infill_Solid.stl"))
df_a1.to_csv(os.path.join(dir_1, "Variant_A1_Triangular_Plates_Schedule.csv"), index=False)
ch_a1 = Part.makeCompound([chassis_shape, v_a1_solid])
ch_a1.exportStep(os.path.join(dir_1, "Chassis_With_Bodywork_Variant_A1.STEP"))
export_standard_binary_stl(ch_a1, os.path.join(dir_1, "Chassis_With_Bodywork_Variant_A1.stl"))
doc_1 = App.newDocument("Chassis_With_Bodywork_Variant_A1")
o1 = doc_1.addObject("Part::Feature", "Chassis_Spaceframe"); o1.Shape = chassis_shape
o2 = doc_1.addObject("Part::Feature", "Bodywork_A1_Infill_Plates"); o2.Shape = v_a1_solid
doc_1.recompute(); doc_1.saveAs(os.path.join(dir_1, "Chassis_With_Bodywork_Variant_A1.FCStd")); App.closeDocument(doc_1.Name)

# 02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS
dir_2 = os.path.join(VARIANTS_DIR, "02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS")
os.makedirs(dir_2, exist_ok=True)
v_a2_solid.exportStep(os.path.join(dir_2, "Bodywork_Variant_A2_Triangular_Over_Chassis_Solid.STEP"))
v_a2_surf.exportStep(os.path.join(dir_2, "Bodywork_Variant_A2_Triangular_Over_Chassis_Surface.STEP"))
export_standard_binary_stl(v_a2_solid, os.path.join(dir_2, "Bodywork_Variant_A2_Triangular_Over_Chassis_Solid.stl"))
standoff_compound.exportStep(os.path.join(dir_2, "Chassis_Mounting_Standoffs_34_Bobbins.STEP"))
export_standard_binary_stl(standoff_compound, os.path.join(dir_2, "Chassis_Mounting_Standoffs_34_Bobbins.stl"))
df_a2.to_csv(os.path.join(dir_2, "Variant_A2_Triangular_Plates_Schedule.csv"), index=False)
df_standoffs.to_csv(os.path.join(dir_2, "Variant_A2_Chassis_Mounting_Standoffs_Schedule.csv"), index=False)
ch_a2 = Part.makeCompound([chassis_shape, standoff_compound, v_a2_solid])
ch_a2.exportStep(os.path.join(dir_2, "Chassis_With_Bodywork_Variant_A2.STEP"))
export_standard_binary_stl(ch_a2, os.path.join(dir_2, "Chassis_With_Bodywork_Variant_A2.stl"))
doc_2 = App.newDocument("Chassis_With_Bodywork_Variant_A2")
o1 = doc_2.addObject("Part::Feature", "Chassis_Spaceframe"); o1.Shape = chassis_shape
o2 = doc_2.addObject("Part::Feature", "Chassis_Mounting_Standoffs"); o2.Shape = standoff_compound
o3 = doc_2.addObject("Part::Feature", "Bodywork_A2_Over_Chassis_Plates"); o3.Shape = v_a2_solid
doc_2.recompute(); doc_2.saveAs(os.path.join(dir_2, "Chassis_With_Bodywork_Variant_A2.FCStd")); App.closeDocument(doc_2.Name)

# 03_VARIANT_A3_TRIANGULAR_AERO_DUCT
dir_3 = os.path.join(VARIANTS_DIR, "03_VARIANT_A3_TRIANGULAR_AERO_DUCT")
os.makedirs(dir_3, exist_ok=True)
v_a3_solid.exportStep(os.path.join(dir_3, "Bodywork_Variant_A3_Triangular_AeroDuct_Solid.STEP"))
v_a3_surf.exportStep(os.path.join(dir_3, "Bodywork_Variant_A3_Triangular_AeroDuct_Surface.STEP"))
export_standard_binary_stl(v_a3_solid, os.path.join(dir_3, "Bodywork_Variant_A3_Triangular_AeroDuct_Solid.stl"))
df_a3.to_csv(os.path.join(dir_3, "Variant_A3_Triangular_Plates_Schedule.csv"), index=False)
ch_a3 = Part.makeCompound([chassis_shape, standoff_compound, v_a3_solid])
ch_a3.exportStep(os.path.join(dir_3, "Chassis_With_Bodywork_Variant_A3.STEP"))
export_standard_binary_stl(ch_a3, os.path.join(dir_3, "Chassis_With_Bodywork_Variant_A3.stl"))
doc_3 = App.newDocument("Chassis_With_Bodywork_Variant_A3")
o1 = doc_3.addObject("Part::Feature", "Chassis_Spaceframe"); o1.Shape = chassis_shape
o2 = doc_3.addObject("Part::Feature", "Chassis_Mounting_Standoffs"); o2.Shape = standoff_compound
o3 = doc_3.addObject("Part::Feature", "Bodywork_A3_AeroDuct_Plates"); o3.Shape = v_a3_solid
doc_3.recompute(); doc_3.saveAs(os.path.join(dir_3, "Chassis_With_Bodywork_Variant_A3.FCStd")); App.closeDocument(doc_3.Name)

print("Saved all variant files.")

# ----------------------------------------------------------------------
# 11. GENERATE VISUALIZATIONS & HIGH-RES RENDERS
# ----------------------------------------------------------------------
print("\n>>> Generating High-Resolution 3D Visualization Renders...")

def render_compound_views(compounds_dict, title_text, output_img_path):
    fig = plt.figure(figsize=(20, 11), facecolor='#0d1117')
    fig.suptitle(title_text, fontsize=16, fontweight='bold', color='#f0f6fc', y=0.98)
    
    views = [
        ('Isometric Front-3/4 View', 25, -55, 1),
        ('Side Profile Elevation View', 0, -90, 2),
        ('Top Aerodynamic Planform View', 90, -90, 3),
        ('Rear Inflow / Wing View', 20, 125, 4)
    ]
    
    for v_title, elev, azim, sp_idx in views:
        ax = fig.add_subplot(2, 2, sp_idx, projection='3d', facecolor='#161b22')
        ax.set_title(v_title, fontsize=12, fontweight='bold', color='#58a6ff', pad=10)
        
        for name, (shape, color, alpha, edge_c) in compounds_dict.items():
            if shape is None: continue
            verts, facets = shape.tessellate(1.5)
            verts = np.array(verts)
            if len(facets) == 0: continue
            triangles = [verts[list(f)] for f in facets]
            poly = Poly3DCollection(triangles, facecolors=color, edgecolors=edge_c,
                                    linewidths=0.3, alpha=alpha)
            ax.add_collection3d(poly)
            
        ax.set_xlim(-800, 800)
        ax.set_ylim(-1600, 1400)
        ax.set_zlim(0, 1350)
        ax.view_init(elev=elev, azim=azim)
        ax.axis('off')
        
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    plt.savefig(output_img_path, dpi=200, facecolor=fig.get_facecolor())
    plt.close()
    print(f"Rendered: {output_img_path}")

# Render Full Vehicle A2 (Over-the-Chassis)
render_compound_views({
    'Chassis': (chassis_shape, '#6e7681', 0.25, '#484f58'),
    'Standoffs': (standoff_compound, '#d29922', 0.90, '#e3b341'),
    'Bodywork_A2': (v_a2_solid, '#238636', 0.85, '#3fb950'),
    'Front_Wing': (fw_assembly, '#da3633', 0.85, '#f85149'),
    'Rear_Wing': (rw_assembly, '#da3633', 0.85, '#f85149')
}, "FSAE Full Vehicle Assembly: Variant A2 (Over-the-Chassis Stealth Faceted Fairing) + Multi-Element Wings",
os.path.join(dir_2, "variant_a2_over_chassis_full_views.png"))

# Copy to brain and assemblies
shutil.copy2(os.path.join(dir_2, "variant_a2_over_chassis_full_views.png"),
             os.path.join(BRAIN_DIR, "variant_a2_over_chassis_full_views.png"))
shutil.copy2(os.path.join(dir_2, "variant_a2_over_chassis_full_views.png"),
             os.path.join(ASSEMBLIES_DIR, "FSAE_Full_Vehicle_Assembly_Variant_A2_Views.png"))

# Render Front Wing Detail
fig = plt.figure(figsize=(14, 8), facecolor='#0d1117')
fig.suptitle("FSAE Realistic Multi-Element Front Wing Assembly (Mainplane + 2 Flaps + Footplates + Strakes + Pylons)", 
             fontsize=14, fontweight='bold', color='#f0f6fc')
ax1 = fig.add_subplot(1, 2, 1, projection='3d', facecolor='#161b22')
ax1.set_title("Front-3/4 Isometric Detail", fontsize=11, color='#58a6ff')
verts, facets = fw_assembly.tessellate(1.0)
verts = np.array(verts)
triangles = [verts[list(f)] for f in facets]
poly1 = Poly3DCollection(triangles, facecolors='#da3633', edgecolors='#f85149', linewidths=0.2, alpha=0.9)
ax1.add_collection3d(poly1)
ax1.set_xlim(-750, 750); ax1.set_ylim(650, 1350); ax1.set_zlim(20, 240)
ax1.view_init(elev=22, azim=-60); ax1.axis('off')

ax2 = fig.add_subplot(1, 2, 2, projection='3d', facecolor='#161b22')
ax2.set_title("Underwing Ground Effect View (Strakes & Footplates)", fontsize=11, color='#58a6ff')
poly2 = Poly3DCollection(triangles, facecolors='#a40e26', edgecolors='#da3633', linewidths=0.2, alpha=0.9)
ax2.add_collection3d(poly2)
ax2.set_xlim(-750, 750); ax2.set_ylim(650, 1350); ax2.set_zlim(20, 240)
ax2.view_init(elev=-25, azim=-45); ax2.axis('off')

plt.tight_layout(rect=[0, 0.02, 1, 0.95])
fw_img = os.path.join(dir_w, "front_wing_realistic_assembly_detail.png")
plt.savefig(fw_img, dpi=200, facecolor=fig.get_facecolor())
plt.close()
shutil.copy2(fw_img, os.path.join(BRAIN_DIR, "front_wing_realistic_assembly_detail.png"))
print("Rendered Front Wing Detail.")

# Render Rear Wing Detail
fig = plt.figure(figsize=(14, 8), facecolor='#0d1117')
fig.suptitle("FSAE Realistic Multi-Element Rear Wing Assembly (Mainplane + 2 Flaps + Beam Wing + DRS Pod + Swan-Necks)", 
             fontsize=14, fontweight='bold', color='#f0f6fc')
ax1 = fig.add_subplot(1, 2, 1, projection='3d', facecolor='#161b22')
ax1.set_title("Swan-Neck & DRS Actuator Pod View", fontsize=11, color='#58a6ff')
verts, facets = rw_assembly.tessellate(1.0)
verts = np.array(verts)
triangles = [verts[list(f)] for f in facets]
poly1 = Poly3DCollection(triangles, facecolors='#1f6feb', edgecolors='#58a6ff', linewidths=0.2, alpha=0.9)
ax1.add_collection3d(poly1)
ax1.set_xlim(-500, 500); ax1.set_ylim(-1600, -1100); ax1.set_zlim(300, 1350)
ax1.view_init(elev=20, azim=135); ax1.axis('off')

ax2 = fig.add_subplot(1, 2, 2, projection='3d', facecolor='#161b22')
ax2.set_title("Endplate Louvers & Multi-Element Cascade", fontsize=11, color='#58a6ff')
poly2 = Poly3DCollection(triangles, facecolors='#1158c7', edgecolors='#388bfd', linewidths=0.2, alpha=0.9)
ax2.add_collection3d(poly2)
ax2.set_xlim(-500, 500); ax2.set_ylim(-1600, -1100); ax2.set_zlim(300, 1350)
ax2.view_init(elev=15, azim=-35); ax2.axis('off')

plt.tight_layout(rect=[0, 0.02, 1, 0.95])
rw_img = os.path.join(dir_w, "rear_wing_realistic_assembly_detail.png")
plt.savefig(rw_img, dpi=200, facecolor=fig.get_facecolor())
plt.close()
shutil.copy2(rw_img, os.path.join(BRAIN_DIR, "rear_wing_realistic_assembly_detail.png"))
print("Rendered Rear Wing Detail.")

# ----------------------------------------------------------------------
# 12. PACKAGING ZIP & TAR.GZ ARCHIVES & MIRRORING TO DRIVE
# ----------------------------------------------------------------------
print("\n>>> Building Distribution Archives (.zip and .tar.gz)...")
import zipfile, tarfile

dirs_to_package = [
    ("00_WINGS_AERODYNAMIC_PACKAGE", dir_w),
    ("01_VARIANT_A1_TRIANGULAR_INFILL", dir_1),
    ("02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS", dir_2),
    ("03_VARIANT_A3_TRIANGULAR_AERO_DUCT", dir_3),
]

for name, src_dir in dirs_to_package:
    temp_zip = f"/tmp/{name}.zip"
    temp_tar = f"/tmp/{name}.tar.gz"
    if os.path.exists(temp_zip): os.remove(temp_zip)
    if os.path.exists(temp_tar): os.remove(temp_tar)
    
    with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith('.FCBak'): continue
                fp = os.path.join(root, file)
                arcname = os.path.relpath(fp, os.path.dirname(src_dir))
                zf.write(fp, arcname)
                
    with tarfile.open(temp_tar, 'w:gz') as tf:
        tf.add(src_dir, arcname=name, filter=lambda ti: None if ti.name.endswith('.FCBak') else ti)
        
    for dest in [VARIANTS_DIR, DOWNLOADS_DIR, DRIVE_DIR, PROJECT_DIR]:
        shutil.copy2(temp_zip, os.path.join(dest, f"{name}.zip"))
        shutil.copy2(temp_tar, os.path.join(dest, f"{name}.tar.gz"))
    print(f"Packaged & Synced: {name}")

# Also mirror directories directly
for name, src_dir in dirs_to_package:
    for dest_root in [DOWNLOADS_DIR, DRIVE_DIR, PROJECT_DIR]:
        target = os.path.join(dest_root, name)
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(src_dir, target)

print("\n" + "="*75)
print("PIPELINE COMPLETED SUCCESSFULLY!")
print("="*75)
