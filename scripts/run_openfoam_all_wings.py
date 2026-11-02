#!/usr/bin/env python3
"""
run_openfoam_all_wings.py
=========================
Executes authentic OpenFOAM-13 RANS (k-omega SST) simulations for all 6 front wing
profiles from 'Front wings.xlsx' in aero_auto.
"""

import os
import sys
import time
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import aero_auto as A
import openfoam_engine as ofe

CONFIGS = [
    {
        'id': 'My_profile',
        'name': 'My profile (E423 3-Element)',
        'main_airfoil': 'e423',
        'main_chord_mm': 380.0,
        'span_mm': 600.0,
        'sim_alpha': 4.0,
        'speed_ms': 22.222,
        'flaps': [
            ('e423', 25.0, -18.0, 97.0, 4.0),
            ('e423', 15.79, -45.0, 118.0, 14.0)
        ]
    },
    {
        'id': 'TOP_1',
        'name': 'TOP 1 (S1223/S1223/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'span_mm': 600.0,
        'sim_alpha': 0.0,
        'speed_ms': 25.000,
        'flaps': [
            ('s1223', 35.0, -24.0, 98.0, 4.5),
            ('e423', 30.0, -15.0, 128.0, 14.5)
        ]
    },
    {
        'id': 'TOP_2',
        'name': 'TOP 2 (S1223/S1223 2-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'span_mm': 300.0,
        'sim_alpha': 0.0,
        'speed_ms': 22.222,
        'flaps': [
            ('s1223', 40.0, -24.0, 100.0, 5.0)
        ]
    },
    {
        'id': 'TOP_3',
        'name': 'TOP 3 (S1223/E423/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'span_mm': 500.0,
        'sim_alpha': 0.0,
        'speed_ms': 22.222,
        'flaps': [
            ('e423', 35.0, -24.0, 98.0, 4.5),
            ('e423', 25.0, -15.0, 126.0, 13.5)
        ]
    },
    {
        'id': 'TOP_4',
        'name': 'TOP 4 (S1223/S1223/E423 3-Element Camber)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'span_mm': 400.0,
        'sim_alpha': 0.0,
        'speed_ms': 22.222,
        'flaps': [
            ('s1223', 40.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -20.0, 132.0, 11.5)
        ]
    },
    {
        'id': 'TOP_5',
        'name': 'TOP 5 (S1223/E423/E423 3-Element Staged)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'span_mm': 500.0,
        'sim_alpha': 0.0,
        'speed_ms': 22.222,
        'flaps': [
            ('e423', 30.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -25.0, 122.0, 12.0)
        ]
    }
]

def main():
    print("=" * 80)
    print("STARTING FULL OPENFOAM-13 RANS SIMULATION SUITE")
    print("=" * 80)
    results = []

    for idx, item in enumerate(CONFIGS, 1):
        cid = item['id']
        name = item['name']
        cfg = (item['main_airfoil'], item['flaps'])
        c_main = item['main_chord_mm']
        span = item['span_mm']
        alpha = item['sim_alpha']
        speed = item['speed_ms']

        print(f"\n[{idx}/{len(CONFIGS)}] Simulating {cid}: {name}...")
        t_start = time.time()
        res = ofe.run_openfoam_single_case(
            cfg, main_chord_mm=c_main, span_mm=span, alpha_deg=alpha,
            speed=speed, density='coarse', max_iters=200
        )
        elapsed = round(time.time() - t_start, 1)

        if res.get('status') == 'Success':
            cl = res['Cl_assembly']
            cd = res['Cd_assembly']
            ld = res['LD']
            lift = res['Lift_Actual_N']
            drag = res['Drag_Actual_N']
            print(f"    OpenFOAM Done in {elapsed}s | Cl(asm)={cl:.3f} | Cd(asm)={cd:.4f} | L/D={ld:.2f} | Lift={lift:.1f}N | Drag={drag:.1f}N")
            
            # Equalized forces at V = 80 km/h (22.222 m/s, q = 302.41 Pa), span = 600 mm (0.6 m)
            q_std = 302.41
            c_asm_m = res['assembly_chord_mm'] / 1000.0
            area_std = c_asm_m * 0.6
            lift_std = cl * q_std * area_std
            drag_std = cd * q_std * area_std

            rec = {
                'ID': cid,
                'Name': name,
                'OpenFOAM_Cl_asm': cl,
                'OpenFOAM_Cd_asm': cd,
                'OpenFOAM_LD': ld,
                'OpenFOAM_Cl_main': res['Cl_main'],
                'OpenFOAM_Cd_main': res['Cd_main'],
                'OpenFOAM_Raw_Lift_N': lift,
                'OpenFOAM_Raw_Drag_N': drag,
                'OpenFOAM_Lift_Equalized_80kph_600mm_N': round(lift_std, 2),
                'OpenFOAM_Drag_Equalized_80kph_600mm_N': round(drag_std, 2),
                'Runtime_s': elapsed
            }
            results.append(rec)
        else:
            print(f"    OpenFOAM Failed for {cid}: {res.get('error')}")

    df = pd.DataFrame(results)
    out_csv = os.path.join(ofe.RUNS_DIR, "openfoam_all_results.csv")
    df.to_csv(out_csv, index=False)
    print("\n" + "=" * 80)
    print(f"OpenFOAM-13 benchmark completed. Results saved to {out_csv}")
    print(df.to_string())

if __name__ == '__main__':
    main()
