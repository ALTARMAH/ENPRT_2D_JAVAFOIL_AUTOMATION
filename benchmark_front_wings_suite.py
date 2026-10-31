#!/usr/bin/env python3
"""
benchmark_front_wings_suite.py
==============================
Full automated benchmark and verification of the 6 front wing profiles from
'Front wings.xlsx' inside aero_auto.

Runs:
  1. JavaFoil panel code with boundary layer
  2. SU2 2D RANS (k-omega SST)
  3. Speed normalization & Reference Area correction
  4. Generates side-by-side charts, polar curves, and CSV data.
"""

import os
import sys
import math
import time
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

RUNS_DIR = os.path.join(HERE, "runs", "front_wings_benchmark")
os.makedirs(RUNS_DIR, exist_ok=True)

CONFIGS = [
    {
        'id': 'My_profile',
        'name': 'My profile (E423 3-Element)',
        'main_airfoil': 'e423',
        'main_chord_mm': 380.0,
        'main_aoa_deg': 4.0,
        'flaps': [
            ('e423', 25.0, -18.0, 97.0, 4.0),
            ('e423', 15.79, -45.0, 118.0, 14.0)
        ],
        'sim_alpha': 4.0,
        'span_mm': 600.0,
        'excel_row': 11,
        'ansys_speed_ms': 22.222,
        'ansys_q_pa': 302.41,
        'ansys_area_m2': 0.2816848,
        'ansys_drag_n': 26.815273,
        'ansys_lift_n': 187.9465,
        'ansys_cd': 0.3147929,
        'ansys_cl': 2.206363,
        'ansys_ld': 7.010358
    },
    {
        'id': 'TOP_1',
        'name': 'TOP 1 (S1223/S1223/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'main_aoa_deg': 0.0,
        'flaps': [
            ('s1223', 35.0, -24.0, 98.0, 4.5),
            ('e423', 30.0, -15.0, 128.0, 14.5)
        ],
        'sim_alpha': 0.0,
        'span_mm': 600.0,
        'excel_row': 14,
        'ansys_speed_ms': 25.000,
        'ansys_q_pa': 382.8125,
        'ansys_area_m2': 0.2678878,
        'ansys_drag_n': 17.029724,
        'ansys_lift_n': 160.22362,
        'ansys_cd': 0.16606137,
        'ansys_cl': 1.5623832,
        'ansys_ld': 9.408469
    },
    {
        'id': 'TOP_2',
        'name': 'TOP 2 (S1223/S1223 2-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'main_aoa_deg': 0.0,
        'flaps': [
            ('s1223', 40.0, -24.0, 100.0, 5.0)
        ],
        'sim_alpha': 0.0,
        'span_mm': 300.0,
        'excel_row': 17,
        'ansys_speed_ms': 22.222,
        'ansys_q_pa': 302.41,
        'ansys_area_m2': 0.1227921,
        'ansys_drag_n': 12.456264,
        'ansys_lift_n': 44.106358,
        'ansys_cd': 0.33544642,
        'ansys_cl': 1.1877815,
        'ansys_ld': 3.540898
    },
    {
        'id': 'TOP_3',
        'name': 'TOP 3 (S1223/E423/E423 3-Element)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'main_aoa_deg': 0.0,
        'flaps': [
            ('e423', 35.0, -24.0, 98.0, 4.5),
            ('e423', 25.0, -15.0, 126.0, 13.5)
        ],
        'sim_alpha': 0.0,
        'span_mm': 500.0,
        'excel_row': 19,
        'ansys_speed_ms': 22.222,
        'ansys_q_pa': 302.41,
        'ansys_area_m2': 0.2294374,
        'ansys_drag_n': 17.195435,
        'ansys_lift_n': 87.680298,
        'ansys_cd': 0.24783035,
        'ansys_cl': 1.2636981,
        'ansys_ld': 5.099045
    },
    {
        'id': 'TOP_4',
        'name': 'TOP 4 (S1223/S1223/E423 3-Element Camber)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'main_aoa_deg': 0.0,
        'flaps': [
            ('s1223', 40.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -20.0, 132.0, 11.5)
        ],
        'sim_alpha': 0.0,
        'span_mm': 400.0,
        'excel_row': 22,
        'ansys_speed_ms': 22.222,
        'ansys_q_pa': 302.41,
        'ansys_area_m2': 0.2015981,
        'ansys_drag_n': 15.839102,
        'ansys_lift_n': 71.177574,
        'ansys_cd': 0.25980687,
        'ansys_cl': 1.1675172,
        'ansys_ld': 4.493789
    },
    {
        'id': 'TOP_5',
        'name': 'TOP 5 (S1223/E423/E423 3-Element Staged)',
        'main_airfoil': 's1223',
        'main_chord_mm': 300.0,
        'main_aoa_deg': 0.0,
        'flaps': [
            ('e423', 30.0, -6.0, 98.0, 4.0),
            ('e423', 30.0, -25.0, 122.0, 12.0)
        ],
        'sim_alpha': 0.0,
        'span_mm': 500.0,
        'excel_row': 25,
        'ansys_speed_ms': 22.222,
        'ansys_q_pa': 302.41,
        'ansys_area_m2': 0.2327838,
        'ansys_drag_n': 22.425089,
        'ansys_lift_n': 108.05426,
        'ansys_cd': 0.31855702,
        'ansys_cl': 1.5349524,
        'ansys_ld': 4.818454
    }
]

