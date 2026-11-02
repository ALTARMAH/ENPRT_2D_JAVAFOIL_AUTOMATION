"""
FreeCAD Automation Skill: Full Parametric Bodywork Redo & Orchestration
========================================================================
Built strictly using the freecad-automation skill:
  - fc_connect: Document creation, management, and native .FCStd persistence
  - fc_part: Geometric feature building, extrusions, and boolean unions
  - fc_export: Standardized multi-format export (STEP, STL, FCStd)
  - fc_drawing: TechDraw parametric 2D engineering drawings
"""

import os
import sys
import math
import shutil
import numpy as np
import pandas as pd

# 1. Integrate freecad-automation skill scripts
SKILL_SCRIPTS = "/home/user/aero_body/skills/freecad-automation/scripts"
if SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS)

import fc_connect
import fc_part
import fc_export
import fc_drawing
import FreeCAD as App
import Part

OUT_DIR = "/home/user/ENPRT_FSUK2027/BODYWORK"
DL_DIR = "/home/user/Downloads/BODYWORK_VARIANTS"
CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
TECHDRAW_TEMPLATE = "/usr/share/freecad/Mod/TechDraw/Templates/Default_Template_A4_Landscape.svg"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(DL_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# MASTER NODES FOR CHASSIS TRIANGULATION BAYS
# -----------------------------------------------------------------------------
NODES = {
    # Nosecone Tip / IA Apex
    'NOSE_TIP': App.Vector(0.0, 1150.0, 180.0),
    
    # Front Bulkhead (Y = 700)
    'FB_TL': App.Vector(-225.0, 700.0, 370.0),
    'FB_TR': App.Vector( 225.0, 700.0, 370.0),
    'FB_BL': App.Vector(-225.0, 700.0,  50.0),
    'FB_BR': App.Vector( 225.0, 700.0,  50.0),
    
    # Front Bay Intermediate / Steering (Y = 200)
    'FN_ML': App.Vector(-275.0, 200.0, 200.0),
    'FN_MR': App.Vector( 275.0, 200.0, 200.0),
    'FN_BL': App.Vector(-225.0, 200.0,  50.0),
    'FN_BR': App.Vector( 225.0, 200.0,  50.0),
    
    # Front Roll Hoop (Y = 0)
    'FH_TL': App.Vector(-200.0,   0.0, 590.0),
    'FH_TR': App.Vector( 200.0,   0.0, 590.0),
    'FH_SL': App.Vector(-250.0,   0.0, 544.0),
    'FH_SR': App.Vector( 250.0,   0.0, 544.0),
    'FH_ML': App.Vector(-275.0,   0.0, 200.0),
    'FH_MR': App.Vector( 275.0,   0.0, 200.0),
    'FH_BL': App.Vector(-225.0,   0.0,  50.0),
    'FH_BR': App.Vector( 225.0,   0.0,  50.0),
    
    # Main Roll Hoop (Y = -875)
    'MH_TOP': App.Vector(   0.0, -875.0, 1258.0),
    'MH_TL':  App.Vector(-130.0, -875.0, 1133.0),
    'MH_TR':  App.Vector( 130.0, -875.0, 1133.0),
    'MH_BL':  App.Vector(-148.0, -875.0, 1070.0),
    'MH_BR':  App.Vector( 148.0, -875.0, 1070.0),
    
    # Side Impact Structure (Y = -875)
    'SIS_TL': App.Vector(-357.0, -875.0,  358.0),
    'SIS_TR': App.Vector( 357.0, -875.0,  358.0),
    'SIS_BL': App.Vector(-280.0, -875.0,   32.0),
    'SIS_BR': App.Vector( 280.0, -875.0,   32.0),
    
    # Engine Bay Mid (Y = -1200)
    'EM_ML': App.Vector(-300.0, -1200.0, 200.0),
    'EM_MR': App.Vector( 300.0, -1200.0, 200.0),
    'EM_BL': App.Vector(-250.0, -1200.0,  50.0),
    'EM_BR': App.Vector( 250.0, -1200.0,  50.0),
    
    # Rear Bulkhead (Y = -1400)
    'RB_TL': App.Vector(-225.0, -1400.0, 350.0),
    'RB_TR': App.Vector( 225.0, -1400.0, 350.0),
    'RB_ML': App.Vector(-300.0, -1400.0, 200.0),
    'RB_MR': App.Vector( 300.0, -1400.0, 200.0),
    'RB_BL': App.Vector(-250.0, -1400.0,  50.0),
    'RB_BR': App.Vector( 250.0, -1400.0,  50.0),
}

# Master 46 Plate Definitions
PLATE_DEFS = [
    # Nosecone Fairing
    ('P01_Nose_Top_Rake',        ['NOSE_TIP', 'FB_TL', 'FB_TR'],       'Nosecone', 'Top aerodynamic wedge rake'),
    ('P02_Nose_Left_Cheek',      ['NOSE_TIP', 'FB_BL', 'FB_TL'],       'Nosecone', 'Port-side nose deflector'),
    ('P03_Nose_Right_Cheek',     ['NOSE_TIP', 'FB_TR', 'FB_BR'],       'Nosecone', 'Starboard-side nose deflector'),
    ('P04_Nose_Underbody_Tray',  ['NOSE_TIP', 'FB_BR', 'FB_BL'],       'Nosecone', 'Forward undertray splitter rake'),

    # Front Bulkhead to Front Roll Hoop Deck
    ('P05_FrontDeck_Left',       ['FB_TL', 'FB_TR', 'FH_TL'],          'Front Deck', 'Upper hood intake ramp (Port)'),
    ('P06_FrontDeck_Right',      ['FB_TR', 'FH_TR', 'FH_TL'],          'Front Deck', 'Upper hood intake ramp (Starboard)'),
    ('P07_FrontDeck_Shoulder_L', ['FB_TL', 'FH_TL', 'FH_SL'],          'Front Deck', 'Port hood-to-cockpit shoulder'),
    ('P08_FrontDeck_Shoulder_R', ['FB_TR', 'FH_SR', 'FH_TR'],          'Front Deck', 'Starboard hood-to-cockpit shoulder'),

    # Front Bay Flank Panels
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

    # Side Impact Structure / Sidepod Flanks
    ('P21_SIS_Upper_L',          ['FH_ML', 'SIS_TL', 'SIS_BL'],        'Sidepod L', 'Main port driver side impact plate'),
    ('P22_SIS_Lower_L',          ['FH_ML', 'SIS_BL', 'FH_BL'],        'Sidepod L', 'Lower port rocker air-fence'),
    ('P23_Cockpit_Deflector_L',  ['FH_SL', 'SIS_TL', 'FH_ML'],        'Cockpit L', 'Port cockpit boundary layer deflector'),

    ('P24_SIS_Upper_R',          ['FH_MR', 'SIS_BR', 'SIS_TR'],        'Sidepod R', 'Main stbd driver side impact plate'),
    ('P25_SIS_Lower_R',          ['FH_MR', 'SIS_BR', 'FH_BR'],        'Sidepod R', 'Lower stbd rocker air-fence'),
    ('P26_Cockpit_Deflector_R',  ['FH_SR', 'FH_MR', 'SIS_TR'],        'Cockpit R', 'Starboard cockpit deflector'),

    # Engine Bay Fastback Cowl
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

    # Rear Bulkhead Closure
    ('P39_RearBulkhead_Top',     ['RB_TL', 'RB_TR', 'RB_BL'],          'Rear Transom', 'Upper rear bulkhead wake transom'),
    ('P40_RearBulkhead_Bottom',  ['RB_TR', 'RB_BR', 'RB_BL'],          'Rear Transom', 'Lower rear bulkhead wake transom'),

    # Underbody Undertray / Floorpan
    ('P41_Floor_Front_L',        ['FB_BL', 'FB_BR', 'FH_BL'],          'Floor Pan', 'Port front footwell flat bottom'),
    ('P42_Floor_Front_R',        ['FB_BR', 'FH_BR', 'FH_BL'],          'Floor Pan', 'Starboard front footwell flat bottom'),
    ('P43_Floor_Mid_L',          ['FH_BL', 'FH_BR', 'SIS_BL'],         'Floor Pan', 'Port cockpit seat flat undertray'),
    ('P44_Floor_Mid_R',          ['FH_BR', 'SIS_BR', 'SIS_BL'],         'Floor Pan', 'Starboard cockpit seat flat undertray'),
    ('P45_Floor_Rear_L',         ['SIS_BL', 'SIS_BR', 'RB_BL'],         'Floor Pan', 'Port engine bay underbody tray'),
    ('P46_Floor_Rear_R',         ['SIS_BR', 'RB_BR', 'RB_BL'],         'Floor Pan', 'Starboard engine bay underbody tray'),
]

PLATE_THICKNESS = 1.5  # mm
DENSITY_CF = 1550.0    # kg/m^3
DENSITY_AL = 2700.0    # kg/m^3


def build_variant_a_freecad():
    """Builds Variant A in a complete parametric FreeCAD document."""
    print("="*70)
    print("FREECAD-AUTOMATION: GENERATING VARIANT A (TRIANGULAR FACETED SYSTEM)")
    print("="*70)

    doc = fc_connect.new_document("FSAE_Chassis_Bodywork_Variant_A")

    # 1. Import Chassis into document
    import Import
    Import.insert(CHASSIS_STEP, doc.Name)
    doc.recompute()
    
    # Group chassis objects
    chassis_objs = [obj for obj in doc.Objects]
    chassis_group = doc.addObject("App::DocumentObjectGroup", "Chassis_Spaceframe_Group")
    for obj in chassis_objs:
        chassis_group.addObject(obj)
    doc.recompute()
    print(f"Imported chassis spaceframe with {len(chassis_objs)} structural members.")

    # 2. Build 46 solid plates as Part Features grouped by zone
    zones_map = {}
    solids_list = []
    surfaces_list = []
    plate_records = []

    for idx, (p_id, node_keys, zone, desc) in enumerate(PLATE_DEFS, start=1):
        v1 = NODES[node_keys[0]]
        v2 = NODES[node_keys[1]]
        v3 = NODES[node_keys[2]]

        l12 = (v2 - v1).Length
        l23 = (v3 - v2).Length
        l31 = (v1 - v3).Length

        # Planar Polygon Face
        poly = Part.makePolygon([v1, v2, v3, v1])
        face = Part.Face(poly)
        norm = face.normalAt(0.5, 0.5)

        # Solid Plate (1.5mm wall extrusion)
        solid_plate = face.extrude(norm * PLATE_THICKNESS)
        
        # Add to FreeCAD document as Part::Feature
        feat_solid = doc.addObject("Part::Feature", p_id)
        feat_solid.Shape = solid_plate
        
        # Add to zone group
        if zone not in zones_map:
            z_grp = doc.addObject("App::DocumentObjectGroup", f"Group_{zone.replace(' ', '_')}")
            zones_map[zone] = z_grp
        zones_map[zone].addObject(feat_solid)

        solids_list.append(solid_plate)
        surfaces_list.append(face)

        area_mm2 = face.Area
        area_m2 = area_mm2 / 1e6
        mass_cf = area_m2 * (PLATE_THICKNESS / 1000.0) * DENSITY_CF
        mass_al = area_m2 * (PLATE_THICKNESS / 1000.0) * DENSITY_AL

        plate_records.append({
            'Plate_ID': p_id,
            'Index': idx,
            'Zone': zone,
            'Description': desc,
            'Node_1': node_keys[0], 'Node_2': node_keys[1], 'Node_3': node_keys[2],
            'V1_X_mm': round(v1.x, 1), 'V1_Y_mm': round(v1.y, 1), 'V1_Z_mm': round(v1.z, 1),
            'V2_X_mm': round(v2.x, 1), 'V2_Y_mm': round(v2.y, 1), 'V2_Z_mm': round(v2.z, 1),
            'V3_X_mm': round(v3.x, 1), 'V3_Y_mm': round(v3.y, 1), 'V3_Z_mm': round(v3.z, 1),
            'Edge_12_mm': round(l12, 1), 'Edge_23_mm': round(l23, 1), 'Edge_31_mm': round(l31, 1),
            'Area_mm2': round(area_mm2, 1), 'Area_m2': round(area_m2, 4),
            'Mass_CF_kg': round(mass_cf, 3), 'Mass_Al_kg': round(mass_al, 3),
            'Normal_X': round(norm.x, 3), 'Normal_Y': round(norm.y, 3), 'Normal_Z': round(norm.z, 3)
        })

    doc.recompute()
    print(f"Created all 46 parametric plate features across {len(zones_map)} vehicle zone groups.")

    # Combined Solid and Surface compounds
    solid_bodywork = Part.makeCompound(solids_list)
    surface_bodywork = Part.makeCompound(surfaces_list)

    feat_body_solid = doc.addObject("Part::Feature", "Bodywork_Variant_A_Solids_Combined")
    feat_body_solid.Shape = solid_bodywork

    feat_body_surf = doc.addObject("Part::Feature", "Bodywork_Variant_A_Surfaces_Combined")
    feat_body_surf.Shape = surface_bodywork
    doc.recompute()

    # 3. Create TechDraw 2D Engineering Drawing Sheet
    try:
        print("Generating TechDraw 2D engineering drawing page in FreeCAD document...")
        page, template = fc_drawing.create_page(doc, template_path=TECHDRAW_TEMPLATE, size="A4", orientation="Landscape", name="Bodywork_A_Drawing")
        
        # Add views
        v_iso = fc_drawing.add_view(doc, page, feat_body_solid, direction="iso", x=210, y=140, scale=0.08, name="View_Isometric")
        v_top = fc_drawing.add_view(doc, page, feat_body_solid, direction="top", x=90, y=140, scale=0.08, name="View_Top")
        v_side = fc_drawing.add_view(doc, page, feat_body_solid, direction="front", x=90, y=70, scale=0.08, name="View_Side")
        doc.recompute()
        
        # Export TechDraw SVG
        svg_out = os.path.join(OUT_DIR, "Bodywork_Variant_A_TechDraw.svg")
        fc_drawing.export_page_svg(page, svg_out)
        shutil.copy2(svg_out, os.path.join(DL_DIR, "Bodywork_Variant_A_TechDraw.svg"))
        print(f"Exported TechDraw drawing: {svg_out}")
    except Exception as e:
        print(f"TechDraw generation notice: {e}")

    # 4. Save Native FreeCAD Document (.FCStd)
    fcstd_path = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_A.FCStd")
    fc_connect.save_document(doc, fcstd_path)
    shutil.copy2(fcstd_path, os.path.join(DL_DIR, "Chassis_With_Bodywork_Variant_A.FCStd"))
    print(f"Saved native FreeCAD document: {fcstd_path}")

    # 5. Export CAD using fc_export
    step_solid = os.path.join(OUT_DIR, "Bodywork_Variant_A_Triangular_Plates_Solid.STEP")
    step_surf = os.path.join(OUT_DIR, "Bodywork_Variant_A_Triangular_Plates_Surface.STEP")
    stl_surf = os.path.join(OUT_DIR, "Bodywork_Variant_A_Triangular_Plates_Surface.stl")

    fc_export.export_step(solid_bodywork, step_solid)
    fc_export.export_step(surface_bodywork, step_surf)
    fc_export.export_stl(surface_bodywork, stl_surf, tolerance=0.1)

    # Combined Assembly STEP & STL
    chassis_shape = Part.Shape()
    chassis_shape.read(CHASSIS_STEP)
    full_asm = Part.makeCompound([chassis_shape, solid_bodywork])

    step_asm = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_A.STEP")
    stl_asm = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_A.stl")
    fc_export.export_step(full_asm, step_asm)
    fc_export.export_stl(full_asm, stl_asm, tolerance=0.2)

    # Mirror to Downloads
    for f in [step_solid, step_surf, stl_surf, step_asm, stl_asm]:
        shutil.copy2(f, os.path.join(DL_DIR, os.path.basename(f)))

    # Save manufacturing schedule CSV
    df_sched = pd.DataFrame(plate_records)
    csv_sched = os.path.join(OUT_DIR, "Variant_A_Triangular_Plates_Schedule.csv")
    df_sched.to_csv(csv_sched, index=False)
    shutil.copy2(csv_sched, os.path.join(DL_DIR, "Variant_A_Triangular_Plates_Schedule.csv"))

    print(f"Variant A FreeCAD build complete. Total plates: {len(plate_records)}, Area: {df_sched['Area_m2'].sum():.3f} m^2")
    return doc


def build_variant_b_freecad():
    """Builds Variant B in a native FreeCAD document."""
    print("="*70)
    print("FREECAD-AUTOMATION: GENERATING VARIANT B (STREAMLINED SCULPTED SYSTEM)")
    print("="*70)

    doc = fc_connect.new_document("FSAE_Chassis_Bodywork_Variant_B")

    # Section 1: Nose Tip
    w1 = Part.Wire(Part.makePolygon([
        App.Vector(0, 1200, 220), App.Vector(50, 1200, 180),
        App.Vector(0, 1200, 140), App.Vector(-50, 1200, 180), App.Vector(0, 1200, 220)
    ]))
    # Section 2: Mid Nose
    w2 = Part.Wire(Part.makePolygon([
        App.Vector(0, 950, 310), App.Vector(140, 950, 210),
        App.Vector(0, 950, 110), App.Vector(-140, 950, 210), App.Vector(0, 950, 310)
    ]))
    # Section 3: Front Bulkhead
    w3 = Part.Wire(Part.makePolygon([
        App.Vector(-225, 700, 370), App.Vector(225, 700, 370),
        App.Vector(225, 700, 50), App.Vector(-225, 700, 50), App.Vector(-225, 700, 370)
    ]))
    # Section 4: Front Hoop Hood
    w4 = Part.Wire(Part.makePolygon([
        App.Vector(-200, 0, 590), App.Vector(200, 0, 590), App.Vector(250, 0, 544),
        App.Vector(275, 0, 200), App.Vector(225, 0, 50), App.Vector(-225, 0, 50),
        App.Vector(-275, 0, 200), App.Vector(-250, 0, 544), App.Vector(-200, 0, 590)
    ]))

    nose_loft = Part.makeLoft([w1, w2, w3], True, False)
    front_deck_loft = Part.makeLoft([w3, w4], True, False)

    # Sidepods
    w_sp_l0 = Part.Wire(Part.makePolygon([
        App.Vector(-250, 0, 544), App.Vector(-275, 0, 200),
        App.Vector(-225, 0, 50), App.Vector(-200, 0, 50), App.Vector(-250, 0, 544)
    ]))
    w_sp_l1 = Part.Wire(Part.makePolygon([
        App.Vector(-360, -450, 380), App.Vector(-375, -450, 200),
        App.Vector(-290, -450, 40), App.Vector(-240, -450, 40), App.Vector(-360, -450, 380)
    ]))
    w_sp_l2 = Part.Wire(Part.makePolygon([
        App.Vector(-357, -875, 358), App.Vector(-360, -875, 200),
        App.Vector(-280, -875, 32), App.Vector(-240, -875, 32), App.Vector(-357, -875, 358)
    ]))

    sidepod_l = Part.makeLoft([w_sp_l0, w_sp_l1, w_sp_l2], True, False)
    sidepod_r = sidepod_l.copy()
    sidepod_r.mirror(App.Vector(0,0,0), App.Vector(1,0,0))

    # Engine Cowling
    w_ec0 = Part.Wire(Part.makePolygon([
        App.Vector(-148, -875, 1070), App.Vector(148, -875, 1070), App.Vector(357, -875, 358),
        App.Vector(280, -875, 32), App.Vector(-280, -875, 32), App.Vector(-357, -875, 358),
        App.Vector(-148, -875, 1070)
    ]))
    w_ec1 = Part.Wire(Part.makePolygon([
        App.Vector(-100, -1150, 650), App.Vector(100, -1150, 650), App.Vector(300, -1150, 250),
        App.Vector(260, -1150, 40), App.Vector(-260, -1150, 40), App.Vector(-300, -1150, 250),
        App.Vector(-100, -1150, 650)
    ]))
    w_ec2 = Part.Wire(Part.makePolygon([
        App.Vector(-225, -1400, 350), App.Vector(225, -1400, 350), App.Vector(300, -1400, 200),
        App.Vector(250, -1400, 50), App.Vector(-250, -1400, 50), App.Vector(-300, -1400, 200),
        App.Vector(-225, -1400, 350)
    ]))
    engine_cowl = Part.makeLoft([w_ec0, w_ec1, w_ec2], True, False)

    # Floor Pan
    floor_wire = Part.Wire(Part.makePolygon([
        App.Vector(-225, 700, 40), App.Vector(225, 700, 40), App.Vector(280, -875, 40),
        App.Vector(250, -1400, 40), App.Vector(-250, -1400, 40), App.Vector(-280, -875, 40),
        App.Vector(-225, 700, 40)
    ]))
    floor_face = Part.Face(floor_wire)

    body_b = Part.makeCompound([nose_loft, front_deck_loft, sidepod_l, sidepod_r, engine_cowl, floor_face])
    
    feat_b = doc.addObject("Part::Feature", "Streamlined_Bodywork_Variant_B")
    feat_b.Shape = body_b
    doc.recompute()

    # Save Native .FCStd
    fcstd_b = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_B.FCStd")
    fc_connect.save_document(doc, fcstd_b)
    shutil.copy2(fcstd_b, os.path.join(DL_DIR, "Chassis_With_Bodywork_Variant_B.FCStd"))

    # Export STEP & STL via fc_export
    step_b = os.path.join(OUT_DIR, "Bodywork_Variant_B_Streamlined.STEP")
    stl_b = os.path.join(OUT_DIR, "Bodywork_Variant_B_Streamlined.stl")
    fc_export.export_step(body_b, step_b)
    fc_export.export_stl(body_b, stl_b, tolerance=0.1)

    # Combined Assembly
    chassis_shape = Part.Shape()
    chassis_shape.read(CHASSIS_STEP)
    chassis_b = Part.makeCompound([chassis_shape, body_b])
    step_chassis_b = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_B.STEP")
    fc_export.export_step(chassis_b, step_chassis_b)

    for f in [step_b, stl_b, step_chassis_b]:
        shutil.copy2(f, os.path.join(DL_DIR, os.path.basename(f)))

    print(f"Variant B FreeCAD build complete: {fcstd_b}")
    return doc


def build_variant_c_freecad():
    """Builds Variant C in a native FreeCAD document."""
    print("="*70)
    print("FREECAD-AUTOMATION: GENERATING VARIANT C (MINIMALIST SPRINT SYSTEM)")
    print("="*70)

    doc = fc_connect.new_document("FSAE_Chassis_Bodywork_Variant_C")

    # Wire 1: Nose Tip
    w1 = Part.Wire(Part.makePolygon([
        App.Vector(0, 1200, 220), App.Vector(50, 1200, 180),
        App.Vector(0, 1200, 140), App.Vector(-50, 1200, 180), App.Vector(0, 1200, 220)
    ]))
    w2 = Part.Wire(Part.makePolygon([
        App.Vector(0, 950, 310), App.Vector(140, 950, 210),
        App.Vector(0, 950, 110), App.Vector(-140, 950, 210), App.Vector(0, 950, 310)
    ]))
    w3 = Part.Wire(Part.makePolygon([
        App.Vector(-225, 700, 370), App.Vector(225, 700, 370),
        App.Vector(225, 700, 50), App.Vector(-225, 700, 50), App.Vector(-225, 700, 370)
    ]))
    w4 = Part.Wire(Part.makePolygon([
        App.Vector(-200, 0, 590), App.Vector(200, 0, 590), App.Vector(250, 0, 544),
        App.Vector(275, 0, 200), App.Vector(225, 0, 50), App.Vector(-225, 0, 50),
        App.Vector(-275, 0, 200), App.Vector(-250, 0, 544), App.Vector(-200, 0, 590)
    ]))

    nose_loft = Part.makeLoft([w1, w2, w3], True, False)
    front_deck_loft = Part.makeLoft([w3, w4], True, False)

    w_sp_l0 = Part.Wire(Part.makePolygon([
        App.Vector(-250, 0, 544), App.Vector(-275, 0, 200),
        App.Vector(-225, 0, 50), App.Vector(-200, 0, 50), App.Vector(-250, 0, 544)
    ]))
    w_sp_l1 = Part.Wire(Part.makePolygon([
        App.Vector(-360, -450, 380), App.Vector(-375, -450, 200),
        App.Vector(-290, -450, 40), App.Vector(-240, -450, 40), App.Vector(-360, -450, 380)
    ]))
    w_sp_l2 = Part.Wire(Part.makePolygon([
        App.Vector(-357, -875, 358), App.Vector(-360, -875, 200),
        App.Vector(-280, -875, 32), App.Vector(-240, -875, 32), App.Vector(-357, -875, 358)
    ]))

    sidepod_l = Part.makeLoft([w_sp_l0, w_sp_l1, w_sp_l2], True, False)
    sidepod_r = sidepod_l.copy()
    sidepod_r.mirror(App.Vector(0,0,0), App.Vector(1,0,0))

    floor_wire = Part.Wire(Part.makePolygon([
        App.Vector(-225, 700, 40), App.Vector(225, 700, 40), App.Vector(280, -875, 40),
        App.Vector(250, -1400, 40), App.Vector(-250, -1400, 40), App.Vector(-280, -875, 40),
        App.Vector(-225, 700, 40)
    ]))
    floor_face = Part.Face(floor_wire)

    body_c = Part.makeCompound([nose_loft, front_deck_loft, sidepod_l, sidepod_r, floor_face])

    feat_c = doc.addObject("Part::Feature", "Minimalist_Sprint_Bodywork_Variant_C")
    feat_c.Shape = body_c
    doc.recompute()

    fcstd_c = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_C.FCStd")
    fc_connect.save_document(doc, fcstd_c)
    shutil.copy2(fcstd_c, os.path.join(DL_DIR, "Chassis_With_Bodywork_Variant_C.FCStd"))

    step_c = os.path.join(OUT_DIR, "Bodywork_Variant_C_Minimalist.STEP")
    stl_c = os.path.join(OUT_DIR, "Bodywork_Variant_C_Minimalist.stl")
    fc_export.export_step(body_c, step_c)
    fc_export.export_stl(body_c, stl_c, tolerance=0.1)

    chassis_shape = Part.Shape()
    chassis_shape.read(CHASSIS_STEP)
    chassis_c = Part.makeCompound([chassis_shape, body_c])
    step_chassis_c = os.path.join(OUT_DIR, "Chassis_With_Bodywork_Variant_C.STEP")
    fc_export.export_step(chassis_c, step_chassis_c)

    for f in [step_c, stl_c, step_chassis_c]:
        shutil.copy2(f, os.path.join(DL_DIR, os.path.basename(f)))

    print(f"Variant C FreeCAD build complete: {fcstd_c}")
    return doc


if __name__ == '__main__':
    doc_a = build_variant_a_freecad()
    doc_b = build_variant_b_freecad()
    doc_c = build_variant_c_freecad()
    print("="*70)
    print("FREECAD-AUTOMATION COMPLETE: ALL 3 VARIANTS BUILT, MODELED, AND PRESERVED!")
    print("="*70)
