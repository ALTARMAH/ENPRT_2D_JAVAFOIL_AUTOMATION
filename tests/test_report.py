"""Helper tests for aero_report / aero_targets and the shared store/version additions.

Run with:  python3 -m unittest discover -s tests -v
No JavaFoil, no GUI; everything is in-memory or in a temp folder.
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

import aero_auto as A  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_version_present(self):
        self.assertIsInstance(A.VERSION, str)
        self.assertRegex(A.VERSION, r"^\d+\.\d+")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aero_store_")
        self._saved = dict(A.AIRFOILS)
        A.AIRFOILS.clear()

    def tearDown(self):
        A.AIRFOILS.clear()
        A.AIRFOILS.update(self._saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_store_missing_dir_is_safe(self):
        A.load_store(store=os.path.join(self.tmp, "does_not_exist"))
        self.assertEqual(A.AIRFOILS, {})

    def test_load_store_merges_profiles(self):
        with mock.patch("aero_auto.load_all", return_value={"custom": object()}):
            A.load_store(store=self.tmp)
        self.assertIn("custom", A.AIRFOILS)


class SelectTopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = __import__("aero_report")

    def _frame(self):
        return pd.DataFrame({
            "Run_ID": ["low", "high", "three"],
            "Elements": [2, 2, 3],
            "Score": [1.0, 9.0, 5.0],
            "Max_LD": [1.0, 2.0, 3.0],
            "Downforce_N": [1.0, 2.0, 3.0],
            "Drag_N": [1.0, 2.0, 3.0],
        })

    def test_select_top_ranks_within_groups(self):
        top = self.R.select_top(self._frame(), 2)
        ids = list(top["Run_ID"])
        self.assertIn("high", ids)          # the better 2-element row must win
        self.assertNotIn("low", ids)

    def test_select_top_covers_every_group(self):
        top = self.R.select_top(self._frame(), 2)
        self.assertEqual(set(top["Elements"]), {2, 3})


class TargetsEvaluateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.T = __import__("aero_targets")

    def test_evaluate_tolerates_missing_band_columns(self):
        d = pd.DataFrame({"Cl_a0": [1.0], "Cd_a0": [0.1]})
        out = self.T.evaluate(d, area=1.0, tol=0.8, tgt_cl_a=1.75, tgt_cd_a=0.45, tgt_ld=3.0)
        for col in ("CL_A_actual", "CD_A_actual", "Within_Tol", "Band_MinAbs", "Dev_Sum"):
            self.assertIn(col, out.columns)
        # Cl_am2 / Cl_ap2 are absent, so the band falls back to the Cl_a0 column only.
        self.assertAlmostEqual(float(out["Band_MinAbs"].iloc[0]), 1.0)
        self.assertTrue(bool(out["Within_Tol"].iloc[0]))

    def test_evaluate_computes_expected_numbers(self):
        d = pd.DataFrame({"Cl_a0": [1.75], "Cd_a0": [0.45],
                          "Cl_am2": [1.6], "Cl_ap2": [1.9]})
        out = self.T.evaluate(d, area=1.0, tol=0.1, tgt_cl_a=1.75, tgt_cd_a=0.45, tgt_ld=1.75 / 0.45)
        self.assertAlmostEqual(float(out["CL_A_actual"].iloc[0]), 1.75)
        self.assertAlmostEqual(float(out["CD_A_actual"].iloc[0]), 0.45)
        self.assertTrue(bool(out["CD_A_under_roof"].iloc[0]))

    def test_allowed_names_toggles(self):
        pool = {"s1223": 0, "e423": 0, "naca0012": 0}
        self.assertEqual(self.T.allowed_names(pool, True), {"s1223", "e423"})
        self.assertEqual(self.T.allowed_names(pool, False), set(pool))


class ForceColumnsTests(unittest.TestCase):
    """force_columns must use the run's PHYS (custom chord/speed/span), not a fixed default."""

    def test_uses_phys_when_set(self):
        saved = A.PHYS
        try:
            A.PHYS = dict(chord_mm=250.0, speed=30.0, span_mm=950.0)
            out = A.force_columns({"Cl_a0": -2.0, "Cd_a0": 0.05})
        finally:
            A.PHYS = saved
        q = 0.5 * A.RHO * 30.0 ** 2
        area = 0.250 * 0.950
        self.assertAlmostEqual(out["Downforce_N"], 2.0 * q * area, places=6)
        self.assertAlmostEqual(out["Drag_N"], 0.05 * q * area, places=6)

    def test_handles_missing_metrics(self):
        self.assertEqual(A.force_columns(None), {})
        self.assertEqual(A.force_columns({"Cl_a0": float("nan"), "Cd_a0": 0.05}), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
