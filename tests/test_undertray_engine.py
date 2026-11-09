"""
test_undertray_engine.py - Automated Unit Tests for ENPRT Chassis Underbody & Diffuser Optimization Engine.

Tests:
1. Aerodynamic physics sanity and Navier-Stokes ground-effect bounds
2. Formula Student Scrutineering Rule Verification (FSG / FSUK)
3. Automated Optimization Sweep and Constraint Enforcement
4. Dynamic Aero Map Generation and Ground-Height Sensitivity
5. DXF CAD and ANSYS Fluent Journal Export Pipelines
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import undertray_engine as UT


class TestUndertrayAerodynamicsEngine(unittest.TestCase):
    def setUp(self):
        self.engine = UT.UndertrayAerodynamicsEngine()

    def test_default_config_physics(self):
        """Verifies baseline undertray physics are realistic and bounded."""
        res = self.engine.compute_aerodynamics()
        self.assertGreater(res["downforce_N"], 100.0, "Downforce must be positive and substantial")
        self.assertLess(res["downforce_N"], 800.0, "Downforce must not exceed theoretical ground effect bounds")
        self.assertGreater(res["drag_N"], 20.0, "Drag must be positive")
        self.assertGreater(res["efficiency_L_D"], 1.5, "L/D must be realistic for multi-channel diffuser")
        self.assertGreater(res["throat_velocity_mps"], 15.0, "Venturi throat must accelerate flow above freestream")
        self.assertLess(res["min_cp"], 0.0, "Peak Cp must represent strong suction")
        self.assertGreaterEqual(res["cop_pct_wheelbase"], 35.0, "CoP must be well forward of rear axle")
        self.assertLessEqual(res["cop_pct_wheelbase"], 60.0, "CoP must be behind front axle")
        self.assertTrue(res["regulations"]["all_passed"], "Default configuration must pass all scrutineering checks")

    def test_scrutineering_rules(self):
        """Verifies scrutineering checks accurately detect legal vs illegal dimensions."""
        # 1. Ground clearance rule T2.2 (min >= 30mm)
        illegal_cfg = dict(UT.DEFAULT_UNDERTRAY_CONFIG)
        illegal_cfg["skirt_edge_height_mm"] = 22.0  # Violation
        eng = UT.UndertrayAerodynamicsEngine(illegal_cfg)
        chk = eng.verify_regulations()
        self.assertFalse(chk["all_passed"], "Should fail when ground clearance < 30mm")
        self.assertTrue(any("FAIL" in c["status"] for c in chk["checks"] if c["rule"] == "Rule T2.2.1"))

        # 2. Maximum floor width rule T8.2.2 (max <= 1250mm)
        illegal_cfg2 = dict(UT.DEFAULT_UNDERTRAY_CONFIG)
        illegal_cfg2["floor_max_width_mm"] = 1320.0  # Violation
        eng2 = UT.UndertrayAerodynamicsEngine(illegal_cfg2)
        chk2 = eng2.verify_regulations()
        self.assertFalse(chk2["all_passed"], "Should fail when width > 1250mm")

        # 3. Front splitter overhang rule T8.2.1 (max <= 700mm)
        illegal_cfg3 = dict(UT.DEFAULT_UNDERTRAY_CONFIG)
        illegal_cfg3["splitter_length_mm"] = 750.0  # Violation
        eng3 = UT.UndertrayAerodynamicsEngine(illegal_cfg3)
        chk3 = eng3.verify_regulations()
        self.assertFalse(chk3["all_passed"], "Should fail when front overhang > 700mm")

    def test_optimization_sweep(self):
        """Verifies 1-click optimizer sweeps space and yields compliant high-downforce setup."""
        opt = self.engine.optimize_undertray()
        self.assertGreaterEqual(opt["evaluations_completed"], 1000)
        self.assertGreater(opt["best_fitness_score"], 0.0)
        opt_res = opt["optimal_results"]
        self.assertTrue(opt_res["regulations"]["all_passed"], "Optimal config must strictly pass 100% of rules")
        self.assertGreater(opt_res["downforce_N"], 150.0)
        self.assertGreaterEqual(opt["optimal_config"]["throat_ground_height_mm"], 30.0)

    def test_aero_map_generation(self):
        """Verifies Aero Map generates complete sensitivity matrix with ground-effect decay."""
        amap = self.engine.compute_aero_map()
        self.assertEqual(len(amap["ride_heights_mm"]), 6)
        self.assertEqual(len(amap["rakes_deg"]), 6)
        mat = amap["downforce_matrix_N"]
        self.assertEqual(len(mat), 6)
        self.assertEqual(len(mat[0]), 6)

        # In ground effect, lower ride height should produce higher downforce
        for col_idx in range(len(amap["rakes_deg"])):
            fz_low = mat[0][col_idx]  # 25 mm
            fz_high = mat[-1][col_idx]  # 50 mm
            self.assertGreater(fz_low, fz_high, "Ground effect must decay with increasing ride height")

    def test_exports(self):
        """Verifies DXF and ANSYS Fluent journals export without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dxf_p = Path(tmpdir) / "undertray_test.dxf"
            res_dxf = self.engine.export_cad_dxf(str(dxf_p))
            self.assertTrue(os.path.isfile(res_dxf))
            self.assertGreater(os.path.getsize(res_dxf), 500)

            jou_p = Path(tmpdir) / "undertray_fluent.jou"
            res_jou = self.engine.export_ansys_fluent_journal(str(jou_p))
            self.assertTrue(os.path.isfile(res_jou))
            with open(res_jou, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("motion-bc-moving", content, "Fluent journal must set moving ground")
            self.assertIn("kw-sst", content, "Fluent journal must configure k-omega SST")


if __name__ == "__main__":
    unittest.main()
