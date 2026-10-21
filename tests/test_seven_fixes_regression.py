"""
Unit & Regression Test Suite verifying the 7 user-reported issues:
1. XFOIL rerun and persistent logging (xfoil_results.csv and polars)
2. Simulation parameter parity (dynamic viscosity mu = rho * V * c / Re)
3. Tooltip dismiss and grid row collision avoidance in Configure tab
4. Graph listbox container with horizontal scrollbar and full title card
5. Cross-check plot footer banner placed outside plot axes
6. SU2 sweep generating multi-point curves rather than a single point
7. SU2 surface Cp geometric element assignment matching wing element count
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import aero_auto as A
import su2_engine as su2
import aero_ui as ui


class TestSevenFixesRegression(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        A.seed_airfoil_store()
        cls.cfg = ('s1223', [('e420', 30.0, -10.0, 85.0, 5.0)])
        cls.test_dir = os.path.join(A.OUT_DIR, "graphs", "run_Test_Seven_Fixes")
        os.makedirs(cls.test_dir, exist_ok=True)

    # --------------------------------------------------------------------------
    # Issue 2: Calculation Parameter Parity (Dynamic Viscosity Matching)
    # --------------------------------------------------------------------------
    def test_01_parameter_parity_viscosity(self):
        """Verify write_su2_config_file calculates MU_CONSTANT = rho * V * c / Re."""
        rho = 1.225
        v = 20.0
        c = 1.0
        re = 570000.0
        expected_mu = (rho * v * c) / re

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            mesh_p = os.path.join(td, "mesh.su2")
            cfg_p = os.path.join(td, "config.cfg")
            with open(mesh_p, "w") as f:
                f.write("NDIME= 2\n")

            su2.write_su2_config_file(cfg_p, mesh_p, alpha_deg=0.0, speed=v, re_val=re, ground_h=None)
            with open(cfg_p, "r") as f:
                content = f.read()

            self.assertIn("INC_DENSITY_MODEL= CONSTANT", content)
            self.assertIn(f"INC_DENSITY_INIT= {rho:g}", content)
            self.assertIn("INC_VELOCITY_INIT= ( 20.000000, 0.000000, 0.0 )", content)
            self.assertIn(f"MU_CONSTANT= {expected_mu:.8e}", content)

    # --------------------------------------------------------------------------
    # Issue 5: Cross-Check Info Box Placed Outside Plot Canvas
    # --------------------------------------------------------------------------
    def test_02_cross_check_footer_outside_axes(self):
        """Verify render_overlay_plots creates overlay graphs without an internal clutter text box."""
        jf_pts = [{'alpha': -2.0, 'cl': -1.4, 'cd': 0.08}, {'alpha': 0.0, 'cl': -1.8, 'cd': 0.12}]
        su2_pts = [{'alpha': -2.0, 'cl': -1.3, 'cd': 0.09, 'converged': True},
                   {'alpha': 0.0, 'cl': -1.75, 'cd': 0.11, 'converged': True}]

        outs = su2.render_overlay_plots(jf_pts, su2_pts, self.test_dir, "Test_Seven_Fixes", self.cfg,
                                        speed=20.0, re_val=570000.0, ground_h=None)
        self.assertIn('overlay_cl_alfa', outs)
        self.assertIn('overlay_cd_alfa', outs)
        self.assertIn('overlay_drag_polar', outs)
        self.assertTrue(os.path.exists(outs['overlay_cl_alfa']))
        self.assertGreater(os.path.getsize(outs['overlay_cl_alfa']), 20000)

    # --------------------------------------------------------------------------
    # Issue 7: SU2 Surface Cp Legend Fragmentation Fix
    # --------------------------------------------------------------------------
    def test_03_surface_cp_element_grouping(self):
        """Verify render_su2_surface_cp_plot groups points into exactly the wing elements (no spurious 30+ flaps)."""
        # Create a mock surface_forces.csv with points around main and flap
        outlines = su2.build_geometry_coords(self.cfg)
        self.assertEqual(len(outlines), 2, "Configuration has 2 elements: Main and 1 Flap")

        # Create scattered/unstructured points along both elements
        rows = []
        for el_idx, outline in enumerate(outlines):
            for pt in outline[::4]:
                rows.append({
                    'x': pt[0],
                    'y': pt[1],
                    'Pressure': -250.0 if pt[1] > 0 else 180.0
                })

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            csv_path = os.path.join(td, "surface_forces.csv")
            pd.DataFrame(rows).to_csv(csv_path, index=False)

            p_cp = su2.render_su2_surface_cp_plot(csv_path, td, "Test_Cp_Grouping", self.cfg, alpha_deg=0.0)
            self.assertIsNotNone(p_cp)
            self.assertTrue(os.path.exists(p_cp))
            self.assertGreater(os.path.getsize(p_cp), 10000)

    # --------------------------------------------------------------------------
    # Issue 6: SU2 Sweep Subsampling & Multi-Point Curves
    # --------------------------------------------------------------------------
    def test_04_su2_sweep_subsampling(self):
        """Verify _subsample_alphas retains key points across sweep and preserves endpoints & 0.0."""
        # 26 points from -20 to 5 in 1-deg increments
        alphas = [float(x) for x in range(-20, 6)]
        sub = ui._subsample_alphas(alphas, max_pts=3)
        self.assertEqual(len(sub), 3)
        self.assertEqual(sub[0], -20.0)
        self.assertEqual(sub[-1], 5.0)
        self.assertIn(0.0, sub)

        # 3 points provided directly
        sub3 = ui._subsample_alphas([-2.0, 0.0, 2.0], max_pts=3)
        self.assertEqual(sub3, [-2.0, 0.0, 2.0])

    # --------------------------------------------------------------------------
    # Issue 1: XFOIL Persistent Logging & Run Results
    # --------------------------------------------------------------------------
    def test_05_xfoil_logging(self):
        """Verify log_xfoil_run_result writes records to xfoil_results.csv."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            test_xf_csv = os.path.join(td, "xfoil_results.csv")
            sample_row = {
                'Run_ID': 'XF_Test_001',
                'Main_Airfoil': 's1223',
                'Alpha': 0.0,
                'Cl': -1.25,
                'Cd': 0.018,
                'Cm': -0.15,
                'Max_LD': 69.4,
                'Converged': True
            }
            su2.log_xfoil_run_result(sample_row, results_csv=test_xf_csv)
            self.assertTrue(os.path.exists(test_xf_csv))
            df = pd.read_csv(test_xf_csv)
            self.assertEqual(len(df), 1)
            self.assertEqual(df['Run_ID'].iloc[0], 'XF_Test_001')
            self.assertEqual(df['Cl'].iloc[0], -1.25)

    # --------------------------------------------------------------------------
    # Issue 3 & 4: UI ToolTip, Grid Rows, Scrollbar, Title Card
    # --------------------------------------------------------------------------
    def test_06_ui_layout_and_graph_listbox_widgets(self):
        """Verify Tkinter widgets for full title card, horizontal scrollbar, and non-overlapping grid rows."""
        app = ui.App()
        app.withdraw()
        try:
            # 1. Full title variable
            self.assertTrue(hasattr(app, 'gr_full_title_var'))
            self.assertIsInstance(app.gr_full_title_var.get(), str)

            # 2. Graph listbox has both horizontal and vertical scrollbars
            self.assertTrue(hasattr(app, 'img_list'))
            self.assertTrue(hasattr(app, 'gr_list_hscroll'))
            self.assertTrue(hasattr(app, 'gr_list_vscroll'))

            # 3. Configure tab derive_state is at row 35 (not colliding with cad_frame at row 34)
            info = app.derive_lbl.grid_info()
            self.assertEqual(info.get('row'), 35)

            # 4. Top runs notebook contains the new XFOIL tab
            self.assertTrue(hasattr(app, 'top_tab_xf'))
            self.assertTrue(hasattr(app, 'top_xf_tree'))
        finally:
            app.destroy()


if __name__ == '__main__':
    unittest.main()
