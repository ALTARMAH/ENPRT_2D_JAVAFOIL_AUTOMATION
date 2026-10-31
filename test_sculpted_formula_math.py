import sys, math
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

CHASSIS_STEP = "/home/user/Downloads/Chassis.STEP"
doc_ch = App.newDocument("ChTest")
Import.insert(CHASSIS_STEP, doc_ch.Name)
chassis = doc_ch.Objects[0].Shape.copy()
App.closeDocument(doc_ch.Name)

def make_thin_panel(poly_pts, out_dir, t=1.5):
    """Creates a thin-walled composite solid panel with outward normal extrusion."""
    v1, v2, v3 = poly_pts[0], poly_pts[1], poly_pts[2]
    norm = (v2 - v1).cross(v3 - v1)
    norm.normalize()
    if norm.dot(out_dir) < 0: norm = -norm
    
    # If 4 points (quadrilateral), make quad face
    if len(poly_pts) == 4 and poly_pts[0] != poly_pts[-1]:
        poly_pts = poly_pts + [poly_pts[0]]
    elif len(poly_pts) == 3 and poly_pts[0] != poly_pts[-1]:
        poly_pts = poly_pts + [poly_pts[0]]
        
    face = Part.Face(Part.makePolygon(poly_pts))
    return face.extrude(norm * t)

# Let's test the F1 Sculpted Panels:
# 1. Monocoque Nose Cone (Curvilinear Faceted)
# 2. Cockpit Top Deck (Sponsor Billboard)
# 3. High-Inlet Undercut Sidepods (Left & Right)
# 4. Engine Cowl with Shark Fin Spine (Yaw stability & Title Sponsor Billboard)
# 5. Full-Length Undertray Diffuser Floor

# Test Shark Fin Spine:
# Spine sits on vehicle centerline X = 0, running from Main Hoop apex (Y=-905, Z=1290)
# down to Rear Bulkhead (Y=-1435, Z=380), with height +350 mm above engine deck!
# Thickness t = 4.0 mm Al / Carbon composite blade!
fin_pts = [
    App.Vector(0.0, -905.0, 1095.0),
    App.Vector(0.0, -905.0, 1320.0),
    App.Vector(0.0, -1250.0, 1180.0),
    App.Vector(0.0, -1435.0, 580.0),
    App.Vector(0.0, -1435.0, 380.0)
]
fin_face = Part.Face(Part.makePolygon(fin_pts + [fin_pts[0]]))
shark_fin_solid = fin_face.extrude(App.Vector(2.0, 0.0, 0.0)) # 4mm thick centered on X=0
shark_fin_solid.translate(App.Vector(-2.0, 0.0, 0.0))

print(f"Shark Fin Solid: isValid={shark_fin_solid.isValid()}")
print(f"Shark Fin vs Chassis: {shark_fin_solid.common(chassis).Volume:.4f} mm3")


# Test Undercut Sidepod (Left and Right)
# Outer Flank (Sponsor Billboard)
p_sp_fwd_top = App.Vector(-440.0, 0.0, 375.0)
p_sp_fwd_mid = App.Vector(-440.0, 0.0, 180.0)
p_sp_fwd_bot = App.Vector(-330.0, 0.0, 40.0)

p_sp_aft_top = App.Vector(-420.0, -875.0, 280.0)
p_sp_aft_mid = App.Vector(-420.0, -875.0, 180.0)
p_sp_aft_bot = App.Vector(-330.0, -875.0, 40.0)

p_sp_in_top_fwd = App.Vector(-310.0, 0.0, 375.0)
p_sp_in_top_aft = App.Vector(-310.0, -875.0, 280.0)

# Top Deck
p_top_deck = make_thin_panel([p_sp_in_top_fwd, p_sp_fwd_top, p_sp_aft_top, p_sp_in_top_aft], App.Vector(0, 0, 1), t=1.5)
# Vertical Billboard
p_billboard = make_thin_panel([p_sp_fwd_top, p_sp_aft_top, p_sp_aft_mid, p_sp_fwd_mid], App.Vector(-1, 0, 0), t=1.5)
# Undercut Scoop
p_undercut = make_thin_panel([p_sp_fwd_mid, p_sp_aft_mid, p_sp_aft_bot, p_sp_fwd_bot], App.Vector(-0.7, 0, -0.7), t=1.5)

for name, s in [('Sidepod_Top', p_top_deck), ('Sidepod_Billboard', p_billboard), ('Sidepod_Undercut', p_undercut)]:
    print(f"{name}: isValid={s.isValid()}, Chassis Clash={s.common(chassis).Volume:.4f} mm3")

