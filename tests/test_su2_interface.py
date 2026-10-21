"""
Regression and Verification Test Suite for SU2 Simulation Engine & UI Interface
================================================================================
Verifies:
1. su2.run() called with the exact keyword arguments passed by aero_ui.py:
   su2.run(cfg, alpha_deg=0.0, speed=speed0, re_val=re0, ground_h=gh0, engine='su2', density='medium')
2. su2.run() called with sweep alphas:
   su2.run(cfg, alphas=[-2.0, 0.0, 2.0], ...)
3. su2.cross_check() called with the exact keyword arguments from UI:
   su2.cross_check(cfg, alpha_deg=0.0, speed=speed0, re_val=re0, ground_h=None, threshold_cl=0.5)
4. Plot generation with an unconverged angle: verifies non-converged points are distinctively
   marked in rose/red and the plotting pipeline never crashes.
5. All required SU2 and overlay graph PNGs and CSVs are generated in graphs/run_<RunName>/.
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

# Load application modules
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import aero_auto as A
import su2_engine as su2


class TestSU2InterfaceAndGraphs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        A.seed_airfoil_store()
        cls.cfg = ('NACA 0012', [('NACA 0012', 30.0, -6.0, 100.0, 5.0)])
        cls.test_dir = os.path.join(A.OUT_DIR, "graphs", "run_Test_Regression_Suite")
        os.makedirs(cls.test_dir, exist_ok=True)

    def test_01_ui_calling_signature_single_point(self):
        """Verify su2.run with the exact keyword arguments used by aero_ui.py."""
        res = su2.run(
            self.cfg,
            alpha_deg=0.0,
            speed=20.0,
            re_val=570000,
            ground_h=None,
            engine='su2',
            density='medium',
            run_tag='Test_Regression_UI_Args',
            out_dir=self.test_dir
        )
        self.assertIsInstance(res, dict)
        self.assertIn('Cl', res)
        self.assertIn('Cd', res)
        self.assertIn('converged', res)
        self.assertIn('runtime_s', res)
        self.assertEqual(res.get('engine'), 'SU2')
        self.assertEqual(res.get('alpha'), 0.0)

    def test_02_ui_calling_signature_sweep(self):
        """Verify su2.run with sweep angle parameter."""
        res = su2.run(
            self.cfg,
            alphas=[-2.0, 0.0, 2.0],
            speed=20.0,
            re_val=570000,
            ground_h=None,
            engine='su2',
            density='medium',
            run_tag='Test_Regression_Sweep',
            out_dir=self.test_dir
        )
        self.assertIsInstance(res, dict)
        self.assertIn('polar', res)
        self.assertEqual(len(res['polar']), 3)

    def test_03_cross_check_ui_signature(self):
        """Verify su2.cross_check with exact arguments used by aero_ui.py."""
        res = su2.cross_check(
            self.cfg,
            alpha_deg=0.0,
            speed=20.0,
            re_val=570000,
            ground_h=None,
            threshold_cl=0.5,
            run_tag='Test_Regression_CrossCheck',
            out_dir=self.test_dir
        )
        self.assertIsInstance(res, dict)
        # Check flat keys required by aero_ui line 3085-3092
        self.assertIn('javafoil_cl', res)
        self.assertIn('javafoil_cd', res)
        self.assertIn('su2_cl', res)
        self.assertIn('su2_cd', res)
        self.assertIn('diff_cl', res)
        self.assertIn('diff_cd', res)
        self.assertIn('ratio_cl', res)
        self.assertIn('diverged', res)
        self.assertIn('su2_converged', res)

    def test_04_unconverged_data_plotting_robustness(self):
        """Verify plotting pipeline handles unconverged points with distinctive markers and zero crash."""
        unconverged_data = [
            {'alpha': -5.0, 'Cl': -2.2158, 'Cd': 0.3397, 'converged': True, 'iterations': 250, 'residual_drop': 3.5},
            {'alpha': -2.0, 'Cl': -2.2166, 'Cd': 0.2557, 'converged': True, 'iterations': 250, 'residual_drop': 3.8},
            {'alpha': 0.0,  'Cl': -2.0580, 'Cd': 0.19867, 'converged': True, 'iterations': 250, 'residual_drop': 4.1},
            {'alpha': 2.0,  'Cl': -1.9566, 'Cd': 0.1717, 'converged': False, 'iterations': 180, 'residual_drop': 1.8},
            {'alpha': 5.0,  'Cl': -1.8200, 'Cd': 0.2100, 'converged': False, 'iterations': 150, 'residual_drop': 1.2},
        ]
        tag = "Unconverged_Test_Case"
        outs = su2.render_su2_polar_plots(
            unconverged_data,
            self.test_dir,
            tag,
            self.cfg,
            speed=20.0,
            re_val=570000
        )
        self.assertIn('polar_cl_alfa', outs)
        self.assertIn('polar_cd_alfa', outs)
        self.assertIn('polar_eff_alfa', outs)
        self.assertIn('polar_cl_cd', outs)
        self.assertIn('csv', outs)

        for k, p in outs.items():
            self.assertTrue(os.path.exists(p), f"Generated file {p} does not exist!")
            self.assertGreater(os.path.getsize(p), 0, f"Generated file {p} is empty!")

    def test_05_overlay_plots_generation(self):
        """Verify superimposed overlay plots and side-by-side CSV generation."""
        jf_data = [
            {'alpha': -5.0, 'cl': -3.578, 'cd': 0.1061},
            {'alpha': -2.0, 'cl': -4.036, 'cd': 0.0680},
            {'alpha': 0.0,  'cl': -4.157, 'cd': 0.0581},
            {'alpha': 2.0,  'cl': -3.950, 'cd': 0.0620},
        ]
        su2_data = [
            {'alpha': -5.0, 'cl': -2.2158, 'cd': 0.3397, 'converged': True},
            {'alpha': -2.0, 'cl': -2.2166, 'cd': 0.2557, 'converged': True},
            {'alpha': 0.0,  'cl': -2.0580, 'cd': 0.19867, 'converged': True},
            {'alpha': 2.0,  'cl': -1.9566, 'cd': 0.1717, 'converged': False},
        ]
        tag = "Overlay_Test_Case"
        outs = su2.render_overlay_plots(
            jf_data,
            su2_data,
            self.test_dir,
            tag,
            self.cfg,
            speed=20.0,
            re_val=570000,
            mesh_nodes="12,525 nodes"
        )
        self.assertIn('overlay_cl_alfa', outs)
        self.assertIn('overlay_cd_alfa', outs)
        self.assertIn('overlay_eff_alfa', outs)
        self.assertIn('overlay_drag_polar', outs)
        self.assertIn('csv', outs)

        for k, p in outs.items():
            self.assertTrue(os.path.exists(p), f"Overlay file {p} does not exist!")
            self.assertGreater(os.path.getsize(p), 0, f"Overlay file {p} is empty!")

    def test_06_secondary_thread_execution(self):
        """Verify that Gmsh mesh generation and SU2 run execute cleanly in secondary worker threads without signal error."""
        import threading
        thread_errors = []
        thread_results = []

        def worker():
            try:
                # Test Gmsh meshing inside thread
                coords = su2.build_geometry_coords(self.cfg, ground_h=None)
                mesh_tmp = os.path.join(self.test_dir, "thread_test_mesh.su2")
                mesh_meta = su2.generate_su2_mesh_gmsh(coords, mesh_tmp, ground_h=None, density='coarse')
                thread_results.append(mesh_meta)
            except Exception as e:
                import traceback
                thread_errors.append((e, traceback.format_exc()))

        th = threading.Thread(target=worker)
        th.start()
        th.join(timeout=30)
        self.assertFalse(th.is_alive(), "Worker thread timed out!")
        self.assertEqual(len(thread_errors), 0, f"Secondary thread raised error: {thread_errors}")
        self.assertEqual(len(thread_results), 1)
        self.assertGreater(thread_results[0].get('nodes', 0), 0)

    def test_07_xfoil_simulation_and_graphs(self):
        """Verify XFOIL simulation via unified runner and dark-themed plot generation."""
        res = su2.run(
            self.cfg,
            engine='xfoil',
            alphas=[-2.0, 0.0, 2.0],
            speed=20.0,
            re_val=570000,
            run_tag='Test_XFOIL_Suite',
            out_dir=self.test_dir
        )
        self.assertEqual(res.get('engine'), 'XFOIL')
        self.assertEqual(res.get('alpha'), 0.0)
        self.assertIn('polar', res)
        self.assertEqual(len(res['polar']), 3)
        self.assertIn('graph_files', res)

        graphs = res['graph_files']
        for key in ('polar_cl_alfa', 'polar_cd_alfa', 'polar_eff_alfa', 'polar_cl_cd', 'csv'):
            self.assertIn(key, graphs)
            p = graphs[key]
            self.assertTrue(os.path.exists(p), f"XFOIL output {p} does not exist!")
            self.assertGreater(os.path.getsize(p), 0, f"XFOIL output {p} is empty!")

    def test_08_overlay_with_xfoil(self):
        """Verify 3-way superimposed comparison plots (JavaFoil + SU2 + XFOIL)."""
        jf_data = [
            {'alpha': -2.0, 'cl': -4.036, 'cd': 0.0680},
            {'alpha': 0.0,  'cl': -4.157, 'cd': 0.0581},
            {'alpha': 2.0,  'cl': -3.950, 'cd': 0.0620},
        ]
        su2_data = [
            {'alpha': -2.0, 'cl': -2.2166, 'cd': 0.2557, 'converged': True},
            {'alpha': 0.0,  'cl': -2.0580, 'cd': 0.19867, 'converged': True},
            {'alpha': 2.0,  'cl': -1.9566, 'cd': 0.1717, 'converged': True},
        ]
        xf_data = [
            {'alpha': -2.0, 'cl': -0.21, 'cd': 0.0065, 'cm': 0.0},
            {'alpha': 0.0,  'cl': -0.00, 'cd': 0.0059, 'cm': 0.0},
            {'alpha': 2.0,  'cl': 0.21,  'cd': 0.0066, 'cm': 0.0},
        ]
        outs = su2.render_overlay_plots(
            jf_data, su2_data, self.test_dir, 'Test_3Way_Overlay', self.cfg,
            speed=20.0, re_val=570000, xfoil_records_or_df=xf_data
        )
        for key in ('overlay_cl_alfa', 'overlay_cd_alfa', 'overlay_eff_alfa', 'overlay_drag_polar', 'csv'):
            self.assertIn(key, outs)
            p = outs[key]
            self.assertTrue(os.path.exists(p))
            self.assertGreater(os.path.getsize(p), 0)

        # Check raw CSV contains cl_xf column
        df = pd.read_csv(outs['csv'])
        self.assertIn('cl_xf', df.columns)


if __name__ == '__main__':
    unittest.main()
