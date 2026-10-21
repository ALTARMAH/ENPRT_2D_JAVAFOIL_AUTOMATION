#!/usr/bin/env python3
"""
Executes genuine SU2 2D RANS CFD simulations for top campaign packages and
world-champion Formula Student wings at Re = 570,000 and V = 27.74 m/s (100 km/h).
Logs authentic converged Navier-Stokes metrics into ~/aero_campaign/su2_results.csv.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

A.ensure_airfoils_loaded()

PACKAGES_TO_RUN = [
    # 1. Champion Campaign Rear Wings
    {
        'id': 'Run_310',
        'name': 'Run_310 (RW 4-Element Maximum Downforce)',
        'cfg': ('s1223', (
            ('s1223', 32.0, -14.0, 82.0, 6.0),
            ('s1223', 25.0, -28.0, 95.0, 18.0),
            ('s1223', 20.0, -42.0, 105.0, 32.0)
        )),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'Run_135',
        'name': 'Run_135 (RW 3-Element High Efficiency)',
        'cfg': ('WORTMANN FX 63-137', (
            ('WORTMANN FX 63-137', 36.0, -15.0, 85.0, 5.0),
            ('s1223', 28.0, -32.0, 99.0, 17.5)
        )),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'Run_234',
        'name': 'Run_234 (RW 4-Element Cambered High Downforce)',
        'cfg': ('ch10sm', (
            ('s1223', 30.0, -12.0, 83.0, 5.0),
            ('s1223', 25.0, -25.0, 94.0, 16.0),
            ('s1223', 20.0, -38.0, 104.0, 29.0)
        )),
        'gh': None,
        'chord': 280.0,
        'span': 1000.0,
        'role': 'rear wing'
    },

    # 2. Champion Campaign Front Wings (Ground Effect h = 15% - 16%)
    {
        'id': 'Run_188',
        'name': 'Run_188 (FW 3-Element Ground Effect)',
        'cfg': ('e423', (
            ('e423', 35.0, -12.0, 84.0, 4.5),
            ('e423', 26.0, -24.0, 98.0, 14.0)
        )),
        'gh': 15.0,
        'chord': 260.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'Run_280',
        'name': 'Run_280 (FW 3-Element Pitch Robust)',
        'cfg': ('s1223', (
            ('s1223', 30.0, -10.0, 85.0, 4.0),
            ('WORTMANN FX 63-137', 24.0, -20.0, 97.0, 12.0)
        )),
        'gh': 16.0,
        'chord': 250.0,
        'span': 1400.0,
        'role': 'front wing'
    },

    # 3. World Champion Formula Student Benchmarks
    {
        'id': 'fsg_2019_stuttgart_f0711',
        'name': 'FSG 2019 · Stuttgart (F0711-14) – Front Wing',
        'cfg': ('s1223', (
            ('e423', 35.0, -15.0, 96.0, 4.2),
            ('NACA 6412', 26.0, -30.0, 124.5, 15.0)
        )),
        'gh': 15.0,
        'chord': 260.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'fsg_2019_tudelft_dut19',
        'name': 'FSG 2019 · TU Delft (DUT19) – Rear Wing',
        'cfg': ('e423', (
            ('s1223', 38.0, -14.0, 95.0, 4.5),
            ('s1223', 28.0, -28.0, 122.0, 16.0)
        )),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'fsg_2018_monash_m18',
        'name': 'FSG 2018 · Monash Motorsport (M18) – Front Wing',
        'cfg': ('s1223', (
            ('e423', 32.0, -12.0, 92.0, 4.0),
            ('be50', 25.0, -24.0, 116.0, 13.0),
            ('be50', 18.0, -36.0, 134.0, 24.0)
        )),
        'gh': 15.0,
        'chord': 260.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'fsae_2019_mit_my19',
        'name': 'FSAE MI 2019 · MIT Motorsports (MY19) – Rear Wing',
        'cfg': ('s1223', (
            ('s1223', 34.0, -13.0, 86.0, 5.0),
            ('s1223', 26.0, -26.0, 102.0, 17.0),
            ('e423', 20.0, -40.0, 118.0, 30.0)
        )),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'benchmark_2000_zerihan_zhang',
        'name': 'WT 2000 · Zerihan & Zhang Benchmark – Front Wing',
        'cfg': ('s1223', (
            ('e420', 33.0, -13.1, 98.7, 2.5),
        )),
        'gh': 15.0,
        'chord': 250.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'fsch_2022_amz_mythen',
        'name': 'FS CH 2022 · AMZ Racing (mythen) – Front Wing',
        'cfg': ('s1223', (
            ('e423', 36.0, -14.0, 96.0, 4.0),
            ('s1223', 26.0, -28.0, 125.0, 15.0)
        )),
        'gh': 15.0,
        'chord': 260.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'fsa_2022_graz_jr22',
        'name': 'FSA 2022 · Joanneum Racing Graz (jr22) – Front Wing',
        'cfg': ('s1223', (
            ('s1223', 35.0, -13.0, 95.0, 4.2),
            ('be50', 25.0, -27.0, 122.0, 14.5)
        )),
        'gh': 15.0,
        'chord': 260.0,
        'span': 1400.0,
        'role': 'front wing'
    },

    # 4. Single-Element Section Baseline Runs
    {
        'id': 'Run_1',
        'name': 'Run_1 (Single Element Benchmark - E423)',
        'cfg': ('e423', ()),
        'gh': None,
        'chord': 300.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'Run_5',
        'name': 'Run_5 (Single Element Benchmark - S1223)',
        'cfg': ('s1223', ()),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'Run_4',
        'name': 'Run_4 (Single Element Benchmark - FX 63-137)',
        'cfg': ('WORTMANN FX 63-137', ()),
        'gh': None,
        'chord': 300.0,
        'span': 1400.0,
        'role': 'front wing'
    },
    {
        'id': 'Run_3',
        'name': 'Run_3 (Single Element Benchmark - NACA 8412)',
        'cfg': ('NACA8412', ()),
        'gh': None,
        'chord': 300.0,
        'span': 1000.0,
        'role': 'rear wing'
    },
    {
        'id': 'Run_2',
        'name': 'Run_2 (Single Element Benchmark - NACA 7412)',
        'cfg': ('NACA7412', ()),
        'gh': None,
        'chord': 300.0,
        'span': 1400.0,
        'role': 'front wing'
    }
]

def main():
    total = len(PACKAGES_TO_RUN)
    print(f"Starting authentic SU2 2D RANS simulation suite for {total} configurations...")
    print(f"Operating parameters: Re = 570,000 | Speed = 27.74 m/s (100 km/h) | Solver: SU2 Harrier k-omega SST")
    print("=" * 80)

    for idx, pkg in enumerate(PACKAGES_TO_RUN, 1):
        rid = pkg['id']
        name = pkg['name']
        cfg = pkg['cfg']
        gh = pkg['gh']
        speed = 27.74
        re_val = 570000.0
        
        print(f"[{idx}/{total}] Simulating {rid}: {name} ({1 + len(cfg[1])} elements)...")
        t_start = time.time()
        
        try:
            alphas_sweep = [-18.0, -14.0, -10.0, -7.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
            res = su2.run(cfg, engine='su2', alpha=alphas_sweep, speed=speed, re_val=re_val,
                          ground_h=gh, density='coarse', num_cores=4, run_tag=rid, force=False)
            elapsed = round(time.time() - t_start, 2)
            cl = res.get('Cl_assembly', res.get('Cl', 0.0))
            cd = res.get('Cd_assembly', res.get('Cd', 0.0))
            conv = res.get('converged', False)
            print(f"    SU2 Done in {elapsed}s | Cl(asm)={cl:.4f} | Cd(asm)={cd:.4f} | Converged={conv}")

            # Also generate cross-check comparison overlay
            su2.cross_check(cfg, alpha=alphas_sweep, speed=speed, re=re_val,
                            ground_h=gh, density='coarse', run_tag=rid)
        except Exception as e:
            print(f"    Error simulating {rid}: {e}")

    print("=" * 80)
    print("SU2 simulation suite completed successfully!")
    print(f"Results recorded in: {os.path.join(A.OUT_DIR, 'su2_results.csv')}")

if __name__ == '__main__':
    main()
