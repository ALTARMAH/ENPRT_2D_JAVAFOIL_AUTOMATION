import sys, os
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import
import numpy as np

WING_STEP = '/home/user/Applications/aero_auto/wing_s1223_solid.step'

def create_airfoil_element(base_solid, chord_scale, span, rot_deg, trans_vec):
    m = App.Matrix()
    m.A11 = chord_scale
    m.A22 = chord_scale
    m.A33 = span / 1400.0
    s = base_solid.copy().transformGeometry(m)
    s.translate(App.Vector(0, 0, -span/2.0))
    s.rotate(App.Vector(0,0,0), App.Vector(0,1,0), 90)
    s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), -90)
    if rot_deg != 0:
        s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), rot_deg)
    s.translate(trans_vec)
    return s

doc_temp = App.newDocument("TempRW")
Import.insert(WING_STEP, doc_temp.Name)
base_solids = doc_temp.Objects[0].Shape.Solids
main_solid = base_solids[0]
flap_solid = base_solids[1] if len(base_solids) > 1 else base_solids[0]

# Rear Wing (Span 950mm)
# Element 1: Mainplane
rw_e1 = create_airfoil_element(main_solid, 1.0, 950.0, 0.0, App.Vector(0, -1180, 1180))
# Element 2: Flap 1
rw_e2 = create_airfoil_element(flap_solid, 0.9, 950.0, 12.0, App.Vector(0, -1250, 1220))
# Element 3: Flap 2
rw_e3 = create_airfoil_element(flap_solid, 0.8, 950.0, 24.0, App.Vector(0, -1310, 1255))
# Element 4: Beam Wing (Lower wake diffuser)
rw_beam = create_airfoil_element(main_solid, 0.7, 800.0, 15.0, App.Vector(0, -1380, 480))

# Gurney Flap on Element 3
gurney = Part.makeBox(950, 4, 10, App.Vector(-475, -1375, 1265))

# Endplates (X = +- 475) with 3 louvers each
def make_endplate(x_pos):
    ep = Part.makeBox(6, 440, 220, App.Vector(x_pos, -1560, 1060))
    # Louvers (3 slots)
    louver1 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1230))
    louver2 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1200))
    louver3 = Part.makeBox(10, 80, 12, App.Vector(x_pos - 2, -1520, 1170))
    ep = ep.cut(louver1).cut(louver2).cut(louver3)
    return ep

rw_ep_l = make_endplate(-481)
rw_ep_r = make_endplate(475)

# DRS Actuator Pod (Centerline X=0)
drs_pod = Part.makeCylinder(14, 120, App.Vector(0, -1400, 1260), App.Vector(0, 1, 0))
drs_nose = Part.makeSphere(14, App.Vector(0, -1280, 1260))
drs_pod = drs_pod.fuse(drs_nose)

# Flap Adjustment Ribs (X = +- 250)
rib_l = Part.makeBox(6, 180, 70, App.Vector(-253, -1330, 1200))
rib_r = Part.makeBox(6, 180, 70, App.Vector(247, -1330, 1200))

# Swan-Neck Pylons:
# Connect Rear Bulkhead (Y=-1400, Z=350) and Main Hoop Braces (Y=-1150, Z=650) to RW suction face (Y=-1220, Z=1230)
def make_swan_neck_pylon(x_pos):
    # Polygonal profile in Y-Z plane
    pts = [
        App.Vector(x_pos, -1400, 350),   # Chassis RB mount
        App.Vector(x_pos, -1370, 350),
        App.Vector(x_pos, -1140, 650),   # Mid brace mount
        App.Vector(x_pos, -1140, 700),
        App.Vector(x_pos, -1200, 1240),  # RW top suction mount
        App.Vector(x_pos, -1230, 1240),  # Swan-neck hook
        App.Vector(x_pos, -1260, 1200),
        App.Vector(x_pos, -1220, 750),
        App.Vector(x_pos, -1370, 400),
        App.Vector(x_pos, -1400, 350)
    ]
    poly = Part.makePolygon(pts)
    face = Part.Face(poly)
    pylon_solid = face.extrude(App.Vector(12, 0, 0))
    return pylon_solid

pylon_l = make_swan_neck_pylon(-186)
pylon_r = make_swan_neck_pylon(174)

rw_comp = Part.makeCompound([rw_e1, rw_e2, rw_e3, rw_beam, gurney, rw_ep_l, rw_ep_r, drs_pod, rib_l, rib_r, pylon_l, pylon_r])
print(f"Full RW compound: solids={len(rw_comp.Solids)}, isValid={rw_comp.isValid()}, BB={rw_comp.BoundBox}")

App.closeDocument(doc_temp.Name)
print("REAR WING TEST SUCCESSFUL")
