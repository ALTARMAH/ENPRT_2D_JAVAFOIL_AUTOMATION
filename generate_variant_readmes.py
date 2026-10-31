import os, shutil

BASE = "/home/user/aero_body/cad/BODYWORK_VARIANTS"

# 1. 00_WINGS_AERODYNAMIC_PACKAGE
rm_wings = """# FSAE Multi-Element Realistic Aerodynamic Wings Package
## ENPRT FSUK 2027 Autonomous Racing Team

### Included Assets & Elements
* **Front Wing Assembly (`Front_Wing_Assembly_Realistic_MultiElement.STEP` / `.stl`)**:
  - **Elements**: 3-element cascade (S1223 high-lift mainplane, slotted lower flap, upper cascade flap, and 8mm trailing edge Gurney flap).
  - **Endplates**: Profiled carbon endplates ($t=5\\text{ mm}$, span 1360 mm, $Z \\ge 35\\text{ mm}$).
  - **Outwash Footplates**: Horizontal ground-effect sealing flanges ($40\\text{ mm}$ width, overall width $1400\\text{ mm}$).
  - **Underwing Strakes**: 4 vertical ground-effect vortex fences (2 port, 2 starboard).
  - **Structural Pylons**: Twin aluminum uprights ($t=10\\text{ mm}$) connecting Front Bulkhead lower crossmember ($Y=700\\text{ mm}$, $Z=50\\text{ mm}$) to mainplane spar ($Y=1180\\text{ mm}$, $Z=75\\text{ mm}$).
  - **Chassis Hardpoints**: 4x M8 double-shear clevis lugs on Front Bulkhead.
* **Rear Wing Assembly (`Rear_Wing_Assembly_Realistic_MultiElement.STEP` / `.stl`)**:
  - **Elements**: 4-element high-downforce stack (S1223 mainplane, flap 1, flap 2, 10mm Gurney, plus lower beam wing).
  - **Endplates**: Deep profiled endplates with 3 aerodynamic pressure relief cutout louvers.
  - **DRS Pod**: Centerline aerodynamic actuator bullet housing.
  - **Flap Brackets**: Multi-hole pitch adjustment ribs at $X = \\pm 250\\text{ mm}$.
  - **Swan-Neck Pylons**: Twin structural towers ($t=12\\text{ mm}$) attaching to Rear Bulkhead ($Y=-1400\\text{ mm}$, $Z=350\\text{ mm}$) and Main Hoop Braces ($Y=-1150\\text{ mm}$, $Z=650\\text{ mm}$) to the top suction surface of the mainplane.
* **Master Wings Assembly**: `Full_Wings_Aerodynamic_Package.STEP`, `.stl`, and `.FCStd`.
"""
with open(os.path.join(BASE, "00_WINGS_AERODYNAMIC_PACKAGE/README.md"), "w") as f:
    f.write(rm_wings)

# 2. 01_VARIANT_A1_TRIANGULAR_INFILL
rm_a1 = """# Variant A1: Triangular Infill Fairing System ("Fill The Gap")
## ENPRT FSUK 2027 Autonomous Racing Team

### Design Philosophy
* **Concept**: 46 flat triangular composite plates mapped 1-to-1 inside the spaceframe bays.
* **Aesthetics**: Raw, technical mechanical exoskeleton appearance. The outer tubular frame is exposed while eliminating interior cavity turbulence.
* **Weight**: $9.43\\text{ kg}$ in $1.5\\text{ mm}$ carbon fiber prepreg ($16.42\\text{ kg}$ in Al 5052-H32).
* **Mounting**: 138 internal tabs welded to tube neutral axes with flush countersunk M5 fasteners.
* **Key Files**:
  - `Bodywork_Variant_A1_Triangular_Infill_Solid.STEP` / `.stl`
  - `Bodywork_Variant_A1_Triangular_Infill_Surface.STEP`
  - `Chassis_With_Bodywork_Variant_A1.STEP` / `.stl` / `.FCStd`
  - `Variant_A1_Triangular_Plates_Schedule.csv`
"""
with open(os.path.join(BASE, "01_VARIANT_A1_TRIANGULAR_INFILL/README.md"), "w") as f:
    f.write(rm_a1)