def run_suite():
    results = []
    print("=" * 80)
    print("AERO_AUTO FRONT WING BENCHMARK SUITE (ANSYS vs SU2 vs JavaFoil)")
    print("=" * 80)

    for item in CONFIGS:
        cid = item['id']
        name = item['name']
        cfg = (item['main_airfoil'], item['flaps'])
        alpha = item['sim_alpha']
        speed = item['ansys_speed_ms']
        c_main_m = item['main_chord_mm'] / 1000.0
        re_val = (1.225 * speed * c_main_m) / 1.7894e-5

        print(f"\n--- Testing [{cid}] : {name} ---")
        print(f"    Speed: {speed:.2f} m/s | Re: {re_val:.0f} | Alpha: {alpha} deg")

        # 1. JavaFoil
        t0 = time.time()
        jf_res = su2.run_javafoil_single_case(cfg, alpha_deg=alpha, re_val=re_val, ground_h=None)
        jf_time = time.time() - t0
        cl_jf = abs(jf_res.get('Cl', 0.0))
        cd_jf = abs(jf_res.get('Cd', 0.0))
        ld_jf = cl_jf / cd_jf if cd_jf > 1e-4 else 0.0
        print(f"    JavaFoil: Cl={cl_jf:.3f}, Cd={cd_jf:.4f}, L/D={ld_jf:.2f} ({jf_time:.1f}s)")

        # 2. SU2 2D RANS
        t0 = time.time()
        su2_res = su2.run_su2_single_case(cfg, alpha_deg=alpha, speed=speed, re_val=re_val,
                                          density='coarse', num_cores=4)
        su2_time = time.time() - t0
        cl_su2_main = abs(su2_res.get('Cl', 0.0))
        cd_su2_main = abs(su2_res.get('Cd', 0.0))
        cl_su2_asm = abs(su2_res.get('Cl_assembly', 0.0))
        cd_su2_asm = abs(su2_res.get('Cd_assembly', 0.0))
        ld_su2_asm = cl_su2_asm / cd_su2_asm if cd_su2_asm > 1e-4 else 0.0
        ld_su2_main = cl_su2_main / cd_su2_main if cd_su2_main > 1e-4 else 0.0
        conv = su2_res.get('converged', False)
        print(f"    SU2 Assembly: Cl={cl_su2_asm:.3f}, Cd={cd_su2_asm:.4f}, L/D={ld_su2_asm:.2f} (Conv={conv}, {su2_time:.1f}s)")
        print(f"    SU2 Mainplane-Ref: Cl={cl_su2_main:.3f}, Cd={cd_su2_main:.4f}, L/D={ld_su2_main:.2f}")

        # Geometric actual planform area
        outs = A.build_outlines(cfg, ground_h=None)
        allp = np.vstack(outs)
        dx_proj_m = (allp[:, 0].max() - allp[:, 0].min()) * c_main_m
        span_m = item['span_mm'] / 1000.0
        actual_area_m2 = dx_proj_m * span_m

        # ANSYS Corrected metrics (using actual planform area)
        q_ansys = item['ansys_q_pa']
        cl_ansys_corrected = item['ansys_lift_n'] / (q_ansys * actual_area_m2)
        cd_ansys_corrected = item['ansys_drag_n'] / (q_ansys * actual_area_m2)

        # Equalized forces at standard baseline: V = 80 km/h (22.22 m/s, q = 302.41 Pa), span = 600 mm (0.6 m)
        q_std = 302.41
        area_std_600 = dx_proj_m * 0.6
        lift_std_ansys = cl_ansys_corrected * q_std * area_std_600
        drag_std_ansys = cd_ansys_corrected * q_std * area_std_600

        lift_std_su2 = cl_su2_asm * q_std * area_std_600
        drag_std_su2 = cd_su2_asm * q_std * area_std_600

        lift_std_jf = cl_jf * q_std * area_std_600
        drag_std_jf = cd_jf * q_std * area_std_600

        # Discrepancy % (ANSYS Corrected vs SU2 Assembly)
        diff_cl_pct = ((item['ansys_cl'] - cl_su2_asm) / cl_su2_asm) * 100.0 if cl_su2_asm > 0 else 0.0
        diff_cd_pct = ((item['ansys_cd'] - cd_su2_asm) / cd_su2_asm) * 100.0 if cd_su2_asm > 0 else 0.0

        rec = {
            'ID': cid,
            'Name': name,
            'Elements': 1 + len(item['flaps']),
            'Main_Airfoil': item['main_airfoil'],
            'Span_mm': item['span_mm'],
            'Speed_ms': speed,
            'Area_Excel_m2': item['ansys_area_m2'],
            'Area_Actual_m2': round(actual_area_m2, 4),
            'ANSYS_Raw_Lift_N': item['ansys_lift_n'],
            'ANSYS_Raw_Drag_N': item['ansys_drag_n'],
            'ANSYS_Reported_Cl': item['ansys_cl'],
            'ANSYS_Reported_Cd': item['ansys_cd'],
            'ANSYS_Reported_LD': item['ansys_ld'],
            'ANSYS_Corrected_Cl': round(cl_ansys_corrected, 3),
            'ANSYS_Corrected_Cd': round(cd_ansys_corrected, 4),
            'JavaFoil_Cl': round(cl_jf, 3),
            'JavaFoil_Cd': round(cd_jf, 4),
            'JavaFoil_LD': round(ld_jf, 2),
            'SU2_Asm_Cl': round(cl_su2_asm, 3),
            'SU2_Asm_Cd': round(cd_su2_asm, 4),
            'SU2_Asm_LD': round(ld_su2_asm, 2),
            'SU2_Main_Cl': round(cl_su2_main, 3),
            'SU2_Main_Cd': round(cd_su2_main, 4),
            'SU2_Converged': conv,
            'Lift_Equalized_80kph_600mm_ANSYS_N': round(lift_std_ansys, 2),
            'Drag_Equalized_80kph_600mm_ANSYS_N': round(drag_std_ansys, 2),
            'Lift_Equalized_80kph_600mm_SU2_N': round(lift_std_su2, 2),
            'Drag_Equalized_80kph_600mm_SU2_N': round(drag_std_su2, 2),
            'Lift_Equalized_80kph_600mm_JF_N': round(lift_std_jf, 2),
            'Drag_Equalized_80kph_600mm_JF_N': round(drag_std_jf, 2),
            'Diff_Cl_Reported_vs_SU2_pct': round(diff_cl_pct, 1),
            'Diff_Cd_Reported_vs_SU2_pct': round(diff_cd_pct, 1)
        }
        results.append(rec)

    df = pd.DataFrame(results)
    csv_path = os.path.join(RUNS_DIR, "front_wings_ansys_vs_aeroauto.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nAll simulations complete. Results saved to {csv_path}")

    # Generate visual charts
    generate_charts(df)
    return df

