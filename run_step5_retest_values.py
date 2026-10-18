"""
Step 5: Re-testing User Values & JavaFoil Inconsistencies
Analyzes Run_1 (NACA8412 + FX63-137 + ClarkY) and Run_1_famous (TBR21 E423 + S1210 + BE50)
Runs JavaFoil vs SU2 across alpha range [-5, -2, 0, 1, 2, 5] at Re = 570,000.
Calculates ratios, lift-curve slopes, and investigates the +1 deg jump and opposite alpha trends.
"""

import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

A.ensure_airfoils_loaded()

# Run_1 (User design)
run_1_cfg = ('NACA8412', [
    ('WORTMANN FX 63-137', 40.0, -26.0, 98.0, 5.0),
    ('clarky', 32.0, -30.0, 136.0, 15.0)
])

# Run_1_famous (TBR21-style)
run_1_famous_cfg = ('e423', [
    ('s1210', 34.0, -15.0, 96.0, 4.3),
    ('be50', 24.0, -31.0, 123.5, 14.8)
])

cases = [
    ("Run_1_MyDesign", run_1_cfg),
    ("Run_1_Famous_TBR21", run_1_famous_cfg)
]

alphas = [-5.0, -2.0, 0.0, 1.0, 2.0, 5.0]
re_val = 570000.0

all_records = []

print("==================================================")
print("Step 5: Re-testing User Values (Run_1 vs Run_1_famous)")
print("==================================================")

for name, cfg in cases:
    print(f"\nEvaluating {name}...")
    
    # 1. Verify geometry overlay
    matched, diff = su2.verify_geometry_overlay(cfg)
    print(f"  Geometry Overlay Check: Matched={matched}, MaxDiff={diff}")
    
    for a in alphas:
        print(f"  -> Alpha {a:g} deg...")
        
        # JavaFoil run
        jf_res = su2.run_javafoil_single_case(cfg, alpha_deg=a, re_val=re_val, ground_h=None)
        
        # SU2 run
        su2_res = su2.run_su2_single_case(cfg, alpha_deg=a, re_val=re_val, ground_h=None,
                                          density='medium', num_cores=4)
        
        cl_jf = jf_res.get('Cl')
        cd_jf = jf_res.get('Cd')
        
        cl_su2_main = su2_res.get('Cl')
        cd_su2_main = su2_res.get('Cd')
        cl_su2_asm = su2_res.get('Cl_assembly')
        cd_su2_asm = su2_res.get('Cd_assembly')
        
        # Ratio of JavaFoil to SU2
        ratio_cl = (cl_jf / cl_su2_asm) if (cl_jf is not None and cl_su2_asm is not None and abs(cl_su2_asm) > 1e-4) else None
        
        all_records.append({
            'Case': name,
            'Alpha': a,
            'JavaFoil_Cl': round(cl_jf, 3) if cl_jf is not None else None,
            'JavaFoil_Cd': round(cd_jf, 4) if cd_jf is not None else None,
            'SU2_Cl_Assembly': round(cl_su2_asm, 4) if cl_su2_asm is not None else None,
            'SU2_Cd_Assembly': round(cd_su2_asm, 5) if cd_su2_asm is not None else None,
            'SU2_Cl_Main': round(cl_su2_main, 4) if cl_su2_main is not None else None,
            'SU2_Cd_Main': round(cd_su2_main, 5) if cd_su2_main is not None else None,
            'Ratio_Cl_JF_to_SU2': round(ratio_cl, 2) if ratio_cl is not None else None,
            'SU2_Converged': su2_res.get('converged', False),
            'SU2_ResDrop': su2_res.get('residual_drop', 0.0),
            'SU2_Runtime_s': su2_res.get('runtime_s', 0.0)
        })

df = pd.DataFrame(all_records)
out_csv = os.path.join(HERE, "step5_retest_values_results.csv")
df.to_csv(out_csv, index=False)
print(f"\nStep 5 Complete. Results saved to {out_csv}")
print(df.to_string())
