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

p_tip = App.Vector(0, 1195, 195)
p_fb_tl = App.Vector(-245, 725, 395)
p_fb_tr = App.Vector( 245, 725, 395)
p_fb_bl = App.Vector(-250, 725, 8)
p_fb_br = App.Vector( 250, 725, 8)

def make_panel(v1, v2, v3, out_dir, t=1.5):
    norm = (v2 - v1).cross(v3 - v1)
    norm.normalize()
    if norm.dot(out_dir) < 0: norm = -norm
    face = Part.Face(Part.makePolygon([v1, v2, v3, v1]))
    return face.extrude(norm * t)

panels = []
panels.append(('Nose_Top', make_panel(p_tip, p_fb_tl, p_fb_tr, App.Vector(0, 0.4, 0.9))))
panels.append(('Nose_Left', make_panel(p_tip, p_fb_bl, p_fb_tl, App.Vector(-1, 0.2, 0))))
panels.append(('Nose_Right', make_panel(p_tip, p_fb_tr, p_fb_br, App.Vector(1, 0.2, 0))))
panels.append(('Nose_Bottom', make_panel(p_tip, p_fb_br, p_fb_bl, App.Vector(0, 0, -1))))

for name, p in panels:
    v_clash = p.common(chassis).Volume
    print(f"{name}: isValid={p.isValid()}, Chassis Clash={v_clash:.4f} mm3")

