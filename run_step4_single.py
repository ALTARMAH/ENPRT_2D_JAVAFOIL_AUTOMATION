"""
Step 4.1: Single-Element Validation Study
Compares SU2 (RANS SST) vs XFOIL (viscous panel) vs JavaFoil for E423 and S1223
at Re = 570,000, alpha = -5 to 10 deg, unbounded flow (no ground).
"""

import os
import sys
import json
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

A.ensure_airfoils_loaded()

alphas = [-5.0, -2.0, 0.0, 2.0, 5.0, 8.0, 10.0]
airfoils = ['e423', 's1223']
re_val = 570000.0

results = []

for foil in airfoils:
    print(f"\n==========================================")
    print(f"Running Single-Element Study: {foil}")
    print(f"==========================================")
    
    # 1. XFOIL Polar
    print(f"Running XFOIL for {foil}...")
    xfoil_data = {r['alpha']: r for r in su2.run_xfoil_single_element(foil, alphas, re_val=re_val)}
    
    # 2. SU2 & JavaFoil points
    cfg = (foil, [])
    
    for a in alphas:
        print(f"  -> Alpha {a:g} deg...")
        
        # JavaFoil
        jf_res = su2.run_javafoil_single_case(cfg, alpha_deg=a, re_val=re_val, ground_h=None)
        
        # SU2
        su2_res = su2.run_su2_single_case(cfg, alpha_deg=a, re_val=re_val, ground_h=None,
                                          density='medium', num_cores=4)
        
        # XFOIL
        xf_r = xfoil_data.get(a, {})
        
        # xfoil_data already has inverted geometry coordinates matching aero_auto convention
        xf_cl = xf_r.get('Cl', None)
        xf_cd = xf_r.get('Cd', None)
        
        results.append({
            'Airfoil': foil,
            'Alpha': a,
            'XFOIL_Cl': round(xf_cl, 4) if xf_cl is not None else None,
            'XFOIL_Cd': round(xf_cd, 5) if xf_cd is not None else None,
            'SU2_Cl': round(su2_res.get('Cl'), 4) if su2_res.get('Cl') is not None else None,
            'SU2_Cd': round(su2_res.get('Cd'), 5) if su2_res.get('Cd') is not None else None,
            'SU2_Converged': su2_res.get('converged', False),
            'SU2_ResDrop': su2_res.get('residual_drop', 0.0),
            'JavaFoil_Cl': round(jf_res.get('Cl'), 4) if jf_res.get('Cl') is not None else None,
            'JavaFoil_Cd': round(jf_res.get('Cd'), 5) if jf_res.get('Cd') is not None else None,
            'SU2_Runtime_s': su2_res.get('runtime_s', 0.0)
        })

df = pd.DataFrame(results)
out_csv = os.path.join(HERE, "step4_single_element_results.csv")
df.to_csv(out_csv, index=False)
print(f"\nStep 4.1 Complete. Results saved to {out_csv}")
print(df.to_string())
