"""
Step 4.2: Mesh Independence Study on 3-Element Wing (FWA_hero)
Tests Coarse, Medium, and Fine meshes in Gmsh + SU2 at Re 570k, alpha 0 deg.
Reports node counts, y+, Cl, Cd, runtime, and percentage change.
"""

import os
import sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

A.ensure_airfoils_loaded()

cfg = ('e423', [
    ('s1223', 43.0, -24.0, 101.0, 9.0),
    ('s1223', 32.0, -30.0, 141.55, 19.0)
])

densities = ['coarse', 'medium', 'fine']
results = []

print("==================================================")
print("Step 4.2: Running Mesh Independence Study (FWA_hero)")
print("==================================================")

base_cl = None
base_cd = None

for d in densities:
    print(f"\nRunning density: {d.upper()}...")
    res = su2.run_su2_single_case(cfg, alpha_deg=0.0, ground_h=None, density=d, num_cores=4)
    
    cl_val = res.get('Cl_assembly')
    cd_val = res.get('Cd_assembly')
    nodes = res.get('mesh_meta', {}).get('nodes', 0)
    elems = res.get('mesh_meta', {}).get('elements', 0)
    
    delta_cl_pct = 0.0
    delta_cd_pct = 0.0
    if base_cl is not None and abs(base_cl) > 1e-5:
        delta_cl_pct = round(100.0 * (cl_val - base_cl) / abs(base_cl), 2)
    if base_cd is not None and abs(base_cd) > 1e-5:
        delta_cd_pct = round(100.0 * (cd_val - base_cd) / abs(base_cd), 2)
        
    base_cl = cl_val
    base_cd = cd_val
    
    results.append({
        'Mesh_Density': d.capitalize(),
        'Nodes': nodes,
        'Elements': elems,
        'Cl_Assembly': round(cl_val, 4) if cl_val is not None else None,
        'Cd_Assembly': round(cd_val, 5) if cd_val is not None else None,
        'Cl_Main': round(res.get('Cl'), 4) if res.get('Cl') is not None else None,
        'Cd_Main': round(res.get('Cd'), 5) if res.get('Cd') is not None else None,
        'Delta_Cl_pct': delta_cl_pct,
        'Delta_Cd_pct': delta_cd_pct,
        'Residual_Drop': res.get('residual_drop', 0.0),
        'Iterations': res.get('iterations', 0),
        'Runtime_s': res.get('runtime_s', 0.0)
    })

df = pd.DataFrame(results)
out_csv = os.path.join(HERE, "step4_mesh_independence_results.csv")
df.to_csv(out_csv, index=False)
print(f"\nMesh Independence Complete. Saved to {out_csv}")
print(df.to_string())
