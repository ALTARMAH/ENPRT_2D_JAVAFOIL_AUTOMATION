#!/usr/bin/env python3
"""
benchmark_front_wings.py
========================
Sets up the 6 front wing geometries from 'Front wings.xlsx' in aero_auto,
runs simulations (JavaFoil and SU2 2D RANS), and evaluates ANSYS reliability.
"""

import os
import sys
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = "/home/user/Applications/aero_auto"
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import aero_auto as A
import su2_engine as su2

A.ensure_airfoils_loaded()

CONFIGS = [
    {
        'id': 'My_profile',
        'name': 'My profile (E423 3-Element)',
        'main_airfoil': 'e423',
        'main_chord': 380.0,
        'main_aoa': 4.0,
        # Flaps: (airfoil, scale_pct, angle_deg, dx_pct, dy_pct)
        # Note: In aero_auto ROT_SIGN = -1, so negative angle rotates TE down.
        # Mainplane is pitched up by 4 deg, flap 1 is at 22 deg, flap 2 at 49 deg.
        'flaps': [
            ('e423', 25.0, -22.0, 97.0, 4.0),
            ('e423', 15.79, -49.0, 118.0, 14.0)
        ],
        'span': 600.0,
        'ansys_speed': 22.22,
        'ansys_area': 0.2816848,
        'ansys_drag': 26.815273,
        'ansys_lift': 187.9465,
        'ansys_cd': 0.3147929,
        'ansys_cl': 2.206363,
        'ansys_ld': 7.010358
    },
    {
        'id': 'TOP_1',
        'name': 'TOP 1 (S1223/S1223/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord': 300.0,
        'main_aoa': 0.0,
        'flaps': [
            ('s1223', 35.0, -24.0, 98.0, 4.5),
            ('e423', 30.0, -15.0, 128.0, 14.5)
        ],
        'span': 600.0,
        'ansys_speed': 25.00,
        'ansys_area': 0.2678878,
        'ansys_drag': 17.029724,
        'ansys_lift': 160.22362,
        'ansys_cd': 0.16606137,
        'ansys_cl': 1.5623832,
        'ansys_ld': 9.408469
    },
    {
        'id': 'TOP_2',
        'name': 'TOP 2 (S1223/S1223 2-Element)',
        'main_airfoil': 's1223',
        'main_chord': 300.0,
        'main_aoa': 0.0,
        'flaps': [
            ('s1223', 40.0, -24.0, 100.0, 5.0)
        ],
        'span': 300.0,
        'ansys_speed': 22.22,
        'ansys_area': 0.1227921,
        'ansys_drag': 12.456264,
        'ansys_lift': 44.106358,
        'ansys_cd': 0.33544642,
        'ansys_cl': 1.1877815,
        'ansys_ld': 3.540898
    },
    {
        'id': 'TOP_3',
        'name': 'TOP 3 (S1223/E423/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord': 300.0,
        'main_aoa': 0.0,
        'flaps': [
            ('e423', 35.0, -24.0, 98.0, 4.5),
            ('e423', 25.0, -15.0, 126.0, 13.5)
        ],
        'span': 500.0,
        'ansys_speed': 22.22,
        'ansys_area': 0.2294374,
        'ansys_drag': 17.195435,
        'ansys_lift': 87.680298,
        'ansys_cd': 0.24783035,
        'ansys_cl': 1.2636981,
        'ansys_ld': 5.099045
    },
    {
        'id': 'TOP_4',
        'name': 'TOP 4 (S1223/S1223/E423 3-Element Camber)',
        'main_airfoil': 's1223',
        'main_chord': 300.0,
        'main_aoa': 0.0,
        'flaps': [
            ('s1223', 40.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -20.0, 132.0, 11.5)
        ],
        'span': 400.0,
        'ansys_speed': 22.22,
        'ansys_area': 0.2015981,
        'ansys_drag': 15.839102,
        'ansys_lift': 71.177574,
        'ansys_cd': 0.25980687,
        'ansys_cl': 1.1675172,
        'ansys_ld': 4.493789
    },
    {
        'id': 'TOP_5',
        'name': 'TOP 5 (S1223/E423/E423 3-Element Staged)',
        'main_airfoil': 's1223',
        'main_chord': 300.0,
        'main_aoa': 0.0,
        'flaps': [
            ('e423', 30.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -25.0, 122.0, 12.0)
        ],
        'span': 500.0,
        'ansys_speed': 22.22,
        'ansys_area': 0.2327838,
        'ansys_drag': 22.425089,
        'ansys_lift': 108.05426,
        'ansys_cd': 0.31855702,
        'ansys_cl': 1.5349524,
        'ansys_ld': 4.818454
    }
]

def check_geometries():
    print("Checking geometry outlines and dimensions...")
    for item in CONFIGS:
        cfg = (item['main_airfoil'], item['flaps'])
        outs = A.build_outlines(cfg, ground_h=None)
        allp = np.vstack(outs)
        xmin, xmax = allp[:, 0].min(), allp[:, 0].max()
        ymin, ymax = allp[:, 1].min(), allp[:, 1].max()
        c_main = item['main_chord']
        dx_mm = (xmax - xmin) * c_main
        dy_mm = (ymax - ymin) * c_main
        c_ov_mm = np.hypot(dx_mm, dy_mm)
        print(f"[{item['id']}] Elements={1+len(item['flaps'])}, X-span={dx_mm:.1f} mm, Y-span={dy_mm:.1f} mm, c_ov={c_ov_mm:.1f} mm")

if __name__ == '__main__':
    check_geometries()
