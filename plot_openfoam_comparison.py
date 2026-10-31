#!/usr/bin/env python3
"""
plot_openfoam_comparison.py
===========================
Generates 4-way comparison charts:
  ANSYS Fluent vs. SU2 2D RANS vs. OpenFOAM-13 vs. JavaFoil
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = "/home/user/Applications/aero_auto"
OF_DIR = os.path.join(HERE, "runs", "openfoam_runs")
SU2_CSV = os.path.join(HERE, "runs", "front_wings_benchmark", "front_wings_ansys_vs_aeroauto.csv")
OF_CSV = os.path.join(OF_DIR, "openfoam_all_results.csv")
ARTIFACTS_DIR = "/home/user/.gemini/antigravity-cli/brain/b1fb5f26-5ea7-4d9a-bbe1-02ad8ed045c5"

df_su2 = pd.read_csv(SU2_CSV)
df_of = pd.read_csv(OF_CSV)

# Merge datasets
df = pd.merge(df_su2, df_of[['ID', 'OpenFOAM_Cl_asm', 'OpenFOAM_Cd_asm', 'OpenFOAM_LD',
                             'OpenFOAM_Raw_Lift_N', 'OpenFOAM_Raw_Drag_N',
                             'OpenFOAM_Lift_Equalized_80kph_600mm_N',
                             'OpenFOAM_Drag_Equalized_80kph_600mm_N']], on='ID')

print(df[['ID', 'ANSYS_Reported_Cl', 'SU2_Asm_Cl', 'OpenFOAM_Cl_asm', 'JavaFoil_Cl']])

plt.style.use('dark_background')

# Chart 1: 4-Way Downforce Comparison at 80 km/h, 600 mm span
fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
ax.set_facecolor('#111827')
fig.patch.set_facecolor('#0b0f19')

x = np.arange(len(df))
width = 0.20

r1 = ax.bar(x - 1.5*width, df['Lift_Equalized_80kph_600mm_ANSYS_N'], width, label='ANSYS Fluent (80km/h, 600mm)', color='#3b82f6')
r2 = ax.bar(x - 0.5*width, df['OpenFOAM_Lift_Equalized_80kph_600mm_N'], width, label='OpenFOAM-13 RANS (80km/h, 600mm)', color='#ec4899')
r3 = ax.bar(x + 0.5*width, df['Lift_Equalized_80kph_600mm_SU2_N'], width, label='SU2 RANS (80km/h, 600mm)', color='#10b981')
r4 = ax.bar(x + 1.5*width, df['Lift_Equalized_80kph_600mm_JF_N'], width, label='JavaFoil Panel Code (80km/h, 600mm)', color='#f59e0b')

ax.set_ylabel('Normalized Downforce (N)', fontsize=12, fontweight='bold', color='#e2e8f0')
ax.set_title('4-Way Front Wing Downforce Comparison (Normalized at V = 80 km/h & Span = 600 mm)\nANSYS Fluent vs. OpenFOAM-13 vs. SU2 2D RANS vs. JavaFoil', fontsize=13, fontweight='bold', color='#38bdf8')
ax.set_xticks(x)
ax.set_xticklabels(df['ID'], fontsize=11, fontweight='bold', color='#e2e8f0')
ax.legend(facecolor='#1e293b', edgecolor='#334155', fontsize=10)
ax.grid(True, linestyle='--', alpha=0.3, axis='y', color='#475569')

for rects in [r1, r2, r3, r4]:
    for rect in rects:
        h = rect.get_height()
        ax.annotate(f'{h:.1f}',
                    xy=(rect.get_x() + rect.get_width() / 2, h),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=7.5, color='#f1f5f9', fontweight='bold')

p1 = os.path.join(OF_DIR, "four_way_downforce_comparison.png")
plt.tight_layout()
plt.savefig(p1, dpi=160)
plt.savefig(os.path.join(ARTIFACTS_DIR, "four_way_downforce_comparison.png"), dpi=160)
plt.close()
print(f"Saved: {p1}")

# Chart 2: Polar Diagram Comparison (Cl vs Cd)
fig, ax = plt.subplots(figsize=(11, 6.5), dpi=160)
ax.set_facecolor('#111827')
fig.patch.set_facecolor('#0b0f19')

colors = ['#f43f5e', '#06b6d4', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

for i, row in df.iterrows():
    c = colors[i % len(colors)]
    # ANSYS Reported
    ax.scatter(row['ANSYS_Reported_Cd'], row['ANSYS_Reported_Cl'], color=c, marker='o', s=130, label=f"{row['ID']} (ANSYS)")
    # OpenFOAM
    ax.scatter(row['OpenFOAM_Cd_asm'], row['OpenFOAM_Cl_asm'], color=c, marker='D', s=110)
    # SU2 Assembly
    ax.scatter(row['SU2_Asm_Cd'], row['SU2_Asm_Cl'], color=c, marker='^', s=110)

ax.set_xlabel('Drag Coefficient Cd', fontsize=12, fontweight='bold', color='#e2e8f0')
ax.set_ylabel('Lift Coefficient Cl (Downforce)', fontsize=12, fontweight='bold', color='#e2e8f0')
ax.set_title('Polar Comparison: ANSYS Fluent (Circles) vs. OpenFOAM-13 (Diamonds) vs. SU2 RANS (Triangles)', fontsize=13, fontweight='bold', color='#38bdf8')
ax.grid(True, linestyle='--', alpha=0.3, color='#475569')
ax.legend(loc='lower right', fontsize=9, facecolor='#1e293b', edgecolor='#334155')

p2 = os.path.join(OF_DIR, "four_way_polar_comparison.png")
plt.tight_layout()
plt.savefig(p2, dpi=160)
plt.savefig(os.path.join(ARTIFACTS_DIR, "four_way_polar_comparison.png"), dpi=160)
plt.close()
print(f"Saved: {p2}")

# Chart 3: Aerodynamic Efficiency (L/D) Comparison
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=160)
ax.set_facecolor('#111827')
fig.patch.set_facecolor('#0b0f19')

r1 = ax.bar(x - width, df['ANSYS_Reported_LD'], width, label='ANSYS Fluent L/D', color='#3b82f6')
r2 = ax.bar(x, df['OpenFOAM_LD'], width, label='OpenFOAM-13 L/D', color='#ec4899')
r3 = ax.bar(x + width, df['SU2_Asm_LD'], width, label='SU2 RANS L/D', color='#10b981')

ax.set_ylabel('Efficiency L/D (-)', fontsize=12, fontweight='bold', color='#e2e8f0')
ax.set_title('Aerodynamic Efficiency (L/D): ANSYS Fluent vs. OpenFOAM-13 vs. SU2 RANS', fontsize=13, fontweight='bold', color='#38bdf8')
ax.set_xticks(x)
ax.set_xticklabels(df['ID'], fontsize=11, fontweight='bold', color='#e2e8f0')
ax.legend(facecolor='#1e293b', edgecolor='#334155', fontsize=10)
ax.grid(True, linestyle='--', alpha=0.3, axis='y', color='#475569')

for rects in [r1, r2, r3]:
    for rect in rects:
        h = rect.get_height()
        ax.annotate(f'{h:.1f}',
                    xy=(rect.get_x() + rect.get_width() / 2, h),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=8, color='#f1f5f9', fontweight='bold')

p3 = os.path.join(OF_DIR, "four_way_ld_comparison.png")
plt.tight_layout()
plt.savefig(p3, dpi=160)
plt.savefig(os.path.join(ARTIFACTS_DIR, "four_way_ld_comparison.png"), dpi=160)
plt.close()
print(f"Saved: {p3}")
