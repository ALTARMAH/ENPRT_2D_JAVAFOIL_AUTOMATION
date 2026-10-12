"""Engine tests for aero_auto (CSV round-trip, legacy upgrade, atomic writes, guards).

Run with:  python3 -m unittest discover -s tests -v
These tests touch no JavaFoil, no GUI and no user data; everything happens in a temp folder.
"""
import csv
import glob
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aero_auto as A


LEGACY_HEADER = ["Run_ID", "Phase", "Elements", "Main",
                 "F1_Airfoil", "F1_Scale", "F1_Angle", "F1_X", "F1_Y",
                 "F2_Airfoil", "F2_Scale", "F2_Angle", "F2_X", "F2_Y",
                 "F3_Airfoil", "F3_Scale", "F3_Angle", "F3_X", "F3_Y",
                 "Cl_peak", "Cd_peak", "Stall_Angle", "Max_LD", "Cl_a0", "Cd_a0",
                 "Cm_a0", "Cl_am2", "Cl_ap2", "Tier", "Score", "Status"]


def legacy_row(run_id="Run_1", main="s1223", status="Valid"):
    """One row matching LEGACY_HEADER (blank flaps 2/3)."""
    return [run_id, "explore", "2", main,
            "e423", "35", "-12", "99", "6", "", "", "", "", "", "", "", "", "", "",
            "1.9", "0.09", "12", "21", "1.45", "0.08", "0.02", "1.2", "1.6", "1", "77.0", status]


def current_row(run_id="Run_2"):
    """One row matching the current FIELDS layout."""
    return [current_row_values(run_id)]


class EngineCsvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aero_test_")
        self._saved = (A.RESULTS_FILE[0], list(A.RESULTS), set(A.DONE),
                       A.RUN_COUNTER, A.START_COUNT[0], A.GROUND_H, A.CHORD_MM)

    def tearDown(self):
        A.RESULTS_FILE[0] = self._saved[0]
        A.RESULTS[:] = self._saved[1]
        A.DONE.clear(); A.DONE.update(self._saved[2])
        A.RUN_COUNTER = self._saved[3]
        A.START_COUNT[0] = self._saved[4]
        A.GROUND_H = self._saved[5]
        A.CHORD_MM = self._saved[6]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, name="results.csv"):
        return os.path.join(self.tmp, name)

    # ---- formatting / guards -------------------------------------------------
    def test_fmt_value_nan_blank(self):
        self.assertEqual(A.fmt_value("Cl_a0", float("nan")), "")
        self.assertEqual(A.fmt_value("Cl_a0", 1.23456), "1.2346")
        self.assertEqual(A.fmt_value("Duration_s", 3.14159), "3.1")

    def test_safe_float(self):
        self.assertIsNone(A._safe_float(""))
        self.assertIsNone(A._safe_float("abc"))
        self.assertIsNone(A._safe_float(float("nan")))
        self.assertIsNone(A._safe_float(None))
        self.assertEqual(A._safe_float("3.5"), 3.5)

    def test_row_to_cfg_skips_malformed(self):
        good = {"Main": "m", "F1_Airfoil": "a", "F1_Scale": "35", "F1_Angle": "-12",
                "F1_X": "99", "F1_Y": "6",
                "F2_Airfoil": "b", "F2_Scale": "", "F2_Angle": "1", "F2_X": "2", "F2_Y": "3"}
        cfg = A.row_to_cfg(good)
        self.assertEqual(cfg[0], "m")
        self.assertEqual(len(cfg[1]), 1)              # malformed F2 dropped, F1 kept
        self.assertEqual(cfg[1][0], ("a", 35.0, -12.0, 99.0, 6.0))

    def test_safe_cfg_key(self):
        self.assertIsNone(A.safe_cfg_key(("m", (("a", "x", 1, 2, 3),))))
        self.assertIsNotNone(A.safe_cfg_key(("m", (("a", 1, 2, 3, 4),))))
        self.assertEqual(A.safe_cfg_key(("m", ())), ("m", ()))

    # ---- atomic write --------------------------------------------------------
    def test_atomic_write_roundtrip(self):
        p = self.path()
        recs = [dict(zip(A.FIELDS, current_row_values("Run_1"))),
                dict(zip(A.FIELDS, current_row_values("Run_2")))]
        self.assertTrue(A.atomic_write_csv(p, recs))
        d = A.read_results_csv(p)
        self.assertEqual(list(d.columns), A.FIELDS)
        self.assertEqual(len(d), 2)
        self.assertEqual(list(d["Run_ID"]), ["Run_1", "Run_2"])
        self.assertFalse(glob.glob(os.path.join(self.tmp, ".tmp_results_*")))

    def test_atomic_write_failure_keeps_original(self):
        p = self.path()
        with open(p, "w") as f:
            f.write("Run_ID,Phase\nRun_old,explore\n")
        with open(p) as f:
            before = f.read()
        with mock.patch("aero_auto.os.replace", side_effect=OSError("boom")):
            self.assertFalse(A.atomic_write_csv(p, [{"Run_ID": "x"}]))
        with open(p) as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(glob.glob(os.path.join(self.tmp, ".tmp_results_*")))

    # ---- write_row / header --------------------------------------------------
    def test_write_row_creates_header(self):
        A.RESULTS_FILE[0] = self.path()
        A.write_row({"Phase": "explore", "Elements": 1, "Main": "m", "Status": "Valid",
                     "Cl_a0": 1.0, "Speed_ms": 27.74})
        self.assertEqual(A.results_header(A.RESULTS_FILE[0]), A.FIELDS)
        d = A.read_results_csv(A.RESULTS_FILE[0])
        self.assertEqual(len(d), 1)
        self.assertEqual(d.iloc[0]["Speed_ms"] if "Speed_ms" in d.columns else None, 27.74)

    # ---- read_results_csv: mixed vintages ------------------------------------
    def test_read_mixed_vintages_keeps_all_rows(self):
        p = self.path()
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(LEGACY_HEADER)
            w.writerow(legacy_row("Run_1"))
            w.writerow(legacy_row("Run_3"))
            w.writerow(current_row_values("Run_2"))      # wider, current layout
        d = A.read_results_csv(p)
        self.assertEqual(len(d), 3)                        # nothing dropped
        self.assertEqual(d["Cl_a0"].notna().sum(), 3)      # metrics aligned for all
        self.assertEqual(float(d[d["Run_ID"] == "Run_2"]["Cl_a0"].iloc[0]), 1.45)

    # ---- load_previous: legacy upgrade ---------------------------------------
    def test_load_previous_upgrades_and_keeps_rows(self):
        p = self.path()
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(LEGACY_HEADER)
            for i in range(5):
                w.writerow(legacy_row(f"Run_{i}", main=f"m{i}"))
        A.RESULTS_FILE[0] = p
        A.RESULTS.clear(); A.DONE.clear()
        A.GROUND_H = 300.0
        A.load_previous()
        self.assertEqual(len(A.RESULTS), 5)
        self.assertEqual(A.START_COUNT[0], 5)
        self.assertEqual(A.results_header(p), A.FIELDS)    # upgraded header
        self.assertEqual(len(glob.glob(os.path.join(self.tmp, "*_backup_*.csv"))), 1)
        d = A.read_results_csv(p)
        self.assertEqual(len(d), 5)                        # rows preserved
        self.assertTrue((d["Status"] == "Valid").all())


