import sys, math
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

def norm_vec(x, y, z):
    v = App.Vector(x, y, z)
    if v.Length > 1e-6:
        v.normalize()
    return v

CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"

doc_ch = App.newDocument("ChTest")
Import.insert(CHASSIS_STEP, doc_ch.Name)
chassis = doc_ch.Objects[0].Shape.copy()
App.closeDocument(doc_ch.Name)

NODES_CHASSIS = {
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

# Floor nodes
FLOOR_NODE_KEYS = {'FB_BL', 'FB_BR', 'FN_BL', 'FN_BR', 'FH_BL', 'FH_BR', 'SIS_BL', 'SIS_BR', 'EM_BL', 'EM_BR', 'RB_BL', 'RB_BR'}

NODES_OUTER = {}
STANDOFF_VECS = {}

for k, pt in NODES_CHASSIS.items():
    if k == 'NOSE_TIP':
        vec = norm_vec(0.0, 1.0, 0.2)
        offset_dist = 30.0
    elif k in ['RB_TL', 'RB_TR']:
        vec = norm_vec(0.3 if pt.x>0 else -0.3, -0.9, 0.3)
        offset_dist = 28.0
    elif k in ['RB_ML', 'RB_MR']:
        vec = norm_vec(0.5 if pt.x>0 else -0.5, -0.85, 0.0)
        offset_dist = 28.0
    elif k in ['RB_BL', 'RB_BR']:
        vec = norm_vec(0.3 if pt.x>0 else -0.3, -0.85, -0.4)
        offset_dist = 28.0
    elif k in ['FB_TL', 'FB_TR']:
        vec = norm_vec(0.5 if pt.x>0 else -0.5, 0.6, 0.6)
        offset_dist = 28.0
    elif k in ['FH_TL', 'FH_TR']:
        vec = norm_vec(0.2 if pt.x>0 else -0.2, 0.0, 0.98)
        offset_dist = 28.0
    elif k in ['FH_SL', 'FH_SR']:
        vec = norm_vec(0.85 if pt.x>0 else -0.85, 0.0, 0.52)
        offset_dist = 28.0
    elif k in ['MH_BL', 'MH_BR', 'MH_TOP']:
        vec = norm_vec(0.4 if pt.x>0 else -0.4, 0.0, 0.92)
        offset_dist = 28.0
    elif k in FLOOR_NODE_KEYS:
        vx = 1.0 if pt.x > 0 else -1.0
        vec = norm_vec(vx * 0.5, 0.0, -0.86)
        offset_dist = 28.0
    else:
        # Flank nodes
        vx = 1.0 if pt.x > 0 else -1.0
        vy = 0.0
        if pt.y > 400: vy = 0.3
        elif pt.y < -1000: vy = -0.3
        vz = 0.1 if pt.z > 150 else -0.1
        vec = norm_vec(vx, vy, vz)
        offset_dist = 28.0
        
    p_inner = pt + vec * offset_dist
    if k in FLOOR_NODE_KEYS:
        # Undertray sits at Z = 8.0 mm (chassis lowest point is Z = 13.5 mm)
        p_inner = App.Vector(pt.x + (20.0 if pt.x>0 else -20.0), pt.y, 8.0)
        
    NODES_OUTER[k] = p_inner
    STANDOFF_VECS[k] = vec

PLATE_TOPOLOGY = [
    ('P01_Nose_Top_Rake',        ['NOSE_TIP', 'FB_TL', 'FB_TR']),
    ('P02_Nose_Left_Cheek',      ['NOSE_TIP', 'FB_BL', 'FB_TL']),
    ('P03_Nose_Right_Cheek',     ['NOSE_TIP', 'FB_TR', 'FB_BR']),
    ('P04_Nose_Underbody_Tray',  ['NOSE_TIP', 'FB_BR', 'FB_BL']),
    ('P05_FrontDeck_Left',       ['FB_TL', 'FB_TR', 'FH_TL']),
    ('P06_FrontDeck_Right',      ['FB_TR', 'FH_TR', 'FH_TL']),
    ('P07_FrontDeck_Shoulder_L', ['FB_TL', 'FH_TL', 'FH_SL']),
    ('P08_FrontDeck_Shoulder_R', ['FB_TR', 'FH_SR', 'FH_TR']),
    ('P09_FrontFlank_Upper_L',   ['FB_TL', 'FH_SL', 'FN_ML']),
    ('P10_FrontFlank_Fwd_L',     ['FB_TL', 'FN_ML', 'FB_BL']),
    ('P11_FrontFlank_Mid_L',     ['FB_BL', 'FN_ML', 'FN_BL']),
    ('P12_FrontFlank_AftUp_L',   ['FN_ML', 'FH_SL', 'FH_ML']),
    ('P13_FrontFlank_AftLo_L',   ['FN_ML', 'FH_ML', 'FN_BL']),
    ('P14_FrontFlank_BotAft_L',  ['FN_BL', 'FH_ML', 'FH_BL']),
    ('P15_FrontFlank_Upper_R',   ['FB_TR', 'FN_MR', 'FH_SR']),
    ('P16_FrontFlank_Fwd_R',     ['FB_TR', 'FB_BR', 'FN_MR']),
    ('P17_FrontFlank_Mid_R',     ['FB_BR', 'FN_BR', 'FN_MR']),
    ('P18_FrontFlank_AftUp_R',   ['FN_MR', 'FH_MR', 'FH_SR']),
    ('P19_FrontFlank_AftLo_R',   ['FN_MR', 'FH_MR', 'FN_BR']),
    ('P20_FrontFlank_BotAft_R',  ['FN_BR', 'FH_MR', 'FH_BR']),
    ('P21_SIS_Upper_L',          ['FH_ML', 'SIS_TL', 'SIS_BL']),
    ('P22_SIS_Lower_L',          ['FH_ML', 'SIS_BL', 'FH_BL']),
    ('P23_Cockpit_Deflector_L',  ['FH_SL', 'SIS_TL', 'FH_ML']),
    ('P24_SIS_Upper_R',          ['FH_MR', 'SIS_BR', 'SIS_TR']),
    ('P25_SIS_Lower_R',          ['FH_MR', 'SIS_BR', 'FH_BR']),
    ('P26_Cockpit_Deflector_R',  ['FH_SR', 'FH_MR', 'SIS_TR']),
    ('P27_EngineDeck_Top_L',     ['MH_BL', 'MH_BR', 'RB_TL']),
    ('P28_EngineDeck_Top_R',     ['MH_BR', 'RB_TR', 'RB_TL']),
    ('P29_EngineFlank_Upper_L',  ['MH_BL', 'RB_TL', 'EM_ML']),
    ('P30_EngineFlank_Upper_R',  ['MH_BR', 'EM_MR', 'RB_TR']),
    ('P31_EngineFlank_Side_L',   ['SIS_TL', 'EM_ML', 'SIS_BL']),
    ('P32_EngineFlank_Side_R',   ['SIS_TR', 'SIS_BR', 'EM_MR']),
    ('P33_EngineFlank_Mid_L',    ['EM_ML', 'RB_ML', 'SIS_BL']),
    ('P34_EngineFlank_Mid_R',    ['EM_MR', 'SIS_BR', 'RB_MR']),
    ('P35_EngineFlank_Lower_L',  ['SIS_BL', 'RB_ML', 'RB_BL']),
    ('P36_EngineFlank_Lower_R',  ['SIS_BR', 'RB_BR', 'RB_MR']),
    ('P37_EngineFlank_Corner_L', ['RB_TL', 'RB_ML', 'EM_ML']),
    ('P38_EngineFlank_Corner_R', ['RB_TR', 'EM_MR', 'RB_MR']),
    ('P39_RearBulkhead_Top',     ['RB_TL', 'RB_TR', 'RB_BL']),
    ('P40_RearBulkhead_Bottom',  ['RB_TR', 'RB_BR', 'RB_BL']),
    ('P41_Floor_Front_L',        ['FB_BL', 'FB_BR', 'FH_BL']),
    ('P42_Floor_Front_R',        ['FB_BR', 'FH_BR', 'FH_BL']),
    ('P43_Floor_Mid_L',          ['FH_BL', 'FH_BR', 'SIS_BL']),
    ('P44_Floor_Mid_R',          ['FH_BR', 'SIS_BR', 'SIS_BL']),
    ('P45_Floor_Rear_L',         ['SIS_BL', 'SIS_BR', 'RB_BL']),
    ('P46_Floor_Rear_R',         ['SIS_BR', 'RB_BR', 'RB_BL']),
]

def inset_pt(pt, cent, dist=1.2):
    vec = cent - pt
    l = vec.Length
    if l > dist: return pt + vec * (dist / l)
    return pt

solids = []
for p_id, keys in PLATE_TOPOLOGY:
    v1 = NODES_OUTER[keys[0]]
    v2 = NODES_OUTER[keys[1]]
    v3 = NODES_OUTER[keys[2]]
    centroid = (v1 + v2 + v3) / 3.0
    
    v1_in = inset_pt(v1, centroid, 1.2)
    v2_in = inset_pt(v2, centroid, 1.2)
    v3_in = inset_pt(v3, centroid, 1.2)
    
    # Compute normal
    norm = (v2 - v1).cross(v3 - v1)
    norm.normalize()
    
    # Outward reference direction
    y_c = centroid.y
    z_ref = 220.0
    if y_c < -800: z_ref = 280.0
    elif y_c > 600: z_ref = 180.0
    ref_pt = App.Vector(0.0, y_c, z_ref)
    
    if 'Floor' in p_id or 'Underbody' in p_id:
        outward_dir = App.Vector(0.0, 0.0, -1.0)
    elif 'RearBulkhead' in p_id:
        outward_dir = App.Vector(0.0, -1.0, 0.0)
    elif 'Nose' in p_id and 'Top' in p_id:
        outward_dir = App.Vector(0.0, 0.5, 0.86)
    else:
        outward_dir = centroid - ref_pt
        
    if norm.dot(outward_dir) < 0:
        norm = -norm
        
    poly = Part.makePolygon([v1_in, v2_in, v3_in, v1_in])
    face = Part.Face(poly)
    solid = face.extrude(norm * 1.5)
    solids.append((p_id, solid))

body_comp = Part.makeCompound([s for _, s in solids])
print(f"Bodywork: {len(solids)} solids, isValid={body_comp.isValid()}")

# Check Body vs Chassis
clashes = []
for p_id, s in solids:
    if s.BoundBox.intersect(chassis.BoundBox):
        v = s.common(chassis).Volume
        if v > 0.001:
            clashes.append((p_id, v))

print(f"Body vs Chassis Clashing plates: {len(clashes)}")
for p_id, v in clashes:
    print(f"  {p_id}: {v:.4f} mm3")

# Check Inter-plate clashing
clash_v = 0.0
for i in range(len(solids)):
    for j in range(i+1, len(solids)):
        if solids[i][1].BoundBox.intersect(solids[j][1].BoundBox):
            v_com = solids[i][1].common(solids[j][1]).Volume
            if v_com > 0.01:
                clash_v += v_com
print(f"Inter-plate clashing: {clash_v:.4f} mm3")