def generate_charts(df):
    print("Generating verification and comparison charts...")
    plt.style.use('dark_background')

    # Chart 1: Polar Curve Comparison (Cl vs Cd)
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    ax.set_facecolor('#111827')
    fig.patch.set_facecolor('#0b0f19')

    colors = ['#f43f5e', '#06b6d4', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

    for i, row in df.iterrows():
        c = colors[i % len(colors)]
        # ANSYS Reported
        ax.scatter(row['ANSYS_Reported_Cd'], row['ANSYS_Reported_Cl'], color=c, marker='o', s=120, label=f"{row['ID']} (ANSYS Rep)")
        # ANSYS Corrected
        ax.scatter(row['ANSYS_Corrected_Cd'], row['ANSYS_Corrected_Cl'], color=c, marker='s', s=100, facecolors='none', edgecolors=c, lw=2)
        # SU2 Assembly
        ax.scatter(row['SU2_Asm_Cd'], row['SU2_Asm_Cl'], color=c, marker='^', s=120)
        # Arrow from reported to SU2
        ax.annotate('', xy=(row['SU2_Asm_Cd'], row['SU2_Asm_Cl']),
                    xytext=(row['ANSYS_Reported_Cd'], row['ANSYS_Reported_Cl']),
                    arrowprops=dict(arrowstyle="->", color=c, lw=1.2, alpha=0.7))

    ax.set_xlabel('Drag Coefficient Cd', fontsize=12, fontweight='bold', color='#e2e8f0')
    ax.set_ylabel('Lift Coefficient Cl (Downforce)', fontsize=12, fontweight='bold', color='#e2e8f0')
    ax.set_title('Front Wing Polars: ANSYS Reported vs SU2 2D RANS vs Corrected\nCircles: ANSYS Reported | Squares: ANSYS Area-Corrected | Triangles: SU2 RANS', fontsize=13, fontweight='bold', color='#38bdf8')
    ax.grid(True, linestyle='--', alpha=0.3, color='#475569')
    ax.legend(loc='lower right', fontsize=9, facecolor='#1e293b', edgecolor='#334155')

    polar_path = os.path.join(RUNS_DIR, "front_wings_polar_comparison.png")
    plt.tight_layout()
    plt.savefig(polar_path, dpi=150)
    plt.close()
    print(f"Polar chart saved to {polar_path}")

    # Chart 2: Equalized Downforce Comparison (at 80 km/h, Span = 600 mm)
    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    ax.set_facecolor('#111827')
    fig.patch.set_facecolor('#0b0f19')

    x = np.arange(len(df))
    width = 0.25

    rects1 = ax.bar(x - width, df['Lift_Equalized_80kph_600mm_ANSYS_N'], width, label='ANSYS Normalized (80 km/h, 600mm)', color='#0ea5e9')
    rects2 = ax.bar(x, df['Lift_Equalized_80kph_600mm_SU2_N'], width, label='SU2 RANS (80 km/h, 600mm)', color='#10b981')
    rects3 = ax.bar(x + width, df['Lift_Equalized_80kph_600mm_JF_N'], width, label='JavaFoil (80 km/h, 600mm)', color='#f59e0b')

    ax.set_ylabel('Normalized Downforce (N)', fontsize=12, fontweight='bold', color='#e2e8f0')
    ax.set_title('Normalized Downforce Comparison at V = 80 km/h & Span = 600 mm\nEqualizing Speed and Span to Reveal True Aerodynamic Merit', fontsize=13, fontweight='bold', color='#38bdf8')
    ax.set_xticks(x)
    ax.set_xticklabels(df['ID'], fontsize=11, fontweight='bold', color='#e2e8f0')
    ax.legend(facecolor='#1e293b', edgecolor='#334155', fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.3, axis='y', color='#475569')

    # Add values on top of bars
    for rects in [rects1, rects2, rects3]:
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.1f}N',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8, color='#f1f5f9', fontweight='bold')

    downforce_path = os.path.join(RUNS_DIR, "front_wings_downforce_comparison.png")
    plt.tight_layout()
    plt.savefig(downforce_path, dpi=150)
    plt.close()
    print(f"Downforce chart saved to {downforce_path}")

    # Chart 3: Aerodynamic Efficiency (L/D) Comparison
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    ax.set_facecolor('#111827')
    fig.patch.set_facecolor('#0b0f19')

    rects1 = ax.bar(x - width/2, df['ANSYS_Reported_LD'], width, label='ANSYS Excel L/D', color='#f43f5e')
    rects2 = ax.bar(x + width/2, df['SU2_Asm_LD'], width, label='SU2 RANS L/D', color='#06b6d4')

    ax.set_ylabel('Efficiency L/D (-)', fontsize=12, fontweight='bold', color='#e2e8f0')
    ax.set_title('Aerodynamic Efficiency (L/D) Comparison: ANSYS Fluent vs SU2 RANS\nHighlighting Flap Stall Under-Prediction in Unconverged 2D RANS', fontsize=13, fontweight='bold', color='#38bdf8')
    ax.set_xticks(x)
    ax.set_xticklabels(df['ID'], fontsize=11, fontweight='bold', color='#e2e8f0')
    ax.legend(facecolor='#1e293b', edgecolor='#334155', fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.3, axis='y', color='#475569')

    for rects in [rects1, rects2]:
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.2f}',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=8.5, color='#f1f5f9', fontweight='bold')

    ld_path = os.path.join(RUNS_DIR, "front_wings_ld_efficiency_comparison.png")
    plt.tight_layout()
    plt.savefig(ld_path, dpi=150)
    plt.close()
    print(f"L/D chart saved to {ld_path}")

if __name__ == '__main__':
    run_suite()
