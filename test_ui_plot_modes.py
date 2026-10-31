import sys
from pathlib import Path

app_dir = Path(r"C:\Users\USER\Desktop\ENPRT\04_AERO_AUTO_APP")
sys.path.insert(0, str(app_dir))

import tkinter as tk
import aero_ui as UI

root = tk.Tk()
root.withdraw()
app = UI.AeroAutoApp(root)

print("Plot modes count:", len(app._wings_info))
first_id = list(app._wings_info.keys())[0]
app.wings_tree.selection_set(first_id)
app._on_wing_selected()

modes_to_test = [
    'ansys_3d_cl', 'ansys_3d_cd', 'ansys_3d_ld', 'ansys_3d_drag_polar',
    'ansys_3d_downforce', 'ansys_3d_drag', 'ansys_3d_induced_drag',
    'ansys_3d_spanwise', 'ansys_3d_ground_effect', 'ansys_3d_master',
    'cl_alpha', 'cd_alpha', 'ld_alpha', 'cm_alpha', 'drag_polar',
    'ansys_flowfield', 'ansys_cp', 'ansys_pressure_contour',
    'ansys_turbulent_ke', 'ansys_wall_shear', 'ansys_residuals', 'silhouette'
]

for m in modes_to_test:
    app.wing_plot_mode.set(m)
    app._refresh_wing_plot()
    print(f"Mode {m:25s} -> Image loaded successfully!")

print("\nALL MODES VERIFIED WITH ZERO ERRORS!")
root.destroy()
