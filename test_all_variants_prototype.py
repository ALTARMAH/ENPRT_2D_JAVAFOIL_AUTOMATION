import sys, os, math
import numpy as np

FREECAD_LIB = '/usr/lib/freecad/lib'
if FREECAD_LIB not in sys.path:
    sys.path.insert(0, FREECAD_LIB)

import FreeCAD as App
import Part, Import

CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
doc_ch = App.newDocument("ChTest")
Import.insert(CHASSIS_STEP, doc_ch.Name)
chassis = doc_ch.Objects[0].Shape.copy()
App.closeDocument(doc_ch.Name)

print("Chassis loaded successfully.")

# Helper to build solid panels from 3D triangles
def build_plate_solids(node_dict, plate_defs, seam_inset=1.2, thickness=1.5):
    def inset_pt(pt, cent, dist):
        vec = cent - pt
        l = vec.Length
        if l > dist: return pt + vec * (dist / l)
        return pt

    solids = []
    faces = []
    for p_id, keys, zone, desc, out_dir in plate_defs:
        v1, v2, v3 = node_dict[keys[0]], node_dict[keys[1]], node_dict[keys[2]]
        cent = (v1 + v2 + v3) / 3.0
        v1_in = inset_pt(v1, cent, seam_inset)
        v2_in = inset_pt(v2, cent, seam_inset)
        v3_in = inset_pt(v3, cent, seam_inset)
        
        norm = (v2 - v1).cross(v3 - v1)
        norm.normalize()
        if norm.dot(out_dir) < 0: norm = -norm
        
        poly = Part.makePolygon([v1_in, v2_in, v3_in, v1_in])
        face = Part.Face(poly)
        solid = face.extrude(norm * thickness)
        solids.append(solid)
        faces.append(Part.Face(Part.makePolygon([v1, v2, v3, v1])))
        
    comp = Part.makeCompound(solids)
    shell = Part.makeShell(faces)
    return comp, shell, solids

print("Helper defined.")