# 3. 02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS
rm_a2 = """# Variant A2: Over-The-Chassis Triangular Fairing ("Hide The Chassis")
## ENPRT FSUK 2027 Autonomous Racing Team

### Design Philosophy
* **Concept**: 46 flat triangular composite plates that wrap **over and outside** the chassis spaceframe, completely concealing the tubular steel frame.
* **Aesthetics**: Futuristic origami / stealth fighter faceted supercar styling with crisp knife-edge polygon ridge lines.
* **Clearance & Envelope**: All vertices offset by $+22.0\\text{ mm}$ outward along local surface normals from the spaceframe nodes, fully encapsulating $\\varnothing 25.4\\text{ mm}$ and $\\varnothing 30.0\\text{ mm}$ tubes with a $7\\text{ mm}$ safety air gap.
* **Mounting System ("Points to Stick to the Chassis")**:
  - 34 solid cylindrical standoff bobbins ($\\varnothing 18\\text{ mm} \\times 22\\text{ mm}$ height, AISI 4130 steel, M5 tapped).
  - Welded directly to the outer crowns of the spaceframe nodes.
  - Neoprene vibration-damping isolators with quick-release 1/4-turn Dzus studs.
* **Key Files**:
  - `Bodywork_Variant_A2_Triangular_Over_Chassis_Solid.STEP` / `.stl`
  - `Chassis_Mounting_Standoffs_34_Bobbins.STEP` / `.stl`
  - `Chassis_With_Bodywork_Variant_A2.STEP` / `.stl` / `.FCStd`
  - `Variant_A2_Triangular_Plates_Schedule.csv`
  - `Variant_A2_Chassis_Mounting_Standoffs_Schedule.csv`
  - `CUTTING_PATTERNS_DXF/`: 46 individual 1:1 CNC waterjet DXFs for fabrication.
  - `variant_a2_over_chassis_full_views.png`: High-resolution 4-view engineering rendering.
"""
with open(os.path.join(BASE, "02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS/README.md"), "w") as f:
    f.write(rm_a2)

# 4. 03_VARIANT_A3_TRIANGULAR_AERO_DUCT
rm_a3 = """# Variant A3: Aero-Duct Integrated Triangular Fairing
## ENPRT FSUK 2027 Autonomous Racing Team

### Design Philosophy
* **Concept**: Aggressive aerodynamic faceted bodywork incorporating high-downforce cooling ducts and underfloor management.
* **Features**:
  - High-rake faceted nosecone ($+30\\text{ mm}$ apex elevation) with an under-nose flow tunnel feeding the front undertray.
  - Angular faceted sidepod radiator scoops ($+40\\text{ mm}$ lateral offset) capturing boundary layer air for powertrain cooling.
  - Fastback boattail engine cowl shielding the rear wing swan-neck pylon towers.
* **Key Files**:
  - `Bodywork_Variant_A3_Triangular_AeroDuct_Solid.STEP` / `.stl`
  - `Chassis_With_Bodywork_Variant_A3.STEP` / `.stl` / `.FCStd`
  - `Variant_A3_Triangular_Plates_Schedule.csv`
"""
with open(os.path.join(BASE, "03_VARIANT_A3_TRIANGULAR_AERO_DUCT/README.md"), "w") as f:
    f.write(rm_a3)

# Sync READMEs to Downloads, Drive, and Project
for root_dst in ["/home/user/Downloads/BODYWORK_VARIANTS",
                 "/home/user/ENPRT_FSUK2027_TEAM_DRIVE/07_BODYWORK_VARIANTS",
                 "/home/user/ENPRT_FSUK2027/BODYWORK"]:
    for fldr in ["00_WINGS_AERODYNAMIC_PACKAGE", "01_VARIANT_A1_TRIANGULAR_INFILL",
                 "02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS", "03_VARIANT_A3_TRIANGULAR_AERO_DUCT"]:
        src_rm = os.path.join(BASE, fldr, "README.md")
        dst_rm = os.path.join(root_dst, fldr, "README.md")
        if os.path.exists(src_rm):
            os.makedirs(os.path.dirname(dst_rm), exist_ok=True)
            shutil.copy2(src_rm, dst_rm)

print("Generated and synced all variant READMEs.")
