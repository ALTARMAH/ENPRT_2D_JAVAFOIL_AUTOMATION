import sys, os, math
import numpy as np
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part

# Chassis spaceframe hardpoint nodes (mm)
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

# External offset direction and distance (22mm standoff)
NODES_OVER = {}
STANDOFFS = []

for k, pt in NODES_CHASSIS.items():
    # Calculate outward unit vector
    vx = 1.0 if pt.x > 10 else (-1.0 if pt.x < -10 else 0.0)
    vy = 0.5 if pt.y > 600 else (-0.5 if pt.y < -1000 else 0.0)
    vz = 1.0 if pt.z > 300 else (-0.4 if pt.z < 100 else 0.0)
    
    vec = App.Vector(vx, vy, vz)
    if vec.Length < 1e-3:
        vec = App.Vector(0, 0, 1)
    vec.normalize()
    
    offset_dist = 22.0
    p_outer = pt + vec * offset_dist
    NODES_OVER[k] = p_outer
    
    # Standoff solid cylinder (Dia 18mm, height 22mm)
    cyl = Part.makeCylinder(9.0, offset_dist, pt, vec)
    STANDOFFS.append(cyl)

print(f"Created {len(NODES_OVER)} external nodes and {len(STANDOFFS)} standoff bobbins.")
standoff_compound = Part.makeCompound(STANDOFFS)
print(f"Standoff compound isValid: {standoff_compound.isValid()}")
