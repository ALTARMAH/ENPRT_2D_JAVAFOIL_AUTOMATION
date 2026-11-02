import sys, math
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

def norm_vec(x, y, z):
    v = App.Vector(x, y, z)
    if v.Length > 1e-6: v.normalize()
    return v

CHASSIS_STEP = '/home/user/Downloads/Chassis.STEP'
doc_ch = App.newDocument('ChTest')
Import.insert(CHASSIS_STEP, doc_ch.Name)
chassis = doc_ch.Objects[0].Shape.copy()
App.closeDocument(doc_ch.Name)

# Master Chassis Nodes
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

# Define calibrated outer node positions:
# Each node is offset outwards from the tube surface (tube radius ~12.7-15mm)
# Standoff distance = 20 to 25mm -> Total offset = 35 to 40mm.
NODES_OUTER = {
    # Nosecone apex (extended forward by 45mm to clear impact attenuator)
    'NOSE_TIP': App.Vector(0.0, 1195.0, 195.0),
    
    # Front Bulkhead (Y=700)
    'FB_TL': App.Vector(-245.0, 725.0, 395.0),
    'FB_TR': App.Vector( 245.0, 725.0, 395.0),
    'FB_BL': App.Vector(-250.0, 725.0,   8.0),
    'FB_BR': App.Vector( 250.0, 725.0,   8.0),
    
    # Front Bay Mid (Y=200)
    'FN_ML': App.Vector(-310.0, 200.0, 200.0),
    'FN_MR': App.Vector( 310.0, 200.0, 200.0),
    'FN_BL': App.Vector(-255.0, 200.0,   8.0),
    'FN_BR': App.Vector( 255.0, 200.0,   8.0),
    
    # Front Hoop (Y=0)
    'FH_TL': App.Vector(-210.0,   0.0, 625.0),
    'FH_TR': App.Vector( 210.0,   0.0, 625.0),
    'FH_SL': App.Vector(-285.0,   0.0, 565.0),
    'FH_SR': App.Vector( 285.0,   0.0, 565.0),
    'FH_ML': App.Vector(-310.0,   0.0, 200.0),
    'FH_MR': App.Vector( 310.0,   0.0, 200.0),
    'FH_BL': App.Vector(-255.0,   0.0,   8.0),
    'FH_BR': App.Vector( 255.0,   0.0,   8.0),
    
    # Main Hoop Fastback & Cockpit (Y=-875)
    'MH_TOP': App.Vector(  0.0, -905.0, 1290.0),
    'MH_BL':  App.Vector(-165.0, -905.0, 1095.0),
    'MH_BR':  App.Vector( 165.0, -905.0, 1095.0),
    'SIS_TL': App.Vector(-395.0, -875.0, 375.0),
    'SIS_TR': App.Vector( 395.0, -875.0, 375.0),
    'SIS_BL': App.Vector(-305.0, -875.0,   8.0),
    'SIS_BR': App.Vector( 305.0, -875.0,   8.0),
    
    # Engine Bay Mid (Y=-1200)
    'EM_ML': App.Vector(-338.0, -1200.0, 205.0),
    'EM_MR': App.Vector( 338.0, -1200.0, 205.0),
    'EM_BL': App.Vector(-275.0, -1200.0,   8.0),
    'EM_BR': App.Vector( 275.0, -1200.0,   8.0),
    
    # Rear Bulkhead (Y=-1400 -> rearward standoff at Y=-1435)
    'RB_TL': App.Vector(-245.0, -1435.0, 370.0),
    'RB_TR': App.Vector( 245.0, -1435.0, 370.0),
    'RB_ML': App.Vector(-335.0, -1435.0, 205.0),
    'RB_MR': App.Vector( 335.0, -1435.0, 205.0),
    'RB_BL': App.Vector(-275.0, -1435.0,  15.0),
    'RB_BR': App.Vector( 275.0, -1435.0,  15.0),
}

# Undertray floor nodes (separate for pure floorpan if needed, but here RB_BL/BR are at Y=-1435, Z=15)
# Note: For floor panels extending from SIS to rear bulkhead, the floor pan ends at Y=-1400, Z=8.0
NODES_OUTER['RB_FLOOR_L'] = App.Vector(-275.0, -1405.0, 8.0)
NODES_OUTER['RB_FLOOR_R'] = App.Vector( 275.0, -1405.0, 8.0)

