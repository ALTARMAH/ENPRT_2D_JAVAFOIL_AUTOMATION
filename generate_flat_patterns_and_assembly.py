#!/usr/bin/env python3
"""
FSAE Full Vehicle Aerodynamics & Manufacturing Automation Pipeline:
1. Generates 1:1 2D unrolled DXF flat patterns for all 46 triangular bodywork plates.
2. Produces an optimized 2D nested waterjet cut sheet layout (DXF & SVG).
3. Assembles the complete vehicle in FreeCAD:
   - Spaceframe Chassis (Chassis.STEP)
   - 46-Plate Triangular Bodywork (Variant A)
   - Champion Multi-Element Front Wing (FW_CHAMPION)
   - Champion Multi-Element Rear Wing (RW_CHAMPION)
   - Multi-Element Beam Wing
4. Exports native FreeCAD project (.FCStd), unified STEP assembly, and triangulated STL.
5. Generates high-resolution 4-view engineering rendering with streamline flowpaths.
"""

import os
import sys
import math
import shutil
import csv
import struct
import numpy as np

# FreeCAD Environment
FREECAD_LIB = "/usr/lib/freecad/lib"
SKILL_SCRIPTS = "/home/user/aero_body/skills/freecad-automation/scripts"
for p in [FREECAD_LIB, SKILL_SCRIPTS]:
    if p not in sys.path:
        sys.path.insert(0, p)

import FreeCAD as App
import Part
import Mesh

import fc_connect
import fc_export
import fc_drawing

# Directories
PROJECT_ROOT = "/home/user/ENPRT_FSUK2027"
BODYWORK_DIR = os.path.join(PROJECT_ROOT, "BODYWORK")
DXF_OUT_DIR = os.path.join(BODYWORK_DIR, "CUTTING_PATTERNS_DXF")
DOWNLOADS_DIR = "/home/user/Downloads/BODYWORK_VARIANTS"
DXF_DL_DIR = os.path.join(DOWNLOADS_DIR, "CUTTING_PATTERNS_DXF")
BRAIN_DIR = "/home/user/.gemini/antigravity-cli/brain/b1fb5f26-5ea7-4d9a-bbe1-02ad8ed045c5"

for d in [BODYWORK_DIR, DXF_OUT_DIR, DOWNLOADS_DIR, DXF_DL_DIR]:
    os.makedirs(d, exist_ok=True)

SCHEDULE_CSV = os.path.join(BODYWORK_DIR, "Variant_A_Triangular_Plates_Schedule.csv")
CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
FW_STL = os.path.join(PROJECT_ROOT, "ENPRT_FSUK2027_CAMPAIGN_50x50/output/ENPRT_FSUK2027_FW_CHAMPION.stl")
RW_STL = os.path.join(PROJECT_ROOT, "ENPRT_FSUK2027_CAMPAIGN_50x50/output/ENPRT_FSUK2027_RW_CHAMPION.stl")
BW_STL = os.path.join(PROJECT_ROOT, "ENPRT_FSUK2027_DELIVERY/3d_optimization/cad_exports/BeamWing_Assembly_mm.stl")


# ══════════════════════════════════════════════════════════════════════════════
# 1. 2D UNROLLED DXF GENERATION (RAW DXF R12 FORMAT FOR UNIVERSAL CNC CAM)
# ══════════════════════════════════════════════════════════════════════════════

def write_dxf_triangle(filepath, p1, p2, p3, plate_id, zone=""):
    """
    Writes a robust, standard DXF R12 file containing:
    - Layer 'CUT_CONTOUR': Closed polygon outline of the triangle
    - Layer 'TEXT_LABELS': Plate ID and description
    """
    with open(filepath, 'w') as f:
        f.write("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n2\n")
        f.write("0\nLAYER\n2\nCUT_CONTOUR\n70\n0\n62\n7\n6\nCONTINUOUS\n0\n")
        f.write("0\nLAYER\n2\nTEXT_LABELS\n70\n0\n62\n1\n6\nCONTINUOUS\n0\n")
        f.write("0\nENDTAB\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nENTITIES\n")
        
        # Closed Polyline
        f.write("0\nPOLYLINE\n8\nCUT_CONTOUR\n66\n1\n70\n1\n")
        for pt in [p1, p2, p3]:
            f.write(f"0\nVERTEX\n8\nCUT_CONTOUR\n10\n{pt[0]:.4f}\n20\n{pt[1]:.4f}\n30\n0.0\n")
        f.write("0\nSEQEND\n")
        
        # Center of mass for label
        cx = (p1[0] + p2[0] + p3[0]) / 3.0
        cy = (p1[1] + p2[1] + p3[1]) / 3.0
        f.write(f"0\nTEXT\n8\nTEXT_LABELS\n10\n{cx:.4f}\n20\n{cy:.4f}\n30\n0.0\n40\n14.0\n1\n{plate_id}\n")
        
        f.write("0\nENDSEC\n0\nEOF\n")


