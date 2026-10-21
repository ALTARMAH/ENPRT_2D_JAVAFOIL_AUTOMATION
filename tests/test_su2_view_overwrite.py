"""
Tests for SU2 graphs auto-generation on View SU2 Graphs click,
and verifying that generating graphs with the same name always overwrites.
"""

import unittest
import os
import sys
import time
import shutil
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import aero_auto as A
import su2_engine as su2
import aero_ui as ui


class TestSu2ViewAndOverwrite(unittest.TestCase):
    def setUp(self):
        self.app = ui.App()
        self.app.withdraw()
        self.app.res_file.set(os.path.join(A.OUT_DIR, "results.csv"))
        if 'al0' in self.app.vars: self.app.vars['al0'].set("0.0")
        if 'al1' in self.app.vars: self.app.vars['al1'].set("0.0")

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def _cleanup_run(self, rid):
        for base in (A.OUT_DIR, os.path.dirname(self.app.res_file.get())):
            gdir = os.path.join(base, "graphs")
            r_dir = os.path.join(gdir, f"run_{rid}")
            if os.path.isdir(r_dir):
                shutil.rmtree(r_dir, ignore_errors=True)
            for f in glob.glob(os.path.join(gdir, f"*{rid}*")):
                try:
                    if os.path.isdir(f):
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        os.remove(f)
                except Exception:
                    pass

    def test_top_view_graphs_auto_generates_when_missing(self):
        """When SU2 graphs are missing, clicking View SU2 Graphs must auto-generate them."""
        rid = "Test_Auto_Gen_Top"
        self._cleanup_run(rid)
        try:
            fake_run = {
                'id': rid,
                'name': f"{rid} Wing",
                'role': 'rear wing',
                'main': 's1223',
                'flaps': [('e420', 30.0, -10.0, 85.0, 5.0)],
                'chord': 250.0,
                'speed': 20.0,
                're': 570000.0,
                'ge': False,
                'gh_pct': None,
                'su2_cl': -1.8,
                'su2_cd': 0.15
            }
            self.app._top_runs_data = [fake_run]
            self.app.top_su2_tree.delete(*self.app.top_su2_tree.get_children())
            iid = f"su2_{rid}"
            self.app.top_su2_tree.insert('', 'end', iid=iid, values=(
                "1", rid, "RW", "2", "s1223", "-1.8", "0.15", "-1.8", "0.15", "12.0", "150.0", "Valid", "3.2", "15.0"
            ))
            self.app.top_su2_tree.selection_set(iid)
            self.app.vars['al0'].set('0.0')
            self.app.vars['al1'].set('2.0')
            self.app.vars['alst'].set('2.0')

            # Confirm no graphs exist
            gdir_main = os.path.join(A.OUT_DIR, "graphs")
            su2_pre = glob.glob(os.path.join(gdir_main, f"su2_*{rid}*.png"))
            self.assertEqual(len(su2_pre), 0)

            # Call _top_view_graphs(source='su2')
            self.app._top_view_graphs(source='su2')

            # Wait for worker thread to finish generating
            t0 = time.time()
            found = False
            while time.time() - t0 < 120:
                self.app._drain_ui()
                self.app.update()
                su2_pngs = glob.glob(os.path.join(gdir_main, f"su2_*{rid}*.png")) + \
                           glob.glob(os.path.join(gdir_main, f"run_{rid}", "su2_*.png"))
                if len(su2_pngs) >= 3:
                    found = True
                    break
                time.sleep(0.5)

            # Verify SU2 graphs were generated
            su2_pngs = glob.glob(os.path.join(gdir_main, f"su2_*{rid}*.png")) + \
                       glob.glob(os.path.join(gdir_main, f"run_{rid}", "su2_*.png"))
            self.assertTrue(found, f"Expected SU2 graphs to be generated for {rid}")
            self.assertGreaterEqual(len(su2_pngs), 3)
        finally:
            self._cleanup_run(rid)

    def test_always_overwrites_same_run_name(self):
        """Re-generating graphs with the same name must overwrite existing files, not return from cache."""
        rid = "Test_Over_Same_Name"
        self._cleanup_run(rid)
        try:
            cfg = ('s1223', [('e420', 30.0, -10.0, 85.0, 5.0)])
            gdir_main = os.path.join(A.OUT_DIR, "graphs")
            os.makedirs(gdir_main, exist_ok=True)
            run_dir = os.path.join(gdir_main, f"run_{rid}")
            os.makedirs(run_dir, exist_ok=True)
            dummy_file = os.path.join(run_dir, f"javafoil_polar_cl_cd_{rid}.png")
            with open(dummy_file, "w") as f:
                f.write("OLD_DUMMY_DATA_BEFORE_OVERWRITE")

            old_mtime = os.path.getmtime(dummy_file)
            time.sleep(1.1)

            # Fast sweep for test execution (2 points)
            self.app.vars['al0'].set("0.0")
            self.app.vars['al1'].set("2.0")
            self.app.vars['alst'].set("2.0")

            # Trigger graph generation with the exact same run name
            self.app.generate_configured_graphs(cfg, run_name=rid, switch=False)

            # Wait for worker thread
            t0 = time.time()
            overwritten = False
            while time.time() - t0 < 120:
                self.app._drain_ui()
                self.app.update()
                if os.path.exists(dummy_file):
                    try:
                        with open(dummy_file, "rb") as f:
                            header = f.read(8)
                            if header.startswith(b'\x89PNG'):
                                overwritten = True
                                break
                    except Exception:
                        pass
                time.sleep(0.5)

            # Verify it was overwritten with genuine PNG data
            self.assertTrue(os.path.exists(dummy_file))
            self.assertTrue(overwritten, "Old dummy file must be replaced with fresh PNG image")
            new_mtime = os.path.getmtime(dummy_file)
            self.assertGreater(new_mtime, old_mtime, "File should have been overwritten with newer timestamp")
        finally:
            self._cleanup_run(rid)


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSu2ViewAndOverwrite)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    os._exit(0 if result.wasSuccessful() else 1)
