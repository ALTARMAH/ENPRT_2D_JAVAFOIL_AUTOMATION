import sys, os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

sys.path.append('/usr/lib/freecad/lib')
import FreeCAD as App
import Part, Import

sys.path.append('/home/user/Applications/aero_auto')
from build_variant_a2_zero_interference import chassis_shape, standoffs_comp, body_solid_comp, fw_shape, rw_shape

def shape_to_facets(shape, tol=2.0):
    mesh = shape.tessellate(tol)
    verts, facets = mesh
    verts = np.array(verts, dtype=np.float32)
    return [verts[list(f)] for f in facets]

print("Tessellating components for rendering...")
facets_ch = shape_to_facets(chassis_shape, tol=4.0)
facets_so = shape_to_facets(standoffs_comp, tol=1.5)
facets_bd = shape_to_facets(body_solid_comp, tol=2.0)
facets_fw = shape_to_facets(fw_shape, tol=3.0)
facets_rw = shape_to_facets(rw_shape, tol=3.0)

fig = plt.figure(figsize=(20, 15), facecolor='#0B0F19')

views = [
    (221, "Isometric View (Over-The-Chassis Fairing & Realistic Wings)", 25, -55),
    (222, "Top Plan View (Z-Axis Down, Aerodynamic Streamlining)", 90, -90),
    (223, "Side Elevation (Profile with Standoff Gap & Ground Clearance)", 0, -90),
    (224, "Front Elevation (Standoff Mounts & Multi-Element Wings)", 0, 0)
]

for pos, title, elev, azim in views:
    ax = fig.add_subplot(pos, projection='3d', facecolor='#0B0F19')
    
    # Chassis Spaceframe (Metallic Steel Grey)
    poly_ch = Poly3DCollection(facets_ch, facecolors='#64748B', edgecolors='#334155', linewidths=0.2, alpha=0.35)
    ax.add_collection3d(poly_ch)
    
    # CNC Standoff Bobbins (Bright Cyan/Gold Accents)
    poly_so = Poly3DCollection(facets_so, facecolors='#F59E0B', edgecolors='#B45309', linewidths=0.4, alpha=0.95)
    ax.add_collection3d(poly_so)
    
    # Bodywork Faceted Panels (Race Red Carbon Gloss)
    poly_bd = Poly3DCollection(facets_bd, facecolors='#EF4444', edgecolors='#991B1B', linewidths=0.4, alpha=0.85)
    ax.add_collection3d(poly_bd)
    
    # Front Wing Multi-Element (Aero Cyan)
    poly_fw = Poly3DCollection(facets_fw, facecolors='#06B6D4', edgecolors='#0891B2', linewidths=0.3, alpha=0.9)
    ax.add_collection3d(poly_fw)
    
    # Rear Wing Multi-Element & DRS (Aero Indigo)
    poly_rw = Poly3DCollection(facets_rw, facecolors='#8B5CF6', edgecolors='#6D28D9', linewidths=0.3, alpha=0.9)
    ax.add_collection3d(poly_rw)
    
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlim([-750, 750])
    ax.set_ylim([-1750, 1450])
    ax.set_zlim([0, 1350])
    
    ax.set_title(title, color='#F8FAFC', fontsize=12, fontweight='bold', pad=12)
    ax.axis('off')

plt.suptitle("ENPRT FSAE FSUK 2027: VARIANT A2 OVER-CHASSIS ZERO-INTERFERENCE ASSEMBLY\n46 Faceted Panels (Red) | 34 CNC Standoffs (Amber) | Spaceframe (Grey) | Multi-Element Wings (Cyan/Purple)",
             color='#38BDF8', fontsize=15, fontweight='bold', y=0.97)

plt.tight_layout(rect=[0.02, 0.02, 0.98, 0.94])

out_img1 = "/home/user/aero_body/cad/BODYWORK_VARIANTS/02_VARIANT_A2_TRIANGULAR_OVER_CHASSIS/variant_a2_over_chassis_full_views.png"
out_img2 = "/home/user/.gemini/antigravity-cli/brain/b1fb5f26-5ea7-4d9a-bbe1-02ad8ed045c5/variant_a2_over_chassis_full_views.png"
out_img3 = "/home/user/aero_body/cad/bodywork_assemblies/FSAE_Full_Vehicle_Assembly_Variant_A2_Views.png"

plt.savefig(out_img1, dpi=180, facecolor='#0B0F19', bbox_inches='tight')
plt.savefig(out_img2, dpi=180, facecolor='#0B0F19', bbox_inches='tight')
plt.savefig(out_img3, dpi=180, facecolor='#0B0F19', bbox_inches='tight')
plt.close()
print("Rendered high-resolution orthographic views successfully!")