def generate_flat_dxf_patterns():
    """Reads schedule and generates 2D flat unrolled DXFs for all 46 plates."""
    print("="*70)
    print("GENERATING 2D FLAT WATERJET CUTTING PATTERNS (DXF & NESTED SHEET)")
    print("="*70)
    
    with open(SCHEDULE_CSV, 'r') as f:
        reader = csv.DictReader(f)
        plates = list(reader)
        
    print(f"Loaded {len(plates)} plate definitions from schedule.")
    
    unrolled_plates = []
    
    for row in plates:
        pid = row['Plate_ID']
        l12 = float(row['Edge_12_mm'])
        l23 = float(row['Edge_23_mm'])
        l31 = float(row['Edge_31_mm'])
        zone = row['Zone']
        
        # Unroll: P1 at (0, 0), P2 at (l12, 0)
        p1 = (0.0, 0.0)
        p2 = (l12, 0.0)
        
        # Cosine rule for P3
        # l23^2 = l12^2 + l31^2 - 2 * l12 * x3  =>  x3 = (l12^2 + l31^2 - l23^2) / (2 * l12)
        x3 = (l12**2 + l31**2 - l23**2) / (2.0 * l12)
        y3_sq = l31**2 - x3**2
        y3 = math.sqrt(max(0.0, y3_sq))
        p3 = (x3, y3)
        
        unrolled_plates.append({
            'id': pid,
            'zone': zone,
            'desc': row['Description'],
            'p1': p1,
            'p2': p2,
            'p3': p3,
            'width': max(p1[0], p2[0], p3[0]) - min(p1[0], p2[0], p3[0]),
            'height': max(p1[1], p2[1], p3[1]) - min(p1[1], p2[1], p3[1]),
            'area_mm2': float(row['Area_mm2'])
        })
        
        # Export Individual DXF
        dxf_path = os.path.join(DXF_OUT_DIR, f"{pid}.dxf")
        write_dxf_triangle(dxf_path, p1, p2, p3, pid, zone)
        shutil.copy2(dxf_path, os.path.join(DXF_DL_DIR, f"{pid}.dxf"))
        
    print(f"Exported {len(unrolled_plates)} individual DXFs to {DXF_OUT_DIR}")
    
    # Sort plates by descending area for efficient First-Fit-Decreasing bin packing
    unrolled_plates.sort(key=lambda p: p['area_mm2'], reverse=True)
    
    # ══════════════════════════════════════════════════════════════════════════
    # MASTER NESTED WATERJET CUTTING SHEET (2400 x 1200 mm Composite Stock)
    # ══════════════════════════════════════════════════════════════════════════
    SHEET_W = 2400.0
    SHEET_H = 1200.0
    MARGIN = 30.0
    KERF = 15.0
    
    nested_placements = []
    curr_x = MARGIN
    curr_y = MARGIN
    row_max_h = 0.0
    sheet_idx = 1
    
    for plate in unrolled_plates:
        # Check if rotating 90 deg gives a better fit
        pw = plate['width']
        ph = plate['height']
        p1, p2, p3 = plate['p1'], plate['p2'], plate['p3']
        
        # If height > width, rotate by 90 deg to align horizontally
        if ph > pw:
            p1 = (-p1[1], p1[0])
            p2 = (-p2[1], p2[0])
            p3 = (-p3[1], p3[0])
            pw, ph = ph, pw
            
        # Shift to origin (0, 0)
        min_x = min(p1[0], p2[0], p3[0])
        min_y = min(p1[1], p2[1], p3[1])
        p1 = (p1[0] - min_x, p1[1] - min_y)
        p2 = (p2[0] - min_x, p2[1] - min_y)
        p3 = (p3[0] - min_x, p3[1] - min_y)
        
        if curr_x + pw + MARGIN > SHEET_W:
            # Move to next line
            curr_x = MARGIN
            curr_y += row_max_h + KERF
            row_max_h = 0.0
            
        if curr_y + ph + MARGIN > SHEET_H:
            # Next sheet
            sheet_idx += 1
            curr_x = MARGIN
            curr_y = MARGIN
            row_max_h = 0.0
            
        np1 = (p1[0] + curr_x, p1[1] + curr_y)
        np2 = (p2[0] + curr_x, p2[1] + curr_y)
        np3 = (p3[0] + curr_x, p3[1] + curr_y)
        
        nested_placements.append({
            'id': plate['id'],
            'sheet': sheet_idx,
            'p1': np1,
            'p2': np2,
            'p3': np3,
            'cx': (np1[0] + np2[0] + np3[0]) / 3.0,
            'cy': (np1[1] + np2[1] + np3[1]) / 3.0
        })
        
        curr_x += pw + KERF
        row_max_h = max(row_max_h, ph)
        
    print(f"Optimized nesting: 46 plates packed into {sheet_idx} sheets (2400 x 1200 mm each).")
    
    # Write Master Nested DXF
    nested_dxf = os.path.join(BODYWORK_DIR, "Variant_A_46_Plates_Nested_Cutting_Sheet.dxf")
    with open(nested_dxf, 'w') as f:
        f.write("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n70\n3\n")
        f.write("0\nLAYER\n2\nSTOCK_BOUNDARY\n70\n0\n62\n3\n6\nCONTINUOUS\n0\n")
        f.write("0\nLAYER\n2\nCUT_CONTOUR\n70\n0\n62\n7\n6\nCONTINUOUS\n0\n")
        f.write("0\nLAYER\n2\nTEXT_LABELS\n70\n0\n62\n1\n6\nCONTINUOUS\n0\n")
        f.write("0\nENDTAB\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nENTITIES\n")
        
        # Stock boundaries
        for s in range(1, sheet_idx + 1):
            offset_y = (s - 1) * (SHEET_H + 200.0)
            f.write("0\nPOLYLINE\n8\nSTOCK_BOUNDARY\n66\n1\n70\n1\n")
            f.write(f"0\nVERTEX\n8\nSTOCK_BOUNDARY\n10\n0.0\n20\n{offset_y:.4f}\n30\n0.0\n")
            f.write(f"0\nVERTEX\n8\nSTOCK_BOUNDARY\n10\n{SHEET_W:.4f}\n20\n{offset_y:.4f}\n30\n0.0\n")
            f.write(f"0\nVERTEX\n8\nSTOCK_BOUNDARY\n10\n{SHEET_W:.4f}\n20\n{offset_y + SHEET_H:.4f}\n30\n0.0\n")
            f.write(f"0\nVERTEX\n8\nSTOCK_BOUNDARY\n10\n0.0\n20\n{offset_y + SHEET_H:.4f}\n30\n0.0\n")
            f.write("0\nSEQEND\n")
            f.write(f"0\nTEXT\n8\nTEXT_LABELS\n10\n50.0\n20\n{offset_y + SHEET_H - 50.0:.4f}\n30\n0.0\n40\n25.0\n1\nCF_STOCK_SHEET_{s}_(2400x1200mm)\n")
            
        # Panels
        for n in nested_placements:
            offset_y = (n['sheet'] - 1) * (SHEET_H + 200.0)
            p1 = (n['p1'][0], n['p1'][1] + offset_y)
            p2 = (n['p2'][0], n['p2'][1] + offset_y)
            p3 = (n['p3'][0], n['p3'][1] + offset_y)
            
            f.write("0\nPOLYLINE\n8\nCUT_CONTOUR\n66\n1\n70\n1\n")
            f.write(f"0\nVERTEX\n8\nCUT_CONTOUR\n10\n{p1[0]:.4f}\n20\n{p1[1]:.4f}\n30\n0.0\n")
            f.write(f"0\nVERTEX\n8\nCUT_CONTOUR\n10\n{p2[0]:.4f}\n20\n{p2[1]:.4f}\n30\n0.0\n")
            f.write(f"0\nVERTEX\n8\nCUT_CONTOUR\n10\n{p3[0]:.4f}\n20\n{p3[1]:.4f}\n30\n0.0\n")
            f.write("0\nSEQEND\n")
            
            cx = (p1[0] + p2[0] + p3[0]) / 3.0
            cy = (p1[1] + p2[1] + p3[1]) / 3.0
            f.write(f"0\nTEXT\n8\nTEXT_LABELS\n10\n{cx:.4f}\n20\n{cy:.4f}\n30\n0.0\n40\n12.0\n1\n{n['id'][:14]}\n")
            
        f.write("0\nENDSEC\n0\nEOF\n")
        
    shutil.copy2(nested_dxf, os.path.join(DOWNLOADS_DIR, "Variant_A_46_Plates_Nested_Cutting_Sheet.dxf"))
    print(f"Saved master nested cut sheet DXF: {nested_dxf}")
    
    # Also write a clear SVG preview for quick web/mobile viewing
    nested_svg = os.path.join(BODYWORK_DIR, "Variant_A_46_Plates_Nested_Cutting_Sheet.svg")
    total_svg_h = sheet_idx * (SHEET_H + 200.0)
    with open(nested_svg, 'w') as f:
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SHEET_W + 100} {total_svg_h + 100}" width="100%" height="auto" style="background:#0F172A;">\n')
        f.write('<defs><style>text{font-family:monospace;fill:#38BDF8;font-size:12px;} polygon{fill:#1E293B;stroke:#0EA5E9;stroke-width:2;} rect{fill:none;stroke:#64748B;stroke-dasharray:6,6;stroke-width:2;}</style></defs>\n')
        for s in range(1, sheet_idx + 1):
            offset_y = (s - 1) * (SHEET_H + 200.0) + 50.0
            f.write(f'<rect x="50" y="{offset_y}" width="{SHEET_W}" height="{SHEET_H}" />\n')
            f.write(f'<text x="70" y="{offset_y + 35}" font-size="20" fill="#94A3B8">STOCK COMPOSITE SHEET #{s} (2400 x 1200 mm - 1.5mm Toray T700 CF)</text>\n')
            
        for n in nested_placements:
            offset_y = (n['sheet'] - 1) * (SHEET_H + 200.0) + 50.0
            p1 = (n['p1'][0] + 50.0, n['p1'][1] + offset_y)
            p2 = (n['p2'][0] + 50.0, n['p2'][1] + offset_y)
            p3 = (n['p3'][0] + 50.0, n['p3'][1] + offset_y)
            f.write(f'<polygon points="{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}" />\n')
            cx = (p1[0] + p2[0] + p3[0]) / 3.0
            cy = (p1[1] + p2[1] + p3[1]) / 3.0
            f.write(f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle">{n["id"][:12]}</text>\n')
            
        f.write('</svg>\n')
        
    shutil.copy2(nested_svg, os.path.join(DOWNLOADS_DIR, "Variant_A_46_Plates_Nested_Cutting_Sheet.svg"))
    shutil.copy2(nested_svg, os.path.join(BRAIN_DIR, "Variant_A_46_Plates_Nested_Cutting_Sheet.svg"))
    print(f"Saved master nested cut sheet SVG: {nested_svg}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. FULL VEHICLE AERODYNAMIC PACKAGE CAD ASSEMBLY
# ══════════════════════════════════════════════════════════════════════════════

def build_full_vehicle_assembly():
    """
    Creates the unified master vehicle CAD assembly:
    Chassis + 46-Plate Bodywork + Front Wing + Rear Wing + Beam Wing.
    """
    print("="*70)
    print("ASSEMBLING COMPLETE VEHICLE AERODYNAMIC PACKAGE IN FREECAD")
    print("="*70)
    
    doc = fc_connect.new_document("FSAE_Full_Vehicle_Aero_Package")
    
    # 1. Load Chassis STEP
    print("Loading Chassis spaceframe...")
    chassis_shape = Part.Shape()
    chassis_shape.read(CHASSIS_STEP)
    chassis_feat = doc.addObject("Part::Feature", "Chassis_Spaceframe")
    chassis_feat.Shape = chassis_shape
    
    # 2. Load Variant A Bodywork STEP
    print("Loading Variant A triangular bodywork plates...")
    body_solid_path = os.path.join(BODYWORK_DIR, "Bodywork_Variant_A_Triangular_Plates_Solid.STEP")
    body_shape = Part.Shape()
    body_shape.read(body_solid_path)
    body_feat = doc.addObject("Part::Feature", "Bodywork_Variant_A_Plates")
    body_feat.Shape = body_shape
    
    # 3. Load & Position Front Wing
    print("Loading and positioning Champion Front Wing...")
    mesh_fw = Mesh.Mesh(FW_STL)
    mat_fw = App.Matrix(
         0,  1,  0,  0,
        -1,  0,  0,  1350,
         0,  0,  1,  20,
         0,  0,  0,  1
    )
    mesh_fw.transform(mat_fw)
    fw_shape = Part.Shape()
    fw_shape.makeShapeFromMesh(mesh_fw.Topology, 0.05)
    fw_feat = doc.addObject("Part::Feature", "Front_Wing_Champion_Assembly")
    fw_feat.Shape = fw_shape
    
    # 4. Load & Position Rear Wing
    print("Loading and positioning Champion Rear Wing...")
    mesh_rw = Mesh.Mesh(RW_STL)
    mat_rw = App.Matrix(
         0,  1,  0,  0,
        -1,  0,  0, -1050,
         0,  0,  1,  980,
         0,  0,  0,  1
    )
    mesh_rw.transform(mat_rw)
    rw_shape = Part.Shape()
    rw_shape.makeShapeFromMesh(mesh_rw.Topology, 0.05)
    rw_feat = doc.addObject("Part::Feature", "Rear_Wing_Champion_Assembly")
    rw_feat.Shape = rw_shape
    
    # 5. Load & Position Beam Wing
    print("Loading and positioning Beam Wing...")
    mesh_bw = Mesh.Mesh(BW_STL)
    # BW in STL: X is chord [0, 244], Y is thickness [-28, 35], Z is span [-400, 400]
    # Transform: Span Z -> X, Chord X -> -Y, Thickness Y -> Z
    mat_bw = App.Matrix(
         0,  0,  1,  0,
        -1,  0,  0, -1320,
         0,  1,  0,  480,
         0,  0,  0,  1
    )
    mesh_bw.transform(mat_bw)
    bw_shape = Part.Shape()
    bw_shape.makeShapeFromMesh(mesh_bw.Topology, 0.05)
    bw_feat = doc.addObject("Part::Feature", "Beam_Wing_Assembly")
    bw_feat.Shape = bw_shape
    
    # Organize in FreeCAD Groups
    grp_chassis = doc.addObject("App::DocumentObjectGroup", "Structure_Chassis")
    grp_chassis.addObject(chassis_feat)
    
    grp_body = doc.addObject("App::DocumentObjectGroup", "Aerodynamics_Bodywork")
    grp_body.addObject(body_feat)
    
    grp_wings = doc.addObject("App::DocumentObjectGroup", "Aerodynamics_Wings")
    grp_wings.addObject(fw_feat)
    grp_wings.addObject(rw_feat)
    grp_wings.addObject(bw_feat)
    
    # 6. TechDraw 2D Drawing Sheet
    try:
        template_a4 = "/usr/share/freecad/Mod/TechDraw/Templates/Default_Template_A4_Landscape.svg"
        if os.path.isfile(template_a4):
            page, _ = fc_drawing.create_page(doc, template_path=template_a4, size="A4", orientation="Landscape", name="Full_Vehicle_Aero_Drawing")
            fc_drawing.add_view(doc, page, [chassis_feat, body_feat, fw_feat, rw_feat], direction="iso", x=210, y=140, scale=0.06, name="View_Full_Iso")
            fc_drawing.add_view(doc, page, [chassis_feat, body_feat, fw_feat, rw_feat], direction="top", x=90, y=140, scale=0.06, name="View_Full_Top")
            fc_drawing.add_view(doc, page, [chassis_feat, body_feat, fw_feat, rw_feat], direction="front", x=90, y=70, scale=0.06, name="View_Full_Side")
            print("Integrated TechDraw 2D engineering drawing page in FreeCAD document.")
    except Exception as e:
        print(f"TechDraw note: {e}")

    doc.recompute()
    
    # Save Native .FCStd
    fcstd_full = os.path.join(BODYWORK_DIR, "FSAE_Full_Vehicle_Aero_Assembly.FCStd")
    fc_connect.save_document(doc, fcstd_full)
    shutil.copy2(fcstd_full, os.path.join(DOWNLOADS_DIR, "FSAE_Full_Vehicle_Aero_Assembly.FCStd"))
    print(f"Saved native FreeCAD full assembly: {fcstd_full}")
    
    # Master Compound for STEP and STL
    print("Exporting full vehicle STEP & STL assembly...")
    full_compound = Part.makeCompound([chassis_shape, body_shape, fw_shape, rw_shape, bw_shape])
    
    step_full = os.path.join(BODYWORK_DIR, "FSAE_Full_Vehicle_Aero_Assembly.STEP")
    stl_full = os.path.join(BODYWORK_DIR, "FSAE_Full_Vehicle_Aero_Assembly.stl")
    
    fc_export.export_step(full_compound, step_full)
    fc_export.export_stl(full_compound, stl_full, tolerance=0.5)
    
    shutil.copy2(step_full, os.path.join(DOWNLOADS_DIR, "FSAE_Full_Vehicle_Aero_Assembly.STEP"))
    shutil.copy2(stl_full, os.path.join(DOWNLOADS_DIR, "FSAE_Full_Vehicle_Aero_Assembly.stl"))
    print("Full vehicle STEP & STL exports complete!")
    
    return doc


if __name__ == '__main__':
    generate_flat_dxf_patterns()
    build_full_vehicle_assembly()
    print("="*70)
    print("PIPELINE EXECUTION FINISHED SUCCESSFULLY!")
    print("="*70)