def current_row_values(run_id="Run_2"):
    """A full current-layout row (list ordered as A.FIELDS)."""
    r = {k: "" for k in A.FIELDS}
    r.update({"Run_ID": run_id, "Phase": "explore", "Elements": "2", "Main": "s1223",
              "F1_Airfoil": "e423", "F1_Scale": "35", "F1_Angle": "-12", "F1_X": "99", "F1_Y": "6",
              "Cl_peak": "1.9", "Cd_peak": "0.09", "Stall_Angle": "12", "Max_LD": "21",
              "Cl_a0": "1.45", "Cd_a0": "0.08", "Cm_a0": "0.02", "Cl_am2": "1.2", "Cl_ap2": "1.6",
              "Tier": "1", "Score": "77.0", "Status": "Valid", "Speed_ms": "27.74"})
    return [str(r[k]) for k in A.FIELDS]


class HeightAndLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aero_lib_")
        self._saved_h = A.GROUND_H

    def tearDown(self):
        A.GROUND_H = self._saved_h
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validate_height(self):
        self.assertIsNone(A.validate_height(None))
        self.assertEqual(A.validate_height("300"), 300.0)
        self.assertEqual(A.validate_height(2), 2.0)
        for bad in (0, -1, "", "x", float("nan")):
            with self.assertRaises(ValueError):
                A.validate_height(bad)

    def test_set_ground_h(self):
        self.assertEqual(A.set_ground_h(150), 150.0)
        self.assertEqual(A.GROUND_H, 150.0)
        with self.assertRaises(ValueError):
            A.set_ground_h(-3)

    def test_build_outlines_rejects_bad_height(self):
        with self.assertRaises(ValueError):
            A.build_outlines(("nonexistent-airfoil", ()), ground_h=0)
        with self.assertRaises(ValueError):
            A.build_outlines(("nonexistent-airfoil", ()), ground_h=-5)

    def test_run_dir_and_meta(self):
        base = self.tmp
        d = A.new_run_dir("single", "s1223", base=base)
        self.assertTrue(os.path.isdir(d))
        self.assertTrue(os.path.basename(d).endswith("_single_s1223"))
        A.write_run_meta(d, kind="single", n_runs=3)
        m = A.read_run_meta(d)
        self.assertEqual(m["n_runs"], 3)
        self.assertEqual(m["kind"], "single")
        runs = A.list_runs(base=base)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["n_runs"], 3)

    def test_import_legacy_results(self):
        base = self.tmp
        os.makedirs(os.path.join(base, "ground", "h100pct"))
        with open(os.path.join(base, "results.csv"), "w") as f:
            f.write("Run_ID,Phase\nRun_1,explore\n")
        with open(os.path.join(base, "ground", "h100pct", "results.csv"), "w") as f:
            f.write("Run_ID,Phase\nRun_2,explore\n")
        added = A.import_legacy_results(base=base)
        self.assertEqual(len(added), 2)
        self.assertEqual(len(A.list_runs(base=base)), 2)
        self.assertEqual(A.import_legacy_results(base=base), [])   # no duplicates


if __name__ == "__main__":
    unittest.main(verbosity=2)
