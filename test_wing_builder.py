import sys, os
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import
import numpy as np

WING_STEP = '/home/user/Applications/aero_auto/wing_s1223_solid.step'

def create_airfoil_element(base_solid, chord_scale, span, rot_deg, trans_vec):
    """
    Scales, rotates, and translates a wing solid.
    base_solid has span along Z [0, 1400], chord along X [0, 318], thickness along Y [45, 110].
    """
    m = App.Matrix()
    m.A11 = chord_scale
    m.A22 = chord_scale
    m.A33 = span / 1400.0
    s = base_solid.copy().transformGeometry(m)
    
    # Center span along Z: [-span/2, span/2]
    s.translate(App.Vector(0, 0, -span/2.0))
    
    # Orient to vehicle frame: Z -> X, X -> -Y, Y -> Z
    s.rotate(App.Vector(0,0,0), App.Vector(0,1,0), 90)
    s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), -90)
    
    # Apply angle of attack rotation around lateral X-axis
    if rot_deg != 0:
        s.rotate(App.Vector(0,0,0), App.Vector(1,0,0), rot_deg)
        
    s.translate(trans_vec)
    return s

doc_temp = App.newDocument("TempWing")
Import.insert(WING_STEP, doc_temp.Name)
base_solids = doc_temp.Objects[0].Shape.Solids
main_solid = base_solids[0]
flap_solid = base_solids[1] if len(base_solids) > 1 else base_solids[0]

print(f"Base solids: {len(base_solids)}")

# Test Front Wing
# Element 1: Mainplane (span 1400, chord scale 1.0)
fw_e1 = create_airfoil_element(main_solid, 1.0, 1400.0, 0.0, App.Vector(0, 1200, 75))
# Element 2: Lower flap
fw_e2 = create_airfoil_element(flap_solid, 0.9, 1400.0, -8.0, App.Vector(0, 1260, 110))
# Element 3: Upper cascade flap
fw_e3 = create_airfoil_element(flap_solid, 0.75, 1380.0, -18.0, App.Vector(0, 1310, 155))

print(f"FW E1 valid={fw_e1.isValid()}, E2 valid={fw_e2.isValid()}, E3 valid={fw_e3.isValid()}")

# Test Endplates
ep_l = Part.makeBox(5, 420, 200, App.Vector(-705, 920, 25))
ep_r = Part.makeBox(5, 420, 200, App.Vector(700, 920, 25))
# Footplates (outboard flanges)
fp_l = Part.makeBox(45, 380, 5, App.Vector(-750, 940, 25))
fp_r = Part.makeBox(45, 380, 5, App.Vector(705, 940, 25))

# Underwing Strakes (2 per side)
strake_l1 = Part.makeBox(3, 260, 45, App.Vector(-350, 960, 28))
strake_l2 = Part.makeBox(3, 260, 45, App.Vector(-520, 960, 28))
strake_r1 = Part.makeBox(3, 260, 45, App.Vector(347, 960, 28))
strake_r2 = Part.makeBox(3, 260, 45, App.Vector(517, 960, 28))

# Mounting Pylons (connect front bulkhead at Y=700, Z=55 to FW at Y=1150, Z=75)
pylon_l = Part.makeBox(10, 460, 45, App.Vector(-165, 700, 55))
pylon_r = Part.makeBox(10, 460, 45, App.Vector(155, 700, 55))

fw_comp = Part.makeCompound([fw_e1, fw_e2, fw_e3, ep_l, ep_r, fp_l, fp_r, 
                             strake_l1, strake_l2, strake_r1, strake_r2, pylon_l, pylon_r])
print(f"Full FW compound: solids={len(fw_comp.Solids)}, isValid={fw_comp.isValid()}, BB={fw_comp.BoundBox}")

App.closeDocument(doc_temp.Name)
print("TEST SUCCESSFUL")
