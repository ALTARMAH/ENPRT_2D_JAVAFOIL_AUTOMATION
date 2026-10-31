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

bb = chassis.BoundBox
print(f"Chassis bounds: X[{bb.XMin:.1f}, {bb.XMax:.1f}], Y[{bb.YMin:.1f}, {bb.YMax:.1f}], Z[{bb.ZMin:.1f}, {bb.ZMax:.1f}]")

# Let's build the Modern F1 Sculpted Fairing over the chassis
# All surfaces sit strictly OUTSIDE the chassis tubes:
# Chassis X is within [-385, +385]
# Chassis Y is within [-1415, +712.5] (plus nose tip at Y=1150)
# Chassis Z is within [13.5, 1258]

# 1. Formula Needle Nose & Front Monocoque Fairing (Y = 1195 down to Front Hoop Y = 0)
# Outer profiles that comfortably enclose the front spaceframe:
# Section 1: Needle Nose Tip at Y=1195, Z=190, Width=120, Height=90
w_n1 = Part.Wire(Part.makePolygon([
    App.Vector(0, 1195, 235),
    App.Vector(60, 1195, 190),
    App.Vector(0, 1195, 145),
    App.Vector(-60, 1195, 190),
    App.Vector(0, 1195, 235)
]))

# Section 2: Mid-Nose (Y=950, Z=210, Width=280, Height=180)
w_n2 = Part.Wire(Part.makePolygon([
    App.Vector(0, 950, 300),
    App.Vector(140, 950, 210),
    App.Vector(0, 950, 120),
    App.Vector(-140, 950, 210),
    App.Vector(0, 950, 300)
]))

# Section 3: Front Bulkhead Outer Shell (Y=700, Z=220, Width=490, Height=380)
# Chassis at Y=700 has tubes at X=+-225, Z=50 to 370
# Outer shell: X=+-245, Z=30 to 400
w_n3 = Part.Wire(Part.makePolygon([
    App.Vector(-245, 715, 395),
    App.Vector( 245, 715, 395),
    App.Vector( 245, 715,  30),
    App.Vector(-245, 715,  30),
    App.Vector(-245, 715, 395)
]))

# Section 4: Cockpit Hood at Front Hoop (Y=0)
# Chassis at Y=0 has tubes at X=+-200..275, Z=50 to 590
# Outer shell: X=+-295, Z=30 to 625
w_n4 = Part.Wire(Part.makePolygon([
    App.Vector(-215, 0, 625),
    App.Vector( 215, 0, 625),
    App.Vector( 295, 0, 565),
    App.Vector( 315, 0, 200),
    App.Vector( 265, 0,  30),
    App.Vector(-265, 0,  30),
    App.Vector(-315, 0, 200),
    App.Vector(-295, 0, 565),
    App.Vector(-215, 0, 625)
]))

nose_solid = Part.makeLoft([w_n1, w_n2, w_n3], True, True)
front_deck_solid = Part.makeLoft([w_n3, w_n4], True, True)

print(f"Nose solid: isValid={nose_solid.isValid()}, Volume={nose_solid.Volume:.1f} mm3")
print(f"Front deck solid: isValid={front_deck_solid.isValid()}, Volume={front_deck_solid.Volume:.1f} mm3")

# Check clash with chassis
print(f"Nose vs Chassis: {nose_solid.common(chassis).Volume:.4f} mm3")
print(f"Front deck vs Chassis: {front_deck_solid.common(chassis).Volume:.4f} mm3")

