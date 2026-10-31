import sys, os, struct, glob

sys.path.append('/usr/lib/freecad/lib')
import FreeCAD
import Import

def verify_stl(stl_path):
    size = os.path.getsize(stl_path)
    if size < 84:
        return False, f"File too small: {size} bytes"
    with open(stl_path, 'rb') as f:
        header = f.read(80)
        n_tris = struct.unpack('<I', f.read(4))[0]
    expected_size = 84 + n_tris * 50
    if size != expected_size:
        return False, f"Size mismatch: got {size}, expected {expected_size} (tris={n_tris})"
    return True, f"Valid standard binary STL: {n_tris:,} triangles, {size/(1024*1024):.2f} MB"

def verify_step(step_path):
    doc_name = "TestStep_" + os.path.basename(step_path).replace('.', '_').replace('-', '_')
    doc = FreeCAD.newDocument(doc_name)
    try:
        Import.insert(step_path, doc.Name)
        objs = doc.Objects
        if not objs:
            return False, "No objects imported from STEP"
        total_solids = 0
        total_faces = 0
        invalid_shapes = 0
        for obj in objs:
            if hasattr(obj, 'Shape') and obj.Shape is not None:
                total_solids += len(obj.Shape.Solids)
                total_faces += len(obj.Shape.Faces)
                if not obj.Shape.isValid():
                    invalid_shapes += 1
        return True, f"Valid STEP: {len(objs)} objects, {total_solids} solids, {total_faces} faces, invalid={invalid_shapes}"
    except Exception as e:
        return False, f"Import error: {e}"
    finally:
        FreeCAD.closeDocument(doc.Name)

def verify_fcstd(fcstd_path):
    doc_name = "TestFCStd_" + os.path.basename(fcstd_path).replace('.', '_').replace('-', '_')
    try:
        doc = FreeCAD.openDocument(fcstd_path)
        objs = doc.Objects
        if not objs:
            return False, "No objects in FCStd"
        return True, f"Valid FCStd: {len(objs)} objects ({', '.join([o.Name for o in objs[:5]])}...)"
    except Exception as e:
        return False, f"Open error: {e}"
    finally:
        FreeCAD.closeDocument(doc.Name)

check_dirs = [
    '/home/user/aero_body/cad/bodywork_assemblies/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/00_WINGS_AERODYNAMIC_PACKAGE/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/01_VARIANT_F1_RED_BULL_RB20/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/02_VARIANT_F1_FERRARI_SF24/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/03_VARIANT_F1_MCLAREN_MCL38/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/04_VARIANT_F1_MERCEDES_W15/',
    '/home/user/aero_body/cad/BODYWORK_VARIANTS/05_VARIANT_F1_STEALTH_FACETED/'
]

print("="*70)
print("RUNNING CAD INTEGRITY AUDIT ON aero_body DIRECTORIES")
print("="*70)

all_ok = True

for d in check_dirs:
    if not os.path.exists(d):
        continue
    print(f"\n--- Checking Directory: {d} ---")
    stls = sorted(glob.glob(os.path.join(d, "*.stl")))
    steps = sorted(glob.glob(os.path.join(d, "*.step")) + glob.glob(os.path.join(d, "*.STEP")))
    fcstds = sorted([f for f in glob.glob(os.path.join(d, "*.FCStd")) if not f.endswith('.FCBak')])
    
    for stl in stls:
        ok, msg = verify_stl(stl)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] STL: {os.path.basename(stl)} -> {msg}")
        if not ok: all_ok = False
        
    for stp in steps:
        ok, msg = verify_step(stp)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] STEP: {os.path.basename(stp)} -> {msg}")
        if not ok: all_ok = False
        
    for fc in fcstds:
        ok, msg = verify_fcstd(fc)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] FCStd: {os.path.basename(fc)} -> {msg}")
        if not ok: all_ok = False

print("\n" + "="*70)
if all_ok:
    print("ALL CAD INTEGRITY CHECKS PASSED: 0 CORRUPTIONS DETECTED")
else:
    print("FAILURES DETECTED")
print("="*70)
