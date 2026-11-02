import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part

from test_all_46_zero_clash import NODES_CHASSIS, NODES_OUTER, comp, chassis

standoffs = []
standoff_records = []

for k, p_tube in NODES_CHASSIS.items():
    if k not in NODES_OUTER: continue
    p_inner = NODES_OUTER[k]
    
    vec_so = p_inner - p_tube
    dist = vec_so.Length
    if dist < 1.0: continue
    
    dir_so = vec_so * (1.0 / dist)
    
    # Start at tube crown (14.0mm from centerline)
    r_tube = 13.5
    h_bobbin = dist - r_tube
    if h_bobbin < 2.0:
        r_tube = dist * 0.3
        h_bobbin = dist * 0.7
        
    p_start = p_tube + dir_so * r_tube
    
    # 12mm dia aluminum bobbin (radius 6.0mm)
    bobbin = Part.makeCylinder(6.0, h_bobbin, p_start, dir_so)
    
    # Cut bodywork so bobbin terminates exactly flush with inner face
    try:
        bobbin_clean = bobbin.cut(comp)
        if not bobbin_clean.isNull() and bobbin_clean.isValid():
            bobbin = bobbin_clean
    except Exception as e:
        pass
        
    standoffs.append(bobbin)
    standoff_records.append({
        'Node': k,
        'X_chassis': p_tube.x, 'Y_chassis': p_tube.y, 'Z_chassis': p_tube.z,
        'X_outer': p_inner.x, 'Y_outer': p_inner.y, 'Z_outer': p_inner.z,
        'Length_mm': h_bobbin,
        'Dia_mm': 12.0,
        'Material': 'Al 6061-T6'
    })

so_comp = Part.makeCompound(standoffs)
print(f"Standoffs compound built: {len(standoffs)} bobbins, isValid={so_comp.isValid()}")
print(f"Standoffs check(True): {so_comp.check(True)}")

# Verify interference
v_so_body = so_comp.common(comp).Volume
print(f"Standoffs vs Bodywork common volume: {v_so_body:.4f} mm3")