PLATE_TOPOLOGY = [
    # Nosecone Fairing
    ('P01_Nose_Top_Rake',        ['NOSE_TIP', 'FB_TL', 'FB_TR']),
    ('P02_Nose_Left_Cheek',      ['NOSE_TIP', 'FB_BL', 'FB_TL']),
    ('P03_Nose_Right_Cheek',     ['NOSE_TIP', 'FB_TR', 'FB_BR']),
    ('P04_Nose_Underbody_Tray',  ['NOSE_TIP', 'FB_BR', 'FB_BL']),
    # Front Deck
    ('P05_FrontDeck_Left',       ['FB_TL', 'FB_TR', 'FH_TL']),
    ('P06_FrontDeck_Right',      ['FB_TR', 'FH_TR', 'FH_TL']),
    ('P07_FrontDeck_Shoulder_L', ['FB_TL', 'FH_TL', 'FH_SL']),
    ('P08_FrontDeck_Shoulder_R', ['FB_TR', 'FH_SR', 'FH_TR']),
    # Front Flank L
    ('P09_FrontFlank_Upper_L',   ['FB_TL', 'FH_SL', 'FN_ML']),
    ('P10_FrontFlank_Fwd_L',     ['FB_TL', 'FN_ML', 'FB_BL']),
    ('P11_FrontFlank_Mid_L',     ['FB_BL', 'FN_ML', 'FN_BL']),
    ('P12_FrontFlank_AftUp_L',   ['FN_ML', 'FH_SL', 'FH_ML']),
    ('P13_FrontFlank_AftLo_L',   ['FN_ML', 'FH_ML', 'FN_BL']),
    ('P14_FrontFlank_BotAft_L',  ['FN_BL', 'FH_ML', 'FH_BL']),
    # Front Flank R
    ('P15_FrontFlank_Upper_R',   ['FB_TR', 'FN_MR', 'FH_SR']),
    ('P16_FrontFlank_Fwd_R',     ['FB_TR', 'FB_BR', 'FN_MR']),
    ('P17_FrontFlank_Mid_R',     ['FB_BR', 'FN_BR', 'FN_MR']),
    ('P18_FrontFlank_AftUp_R',   ['FN_MR', 'FH_MR', 'FH_SR']),
    ('P19_FrontFlank_AftLo_R',   ['FN_MR', 'FH_MR', 'FN_BR']),
    ('P20_FrontFlank_BotAft_R',  ['FN_BR', 'FH_MR', 'FH_BR']),
    # Side Impact
    ('P21_SIS_Upper_L',          ['FH_ML', 'SIS_TL', 'SIS_BL']),
    ('P22_SIS_Lower_L',          ['FH_ML', 'SIS_BL', 'FH_BL']),
    ('P23_Cockpit_Deflector_L',  ['FH_SL', 'SIS_TL', 'FH_ML']),
    ('P24_SIS_Upper_R',          ['FH_MR', 'SIS_BR', 'SIS_TR']),
    ('P25_SIS_Lower_R',          ['FH_MR', 'SIS_BR', 'FH_BR']),
    ('P26_Cockpit_Deflector_R',  ['FH_SR', 'FH_MR', 'SIS_TR']),
    # Engine Cowl & Flanks
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
    # Rear Transom Bulkhead
    ('P39_RearBulkhead_Top',     ['RB_TL', 'RB_TR', 'RB_BL']),
    ('P40_RearBulkhead_Bottom',  ['RB_TR', 'RB_BR', 'RB_BL']),
    # Underbody Floor
    ('P41_Floor_Front_L',        ['FB_BL', 'FB_BR', 'FH_BL']),
    ('P42_Floor_Front_R',        ['FB_BR', 'FH_BR', 'FH_BL']),
    ('P43_Floor_Mid_L',          ['FH_BL', 'FH_BR', 'SIS_BL']),
    ('P44_Floor_Mid_R',          ['FH_BR', 'SIS_BR', 'SIS_BL']),
    ('P45_Floor_Rear_L',         ['SIS_BL', 'SIS_BR', 'RB_FLOOR_L']),
    ('P46_Floor_Rear_R',         ['SIS_BR', 'RB_FLOOR_R', 'RB_FLOOR_L']),
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
    
    norm = (v2 - v1).cross(v3 - v1)
    norm.normalize()
    
    if 'Floor' in p_id or 'Underbody' in p_id:
        outward_dir = App.Vector(0.0, 0.0, -1.0)
    elif 'RearBulkhead' in p_id:
        outward_dir = App.Vector(0.0, -1.0, 0.0)
    elif 'Nose' in p_id and 'Top' in p_id:
        outward_dir = App.Vector(0.0, 0.5, 0.86)
    elif 'FrontDeck' in p_id:
        outward_dir = App.Vector(0.0, 0.2, 0.98)
    elif 'EngineDeck' in p_id:
        outward_dir = App.Vector(0.0, -0.6, 0.8)
    else:
        y_c = centroid.y
        z_ref = 220.0
        if y_c < -800: z_ref = 280.0
        elif y_c > 600: z_ref = 180.0
        ref_pt = App.Vector(0.0, y_c, z_ref)
        outward_dir = centroid - ref_pt
        
    if norm.dot(outward_dir) < 0:
        norm = -norm
        
    poly = Part.makePolygon([v1_in, v2_in, v3_in, v1_in])
    face = Part.Face(poly)
    # Extrude outward
    solid = face.extrude(norm * 1.5)
    solids.append((p_id, solid))

comp = Part.makeCompound([s for _, s in solids])
print(f"Body compound built: {len(solids)} solids, isValid={comp.isValid()}")
print(f"Compound check(True): {comp.check(True)}")

# Check inter-plate clashing
clash_v = 0.0
for i in range(len(solids)):
    for j in range(i+1, len(solids)):
        if solids[i][1].BoundBox.intersect(solids[j][1].BoundBox):
            v_com = solids[i][1].common(solids[j][1]).Volume
            if v_com > 0.01:
                clash_v += v_com
print(f"Inter-plate clashing volume: {clash_v:.4f} mm3")

# Check Body vs Chassis
clashes = []
total_body_chassis_v = 0.0
for p_id, s in solids:
    if s.BoundBox.intersect(chassis.BoundBox):
        v = s.common(chassis).Volume
        if v > 0.001:
            clashes.append((p_id, v))
            total_body_chassis_v += v

print(f"Clashing plates with chassis: {len(clashes)} (Total Volume: {total_body_chassis_v:.4f} mm3)")
for p_id, v in clashes:
    print(f"  {p_id}: {v:.4f} mm3")

